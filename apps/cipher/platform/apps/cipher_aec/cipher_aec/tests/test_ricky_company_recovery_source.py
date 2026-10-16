"""Host-only recovery fixture contracts; no native/runtime qualification."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import ricky_company_acceptance_support as support
from . import test_ricky_company_http as http

R12_CASES = ("interrupted-read-r12", "recovery-authority-r12", "quarantine-r12")


class CompanyRecoveryFixtureSourceTests(unittest.TestCase):
    def setUp(self):
        from .test_ricky_company_acceptance_source import CompanyAcceptanceSourceTests
        self.fixture = CompanyAcceptanceSourceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_new_cases_have_distinct_literal_names_without_replacing_predecessors(self):
        for case in R12_CASES:
            self.assertIn(case, support.CASES)
            self.assertNotIn(case, support.CORRECTED_CASES)
        self.assertIn("claim-race-r11", support.CASES)

    def test_quarantine_denial_validates_actual_wire_schema_and_retains_new_denied_uuid(self):
        f = self.fixture
        intent = f.admission()
        original = deepcopy(support.Journal(f.work).rows)
        rpc = http._HTTP(f.path, "http://localhost"); rpc.role = "author"; rpc.csrf = "HOST_ONLY"
        envelope = f.wire_envelope(intent, error="execution_quarantined")
        payload = {key: value for key, value in intent["payload"].items() if key != "operation_id"}
        with patch.object(rpc, "_wire", return_value=(503, {"message": envelope}, 0)):
            self.assertIs(rpc.call(http.RICKY + "start_read", payload,
                key="quarantine-admission-r12", expected={"execution_quarantined"}), envelope)
        rows = support.Journal(f.work).rows
        self.assertEqual(rows[:len(original)], original)
        self.assertNotEqual(rows[-1]["operation_id"], intent["operation_id"])
        self.assertEqual(rows[-1]["attempts"][-1]["status"], 503)

    def test_new_success_cases_keep_exact_lookup_expectation(self):
        pursuit = {"title": "Exact stored pursuit", "id": "host-only"}
        result = {"title": pursuit["title"], "record_digest": support.sha(pursuit)}
        for case in (R12_CASES[0], R12_CASES[2]):
            support.verify_read_value({"pursuit": pursuit}, case, result)
            with self.assertRaises(AssertionError):
                support.verify_read_value({"pursuit": pursuit}, case, {**result, "record_digest": "0" * 64})


class RecoveryCheckpointSourceTests(unittest.TestCase):
    def setUp(self):
        from .test_ricky_company_acceptance_source import CompanyAcceptanceSourceTests
        from . import ricky_company_recovery_acceptance as recovery
        self.r = recovery
        self.f = CompanyAcceptanceSourceTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.value, self.path = self.f.fixture, self.f.path
        self.baseline = {"fixture_id": self.value["fixture_id"], "older_cases": [], "older_terminal": {},
            "site_terminal_payloads": {}, "original_config": {"present": False, "value": None}}
        self.baseline_path = self.f.work / "recovery-r12-baseline.secret.json"
        self.write_declaration()
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.run = {"id": "host-run", "status": "executing", "lease_token": 1,
            "lease_expires_at": (self.now + timedelta(seconds=180)).isoformat(),
            "deadline": (self.now + timedelta(seconds=300)).isoformat(), "company": "Exact Company",
            "authority": {"session_reference": "ORIGINAL"}, "tool_calls": 1, "context": [{"tool": "original"}],
            "result": None, "result_digest": None, "error": None, "generations": 0, "proposal_ids": []}
        self.children = {"step": {"old-step": '{"value":1.0}'}, "invocation": {"old-call": '{"value":1}'},
            "artifact": {"old-artifact": "EXACT_BYTES"}, "delegation": {"original-delegation": "ORIGINAL"}, "proposal": {}}
        self.rollbacks = []
        self.frappe = SimpleNamespace(conf={}, db=SimpleNamespace(rollback=lambda: self.rollbacks.append(True)))
        self.governance = SimpleNamespace(require_effects_enabled=lambda: None, execution_quarantined=lambda: True)

    def write_declaration(self):
        import hashlib
        support.write_private(self.baseline_path, self.baseline)
        self.value["stages"]["recovery_r12_declaration"] = {"schema": "cipher.fixture.ricky.company.recovery.v1",
            "fixture_id": self.value["fixture_id"], "cases": dict(zip(R12_CASES, ("successful-invocation", "claimed", "queued"))),
            "baseline_file": self.baseline_path.name, "baseline_sha256": hashlib.sha256(self.baseline_path.read_bytes()).hexdigest()}
        self.value["stages"].setdefault("recovery_r12", {})
        support.write_private(self.path, self.value)

    def phase(self, case=R12_CASES[0], status="checkpoint_captured"):
        phase = {"status": status, "events": [], "checkpoint": {"run": deepcopy(self.run), "children": deepcopy(self.children)}}
        self.value["stages"]["recovery_r12"][case] = phase
        return phase

    def test_exact_baseline_binding_and_serial_admission_refuse_before_login(self):
        support.recovery_case(self.value, R12_CASES[0], admission=True)
        for case in R12_CASES[1:]:
            with self.assertRaisesRegex(ValueError, "Finish each"):
                support.recovery_case(self.value, case, admission=True)
        self.phase(status="passed")
        support.recovery_case(self.value, R12_CASES[1], admission=True)
        self.baseline["fixture_id"] = "foreign"
        self.write_declaration()
        with patch.object(http._HTTP, "login", side_effect=AssertionError("No login allowed")) as login:
            with self.assertRaisesRegex(ValueError, "exact fixture"):
                http.start_company_http_case(self.path, R12_CASES[0], "http://not-used.invalid")
        login.assert_not_called()

    def test_tampered_baseline_bytes_and_changed_literal_case_refuse(self):
        self.baseline_path.write_text(self.baseline_path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "baseline bytes changed"):
            support.recovery_case(self.value, R12_CASES[0])
        self.write_declaration()
        self.value["stages"]["recovery_r12_declaration"]["cases"][R12_CASES[0]] = "arbitrary-action"
        with self.assertRaisesRegex(ValueError, "exact three"):
            support.recovery_case(self.value, R12_CASES[0])

    def test_existing_author_cookie_is_required_before_any_login_or_start(self):
        with patch.object(http._HTTP, "login", side_effect=AssertionError("No replacement login")) as login:
            with self.assertRaisesRegex(RuntimeError, "existing current author cookie"):
                http.start_company_http_case(self.path, R12_CASES[0], "http://not-used.invalid")
        login.assert_not_called()

    def test_real_window_observes_expiry_and_remaining_delegation_without_mutation(self):
        before = deepcopy(self.run)
        window = self.r._window(self.run, before, self.now, expired=False)
        self.assertEqual(window["seconds_until_lease"], 180)
        self.assertEqual(window["seconds_until_deadline"], 300)
        with self.assertRaisesRegex(RuntimeError, "not expired"):
            self.r._window(self.run, before, self.now + timedelta(seconds=179), expired=True)
        ready = self.r._window(self.run, before, self.now + timedelta(seconds=181), expired=True)
        self.assertEqual(ready["seconds_until_deadline"], 119)
        self.assertEqual(self.run, before)
        for elapsed in (271, 301):
            with self.subTest(elapsed=elapsed), self.assertRaisesRegex(RuntimeError, "Insufficient real"):
                self.r._window(self.run, before, self.now + timedelta(seconds=elapsed), expired=True)
        for field in ("deadline", "lease_expires_at", "lease_token"):
            changed = {**self.run, field: 9 if field == "lease_token" else self.now.isoformat()}
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, "lease/deadline changed"):
                self.r._window(changed, before, self.now, expired=False)

    def test_dispatch_refuses_unexpired_lease_and_persists_natural_ready_observation(self):
        phase = self.phase()
        with patch.dict("sys.modules", {"frappe": self.frappe, "cipher_aec.governance.context": self.governance}), \
                patch.object(self.r.native, "_fixture", return_value=self.value), \
                patch.object(self.r.native, "_run", return_value=self.run), \
                patch.object(self.r, "_payloads", return_value=self.children), \
                patch.object(self.r, "_unchanged"), patch.object(self.r, "_only_active") as active, \
                patch("cipher_aec.ricky.contracts.utcnow", return_value=self.now):
            with self.assertRaisesRegex(RuntimeError, "not expired"):
                self.r.prepare_company_recovery_dispatch(self.path, R12_CASES[0])
            self.assertEqual(phase["status"], "checkpoint_captured")
            self.assertEqual(phase["events"], [])
            with patch("cipher_aec.ricky.contracts.utcnow", return_value=self.now + timedelta(seconds=181)):
                ready = self.r.prepare_company_recovery_dispatch(self.path, R12_CASES[0])
            active.assert_called_with("host-run")
        self.assertEqual(ready["status"], "dispatch_ready")
        self.assertEqual(ready["events"][-1]["window"]["seconds_until_deadline"], 119)
        self.assertEqual(self.run, phase["checkpoint"]["run"])

    def test_sitewide_preflight_refuses_any_other_company_or_project_active_run(self):
        from cipher_aec.ricky.storage import FrappeStore
        with patch.object(FrappeStore, "__init__", return_value=None), patch.object(FrappeStore, "find") as find:
            for rows in ([{"id": "host-run"}, {"id": "foreign-project-run"}], [], [{"id": "foreign-company-run"}]):
                find.return_value = rows
                with self.subTest(rows=rows), self.assertRaises(RuntimeError): self.r._only_active("host-run")
            find.return_value = [{"id": "host-run"}]
            self.r._only_active("host-run")
            find.return_value = []
            self.r._only_active()

    def test_native_payload_snapshot_retains_exact_json_text_and_older_project_rows(self):
        def sql(query, args=None):
            if "WHERE run_id" in query: return [("old", '{"amount":1.0}')]
            return [("old-project", None, '{"scope_type":"Project", "amount":1.0}'),
                ("new-run", "new-run", '{"scope_type":"Company"}'), ("new-child", "new-run", '{}')]
        self.frappe.db.sql = sql
        with patch.dict("sys.modules", {"frappe": self.frappe, "cipher_aec.governance.context": self.governance}):
            self.assertEqual(self.r._payloads("old")["invocation"]["old"], '{"amount":1.0}')
            snapshot = self.r._site_payloads(["new-run"])
        self.assertEqual(set(snapshot["run"]), {"old-project"})
        self.assertIn('"amount":1.0', snapshot["run"]["old-project"]["data_json"])

    def test_older_project_or_receipt_byte_drift_is_detected(self):
        self.baseline.update(site_terminal_payloads={"run": {"project": "ORIGINAL"}}, older_cases=[], older_terminal={})
        self.write_declaration()
        with patch.object(self.r, "_terminal_snapshot", return_value={}), \
                patch.object(self.r, "_site_payloads", return_value={"run": {"project": "CHANGED"}}):
            with self.assertRaisesRegex(AssertionError, "older terminal"):
                self.r._unchanged(self.value)

    def test_later_case_preserves_earlier_r12_terminal_children_intent_and_start_receipt(self):
        intent = {"run_id": "earlier-r12", "operation_id": "original-operation"}
        receipt = {"result_json": '{"queued":true}', "result_hash": "ORIGINAL"}
        phase = self.phase(status="passed")
        phase.update(terminal_payloads=deepcopy(self.children), terminal_intent=deepcopy(intent), start_receipt=deepcopy(receipt))
        with patch.object(self.r, "_site_payloads", return_value={}), patch.object(self.r, "_terminal_snapshot", return_value={}), \
                patch.object(self.r, "saved_intent", return_value=intent), patch.object(self.r, "_payloads", return_value=self.children), \
                patch.object(self.r.native, "_receipt", return_value=({}, receipt)):
            self.r._unchanged(self.value)
            changes = (("terminal_payloads", {"artifact": {"old-artifact": "CHANGED"}}),
                ("terminal_intent", {**intent, "operation_id": "REPLACED"}),
                ("start_receipt", {**receipt, "result_json": '{"queued":1}'}))
            for key, changed in changes:
                before = phase[key]; phase[key] = changed
                with self.subTest(key=key), self.assertRaisesRegex(AssertionError, "earlier completed R12"):
                    self.r._unchanged(self.value)
                phase[key] = before

    def test_quarantine_denied_journal_has_no_native_run_or_receipt_and_is_never_repurposed(self):
        row = support.Journal(self.f.work).prepare("quarantine-admission-r12", "author", http.RICKY + "start_read",
            {"company": self.value["company"], "request": {"fixed": True}})
        journal = support.Journal(self.f.work)
        journal.response(journal.rows[0], status=503, envelope={"error": {"code": "execution_quarantined"}})
        intent = {"operation_id": "a-distinct-start", "payload": {"company": self.value["company"],
            "request": {"fixed": True}, "operation_id": "a-distinct-start"}}
        self.frappe.db.exists = lambda *args: False
        self.frappe.db.count = lambda *args: 0
        with patch.dict("sys.modules", {"frappe": self.frappe}), patch.object(self.r, "saved_intent", return_value=intent):
            self.assertEqual(self.r._denied_admission(self.value), {"operation_id": row["operation_id"], "no_receipt_or_run": True})
            self.frappe.db.exists = lambda *args: True
            with self.assertRaisesRegex(AssertionError, "created a receipt or Run"):
                self.r._denied_admission(self.value)
            self.frappe.db.exists = lambda *args: False
            self.frappe.db.count = lambda *args: 1
            with self.assertRaisesRegex(AssertionError, "created a receipt or Run"):
                self.r._denied_admission(self.value)
            self.frappe.db.count = lambda *args: 0
            intent["operation_id"] = row["operation_id"]
            with self.assertRaisesRegex(AssertionError, "distinct exact original denied"):
                self.r._denied_admission(self.value)

    def test_checkpoint_effect_cannot_run_twice_or_rewrite_failed_phase(self):
        for status in ("entered_checkpoint", "checkpoint_captured", "passed", "failed"):
            self.phase(status=status)
            with self.subTest(status=status), patch.dict("sys.modules", {"cipher_aec.governance.context": self.governance}), \
                    patch.object(self.r.native, "_fixture", return_value=self.value), \
                    patch("cipher_aec.ricky.company_service.build_service") as build:
                with self.assertRaisesRegex(RuntimeError, "one-shot"):
                    self.r.checkpoint_company_recovery_case(self.path, R12_CASES[0])
                build.assert_not_called()

    def test_interrupted_transition_preserves_original_binding_and_requires_new_fencing_token(self):
        after = {**deepcopy(self.run), "status": "succeeded", "lease_token": 2,
            "lease_expires_at": (self.now + timedelta(seconds=361)).isoformat(), "result": {"exact": 1}, "result_digest": "digest",
            "completed_at": (self.now + timedelta(seconds=181)).isoformat()}
        self.r._verify_transition(R12_CASES[0], self.run, after)
        for changed in ({"lease_token": 1}, {"authority": {"session_reference": "REPLACED"}}, {"tool_calls": 2}, {"status": "failed"}):
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                self.r._verify_transition(R12_CASES[0], self.run, {**after, **changed})

    def test_failed_verification_retains_observation_and_error_and_cannot_be_relabelled(self):
        self.phase(status="dispatch_ready")
        terminal = {**self.run, "status": "succeeded", "lease_token": 1}
        with patch.dict("sys.modules", {"frappe": self.frappe, "cipher_aec.governance.context": self.governance}), \
                patch.object(self.r.native, "_fixture", return_value=self.value), \
                patch.object(self.r.native, "_run", return_value=terminal), \
                patch.object(self.r, "_payloads", return_value=self.children):
            with self.assertRaisesRegex(AssertionError, "fencing transition"):
                self.r.verify_company_recovery_case(self.path, R12_CASES[0])
            failed = deepcopy(self.value["stages"]["recovery_r12"][R12_CASES[0]])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["events"][0]["terminal_observation"]["run"], terminal)
            self.assertIn("error", failed["events"][-1])
            with self.assertRaisesRegex(RuntimeError, "never turn a failed"):
                self.r.verify_company_recovery_case(self.path, R12_CASES[0])
            self.assertEqual(self.value["stages"]["recovery_r12"][R12_CASES[0]], failed)

    def test_quarantine_requires_native_and_http_proof_and_exact_config_restoration(self):
        case = R12_CASES[2]
        self.run.update(status="queued", lease_token=0, lease_expires_at=None, tool_calls=0)
        phase = self.phase(case)
        with patch.dict("sys.modules", {"frappe": self.frappe, "cipher_aec.governance.context": self.governance}), \
                patch.object(self.r.native, "_fixture", return_value=self.value), \
                patch.object(self.r.native, "_run", return_value=self.run), \
                patch.object(self.r, "_payloads", return_value=self.children), \
                patch.object(self.r, "_unchanged"), patch.object(self.r, "_only_active"), \
                patch("cipher_aec.ricky.contracts.utcnow", return_value=self.now):
            with self.assertRaisesRegex(RuntimeError, "Both fresh native"):
                self.r.prepare_company_recovery_dispatch(self.path, case)
            phase.update(quarantine_native={"proof": True}, quarantine_http={"proof": True})
            self.frappe.conf["cipher_execution_quarantined"] = False
            with self.assertRaisesRegex(AssertionError, "key/value/presence"):
                self.r.prepare_company_recovery_dispatch(self.path, case)
            del self.frappe.conf["cipher_execution_quarantined"]
            self.assertEqual(self.r.prepare_company_recovery_dispatch(self.path, case)["status"], "dispatch_ready")

    def test_native_quarantine_uses_supported_guards_without_mutating_configuration(self):
        from cipher_aec.api.errors import DomainError
        case = R12_CASES[2]
        self.run.update(status="queued", lease_token=0, lease_expires_at=None, tool_calls=0)
        phase = self.phase(case)
        self.frappe.conf["cipher_execution_quarantined"] = 1
        skipped = {"status": "skipped", "code": "execution_quarantined"}
        service = SimpleNamespace(process=lambda run_id: (_ for _ in ()).throw(DomainError("execution_quarantined", "fixture", 503)))
        with patch.dict("sys.modules", {"frappe": self.frappe, "cipher_aec.governance.context": self.governance}), \
                patch.object(self.r.native, "_fixture", return_value=self.value), \
                patch.object(self.r.native, "_run", return_value=self.run), \
                patch.object(self.r, "_payloads", return_value=self.children), \
                patch.object(self.r, "_unchanged"), patch.object(self.r, "_only_active"), \
                patch("cipher_aec.ricky.company_service.build_service", return_value=service), \
                patch("cipher_aec.ricky.worker.process_run", return_value=skipped), \
                patch("cipher_aec.ricky.worker.recover_pending", return_value=skipped):
            result = self.r.verify_company_quarantine_native(self.path)
        self.assertEqual(result["before_sha256"], result["after_sha256"])
        self.assertEqual(self.frappe.conf, {"cipher_execution_quarantined": 1})
        self.assertEqual(phase["status"], "checkpoint_captured")

    def test_readonly_checkpoint_capture_reconciles_commit_without_reclaiming_or_reinvoking(self):
        self.value["inputs"] = {"pursuit": {"title": "Exact pursuit"}}
        output = {"title": "Exact pursuit", "record_digest": support.sha(self.value["inputs"]["pursuit"])}
        phase = self.phase(status="entered_checkpoint"); del phase["checkpoint"]
        service = SimpleNamespace(_successful_invocation=lambda run: {"output": output})
        with patch.dict("sys.modules", {"frappe": self.frappe}), \
                patch.object(self.r.native, "_fixture", return_value=self.value), \
                patch.object(self.r.native, "_run", return_value=self.run), \
                patch.object(self.r, "_payloads", return_value=self.children), \
                patch.object(self.r, "_unchanged"), patch.object(self.r, "_only_active"), \
                patch("cipher_aec.ricky.company_service.build_service", return_value=service), \
                patch("cipher_aec.ricky.company_service.CompanyExecution") as execution, \
                patch("cipher_aec.ricky.contracts.utcnow", return_value=self.now):
            captured = self.r.capture_company_recovery_checkpoint(self.path, R12_CASES[0])
            execution.assert_not_called()
            self.assertEqual(captured["checkpoint"], {"run": self.run, "children": self.children})
            self.assertEqual(captured["status"], "checkpoint_captured")
            self.assertIn("no OS-kill", captured["events"][-1]["qualification"])
            changed = deepcopy(self.children); changed["invocation"]["old-call"] = '{"value":1.0}'
            with patch.object(self.r, "_payloads", return_value=changed), self.assertRaisesRegex(AssertionError, "payload changed"):
                self.r.capture_company_recovery_checkpoint(self.path, R12_CASES[0])

    def test_authority_outage_always_rolls_back_and_restores_exact_original_after_worker_error(self):
        case = R12_CASES[1]
        self.run.update(status="retrieving", tool_calls=0)
        phase = self.phase(case)
        original = {"active": 1, "fields": {"active": self.r.native._native_scalar(1)}}
        calls = []
        with patch.dict("sys.modules", {"frappe": self.frappe}), \
                patch.object(self.r.native, "_fixture", return_value=self.value), \
                patch.object(self.r.native, "_run", return_value=self.run), patch.object(self.r, "_only_active"), \
                patch.object(self.r.native, "_capture_duty_outage", return_value=original), \
                patch.object(self.r.native, "_duty", side_effect=lambda value, ability, active, saved: calls.append((active, deepcopy(saved)))), \
                patch.object(self.r.native, "_independent_duty_readback") as readback, \
                patch("cipher_aec.ricky.worker.process_run", side_effect=RuntimeError("Explicit host worker failure")) as process, \
                patch("cipher_aec.ricky.contracts.utcnow", return_value=self.now + timedelta(seconds=181)):
            with self.assertRaisesRegex(RuntimeError, "host worker failure"):
                self.r.run_company_recovery_authority_refusal(self.path)
        self.assertEqual(calls, [(0, original), (1, original)])
        self.assertEqual(readback.call_args_list[-1].args[-1], original)
        self.assertTrue(self.rollbacks)
        self.assertEqual(phase["status"], "failed")
        self.assertEqual(phase["events"][-2]["error"]["error_type"], "RuntimeError")
        self.assertTrue(phase["events"][-1]["exact_duty_restored"])
        process.assert_called_once_with("host-run")

    def test_quarantine_measured_http_denial_keeps_queued_receipt_and_distinct_command(self):
        case = R12_CASES[2]
        self.run.update(status="queued", lease_token=0, lease_expires_at=None, tool_calls=0)
        phase = self.phase(case); phase["quarantine_native"] = {"proof": True}
        (self.f.work / "author.cookies.secret").write_text("HOST_ONLY")
        intent = {"run_id": "target", "operation_id": "start-operation", "start": {"id": "target", "status": "queued"},
            "payload": {"company": self.value["company"], "request": {"fixed": True}, "operation_id": "start-operation"}}
        calls = []
        rpc = SimpleNamespace(value=self.value, work=self.f.work, login=lambda: calls.append("existing-cookie-login"))
        def call(method, fields, **kwargs):
            calls.append((method, deepcopy(fields), kwargs))
            if kwargs.get("expected"): return {"request_id": "actual503request", "error": {"code": "execution_quarantined"}}
            if kwargs.get("key"): return {"data": {**intent["start"], "operation": {"replayed": True}}}
            return {"data": intent["start"]}
        rpc.call = call
        with patch.object(http, "_HTTP", return_value=rpc), patch.object(self.r, "saved_intent", return_value=intent):
            result = self.r.verify_company_quarantine_http(self.path, "http://not-used.invalid")
        commands = [row for row in calls if isinstance(row, tuple) and row[2].get("key")]
        self.assertEqual([row[2]["key"] for row in commands], ["start-quarantine-r12", "quarantine-admission-r12"])
        self.assertEqual(commands[-1][2]["expected"], {"execution_quarantined"})
        self.assertEqual(result["quarantine_http"]["denial_request_id"], "actual503request")
        self.assertEqual(phase["status"], "checkpoint_captured")

    def test_restore_web_proof_requires_new_source_free_receipt_and_preserves_full_success_dto(self):
        case = R12_CASES[2]
        phase = self.phase(case, "passed")
        (self.f.work / "author.cookies.secret").write_text("HOST_ONLY")
        current = {"id": "target", "status": "succeeded", "result": {"exact": 1}}
        intent = {"run_id": "target"}
        commands = []
        def call(method, fields, **kwargs):
            if kwargs.get("key"):
                self.assertEqual(method, http.RICKY + "cancel_run")
                self.assertEqual(kwargs["key"], "stop-quarantine-r12")
                commands.append(method)
                return {"data": {"id": "target", "status": "succeeded", "operation": {"id": "new-stop", "replayed": len(commands) > 1}}}
            return {"data": deepcopy(current)}
        rpc = SimpleNamespace(value=self.value, work=self.f.work, login=lambda: None, call=call)
        with patch.object(http, "_HTTP", return_value=rpc), patch.object(self.r, "saved_intent", return_value=intent):
            result = self.r.verify_company_quarantine_restored_http(self.path, "http://not-used.invalid")
        self.assertEqual(len(commands), 2)
        self.assertTrue(result["restored_http"]["terminal_dto_unchanged"])
        self.assertFalse(result["restored_http"]["first_stop"]["operation"]["replayed"])
        self.assertEqual(phase["status"], "passed")



class CompanyCheckpointEngineSourceTests(unittest.TestCase):
    """Exercise production engine methods with existing explicit host fixtures."""
    def fixture(self):
        from .test_ricky_company_service import CompanyStrategyTests
        f = CompanyStrategyTests(); f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def test_successful_checkpoint_resume_reuses_immutable_children_and_original_selection(self):
        from cipher_aec.ricky.company_service import CompanyExecution
        f = self.fixture(); run = f.start()
        _, token = f.service.claim(run["id"])
        output = CompanyExecution(f.service, run["id"], token).invoke("aec.pursuit.lookup", {}, "selected-deterministic-read")
        checkpoint = f.store.get("run", run["id"])
        children = {kind: deepcopy(f.store.find(kind, {"run_id": run["id"]})) for kind in ("step", "invocation", "artifact")}
        self.assertEqual(checkpoint["status"], "executing")
        self.assertIsNone(checkpoint["result"])
        # Only this host unit fixture clock advances; native procedure uses real elapsed time.
        f.now += timedelta(seconds=181)
        with patch.object(f.service.registry, "execute", side_effect=AssertionError("A committed read must not execute twice")):
            f.service.process(run["id"])
        terminal = f.store.get("run", run["id"])
        self.assertEqual(terminal["status"], "succeeded")
        self.assertEqual(terminal["lease_token"], 2)
        self.assertEqual(terminal["result"], output)
        self.assertEqual(terminal["authority"], run["authority"])
        for kind, rows in children.items(): self.assertEqual(f.store.find(kind, {"run_id": run["id"]}), rows)

    def test_expired_claim_recovery_rechecks_original_session_before_any_invocation(self):
        f = self.fixture(); run = f.start(); f.service.claim(run["id"])
        f.now += timedelta(seconds=181); f.boundary.session = False
        f.service.process(run["id"])
        terminal = f.store.get("run", run["id"])
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["error"]["code"], "session_revoked")
        self.assertEqual(terminal["lease_token"], 1)
        self.assertEqual(f.store.find("invocation", {"run_id": run["id"]}), [])
