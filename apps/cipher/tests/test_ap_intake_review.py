"""Independent reproduced AP intake source and HTTP boundary regressions."""
import json
import unittest

from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, REVIEWER_LOGIN
from apps.cipher.tests import test_ap_intake_http as http_fixture


class APIntakeReviewTests(unittest.TestCase):
    setUp = http_fixture.APIntakeHTTPTests.setUp
    tearDown = http_fixture.APIntakeHTTPTests.tearDown
    request = http_fixture.APIntakeHTTPTests.request
    session = http_fixture.APIntakeHTTPTests.session
    snapshot = http_fixture.APIntakeHTTPTests.snapshot

    def receive(self):
        c = self.server.cipher
        commitment = c.commitments.get(self.records["visible_commitment_ids"][0])
        revision = c.evidence.revision(self.records["visible_invoice_evidence_revision_ids"][0])
        bill = c.bills.latest(commitment["id"])
        return c.plugin("ap_intake").receive_invoice(
            commitment["supplier_id"], "REVIEW-INTAKE-001", "2026-10-14", bill["amount_due"],
            revision["content_hash"], ACCOUNTANT_LOGIN,
            project_id=commitment["project_id"], commitment_id=commitment["id"])

    def forge_status(self, invoice_id, status):
        c = self.server.cipher
        for trigger in c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoices'"):
            c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        c.db.execute("UPDATE ap_invoices SET status=? WHERE id=?", (status, invoice_id))

    def assert_source_refused_before_reads_and_review(self, invoice_id, headers):
        before = self.snapshot()
        requests = (("invoices/" + invoice_id, "GET", None), ("invoices", "GET", None),
                    ("invoices/" + invoice_id + "/compute-match:preflight", "POST", "{}"))
        for route, method, body in requests:
            with self.subTest(route=route):
                status, _, response = self.request(route, method=method, headers=headers, body=body)
                self.assertEqual((status, response.get("error", {}).get("code")), (422, "invalid_record"), response)
        self.assertEqual(before, self.snapshot())

    def test_rejected_invoice_cannot_be_resurrected_by_a_raw_status_edit(self):
        headers, _ = self.session()
        with self.server.cipher_lock:
            invoice = self.receive()
            self.server.cipher.plugin("ap_intake").reject_invoice(invoice["id"], "Synthetic wrong supplier source", ACCOUNTANT_LOGIN)
            self.forge_status(invoice["id"], "received")
        self.assert_source_refused_before_reads_and_review(invoice["id"], headers)

    def test_matched_invoice_cannot_be_reopened_without_a_new_audited_version(self):
        headers, _ = self.session()
        with self.server.cipher_lock:
            c = self.server.cipher
            ap = c.plugin("ap_intake")
            invoice = self.receive()
            ap.match(invoice["id"], ACCOUNTANT_LOGIN)
            approval = c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
            c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
            c.execute(approval["id"], actor=ACCOUNTANT_LOGIN)
            self.forge_status(invoice["id"], "received")
        self.assert_source_refused_before_reads_and_review(invoice["id"], headers)

    def test_forged_rejection_cannot_release_source_evidence_for_a_new_invoice(self):
        headers, _ = self.session()
        with self.server.cipher_lock:
            invoice = self.receive()
            self.forge_status(invoice["id"], "rejected")
        before = self.snapshot()
        with self.subTest(boundary="evidence list"):
            status, _, response = self.request("invoice-evidence", headers=headers)
            self.assertEqual((status, response.get("error", {}).get("code")), (422, "invalid_record"), response)
        with self.subTest(boundary="receive review"):
            body = {"invoiceNumber": "REVIEW-REUSE-002", "invoiceDate": "2026-10-14", "amountCents": 100,
                    "evidenceRevisionId": self.records["visible_invoice_evidence_revision_ids"][0]}
            route = "commitments/" + invoice["commitment_id"] + "/receive-invoice:preflight"
            status, _, response = self.request(route, method="POST", headers=headers,
                                                body=json.dumps(body))
            self.assertTrue(status >= 400 or response.get("allowed") is False, response)
        self.assertEqual(before, self.snapshot())

    def test_earlier_genuine_match_cannot_replace_the_latest_audited_exception(self):
        headers, _ = self.session()
        with self.server.cipher_lock:
            c = self.server.cipher
            ap = c.plugin("ap_intake")
            invoice = self.receive()
            first = ap.match(invoice["id"], ACCOUNTANT_LOGIN)
            c.bills.void(first["bill"]["id"], actor=ACCOUNTANT_LOGIN, reason="Synthetic canceled draft")
            second = ap.match(invoice["id"], ACCOUNTANT_LOGIN)
            self.assertEqual((first["status"], second["status"]), ("matched", "exception"))
            self.forge_status(invoice["id"], "received")
            c.db.execute("UPDATE ap_invoices SET match_attempt_id=?,match_status='matched',match_exceptions_json='[]' WHERE id=?",
                         (first["attempt_id"], invoice["id"]))
        self.assert_source_refused_before_reads_and_review(invoice["id"], headers)

    def test_duplicate_review_cannot_be_replayed_after_invoice_date_changed(self):
        headers, _ = self.session()
        with self.server.cipher_lock:
            c = self.server.cipher
            ap = c.plugin("ap_intake")
            first = self.receive()
            revision = c.evidence.revision(self.records["visible_invoice_evidence_revision_ids"][1])
            invoice = ap.receive_invoice(first["supplier_id"], "REVIEW-DUPLICATE-002", "2026-10-14", first["amount"],
                                         revision["content_hash"], ACCOUNTANT_LOGIN,
                                         project_id=first["project_id"], commitment_id=first["commitment_id"])
            reviewed = ap.clear_duplicate_flag(invoice["id"], "Original synthetic duplicate facts reviewed", ACCOUNTANT_LOGIN)
            revised = ap.revise_invoice(invoice["id"], ACCOUNTANT_LOGIN, reason="Synthetic supplier changed the invoice date",
                                        invoice_date="2026-10-15")
            self.assertTrue(revised["duplicate_blocking"])
            self.assertIsNone(revised["duplicate_cleared_at"])
            self.forge_status(invoice["id"], "received")
            c.db.execute("UPDATE ap_invoices SET duplicate_cleared_by=?,duplicate_cleared_at=?,duplicate_clear_reason=? WHERE id=?",
                         (reviewed["duplicate_cleared_by"], reviewed["duplicate_cleared_at"], reviewed["duplicate_clear_reason"], invoice["id"]))
        self.assert_source_refused_before_reads_and_review(invoice["id"], headers)


if __name__ == "__main__":
    unittest.main()
