"""Plan section 10, Test V1: the complete synthetic vertical acceptance test.

One ordered estimate-to-closeout scenario for a $100,000 subcontract inside a prime
project, driven only through public service and plugin APIs and approvals
(``request_approval`` / ``approve`` / ``execute`` or ``approve_and_execute``).  Nothing
here writes SQL or posts a journal directly except the late-correction attempts of
step 11, which must fail.  Fictional parties, synthetic bank and provider records,
company-owned placeholder evidence; nothing leaves the prototype.

Period choice: three accounting periods.  P1 (October 2026) carries steps 1-6 (the
period-1 certification and its payment); P2 (November) steps 7-9 (the period-2
certification, the prime bill and the collection); P3 (December) the late return,
the final work, closeout and retainage (steps 9-11).  Each period is closed through the
close module's checklist approval, with its bank statement imported, matched and its
reconciliation locked through the banking module, before the next one opens.  The
modules do not force separate periods, but payment acceptance and settlement post into
the latest open period, and the plan needs a closed period behind the late return.

``VerticalV1Tests`` runs the scenario as ordered step tests sharing one workspace:
each ``test_stepNN`` runs every earlier step it depends on exactly once, so a single
step can be run on its own; a step whose prerequisite failed is skipped, not
re-run.  ``VerticalV1VariantTests`` adds focused adversarial variants that the module
suites do not already cover.  ``VerticalV1KnownDefectTests`` asserts the plan's
behaviour where a module once fell short; every named defect has since been fixed,
so these are regression tests now.  The plan's full adversarial-variant list is in
``test_adversarial_variants.py``.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalConsumed, ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.core.ids import hash_json, sha256_hex
from apps.cipher.domain.banking import BankingError
from apps.cipher.domain.bills import BillError
from apps.cipher.domain.close import CloseError
from apps.cipher.domain.estimates import EstimateError
from apps.cipher.domain.field import FieldError
from apps.cipher.domain.labor import LaborError
from apps.cipher.domain.ledger import LedgerError, PeriodNotOpen
from apps.cipher.domain.payments import PaymentError, ReleaseQuarantined
from apps.cipher.domain.receivables import ReceivableError
from apps.cipher.service import Cipher

D = Decimal
STALE = (StaleApprovalError, ApprovalNotGranted)
SHADOW = "SHADOW - not authoritative"
PERIODS = {"P1": ("2026-10-01", "2026-10-31"), "P2": ("2026-11-01", "2026-11-30"), "P3": ("2026-12-01", "2026-12-31")}
SUPPLIER_DESTINATION = "ACH-SIM-V1-SUB-0001"
MEASUREMENT_BASIS_A = "Drawing A rev 0 at 1:100, scale verified against the dimensioned grid"
CLOSEOUT_DELIVERABLES = (
    ("as_builts", "As-built drawings"),
    ("om_manuals", "O&M manuals"),
    ("warranties", "Warranties"),
    ("final_lien_release", "Final lien release"),
)
# journals that record a bank or provider fact rather than a human decision
BANK_FACT_SOURCES = {"collection", "collection_return", "provider_event"}


def lines_of(journal):
    return [(ln["account_code"], ln["debit"], ln["credit"]) for ln in journal["lines"]]


def pick(record, keys):
    return {k: record[k] for k in keys}


def claim_restored_copy(restored, *, reason="V1 restore drill: claim the recovered copy"):
    """Claim write authority on a restored copy as the attested owner action.  A read-only
    copy cannot record an approval of its own, so the claim records its approver and
    reason (and, when CIPHER_OWNER_SECRET is configured, needs the owner claim code)."""
    return restored.claim_write_authority(approval_ref="ext-ref-v1-restore-drill", actor="owner", reason=reason)


def send_prime_bill(c, prime_bill_id, *, role="pm"):
    """Sending a prime bill is its own approval-bound authority (``prime_bill.send``)."""
    ap = c.request_approval("prime_bill.send", prime_bill_id, actor_role=role, requested_by=role)
    c.approve(ap["id"], approver="owner")
    return ap, c.execute(ap["id"], actor=role).result


def record_mandate(c, project_id, customer_id, ref):
    """The customer's signed ACH debit authorization, filed as evidence on its project."""
    doc = c.evidence.register_document(project_id=project_id, kind="ach_mandate", title=f"Customer ACH debit authorization {ref} (synthetic)", actor="treasury")
    rev = c.evidence.add_revision(document_id=doc["id"], content=f"V1 synthetic signed ACH debit authorization {ref}".encode(), actor="treasury")
    return c.receivables.record_mandate(customer_id=customer_id, mandate_ref=ref, evidence_hash=rev["content_hash"], actor="treasury")


def stored_evidence(c, project_id, label):
    """A stored-material evidence revision (title/control, insurance, location, delivery) on the project."""
    doc = c.evidence.register_document(project_id=project_id, kind="stored_material_evidence", title=f"{label} (synthetic)", actor="pm")
    return c.evidence.add_revision(document_id=doc["id"], content=f"V1 synthetic title, insurance, location and delivery evidence: {label}".encode(), actor="pm")


# --------------------------------------------------------------------------- #
# The ordered scenario                                                         #
# --------------------------------------------------------------------------- #

class VerticalV1:
    """The shared workspace and the plan's steps 1-11, plus the pass criteria (step 12)."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="cipher-v1-")
        self.done: set[int] = set()
        self.failed: dict[int, str] = {}
        self.restored = None
        self.close_results: dict[str, dict] = {}
        c = self.c = Cipher()
        self.drawings = c.plugin("drawing")
        self.field = c.plugin("field")
        self.labor = c.plugin("labor")
        self.bank = c.plugin("banking")
        self.close = c.plugin("close")
        self.reimb = c.plugin("reimbursement")

    def cleanup(self):
        if self.restored is not None:
            try:
                self.restored.db.close()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_through(self, n, tc):
        for k in range(1, n + 1):
            if k in self.done:
                continue
            if k in self.failed:
                raise unittest.SkipTest(f"prerequisite step {k} failed: {self.failed[k]}")
            try:
                getattr(self, f"step{k}")(tc)
            except unittest.SkipTest:
                raise
            except BaseException as exc:
                self.failed[k] = f"{type(exc).__name__}: {exc}"
                raise
            self.done.add(k)

    # ---- helpers --------------------------------------------------------- #

    def evidence(self, kind, title, content):
        doc = self.c.evidence.register_document(project_id=self.pid, kind=kind, title=title, actor="pm")
        return self.c.evidence.add_revision(document_id=doc["id"], content=content, actor="pm")

    def refused(self, tc, operation, subject_id, exc, *, role, period_id=None):
        """Request and grant ``operation``; execution must raise ``exc``.  The approval
        is then withdrawn so no granted approval lingers."""
        ap = self.c.request_approval(operation, subject_id, actor_role=role, requested_by=role)
        self.c.approve(ap["id"], approver="owner")
        with tc.assertRaises(exc):
            self.c.execute(ap["id"], actor=role, period_id=period_id)
        self.c.reject(ap["id"], approver="owner", reason="refused at execution; withdrawn")
        tc.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        return ap

    def pay_bill(self, tc, bill_id, expected_ref):
        """Treasury approval, outbox dispatch, provider acceptance, settlement webhook."""
        c = self.c
        r = c.approve_and_execute("payment.release", bill_id, actor_role="treasury", actor="treasury")
        out = c.dispatch_payments()
        tc.assertEqual([(x["status"], x["provider_ref"]) for x in out], [("accepted", expected_ref)])
        intent = c.payments.get(r.result["intent"])
        tc.assertTrue(c.payments.ingest_event(c.provider.settle(intent["logical_op_id"]), actor="webhook")["applied"])
        tc.assertEqual(c.payments.get(intent["id"])["status"], "settled")
        return intent["id"]

    def reconcile_and_close(self, tc, period_id, statement_ref, opening, closing, lines, *, before_close=None):
        """Import the period's bank statement, match it, lock the reconciliation through an
        approval, then close the period through the close module's checklist approval."""
        c = self.c
        st = self.bank.import_statement(statement_ref=statement_ref, period_id=period_id, opening_balance=opening,
                                        closing_balance=closing, lines=lines, actor="reconciler")
        tc.assertEqual((st["imported_count"], st["skipped_count"]), (len(lines), 0))
        tc.assertIn("bank reconciliation", self.close.checklist_report(period_id)["failing"])  # imported, not yet reconciled and locked
        m = self.bank.auto_match(st["id"], actor="reconciler")
        tc.assertEqual((len(m["matched"]), m["ambiguous"], m["unmatched"]), (len(lines), [], []))
        tc.assertEqual({x["basis"] for x in m["matched"]}, {"reference"})
        rec = self.bank.reconciliation(st["id"])
        tc.assertEqual(pick(rec, ("reconciled", "difference", "statement_closing", "adjusted_gl_balance", "in_transit_total")),
                       {"reconciled": True, "difference": "0.00", "statement_closing": closing, "adjusted_gl_balance": closing, "in_transit_total": "0.00"})
        lock = c.approve_and_execute("banking.lock_reconciliation", st["id"], actor_role="reconciler", actor="reconciler", period_id=period_id)
        tc.assertEqual((lock.result["status"], lock.result["difference"]), ("locked", "0.00"))
        if before_close is not None:
            before_close(tc)
        report = self.close.checklist_report(period_id)
        tc.assertTrue(report["all_ok"], report["failing"])
        checks = {ch["check"]: ch for ch in report["checks"]}
        for name in ("trial_balance_balanced", "earlier_periods_closed", "ap_reconciled", "ar_reconciled", "no_draft_supplier_bills",
                     "no_draft_prime_bills", "no_unresolved_payments", "employee_payable_reconciled", "wip_reconciled",
                     "bank reconciliation", "labor: accrued payroll subledger reconciles to 2200"):
            tc.assertTrue(checks[name]["ok"], name)
        tc.assertEqual(checks["bank reconciliation"]["source"], "banking")
        res = c.approve_and_execute("close.close_period", period_id, actor_role="controller", actor="controller", period_id=period_id)
        tc.assertEqual(res.result["status"], "closed")
        tc.assertEqual(c.ledger.period(period_id)["status"], "closed")
        run = self.close.close_run(res.result["close_run_id"])
        tc.assertTrue(run["checklist"] and all(ch["ok"] for ch in run["checklist"]))
        tc.assertEqual(run["statements"]["label"], SHADOW)
        tc.assertTrue(run["statements"]["balance_sheet"]["balanced"])
        self.close_results[period_id] = res.result
        return st

    # ---- step 1 ------------------------------------------------------------ #

    def step1(self, tc):
        """Estimate from drawing A approved; D-A issued; $100,000 subcontract executed (60,000 + 40,000)."""
        c = self.c
        self.supplier = c.add_party(kind="supplier", name="Synthetic Sheet Pile and Dewatering Subcontractor (V1)", destination=SUPPLIER_DESTINATION)
        c.verify_destination(self.supplier["id"], destination=SUPPLIER_DESTINATION, verified_by="bank-detail-maintainer")
        self.customer = c.add_party(kind="customer", name="Synthetic Owner Agency (V1)")
        self.employee = c.add_party(kind="employee", name="Synthetic Field Engineer (V1)")
        self.project = c.create_project(name="V1 synthetic cofferdam and pump station", entity="S&A Solutions LLC (synthetic)",
                                        budget="125000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        c.open_period("P1", "P1", *PERIODS["P1"])

        # drawing A: an immutable evidence revision, registered as D-A and issued through an approval
        self.ev_a = self.evidence("drawing", "Drawing A - sheet pile cofferdam and pump station", b"V1 synthetic drawing A rev 0 (company-owned placeholder)")
        self.dwg_a = self.drawings.register_drawing(self.pid, "D-A", "Sheet pile cofferdam and pump station", "civil", actor="engineer")
        rev = self.drawings.add_revision(self.dwg_a["id"], "0", self.ev_a["id"], note="issued for pricing", actor="engineer")
        res = c.approve_and_execute("drawing.issue", rev["id"], actor_role="pm", actor="pm", period_id="P1")
        tc.assertEqual(pick(res.result, ("status", "number", "label", "period_id")), {"status": "issued", "number": "D-A", "label": "0", "period_id": "P1"})
        self.dwr_a = self.drawings.revision(rev["id"])
        tc.assertEqual((self.dwr_a["status"], self.dwr_a["content_hash"]), ("issued", self.ev_a["content_hash"]))
        tc.assertEqual(self.drawings.usable_revision(self.dwg_a["id"])["id"], rev["id"])

        # estimate priced from that exact revision: quantities, units, price-book edition, exclusions;
        # a measured unit (SF) states how it was taken off the drawing (unit/scale control)
        with tc.assertRaises(EstimateError):
            c.estimates.create(project_id=self.pid, document_revision_id=self.ev_a["id"], lines=[
                {"description": "PZ-27 sheet pile cofferdam incl. dewatering", "quantity": "1200", "unit": "SF", "unit_price": "50.00"},
            ], actor="estimator")
        est = c.estimates.create(project_id=self.pid, document_revision_id=self.ev_a["id"], lines=[
            {"description": "PZ-27 sheet pile cofferdam incl. dewatering (price book PB-2026.1; excludes rock excavation)", "quantity": "1200", "unit": "SF", "unit_price": "50.00"},
            {"description": "Pump station (price book PB-2026.1; excludes electrical service)", "quantity": "1", "unit": "LS", "unit_price": "40000.00"},
        ], actor="estimator", price_book_ref="PB-2026.1", exclusions=["rock excavation", "electrical service"],
            measurement_basis=MEASUREMENT_BASIS_A)
        tc.assertEqual(est["total"], "100000.00")
        tc.assertEqual([(ln["quantity"], ln["unit"], ln["amount"]) for ln in est["lines"]], [("1200", "SF", "60000.00"), ("1", "LS", "40000.00")])
        ap = c.request_approval("estimate.approve", est["id"], actor_role="estimator", requested_by="estimator")
        tc.assertEqual(ap["manifest"]["bindings"]["document_hash"], self.ev_a["content_hash"])
        tc.assertEqual((ap["manifest"]["bindings"]["price_book_ref"], ap["manifest"]["bindings"]["exclusions"], ap["manifest"]["bindings"]["measurement_basis"]),
                       ("PB-2026.1", ["rock excavation", "electrical service"], MEASUREMENT_BASIS_A))
        c.approve(ap["id"], approver="owner")
        tc.assertEqual(c.execute(ap["id"], actor="estimator").result["status"], "approved")
        self.estimate = c.estimates.get(est["id"])
        tc.assertEqual((self.estimate["status"], self.estimate["stale"], self.estimate["approval_id"]), ("approved", False, ap["id"]))
        self.drawings.reference(self.dwr_a["id"], "estimate", est["id"], actor="estimator")

        # the PM proposes the exact agreement; the authorised signer executes it
        cmt = c.commitments.create(
            project_id=self.pid, supplier_id=self.supplier["id"], title="V1 subcontract - cofferdam and pump station",
            sov_lines=[{"description": "Sheet pile cofferdam and dewatering", "amount": "60000", "cost_code": "XX 10 00"},
                       {"description": "Pump station", "amount": "40000", "cost_code": "XX 20 00"}],
            retainage_rate="0.10", estimate_id=est["id"], actor="pm",
        )
        self.cid = cmt["id"]
        ap = c.request_approval("commitment.execute", self.cid, actor_role="pm", requested_by="pm")
        tc.assertEqual(ap["manifest"]["amounts"], {"total": "100000.00"})
        tc.assertEqual(ap["manifest"]["bindings"]["estimate_hash"], self.estimate["content_hash"])
        tc.assertEqual((ap["manifest"]["destination"]["party_id"], ap["manifest"]["destination"]["destination"]), (self.supplier["id"], SUPPLIER_DESTINATION))
        c.approve(ap["id"], approver="owner")
        res = c.execute(ap["id"], actor="owner")
        tc.assertEqual((res.result["status"], res.result["executed_amount"]), ("executed", "100000.00"))
        tc.assertEqual(c.approvals.get(ap["id"])["status"], "consumed")
        cmt = c.commitments.get(self.cid)
        tc.assertEqual([s["amount"] for s in cmt["sov"]], ["60000.00", "40000.00"])
        tc.assertEqual((cmt["original_amount"], cmt["executed_amount"], cmt["retainage_rate"]), ("100000.00", "100000.00", "0.100000"))
        self.line1, self.line2 = cmt["sov"][0]["id"], cmt["sov"][1]["id"]
        self.drawings.reference(self.dwr_a["id"], "commitment", self.cid, actor="pm")
        tc.assertEqual(sorted(r["referenced_by_type"] for r in self.drawings.references(self.dwr_a["id"])), ["commitment", "estimate"])

    # ---- step 2 ------------------------------------------------------------ #

    def step2(self, tc):
        """Drawing B issued; RFI cites both; response approved apart from distribution; $10,000 change."""
        c, f = self.c, self.field
        self.ev_b = self.evidence("drawing", "Drawing B - cofferdam extension", b"V1 synthetic drawing B rev 0: cofferdam extended 40 LF")
        self.dwg_b = self.drawings.register_drawing(self.pid, "D-B", "Cofferdam extension", "civil", actor="engineer")
        rev = self.drawings.add_revision(self.dwg_b["id"], "0", self.ev_b["id"], note="scope change", actor="engineer")
        c.approve_and_execute("drawing.issue", rev["id"], actor_role="pm", actor="pm", period_id="P1")
        self.dwr_b = self.drawings.revision(rev["id"])
        tc.assertEqual(self.dwr_b["status"], "issued")
        summary = self.drawings.state(self.pid)["summary"]
        tc.assertEqual((summary["drawings"], summary["issued"], summary["working"]), (2, 2, 0))

        # the RFI cites both issued revisions exactly (append-only register references)
        rfi = f.create_rfi(self.pid, "Cofferdam extension shown on D-B",
                           "D-B extends the D-A cofferdam by 40 LF. Confirm the added sheet piling and dewatering scope and its price?", "pm",
                           drawing_revision_ids=[self.dwr_a["id"], self.dwr_b["id"]])
        self.rfi_id = rfi["id"]
        tc.assertEqual((rfi["number"], rfi["status"], rfi["drawing_revision_ids"]), ("RFI-001", "open", [self.dwr_a["id"], self.dwr_b["id"]]))
        for dwr in (self.dwr_a, self.dwr_b):
            refs = [(r["referenced_by_id"], r["content_hash"]) for r in self.drawings.references(dwr["id"]) if r["referenced_by_type"] == "rfi"]
            tc.assertEqual(refs, [(rfi["id"], dwr["content_hash"])])

        # the official response is approved on its own; approving it sends nothing
        f.draft_response(rfi["id"], "Confirmed: add 40 LF of PZ-27 sheet piling with dewatering at the PB-2026.1 unit rates.",
                         cost_impact="10000", schedule_impact_days=5, actor="engineer")
        recipients = ["Synthetic Owner Agency representative", "Synthetic subcontractor project manager"]
        # nothing can be distributed before the official response exists
        with tc.assertRaises(FieldError):
            f.set_distribution_list(rfi["id"], recipients, "pm")
        with tc.assertRaises(FieldError):
            c.request_approval("field.distribute_rfi", rfi["id"], actor_role="pm", requested_by="pm")
        with tc.assertRaises(FieldError):  # the retired direct path refuses and points at the approval
            f.distribute_rfi(rfi["id"], recipients, actor="pm")
        ap = c.request_approval("field.respond_rfi", rfi["id"], actor_role="pm", requested_by="pm")
        tc.assertEqual(ap["manifest"]["amounts"], {"cost_impact": "10000.00"})
        c.approve(ap["id"], approver="owner")
        res = c.execute(ap["id"], actor="pm")
        tc.assertEqual(pick(res.result, ("status", "cost_impact", "schedule_impact_days")), {"status": "answered", "cost_impact": "10000.00", "schedule_impact_days": 5})
        tc.assertEqual(f.rfi(rfi["id"])["distributions"], [])
        # distribution is a separate, approval-bound step, to the mail sink only, and never repeated
        f.set_distribution_list(rfi["id"], recipients, "pm")
        ap = c.request_approval("field.distribute_rfi", rfi["id"], actor_role="pm", requested_by="pm")
        tc.assertEqual((ap["manifest"]["bindings"]["recipients"], ap["manifest"]["bindings"]["channel"], ap["manifest"]["bindings"]["leaves_the_prototype"]),
                       (recipients, "mail-sink", False))
        c.approve(ap["id"], approver="owner")
        dist = c.execute(ap["id"], actor="pm").result
        tc.assertEqual((dist["channel"], dist["recipients"], dist["response_hash"], dist["approval_id"]),
                       ("mail-sink", recipients, f.rfi(rfi["id"])["response_hash"], ap["id"]))
        tc.assertEqual(len(f.rfi(rfi["id"])["distributions"]), 1)
        with tc.assertRaises(FieldError):
            c.request_approval("field.distribute_rfi", rfi["id"], actor_role="pm", requested_by="pm")
        with tc.assertRaises(FieldError):
            f.set_distribution_list(rfi["id"], recipients, "pm")

        # the RFI's cost impact becomes a pending change; only change.execute moves the commitment
        ch = f.link_change(rfi["id"], self.cid, "pm", sov_line_id=self.line1)
        tc.assertEqual((ch["status"], ch["amount"], ch["rfi_number"]), ("pending", "10000.00", "RFI-001"))
        tc.assertEqual(c.commitments.get(self.cid)["executed_amount"], "100000.00")
        res = c.approve_and_execute("change.execute", ch["id"], actor_role="pm", actor="owner")
        tc.assertEqual(res.result["commitment_executed_amount"], "110000.00")
        cmt = c.commitments.get(self.cid)
        tc.assertEqual(([s["amount"] for s in cmt["sov"]], cmt["sov_total"], cmt["executed_amount"]), (["70000.00", "40000.00"], "110000.00", "110000.00"))
        tc.assertEqual(f.rfi(rfi["id"])["change"]["status"], "executed")

        # an unexecuted alternative reaches only the separately labelled forecast
        self.alt = c.commitments.propose_change(self.cid, amount="12000", reason="Alternative: heavier PZ-35 sections (not executed)",
                                                sov_line_id=self.line1, actor="pm")
        cmt = c.commitments.get(self.cid)
        tc.assertEqual((cmt["executed_amount"], cmt["sov_total"], cmt["pending_exposure"]), ("110000.00", "110000.00", "12000.00"))
        fc = c.forecast.project(self.pid)
        tc.assertEqual(pick(fc, ("executed_commitments", "pending_exposure", "forecast_at_completion")),
                       {"executed_commitments": "110000.00", "pending_exposure": "12000.00", "forecast_at_completion": "122000.00"})
        tc.assertIn("SHADOW", fc["label"])

    # ---- step 3 ------------------------------------------------------------ #

    def step3(self, tc):
        """Approved timesheets allocate labor to the WBS; payroll settles it without counting it twice."""
        c, lab, emp = self.c, self.labor, self.employee["id"]
        lab.set_rate(emp, "2026-10-01", "65.00", "150.00", actor="controller")
        self.ph1 = lab.add_phase(self.pid, "WBS-1.1", "Cofferdam engineering support", "40", "2600.00", True, actor="pm")
        self.ph2 = lab.add_phase(self.pid, "WBS-1.2", "Pump station engineering support", "40", "2600.00", True, actor="pm")
        lab.log_time(emp, self.pid, self.ph1["id"], "2026-10-05", "8", "sheet pile layout check", actor="engineer")
        lab.log_time(emp, self.pid, self.ph1["id"], "2026-10-06", "4", "dewatering well review", actor="engineer")
        lab.log_time(emp, self.pid, self.ph2["id"], "2026-10-06", "4", "wet well review", actor="engineer")
        ts = lab.submit_timesheet(emp, "P1", actor="engineer")
        tc.assertEqual((ts["status"], ts["total_hours"], ts["total_cost"]), ("submitted", "16.00", "1040.00"))
        res = c.approve_and_execute("labor.approve_timesheet", ts["id"], actor_role="pm", actor="pm", period_id="P1")
        tc.assertEqual([(a["phase_code"], a["hours"], a["cost"]) for a in res.result["allocation"]], [("WBS-1.1", "12.00", "780.00"), ("WBS-1.2", "4.00", "260.00")])
        j = c.ledger.journal(res.result["journal_id"])
        tc.assertEqual(lines_of(j), [("5300", "780.00", "0.00"), ("5300", "260.00", "0.00"), ("2200", "0.00", "1040.00")])
        tc.assertEqual([ln["project_id"] for ln in j["lines"][:2]], [self.pid, self.pid])
        tc.assertIn("WBS-1.1", j["lines"][0]["memo"])
        tc.assertIn("WBS-1.2", j["lines"][1]["memo"])

        # the payroll import settles the accrual; labor cost is not posted a second time
        pay = lab.record_payroll("P1", emp, "1040.00", "PR-2026-10-01", actor="payroll-import")
        res = c.approve_and_execute("labor.post_payroll", pay["id"], actor_role="controller", actor="controller", period_id="P1")
        tc.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])), [("2200", "1040.00", "0.00"), ("1000", "0.00", "1040.00")])
        tc.assertEqual(c.ledger.balance("5300", project_id=self.pid), D("1040.00"))
        tc.assertEqual(c.ledger.balance("2200"), D("0.00"))
        # distinct test line: importing the same time again is refused, as is a reused payroll reference
        with tc.assertRaises(LaborError):
            lab.record_payroll("P1", emp, "1040.00", "PR-2026-10-01-REIMPORT", actor="payroll-import")
        with tc.assertRaises(LaborError):
            lab.record_payroll("P1", emp, "1.00", "PR-2026-10-01", actor="payroll-import")
        tc.assertEqual(c.ledger.balance("5300"), D("1040.00"))
        rec = lab.accrued_payroll_reconciliation("P1")
        tc.assertEqual(pick(rec, ("reconciled", "subledger_total", "control_balance", "overdrawn")),
                       {"reconciled": True, "subledger_total": "0.00", "control_balance": "0.00", "overdrawn": []})
        fees = {p["code"]: (p["actual_hours"], p["actual_cost"]) for p in lab.fee_status(self.pid)["phases"]}
        tc.assertEqual(fees, {"WBS-1.1": ("12.00", "780.00"), "WBS-1.2": ("4.00", "260.00")})

    # ---- step 4 ------------------------------------------------------------ #

    def step4(self, tc):
        """Period 1: 20,000 installed + 10,000 eligible stored with evidence = 30,000; 3,000 retainage; 27,000 due."""
        c = self.c
        self.ev_lot1 = self.evidence("stored_material_evidence", "PZ-27 sheet piling stored on site",
                                     b"V1 title, insurance certificate, laydown location and delivery ticket: PZ-27 sheet piling")
        with tc.assertRaises(BillError):  # stored material without title/control/location evidence is ineligible
            c.bills.add_stored_material(commitment_id=self.cid, sov_line_id=self.line1, description="PZ-27 sheet piling", eligible_amount="10000", evidence_hash="", actor="pm")
        self.lot1 = c.bills.add_stored_material(commitment_id=self.cid, sov_line_id=self.line1, description="PZ-27 sheet piling stored on site",
                                                eligible_amount="10000", evidence_hash=self.ev_lot1["content_hash"], location="Laydown yard A (synthetic)", actor="pm")
        bill = c.bills.certify(commitment_id=self.cid, period_id="P1", installed=[{"sov_line_id": self.line1, "cumulative_installed": "20000"}], actor="pm")
        expected = {"cumulative_installed": "20000.00", "cumulative_stored": "10000.00", "cumulative_gross": "30000.00", "cumulative_retainage": "3000.00",
                    "cumulative_net": "27000.00", "prior_net": "0.00", "amount_due": "27000.00", "retainage_this_period": "3000.00",
                    "stored_added_this_period": "10000.00", "stored_transferred_this_period": "0.00", "status": "draft"}
        tc.assertEqual(pick(bill, expected), expected)
        tc.assertEqual(c.bills.lot(self.lot1["id"])["evidence_hash"], self.ev_lot1["content_hash"])
        self.bill1 = bill

    # ---- step 5 ------------------------------------------------------------ #

    def step5(self, tc):
        """Dr cost 20,000 + Dr stored 10,000 / Cr AP 27,000 + Cr retainage payable 3,000."""
        c = self.c
        ap = c.request_approval("bill.approve", self.bill1["id"], actor_role="accountant", requested_by="accountant")
        tc.assertEqual(ap["manifest"]["amounts"], {"amount_due": "27000.00", "retainage_this_period": "3000.00", "cumulative_gross": "30000.00"})
        tc.assertEqual(ap["manifest"]["bindings"]["posting_rule"], "cipher-posting-rules/1")
        c.approve(ap["id"], approver="controller")
        res = c.execute(ap["id"], actor="accountant")
        tc.assertEqual((res.result["status"], res.result["amount_due"]), ("posted", "27000.00"))
        js = c.ledger.journals(source_type="bill", source_id=self.bill1["id"])
        tc.assertEqual(len(js), 1)  # nothing moved from stored to installed in period 1
        tc.assertEqual(lines_of(js[0]), [("5000", "20000.00", "0.00"), ("1300", "10000.00", "0.00"), ("2000", "0.00", "27000.00"), ("2050", "0.00", "3000.00")])
        tc.assertEqual((js[0]["period_id"], js[0]["approval_id"]), ("P1", ap["id"]))
        for code, bal in (("5000", "20000.00"), ("1300", "10000.00"), ("2000", "27000.00"), ("2050", "3000.00")):
            tc.assertEqual(c.ledger.balance(code, project_id=self.pid), D(bal), code)
        tc.assertTrue(c.bills.ap_open_items(self.pid)["reconciled"])

    # ---- step 6 ------------------------------------------------------------ #

    def step6(self, tc):
        """Treasury releases 27,000; the provider accepts then times out; reconciliation finds the
        transfer; a replayed command and a duplicate webhook leave one transfer and one cash effect."""
        c = self.c
        ap = c.request_approval("payment.release", self.bill1["id"], actor_role="treasury", requested_by="accountant")
        m = ap["manifest"]
        tc.assertEqual(m["amounts"], {"amount": "27000.00"})
        tc.assertEqual((m["bindings"]["fees"], m["bindings"]["funding_source"], m["bindings"]["destination_verified"]), ("0.00", "operating-bank-simulated", True))
        tc.assertEqual((m["destination"]["destination"], m["destination"]["destination_version"]), (SUPPLIER_DESTINATION, 2))
        c.approve(ap["id"], approver="treasury")
        first = c.execute(ap["id"], actor="treasury")
        replay = c.execute(ap["id"], actor="treasury")
        tc.assertEqual((first.replayed, replay.replayed, replay.result), (False, True, first.result))
        with tc.assertRaises(ApprovalConsumed):  # a second worker with its own command id cannot release it again
            c.execute(ap["id"], actor="treasury", op_id="exec:second-treasury-worker")
        intents = c.payments.list()
        tc.assertEqual([(p["status"], p["amount"], p["payable_account"]) for p in intents], [("queued", "27000.00", "2000")])
        intent = intents[0]

        c.provider.mode = "timeout_after_accept"
        tc.assertEqual([r["status"] for r in c.dispatch_payments()], ["outcome_unknown"])
        tc.assertEqual(len(c.provider.transfers), 1)  # the rail has it; Cipher does not know yet
        tc.assertEqual(c.dispatch_payments(), [])  # an unknown outcome is never resubmitted
        self.backup_path = c.snapshot(os.path.join(self.tmp, "v1-backup-outcome-unknown.sqlite"))  # the older backup used in step 11
        c.provider.mode = "accept"
        rec = c.reconcile_payments()
        tc.assertEqual([(r["status"], r["provider_ref"]) for r in rec], [("accepted", "sim_000001")])
        intent = c.payments.get(intent["id"])
        settle = c.provider.settle(intent["logical_op_id"])
        tc.assertTrue(c.payments.ingest_event(settle, actor="webhook")["applied"])
        dup = c.payments.ingest_event(settle, actor="webhook")
        tc.assertEqual((dup["applied"], dup["reason"]), (False, "duplicate event"))
        tc.assertEqual(c.reconcile_payments(), [])
        tc.assertEqual(c.payments.get(intent["id"])["status"], "settled")
        tc.assertEqual((len(c.provider.transfers), len(c.provider.submissions)), (1, 1))
        tc.assertEqual(len(c.ledger.journals(source_type="payment_intent", source_id=intent["id"])), 1)
        tc.assertEqual(len(c.ledger.journals(source_type="provider_event")), 1)
        tc.assertEqual(c.ledger.balance("1200"), D("0.00"))
        tc.assertEqual(c.ledger.balance("1000"), D("-28040.00"))  # payroll 1,040 and exactly one 27,000 disbursement
        tc.assertEqual(c.bills.get(self.bill1["id"])["status"], "paid")
        ap_items = c.bills.ap_open_items(self.pid)
        tc.assertEqual((ap_items["subledger_total"], ap_items["control_balance"], ap_items["reconciled"]), ("0.00", "0.00", True))
        self.bill1_intent = intent["id"]

    # ---- step 7 ------------------------------------------------------------ #

    def step7(self, tc):
        """P1 closes; period 2: cumulative installed 45,000 incl. the 10,000 stored transfer, 5,000 new stored."""
        c = self.c
        self.reconcile_and_close(tc, "P1", "SIM-BANK-2026-10", "0.00", "-28040.00", [
            {"date": "2026-10-16", "amount": "-1040.00", "description": "Payroll (simulated)", "reference": "PR-2026-10-01"},
            {"date": "2026-10-21", "amount": "-27000.00", "description": "ACH disbursement (simulator)", "reference": "sim_000001"},
        ])
        c.open_period("P2", "P2", *PERIODS["P2"])

        self.ev_lot2 = self.evidence("stored_material_evidence", "Dewatering pumps stored on site",
                                     b"V1 title, insurance certificate, laydown location and delivery ticket: dewatering pumps and valves")
        self.lot2 = c.bills.add_stored_material(commitment_id=self.cid, sov_line_id=self.line1, description="Dewatering pumps and valves stored on site",
                                                eligible_amount="5000", evidence_hash=self.ev_lot2["content_hash"], location="Laydown yard A (synthetic)", actor="pm")
        bill = c.bills.certify(commitment_id=self.cid, period_id="P2", installed=[{"sov_line_id": self.line1, "cumulative_installed": "45000"}],
                               transfers=[{"lot_id": self.lot1["id"], "amount": "10000"}], actor="pm")
        expected = {"cumulative_installed": "45000.00", "cumulative_stored": "5000.00", "cumulative_gross": "50000.00", "cumulative_retainage": "5000.00",
                    "cumulative_net": "45000.00", "prior_net": "27000.00", "amount_due": "18000.00", "retainage_this_period": "2000.00",
                    "installed_this_period": "25000.00", "stored_added_this_period": "5000.00", "stored_transferred_this_period": "10000.00"}
        tc.assertEqual(pick(bill, expected), expected)
        res = c.approve_and_execute("bill.approve", bill["id"], actor_role="accountant", actor="accountant")
        js = c.ledger.journals(source_type="bill", source_id=bill["id"])
        tc.assertEqual([lines_of(j) for j in js], [
            [("5000", "10000.00", "0.00"), ("1300", "0.00", "10000.00")],  # transfer: stored -> installed
            [("5000", "15000.00", "0.00"), ("1300", "5000.00", "0.00"), ("2000", "0.00", "18000.00"), ("2050", "0.00", "2000.00")],  # incremental
        ])
        tc.assertEqual({(j["period_id"], j["approval_id"]) for j in js}, {("P2", c.bills.get(bill["id"])["approval_id"])})
        tc.assertEqual(res.result["journal_id"], js[-1]["id"])
        # cumulative cost 45,000 and stored asset 5,000: nothing counted twice
        tc.assertEqual(c.ledger.balance("5000", project_id=self.pid), D("45000.00"))
        tc.assertEqual(c.ledger.balance("1300", project_id=self.pid), D("5000.00"))
        tc.assertEqual(c.ledger.balance("2050", project_id=self.pid), D("5000.00"))
        tc.assertEqual({lot["id"]: lot["remaining_amount"] for lot in c.bills.lots(self.cid)}, {self.lot1["id"]: "0.00", self.lot2["id"]: "5000.00"})
        with tc.assertRaises(BillError):  # the transferred lot cannot be transferred (billed) again
            c.bills.certify(commitment_id=self.cid, period_id="P2", installed=[{"sov_line_id": self.line1, "cumulative_installed": "55000"}],
                            transfers=[{"lot_id": self.lot1["id"], "amount": "10000"}], actor="pm")
        tc.assertEqual(c.bills.latest(self.cid)["id"], bill["id"])
        self.bill2 = c.bills.get(bill["id"])
        self.pay_bill(tc, bill["id"], "sim_000002")

    # ---- step 8 ------------------------------------------------------------ #

    def step8(self, tc):
        """Prime bill: 60,000 certified, 6,000 retainage, 54,000 AR (fixture policy, SHADOW statements)."""
        c = self.c
        prime = c.receivables.certify(project_id=self.pid, period_id="P2", certified_cumulative="60000", retainage_rate="0.10", actor="pm")
        expected = {"certified_cumulative": "60000.00", "retainage_cumulative": "6000.00", "amount_due": "54000.00",
                    "revenue_this_period": "60000.00", "retainage_this_period": "6000.00", "status": "draft"}
        tc.assertEqual(pick(prime, expected), expected)
        ap = c.request_approval("prime_bill.approve", prime["id"], actor_role="accountant", requested_by="pm")
        tc.assertIn("SHADOW", ap["manifest"]["bindings"]["recognition_policy"])
        c.approve(ap["id"], approver="controller")
        j = c.ledger.journal(c.execute(ap["id"], actor="accountant").result["journal_id"])
        tc.assertEqual(lines_of(j), [("1100", "54000.00", "0.00"), ("1150", "6000.00", "0.00"), ("4000", "0.00", "60000.00")])
        tc.assertEqual(j["period_id"], "P2")
        tc.assertEqual(c.ledger.income_statement()["label"], SHADOW)
        statements = self.close.statements("P2")
        tc.assertEqual((statements["label"], statements["income_statement"]["revenue"]), (SHADOW, "60000.00"))
        tc.assertIn("SHADOW", c.forecast.project(self.pid)["label"])
        ar = c.receivables.ar_open_items(self.pid)
        tc.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("54000.00", "54000.00", True))
        self.prime1 = c.receivables.get(prime["id"])

    # ---- step 9 ------------------------------------------------------------ #

    def step9(self, tc):
        """Mail sink; 54,000 collected with a 5.00 fee; bank statement reconciled; P2 closes; a late
        return lands in the open period and the original receipt is preserved."""
        c = self.c
        with tc.assertRaises(ReceivableError):  # sending is its own approval-bound authority, never a direct call
            c.receivables.send(self.prime1["id"], actor="pm")
        send_ap, sent_result = send_prime_bill(c, self.prime1["id"])
        tc.assertEqual((sent_result["status"], sent_result["channel"]), ("sent", "mail-sink"))
        tc.assertEqual((send_ap["manifest"]["amounts"], send_ap["manifest"]["bindings"]["bill_hash"]), ({"amount_due": "54000.00"}, self.prime1["content_hash"]))
        tc.assertEqual(c.receivables.get(self.prime1["id"])["status"], "sent")
        sent = [e for e in c.audit.entries(entity_type="prime_bill", entity_id=self.prime1["id"]) if e["action"] == "prime_bill.sent"]
        tc.assertEqual(len(sent), 1)
        tc.assertEqual(json.loads(sent[0]["payload_json"])["channel"], "mail-sink")
        with tc.assertRaises(ReceivableError):  # an approved send is delivered once
            c.request_approval("prime_bill.send", self.prime1["id"], actor_role="pm", requested_by="pm")
        # an ACH debit needs the customer's recorded mandate, backed by owned evidence
        with tc.assertRaises(ReceivableError):
            c.receivables.record_collection(prime_bill_id=self.prime1["id"], period_id="P2", amount="54000", fee="5.00",
                                            provider_ref="ach_sim_rcv_0001", actor="treasury")
        record_mandate(c, self.pid, self.customer["id"], "MANDATE-SIM-V1-0001")
        col = c.receivables.record_collection(prime_bill_id=self.prime1["id"], period_id="P2", amount="54000", fee="5.00",
                                              provider_ref="ach_sim_rcv_0001", actor="treasury")
        tc.assertEqual((col["amount"], col["fee"], col["status"]), ("54000.00", "5.00", "received"))
        receipt = c.ledger.journal(col["journal_id"])
        tc.assertEqual(lines_of(receipt), [("1000", "53995.00", "0.00"), ("6000", "5.00", "0.00"), ("1100", "0.00", "54000.00")])
        with tc.assertRaises(ReceivableError):  # a replayed receipt is never booked twice
            c.receivables.record_collection(prime_bill_id=self.prime1["id"], period_id="P2", amount="54000", fee="5.00", provider_ref="ach_sim_rcv_0001", actor="treasury")
        tc.assertEqual((c.ledger.balance("6000"), c.ledger.balance("1100"), c.ledger.balance("1200")), (D("5.00"), D("0.00"), D("0.00")))
        tc.assertEqual(c.ledger.balance("1000"), D("7955.00"))  # -28,040 - 18,000 + 53,995
        self.reconcile_and_close(tc, "P2", "SIM-BANK-2026-11", "-28040.00", "7955.00", [
            {"date": "2026-11-10", "amount": "-18000.00", "description": "ACH disbursement (simulator)", "reference": "sim_000002"},
            {"date": "2026-11-20", "amount": "53995.00", "description": "ACH receipt net of processing fee", "reference": "ach_sim_rcv_0001"},
        ])

        # the late return arrives after P2 closed: it posts in open P3, never in P2
        c.open_period("P3", "P3", *PERIODS["P3"])
        reason = "R01 insufficient funds - late return after close (simulated)"
        with tc.assertRaises(PeriodNotOpen):
            c.receivables.record_return(collection_id=col["id"], period_id="P2", reason=reason, actor="treasury")
        tc.assertEqual([x["status"] for x in c.receivables.get(self.prime1["id"])["collections"]], ["received"])
        ret = c.receivables.record_return(collection_id=col["id"], period_id="P3", reason=reason, actor="treasury")
        tc.assertEqual((ret["status"], ret["journal_id"]), ("returned", col["journal_id"]))
        rj = c.ledger.journal(ret["return_journal_id"])
        tc.assertEqual((rj["period_id"], lines_of(rj)), ("P3", [("1100", "54000.00", "0.00"), ("1000", "0.00", "54000.00")]))
        original = c.ledger.journal(col["journal_id"])
        tc.assertEqual((original["period_id"], lines_of(original), original["reversed_by"]), ("P2", lines_of(receipt), None))
        tc.assertEqual(hash_json(self.close.statements("P2")), self.close_results["P2"]["statements_hash"])  # closed P2 did not move
        tc.assertEqual(c.receivables.get(self.prime1["id"])["status"], "sent")
        ar = c.receivables.ar_open_items(self.pid)
        tc.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("54000.00", "54000.00", True))

    # ---- step 10 ----------------------------------------------------------- #

    def step10(self, tc):
        """Final gross 110,000, retainage 11,000, net 99,000; 54,000 payable; closeout accepted through
        the field module closes the commitment; 11,000 retainage released and paid separately."""
        c, f = self.c, self.field
        bill = c.bills.certify(commitment_id=self.cid, period_id="P3",
                               installed=[{"sov_line_id": self.line1, "cumulative_installed": "70000"}, {"sov_line_id": self.line2, "cumulative_installed": "40000"}],
                               transfers=[{"lot_id": self.lot2["id"], "amount": "5000"}], actor="pm")
        expected = {"cumulative_installed": "110000.00", "cumulative_stored": "0.00", "cumulative_gross": "110000.00", "cumulative_retainage": "11000.00",
                    "cumulative_net": "99000.00", "prior_net": "45000.00", "amount_due": "54000.00", "retainage_this_period": "6000.00",
                    "installed_this_period": "65000.00", "stored_added_this_period": "0.00", "stored_transferred_this_period": "5000.00"}
        tc.assertEqual(pick(bill, expected), expected)
        c.approve_and_execute("bill.approve", bill["id"], actor_role="accountant", actor="accountant")
        tc.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=bill["id"])], [
            [("5000", "5000.00", "0.00"), ("1300", "0.00", "5000.00")],
            [("5000", "60000.00", "0.00"), ("2000", "0.00", "54000.00"), ("2050", "0.00", "6000.00")],
        ])
        tc.assertEqual(c.ledger.balance("5000", project_id=self.pid), D("110000.00"))
        tc.assertEqual(c.ledger.balance("1300", project_id=self.pid), D("0.00"))
        tc.assertEqual(c.ledger.balance("2050", project_id=self.pid), D("11000.00"))
        self.bill3 = c.bills.get(bill["id"])
        self.pay_bill(tc, bill["id"], "sim_000003")

        # prime final billing under its own contract (fixture: 132,000 contract, 10% retainage)
        prime = c.receivables.certify(project_id=self.pid, period_id="P3", certified_cumulative="132000", retainage_rate="0.10", actor="pm")
        expected = {"certified_cumulative": "132000.00", "retainage_cumulative": "13200.00", "prior_net": "54000.00", "amount_due": "64800.00",
                    "revenue_this_period": "72000.00", "retainage_this_period": "7200.00"}
        tc.assertEqual(pick(prime, expected), expected)
        res = c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="accountant", actor="accountant")
        tc.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])), [("1100", "64800.00", "0.00"), ("1150", "7200.00", "0.00"), ("4000", "0.00", "72000.00")])
        send_prime_bill(c, prime["id"])
        self.prime2 = c.receivables.get(prime["id"])
        tc.assertEqual(self.prime2["status"], "sent")

        # closeout: required deliverables, punch closure and no pending change
        f.set_closeout_requirements(self.cid, [item for item, _ in CLOSEOUT_DELIVERABLES], "pm")
        punch = f.add_punch_item(self.pid, self.cid, "Seal weep holes at the pump station wet well", "superintendent")
        with tc.assertRaises(FieldError):
            c.request_approval("field.accept_closeout", self.cid, actor_role="pm")
        for item, title in CLOSEOUT_DELIVERABLES:
            ev = self.evidence("closeout", f"{title} (synthetic)", f"V1 synthetic {title} for the cofferdam and pump station".encode())
            f.submit_closeout_item(self.cid, item, ev["content_hash"], "pm")
        photo = self.evidence("punch_evidence", "Wet well weep holes sealed (photo)", b"V1 synthetic photo: weep holes sealed")
        f.close_punch_item(punch["id"], photo["content_hash"], "superintendent")
        co = f.closeout(self.cid)
        tc.assertEqual((co["missing"], co["open_punch_count"], [ch["id"] for ch in co["pending_changes"]]), ([], 0, [self.alt["id"]]))
        tc.assertFalse(co["ready_for_acceptance"])
        with tc.assertRaises(FieldError):  # the pending alternative would let the commitment grow after closeout
            c.request_approval("field.accept_closeout", self.cid, actor_role="pm")
        c.commitments.reject_change(self.alt["id"], actor="pm", reason="alternative not selected by the owner")
        cmt = c.commitments.get(self.cid)
        tc.assertEqual((cmt["executed_amount"], cmt["pending_exposure"]), ("110000.00", "0.00"))
        tc.assertTrue(f.closeout(self.cid)["ready_for_acceptance"])
        res = c.approve_and_execute("field.accept_closeout", self.cid, actor_role="pm", actor="owner", period_id="P3")
        tc.assertEqual(pick(res.result, ("status", "commitment_status", "period_id")), {"status": "accepted", "commitment_status": "closed", "period_id": "P3"})
        tc.assertEqual(c.commitments.get(self.cid)["status"], "closed")
        tc.assertEqual(sorted(f.closeout(self.cid)["required_items"]), sorted(item for item, _ in CLOSEOUT_DELIVERABLES))

        # retainage is released separately, through its own approval
        ap = c.request_approval("retainage.release", self.cid, actor_role="accountant", requested_by="pm")
        tc.assertEqual(ap["manifest"]["amounts"], {"retainage_held": "11000.00"})
        c.approve(ap["id"], approver="owner")
        res = c.execute(ap["id"], actor="accountant", period_id="P3")
        tc.assertEqual(res.result["amount"], "11000.00")
        tc.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])), [("2050", "11000.00", "0.00"), ("2000", "0.00", "11000.00")])
        tc.assertEqual(c.ledger.balance("2050"), D("0.00"))
        self.refused(tc, "retainage.release", self.cid, BillError, role="accountant", period_id="P3")  # nothing is left to release

        # ... and paid through the durable outbox
        ap = c.request_approval("payment.release_retainage", self.cid, actor_role="treasury", requested_by="accountant")
        tc.assertEqual(ap["manifest"]["amounts"], {"amount": "11000.00"})
        c.approve(ap["id"], approver="treasury")
        r = c.execute(ap["id"], actor="treasury")
        pending = c.commands.pending("payment")
        tc.assertEqual([p["payload"]["intent_id"] for p in pending], [r.result["intent"]])
        tc.assertEqual([(x["status"], x["provider_ref"]) for x in c.dispatch_payments()], [("accepted", "sim_000004")])
        intent = c.payments.get(r.result["intent"])
        tc.assertTrue(c.payments.ingest_event(c.provider.settle(intent["logical_op_id"]), actor="webhook")["applied"])
        with tc.assertRaises(PaymentError):  # released retainage is paid exactly once
            c.request_approval("payment.release_retainage", self.cid, actor_role="treasury")
        ap_items = c.bills.ap_open_items(self.pid)
        tc.assertEqual((ap_items["subledger_total"], ap_items["control_balance"], ap_items["reconciled"]), ("0.00", "0.00", True))
        settled = [p["amount"] for p in c.payments.list() if p["status"] == "settled"]
        tc.assertEqual(sorted(settled), sorted(["27000.00", "18000.00", "54000.00", "11000.00"]))
        tc.assertEqual(sum(D(a) for a in settled), D("110000.00"))  # 99,000 net certifications + 11,000 retainage

    # ---- step 11 ----------------------------------------------------------- #

    def step11(self, tc):
        """The period closes through the checklist; late corrections cannot edit or bypass the lock;
        an older backup restores read-only and quarantined; no payment is sent twice."""
        c = self.c

        def stale_close_probe(tc_):
            # a close approval granted before a late draft time entry goes stale instead of executing
            ap = c.request_approval("close.close_period", "P3", actor_role="controller", requested_by="controller")
            tc_.assertTrue(ap["manifest"]["bindings"]["checklist_ok"])
            c.approve(ap["id"], approver="owner")
            entry = self.labor.log_time(self.employee["id"], self.pid, self.ph1["id"], "2026-12-20", "2", "late timesheet entry", actor="engineer")
            with tc_.assertRaises(STALE):
                c.execute(ap["id"], actor="controller", period_id="P3")
            tc_.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
            tc_.assertEqual(c.ledger.period("P3")["status"], "open")
            self.labor.delete_entry(entry["id"], actor="engineer", reason="logged in error")

        self.reconcile_and_close(tc, "P3", "SIM-BANK-2026-12", "7955.00", "-111045.00", [
            {"date": "2026-12-03", "amount": "-54000.00", "description": "ACH return R01 (simulated)", "reference": "ach_sim_rcv_0001"},
            {"date": "2026-12-15", "amount": "-54000.00", "description": "ACH disbursement (simulator)", "reference": "sim_000003"},
            {"date": "2026-12-18", "amount": "-11000.00", "description": "ACH disbursement (simulator)", "reference": "sim_000004"},
        ], before_close=stale_close_probe)

        # a late correction cannot edit a posted row ...
        j1 = c.ledger.journals(source_type="bill", source_id=self.bill1["id"])[0]
        j3 = c.ledger.journals(source_type="bill", source_id=self.bill3["id"])[-1]
        for sql, params in (
            ("UPDATE journal_lines SET debit='19000.00' WHERE id=?", (j1["lines"][0]["id"],)),
            ("UPDATE journals SET period_id='P3' WHERE id=?", (j1["id"],)),
            ("DELETE FROM journal_lines WHERE id=?", (j1["lines"][0]["id"],)),
            ("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES ('jln_v1_late', ?, 99, '5000', '1.00', '0.00', 'late correction')", (j3["id"],)),
            ("INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by) "
             "VALUES ('jrn_v1_late', 'P3', '2026-12-31T23:59:59Z', 'late correction', 'late_correction', 'v1-late', '1', 'cipher-posting-rules/1', 'accountant')", ()),
        ):
            with tc.assertRaises(sqlite3.DatabaseError, msg=sql):
                c.db.execute(sql, params)
        tc.assertEqual(lines_of(c.ledger.journal(j1["id"])), lines_of(j1))
        tc.assertEqual(lines_of(c.ledger.journal(j3["id"])), lines_of(j3))
        # ... nor bypass the period lock through the ledger or a module
        with tc.assertRaises(PeriodNotOpen):
            c.ledger.post(period_id="P3", description="late correction", lines=[{"account": "5000", "debit": "100"}, {"account": "2000", "credit": "100"}],
                          source_type="late_correction", source_id="v1-late-1", source_version="1", posted_by="accountant")
        with tc.assertRaises(PeriodNotOpen):
            c.ledger.reverse(j3["id"], period_id="P3", posted_by="accountant", reason="late correction")
        with tc.assertRaises(PeriodNotOpen):
            c.receivables.certify(project_id=self.pid, period_id="P3", certified_cumulative="140000", actor="pm")
        tc.assertEqual(c.ledger.trial_balance("P3")["journal_count"], self.close.close_run(self.close_results["P3"]["close_run_id"])["journal_count"])

        # the closed periods are locked in order; a locked period never reopens
        for pid in PERIODS:
            res = c.approve_and_execute("close.lock_period", pid, actor_role="controller", actor="controller", period_id=pid)
            tc.assertEqual(res.result["status"], "locked")
        self.refused(tc, "close.reopen_period", "P3", CloseError, role="controller", period_id="P3")
        with tc.assertRaises(LedgerError):
            c.ledger.reopen_period("P3", actor="controller", approval_ref="apr_v1_late_reopen")
        tc.assertEqual([c.ledger.period(p)["status"] for p in PERIODS], ["locked", "locked", "locked"])

        # an older backup restored: read-only, payment release quarantined until recovery reconciliation
        transfers_before = {k: v["provider_ref"] for k, v in c.provider.transfers.items()}
        submissions_before = len(c.provider.submissions)
        tc.assertEqual((len(transfers_before), submissions_before), (4, 4))
        restored = self.restored = Cipher.open_restored(self.backup_path, provider=c.provider)
        tc.assertFalse(restored.db.has_write_authority())
        tc.assertFalse(restored.db.authority_status()["effective_write_authority"])
        tc.assertEqual(restored.payments.get(self.bill1_intent)["status"], "outcome_unknown")  # the backup predates the reconciliation
        attempt = {}
        with tc.assertRaises(WriteAuthorityError):  # a release from the copy is refused at the command boundary
            attempt["ap"] = restored.request_approval("payment.release", self.bill1["id"], actor_role="treasury", requested_by="treasury")
            restored.approve(attempt["ap"]["id"], approver="treasury")
            restored.execute(attempt["ap"]["id"], actor="treasury")
        tc.assertEqual(len(restored.payments.list()), 1)
        with tc.assertRaises(WriteAuthorityError):  # nor can the copy change any other record before the claim
            restored.add_party(kind="supplier", name="Injected payee (restored copy)", destination="ACH-SIM-INJECTED")
        tc.assertIn("authority", {it["kind"] for it in restored.ricky.brief(self.pid, actor_role="owner")["items"] if it["level"] == "blocker"})
        status = claim_restored_copy(restored)
        tc.assertTrue(status["effective_write_authority"])
        tc.assertTrue(status["release_quarantined"])
        claim = [e for e in restored.audit.entries(entity_type="workspace") if e["action"] == "workspace.claim_write_authority"]
        tc.assertEqual(len(claim), 1)
        tc.assertEqual({k: json.loads(claim[0]["payload_json"])[k] for k in ("approver", "restored_copy")}, {"approver": "owner", "restored_copy": True})
        if "ap" in attempt:
            restored.reject(attempt["ap"]["id"], approver="owner", reason="attempted from a restored copy")
        with tc.assertRaises(ReleaseQuarantined):
            restored.dispatch_payments()
        # recovery finds the transfer the backup only knew as "outcome unknown" without resubmitting it,
        # and holds the quarantine: the live workspace made three more transfers the older backup never recorded
        outcome = restored.complete_recovery(actor="reconciler")
        tc.assertFalse(outcome["quarantine_lifted"])
        tc.assertEqual([(r["status"], r["provider_ref"]) for r in outcome["results"]], [("accepted", "sim_000001")])
        # the settlement callback the backup never saw is caught up exactly once, as a signed reconciliation event
        tc.assertEqual([(cb["status"], cb["caught_up_event"]) for cb in outcome["callbacks"]], [("settled", "recon_sim_000001_settled")])
        tc.assertEqual(restored.payments.get(self.bill1_intent)["status"], "settled")
        tc.assertEqual(len(restored.ledger.journals(source_type="payment_intent", source_id=self.bill1_intent)), 1)
        tc.assertEqual([t["provider_ref"] for t in outcome["unrecorded_transfers"]], ["sim_000002", "sim_000003", "sim_000004"])
        tc.assertTrue(any("payment.adopt_transfer" in h for h in outcome["held"]), outcome["held"])
        tc.assertTrue(restored.db.authority_status()["release_quarantined"])
        # the open quarantine is routed to its owner: Ricky's brief carries it as a blocker
        tc.assertIn("quarantine", {it["kind"] for it in restored.ricky.brief(self.pid, actor_role="owner")["items"] if it["level"] == "blocker"})
        with tc.assertRaises(ReleaseQuarantined):
            restored.dispatch_payments()
        tc.assertEqual({k: v["provider_ref"] for k, v in c.provider.transfers.items()}, transfers_before)  # no payment sent twice
        tc.assertEqual(len(c.provider.submissions), submissions_before)
        tc.assertTrue(restored.ledger.trial_balance()["balanced"])
        tc.assertTrue(restored.audit.verify_chain()["ok"])
        tc.assertTrue(c.db.has_write_authority())  # the live workspace is untouched

    # ---- step 12: pass criteria ---------------------------------------------- #

    def step12(self, tc):
        c = self.c
        # every journal batch balances exactly; the trial balance balances overall and per period
        journals = c.ledger.journals()
        for j in journals:
            dr = sum(D(ln["debit"]) for ln in j["lines"])
            cr = sum(D(ln["credit"]) for ln in j["lines"])
            tc.assertEqual(dr, cr, j["id"])
            tc.assertGreater(dr, 0, j["id"])
        tc.assertTrue(c.ledger.trial_balance()["balanced"])
        for pid in PERIODS:
            tc.assertTrue(c.ledger.trial_balance(pid)["balanced"], pid)
            tc.assertTrue(self.close.statements(pid)["balance_sheet"]["balanced"], pid)

        # AP, AR, employee payables and bank reconcile
        ap = c.bills.ap_open_items()
        tc.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("0.00", "0.00", True))
        ar = c.receivables.ar_open_items()
        tc.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("118800.00", "118800.00", True))
        emp = self.reimb.employee_payable_reconciliation(self.pid)
        tc.assertEqual((emp["subledger_total"], emp["control_balance"], emp["reconciled"]), ("0.00", "0.00", True))
        accrued = self.labor.accrued_payroll_reconciliation()
        tc.assertEqual((accrued["subledger_total"], accrued["control_balance"], accrued["reconciled"]), ("0.00", "0.00", True))
        for pid in PERIODS:
            tc.assertTrue(self.bank.reconciliation_status(pid)["reconciled"], pid)
        balances = {code: c.ledger.balance(code) for code in ("1000", "1100", "1150", "1200", "1300", "2000", "2050", "2200", "4000", "5000", "5300", "6000")}
        tc.assertEqual(balances, {"1000": D("-111045.00"), "1100": D("118800.00"), "1150": D("13200.00"), "1200": D("0.00"), "1300": D("0.00"),
                                  "2000": D("0.00"), "2050": D("0.00"), "2200": D("0.00"), "4000": D("132000.00"), "5000": D("110000.00"),
                                  "5300": D("1040.00"), "6000": D("5.00")})

        # provider transfers are unique: one transfer, one acceptance and one cash effect per intent
        intents = c.payments.list()
        tc.assertEqual(len(intents), 4)
        tc.assertEqual(len({p["logical_op_id"] for p in intents}), 4)
        tc.assertEqual(sorted(p["provider_ref"] for p in intents), ["sim_000001", "sim_000002", "sim_000003", "sim_000004"])
        tc.assertEqual(sorted(t["provider_ref"] for t in c.provider.transfers.values()), sorted(p["provider_ref"] for p in intents))
        tc.assertEqual(len(c.provider.submissions), 4)
        tc.assertEqual(len(c.ledger.journals(source_type="payment_intent")), 4)
        tc.assertEqual(len(c.ledger.journals(source_type="provider_event")), 4)

        # stored material never double counted
        lots = c.bills.lots(self.cid)
        tc.assertEqual([lot["remaining_amount"] for lot in lots], ["0.00", "0.00"])
        transferred = sum(D(t["amount"]) for b in c.bills.list(commitment_id=self.cid) for t in b["transfers"])
        tc.assertEqual((transferred, sum(D(lot["eligible_amount"]) for lot in lots)), (D("15000.00"), D("15000.00")))
        tc.assertEqual(c.ledger.balance("5000", project_id=self.pid), D(c.bills.latest(self.cid)["cumulative_gross"]))

        # every consequential action is recorded as a consumed approval
        consumed = c.approvals.list(status="consumed")
        ops = {a["operation"] for a in consumed}
        for op in ("estimate.approve", "commitment.execute", "drawing.issue", "field.respond_rfi", "field.distribute_rfi", "change.execute", "labor.approve_timesheet",
                   "labor.post_payroll", "bill.approve", "payment.release", "prime_bill.approve", "prime_bill.send", "banking.lock_reconciliation", "close.close_period",
                   "field.accept_closeout", "retainage.release", "payment.release_retainage", "close.lock_period"):
            tc.assertIn(op, ops)
        tc.assertEqual(sum(1 for a in consumed if a["operation"] == "prime_bill.send"), 2)
        tc.assertEqual(sum(1 for a in consumed if a["operation"] == "bill.approve"), 3)
        tc.assertEqual(sum(1 for a in consumed if a["operation"] == "payment.release"), 3)
        tc.assertEqual(sum(1 for a in consumed if a["operation"] == "close.close_period"), 3)
        for j in journals:
            if j["approval_id"]:
                tc.assertEqual(c.approvals.get(j["approval_id"])["status"], "consumed", j["id"])
            else:
                tc.assertIn(j["source_type"], BANK_FACT_SOURCES, j["id"])
        tc.assertEqual(c.approvals.list(status="granted"), [])
        tc.assertEqual(c.approvals.list(status="pending"), [])
        for bill in c.bills.list(commitment_id=self.cid):
            tc.assertEqual((bill["status"], c.approvals.get(bill["approval_id"])["status"]), ("paid", "consumed"))
        tc.assertEqual(c.approvals.get(self.field.rfi(self.rfi_id)["approval_id"])["status"], "consumed")
        tc.assertEqual(c.approvals.get(self.field.closeout(self.cid)["approval_id"])["status"], "consumed")

        # the audit chain verifies and the project state carries every module
        tc.assertTrue(c.audit.verify_chain()["ok"])
        state = c.project_state(self.pid)
        json.dumps(state, default=str)
        tc.assertTrue(state["audit_chain"]["ok"])
        tc.assertEqual((state["forecast"]["executed_commitments"], state["forecast"]["paid_to_date"]), ("110000.00", "110000.00"))
        tc.assertEqual(state["drawing"]["summary"]["issued"], 2)
        tc.assertEqual((state["field"]["summary"]["rfis_answered"], state["field"]["summary"]["closeouts_accepted"]), (1, 1))
        tc.assertEqual(state["labor"]["ledger"]["labor_cost_5300"], "1040.00")
        tc.assertEqual(state["banking"]["scope"], "entity")
        tc.assertEqual(state["close"]["label"], SHADOW)
        tc.assertEqual(state["income_statement"]["label"], SHADOW)


class VerticalV1Tests(unittest.TestCase):
    """Plan section 10, steps 1-11 in order, then the pass criteria."""

    scenario: VerticalV1 | None = None

    @classmethod
    def setUpClass(cls):
        cls.scenario = VerticalV1()

    @classmethod
    def tearDownClass(cls):
        if cls.scenario is not None:
            cls.scenario.cleanup()

    def run_step(self, n):
        self.scenario.run_through(n, self)

    def test_step01_estimate_drawing_a_and_executed_subcontract(self):
        self.run_step(1)

    def test_step02_drawing_b_rfi_response_distribution_and_change(self):
        self.run_step(2)

    def test_step03_timesheets_to_wbs_and_payroll_without_double_count(self):
        self.run_step(3)

    def test_step04_period1_certification_with_stored_material_evidence(self):
        self.run_step(4)

    def test_step05_period1_posting_rule(self):
        self.run_step(5)

    def test_step06_release_timeout_reconciliation_and_replay(self):
        self.run_step(6)

    def test_step07_period1_close_and_period2_certification(self):
        self.run_step(7)

    def test_step08_prime_progress_bill_shadow(self):
        self.run_step(8)

    def test_step09_collection_bank_reconciliation_and_late_return(self):
        self.run_step(9)

    def test_step10_final_work_closeout_and_retainage(self):
        self.run_step(10)

    def test_step11_close_late_correction_and_restore(self):
        self.run_step(11)

    def test_step12_pass_criteria(self):
        self.run_step(12)


# --------------------------------------------------------------------------- #
# Focused variants                                                             #
# --------------------------------------------------------------------------- #

class World:
    """A small workspace: verified subcontractor, customer, project, open periods, executed $100,000 commitment."""

    def __init__(self, periods=("P1",)):
        c = self.c = Cipher()
        self.supplier = c.add_party(kind="supplier", name="Synthetic Subcontractor (V1 variant)", destination="ACH-SIM-V1-VAR-0001")
        c.verify_destination(self.supplier["id"], destination="ACH-SIM-V1-VAR-0001", verified_by="bank-detail-maintainer")
        self.customer = c.add_party(kind="customer", name="Synthetic Owner Agency (V1 variant)")
        self.project = c.create_project(name="V1 variant project", entity="S&A Solutions LLC (synthetic)", budget="125000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        for p in periods:
            c.open_period(p, p, *PERIODS[p])
        cmt = c.commitments.create(project_id=self.pid, supplier_id=self.supplier["id"], title="V1 variant subcontract",
                                   sov_lines=[{"description": "Cofferdam", "amount": "60000"}, {"description": "Pump station", "amount": "40000"}],
                                   retainage_rate="0.10", actor="pm")
        c.approve_and_execute("commitment.execute", cmt["id"], actor_role="pm")
        self.cid = cmt["id"]
        sov = c.commitments.get(self.cid)["sov"]
        self.line1, self.line2 = sov[0]["id"], sov[1]["id"]

    def posted_bill(self, cumulative, period="P1"):
        b = self.c.bills.certify(commitment_id=self.cid, period_id=period, installed=[{"sov_line_id": self.line1, "cumulative_installed": cumulative}], actor="pm")
        self.c.approve_and_execute("bill.approve", b["id"], actor_role="accountant")
        return self.c.bills.get(b["id"])


class VerticalV1VariantTests(unittest.TestCase):
    """Adversarial variants of the vertical that cross module boundaries."""

    def test_unexecuted_alternative_never_raises_the_billable_total(self):
        w = World()
        c = w.c
        alt = c.commitments.propose_change(w.cid, amount="12000", reason="Alternative (not executed)", sov_line_id=w.line1, actor="pm")
        with self.assertRaises(BillError):  # line 1 is still 60,000; the pending 12,000 cannot be billed
            c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": w.line1, "cumulative_installed": "65000"}], actor="pm")
        with self.assertRaises(BillError):  # a hash Cipher never stored is not evidence
            c.bills.add_stored_material(commitment_id=w.cid, sov_line_id=w.line1, description="Stored sheet piling", eligible_amount="5000",
                                        evidence_hash=sha256_hex(b"V1 variant stored material evidence"), location="Laydown yard B (synthetic)", actor="pm")
        ev = stored_evidence(c, w.pid, "Stored sheet piling, laydown yard B")
        c.bills.add_stored_material(commitment_id=w.cid, sov_line_id=w.line1, description="Stored sheet piling", eligible_amount="5000",
                                    evidence_hash=ev["content_hash"], location="Laydown yard B (synthetic)", actor="pm")
        with self.assertRaises(BillError):  # 100,000 installed + 5,000 stored would overbill the executed 100,000
            c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": w.line1, "cumulative_installed": "60000"},
                                                                            {"sov_line_id": w.line2, "cumulative_installed": "40000"}], actor="pm")
        self.assertEqual(c.bills.list(commitment_id=w.cid), [])
        self.assertEqual(c.ledger.journals(), [])
        cmt = c.commitments.get(w.cid)
        self.assertEqual((cmt["executed_amount"], cmt["pending_exposure"], c.commitments.change(alt["id"])["status"]), ("100000.00", "12000.00", "pending"))
        fc = c.forecast.project(w.pid)
        self.assertEqual((fc["executed_commitments"], fc["pending_exposure"], fc["forecast_at_completion"]), ("100000.00", "12000.00", "112000.00"))
        # only executing the change through its approval makes the value billable
        c.approve_and_execute("change.execute", alt["id"], actor_role="pm")
        bill = c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": w.line1, "cumulative_installed": "65000"}], actor="pm")
        self.assertEqual((bill["cumulative_gross"], bill["amount_due"]), ("70000.00", "63000.00"))

    def test_unbooked_bank_charge_blocks_the_close_until_booked_through_an_approval(self):
        w = World()
        c = w.c
        bank, close = c.plugin("banking"), c.plugin("close")
        prime = c.receivables.certify(project_id=w.pid, period_id="P1", certified_cumulative="60000", retainage_rate="0.10", actor="pm")
        c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="accountant")
        send_prime_bill(c, prime["id"])
        record_mandate(c, w.pid, w.customer["id"], "MANDATE-SIM-V1-VAR-9001")
        c.receivables.record_collection(prime_bill_id=prime["id"], period_id="P1", amount="54000", fee="5", provider_ref="ach_sim_rcv_9001", actor="treasury")
        st = bank.import_statement(statement_ref="SIM-BANK-VAR-2026-10", period_id="P1", opening_balance="0.00", closing_balance="53970.00", actor="reconciler", lines=[
            {"date": "2026-10-20", "amount": "53995.00", "description": "ACH receipt net of processing fee", "reference": "ach_sim_rcv_9001"},
            {"date": "2026-10-31", "amount": "-25.00", "description": "Incoming ACH service charge", "reference": "BKFEE-2026-10"},
        ])
        m = bank.auto_match(st["id"], actor="reconciler")
        self.assertEqual((len(m["matched"]), [u["reference"] for u in m["unmatched"]]), (1, ["BKFEE-2026-10"]))
        rec = bank.reconciliation(st["id"])
        self.assertEqual((rec["reconciled"], rec["difference"], len(rec["unmatched_statement_lines"])), (False, "-25.00", 1))
        with self.assertRaises(BankingError):  # an unreconciled statement cannot be locked
            c.request_approval("banking.lock_reconciliation", st["id"], actor_role="reconciler")
        self.assertIn("bank reconciliation", close.checklist_report("P1")["failing"])
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.close_period", "P1", actor_role="controller", period_id="P1")
        self.assertEqual(c.ledger.period("P1")["status"], "open")

        fee_line = next(ln for ln in bank.lines(st["id"]) if not ln["matched"])
        ap = c.request_approval("banking.post_fee", fee_line["id"], actor_role="accountant")
        self.assertEqual(ap["manifest"]["amounts"], {"fee": "25.00", "line_amount": "-25.00"})
        c.approve(ap["id"], approver="controller")
        res = c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])), [("6000", "25.00", "0.00"), ("1000", "0.00", "25.00")])
        with self.assertRaises(BankingError):  # the charge is never booked twice
            c.request_approval("banking.post_fee", fee_line["id"], actor_role="accountant")
        self.assertTrue(bank.reconciliation(st["id"])["reconciled"])
        c.approve_and_execute("banking.lock_reconciliation", st["id"], actor_role="reconciler", period_id="P1")
        report = close.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        self.assertEqual(c.approve_and_execute("close.close_period", "P1", actor_role="controller", period_id="P1").result["status"], "closed")
        self.assertEqual((c.ledger.balance("6000"), c.ledger.balance("1000")), (D("30.00"), D("53970.00")))
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_period_lock_applies_to_every_entry_path(self):
        w = World()
        c = w.c
        lab, bank, drawings = c.plugin("labor"), c.plugin("banking"), c.plugin("drawing")
        bill = w.posted_bill("20000")
        bill_journal = c.ledger.journals(source_type="bill", source_id=bill["id"])[0]
        emp = c.add_party(kind="employee", name="Synthetic Engineer (V1 variant)")
        lab.set_rate(emp["id"], "2026-10-01", "60.00", "140.00", actor="controller")
        phase = lab.add_phase(w.pid, "WBS-9", "Variant support", "10", "600.00", True, actor="pm")
        doc = c.evidence.register_document(project_id=w.pid, kind="drawing", title="Variant drawing", actor="engineer")
        ev = c.evidence.add_revision(document_id=doc["id"], content=b"V1 variant drawing rev 0", actor="engineer")
        dwg = drawings.register_drawing(w.pid, "D-V", "Variant drawing", "civil", actor="engineer")
        rev = drawings.add_revision(dwg["id"], "0", ev["id"], actor="engineer")
        self.assertEqual(c.approve_and_execute("close.close_period", "P1", actor_role="controller", period_id="P1").result["status"], "closed")
        c.open_period("P2", "P2", *PERIODS["P2"])
        p1_journals = c.ledger.trial_balance("P1")["journal_count"]

        with self.assertRaises(PeriodNotOpen):
            c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": w.line1, "cumulative_installed": "30000"}], actor="pm")
        with self.assertRaises(PeriodNotOpen):
            c.receivables.certify(project_id=w.pid, period_id="P1", certified_cumulative="10000", actor="pm")
        with self.assertRaises(PeriodNotOpen):
            c.ledger.reverse(bill_journal["id"], period_id="P1", posted_by="accountant", reason="late correction")
        with self.assertRaises(LaborError):
            lab.log_time(emp["id"], w.pid, phase["id"], "2026-10-20", "4", "late time", actor="engineer")
        with self.assertRaises(LaborError):
            lab.record_payroll("P1", emp["id"], "10.00", "PR-V1-LATE", actor="payroll-import")
        with self.assertRaises(BankingError):
            bank.import_statement(statement_ref="SIM-BANK-V1-LATE", period_id="P1", opening_balance="0.00", closing_balance="-1.00", actor="reconciler",
                                  lines=[{"date": "2026-10-30", "amount": "-1.00", "description": "late charge", "reference": "LATE-1"}])
        with self.assertRaises(PeriodNotOpen):
            c.approve_and_execute("drawing.issue", rev["id"], actor_role="pm", period_id="P1")
        self.assertEqual(drawings.revision(rev["id"])["status"], "working")
        prime = c.receivables.certify(project_id=w.pid, period_id="P2", certified_cumulative="10000", retainage_rate="0.10", actor="pm")
        c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="accountant")
        with self.assertRaises(PeriodNotOpen):
            c.receivables.record_collection(prime_bill_id=prime["id"], period_id="P1", amount="9000", fee="0", provider_ref="ach_sim_rcv_late", actor="treasury")
        # a background job (provider acceptance) books into the open period, never the closed one
        c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        self.assertEqual([j["period_id"] for j in c.ledger.journals(source_type="payment_intent")], ["P2"])
        self.assertEqual(c.ledger.trial_balance("P1")["journal_count"], p1_journals)
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.bills.ap_open_items()["reconciled"])


# --------------------------------------------------------------------------- #
# Former known defects (now regression tests)                                  #
# --------------------------------------------------------------------------- #

def queued_payment_backup(tc):
    """A live workspace with a released payment whose backup was taken while the intent was
    still queued in the outbox; the live workspace then dispatched it and the provider
    accepted the transfer.  Returns (world, restored copy of the backup)."""
    w = World()
    c = w.c
    bill = w.posted_bill("20000")
    c.approve_and_execute("payment.release", bill["id"], actor_role="treasury", actor="treasury")
    d = tempfile.mkdtemp(prefix="cipher-v1-restore-")
    tc.addCleanup(shutil.rmtree, d, True)
    backup = c.snapshot(os.path.join(d, "backup-queued.sqlite"))
    tc.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
    tc.assertEqual((len(c.provider.transfers), len(c.provider.submissions)), (1, 1))
    restored = Cipher.open_restored(backup, provider=c.provider)
    tc.addCleanup(restored.db.close)
    return w, restored


class VerticalV1KnownDefectTests(unittest.TestCase):
    """Each test asserts the plan's behaviour where a module once fell short.  All of them
    were expected failures; each named defect is now fixed, so they are plain regression
    tests (the class keeps its name so test ids stay stable)."""

    def test_retainage_release_requires_an_accepted_closeout(self):
        """Fixed (bills/service): ``retainage.release`` executed before closeout acceptance;
        plan step 10 releases retainage only on approved closeout evidence."""
        w = World()
        c = w.c
        w.posted_bill("30000")
        self.assertEqual(c.ledger.balance("2050"), D("3000.00"))
        self.assertEqual(c.plugin("field").closeout(w.cid)["status"], "not_started")
        with self.assertRaises(BillError):
            c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", period_id="P1")
        self.assertEqual(c.ledger.balance("2050"), D("3000.00"))
        self.assertEqual(c.ledger.journals(source_type="retainage_release"), [])
        self.assertEqual(c.ricky.propose("retainage.release", actor_role="accountant", context={"commitment_id": w.cid})["decision"], "abstained")

    def test_restored_copy_refuses_record_writes_before_authority_is_claimed(self):
        """Fixed (core db/service): a restored copy without write authority accepted record
        writes (core gate g8.restored_copy_refuses_mutations)."""
        w = World()
        d = tempfile.mkdtemp(prefix="cipher-v1-restore-")
        self.addCleanup(shutil.rmtree, d, True)
        restored = Cipher.open_restored(w.c.snapshot(os.path.join(d, "backup.sqlite")), provider=w.c.provider)
        self.addCleanup(restored.db.close)
        self.assertFalse(restored.db.has_write_authority())
        parties = len(restored.parties())
        with self.assertRaises(WriteAuthorityError):
            restored.add_party(kind="supplier", name="Injected payee (restored copy)", destination="ACH-SIM-INJECTED")
        with self.assertRaises(WriteAuthorityError):
            restored.ledger.post(period_id="P1", description="injected", lines=[{"account": "5000", "debit": "1"}, {"account": "2000", "credit": "1"}],
                                 source_type="injected", source_id="x", source_version="1", posted_by="intruder")
        self.assertEqual(len(restored.parties()), parties)
        self.assertEqual(restored.ledger.journals(source_type="injected"), [])

    def test_restored_copy_cannot_dispatch_a_queued_payment_before_recovery(self):
        """Fixed (payments): an unclaimed restored copy dispatched its queued outbox row to
        the rail again (plan section 6: quarantine external execution after restore)."""
        w, restored = queued_payment_backup(self)
        self.assertFalse(restored.db.has_write_authority())
        with self.assertRaises(ReleaseQuarantined):
            restored.dispatch_payments()
        self.assertEqual(len(w.c.provider.submissions), 1)
        self.assertEqual(restored.payments.list()[0]["status"], "queued")

    def test_older_backup_recovery_never_resubmits_a_queued_payment(self):
        """Fixed (payments): recovery looked up only submitted/outcome-unknown intents, lifted
        the quarantine and the queued intent was submitted a second time (core gate
        g8.older_backup_no_resubmission); plan: reconcile external receipts first."""
        w, restored = queued_payment_backup(self)
        status = claim_restored_copy(restored)
        self.assertTrue(status["release_quarantined"])
        with self.assertRaises(ReleaseQuarantined):
            restored.dispatch_payments()
        outcome = restored.complete_recovery(actor="reconciler")
        self.assertTrue(outcome["quarantine_lifted"], outcome["held"])
        self.assertEqual([(r["status"], r.get("recovered_from")) for r in outcome["results"]], [("accepted", "queued")])
        self.assertEqual(restored.dispatch_payments(), [])
        self.assertEqual((len(w.c.provider.transfers), len(w.c.provider.submissions)), (1, 1))
        self.assertEqual(len(restored.ledger.journals(source_type="payment_intent")), 1)
        self.assertTrue(restored.ledger.trial_balance()["balanced"])

    def test_raw_sql_cannot_unlock_a_locked_period(self):
        """Fixed (core db): a raw UPDATE set a locked period back to open (core gate
        g4.raw_unlock_refused)."""
        w = World()
        c = w.c
        w.posted_bill("20000")
        c.approve_and_execute("close.close_period", "P1", actor_role="controller", period_id="P1")
        c.approve_and_execute("close.lock_period", "P1", actor_role="controller", period_id="P1")
        self.assertEqual(c.ledger.period("P1")["status"], "locked")
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("UPDATE periods SET status='open' WHERE id='P1'")
        self.assertEqual(c.ledger.period("P1")["status"], "locked")

    def test_prime_retainage_is_released_after_final_acceptance(self):
        """Fixed (receivables): no operation released prime retainage receivable (1150), so
        plan step 10 ("complete prime final billing/retainage") could not finish.  The
        approval-bound ``prime_retainage.release`` now invoices it (Dr 1100 / Cr 1150)."""
        w = World()
        c = w.c
        prime = c.receivables.certify(project_id=w.pid, period_id="P1", certified_cumulative="132000", retainage_rate="0.10", actor="pm")
        c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="accountant")
        self.assertEqual(c.ledger.balance("1150"), D("13200.00"))
        res = c.approve_and_execute("prime_retainage.release", w.pid, actor_role="accountant", period_id="P1")
        self.assertEqual((res.result["amount"], res.result["status"]), ("13200.00", "open"))
        self.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])), [("1100", "13200.00", "0.00"), ("1150", "0.00", "13200.00")])
        self.assertEqual(c.ledger.balance("1150"), D("0.00"))
        self.assertEqual(c.ledger.balance("1100"), D("132000.00"))
        with self.assertRaises(ReceivableError):  # nothing is left to release
            c.request_approval("prime_retainage.release", w.pid, actor_role="accountant")
        ar = c.receivables.ar_open_items(w.pid)
        self.assertEqual((ar["subledger_total"], ar["control_balance"], ar["reconciled"]), ("132000.00", "132000.00", True))
        self.assertTrue(c.ledger.trial_balance()["balanced"])


if __name__ == "__main__":
    unittest.main()
