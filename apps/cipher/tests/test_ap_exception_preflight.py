"""Pure exception plans, independent correction decisions and exact effect previews."""
import datetime
from decimal import Decimal
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_exception_contract import APExceptionContract
from apps.cipher.ap_exception_preflight import APExceptionPreflight
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.core.ids import utcnow


class ExceptionWorld:
    def __init__(self):
        self.c = make_ap_practice_fixture()
        self.secret = b"ap-exception-private-test-key-32"
        self.base = APContract(self.c, secret=self.secret)
        self.intake = APIntakeContract(self.c, self.base, secret=self.secret)
        self.contract = APExceptionContract(self.c, self.base, self.intake, secret=self.secret)
        self.preflight = APExceptionPreflight(self.c, self.contract, secret=self.secret)
        self.records = self.c.ap_practice_records
        self.accountant, self.reviewer, self.pm = (self.c.ap_practice_persona_people[persona]["person_id"] for persona in ("accountant", "reviewer", "pm"))
        self.ap = self.c.plugin("ap_intake")

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions), dict(self.c.provider.transfers)

    def receive(self, *, number="SYN-EX-101", evidence=0):
        bill = self.c.bills.get(self.records["draft_bill_id"])
        revision = self.c.evidence.revision(self.records["visible_invoice_evidence_revision_ids"][evidence])
        return self.ap.receive_invoice(bill["supplier_id"], number, "2026-10-14", bill["amount_due"], revision["content_hash"],
            "practice.accountant", project_id=bill["project_id"], commitment_id=bill["commitment_id"])

    def revision_body(self, invoice):
        return {"reason": "Supplier revised the synthetic amount", "invoiceNumber": invoice["invoice_number"],
                "invoiceDate": invoice["invoice_date"], "amountCents": int(Decimal(invoice["amount"]) * 100) + 1,
                "evidenceRevisionId": invoice["evidence_revision_id"]}

    def post(self):
        bill = self.records["approved_bill_id"]
        self.c.post_bill(bill, actor="practice.accountant", period_id="2026-10")
        return bill

    def request_correction(self):
        bill = self.post()
        self.c.bills.prepare_correction(bill, "Synthetic quantity correction", "practice.accountant")
        approval = self.c.request_approval("bill.correct", bill, actor_role="accountant", requested_by="practice.accountant")
        return bill, approval


class APExceptionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.w = ExceptionWorld()
        self.addCleanup(self.w.c.db.close)

    def test_revision_rejection_and_duplicate_reviews_do_not_write(self):
        w = self.w
        invoice = w.receive()
        duplicate = w.receive(number="SYN-EX-102", evidence=1)
        before = w.snapshot()
        for action, resource, body in (("invoice.revise", invoice["id"], w.revision_body(invoice)),
                                      ("invoice.reject", invoice["id"], {"reason": "Synthetic invoice not owed"}),
                                      ("invoice.reviewDuplicate", duplicate["id"], {"reason": "Distinct synthetic obligation verified"})):
            with self.subTest(action=action):
                review = w.preflight.review(w.accountant, action, resource, body)
                self.assertTrue(review["allowed"], review)
                self.assertEqual(review["safeEffects"]["workingLedgerJournalDelta"], 0)
                self.assertEqual(review["safeEffects"]["apPayableDeltaCents"], 0)
                self.assertTrue(review["fingerprint"])
        self.assertEqual(w.snapshot(), before)

    def test_revision_fingerprint_binds_exact_amount_reason_and_evidence(self):
        w = self.w
        invoice = w.receive()
        body = w.revision_body(invoice)
        review = w.preflight.review(w.accountant, "invoice.revise", invoice["id"], body)
        before = w.snapshot()
        checked = w.preflight.verify(w.accountant, "invoice.revise", invoice["id"], {**body, "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(checked["plan"]["content"]["amount"], "11111.11")
        self.assertEqual(review["changes"], [{"field": "amountCents", "before": 1111110, "after": 1111111}])
        with self.assertRaises(APRefusal) as failure:
            w.preflight.verify(w.accountant, "invoice.revise", invoice["id"], {**body, "reason": "Another reason", "fingerprint": review["fingerprint"]}, review["resourceVersion"])
        self.assertEqual(failure.exception.code, "preflight_changed")
        self.assertEqual(w.snapshot(), before)

    def test_hidden_evidence_and_invoice_are_consistently_not_found(self):
        w = self.w
        invoice = w.receive()
        before = w.snapshot()
        for action, resource, body in (("invoice.revise", invoice["id"], {**w.revision_body(invoice), "evidenceRevisionId": w.records["hidden_invoice_evidence_revision_ids"][0]}),
                                      ("bill.cancel", w.records["hidden_bill_id"], {"reason": "Synthetic reason"})):
            with self.subTest(action=action), self.assertRaises(APRefusal) as failure:
                w.preflight.review(w.accountant, action, resource, body)
            self.assertEqual(failure.exception.status, 404)
        self.assertEqual(w.snapshot(), before)

    def test_typed_shape_refuses_forged_roles_bool_cents_and_unknown_fields(self):
        w = self.w
        invoice = w.receive()
        body = w.revision_body(invoice)
        before = w.snapshot()
        for value in ({**body, "actor": "practice.bootstrap"}, {**body, "amountCents": True},
                      {**body, "amountCents": 1 << 53}, {**body, "reason": ""}, {**body, "invoiceDate": "2026-42-01"}):
            with self.subTest(body=value), self.assertRaises(APRefusal):
                w.preflight.review(w.accountant, "invoice.revise", invoice["id"], value)
        self.assertEqual(w.snapshot(), before)

    def test_draft_cancellation_is_accountant_duty_and_approved_withdrawal_is_original_pm(self):
        w = self.w
        before = w.snapshot()
        draft = w.preflight.review(w.accountant, "bill.cancel", w.records["draft_bill_id"], {"reason": "Synthetic measurement canceled"})
        approved = w.preflight.review(w.pm, "bill.cancel", w.records["approved_bill_id"], {"reason": "Synthetic business decision withdrawn"})
        self.assertTrue(draft["allowed"], draft)
        self.assertTrue(approved["allowed"], approved)
        for person, bill in ((w.pm, w.records["draft_bill_id"]), (w.accountant, w.records["approved_bill_id"])):
            with self.assertRaises(APRefusal) as failure:
                w.preflight.review(person, "bill.cancel", bill, {"reason": "Synthetic reason"})
            self.assertEqual(failure.exception.status, 403)
        self.assertEqual(w.snapshot(), before)

    def test_original_pm_keeps_authorization_for_exact_withdrawal_retry_after_void(self):
        w = self.w
        bill = w.records["approved_bill_id"]
        w.c.bills.void(bill, actor="practice.pm", reason="Synthetic business withdrawal")
        before = w.snapshot()
        context = w.preflight.authorize(w.pm, "bill.cancel", bill)
        self.assertEqual(context["duty"], "pm")
        with self.assertRaises(APRefusal):
            w.preflight.authorize(w.accountant, "bill.cancel", bill)
        blocked = w.preflight.review(w.pm, "bill.cancel", bill, {"reason": "Synthetic repeated withdrawal"})
        self.assertFalse(blocked["allowed"])
        self.assertEqual(w.snapshot(), before)

    def test_correction_prepare_request_grant_and_execute_previews_are_pure(self):
        w = self.w
        bill = w.post()
        before = w.snapshot()
        prepare = w.preflight.review(w.accountant, "bill.prepareCorrection", bill, {"reason": "Synthetic quantity corrected"})
        self.assertTrue(prepare["allowed"], prepare)
        self.assertEqual(w.snapshot(), before)
        w.c.bills.prepare_correction(bill, "Synthetic quantity corrected", "practice.accountant")
        before = w.snapshot()
        request = w.preflight.review(w.accountant, "bill.requestCorrection", bill, {})
        self.assertTrue(request["allowed"], request)
        self.assertEqual(w.snapshot(), before)
        approval = w.c.request_approval("bill.correct", bill, actor_role="accountant", requested_by="practice.accountant")
        before = w.snapshot()
        grant = w.preflight.review(w.reviewer, "bill.approveCorrection", approval["id"], {})
        self.assertTrue(grant["allowed"], grant)
        self.assertEqual(w.snapshot(), before)
        w.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        before = w.snapshot()
        execute = w.preflight.review(w.accountant, "bill.executeCorrection", approval["id"], {"periodId": "2026-11"})
        self.assertTrue(execute["allowed"], execute)
        self.assertEqual(execute["safeEffects"]["workingLedgerJournalDelta"], 1)
        self.assertEqual(execute["safeEffects"]["apPayableDeltaCents"], -2111110)
        lines = execute["safeEffects"]["journalPreview"][0]["lines"]
        self.assertEqual(sum(line["debitCents"] for line in lines), sum(line["creditCents"] for line in lines))
        self.assertEqual(w.snapshot(), before)

    def test_correction_request_nonce_does_not_change_review_fingerprint(self):
        w = self.w
        bill = w.post()
        w.c.bills.prepare_correction(bill, "Synthetic quantity corrected", "practice.accountant")
        first = w.preflight.review(w.accountant, "bill.requestCorrection", bill, {})
        with patch("apps.cipher.core.approvals.utcnow", return_value=utcnow() + datetime.timedelta(minutes=5)):
            second = w.preflight.review(w.accountant, "bill.requestCorrection", bill, {})
        self.assertTrue(first["allowed"], first)
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_expiry_and_locked_period_are_pure_correction_refusals(self):
        w = self.w
        _bill, approval = w.request_correction()
        w.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        w.c.db.execute("UPDATE periods SET status='closed' WHERE id='2026-11'")
        before = w.snapshot()
        locked = w.preflight.review(w.accountant, "bill.executeCorrection", approval["id"], {"periodId": "2026-11"})
        self.assertFalse(locked["allowed"])
        self.assertIsNone(locked["fingerprint"])
        w.preflight.now = lambda: utcnow() + datetime.timedelta(days=2)
        expired = w.preflight.review(w.accountant, "bill.executeCorrection", approval["id"], {"periodId": "2026-10"})
        self.assertEqual(expired["checks"][-1]["code"], "approval_expired")
        self.assertEqual(w.snapshot(), before)

    def test_duplicate_request_self_grant_and_pm_correction_duty_are_refused(self):
        w = self.w
        bill, approval = w.request_correction()
        before = w.snapshot()
        duplicate = w.preflight.review(w.accountant, "bill.requestCorrection", bill, {})
        same = w.preflight.review(w.accountant, "bill.approveCorrection", approval["id"], {})
        self.assertEqual(duplicate["checks"][-1]["code"], "duplicate_request")
        self.assertFalse(same["allowed"])
        with self.assertRaises(APRefusal) as failure:
            w.preflight.review(w.pm, "bill.approveCorrection", approval["id"], {})
        self.assertEqual(failure.exception.status, 403)
        self.assertEqual(w.snapshot(), before)

    def test_caught_outer_service_command_audit_failure_rolls_back_correction_and_consumption(self):
        w = self.w
        _bill, approval = w.request_correction()
        w.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        original = w.c.audit.record
        def fail_after_command(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == "command.executed":
                raise RuntimeError("Injected command bookkeeping failure")
            return result
        with w.c.db.transaction():
            before = tuple(w.c.db.conn.iterdump())
            with patch.object(w.c.audit, "record", side_effect=fail_after_command), self.assertRaises(RuntimeError):
                w.c.execute(approval["id"], actor="practice.accountant", period_id="2026-11")
            self.assertEqual(tuple(w.c.db.conn.iterdump()), before)
            self.assertEqual(w.c.approvals.get(approval["id"])["status"], "granted")
