"""Current AR source proof over original native synthetic contributor history."""
from copy import deepcopy
import unittest

from apps.cipher.ar_practice_fixture import make_ar_practice_fixture, PM_LOGIN, REVIEWER_LOGIN, POSTER_LOGIN
from apps.cipher.domain.owner_billing import OwnerBillingError
from apps.cipher.tests.test_owner_billing import preparation_body


class OwnerBillingContributorTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ar_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.o = self.c.plugin("owner_billing")
        self.r = self.c.ar_practice_records
        self.bill_id = self.o.prepare(self.r["basis_id"], preparation_body(self.c), actor=PM_LOGIN)["primeBillId"]
        approval = self.c.request_approval("prime_bill.approve", self.bill_id, requested_by=PM_LOGIN, actor_role="accountant")
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.post_prime_bill(self.bill_id, actor=POSTER_LOGIN)

    def collect(self):
        return self.c.receivables.record_collection(prime_bill_id=self.bill_id, period_id="2026-10", amount="100", fee="5", method="check",
            provider_ref="OWNER-CHECK-SYNTHETIC-1", actor=POSTER_LOGIN, settlement_date="2026-10-01")

    def raw(self, table, sql, parameters):
        guards = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
        for guard in guards:
            self.c.db.execute(f"DROP TRIGGER {guard['name']}")
        self.c.db.execute(sql, parameters)
        for guard in guards:
            self.c.db.execute(guard["sql"])

    def test_genuine_partial_receipt_and_fee_prove_original_records_journal_and_current_open(self):
        original = self.o.posting_receipt(self.bill_id)
        collection = self.collect()
        current = self.o.current_ar_proof(self.bill_id)
        self.assertEqual((current["currentBill"]["open"], current["collections"]["received"]), ("20150.00", "100.00"))
        proof = current["collections"]["records"][0]
        self.assertEqual(proof["record"]["id"], collection["id"])
        self.assertEqual(proof["qualification"], "historical_synthetic_native_record")
        self.assertEqual([(line["account_code"], line["debit"], line["credit"]) for line in proof["journal"]["lines"]],
                         [("1000", "95.00", "0.00"), ("6000", "5.00", "0.00"), ("1100", "0.00", "100.00")])
        self.assertEqual(self.o.posting_receipt(self.bill_id), original)
        self.assertEqual(self.o.require_current_project_finance(self.r["project_id"])["ar"]["subledger_total"], "20150.00")

    def test_raw_same_id_collection_edits_cannot_change_a_qualified_current_balance_or_fresh_send(self):
        collection = self.collect()
        for key, altered in (("amount", "101.00"), ("fee", "4.00"), ("method", "wire"),
                             ("provider_ref", "UNRELATED-REF"), ("settlement_date", "2026-10-02")):
            original = self.c.db.one("SELECT * FROM collections WHERE id=?", (collection["id"],))[key]
            self.raw("collections", f"UPDATE collections SET {key}=? WHERE id=?", (altered, collection["id"]))
            with self.subTest(key=key):
                with self.assertRaises(OwnerBillingError):
                    self.o.current_ar_proof(self.bill_id)
                with self.assertRaises(OwnerBillingError):
                    self.c._manifest("prime_bill.send", self.bill_id, "pm")
            self.raw("collections", f"UPDATE collections SET {key}=? WHERE id=?", (original, collection["id"]))
        self.assertEqual(self.o.current_ar_proof(self.bill_id)["currentBill"]["open"], "20150.00")

    def test_deleted_collection_is_detected_from_original_birth_even_when_native_balance_reopens(self):
        collection = self.collect()
        self.raw("collections", "DELETE FROM collections WHERE id=?", (collection["id"],))
        self.assertEqual(self.c.receivables.get(self.bill_id)["open"], "20250.00")
        with self.assertRaises(OwnerBillingError):
            self.o.current_ar_proof(self.bill_id)
        with self.assertRaises(OwnerBillingError):
            self.c._manifest("prime_bill.send", self.bill_id, "pm")

    def test_genuine_late_return_proves_exact_inverse_contributor_and_restores_open(self):
        collection = self.collect()
        self.c.ledger.close_period("2026-10", actor=POSTER_LOGIN)
        self.c.receivables.record_return(collection_id=collection["id"], period_id="2026-11",
                                         reason="Synthetic historical check returned", actor=POSTER_LOGIN)
        current = self.o.current_ar_proof(self.bill_id)
        self.assertEqual((current["collections"]["received"], current["currentBill"]["open"]), ("0.00", "20250.00"))
        self.assertIsNotNone(current["collections"]["records"][0]["return"])
        self.assertTrue(self.o.require_current_project_finance(self.r["project_id"])["ar"]["reconciled"])

    def test_raw_removal_of_return_status_cannot_hide_original_returned_birth(self):
        collection = self.collect()
        self.c.receivables.record_return(collection_id=collection["id"], period_id="2026-11",
                                         reason="Synthetic historical check returned", actor=POSTER_LOGIN)
        self.raw("collections", "UPDATE collections SET status='received',return_journal_id=NULL,returned_at=NULL WHERE id=?", (collection["id"],))
        with self.assertRaises(OwnerBillingError):
            self.o.current_ar_proof(self.bill_id)

    def test_unqualified_credit_and_deleted_credit_birth_hold_current_AR_but_preserve_original_posting(self):
        original = self.o.posting_receipt(self.bill_id)
        revision = self.c.evidence.revision(self.r["review_revision_id"])
        credit = self.c.receivables.prepare_credit_memo(self.bill_id, "100", "Synthetic later owner credit", revision["content_hash"], actor=POSTER_LOGIN)
        with self.assertRaises(OwnerBillingError):
            self.o.current_ar_proof(self.bill_id)
        self.assertEqual(self.o.posting_receipt(self.bill_id), original)
        self.raw("prime_bill_credit_memos", "DELETE FROM prime_bill_credit_memos WHERE id=?", (credit["id"],))
        with self.assertRaises(OwnerBillingError):
            self.o.current_ar_proof(self.bill_id)
        self.assertEqual(self.o.posting_receipt(self.bill_id), original)

    def test_unqualified_deposit_holds_project_current_AR_without_rewriting_original_bill(self):
        original = self.o.posting_receipt(self.bill_id)
        self.c.receivables.record_deposit(self.r["customer_id"], self.r["project_id"], "100", "SYNTHETIC-OWNER-DEPOSIT", method="check",
                                          actor=POSTER_LOGIN, period_id="2026-10", settlement_date="2026-10-01")
        with self.assertRaises(OwnerBillingError):
            self.o.require_current_project_finance(self.r["project_id"])
        self.assertEqual(self.o.posting_receipt(self.bill_id), original)


if __name__ == "__main__":
    unittest.main()
