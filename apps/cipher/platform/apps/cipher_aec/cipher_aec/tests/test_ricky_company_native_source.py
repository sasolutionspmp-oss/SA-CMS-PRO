"""Host-only native fixture observation/restoration checks; no site or network."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import test_ricky_company_native as native
from .ricky_company_acceptance_support import SCHEMA, sha, typed_equal, write_private, manifest


class NativeFixtureSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "fixture.secret.json"
        self.value = {"company": "Exact Company", "users": {"author": {"user": "owner", "person": "exactperson"}},
            "duties": {"document.read": "exactduty"}, "stages": {}}
        self.row = SimpleNamespace(name="exactduty", company="Exact Company", person="exactperson",
            scope_type="Company", project=None, ability="document.read", active=1,
            valid_from=date(2026, 10, 1), valid_until=None, scope_key="exactscope")
        self.original = native._duty_state(self.value, "document.read", self.row)
        self.value["stages"]["original_duty_states"] = {"document.read": deepcopy(self.original)}

    def test_native_inventory_preserves_native_type_and_exact_representation(self):
        values = [None, True, 1, "1", Decimal("1"), Decimal("1.0"), 1.0, b"1",
            date(2026, 10, 1), "2026-10-01", datetime(2026, 10, 1), time(1, 2), timedelta(seconds=1)]
        encoded = [native._native_scalar(value) for value in values]
        self.assertEqual(len({sha(value) for value in encoded}), len(values))
        for value in encoded:
            self.assertTrue(typed_equal(value, json.loads(json.dumps(value))))
        for value in (float("nan"), float("inf"), Decimal("NaN"), object(), {"unqualified": 1}):
            with self.subTest(kind=type(value).__name__), self.assertRaises((TypeError, ValueError)):
                native._native_scalar(value)

    def test_actual_inventory_hash_path_detects_int_to_text_drift(self):
        row = {"name": "old", "value": 1}
        def sql(query, as_dict=False):
            return [] if "tabSingles" in query else [deepcopy(row)]
        fake = SimpleNamespace(get_installed_apps=lambda: [], db=SimpleNamespace(exists=lambda *args: True, sql=sql))
        with patch.dict("sys.modules", {"frappe": fake}), patch.object(native, "INVENTORY_TABLES", ("Company",)):
            before = native._inventory()
            row["value"] = "1"
            after = native._inventory()
        delta = native._old_row_changes(before, after)
        self.assertEqual(len(delta), 1)
        self.assertEqual(delta[0]["name"], "old")
        self.assertNotEqual(delta[0]["before"]["value"], delta[0]["after"]["value"])

    def test_exact_original_duty_is_fsynced_before_outage_and_not_replaced(self):
        fake = SimpleNamespace(get_doc=lambda *args: self.row)
        with patch.dict("sys.modules", {"frappe": fake}):
            original = native._capture_duty_outage(self.value, "document.read", "source-revocation", self.path)
            saved = json.loads(self.path.read_text())["stages"]["source-revocation"]
            self.assertTrue(typed_equal(saved["original_duty"], self.original))
            self.assertEqual(self.row.active, 1)
            self.assertTrue(typed_equal(original, self.original))
            with self.assertRaises(RuntimeError):
                native._capture_duty_outage(self.value, "document.read", "source-revocation", self.path)
            self.row.active = 0
            with self.assertRaises(AssertionError):
                native._capture_duty_outage(self.value, "document.read", "another-stage", self.path)

    def test_supported_restore_uses_captured_active_and_refuses_scope_or_validity_drift(self):
        calls = []
        self.row.save = lambda **kwargs: calls.append(("save", self.row.active, kwargs))
        fake = SimpleNamespace(get_doc=lambda *args: self.row, db=SimpleNamespace(commit=lambda: calls.append("commit")))
        module = SimpleNamespace(trusted_write=nullcontext)
        with patch.dict("sys.modules", {"frappe": fake, "cipher_aec.governance.context": module}):
            original_inactive = deepcopy(self.original)
            original_inactive["active"] = 0
            original_inactive["fields"]["active"] = native._native_scalar(0)
            native._duty(self.value, "document.read", original_inactive["active"], original_inactive)
            self.assertEqual(self.row.active, 0)
            self.assertEqual(calls, [("save", 0, {"ignore_permissions": True}), "commit"])
            for field, changed in (("project", "Foreign Project"), ("scope_type", "Project"),
                    ("valid_until", date(2026, 11, 1)), ("scope_key", "changed")):
                old = getattr(self.row, field)
                setattr(self.row, field, changed)
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    native._duty(self.value, "document.read", 1, self.original)
                setattr(self.row, field, old)
            self.assertEqual(len(calls), 2)

    def test_independent_readback_checks_exact_scope_active_and_cleans_connection(self):
        calls = []
        class InlineThread:
            def __init__(self, target, daemon): self.target = target
            def start(self): self.target()
            def join(self, seconds): pass
            def is_alive(self): return False
        def get_value(doctype, name, fields, as_dict):
            self.assertEqual(tuple(fields), native.DUTY_FIELDS)
            return self.row
        fake = SimpleNamespace(local=SimpleNamespace(site="exact.site"),
            init=lambda **kw: calls.append("init"), connect=lambda: calls.append("connect"),
            db=SimpleNamespace(get_value=get_value, rollback=lambda: calls.append("rollback")),
            destroy=lambda: calls.append("destroy"))
        with patch.dict("sys.modules", {"frappe": fake}), patch.object(native.threading, "Thread", InlineThread):
            native._independent_duty_readback(self.value, "document.read", self.original)
            self.assertEqual(calls, ["init", "connect", "rollback", "destroy"])
            for field, changed in (("active", 0), ("project", ""), ("scope_type", "Project"), ("valid_until", date(2027, 1, 1))):
                old = getattr(self.row, field)
                setattr(self.row, field, changed)
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    native._independent_duty_readback(self.value, "document.read", self.original)
                setattr(self.row, field, old)
                self.assertEqual(calls[-2:], ["rollback", "destroy"])

    def test_native_saved_run_request_comparison_is_type_sensitive(self):
        intent = {"run_id": "saved-http-run", "operation_id": "saved-http-operation", "payload": {"request": {"value": True}}}
        run = {"company": self.value["company"], "user": "owner", "person": "exactperson",
            "operation_id": intent["operation_id"], "request": {"value": 1}}
        fake_store = SimpleNamespace(CompanyStore=lambda **kwargs: SimpleNamespace(get=lambda *args: run))
        with patch.dict("sys.modules", {"cipher_aec.ricky.storage": fake_store}), patch.object(native, "saved_intent", return_value=intent):
            with self.assertRaises(AssertionError): native._run(self.value, "lookup")
            run["request"] = {"value": True}
            self.assertIs(native._run(self.value, "lookup"), run)

    def test_claim_race_saves_bounded_failure_diagnostics_and_cleanup_before_assertion(self):
        calls = []
        class InlineThread:
            def __init__(self, target, daemon): self.target = target
            def start(self): self.target()
            def join(self, seconds): pass
            def is_alive(self): return False
        class LockFailure(Exception): pass
        def claim(run): raise LockFailure(1205, "Explicit host lock failure " + "x" * 1000)
        fake = SimpleNamespace(local=SimpleNamespace(site="host.only"), init=lambda **kw: calls.append("init"),
            connect=lambda: calls.append("connect"), db=SimpleNamespace(rollback=lambda: calls.append("rollback")),
            destroy=lambda: calls.append("destroy"))
        service = SimpleNamespace(backend=SimpleNamespace(original_user=lambda authority: nullcontext()), claim=claim)
        value = deepcopy(self.value)
        with patch.dict("sys.modules", {"frappe": fake,
                "cipher_aec.ricky.company_service": SimpleNamespace(build_service=lambda **kw: service),
                "cipher_aec.ricky.company_contracts": SimpleNamespace(decode_run_authority=lambda run: object())}), \
                patch.object(native, "_fixture", return_value=value), \
                patch.object(native, "_run", return_value={"id": "host-only-run", "status": "queued"}), \
                patch.object(native.threading, "Thread", InlineThread), \
                patch.object(native.threading, "Barrier", return_value=SimpleNamespace(wait=lambda timeout: None)):
            with self.assertRaisesRegex(AssertionError, "did not complete cleanly"):
                native.run_company_claim_race(str(self.path))
            saved = json.loads(self.path.read_text())["stages"]["claim-race"]
            self.assertEqual(saved["status"], "observed_before_assertions")
            self.assertEqual(saved["thread_alive"], [False, False])
            self.assertEqual(len(saved["claims"]), 2)
            self.assertTrue(all(row["error_code"] == "1205" and row["error_type"] == "LockFailure"
                and len(row["error_message"]) == 512 for row in saved["claims"]))
            self.assertEqual(calls.count("destroy"), 2)
            with self.assertRaisesRegex(RuntimeError, "one-shot"):
                native.run_company_claim_race(str(self.path))


class PreinventoryContinuationSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        marker = "012345abcdef"
        self.path = self.work / "fixture.secret.json"
        self.value = {"schema": SCHEMA, "fixture_id": "ricky-company-" + marker, "site": "exact.synthetic.site",
            "created_at": "2026-10-16T03:00:00+00:00", "company": "Ricky Company " + marker,
            "users": {role: {"user": f"ricky.company.{role}.{marker}@cipher.example",
                "person": "b" * 10 if role == "outsider" else "a" * 10, "password": "original-" + role}
                for role in ("author", "alias", "outsider")},
            "native": {"role": "Ricky Company read " + marker,
                "uoms": ["Ricky metre " + marker, "Ricky centimetre " + marker], "customer": "Ricky customer " + marker,
                "setup_inputs": {"company_abbr": "RC" + marker[:6], "currency": "USD", "country": "United States",
                    "customer_group": "All Customer Groups", "territory": "All Territories", "uom_symbols": ["RC0" + marker, "RC1" + marker]}},
            "duties": {}, "inputs": {}, "intents": {}, "stages": {}, "preservation": {}, "journal_directory": str(self.work),
            "metadata_preservation": {}, "native_projection_observations": [], "shared_receipt_observations": []}
        write_private(self.path, self.value)
        self.original_raw = self.path.read_bytes()
        self.log = self.work / "failed-setup.secret.log"
        self.log.write_text('  File "test_ricky_company_native.py", line 178, in prepare_company_fixture\n'
            '    before = _inventory()\n  File "test_ricky_company_native.py", line 120, in _inventory\n'
            'RuntimeError: Missing required ordinary fixture metadata: Expense Claim\n')
        self.log.chmod(0o600)
        self.record = self.work / "failed-phase.secret.json"
        self.phase = {"schema": "cipher.company-ricky.native-phase.v1", "phase": "setup", "site": self.value["site"],
            "module": "test_ricky_company_native", "function": "prepare_company_fixture", "status": "failed",
            "main_changed": False, "exit_code": 1, "log_sha256": hashlib.sha256(self.log.read_bytes()).hexdigest()}
        write_private(self.record, self.phase)
        self.calls = []
        self.present = {("DocType", json.dumps("Company"))}
        def exists(doctype, selector):
            self.calls.append((doctype, deepcopy(selector)))
            return (doctype, json.dumps(selector, sort_keys=True)) in self.present
        self.fake = SimpleNamespace(get_installed_apps=lambda: ["frappe", "erpnext", "cipher_aec"],
            db=SimpleNamespace(exists=exists, sql=lambda *args, **kwargs: []))

    def continuation(self):
        with patch.dict("sys.modules", {"frappe": self.fake}), \
                patch.object(native, "_load_fixture", side_effect=lambda path: manifest(path)), \
                patch.object(native, "_setup_preconditions", create=True), \
                patch.object(native, "_complete_company_fixture_setup", create=True, return_value={"status": "host-shape-only"}) as setup, \
                patch.object(native, "uuid4", side_effect=AssertionError("Must retain original fixture IDs")), \
                patch.object(native.secrets, "token_hex", side_effect=AssertionError("Must retain original Persons")), \
                patch.object(native.secrets, "token_urlsafe", side_effect=AssertionError("Must retain original credentials")):
            result = native.continue_company_fixture_preinventory(self.path, self.record, self.log)
            return result, setup

    def test_optional_metadata_requires_absent_hrms_and_records_presence_transition(self):
        with patch.dict("sys.modules", {"frappe": self.fake}), patch.object(native, "INVENTORY_TABLES", ("Company", "Expense Claim")):
            before = native._inventory()
            self.assertEqual(before["Inventory metadata"]["Expense Claim"],
                {"present": False, "owner_app": "hrms", "owner_app_installed": False})
            self.present.add(("DocType", json.dumps("Expense Claim")))
            after = native._inventory()
            changes = native._old_row_changes(before, after)
            self.assertEqual([row["doctype"] for row in changes], ["Inventory metadata"])
            self.assertTrue(changes[0]["after"]["present"])
            self.present.clear()
            self.fake.get_installed_apps = lambda: ["hrms"]
            with self.assertRaisesRegex(RuntimeError, "Expense Claim"):
                native._inventory()

    def test_required_missing_table_still_refuses(self):
        self.present.clear()
        with patch.dict("sys.modules", {"frappe": self.fake}), patch.object(native, "INVENTORY_TABLES", ("Company",)):
            with self.assertRaisesRegex(RuntimeError, "Company"):
                native._inventory()

    def test_same_manifest_continuation_archives_originals_and_checks_all_sixteen_selectors(self):
        result, setup = self.continuation()
        self.assertEqual(result, {"status": "host-shape-only"})
        passed_value, passed_path = setup.call_args.args
        self.assertEqual(passed_path, self.path)
        self.assertEqual(passed_value["users"], self.value["users"])
        self.assertEqual(passed_value["native"], self.value["native"])
        self.assertEqual(len([row for row in self.calls if row[0] != "DocType"]), 16)
        saved = manifest(self.path)
        stage = saved["stages"]["preinventory_continuation"]
        self.assertEqual(stage["original_manifest_sha256"], hashlib.sha256(self.original_raw).hexdigest())
        archive = json.loads(Path(stage["archive_path"]).read_text())
        import base64
        self.assertEqual(base64.b64decode(archive["manifest_base64"]), self.original_raw)
        self.assertEqual(base64.b64decode(archive["failed_phase_record_base64"]), self.record.read_bytes())
        self.assertEqual(base64.b64decode(archive["failed_phase_log_base64"]), self.log.read_bytes())
        with self.assertRaises(RuntimeError):
            self.continuation()

    def test_any_partial_state_or_original_journal_refuses_before_setup(self):
        for field, changed in (("stages", {"setup": {"status": "failed"}}), ("duties", {"one": "row"}),
                ("inputs", {"ready": False}), ("intents", {"lookup": {}}), ("preservation", {"setup_old_rows_unchanged": False}),
                ("metadata_preservation", {"before": "captured"}), ("native_projection_observations", [{}]), ("shared_receipt_observations", [{}])):
            with self.subTest(field=field):
                write_private(self.path, {**self.value, field: changed})
                with self.assertRaises((ValueError, RuntimeError)):
                    self.continuation()
        write_private(self.path, self.value)
        for name in ("preservation-before.secret.json", "preservation-after-setup.secret.json", "http-journal.secret.json"):
            journal = self.work / name; write_private(journal, {})
            with self.subTest(journal=name), self.assertRaises(RuntimeError):
                self.continuation()
            journal.unlink()

    def test_each_allocated_selector_collision_refuses_without_reseed(self):
        marker = self.value["fixture_id"].removeprefix("ricky-company-")
        selectors = [("Company", self.value["company"]), ("Role", self.value["native"]["role"]),
            ("Customer", {"customer_name": self.value["native"]["customer"]}), ("Company", {"abbr": "RC" + marker[:6]}),
            *(("UOM", name) for name in self.value["native"]["uoms"]),
            *(("UOM", {"symbol": symbol}) for symbol in self.value["native"]["setup_inputs"]["uom_symbols"]),
            *(("User", row["user"]) for row in self.value["users"].values()),
            *(("Cipher Person", person) for person in ("a" * 10, "b" * 10)),
            *(("Cipher Identity Binding", {"user": row["user"]}) for row in self.value["users"].values())]
        for doctype, selector in selectors:
            self.present = {(doctype, json.dumps(selector, sort_keys=True))}
            with self.subTest(doctype=doctype, selector=selector), self.assertRaises(RuntimeError):
                self.continuation()
            self.assertEqual(self.path.read_bytes(), self.original_raw)
        self.assertEqual(len(selectors), 16)

    def test_wrong_failure_or_native_allocation_drift_refuses(self):
        for field, changed in (("site", "other.site"), ("function", "other_setup"), ("status", "succeeded"),
                ("phase", "reconcile-setup"), ("exit_code", 0), ("exit_code", True), ("main_changed", True), ("log_sha256", "f" * 64)):
            with self.subTest(field=field):
                write_private(self.record, {**self.phase, field: changed})
                with self.assertRaises((ValueError, RuntimeError)):
                    self.continuation()
        write_private(self.record, self.phase)
        for field, changed in (("role", "another role"), ("customer", "another customer"), ("uoms", ["metre", "centimetre"])):
            value = deepcopy(self.value); value["native"][field] = changed; write_private(self.path, value)
            with self.subTest(native=field), self.assertRaises(RuntimeError):
                self.continuation()

    def test_changed_hrms_or_expense_metadata_cannot_use_original_failure_continuation(self):
        self.fake.get_installed_apps = lambda: ["frappe", "erpnext", "cipher_aec", "hrms"]
        with self.assertRaises(RuntimeError):
            self.continuation()
        self.fake.get_installed_apps = lambda: ["frappe", "erpnext", "cipher_aec"]
        self.present.add(("DocType", json.dumps("Expense Claim")))
        with self.assertRaises(RuntimeError):
            self.continuation()
        self.assertEqual(self.path.read_bytes(), self.original_raw)


    def test_bad_or_nonprivate_failure_log_refuses_without_mutating_manifest(self):
        self.log.write_text("Unrelated preinventory exception")
        with self.assertRaises(RuntimeError):
            self.continuation()
        write_private(self.record, {**self.phase, "log_sha256": hashlib.sha256(self.log.read_bytes()).hexdigest()})
        with self.assertRaises(RuntimeError):
            self.continuation()
        self.log.chmod(0o644)
        with self.assertRaises(RuntimeError):
            self.continuation()
        self.assertEqual(self.path.read_bytes(), self.original_raw)

    def test_setup_body_failure_leaves_a_one_shot_marker_and_original_evidence(self):
        with patch.dict("sys.modules", {"frappe": self.fake}), \
                patch.object(native, "_load_fixture", side_effect=lambda path: manifest(path)), \
                patch.object(native, "_setup_preconditions"), \
                patch.object(native, "_complete_company_fixture_setup", side_effect=RuntimeError("Host setup refusal")) as setup:
            with self.assertRaisesRegex(RuntimeError, "Host setup refusal"):
                native.continue_company_fixture_preinventory(self.path, self.record, self.log)
            self.assertEqual(setup.call_count, 1)
            with self.assertRaises(RuntimeError):
                native.continue_company_fixture_preinventory(self.path, self.record, self.log)
            self.assertEqual(setup.call_count, 1)
        stage = manifest(self.path)["stages"]["preinventory_continuation"]
        self.assertEqual(stage["original_manifest_sha256"], hashlib.sha256(self.original_raw).hexdigest())
        self.assertTrue(Path(stage["archive_path"]).is_file())

    def test_manifest_drift_during_readback_cannot_rebind_original_credentials(self):
        def readback(value):
            changed = deepcopy(value); changed["users"]["author"]["password"] = "changed-after-load"
            write_private(self.path, changed)
            return [{"exists": False} for _ in range(16)]
        with patch.object(native, "_proposed_identity_observations", side_effect=readback):
            with self.assertRaisesRegex(RuntimeError, "manifest changed"):
                self.continuation()
        self.assertFalse((self.work / "preinventory-continuation-original.secret.json").exists())

    def test_reconciliation_without_original_inventory_records_pending_not_preserved(self):
        rolled_back = []
        self.fake.db.rollback = lambda: rolled_back.append(True)
        with patch.dict("sys.modules", {"frappe": self.fake}), \
                patch.object(native, "_load_fixture", side_effect=lambda path: manifest(path)), \
                patch.object(native, "_inventory", side_effect=AssertionError("No fabricated preinventory baseline")):
            result = native.reconcile_company_setup(self.path)
        self.assertIsNone(result["existing_old_row_changes"])
        self.assertEqual(result["preservation_status"], "not_established_no_original_before_inventory")
        saved = json.loads((self.work / "setup-reconciliation.secret.json").read_text())
        self.assertIsNone(saved["old_row_changes"])
        self.assertEqual(len(saved["proposed_identity_readback"]), 16)
        self.assertTrue(all(row["exists"] is False for row in saved["proposed_identity_readback"]))
        self.assertEqual(rolled_back, [True])
        self.assertEqual(self.path.read_bytes(), self.original_raw)


class CustomerFixturePrerequisiteSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.references = {("Customer Group", "Commercial"): {"name": "Commercial", "is_group": 0},
            ("Territory", "United States"): {"name": "United States", "is_group": 0}}
        self.reads = []
        def get_value(table, name, fields, as_dict):
            self.reads.append((table, name, fields, as_dict))
            return deepcopy(self.references.get((table, name)))
        self.fake = SimpleNamespace(local=SimpleNamespace(site="explicit.host.source.site"),
            get_site_path=lambda *args: str(self.work), db=SimpleNamespace(get_value=get_value))

    def test_required_customer_leaves_are_validated_and_recorded_before_new_setup(self):
        def complete(value, path):
            self.assertEqual(len(self.reads), 2)
            self.assertEqual(manifest(path), value)
            self.assertEqual(value["native"]["setup_inputs"]["customer_group"], "Commercial")
            self.assertEqual(value["native"]["setup_inputs"]["territory"], "United States")
            return {"private_manifest": str(path), "status": "host-shape-only"}
        with patch.dict("sys.modules", {"frappe": self.fake}), patch.object(native, "_setup_preconditions"), \
                patch.object(native, "_complete_company_fixture_setup", side_effect=complete):
            result = native.prepare_company_fixture(self.work)
        self.assertEqual(result["status"], "host-shape-only")
        self.assertEqual([(row[0], row[1]) for row in self.reads], [("Customer Group", "Commercial"), ("Territory", "United States")])
        self.assertEqual(len(list(self.work.iterdir())), 1)

    def test_missing_group_or_aliased_reference_refuses_before_ids_passwords_or_directory(self):
        for key, original in tuple(self.references.items()):
            for changed in (None, {**original, "is_group": 1}, {**original, "is_group": "0"},
                    {**original, "is_group": False}, {**original, "name": original["name"].lower()}):
                saved = self.references[key]; self.references[key] = changed
                with self.subTest(table=key[0], changed=changed), patch.dict("sys.modules", {"frappe": self.fake}), \
                        patch.object(native, "_setup_preconditions"), \
                        patch.object(native, "uuid4", side_effect=AssertionError("Must refuse before allocating fixture")), \
                        patch.object(native.secrets, "token_hex", side_effect=AssertionError("Must not allocate Person")), \
                        patch.object(native.secrets, "token_urlsafe", side_effect=AssertionError("Must not allocate password")), \
                        self.assertRaises(RuntimeError):
                    native.prepare_company_fixture(self.work)
                self.references[key] = saved
                self.assertEqual(list(self.work.iterdir()), [])

    def test_customer_insert_uses_original_recorded_reference_values(self):
        captured = []
        class CapturedCustomer(Exception): pass
        class HostDoc:
            def __init__(self, fields):
                self.fields = fields
                self.name = fields.get("name") or fields.get("company_name") or fields.get("role_name") or "host-owned-record"
                self.default_receivable_account = "host-new-company-receivable"
            def insert(self, **kwargs):
                if self.fields["doctype"] == "Customer":
                    captured.append(deepcopy(self.fields))
                    raise CapturedCustomer()
                return self
            def append(self, *args): pass
            def save(self, **kwargs): pass
        fake = SimpleNamespace(get_doc=lambda doctype, name=None: HostDoc(doctype if isinstance(doctype, dict) else {"doctype": doctype, "name": name}),
            db=SimpleNamespace(get_value=lambda *args: "host-binding", rollback=lambda: None))
        marker = "012345abcdef"
        value = {"fixture_id": "ricky-company-" + marker, "company": "host-new-company", "journal_directory": str(self.work),
            "users": {role: {"user": role, "person": "author" if role != "outsider" else "outsider", "password": "host-only"}
                for role in ("author", "alias", "outsider")}, "stages": {}, "duties": {},
            "native": {"role": "host-role", "customer": "host-customer", "uoms": ["host-metre", "host-centimetre"],
                "setup_inputs": {"company_abbr": "HOST", "customer_group": "Commercial", "territory": "United States", "uom_symbols": ["HM", "HC"]}}}
        installer = SimpleNamespace(**{name: lambda *args: None for name in ("_person", "_user", "_binding", "_grant_company")})
        permissions = SimpleNamespace(add_permission=lambda *args: None, update_permission_property=lambda *args: None)
        with patch.dict("sys.modules", {"frappe": fake, "frappe.permissions": permissions,
                "cipher_aec.governance.context": SimpleNamespace(trusted_write=nullcontext), "cipher_aec.install": installer}), \
                patch.object(native, "ABILITIES", ()), patch.object(native, "_inventory", return_value={}), \
                patch.object(native, "_proposed_identity_observations", return_value=[]), self.assertRaises(CapturedCustomer):
            native._complete_company_fixture_setup(value, self.work / "fixture.secret.json")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["customer_group"], "Commercial")
        self.assertEqual(captured[0]["territory"], "United States")
        self.assertEqual(captured[0]["accounts"], [{"company": "host-new-company", "account": "host-new-company-receivable"}])

    def test_inventory_detects_existing_customer_master_changes(self):
        rows = {"Customer Group": {"name": "Commercial", "is_group": 0},
            "Territory": {"name": "United States", "is_group": 0}}
        def sql(query, **kwargs):
            return [deepcopy(row)] if (row := next((row for table, row in rows.items() if "`tab" + table + "`" in query), None)) else []
        fake = SimpleNamespace(get_installed_apps=lambda: [], db=SimpleNamespace(exists=lambda *args: True, sql=sql))
        with patch.dict("sys.modules", {"frappe": fake}):
            before = native._inventory()
            rows["Customer Group"]["is_group"] = 1
            rows["Territory"]["is_group"] = 1
            after = native._inventory()
        self.assertEqual({row["doctype"] for row in native._old_row_changes(before, after)}, {"Customer Group", "Territory"})


class ExistingCompanyReferenceSourceTests(unittest.TestCase):
    def setUp(self):
        CustomerFixturePrerequisiteSourceTests.setUp(self)
        self.reference = {"schema": "cipher.fixture.ricky.company.reference.v1", "company": "Cipher Synthetic Company",
            "abbr": "CSA", "default_currency": "USD", "country": "United States", "default_receivable_account": "Debtors - CSA",
            "account": {"name": "Debtors - CSA", "company": "Cipher Synthetic Company", "account_currency": "USD",
                "account_type": "Receivable", "is_group": 0, "disabled": 0}, "initial_project_ids": ["PROJ-BASELINE"]}
        self.projects = ["PROJ-BASELINE"]
        self.company = {"name": self.reference["company"], **{key: self.reference[key] for key in
            ("abbr", "default_currency", "country", "default_receivable_account")}, "is_group": 0}
        self.account = deepcopy(self.reference["account"])
        read_master = self.fake.db.get_value
        def get_value(table, name, fields, as_dict=False):
            if table == "Company": return deepcopy(self.company)
            if table == "Account": return deepcopy(self.account)
            if table == "Cipher Identity Binding": return "host-new-binding"
            return read_master(table, name, fields, as_dict)
        self.fake.db.get_value = get_value
        self.fake.get_all = lambda table, **kwargs: list(self.projects)
        self.fake.db.exists = lambda *args: False
        self.fake.db.rollback = lambda: None

    def prepare(self):
        with patch.dict("sys.modules", {"frappe": self.fake}), patch.object(native, "_setup_preconditions"), \
                patch.object(native, "_complete_company_fixture_setup", side_effect=lambda value, path: manifest(path)):
            return native.prepare_company_fixture(self.work, company_reference=self.reference)

    def test_existing_reference_is_recorded_with_new_distinct_fixture_identities(self):
        value = self.prepare()
        self.assertEqual(value["company"], self.reference["company"])
        self.assertEqual(value["native"]["company_reference"], self.reference)
        self.assertEqual(value["native"]["original_project_ids"], self.projects)
        self.assertEqual(value["native"]["setup_inputs"]["company_abbr"], "CSA")
        self.assertNotEqual(value["users"]["author"]["person"], value["users"]["outsider"]["person"])
        self.assertTrue(all(value["fixture_id"].removeprefix("ricky-company-") in row["user"] for row in value["users"].values()))
        with patch.dict("sys.modules", {"frappe": self.fake}):
            observed = native._proposed_identity_observations(value)
        self.assertEqual(len(observed), 14)
        self.assertFalse(any(row["doctype"] == "Company" for row in observed))
        self.assertTrue(all(row["exists"] is False for row in observed))
        path = Path(value["journal_directory"]) / "fixture.secret.json"
        for change in ({"original_project_ids": []}, {"company_reference": {**self.reference, "company": "Foreign"}}):
            altered = deepcopy(value); altered["native"].update(change); write_private(path, altered)
            with self.assertRaises(ValueError): manifest(path)

    def test_foreign_or_changed_company_account_and_project_set_refuse_before_allocation(self):
        for target, key, changed in ((self.company, "name", "Foreign"), (self.company, "abbr", "DIFF"),
                (self.company, "default_currency", "EUR"), (self.company, "default_receivable_account", "Foreign Account"),
                (self.company, "is_group", 1), (self.account, "name", "Other"), (self.account, "company", "Foreign"),
                (self.account, "account_currency", "EUR"), (self.account, "account_type", "Payable"),
                (self.account, "is_group", 1), (self.account, "disabled", 1)):
            original = target[key]; target[key] = changed
            with self.subTest(field=key, changed=changed), patch.object(native, "uuid4", side_effect=AssertionError("Before allocation")), \
                    self.assertRaises((ValueError, RuntimeError)):
                self.prepare()
            target[key] = original
            self.assertEqual(list(self.work.iterdir()), [])

        for ids in ([], ["PROJ-OTHER"], ["PROJ-BASELINE", "PROJ-EXTRA"]):
            self.projects = ids
            with self.subTest(projects=ids), patch.object(native, "uuid4", side_effect=AssertionError("Before allocation")), \
                    self.assertRaises((ValueError, RuntimeError)):
                self.prepare()
            self.assertEqual(list(self.work.iterdir()), [])

    def test_reference_setup_never_inserts_or_saves_company_or_account_and_reconciles_expected_company(self):
        value = self.prepare()
        captured = []
        class CapturedCustomer(Exception): pass
        class HostDoc:
            def __init__(self, fields):
                self.fields = fields
                self.name = fields.get("name") or fields.get("role_name") or "host-new-record"
                self.default_receivable_account = "Debtors - CSA"
            def insert(self, **kwargs):
                if self.fields["doctype"] in ("Company", "Account"):
                    raise AssertionError("A referenced Company/account must never be inserted")
                if self.fields["doctype"] == "Customer":
                    captured.append(deepcopy(self.fields))
                    raise CapturedCustomer()
                return self
            def append(self, *args): pass
            def save(self, **kwargs):
                if self.fields["doctype"] in ("Company", "Account"):
                    raise AssertionError("A referenced Company/account must never be saved")
        self.fake.get_doc = lambda doctype, name=None: HostDoc(doctype if isinstance(doctype, dict) else {"doctype": doctype, "name": name})
        self.fake.db.exists = lambda table, selector: table == "Company" and selector == value["company"]
        installer = SimpleNamespace(**{name: lambda *args: None for name in ("_person", "_user", "_binding", "_grant_company")})
        permissions = SimpleNamespace(add_permission=lambda *args: None, update_permission_property=lambda *args: None)
        path = Path(value["journal_directory"]) / "fixture.secret.json"
        with patch.dict("sys.modules", {"frappe": self.fake, "frappe.permissions": permissions,
                "cipher_aec.governance.context": SimpleNamespace(trusted_write=nullcontext), "cipher_aec.install": installer}), \
                patch.object(native, "ABILITIES", ()), patch.object(native, "_inventory", return_value={}) as inventory:
            self.references[("Customer Group", "Commercial")]["is_group"] = 1
            with self.assertRaisesRegex(RuntimeError, "non-group fixture master"):
                native._complete_company_fixture_setup(value, path)
            self.assertEqual(inventory.call_count, 0)
            self.assertEqual(captured, [])
            self.references[("Customer Group", "Commercial")]["is_group"] = 0
            with self.assertRaises(CapturedCustomer):
                native._complete_company_fixture_setup(value, path)
            with patch.object(native, "_load_fixture", side_effect=lambda path: manifest(path)):
                result = native.reconcile_company_setup(path)
        self.assertEqual(captured[0]["accounts"], [{"company": value["company"], "account": "Debtors - CSA"}])
        self.assertEqual(result["company_mode"], "referenced-existing")
        self.assertIs(result["company_expected_present"], True)
        self.assertIs(result["company_exists"], True)
        self.assertIs(result["company_reference_matches"], True)
        self.assertEqual(result["existing_fixture_users"], 0)
        self.assertEqual(result["existing_old_row_changes"], 0)
        readback = json.loads((path.parent / "setup-reconciliation.secret.json").read_text())
        self.assertEqual(len(readback["proposed_identity_readback"]), 14)
        self.assertFalse(any(row["exists"] for row in readback["proposed_identity_readback"]))

    def test_restoration_keeps_exact_existing_project_set_and_reports_zero_introduced(self):
        value = self.prepare()
        value["preservation"] = {"setup_old_rows_unchanged": True}
        value["duties"] = {}
        value["stages"] = {}
        self.fake.db.count = lambda table, filters: len(self.projects)
        write_private(Path(value["journal_directory"]) / "preservation-before.secret.json", {})
        context = SimpleNamespace(current_actor=lambda user: SimpleNamespace(person_id=next(row["person"] for row in value["users"].values() if row["user"] == user)),
            duty_rows=lambda actor: [])
        with patch.dict("sys.modules", {"frappe": self.fake, "cipher_aec.governance.context": context}), \
                patch.object(native, "_fixture", return_value=value), patch.object(native, "_inventory", return_value={}):
            result = native.verify_company_restoration("host-manifest")
            self.assertEqual(result["company_projects"], 1)
            self.assertEqual(result["introduced_projects"], 0)
            for ids in ([], ["PROJ-OTHER"], ["PROJ-BASELINE", "PROJ-EXTRA"]):
                self.projects = ids
                with self.subTest(projects=ids), self.assertRaises((RuntimeError, AssertionError)):
                    native.verify_company_restoration("host-manifest")
            self.projects = ["PROJ-BASELINE"]
            write_private(Path(value["journal_directory"]) / "preservation-before.secret.json", {"Project": {"PROJ-BASELINE": {"old_field": "old-hash"}}})
            with patch.object(native, "_inventory", return_value={"Project": {"PROJ-BASELINE": {"old_field": "changed-hash"}}}):
                with self.assertRaisesRegex(AssertionError, "existing literal"):
                    native.verify_company_restoration("host-manifest")

