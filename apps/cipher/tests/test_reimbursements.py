"""Staff expense reimbursements: golden sequence and adversarial variants."""
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalConsumed, ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.reimbursements import PLUGIN_NAME, ReimbursementError
from apps.cipher.service import Cipher


class Scenario:
    """Fresh in-memory workspace: employee, supplier, customer, project, open period P1."""

    def __init__(self):
        self.c = Cipher()
        self.r = self.c.plugin(PLUGIN_NAME)
        self.employee = self.c.add_party(kind="employee", name="Field Engineer", destination="ACH-EMP-1")
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

        # partial payment
        pay = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        self.assertEqual(pay["status"], "draft")
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("120.00"))  # drafts do not reduce the payable
        res = self.c.approve_and_execute("reimbursement.pay", pay["id"], actor_role="treasury", actor="treasury", period_id="P1")
        self.assertEqual(res.result["status"], "booked")
        self.assertEqual(res.result["outstanding"], "80.00")
        self.assertEqual(self.r.payment(pay["id"])["status"], "booked")
        cl = self.r.claim(cl["id"])
        self.assertEqual(cl["status"], "partially_paid")
        self.assertEqual(cl["outstanding"], "80.00")
        self.assertEqual(self.r.outstanding(cl["id"]), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-40.00"))

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
        self.c.approve_and_execute("reimbursement.pay", p1["id"], period_id="P1")
        self.assertEqual(self.r.claim(cl["id"])["status"], "partially_paid")
        p2 = self.r.record_payment(cl["id"], "80.00", actor="t")
        res = self.c.approve_and_execute("reimbursement.pay", p2["id"], period_id="P1")
        self.assertEqual(res.result["claim_status"], "paid")
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
        self.c.execute(ap1["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "granted")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap2["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        self.assertEqual(self.r.payment(p2["id"])["status"], "draft")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        # re-approving the still-valid draft against the current state works
        self.c.approve_and_execute("reimbursement.pay", p2["id"], actor_role="treasury", actor="treasury", period_id="P1")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("40.00"))
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
        self.assertEqual(self.c.ledger.balance("1100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 3)
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
        self.c.approve_and_execute("reimbursement.pay", p["id"], period_id="P1")
        bill = self.r.create_billing(a["id"], "120.00", actor="pm")
        self.c.approve_and_execute("reimbursement.bill", bill["id"], period_id="P1")

        rec = self.r.employee_payable_reconciliation(self.s.project["id"])
        self.assertEqual(rec["subledger_total"], "110.00")
        self.assertEqual(rec["control_balance"], "110.00")
        self.assertTrue(rec["reconciled"])
        self.assertEqual(sorted(i["claim_id"] for i in rec["items"]), sorted([a["id"], b["id"]]))

        st = self.r.state(self.s.project["id"])
        self.assertEqual(set(st), {"claims", "payments", "billings", "reconciliation"})
        self.assertEqual([c["id"] for c in st["claims"]], [a["id"], b["id"], pending["id"]])
        first = st["claims"][0]
        self.assertEqual(first["outstanding"], "80.00")
        self.assertEqual(first["status"], "partially_paid")
        self.assertEqual([x["status"] for x in first["payments"]], ["booked"])
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
        self.assertEqual(self.r.state(empty["id"]), {"claims": [], "payments": [], "billings": [], "reconciliation": {"items": [], "subledger_total": "0.00", "control_balance": "0.00", "reconciled": True}})

    def test_claim_status_transitions_are_enforced_by_schema(self):
        submitted = self.s.claim("10.00")
        paid = self.s.approved_claim("120.00")
        p = self.r.record_payment(paid["id"], "120.00", actor="t")
        self.c.approve_and_execute("reimbursement.pay", p["id"], period_id="P1")
        partial = self.s.approved_claim("50.00")
        p2 = self.r.record_payment(partial["id"], "20.00", actor="t")
        self.c.approve_and_execute("reimbursement.pay", p2["id"], period_id="P1")
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
        self.assertFalse(ap["manifest"]["bindings"]["destination_verified"])
        self.c.approve(ap["id"])
        self.c.verify_destination(self.s.employee["id"], destination="ACH-EMP-2", verified_by="owner")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("0.00"))
        # a fresh approval binds the verified destination and its new version
        ap2 = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.assertTrue(ap2["manifest"]["bindings"]["destination_verified"])
        self.assertEqual(ap2["manifest"]["destination"]["destination_version"], 2)
        self.c.approve(ap2["id"])
        self.c.execute(ap2["id"], actor="treasury", period_id="P1")
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
        self.c.approve_and_execute("reimbursement.pay", p["id"], period_id="P1")
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
        self.c.approve_and_execute("reimbursement.pay", p["id"], period_id="P1")
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

    def test_void_approval_dies_with_a_payment_and_respects_the_period_lock(self):
        cl = self.s.approved_claim("120.00")
        ap = self.c.request_approval("reimbursement.void", cl["id"])
        self.c.approve(ap["id"])
        self.assertEqual(ap["manifest"]["bindings"]["journal_id"], cl["journal_id"])
        self.assertEqual(ap["manifest"]["amounts"]["booked_payments"], "0.00")
        # a payment booked after the void was granted makes the void meaningless
        p = self.r.record_payment(cl["id"], "40.00", actor="t")
        self.c.approve_and_execute("reimbursement.pay", p["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
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


if __name__ == "__main__":
    unittest.main()
