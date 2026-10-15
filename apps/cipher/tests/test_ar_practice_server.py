"""Actual seven-route AR HTTP, original outcomes and safe isolated transport."""
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

from apps.cipher.ar_practice_server import API_PREFIX, COOKIE_NAME, make_ar_practice_server
from apps.cipher.ar_practice_fixture import BOOTSTRAP_LOGIN, PM_LOGIN
from apps.cipher.core.db import WorkspaceModeError


class ARPracticeServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "ar-practice.html").write_text(
            '<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__">'
            '<div id="root"></div><script type="module" src="/assets/app.js"></script>', encoding="utf-8")
        (self.root / "assets" / "app.js").write_text("export const ar = true;", encoding="utf-8")
        self.server = make_ar_practice_server(port=0, webroot=self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.c, self.r = self.server.cipher, self.server.cipher.ar_practice_records

    def request(self, route, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.request(method, route, body=body, headers=headers or {})
            result = conn.getresponse()
            return result.status, dict(result.getheaders()), result.read()
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
        status, received, body = self.api("session", method="POST", headers=headers, body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        headers.update({"Cookie": received["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"]})
        return headers

    def snapshot(self):
        with self.server.cipher_lock:
            return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions), dict(self.c.provider.transfers)

    def input(self):
        return {"claimRevisionId": self.r["claim_revision_id"], "reviewRevisionId": self.r["review_revision_id"], "periodId": self.r["period_id"],
                "lines": [{"lineId": "U1", "claimedCumulative": "12", "reviewedCumulative": "10", "differenceReason": "Two claimed items unverified",
                           "claimSourceLocator": "Claim page 1, U1", "reviewSourceLocator": "Review page 2, U1"},
                          {"lineId": "L2", "claimedCumulative": "15000", "reviewedCumulative": "12500", "differenceReason": "Testing incomplete",
                           "claimSourceLocator": "Claim page 1, L2", "reviewSourceLocator": "Review page 2, L2"}]}

    def prepared(self, headers, route, body=None):
        typed = {} if body is None else body
        before = self.snapshot()
        status, _, review = self.api(route + ":preflight", method="POST", headers=headers, body=json.dumps(typed))
        self.assertEqual(status, 200, review)
        self.assertTrue(review["allowed"], review)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(review["safeEffects"]["externalDelivery"])
        self.assertFalse(review["safeEffects"]["quickBooksAccepted"])
        return route, {**headers, "Repeatability-Request-ID": str(uuid.uuid4()), "If-Match": '"' + review["resourceVersion"] + '"'}, \
            json.dumps({**typed, "fingerprint": review["fingerprint"]})

    def send(self, request):
        route, headers, body = request
        return self.api(route, method="POST", headers=headers, body=body)

    def act(self, headers, route, body=None):
        request = self.prepared(headers, route, body)
        status, _, result = self.send(request)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["effectApplied"])
        self.assertFalse(result["replayed"])
        return result, request

    def granted(self):
        pm, reviewer, poster = self.session(), self.session("reviewer"), self.session("poster")
        first, first_request = self.act(pm, f"owner-bases/{self.r['basis_id']}/prepare-bill", self.input())
        bill = first["result"]["billId"]
        second, second_request = self.act(pm, f"owner-bills/{bill}/request-approval")
        approval = second["result"]["approvalId"]
        third, third_request = self.act(reviewer, f"owner-bill-approvals/{approval}/approve")
        return bill, approval, pm, reviewer, poster, [(first, first_request), (second, second_request), (third, third_request)]

    def test_factory_has_only_loopback_fresh_memory_and_no_identity_workspace_or_provider_selector(self):
        for key, value in (("path", "live.sqlite"), ("host", "0.0.0.0"), ("cipher", self.c), ("actor", "owner"),
                           ("mode", "live"), ("provider", object()), ("credentials", {}), ("policy", {})):
            with self.subTest(key=key), self.assertRaises(TypeError):
                make_ar_practice_server(port=0, **{key: value})
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.c.db.in_memory)
        self.assertTrue(self.c.db.mode_status()["verified"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)

    def test_all_seven_real_routes_preserve_journal_free_grant_original_post_and_synthetic_send(self):
        bill, approval, pm, reviewer, poster, receipts = self.granted()
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.c.receivables.get(bill)["status"], "draft")
        posted, request = self.act(poster, f"owner-bills/{bill}/post")
        receipts.append((posted, request))
        self.assertEqual(posted["result"]["journalCountDelta"], 1)
        self.assertEqual(posted["result"]["arBalanceDeltaCents"], 2025000)
        self.assertEqual(posted["result"]["retainedArDeltaCents"], 225000)
        requested, request = self.act(pm, f"owner-bills/{bill}/request-send")
        receipts.append((requested, request))
        send_approval = requested["result"]["approvalId"]
        granted, request = self.act(reviewer, f"owner-send-approvals/{send_approval}/approve")
        receipts.append((granted, request))
        sent, request = self.act(pm, f"owner-send-approvals/{send_approval}/send")
        receipts.append((sent, request))
        self.assertTrue(sent["result"]["syntheticMailSink"])
        self.assertEqual(sent["result"]["externalDelivery"], "not_attempted")
        status, response_headers, record = self.api(f"owner-bills/{bill}", headers=pm)
        self.assertEqual(status, 200, record)
        self.assertEqual((record["status"], record["effectiveStatus"]), ("sent", "sent_open"))
        self.assertEqual(record["businessApproval"]["status"], "granted")
        self.assertEqual(record["businessApproval"]["authorizationStatus"], "consumed")
        self.assertEqual(record["send"]["status"], "sent_to_synthetic_sink")
        self.assertEqual(response_headers["ETag"], '"' + record["version"] + '"')
        self.assertEqual((record["invoiceDate"], record["dueDate"]), ("2026-10-01", "2026-10-31"))
        self.assertNotEqual(record["claimSource"]["documentId"], record["reviewSource"]["documentId"])
        self.assertTrue(all(link["apiRoute"].startswith(API_PREFIX) for link in record["relatedRecords"]))
        for route in (f"owner-bill-approvals/{approval}/packet", f"owner-send-approvals/{send_approval}/packet", f"owner-bills/{bill}/send-preparation"):
            self.assertEqual(self.api(route, headers=pm)[0], 200)
        for original, request in receipts:
            before = self.snapshot()
            status, _, replay = self.send(request)
            self.assertEqual(status, 200, replay)
            self.assertEqual(replay, {**original, "replayed": True, "effectApplied": False})
            self.assertEqual(before, self.snapshot())
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ar_action_receipts"), 7)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM outbox"), 0)
        self.assertFalse(self.c.provider.submissions)
        self.assertFalse(self.c.provider.transfers)

    def test_scoped_collection_preparation_aging_and_head_reads_are_pure_and_exact(self):
        headers = self.session()
        before = self.snapshot()
        for route in ("projects", "owner-bases", "owner-bills", "owner-bill-approvals", "owner-send-approvals",
                      "ar-aging?asOf=2026-10-31", "retainage-aging?asOf=2026-11-30"):
            status, _, body = self.api(route, headers=headers)
            self.assertEqual(status, 200, body)
            self.assertNotIn(self.r["hidden_project_id"], json.dumps(body))
            self.assertNotIn(self.r["hidden_basis_id"], json.dumps(body))
        status, _, prep = self.api(f"owner-bases/{self.r['basis_id']}/preparation", headers=headers)
        self.assertEqual(status, 200, prep)
        self.assertEqual(prep["claimSources"][0]["revisionId"], self.r["claim_revision_id"])
        self.assertEqual(prep["reviewSources"][0]["revisionId"], self.r["review_revision_id"])
        self.assertEqual(prep["previous"]["certifiedCents"], 0)
        status, received, raw = self.request(API_PREFIX + f"owner-bases/{self.r['basis_id']}/preparation", method="HEAD", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(raw, b"")
        self.assertIn("ETag", received)
        for route in (f"owner-bases/{self.r['hidden_basis_id']}/preparation", "owner-bills?projectId=" + self.r["hidden_project_id"],
                      "ar-aging?projectId=" + self.r["hidden_project_id"]):
            self.assertEqual(self.api(route, headers=headers)[0], 404)
        for route in ("ar-aging?asOf=2026-02-29", "ar-aging?asOf=2026-10-31T00:00:00Z", "owner-bills?top=1&top=2", "owner-bills?actor=owner"):
            self.assertEqual(self.api(route, headers=headers)[0], 422)
        self.assertEqual(before, self.snapshot())

    def test_session_personas_rotation_expiry_and_foreign_application_cookie(self):
        status, _, personas = self.api("personas")
        self.assertEqual(status, 200)
        self.assertEqual({item["personaId"] for item in personas["value"]}, {"preparer", "reviewer", "poster", "controller"})
        headers, anonymous = self.anonymous()
        status, response_headers, selected = self.api("session", method="POST", headers=headers, body='{"personaId":"preparer"}')
        self.assertEqual(status, 200, selected)
        current = {**headers, "Cookie": response_headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": selected["csrfToken"]}
        self.assertNotEqual(current["Cookie"], headers["Cookie"])
        self.assertNotEqual(selected["csrfToken"], anonymous["csrfToken"])
        self.assertEqual(self.api("owner-bills", headers=headers)[0], 401)
        self.assertEqual(self.api("owner-bills", headers={**current, "Cookie": current["Cookie"].replace(COOKIE_NAME, "cipher_ap_practice")})[0], 401)
        self.assertEqual(self.api("session/logout", method="POST", headers=current, body="{}")[0], 200)
        self.assertEqual(self.api("owner-bills", headers=current)[0], 401)
        current = self.session()
        stored = self.server.sessions._sessions[current["Cookie"].partition("=")[2]]
        self.server.sessions.clock = lambda: stored.last_seen + 1800
        self.assertEqual(self.api("owner-bills", headers=current)[0], 401)

    def test_origin_csrf_identity_forgery_and_strict_exact_bodies_refuse_without_effect(self):
        headers = self.session()
        route = f"owner-bases/{self.r['basis_id']}/prepare-bill:preflight"
        before = self.snapshot()
        for override in ({"Origin": "https://example.invalid"}, {"Host": "example.invalid"},
                         {"X-CSRF-Token": "wrong"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.api(route, method="POST", headers={**headers, **override}, body=json.dumps(self.input()))[0], 403)
        for field in ("actor", "provider", "invoiceDate", "retainageRate", "recipients", "previousCertifiedCents"):
            self.assertEqual(self.api(route, method="POST", headers=headers, body=json.dumps({**self.input(), field: "injected"}))[0], 422)
        for value in (True, 1, 1.0, "1e3", "-1"):
            body = self.input()
            body["lines"][0]["claimedCumulative"] = value
            self.assertEqual(self.api(route, method="POST", headers=headers, body=json.dumps(body))[0], 422)
        for raw in ('[]', '{"lines":[],"lines":[]}', '{"value":NaN}'):
            self.assertEqual(self.api(route, method="POST", headers=headers, body=raw)[0], 422)
        self.assertEqual(before, self.snapshot())

    def test_reviewer_cannot_post_controller_can_post_and_controller_cannot_send(self):
        bill, approval, _, reviewer, _, _ = self.granted()
        before = self.snapshot()
        status, _, review = self.api(f"owner-bills/{bill}/post:preflight", method="POST", headers=reviewer, body="{}")
        self.assertEqual(status, 200, review)
        self.assertFalse(review["allowed"])
        self.assertEqual(before, self.snapshot())
        controller = self.session("controller")
        posted, _ = self.act(controller, f"owner-bills/{bill}/post")
        self.assertEqual(posted["result"]["approvalId"], approval)
        self.assertEqual(self.api(f"owner-bills/{bill}/request-send:preflight", method="POST", headers=controller, body="{}")[0], 403)

    def test_concurrent_post_has_one_original_journal_and_same_receipt(self):
        bill, _, _, _, poster, _ = self.granted()
        request = self.prepared(poster, f"owner-bills/{bill}/post")
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.send(request), range(2)))
        self.assertEqual([item[0] for item in responses], [200, 200], responses)
        self.assertEqual(responses[0][2]["receiptId"], responses[1][2]["receiptId"])
        self.assertEqual(sum(item[2]["effectApplied"] for item in responses), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM owner_billing_postings"), 1)

    def test_actual_dropped_tcp_response_preserves_committed_original_draft_receipt(self):
        route, headers, body = self.prepared(self.session(), f"owner-bases/{self.r['basis_id']}/prepare-bill", self.input())
        raw = (f"POST {API_PREFIX + route} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n" +
               "".join(f"{key}: {value}\r\n" for key, value in headers.items()) +
               f"Content-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n" + body).encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as conn:
            conn.sendall(raw)
            conn.shutdown(socket.SHUT_RDWR)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.cipher_lock:
                if self.c.db.scalar("SELECT COUNT(*) FROM ar_action_receipts"):
                    break
            time.sleep(0.01)
        else:
            self.fail("The disconnected request did not preserve its committed original receipt")
        before = self.snapshot()
        status, _, replay = self.send((route, headers, body))
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["effectApplied"])
        self.assertEqual(before, self.snapshot())

    def test_late_post_receipt_failure_restores_grant_journal_and_command(self):
        bill, approval, _, _, poster, _ = self.granted()
        request = self.prepared(poster, f"owner-bills/{bill}/post")
        before = self.snapshot()[0]
        with patch.object(self.server.actions.receipts, "record", side_effect=RuntimeError("private injected receipt fault")):
            status, _, refusal = self.send(request)
        self.assertEqual(status, 500, refusal)
        self.assertNotIn("private injected", json.dumps(refusal))
        self.assertEqual(before, self.snapshot()[0])
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.send(request)[0], 200)

    def test_current_duty_precedes_retry_and_required_uuid_quoted_version_are_strict(self):
        request = self.prepared(self.session(), f"owner-bases/{self.r['basis_id']}/prepare-bill", self.input())
        before = self.snapshot()
        for override in ({"If-Match": request[1]["If-Match"].strip('"')}, {"If-Match": 'W/"old"'}, {"Repeatability-Request-ID": "invalid"}):
            self.assertEqual(self.send((request[0], {**request[1], **override}, request[2]))[0], 422)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.send(request)[0], 200)
        body = json.loads(request[2]); body["fingerprint"] = "arpf1.changed"
        self.assertEqual(self.send((request[0], request[1], json.dumps(body)))[0], 409)
        with self.server.cipher_lock:
            self.c.plugin("people").end_membership(PM_LOGIN, self.r["project_id"], reason="Synthetic AR assignment ended", actor=BOOTSTRAP_LOGIN)
        before = self.snapshot()
        self.assertEqual(self.send(request)[0], 404)
        self.assertEqual(before, self.snapshot())

    def test_foreign_claim_and_review_refs_are_not_dereferenced_as_preparation_sources(self):
        headers = self.session()
        route = f"owner-bases/{self.r['basis_id']}/prepare-bill:preflight"
        before = self.snapshot()
        with patch.object(self.c.plugin("owner_billing"), "prepare_preflight", side_effect=AssertionError("scope before source plan")) as prepare:
            for field, hidden in (("claimRevisionId", self.r["hidden_claim_revision_id"]),
                                  ("reviewRevisionId", self.r["hidden_review_revision_id"])):
                typed = self.input(); typed[field] = hidden
                status, _, body = self.api(route, method="POST", headers=headers, body=json.dumps(typed))
                self.assertEqual(status, 404, body)
                self.assertNotIn(hidden, json.dumps(body))
            prepare.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_unchanged_zero_progress_is_blocked_at_review_before_native_preparation(self):
        headers = self.session()
        typed = self.input()
        for line in typed["lines"]:
            line.update(claimedCumulative="0", reviewedCumulative="0", differenceReason="")
        before = self.snapshot()
        status, _, review = self.api(f"owner-bases/{self.r['basis_id']}/prepare-bill:preflight",
                                     method="POST", headers=headers, body=json.dumps(typed))
        self.assertEqual(status, 200, review)
        self.assertFalse(review["allowed"])
        self.assertIsNone(review["fingerprint"])
        self.assertEqual(before, self.snapshot())

    def test_duplicate_framing_static_nonce_csp_path_boundaries_and_workspace_mode(self):
        headers = self.session()
        route = API_PREFIX + f"owner-bases/{self.r['basis_id']}/prepare-bill:preflight"
        before = self.snapshot()
        for duplicate in ("Content-Type", "Content-Length", "Origin", "Cookie", "X-CSRF-Token"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.putrequest("POST", route)
                for key, value in {**headers, "Content-Length": "2"}.items():
                    conn.putheader(key, value)
                conn.putheader(duplicate, {**headers, "Content-Length": "2"}[duplicate])
                conn.endheaders(b"{}")
                response = conn.getresponse()
                self.assertEqual(response.status, 400, (duplicate, response.read()))
                response.read()
            finally:
                conn.close()
        self.assertEqual(self.request(route, method="POST", headers=headers, body=" " * 16385)[0], 413)
        status, response_headers, page = self.request("/owner-bills/one")
        self.assertEqual(status, 200)
        nonce = page.decode().split('content="', 1)[1].split('"', 1)[0]
        self.assertIn("'nonce-" + nonce + "'", response_headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response_headers["Content-Security-Policy"])
        self.assertNotIn(b"__CIPHER_STYLE_NONCE__", page)
        self.assertEqual(self.request("/assets/app.js")[0], 200)
        for path in ("/../AGENTS.md", "/%2e%2e/AGENTS.md", "/api/ap-practice/v1/session", "/api/commercial-practice/v1/session"):
            self.assertIn(self.request(path)[0], (400, 404))
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            self.assertEqual(self.request(API_PREFIX + "session", method=method, headers={"Origin": self.origin})[0], 405)
        with patch.object(self.server, "require_practice", side_effect=WorkspaceModeError("private mode failure")):
            status, _, raw = self.request(API_PREFIX + "session")
        self.assertEqual(status, 503)
        self.assertNotIn(b"private mode failure", raw)
        self.assertEqual(before, self.snapshot())


class ARPracticeCommandTests(unittest.TestCase):
    def test_cli_only_accepts_port_and_launches_the_owned_synthetic_server(self):
        from apps.cipher.__main__ import main
        with patch("apps.cipher.ar_practice_server.serve_ar_practice") as serve:
            self.assertEqual(main(["ar-practice-web"]), 0)
            serve.assert_called_once_with(port=8769)
        for extra in (("--db", "live.sqlite"), ("--host", "0.0.0.0"), ("--provider", "live")):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["ar-practice-web", *extra])
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
