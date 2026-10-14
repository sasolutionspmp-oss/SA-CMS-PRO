"""Independent HTTP checks for scoped action review and usable safe errors."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
import uuid

from apps.cipher.ap_practice_server import APPracticeHandler, make_ap_practice_server
from apps.cipher.ap_sessions import ABSOLUTE_SECONDS


PREFIX = "/api/ap-practice/v1/"


class APBoundaryReviewTests(unittest.TestCase):
    def setUp(self):
        self.server = make_ap_practice_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.records = self.server.cipher.ap_practice_records

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, route, *, method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, PREFIX + route, headers=headers or {},
                               body=json.dumps(body) if body is not None else None)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            connection.close()

    def session(self, persona="accountant"):
        status, headers, anonymous = self.request("session")
        self.assertEqual(status, 200)
        credentials = {"Origin": self.origin, "Content-Type": "application/json",
                       "Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": anonymous["csrfToken"]}
        status, headers, bound = self.request("session", method="POST", headers=credentials, body={"personaId": persona})
        self.assertEqual(status, 200)
        credentials.update(Cookie=headers["Set-Cookie"].split(";", 1)[0])
        credentials["X-CSRF-Token"] = bound["csrfToken"]
        return credentials, bound

    def snapshot(self):
        with self.server.cipher_lock:
            c = self.server.cipher
            return ("\n".join(c.db.conn.iterdump()), c.db.conn.total_changes,
                    tuple(c.provider.submissions), dict(c.provider.transfers))

    def test_safe_http_error_uses_supported_problem_shape(self):
        status, _, value = self.request("bills")
        self.assertEqual(status, 401)
        error = value["error"]
        self.assertIsInstance(error["code"], str)
        self.assertIsInstance(error["message"], str)
        self.assertTrue(error.get("fix") is None or isinstance(error["fix"], str))
        self.assertTrue(error["target"] is None or isinstance(error["target"], str))

    def test_session_expiry_during_body_read_refuses_before_posting_effects(self):
        credentials, _ = self.session()
        bill_id = self.records["approved_bill_id"]
        route = "bills/" + bill_id + "/post"
        body = {"periodId": "2026-10", "reason": ""}
        status, _, review = self.request(route + ":preflight", method="POST", headers=credentials, body=body)
        self.assertEqual(status, 200)
        self.assertTrue(review["allowed"])
        token = credentials["Cookie"].partition("=")[2]
        current = self.server.sessions._sessions[token]
        before = self.snapshot()
        original_body = APPracticeHandler._body

        def expired_while_reading(handler, **kwargs):
            value = original_body(handler, **kwargs)
            handler.server.sessions.clock = lambda: current.created_at + ABSOLUTE_SECONDS
            return value

        with patch.object(APPracticeHandler, "_body", expired_while_reading):
            status, _, result = self.request(route, method="POST",
                headers={**credentials, "If-Match": '"' + review["resourceVersion"] + '"',
                         "Repeatability-Request-ID": str(uuid.uuid4())},
                body={**body, "fingerprint": review["fingerprint"]})
        self.assertEqual(status, 401, result)
        self.assertEqual(before, self.snapshot())

    def test_quoted_detail_etag_matches_current_review_and_refuses_unquoted_action(self):
        credentials, _ = self.session()
        bill_id = self.records["approved_bill_id"]
        status, detail_headers, detail = self.request("bills/" + bill_id, headers=credentials)
        self.assertEqual(status, 200)
        self.assertEqual(detail_headers["ETag"], '"' + detail["version"] + '"')
        route = "bills/" + bill_id + "/post"
        body = {"periodId": "2026-10", "reason": ""}
        status, _, review = self.request(route + ":preflight", method="POST", headers=credentials, body=body)
        self.assertEqual(status, 200)
        self.assertEqual(detail["version"], review["resourceVersion"])
        before = self.snapshot()
        repeatability = str(uuid.uuid4())
        status, _, refused = self.request(route, method="POST",
            headers={**credentials, "If-Match": review["resourceVersion"], "Repeatability-Request-ID": repeatability},
            body={**body, "fingerprint": review["fingerprint"]})
        self.assertEqual(status, 422, refused)
        self.assertEqual(before, self.snapshot())
        status, _, result = self.request(route, method="POST",
            headers={**credentials, "If-Match": detail_headers["ETag"], "Repeatability-Request-ID": repeatability},
            body={**body, "fingerprint": review["fingerprint"]})
        self.assertEqual(status, 200, result)
        self.assertTrue(result["effectApplied"])

    def test_scope_loss_refuses_committed_receipt_replay_without_disclosing_receipt(self):
        credentials, session = self.session()
        bill_id = self.records["approved_bill_id"]
        route = "bills/" + bill_id + "/post"
        body = {"periodId": "2026-10", "reason": ""}
        status, _, review = self.request(route + ":preflight", method="POST", headers=credentials, body=body)
        self.assertEqual(status, 200)
        action_headers = {**credentials, "If-Match": '"' + review["resourceVersion"] + '"',
                          "Repeatability-Request-ID": str(uuid.uuid4())}
        action_body = {**body, "fingerprint": review["fingerprint"]}
        status, _, posted = self.request(route, method="POST", headers=action_headers, body=action_body)
        self.assertEqual(status, 200, posted)
        with self.server.cipher_lock:
            c = self.server.cipher
            project_id = c.bills.get(bill_id)["project_id"]
            person = c.db.one("SELECT login FROM people_persons WHERE id=?", (session["person"]["id"],))
            c.plugin("people").end_membership(person["login"], project_id, reason="Synthetic project authority ended",
                                              actor="practice.bootstrap")
        before = self.snapshot()
        status, _, replay = self.request(route, method="POST", headers=action_headers, body=action_body)
        self.assertEqual(status, 404, replay)
        self.assertNotIn("receiptId", replay)
        self.assertNotIn(posted["receiptId"], json.dumps(replay))
        self.assertEqual(self.request("bills/" + bill_id, headers=credentials)[0], 404)
        self.assertEqual(before, self.snapshot())
