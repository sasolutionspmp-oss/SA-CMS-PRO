"""Actual commercial HTTP journeys, scoped transport and original retries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
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
import uuid

from apps.cipher.commercial_practice_server import API_PREFIX, COOKIE_NAME, make_commercial_practice_server
from apps.cipher.commercial_practice_fixture import BOOTSTRAP_LOGIN, ESTIMATOR_LOGIN
from apps.cipher.commercial_sessions import IDLE_SECONDS
from apps.cipher.core.db import WorkspaceModeError


class CommercialPracticeServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "commercial-practice.html").write_text(
            '<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__">'
            '<div id="root"></div><script type="module" src="/assets/app.js"></script>', encoding="utf-8")
        (self.root / "assets" / "app.js").write_text("export const commercial = true;", encoding="utf-8")
        self.server = make_commercial_practice_server(port=0, webroot=self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.c = self.server.cipher
        self.r = self.c.commercial_practice_records

    def request(self, route, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, route, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def api(self, route, **kwargs):
        status, headers, raw = self.request(API_PREFIX + route, **kwargs)
        return status, headers, json.loads(raw) if raw else None

    def anonymous(self):
        status, headers, body = self.api("session")
        self.assertEqual(status, 200, body)
        return {"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"],
                "Origin": self.origin, "Content-Type": "application/json"}, body

    def session(self, persona="preparer"):
        headers, _ = self.anonymous()
        status, received, body = self.api("session", method="POST", headers=headers,
                                         body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        headers.update({"Cookie": received["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"]})
        return headers

    def snapshot(self):
        with self.server.cipher_lock:
            return (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                    tuple(self.c.provider.submissions), dict(self.c.provider.transfers))

    def review(self, headers, route, body=None):
        before = self.snapshot()
        status, _, result = self.api(route + ":preflight", method="POST", headers=headers,
                                     body=json.dumps({} if body is None else body))
        self.assertEqual(status, 200, result)
        self.assertTrue(result["allowed"], result)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(result["safeEffects"]["workingLedgerJournalDelta"], 0)
        self.assertEqual(result["safeEffects"]["providerCallBound"], 0)
        return result

    def prepared(self, headers, route, body=None):
        typed = {} if body is None else body
        review = self.review(headers, route, typed)
        return route, {**headers, "Repeatability-Request-ID": str(uuid.uuid4()),
                       "If-Match": '"' + review["resourceVersion"] + '"'}, json.dumps({**typed, "fingerprint": review["fingerprint"]})

    def send(self, request):
        route, headers, body = request
        return self.api(route, method="POST", headers=headers, body=body)

    def act(self, headers, route, body=None):
        request = self.prepared(headers, route, body)
        status, _, result = self.send(request)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["replayed"])
        self.assertTrue(result["effectApplied"])
        return result, request

    def input(self):
        return {"documentRevisionId": self.r["current_drawing_revision_id"], "lines": [{
            "description": "Manual distinct HTTP scope", "quantity": "13.125", "unit": "LF", "unitPriceCents": 2500,
            "sourceLocator": "A-101, manually entered run 4", "costCode": "33-110"}],
            "priceBookRef": "Synthetic practice rates v1", "inclusions": ["Manual HTTP scope"],
            "exclusions": ["Excavation"], "contingencyRate": "0", "measurementBasis": "Manual quantity; geometry unverified"}

    def test_factory_is_fresh_memory_loopback_with_no_provider_or_workspace_selector(self):
        for key, value in (("path", "live.sqlite"), ("cipher", self.c), ("host", "0.0.0.0"),
                           ("actor", "owner"), ("provider", object()), ("credentials", {}), ("mode", "live")):
            with self.subTest(key=key), self.assertRaises(TypeError):
                make_commercial_practice_server(port=0, **{key: value})
        for port in (True, -1, 65536, "8768"):
            with self.assertRaises(ValueError):
                make_commercial_practice_server(port=port)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.c.db.in_memory)
        self.assertTrue(self.c.db.mode_status()["verified"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_fixed_registered_personas_and_rotated_independent_sessions(self):
        status, _, personas = self.api("personas")
        self.assertEqual(status, 200)
        self.assertEqual({value["personaId"] for value in personas["value"]}, {"preparer", "reviewer", "pm"})
        anonymous, original = self.anonymous()
        self.assertFalse(original["authenticated"])
        self.assertFalse(original["capabilities"]["verifiedGeometry"])
        self.assertNotIn("owner", json.dumps(personas))
        status, headers, selected = self.api("session", method="POST", headers=anonymous, body='{"personaId":"preparer"}')
        self.assertEqual(status, 200, selected)
        cookie = headers["Set-Cookie"]
        self.assertIn(COOKIE_NAME + "=", cookie)
        for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertNotEqual(cookie.split(";", 1)[0], anonymous["Cookie"])
        self.assertNotEqual(selected["csrfToken"], original["csrfToken"])
        self.assertEqual(selected["duties"], ["estimator"])
        self.assertEqual(self.api("estimates", headers=anonymous)[0], 401)
        current = {**anonymous, "Cookie": cookie.split(";", 1)[0], "X-CSRF-Token": selected["csrfToken"]}
        status, _, logged_out = self.api("session/logout", method="POST", headers=current, body="{}")
        self.assertEqual(status, 200, logged_out)
        self.assertFalse(logged_out["authenticated"])
        self.assertEqual(self.api("estimates", headers=current)[0], 401)

    def test_full_seven_action_http_journey_original_receipts_and_exact_source_preserving_draft(self):
        preparer, reviewer, pm = self.session(), self.session("reviewer"), self.session("pm")
        receipts = []
        created, request = self.act(preparer, f"projects/{self.r['project_id']}/create-estimate", self.input())
        receipts.append((created, request))
        first = created["result"]["estimateId"]
        _, _, source = self.api(f"estimates/{first}", headers=preparer)
        revision = self.input()
        revision["lines"][0].update({"quantity": "14.125", "previousLineId": source["lines"][0]["id"]})
        revision["removedExclusions"] = []
        revised, request = self.act(preparer, f"estimates/{first}/revise", revision)
        receipts.append((revised, request))
        estimate_id = revised["result"]["estimateId"]
        requested, request = self.act(preparer, f"estimates/{estimate_id}/request-acceptance")
        receipts.append((requested, request))
        approval_id = requested["result"]["approvalId"]
        accepted, request = self.act(reviewer, f"estimate-approvals/{approval_id}/accept")
        receipts.append((accepted, request))
        applied, request = self.act(preparer, f"estimate-approvals/{approval_id}/apply")
        receipts.append((applied, request))
        handoff, request = self.act(preparer, f"estimates/{estimate_id}/prepare-handoff")
        receipts.append((handoff, request))
        handoff_id = handoff["result"]["handoffId"]
        committed, request = self.act(pm, f"estimate-handoffs/{handoff_id}/create-commitment")
        receipts.append((committed, request))
        commitment_id = committed["result"]["commitmentId"]
        status, headers, draft = self.api(f"commercial-commitments/{commitment_id}", headers=preparer)
        self.assertEqual(status, 200, draft)
        self.assertEqual(headers["ETag"], '"' + draft["version"] + '"')
        self.assertEqual((draft["status"], draft["creationStatus"]), ("draft", "draft"))
        self.assertEqual(draft["originalAmountCents"], 35313)
        self.assertEqual(draft["lines"][0]["quantity"], "14.125")
        self.assertEqual(draft["lines"][0]["amountCents"], 35313)
        self.assertEqual(draft["estimate"]["acceptanceApprovalId"], approval_id)
        self.assertFalse(draft["executionAvailableHere"])
        self.assertFalse(draft["lines"][0]["verifiedGeometry"])
        self.assertEqual(draft["lines"][0]["measurementMethod"], "manual_entry")
        self.assertTrue(all(link["apiRoute"].startswith(API_PREFIX) for link in draft["relatedRecords"]))
        self.assertNotIn("ap-practice", json.dumps(draft))
        for original, request in receipts:
            before = self.snapshot()
            status, _, replay = self.send(request)
            self.assertEqual(status, 200, replay)
            self.assertEqual(replay, {**original, "replayed": True, "effectApplied": False})
            self.assertEqual(before, self.snapshot())
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commercial_action_receipts"), 7)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM outbox"), 0)
        self.assertFalse(self.c.provider.submissions)
        self.assertFalse(self.c.provider.transfers)

    def test_scoped_lists_details_filters_cursor_and_head_are_read_only(self):
        headers = self.session()
        before = self.snapshot()
        for route in ("projects", "drawing-revisions", "estimates", "estimate-approvals", "estimate-handoffs"):
            status, _, body = self.api(route, headers=headers)
            self.assertEqual(status, 200, body)
            self.assertNotIn(self.r["hidden_project_id"], json.dumps(body))
            self.assertNotIn(self.r["hidden_estimate_id"], json.dumps(body))
        status, _, first = self.api("estimates?top=1", headers=headers)
        self.assertEqual(status, 200, first)
        self.assertEqual(first["count"], 2)
        self.assertIsNotNone(first["nextCursor"])
        status, _, second = self.api("estimates?top=1&cursor=" + first["nextCursor"], headers=headers)
        self.assertEqual(status, 200, second)
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        for route in (f"projects/{self.r['project_id']}/estimate-preparation", f"estimates/{self.r['current_estimate_id']}",
                      f"estimates/{self.r['current_estimate_id']}/comparison", f"estimates/{self.r['current_estimate_id']}/handoff-preparation"):
            status, _, body = self.api(route, headers=headers)
            self.assertEqual(status, 200, body)
        status, response_headers, raw = self.request(API_PREFIX + f"estimates/{self.r['current_estimate_id']}", method="HEAD", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(raw, b"")
        self.assertIn("ETag", response_headers)
        for route in (f"estimates/{self.r['hidden_estimate_id']}", f"projects/{self.r['hidden_project_id']}/estimate-preparation",
                      "estimates?projectId=" + self.r["hidden_project_id"]):
            status, _, body = self.api(route, headers=headers)
            self.assertEqual(status, 404, body)
            self.assertNotIn("hidden", json.dumps(body).lower())
        for query in ("top=0", "top=51", "top=1&top=2", "search=", "actor=owner", "cursor=wrong"):
            self.assertEqual(self.api("estimates?" + query, headers=headers)[0], 422, query)
        self.assertEqual(before, self.snapshot())

    def test_strict_json_bodies_cannot_supply_identity_authority_or_approximate_values(self):
        headers = self.session()
        route = f"projects/{self.r['project_id']}/create-estimate:preflight"
        invalid = []
        for field, value in (("actor", "owner"), ("role", "estimator"), ("provider", {}), ("supplierId", self.r["supplier_id"]),
                             ("packageId", self.r["package_id"]), ("mode", "live"), ("path", "live.sqlite")):
            invalid.append(json.dumps({**self.input(), field: value}))
        for value in (1.25, True, "1e3", "1,000", "-1", "NaN"):
            body = self.input()
            body["lines"][0]["quantity"] = value
            invalid.append(json.dumps(body))
        for value in (1.0, True, -1, "2500"):
            body = self.input()
            body["lines"][0]["unitPriceCents"] = value
            invalid.append(json.dumps(body))
        invalid.extend(('[]', '{}', '{"lines":[],"lines":[]}', json.dumps(self.input()).replace('"unitPriceCents": 2500', '"unitPriceCents": NaN')))
        before = self.snapshot()
        for raw in invalid:
            status, _, body = self.api(route, method="POST", headers=headers, body=raw)
            self.assertEqual(status, 422, (raw, body))
            self.assertEqual(body["contractVersion"], "cipher.commercial-practice.v1")
        self.assertEqual(before, self.snapshot())

    def test_origin_csrf_host_and_foreign_cookie_fail_before_effect(self):
        headers = self.session()
        route = f"estimates/{self.r['current_estimate_id']}/request-acceptance:preflight"
        before = self.snapshot()
        for overrides in ({"Origin": "https://example.invalid"}, {"Origin": "null"}, {"X-CSRF-Token": "wrong"},
                          {"Host": "example.invalid"}, {"Sec-Fetch-Site": "cross-site"}, {"X-CSRF-Token": ""}):
            status, _, body = self.api(route, method="POST", headers={**headers, **overrides}, body="{}")
            self.assertEqual(status, 403, body)
        no_origin = {key: value for key, value in headers.items() if key != "Origin"}
        self.assertEqual(self.api(route, method="POST", headers=no_origin, body="{}")[0], 403)
        foreign_cookie = {**headers, "Cookie": headers["Cookie"].replace(COOKIE_NAME, "cipher_ap_practice")}
        self.assertEqual(self.api("estimates", headers=foreign_cookie)[0], 401)
        self.assertEqual(before, self.snapshot())

    def test_repeatability_and_quoted_version_headers_are_required_and_current_duty_precedes_retry(self):
        headers = self.session()
        route = f"estimates/{self.r['current_estimate_id']}/request-acceptance"
        request = self.prepared(headers, route)
        before = self.snapshot()
        for override in ({"If-Match": request[1]["If-Match"].strip('"')}, {"If-Match": 'W/"stale"'},
                         {"Repeatability-Request-ID": "not-a-uuid"}):
            status, _, body = self.send((route, {**request[1], **override}, request[2]))
            self.assertEqual(status, 422, body)
        for name in ("If-Match", "Repeatability-Request-ID"):
            missing = {key: value for key, value in request[1].items() if key != name}
            self.assertEqual(self.send((route, missing, request[2]))[0], 400)
        self.assertEqual(before, self.snapshot())
        status, _, original = self.send(request)
        self.assertEqual(status, 200, original)
        changed = json.loads(request[2])
        changed["fingerprint"] = "cmpf1.changed"
        self.assertEqual(self.send((route, request[1], json.dumps(changed)))[0], 409)
        with self.server.cipher_lock:
            self.c.plugin("people").end_membership(ESTIMATOR_LOGIN, self.r["project_id"],
                reason="Synthetic HTTP assignment ended", actor=BOOTSTRAP_LOGIN)
        before = self.snapshot()
        self.assertEqual(self.send(request)[0], 404)
        self.assertEqual(before, self.snapshot())

    def test_independent_estimator_review_is_required_and_pm_cannot_accept(self):
        preparer, pm = self.session(), self.session("pm")
        result, _ = self.act(preparer, f"estimates/{self.r['current_estimate_id']}/request-acceptance")
        approval = result["result"]["approvalId"]
        before = self.snapshot()
        status, _, review = self.api(f"estimate-approvals/{approval}/accept:preflight", method="POST", headers=preparer, body="{}")
        self.assertEqual(status, 200, review)
        self.assertFalse(review["allowed"])
        status, _, body = self.api(f"estimate-approvals/{approval}/accept:preflight", method="POST", headers=pm, body="{}")
        self.assertEqual(status, 403, body)
        self.assertEqual(before, self.snapshot())

    def test_concurrent_identical_requests_commit_one_effect(self):
        request = self.prepared(self.session(), f"estimates/{self.r['current_estimate_id']}/request-acceptance")
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.send(request), range(2)))
        self.assertEqual([value[0] for value in responses], [200, 200], responses)
        first, second = (value[2] for value in responses)
        self.assertEqual(first["receiptId"], second["receiptId"])
        self.assertEqual(sorted((first["replayed"], second["replayed"])), [False, True])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commercial_action_receipts"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE operation='estimate.approve'"), 1)

    def test_response_loss_retains_original_receipt_for_exact_retry(self):
        route, headers, body = self.prepared(self.session(), f"estimates/{self.r['current_estimate_id']}/request-acceptance")
        raw = (f"POST {API_PREFIX + route} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n" +
               "".join(f"{key}: {value}\r\n" for key, value in headers.items()) +
               f"Content-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n" + body).encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as conn:
            conn.sendall(raw)
            conn.shutdown(socket.SHUT_RDWR)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.cipher_lock:
                if self.c.db.scalar("SELECT COUNT(*) FROM commercial_action_receipts") == 1:
                    break
            time.sleep(0.01)
        else:
            self.fail("The disconnected request did not retain its committed receipt")
        before = self.snapshot()
        status, _, replay = self.send((route, headers, body))
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["effectApplied"])
        self.assertEqual(before, self.snapshot())

    def test_late_receipt_failure_rolls_back_actual_http_effect(self):
        request = self.prepared(self.session(), f"estimates/{self.r['current_estimate_id']}/request-acceptance")
        before = self.snapshot()[0]
        with patch.object(self.server.actions.receipts, "record", side_effect=RuntimeError("private internal failure")):
            status, _, body = self.send(request)
        self.assertEqual(status, 500, body)
        self.assertNotIn("private internal failure", json.dumps(body))
        self.assertEqual(before, self.snapshot()[0])
        status, _, result = self.send(request)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["replayed"])

    def test_static_csp_nonce_spa_path_escape_and_fixed_methods(self):
        before = self.snapshot()
        status, headers, page = self.request("/estimates/one")
        self.assertEqual(status, 200)
        self.assertNotIn(b"__CIPHER_STYLE_NONCE__", page)
        nonce = page.decode().split('content="', 1)[1].split('"', 1)[0]
        self.assertIn("'nonce-" + nonce + "'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("/assets/app.js")[0], 200)
        for path in ("/../AGENTS.md", "/%2e%2e/AGENTS.md", "/api/ap-practice/v1/session", "/api/commercial-practice/v1/action"):
            self.assertIn(self.request(path)[0], (400, 404))
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "secret.js"
            secret.write_text("private outside bytes", encoding="utf-8")
            (self.root / "assets" / "escape.js").symlink_to(secret)
            self.assertEqual(self.request("/assets/escape.js")[0], 404)
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            status, headers, _ = self.request(API_PREFIX + "session", method=method, headers={"Origin": self.origin})
            self.assertEqual(status, 405)
            self.assertEqual(headers["Allow"], "GET, HEAD, POST")
        self.assertEqual(before, self.snapshot())

    def test_foreign_source_and_previous_line_fail_before_private_creation_plan(self):
        headers = self.session()
        hidden = self.c.plugin("commercial").source(self.r["hidden_estimate_id"])
        typed = self.input()
        typed["documentRevisionId"] = hidden["drawing"]["revisionId"]
        before = self.snapshot()
        with patch.object(self.c.plugin("commercial"), "create_preflight", side_effect=AssertionError("scope before material")) as create:
            status, _, body = self.api(f"projects/{self.r['project_id']}/create-estimate:preflight", method="POST",
                                       headers=headers, body=json.dumps(typed))
            self.assertEqual(status, 404, body)
            create.assert_not_called()
        typed = self.input()
        typed["lines"][0]["previousLineId"] = hidden["lines"][0]["estimate_line_id"]
        typed["removedExclusions"] = []
        status, _, body = self.api(f"estimates/{self.r['current_estimate_id']}/revise:preflight", method="POST",
                                   headers=headers, body=json.dumps(typed))
        self.assertEqual(status, 404, body)
        self.assertNotIn(hidden["estimateId"], json.dumps(body))
        self.assertEqual(before, self.snapshot())

    def test_stale_review_and_duplicate_effect_headers_do_not_commit(self):
        headers = self.session()
        route, effect_headers, body = self.prepared(headers, f"estimates/{self.r['current_estimate_id']}/request-acceptance")
        before = self.snapshot()
        for duplicate in ("If-Match", "Repeatability-Request-ID"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.putrequest("POST", API_PREFIX + route)
                for key, value in {**effect_headers, "Content-Length": str(len(body.encode()))}.items():
                    conn.putheader(key, value)
                conn.putheader(duplicate, effect_headers[duplicate])
                conn.endheaders(body.encode())
                response = conn.getresponse()
                self.assertEqual(response.status, 400, (duplicate, response.read()))
                response.read()
            finally:
                conn.close()
        self.assertEqual(before, self.snapshot())
        with self.server.cipher_lock:
            additional = self.c.evidence.register_document(project_id=self.r["project_id"], kind="drawing",
                title="Genuine additional source after HTTP review", actor=ESTIMATOR_LOGIN)
            self.c.evidence.add_revision(document_id=additional["id"], content="Genuine additional synthetic drawing source",
                                         note="Added after the HTTP review", actor=ESTIMATOR_LOGIN)
        before = self.snapshot()
        status, _, result = self.send((route, effect_headers, body))
        self.assertEqual(status, 412, result)
        self.assertEqual(before, self.snapshot())

    def test_expired_or_absent_session_cannot_read_or_preview(self):
        # Create and expire sessions on one exact, deterministic clock.
        now = 1000.0
        self.server.sessions.clock = lambda: now
        for headers in ({}, self.anonymous()[0], {"Cookie": COOKIE_NAME + "=" + "x" * 43}):
            self.assertEqual(self.api("estimates", headers=headers)[0], 401)
        headers = self.session()
        now += IDLE_SECONDS - 1
        self.assertEqual(self.api("estimates", headers=headers)[0], 200)
        # The successful read refreshed activity; expire exactly at its cutoff.
        now += IDLE_SECONDS
        before = self.snapshot()
        self.assertEqual(self.api("estimates", headers=headers)[0], 401)
        status, _, _ = self.api(f"estimates/{self.r['current_estimate_id']}/request-acceptance:preflight",
                                method="POST", headers=headers, body="{}")
        self.assertEqual(status, 401)
        self.assertEqual(before, self.snapshot())

    def test_duplicate_headers_framing_limits_and_mode_refusal_are_typed(self):
        headers = self.session()
        route = API_PREFIX + f"estimates/{self.r['current_estimate_id']}/request-acceptance:preflight"
        before = self.snapshot()
        for duplicate in ("Content-Type", "Content-Length", "Origin", "X-CSRF-Token", "Cookie"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.putrequest("POST", route)
                fields = {**headers, "Content-Length": "2"}
                for key, value in fields.items():
                    conn.putheader(key, value)
                conn.putheader(duplicate, fields[duplicate])
                conn.endheaders(b"{}")
                response = conn.getresponse()
                self.assertEqual(response.status, 400, (duplicate, response.read()))
                response.read()
            finally:
                conn.close()
        status, _, _ = self.request(route, method="POST", headers={**headers, "Transfer-Encoding": "chunked"}, body="{}")
        self.assertEqual(status, 400)
        status, _, _ = self.request(route, method="POST", headers=headers, body=" " * 16385)
        self.assertEqual(status, 413)
        with patch.object(self.server, "require_practice", side_effect=WorkspaceModeError("private mode")):
            status, _, raw = self.request(API_PREFIX + "session")
        self.assertEqual(status, 503)
        self.assertNotIn(b"private mode", raw)
        self.assertEqual(before, self.snapshot())


class CommercialPracticeCommandTests(unittest.TestCase):
    def test_cli_launches_only_fixed_synthetic_server_with_selected_port(self):
        from apps.cipher.__main__ import main
        with patch("apps.cipher.commercial_practice_server.serve_commercial_practice") as serve:
            self.assertEqual(main(["commercial-practice-web"]), 0)
            serve.assert_called_once_with(port=8768)
        with patch("apps.cipher.commercial_practice_server.serve_commercial_practice") as serve:
            self.assertEqual(main(["commercial-practice-web", "--port", "8870"]), 0)
            serve.assert_called_once_with(port=8870)

    def test_cli_refuses_workspace_or_host_selector_and_reports_start_failure(self):
        from apps.cipher.__main__ import main
        for extra in (("--db", "live.sqlite"), ("--host", "0.0.0.0"), ("--provider", "live")):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["commercial-practice-web", *extra])
            self.assertEqual(caught.exception.code, 2)
        error = io.StringIO()
        with patch("apps.cipher.commercial_practice_server.serve_commercial_practice", side_effect=OSError("Port unavailable")), redirect_stderr(error):
            self.assertEqual(main(["commercial-practice-web"]), 2)
        self.assertIn("Port unavailable", error.getvalue())


if __name__ == "__main__":
    unittest.main()
