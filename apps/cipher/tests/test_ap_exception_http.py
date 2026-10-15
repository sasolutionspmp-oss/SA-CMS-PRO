"""Actual HTTP AP exception, withdrawal and approved correction workflows."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from apps.cipher.ap_practice_server import make_ap_practice_server


PREFIX = "/api/ap-practice/v1/"


class APExceptionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ap-practice.html").write_text(
            '<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__"><div id="root"></div>',
            encoding="utf-8")
        self.server = make_ap_practice_server(port=0, webroot=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.records = self.server.cipher.ap_practice_records
        self.accountant, _ = self.session("accountant")
        self.reviewer, _ = self.session("reviewer")
        self.pm, _ = self.session("pm")

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp.cleanup()

    def request(self, route, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            conn.request(method, PREFIX + route, body=body, headers=headers or {})
            response = conn.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw) if raw else None
        finally:
            conn.close()

    def session(self, persona):
        status, headers, body = self.request("session")
        self.assertEqual(status, 200, body)
        auth = {"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"],
                "Origin": self.origin, "Content-Type": "application/json"}
        status, headers, body = self.request("session", method="POST", headers=auth, body=json.dumps({"personaId": persona}))
        self.assertEqual(status, 200, body)
        auth.update({"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-CSRF-Token": body["csrfToken"]})
        return auth, body

    def snapshot(self):
        with self.server.cipher_lock:
            c = self.server.cipher
            return ("\n".join(c.db.conn.iterdump()), c.db.conn.total_changes,
                    tuple(c.provider.submissions), dict(c.provider.transfers))

    def preflight(self, route, headers, data):
        before = self.snapshot()
        status, _, review = self.request(route + ":preflight", method="POST", headers=headers, body=json.dumps(data))
        self.assertEqual(status, 200, review)
        self.assertEqual(self.snapshot(), before, "Review must not create control or financial effects.")
        return review

    def reviewed_request(self, route, headers, data):
        review = self.preflight(route, headers, data)
        self.assertTrue(review["allowed"], review)
        return ({**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())},
                json.dumps({**data, "fingerprint": review["fingerprint"]}))

    def action(self, route, headers, data, *, replay=True):
        request_headers, body = self.reviewed_request(route, headers, data)
        status, _, result = self.request(route, method="POST", headers=request_headers, body=body)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["effectApplied"], result)
        if replay:
            before = self.snapshot()
            status, _, repeated = self.request(route, method="POST", headers=request_headers, body=body)
            self.assertEqual(status, 200, repeated)
            self.assertTrue(repeated["replayed"])
            self.assertFalse(repeated["effectApplied"])
            self.assertEqual(repeated["result"], result["result"])
            self.assertEqual(repeated["receiptId"], result["receiptId"])
            self.assertEqual(self.snapshot(), before)
        return result

    def installed_body(self, *, period="2026-10", amounts=(100_000, 200_000)):
        commitment = self.server.cipher.commitments.get(self.records["prep_commitment_id"])
        return {"periodId": period, "installed": [
            {"sovLineId": line["id"], "cumulativeInstalledCents": amount}
            for line, amount in zip(commitment["sov"], amounts)]}

    def invoice_body(self, *, number="SYN-EXCEPTION-1001", amount=270_000, evidence_index=0):
        return {"invoiceNumber": number, "invoiceDate": "2026-10-14", "amountCents": amount,
                "evidenceRevisionId": self.records["visible_invoice_evidence_revision_ids"][evidence_index]}

    def receive(self, **kwargs):
        return self.action("commitments/" + self.records["prep_commitment_id"] + "/receive-invoice", self.accountant,
                           self.invoice_body(**kwargs))["result"]["invoiceId"]

    def prepare(self, **kwargs):
        return self.action("commitments/" + self.records["prep_commitment_id"] + "/prepare-bill", self.accountant,
                           self.installed_body(**kwargs))["result"]["billId"]

    def match(self, invoice_id):
        computed = self.action("invoices/" + invoice_id + "/compute-match", self.accountant, {})
        self.assertEqual(computed["result"]["status"], "matched")
        requested = self.action("invoices/" + invoice_id + "/request-match-approval", self.accountant, {})
        approval_id = requested["result"]["approvalId"]
        self.action("match-approvals/" + approval_id + "/approve", self.reviewer, {})
        return self.action("match-approvals/" + approval_id + "/execute", self.accountant, {})

    def grant_and_post(self, bill_id, *, period="2026-10"):
        requested = self.action("bills/" + bill_id + "/request-approval", self.accountant, {})
        self.action("approvals/" + requested["result"]["approvalId"] + "/approve", self.pm, {})
        return self.action("bills/" + bill_id + "/post", self.accountant, {"periodId": period, "reason": ""})

    def test_revision_releases_old_evidence_and_requires_fresh_match_and_business_review(self):
        c = self.server.cipher
        journals = c.db.scalar("SELECT COUNT(*) FROM journals")
        bill_id = self.prepare()
        invoice_id = self.receive()
        self.match(invoice_id)
        business = self.action("bills/" + bill_id + "/request-approval", self.accountant, {})["result"]["approvalId"]
        self.action("approvals/" + business + "/approve", self.pm, {})
        status, headers, review = self.request("invoices/" + invoice_id + "/exception-review", headers=self.accountant)
        self.assertEqual(status, 200, review)
        self.assertEqual(headers["ETag"], '"' + review["version"] + '"')
        revised = self.action("invoices/" + invoice_id + "/revise", self.accountant,
                              {**self.invoice_body(evidence_index=1), "reason": "Supplier replaced its synthetic invoice document"})
        self.assertEqual(revised["result"]["invoiceId"], invoice_id)
        self.assertEqual(c.plugin("ap_intake").invoice(invoice_id)["version"], 2)
        self.assertEqual(c.plugin("ap_intake").invoice(invoice_id)["status"], "received")
        # The original business decision stays recorded. Its invoice facts are
        # stale, so posting must refuse it until a fresh match and review.
        self.assertEqual(c.approvals.get(business)["status"], "granted")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.assertEqual(str(c.bills.open_payable(bill_id)), "0.00")
        status, _, evidence = self.request("invoice-evidence?status=available", headers=self.accountant)
        self.assertEqual(status, 200, evidence)
        available = {row["revisionId"] for row in evidence["value"]}
        self.assertIn(self.records["visible_invoice_evidence_revision_ids"][0], available)
        self.assertNotIn(self.records["visible_invoice_evidence_revision_ids"][1], available)
        self.assertFalse(self.preflight("bills/" + bill_id + "/post", self.accountant, {"periodId": "2026-10", "reason": ""})["allowed"])
        self.match(invoice_id)
        self.assertEqual(c.approvals.get(business)["status"], "invalidated")
        self.grant_and_post(bill_id)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), journals + 1)
        self.assertFalse(c.provider.submissions)

    def test_final_rejection_frees_evidence_but_preserves_reserved_invoice_number(self):
        invoice_id = self.receive()
        c = self.server.cipher
        before_journals = c.db.scalar("SELECT COUNT(*) FROM journals")
        result = self.action("invoices/" + invoice_id + "/reject", self.accountant, {"reason": "Synthetic invoice is not owed"})
        self.assertEqual(result["result"]["invoiceId"], invoice_id)
        self.assertEqual(c.plugin("ap_intake").invoice(invoice_id)["status"], "rejected")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), before_journals)
        self.assertFalse(self.preflight("invoices/" + invoice_id + "/revise", self.accountant,
                                       {**self.invoice_body(), "reason": "Attempt to revise final rejection"})["allowed"])
        self.assertFalse(self.preflight("commitments/" + self.records["prep_commitment_id"] + "/receive-invoice", self.accountant,
                                       self.invoice_body())["allowed"])
        replacement = self.receive(number="SYN-EXCEPTION-REPLACEMENT")
        self.assertNotEqual(replacement, invoice_id)
        self.assertFalse(c.provider.submissions)

    def test_possible_duplicate_requires_documented_review_before_match_request(self):
        bill_id = self.prepare()
        self.receive()
        possible = self.receive(number="SYN-EXCEPTION-1002", evidence_index=1)
        c = self.server.cipher
        self.assertTrue(c.plugin("ap_intake").invoice(possible)["duplicate_blocking"])
        computed = self.action("invoices/" + possible + "/compute-match", self.accountant, {})
        self.assertEqual(computed["result"]["status"], "exception")
        self.assertFalse(self.preflight("invoices/" + possible + "/request-match-approval", self.accountant, {})["allowed"])
        journals = c.db.scalar("SELECT COUNT(*) FROM journals")
        self.action("invoices/" + possible + "/review-duplicate", self.reviewer,
                    {"reason": "Reviewed separate synthetic supplier invoice and its evidence"})
        self.assertFalse(c.plugin("ap_intake").invoice(possible)["duplicate_blocking"])
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.match(possible)
        self.assertEqual(str(c.bills.open_payable(bill_id)), "0.00")
        self.assertFalse(c.provider.submissions)

    def test_draft_cancellation_and_original_pm_withdrawal_require_new_bill_review(self):
        c = self.server.cipher
        draft = self.prepare()
        journal_count = c.db.scalar("SELECT COUNT(*) FROM journals")
        self.action("bills/" + draft + "/cancel", self.accountant, {"reason": "Replace synthetic draft quantities"})
        self.assertEqual(c.bills.get(draft)["status"], "void")
        replacement = self.prepare(amounts=(120_000, 220_000))
        self.assertNotEqual(replacement, draft)
        approved = self.records["approved_bill_id"]
        for person in (self.accountant, self.reviewer):
            status, _, refused = self.request("bills/" + approved + "/cancel:preflight", method="POST", headers=person,
                                               body='{"reason":"Unqualified business withdrawal"}')
            self.assertIn(status, (200, 403), refused)
            if status == 200:
                self.assertFalse(refused["allowed"])
        self.action("bills/" + approved + "/cancel", self.pm, {"reason": "Original PM withdraws synthetic business approval"})
        self.assertEqual(c.bills.get(approved)["status"], "void")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), journal_count)
        self.assertEqual(str(c.bills.open_payable(replacement)), "0.00")
        self.assertFalse(c.provider.submissions)

    def test_posted_bill_correction_is_independently_approved_and_replacement_is_separate(self):
        c = self.server.cipher
        bill_id = self.prepare()
        invoice_id = self.receive()
        self.match(invoice_id)
        self.grant_and_post(bill_id)
        original_journal_count = c.db.scalar("SELECT COUNT(*) FROM journals")
        self.assertEqual(str(c.bills.open_payable(bill_id)), "2700.00")
        revised_body = {**self.invoice_body(amount=450_000, evidence_index=1), "reason": "Replace invoice after approved working correction"}
        self.assertFalse(self.preflight("invoices/" + invoice_id + "/revise", self.accountant, revised_body)["allowed"])
        self.action("bills/" + bill_id + "/prepare-correction", self.accountant, {"reason": "Incorrect synthetic installed quantities"})
        requested = self.action("bills/" + bill_id + "/request-correction", self.accountant, {})
        approval_id = requested["result"]["approvalId"]
        status, headers, packet = self.request("correction-approvals/" + approval_id + "/packet", headers=self.reviewer)
        self.assertEqual(status, 200, packet)
        self.assertEqual(headers["ETag"], '"' + packet["version"] + '"')
        self.assertFalse(self.preflight("correction-approvals/" + approval_id + "/approve", self.accountant, {})["allowed"])
        self.action("correction-approvals/" + approval_id + "/approve", self.reviewer, {})
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), original_journal_count)
        corrected = self.action("correction-approvals/" + approval_id + "/execute", self.accountant, {"periodId": "2026-11"})
        self.assertEqual(corrected["result"]["billId"], bill_id)
        self.assertEqual(c.bills.get(bill_id)["status"], "corrected")
        self.assertEqual(str(c.bills.open_payable(bill_id)), "0.00")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), original_journal_count + 1)
        self.action("invoices/" + invoice_id + "/revise", self.accountant, revised_body)
        replacement = self.prepare(period="2026-11", amounts=(250_000, 250_000))
        self.assertNotEqual(replacement, bill_id)
        self.assertEqual(str(c.bills.open_payable(replacement)), "0.00")
        self.match(invoice_id)
        self.grant_and_post(replacement, period="2026-11")
        self.assertEqual(str(c.bills.open_payable(replacement)), "4500.00")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), original_journal_count + 2)
        self.assertFalse(c.provider.submissions)
        self.assertFalse(c.provider.transfers)
        status, _, decisions = self.request("correction-approvals?status=consumed", headers=self.accountant)
        self.assertEqual(status, 200, decisions)
        self.assertEqual(decisions["count"], 1)
        self.assertEqual(decisions["value"][0]["id"], approval_id)

    def test_exception_references_and_filters_stay_scoped_before_source_lookup(self):
        before = self.snapshot()
        for route in ("correction-approvals?projectId=" + self.records["hidden_project_id"],
                      "bills/" + self.records["hidden_bill_id"] + "/exception-review",
                      "invoices/unreadable/exception-review", "correction-approvals/unreadable/packet"):
            status, _, refused = self.request(route, headers=self.accountant)
            self.assertEqual(status, 404, (route, refused))
            self.assertNotIn("Hidden", json.dumps(refused))
        for route, body in (("bills/" + self.records["hidden_bill_id"] + "/cancel:preflight", {"reason": "Hidden bill probe"}),
                            ("invoices/unreadable/reject:preflight", {"reason": "Unknown invoice probe"})):
            self.assertEqual(self.request(route, method="POST", headers=self.accountant, body=json.dumps(body))[0], 404)
        for query in ("role=owner", "provider=real", "mode=live", "top=1&top=2", "status=bogus"):
            self.assertIn(self.request("correction-approvals?" + query, headers=self.accountant)[0], (400, 422))
        self.assertEqual(self.snapshot(), before)

    def test_exception_action_fields_headers_and_nested_forgery_are_refused(self):
        before = self.snapshot()
        routes = (
            ("invoices/unreadable/revise", {**self.invoice_body(), "reason": "Synthetic revision reason"}),
            ("invoices/unreadable/reject", {"reason": "Synthetic rejection"}),
            ("invoices/unreadable/review-duplicate", {"reason": "Synthetic duplicate review"}),
            ("bills/unreadable/cancel", {"reason": "Synthetic cancellation"}),
            ("bills/unreadable/prepare-correction", {"reason": "Synthetic correction"}),
            ("bills/unreadable/request-correction", {}),
            ("correction-approvals/unreadable/approve", {}),
            ("correction-approvals/unreadable/execute", {"periodId": "2026-11"}),
        )
        for route, body in routes:
            for forged in ("actor", "role", "personId", "operation", "provider", "mode"):
                status, _, refused = self.request(route + ":preflight", method="POST", headers=self.accountant,
                                                   body=json.dumps({**body, forged: "owner"}))
                self.assertEqual(status, 422, (route, refused))
            for malformed in ({"If-Match": "unquoted", "Repeatability-Request-ID": str(uuid.uuid4())},
                              {"If-Match": '"version"', "Repeatability-Request-ID": "bad-key"}):
                self.assertEqual(self.request(route, method="POST", headers={**self.accountant, **malformed},
                                              body=json.dumps({**body, "fingerprint": "unreviewed"}))[0], 422)
        revision = {**self.invoice_body(), "reason": "Synthetic revision"}
        for field, value in (("amountCents", True), ("amountCents", 1.5), ("amountCents", "270000"),
                             ("amountCents", 9_007_199_254_740_992), ("evidenceRevisionId", "../secret"),
                             ("reason", {"actor": "owner"}), ("reason", " "), ("invoiceNumber", ["number"])):
            self.assertEqual(self.request("invoices/unreadable/revise:preflight", method="POST", headers=self.accountant,
                                          body=json.dumps({**revision, field: value}))[0], 422)
        duplicate = '{"reason":"first","reason":"second"}'
        self.assertEqual(self.request("invoices/unreadable/reject:preflight", method="POST", headers=self.accountant, body=duplicate)[0], 422)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_revision_has_one_effect_and_changed_retry_conflicts(self):
        invoice_id = self.receive()
        route = "invoices/" + invoice_id + "/revise"
        data = {**self.invoice_body(amount=280_000), "reason": "Synthetic supplier amount adjustment"}
        headers, body = self.reviewed_request(route, self.accountant, data)
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: self.request(route, method="POST", headers=headers, body=body), range(4)))
        self.assertTrue(all(status == 200 for status, _, _ in outcomes), outcomes)
        self.assertEqual(len({result["receiptId"] for _, _, result in outcomes}), 1)
        self.assertEqual(sum(not result["replayed"] for _, _, result in outcomes), 1)
        self.assertEqual(self.server.cipher.plugin("ap_intake").invoice(invoice_id)["version"], 2)
        changed = json.loads(body)
        changed["reason"] = "Different review after completion"
        before = self.snapshot()
        self.assertEqual(self.request(route, method="POST", headers=headers, body=json.dumps(changed))[0], 409)
        self.assertEqual(self.snapshot(), before)

    def test_current_person_is_rechecked_after_exception_body_and_csrf_is_required(self):
        invoice_id = self.receive()
        route = "invoices/" + invoice_id + "/reject:preflight"
        data = '{"reason":"Synthetic invalid invoice"}'
        before = self.snapshot()
        for changed in ({**self.accountant, "X-CSRF-Token": "bad"}, {**self.accountant, "Origin": "https://outside.example"}):
            self.assertEqual(self.request(route, method="POST", headers=changed, body=data)[0], 403)
        self.assertEqual(self.snapshot(), before)
        from apps.cipher.ap_practice_server import APPracticeHandler
        original = APPracticeHandler._body
        c = self.server.cipher
        def revoke_after_body(handler, **kwargs):
            result = original(handler, **kwargs)
            c.plugin("people").deactivate_person("practice.accountant", reason="Synthetic current-session test", actor="practice.bootstrap")
            return result
        with patch.object(APPracticeHandler, "_body", new=revoke_after_body):
            status, _, refused = self.request(route, method="POST", headers=self.accountant, body=data)
        self.assertEqual(status, 401, refused)
        self.assertEqual(c.plugin("ap_intake").invoice(invoice_id)["status"], "received")
        self.assertFalse(c.provider.submissions)


if __name__ == "__main__":
    unittest.main()
