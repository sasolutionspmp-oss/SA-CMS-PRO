"""Six genuine library HTTP actions, exact retries and isolated transport."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.library_practice_server import API_PREFIX, COOKIE_NAME, make_library_practice_server
from apps.cipher.library_practice_fixture import PM_LOGIN, BOOTSTRAP_LOGIN
from apps.cipher.core.db import WorkspaceModeError


class LibraryPracticeServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "library-practice.html").write_text('<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__"><div id="root"></div><script type="module" src="/assets/app.js"></script>')
        (self.root / "assets" / "app.js").write_text("export const library = true;")
        self.server = make_library_practice_server(port=0, webroot=self.root)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.c = self.server.cipher
        self.project = self.c.library_practice_records["project_id"]

    def request(self, path, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def api(self, path, **kwargs):
        status, headers, raw = self.request(API_PREFIX + path, **kwargs)
        return status, headers, json.loads(raw) if raw else None

    def session(self, persona="author"):
        status, headers, body = self.api("session")
        self.assertEqual(status, 200, body)
        outgoing = {"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"],
            "Origin": self.origin, "Content-Type": "application/json"}
        status, headers, body = self.api("session", method="POST", headers=outgoing, body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        outgoing.update({"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"]})
        return outgoing

    def state(self):
        with self.server.cipher_lock:
            return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions), dict(self.c.provider.transfers)

    def authored(self, **changes):
        return {"kind": "contract_clause", "title": "Synthetic authored quality clause", "text": "Exact synthetic authored text.\nSecond paragraph.",
            "sourceLocator": "Author editor / original clause", **changes}

    def prepared(self, headers, route, body=None):
        typed = {} if body is None else body
        before = self.state()
        status, _, review = self.api(route + ":preflight", method="POST", headers=headers, body=json.dumps(typed))
        self.assertEqual(status, 200, review)
        self.assertTrue(review["allowed"], review)
        self.assertEqual(self.state(), before)
        self.assertEqual(review["safeEffects"]["journalDelta"], 0)
        self.assertFalse(review["safeEffects"]["externalDistribution"])
        return route, {**headers, "Repeatability-Request-ID": str(uuid4()), "If-Match": '"' + review["resourceVersion"] + '"'}, json.dumps({**typed, "fingerprint": review["fingerprint"]})

    def send(self, request):
        route, headers, body = request
        return self.api(route, method="POST", headers=headers, body=body)

    def act(self, headers, route, body=None):
        request = self.prepared(headers, route, body)
        status, _, result = self.send(request)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["effectApplied"])
        return result, request

    def granted(self):
        author, reviewer = self.session(), self.session("reviewer")
        created, create_request = self.act(author, f"projects/{self.project}/create-entry", self.authored())
        entry, revision = created["result"]["entryId"], created["result"]["revisionId"]
        revised, revise_request = self.act(author, f"library-entries/{entry}/revise", {"previousRevisionId": revision,
            "text": "Revised exact synthetic authored text.\nIndependent review is required.", "sourceLocator": "Author editor / revised clause", "changeReason": "Synthetic clarification"})
        revision = revised["result"]["revisionId"]
        prepared, prepare_request = self.act(author, f"library-revisions/{revision}/prepare-reference", {"targetLocator": "Project reference / clause 1", "purpose": "Internal synthetic project reference"})
        plan = prepared["result"]["planId"]
        requested, request = self.act(author, f"reference-plans/{plan}/request-adoption")
        approval = requested["result"]["approvalId"]
        granted, grant_request = self.act(reviewer, f"adoption-approvals/{approval}/approve")
        return author, reviewer, entry, revision, plan, approval, [(created, create_request), (revised, revise_request), (prepared, prepare_request), (requested, request), (granted, grant_request)]

    def test_factory_owns_fresh_memory_and_exposes_no_workspace_actor_or_provider_selector(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.c.db.in_memory)
        self.assertTrue(self.c.db.mode_status()["verified"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_entries"), 0)
        for key, value in (("path", "live.sqlite"), ("host", "0.0.0.0"), ("cipher", self.c), ("actor", "owner"),
                           ("mode", "live"), ("provider", object()), ("credentials", {}), ("policy", {})):
            with self.subTest(key=key), self.assertRaises(TypeError): make_library_practice_server(port=0, **{key: value})

    def test_all_six_actual_routes_and_original_replays_preserve_reference_text_after_edit(self):
        author, reviewer, entry, revision, plan, approval, receipts = self.granted()
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_adoptions"), 0)
        applied, request = self.act(author, f"adoption-approvals/{approval}/apply")
        receipts.append((applied, request))
        reference = applied["result"]["referenceId"]
        status, response_headers, original = self.api(f"project-references/{reference}", headers=author)
        self.assertEqual(status, 200, original)
        self.assertEqual(response_headers["ETag"], '"' + original["version"] + '"')
        later, _ = self.act(author, f"library-entries/{entry}/revise", {"previousRevisionId": revision, "text": "Later synthetic current source.",
            "sourceLocator": "Author editor / later revision", "changeReason": "Synthetic current update"})
        status, _, current = self.api(f"project-references/{reference}", headers=author)
        self.assertEqual(status, 200, current)
        self.assertEqual(current["text"], original["text"])
        self.assertEqual(current["revisionId"], revision)
        self.assertEqual(current["currentRevisionId"], later["result"]["revisionId"])
        self.assertFalse(current["sourceCurrent"])
        for original, request in receipts:
            before = self.state()
            status, _, replay = self.send(request)
            self.assertEqual(status, 200, replay)
            self.assertEqual(replay, {**original, "replayed": True, "effectApplied": False})
            self.assertEqual(self.state(), before)
        for table in ("journals", "outbox", "prime_bill_sends"):
            self.assertEqual(self.c.db.scalar(f"SELECT COUNT(*) FROM {table}"), 0)
        self.assertEqual(self.c.provider.submissions, [])

    def test_same_author_cannot_independently_review_the_reference(self):
        author = self.session()
        created, _ = self.act(author, f"projects/{self.project}/create-entry", self.authored())
        prepared, _ = self.act(author, f"library-revisions/{created['result']['revisionId']}/prepare-reference", {"targetLocator": "Project reference", "purpose": "Internal reference"})
        requested, _ = self.act(author, f"reference-plans/{prepared['result']['planId']}/request-adoption")
        before = self.state()
        status, _, review = self.api(f"adoption-approvals/{requested['result']['approvalId']}/approve:preflight", method="POST", headers=author, body="{}")
        self.assertEqual(status, 200, review)
        self.assertFalse(review["allowed"])
        self.assertEqual(self.state(), before)

    def test_simultaneous_apply_commits_one_original_reference_and_receipt(self):
        author, _, _, _, _, approval, _ = self.granted()
        request = self.prepared(author, f"adoption-approvals/{approval}/apply")
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.send(request), range(2)))
        self.assertEqual([response[0] for response in responses], [200, 200], responses)
        self.assertEqual(responses[0][2]["receiptId"], responses[1][2]["receiptId"])
        self.assertEqual(sum(response[2]["effectApplied"] for response in responses), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_adoptions"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_actual_dropped_tcp_response_retains_committed_text_and_original_receipt(self):
        request = self.prepared(self.session(), f"projects/{self.project}/create-entry", self.authored())
        route, headers, body = request
        raw = (f"POST {API_PREFIX + route} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items()) +
               f"Content-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n" + body).encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as conn:
            conn.sendall(raw)
            conn.shutdown(socket.SHUT_RDWR)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.cipher_lock:
                if self.c.db.scalar("SELECT COUNT(*) FROM library_action_receipts"): break
            time.sleep(0.01)
        else: self.fail("Disconnected request lost its committed original receipt")
        before = self.state()
        status, _, replay = self.send(request)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["effectApplied"])
        self.assertEqual(self.state(), before)

    def test_late_receipt_failure_rolls_back_consumption_reference_and_command(self):
        author, _, _, _, _, approval, _ = self.granted()
        request = self.prepared(author, f"adoption-approvals/{approval}/apply")
        before = self.state()
        with patch.object(self.server.actions.receipts, "record", side_effect=RuntimeError("private injected receipt completion fault")):
            status, _, refusal = self.send(request)
        self.assertEqual(status, 500, refusal)
        self.assertNotIn("private injected", json.dumps(refusal))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.send(request)[0], 200)

    def test_strict_origins_csrf_forged_identity_and_exact_body_refuse_before_effect(self):
        headers = self.session()
        route = f"projects/{self.project}/create-entry:preflight"
        before = self.state()
        for override, expected in (({"Origin": "https://foreign.invalid"}, 403), ({"X-CSRF-Token": "wrong"}, 403),
                                   ({"Cookie": "cipher_ar_practice=foreign_application_cookie_token"}, 401)):
            self.assertEqual(self.api(route, method="POST", headers={**headers, **override}, body=json.dumps(self.authored()))[0], expected)
        for extra in ("personId", "actor", "rightsUse", "provider", "filePath", "destination"):
            self.assertEqual(self.api(route, method="POST", headers=headers, body=json.dumps(self.authored(**{extra: "selected"})))[0], 422)
        self.assertEqual(self.state(), before)

    def test_current_duty_before_completed_replay_and_strict_uuid_if_match(self):
        request = self.prepared(self.session(), f"projects/{self.project}/create-entry", self.authored())
        before = self.state()
        for overrides in ({"If-Match": request[1]["If-Match"].strip('"')}, {"If-Match": 'W/"old"'}, {"Repeatability-Request-ID": "wrong"}):
            self.assertEqual(self.send((request[0], {**request[1], **overrides}, request[2]))[0], 422)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.send(request)[0], 200)
        self.c.plugin("people").end_membership(PM_LOGIN, self.project, reason="Synthetic library duty ended", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.server.actions.receipts, "find", side_effect=AssertionError("Ended PM disclosed a receipt")) as find:
            self.assertIn(self.send(request)[0], (401, 403, 404))
            find.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_current_read_detail_and_head_are_pure_and_hide_other_project(self):
        author = self.session()
        created, _ = self.act(author, f"projects/{self.project}/create-entry", self.authored())
        before = self.state()
        for route in ("projects", "library-entries", "reference-plans", "adoption-approvals", "project-references", f"projects/{self.project}/preparation",
                      f"library-entries/{created['result']['entryId']}", f"library-revisions/{created['result']['revisionId']}"):
            self.assertEqual(self.api(route, headers=author)[0], 200, route)
        status, headers, raw = self.request(API_PREFIX + f"library-entries/{created['result']['entryId']}", method="HEAD", headers=author)
        self.assertEqual(status, 200)
        self.assertEqual(raw, b"")
        self.assertIn("ETag", headers)
        hidden = self.c.library_practice_records["hidden_project_id"]
        self.assertEqual(self.api(f"projects/{hidden}/preparation", headers=author)[0], 404)
        self.assertEqual(self.api(f"library-entries?projectId={hidden}", headers=author)[0], 404)
        self.assertEqual(self.state(), before)

    def test_static_nonce_csp_path_bounds_and_mode_boundary(self):
        status, headers, first = self.request("/")
        self.assertEqual(status, 200)
        self.assertNotIn(b"__CIPHER_STYLE_NONCE__", first)
        self.assertIn("style-src 'self' 'nonce-", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotEqual(first, self.request("/")[2])
        self.assertEqual(self.request("/library/entries")[0], 200)
        for path in ("/../private.py", "/%2e%2e/private.py", "/assets/missing.js", "/api/ar-practice/v1/session", "/api/library-practice/v1/execute"):
            self.assertIn(self.request(path)[0], (400, 404))
        with patch.object(self.server, "require_practice", side_effect=WorkspaceModeError("private mode reason")):
            status, _, body = self.api("session")
        self.assertEqual(status, 503, body)
        self.assertNotIn("private mode reason", json.dumps(body))

    def test_duplicate_framing_and_oversized_envelope_refuse_before_body_or_effect(self):
        headers = self.session()
        route = API_PREFIX + f"projects/{self.project}/create-entry:preflight"
        before = self.state()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", route)
            for key, value in headers.items(): conn.putheader(key, value)
            conn.putheader("Content-Length", "2")
            conn.putheader("Content-Length", "3")
            conn.endheaders(b"{}")
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            conn.close()
        for extra, status in (({"Transfer-Encoding": "chunked"}, 400), ({"Content-Length": "524289"}, 413),
                              ({"Content-Type": "text/plain"}, 415)):
            self.assertEqual(self.api(route.removeprefix(API_PREFIX), method="POST", headers={**headers, **extra}, body="{}")[0], status)
        self.assertEqual(self.state(), before)

    def test_genuine_source_change_refuses_old_review_then_current_review_can_complete(self):
        author = self.session()
        request = self.prepared(author, f"projects/{self.project}/create-entry", self.authored())
        self.c.plugin("library").create(self.project, self.authored(title="Independent genuine intervening source"), actor=PM_LOGIN)
        before = self.state()
        status, _, refusal = self.send(request)
        self.assertEqual(status, 412, refusal)
        self.assertEqual(refusal["error"]["code"], "record_changed")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_action_receipts"), 0)
        completed, _ = self.act(author, f"projects/{self.project}/create-entry", self.authored())
        self.assertEqual(completed["result"]["status"], "draft")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_entries"), 2)

    def test_cli_launches_only_owned_library_server_with_port(self):
        from apps.cipher.__main__ import main
        with patch("apps.cipher.library_practice_server.serve_library_practice") as serve:
            self.assertEqual(main(["library-practice-web", "--port", "8770"]), 0)
            serve.assert_called_once_with(port=8770)
        for option in ("--db", "--host", "--actor", "--provider", "--token"):
            with self.subTest(option=option), patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                main(["library-practice-web", option, "caller-selected"])


if __name__ == "__main__":
    unittest.main()
