"""Golden synthetic workflow and focused adversarial cases.  The plan section 10
adversarial-variant list, one test per variant, is ``test_adversarial_variants.py``."""
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.core.approvals import ApprovalConsumed, ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.domain.bills import BillError
from apps.cipher.domain.commitments import CommitmentError
from apps.cipher.domain.estimates import EstimateError
from apps.cipher.domain.payments import PaymentError, ReleaseQuarantined
from apps.cipher.domain.receivables import ReceivableError
from apps.cipher.service import Cipher, run_golden_fixture


class GoldenFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Cipher()
        cls.r = run_golden_fixture(cls.c)

    def test_commitment_and_sov(self):
        # $100,000 + $10,000 executed + $12,000 executed later in the stale-approval scenario
        self.assertEqual(self.r["executed_amount"], "122000.00")
        self.assertEqual(self.r["sov"], ["82000.00", "40000.00"])

    def test_period_one_bill(self):
        self.assertEqual(self.r["bill1"], {"cumulative_gross": "30000.00", "cumulative_retainage": "3000.00", "amount_due": "27000.00", "status": "paid"})

    def test_period_two_bill_without_double_counting(self):
        b = self.r["bill2"]
        self.assertEqual(b["cumulative_installed"], "45000.00")
        self.assertEqual(b["cumulative_stored"], "5000.00")
        self.assertEqual(b["cumulative_gross"], "50000.00")
        self.assertEqual(b["cumulative_retainage"], "5000.00")
        self.assertEqual(b["cumulative_net"], "45000.00")
        self.assertEqual(b["amount_due"], "18000.00")
        self.assertEqual(b["retainage_this_period"], "2000.00")
        self.assertEqual(b["stored_transferred_this_period"], "10000.00")
        self.assertEqual(self.r["cost"], "45000.00")
        self.assertEqual(self.r["stored"], "5000.00")

    def test_lot_balances(self):
        remaining = sorted(l["remaining_amount"] for l in self.r["lots"])
        self.assertEqual(remaining, ["0.00", "5000.00"])
        # every lot rests on the current revision of its own evidence document and names its location
        for lot in self.r["lots"]:
            self.assertEqual(lot["evidence_status"], "current")
            self.assertFalse(lot["eligibility_confirmation_required"])
            self.assertTrue(lot["billed"])
            self.assertEqual(self.c.evidence.revision(lot["evidence_revision_id"])["content_hash"], lot["evidence_hash"])
            self.assertEqual(lot["location"], "laydown yard")

    def test_payment_timeout_reconciliation_and_replay(self):
        p = self.r["payment"]
        self.assertFalse(p["first_replayed"])
        self.assertTrue(p["replay_replayed"])
        self.assertEqual(p["dispatch"][0]["status"], "outcome_unknown")
        self.assertEqual(p["reconciled"][0]["status"], "accepted")
        self.assertEqual(p["transfers"], 1)
        self.assertEqual(p["status"], "settled")
        self.assertFalse(p["duplicate_event"]["applied"])

    def test_forecast(self):
        f = self.r["forecast_before_change"]
        self.assertEqual(f["executed_commitments"], "110000.00")
        self.assertEqual(f["pending_exposure"], "12000.00")
        self.assertEqual(f["forecast_at_completion"], "122000.00")
        self.assertEqual(f["variance_to_budget"], "-7000.00")
        self.assertTrue(f["over_budget"])
        self.assertEqual(f["paid_to_date"], "27000.00")

    def test_prime_billing_and_collection(self):
        self.assertEqual(self.r["prime"]["amount_due"], "54000.00")
        self.assertEqual(self.r["prime"]["retainage_cumulative"], "6000.00")
        self.assertEqual(self.r["prime"]["revenue_this_period"], "60000.00")
        self.assertEqual(self.r["collection"]["status"], "received")
        self.assertEqual(self.r["late_return"]["status"], "returned")
        self.assertIsNotNone(self.r["late_return"]["return_journal_id"])
        self.assertEqual(self.r["fees"], "5.00")
        # paid 27,000 out, received 53,995, returned 54,000
        self.assertEqual(self.r["bank"], "-27005.00")

    def test_stale_bill_approval_invalidated_by_change(self):
        self.assertEqual(self.r["ap_bill3_status"], "invalidated")
        self.assertIn(self.r["stale_result"], ("ApprovalNotGranted", "StaleApprovalError"))

    def test_ricky_abstentions(self):
        self.assertEqual(self.r["ricky_abstain"]["decision"], "abstained")
        self.assertIn("superseded document", self.r["ricky_abstain"]["reason"])
        self.assertEqual(self.r["ricky_role"]["decision"], "abstained")
        self.assertIn("not authorized", self.r["ricky_role"]["reason"])

    def test_books_reconcile(self):
        self.assertTrue(self.r["trial_balance"]["balanced"])
        self.assertTrue(self.r["ap"]["reconciled"])
        self.assertTrue(self.r["ar"]["reconciled"])
        self.assertTrue(self.r["audit"]["ok"])
        # retainage payable (2050): 3,000 + 2,000 withheld on the two posted bills; stored materials (1300): 5,000 carried
        ret = self.c.bills.retainage_open_items(self.r["project_id"])
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("5000.00", "5000.00", True))
        stored = self.c.bills.stored_material_items(self.r["project_id"])
        self.assertEqual((stored["subledger_total"], stored["control_balance"], stored["reconciled"]), ("5000.00", "5000.00", True))

    def test_state_and_export(self):
        state = self.c.project_state(self.r["project_id"])
        self.assertEqual(len(state["commitments"]), 2)
        self.assertTrue(state["audit_chain"]["ok"])
        export = self.c.audit_export()
        self.assertIn("schema", export)
        self.assertTrue(export["audit"]["chain"]["ok"])


def send_prime_bill(tc, c, prime_bill_id):
    """Sending is its own approval-bound authority (``prime_bill.send``); the direct call is refused."""
    with tc.assertRaises(ReceivableError):
        c.receivables.send(prime_bill_id, actor="o")
    return c.approve_and_execute("prime_bill.send", prime_bill_id, actor_role="owner").result


def record_ach_mandate(c, project_id, customer_id):
    """ACH collection needs the customer's recorded debit mandate, backed by an evidence revision on its project."""
    doc = c.evidence.register_document(project_id=project_id, kind="ach_mandate", title="Customer ACH debit authorization (synthetic)", actor="o")
    rev = c.evidence.add_revision(document_id=doc["id"], content=b"synthetic ACH debit authorization (workflow tests)", actor="o")
    return c.receivables.record_mandate(customer_id=customer_id, mandate_ref="MANDATE-SIM-WF-0001", evidence_hash=rev["content_hash"], actor="o")


class Scenario:
    """Small reusable setup: verified supplier, customer, project, open period, executed $100k commitment."""

    def __init__(self):
        self.c = Cipher()
        self.supplier = self.c.add_party(kind="supplier", name="Sub", destination="ACH-1")
        self.c.verify_destination(self.supplier["id"], destination="ACH-1", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Cust")
        self.project = self.c.create_project(name="P", entity="E", budget="115000", customer_id=self.customer["id"])
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.doc = self.c.evidence.register_document(project_id=self.project["id"], kind="drawing", title="A", actor="o")
        self.rev = self.c.evidence.add_revision(document_id=self.doc["id"], content=b"rev1", actor="o")
        self.est = self.c.estimates.create(project_id=self.project["id"], document_revision_id=self.rev["id"], lines=[{"description": "x", "quantity": "1", "unit": "LS", "unit_price": "100000"}], actor="o")
        self.c.approve_and_execute("estimate.approve", self.est["id"])
        self.cmt = self.c.commitments.create(project_id=self.project["id"], supplier_id=self.supplier["id"], title="Sub", sov_lines=[{"description": "a", "amount": "60000"}, {"description": "b", "amount": "40000"}], estimate_id=self.est["id"], actor="o")
        self.c.approve_and_execute("commitment.execute", self.cmt["id"])
        self.cmt = self.c.commitments.get(self.cmt["id"])
        self.line1 = self.cmt["sov"][0]["id"]
        self.line2 = self.cmt["sov"][1]["id"]

    def stored_evidence(self, label: str) -> dict:
        """A title/control, insurance, location and delivery evidence revision on the project."""
        doc = self.c.evidence.register_document(project_id=self.project["id"], kind="stored_material_evidence", title=f"Stored material evidence: {label}", actor="o")
        return self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic stored-material evidence: {label}".encode(), actor="o")

    def add_lot(self, label: str, amount: str, line: str | None = None) -> dict:
        ev = self.stored_evidence(label)
        return self.c.bills.add_stored_material(commitment_id=self.cmt["id"], sov_line_id=line or self.line1, description=label, eligible_amount=amount,
                                                evidence_hash=ev["content_hash"], location="synthetic laydown yard", actor="o")


class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c

    def test_pending_change_does_not_change_commitment(self):
        self.c.commitments.propose_change(self.s.cmt["id"], amount="10000", reason="alt", sov_line_id=self.s.line1, actor="o")
        self.assertEqual(self.c.commitments.get(self.s.cmt["id"])["executed_amount"], "100000.00")
        self.assertEqual(self.c.forecast.project(self.s.project["id"])["pending_exposure"], "10000.00")

    def test_cumulative_installed_cannot_exceed_sov_or_decrease(self):
        with self.assertRaises(BillError):
            self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "60001"}], actor="o")
        b1 = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        approve_and_post_bill(self.c, b1["id"], approver="owner", approver_role="owner", poster="accountant")
        with self.assertRaises(BillError):
            self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "19000"}], actor="o")

    def test_stored_transfer_cannot_exceed_lot(self):
        lot = self.s.add_lot("pipe", "10000")
        with self.assertRaises(BillError):
            self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], transfers=[{"lot_id": lot["id"], "amount": "10001"}], actor="o")
        with self.assertRaises(BillError):  # the same lot cannot be transferred twice in one bill either
            self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}],
                                 transfers=[{"lot_id": lot["id"], "amount": "5000"}, {"lot_id": lot["id"], "amount": "5000"}], actor="o")
        self.assertEqual(self.c.bills.list(commitment_id=self.s.cmt["id"]), [])
        self.assertEqual(self.c.bills.lot(lot["id"])["remaining_amount"], "10000.00")

    def test_stored_material_requires_evidence(self):
        cid, line = self.s.cmt["id"], self.s.line1
        with self.assertRaises(BillError):
            self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe", eligible_amount="10000", evidence_hash="", location="yard", actor="o")
        with self.assertRaises(BillError):  # a hash Cipher never stored is not evidence
            self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe", eligible_amount="10000", evidence_hash="h", location="yard", actor="o")
        with self.assertRaises(BillError):  # a stored revision, but of a drawing: not stored-material evidence
            self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe", eligible_amount="10000", evidence_hash=self.s.rev["content_hash"], location="yard", actor="o")
        ev = self.s.stored_evidence("pipe")
        with self.assertRaises(BillError):  # real evidence, but no storage location
            self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe", eligible_amount="10000", evidence_hash=ev["content_hash"], actor="o")
        lot = self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe", eligible_amount="10000", evidence_hash=ev["content_hash"], location="yard", actor="o")
        self.assertEqual((lot["evidence_revision_id"], lot["evidence_status"], lot["remaining_amount"]), (ev["id"], "current", "10000.00"))
        with self.assertRaises(BillError):  # one evidence revision supports one lot
            self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe again", eligible_amount="1000", evidence_hash=ev["content_hash"], location="yard", actor="o")
        rev2 = self.c.evidence.add_revision(document_id=ev["document_id"], content=b"synthetic stored-material evidence: pipe (reissued)", actor="o")
        with self.assertRaises(BillError):  # nor does a newer revision of the same document: it re-confirms the lot instead
            self.c.bills.add_stored_material(commitment_id=cid, sov_line_id=line, description="pipe again", eligible_amount="1000", evidence_hash=rev2["content_hash"], location="yard", actor="o")
        self.assertEqual(len(self.c.bills.lots(cid)), 1)
        self.assertTrue(self.c.bills.lot(lot["id"])["frozen"])
        self.assertEqual(self.c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "o")["evidence_revision_id"], rev2["id"])

    def test_void_draft_restores_lot(self):
        lot = self.s.add_lot("pipe", "10000")
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], transfers=[{"lot_id": lot["id"], "amount": "4000"}], actor="o")
        self.assertEqual(self.c.bills.lot(lot["id"])["remaining_amount"], "6000.00")
        self.assertEqual(self.c.bills.lot(lot["id"])["billed_bill_id"], b["id"])
        self.c.bills.void(b["id"], actor="o", reason="redo")
        self.assertEqual(self.c.bills.lot(lot["id"])["remaining_amount"], "10000.00")
        self.assertIsNone(self.c.bills.lot(lot["id"])["billed_bill_id"])  # the voided draft no longer counts as its billing history

    def test_stored_material_respects_the_sov_line_cap(self):
        b1 = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "55000"}], actor="o")
        approve_and_post_bill(self.c, b1["id"], approver="owner", approver_role="owner", poster="accountant")
        with self.assertRaises(BillError) as cm:  # 55,000 installed + 6,000 stored would exceed line 1 (60,000)
            self.s.add_lot("pipe", "6000")
        self.assertIn("SOV line 1", str(cm.exception))
        self.s.add_lot("valves", "5000")  # exactly the line value is allowed
        self.assertEqual(self.c.ledger.balance("2050"), Decimal("5500.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_business_review_binds_entity_currency_and_posting_receipt_binds_preview(self):
        lot = self.s.add_lot("pipe", "10000")
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        ap = self.c.request_approval("bill.approve", b["id"], actor_role="accountant")
        m = ap["manifest"]
        self.assertEqual((m["entity"], m["currency"]), ("E", "USD"))
        self.assertNotIn("journal_preview", m["bindings"])
        preview = self.c.bills.journal_preview(b["id"])
        self.assertEqual([[(ln["account"], ln["debit"], ln["credit"]) for ln in j["lines"]] for j in preview],
                         [[("5000", "20000.00", "0.00"), ("1300", "10000.00", "0.00"), ("2000", "0.00", "27000.00"), ("2050", "0.00", "3000.00")]])
        self.assertEqual(m["bindings"]["stored_lots"], [{"lot_id": lot["id"], "evidence_revision_id": lot["evidence_revision_id"], "evidence_status": "current"}])
        self.c.approve(ap["id"], approver="controller", approver_role="controller")
        res = self.c.post_bill(b["id"], actor="accountant")
        self.assertEqual(self.c.bills.posting_receipt(b["id"])["preview"], preview)
        posted = self.c.ledger.journals(source_type="bill", source_id=b["id"])
        self.assertEqual([[{k: ln[k if k != "account" else "account_code"] for k in ("account", "debit", "credit", "project_id", "party_id", "memo")} for ln in j["lines"]] for j in posted],
                         [j["lines"] for j in preview])
        self.assertEqual(res.result["journal_id"], posted[-1]["id"])
        # commitment and change approvals bind the project's entity and currency too
        self.assertEqual(self.c.approvals.get(self.s.cmt["approval_id"])["manifest"]["entity"], "E")
        ch =self.c.commitments.propose_change(self.s.cmt["id"], amount="1000", reason="x", sov_line_id=self.s.line2, actor="o")
        cm = self.c.request_approval("change.execute", ch["id"], actor_role="pm")["manifest"]
        self.assertEqual((cm["entity"], cm["currency"], cm["bindings"]["change_status"]), ("E", "USD", "pending"))

    def test_bill_approval_invalidated_when_commitment_changes(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        ap = self.c.request_approval("bill.approve", b["id"])
        self.c.approve(ap["id"])
        ch = self.c.commitments.propose_change(self.s.cmt["id"], amount="5000", reason="x", sov_line_id=self.s.line1, actor="o")
        self.c.approve_and_execute("change.execute", ch["id"])
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            self.c.post_bill(b["id"], actor="accountant")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertTrue(self.c.bills.get(b["id"])["stale"])

    def test_changed_payee_destination_invalidates_payment_approval(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        ap = self.c.request_approval("payment.release", b["id"], actor_role="treasury")
        self.c.approve(ap["id"])
        self.c.verify_destination(self.s.supplier["id"], destination="ACH-ATTACKER", verified_by="owner")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            self.c.execute(ap["id"], actor="treasury")
        self.assertEqual(self.c.payments.list(), [])

    def test_unverified_destination_blocks_release(self):
        sup2 = self.c.add_party(kind="supplier", name="Unverified", destination="ACH-9")
        cmt2 = self.c.commitments.create(project_id=self.s.project["id"], supplier_id=sup2["id"], title="S2", sov_lines=[{"description": "a", "amount": "1000"}], actor="o")
        self.c.approve_and_execute("commitment.execute", cmt2["id"])
        line = self.c.commitments.get(cmt2["id"])["sov"][0]["id"]
        b = self.c.bills.certify(commitment_id=cmt2["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": "1000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        with self.assertRaises(PaymentError):
            self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        self.assertEqual(self.c.ricky.propose("payment.release", actor_role="treasury", context={"bill_id": b["id"]})["decision"], "abstained")

    def test_duplicate_dispatch_and_concurrent_release_create_one_transfer(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        ap = self.c.request_approval("payment.release", b["id"], actor_role="treasury")
        self.c.approve(ap["id"])
        self.c.execute(ap["id"], actor="treasury")
        self.assertTrue(self.c.execute(ap["id"], actor="treasury").replayed)  # replay returns the stored result
        with self.assertRaises(ApprovalConsumed):  # a second worker with its own op id cannot consume the approval again
            self.c.execute(ap["id"], actor="treasury", op_id="exec:second-worker")
        self.assertEqual(len(self.c.payments.list()), 1)
        self.c.dispatch_payments()
        self.c.dispatch_payments()
        self.assertEqual(len(self.c.provider.transfers), 1)
        self.assertEqual(len(self.c.provider.submissions), 1)

    def test_rejected_payment_keeps_obligation_open(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        self.c.provider.mode = "reject"
        res = self.c.dispatch_payments()
        self.assertEqual(res[0]["status"], "failed")
        self.assertEqual(self.c.bills.ap_open_items()["subledger_total"], "18000.00")
        self.assertTrue(self.c.bills.ap_open_items()["reconciled"])

    def test_unavailable_provider_holds_unknown_outcome_without_retry(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        self.c.provider.mode = "unavailable"
        self.assertEqual(self.c.dispatch_payments()[0]["status"], "outcome_unknown")
        self.assertEqual(self.c.reconcile_payments()[0]["status"], "outcome_unknown")
        self.c.provider.mode = "accept"
        self.assertEqual(self.c.reconcile_payments()[0]["status"], "failed")  # never submitted: provider has no record
        self.assertEqual(len(self.c.provider.transfers), 0)

    def test_returned_payment_reinstates_payable(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "20000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        r = self.c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        self.c.dispatch_payments()
        intent = self.c.payments.get(r.result["intent"])
        self.c.payments.ingest_event(self.c.provider.settle(intent["logical_op_id"]), actor="hook")
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-18000.00"))
        self.c.payments.ingest_event(self.c.provider.return_payment(intent["logical_op_id"]), actor="hook")
        self.assertEqual(self.c.payments.get(intent["id"])["status"], "returned")
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("18000.00"))
        self.assertEqual(self.c.bills.get(b["id"])["status"], "posted")
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_closed_period_rejects_posting_and_late_correction_goes_to_open_period(self):
        prime = self.c.receivables.certify(project_id=self.s.project["id"], period_id="P1", certified_cumulative="60000", actor="o")
        self.c.approve_and_execute("prime_bill.approve", prime["id"])
        self.assertEqual(send_prime_bill(self, self.c, prime["id"])["status"], "sent")
        with self.assertRaises(ReceivableError):  # an ACH debit without the customer's mandate is refused
            self.c.receivables.record_collection(prime_bill_id=prime["id"], period_id="P1", amount="54000", fee="5", provider_ref="rcv1", actor="o")
        record_ach_mandate(self.c, self.s.project["id"], self.s.customer["id"])
        col = self.c.receivables.record_collection(prime_bill_id=prime["id"], period_id="P1", amount="54000", fee="5", provider_ref="rcv1", actor="o")
        self.c.close_period("P1")
        with self.assertRaises(Exception):
            self.c.receivables.record_return(collection_id=col["id"], period_id="P1", reason="late", actor="o")
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.c.receivables.record_return(collection_id=col["id"], period_id="P2", reason="late", actor="o")
        self.assertEqual(self.c.receivables.ar_open_items()["subledger_total"], "54000.00")
        self.assertTrue(self.c.receivables.ar_open_items()["reconciled"])
        with self.assertRaises(ReceivableError):
            self.c.receivables.record_collection(prime_bill_id=prime["id"], period_id="P2", amount="54000", fee="0", provider_ref="rcv1", actor="o")

    def test_stale_estimate_blocks_commitment(self):
        self.c.evidence.add_revision(document_id=self.s.doc["id"], content=b"rev2", actor="o")
        cmt2 = self.c.commitments.create(project_id=self.s.project["id"], supplier_id=self.s.supplier["id"], title="S2", sov_lines=[{"description": "a", "amount": "1000"}], estimate_id=self.s.est["id"], actor="o")
        with self.assertRaises(CommitmentError):
            self.c.approve_and_execute("commitment.execute", cmt2["id"])
        est2 = self.c.estimates.create(project_id=self.s.project["id"], document_revision_id=self.s.rev["id"], lines=[{"description": "x", "quantity": "1", "unit": "LS", "unit_price": "1"}], actor="o")
        with self.assertRaises(EstimateError):
            self.c.approve_and_execute("estimate.approve", est2["id"])

    def test_retainage_release_only_after_closeout(self):
        b = self.c.bills.certify(commitment_id=self.s.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.s.line1, "cumulative_installed": "60000"}, {"sov_line_id": self.s.line2, "cumulative_installed": "40000"}], actor="o")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        self.assertEqual(self.c.ledger.balance("2050"), Decimal("10000.00"))
        self.assertEqual(self.c.ricky.propose("retainage.release", actor_role="owner", context={"commitment_id": self.s.cmt["id"]})["decision"], "abstained")
        with self.assertRaises(BillError):  # the service refuses too, not only Ricky: no release before closeout
            self.c.approve_and_execute("retainage.release", self.s.cmt["id"], period_id="P1")
        self.assertEqual(self.c.ledger.journals(source_type="retainage_release"), [])
        self.assertEqual(self.c.bills.retainage_open_items()["subledger_total"], "10000.00")
        with self.assertRaises(sqlite3.DatabaseError):  # a raw status edit does not close a commitment
            self.c.db.execute("UPDATE commitments SET status='closed' WHERE id=?", (self.s.cmt["id"],))
        self.assertEqual(self.c.commitments.get(self.s.cmt["id"])["status"], "executed")
        self.c.commitments.close(self.s.cmt["id"], actor="o")
        self.assertEqual(self.c.commitments.closure(self.s.cmt["id"])["basis"], "direct")  # no field closeout was ever opened
        self.assertEqual(self.c.ricky.propose("retainage.release", actor_role="owner", context={"commitment_id": self.s.cmt["id"]})["decision"], "proposed")
        released = self.c.approve_and_execute("retainage.release", self.s.cmt["id"], period_id="P1")
        used = self.c.ledger.journal(released.result["journal_id"])["approval_id"]
        with self.assertRaises(BillError):  # nothing is held now, and the consumed approval already took effect once
            self.c.bills.release_retainage(commitment_id=self.s.cmt["id"], period_id="P1", approval_id=used, actor="o")
        self.assertEqual(self.c.ledger.balance("2050"), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("100000.00"))
        self.assertTrue(self.c.bills.ap_open_items()["reconciled"])
        ret = self.c.bills.retainage_open_items()
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("0.00", "0.00", True))
        with self.assertRaises(BillError):  # nothing is left to release a second time
            self.c.approve_and_execute("retainage.release", self.s.cmt["id"], period_id="P1")
        r = self.c.approve_and_execute("payment.release_retainage", self.s.cmt["id"], actor_role="treasury", actor="treasury")
        self.assertEqual(r.result["amount"], "10000.00")


class RestoreQuarantineTests(unittest.TestCase):
    def test_restore_quarantines_releases_until_reconciled(self):
        d = tempfile.mkdtemp()
        c = Cipher(os.path.join(d, "live.sqlite"))
        self.addCleanup(c.db.close)
        s_sup = c.add_party(kind="supplier", name="Sub", destination="ACH-1")
        c.verify_destination(s_sup["id"], destination="ACH-1", verified_by="o")
        prj = c.create_project(name="P", entity="E", budget="1000")
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        cmt = c.commitments.create(project_id=prj["id"], supplier_id=s_sup["id"], title="S", sov_lines=[{"description": "a", "amount": "1000"}], actor="o")
        c.approve_and_execute("commitment.execute", cmt["id"])
        line = c.commitments.get(cmt["id"])["sov"][0]["id"]
        b = c.bills.certify(commitment_id=cmt["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": "1000"}], actor="o")
        approve_and_post_bill(c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        c.provider.mode = "timeout_after_accept"
        c.dispatch_payments()  # transfer exists at the provider, Cipher does not know
        snap = c.snapshot(os.path.join(d, "backup.sqlite"))
        restored = Cipher.open_restored(snap, provider=c.provider)
        self.addCleanup(restored.db.close)
        restored.provider.mode = "accept"
        self.assertFalse(restored.db.has_write_authority())
        with self.assertRaises(WriteAuthorityError):  # read-only until the owner claims it
            restored.add_party(kind="supplier", name="Injected payee", destination="ACH-INJECTED")
        # the claim is an attested owner action: approver and reason are recorded
        restored.claim_write_authority(approval_ref="apr_controller", actor="owner", reason="restore drill: claim the recovered copy")
        self.assertTrue(restored.db.has_write_authority())
        self.assertTrue(restored.db.authority_status()["release_quarantined"])
        with self.assertRaises(ReleaseQuarantined):
            restored.dispatch_payments()
        self.assertEqual(restored.ricky.propose("payment.release", actor_role="treasury", context={"bill_id": b["id"]})["decision"], "abstained")
        outcome = restored.complete_recovery()
        self.assertTrue(outcome["quarantine_lifted"])
        self.assertEqual(restored.payments.list()[0]["status"], "accepted")
        self.assertEqual(len(c.provider.transfers), 1)
        self.assertFalse(restored.db.authority_status()["release_quarantined"])


if __name__ == "__main__":
    unittest.main()
