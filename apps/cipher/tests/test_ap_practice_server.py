"""Actual HTTP boundaries and independent human AP practice actions."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from apps.cipher.ap_practice_server import APPracticeHandler, COOKIE_NAME, make_ap_practice_server
from apps.cipher.core.db import WorkspaceModeError


PREFIX = "/api/ap-practice/v1/"


class APPracticeServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "ap-practice.html").write_text(
            '<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__">'
            '<div id="root"></div><script type="module" src="/assets/app.js"></script>', encoding="utf-8")
        (self.root / "assets" / "app.js").write_text("export const practice = true;", encoding="utf-8")
        (self.root / "assets" / "app.css").write_text("body { color: navy; }", encoding="utf-8")
        self.server = make_ap_practice_server(port=0, webroot=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.records = self.server.cipher.ap_practice_records

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp.cleanup()

    def request(self, route, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, route, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def json_request(self, route, **kwargs):
        status, headers, raw = self.request(PREFIX + route, **kwargs)
        return status, headers, json.loads(raw) if raw else None

    def anonymous(self):
        status, headers, body = self.json_request("session")
        self.assertEqual(status, 200, body)
        return {"Cookie": headers["Set-Cookie"].split(";", 1)[0],
                "X-CSRF-Token": body["csrfToken"], "Origin": self.origin,
                "Content-Type": "application/json"}, body

    def session(self, persona="accountant"):
        headers, _ = self.anonymous()
        status, response_headers, body = self.json_request(
            "session", method="POST", headers=headers, body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        headers["Cookie"] = response_headers["Set-Cookie"].split(";", 1)[0]
        headers["X-CSRF-Token"] = body["csrfToken"]
        return headers, body

    def snapshot(self):
        with self.server.cipher_lock:
            c = self.server.cipher
            return ("\n".join(c.db.conn.iterdump()), c.db.conn.total_changes,
                    tuple(c.provider.submissions), dict(c.provider.transfers))

    def test_factory_has_no_workspace_identity_provider_or_mode_argument(self):
        for key, value in (("path", "live.sqlite"), ("cipher", self.server.cipher), ("host", "0.0.0.0"),
                           ("actor", "owner"), ("provider", object()), ("credentials", {}), ("mode", "live")):
            with self.assertRaises(TypeError):
                make_ap_practice_server(port=0, **{key: value})
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.server.cipher.db.in_memory)
        self.assertTrue(self.server.cipher.db.mode_status()["verified"])
        self.assertTrue(self.server.cipher.plugin("people").current_policy()["segregate"])

    def test_anonymous_session_fixed_personas_and_cookie_provenance(self):
        status, headers, body = self.json_request("session")
        self.assertEqual(status, 200, body)
        self.assertFalse(body["authenticated"])
        self.assertEqual(body["mode"], "practice")
        self.assertTrue(body["synthetic"])
        self.assertFalse(body["capabilities"]["microsoftSignIn"])
        self.assertIn(COOKIE_NAME + "=", headers["Set-Cookie"])
        for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, headers["Set-Cookie"])
        self.assertNotIn("Domain=", headers["Set-Cookie"])
        self.assertNotIn("Secure", headers["Set-Cookie"])
        status, _, personas = self.json_request("personas")
        self.assertEqual(status, 200, personas)
        self.assertEqual({p["personaId"] for p in personas["value"]}, {"accountant", "pm"})
        self.assertNotIn("owner", json.dumps(personas))

    def test_select_and_logout_rotate_cookie_and_csrf_and_invalidate_previous_cookie(self):
        anonymous_headers, anonymous = self.anonymous()
        status, headers, body = self.json_request("session", method="POST", headers=anonymous_headers,
                                                body='{"personaId":"accountant"}')
        self.assertEqual(status, 200, body)
        selected_cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertNotEqual(selected_cookie, anonymous_headers["Cookie"])
        self.assertNotEqual(body["csrfToken"], anonymous["csrfToken"])
        self.assertEqual(body["duties"], ["accountant"])
        self.assertEqual(self.json_request("bills", headers=anonymous_headers)[0], 401)
        authenticated = {**anonymous_headers, "Cookie": selected_cookie, "X-CSRF-Token": body["csrfToken"]}
        status, logout_headers, logout = self.json_request("session/logout", method="POST", headers=authenticated, body="{}")
        self.assertEqual(status, 200, logout)
        self.assertFalse(logout["authenticated"])
        self.assertNotEqual(logout_headers["Set-Cookie"].split(";", 1)[0], selected_cookie)
        self.assertEqual(self.json_request("bills", headers=authenticated)[0], 401)

    def test_unbound_unknown_and_expired_sessions_cannot_read_records(self):
        for headers in ({}, {"Cookie": COOKIE_NAME + "=" + "x" * 43}, self.anonymous()[0]):
            status, _, body = self.json_request("bills", headers=headers)
            self.assertEqual(status, 401, body)
        headers, _ = self.session()
        token = headers["Cookie"].partition("=")[2]
        stored = self.server.sessions._sessions[token]
        self.server.sessions.clock = lambda: stored.last_seen + 1800
        status, _, body = self.json_request("bills", headers=headers)
        self.assertEqual(status, 401, body)

    def test_session_identity_forgery_and_duplicate_fields_are_refused_without_database_effect(self):
        headers, _ = self.anonymous()
        before = self.snapshot()
        for body in (
            '{"personaId":"owner"}', '{"personaId":"accountant","actor":"owner"}',
            '{"personaId":"accountant","role":"owner"}', '{"personId":"accountant"}',
            '{"personaId":"accountant","personaId":"pm"}', '{"personaId":"accountant","mode":"live"}',
            '{"personaId":"accountant","provider":{}}', '[]', '{"personaId":NaN}',
        ):
            status, _, value = self.json_request("session", method="POST", headers=headers, body=body)
            self.assertEqual(status, 422, (body, value))
        self.assertEqual(before, self.snapshot())

    def test_missing_wrong_and_rotated_csrf_refuse_session_bind_and_actions(self):
        headers, _ = self.anonymous()
        before = self.snapshot()
        for override in ({"X-CSRF-Token": "wrong"}, {"X-CSRF-Token": ""}):
            status, _, body = self.json_request("session", method="POST", headers={**headers, **override}, body='{"personaId":"accountant"}')
            self.assertEqual(status, 403, body)
        headers.pop("X-CSRF-Token")
        status, _, _ = self.json_request("session", method="POST", headers=headers, body='{"personaId":"accountant"}')
        self.assertIn(status, (400, 403))
        self.assertEqual(before, self.snapshot())

    def test_host_origin_and_fetch_site_are_checked_before_effects(self):
        headers, _ = self.anonymous()
        before = self.snapshot()
        for override in (
            {"Host": "attacker.example"}, {"Host": "127.0.0.1:1"}, {"Origin": "https://attacker.example"},
            {"Origin": f"http://localhost:{self.port}"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
        ):
            status, _, body = self.json_request("session", method="POST", headers={**headers, **override}, body='{"personaId":"accountant"}')
            self.assertEqual(status, 403, body)
        missing_origin = {key: value for key, value in headers.items() if key != "Origin"}
        self.assertEqual(self.json_request("session", method="POST", headers=missing_origin, body='{"personaId":"accountant"}')[0], 403)
        self.assertEqual(before, self.snapshot())

    def test_strict_bounded_json_and_content_type(self):
        headers, _ = self.anonymous()
        before = self.snapshot()
        status, _, _ = self.json_request("session", method="POST", headers={**headers, "Content-Type": "text/plain"}, body='{"personaId":"accountant"}')
        self.assertEqual(status, 415)
        for raw in (b"\xff", b"{}trailing", b"null", b"", b'{"personaId":false}'):
            self.assertEqual(self.json_request("session", method="POST", headers=headers, body=raw)[0], 422)
        self.assertEqual(self.json_request("session", method="POST", headers=headers, body="x" * 16385)[0], 413)
        self.assertEqual(before, self.snapshot())

    def test_scoped_reads_packets_queues_and_totals_hide_unassigned_project(self):
        headers, _ = self.session()
        hidden = self.records["hidden_project_id"]
        for route in ("projects", "commitments", "bills", "approvals", "posting-queue"):
            status, _, body = self.json_request(route, headers=headers)
            self.assertEqual(status, 200, (route, body))
            self.assertNotIn(hidden, json.dumps(body))
            self.assertNotIn("Hidden synthetic", json.dumps(body))
        for route in ("bills/" + self.records["hidden_bill_id"], "bills?projectId=" + hidden,
                      "posting-queue?projectId=" + hidden):
            status, _, body = self.json_request(route, headers=headers)
            self.assertEqual(status, 404, (route, body))
        hidden_approval = self.server.cipher.bills.get(self.records["hidden_bill_id"])["business_approval_id"]
        status, _, body = self.json_request("approvals/" + hidden_approval + "/packet", headers=headers)
        self.assertEqual(status, 404, body)

    def test_unknown_duplicate_and_forged_query_fields_are_refused(self):
        headers, _ = self.session()
        before = self.snapshot()
        for query in ("actor=owner", "role=owner", "personId=owner", "mode=live", "provider=real", "top=1&top=2",
                      "top=NaN", "top=1.0", "top=-1", "top=0", "top=101", "search="):
            self.assertEqual(self.json_request("bills?" + query, headers=headers)[0], 400, query)
        self.assertEqual(self.json_request("posting-queue?ready=1", headers=headers)[0], 400)
        self.assertEqual(before, self.snapshot())

    def test_cursor_cannot_be_reused_by_a_different_practice_person(self):
        accountant, _ = self.session()
        pm, _ = self.session("pm")
        status, _, body = self.json_request("bills?top=1", headers=accountant)
        self.assertEqual(status, 200, body)
        self.assertIsNotNone(body["nextCursor"])
        status, _, refusal = self.json_request("bills?top=1&cursor=" + body["nextCursor"], headers=pm)
        self.assertIn(status, (400, 403, 412, 422), refusal)

    def test_current_authority_is_rechecked_after_session_binding(self):
        headers, dto = self.session()
        person = self.server.cipher.db.one("SELECT * FROM people_persons WHERE id=?", (dto["person"]["id"],))
        with self.server.cipher_lock:
            self.server.cipher.plugin("people").deactivate_person(person["login"], reason="Practice session revocation", actor="practice.bootstrap")
        status, _, body = self.json_request("bills", headers=headers)
        self.assertEqual(status, 401, body)

    def test_preflight_is_zero_write_and_actual_post_allows_empty_same_period_reason(self):
        headers, _ = self.session()
        bill_id = self.records["approved_bill_id"]
        before = self.snapshot()
        status, _, review = self.json_request("bills/" + bill_id + "/post:preflight", method="POST", headers=headers,
                                             body=json.dumps({"periodId": "2026-10", "reason": ""}))
        self.assertEqual(status, 200, review)
        self.assertTrue(review["allowed"], review)
        self.assertEqual(before, self.snapshot())
        action_headers = {**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
        status, _, result = self.json_request("bills/" + bill_id + "/post", method="POST", headers=action_headers,
                                             body=json.dumps({"periodId": "2026-10", "reason": "", "fingerprint": review["fingerprint"]}))
        self.assertEqual(status, 200, result)
        self.assertTrue(result["effectApplied"])

    def test_accountant_request_pm_grant_and_accountant_post_use_distinct_registered_people(self):
        accountant, _ = self.session()
        pm, _ = self.session("pm")
        bill_id = self.records["draft_bill_id"]
        c = self.server.cipher
        before_journals = c.db.one("SELECT COUNT(*) AS n FROM journals")["n"]

        def action(route, headers, data):
            status, _, review = self.json_request(route + ":preflight", method="POST", headers=headers, body=json.dumps(data))
            self.assertEqual(status, 200, review)
            self.assertTrue(review["allowed"], review)
            request_headers = {**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
            status, _, result = self.json_request(route, method="POST", headers=request_headers,
                                                 body=json.dumps({**data, "fingerprint": review["fingerprint"]}))
            self.assertEqual(status, 200, result)
            return result

        requested = action("bills/" + bill_id + "/request-approval", accountant, {})
        approval_id = requested["result"]["approvalId"]
        status, _, refusal = self.json_request("approvals/" + approval_id + "/approve:preflight", method="POST", headers=accountant, body="{}")
        self.assertIn(status, (200, 403), refusal)
        if status == 200:
            self.assertFalse(refusal["allowed"])
        granted = action("approvals/" + approval_id + "/approve", pm, {})
        self.assertEqual(granted["result"]["status"], "approved")
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], before_journals)
        self.assertEqual(c.bills.get(bill_id)["status"], "approved")
        status, _, refusal = self.json_request("bills/" + bill_id + "/post:preflight", method="POST", headers=pm,
                                              body='{"periodId":"2026-11","reason":"Reviewed later practice period"}')
        self.assertIn(status, (200, 403), refusal)
        if status == 200:
            self.assertFalse(refusal["allowed"])
        posted = action("bills/" + bill_id + "/post", accountant,
                        {"periodId": "2026-11", "reason": "Reviewed later practice period"})
        self.assertEqual(posted["result"]["status"], "posted")
        self.assertEqual(c.bills.get(bill_id)["posting_period_id"], "2026-11")
        self.assertEqual(c.db.one("SELECT COUNT(*) AS n FROM journals")["n"], before_journals + 1)
        self.assertFalse(c.provider.submissions)

    def test_exact_concurrent_retry_posts_once_and_changed_body_conflicts(self):
        headers, _ = self.session()
        bill_id = self.records["approved_bill_id"]
        status, _, review = self.json_request("bills/" + bill_id + "/post:preflight", method="POST", headers=headers,
                                              body='{"periodId":"2026-11","reason":"Reviewed practice posting"}')
        self.assertEqual(status, 200, review)
        self.assertTrue(review["allowed"], review)
        headers = {**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
        body = {"periodId": "2026-11", "reason": "Reviewed practice posting", "fingerprint": review["fingerprint"]}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.json_request("bills/" + bill_id + "/post", method="POST", headers=headers, body=json.dumps(body)), range(4)))
        self.assertTrue(all(status == 200 for status, _, _ in results), results)
        self.assertEqual(len({result["receiptId"] for _, _, result in results}), 1)
        self.assertEqual(sum(not result["replayed"] for _, _, result in results), 1)
        before = self.snapshot()
        status, _, refusal = self.json_request("bills/" + bill_id + "/post", method="POST", headers=headers,
                                               body=json.dumps({**body, "reason": "Changed after action"}))
        self.assertEqual(status, 409, refusal)
        self.assertEqual(before, self.snapshot())

    def test_actual_action_requires_quoted_version_uuid_and_fixed_body_shape(self):
        headers, _ = self.session()
        route = "bills/" + self.records["draft_bill_id"] + "/request-approval"
        before = self.snapshot()
        for forged in ("actor", "role", "mode", "provider", "operation", "method", "personId"):
            status, _, body = self.json_request(route, method="POST", headers=headers,
                                                body=json.dumps({"fingerprint": "unreviewed", forged: "owner"}))
            self.assertEqual(status, 422, body)
        for extra in (
            {"If-Match": '"version"', "Repeatability-Request-ID": "invalid"},
            {"If-Match": "version", "Repeatability-Request-ID": str(uuid.uuid4())},
        ):
            status, _, body = self.json_request(route, method="POST", headers={**headers, **extra}, body='{"fingerprint":"unreviewed"}')
            self.assertEqual(status, 422, body)
        self.assertEqual(before, self.snapshot())

    def test_duplicate_security_headers_and_ambiguous_cookie_refuse_before_effects(self):
        headers, _ = self.session()
        before = self.snapshot()
        for duplicated in ("Host", "Origin", "Sec-Fetch-Site", "Cookie", "X-CSRF-Token", "Content-Type", "Content-Length"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            values = {"Host": f"127.0.0.1:{self.port}", "Sec-Fetch-Site": "same-origin", "Content-Length": "2", **headers}
            try:
                conn.putrequest("POST", PREFIX + "session/logout", skip_host=True)
                for key, value in values.items():
                    conn.putheader(key, value)
                conn.putheader(duplicated, values[duplicated])
                conn.endheaders(b"{}")
                response = conn.getresponse()
                self.assertEqual(response.status, 400, (duplicated, response.read()))
                response.read()
            finally:
                conn.close()
        double_cookie = headers["Cookie"] + "; " + headers["Cookie"]
        self.assertEqual(self.json_request("bills", headers={**headers, "Cookie": double_cookie})[0], 400)
        self.assertEqual(before, self.snapshot())

    def test_changed_record_version_or_review_fingerprint_has_no_business_effect(self):
        headers, _ = self.session()
        bill_id = self.records["approved_bill_id"]
        route = "bills/" + bill_id + "/post"
        data = {"periodId": "2026-11", "reason": "Reviewed practice posting"}
        status, _, review = self.json_request(route + ":preflight", method="POST", headers=headers, body=json.dumps(data))
        self.assertEqual(status, 200, review)
        self.assertTrue(review["allowed"], review)
        before = self.snapshot()
        for version, fingerprint in (("stale-version", review["fingerprint"]), (review["resourceVersion"], "pf1.changed")):
            action_headers = {**headers, "If-Match": '"' + version + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
            status, _, refusal = self.json_request(route, method="POST", headers=action_headers,
                                                   body=json.dumps({**data, "fingerprint": fingerprint}))
            self.assertEqual(status, 412, refusal)
        # Savepoint commands do not change SQLite total_changes; no action ran.
        self.assertEqual(before, self.snapshot())

    def test_old_generic_and_non_ap_routes_are_absent(self):
        headers, _ = self.session()
        before = self.snapshot()
        for route in ("/api/action/run_demo", "/api/state", "/api/practice/v1/bills", "/api/ricky/invoke", PREFIX + "payments", PREFIX + "modules"):
            self.assertEqual(self.request(route, headers=headers)[0], 404, route)
            self.assertEqual(self.request(route, method="POST", headers=headers, body="{}")[0], 404, route)
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            status, response_headers, _ = self.request(PREFIX + "bills", method=method, headers=headers, body="{}")
            self.assertEqual(status, 405)
            self.assertNotIn("Access-Control-Allow-Origin", response_headers)
        self.assertEqual(before, self.snapshot())

    def test_static_spa_nonce_explicit_mime_traversal_and_symlink_boundaries(self):
        nonces = []
        for route in ("/", "/ap-practice.html", "/bills/example"):
            status, headers, raw = self.request(route)
            self.assertEqual(status, 200, raw)
            nonce = raw.decode().split('name="cipher-style-nonce" content="', 1)[1].split('"', 1)[0]
            nonces.append(nonce)
            self.assertIn("'nonce-" + nonce + "'", headers["Content-Security-Policy"])
            self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
            self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(len(set(nonces)), 3)
        status, headers, _ = self.request("/assets/app.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(self.request("/assets/missing.js")[0], 404)
        secret = self.root.parent / (self.root.name + "-secret.js")
        secret.write_text("unexposed-source", encoding="utf-8")
        (self.root / "escape.js").symlink_to(secret)
        (self.root / "loop.js").symlink_to("loop.js")
        try:
            for route in ("/%2e%2e/secret.js", "/escape.js", "/loop.js", "/%ZZ", "/%00"):
                status, _, raw = self.request(route)
                self.assertIn(status, (400, 404), (route, raw))
                self.assertNotIn(b"unexposed-source", raw)
        finally:
            secret.unlink()

    def test_workspace_mode_is_checked_on_static_reads_and_actions(self):
        headers, _ = self.session()
        before = self.snapshot()
        with patch.object(self.server.cipher.db, "require_practice_mode", side_effect=WorkspaceModeError("private path must not leak")):
            for route, method in (("/", "GET"), (PREFIX + "bills", "GET"), (PREFIX + "session", "POST")):
                status, _, raw = self.request(route, method=method, headers=headers, body="{}" if method == "POST" else None)
                self.assertEqual(status, 503, raw)
                self.assertEqual(json.loads(raw)["error"]["code"], "workspace_mode_unavailable")
                self.assertNotIn(b"private path", raw)
        self.assertEqual(before, self.snapshot())

    def test_unexpected_failures_return_safe_error_and_head_has_no_body(self):
        headers, _ = self.session()
        with patch.object(self.server.contract, "read", side_effect=RuntimeError("SQL secret provider credential")):
            status, _, body = self.json_request("bills", headers=headers)
            self.assertEqual(status, 500, body)
            self.assertNotIn("SQL secret", json.dumps(body))
        status, response_headers, raw = self.request(PREFIX + "bills", method="HEAD", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(raw, b"")
        self.assertGreater(int(response_headers["Content-Length"]), 0)

    def test_client_disconnect_after_commit_keeps_receipt_without_second_response(self):
        headers, _ = self.session()
        bill_id = self.records["approved_bill_id"]
        route = "bills/" + bill_id + "/post"
        body = {"periodId": "2026-10", "reason": ""}
        status, _, review = self.json_request(route + ":preflight", method="POST", headers=headers, body=json.dumps(body))
        self.assertEqual(status, 200, review)
        self.assertTrue(review["allowed"], review)
        headers = {**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
        body["fingerprint"] = review["fingerprint"]
        attempts = []
        unhandled = []
        original_response = APPracticeHandler._respond

        def disconnect(handler, status, payload, content_type, **kwargs):
            if handler.path != PREFIX + route or handler.command != "POST":
                return original_response(handler, status, payload, content_type, **kwargs)
            attempts.append(status)
            if status != 200:
                return original_response(handler, status, payload, content_type, **kwargs)
            original_write = handler.wfile.write

            def failed_payload(data):
                if data == payload:
                    raise BrokenPipeError("ordinary practice browser disconnect")
                return original_write(data)

            with patch.object(handler.wfile, "write", side_effect=failed_payload):
                return original_response(handler, status, payload, content_type, **kwargs)

        with patch.object(APPracticeHandler, "_respond", new=disconnect), patch.object(
                self.server, "handle_error", side_effect=lambda *args: unhandled.append(True)):
            try:
                self.request(PREFIX + route, method="POST", headers=headers, body=json.dumps(body))
            except http.client.IncompleteRead:
                pass  # The browser lost the committed response, so it retries.
        self.assertEqual(attempts, [200])
        self.assertFalse(unhandled)
        self.assertEqual(self.server.cipher.bills.get(bill_id)["status"], "posted")
        status, _, replay = self.json_request(route, method="POST", headers=headers, body=json.dumps(body))
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["effectApplied"])
        self.assertEqual(self.server.cipher.db.one("SELECT COUNT(*) AS n FROM ap_action_receipts")["n"], 1)


if __name__ == "__main__":
    unittest.main()
