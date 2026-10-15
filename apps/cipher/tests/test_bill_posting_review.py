"""Independent adversarial checks for historical and current posting proof."""
import unittest

from apps.cipher.domain.bills import BillError
from apps.cipher.domain.payments import PaymentError
from apps.cipher.tests import test_bill_service_split as fixtures


class BillPostingReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BillServiceSplitTests("test_grant_records_approved_state_without_journal")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.c, self.bill = self.fixture.c, self.fixture.bill

    def post(self):
        approval = self.fixture.grant()
        self.c.post_bill(self.bill["id"], actor="poster")
        return approval

    def fake_legacy_posting(self):
        self.c.db.execute("DROP TRIGGER bills_status_transitions")
        plan = self.c.bills.journal_preview(self.bill["id"])[0]
        journal = self.c.ledger.post(
            period_id=plan["period_id"], description="Unrelated synthetic entry", lines=plan["lines"],
            source_type="unrelated_source", source_id="unrelated_record", source_version="1", posted_by="poster",
        )
        self.c.db.execute("UPDATE bills SET status='posted',journal_id=? WHERE id=?", (journal["id"], self.bill["id"]))

    def verify_destination(self):
        supplier_id = self.c.bills.get(self.bill["id"])["supplier_id"]
        self.c.verify_destination(supplier_id, destination="SIM-REVIEW-DESTINATION", verified_by="reviewer")

    def test_unapproved_new_bill_cannot_use_an_unrelated_journal_as_legacy_proof(self):
        self.fake_legacy_posting()
        with self.assertRaises(BillError):
            self.c.bills.posting_receipt(self.bill["id"])
        self.assertFalse(all(check["ok"] for check in self.c.bills.lifecycle_integrity_checks(self.bill["id"])))

    def test_false_legacy_posting_cannot_request_payment(self):
        self.fake_legacy_posting()
        self.verify_destination()
        with self.assertRaises((BillError, PaymentError)):
            self.c.request_approval("payment.release", self.bill["id"], actor_role="treasury", requested_by="poster")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM payment_intents"), 0)

    def test_posted_bill_amount_must_match_original_business_snapshot(self):
        self.post()
        self.c.db.execute("DROP TRIGGER bills_posted_figures_immutable")
        self.c.db.execute("UPDATE bills SET amount_due='990.00' WHERE id=?", (self.bill["id"],))
        with self.assertRaises(BillError):
            self.c.bills.posting_receipt(self.bill["id"])

    def test_tampered_posted_amount_cannot_authorize_an_inflated_payment(self):
        self.post()
        self.verify_destination()
        self.c.db.execute("DROP TRIGGER bills_posted_figures_immutable")
        self.c.db.execute("UPDATE bills SET amount_due='990.00' WHERE id=?", (self.bill["id"],))
        with self.assertRaises((BillError, PaymentError)):
            self.c.request_approval("payment.release", self.bill["id"], actor_role="treasury", requested_by="poster")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM payment_intents"), 0)

    def test_posted_bill_lines_must_match_original_business_hash(self):
        self.post()
        self.c.db.execute("DROP TRIGGER bill_lines_posted_immutable")
        self.c.db.execute("UPDATE bill_lines SET cumulative_installed='900.00' WHERE bill_id=?", (self.bill["id"],))
        with self.assertRaises(BillError):
            self.c.bills.posting_receipt(self.bill["id"])

    def test_requester_identity_cannot_be_rewritten_after_business_grant(self):
        approval = self.fixture.grant()
        self.c.db.execute("DROP TRIGGER approvals_request_immutable")
        self.c.db.execute("UPDATE approvals SET requested_by='reviewer' WHERE id=?", (approval["id"],))
        with self.assertRaises(BillError):
            self.c.post_bill(self.bill["id"], actor="poster")
        self.assertIsNone(self.c.bills.get(self.bill["id"])["journal_id"])

    def test_original_journal_source_version_cannot_differ_from_receipt(self):
        self.post()
        journal_id = self.c.bills.get(self.bill["id"])["journal_id"]
        self.c.db.execute("DROP TRIGGER journals_no_update")
        self.c.db.execute("UPDATE journals SET source_version='forged-version' WHERE id=?", (journal_id,))
        with self.assertRaises(BillError):
            self.c.bills.posting_receipt(self.bill["id"])

    def test_completed_posting_proof_survives_later_supplier_display_changes(self):
        self.post()
        supplier_id = self.c.bills.get(self.bill["id"])["supplier_id"]
        self.c.db.execute("UPDATE parties SET name='Synthetic renamed supplier',destination='SIM-NEW' WHERE id=?", (supplier_id,))
        self.assertIsNotNone(self.c.bills.posting_receipt(self.bill["id"]))
        self.assertTrue(all(check["ok"] for check in self.c.bills.lifecycle_integrity_checks(self.bill["id"])))


if __name__ == "__main__":
    unittest.main()
