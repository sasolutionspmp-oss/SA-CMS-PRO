"""Staff expense reimbursements: golden sequence and adversarial variants.

Payments leave through the core payment outbox: executing ``reimbursement.pay``
queues a payment intent (the payment is ``in_flight``); ``c.dispatch_payments()``
lets the simulated provider accept it (Dr 2100 / Cr 1200, payment ``booked``);
a settlement event then moves the bank (Dr 1200 / Cr 1000)."""
import os
import shutil
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalConsumed, ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.payments import ReleaseQuarantined
from apps.cipher.domain.reimbursements import PLUGIN_NAME, ReimbursementError
from apps.cipher.service import Cipher


class Scenario:
    """Fresh workspace (in memory unless ``path`` is given): employee with a verified destination, supplier, customer, project, open period P1."""

    def __init__(self, path: str = ":memory:"):
        self.c = Cipher(path)
        self.r = self.c.plugin(PLUGIN_NAME)
        self.employee = self.c.add_party(kind="employee", name="Field Engineer", destination="ACH-EMP-1")
        self.employee = self.c.verify_destination(self.employee["id"], destination="ACH-EMP-1", verified_by="owner")
        self.supplier = self.c.add_party(kind="supplier", name="Sub", destination="ACH-SUB-1")
        self.customer = self.c.add_party(kind="customer", name="Owner Agency")
        self.project = self.c.create_project(name="Pump station", entity="E", budget="50000", customer_id=self.customer["id"])
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self._receipt_seq = 0

    def receipt(self) -> str:
        self._receipt_seq += 1
        return f"rcpt-{self._receipt_seq:04d}"

    def claim(self, amount="120.00", *, billable=True, description="Mileage to site"):
        return self.r.submit_claim(project_id=self.project["id"], employee_id=self.employee["id"], description=description, amount=amount, receipt_hash=self.receipt(), billable=billable, actor="emp")

    def approved_claim(self, amount="120.00", *, billable=True):
        cl = self.claim(amount, billable=billable)
        self.c.approve_and_execute("reimbursement.approve", cl["id"], period_id="P1")
        return self.r.claim(cl["id"])

    def release(self, payment_id: str):
        """Approve and execute reimbursement.pay: the payment is queued in the outbox."""
        return self.c.approve_and_execute("reimbursement.pay", payment_id, actor_role="treasury", actor="treasury", period_id="P1")

    def settle(self, payment_id: str):
        intent = self.c.payments.get(self.r.payment(payment_id)["intent_id"])
        return self.c.payments.ingest_event(self.c.provider.settle(intent["logical_op_id"]), actor="webhook")

    def pay(self, payment_id: str, *, settle: bool = True):
        """Release, dispatch (provider accepts: payment booked) and optionally settle."""
        res = self.release(payment_id)
        self.c.dispatch_payments()
        if settle:
            self.settle(payment_id)
        return res


class ReimbursementGoldenTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.r = self.s.r

    def test_golden_sequence(self):
        cl = self.s.claim("120.00", billable=True)
        self.assertEqual(cl["status"], "submitted")
        self.assertEqual(cl["version"], 1)
        self.assertEqual(cl["amount"], "120.00")
        # no payable exists before approval
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("5100"), Decimal("0.00"))
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("0.00"))

        res = self.c.approve_and_execute("reimbursement.approve", cl["id"], period_id="P1")
        self.assertEqual(res.result["status"], "approved")
        self.assertEqual(res.result["amount"], "120.00")
        cl = self.r.claim(cl["id"])
        self.assertEqual(cl["status"], "approved")
        self.assertIsNotNone(cl["journal_id"])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("5100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("2100", party_id=self.s.employee["id"]), Decimal("120.00"))
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("120.00"))

        # partial payment: executing it queues a payment intent; nothing is posted yet
        pay = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        self.assertEqual(pay["status"], "draft")
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("120.00"))  # drafts do not reduce the payable
        res = self.c.approve_and_execute("reimbursement.pay", pay["id"], actor_role="treasury", actor="treasury", period_id="P1")
        self.assertEqual(res.result["status"], "in_flight")
        self.assertEqual(res.result["intent_status"], "queued")
        self.assertEqual(res.result["outstanding"], "80.00")  # the in-flight 40.00 is reserved at once
        self.assertEqual(self.r.payment(pay["id"])["status"], "in_flight")
        self.assertEqual(self.r.claim(cl["id"])["status"], "approved")
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])
        with self.assertRaises(ReimbursementError):  # the reservation already blocks an overpayment
            self.r.record_payment(cl["id"], "80.01", actor="treasury")
        # the outbox dispatches it; the provider accepts: Dr 2100 / Cr 1200 and the payment is booked
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(self.r.payment(pay["id"])["status"], "booked")
        cl = self.r.claim(cl["id"])
        self.assertEqual(cl["status"], "partially_paid")
        self.assertEqual(cl["outstanding"], "80.00")
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("-40.00"))
        # settlement moves the bank
        self.s.settle(pay["id"])
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-40.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("0.00"))

        # paying more than the outstanding balance is rejected
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "90.00", actor="treasury")

        # billing the customer is a separate authority path and never touches 2100
        bill = self.r.create_billing(cl["id"], "120.00", actor="pm")
        self.assertEqual(bill["status"], "draft")
        self.assertEqual(bill["customer_id"], self.s.customer["id"])
        res = self.c.approve_and_execute("reimbursement.bill", bill["id"], period_id="P1")
        self.assertEqual(res.result["status"], "billed")
        self.assertEqual(self.r.billing(bill["id"])["status"], "billed")
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("1100", party_id=self.s.customer["id"]), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("4000"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        self.assertEqual(self.r.claim(cl["id"])["billed"], "120.00")

        # a non-billable claim cannot be billed
        other = self.s.approved_claim("15.00", billable=False)
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(other["id"], "15.00", actor="pm")

        # editing after a granted approval makes the approval stale
        edited = self.s.claim("50.00")
        ap = self.c.request_approval("reimbursement.approve", edited["id"])
        self.c.approve(ap["id"])
        self.r.update_claim(edited["id"], actor="emp", amount="55.00")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")

        # input validation
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="no receipt", amount="10.00", receipt_hash="", actor="emp")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.supplier["id"], description="supplier", amount="10.00", receipt_hash=self.s.receipt(), actor="emp")

        rec = self.r.employee_payable_reconciliation(self.s.project["id"])
        self.assertEqual(rec["subledger_total"], "95.00")  # 80.00 + 15.00
        self.assertEqual(rec["control_balance"], "95.00")
        self.assertTrue(rec["reconciled"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class ReimbursementRecordTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.r = self.s.r

    def test_submit_creates_no_payable_and_no_journal(self):
        cl = self.s.claim("120.00")
        self.assertEqual(cl["status"], "submitted")
        self.assertEqual(cl["version"], 1)
        self.assertEqual(cl["outstanding"], "0.00")
        self.assertTrue(cl["billable"])
        self.assertIsNone(cl["journal_id"])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertEqual(self.r.employee_payable_reconciliation(self.s.project["id"])["subledger_total"], "0.00")

    def test_approve_posts_expense_and_payable_to_employee(self):
        cl = self.s.approved_claim("120.00")
        self.assertEqual(cl["status"], "approved")
        self.assertEqual(cl["period_id"], "P1")
        j = self.c.ledger.journal(cl["journal_id"])
        self.assertEqual(j["source_type"], "reimbursement_claim")
        self.assertEqual(j["source_id"], cl["id"])
        self.assertEqual(j["approval_id"], cl["approval_id"])
        by_account = {ln["account_code"]: ln for ln in j["lines"]}
        self.assertEqual(by_account["5100"]["debit"], "120.00")
        self.assertEqual(by_account["2100"]["credit"], "120.00")
        self.assertEqual(by_account["2100"]["party_id"], self.s.employee["id"])
        self.assertEqual(by_account["2100"]["project_id"], self.s.project["id"])
        self.assertEqual(self.c.ledger.balance("5100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("2100", project_id=self.s.project["id"]), Decimal("120.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_full_payment_marks_claim_paid(self):
        cl = self.s.approved_claim("120.00")
        p1 = self.r.record_payment(cl["id"], "40.00", actor="t")
        self.s.pay(p1["id"])
        self.assertEqual(self.r.claim(cl["id"])["status"], "partially_paid")
        p2 = self.r.record_payment(cl["id"], "80.00", actor="t")
        res = self.s.release(p2["id"])
        self.assertEqual(res.result["claim_status"], "partially_paid")  # still owed until the provider accepts
        self.assertEqual(res.result["outstanding"], "0.00")
        self.c.dispatch_payments()
        self.s.settle(p2["id"])
        cl = self.r.claim(cl["id"])
        self.assertEqual(cl["status"], "paid")
        self.assertEqual(cl["outstanding"], "0.00")
        self.assertEqual(cl["paid"], "120.00")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-120.00"))
        # nothing more can be paid on a settled claim
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "0.01", actor="t")
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])

    def test_payment_cannot_exceed_outstanding_including_drafts(self):
        cl = self.s.approved_claim("120.00")
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "120.01", actor="t")
        self.r.record_payment(cl["id"], "100.00", actor="t")
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "20.01", actor="t")  # 100 is already reserved by a draft
        self.r.record_payment(cl["id"], "20.00", actor="t")

    def test_payment_requires_approved_claim(self):
        cl = self.s.claim("120.00")
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "10.00", actor="t")

    def test_billing_limited_to_claim_amount_and_approved_claims(self):
        submitted = self.s.claim("30.00")
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(submitted["id"], "30.00", actor="pm")
        cl = self.s.approved_claim("120.00")
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(cl["id"], "120.01", actor="pm")
        b1 = self.r.create_billing(cl["id"], "100.00", actor="pm")
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(cl["id"], "20.01", actor="pm")
        b2 = self.r.create_billing(cl["id"], "20.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b1["id"], period_id="P1")
        self.c.approve_and_execute("reimbursement.bill", b2["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("4000"), Decimal("120.00"))
        self.assertEqual(self.r.claim(cl["id"])["billed"], "120.00")

    def test_billing_never_changes_employee_payable(self):
        cl = self.s.approved_claim("120.00")
        b = self.r.create_billing(cl["id"], "120.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b["id"], period_id="P1")
        j = self.c.ledger.journal(self.r.billing(b["id"])["journal_id"])
        self.assertEqual(sorted(ln["account_code"] for ln in j["lines"]), ["1100", "4000"])
        self.assertTrue(all(ln["party_id"] == self.s.customer["id"] for ln in j["lines"]))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("120.00"))
        self.assertEqual(self.r.claim(cl["id"])["status"], "approved")

    def test_non_billable_claim_cannot_be_billed(self):
        cl = self.s.approved_claim("15.00", billable=False)
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(cl["id"], "15.00", actor="pm")
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("0.00"))

    def test_update_only_while_submitted_and_frozen_after_approval(self):
        cl = self.s.claim("120.00")
        updated = self.r.update_claim(cl["id"], actor="emp", amount="130.00", description="Mileage and tolls")
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["amount"], "130.00")
        self.assertNotEqual(updated["content_hash"], cl["content_hash"])
        with self.assertRaises(ReimbursementError):
            self.r.update_claim(cl["id"], actor="emp")  # nothing to update
        self.c.approve_and_execute("reimbursement.approve", cl["id"], period_id="P1")
        with self.assertRaises(ReimbursementError):
            self.r.update_claim(cl["id"], actor="emp", amount="140.00")
        # the schema enforces it too: a direct edit of an approved claim is rejected by trigger
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("UPDATE reimbursement_claims SET amount='999.00' WHERE id=?", (cl["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("DELETE FROM reimbursement_claims WHERE id=?", (cl["id"],))
        self.assertEqual(self.r.claim(cl["id"])["amount"], "130.00")
        with self.assertRaises(ReimbursementError):
            self.r.update_claim("rclm_missing", actor="emp", amount="1.00")


class ReimbursementAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.r = self.s.r

    def test_edit_after_granted_approval_invalidates_it(self):
        cl = self.s.claim("120.00")
        ap = self.c.request_approval("reimbursement.approve", cl["id"])
        self.c.approve(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.r.update_claim(cl["id"], actor="emp", amount="130.00")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.r.claim(cl["id"])["status"], "submitted")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        # a fresh approval of the edited claim carries the new amount
        res = self.c.approve_and_execute("reimbursement.approve", cl["id"], period_id="P1")
        self.assertEqual(res.result["amount"], "130.00")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("130.00"))
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_manifest_hash_detects_change_bypassing_proactive_invalidation(self):
        """Two drafted payments both approved: booking the first changes the claim's
        outstanding balance, so the second approval no longer matches and is invalidated."""
        cl = self.s.approved_claim("120.00")
        p1 = self.r.record_payment(cl["id"], "40.00", actor="t")
        p2 = self.r.record_payment(cl["id"], "40.00", actor="t")
        ap1 = self.c.request_approval("reimbursement.pay", p1["id"], actor_role="treasury")
        ap2 = self.c.request_approval("reimbursement.pay", p2["id"], actor_role="treasury")
        self.c.approve(ap1["id"])
        self.c.approve(ap2["id"])
        # releasing the first reserves 40.00 at once, so the second's bound outstanding no longer holds
        self.c.execute(ap1["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "granted")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap2["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        self.assertEqual(self.r.payment(p2["id"])["status"], "draft")
        self.c.dispatch_payments()
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        # re-approving the still-valid draft against the current state works
        self.s.pay(p2["id"])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("40.00"))
        self.assertEqual(len(self.c.provider.transfers), 2)
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])

    def test_closed_period_rejects_posting(self):
        cl = self.s.claim("120.00")
        ap = self.c.request_approval("reimbursement.approve", cl["id"])
        self.c.approve(ap["id"])
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.r.claim(cl["id"])["status"], "submitted")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # the failed command rolled back
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.c.execute(ap["id"], period_id="P2")
        cl = self.r.claim(cl["id"])
        self.assertEqual(cl["status"], "approved")
        self.assertEqual(cl["period_id"], "P2")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_duplicate_receipt_rejected(self):
        self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="Hotel", amount="200.00", receipt_hash="rcpt-dup", actor="emp")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="Hotel again", amount="200.00", receipt_hash="rcpt-dup", actor="emp")
        other = self.s.claim("10.00")
        with self.assertRaises(ReimbursementError):
            self.r.update_claim(other["id"], actor="emp", receipt_hash="rcpt-dup")
        self.assertEqual(len(self.r.claims(self.s.project["id"])), 2)

    def test_claim_without_receipt_rejected(self):
        for bad in ("", "   ", None):
            with self.assertRaises(ReimbursementError):
                self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="x", amount="10.00", receipt_hash=bad, actor="emp")
        self.assertEqual(self.r.claims(self.s.project["id"]), [])

    def test_only_employees_can_claim(self):
        for party in (self.s.supplier, self.s.customer):
            with self.assertRaises(ReimbursementError):
                self.r.submit_claim(project_id=self.s.project["id"], employee_id=party["id"], description="x", amount="10.00", receipt_hash=self.s.receipt(), actor="emp")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id="pty_missing", description="x", amount="10.00", receipt_hash=self.s.receipt(), actor="emp")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id="prj_missing", employee_id=self.s.employee["id"], description="x", amount="10.00", receipt_hash=self.s.receipt(), actor="emp")

    def test_invalid_amounts_and_fields_rejected(self):
        for bad in ("0", "-5.00", 12.5, "abc", ""):
            with self.assertRaises(ReimbursementError):
                self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="x", amount=bad, receipt_hash=self.s.receipt(), actor="emp")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="", amount="10.00", receipt_hash=self.s.receipt(), actor="emp")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="x", amount="10.00", receipt_hash=self.s.receipt(), billable="yes", actor="emp")
        cl = self.s.approved_claim("20.00")
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "-1.00", actor="t")
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(cl["id"], 5.0, actor="pm")
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.write_off", cl["id"])

    def test_duplicate_approvals_on_one_subject_cannot_post_twice(self):
        cl = self.s.claim("120.00")
        ap_a = self.c.request_approval("reimbursement.approve", cl["id"])
        ap_b = self.c.request_approval("reimbursement.approve", cl["id"])
        self.c.approve(ap_a["id"])
        self.c.approve(ap_b["id"])
        self.c.execute(ap_a["id"], period_id="P1")
        # executing the first approval invalidated the second; the claim is no longer approvable
        self.assertEqual(self.c.approvals.get(ap_b["id"])["status"], "invalidated")
        with self.assertRaises(ReimbursementError):
            self.c.execute(ap_b["id"], period_id="P1")
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.approve", cl["id"])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 1)
        # the same holds for two approvals on one payment and on one billing
        p = self.r.record_payment(cl["id"], "120.00", actor="t")
        pa = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        pb = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.c.approve(pa["id"])
        self.c.approve(pb["id"])
        self.c.execute(pa["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.approvals.get(pb["id"])["status"], "invalidated")
        with self.assertRaises(ReimbursementError):
            self.c.execute(pb["id"], actor="treasury", period_id="P1")
        self.assertEqual(len(self.c.payments.list()), 1)  # one intent, one transfer
        self.c.dispatch_payments()
        self.s.settle(p["id"])
        self.assertEqual(len(self.c.provider.transfers), 1)
        b = self.r.create_billing(cl["id"], "120.00", actor="pm")
        ba = self.c.request_approval("reimbursement.bill", b["id"])
        bb = self.c.request_approval("reimbursement.bill", b["id"])
        self.c.approve(ba["id"])
        self.c.approve(bb["id"])
        self.c.execute(ba["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(bb["id"])["status"], "invalidated")
        with self.assertRaises(ReimbursementError):
            self.c.execute(bb["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-120.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("120.00"))
        # approval, provider acceptance, settlement, billing
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 4)
        self.assertEqual(self.c.approvals.list(status="granted"), [])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_cancel_draft_payment_invalidates_its_approval(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "120.00", actor="t")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.c.approve(ap["id"])
        self.r.cancel_payment(p["id"], actor="t", reason="wrong amount")
        self.assertEqual(self.r.payment(p["id"])["status"], "canceled")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ReimbursementError):  # a canceled payment has no manifest to execute against
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        with self.assertRaises(ReimbursementError):
            self.r.cancel_payment(p["id"], actor="t")
        # the reservation is released: a new draft for the full balance is accepted
        self.r.record_payment(cl["id"], "120.00", actor="t")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))

    def test_reconciliation_and_state_shape(self):
        a = self.s.approved_claim("120.00")
        b = self.s.approved_claim("30.00", billable=False)
        pending = self.s.claim("5.00")  # submitted: not part of the payable
        p = self.r.record_payment(a["id"], "40.00", actor="t")
        self.s.pay(p["id"])
        bill = self.r.create_billing(a["id"], "120.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", bill["id"], period_id="P1")

        rec = self.r.employee_payable_reconciliation(self.s.project["id"])
        self.assertEqual(rec["subledger_total"], "110.00")
        self.assertEqual(rec["control_balance"], "110.00")
        self.assertTrue(rec["reconciled"])
        self.assertEqual(sorted(i["claim_id"] for i in rec["items"]), sorted([a["id"], b["id"]]))

        st = self.r.state(self.s.project["id"])
        self.assertEqual(set(st), {"claims", "payments", "billings", "collections", "reconciliation", "receivable"})
        self.assertEqual((st["receivable"]["subledger_total"], st["receivable"]["ledger_postings"], st["receivable"]["reconciled_to_postings"]), ("120.00", "120.00", True))
        self.assertEqual(st["collections"], [])
        self.assertEqual([c["id"] for c in st["claims"]], [a["id"], b["id"], pending["id"]])
        first = st["claims"][0]
        self.assertEqual(first["outstanding"], "80.00")
        self.assertEqual(first["status"], "partially_paid")
        self.assertEqual([x["status"] for x in first["payments"]], ["booked"])
        self.assertEqual([x["intent_status"] for x in first["payments"]], ["settled"])
        self.assertEqual([x["status"] for x in first["billings"]], ["billed"])
        self.assertEqual(st["claims"][2]["outstanding"], "0.00")
        self.assertEqual(len(st["payments"]), 1)
        self.assertEqual(len(st["billings"]), 1)
        self.assertTrue(st["reconciliation"]["reconciled"])

        # the service exposes the plugin under its operation prefix
        full = self.c.project_state(self.s.project["id"])
        self.assertIn(PLUGIN_NAME, full)
        self.assertEqual(full[PLUGIN_NAME]["reconciliation"]["subledger_total"], "110.00")
        self.assertTrue(full["trial_balance"]["balanced"])
        self.assertTrue(full["audit_chain"]["ok"])
        # an empty project reconciles trivially
        empty = self.c.create_project(name="Empty", entity="E", budget="0")
        empty_state = self.r.state(empty["id"])
        self.assertEqual({k: v for k, v in empty_state.items() if k != "receivable"},
                         {"claims": [], "payments": [], "billings": [], "collections": [], "reconciliation": {"items": [], "subledger_total": "0.00", "in_flight_total": "0.00", "control_balance": "0.00", "reconciled": True}})
        self.assertEqual((empty_state["receivable"]["items"], empty_state["receivable"]["subledger_total"], empty_state["receivable"]["reconciled_to_postings"]), ([], "0.00", True))

    def test_claim_status_transitions_are_enforced_by_schema(self):
        submitted = self.s.claim("10.00")
        paid = self.s.approved_claim("120.00")
        p = self.r.record_payment(paid["id"], "120.00", actor="t")
        self.s.pay(p["id"])
        partial = self.s.approved_claim("50.00")
        p2 = self.r.record_payment(partial["id"], "20.00", actor="t")
        self.s.pay(p2["id"])
        self.assertEqual(self.r.claim(paid["id"])["status"], "paid")
        self.assertEqual(self.r.claim(partial["id"])["status"], "partially_paid")
        illegal = (
            (submitted["id"], "partially_paid"), (submitted["id"], "paid"), (submitted["id"], "voided"),
            (paid["id"], "submitted"), (paid["id"], "approved"), (paid["id"], "partially_paid"), (paid["id"], "voided"),
            (partial["id"], "submitted"), (partial["id"], "approved"), (partial["id"], "voided"),
            (submitted["id"], "reopened"),  # unknown status: CHECK constraint
        )
        for claim_id, status in illegal:
            with self.assertRaises(sqlite3.DatabaseError, msg=f"{status} should be rejected"):
                self.c.db.execute("UPDATE reimbursement_claims SET status=? WHERE id=?", (status, claim_id))
        self.assertEqual(self.r.claim(submitted["id"])["status"], "submitted")
        self.assertEqual(self.r.claim(paid["id"])["status"], "paid")
        self.assertEqual(self.r.claim(partial["id"])["status"], "partially_paid")
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])

    def test_cancel_draft_billing_releases_reservation_and_invalidates_approval(self):
        cl = self.s.approved_claim("120.00")
        b = self.r.create_billing(cl["id"], "120.00", actor="pm")
        ap = self.c.request_approval("reimbursement.bill", b["id"])
        self.c.approve(ap["id"])
        with self.assertRaises(ReimbursementError):  # the draft reserves the whole claim amount
            self.r.create_billing(cl["id"], "0.01", actor="pm")
        self.r.cancel_billing(b["id"], actor="pm", reason="wrong customer PO")
        self.assertEqual(self.r.billing(b["id"])["status"], "canceled")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ReimbursementError):  # a canceled billing has no manifest to execute against
            self.c.execute(ap["id"], period_id="P1")
        with self.assertRaises(ReimbursementError):
            self.r.cancel_billing(b["id"], actor="pm")
        b2 = self.r.create_billing(cl["id"], "120.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b2["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("120.00"))
        self.assertEqual(self.r.claim(cl["id"])["billed"], "120.00")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual([x["status"] for x in self.r.claim(cl["id"])["billings"]], ["canceled", "billed"])

    def test_destination_change_invalidates_granted_pay_approval(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "120.00", actor="t")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.assertEqual(ap["manifest"]["destination"]["party_id"], self.s.employee["id"])
        self.assertEqual(ap["manifest"]["destination"]["destination"], "ACH-EMP-1")
        self.assertEqual(ap["manifest"]["destination"]["destination_version"], 2)
        self.assertTrue(ap["manifest"]["bindings"]["destination_verified"])
        self.c.approve(ap["id"])
        self.c.verify_destination(self.s.employee["id"], destination="ACH-EMP-2", verified_by="owner")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.payments.list(), [])  # nothing reached the outbox
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("0.00"))
        # a fresh approval binds the newly verified destination and its version
        ap2 = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.assertTrue(ap2["manifest"]["bindings"]["destination_verified"])
        self.assertEqual(ap2["manifest"]["destination"]["destination_version"], 3)
        self.c.approve(ap2["id"])
        res = self.c.execute(ap2["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.payments.get(res.result["intent"])["destination"], "ACH-EMP-2")
        self.c.dispatch_payments()
        self.s.settle(p["id"])
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-120.00"))

    def test_execute_replay_is_idempotent(self):
        cl = self.s.claim("120.00")
        ap = self.c.request_approval("reimbursement.approve", cl["id"])
        self.c.approve(ap["id"])
        first = self.c.execute(ap["id"], period_id="P1")
        replay = self.c.execute(ap["id"], period_id="P1")
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, first.result)
        with self.assertRaises((ApprovalConsumed, ReimbursementError)):  # another worker's op id cannot post it again either
            self.c.execute(ap["id"], period_id="P1", op_id="exec:second-worker")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 1)
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "consumed")
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_billing_a_paid_claim_leaves_payable_at_zero(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "120.00", actor="t")
        self.s.pay(p["id"])
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        b = self.r.create_billing(cl["id"], "120.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b["id"], period_id="P1")
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")  # billing never changes the claim's payable status
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("4000"), Decimal("120.00"))
        rec = self.r.employee_payable_reconciliation(self.s.project["id"])
        self.assertEqual(rec["items"], [])  # paid claims are out of the payable subledger
        self.assertTrue(rec["reconciled"])


class ReimbursementVoidTests(unittest.TestCase):
    """reimbursement.void: the only correction path for an approval granted in error."""

    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.r = self.s.r

    def test_void_reverses_approval_and_releases_receipt(self):
        cl = self.s.approved_claim("120.00")
        receipt = cl["receipt_hash"]
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        res = self.c.approve_and_execute("reimbursement.void", cl["id"], period_id="P1")
        self.assertEqual(res.result["status"], "voided")
        self.assertEqual(res.result["amount"], "120.00")
        self.assertEqual(res.result["reversed_journal_id"], cl["journal_id"])
        self.assertEqual(res.result["payments_canceled"], [])
        self.assertEqual(res.result["billings_canceled"], [])
        cl = self.r.claim(cl["id"])
        self.assertEqual(cl["status"], "voided")
        self.assertEqual(cl["outstanding"], "0.00")
        self.assertEqual(cl["amount"], "120.00")  # the record itself is history, not edited
        self.assertIsNotNone(cl["voided_at"])
        self.assertIsNotNone(cl["void_approval_id"])
        self.assertNotEqual(cl["void_approval_id"], cl["approval_id"])
        rev = self.c.ledger.journal(cl["reversal_journal_id"])
        self.assertEqual(rev["reversal_of"], cl["journal_id"])
        self.assertEqual(rev["approval_id"], cl["void_approval_id"])
        self.assertEqual(self.c.ledger.journal(cl["journal_id"])["reversed_by"], rev["id"])
        by_account = {ln["account_code"]: ln for ln in rev["lines"]}
        self.assertEqual(by_account["2100"]["debit"], "120.00")
        self.assertEqual(by_account["5100"]["credit"], "120.00")
        self.assertEqual(by_account["2100"]["party_id"], self.s.employee["id"])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("5100"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 2)  # original + reversal; nothing deleted
        rec = self.r.employee_payable_reconciliation(self.s.project["id"])
        self.assertEqual(rec["items"], [])
        self.assertEqual(rec["subledger_total"], "0.00")
        self.assertTrue(rec["reconciled"])
        # a voided claim is frozen and finished
        with self.assertRaises(ReimbursementError):
            self.r.update_claim(cl["id"], actor="emp", amount="1.00")
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "1.00", actor="t")
        with self.assertRaises(ReimbursementError):
            self.r.create_billing(cl["id"], "1.00", actor="pm")
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.void", cl["id"])
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.approve", cl["id"])
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("UPDATE reimbursement_claims SET status='approved' WHERE id=?", (cl["id"],))
        # the receipt is released for a corrected resubmission, still one live claim per receipt
        again = self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="Mileage to site (corrected)", amount="110.00", receipt_hash=receipt, actor="emp")
        self.assertEqual(again["status"], "submitted")
        with self.assertRaises(ReimbursementError):
            self.r.submit_claim(project_id=self.s.project["id"], employee_id=self.s.employee["id"], description="dup", amount="1.00", receipt_hash=receipt, actor="emp")
        self.assertEqual([c["status"] for c in self.r.claims(self.s.project["id"])], ["voided", "submitted"])
        self.c.approve_and_execute("reimbursement.approve", again["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("110.00"))
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_void_only_for_approved_claims_with_nothing_paid_or_billed(self):
        submitted = self.s.claim("10.00")
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.void", submitted["id"])
        paid = self.s.approved_claim("50.00")
        p = self.r.record_payment(paid["id"], "20.00", actor="t")
        self.s.release(p["id"])
        self.assertEqual(self.r.claim(paid["id"])["status"], "approved")
        with self.assertRaises(ReimbursementError):  # money is moving
            self.c.request_approval("reimbursement.void", paid["id"])
        self.c.dispatch_payments()
        self.s.settle(p["id"])
        with self.assertRaises(ReimbursementError):  # money has moved
            self.c.request_approval("reimbursement.void", paid["id"])
        billed = self.s.approved_claim("60.00")
        b = self.r.create_billing(billed["id"], "60.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b["id"], period_id="P1")
        self.assertEqual(self.r.claim(billed["id"])["status"], "approved")
        with self.assertRaises(ReimbursementError):  # the customer has been billed
            self.c.request_approval("reimbursement.void", billed["id"])
        # drafts do not block a void: they are canceled with it and their approvals invalidated
        cl = self.s.approved_claim("120.00")
        draft_pay = self.r.record_payment(cl["id"], "40.00", actor="t")
        draft_bill = self.r.create_billing(cl["id"], "120.00", actor="pm")
        pay_ap = self.c.request_approval("reimbursement.pay", draft_pay["id"], actor_role="treasury")
        self.c.approve(pay_ap["id"])
        res = self.c.approve_and_execute("reimbursement.void", cl["id"], period_id="P1")
        self.assertEqual(res.result["payments_canceled"], [draft_pay["id"]])
        self.assertEqual(res.result["billings_canceled"], [draft_bill["id"]])
        self.assertEqual(self.r.payment(draft_pay["id"])["status"], "canceled")
        self.assertEqual(self.r.billing(draft_bill["id"])["status"], "canceled")
        self.assertEqual(self.c.approvals.get(pay_ap["id"])["status"], "invalidated")
        with self.assertRaises(ReimbursementError):
            self.c.execute(pay_ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("90.00"))  # 30.00 + 60.00; the voided 120.00 is gone
        self.assertEqual(self.c.ledger.balance("5100"), Decimal("110.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-20.00"))
        rec = self.r.employee_payable_reconciliation(self.s.project["id"])
        self.assertEqual(rec["subledger_total"], "90.00")
        self.assertTrue(rec["reconciled"])
        self.assertEqual(self.c.approvals.list(status="granted"), [])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_void_cannot_be_dated_before_the_approval_it_reverses(self):
        self.c.open_period("P0", "P0", "2026-09-01", "2026-09-30")
        cl = self.s.approved_claim("250.00")  # approved in October (P1)
        ap = self.c.request_approval("reimbursement.void", cl["id"])
        self.assertIn("2026-10-01", ap["manifest"]["bindings"]["target_rule"])
        self.c.approve(ap["id"])
        with self.assertRaises(ReimbursementError) as ctx:  # September starts before the approval journal
            self.c.execute(ap["id"], period_id="P0")
        self.assertIn("cannot be dated before", str(ctx.exception))
        self.assertEqual(self.r.claim(cl["id"])["status"], "approved")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # the failed command rolled back
        self.assertEqual(self.c.ledger.journals(period_id="P0"), [])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("250.00"))
        res = self.c.execute(ap["id"])  # default: the latest open period
        self.assertEqual((res.result["status"], res.result["period_id"]), ("voided", "P1"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_void_approval_dies_with_a_payment_and_respects_the_period_lock(self):
        cl = self.s.approved_claim("120.00")
        ap = self.c.request_approval("reimbursement.void", cl["id"])
        self.c.approve(ap["id"])
        self.assertEqual(ap["manifest"]["bindings"]["journal_id"], cl["journal_id"])
        self.assertEqual(ap["manifest"]["amounts"]["booked_payments"], "0.00")
        # a payment released after the void was granted makes the void meaningless
        p = self.r.record_payment(cl["id"], "40.00", actor="t")
        self.s.release(p["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.c.dispatch_payments()
        self.s.settle(p["id"])
        with self.assertRaises((ApprovalNotGranted, ReimbursementError)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.r.claim(cl["id"])["status"], "partially_paid")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        # the same happens when the customer is billed after the void was granted
        billed = self.s.approved_claim("30.00")
        ap_b = self.c.request_approval("reimbursement.void", billed["id"])
        self.c.approve(ap_b["id"])
        b = self.r.create_billing(billed["id"], "30.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap_b["id"])["status"], "invalidated")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("110.00"))
        # the reversal obeys the period lock like every other posting
        other = self.s.approved_claim("25.00")
        ap2 = self.c.request_approval("reimbursement.void", other["id"])
        self.c.approve(ap2["id"])
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap2["id"], period_id="P1")
        self.assertEqual(self.r.claim(other["id"])["status"], "approved")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "granted")  # the failed command rolled back
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("135.00"))
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        res = self.c.execute(ap2["id"], period_id="P2")
        self.assertEqual(res.result["period_id"], "P2")
        self.assertEqual(self.c.ledger.journal(res.result["reversal_journal_id"])["period_id"], "P2")
        self.assertEqual(self.r.claim(other["id"])["status"], "voided")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("110.00"))
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class ReimbursementReceivableTests(unittest.TestCase):
    """Billings debit 1100; collections (and only collections, or a reversal of the billing
    journal) clear them, so the AR items reconcile to the 1100 postings they made."""

    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.r = self.s.r
        self.pid = self.s.project["id"]

    def billed(self, amount="120.00"):
        cl = self.s.approved_claim(amount)
        b = self.r.create_billing(cl["id"], amount, actor="pm")
        self.c.approve_and_execute("reimbursement.bill", b["id"], period_id="P1")
        return self.r.billing(b["id"])

    def assertReceivable(self, open_total):
        ar = self.r.ar_open_items(self.pid)
        self.assertEqual((ar["subledger_total"], ar["ledger_postings"], ar["reconciled_to_postings"]), (open_total, open_total, True))
        self.assertEqual(self.c.ledger.balance("1100", project_id=self.pid), Decimal(open_total))
        checks = {chk["check"]: chk for chk in self.r.close_checks("P1")}
        self.assertTrue(checks["reimbursement billings receivable matches its 1100 postings"]["ok"])
        rec = self.c.receivables.ar_open_items(self.pid)
        if Decimal(rec["subledger_total"]) != 0:  # the receivables domain includes this source in its AR subledger
            self.assertTrue(rec["reconciled"], rec)
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        return ar

    def test_collections_clear_the_billing_receivable(self):
        b = self.billed("120.00")
        ar = self.assertReceivable("120.00")
        self.assertEqual([(i["kind"], i["billing_id"], i["amount_due"], i["received"], i["open"]) for i in ar["items"]],
                         [("reimbursement_billing", b["id"], "120.00", "0.00", "120.00")])
        col = self.r.record_billing_collection(b["id"], "50.00", period_id="P1", provider_ref="ach-sim-rb-0001", fee="1.00", actor="treasury")
        self.assertEqual((col["amount"], col["fee"], col["billing_id"], col["period_id"]), ("50.00", "1.00", b["id"], "P1"))
        j = self.c.ledger.journal(col["journal_id"])
        self.assertEqual([(ln["account_code"], ln["debit"], ln["credit"]) for ln in j["lines"]],
                         [("1000", "49.00", "0.00"), ("6000", "1.00", "0.00"), ("1100", "0.00", "50.00")])
        self.assertTrue(all(ln["project_id"] == self.pid and ln["party_id"] == self.s.customer["id"] for ln in j["lines"]))
        ar = self.assertReceivable("70.00")
        self.assertEqual((ar["items"][0]["received"], ar["items"][0]["open"]), ("50.00", "70.00"))
        self.assertEqual((self.c.ledger.balance("1000"), self.c.ledger.balance("6000")), (Decimal("49.00"), Decimal("1.00")))
        bad = [
            dict(amount="20.00", provider_ref="ach-sim-rb-0001"),  # the same receipt twice
            dict(amount="70.01", provider_ref="ach-sim-rb-0002"),  # more than is open
            dict(amount="10.00", provider_ref="ach-sim-rb-0003", fee="10.01"),  # fee above the receipt
            dict(amount="10.00", provider_ref="ach-sim-rb-0004", fee="-0.01"),
            dict(amount="0", provider_ref="ach-sim-rb-0005"),
            dict(amount="10.00", provider_ref="  "),
        ]
        for kwargs in bad:
            with self.assertRaises(ReimbursementError, msg=str(kwargs)):
                self.r.record_billing_collection(b["id"], kwargs.pop("amount"), period_id="P1", actor="treasury", **kwargs)
        self.assertReceivable("70.00")
        self.r.record_billing_collection(b["id"], "70.00", period_id="P1", provider_ref="ach-sim-rb-0006", actor="treasury")
        ar = self.assertReceivable("0.00")
        self.assertEqual(ar["items"][0]["open"], "0.00")
        with self.assertRaises(ReimbursementError):
            self.r.record_billing_collection(b["id"], "0.01", period_id="P1", provider_ref="ach-sim-rb-0007", actor="treasury")
        self.assertEqual(len(self.r.collections(self.pid)), 2)
        self.assertEqual(self.r.ar_open_items(self.c.create_project(name="Other", entity="E", budget="0")["id"])["items"], [])

    def test_only_posted_billings_in_open_periods_are_collected(self):
        cl = self.s.approved_claim("80.00")
        draft = self.r.create_billing(cl["id"], "80.00", actor="pm")
        with self.assertRaises(ReimbursementError):
            self.r.record_billing_collection(draft["id"], "10.00", period_id="P1", provider_ref="ach-sim-rb-0100", actor="treasury")
        self.c.approve_and_execute("reimbursement.bill", draft["id"], period_id="P1")
        self.c.close_period("P1")
        journals = self.c.ledger.trial_balance()["journal_count"]
        with self.assertRaises(PeriodNotOpen):
            self.r.record_billing_collection(draft["id"], "10.00", period_id="P1", provider_ref="ach-sim-rb-0101", actor="treasury")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], journals)
        self.assertEqual(self.r.collections(self.pid), [])
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        col = self.r.record_billing_collection(draft["id"], "80.00", period_id="P2", provider_ref="ach-sim-rb-0101", actor="treasury")
        self.assertEqual(self.c.ledger.journal(col["journal_id"])["period_id"], "P2")
        self.assertReceivable("0.00")

    def test_a_collection_cannot_be_dated_before_the_billing_it_settles(self):
        self.c.open_period("P0", "P0", "2026-09-01", "2026-09-30")
        b = self.billed("300.00")  # billed in October (P1)
        journals = self.c.ledger.trial_balance()["journal_count"]
        with self.assertRaises(ReimbursementError) as ctx:  # September starts before the billing journal
            self.r.record_billing_collection(b["id"], "300.00", period_id="P0", provider_ref="ach-sim-rb-0150", actor="treasury")
        self.assertIn("cannot be dated before", str(ctx.exception))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], journals)
        self.assertEqual(self.c.ledger.journals(period_id="P0"), [])
        self.assertEqual(self.r.collections(self.pid), [])
        col = self.r.record_billing_collection(b["id"], "300.00", period_id="P1", provider_ref="ach-sim-rb-0150", actor="treasury")
        self.assertEqual(self.c.ledger.journal(col["journal_id"])["period_id"], "P1")
        self.assertReceivable("0.00")

    def test_collections_are_immutable_and_cite_their_own_journal(self):
        b = self.billed("60.00")
        col = self.r.record_billing_collection(b["id"], "60.00", period_id="P1", provider_ref="ach-sim-rb-0200", actor="treasury")
        db = self.c.db
        for sql, params in (
            ("UPDATE reimbursement_collections SET amount='1.00' WHERE id=?", (col["id"],)),
            ("DELETE FROM reimbursement_collections WHERE id=?", (col["id"],)),
            ("INSERT INTO reimbursement_collections (id, billing_id, amount, fee, provider_ref, journal_id, period_id, received_at, recorded_by) "
             "VALUES ('rcol_forged', ?, '5.00', '0.00', 'forged', ?, 'P1', 't', 'x')", (b["id"], col["journal_id"])),  # another collection's journal
        ):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql, params)
        self.assertReceivable("0.00")

    def test_a_reversed_billing_journal_clears_the_receivable(self):
        b = self.billed("45.00")
        self.c.ledger.reverse(b["journal_id"], period_id="P1", posted_by="controller", reason="billed to the wrong customer (synthetic)")
        ar = self.assertReceivable("0.00")
        self.assertEqual((ar["items"][0]["reversed"], ar["items"][0]["open"]), ("45.00", "0.00"))
        with self.assertRaises(ReimbursementError):
            self.r.record_billing_collection(b["id"], "45.00", period_id="P1", provider_ref="ach-sim-rb-0300", actor="treasury")

    def test_a_reversed_billing_frees_its_amount_to_be_billed_again_once(self):
        b = self.billed("45.00")
        self.c.ledger.prepare_reversal(b["journal_id"], "billed under the wrong project phase; reissue (synthetic)", "accountant")
        self.c.approve_and_execute("journal.reverse", b["journal_id"], actor="accountant", period_id="P1")
        self.assertEqual(self.r.claim(b["claim_id"])["billed"], "0.00")
        again = self.r.create_billing(b["claim_id"], "45.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", again["id"], period_id="P1")
        self.assertEqual(self.r.claim(b["claim_id"])["billed"], "45.00")
        self.assertReceivable("45.00")
        self.assertEqual(self.c.ledger.balance("4000", project_id=self.pid), Decimal("45.00"))
        with self.assertRaisesRegex(ReimbursementError, "exceeds the unbilled claim amount"):
            self.r.create_billing(b["claim_id"], "0.01", actor="pm")  # billed again exactly once


class ReimbursementPaymentControlTests(unittest.TestCase):
    """Reimbursement payments under the core payment controls: canceled intents, transfer
    terms bound by the approval, and the kill switch."""

    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.r = self.s.r

    def test_canceled_intent_puts_the_payment_back_to_draft_and_keeps_the_claim_payable(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        res = self.s.release(p["id"])
        released = self.r.payment(p["id"])
        journals = self.c.ledger.trial_balance()["journal_count"]
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("80.00"))
        out = self.c.payments.cancel_intent(res.result["intent"], "employee asked for a single payment", "treasury")
        self.assertEqual(out["status"], "canceled")
        self.assertEqual((out["source_type"], out["source_id"]), ("reimbursement_payment", p["id"]))  # the canceled intent still names the payment
        pay = self.r.payment(p["id"])
        self.assertEqual((pay["status"], pay["intent_id"], pay["approval_id"], pay["journal_id"], pay["released_at"]), ("draft", None, None, None, None))
        self.assertEqual(pay["version"], released["version"] + 1)
        claim = self.r.claim(cl["id"])
        self.assertEqual((claim["status"], claim["outstanding"], claim["in_flight"], claim["paid"]), ("approved", "120.00", "0.00", "0.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], journals)
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])
        self.assertTrue(all(chk["ok"] for chk in self.r.close_checks("P1")))
        reopened = [e for e in self.c.audit.entries(entity_id=p["id"]) if e["action"] == "reimbursement.payment_reopened"]
        self.assertEqual(len(reopened), 1)
        self.assertEqual(self.c.dispatch_payments(), [])
        self.assertEqual(len(self.c.provider.submissions), 0)
        # the consumed approval cannot release it again: the reopened draft needs a fresh approval
        first_approval = res.op_id.split(":", 1)[1]
        self.assertTrue(self.c.execute(first_approval, actor="treasury", period_id="P1").replayed)  # a replay only returns the stored result
        with self.assertRaises(ApprovalConsumed):
            self.c.execute(first_approval, actor="treasury", op_id="exec-again-after-cancel", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(len(self.c.commands.pending("payment")), 0)
        # the drafted amount is reserved again, so nothing can overpay the claim
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "120.00", actor="treasury")
        again = self.s.release(p["id"])
        self.assertNotEqual(again.result["intent"], res.result["intent"])
        self.assertEqual(self.r.payment(p["id"])["status"], "in_flight")
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(self.r.payment(p["id"])["status"], "booked")
        rest = self.r.record_payment(cl["id"], "80.00", actor="treasury")
        self.s.pay(rest["id"])
        self.s.settle(p["id"])
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertEqual((self.c.ledger.balance("2100"), self.c.ledger.balance("1000")), (Decimal("0.00"), Decimal("-120.00")))
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])
        self.assertTrue(all(chk["ok"] for chk in self.r.close_checks("P1")))
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_a_reopened_draft_can_be_canceled_and_raw_reopening_is_refused(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        self.s.release(p["id"])
        db = self.c.db
        # an in-flight payment cannot be reopened while its intent is still queued
        with self.assertRaisesRegex(sqlite3.DatabaseError, "follow their payment intent"):
            db.execute("UPDATE reimbursement_payments SET status='draft', intent_id=NULL, approval_id=NULL WHERE id=?", (p["id"],))
        self.c.payments.cancel_intent(self.r.payment(p["id"])["intent_id"], "drill", "treasury")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.r.cancel_payment(p["id"], actor="treasury", reason="not needed")["status"], "canceled")
        self.assertEqual(self.r.claim(cl["id"])["outstanding"], "120.00")
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])

    def test_pay_manifest_binds_the_transfer_terms(self):
        from apps.cipher.core.ids import utcnow
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        m = ap["manifest"]
        self.assertEqual((m["entity"], m["currency"]), ("E", "USD"))
        self.assertEqual((m["bindings"]["fees"], m["bindings"]["value_date"]), ("0.00", utcnow().date().isoformat()))
        self.c.approve(ap["id"], approver="treasury", approver_role="treasury")
        self.c.provider.fee = "0.25"  # the provider's fee changes after the grant
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.payments.list(), [])
        res = self.s.release(p["id"])  # approved at the new fee
        intent = self.c.payments.get(res.result["intent"])
        self.assertEqual((intent["fee"], intent["entity"], intent["currency"]), ("0.25", "E", "USD"))
        self.c.dispatch_payments()
        self.s.settle(p["id"])
        self.assertEqual((self.c.ledger.balance("2100"), self.c.ledger.balance("1000"), self.c.ledger.balance("6000")),
                         (Decimal("80.00"), Decimal("-40.25"), Decimal("0.25")))
        self.assertTrue(self.r.employee_payable_reconciliation(self.s.project["id"])["reconciled"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_kill_switch_refuses_a_reimbursement_release(self):
        from apps.cipher.domain.payments import KillSwitchEngaged
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.c.approve(ap["id"], approver="treasury", approver_role="treasury")
        self.c.payments.engage_kill_switch("treasury drill", "owner")
        self.assertEqual(self.c.ricky.propose("reimbursement.pay", actor_role="treasury", context={"payment_id": p["id"]})["decision"], "abstained")
        with self.assertRaises(KillSwitchEngaged):
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.c.approve_and_execute("payment.resume_releases", "payments", actor_role="treasury", actor="treasury")
        self.assertEqual(self.c.execute(ap["id"], actor="treasury", period_id="P1").result["status"], "in_flight")
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["accepted"])
        self.assertEqual(self.r.payment(p["id"])["status"], "booked")


class ReimbursementRestoreAdoptionTests(unittest.TestCase):
    """A restored older backup whose provider holds a reimbursement transfer the copy never
    recorded keeps the release quarantine until the transfer is adopted (payment.adopt_transfer)."""

    def setUp(self):
        d = tempfile.mkdtemp(prefix="cipher-rmb-restore-")
        self.addCleanup(shutil.rmtree, d, True)
        self.dir = d
        self.s = Scenario(os.path.join(d, "live.sqlite"))
        self.addCleanup(self.s.c.db.close)
        self.c = self.s.c
        self.r = self.s.r

    def restored(self, name):
        copy = Cipher.open_restored(self.c.snapshot(os.path.join(self.dir, name)), provider=self.c.provider)
        self.addCleanup(copy.db.close)
        copy.claim_write_authority(approval_ref="ext-ref-rmb-restore", actor="owner", reason="restore drill: claim the recovered copy")
        return copy

    def adopt(self, copy, provider_ref):
        return copy.approve_and_execute("payment.adopt_transfer", provider_ref, actor_role="owner", actor="owner").result

    def assert_clean(self, copy, project_id):
        rr = copy.plugin(PLUGIN_NAME)
        self.assertTrue(rr.employee_payable_reconciliation(project_id)["reconciled"])
        self.assertTrue(all(chk["ok"] for chk in rr.close_checks("P1")), rr.close_checks("P1"))
        self.assertTrue(copy.payments.clearing_items()["reconciled"])
        self.assertTrue(copy.ledger.trial_balance()["balanced"])
        self.assertTrue(copy.audit.verify_chain()["ok"])

    def test_a_draft_in_the_backup_paid_by_the_live_workspace_is_adopted_not_paid_again(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        copy = self.restored("backup-draft.sqlite")  # the payment is still a draft here
        self.s.pay(p["id"])  # live: released, accepted and settled
        self.assertEqual((len(self.c.provider.submissions), len(self.c.provider.transfers)), (1, 1))
        rr = copy.plugin(PLUGIN_NAME)
        self.assertEqual(rr.payment(p["id"])["status"], "draft")
        outcome = copy.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        [t] = outcome["unrecorded_transfers"]
        self.assertEqual((t["provider_ref"], t["amount"], t["status"], t["adoptable"], t["pays"]), ("sim_000001", "40.00", "settled", True, f"reimbursement_payment {p['id']}"))
        # releasing the same payment from this copy is exactly the double payment the quarantine prevents
        ap = copy.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        copy.approve(ap["id"], approver="treasury", approver_role="treasury")
        with self.assertRaises(ReleaseQuarantined):
            copy.execute(ap["id"], actor="treasury", period_id="P1")
        result = self.adopt(copy, "sim_000001")
        self.assertEqual((result["status"], result["source_id"], result["superseded"]), ("settled", p["id"], []))
        self.assertEqual(rr.payment(p["id"])["status"], "booked")
        claim = rr.claim(cl["id"])
        self.assertEqual((claim["status"], claim["paid"], claim["outstanding"]), ("partially_paid", "40.00", "80.00"))
        self.assertEqual((copy.ledger.balance("2100"), copy.ledger.balance("1000"), copy.ledger.balance("1200")), (Decimal("80.00"), Decimal("-40.00"), Decimal("0.00")))
        self.assertEqual(copy.approvals.get(ap["id"])["status"], "invalidated")  # the payment is booked: that release is moot
        lifted = copy.complete_recovery(actor="reconciler")
        self.assertTrue(lifted["quarantine_lifted"], lifted["held"])
        self.assertEqual(copy.dispatch_payments(), [])
        self.assertEqual((len(self.c.provider.submissions), len(self.c.provider.transfers)), (1, 1))
        self.assert_clean(copy, self.s.project["id"])

    def test_a_queued_release_the_live_workspace_canceled_and_replaced_is_superseded(self):
        cl = self.s.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        first = self.s.release(p["id"]).result["intent"]
        copy = self.restored("backup-in-flight.sqlite")  # in flight on a queued intent here
        self.c.payments.cancel_intent(first, "wrong funding account", "treasury")  # live: back to draft ...
        self.s.release(p["id"])  # ... and released again under a fresh approval
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["accepted"])
        submissions = len(self.c.provider.submissions)
        rr = copy.plugin(PLUGIN_NAME)
        outcome = copy.complete_recovery(actor="reconciler")
        self.assertFalse(outcome["quarantine_lifted"])
        self.assertEqual(outcome["queued"], [first])  # the provider never saw it, so it stays queued ...
        self.assertEqual([(t["provider_ref"], t["supersedes"]) for t in outcome["unrecorded_transfers"]], [("sim_000001", [first])])  # ... but it is replaced
        with self.assertRaises(ReleaseQuarantined):
            copy.dispatch_payments()
        result = self.adopt(copy, "sim_000001")
        self.assertEqual((result["status"], result["superseded"]), ("accepted", [first]))
        old = copy.payments.get(first)
        self.assertEqual(old["status"], "canceled")
        self.assertIn("superseded by provider transfer sim_000001", copy.commands.get(old["outbox_id"])["last_error"])
        pay = rr.payment(p["id"])
        self.assertEqual((pay["status"], pay["intent_id"]), ("booked", result["intent"]))
        self.assertEqual(copy.ledger.balance("2100"), Decimal("80.00"))
        lifted = copy.complete_recovery(actor="reconciler")
        self.assertTrue(lifted["quarantine_lifted"], lifted["held"])
        self.assertEqual(lifted["queued"], [])
        self.assertEqual(copy.dispatch_payments(), [])
        self.assertEqual(len(self.c.provider.submissions), submissions)  # nothing sent twice
        self.assert_clean(copy, self.s.project["id"])


if __name__ == "__main__":
    unittest.main()
