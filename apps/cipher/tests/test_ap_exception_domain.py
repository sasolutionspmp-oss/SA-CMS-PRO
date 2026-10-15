"""Pure, source-backed invoice exception decisions and atomic human effects."""
import unittest
from unittest.mock import patch

from apps.cipher.core.ids import hash_json, utcnow_iso
from apps.cipher.domain.ap_intake import APIntakeError, DuplicateInvoiceError
from apps.cipher.tests.test_ap_intake import World


class InvoiceExceptionTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c, self.ap = self.w.c, self.w.ap
        self.addCleanup(self.c.db.close)

    def snapshot(self, *, changes=True):
        return (hash_json(list(self.c.db.conn.iterdump())), self.c.db.conn.total_changes if changes else None,
                list(self.c.provider.submissions), dict(self.c.provider.transfers))

    def invoice(self, number="EXC-001", amount="27000"):
        return self.w.receive(number, amount)

    def linked(self, *, posted=False):
        bill = self.w.certify({1: "30000"})
        invoice = self.invoice()
        self.w.match_and_execute(invoice["id"])
        if posted:
            self.w.post(bill["id"])
        return self.ap.invoice(invoice["id"]), self.c.bills.get(bill["id"])

    def test_posted_invoice_revision_refuses_without_changing_journals_or_ap(self):
        invoice, _ = self.linked(posted=True)
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "posted|correction"):
            self.ap.revise_invoice(invoice["id"], "accountant", reason="Supplier changed amount", amount="26000")
        self.assertEqual(before, self.snapshot())

    def test_paid_invoice_revision_refuses_without_changing_the_original_source(self):
        invoice, bill = self.linked(posted=True)
        # The bill is conservatively treated as financially committed even if
        # a diagnostic fixture changes its status without constructing a rail.
        self.c.db.execute("DROP TRIGGER bills_status_transitions")
        self.c.db.execute("UPDATE bills SET status='paid' WHERE id=?", (bill["id"],))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            self.ap.revise_invoice(invoice["id"], "accountant", reason="Supplier changed amount", amount="26000")
        self.assertEqual(before, self.snapshot())

    def test_posted_invoice_revision_and_rejection_reviews_are_zero_write(self):
        invoice, _ = self.linked(posted=True)
        for review in (lambda: self.ap.revision_preflight(invoice["id"], reason="Changed date", invoice_date="2026-10-16"),
                       lambda: self.ap.rejection_preflight(invoice["id"], reason="Withdrawn invoice")):
            before = self.snapshot()
            with self.assertRaisesRegex(APIntakeError, "posted|correction"):
                review()
            self.assertEqual(before, self.snapshot())

    def test_governed_bill_correction_allows_a_new_invoice_revision(self):
        invoice, bill = self.linked(posted=True)
        self.c.bills.prepare_correction(bill["id"], "Synthetic incorrect certification", "accountant")
        approval = self.c.request_approval("bill.correct", bill["id"], actor_role="accountant", requested_by="accountant")
        self.c.approve(approval["id"], approver="controller", approver_role="controller")
        self.c.execute(approval["id"], actor="accountant", period_id="P1")
        before = self.snapshot()
        plan = self.ap.revision_preflight(invoice["id"], reason="Supplier corrected invoice", amount="26000")
        self.assertEqual(before, self.snapshot())
        changed = self.ap.revise_invoice(invoice["id"], "accountant", reason=plan["reason"], amount="26000")
        self.assertEqual((changed["version"], changed["status"], changed["amount"]), (2, "received", "26000.00"))
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "corrected")
        self.assertEqual(self.c.bills.ap_open_items()["subledger_total"], "0.00")
        self.ap.invoice_proof(invoice["id"])

    def test_fake_corrected_status_does_not_release_a_posted_invoice(self):
        invoice, bill = self.linked(posted=True)
        request = self.c.bills.prepare_correction(bill["id"], "Synthetic pending correction", "accountant")
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bills'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        self.c.db.execute("UPDATE bills SET status='corrected',correction_id=?,corrected_at=? WHERE id=?",
                          (request["id"], utcnow_iso(), bill["id"]))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            self.ap.revision_preflight(invoice["id"], reason="Attempted posted revision", amount="26000")
        self.assertEqual(before, self.snapshot())

    def test_legacy_received_invoice_on_posted_bill_cannot_be_rejected(self):
        invoice, _ = self.linked(posted=True)
        self.seed_legacy_revision(invoice)
        before = self.snapshot()
        with self.assertRaisesRegex(APIntakeError, "posted|correction"):
            self.ap.reject_invoice(invoice["id"], "Supplier withdrew invoice", "accountant")
        self.assertEqual(before, self.snapshot())

    def seed_legacy_revision(self, invoice):
        """An audited pre-safety release could revise a posted bill's invoice.

        Preserve that genuine historical shape for upgrade refusal testing; the
        current public method must never recreate it.
        """
        row = self.ap._row(invoice["id"])
        new = {**row, "version": row["version"] + 1, "due_date": "2026-12-01", "terms_days": None}
        new["content_hash"] = self.ap._content_hash(new)
        with self.c.db.transaction() as conn:
            self.c.audit.record("accountant", "ap_intake.invoice_revised", "ap_invoice", row["id"], {
                "reason": "Historical supplier due-date correction", "changes": {"due_date": new["due_date"]},
                "version": new["version"], "previous_status": row["status"], "content_hash": new["content_hash"],
                "amount": row["amount"], "possible_duplicate": row["possible_duplicate"],
                "possible_duplicate_of": [], "approvals_invalidated": 0, "attached_bill_id": row["matched_bill_id"],
            })
            conn.execute("UPDATE ap_invoices SET version=?,due_date=?,terms_days=NULL,content_hash=?,status='received',match_status=NULL,match_basis=NULL,match_exceptions_json='[]',match_attempt_id=NULL,updated_at=? WHERE id=?",
                         (new["version"], new["due_date"], new["content_hash"], utcnow_iso(), row["id"]))
        self.ap.invoice_proof(row["id"])

    def test_revision_preflight_is_zero_write_and_predicts_the_exact_effect(self):
        invoice = self.invoice()
        _, evidence = self.w.pdf("replacement")
        args = {"reason": "Supplier corrected invoice", "invoice_number": "EXC-002", "invoice_date": "2026-10-16",
                "amount": "26999.99", "evidence_hash": evidence["content_hash"]}
        before = self.snapshot()
        plan = self.ap.revision_preflight(invoice["id"], **args)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["content"]["version"], 2)
        self.assertEqual(plan["content"]["due_date"], "2026-11-15")
        changed = self.ap.revise_invoice(invoice["id"], "accountant", **args)
        self.assertEqual(changed["content_hash"], plan["content"]["content_hash"])
        for field in ("invoice_number", "invoice_date", "due_date", "amount", "evidence_hash", "version"):
            self.assertEqual(changed[field], plan["content"][field])
        self.assertEqual(changed["status"], "received")

    def test_revision_keeps_invoice_bound_terms_when_current_supplier_terms_change(self):
        invoice = self.invoice()
        self.ap.set_terms(invoice["supplier_id"], 60, "controller")
        before = self.snapshot()
        plan = self.ap.revision_preflight(invoice["id"], reason="Supplier corrected invoice date", invoice_date="2026-10-16")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["source_facts"]["terms"]["days"], 60)
        self.assertEqual((plan["content"]["terms_days"], plan["content"]["due_date"]), (30, "2026-11-15"))

    def test_rejection_preflight_is_zero_write_and_final_number_stays_reserved(self):
        invoice = self.invoice()
        before = self.snapshot()
        plan = self.ap.rejection_preflight(invoice["id"], reason="Supplier issued invoice in error")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["invoice_id"], invoice["id"])
        rejected = self.ap.reject_invoice(invoice["id"], plan["reason"], "accountant")
        self.assertEqual(rejected["status"], "rejected")
        with self.assertRaises(APIntakeError):
            self.ap.revision_preflight(invoice["id"], reason="Try again", amount="1")
        with self.assertRaises(DuplicateInvoiceError):
            self.w.receive("exc 001", "1")

    def test_duplicate_review_preflight_is_zero_write_and_leaves_the_flag_visible(self):
        self.invoice()
        duplicate = self.invoice("EXC-002")
        before = self.snapshot()
        plan = self.ap.duplicate_review_preflight(duplicate["id"], reason="Distinct supplier scope checked")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["content"]["version"], 1)
        reviewed = self.ap.clear_duplicate_flag(duplicate["id"], plan["reason"], "accountant")
        self.assertTrue(reviewed["possible_duplicate"])
        self.assertFalse(reviewed["duplicate_blocking"])
        with self.assertRaises(APIntakeError):
            self.ap.duplicate_review_preflight(duplicate["id"], reason="Repeat")

    def test_revised_duplicate_facts_reset_review_even_when_pool_ids_are_unchanged(self):
        self.invoice()
        duplicate = self.invoice("EXC-002")
        self.ap.clear_duplicate_flag(duplicate["id"], "Distinct supplier scope checked", "accountant")
        before = self.snapshot()
        plan = self.ap.revision_preflight(duplicate["id"], reason="Supplier corrected date", invoice_date="2026-10-16")
        self.assertEqual(before, self.snapshot())
        self.assertTrue(plan["possible_duplicate"])
        self.assertEqual(plan["duplicate_review"], {"cleared_by": None, "cleared_at": None, "reason": None})
        changed = self.ap.revise_invoice(duplicate["id"], "accountant", reason="Supplier corrected date", invoice_date="2026-10-16")
        self.assertTrue(changed["duplicate_blocking"])
        self.ap.invoice_proof(changed["id"])

    def test_evidence_only_revision_preserves_genuine_duplicate_review(self):
        self.invoice()
        duplicate = self.invoice("EXC-002")
        reviewed = self.ap.clear_duplicate_flag(duplicate["id"], "Distinct supplier scope checked", "accountant")
        _, evidence = self.w.pdf("replacement")
        before = self.snapshot()
        plan = self.ap.revision_preflight(duplicate["id"], reason="Supplier replaced PDF", evidence_hash=evidence["content_hash"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["duplicate_review"]["cleared_at"], reviewed["duplicate_cleared_at"])
        changed = self.ap.revise_invoice(duplicate["id"], "accountant", reason="Supplier replaced PDF", evidence_hash=evidence["content_hash"])
        self.assertFalse(changed["duplicate_blocking"])
        self.ap.invoice_proof(changed["id"])

    def test_revision_previews_exact_open_approval_invalidations(self):
        self.w.certify({1: "30000"})
        invoice = self.invoice()
        self.ap.match(invoice["id"], "ap clerk")
        approval = self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by="ap clerk")
        before = self.snapshot()
        plan = self.ap.revision_preflight(invoice["id"], reason="Supplier changed date", invoice_date="2026-10-16")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan["invalidated_approval_ids"], [approval["id"]])
        self.ap.revise_invoice(invoice["id"], "accountant", reason="Supplier changed date", invoice_date="2026-10-16")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "invalidated")

    def test_invalid_or_no_change_revision_reviews_are_zero_write(self):
        invoice = self.invoice()
        for fields in ({"amount": "0"}, {"amount": "1.001"}, {"amount": 1.5}, {"invoice_date": "bad"},
                       {"invoice_number": ""}, {"evidence_hash": "missing"}, {}):
            before = self.snapshot()
            with self.subTest(fields=fields), self.assertRaises(APIntakeError):
                self.ap.revision_preflight(invoice["id"], reason="Supplier correction", **fields)
            self.assertEqual(before, self.snapshot())

    def test_original_doc_and_current_terms_tampering_refuse_exception_reviews(self):
        invoice = self.invoice()
        self.c.db.execute("UPDATE documents SET title='Unrecorded title' WHERE id=?", (invoice["evidence_document_id"],))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            self.ap.revision_preflight(invoice["id"], reason="Date correction", invoice_date="2026-10-16")
        self.assertEqual(before, self.snapshot())
        # A separate valid source proves the current commercial terms independently.
        another = self.invoice("EXC-002", "100")
        self.ap.set_terms(another["supplier_id"], 45, "controller")
        self.c.db.execute("UPDATE ap_supplier_terms SET days=1,version=version+1 WHERE supplier_id=?", (another["supplier_id"],))
        before = self.snapshot()
        with self.assertRaises(APIntakeError):
            self.ap.rejection_preflight(another["id"], reason="Supplier withdrew invoice")
        self.assertEqual(before, self.snapshot())

    def test_exception_reviews_work_when_sqlite_is_query_only(self):
        self.invoice()
        duplicate = self.invoice("EXC-002")
        with self.c.db._lock:
            self.c.db._set_query_only(True)
        before = self.snapshot()
        try:
            self.ap.revision_preflight(duplicate["id"], reason="Date correction", invoice_date="2026-10-16")
            self.ap.rejection_preflight(duplicate["id"], reason="Supplier withdrew invoice")
            self.ap.duplicate_review_preflight(duplicate["id"], reason="Distinct scope checked")
            self.assertEqual(before, self.snapshot())
        finally:
            with self.c.db._lock:
                self.c.db._set_query_only(False)

    def test_revision_failure_rolls_back_content_and_invalidations_when_caught(self):
        self.w.certify({1: "30000"})
        invoice = self.invoice()
        self.ap.match(invoice["id"], "ap clerk")
        self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by="ap clerk")
        self.assert_atomic("ap_intake.invoice_revised", lambda: self.ap.revise_invoice(invoice["id"], "accountant", reason="Changed date", invoice_date="2026-10-16"))

    def test_rejection_failure_rolls_back_its_audit_and_invalidations_when_caught(self):
        self.w.certify({1: "30000"})
        invoice = self.invoice()
        self.ap.match(invoice["id"], "ap clerk")
        self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by="ap clerk")
        self.assert_atomic("ap_intake.invoice_rejected", lambda: self.ap.reject_invoice(invoice["id"], "Wrong invoice", "accountant"))

    def test_duplicate_review_failure_rolls_back_its_audit_when_caught(self):
        self.invoice()
        duplicate = self.invoice("EXC-002")
        self.assert_atomic("ap_intake.duplicate_flag_cleared", lambda: self.ap.clear_duplicate_flag(duplicate["id"], "Distinct scope", "accountant"))

    def assert_atomic(self, action, call):
        original = self.c.audit.record

        def fail_after_audit(actor, code, entity_type, entity_id, payload=None):
            result = original(actor, code, entity_type, entity_id, payload)
            if code == action:
                raise RuntimeError("Injected invoice exception failure")
            return result

        before = self.snapshot(changes=False)
        with self.c.db.transaction():
            with patch.object(self.c.audit, "record", side_effect=fail_after_audit):
                with self.assertRaisesRegex(RuntimeError, "Injected"):
                    call()
            self.assertEqual(before, self.snapshot(changes=False))
        self.assertEqual(before, self.snapshot(changes=False))


if __name__ == "__main__":
    unittest.main()
