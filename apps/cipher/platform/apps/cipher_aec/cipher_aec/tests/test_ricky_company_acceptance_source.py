"""Host-only fixture-journal/expectation checks; no site or network execution."""
import ast
from copy import deepcopy
import json
import hashlib
from io import BytesIO
from email.message import Message
from urllib.request import BaseHandler, build_opener
from urllib.error import HTTPError
from urllib.response import addinfourl
from uuid import uuid4
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .ricky_company_acceptance_support import (SCHEMA, Journal, RICKY_TYPES, manifest, saved_intent,
    sha, verify_read_value, write_private, require_projection_coverage, typed_equal, declared_case, declare_corrected_case, completed_read_cases)
from .test_ricky_company_native import _old_row_changes
from .test_ricky_company_http import _HTTP, RICKY


class CompanyAcceptanceSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        marker = "012345abcdef"
        self.path = self.work / "fixture.secret.json"
        self.fixture = {"schema": SCHEMA, "fixture_id": "ricky-company-" + marker, "site": "explicit.synthetic",
            "created_at": "2026-10-16T00:00:00+00:00", "company": "Ricky Company " + marker,
            "users": {role: {"user": f"ricky.company.{role}.{marker}@cipher.example",
                "person": "b" * 10 if role == "outsider" else "a" * 10, "password": "HOST_ONLY_UNUSED"}
                for role in ("author", "alias", "outsider")}, "native": {}, "duties": {}, "inputs": {},
            "intents": {}, "stages": {}, "preservation": {}, "journal_directory": str(self.work),
            "metadata_preservation": {}, "native_projection_observations": [], "shared_receipt_observations": []}
        write_private(self.path, self.fixture)

    def test_manifest_exact_scope_identity_and_private_permissions(self):
        self.assertEqual(manifest(self.path)["users"]["alias"]["person"], "a" * 10)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        for change in ({"company": "Other Company"}, {"schema": "other"}, {"project": "inferred"}, {"intents": {"unplanned": {}}}):
            with self.subTest(change=change):
                write_private(self.path, {**self.fixture, **change})
                with self.assertRaises(ValueError): manifest(self.path)
        write_private(self.path, self.fixture)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): manifest(self.path)

    def test_alias_is_same_person_but_never_rewritten_original_user(self):
        changed = deepcopy(self.fixture)
        changed["users"]["alias"]["person"] = "c" * 10
        write_private(self.path, changed)
        with self.assertRaises(ValueError): manifest(self.path)
        changed = deepcopy(self.fixture)
        changed["users"]["author"]["user"] = changed["users"]["alias"]["user"]
        write_private(self.path, changed)
        with self.assertRaises(ValueError): manifest(self.path)

    def test_first_send_is_durable_and_uncertain_retry_keeps_original_uuid(self):
        journal = Journal(self.work)
        with patch("cipher_aec.tests.ricky_company_acceptance_support.os.fsync", wraps=__import__("os").fsync) as fsync:
            row = journal.prepare("start-lookup", "author", RICKY + "start_read", {"company": self.fixture["company"], "request": {"fixed": True}})
        self.assertGreaterEqual(fsync.call_count, 2)
        original = row["operation_id"]
        journal.uncertain(row, TimeoutError())
        restored = Journal(self.work)
        retry = restored.prepare("start-lookup", "author", RICKY + "start_read", {"company": self.fixture["company"], "request": {"fixed": True}})
        self.assertEqual(retry["operation_id"], original)
        self.assertEqual(retry["uncertain_transport"]["error_type"], "TimeoutError")
        self.assertEqual(len(restored.rows), 1)

    def test_original_payload_actor_or_method_cannot_drift(self):
        journal = Journal(self.work)
        journal.prepare("case", "author", RICKY + "start_read", {"company": "A"})
        for role, method, body in (("alias", RICKY + "start_read", {"company": "A"}),
                ("author", RICKY + "cancel_run", {"company": "A"}), ("author", RICKY + "start_read", {"company": "B"})):
            with self.subTest(role=role, method=method, body=body), self.assertRaises(ValueError):
                journal.prepare("case", role, method, body)

    def test_credentials_and_tampered_hash_never_reach_a_send(self):
        journal = Journal(self.work)
        for value in ({"pwd": "secret"}, {"request": {"sources": [{"cookie": "secret"}]}}):
            with self.assertRaises(ValueError): journal.prepare("case", "author", RICKY + "start_read", value)
        row = journal.prepare("case", "author", RICKY + "start_read", {"company": "A"})
        row["payload_sha256"] = "f" * 64
        with self.assertRaises(ValueError): journal.prepare("case", "author", RICKY + "start_read", {"company": "A"})

    def test_http_uncertain_outcome_preserves_durable_intent_before_wire(self):
        rpc = _HTTP(self.path, "http://localhost:8000")
        rpc.role, rpc.csrf = "author", "HOST_ONLY_UNUSED_CSRF"
        def timeout(*args, **kwargs):
            prepared = Journal(self.work).rows
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0]["operation_id"], kwargs["operation"])
            raise TimeoutError("Explicit host transport double")
        with patch.object(rpc, "_wire", side_effect=timeout):
            with self.assertRaises(TimeoutError): rpc.call(RICKY + "start_read", {"company": self.fixture["company"], "request": {"schema": "cipher.ricky.company.read-request.v1", "pursuit_id": "12345678-1234-4234-8234-123456789abc", "action": "aec.pursuit.lookup", "arguments": {}, "sources": [], "measurement_ids": []}}, key="start-lookup")
        original = Journal(self.work).rows[0]
        self.assertEqual(original["uncertain_transport"]["error_type"], "TimeoutError")
        self.assertEqual(original["attempts"], [])

    def test_no_arbitrary_route_or_credential_origin(self):
        with self.assertRaises(ValueError): _HTTP(self.path, "http://user:password@localhost:8000")
        rpc = _HTTP(self.path, "http://localhost:8000")
        with patch.object(rpc, "_wire", side_effect=AssertionError("Must not send")):
            with self.assertRaises(ValueError): rpc.call("frappe.client.insert", {})
            with self.assertRaises(ValueError): rpc.login("Administrator")

    def admission(self, case="lookup"):
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        request = {"schema": "cipher.ricky.company.read-request.v1", "pursuit_id": str(uuid4()),
            "action": "aec.pursuit.lookup", "arguments": {}, "sources": [], "measurement_ids": []}
        if case == "convert": request.update(action="aec.quantity.convert", arguments={"source_kind": "estimate-line", "source_id": str(uuid4()), "target_unit_id": str(uuid4())})
        row = Journal(self.work).prepare("start-" + case, "author", RICKY + "start_read", {"company": self.fixture["company"], "request": request})
        body = {"id": str(uuid4()), "company": self.fixture["company"], "scope_type": "Company", "project": None,
            "request_kind": "deterministic-read-v1", "status": "queued", "cancel_requested": False,
            "created_at": self.fixture["created_at"], "completed_at": None, "action": request["action"], "result": None,
            "result_digest": None, "error": None, "standing": DeterministicReadRequest.model_standing(),
            "result_basis": "original-tool-observation-v1", "selection": request,
            "selection_digest": DeterministicReadRequest.from_value(request).selection_digest()}
        request_id = str(uuid4())
        envelope = {"schema": "cipher.api.v1", "request_id": request_id, "meta": {"request_id": request_id, "api_version": "v1"},
            "data": {**body, "operation": {"id": row["operation_id"], "status": "succeeded", "replayed": False}}}
        journal = Journal(self.work); journal.response(next(row for row in journal.rows if row["key"] == "start-" + case), status=200, envelope=envelope)
        intent = {"case": case, "operation_id": row["operation_id"], "payload": row["payload"], "payload_sha256": row["payload_sha256"],
            "start": body, "run_id": body["id"], "request_id": request_id}
        self.fixture["intents"][case] = intent
        return intent

    def correction(self, case="convert-r9"):
        original = "convert" if case == "convert-r9" else "claim-race"
        intent = self.admission(original)
        run = {"id": intent["run_id"], "operation_id": intent["operation_id"], "company": self.fixture["company"],
            "user": self.fixture["users"]["author"]["user"], "person": self.fixture["users"]["author"]["person"],
            "status": "failed" if original == "convert" else "cancelled", "scope_type": "Company", "project": None,
            "request": intent["payload"]["request"], "cancel_requested": original != "convert", "result": None,
            "completed_at": self.fixture["created_at"], "error": {"code": "source_integrity"} if original == "convert" else None}
        proof = self.work / (original + "-terminal.private.json")
        write_private(proof, {"run": run})
        declaration = {"schema": "cipher.fixture.ricky.corrected-case.v1", "case": case, "predecessor_case": original,
            "predecessor_run_id": intent["run_id"], "predecessor_operation_id": intent["operation_id"],
            "predecessor_intent_sha256": sha(intent), "predecessor_status": run["status"], "predecessor_run_sha256": sha(run),
            "evidence": [{"file": proof.name, "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}]}
        if original == "claim-race":
            unresolved = self.work / "claim-race-unqualified.private.json"
            write_private(unresolved, {"run": {**run, "status": "retrieving", "completed_at": None, "cancel_requested": False}})
            declaration["evidence"].append({"file": unresolved.name, "sha256": hashlib.sha256(unresolved.read_bytes()).hexdigest()})
        write_private(self.path, self.fixture)
        return declaration

    def test_corrected_case_requires_explicit_original_terminal_evidence_before_login(self):
        from . import test_ricky_company_http as http
        self.admission("convert"); write_private(self.path, self.fixture)
        original = (self.work / "http-journal.secret.json").read_bytes()
        with patch.object(http._HTTP, "login", side_effect=AssertionError("No login before declaration")), self.assertRaises(ValueError):
            http.start_company_http_case(self.path, "convert-r9", "http://localhost:8000")
        self.assertEqual((self.work / "http-journal.secret.json").read_bytes(), original)

    def test_corrected_declaration_retains_original_and_uses_distinct_case_without_allocating(self):
        declaration = self.correction()
        before = deepcopy(self.fixture["intents"]["convert"])
        journal = (self.work / "http-journal.secret.json").read_bytes()
        declare_corrected_case(self.path, declaration)
        value = manifest(self.path)
        self.assertEqual(saved_intent(value, "convert"), before)
        self.assertEqual(declared_case(value, "convert-r9"), "convert")
        self.assertEqual(completed_read_cases(value), ("lookup", "recompute", "compare", "convert-r9"))
        self.assertEqual((self.work / "http-journal.secret.json").read_bytes(), journal)
        with self.assertRaises(ValueError): declare_corrected_case(self.path, {**declaration, "predecessor_run_sha256": "0" * 64})

    def test_corrected_predecessor_tampering_foreign_identity_and_nonterminal_proof_refuse(self):
        declaration = self.correction()
        for changes in ({"predecessor_operation_id": str(uuid4())}, {"predecessor_status": "succeeded"},
                {"predecessor_intent_sha256": "0" * 64}, {"evidence": [{"file": "../escape", "sha256": "0" * 64}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                declare_corrected_case(self.path, {**deepcopy(declaration), **changes})
        proof = self.work / declaration["evidence"][0]["file"]
        data = json.loads(proof.read_text()); data["run"]["status"] = "retrieving"
        write_private(proof, data)
        with self.assertRaises(ValueError): declare_corrected_case(self.path, declaration)

    def test_corrected_conversion_start_has_distinct_journal_uuid_and_preserves_failed_origin(self):
        from . import test_ricky_company_http as http
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        declaration = self.correction()
        declare_corrected_case(self.path, declaration)
        value = manifest(self.path)
        original = deepcopy(saved_intent(value, "convert"))
        original_row = deepcopy(Journal(self.work).rows[0])
        request = original["payload"]["request"]
        value["inputs"] = {"ready": True, "pursuit": {"id": request["pursuit_id"]}, "line_record": request["arguments"]["source_id"],
            "units": [{"id": str(uuid4())}, {"id": request["arguments"]["target_unit_id"]}], "measurement": {"id": str(uuid4())},
            "citation": {"id": "a" * 64, "revision_id": "fixture-raw-revision", "page": 1, "excerpt_sha256": "b" * 64, "source_sha256": "c" * 64}}
        write_private(self.path, value)
        owner = self
        class LocalStart:
            def __init__(self, *args): self.value, self.journal = manifest(owner.path), Journal(owner.work)
            def login(self): pass
            def call(self, method, payload, *, key):
                self.assertion = (method, key)
                row = self.journal.prepare(key, "author", method, payload)
                selected = DeterministicReadRequest.from_value(payload["request"])
                body = {**deepcopy(original["start"]), "id": str(uuid4()), "selection": payload["request"],
                    "selection_digest": selected.selection_digest(), "action": selected.action}
                request_id = str(uuid4())
                envelope = {"schema": "cipher.api.v1", "request_id": request_id,
                    "meta": {"request_id": request_id, "api_version": "v1"},
                    "data": {**body, "operation": {"id": row["operation_id"], "status": "succeeded", "replayed": False}}}
                self.journal.response(row, status=200, envelope=envelope)
                return envelope
        with patch.object(http, "_HTTP", LocalStart):
            result = http.start_company_http_case(self.path, "convert-r9", "http://not-used.invalid")
        current = manifest(self.path)
        corrected = saved_intent(current, "convert-r9")
        self.assertEqual(result["case"], "convert-r9")
        self.assertEqual(corrected["payload"]["request"]["action"], "aec.quantity.convert")
        self.assertNotEqual(corrected["operation_id"], original["operation_id"])
        self.assertNotEqual(corrected["run_id"], original["run_id"])
        self.assertEqual(saved_intent(current, "convert"), original)
        self.assertEqual(Journal(self.work).rows[0], original_row)
        current["intents"]["convert-r9"]["operation_id"] = original["operation_id"]
        current["intents"]["convert-r9"]["payload"]["operation_id"] = original["operation_id"]
        current["intents"]["convert-r9"]["payload_sha256"] = sha(current["intents"]["convert-r9"]["payload"])
        with self.assertRaises(ValueError): saved_intent(current, "convert-r9")

    def test_corrected_race_declaration_keeps_cancelled_predecessor_and_is_opt_in(self):
        declaration = self.correction("claim-race-r9")
        with self.assertRaises(ValueError):
            declare_corrected_case(self.path, {**declaration, "evidence": declaration["evidence"][:1]})
        declare_corrected_case(self.path, declaration)
        value = manifest(self.path)
        self.assertEqual(declared_case(value, "claim-race-r9"), "claim-race")
        self.assertNotIn("claim-race-r9", value["intents"])
        self.assertEqual(value["stages"]["corrected_cases"]["claim-race-r9"]["predecessor_status"], "cancelled")

    def test_original_failed_conversion_observation_retains_queued_receipt_without_claiming_success(self):
        from . import test_ricky_company_http as http
        declaration = self.correction()
        declare_corrected_case(self.path, declaration)
        original = deepcopy(self.fixture["intents"]["convert"])
        current = {**deepcopy(original["start"]), "status": "failed", "completed_at": self.fixture["created_at"],
            "error": {"code": "source_integrity", "message": "Original retained failure", "retryable": False}}
        owner = self
        class LocalObserve:
            def __init__(self, *args): self.value = manifest(owner.path)
            def login(self, *args): pass
            def call(self, method, payload, **kwargs):
                if method == RICKY + "get_run": return {"data": deepcopy(current)}
                if method == RICKY + "run_events": return {"data": []}
                return {"data": {**deepcopy(original["start"]), "operation": {
                    "id": original["operation_id"], "status": "succeeded", "replayed": True}}}
        # Owner denials are separate ordinary calls, modeled by this scoped
        # stub; this test checks only retained predecessor vs queued receipt.
        with patch.object(http, "_HTTP", LocalObserve):
            observed = http.observe_company_http_case(self.path, "convert", "http://not-used.invalid")
            self.assertEqual(observed["standing"], "failed")
            current.update(status="succeeded")
            with self.assertRaisesRegex(AssertionError, "cannot become"):
                http.observe_company_http_case(self.path, "convert", "http://not-used.invalid")
        value = manifest(self.path)
        self.assertEqual(saved_intent(value, "convert"), original)
        self.assertEqual(value["stages"]["receipt_http_observations"]["start-convert"]["replay"]["status"], "queued")

    def test_saved_origin_requires_original_queued_http_selection(self):
        self.admission(); saved_intent(self.fixture, "lookup")
        for field, value in (("run_id", str(uuid4())), ("payload_sha256", "f" * 64), ("case", "compare"), ("request_id", str(uuid4()))):
            changed = deepcopy(self.fixture); changed["intents"]["lookup"][field] = value
            with self.assertRaises(ValueError): saved_intent(changed, "lookup")
        changed = deepcopy(self.fixture); changed["intents"]["lookup"]["start"]["status"] = "succeeded"
        with self.assertRaises(ValueError): saved_intent(changed, "lookup")

    def test_boolean_integer_admission_or_standing_substitution_refuses(self):
        self.admission()
        self.assertFalse(typed_equal({"page": 1}, {"page": True}))
        for mutate in (lambda row: row["start"].update(cancel_requested=0),
                lambda row: row["start"]["standing"].update(model_invoked=0),
                lambda row: row["start"].update(selection_digest="f" * 64)):
            changed = deepcopy(self.fixture); mutate(changed["intents"]["lookup"])
            with self.assertRaises((ValueError, __import__("jsonschema").ValidationError)): saved_intent(changed, "lookup")

    def test_preservation_catches_old_raw_json_config_field_change_and_removal(self):
        before = {"Cipher Ricky Run": {"old": {"data_json": sha('{"project":"old"}')}}, "Currency": {"USD": {"modified": sha("old")}}}
        self.assertEqual(_old_row_changes(before, {**before, "Company": {"new": {}}}), [])
        changed = deepcopy(before); changed["Currency"]["USD"]["modified"] = sha("new")
        self.assertEqual(_old_row_changes(before, changed)[0]["doctype"], "Currency")
        changed = deepcopy(before); changed["Cipher Ricky Run"].clear()
        self.assertIsNone(_old_row_changes(before, changed)[0]["after"])

    def test_fixed_result_checks_refuse_changed_values_and_false_geometry_claims(self):
        inputs = {"pursuit": {"title": "Authored fixture"}, "line_value": {"id": "original-line"}, "units": [{"id": "metre"}, {"id": "centimetre"}]}
        verify_read_value(inputs, "lookup", {"title": "Authored fixture", "record_digest": sha(inputs["pursuit"])})
        conversion = {"numerator": "200", "denominator": "1", "source_digest": sha(inputs["line_value"]), "target_unit_id": "centimetre",
            "provenance": "authored-estimate-line", "independently_verified": False, "eligible_for_new_use": False, "model_supplied_quantity": False}
        verify_read_value(inputs, "convert", conversion)
        for change in ({"numerator": "201"}, {"independently_verified": True}, {"model_supplied_quantity": True}, {"eligible_for_new_use": True}):
            with self.assertRaises(AssertionError): verify_read_value(inputs, "convert", {**conversion, **change})

    def test_fixture_has_no_new_start_native_session_or_worker_config_path(self):
        root = Path(__file__).parent
        tree = ast.parse((root / "test_ricky_company_native.py").read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(node.func, ast.Attribute) and node.func.attr in {"start_read", "enqueue", "begin"} for node in calls))
        self.assertFalse(any(isinstance(node.func, ast.Name) and node.func.id in {"Session", "FixtureAdapter"} for node in calls))
        self.assertNotIn("INSERT INTO tabSessions", (root / "test_ricky_company_native.py").read_text())
        for name in ("test_ricky_company_native.py", "test_ricky_company_http.py"):
            module = ast.parse((root / name).read_text())
            self.assertFalse(any(isinstance(node, ast.FunctionDef) and node.name == "run_acceptance" for node in module.body))

    def test_projection_partial_duplicate_or_missing_known_ids_cannot_claim_all_six(self):
        known = {table: [] if table == "Cipher Proposed Change" else ["actual-known-" + table] for table in RICKY_TYPES}
        rows = [{"user": user["user"], "doctype": table, "known_company_ids": known[table]} for user in self.fixture["users"].values() for table in RICKY_TYPES]
        require_projection_coverage(self.fixture, rows, known)
        for changed in (rows[:-1], rows + [rows[0]], rows[:-1] + [rows[0]]):
            with self.assertRaises(ValueError): require_projection_coverage(self.fixture, changed, known)
        changed = deepcopy(rows); changed[0]["known_company_ids"] = []
        with self.assertRaises(ValueError): require_projection_coverage(self.fixture, changed, known)
        forged = deepcopy(known); forged["Cipher Proposed Change"] = ["fabricated"]
        with self.assertRaises(ValueError): require_projection_coverage(self.fixture, rows, forged)

    def test_missing_actual_receipt_facts_remain_pending_not_qualified(self):
        from . import test_ricky_company_native as native
        with patch.dict("sys.modules", {"frappe": SimpleNamespace()}), patch.object(native, "_fixture", return_value=self.fixture):
            result = native.verify_company_shared_receipts(self.path)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(result["missing_actual_captures"]), 6)

    def test_no_redirected_login_or_csrf_send_and_pure_origin_only(self):
        from .test_ricky_company_http import _NoRedirect
        for url in ("http://localhost/prefix", "http://localhost/?query=yes", "http://localhost/#fragment"):
            with self.assertRaises(ValueError): _HTTP(self.path, url)
        sent = []
        class RedirectFixture(BaseHandler):
            handler_order = 0
            def http_open(self, request):
                sent.append(request.full_url)
                headers = Message(); headers["Location"] = "https://another-origin.invalid/steal"
                response = addinfourl(BytesIO(b"redirect"), headers, request.full_url, 302)
                response.msg = "Found"
                return response
            https_open = http_open
        rpc = _HTTP(self.path, "http://localhost")
        rpc.opener = build_opener(RedirectFixture(), _NoRedirect())
        with self.assertRaises(AssertionError): rpc._wire("POST", "/api/method/login", {"usr": "HOST_ONLY", "pwd": "HOST_ONLY"}, csrf="HOST_ONLY")
        self.assertEqual(sent, ["http://localhost/api/method/login"])
        facts = json.loads((self.work / "wire-observations.secret.json").read_text())
        self.assertEqual(facts[0]["refusal"], "redirect_refused_no_forward")
        self.assertEqual(facts[0]["status"], 302)

    def test_malformed_json_response_is_bound_to_original_uuid_before_refusal(self):
        class MalformedFixture(BaseHandler):
            handler_order = 0
            def http_open(self, request):
                response = addinfourl(BytesIO(b"<html>malformed</html>"), Message(), request.full_url, 200)
                response.msg = "OK"
                return response
        intent = self.admission()
        # Keep the existing original request; the response is a new observation,
        # not a substitute start or new operation UUID.
        rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
        rpc.opener = build_opener(MalformedFixture())
        with self.assertRaises(AssertionError): rpc.call(RICKY + "start_read", {key: item for key, item in intent["payload"].items() if key != "operation_id"}, key="start-lookup")
        row = Journal(self.work).rows[0]
        self.assertEqual(row["operation_id"], intent["operation_id"])
        self.assertEqual(row["uncertain_transport"]["response_observation"]["body_sha256"], hashlib.sha256(b"<html>malformed</html>").hexdigest())

    def test_http_error_body_is_closed_on_denial_refusal_and_read_failure(self):
        class FailedRead(BytesIO):
            def read(self, *args):
                raise OSError("Explicit host body-read failure")
        cases = ((403, BytesIO(b'{"error":"denied"}'), None),
            (403, BytesIO(b"malformed"), AssertionError),
            (302, BytesIO(b"redirect"), AssertionError),
            (503, BytesIO(b"x" * 2097153), AssertionError),
            (403, FailedRead(), OSError))
        for status, body, refusal in cases:
            with self.subTest(status=status, refusal=refusal):
                rpc = _HTTP(self.path, "http://localhost")
                error = HTTPError("http://localhost/api/method/fixture", status, "Host fixture", Message(), body)
                def denied(request, timeout):
                    raise error
                rpc.opener = SimpleNamespace(open=denied)
                if refusal is None:
                    actual, payload, _ = rpc._wire("GET", "/api/method/fixture")
                    self.assertEqual((actual, payload), (403, {"error": "denied"}))
                else:
                    with self.assertRaises(refusal):
                        rpc._wire("GET", "/api/method/fixture")
                self.assertTrue(body.closed)

    def test_malformed_envelope_retains_private_status_hash_refusal(self):
        intent = self.admission()
        rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
        rpc.last_wire_observation = {"status": 200, "body_sha256": "a" * 64}
        with patch.object(rpc, "_wire", return_value=(200, {"message": {"schema": "wrong"}}, 0)):
            with self.assertRaises(AssertionError): rpc.call(RICKY + "start_read", {key: item for key, item in intent["payload"].items() if key != "operation_id"}, key="start-lookup")
        row = Journal(self.work).rows[0]
        self.assertEqual(row["attempts"][-1]["refusal"], "malformed_canonical_envelope")
        self.assertEqual(row["attempts"][-1]["response_observation"]["body_sha256"], "a" * 64)

    def test_original_cookie_jar_is_archived_exactly_before_renewal(self):
        rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"
        rpc.cookie_path = self.work / "author.cookies.secret"
        raw = b"HOST_ONLY_OPAQUE_COOKIE_JAR_BYTES_NO_SESSION_CREATED"
        rpc.cookie_path.write_bytes(raw); rpc.cookie_path.chmod(0o600)
        digest = rpc.archive_cookie_context("before-deliberate-logout")
        rpc.cookie_path.write_bytes(b"new-context")
        archive = Path(rpc.value["stages"]["cookie_provenance"][0]["path"])
        self.assertEqual(archive.read_bytes(), raw)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_expected_denial_still_validates_original_request_before_wire(self):
        from jsonschema import ValidationError
        rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
        with patch.object(rpc, "_wire", side_effect=AssertionError("Must not send invalid fixture input")):
            with self.assertRaises(ValidationError): rpc.call(RICKY + "start_read", {"company": self.fixture["company"]}, key="denied", expected={"capability_denied"})

    def wire_envelope(self, intent, *, error=None):
        request_id = str(uuid4())
        envelope = {"schema": "cipher.api.v1", "request_id": request_id,
            "meta": {"request_id": request_id, "api_version": "v1", "server_time": self.fixture["created_at"]}}
        if error is None:
            envelope["data"] = {**deepcopy(intent["start"]), "operation": {"id": intent["operation_id"], "status": "succeeded", "replayed": True}}
        else:
            envelope["error"] = {"code": error, "message": "Explicit host denial", "details": {}, "retryable": False}
        return envelope

    def test_actual_openapi_accepts_wrapped_wire_response_then_returns_normalized_envelope(self):
        from jsonschema import Draft202012Validator, FormatChecker, ValidationError
        intent = self.admission()
        rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
        envelope = self.wire_envelope(intent); payload = {"message": envelope}
        schema = rpc.openapi["paths"]["/api/method/" + RICKY + "start_read"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        validator = Draft202012Validator({"components": rpc.openapi["components"], **schema}, format_checker=FormatChecker())
        validator.validate(payload)
        with self.assertRaises(ValidationError): validator.validate(envelope)
        cookie_path = self.work / "author.cookies.secret"
        cookie_path.write_bytes(b"HOST_ONLY_ORIGINAL_COOKIE_BYTES"); cookie_path.chmod(0o600)
        with patch.object(rpc, "_wire", return_value=(200, payload, 0)):
            actual = rpc.call(RICKY + "start_read", {key: value for key, value in intent["payload"].items() if key != "operation_id"}, key="start-lookup")
        self.assertIs(actual, envelope)
        rows = Journal(self.work).rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operation_id"], intent["operation_id"])
        self.assertEqual(rows[0]["payload_sha256"], intent["payload_sha256"])
        self.assertEqual(rows[0]["attempts"][-1]["envelope"], envelope)
        self.assertEqual(cookie_path.read_bytes(), b"HOST_ONLY_ORIGINAL_COOKIE_BYTES")

    def test_actual_openapi_refuses_missing_or_malformed_wire_wrapper_without_new_intent(self):
        intent = self.admission()
        envelope = self.wire_envelope(intent)
        for payload in (envelope, {}, {"message": None}, {"message": [envelope]}, {"message": envelope, "unexpected": True}):
            rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
            with self.subTest(payload_type=type(payload.get("message")).__name__), patch.object(rpc, "_wire", return_value=(200, payload, 0)), self.assertRaises(AssertionError):
                rpc.call(RICKY + "start_read", {key: value for key, value in intent["payload"].items() if key != "operation_id"}, key="start-lookup")
            rows = Journal(self.work).rows
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["operation_id"], intent["operation_id"])
            self.assertEqual(rows[0]["payload_sha256"], intent["payload_sha256"])
            self.assertIn("refusal", rows[0]["attempts"][-1])

    def test_actual_openapi_validates_wrapped_authorization_and_authentication_denials(self):
        intent = self.admission()
        for status, code in ((403, "capability_denied"), (401, "authentication_required")):
            rpc = _HTTP(self.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
            envelope = self.wire_envelope(intent, error=code)
            values = {key: value for key, value in intent["payload"].items() if key != "operation_id"}
            with self.subTest(status=status), patch.object(rpc, "_wire", return_value=(status, {"message": envelope}, 0)):
                if status == 403:
                    self.assertEqual(rpc.call(RICKY + "start_read", values, key="start-lookup", expected={code}), envelope)
                else:
                    with self.assertRaisesRegex(AssertionError, "ordinary fixture request failed"):
                        rpc.call(RICKY + "start_read", values, key="start-lookup")
            rows = Journal(self.work).rows
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["operation_id"], intent["operation_id"])
            self.assertEqual(rows[0]["attempts"][-1]["envelope"], envelope)
            self.assertNotIn("refusal", rows[0]["attempts"][-1])

    def qualified_input_units(self):
        return [{"id": str(uuid4()), "kind": "uom", "revision": 1,
            "fields": {"symbol": symbol, "dimension": "length", "precision": 6}, "target": {"doctype": "UOM", "name": name}}
            for name, symbol in (("Host metre", "HM"), ("Host centimetre", "HC"))]

    def test_operator_unit_references_are_required_before_any_authored_command(self):
        from . import test_ricky_company_http as http
        units = self.qualified_input_units()
        self.fixture["preservation"]["setup_old_rows_unchanged"] = True
        base_native = {"uoms": ["Host metre", "Host centimetre"], "qualified_units": units}
        changed = [None, [], units[:1], [*units, units[0]], [units[0], units[0]], list(reversed(units))]
        for mutate in (lambda rows: rows[0]["target"].update(name="Foreign unit"),
                lambda rows: rows[0]["fields"].update(dimension="area"), lambda rows: rows[0]["fields"].update(precision=5)):
            rows = deepcopy(units); mutate(rows); changed.append(rows)
        for recorded in changed:
            self.fixture["native"] = {**base_native, "qualified_units": recorded}; write_private(self.path, self.fixture)
            with self.subTest(recorded=recorded), patch.object(http._HTTP, "login", side_effect=AssertionError("Refuse invalid prerequisite before login")), \
                    patch.object(http._HTTP, "command", side_effect=AssertionError("No new authored command")), self.assertRaises(RuntimeError):
                http.run_company_http_inputs(self.path, "http://not-used.invalid")
        self.assertFalse((self.work / "http-journal.secret.json").exists())

    def test_stale_or_missing_current_author_units_refuse_without_touching_original_denied_journal(self):
        from . import test_ricky_company_http as http
        units = self.qualified_input_units()
        self.fixture["preservation"]["setup_old_rows_unchanged"] = True
        self.fixture["native"] = {"uoms": ["Host metre", "Host centimetre"], "qualified_units": units}
        write_private(self.path, self.fixture)
        denied = Journal(self.work)
        row = denied.prepare("input-unit-0", "author", http.EST + "register_unit", {"company": self.fixture["company"], "uom": "Host metre", "dimension": "length", "quantity_precision": 6})
        denied.response(row, status=403, envelope={"error": {"code": "unit_administrator_required"}})
        original = (self.work / "http-journal.secret.json").read_bytes()
        cases = [[], units[:1], [*units, units[0]]]
        for field, value in (("revision", 2), ("revision", 1.0), ("target", {"doctype": "UOM", "name": "Foreign unit"}),
                ("fields", {"symbol": "changed", "dimension": "length", "precision": 6})):
            changed = deepcopy(units); changed[0][field] = value; cases.append(changed)
        for current in cases:
            with self.subTest(current=current), patch.object(http._HTTP, "login") as login, \
                    patch.object(http._HTTP, "call", return_value={"data": {"items": current}}) as read, \
                    patch.object(http._HTTP, "command", side_effect=AssertionError("No new authored command")), self.assertRaises(RuntimeError):
                http.run_company_http_inputs(self.path, "http://not-used.invalid")
            login.assert_called_once_with()
            read.assert_called_once_with(http.EST + "list_units", {"company": self.fixture["company"]})
            self.assertEqual((self.work / "http-journal.secret.json").read_bytes(), original)

    def test_author_unit_selection_uses_exact_current_read_objects_in_fixture_order(self):
        from . import test_ricky_company_http as http
        units = self.qualified_input_units()
        current = deepcopy(units)
        unrelated = self.qualified_input_units()[0]
        self.fixture["native"] = {"uoms": ["Host metre", "Host centimetre"], "qualified_units": units}
        rpc = SimpleNamespace(value=self.fixture, openapi=json.loads((Path(__file__).parents[1] / "api/openapi.json").read_text()),
            call=lambda method, values: {"data": {"items": [current[1], unrelated, current[0]]}})
        selected = http._current_input_units(rpc, units)
        self.assertIs(selected[0], current[0])
        self.assertIs(selected[1], current[1])
        self.assertIn(http.EST + "list_units", http.GETS)
        self.assertNotIn(http.EST + "register_unit", http.POSTS)

    def test_every_authored_input_and_fixed_action_request_matches_actual_openapi_locally(self):
        from jsonschema import Draft202012Validator, FormatChecker
        from . import test_ricky_company_http as http
        openapi = json.loads((Path(__file__).parents[1] / "api/openapi.json").read_text())
        observed = []
        qualified_units = self.qualified_input_units()
        def validate(method, body):
            operation = openapi["paths"]["/api/method/" + method]["post"]
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            Draft202012Validator({"components": openapi["components"], **schema}, format_checker=FormatChecker()).validate(body)
            observed.append(method)
        owner = self
        class LocalShapeRecorder:
            def __init__(self, *args):
                self.value = deepcopy(owner.fixture); self.path = owner.path; self.work = owner.work
                self.openapi = openapi
                self.value["native"] = {"uoms": ["Host metre", "Host centimetre"], "qualified_units": qualified_units, "customer": "Host shape customer"}
                self.value["preservation"]["setup_old_rows_unchanged"] = True
            def login(self):
                pass  # Local shape recording only: no authentication/session claim.
            def command(self, key, method, fields):
                validate(method, {"company": self.value["company"], "operation_id": str(uuid4()), **fields})
                record = {"id": str(uuid4())}
                if method.endswith("upload_document"): return {"document": record, "revision": {"id": "HOST-RAW-REVISION"}}
                if method.endswith("create_conversion"): return {"conversion": record}
                if method.endswith("create_pursuit"): return {"pursuit": record}
                if method.endswith("create_rate"): return {"rate_source": record}
                if method.endswith("create_estimate"): return {"estimate": record}
                if method.endswith("calculate_revision"): return {"revision": {**record, "line_record_ids": [str(uuid4())]}, "calculation": {"id": str(uuid4())}}
                if method.endswith("create_set"): return {"takeoff_set": record}
                if method.endswith("create_measurement"): return {"measurement": record}
                raise AssertionError("Unexpected authored input route")
            def call(self, method, body):
                if method == http.EST + "list_units": return {"data": {"items": list(reversed(deepcopy(qualified_units)))}}
                if method == http.DOC + "get_citation":
                    return {"data": {"id": "a" * 64, "revision_id": "HOST-RAW-REVISION", "page": 1,
                        "source_sha256": "b" * 64, "excerpt_sha256": "c" * 64}}
                if method == http.EST + "get_record": return {"data": {"id": body["record_id"]}}
                raise AssertionError("Unexpected local input lookup")
        with patch.object(http, "_HTTP", LocalShapeRecorder):
            http.run_company_http_inputs(self.path, "http://not-used.invalid")
        self.assertEqual(len(observed), 9)
        self.assertEqual(set(observed), http.POSTS - {http.RICKY + "start_read", http.RICKY + "cancel_run"})
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        from cipher_aec.ricky.aec_contracts import SourceReference
        original = manifest(self.path)
        inputs = original["inputs"]
        self.assertEqual(inputs["units"], qualified_units)
        self.assertIn("Separate native Administrator-service prerequisite", inputs["unit_qualification_basis"])
        citation = inputs["citation"]
        source = SourceReference(citation["id"], citation["revision_id"], citation["page"], citation["excerpt_sha256"], citation["source_sha256"])
        for action, arguments in (("aec.pursuit.lookup", {}), ("aec.estimate.recompute", {"revision_id": inputs["revisions"][0]["id"]}),
                ("aec.estimate.compare", {"left_revision_id": inputs["revisions"][0]["id"], "right_revision_id": inputs["revisions"][1]["id"]}),
                ("aec.quantity.convert", {"source_kind": "estimate-line", "source_id": inputs["line_record"], "target_unit_id": inputs["units"][1]["id"]})):
            selected = DeterministicReadRequest(inputs["pursuit"]["id"], action, json.dumps(arguments, sort_keys=True, separators=(",", ":")), (source,), (inputs["measurement"]["id"],))
            validate(http.RICKY + "start_read", {"company": original["company"], "request": selected.binding(), "operation_id": str(uuid4())})
        validate(http.RICKY + "cancel_run", {"company": original["company"], "run_id": str(uuid4()), "operation_id": str(uuid4())})


if __name__ == "__main__": unittest.main()
