"""Pure cancellation/correction reviews and atomic governed bill effects."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, PM_LOGIN, REVIEWER_LOGIN, make_ap_practice_fixture
from apps.cipher.core.ids import canonical_json
from apps.cipher.domain.bills import BillError


class APExceptionBillTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.bill_id = self.c.ap_practice_records["draft_bill_id"]

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), len(self.c.provider.submissions), tuple(self.c.provider.transfers)

    def post(self, period="2026-10"):
        ap = self.c.request_approval("bill.approve", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.post_bill(self.bill_id, actor=ACCOUNTANT_LOGIN, actor_role="accountant", period_id=period,
                         reason="Reviewed later posting" if period != "2026-10" else "")
        return self.c.bills.get(self.bill_id)

    def approve_correction(self):
        request = self.c.bills.prepare_correction(self.bill_id, "Synthetic certified work measured twice", ACCOUNTANT_LOGIN)
        ap = self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        return request, ap

    def drop_guards(self, table):
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')

    def test_failed_preparation_rolls_back_when_outer_caller_catches_it(self):
        self.post()
        with self.c.db.transaction():
            before = self.snapshot()
            with patch.object(self.c.audit, "record", side_effect=RuntimeError("injected request audit failure")):
                with self.assertRaises(RuntimeError):
                    self.c.bills.prepare_correction(self.bill_id, "Synthetic correction", ACCOUNTANT_LOGIN)
            self.assertEqual(before, self.snapshot())

    def test_unaudited_correction_reason_cannot_become_a_new_manifest(self):
        self.post()
        request = self.c.bills.prepare_correction(self.bill_id, "Original audited reason", ACCOUNTANT_LOGIN)
        self.drop_guards("bill_corrections")
        self.c.db.execute("UPDATE bill_corrections SET reason='Unrecorded altered reason' WHERE id=?", (request["id"],))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_unreceipted_bill_journal_cannot_be_absorbed_into_correction(self):
        bill = self.post()
        self.c.ledger.post(period_id="2026-10", description="Unapproved extra source", source_type="bill", source_id=bill["id"],
                           source_version=str(bill["commitment_version"]), posted_by=ACCOUNTANT_LOGIN,
                           lines=[{"account": "5000", "debit": "100.00", "project_id": bill["project_id"], "party_id": bill["supplier_id"]},
                                  {"account": "2000", "credit": "100.00", "project_id": bill["project_id"], "party_id": bill["supplier_id"]}])
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.bills.prepare_correction(self.bill_id, "Synthetic correction", ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_void_preview_is_pure_and_actual_cancellation_invalidates_open_grants(self):
        approval = self.c.request_approval("bill.approve", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        before = self.snapshot()
        changes = self.c.db.conn.total_changes
        plan = self.c.bills.void_preflight(self.bill_id, actor=ACCOUNTANT_LOGIN, reason="Synthetic replaced draft")
        self.assertEqual(plan["bill"]["status"], "draft")
        self.assertEqual(plan["open_approval_ids"], [approval["id"]])
        self.assertEqual(plan["restore_transfers"], [])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(changes, self.c.db.conn.total_changes)
        self.c.bills.void(self.bill_id, actor=ACCOUNTANT_LOGIN, reason="Synthetic replaced draft")
        self.assertEqual(self.c.bills.get(self.bill_id)["status"], "void")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "invalidated")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)

    def test_original_pm_withdrawal_keeps_business_proof_and_creates_no_journal(self):
        ap = self.c.request_approval("bill.approve", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=PM_LOGIN, approver_role="pm")
        record = self.c.bills.get(self.bill_id)["approval_record_id"]
        before = self.snapshot()
        with self.assertRaises(PermissionError):
            self.c.bills.void_preflight(self.bill_id, actor=ACCOUNTANT_LOGIN, reason="Synthetic withdrawal")
        self.assertEqual(before, self.snapshot())
        plan = self.c.bills.void_preflight(self.bill_id, actor=PM_LOGIN, reason="Synthetic withdrawal")
        self.assertEqual(plan["bill"]["status"], "approved")
        self.c.bills.void(self.bill_id, actor=PM_LOGIN, reason="Synthetic withdrawal")
        self.assertEqual(self.c.bills.get(self.bill_id)["approval_record_id"], record)
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)

    def test_void_failure_rolls_back_when_outer_caller_catches_it(self):
        with self.c.db.transaction():
            before = self.snapshot()
            with patch.object(self.c.audit, "record", side_effect=RuntimeError("injected void audit failure")):
                with self.assertRaises(RuntimeError):
                    self.c.bills.void(self.bill_id, actor=ACCOUNTANT_LOGIN, reason="Synthetic cancellation")
            self.assertEqual(before, self.snapshot())

    def test_correction_prepare_and_execution_reviews_are_zero_write(self):
        bill = self.post()
        before = self.snapshot()
        changes = self.c.db.conn.total_changes
        prepare = self.c.bills.correction_prepare_preflight(self.bill_id, "Synthetic correction")
        self.assertEqual(prepare["facts"]["bill"]["id"], bill["id"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(changes, self.c.db.conn.total_changes)
        request, approval = self.approve_correction()
        before = self.snapshot()
        changes = self.c.db.conn.total_changes
        plan = self.c.bills.correction_execution_preflight(self.bill_id, period_id="2026-11", approval_id=approval["id"], manifest=approval["manifest"])
        self.assertEqual(plan["target"]["id"], "2026-11")
        self.assertEqual(plan["facts"]["request"]["id"], request["id"])
        self.assertEqual(len(plan["journal_preview"]), 1)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(changes, self.c.db.conn.total_changes)

    def test_correction_actual_reversal_matches_exact_pure_plan_and_preserves_posting(self):
        self.post()
        original = self.c.bills.posting_receipt(self.bill_id)
        request, ap = self.approve_correction()
        plan = self.c.bills.correction_execution_preflight(self.bill_id, period_id="2026-11", approval_id=ap["id"], manifest=ap["manifest"])
        result = self.c.execute(ap["id"], actor=ACCOUNTANT_LOGIN, period_id="2026-11")
        for journal_id, preview in zip(result.result["reversal_journals"], plan["journal_preview"]):
            journal = self.c.ledger.journal(journal_id)
            for key in ("period_id", "description", "source_type", "source_id", "source_version", "rule_version", "reversal_of"):
                self.assertEqual(journal[key], preview[key])
            self.assertEqual([{key: line[key] for key in ("account_code", "debit", "credit", "project_id", "party_id", "memo")} for line in journal["lines"]],
                             [{"account_code": line["account"], **{key: line[key] for key in ("debit", "credit", "project_id", "party_id", "memo")}} for line in preview["lines"]])
        self.assertEqual(self.c.bills.posting_receipt(self.bill_id)["receipt_hash"], original["receipt_hash"])
        proof = self.c.bills.corrected_bill_proof(self.bill_id)
        self.assertEqual(proof["id"], request["id"])
        self.assertEqual(proof["status"], "executed")
        self.assertEqual(self.c.bills.open_payable(self.bill_id), 0)
        self.assertEqual(self.c.ledger.balance("2000"), 0)
        self.assertEqual(self.c.ledger.balance("5000"), 0)
        self.assertEqual(self.c.ledger.balance("2050"), 0)

    def test_correction_uses_actual_posting_period_not_certification_period(self):
        self.post("2026-11")
        _, ap = self.approve_correction()
        with self.assertRaises(BillError):
            self.c.bills.correction_execution_preflight(self.bill_id, period_id="2026-10", approval_id=ap["id"], manifest=ap["manifest"])
        self.assertEqual(self.c.bills.correction_execution_preflight(self.bill_id, period_id="2026-11")["target"]["id"], "2026-11")

    def test_corrected_status_requires_genuine_approved_reversal_source(self):
        self.post()
        request = self.c.bills.prepare_correction(self.bill_id, "Pending unexecuted request", ACCOUNTANT_LOGIN)
        self.drop_guards("bills")
        self.c.db.execute("UPDATE bills SET status='corrected',correction_id=?,corrected_at='2026-10-14T12:00:00Z' WHERE id=?", (request["id"], self.bill_id))
        with self.assertRaises(BillError):
            self.c.bills.corrected_bill_proof(self.bill_id)
        self.assertTrue(any(not check["ok"] for check in self.c.bills.lifecycle_integrity_checks(self.bill_id)))

    def test_cancelled_correction_request_has_audited_source_and_failure_rolls_back(self):
        self.post()
        request = self.c.bills.prepare_correction(self.bill_id, "Original audited request", ACCOUNTANT_LOGIN)
        with self.c.db.transaction():
            before = self.snapshot()
            with patch.object(self.c.audit, "record", side_effect=RuntimeError("injected cancellation audit failure")):
                with self.assertRaises(RuntimeError):
                    self.c.bills.cancel_correction(request["id"], "Synthetic withdrawal", ACCOUNTANT_LOGIN)
            self.assertEqual(before, self.snapshot())
        self.c.bills.cancel_correction(request["id"], "Synthetic withdrawal", ACCOUNTANT_LOGIN)
        proof = self.c.bills.correction_proof(request["id"])
        self.assertEqual(proof["status"], "cancelled")
        self.assertEqual(proof["resolution_note"], "Synthetic withdrawal")

    def test_direct_apply_rolls_back_domain_effects_when_outer_caller_catches_failure(self):
        self.post()
        _, ap = self.approve_correction()
        manifest = self.c._manifest("bill.correct", self.bill_id, "accountant")
        self.c.approvals.consume(ap["id"], current_manifest=manifest, consumer=ACCOUNTANT_LOGIN)
        def fail_hook(*args):
            raise RuntimeError("injected reversal hook failure")
        self.c.ledger.reversal_hooks["bill"] = fail_hook
        with self.c.db.transaction():
            before = self.snapshot()
            with self.assertRaises(RuntimeError):
                self.c.bills.apply("bill.correct", self.bill_id, approval_id=ap["id"], manifest=manifest,
                                   actor=ACCOUNTANT_LOGIN, period_id="2026-10")
            self.assertEqual(before, self.snapshot())

    def test_actual_accountant_roles_enforce_independent_correction_grant(self):
        self.post()
        self.c.bills.prepare_correction(self.bill_id, "Synthetic accounting correction", ACCOUNTANT_LOGIN)
        ap = self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        before = self.snapshot()
        with self.assertRaises(PermissionError):
            self.c.approve(ap["id"], approver=ACCOUNTANT_LOGIN, approver_role="accountant")
        with self.assertRaises(PermissionError):
            self.c.approve(ap["id"], approver=PM_LOGIN, approver_role="pm")
        self.assertEqual(before, self.snapshot())
        self.c.approve(ap["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.assertEqual(self.c.bills.correction_approval_proof(ap["id"])["requestedBy"], ACCOUNTANT_LOGIN)
        self.c.execute(ap["id"], actor=ACCOUNTANT_LOGIN, period_id="2026-10")
        self.assertEqual(self.c.bills.corrected_bill_proof(self.bill_id)["resolved_by"], ACCOUNTANT_LOGIN)

    def payment(self):
        bill = self.c.bills.get(self.bill_id)
        self.c.verify_destination(bill["supplier_id"], destination="SIM-PRACTICE-NO-DELIVERY", verified_by="practice.bootstrap")
        approval = self.c.request_approval("payment.release", self.bill_id, actor_role="owner", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver="practice.bootstrap", approver_role="owner")
        self.c.execute(approval["id"], actor="practice.bootstrap")
        return self.c.db.one("SELECT * FROM payment_intents WHERE bill_id=?", (self.bill_id,))

    def test_forged_final_payment_state_cannot_remove_a_correction_hold(self):
        self.post()
        intent = self.payment()
        self.drop_guards("payment_intents")
        self.c.db.execute("UPDATE payment_intents SET status='failed' WHERE id=?", (intent["id"],))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.bills.prepare_correction(self.bill_id, "Synthetic correction despite forged payment", ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_deleted_payment_intent_cannot_remove_a_correction_hold(self):
        self.post()
        intent = self.payment()
        self.drop_guards("payment_intents")
        self.c.db.execute("DELETE FROM payment_intents WHERE id=?", (intent["id"],))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.bills.prepare_correction(self.bill_id, "Synthetic correction despite omitted payment", ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_forged_cancelled_credit_cannot_remove_a_correction_hold(self):
        bill = self.post()
        document = self.c.evidence.register_document(project_id=bill["project_id"], kind="supplier_credit_note",
                                                    title="Synthetic supplier credit", actor=ACCOUNTANT_LOGIN)
        revision = self.c.evidence.add_revision(document_id=document["id"], content="Synthetic credit source", actor=ACCOUNTANT_LOGIN)
        note = self.c.bills.prepare_credit_note(self.bill_id, "100.00", "Synthetic credit", revision["content_hash"], ACCOUNTANT_LOGIN)
        self.drop_guards("bill_credit_notes")
        self.c.db.execute("UPDATE bill_credit_notes SET status='cancelled',cancelled_by=?,cancelled_at='2026-10-14T12:00:00Z',cancel_reason='Forged cancellation' WHERE id=?", (ACCOUNTANT_LOGIN, note["id"]))
        before = self.snapshot()
        with self.assertRaises(BillError):
            self.c.bills.prepare_correction(self.bill_id, "Synthetic correction despite forged credit", ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_genuine_cancelled_payment_retains_history_and_allows_unpaid_correction(self):
        self.post()
        intent = self.payment()
        self.c.payments.cancel_intent(intent["id"], "Synthetic duplicate release withdrawn", "practice.bootstrap")
        before = self.snapshot()
        plan = self.c.bills.correction_prepare_preflight(self.bill_id, "Synthetic unpaid correction")
        self.assertEqual(plan["facts"]["intents"][0]["status"], "canceled")
        self.assertEqual(before, self.snapshot())

    def test_genuine_returned_payment_retains_history_and_allows_unpaid_correction(self):
        self.post()
        intent = self.payment()
        self.c.dispatch_payments(actor="practice.bootstrap")
        event = self.c.provider.return_payment(intent["logical_op_id"], "Synthetic transfer returned")
        self.c.payments.ingest_event(event, actor="practice.bootstrap")
        before = self.snapshot()
        plan = self.c.bills.correction_prepare_preflight(self.bill_id, "Synthetic returned unpaid correction")
        self.assertEqual(plan["facts"]["intents"][0]["status"], "returned")
        self.assertEqual(plan["facts"]["bill"]["status"], "posted")
        self.assertEqual(before, self.snapshot())

    def test_correction_inventory_detects_omitted_later_preparation_without_eligibility(self):
        self.post()
        first = self.c.bills.prepare_correction(self.bill_id, "Synthetic first request", ACCOUNTANT_LOGIN)
        self.c.bills.cancel_correction(first["id"], "Synthetic superseded request", ACCOUNTANT_LOGIN)
        second = self.c.bills.prepare_correction(self.bill_id, "Synthetic second request", ACCOUNTANT_LOGIN)
        before = self.snapshot()
        self.assertEqual([row["id"] for row in self.c.bills.correction_inventory(self.bill_id)], [first["id"], second["id"]])
        self.assertEqual(before, self.snapshot())
        self.drop_guards("bill_corrections")
        self.c.db.execute("DELETE FROM bill_corrections WHERE id=?", (second["id"],))
        with self.assertRaises(BillError):
            self.c.bills.correction_inventory(self.bill_id)
        self.assertTrue(any(not check["ok"] for check in self.c.bills.lifecycle_integrity_checks(self.bill_id)))


if __name__ == "__main__":
    unittest.main()
