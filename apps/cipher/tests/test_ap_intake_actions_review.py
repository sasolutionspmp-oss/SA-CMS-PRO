"""Independent regressions for fixed intake effect boundaries."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_intake_actions import APIntakeActionRunner
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_intake_preflight import APIntakePreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.domain.ap_intake import OP_MATCH


class APIntakeActionReviewTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        secret = b"independent-intake-review-server-key-at-least-32-bytes"
        self.base = APContract(self.c, secret=secret)
        self.contract = APIntakeContract(self.c, self.base, secret=secret)
        self.preflight = APIntakePreflight(self.c, self.contract, secret=secret)
        self.runner = APIntakeActionRunner(self.c, self.contract, self.preflight)
        self.person = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.login = self.c.ap_practice_persona_people["accountant"]["login"]
        self.ap = self.c.plugin("ap_intake")

    def invoice_for_bill(self, bill_id, evidence_id, number):
        bill = self.c.bills.get(bill_id)
        commitment = self.c.commitments.get(bill["commitment_id"])
        evidence = self.c.db.one("SELECT content_hash FROM document_revisions WHERE id=?", (evidence_id,))
        invoice = self.ap.receive_invoice(commitment["supplier_id"], number, "2026-10-14", bill["amount_due"],
            evidence["content_hash"], self.login, project_id=bill["project_id"], commitment_id=bill["commitment_id"])
        self.ap.match(invoice["id"], self.login)
        return invoice["id"]

    def args(self, action, resource, body=None):
        body = body or {}
        review = self.preflight.review(self.person, action, resource, body)
        self.assertTrue(review["allowed"], review)
        return {"person_id": self.person, "action": action, "resource_id": resource,
                "body": {**body, "fingerprint": review["fingerprint"]},
                "if_match": review["resourceVersion"], "repeatability_key": str(uuid4())}

    def test_success_return_cannot_create_an_unreviewed_second_match_approval(self):
        records = self.c.ap_practice_records
        commitment = self.c.commitments.get(records["prep_commitment_id"])
        prepared = self.c.bills.certify(commitment_id=commitment["id"], period_id="2026-10", installed=[
            {"sov_line_id": line["id"], "cumulative_installed": amount}
            for line, amount in zip(commitment["sov"], ("1000.00", "2000.00"))], actor=self.login)
        intended = self.invoice_for_bill(prepared["id"], records["visible_invoice_evidence_revision_ids"][0], "SYN-REVIEW-INTENDED")
        other = self.invoice_for_bill(records["draft_bill_id"], records["visible_invoice_evidence_revision_ids"][1], "SYN-REVIEW-OTHER")
        request = self.args("invoice.requestMatchApproval", intended)
        before = tuple(self.c.db.conn.iterdump())
        original_request = self.c.request_approval

        def extra_approval(operation, subject_id, **kwargs):
            result = original_request(operation, subject_id, **kwargs)
            original_request(OP_MATCH, other, actor_role="accountant", requested_by=self.login)
            return result

        with patch.object(self.c, "request_approval", side_effect=extra_approval):
            with self.assertRaises(APRefusal) as refused:
                self.runner.run(**request)
        self.assertEqual(refused.exception.status, 500)
        self.assertEqual(tuple(self.c.db.conn.iterdump()), before)

    def test_receive_retry_refuses_current_invoice_lifecycle_without_audited_match(self):
        records = self.c.ap_practice_records
        request = self.args("invoice.receive", records["prep_commitment_id"], {
            "invoiceNumber": "SYN-REVIEW-LIFECYCLE", "invoiceDate": "2026-10-14", "amountCents": 270_000,
            "evidenceRevisionId": records["visible_invoice_evidence_revision_ids"][0]})
        first = self.runner.run(**request)
        invoice_id = first["result"]["invoiceId"]
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='ap_invoices'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        self.c.db.conn.execute("UPDATE ap_invoices SET status='matched',matched_by='raw.unapproved.actor' WHERE id=?", (invoice_id,))
        before = tuple(self.c.db.conn.iterdump())
        with self.assertRaises(APRefusal) as refused:
            self.runner.run(**request)
        self.assertEqual(refused.exception.status, 500)
        self.assertEqual(tuple(self.c.db.conn.iterdump()), before)
        self.assertFalse(all(check["ok"] for check in self.runner.integrity_checks()))

    def test_prepare_retry_refuses_current_bill_approval_without_audited_grant(self):
        records = self.c.ap_practice_records
        commitment = self.c.commitments.get(records["prep_commitment_id"])
        request = self.args("bill.prepare", commitment["id"], {"periodId": "2026-10", "installed": [
            {"sovLineId": line["id"], "cumulativeInstalledCents": amount}
            for line, amount in zip(commitment["sov"], (100_000, 200_000))]})
        first = self.runner.run(**request)
        bill_id = first["result"]["billId"]
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bills'"):
            self.c.db.conn.execute('DROP TRIGGER "' + trigger["name"].replace('"', '""') + '"')
        self.c.db.conn.execute("UPDATE bills SET status='approved' WHERE id=?", (bill_id,))
        before = tuple(self.c.db.conn.iterdump())
        with self.assertRaises(APRefusal) as refused:
            self.runner.run(**request)
        self.assertEqual(refused.exception.status, 500)
        self.assertEqual(tuple(self.c.db.conn.iterdump()), before)
        self.assertFalse(all(check["ok"] for check in self.runner.integrity_checks()))


if __name__ == "__main__":
    unittest.main()
