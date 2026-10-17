"""Closed DOC04 registration and the existing transport's command boundaries."""
import ast
from contextlib import contextmanager, nullcontext
import copy
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator, FormatChecker
from cipher_aec.api.catalog import ROUTES, RPC
from cipher_aec.api.openapi import generate

ROOT = Path(__file__).parents[1]
SCOPE = {"company": "Cipher Synthetic Company", "scope_type": "Project", "project": "PROJ-0001"}
OPERATION = "11111111-1111-4111-8111-111111111111"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_function(path, name, namespace):
    tree = ast.parse(path.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@contextmanager
def transport_boundary():
    frappe = types.ModuleType("frappe")
    frappe.local = types.SimpleNamespace(request=types.SimpleNamespace(method="POST"), response={}, response_headers={})
    frappe.form_dict = {}
    frappe.db = types.SimpleNamespace(rollback=Mock())
    frappe.headers = {}
    frappe.get_request_header = lambda name: frappe.headers.get(name)
    frappe.whitelist = lambda **kw: lambda function: function
    frappe.log_error = Mock()
    frappe.QueryDeadlockError = type("Deadlock", (Exception,), {})
    frappe.QueryTimeoutError = type("Timeout", (Exception,), {})
    context = types.ModuleType("cipher_aec.governance.context")
    context.assert_synthetic_site = Mock()
    context.current_actor = Mock(return_value=types.SimpleNamespace(user="reader@cipher.example", person="PERSON-1"))
    backend = types.ModuleType("cipher_aec.semantic_index.api")
    backend.call = Mock(return_value={"status": "active"})
    package = types.ModuleType("cipher_aec.semantic_index")
    package.api = backend
    with patch.dict(sys.modules, {"frappe": frappe, "cipher_aec.governance.context": context,
                                 "cipher_aec.semantic_index": package, "cipher_aec.semantic_index.api": backend}):
        transport = load_file("cipher_aec.api._semantic_transport_test", ROOT / "api/transport.py")
        with patch.dict(sys.modules, {"cipher_aec.api.transport": transport}):
            wrapper = load_file("cipher_aec.api._semantic_wrapper_test", ROOT / "api/semantic.py")
            yield frappe, backend, transport, wrapper


class SemanticIntegrationTests(unittest.TestCase):
    def test_filtered_unknown_wire_fields_are_refused_before_backend_dispatch(self):
        cases = (("prepare", {"sources": [], "operation_id": OPERATION}),
                 ("cancel", {"operation_id": OPERATION}),
                 ("status", {"job_operation_id": OPERATION}),
                 ("query", {"question": "Authorized evidence?", "limit": 2}))
        for name, arguments in cases:
            with self.subTest(name=name), transport_boundary() as (frappe, backend, transport, wrapper):
                frappe.headers["Idempotency-Key"] = OPERATION
                method = getattr(wrapper, name)
                for extra in ({"unexpected": True}, {"cmd": "cipher_aec.api.semantic.prepare" if name != "prepare" else "cipher_aec.api.v1.create_task"},
                              *([{"operation_id": OPERATION}] if name == "status" else [])):
                    frappe.form_dict = {"scope": SCOPE, **arguments, **extra}
                    self.assertEqual(method(scope=SCOPE, **arguments)["error"]["code"], "semantic_invalid_input")
                    backend.call.assert_not_called()
                # An exact upstream cmd does not choose an arbitrary handler.
                frappe.form_dict = {"scope": SCOPE, **arguments, "cmd": "cipher_aec.api.semantic." + name}
                self.assertIn("data", method(scope=SCOPE, **arguments))
                backend.call.assert_called_once()

    def test_status_references_existing_job_without_a_command_key(self):
        with transport_boundary() as (frappe, backend, transport, wrapper):
            result = wrapper.status(scope=SCOPE, job_operation_id=OPERATION)
            self.assertEqual(result["data"], {"status": "active"})
            backend.call.assert_called_once_with("status", {"scope": SCOPE, "operation_id": OPERATION})
            self.assertEqual(frappe.headers, {})
            frappe.db.rollback.assert_not_called()

    def test_semantic_commands_keep_key_agreement_and_forged_actor_denial(self):
        for name, arguments in (("prepare", {"sources": []}), ("cancel", {})):
            with self.subTest(name=name), transport_boundary() as (frappe, backend, transport, wrapper):
                method = getattr(wrapper, name)
                self.assertEqual(method(scope=SCOPE, operation_id=OPERATION, **arguments)["error"]["code"], "idempotency_key_required")
                backend.call.assert_not_called()
                frappe.headers["Idempotency-Key"] = OPERATION
                self.assertEqual(method(scope=SCOPE, operation_id="22222222-2222-4222-8222-222222222222", **arguments)["error"]["code"], "operation_conflict")
                backend.call.assert_not_called()
                self.assertIn("data", method(scope=SCOPE, operation_id=OPERATION, **arguments))
                self.assertEqual(backend.call.call_args.args, (name, {"scope": SCOPE, "operation_id": OPERATION, **arguments}))
                backend.call.reset_mock()
                # The established transport may inject the key from the header.
                frappe.form_dict = {"scope": SCOPE, **arguments}
                self.assertIn("data", method(scope=SCOPE, **arguments))
                self.assertEqual(backend.call.call_args.args[1]["operation_id"], OPERATION)
                backend.call.reset_mock()
                frappe.form_dict = {"actor": "forged"}
                self.assertEqual(method(scope=SCOPE, operation_id=OPERATION, **arguments)["error"]["code"], "forged_authority")
                backend.call.assert_not_called()

    def test_existing_task_commands_still_require_idempotency_header(self):
        arguments = {
            "create_task": {"company": "C", "project": "P", "operation_id": OPERATION},
            "assign_task": {"company": "C", "project": "P", "task": "TASK-1", "assignee_person": "PERSON-1", "operation_id": OPERATION},
            "update_task_status": {"company": "C", "project": "P", "task": "TASK-1", "status": "Working", "operation_id": OPERATION},
        }
        for name, values in arguments.items():
            with self.subTest(name=name), transport_boundary() as (frappe, backend, transport, wrapper):
                service = Mock()
                function = source_function(ROOT / "api/v1.py", name,
                    {"endpoint": transport.endpoint, "service": service, "task_service": service})
                self.assertEqual(function(**values)["error"]["code"], "idempotency_key_required")
                self.assertEqual(service.mock_calls, [])

    def test_catalog_exports_only_four_closed_semantic_operations(self):
        artifact = generate()
        prefix = "cipher_aec.api.semantic."
        self.assertEqual({key for key in ROUTES if key.startswith(prefix)}, {prefix + n for n in ("prepare", "cancel", "status", "query")})
        self.assertNotIn("cipher_aec.semantic_index.api.call", RPC)
        for name, schema in {"prepare": "SemanticPrepareRequest", "cancel": "SemanticJobRequest", "status": "SemanticStatusRequest", "query": "SemanticQueryRequest"}.items():
            route = ROUTES[prefix + name]
            operation = artifact["paths"]["/api/method/" + prefix + name]["post"]
            self.assertEqual(operation["requestBody"]["content"]["application/json"]["schema"], artifact["components"]["schemas"][schema])
            headers = {p["name"] for p in operation["parameters"]}
            self.assertEqual("Idempotency-Key" in headers, name in ("prepare", "cancel"))
            self.assertEqual(route.command, name in ("prepare", "cancel"))
            if name=="cancel":
                self.assertIn("original rebuild operation UUID", operation["x-idempotency-scope"])
                self.assertIn("without creating a second rebuild receipt", operation["x-idempotency-scope"])

    def test_status_alias_and_scope_schema_reject_transport_command_spelling(self):
        schema = json.loads((ROOT / "api/schema.json").read_text())
        validator = Draft202012Validator({"$ref": "#/$defs/SemanticStatusRequest", "$defs": schema["$defs"]}, format_checker=FormatChecker())
        good = {"scope": SCOPE, "job_operation_id": OPERATION}
        validator.validate(good)
        company = copy.deepcopy(good); company["scope"].update(scope_type="Company", project=None)
        validator.validate(company)
        for bad in ({"scope": SCOPE, "operation_id": OPERATION},
                    {**good, "operation_id": OPERATION},
                    {**good, "job_operation_id": "DOC-0001"},
                    {**good, "scope": {**SCOPE, "project": None}},
                    {**company, "scope": {**company["scope"], "project": "P"}}):
            with self.subTest(bad=bad): self.assertTrue(list(validator.iter_errors(bad)))

    def test_default_fixture_grants_exclude_optional_semantic_management(self):
        constants = {}
        for node in ast.parse((ROOT / "governance/context.py").read_text()).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "frozenset":
                constants[node.targets[0].id] = frozenset(ast.literal_eval(node.value.args[0]))
        ability = "document.semantic.manage"
        self.assertIn(ability, constants["PROJECT_ABILITIES"])
        self.assertIn(ability, constants["COMPANY_ABILITIES"])
        granted = []
        db = types.SimpleNamespace(exists=lambda *a, **k: True,
            get_value=lambda kind, *a, **k: "PERSON-1" if kind == "Cipher Identity Binding" else "PROJ-1")
        namespace = {**constants, "frappe": types.SimpleNamespace(session=types.SimpleNamespace(user="Administrator"), db=db),
            "assert_synthetic_site": lambda: None, "trusted_write": nullcontext, "os": types.SimpleNamespace(environ={}),
            "_person": lambda name, title: name, "_user": lambda *a: None, "_binding": lambda *a: None,
            "_grant": lambda person, company, project, item: granted.append(item),
            "_grant_company": lambda person, company, item: granted.append(item)}
        source_function(ROOT / "install.py", "seed_synthetic", namespace)()
        self.assertNotIn(ability, granted)
        granted.clear()
        company_grants = source_function(ROOT / "install.py", "grant_synthetic_company_duties", namespace)
        company_grants("reader@cipher.example", "C")
        self.assertNotIn(ability, granted)
        granted.clear()
        company_grants("reader@cipher.example", "C", [ability])
        self.assertEqual(granted, [ability])

    def test_checkpoint_native_routes_are_denied_even_to_native_reader_roles(self):
        hooks = runpy.run_path(str(ROOT / "hooks.py"))
        self.assertEqual(hooks["permission_query_conditions"]["Cipher Semantic Corpus"], "cipher_aec.semantic_index.store.no_native_rows")
        self.assertEqual(hooks["has_permission"]["Cipher Semantic Corpus"], "cipher_aec.semantic_index.store.deny_native_access")
        metadata = json.loads((ROOT / "cipher_semantic_index/doctype/cipher_semantic_corpus/cipher_semantic_corpus.json").read_text())
        self.assertTrue(any(row.get("role") == "System Manager" and row.get("read") for row in metadata["permissions"]))
        self.assertFalse(any(row.get("export") for row in metadata["permissions"]))


if __name__ == "__main__": unittest.main()
