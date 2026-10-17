"""HTTP verifier journal tests; native HTTP execution is qualified separately."""
from contextlib import redirect_stdout
import importlib.util
import hashlib
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
    spec = importlib.util.spec_from_file_location("verify_local_trial_under_test", OPERATIONS / "verify_local_trial.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
finally:
    sys.path.pop(0)


class LocalTrialVerifierTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.fixture = root / "fixture.json"
        self.fixture.write_text(json.dumps({"schema": "cipher.local-trial.v1", "site_mode": "synthetic", "company": "C", "project": "P"}))
        self.args = SimpleNamespace(fixture=self.fixture, base_url="http://127.0.0.1:18890", host_header="cipher.localhost",
            output=root / "report.json", resume=False, phase="journey", recovery_source_state=None)

    def recovery_source(self):
        source = self.args.output.parent / "original-trial.json.state.json"
        fixture = json.loads(self.fixture.read_text())
        original = {"schema": "cipher.local-trial.http-state.v1", "fixture_digest": verifier.digest(fixture),
            "origin": "http://127.0.0.1:18890", "run_id": "original-run", "commands": {"original-command": {"payload": {"operation_id": "original-uuid"}}},
            "records": {"task": "TASK-1", "estimate": {"id": "EST-1"}, "proposal": {"id": "PROP-1"}, "engineering": {"distribution": "DIST-1"}}}
        source.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
        return source, source.read_bytes(), original

    def test_unknown_result_preserves_original_uuid_and_payload_for_resume(self):
        runner = verifier.TrialVerifier(self.args)
        observed = []
        def uncertain(route, payload, **kwargs):
            observed.append((route, payload.copy(), kwargs))
            raise verifier.CheckFailure("Synthetic uncertain HTTP result")
        runner.clients["primary"] = SimpleNamespace(api=uncertain)
        with self.assertRaises(verifier.CheckFailure):
            runner.command("create", "primary", "cipher_aec.api.v1.create_task", {"subject": "Original"})
        saved = json.loads(runner.state_path.read_text())["commands"]["create"]
        self.assertEqual(saved["status"], "intent")
        self.args.resume = True
        resumed = verifier.TrialVerifier(self.args)
        def success(route, payload, **kwargs):
            self.assertEqual(payload, saved["payload"])
            self.assertEqual(kwargs["operation"], saved["payload"]["operation_id"])
            return {"task": {"id": "TASK-1"}}
        resumed.clients["primary"] = SimpleNamespace(api=success)
        result = resumed.command("create", "primary", "cipher_aec.api.v1.create_task", {"subject": "Changed after timeout"})
        self.assertEqual(result["task"]["id"], "TASK-1")
        self.assertEqual(resumed.state["commands"]["create"]["status"], "returned")

    def test_returned_command_is_not_repeated_during_resume(self):
        runner = verifier.TrialVerifier(self.args)
        calls = []
        runner.clients["primary"] = SimpleNamespace(api=lambda *args, **kwargs: calls.append(args) or {"id": "SAVED"})
        first = runner.command("save", "primary", "route", {"title": "Original"})
        second = runner.command("save", "primary", "route", {"title": "Other"})
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_nonlocal_origin_is_refused_before_journal_or_login(self):
        self.args.base_url = "http://example.com:18890"
        with self.assertRaises(verifier.CheckFailure):
            verifier.TrialVerifier(self.args)
        self.assertFalse(self.args.output.exists())
        self.assertFalse(self.args.output.with_suffix(".json.state.json").exists())

    def test_recovery_source_is_refused_for_journey_or_resume(self):
        source, raw, _ = self.recovery_source()
        self.args.recovery_source_state = source
        self.args.host_header = "cipher-restore-20261017063628.localhost"
        with self.assertRaises(verifier.CheckFailure):
            verifier.TrialVerifier(self.args)
        self.args.phase = "readback"
        self.args.resume = True
        with self.assertRaises(verifier.CheckFailure):
            verifier.TrialVerifier(self.args)
        self.assertEqual(source.read_bytes(), raw)

    def test_recovery_target_requires_loopback_and_exact_restored_host(self):
        source, raw, _ = self.recovery_source()
        self.args.recovery_source_state = source
        self.args.phase = "readback"
        cases = (("http://127.0.0.1:18901", "cipher.localhost"),
            ("http://127.0.0.1:18901", "cipher-restore-20261017.localhost"),
            ("http://cipher-trial.localhost:18890", "cipher-restore-20261017063628.localhost"),
            ("http://example.com:18901", "cipher-restore-20261017063628.localhost"))
        for origin, host in cases:
            with self.subTest(origin=origin, host=host):
                self.args.base_url, self.args.host_header = origin, host
                with self.assertRaises(verifier.CheckFailure):
                    verifier.TrialVerifier(self.args)
        self.assertEqual(source.read_bytes(), raw)

    def test_recovery_derives_new_readonly_state_and_preserves_original(self):
        source, raw, original = self.recovery_source()
        self.args.recovery_source_state = source
        self.args.phase = "readback"
        self.args.base_url = "http://127.0.0.1:18901"
        self.args.host_header = "cipher-restore-20261017063628.localhost"
        runner = verifier.TrialVerifier(self.args)
        self.assertEqual(runner.state["commands"], {})
        self.assertEqual(runner.state["records"], original["records"])
        self.assertEqual(runner.state["recovery"]["source_state_sha256"], hashlib.sha256(raw).hexdigest())
        with self.assertRaises(verifier.CheckFailure):
            runner.command("forbidden", "primary", "route", {})
        for method in ("authenticate", "task_readback", "source_bytes", "estimate_readback", "proposal_readback", "engineering_readback"):
            setattr(runner, method, lambda: "Readback journal test")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run(), 0)
        self.assertTrue(json.loads(self.args.output.read_text())["recovery_source_unchanged"])
        self.assertEqual(source.read_bytes(), raw)
        self.assertNotEqual(runner.state_path, source)

    def test_normal_readback_still_requires_original_origin(self):
        runner = verifier.TrialVerifier(self.args)
        raw = runner.state_path.read_bytes()
        self.args.phase = "readback"
        self.args.base_url = "http://127.0.0.1:18901"
        with self.assertRaises(verifier.CheckFailure):
            verifier.TrialVerifier(self.args)
        self.assertEqual(runner.state_path.read_bytes(), raw)

    def test_derived_recovery_journal_cannot_resume_business_journey(self):
        source, raw, _ = self.recovery_source()
        self.args.recovery_source_state = source
        self.args.phase = "readback"
        self.args.base_url = "http://127.0.0.1:18901"
        self.args.host_header = "cipher-restore-20261017063628.localhost"
        verifier.TrialVerifier(self.args)
        self.args.recovery_source_state = None
        self.args.resume = True
        self.args.phase = "journey"
        with self.assertRaises(verifier.CheckFailure):
            verifier.TrialVerifier(self.args)
        self.assertEqual(source.read_bytes(), raw)
