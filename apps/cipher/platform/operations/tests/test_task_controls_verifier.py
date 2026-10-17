"""Host guard/journal/schema checks; these do not qualify native Task behavior."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest


OPERATIONS = Path(__file__).parents[1]
sys.path.insert(0, str(OPERATIONS))
try:
    spec = importlib.util.spec_from_file_location("task_controls_verifier_under_test", OPERATIONS / "verify_task_controls.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
finally:
    sys.path.pop(0)


class TaskControlVerifierTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        fixture = {"schema": "cipher.local-trial.v1", "site_mode": "synthetic", "company": "C", "project": "P", "users": {
            role: {"user": role + "@cipher.example", "person": "PERSON-" + ("PRIMARY" if role == "alias" else role.upper())}
            for role in ("primary", "alias", "reviewer", "outsider")}}
        self.fixture = root / "fixture.json"
        self.fixture.write_text(json.dumps(fixture), encoding="utf-8")
        self.legacy_task = {"id": "TASK-OLD", "project": "P", "subject": "Original", "status": "Open", "description": "", "version": "2026-10-17 01:02:03.000000"}
        historical = {"schema": "cipher.local-trial.http-state.v1", "fixture_digest": verifier.digest(fixture), "commands": {"task-create": {
            "status": "returned", "payload": {"operation_id": "83dafcd3-76f0-4d06-bf0c-c8f7cfcc6ae9"}, "result": {"task": self.legacy_task}}}}
        self.historical = root / "historical.json.state.json"
        self.historical.write_text(json.dumps(historical), encoding="utf-8")
        self.args = SimpleNamespace(fixture=self.fixture, historical_state=self.historical, schema=verifier.DEFAULT_SCHEMA,
            base_url="http://127.0.0.1:18900", host_header="cipher.localhost", output=root / "task-http.json", state=None,
            resume=False, phase="journey", assignee_role="reviewer", revoked_ability=None)

    def current_task(self):
        return {"id": "TASK-NEW", "project": "P", "subject": "New", "description": "", "status": "Open", "version": "a" * 64,
            "assignees": [], "assignment_conflict": False}

    def assign_payload(self):
        return {"company": "C", "project": "P", "task": "TASK-NEW", "assignee_person": "PERSON-REVIEWER", "expected_version": "a" * 64}

    def test_uncertain_assignment_persists_intent_before_http_and_resumes_same_uuid(self):
        runner = verifier.TaskVerifier(self.args)
        def uncertain(route, payload, **kwargs):
            disk = json.loads(runner.state_path.read_text())["commands"]["assignment"]
            self.assertEqual(disk["payload"], payload)
            self.assertEqual(disk["status"], "intent")
            raise verifier.CheckFailure("Synthetic uncertain HTTP result")
        runner.clients["primary"] = SimpleNamespace(api=uncertain)
        with self.assertRaises(verifier.CheckFailure):
            runner.command("assignment", "primary", "assign_task", self.assign_payload())
        original = deepcopy(runner.state["commands"]["assignment"]["payload"])
        self.args.resume = True
        resumed = verifier.TaskVerifier(self.args)
        def success(route, payload, **kwargs):
            self.assertEqual(payload, original)
            self.assertEqual(kwargs["operation"], original["operation_id"])
            return {"task": self.current_task(), "project_version": "project-version", "operation": {"id": original["operation_id"], "status": "succeeded", "replayed": True}}
        resumed.clients["primary"] = SimpleNamespace(api=success)
        changed = {**self.assign_payload(), "assignee_person": "ANOTHER-PERSON", "expected_version": "b" * 64}
        resumed.command("assignment", "primary", "assign_task", changed)
        self.assertEqual(resumed.state["commands"]["assignment"]["payload"], original)

    def test_unknown_task_creation_keeps_its_original_operation_and_never_replaces_it(self):
        runner = verifier.TaskVerifier(self.args)
        runner.clients["primary"] = SimpleNamespace(api=lambda *args, **kwargs: (_ for _ in ()).throw(verifier.CheckFailure("Synthetic timeout")))
        payload = {"company": "C", "project": "P", "expected_version": "project-original", "subject": "Dedicated original Task"}
        with self.assertRaises(verifier.CheckFailure):
            runner.command("create", "primary", "create_task", payload)
        operation = runner.state["commands"]["create"]["payload"]["operation_id"]
        self.args.resume = True
        resumed = verifier.TaskVerifier(self.args)
        self.assertEqual(resumed.state["commands"]["create"]["payload"]["operation_id"], operation)
        self.assertEqual(resumed.state["commands"]["create"]["payload"]["expected_version"], "project-original")
        self.assertEqual(len(resumed.state["commands"]), 1)

    def test_historical_task_schema_remains_permissive_but_current_task_is_strict(self):
        runner = verifier.TaskVerifier(self.args)
        self.assertEqual(runner.validate("Task", self.legacy_task), self.legacy_task)
        with self.assertRaises(verifier.CheckFailure):
            runner.validate("CurrentTask", self.legacy_task)
        runner.validate("CurrentTask", self.current_task())

    def test_fresh_journey_without_history_reports_it_unexercised_never_passed(self):
        self.args.historical_state = None
        runner = verifier.TaskVerifier(self.args)
        self.assertIsNone(runner.state["historical"])
        self.assertIsNone(runner.report["historical_source"])
        for method in ("authenticate", "preflight", "controls", "readback", "receipts"):
            setattr(runner, method, lambda: "Host admission/journal test only")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run(), 0)
        report = json.loads(self.args.output.read_text())
        historical = [check for check in report["checks"] if "pre-upgrade historical" in check["check"]]
        self.assertEqual(historical, [{"check": "pre-upgrade historical immutable Task receipt schema", "status": "not_exercised",
            "detail": "not exercised: no pre-upgrade records in this fresh integration site"}])
        self.assertNotIn("historical_source_unchanged", report)

    def test_provided_history_requires_exact_original_receipt_and_preserves_bytes(self):
        original = self.historical.read_bytes()
        runner = verifier.TaskVerifier(self.args)
        calls = []
        def get(role, route, payload, schema=None, expected=(200,)):
            calls.append((role, payload["operation_id"], schema))
            return {"task": deepcopy(self.legacy_task)}
        runner.get = get
        result = runner.historical_receipts()
        self.assertEqual(result["historical_assignment_fields_present"], [])
        self.assertEqual([item[0] for item in calls], ["primary", "alias"])
        self.assertTrue(all(item[2] == "CreateTaskResponse" for item in calls))
        runner.get = lambda *args, **kwargs: {"task": {**self.legacy_task, "assignees": []}}
        with self.assertRaises(verifier.CheckFailure):
            runner.historical_receipts()
        self.assertEqual(self.historical.read_bytes(), original)

    def test_resume_cannot_attach_history_to_a_fresh_database_run(self):
        self.args.historical_state = None
        runner = verifier.TaskVerifier(self.args)
        raw = runner.state_path.read_bytes()
        self.args.resume = True
        self.args.historical_state = self.historical
        with self.assertRaises(verifier.CheckFailure):
            verifier.TaskVerifier(self.args)
        self.assertEqual(runner.state_path.read_bytes(), raw)

    def test_changed_provided_history_refuses_resume_before_writes(self):
        runner = verifier.TaskVerifier(self.args)
        raw = runner.state_path.read_bytes()
        self.args.resume = True
        self.historical.write_text(self.historical.read_text() + "\n", encoding="utf-8")
        with self.assertRaises(verifier.CheckFailure):
            verifier.TaskVerifier(self.args)
        self.assertEqual(runner.state_path.read_bytes(), raw)

    def test_request_uses_assignee_person_and_explicit_null(self):
        runner = verifier.TaskVerifier(self.args)
        payload = {**self.assign_payload(), "operation_id": "83dafcd3-76f0-4d06-bf0c-c8f7cfcc6ae9", "assignee_person": None}
        runner.validate("AssignTaskRequest", payload)
        payload["person"] = payload.pop("assignee_person")
        with self.assertRaises(verifier.CheckFailure):
            runner.validate("AssignTaskRequest", payload)

    def test_alias_replay_is_journaled_before_call_and_uses_original_operation(self):
        runner = verifier.TaskVerifier(self.args)
        operation = "83dafcd3-76f0-4d06-bf0c-c8f7cfcc6ae9"
        task = self.current_task()
        original = {"role": "primary", "route": "assign_task", "payload": {**self.assign_payload(), "operation_id": operation},
            "expected": [200], "error_code": None, "status": "returned", "result": {"task": task, "project_version": "v", "operation": {"id": operation, "status": "succeeded", "replayed": False}}}
        runner.state["commands"]["assignment"] = original
        runner.persist()
        calls = []
        def replay(route, payload, **kwargs):
            probe = json.loads(runner.state_path.read_text())["probes"]["alias-replay"]
            self.assertEqual(probe["status"], "intent")
            self.assertEqual(probe["payload"], original["payload"])
            self.assertEqual(kwargs["operation"], operation)
            calls.append(route)
            return {"task": task, "project_version": "v", "operation": {"id": operation, "status": "succeeded", "replayed": True}}
        runner.clients["alias"] = SimpleNamespace(api=replay)
        runner.replay("alias-replay", "assignment", "alias")
        runner.replay("alias-replay", "assignment", "alias")
        self.assertEqual(calls, [verifier.CORE + "assign_task"])
        self.assertEqual(runner.state["commands"]["assignment"], original)

    def test_input_and_source_aliases_refuse_before_any_write(self):
        protected = (self.fixture, self.historical, self.args.schema)
        originals = {path: path.read_bytes() for path in protected}
        baseline = deepcopy(self.args)
        for field in ("output", "state"):
            for path in protected:
                with self.subTest(field=field, path=str(path)):
                    args = deepcopy(baseline)
                    setattr(args, field, path)
                    with self.assertRaises(verifier.CheckFailure):
                        verifier.TaskVerifier(args)
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_origin_and_schema_drift_refuse_resume_without_rewriting_state(self):
        schema = self.args.output.parent / "schema.json"
        schema.write_bytes(self.args.schema.read_bytes())
        self.args.schema = schema
        runner = verifier.TaskVerifier(self.args)
        original_state = runner.state_path.read_bytes()
        self.args.resume = True
        self.args.base_url = "http://127.0.0.1:18890"
        with self.assertRaises(verifier.CheckFailure):
            verifier.TaskVerifier(self.args)
        self.args.base_url = "http://127.0.0.1:18900"
        value = json.loads(schema.read_text())
        value["description"] = "Changed schema"
        schema.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(verifier.CheckFailure):
            verifier.TaskVerifier(self.args)
        self.assertEqual(runner.state_path.read_bytes(), original_state)

    def test_readback_forbids_business_commands_replays_and_journal_writes(self):
        runner = verifier.TaskVerifier(self.args)
        raw = runner.state_path.read_bytes()
        self.args.phase = "readback"
        self.args.state = runner.state_path
        reader = verifier.TaskVerifier(self.args)
        for callback in (lambda: reader.command("x", "primary", "assign_task", self.assign_payload()),
            lambda: reader.replay("x", "missing", "primary"), reader.persist):
            with self.assertRaises(verifier.CheckFailure):
                callback()
        self.assertEqual(runner.state_path.read_bytes(), raw)

    def test_non_task_business_routes_are_not_admitted(self):
        runner = verifier.TaskVerifier(self.args)
        with self.assertRaises(verifier.CheckFailure):
            runner.command("unrelated", "primary", "execute_packet", {})
        self.assertEqual(runner.state["commands"], {})

    def test_revoked_phase_requires_explicit_ability_and_completed_source_run(self):
        runner = verifier.TaskVerifier(self.args)
        raw = runner.state_path.read_bytes()
        self.args.phase = "revoked"
        self.args.state = runner.state_path
        with self.assertRaises(verifier.CheckFailure):
            verifier.TaskVerifier(self.args)
        self.args.revoked_ability = "task.assign"
        with self.assertRaises(verifier.CheckFailure):
            verifier.TaskVerifier(self.args)
        self.assertEqual(runner.state_path.read_bytes(), raw)
