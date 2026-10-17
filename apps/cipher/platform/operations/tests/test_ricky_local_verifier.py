"""Operation-journal and native-journey contract tests; no model/site execution."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


OPERATIONS = Path(__file__).parents[1]
sys.path.insert(0, str(OPERATIONS))
try:
    spec = importlib.util.spec_from_file_location("verify_ricky_local_under_test", OPERATIONS / "verify_ricky_local.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
finally:
    sys.path.pop(0)


class RickyLocalVerifierTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.fixture = root / "fixture.json"
        self.fixture.write_text(json.dumps({"schema": "cipher.local-trial.v1", "site_mode": "synthetic", "company": "C", "project": "P",
            "source": {"document": "DOC-1", "citation": {"revision_id": "REV-1", "page": 1, "excerpt_sha256": "e" * 64, "source_sha256": "s" * 64}}}))
        self.args = SimpleNamespace(fixture=self.fixture, base_url="http://127.0.0.1:18890", host_header="cipher.localhost", output=root / "report.json",
            resume=False, phase="journey", poll_seconds=1, poll_timeout=30, answer_question=None, proposal_question=None)

    def runner(self):
        return verifier.RickyVerifier(self.args)

    def prepared_runner(self):
        runner = self.runner()
        runner.state["model"] = {"name": "real-model:latest", "digest": "a" * 64}
        runner.state["source"] = {"citation_id": "citation-1", "document_id": "DOC-1", "revision_id": "REV-1", "page": 1,
            "source_sha256": "s" * 64, "excerpt_sha256": "e" * 64, "excerpt": "Trial labor rate: USD 75.00."}
        return runner

    def model_run(self, runner):
        return {"id": "RUN-1", "company": "C", "project": "P", "status": "succeeded", "answer": "The rate is USD 75.00.", "proposal_ids": [],
            "citations": [deepcopy(runner.state["source"])], "model": {"version": "real-model:latest@sha256:" + "a" * 64,
                "profile_fingerprint": "b" * 64, "prompt_version": "cipher-r0-1"}}

    def test_only_explicit_local_origin_and_bound_host_are_admitted(self):
        for origin, host in (("http://example.invalid:18890", "cipher.localhost"), ("http://user:pass@127.0.0.1:18890", "cipher.localhost"),
                             ("http://127.0.0.1:18890/path", "cipher.localhost"), ("http://127.0.0.1:18890", "other.localhost")):
            with self.subTest(origin=origin, host=host):
                self.args.base_url, self.args.host_header = origin, host
                with self.assertRaises(verifier.CheckFailure):
                    self.runner()
        self.assertFalse(self.args.output.with_suffix(".json.state.json").exists())

    def test_unknown_post_resumes_original_uuid_and_payload_only(self):
        runner = self.runner()
        original = {"company": "C", "project": "P", "question": "What is trial labor rate?"}
        def uncertain(route, payload, **kwargs):
            stored = json.loads(runner.state_path.read_text())["commands"]["start"]
            self.assertEqual(stored["payload"], payload)
            raise OSError("synthetic transport uncertainty")
        runner.clients["primary"] = SimpleNamespace(api=uncertain)
        with self.assertRaises(OSError):
            runner.command("start", "primary", verifier.RICKY + "start_run", original)
        saved = deepcopy(runner.state["commands"]["start"])
        self.args.resume = True
        resumed = self.runner()
        calls = []
        resumed.clients["primary"] = SimpleNamespace(api=lambda route, payload, **kwargs: calls.append((payload, kwargs)) or {"id": "ORIGINAL-RUN"})
        result = resumed.command("start", "primary", verifier.RICKY + "start_run", original)
        self.assertEqual("ORIGINAL-RUN", result["id"])
        self.assertEqual(saved["payload"], calls[0][0])
        self.assertEqual(saved["payload"]["operation_id"], calls[0][1]["operation"])
        with self.assertRaises(verifier.CheckFailure):
            resumed.command("start", "primary", verifier.RICKY + "start_run", {**original, "question": "A changed request"})
        self.assertEqual(1, len(calls))

    def test_returned_intent_is_cached_and_explicit_replay_requires_same_task_receipt(self):
        runner, calls = self.runner(), []
        receipt = {"task": {"id": "TASK-1"}, "operation": {"id": "original-operation", "replayed": False}}
        runner.clients["primary"] = SimpleNamespace(api=lambda *args, **kwargs: calls.append(args) or deepcopy(receipt))
        payload = {"proposal_id": "PROP-1", "proposal_version": 1}
        runner.command("save", "primary", verifier.RICKY + "commit_proposal", payload)
        runner.command("save", "primary", verifier.RICKY + "commit_proposal", payload)
        self.assertEqual(1, len(calls))
        runner.command("save", "primary", verifier.RICKY + "commit_proposal", payload, replay=True)
        self.assertEqual(2, len(calls))
        receipt["task"]["id"] = "TASK-2"
        with self.assertRaises(verifier.CheckFailure):
            runner.command("save", "primary", verifier.RICKY + "commit_proposal", payload, replay=True)

    def test_readback_and_authority_denial_phases_forbid_business_posts(self):
        runner = self.runner()
        for phase in ("readback", "authority-denial"):
            self.args.phase = phase
            with self.assertRaises(verifier.CheckFailure):
                runner.intent("unsafe", "primary", verifier.RICKY + "start_run", {"question": "invalid"})
        self.assertEqual({}, runner.state["commands"])

    def test_route_allowlist_refuses_setup_approval_or_arbitrary_execution(self):
        runner = self.runner()
        for route in ("cipher_aec.api.approvals.decide_packet", "cipher_aec.trial.initialize", "arbitrary.method"):
            with self.assertRaises(verifier.CheckFailure):
                runner.intent("unsafe", "primary", route, {})
        self.assertEqual({}, runner.state["commands"])

    def test_resume_pins_host_fixture_and_original_questions(self):
        runner = self.runner()
        self.args.resume = True
        self.args.host_header = "cipher-integration.localhost"
        with self.assertRaises(verifier.CheckFailure):
            self.runner()
        self.args.host_header = "cipher.localhost"
        self.args.proposal_question = "Changed after unknown outcome"
        with self.assertRaises(verifier.CheckFailure):
            self.runner()
        self.args.proposal_question = None
        self.fixture.write_text(json.dumps({**runner.fixture, "project": "OTHER"}))
        with self.assertRaises(verifier.CheckFailure):
            self.runner()

    def test_run_requires_actual_pinned_identity_and_exact_source(self):
        runner = self.prepared_runner()
        run = self.model_run(runner)
        runner.validate_run(run)
        self.assertEqual("not-exposed-http; separate root native read audit required", runner.report["sampling_readback"])
        for change in ("identity", "source", "failure"):
            changed = deepcopy(run)
            if change == "identity":
                changed["model"]["version"] = "explicit-test-fixture"
            elif change == "source":
                changed["citations"][0]["source_sha256"] = "changed"
            else:
                changed.update(status="failed", error={"code": "upstream_unavailable"})
            with self.assertRaises(verifier.CheckFailure):
                runner.validate_run(changed)

    def test_reported_sampling_is_only_read_from_response_not_invented(self):
        runner = self.prepared_runner()
        run = self.model_run(runner)
        run["model"]["sampling"] = {"temperature": 0, "num_ctx": 8192, "num_predict": 1024, "num_thread": 4}
        runner.validate_run(run)
        self.assertEqual(run["model"]["sampling"], runner.report["sampling"]["RUN-1"])
        run["model"]["sampling"] = {"temperature": 0}
        with self.assertRaises(verifier.CheckFailure):
            runner.validate_run(run)

    def test_failed_provider_run_does_not_start_replacement_or_simulate(self):
        runner = self.prepared_runner()
        calls = []
        def api(route, payload, **kwargs):
            calls.append((route, deepcopy(payload), kwargs))
            if route.endswith("start_run"):
                return {"id": "ORIGINAL-RUN"}
            return {"id": "ORIGINAL-RUN", "status": "failed", "error": {"code": "upstream_unavailable"}}
        runner.clients["primary"] = SimpleNamespace(api=api)
        with self.assertRaises(verifier.CheckFailure):
            runner.complete_run("answer")
        self.assertEqual(1, len([call for call in calls if call[2].get("method") == "POST"]))
        self.assertEqual("ORIGINAL-RUN", runner.state["records"]["answer_run"])

    def test_actual_question_preflight_must_find_exact_source_before_any_start(self):
        runner = self.prepared_runner()
        calls = []
        def api(route, payload=None, **kwargs):
            calls.append((route, payload))
            if route == "project":
                return {"capabilities": ["ricky.run", "document.read", "task.create"]}
            if route.endswith("connection_status"):
                return {"available": True, "adapter_kind": "ollama-local-v1", "cloud_fallback": False,
                        "model": "real-model:latest", "model_digest": "a" * 64}
            return {"items": []}
        runner.clients["primary"] = SimpleNamespace(api=api)
        with self.assertRaises(verifier.CheckFailure):
            runner.readiness()
        self.assertEqual({}, runner.state["commands"])
        self.assertEqual("trial labor rate", calls[-1][1]["query"])

    def test_literal_task_topic_normalization_matches_runtime_contract(self):
        package = OPERATIONS.parents[0] / "apps" / "cipher_aec"
        sys.path.insert(0, str(package))
        try:
            from cipher_aec.ricky.engine import question_keywords
            for question in ("What is trial labor rate?", "Please propose a Task to review the trial labor rate.", "Task regarding the review meeting",
                             "Please create a task to review", "Where are trial draft task review notes?"):
                self.assertEqual(question_keywords(question), verifier.question_keywords(question))
        finally:
            sys.path.pop(0)

    def test_task_pagination_is_bounded_and_repeated_cursors_are_refused(self):
        runner = self.runner()
        runner.clients["primary"] = SimpleNamespace(api=lambda *args, **kwargs: {"items": [{"id": "TASK-1"}], "next_cursor": "repeated"})
        with self.assertRaises(verifier.CheckFailure):
            runner.task_ids()

    def test_complete_journey_has_two_original_runs_and_one_exact_task_effect(self):
        runner = self.prepared_runner()
        runner.state["tasks_before"] = ["ORIGINAL-TASK"]
        calls, runs = [], {}
        proposal = {"id": "PROP-1", "run_id": "RUN-proposal", "version": 1, "status": "proposed",
            "fields": {"subject": "Review authored labor rate", "description": "Review the exact cited synthetic rate."},
            "sources": [deepcopy(runner.state["source"])], "content_digest": "p" * 64, "expires_at": "2099-01-01T00:00:00Z", "receipt": None}
        def api(role, route, payload=None, **kwargs):
            calls.append((role, route, deepcopy(payload), kwargs))
            if role in {"alias", "outsider"}:
                return {"code": "not_found"}
            if route.endswith("start_run"):
                kind = "answer" if payload["question"] == runner.state["questions"]["answer"] else "proposal"
                run = self.model_run(runner)
                run["id"] = "RUN-" + kind
                if kind == "proposal":
                    run.update(status="waiting-for-review", proposal_ids=["PROP-1"])
                runs[run["id"]] = run
                return {"id": run["id"]}
            if route.endswith("get_run"):
                return deepcopy(runs[payload["run_id"]])
            if route.endswith("run_events"):
                tools = ["project.lookup", "document.search"] + (["task.propose"] if payload["run_id"] == "RUN-proposal" else [])
                return {"items": [{"id": "STEP-" + tool, "tool_name": tool, "status": "succeeded"} for tool in tools]}
            if route.endswith("get_proposal"):
                return deepcopy(proposal)
            if route.endswith("commit_proposal"):
                if proposal["receipt"] is None:
                    proposal["receipt"] = {"task": {"id": "NEW-TASK", **proposal["fields"]}, "operation": {"id": payload["operation_id"], "replayed": False}}
                    proposal["status"] = "applied"
                return deepcopy(proposal["receipt"])
            if route == "task":
                return {"id": "NEW-TASK", "status": "Open", **proposal["fields"]}
            if route == "tasks":
                return {"items": [{"id": "ORIGINAL-TASK"}, {"id": "NEW-TASK"}]}
            raise AssertionError(route)
        for role in ("primary", "alias", "outsider"):
            runner.clients[role] = SimpleNamespace(api=lambda route, payload=None, _role=role, **kwargs: api(_role, route, payload, **kwargs))
        runner.complete_run("answer")
        runner.complete_run("proposal")
        runner.proposal_packet()
        runner.identity_denials()
        self.assertEqual("NEW-TASK", runner.save_task()["task"])
        self.args.phase = "readback"
        before = len([call for call in calls if call[3].get("method") == "POST"])
        self.assertEqual("NEW-TASK", runner.readback()["task"])
        self.assertEqual(before, len([call for call in calls if call[3].get("method") == "POST"]))
        primary_posts = [call for call in calls if call[0] == "primary" and call[3].get("method") == "POST"]
        self.assertEqual(2, len([call for call in primary_posts if call[1].endswith("start_run")]))
        saves = [call for call in primary_posts if call[1].endswith("commit_proposal")]
        self.assertEqual(2, len(saves))
        self.assertEqual(saves[0][2], saves[1][2])


class BoundedClientHttpTests(unittest.TestCase):
    def setUp(self):
        self.handler = lambda handler: self.send(handler, b'{"ok":true}')
        test = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                test.handler(self)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = verifier.BoundedClient("http://127.0.0.1:" + str(self.server.server_port))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def send(self, handler, body, declared=None, status=200):
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body) if declared is None else declared))
        if status == 302:
            handler.send_header("Location", "http://external.invalid")
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except OSError:
            pass

    def test_bounded_client_is_direct_and_does_not_follow_redirects(self):
        with patch.dict("os.environ", {"HTTP_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            self.assertEqual({"ok": True}, self.client.request("GET", "/api/method/test", expected=(200,))[1])
        self.handler = lambda handler: self.send(handler, b"{}", status=302)
        self.assertEqual(302, self.client.request("GET", "/api/method/test", expected=(302,))[0])

    def test_oversized_or_truncated_framing_is_rejected(self):
        for size in (verifier.MAX_HTTP_BYTES + 1, 100):
            self.handler = lambda handler: self.send(handler, b'{"ok":true}', declared=size)
            with self.assertRaises(verifier.CheckFailure):
                self.client.request("GET", "/api/method/test")

    def test_header_drip_cannot_extend_the_http_wall_deadline(self):
        def drip(handler):
            try:
                handler.wfile.write(b"HTTP/1.0 200 OK\r\nX-Drip: ")
                for _ in range(20):
                    handler.wfile.write(b"x")
                    handler.wfile.flush()
                    time.sleep(0.04)
            except OSError:
                pass
        self.handler = drip
        start = time.monotonic()
        with patch.object(verifier, "HTTP_TIMEOUT_SECONDS", 0.15):
            with self.assertRaises(Exception):
                self.client.request("GET", "/api/method/test")
        self.assertLess(time.monotonic() - start, 0.6)


if __name__ == "__main__":
    unittest.main()
