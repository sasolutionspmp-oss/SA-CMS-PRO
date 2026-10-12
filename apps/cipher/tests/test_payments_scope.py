"""Payment intent scope (project, source, payable account) and staff reimbursements
routed through the core payment outbox."""
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalConsumed, ApprovalNotGranted, build_manifest
from apps.cipher.core.db import SCHEMA_CATALOG, Database
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.payments import SCOPE_SCHEMA_NAME, PaymentError, ReleaseQuarantined
from apps.cipher.domain.reimbursements import OUTBOX_GUARDS_SCHEMA_NAME, OUTBOX_SCHEMA_NAME, PLUGIN_NAME, REOPEN_SCHEMA_NAME, SCHEMA_NAME, ReimbursementError
from apps.cipher.service import Cipher


def _lines(journal):
    return {ln["account_code"]: ln for ln in journal["lines"]}


class ReimbursementWorld:
    """Employee with a verified destination, customer, project and open period P1."""

    def __init__(self, path: str = ":memory:", *, provider=None):
        self.c = Cipher(path, provider=provider)
        self.r = self.c.plugin(PLUGIN_NAME)
        emp = self.c.add_party(kind="employee", name="Field Engineer", destination="ACH-EMP-1")
        self.employee = self.c.verify_destination(emp["id"], destination="ACH-EMP-1", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Owner Agency")
        self.project = self.c.create_project(name="Pump station", entity="E", budget="50000", customer_id=self.customer["id"])
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.seq = 0

    def approved_claim(self, amount="120.00", *, employee_id=None):
        self.seq += 1
        cl = self.r.submit_claim(project_id=self.project["id"], employee_id=employee_id or self.employee["id"], description="Mileage to site",
                                 amount=amount, receipt_hash=f"scope-rcpt-{self.seq:04d}", billable=True, actor="emp")
        self.c.approve_and_execute("reimbursement.approve", cl["id"], period_id="P1")
        return self.r.claim(cl["id"])

    def release(self, claim_id, amount, *, period_id="P1"):
        p = self.r.record_payment(claim_id, amount, actor="treasury")
        res = self.c.approve_and_execute("reimbursement.pay", p["id"], actor_role="treasury", actor="treasury", period_id=period_id)
        return p["id"], res.result

    def intent_for(self, payment_id):
        return self.c.payments.get(self.r.payment(payment_id)["intent_id"])

    def settle(self, payment_id):
        return self.c.payments.ingest_event(self.c.provider.settle(self.intent_for(payment_id)["logical_op_id"]), actor="webhook")

    def give_back(self, payment_id, reason="account closed"):
        return self.c.payments.ingest_event(self.c.provider.return_payment(self.intent_for(payment_id)["logical_op_id"], reason), actor="webhook")

    def rec(self):
        return self.r.employee_payable_reconciliation(self.project["id"])

    def supplier_bill(self, installed="10000"):
        """A posted subcontract bill on the same project (10% retainage), payee verified."""
        sup = self.c.add_party(kind="supplier", name="Sub", destination="ACH-SUP-1")
        sup = self.c.verify_destination(sup["id"], destination="ACH-SUP-1", verified_by="owner")
        cmt = self.c.commitments.create(project_id=self.project["id"], supplier_id=sup["id"], title="Sub", sov_lines=[{"description": "a", "amount": "20000"}], actor="o")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        line = self.c.commitments.get(cmt["id"])["sov"][0]["id"]
        b = self.c.bills.certify(commitment_id=cmt["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": installed}], actor="o")
        self.c.approve_and_execute("bill.approve", b["id"])
        return self.c.bills.get(b["id"])


class ReimbursementOutboxTests(unittest.TestCase):
    def setUp(self):
        self.w = ReimbursementWorld()
        self.c = self.w.c
        self.r = self.w.r

    def assertBooksClean(self):
        self.assertTrue(self.w.rec()["reconciled"], self.w.rec())
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_release_queues_a_scoped_intent_and_posts_nothing(self):
        cl = self.w.approved_claim("120.00")
        journals = self.c.ledger.trial_balance()["journal_count"]
        pid, res = self.w.release(cl["id"], "40.00")
        self.assertEqual(res["status"], "in_flight")
        intent = self.c.payments.get(res["intent"])
        self.assertEqual(intent["status"], "queued")
        self.assertEqual(intent["project_id"], self.w.project["id"])
        self.assertEqual(intent["source_type"], "reimbursement_payment")
        self.assertEqual(intent["source_id"], pid)
        self.assertEqual(intent["payable_account"], "2100")
        self.assertIsNone(intent["bill_id"])
        self.assertEqual(intent["party_id"], self.w.employee["id"])
        self.assertEqual((intent["destination"], intent["destination_version"]), ("ACH-EMP-1", 2))
        self.assertEqual(intent["amount"], "40.00")
        self.assertEqual(intent["note"], "reimbursement payment")
        p = self.r.payment(pid)
        self.assertEqual((p["status"], p["intent_id"], p["intent_status"]), ("in_flight", intent["id"], "queued"))
        self.assertIsNone(p["journal_id"])
        self.assertEqual(len(self.c.commands.pending("payment")), 1)
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], journals)
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        rec = self.w.rec()
        self.assertEqual((rec["subledger_total"], rec["in_flight_total"], rec["control_balance"]), ("120.00", "40.00", "120.00"))
        self.assertEqual((rec["items"][0]["payable"], rec["items"][0]["outstanding"]), ("120.00", "80.00"))
        cl = self.r.claim(cl["id"])
        self.assertEqual((cl["status"], cl["payable"], cl["in_flight"], cl["outstanding"], cl["paid"]), ("approved", "120.00", "40.00", "80.00", "0.00"))
        self.assertBooksClean()

    def test_acceptance_books_the_payment_and_settlement_moves_the_bank(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "40.00")
        out = self.c.dispatch_payments()
        self.assertEqual([d["status"] for d in out], ["accepted"])
        intent = self.w.intent_for(pid)
        lines = _lines(self.c.ledger.journal(intent["journal_id"]))
        self.assertEqual((lines["2100"]["debit"], lines["1200"]["credit"]), ("40.00", "40.00"))
        for code in ("2100", "1200"):
            self.assertEqual(lines[code]["project_id"], self.w.project["id"])
            self.assertEqual(lines[code]["party_id"], self.w.employee["id"])
        p = self.r.payment(pid)
        self.assertEqual((p["status"], p["journal_id"], p["period_id"], p["intent_status"]), ("booked", intent["journal_id"], "P1", "accepted"))
        cl = self.r.claim(cl["id"])
        self.assertEqual((cl["status"], cl["outstanding"], cl["paid"]), ("partially_paid", "80.00", "40.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("-40.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("0.00"))
        self.assertBooksClean()
        self.assertTrue(self.w.settle(pid)["applied"])
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-40.00"))
        self.assertEqual(self.r.payment(pid)["status"], "booked")
        self.assertEqual(self.r.payment(pid)["intent_status"], "settled")
        self.assertBooksClean()

    def test_timeout_after_accept_reconciles_to_one_transfer_and_one_posting(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "120.00")
        self.c.provider.mode = "timeout_after_accept"
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["outcome_unknown"])
        p = self.r.payment(pid)
        self.assertEqual((p["status"], p["intent_status"]), ("in_flight", "outcome_unknown"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.w.rec()["in_flight_total"], "120.00")
        with self.assertRaises(ReimbursementError):  # the unknown outcome keeps the amount reserved
            self.r.record_payment(cl["id"], "0.01", actor="treasury")
        checks = {chk["check"]: chk for chk in self.r.close_checks("P1")}
        self.assertTrue(checks["reimbursement payments follow their payment intents"]["ok"])  # in flight is the right state
        self.assertEqual(checks["reimbursement payments in flight"]["detail"], "1 in flight (120.00); they post when the provider accepts them")
        self.assertBooksClean()

        self.c.provider.mode = "accept"
        self.assertEqual([d["status"] for d in self.c.reconcile_payments()], ["accepted"])
        self.assertEqual(self.r.payment(pid)["status"], "booked")
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertEqual(len(self.c.provider.transfers), 1)
        self.assertEqual(len(self.c.provider.submissions), 1)
        self.assertEqual(self.c.reconcile_payments(), [])
        self.assertEqual(self.c.dispatch_payments(), [])
        self.assertEqual(self.c.ledger.account_activity("2100", project_id=self.w.project["id"])["debit"], Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertTrue(all(chk["ok"] for chk in self.r.close_checks("P1")))
        self.assertBooksClean()

    def test_duplicate_settled_event_is_ignored(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "120.00")
        self.c.dispatch_payments()
        event = self.c.provider.settle(self.w.intent_for(pid)["logical_op_id"])
        self.assertTrue(self.c.payments.ingest_event(event, actor="webhook")["applied"])
        dup = self.c.payments.ingest_event(event, actor="webhook")
        self.assertFalse(dup["applied"])
        self.assertEqual(dup["reason"], "duplicate event")
        self.assertEqual(len(self.c.ledger.journals(source_type="provider_event")), 1)
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-120.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("0.00"))
        self.assertEqual(self.r.payment(pid)["status"], "booked")
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertBooksClean()

    def test_return_reinstates_the_payable_and_the_claim_outstanding(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "120.00")
        self.c.dispatch_payments()
        self.w.settle(pid)
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertTrue(self.w.give_back(pid)["applied"])
        self.assertEqual(self.w.intent_for(pid)["status"], "returned")
        self.assertEqual(self.r.payment(pid)["status"], "returned")
        cl = self.r.claim(cl["id"])
        self.assertEqual((cl["status"], cl["outstanding"], cl["paid"], cl["payments_returned"]), ("approved", "120.00", "0.00", 1))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("0.00"))
        ret = [j for j in self.c.ledger.journals(source_type="provider_event") if "returned" in j["description"]][0]
        lines = _lines(ret)
        self.assertEqual((lines["1000"]["debit"], lines["2100"]["credit"]), ("120.00", "120.00"))
        self.assertEqual(lines["2100"]["project_id"], self.w.project["id"])
        self.assertEqual(self.w.rec()["subledger_total"], "120.00")
        self.assertBooksClean()
        # the reinstated obligation can be paid again
        pid2, _ = self.w.release(cl["id"], "120.00")
        self.c.dispatch_payments()
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertEqual(len(self.c.provider.transfers), 2)
        self.assertBooksClean()

    def test_partial_return_before_settlement_moves_a_paid_claim_back_once(self):
        cl = self.w.approved_claim("120.00")
        p1, _ = self.w.release(cl["id"], "40.00")
        p2, _ = self.w.release(cl["id"], "80.00")
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["accepted", "accepted"])
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.w.give_back(p2)  # accepted, not yet settled: the clearing account takes it back
        cl = self.r.claim(cl["id"])
        self.assertEqual((cl["status"], cl["outstanding"], cl["payments_returned"]), ("partially_paid", "80.00", 1))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("-40.00"))
        # without a further returned payment the schema refuses to move the claim back again
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("UPDATE reimbursement_claims SET status='approved' WHERE id=?", (cl["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("UPDATE reimbursement_claims SET status='approved', payments_returned=payments_returned+1 WHERE id=?", (cl["id"],))
        self.assertEqual(self.r.claim(cl["id"])["status"], "partially_paid")
        self.assertBooksClean()

    def test_rejected_payment_fails_and_keeps_the_obligation_open(self):
        cl = self.w.approved_claim("120.00")
        journals = self.c.ledger.trial_balance()["journal_count"]
        pid, _ = self.w.release(cl["id"], "120.00")
        self.c.provider.mode = "reject"
        self.assertEqual([d["status"] for d in self.c.dispatch_payments()], ["failed"])
        p = self.r.payment(pid)
        self.assertEqual((p["status"], p["intent_status"]), ("failed", "failed"))
        cl = self.r.claim(cl["id"])
        self.assertEqual((cl["status"], cl["outstanding"], cl["in_flight"]), ("approved", "120.00", "0.00"))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], journals)
        with self.assertRaises(ReimbursementError):
            self.r.cancel_payment(pid, actor="treasury")
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.pay", pid, actor_role="treasury")
        self.assertBooksClean()
        self.c.provider.mode = "accept"
        self.w.release(cl["id"], "120.00")
        self.c.dispatch_payments()
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        self.assertBooksClean()

    def test_unverified_or_missing_employee_destination_blocks_payment(self):
        unverified = self.c.add_party(kind="employee", name="New Hire", destination="ACH-EMP-9")
        nowhere = self.c.add_party(kind="employee", name="No Bank", destination=None)
        for emp in (unverified, nowhere):
            cl = self.w.approved_claim("50.00", employee_id=emp["id"])
            p = self.r.record_payment(cl["id"], "50.00", actor="treasury")
            with self.assertRaises(ReimbursementError):
                self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
            self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.payments.list(), [])
        self.assertEqual(self.c.commands.pending("payment"), [])

    def test_destination_change_after_grant_makes_the_payment_approval_stale(self):
        cl = self.w.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.assertEqual(ap["manifest"]["destination"], {"party_id": self.w.employee["id"], "destination": "ACH-EMP-1", "destination_version": 2})
        self.assertEqual(ap["manifest"]["amounts"]["amount"], "40.00")
        self.c.approve(ap["id"])
        self.c.verify_destination(self.w.employee["id"], destination="ACH-EMP-ATTACKER", verified_by="owner")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.payments.list(), [])
        self.assertEqual(self.c.commands.pending("payment"), [])

    def test_in_flight_amount_is_reserved_and_blocks_a_void(self):
        cl = self.w.approved_claim("120.00")
        self.w.release(cl["id"], "100.00")
        with self.assertRaises(ReimbursementError):
            self.r.record_payment(cl["id"], "20.01", actor="treasury")
        self.r.record_payment(cl["id"], "20.00", actor="treasury")
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.void", cl["id"])
        self.c.dispatch_payments()
        with self.assertRaises(ReimbursementError):
            self.c.request_approval("reimbursement.void", cl["id"])
        self.assertBooksClean()

    def test_release_needs_an_open_period_and_acceptance_posts_only_into_one(self):
        cl = self.w.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.c.approve(ap["id"])
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertEqual(self.r.payment(p["id"])["status"], "draft")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # the failed command rolled back
        self.assertEqual(self.c.payments.list(), [])
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.c.execute(ap["id"], actor="treasury", period_id="P2")
        self.c.close_period("P2")
        # the provider accepts but no period is open: nothing is posted and the outcome waits for reconciliation
        with self.assertRaises(PaymentError):
            self.c.dispatch_payments()
        self.assertEqual(self.r.payment(p["id"])["status"], "in_flight")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.c.open_period("P3", "P3", "2026-12-01", "2026-12-31")
        self.assertEqual([d["status"] for d in self.c.reconcile_payments()], ["accepted"])
        p = self.r.payment(p["id"])
        self.assertEqual((p["status"], p["period_id"]), ("booked", "P3"))
        self.assertEqual(self.c.ledger.journal(p["journal_id"])["period_id"], "P3")
        self.assertEqual(len(self.c.provider.transfers), 1)
        self.assertBooksClean()

    def test_replayed_or_concurrent_release_creates_one_intent(self):
        cl = self.w.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "120.00", actor="treasury")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.c.approve(ap["id"])
        first = self.c.execute(ap["id"], actor="treasury", period_id="P1")
        replay = self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, first.result)
        with self.assertRaises((ApprovalConsumed, ReimbursementError)):  # the payment is no longer a draft either
            self.c.execute(ap["id"], actor="treasury", period_id="P1", op_id="exec:second-worker")
        # the core refuses a second intent for a source whose intent is still in progress
        forged = dict(ap["manifest"], nonce="forged-second-release")
        ap2 = self.c.approvals.request(forged, requested_by="treasury")
        with self.assertRaises(PaymentError):
            self.c.payments.create_intent(manifest=forged, approval_id=ap2["id"], bill_id=None, note="reimbursement payment", actor="treasury",
                                          project_id=self.w.project["id"], source_type="reimbursement_payment", source_id=p["id"], payable_account="2100")
        self.assertEqual(len(self.c.payments.list()), 1)
        self.c.dispatch_payments()
        self.c.dispatch_payments()
        self.assertEqual(len(self.c.provider.transfers), 1)
        self.assertEqual(len(self.c.provider.submissions), 1)
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertBooksClean()

    def test_payment_rows_can_only_follow_their_intent(self):
        cl = self.w.approved_claim("120.00")
        draft = self.r.record_payment(cl["id"], "10.00", actor="treasury")
        moving, _ = self.w.release(cl["id"], "40.00")
        db = self.c.db
        illegal = [
            ("UPDATE reimbursement_payments SET status='booked' WHERE id=?", (moving,)),  # intent only queued
            ("UPDATE reimbursement_payments SET status='failed' WHERE id=?", (moving,)),
            ("UPDATE reimbursement_payments SET intent_id=NULL WHERE id=?", (moving,)),
            ("UPDATE reimbursement_payments SET status='in_flight' WHERE id=?", (draft["id"],)),  # no intent
            ("UPDATE reimbursement_payments SET amount='1.00' WHERE id=?", (draft["id"],)),
            ("DELETE FROM reimbursement_payments WHERE id=?", (draft["id"],)),
            ("INSERT INTO reimbursement_payments (id, claim_id, amount, status, version, created_at) VALUES ('rpay_forged', ?, '5.00', 'booked', 1, 't')", (cl["id"],)),
        ]
        for sql, params in illegal:
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql, params)
        self.c.dispatch_payments()
        for sql in ("UPDATE reimbursement_payments SET status='returned' WHERE id=?", "UPDATE reimbursement_payments SET status='draft' WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql, (moving,))
        self.assertEqual(self.r.payment(moving)["status"], "booked")
        self.assertEqual(self.r.payment(draft["id"])["status"], "draft")
        self.assertBooksClean()

    def test_sync_repairs_payments_whose_intent_moved_while_unobserved(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "40.00")
        self.c.payments._listeners.clear()  # a worker process that did not load this module
        self.c.dispatch_payments()
        self.assertEqual(self.r.payment(pid)["status"], "in_flight")
        self.assertFalse(self.w.rec()["reconciled"])
        checks = {chk["check"]: chk["ok"] for chk in self.r.close_checks("P1")}
        self.assertFalse(checks["reimbursement payments follow their payment intents"])
        out = self.r.sync_payments(actor="owner")
        self.assertEqual(out["moved"], [{"payment": pid, "intent": self.w.intent_for(pid)["id"], "intent_status": "accepted", "moved": ["booked"]}])
        self.assertEqual(self.r.payment(pid)["status"], "booked")
        self.assertEqual(self.r.claim(cl["id"])["status"], "partially_paid")
        self.assertEqual(self.r.sync_payments(actor="owner"), {"moved": []})
        self.assertTrue(all(chk["ok"] for chk in self.r.close_checks("P1")))
        self.assertBooksClean()

    def test_employee_payee_without_project_never_crashes_the_core_lookup(self):
        self.assertIsNone(self.c.payments._project_for({"project_id": None, "bill_id": None, "party_id": self.w.employee["id"]}))
        self.assertEqual(self.c.payments._payable_for({"payable_account": None}), "2000")
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "120.00")
        self.c.dispatch_payments()
        self.w.settle(pid)
        self.w.give_back(pid)
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("0.00"))  # supplier AP is never touched
        self.assertBooksClean()

    def test_failing_source_listener_never_undoes_an_accepted_transfer_or_stalls_dispatch(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "40.00")
        bill = self.w.supplier_bill("10000")
        self.c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
        book = self.r._book_payment

        def defective(p, intent, *, actor):
            book(p, intent, actor=actor)  # writes the booking, then fails: those writes must go too
            raise ReimbursementError("simulated defect after booking")

        self.r._book_payment = defective
        out = {d["intent_id"]: d for d in self.c.dispatch_payments()}
        intent = self.w.intent_for(pid)
        # the provider moved both payments, so the core books both and keeps dispatching
        self.assertEqual([d["status"] for d in out.values()], ["accepted", "accepted"])
        self.assertEqual([e["error"] for e in out.pop(intent["id"])["listener_errors"]], ["ReimbursementError: simulated defect after booking"])
        self.assertNotIn("listener_errors", out.popitem()[1])  # the supplier payment
        self.assertEqual(len(self.c.provider.transfers), 2)
        self.assertEqual((intent["status"], intent["project_id"]), ("accepted", self.w.project["id"]))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("0.00"))  # 9000.00 posted, 9000.00 paid
        self.assertEqual(self.c.bills.get(bill["id"])["status"], "paid")
        p = self.r.payment(pid)
        self.assertEqual((p["status"], p["journal_id"], p["intent_status"]), ("in_flight", None, "accepted"))
        self.assertEqual(self.r.claim(cl["id"])["status"], "approved")
        failed = [e for e in self.c.audit.entries(entity_type="payment_intent", entity_id=intent["id"]) if e["action"] == "payment.listener_failed"]
        self.assertEqual(len(failed), 1)
        self.assertNotIn("reimbursement.payment_booked", [e["action"] for e in self.c.audit.entries(entity_id=pid)])
        # the gap is visible: the subledger and the module's close check both refuse it
        self.assertFalse(self.w.rec()["reconciled"])
        checks = {chk["check"]: chk["ok"] for chk in self.r.close_checks("P1")}
        self.assertFalse(checks["reimbursement payments follow their payment intents"])
        # a settlement event is applied too; the still-defective handler is reported, not fatal
        settled = self.w.settle(pid)
        self.assertTrue(settled["applied"])
        self.assertEqual(len(settled["listener_errors"]), 1)
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-40.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        # once the defect is fixed the repair path brings the payment into step
        del self.r._book_payment
        moved = self.r.sync_payments(actor="owner")["moved"]
        self.assertEqual([(m["payment"], m["intent_status"], m["moved"]) for m in moved], [(pid, "settled", ["booked"])])
        self.assertEqual(self.r.payment(pid)["journal_id"], intent["journal_id"])
        self.assertEqual(self.r.claim(cl["id"])["status"], "partially_paid")
        self.assertTrue(all(chk["ok"] for chk in self.r.close_checks("P1")))
        self.assertBooksClean()

    def test_intent_must_book_where_the_payment_approval_binds(self):
        cl = self.w.approved_claim("120.00")
        p = self.r.record_payment(cl["id"], "40.00", actor="treasury")
        ap = self.c.request_approval("reimbursement.pay", p["id"], actor_role="treasury")
        self.assertEqual((ap["manifest"]["bindings"]["project_id"], ap["manifest"]["bindings"]["payable_account"]), (self.w.project["id"], "2100"))
        self.c.approve(ap["id"])
        other = self.c.create_project(name="Other", entity="E", budget="0")
        base = dict(manifest=ap["manifest"], approval_id=ap["id"], bill_id=None, note="reimbursement payment", actor="treasury",
                    source_type="reimbursement_payment", source_id=p["id"])
        for kwargs in (
            {"project_id": other["id"], "payable_account": "2100"},  # a project the approver did not see
            {"project_id": self.w.project["id"], "payable_account": "2000"},  # supplier AP instead of the employee payable
            {"payable_account": "2100"},  # no project at all: nothing to derive it from
        ):
            with self.assertRaises(PaymentError, msg=str(kwargs)):
                self.c.payments.create_intent(**base, **kwargs)
        self.assertEqual(self.c.payments.list(), [])
        self.assertEqual(self.c.commands.pending("payment"), [])
        # the approval itself is untouched and executes as approved
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.c.execute(ap["id"], actor="treasury", period_id="P1")
        self.c.dispatch_payments()
        self.assertEqual(self.r.payment(p["id"])["status"], "booked")
        self.assertEqual(self.c.ledger.balance("2100", project_id=self.w.project["id"]), Decimal("80.00"))
        self.assertEqual(self.c.ledger.balance("2100", project_id=other["id"]), Decimal("0.00"))
        self.assertBooksClean()

    def test_payment_rows_bind_their_intents_journal_period_and_approval(self):
        cl = self.w.approved_claim("120.00")
        pid, _ = self.w.release(cl["id"], "40.00")
        draft = self.r.record_payment(cl["id"], "10.00", actor="treasury")
        listeners = dict(self.c.payments._listeners)
        self.c.payments._listeners.clear()  # leave the payment in flight after the provider accepts it
        self.c.dispatch_payments()
        intent = self.w.intent_for(pid)
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        db = self.c.db
        forged = [
            ("UPDATE reimbursement_payments SET status='booked', journal_id=?, period_id='P1' WHERE id=?", (cl["journal_id"], pid)),  # not its journal
            ("UPDATE reimbursement_payments SET status='booked', journal_id=?, period_id='P2' WHERE id=?", (intent["journal_id"], pid)),  # not that journal's period
            ("UPDATE reimbursement_payments SET status='booked', journal_id=?, period_id='P1', approval_id=? WHERE id=?", (intent["journal_id"], cl["approval_id"], pid)),
            ("UPDATE reimbursement_payments SET journal_id=? WHERE id=?", (intent["journal_id"], pid)),  # a journal without booking
            ("UPDATE reimbursement_payments SET status='canceled', journal_id=? WHERE id=?", (cl["journal_id"], draft["id"])),
        ]
        for sql, params in forged:
            with self.assertRaisesRegex(sqlite3.DatabaseError, "follow their payment intent", msg=sql):
                db.execute(sql, params)
        self.c.payments._listeners.update(listeners)
        self.assertEqual(self.r.sync_payments(actor="owner")["moved"][0]["moved"], ["booked"])
        p = self.r.payment(pid)
        self.assertEqual((p["status"], p["journal_id"], p["period_id"], p["approval_id"]), ("booked", intent["journal_id"], "P1", intent["approval_id"]))
        for sql, params in (
            ("UPDATE reimbursement_payments SET period_id='P2' WHERE id=?", (pid,)),
            ("UPDATE reimbursement_payments SET approval_id=? WHERE id=?", (cl["approval_id"], pid)),
            ("UPDATE reimbursement_payments SET journal_id=NULL WHERE id=?", (pid,)),
        ):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "follow their payment intent", msg=sql):
                db.execute(sql, params)
        self.assertEqual(self.r.cancel_payment(draft["id"], actor="treasury")["status"], "canceled")
        self.assertBooksClean()

    def test_claim_status_follows_its_booked_payments_and_returns(self):
        cl = self.w.approved_claim("120.00")
        p1, _ = self.w.release(cl["id"], "40.00")
        p2, _ = self.w.release(cl["id"], "80.00")
        db = self.c.db
        illegal = "illegal reimbursement claim status transition"
        with self.assertRaisesRegex(sqlite3.DatabaseError, illegal):  # nothing is booked yet
            db.execute("UPDATE reimbursement_claims SET status='partially_paid' WHERE id=?", (cl["id"],))
        with self.assertRaisesRegex(sqlite3.DatabaseError, illegal):  # money is in flight
            db.execute("UPDATE reimbursement_claims SET status='voided' WHERE id=?", (cl["id"],))
        self.c.dispatch_payments()
        self.assertEqual(self.r.claim(cl["id"])["status"], "paid")
        # a writer outside this module records the return of the 40.00 itself
        listeners = dict(self.c.payments._listeners)
        self.c.payments._listeners.clear()
        self.w.give_back(p1)
        db.execute("UPDATE reimbursement_payments SET status='returned' WHERE id=?", (p1,))  # its intent was returned
        with self.assertRaisesRegex(sqlite3.DatabaseError, illegal):  # 80.00 is still booked: the claim cannot go back to approved
            db.execute("UPDATE reimbursement_claims SET status='approved', payments_returned=payments_returned+1 WHERE id=?", (cl["id"],))
        db.execute("UPDATE reimbursement_claims SET status='partially_paid', payments_returned=payments_returned+1 WHERE id=?", (cl["id"],))
        self.assertTrue(self.w.rec()["reconciled"])
        # the module handles the second return: nothing booked remains, so the claim is plainly approved again
        self.c.payments._listeners.update(listeners)
        self.w.give_back(p2)
        cl = self.r.claim(cl["id"])
        self.assertEqual((cl["status"], cl["payments_returned"], cl["outstanding"], cl["paid"]), ("approved", 2, "120.00", "0.00"))
        with self.assertRaisesRegex(sqlite3.DatabaseError, illegal):  # and with nothing booked it cannot be marked paid
            db.execute("UPDATE reimbursement_claims SET status='paid' WHERE id=?", (cl["id"],))
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("120.00"))
        self.assertEqual(self.c.ledger.balance("1200"), Decimal("0.00"))
        # with nothing booked or in flight the claim can be voided again
        res = self.c.approve_and_execute("reimbursement.void", cl["id"], period_id="P1")
        self.assertEqual(res.result["status"], "voided")
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertBooksClean()


class RestoreQuarantineTests(unittest.TestCase):
    def test_restored_copy_quarantines_reimbursement_payments_until_recovery(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            w = ReimbursementWorld(os.path.join(d, "live.sqlite"))
            restored = None
            try:
                cl = w.approved_claim("120.00")
                p1, _ = w.release(cl["id"], "40.00")
                w.c.provider.mode = "timeout_after_accept"
                w.c.dispatch_payments()  # the transfer exists at the provider; Cipher does not know
                p2 = w.r.record_payment(cl["id"], "30.00", actor="treasury")
                snap = w.c.snapshot(os.path.join(d, "backup.sqlite"))
                restored = Cipher.open_restored(snap, provider=w.c.provider)
                restored.provider.mode = "accept"
                rr = restored.plugin(PLUGIN_NAME)
                restored.claim_write_authority(approval_ref="apr_controller")
                self.assertTrue(restored.db.authority_status()["release_quarantined"])
                ap = restored.request_approval("reimbursement.pay", p2["id"], actor_role="treasury")
                restored.approve(ap["id"])
                with self.assertRaises(ReleaseQuarantined):
                    restored.execute(ap["id"], actor="treasury", period_id="P1")
                self.assertEqual(rr.payment(p2["id"])["status"], "draft")
                self.assertEqual(restored.approvals.get(ap["id"])["status"], "granted")
                self.assertEqual(len(restored.payments.list()), 1)
                with self.assertRaises(ReleaseQuarantined):
                    restored.dispatch_payments()
                outcome = restored.complete_recovery()
                self.assertTrue(outcome["quarantine_lifted"])
                self.assertEqual(rr.payment(p1)["status"], "booked")  # found by reconciliation, never resubmitted
                self.assertEqual(len(w.c.provider.transfers), 1)
                self.assertEqual(restored.ledger.balance("2100"), Decimal("80.00"))
                restored.execute(ap["id"], actor="treasury", period_id="P1")
                restored.dispatch_payments()
                self.assertEqual(rr.payment(p2["id"])["status"], "booked")
                self.assertEqual(len(w.c.provider.transfers), 2)
                self.assertEqual(restored.ledger.balance("2100"), Decimal("50.00"))
                self.assertTrue(rr.employee_payable_reconciliation(w.project["id"])["reconciled"])
                self.assertTrue(restored.ledger.trial_balance()["balanced"])
                self.assertTrue(restored.audit.verify_chain()["ok"])
            finally:
                if restored is not None:
                    restored.db.close()
                w.c.db.close()


class CorePaymentScopeTests(unittest.TestCase):
    """Supplier bill and retainage payments keep working and now carry their scope."""

    def setUp(self):
        self.c = Cipher()
        sup = self.c.add_party(kind="supplier", name="Sub", destination="ACH-1")
        self.supplier = self.c.verify_destination(sup["id"], destination="ACH-1", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Cust")
        self.project = self.c.create_project(name="P", entity="E", budget="115000", customer_id=self.customer["id"])
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        cmt = self.c.commitments.create(project_id=self.project["id"], supplier_id=self.supplier["id"], title="Sub",
                                        sov_lines=[{"description": "a", "amount": "60000"}, {"description": "b", "amount": "40000"}], actor="o")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        self.cmt = self.c.commitments.get(cmt["id"])
        self.line1, self.line2 = self.cmt["sov"][0]["id"], self.cmt["sov"][1]["id"]

    def posted_bill(self, installed):
        b = self.c.bills.certify(commitment_id=self.cmt["id"], period_id="P1", installed=installed, actor="o")
        self.c.approve_and_execute("bill.approve", b["id"])
        return self.c.bills.get(b["id"])

    def test_bill_payment_carries_scope_and_still_accepts_settles_and_returns(self):
        b = self.posted_bill([{"sov_line_id": self.line1, "cumulative_installed": "20000"}])
        r = self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        intent = self.c.payments.get(r.result["intent"])
        self.assertEqual((intent["project_id"], intent["source_type"], intent["source_id"], intent["payable_account"], intent["bill_id"]),
                         (self.project["id"], "bill", b["id"], "2000", b["id"]))
        # a newer commitment for the same supplier on another project must not capture the postings
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        self.c.commitments.create(project_id=other["id"], supplier_id=self.supplier["id"], title="Later", sov_lines=[{"description": "x", "amount": "1000"}], actor="o")
        self.c.dispatch_payments()
        intent = self.c.payments.get(intent["id"])
        lines = _lines(self.c.ledger.journal(intent["journal_id"]))
        self.assertEqual((lines["2000"]["debit"], lines["2000"]["project_id"]), ("18000.00", self.project["id"]))
        self.assertEqual(self.c.bills.get(b["id"])["status"], "paid")
        self.assertTrue(self.c.bills.ap_open_items(self.project["id"])["reconciled"])
        self.c.payments.ingest_event(self.c.provider.settle(intent["logical_op_id"]), actor="hook")
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-18000.00"))
        self.c.payments.ingest_event(self.c.provider.return_payment(intent["logical_op_id"]), actor="hook")
        self.assertEqual(self.c.payments.get(intent["id"])["status"], "returned")
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("18000.00"))
        self.assertEqual(self.c.ledger.balance("2000", project_id=self.project["id"]), Decimal("18000.00"))
        self.assertEqual(self.c.ledger.balance("1000", project_id=other["id"]), Decimal("0.00"))
        for j in self.c.ledger.journals(source_type="provider_event"):
            self.assertTrue(all(ln["project_id"] == self.project["id"] for ln in j["lines"]))
        self.assertEqual(self.c.bills.get(b["id"])["status"], "posted")
        self.assertTrue(self.c.bills.ap_open_items(self.project["id"])["reconciled"])
        self.assertEqual(self.c.ledger.balance("2100"), Decimal("0.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_retainage_payment_carries_the_commitment_project_and_survives_an_unknown_outcome(self):
        self.posted_bill([{"sov_line_id": self.line1, "cumulative_installed": "60000"}, {"sov_line_id": self.line2, "cumulative_installed": "40000"}])
        self.c.commitments.close(self.cmt["id"], actor="o")
        self.c.approve_and_execute("retainage.release", self.cmt["id"], period_id="P1")
        r = self.c.approve_and_execute("payment.release_retainage", self.cmt["id"], actor_role="treasury", actor="treasury")
        intent = self.c.payments.get(r.result["intent"])
        self.assertEqual((intent["project_id"], intent["source_type"], intent["source_id"], intent["payable_account"], intent["amount"]),
                         (self.project["id"], "retainage_release", self.cmt["id"], "2000", "10000.00"))
        self.c.provider.mode = "timeout_after_accept"
        self.c.dispatch_payments()
        intent = self.c.payments.get(intent["id"])
        self.assertEqual(intent["status"], "outcome_unknown")
        self.assertTrue(intent["note"].startswith("retainage release payment | "))  # the purpose label survives
        with self.assertRaises(PaymentError):  # the unresolved release still counts: no second retainage payment
            self.c.request_approval("payment.release_retainage", self.cmt["id"], actor_role="treasury")
        self.c.provider.mode = "accept"
        self.c.reconcile_payments()
        intent = self.c.payments.get(intent["id"])
        self.assertEqual((intent["status"], intent["note"]), ("accepted", "retainage release payment"))
        self.assertEqual(_lines(self.c.ledger.journal(intent["journal_id"]))["2000"]["project_id"], self.project["id"])
        ap = self.c.bills.ap_open_items(self.project["id"])
        self.assertTrue(ap["reconciled"], ap)
        self.assertEqual(ap["control_balance"], "90000.00")
        self.assertEqual(len(self.c.provider.transfers), 1)

    def test_create_intent_validates_scope_arguments(self):
        b = self.posted_bill([{"sov_line_id": self.line1, "cumulative_installed": "20000"}])
        ap = self.c.request_approval("payment.release", b["id"], actor_role="treasury")
        m = ap["manifest"]
        base = dict(manifest=m, approval_id=ap["id"], bill_id=b["id"], note="bill payment", actor="treasury")
        bad = [
            {"payable_account": "1000"},  # an asset, not a payable
            {"payable_account": "9999"},  # not in the chart
            {"payable_account": ""},
            {"project_id": "prj_missing"},  # not the bill's project
            {"source_type": "bill"},  # without source_id
            {"source_type": "bill", "source_id": "bill_other"},  # not what the manifest covers
        ]
        for kwargs in bad:
            with self.assertRaises(PaymentError, msg=str(kwargs)):
                self.c.payments.create_intent(**base, **kwargs)
        no_dest = dict(m, destination=None)
        with self.assertRaises(PaymentError):
            self.c.payments.create_intent(**dict(base, manifest=no_dest))
        self.assertEqual(self.c.payments.list(), [])
        self.assertEqual(self.c.commands.pending("payment"), [])

    def test_only_legacy_intents_borrow_a_project_from_the_payees_commitments(self):
        p = self.c.payments
        legacy = {"project_id": None, "bill_id": None, "party_id": self.supplier["id"], "payable_account": None}
        self.assertEqual(p._project_for(legacy), self.project["id"])  # created before intents carried a project
        scoped = dict(legacy, payable_account="2000", source_type="misc", source_id="misc_1")
        self.assertIsNone(p._project_for(scoped))  # never guessed for an intent that carries its scope
        # and a new intent that resolves to no project is refused rather than guessed or posted unscoped
        m = build_manifest(operation="payment.release", subject_type="misc", subject_id="misc_1", actor_role="treasury", amounts={"amount": "10.00"},
                           destination={"party_id": self.supplier["id"], "destination": "ACH-1", "destination_version": self.supplier["destination_version"]})
        ap = self.c.approvals.request(m, requested_by="treasury")
        for kwargs in ({}, {"source_type": "misc", "source_id": "misc_1"}):
            with self.assertRaises(PaymentError, msg=str(kwargs)):
                p.create_intent(manifest=m, approval_id=ap["id"], bill_id=None, note="misc payment", actor="treasury", **kwargs)
        self.assertEqual(p.list(), [])
        self.assertEqual(self.c.commands.pending("payment"), [])
        # naming the project explicitly works and the postings land there
        intent = p.create_intent(manifest=m, approval_id=ap["id"], bill_id=None, note="misc payment", actor="treasury",
                                 project_id=self.project["id"], source_type="misc", source_id="misc_1")
        self.assertEqual((intent["project_id"], intent["payable_account"]), (self.project["id"], "2000"))

    def test_scope_schema_entries_are_registered_and_applied(self):
        names = [name for _, name, _ in SCHEMA_CATALOG]
        self.assertLess(names.index(SCOPE_SCHEMA_NAME), names.index(OUTBOX_SCHEMA_NAME))
        self.assertLess(names.index(SCHEMA_NAME), names.index(OUTBOX_SCHEMA_NAME))
        self.assertLess(names.index(OUTBOX_SCHEMA_NAME), names.index(OUTBOX_GUARDS_SCHEMA_NAME))
        status = {v["name"]: v for v in self.c.db.schema_status()["versions"]}
        for name in (SCOPE_SCHEMA_NAME, SCHEMA_NAME, OUTBOX_SCHEMA_NAME, OUTBOX_GUARDS_SCHEMA_NAME):
            self.assertTrue(status[name]["applied"] and status[name]["checksum_matches"], name)
        cols = {r["name"] for r in self.c.db.query("PRAGMA table_info(payment_intents)")}
        self.assertTrue({"project_id", "source_type", "source_id", "payable_account"} <= cols)

    def test_existing_workspace_upgrades_and_keeps_legacy_reimbursement_rows(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            path = os.path.join(d, "old.sqlite")
            saved = list(SCHEMA_CATALOG)
            try:
                # a workspace from before the scope columns also predates every later reimbursement entry
                SCHEMA_CATALOG[:] = [e for e in saved if e[1] not in (SCOPE_SCHEMA_NAME, OUTBOX_SCHEMA_NAME, OUTBOX_GUARDS_SCHEMA_NAME, REOPEN_SCHEMA_NAME)]
                old = Database(path)
                with old.transaction() as conn:
                    conn.execute("INSERT INTO parties (id, kind, name, destination, destination_version, destination_verified, created_at) VALUES ('pty_e','employee','E','ACH',1,1,'t')")
                    conn.execute("INSERT INTO projects (id, name, entity, currency, budget, created_at) VALUES ('prj_old','Old','E','USD','0.00','t')")
                    conn.execute("""INSERT INTO reimbursement_claims (id, project_id, employee_id, description, amount, receipt_hash, billable, status, version, content_hash, created_at, updated_at)
                                    VALUES ('rclm_old','prj_old','pty_e','Hotel','50.00','r-old',0,'paid',1,'h','t','t')""")
                    conn.execute("INSERT INTO reimbursement_payments (id, claim_id, amount, status, version, created_at, booked_at) VALUES ('rpay_old','rclm_old','50.00','booked',1,'t','t')")
                old.close()
            finally:
                SCHEMA_CATALOG[:] = saved
            upgraded = Database(path)
            try:
                self.assertEqual(upgraded.schema_status()["pending"], [])
                row = upgraded.one("SELECT * FROM reimbursement_payments WHERE id='rpay_old'")
                self.assertEqual((row["status"], row["amount"], row["intent_id"]), ("booked", "50.00", None))
                self.assertEqual(upgraded.one("SELECT payments_returned FROM reimbursement_claims WHERE id='rclm_old'")["payments_returned"], 0)
                with self.assertRaises(sqlite3.DatabaseError):  # a legacy booked payment has no intent to follow
                    upgraded.execute("UPDATE reimbursement_payments SET status='returned' WHERE id='rpay_old'")
                with self.assertRaises(sqlite3.DatabaseError):
                    upgraded.execute("UPDATE reimbursement_claims SET status='approved' WHERE id='rclm_old'")
                cols = {r["name"] for r in upgraded.query("PRAGMA table_info(payment_intents)")}
                self.assertIn("payable_account", cols)
            finally:
                upgraded.close()

    def test_workspace_with_the_outbox_entry_gains_the_guards_in_place(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            path = os.path.join(d, "outbox.sqlite")
            saved = list(SCHEMA_CATALOG)
            try:
                SCHEMA_CATALOG[:] = [e for e in saved if e[1] not in (OUTBOX_GUARDS_SCHEMA_NAME, REOPEN_SCHEMA_NAME)]
                Database(path).close()
            finally:
                SCHEMA_CATALOG[:] = saved
            upgraded = Database(path)
            try:
                status = {v["name"]: v for v in upgraded.schema_status()["versions"]}
                self.assertEqual(upgraded.schema_status()["pending"], [])
                self.assertTrue(status[OUTBOX_SCHEMA_NAME]["checksum_matches"] and status[OUTBOX_GUARDS_SCHEMA_NAME]["checksum_matches"])
                self.assertTrue(status[REOPEN_SCHEMA_NAME]["applied"] and status[REOPEN_SCHEMA_NAME]["checksum_matches"])
                triggers = {r["name"]: r["sql"] for r in upgraded.query("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('reimbursement_payments','reimbursement_claims')")}
                self.assertIn("i.journal_id", triggers["reimbursement_payments_follow_intent"])
                self.assertIn("i.status = 'canceled' AND i.journal_id IS NULL", triggers["reimbursement_payments_follow_intent"])  # the reopen transition
                self.assertIn("p.status IN ('in_flight','booked')", triggers["reimbursement_claims_status_lifecycle"])
            finally:
                upgraded.close()


if __name__ == "__main__":
    unittest.main()
