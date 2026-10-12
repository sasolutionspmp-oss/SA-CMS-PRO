"""Staff expense reimbursements: golden sequence and adversarial variants."""
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
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
            self.c.request_approval("reimbursement.void", cl["id"])

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


if __name__ == "__main__":
    unittest.main()
