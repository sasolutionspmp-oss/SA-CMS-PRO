"""Forecast v2: versioned approved budgets (budget.revise), full cost to date, estimate to
complete per cost code, the unversioned budget pool, supplier credits and bill reversals,
immutable snapshots, database guards and cross-project isolation."""
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.core.ids import utcnow_iso
from apps.cipher.domain.forecast import (
    FORECAST_GUARDS_SCHEMA_NAME, FORECAST_SCHEMA_NAME, OP_REVISE, UNMAPPED, BudgetAlreadySet, BudgetRevisionStale, ForecastError,
    _version_hash, normalize_cost_code, phase_code_from_memo,
)
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher, RoleNotAuthorized, run_golden_fixture

ENTITY = "S&A Solutions LLC (synthetic)"

# forecast_before_change of the golden fixture before forecast v2 (project_id excluded)
GOLDEN_LEGACY = {
    "billed_gross_to_date": "50000.00", "billed_net_to_date": "45000.00", "budget": "115000.00", "cost_posted_to_date": "45000.00",
    "executed_commitments": "110000.00", "forecast_at_completion": "122000.00", "label": "SHADOW - synthetic prototype, not authoritative",
    "over_budget": True, "paid_to_date": "27000.00", "pending_exposure": "12000.00", "prime_certified_to_date": "0.00",
    "retainage_held": "5000.00", "stored_materials_asset": "5000.00", "variance_to_budget": "-7000.00",
}

INITIAL_LINES = [
    {"cost_code": "XX 10 00", "amount": "65000"},
    {"cost_code": "xx 20 00", "amount": "38000.00"},
    {"cost_code": "XX 30 00", "amount": "2000"},
    {"cost_code": "ADM", "amount": "300"},
]


def legacy(f: dict) -> dict:
    return {k: f[k] for k in GOLDEN_LEGACY}


def row(f: dict, code: str) -> dict:
    """A cost-code row without its cost-by-type breakdown."""
    return {k: v for k, v in f["by_cost_code"][code].items() if k != "cost_to_date_by_type"}


def assert_rollup(test: unittest.TestCase, f: dict) -> None:
    """Per-code figures add up to the project totals and each row is internally consistent."""
    codes = list(f["by_cost_code"].values())
    tally = lambda key: sum((Decimal(v[key]) for v in codes), Decimal("0"))
    test.assertEqual(tally("fac"), Decimal(f["fac_v2"]))
    test.assertEqual(tally("etc"), Decimal(f["etc_total"]))
    test.assertEqual(tally("cost_to_date"), Decimal(f["cost_to_date_by_type"]["total"]))
    test.assertEqual(tally("uncommitted_budget"), Decimal(f["uncommitted_budget"]))
    test.assertEqual(tally("variance_to_budget"), Decimal(f["variance_to_budget_v2"]))
    test.assertEqual(tally("budget"), Decimal(f["budget"]))
    test.assertEqual(tally("committed_remaining"), Decimal(f["committed_remaining"]))
    for kind in ("subcontract", "labor", "reimbursable"):
        test.assertEqual(sum((Decimal(v["cost_to_date_by_type"][kind]) for v in codes), Decimal("0")), Decimal(f["cost_to_date_by_type"][kind]))
    for v in codes:
        test.assertEqual(Decimal(v["fac"]), Decimal(v["cost_to_date"]) + Decimal(v["etc"]) + Decimal(v["pending_exposure"]))
        test.assertEqual(Decimal(v["variance_to_budget"]), Decimal(v["budget"]) - Decimal(v["fac"]))
        test.assertEqual(Decimal(v["uncommitted_budget"]), Decimal(v["budget"]) - Decimal(v["committed"]))
        test.assertGreaterEqual(Decimal(v["etc"]), Decimal(v["committed_remaining"]))
    test.assertEqual(Decimal(f["unbudgeted_fac"]), sum((Decimal(v["fac"]) for v in codes if v["budget_source"] == "none"), Decimal("0")))


class World:
    """One workspace: a verified supplier, a customer, an employee with a labor rate,
    closed period P0 (September 2026) and open period P1 (October 2026)."""

    def __init__(self, path: str = ":memory:"):
        self.c = c = Cipher(path)
        self.supplier = c.add_party(kind="supplier", name="Synthetic Sheet Pile Subcontractor", destination="ACH-SIM-FC-1")
        c.verify_destination(self.supplier["id"], destination="ACH-SIM-FC-1", verified_by="owner")
        self.customer = c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.emp = c.add_party(kind="employee", name="Synthetic Design Engineer", destination="ACH-SIM-FC-EMP")
        c.verify_destination(self.emp["id"], destination="ACH-SIM-FC-EMP", verified_by="owner")
        c.open_period("P0", "September 2026", "2026-09-01", "2026-09-30")
        c.open_period("P1", "October 2026", "2026-10-01", "2026-10-31")
        c.close_period("P0")
        self.lab = c.plugin("labor")
        self.reimb = c.plugin("reimbursement")
        self.lab.set_rate(self.emp["id"], "2026-10-01", "50.00", "120.00", actor="owner")
        self.receipts = 0

    def project(self, name: str = "Synthetic cofferdam and dewatering", budget: str = "100000") -> str:
        return self.c.create_project(name=name, entity=ENTITY, budget=budget, customer_id=self.customer["id"])["id"]

    def commitment(self, pid: str, lines: list[tuple[str, str, str]]) -> dict:
        cmt = self.c.commitments.create(
            project_id=pid, supplier_id=self.supplier["id"], title="Subcontract - sheet piling and dewatering",
            sov_lines=[{"description": d, "amount": a, "cost_code": cc} for d, a, cc in lines], retainage_rate="0.10", actor="pm")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        return self.c.commitments.get(cmt["id"])

    def bill(self, cmt: dict, installed: list[tuple[str, str]]) -> dict:
        b = self.c.bills.certify(commitment_id=cmt["id"], period_id="P1",
                                 installed=[{"sov_line_id": sid, "cumulative_installed": amt} for sid, amt in installed], actor="pm")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        return self.c.bills.get(b["id"])

    def credit_note(self, bill: dict, amount: str, reason: str = "Backcharge for damaged sheet piles") -> dict:
        """A supplier credit note on a posted bill, on its own evidence, through bill.credit_note."""
        self.receipts += 1
        doc = self.c.evidence.register_document(project_id=bill["project_id"], kind="supplier_credit_note", title=f"Supplier credit {self.receipts}", actor="pm")
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic supplier credit note {self.receipts} (forecast v2)".encode(),
                                           note="credit", actor="pm")
        note = self.c.bills.prepare_credit_note(bill["id"], amount, reason, rev["content_hash"], "pm")
        self.c.approve_and_execute("bill.credit_note", note["id"], period_id="P1")
        return self.c.bills.credit_note(note["id"])

    def phase(self, pid: str, code: str) -> dict:
        return self.lab.add_phase(pid, code, f"Phase {code}", "100", "6000.00", True, actor="pm")

    def timesheet(self, pid: str, entries: list[tuple[dict, str, str]]) -> dict:
        for phase, day, hours in entries:
            self.lab.log_time(self.emp["id"], pid, phase["id"], day, hours, "", actor="emp")
        ts = self.lab.submit_timesheet(self.emp["id"], "P1", actor="emp")
        return self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1").result

    def reimbursement(self, pid: str, amount: str) -> dict:
        self.receipts += 1
        claim = self.reimb.submit_claim(project_id=pid, employee_id=self.emp["id"], description="Pump hire receipts", amount=amount,
                                        receipt_hash=f"fc-receipt-{self.receipts}", actor="emp")
        return self.c.approve_and_execute("reimbursement.approve", claim["id"], period_id="P1").result

    def costed_project(self):
        """Budget v1 105,300 by four codes; subcontract XX 10 00 60,000 + XX 20 00 40,000 with
        20,000 installed on the first line; labor 400 on phase XX 30 00 and 200 on ADM;
        a 120 reimbursable claim; a pending +5,000 change on the XX 20 00 line."""
        pid = self.project()
        self.c.forecast.set_initial_budget(pid, lines=INITIAL_LINES, actor="pm")
        cmt = self.commitment(pid, [("Sheet piling", "60000", "XX 10 00"), ("Dewatering", "40000", "xx  20 00")])
        line1, line2 = (s["id"] for s in cmt["sov"])
        self.bill(cmt, [(line1, "20000")])
        design, adm = self.phase(pid, "xx 30 00"), self.phase(pid, "ADM")
        ts = self.timesheet(pid, [(design, "2026-10-15", "8"), (adm, "2026-10-16", "4")])
        self.reimbursement(pid, "120.00")
        change = self.c.commitments.propose_change(cmt["id"], amount="5000", reason="Additional wellpoints", sov_line_id=line2, actor="pm")
        return pid, cmt, ts, change


def assert_books(test: unittest.TestCase, c: Cipher, *project_ids: str) -> None:
    test.assertTrue(c.ledger.trial_balance()["balanced"])
    test.assertTrue(c.audit.verify_chain()["ok"])
    test.assertTrue(c.forecast.verify()["ok"], c.forecast.verify()["problems"])
    for pid in project_ids:
        test.assertTrue(c.bills.ap_open_items(pid)["reconciled"])
    test.assertTrue(c.bills.ap_open_items()["reconciled"])


def golden_first_half(c: Cipher) -> tuple[str, dict]:
    """The golden fixture's steps up to its forecast_before_change (no prime billing)."""
    owner = "owner"
    supplier = c.add_party(kind="supplier", name="Synthetic Subcontractor A", destination="ACH-SIM-0001")
    c.verify_destination(supplier["id"], destination="ACH-SIM-0001", verified_by="owner")
    customer = c.add_party(kind="customer", name="Synthetic Owner Agency")
    project = c.create_project(name="Synthetic WWTP upgrade", entity=ENTITY, budget="115000", customer_id=customer["id"])
    c.open_period("2026-10", "October 2026", "2026-10-01", "2026-10-31")
    drawing = c.evidence.register_document(project_id=project["id"], kind="drawing", title="Drawing A", actor=owner)
    rev1 = c.evidence.add_revision(document_id=drawing["id"], content=b"drawing A rev 1 (synthetic, forecast v2)", note="issued for pricing", actor=owner)
    estimate = c.estimates.create(project_id=project["id"], document_revision_id=rev1["id"], lines=[
        {"description": "Site piping", "quantity": "1", "unit": "LS", "unit_price": "60000"},
        {"description": "Pump station", "quantity": "1", "unit": "LS", "unit_price": "40000"},
    ], actor=owner)
    c.approve_and_execute("estimate.approve", estimate["id"])
    cmt = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Subcontract - site piping and pump station",
                               sov_lines=[{"description": "Site piping", "amount": "60000"}, {"description": "Pump station", "amount": "40000"}],
                               retainage_rate="0.10", estimate_id=estimate["id"], actor=owner)
    c.approve_and_execute("commitment.execute", cmt["id"])
    line1 = c.commitments.get(cmt["id"])["sov"][0]["id"]
    change = c.commitments.propose_change(cmt["id"], amount="10000", reason="Drawing B scope addition", sov_line_id=line1, actor=owner)
    c.approve_and_execute("change.execute", change["id"])
    ev1 = c.evidence.register_document(project_id=project["id"], kind="stored_material_evidence", title="DI pipe evidence", actor=owner)
    ev1r = c.evidence.add_revision(document_id=ev1["id"], content=b"synthetic stored-material evidence: DI pipe (forecast v2)", note="title", actor=owner)
    lot1 = c.bills.add_stored_material(commitment_id=cmt["id"], sov_line_id=line1, description="Ductile iron pipe, on site", eligible_amount="10000",
                                       evidence_hash=ev1r["content_hash"], location="laydown yard", actor=owner)
    bill1 = c.bills.certify(commitment_id=cmt["id"], period_id="2026-10", installed=[{"sov_line_id": line1, "cumulative_installed": "20000"}], actor=owner)
    approve_and_post_bill(c, bill1["id"], approver="owner", approver_role="owner", poster="accountant")
    ap = c.request_approval("payment.release", bill1["id"], actor_role="treasury", requested_by="owner")
    c.approve(ap["id"], approver="owner")
    first = c.execute(ap["id"], actor="treasury")
    c.provider.mode = "timeout_after_accept"
    c.dispatch_payments()
    c.provider.mode = "accept"
    c.reconcile_payments()
    intent = c.payments.get(first.result["intent"])
    c.payments.ingest_event(c.provider.settle(intent["logical_op_id"]), actor="webhook")
    ev2 = c.evidence.register_document(project_id=project["id"], kind="stored_material_evidence", title="Valve evidence", actor=owner)
    ev2r = c.evidence.add_revision(document_id=ev2["id"], content=b"synthetic stored-material evidence: valves (forecast v2)", note="title", actor=owner)
    c.bills.add_stored_material(commitment_id=cmt["id"], sov_line_id=line1, description="Valves, on site", eligible_amount="5000",
                                evidence_hash=ev2r["content_hash"], location="laydown yard", actor=owner)
    bill2 = c.bills.certify(commitment_id=cmt["id"], period_id="2026-10", installed=[{"sov_line_id": line1, "cumulative_installed": "45000"}],
                            transfers=[{"lot_id": lot1["id"], "amount": "10000"}], actor=owner)
    approve_and_post_bill(c, bill2["id"], approver="owner", approver_role="owner", poster="accountant")
    c.commitments.propose_change(cmt["id"], amount="12000", reason="Pending alternative - not executed", sov_line_id=line1, actor=owner)
    return project["id"], c.forecast.project(project["id"])


# --------------------------------------------------------------------------- #
# 1. golden fixture compatibility                                              #
# --------------------------------------------------------------------------- #

class GoldenCompatibilityTests(unittest.TestCase):
    def test_legacy_keys_unchanged_and_v2_keys_added(self):
        c = Cipher()
        pid, f = golden_first_half(c)
        self.assertEqual(legacy(f), GOLDEN_LEGACY)
        self.assertEqual(f["project_id"], pid)
        # v2: no budget version yet, and the SOV lines carry no cost code: the whole project
        # budget is the unallocated pool on UNMAPPED
        self.assertEqual((f["budget_version"], f["budget_basis"]), (None, "project_budget"))
        self.assertEqual(f["cost_to_date_by_type"], {"subcontract": "45000.00", "labor": "0.00", "reimbursable": "0.00", "total": "45000.00"})
        self.assertEqual((f["committed_remaining"], f["etc_total"], f["fac_v2"], f["uncommitted_budget"], f["variance_to_budget_v2"], f["over_budget_v2"],
                          f["unbudgeted_fac"]),
                         ("65000.00", "70000.00", "127000.00", "5000.00", "-12000.00", True, "0.00"))
        self.assertEqual(f["by_cost_code"], {UNMAPPED: {
            "budget": "115000.00", "budget_source": "project_budget", "committed": "110000.00", "uncommitted_budget": "5000.00",
            "certified_to_date": "45000.00", "committed_remaining": "65000.00",
            "cost_to_date_by_type": {"subcontract": "45000.00", "labor": "0.00", "reimbursable": "0.00"},
            "cost_to_date": "45000.00", "etc": "70000.00", "pending_exposure": "12000.00", "fac": "127000.00", "variance_to_budget": "-12000.00",
        }})
        self.assertEqual(f["residuals"], {"subcontract_cost_not_on_sov_lines": "0.00", "subcontract_bill_credits_and_reversals": "0.00",
                                          "commitments_not_on_sov_lines": "0.00"})
        self.assertEqual(f["cost_to_date_by_type"]["subcontract"], f["cost_posted_to_date"])
        assert_rollup(self, f)
        assert_books(self, c, pid)

    def test_full_golden_fixture_forecast_keys(self):
        c = Cipher()
        r = run_golden_fixture(c)
        self.assertEqual(legacy(r["forecast_before_change"]), GOLDEN_LEGACY)
        self.assertEqual(r["forecast_before_change"]["fac_v2"], "127000.00")
        # after the fixture executes the 12,000 alternative and bills the customer
        f = c.forecast.project(r["project_id"])
        self.assertEqual((f["budget"], f["executed_commitments"], f["pending_exposure"], f["forecast_at_completion"], f["variance_to_budget"],
                          f["prime_certified_to_date"], f["cost_posted_to_date"]),
                         ("115000.00", "122000.00", "0.00", "122000.00", "-7000.00", "60000.00", "45000.00"))
        self.assertEqual((f["committed_remaining"], f["etc_total"], f["fac_v2"], f["uncommitted_budget"]), ("77000.00", "77000.00", "122000.00", "-7000.00"))
        self.assertTrue(c.audit.verify_chain()["ok"] and c.ledger.trial_balance()["balanced"])


# --------------------------------------------------------------------------- #
# 2. cost to date, ETC and the cost-code rollup                                #
# --------------------------------------------------------------------------- #

class CostToDateTests(unittest.TestCase):
    def test_full_cost_to_date_and_per_code_etc(self):
        w = World()
        c = w.c
        pid, cmt, ts, change = w.costed_project()
        f = c.forecast.project(pid)
        self.assertEqual(f["cost_to_date_by_type"], {"subcontract": "20000.00", "labor": "600.00", "reimbursable": "120.00", "total": "20720.00"})
        # the totals are the ledger's project activity
        self.assertEqual(f["cost_to_date_by_type"]["labor"], f"{c.ledger.balance('5300', project_id=pid):f}")
        self.assertEqual(f["cost_to_date_by_type"]["reimbursable"], f"{c.ledger.balance('5100', project_id=pid):f}")
        self.assertEqual(f["cost_to_date_by_type"]["subcontract"], f["cost_posted_to_date"])
        self.assertEqual(list(f["by_cost_code"]), ["ADM", "XX 10 00", "XX 20 00", "XX 30 00", UNMAPPED])
        self.assertEqual(row(f, "XX 10 00"), {"budget": "65000.00", "budget_source": "approved_version", "committed": "60000.00", "uncommitted_budget": "5000.00",
                                              "certified_to_date": "20000.00", "committed_remaining": "40000.00", "cost_to_date": "20000.00", "etc": "45000.00",
                                              "pending_exposure": "0.00", "fac": "65000.00", "variance_to_budget": "0.00"})
        # committed remaining (40,000) exceeds the remaining budget (38,000): it drives the ETC
        self.assertEqual(row(f, "XX 20 00"), {"budget": "38000.00", "budget_source": "approved_version", "committed": "40000.00", "uncommitted_budget": "-2000.00",
                                              "certified_to_date": "0.00", "committed_remaining": "40000.00", "cost_to_date": "0.00", "etc": "40000.00",
                                              "pending_exposure": "5000.00", "fac": "45000.00", "variance_to_budget": "-7000.00"})
        self.assertEqual(f["by_cost_code"]["XX 30 00"]["cost_to_date_by_type"], {"subcontract": "0.00", "labor": "400.00", "reimbursable": "0.00"})
        self.assertEqual((f["by_cost_code"]["XX 30 00"]["etc"], f["by_cost_code"]["XX 30 00"]["fac"]), ("1600.00", "2000.00"))
        self.assertEqual((f["by_cost_code"]["ADM"]["cost_to_date"], f["by_cost_code"]["ADM"]["etc"], f["by_cost_code"]["ADM"]["fac"]), ("200.00", "100.00", "300.00"))
        # the reimbursable claim carries no cost code; an unbudgeted overrun has no ETC
        self.assertEqual(row(f, UNMAPPED), {"budget": "0.00", "budget_source": "none", "committed": "0.00", "uncommitted_budget": "0.00",
                                            "certified_to_date": "0.00", "committed_remaining": "0.00", "cost_to_date": "120.00", "etc": "0.00",
                                            "pending_exposure": "0.00", "fac": "120.00", "variance_to_budget": "-120.00"})
        self.assertEqual((f["budget"], f["budget_version"], f["budget_basis"], f["committed_remaining"], f["etc_total"], f["fac_v2"],
                          f["variance_to_budget_v2"], f["over_budget_v2"], f["uncommitted_budget"], f["unbudgeted_fac"]),
                         ("105300.00", 1, "approved_version", "80000.00", "86700.00", "112420.00", "-7120.00", True, "5300.00", "120.00"))
        self.assertEqual(f["residuals"], {"subcontract_cost_not_on_sov_lines": "0.00", "subcontract_bill_credits_and_reversals": "0.00",
                                          "commitments_not_on_sov_lines": "0.00"})
        # per-code figures add up to the totals
        assert_rollup(self, f)
        # legacy figures keep their meaning: commitments plus pending changes against the current budget
        self.assertEqual((f["executed_commitments"], f["pending_exposure"], f["forecast_at_completion"], f["variance_to_budget"], f["over_budget"],
                          f["billed_gross_to_date"], f["billed_net_to_date"], f["retainage_held"], f["paid_to_date"]),
                         ("100000.00", "5000.00", "105000.00", "300.00", False, "20000.00", "18000.00", "2000.00", "0.00"))
        assert_books(self, c, pid)

    def test_labor_reversal_follows_the_phase_codes(self):
        w = World()
        c = w.c
        pid, cmt, ts, change = w.costed_project()
        rev = c.ledger.reverse(ts["journal_id"], period_id="P1", posted_by="controller", reason="timesheet charged to the wrong project")
        self.assertEqual(rev["reversal_of"], ts["journal_id"])
        f = c.forecast.project(pid)
        self.assertEqual(f["cost_to_date_by_type"]["labor"], "0.00")
        self.assertEqual({code: f["by_cost_code"][code]["cost_to_date_by_type"]["labor"] for code in ("ADM", "XX 30 00")}, {"ADM": "0.00", "XX 30 00": "0.00"})
        self.assertEqual((f["by_cost_code"]["XX 30 00"]["etc"], f["by_cost_code"]["ADM"]["etc"]), ("2000.00", "300.00"))
        self.assertEqual(f["by_cost_code"][UNMAPPED]["cost_to_date_by_type"]["labor"], "0.00")
        assert_books(self, c, pid)

    def test_labor_cost_without_a_phase_is_unmapped(self):
        w = World()
        c = w.c
        pid, cmt, ts, change = w.costed_project()
        c.ledger.post(period_id="P1", description="Labor accrual adjustment (synthetic)", source_type="manual_adjustment", source_id="adj-1",
                      source_version="1", posted_by="controller", lines=[
                          {"account": "5300", "debit": "75.00", "project_id": pid, "memo": "labor phase XX 30 00: 1.50 h (timesheet none)"},
                          {"account": "3000", "credit": "75.00", "memo": "synthetic adjustment"},
                      ])
        f = c.forecast.project(pid)
        self.assertEqual(f["cost_to_date_by_type"]["labor"], "675.00")
        self.assertEqual(f["by_cost_code"][UNMAPPED]["cost_to_date_by_type"], {"subcontract": "0.00", "labor": "75.00", "reimbursable": "120.00"})
        self.assertEqual(f["by_cost_code"]["XX 30 00"]["cost_to_date_by_type"]["labor"], "400.00")  # a memo on another source maps nothing
        assert_books(self, c, pid)

    def test_subcontract_cost_off_the_sov_is_a_residual_and_stored_material_stays_remaining(self):
        w = World()
        c = w.c
        pid = w.project(budget="50000")
        cmt = w.commitment(pid, [("Wellpoints", "30000", "XX 40 00")])
        line = cmt["sov"][0]["id"]
        ev = c.evidence.register_document(project_id=pid, kind="stored_material_evidence", title="Header pipe evidence", actor="pm")
        evr = c.evidence.add_revision(document_id=ev["id"], content=b"synthetic stored-material evidence: header pipe (forecast v2)", note="title", actor="pm")
        c.bills.add_stored_material(commitment_id=cmt["id"], sov_line_id=line, description="Header pipe, on site", eligible_amount="4000",
                                    evidence_hash=evr["content_hash"], location="laydown yard", actor="pm")
        w.bill(cmt, [(line, "10000")])
        c.ledger.post(period_id="P1", description="Direct subcontract cost (synthetic)", source_type="manual_adjustment", source_id="adj-2",
                      source_version="1", posted_by="controller", lines=[
                          {"account": "5000", "debit": "250.00", "project_id": pid, "memo": "direct cost"},
                          {"account": "3000", "credit": "250.00", "memo": "synthetic adjustment"},
                      ])
        f = c.forecast.project(pid)
        self.assertEqual((f["cost_posted_to_date"], f["stored_materials_asset"]), ("10250.00", "4000.00"))
        self.assertEqual(f["residuals"]["subcontract_cost_not_on_sov_lines"], "250.00")
        code = f["by_cost_code"]["XX 40 00"]
        # stored material is an asset until installed: it stays in committed remaining
        self.assertEqual((code["certified_to_date"], code["cost_to_date"], code["committed_remaining"], code["etc"]), ("10000.00", "10000.00", "20000.00", "20000.00"))
        self.assertEqual(f["by_cost_code"][UNMAPPED]["cost_to_date"], "250.00")
        # unversioned: the coded commitment draws its forecast (10,000 + 20,000) from the 50,000
        # project budget and the rest stays unallocated on UNMAPPED, so nothing is counted twice
        self.assertEqual((code["budget"], code["budget_source"], code["uncommitted_budget"], code["fac"]), ("30000.00", "drawn_from_project_budget", "0.00", "30000.00"))
        self.assertEqual(row(f, UNMAPPED), {"budget": "20000.00", "budget_source": "project_budget", "committed": "0.00", "uncommitted_budget": "20000.00",
                                            "certified_to_date": "0.00", "committed_remaining": "0.00", "cost_to_date": "250.00", "etc": "19750.00",
                                            "pending_exposure": "0.00", "fac": "20000.00", "variance_to_budget": "0.00"})
        self.assertEqual((f["budget_basis"], f["etc_total"], f["fac_v2"], f["variance_to_budget_v2"], f["over_budget_v2"], f["uncommitted_budget"]),
                         ("project_budget", "39750.00", "50000.00", "0.00", False, "20000.00"))
        assert_rollup(self, f)
        assert_books(self, c, pid)

    def test_closed_commitment_has_nothing_remaining(self):
        w = World()
        c = w.c
        pid = w.project(budget="20000")
        c.forecast.set_initial_budget(pid, [{"cost_code": "XX 50 00", "amount": "20000"}], "pm")
        cmt = w.commitment(pid, [("Cofferdam bracing", "12000", "XX 50 00")])
        w.bill(cmt, [(cmt["sov"][0]["id"], "9000")])
        self.assertEqual(c.forecast.project(pid)["by_cost_code"]["XX 50 00"]["committed_remaining"], "3000.00")
        c.commitments.close(cmt["id"], actor="pm")
        code = c.forecast.project(pid)["by_cost_code"]["XX 50 00"]
        self.assertEqual((code["committed"], code["committed_remaining"], code["etc"], code["fac"]), ("12000.00", "0.00", "11000.00", "20000.00"))

    def test_normalization_and_memo_parser(self):
        self.assertEqual(normalize_cost_code("  xx   10\t00 "), "XX 10 00")
        self.assertEqual(normalize_cost_code(None), "")
        self.assertEqual(phase_code_from_memo("labor phase dd: 8.00 h (timesheet lts_1)"), "DD")
        self.assertEqual(phase_code_from_memo("reversal: labor phase XX 30 00: 1.50 h (timesheet lts_2)"), "XX 30 00")
        self.assertIsNone(phase_code_from_memo("installed work"))
        self.assertIsNone(phase_code_from_memo("labor phase : 8 h (timesheet x)"))
        self.assertIsNone(phase_code_from_memo(None))


class UnversionedBudgetPoolTests(unittest.TestCase):
    """Until a project is versioned its budget is one pool that every cost code draws on."""

    def coded(self, w: World, pid: str) -> dict:
        cmt = w.commitment(pid, [("Sheet piling", "60000", "XX 10 00"), ("Dewatering", "40000", "XX 20 00")])
        w.bill(cmt, [(cmt["sov"][0]["id"], "20000")])
        return cmt

    def test_coded_commitments_on_an_unversioned_budget_are_not_counted_twice(self):
        w = World()
        c = w.c
        pid = w.project(budget="100000")
        self.coded(w, pid)
        f = c.forecast.project(pid)
        self.assertEqual((f["budget"], f["budget_basis"], f["forecast_at_completion"]), ("100000.00", "project_budget", "100000.00"))
        self.assertEqual((f["committed_remaining"], f["etc_total"], f["fac_v2"], f["variance_to_budget_v2"], f["over_budget_v2"], f["uncommitted_budget"],
                          f["unbudgeted_fac"]),
                         ("80000.00", "80000.00", "100000.00", "0.00", False, "0.00", "0.00"))
        self.assertEqual(row(f, "XX 10 00"), {"budget": "60000.00", "budget_source": "drawn_from_project_budget", "committed": "60000.00",
                                              "uncommitted_budget": "0.00", "certified_to_date": "20000.00", "committed_remaining": "40000.00",
                                              "cost_to_date": "20000.00", "etc": "40000.00", "pending_exposure": "0.00", "fac": "60000.00",
                                              "variance_to_budget": "0.00"})
        self.assertEqual((row(f, "XX 20 00")["budget"], row(f, "XX 20 00")["etc"], row(f, "XX 20 00")["uncommitted_budget"]), ("40000.00", "40000.00", "0.00"))
        self.assertNotIn(UNMAPPED, f["by_cost_code"])  # the pool is fully drawn and nothing else is unmapped
        assert_rollup(self, f)
        # the same project on an approved version of those two codes forecasts the same
        v = w.project(name="Versioned twin", budget="100000")
        c.forecast.set_initial_budget(v, [{"cost_code": "XX 10 00", "amount": "60000"}, {"cost_code": "XX 20 00", "amount": "40000"}], "pm")
        self.coded(w, v)
        fv = c.forecast.project(v)
        self.assertEqual((fv["etc_total"], fv["fac_v2"], fv["over_budget_v2"]), ("80000.00", "100000.00", False))
        self.assertEqual({k: row(fv, k)["fac"] for k in fv["by_cost_code"]}, {k: row(f, k)["fac"] for k in f["by_cost_code"]})
        assert_books(self, c, pid, v)

    def test_the_pool_covers_labor_and_reimbursables_and_overruns_show(self):
        w = World()
        c = w.c
        pid = w.project(budget="100000")
        cmt = self.coded(w, pid)
        design, adm = w.phase(pid, "XX 30 00"), w.phase(pid, "ADM")
        w.timesheet(pid, [(design, "2026-10-15", "8"), (adm, "2026-10-16", "4")])
        w.reimbursement(pid, "120.00")
        f = c.forecast.project(pid)
        # need: ADM 200 + XX 10 00 60,000 + XX 20 00 40,000 + XX 30 00 400 + UNMAPPED 120 = 100,720 against 100,000
        self.assertEqual(f["cost_to_date_by_type"], {"subcontract": "20000.00", "labor": "600.00", "reimbursable": "120.00", "total": "20720.00"})
        self.assertEqual((f["etc_total"], f["fac_v2"], f["variance_to_budget_v2"], f["over_budget_v2"]), ("80000.00", "100720.00", "-720.00", True))
        self.assertEqual({k: (v["budget"], v["budget_source"], v["etc"], v["fac"]) for k, v in f["by_cost_code"].items()}, {
            "ADM": ("200.00", "drawn_from_project_budget", "0.00", "200.00"),
            "XX 10 00": ("60000.00", "drawn_from_project_budget", "40000.00", "60000.00"),
            "XX 20 00": ("39800.00", "drawn_from_project_budget", "40000.00", "40000.00"),  # the pool ran out here
            "XX 30 00": ("0.00", "none", "0.00", "400.00"),
            UNMAPPED: ("0.00", "project_budget", "0.00", "120.00"),
        })
        self.assertEqual(f["unbudgeted_fac"], "400.00")
        assert_rollup(self, f)
        # a larger (still unversioned) budget leaves an unallocated remainder on UNMAPPED
        c.set_budget(pid, "120000")
        f = c.forecast.project(pid)
        self.assertEqual(row(f, UNMAPPED), {"budget": "19400.00", "budget_source": "project_budget", "committed": "0.00", "uncommitted_budget": "19400.00",
                                            "certified_to_date": "0.00", "committed_remaining": "0.00", "cost_to_date": "120.00", "etc": "19280.00",
                                            "pending_exposure": "0.00", "fac": "19400.00", "variance_to_budget": "0.00"})
        self.assertEqual((f["etc_total"], f["fac_v2"], f["variance_to_budget_v2"], f["over_budget_v2"], f["unbudgeted_fac"]),
                         ("99280.00", "120000.00", "0.00", False, "0.00"))
        # pending changes are exposure on top of the forecast
        c.commitments.propose_change(cmt["id"], amount="5000", reason="Additional wellpoints", sov_line_id=cmt["sov"][1]["id"], actor="pm")
        f = c.forecast.project(pid)
        self.assertEqual((f["fac_v2"], f["variance_to_budget_v2"], row(f, "XX 20 00")["pending_exposure"], row(f, "XX 20 00")["variance_to_budget"]),
                         ("125000.00", "-5000.00", "5000.00", "-5000.00"))
        assert_rollup(self, f)
        assert_books(self, c, pid)

    def test_uncoded_commitments_on_a_versioned_budget_are_unbudgeted_until_budgeted(self):
        w = World()
        c = w.c
        pid = w.project(budget="100000")
        c.forecast.set_initial_budget(pid, [{"cost_code": "XX 10 00", "amount": "60000"}, {"cost_code": "XX 20 00", "amount": "40000"}], "pm")
        cmt = w.commitment(pid, [("Sheet piling", "60000", ""), ("Dewatering", "40000", "")])
        w.bill(cmt, [(cmt["sov"][0]["id"], "20000")])
        f = c.forecast.project(pid)
        # the approved lines still forecast their budget; the uncoded commitment maps to none of them
        self.assertEqual((f["fac_v2"], f["over_budget_v2"], f["unbudgeted_fac"]), ("200000.00", True, "100000.00"))
        self.assertEqual((row(f, UNMAPPED)["budget_source"], row(f, UNMAPPED)["fac"], row(f, "XX 10 00")["etc"]), ("none", "100000.00", "60000.00"))
        assert_rollup(self, f)
        # budgeting the uncoded work (UNMAPPED may carry a line) resolves it
        rev = c.forecast.prepare_budget_revision(pid, [{"cost_code": "unmapped", "amount": "100000"}], "Budget follows the uncoded subcontract", "pm")
        c.approve_and_execute(OP_REVISE, rev["id"], actor_role="controller")
        f = c.forecast.project(pid)
        self.assertEqual((f["budget"], f["budget_version"], f["fac_v2"], f["over_budget_v2"], f["unbudgeted_fac"]), ("100000.00", 2, "100000.00", False, "0.00"))
        self.assertEqual((list(f["by_cost_code"]), row(f, UNMAPPED)["budget_source"], row(f, UNMAPPED)["etc"]), ([UNMAPPED], "approved_version", "80000.00"))
        assert_rollup(self, f)
        assert_books(self, c, pid)


class SubcontractCreditTests(unittest.TestCase):
    """5000 credits and reversals follow the bill they belong to; none becomes phantom ETC."""

    def setUp(self):
        self.w = World()
        self.c = self.w.c
        self.pid, self.cmt, self.ts, self.change = self.w.costed_project()
        self.line1, self.line2 = (s["id"] for s in self.cmt["sov"])

    def second_bill(self) -> dict:
        # bill 2 installs 10,000 more on XX 10 00 and 5,000 on XX 20 00
        return self.w.bill(self.c.commitments.get(self.cmt["id"]), [(self.line1, "30000"), (self.line2, "5000")])

    def test_supplier_credit_note_follows_the_bill_codes_and_lowers_the_forecast(self):
        bill2 = self.second_bill()
        before = self.c.forecast.project(self.pid)
        self.assertEqual((before["fac_v2"], row(before, "XX 20 00")["fac"]), ("112420.00", "45000.00"))
        self.w.credit_note(bill2, "300")
        f = self.c.forecast.project(self.pid)
        self.assertEqual((f["cost_posted_to_date"], f["cost_to_date_by_type"]["subcontract"]), ("34700.00", "34700.00"))
        # spread 2:1 like bill 2's installed value; certified installed value is unchanged
        self.assertEqual(row(f, "XX 10 00"), {"budget": "65000.00", "budget_source": "approved_version", "committed": "60000.00", "uncommitted_budget": "5000.00",
                                              "certified_to_date": "30000.00", "committed_remaining": "30000.00", "cost_to_date": "29800.00", "etc": "35200.00",
                                              "pending_exposure": "0.00", "fac": "65000.00", "variance_to_budget": "0.00"})
        self.assertEqual(row(f, "XX 20 00"), {"budget": "38000.00", "budget_source": "approved_version", "committed": "40000.00", "uncommitted_budget": "-2000.00",
                                              "certified_to_date": "5000.00", "committed_remaining": "35000.00", "cost_to_date": "4900.00", "etc": "35000.00",
                                              "pending_exposure": "5000.00", "fac": "44900.00", "variance_to_budget": "-6900.00"})
        # nothing lands on UNMAPPED: no phantom ETC there
        self.assertEqual(row(f, UNMAPPED), row(before, UNMAPPED))
        self.assertEqual(f["residuals"], {"subcontract_cost_not_on_sov_lines": "0.00", "subcontract_bill_credits_and_reversals": "-300.00",
                                          "commitments_not_on_sov_lines": "0.00"})
        # the credit lowers the forecast where the commitment drives it (XX 20 00); XX 10 00 stays on its budget
        self.assertEqual((f["fac_v2"], f["variance_to_budget_v2"]), ("112320.00", "-7020.00"))
        assert_rollup(self, f)
        assert_books(self, self.c, self.pid)

    def test_unattributed_credit_lowers_the_forecast_without_phantom_etc(self):
        self.c.ledger.post(period_id="P1", description="Subcontract cost recovery (synthetic)", source_type="manual_adjustment", source_id="adj-3",
                           source_version="1", posted_by="controller", lines=[
                               {"account": "5000", "credit": "50.00", "project_id": self.pid, "memo": "recovery"},
                               {"account": "3000", "debit": "50.00", "memo": "synthetic adjustment"},
                           ])
        f = self.c.forecast.project(self.pid)
        self.assertEqual((row(f, UNMAPPED)["cost_to_date"], row(f, UNMAPPED)["etc"], row(f, UNMAPPED)["fac"]), ("70.00", "0.00", "70.00"))
        self.assertEqual((f["residuals"]["subcontract_cost_not_on_sov_lines"], f["fac_v2"], f["cost_posted_to_date"]), ("-50.00", "112370.00", "19950.00"))
        assert_rollup(self, f)

    def test_corrected_bill_nets_out_by_code(self):
        before = self.c.forecast.project(self.pid)
        bill2 = self.second_bill()
        self.c.bills.prepare_correction(bill2["id"], "certified against the wrong period (synthetic)", "pm")
        self.c.approve_and_execute("bill.correct", bill2["id"], period_id="P1")
        self.assertEqual(self.c.bills.get(bill2["id"])["status"], "corrected")
        f = self.c.forecast.project(self.pid)
        for code in ("XX 10 00", "XX 20 00", UNMAPPED):
            self.assertEqual(row(f, code), row(before, code), code)
        self.assertEqual((f["fac_v2"], f["cost_posted_to_date"], f["residuals"]["subcontract_bill_credits_and_reversals"]), ("112420.00", "20000.00", "-15000.00"))
        assert_rollup(self, f)
        assert_books(self, self.c, self.pid)

    def test_a_raw_reversal_of_a_bill_journal_stays_on_the_bill_codes(self):
        bill1 = self.c.bills.list(commitment_id=self.cmt["id"])[0]
        self.c.ledger.reverse(bill1["journal_id"], period_id="P1", posted_by="controller", reason="synthetic out-of-band reversal")
        f = self.c.forecast.project(self.pid)
        self.assertEqual((row(f, "XX 10 00")["cost_to_date"], row(f, "XX 10 00")["certified_to_date"], row(f, "XX 10 00")["etc"]), ("0.00", "20000.00", "65000.00"))
        self.assertEqual((row(f, UNMAPPED)["cost_to_date"], row(f, UNMAPPED)["etc"]), ("120.00", "0.00"))
        self.assertEqual(f["residuals"]["subcontract_bill_credits_and_reversals"], "-20000.00")
        assert_rollup(self, f)
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])


# --------------------------------------------------------------------------- #
# 3. versioned budgets and budget.revise                                       #
# --------------------------------------------------------------------------- #

class BudgetVersionTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c
        self.pid = self.w.project(budget="100000")
        self.fc = self.c.forecast

    def initial(self):
        return self.fc.set_initial_budget(self.pid, lines=INITIAL_LINES, actor="pm")

    def revise(self, lines, reason="Scope transfer between cost codes"):
        return self.fc.prepare_budget_revision(self.pid, lines, reason, "pm")

    def test_fallback_until_the_initial_version(self):
        self.assertEqual((self.fc.project(self.pid)["budget"], self.fc.project(self.pid)["budget_version"]), ("100000.00", None))
        self.c.set_budget(self.pid, "110000")  # unversioned: the legacy column is still the budget
        self.assertEqual(self.fc.project(self.pid)["budget"], "110000.00")
        v1 = self.initial()
        self.assertEqual((v1["version"], v1["total"], v1["legacy_budget"], v1["approval_id"], v1["previous_hash"]), (1, "105300.00", "110000.00", None, None))
        self.assertEqual(v1["lines"], [{"cost_code": "ADM", "amount": "300.00"}, {"cost_code": "XX 10 00", "amount": "65000.00"},
                                       {"cost_code": "XX 20 00", "amount": "38000.00"}, {"cost_code": "XX 30 00", "amount": "2000.00"}])
        f = self.fc.project(self.pid)
        self.assertEqual((f["budget"], f["budget_version"], f["budget_version_hash"], f["budget_basis"]), ("105300.00", 1, v1["version_hash"], "approved_version"))
        self.assertEqual(self.c.project(self.pid)["budget"], "105300.00")  # the legacy column follows the approved version
        # once versioned, the legacy column cannot be moved off the approved version
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.set_budget(self.pid, "999999")
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("UPDATE projects SET budget='1.00' WHERE id=?", (self.pid,))
        self.assertEqual(self.fc.project(self.pid)["budget"], "105300.00")
        self.assertEqual([e["action"] for e in self.c.audit.entries(entity_type="project", entity_id=self.pid)][-1], "budget.initial_set")

    def test_initial_budget_only_once(self):
        self.initial()
        with self.assertRaises(BudgetAlreadySet):
            self.fc.set_initial_budget(self.pid, [{"cost_code": "XX 10 00", "amount": "1"}], "pm")
        self.assertEqual(len(self.fc.budget_versions(self.pid)), 1)
        with self.assertRaises(ForecastError):  # a revision needs an initial version first
            self.fc.prepare_budget_revision(self.w.project(name="Second synthetic project"), INITIAL_LINES, "no budget yet", "pm")

    def test_invalid_budget_input_is_refused(self):
        bad = [
            [], "XX 10 00", {"cost_code": "XX 10 00", "amount": "1"}, [["XX 10 00", "1"]],
            [{"cost_code": "XX 10 00"}], [{"amount": "1"}], [{"cost_code": "XX 10 00", "amount": "1", "note": "x"}],
            [{"cost_code": "XX 10 00", "amount": 1.5}], [{"cost_code": "XX 10 00", "amount": "100.505"}], [{"cost_code": "XX 10 00", "amount": "-1"}],
            [{"cost_code": "XX 10 00", "amount": "NaN"}], [{"cost_code": "XX 10 00", "amount": "1e20"}], [{"cost_code": "XX 10 00", "amount": "0"}],
            [{"cost_code": "  ", "amount": "1"}], [{"cost_code": 1000, "amount": "1"}],
            [{"cost_code": "X" * 65, "amount": "1"}], [{"cost_code": "XX\x0010", "amount": "1"}],
            [{"cost_code": "XX 10 00", "amount": "1"}, {"cost_code": "xx  10 00", "amount": "2"}],
            [{"cost_code": "XX 10 00", "amount": "-0"}], [{"cost_code": "UNMAPPED", "amount": "1"}, {"cost_code": " unmapped ", "amount": "1"}],
        ]
        for lines in bad:
            with self.subTest(lines=lines), self.assertRaises(ForecastError):
                self.fc.set_initial_budget(self.pid, lines, "pm")
        with self.assertRaises(ForecastError):
            self.fc.set_initial_budget(self.pid, INITIAL_LINES, "  ")
        with self.assertRaises(ForecastError):
            self.fc.set_initial_budget("prj_missing", INITIAL_LINES, "pm")
        self.assertEqual(self.fc.budget_versions(self.pid), [])
        self.initial()
        for lines, reason in ((INITIAL_LINES, "no change"), ([{"cost_code": "XX 10 00", "amount": "1"}], " ")):
            with self.subTest(reason=reason), self.assertRaises(ForecastError):
                self.revise(lines, reason)
        with self.assertRaises(ForecastError):
            self.fc.manifest_for(OP_REVISE, "bdr_missing", actor_role="pm")
        with self.assertRaises(KeyError):  # unchanged legacy behavior of project()
            self.fc.project("prj_missing")

    def test_revision_through_approval(self):
        v1 = self.initial()
        lines = [{"cost_code": "XX 10 00", "amount": "60000"}, {"cost_code": "XX 20 00", "amount": "45000"}, {"cost_code": "XX 30 00", "amount": "2000"}]
        rev = self.revise(lines)
        self.assertEqual((rev["status"], rev["base_version"], rev["total"]), ("pending", 1, "107000.00"))
        self.assertEqual(self.fc.project(self.pid)["budget"], "105300.00")  # a draft changes nothing
        with self.assertRaises(ForecastError):  # the same lines cannot be drafted twice
            self.revise(lines, "Same lines again")
        ap = self.c.request_approval(OP_REVISE, rev["id"], actor_role="pm", requested_by="pm")
        m = ap["manifest"]
        self.assertEqual((m["subject"], m["entity"], m["currency"]), ({"type": "budget_revision", "id": rev["id"]}, ENTITY, "USD"))
        self.assertEqual(m["amounts"], {"new_total": "107000.00", "current_total": "105300.00", "change": "1700.00"})
        b = m["bindings"]
        self.assertEqual((b["current_version"], b["current_version_hash"], b["new_version"], b["new_lines_hash"], b["new_total"], b["reason"], b["project_id"]),
                         (1, v1["version_hash"], 2, rev["lines_hash"], "107000.00", "Scope transfer between cost codes", self.pid))
        self.assertEqual(b["new_lines"], rev["lines"])
        with self.assertRaises(RoleNotAuthorized):
            self.c.approve(ap["id"], approver="estimator", approver_role="estimator")
        self.c.approve(ap["id"], approver="controller", approver_role="controller")
        res = self.c.execute(ap["id"], actor="pm")
        self.assertEqual((res.result["budget_version"], res.result["total"], res.result["previous_total"], res.result["change"], res.result["superseded_revisions"]),
                         (2, "107000.00", "105300.00", "1700.00", []))
        v2 = self.fc.budget_version(self.pid)
        self.assertEqual((v2["version"], v2["approval_id"], v2["revision_id"], v2["previous_hash"], v2["effective_period_id"]), (2, ap["id"], rev["id"], v1["version_hash"], None))
        self.assertEqual(self.fc.revision(rev["id"])["status"], "executed")
        f = self.fc.project(self.pid)
        self.assertEqual((f["budget"], f["budget_version"], self.c.project(self.pid)["budget"]), ("107000.00", 2, "107000.00"))
        self.assertNotIn("ADM", f["by_cost_code"])  # dropped by the revision and carrying nothing
        self.assertEqual(self.fc.budget_version(self.pid, 1)["total"], "105300.00")  # history is kept
        # the same approval never takes effect twice
        self.assertTrue(self.c.execute(ap["id"], actor="pm").replayed)
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="pm", op_id="another-attempt")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "consumed")
        self.assertEqual(len(self.fc.budget_versions(self.pid)), 2)
        assert_books(self, self.c, self.pid)

    def test_roles_without_budget_authority_are_refused(self):
        self.initial()
        rev = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}])
        for role in ("accountant", "viewer", "estimator", "treasury", "unknown"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorized):
                self.c.request_approval(OP_REVISE, rev["id"], actor_role=role)
        self.assertEqual(self.c.ricky.propose(OP_REVISE, actor_role="estimator", context={"revision_id": rev["id"]})["decision"], "abstained")
        proposal = self.c.ricky.propose(OP_REVISE, actor_role="pm", context={"revision_id": rev["id"]})
        self.assertEqual((proposal["decision"], proposal["manifest"]["operation"]), ("proposed", OP_REVISE))
        self.assertEqual(self.fc.project(self.pid)["budget_version"], 1)

    def test_approval_is_stale_when_another_revision_lands_first(self):
        self.initial()
        a = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}, {"cost_code": "XX 20 00", "amount": "40000"}], "Revision A")
        b = self.revise([{"cost_code": "XX 10 00", "amount": "66000"}, {"cost_code": "XX 20 00", "amount": "40000"}], "Revision B")
        ap_a = self.c.request_approval(OP_REVISE, a["id"], actor_role="pm")
        ap_b = self.c.request_approval(OP_REVISE, b["id"], actor_role="pm")
        self.c.approve(ap_a["id"])
        self.c.approve(ap_b["id"])
        res = self.c.execute(ap_b["id"], actor="pm")
        self.assertEqual((res.result["budget_version"], res.result["superseded_revisions"]), (2, [a["id"]]))
        self.assertEqual(self.fc.revision(a["id"])["status"], "superseded")
        self.assertEqual(self.c.approvals.get(ap_a["id"])["status"], "invalidated")
        with self.assertRaises(StaleApprovalError) as ctx:
            self.c.execute(ap_a["id"], actor="pm")
        self.assertIsInstance(ctx.exception, BudgetRevisionStale)
        with self.assertRaises(BudgetRevisionStale):  # no fresh approval for a superseded draft either
            self.c.request_approval(OP_REVISE, a["id"], actor_role="pm")
        f = self.fc.project(self.pid)
        self.assertEqual((f["budget"], f["budget_version"], len(self.fc.budget_versions(self.pid))), ("106000.00", 2, 2))
        # a new draft against version 2 is fine
        c3 = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}, {"cost_code": "XX 20 00", "amount": "40000"}], "Revision A, re-prepared")
        self.assertEqual(c3["base_version"], 2)
        self.c.approve_and_execute(OP_REVISE, c3["id"], actor_role="controller")
        self.assertEqual(self.fc.project(self.pid)["budget"], "110000.00")
        assert_books(self, self.c, self.pid)

    def test_canceled_draft_invalidates_its_approval(self):
        self.initial()
        rev = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}])
        ap = self.c.request_approval(OP_REVISE, rev["id"], actor_role="pm")
        self.c.approve(ap["id"])
        self.fc.cancel_budget_revision(rev["id"], actor="pm", reason="superseded by the field estimate")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], actor="pm")
        with self.assertRaises(ForecastError):
            self.fc.cancel_budget_revision(rev["id"], actor="pm", reason="again")
        self.assertEqual(self.fc.project(self.pid)["budget_version"], 1)

    def test_closed_period_refused_then_open_period_recorded(self):
        self.initial()
        rev = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}])
        ap = self.c.request_approval(OP_REVISE, rev["id"], actor_role="pm")
        self.c.approve(ap["id"])
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], actor="pm", period_id="P0")
        self.assertEqual((self.c.approvals.get(ap["id"])["status"], self.fc.project(self.pid)["budget_version"]), ("granted", 1))
        res = self.c.execute(ap["id"], actor="pm", period_id="P1")
        self.assertEqual((res.result["effective_period_id"], self.fc.budget_version(self.pid)["effective_period_id"]), ("P1", "P1"))

    def test_no_version_without_a_consumed_approval(self):
        v1 = self.initial()
        rev = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}])
        ap = self.c.request_approval(OP_REVISE, rev["id"], actor_role="pm")
        manifest = self.fc.manifest_for(OP_REVISE, rev["id"], actor_role="pm")
        for approval_id in (None, "", "apr_missing", ap["id"]):  # the last is pending, not consumed
            with self.subTest(approval_id=approval_id), self.assertRaises(ForecastError):
                self.fc.apply(OP_REVISE, rev["id"], approval_id=approval_id, manifest=manifest, actor="pm", period_id=None)
        with self.assertRaises(sqlite3.DatabaseError):  # raw SQL cannot add a version either
            self.c.db.execute(
                """INSERT INTO budget_versions (id, project_id, version, total, lines_json, lines_hash, reason, approval_id, revision_id, previous_hash,
                       version_hash, created_by, created_at) VALUES ('bud_raw', ?, 2, '70000.00', ?, ?, ?, ?, ?, ?, 'x', 'intruder', 't')""",
                (self.pid, '[{"amount":"70000.00","cost_code":"XX 10 00"}]', rev["lines_hash"], rev["reason"], ap["id"], rev["id"], v1["version_hash"]))
        self.assertEqual(len(self.fc.budget_versions(self.pid)), 1)

    def test_versions_and_drafts_are_immutable(self):
        v1 = self.initial()
        rev = self.revise([{"cost_code": "XX 10 00", "amount": "70000"}])
        db = self.c.db
        for sql, params in (
            ("UPDATE budget_versions SET total='1.00' WHERE id=?", (v1["id"],)),
            ("DELETE FROM budget_versions WHERE id=?", (v1["id"],)),
            ("INSERT OR REPLACE INTO budget_versions (id, project_id, version, total, lines_json, lines_hash, reason, version_hash, created_by, created_at) "
             "VALUES (?, ?, 1, '1.00', '[]', 'h', 'r', 'h', 'x', 't')", (v1["id"], self.pid)),
            ("UPDATE budget_revisions SET total='1.00' WHERE id=?", (rev["id"],)),
            ("UPDATE budget_revisions SET status='executed' WHERE id=?", (rev["id"],)),
            ("DELETE FROM budget_revisions WHERE id=?", (rev["id"],)),
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql, params)
        self.assertEqual(self.fc.budget_version(self.pid)["total"], "105300.00")
        self.assertEqual(self.fc.revision(rev["id"])["status"], "pending")
        self.assertTrue(self.fc.verify()["ok"])

    def test_negative_zero_is_zero_so_an_unchanged_budget_is_not_a_revision(self):
        v1 = self.fc.set_initial_budget(self.pid, [{"cost_code": "A", "amount": "100"}, {"cost_code": "B", "amount": "-0"}], "pm")
        self.assertEqual(v1["lines"], [{"cost_code": "A", "amount": "100.00"}, {"cost_code": "B", "amount": "0.00"}])
        for zero in ("-0", "-0.00", "0", Decimal("-0")):
            with self.subTest(zero=zero), self.assertRaisesRegex(ForecastError, "nothing to revise"):
                self.revise([{"cost_code": "a", "amount": "100.00"}, {"cost_code": "b", "amount": zero}], "No real change")
        self.assertEqual(self.fc.revisions(self.pid), [])
        rev = self.revise([{"cost_code": "A", "amount": "100"}], "Drop the empty line")  # a real change is still a revision
        self.assertEqual(rev["lines"], [{"cost_code": "A", "amount": "100.00"}])

    def test_versioned_project_is_never_replaced_and_its_budget_column_follows_every_version(self):
        self.initial()
        replace = ("INSERT OR REPLACE INTO projects (id, name, entity, currency, customer_id, budget, created_at) "
                   "SELECT id, name, entity, currency, customer_id, '1.00', created_at FROM projects WHERE id=?")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "versioned"):
            self.c.db.execute(replace, (self.pid,))
        self.assertEqual((self.c.project(self.pid)["budget"], self.fc.project(self.pid)["budget"]), ("105300.00", "105300.00"))
        other = self.w.project(name="Unversioned synthetic project", budget="10")
        self.c.db.execute(replace, (other,))  # an unversioned project is not guarded
        self.assertEqual(self.c.project(other)["budget"], "1.00")
        self.assertTrue(self.fc.verify()["ok"])
        # with the column guard removed (an intruder with DDL), verify still notices the drift
        self.c.db.execute("DROP TRIGGER projects_versioned_budget_guard")
        self.c.db.execute("UPDATE projects SET budget='1.00' WHERE id=?", (self.pid,))
        check = self.fc.verify()
        self.assertFalse(check["ok"])
        self.assertTrue(any("budget column" in p and self.pid in p for p in check["problems"]), check["problems"])
        self.assertEqual(self.fc.project(self.pid)["budget"], "105300.00")  # the forecast reads the approved version

    def test_a_forged_grant_creates_no_version(self):
        v1 = self.initial()
        rev = self.revise([{"cost_code": "XX 10 00", "amount": "72000"}], "Forged revision")
        ap = self.c.request_approval(OP_REVISE, rev["id"], actor_role="pm")
        db, now = self.c.db, utcnow_iso()
        # raw SQL walks the real pending approval to consumed without Cipher.approve or Cipher.execute
        db.execute("UPDATE approvals SET status='granted', approver='intruder', granted_at=? WHERE id=?", (now, ap["id"]))
        db.execute("UPDATE approvals SET status='consumed', consumed_at=?, consumed_by='intruder' WHERE id=?", (now, ap["id"]))
        lines_json = db.one("SELECT lines_json FROM budget_revisions WHERE id=?", (rev["id"],))["lines_json"]
        record = {"id": "bud_forged", "project_id": self.pid, "version": 2, "total": rev["total"], "lines_hash": rev["lines_hash"], "reason": rev["reason"],
                  "approval_id": ap["id"], "revision_id": rev["id"], "previous_hash": v1["version_hash"], "legacy_budget": None,
                  "effective_period_id": None, "created_by": "intruder", "created_at": now}
        record["version_hash"] = _version_hash(record)
        insert = ("INSERT INTO budget_versions (id, project_id, version, total, lines_json, lines_hash, reason, approval_id, revision_id, previous_hash, "
                  "version_hash, legacy_budget, effective_period_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        params = (record["id"], self.pid, 2, record["total"], lines_json, record["lines_hash"], record["reason"], ap["id"], rev["id"],
                  record["previous_hash"], record["version_hash"], None, None, "intruder", now)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "granted and consumed budget.revise approval"):
            db.execute(insert, params)
        self.assertEqual((len(self.fc.budget_versions(self.pid)), self.fc.project(self.pid)["budget"], self.c.project(self.pid)["budget"]),
                         (1, "105300.00", "105300.00"))
        self.assertTrue(self.fc.verify()["ok"])
        # with that guard dropped too, the forged version lands (and carries the column with it), but verify names it
        db.execute("DROP TRIGGER budget_versions_bound_by_granted_approval")
        db.execute(insert, params)
        self.assertEqual((self.fc.project(self.pid)["budget"], self.c.project(self.pid)["budget"]), ("72000.00", "72000.00"))
        problems = self.fc.verify()["problems"]
        self.assertTrue(any("approval.granted" in p for p in problems), problems)
        self.assertTrue(any("budget.revised" in p for p in problems), problems)
        self.assertTrue(any(rev["id"] in p and "not recorded as executed" in p for p in problems), problems)

    def test_schema_entry_is_registered_and_exported(self):
        self.initial()
        self.assertIn(FORECAST_SCHEMA_NAME, {r["name"] for r in self.c.db.query("SELECT name FROM schema_version")})
        self.assertIn(FORECAST_GUARDS_SCHEMA_NAME, {r["name"] for r in self.c.db.query("SELECT name FROM schema_version")})
        self.assertEqual(self.c.db.schema_status()["pending"], [])
        export = self.c.audit_export()
        fc = export["core_domains"]["forecast"]
        self.assertEqual((len(fc["budget_versions"]), fc["verification"]["ok"]), (1, True))
        self.assertIn("budget_versions", export["tables"])


# --------------------------------------------------------------------------- #
# 4. snapshots                                                                 #
# --------------------------------------------------------------------------- #

class SnapshotTests(unittest.TestCase):
    def test_snapshots_are_immutable_and_compare(self):
        w = World()
        c = w.c
        pid, cmt, ts, change = w.costed_project()
        fc = c.forecast
        with self.assertRaises(ForecastError):
            fc.variance_to_previous(pid)
        s1 = fc.snapshot(pid, "pm", "October 2026 month end")
        live = fc.project(pid)
        self.assertEqual((s1["sequence"], s1["budget_version"], s1["inputs_hash"], s1["intact"]), (1, 1, live["inputs_hash"], True))
        self.assertEqual(s1["figures"], live)
        with self.assertRaises(ForecastError):
            fc.variance_to_previous(pid)
        with self.assertRaises(ForecastError):  # labels are unique per project, ignoring case
            fc.snapshot(pid, "pm", "OCTOBER 2026 MONTH END")
        for actor, label in (("pm", " "), ("", "x"), ("pm", "y" * 121)):
            with self.subTest(actor=actor, label=label), self.assertRaises(ForecastError):
                fc.snapshot(pid, actor, label)
        with self.assertRaises(ForecastError):
            fc.snapshot("prj_missing", "pm", "z")
        # more cost and an executed change, then a second snapshot
        w.bill(c.commitments.get(cmt["id"]), [(cmt["sov"][0]["id"], "30000")])
        c.approve_and_execute("change.execute", change["id"])
        s2 = fc.snapshot(pid, "pm", "Mid November review")
        self.assertEqual(fc.snapshot_record(s1["id"])["figures"], live)  # the first snapshot never moves
        v = fc.variance_to_previous(pid)
        self.assertEqual((v["previous"]["id"], v["latest"]["id"], v["inputs_changed"]), (s1["id"], s2["id"], True))
        self.assertEqual(v["totals"]["executed_commitments"], {"previous": "100000.00", "latest": "105000.00", "change": "5000.00"})
        self.assertEqual(v["totals"]["pending_exposure"], {"previous": "5000.00", "latest": "0.00", "change": "-5000.00"})
        self.assertEqual(v["cost_to_date_by_type"]["subcontract"], {"previous": "20000.00", "latest": "30000.00", "change": "10000.00"})
        self.assertEqual(v["totals"]["fac_v2"], {"previous": "112420.00", "latest": "112420.00", "change": "0.00"})
        self.assertEqual(v["by_cost_code"]["XX 10 00"]["cost_to_date"]["change"], "10000.00")
        self.assertEqual(v["by_cost_code"]["XX 10 00"]["committed_remaining"], {"previous": "40000.00", "latest": "30000.00", "change": "-10000.00"})
        self.assertEqual(v["by_cost_code"]["XX 20 00"]["committed"]["change"], "5000.00")
        self.assertEqual(v["by_cost_code"]["XX 20 00"]["etc"], {"previous": "40000.00", "latest": "45000.00", "change": "5000.00"})
        # immutability at the database
        for sql, params in (
            ("UPDATE forecast_snapshots SET figures_json='{}' WHERE id=?", (s1["id"],)),
            ("DELETE FROM forecast_snapshots WHERE id=?", (s1["id"],)),
            ("INSERT OR REPLACE INTO forecast_snapshots (id, project_id, sequence, label, inputs_hash, figures_json, figures_hash, created_by, created_at) "
             "VALUES ('fcs_x', ?, 3, 'october 2026 month end', 'h', '{}', 'h', 'x', 't')", (pid,)),
            ("INSERT INTO forecast_snapshots (id, project_id, sequence, label, inputs_hash, figures_json, figures_hash, created_by, created_at) "
             "VALUES ('fcs_y', ?, 7, 'gap', 'h', '{}', 'h', 'x', 't')", (pid,)),
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, params)
        self.assertEqual([s["sequence"] for s in fc.snapshots(pid)], [1, 2])
        self.assertTrue(all(s["intact"] for s in fc.snapshots(pid)))
        # nothing changed since the second snapshot
        fc.snapshot(pid, "pm", "Mid November review, again")
        v = fc.variance_to_previous(pid)
        self.assertFalse(v["inputs_changed"])
        self.assertTrue(all(d["change"] == "0.00" for d in v["totals"].values()))
        self.assertEqual([e["action"] for e in c.audit.entries(entity_type="forecast_snapshot")], ["forecast.snapshot_taken"] * 3)
        assert_books(self, c, pid)

    def test_restored_copy_reads_but_cannot_snapshot(self):
        d = tempfile.mkdtemp()
        w = World(os.path.join(d, "live.sqlite"))
        self.addCleanup(w.c.db.close)
        pid, cmt, ts, change = w.costed_project()
        w.c.forecast.snapshot(pid, "pm", "Before backup")
        restored = Cipher.open_restored(w.c.snapshot(os.path.join(d, "backup.sqlite")))
        self.addCleanup(restored.db.close)
        self.assertEqual(restored.forecast.project(pid), w.c.forecast.project(pid))
        self.assertEqual([s["label"] for s in restored.forecast.snapshots(pid)], ["Before backup"])
        with self.assertRaises(WriteAuthorityError):
            restored.forecast.snapshot(pid, "pm", "On the restored copy")
        with self.assertRaises(WriteAuthorityError):
            restored.forecast.prepare_budget_revision(pid, [{"cost_code": "XX 10 00", "amount": "1"}], "on the restored copy", "pm")
        self.assertEqual(len(restored.forecast.snapshots(pid)), 1)


# --------------------------------------------------------------------------- #
# 5. cross-project isolation                                                   #
# --------------------------------------------------------------------------- #

class IsolationTests(unittest.TestCase):
    def test_projects_do_not_leak_into_each_other(self):
        w = World()
        c = w.c
        a, cmt, ts, change = w.costed_project()
        before = c.forecast.project(a)
        b = w.project(name="Synthetic lift station", budget="5000")
        c.forecast.set_initial_budget(b, [{"cost_code": "XX 30 00", "amount": "5000"}], "pm")
        design_b = w.phase(b, "XX 30 00")  # same phase code on another project
        w.lab.log_time(w.emp["id"], b, design_b["id"], "2026-10-20", "2", "", actor="emp")
        w.lab.log_time(w.emp["id"], a, c.plugin("labor").phases(a)[1]["id"], "2026-10-20", "1", "", actor="emp")
        ts2 = w.lab.submit_timesheet(w.emp["id"], "P1", actor="emp")
        c.approve_and_execute("labor.approve_timesheet", ts2["id"], period_id="P1")
        w.reimbursement(b, "80.00")
        rev_a = c.forecast.prepare_budget_revision(a, [{"cost_code": "XX 10 00", "amount": "90000"}], "Revision on A", "pm")
        rev_b = c.forecast.prepare_budget_revision(b, [{"cost_code": "XX 30 00", "amount": "6000"}], "Revision on B", "pm")
        ap_b = c.request_approval(OP_REVISE, rev_b["id"], actor_role="pm")
        c.approve(ap_b["id"])
        c.approve_and_execute(OP_REVISE, rev_a["id"], actor_role="pm")
        self.assertEqual(c.forecast.revision(rev_b["id"])["status"], "pending")  # A's revision supersedes nothing on B
        self.assertEqual(c.execute(ap_b["id"]).result["budget_version"], 2)
        c.forecast.snapshot(a, "pm", "Shared label")
        c.forecast.snapshot(b, "pm", "Shared label")  # labels are unique per project only
        fa, fb = c.forecast.project(a), c.forecast.project(b)
        # B: 2 h at 50 on its own XX 30 00 phase and its own claim
        self.assertEqual(fb["cost_to_date_by_type"], {"subcontract": "0.00", "labor": "100.00", "reimbursable": "80.00", "total": "180.00"})
        self.assertEqual((fb["by_cost_code"]["XX 30 00"]["cost_to_date"], fb["budget"], fb["budget_version"]), ("100.00", "6000.00", 2))
        # A: only its own extra hour (on XX 30 00); budget now version 2
        self.assertEqual(fa["cost_to_date_by_type"], {"subcontract": "20000.00", "labor": "650.00", "reimbursable": "120.00", "total": "20770.00"})
        self.assertEqual(fa["by_cost_code"]["XX 30 00"]["cost_to_date"], "450.00")
        self.assertEqual((fa["budget"], fa["budget_version"], fa["executed_commitments"]), ("90000.00", 2, before["executed_commitments"]))
        self.assertEqual([s["sequence"] for s in c.forecast.snapshots(a)], [1])
        self.assertEqual([s["sequence"] for s in c.forecast.snapshots(b)], [1])
        self.assertEqual([v["version"] for v in c.forecast.budget_versions(b)], [1, 2])
        assert_books(self, c, a, b)


if __name__ == "__main__":
    unittest.main()
