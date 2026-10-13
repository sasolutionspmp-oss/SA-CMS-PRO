"""Period close, statements, aging and WIP: golden sequence and adversarial variants."""
import datetime as dt
import json
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

from apps.cipher.core.approvals import ApprovalConsumed, ApprovalExpired, ApprovalNotGranted, StaleApprovalError, build_manifest
from apps.cipher.core.ids import hash_json
from apps.cipher.domain.close import (
    GUARDS_SCHEMA_NAME, PLUGIN_NAME, REOPEN_GOVERNANCE_SCHEMA_NAME, REOPEN_GRANTS_SCHEMA_NAME, SCHEMA_NAME, CloseError, ReopenAuthorityError,
    percent_complete,
)
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher, CoreReconciliationChecks, RoleNotAuthorized

D = Decimal

# Sibling plugins are built independently and may contribute their own blocking close
# checks; the scenarios keep only this module, the reimbursement plugin (whose
# employee-payable reconciliation the checklist reads) and the core subledger checks
# ("core_reconciliation": retainage payable 2050, stored materials 1300, retainage
# receivable 1150, provider clearing 1200), so the expected checklist is deterministic.
# Aggregation of other plugins' hooks is tested with fakes below; the golden close (with
# a banking reconciliation, a stale close approval, the WIP adjustment, its reversal and
# the lock) also runs with every registered plugin, and one more test checks the
# checklist shape against every registered plugin.
KEEP_PLUGINS = ("close", "reimbursement", "core_reconciliation")
CORE_SOURCE = "core_reconciliation"


class Scenario:
    """Fresh in-memory workspace: verified supplier, customer, project, open periods P1 and P2."""

    def __init__(self, *, isolate: bool = True, keep: tuple[str, ...] = ()):
        self.c = Cipher()
        if isolate:
            for name in list(self.c._plugins):
                if name not in KEEP_PLUGINS + keep:
                    del self.c._plugins[name]
        self.close = self.c.plugin(PLUGIN_NAME)
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic Subcontractor", destination="ACH-SIM-SUB")
        self.c.verify_destination(self.supplier["id"], destination="ACH-SIM-SUB", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.project = self.c.create_project(name="Synthetic WWTP upgrade", entity="S&A Solutions LLC (synthetic)", budget="100000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self._ref = 0

    def commitment(self, amounts=("60000", "40000")):
        cmt = self.c.commitments.create(
            project_id=self.pid, supplier_id=self.supplier["id"], title="Subcontract - piping and pump station",
            sov_lines=[{"description": f"Line {i}", "amount": a} for i, a in enumerate(amounts, start=1)], retainage_rate="0.10", actor="owner",
        )
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        return self.c.commitments.get(cmt["id"])

    def supplier_bill(self, cmt, cumulative_installed, *, period="P1", post=True):
        bill = self.c.bills.certify(commitment_id=cmt["id"], period_id=period, installed=[{"sov_line_id": cmt["sov"][0]["id"], "cumulative_installed": cumulative_installed}], actor="owner")
        if post:
            self.c.approve_and_execute("bill.approve", bill["id"])
        return self.c.bills.get(bill["id"])

    def prime_bill(self, certified, *, period="P1", post=True):
        pb = self.c.receivables.certify(project_id=self.pid, period_id=period, certified_cumulative=certified, retainage_rate="0.10", actor="owner")
        if post:
            self.c.approve_and_execute("prime_bill.approve", pb["id"])
        return self.c.receivables.get(pb["id"])

    def send(self, prime):
        """Sending a prime bill is its own approval-bound authority."""
        return self.c.approve_and_execute("prime_bill.send", prime["id"])

    def ach_collection(self, prime, amount, *, fee="0", ref, period="P1"):
        """ACH receipt on a prime bill, backed by the customer's recorded debit mandate."""
        if not self.c.receivables.active_mandate(self.customer["id"]):
            doc = self.c.evidence.register_document(project_id=self.pid, kind="ach_mandate", title="Customer ACH debit authorization (synthetic)", actor="owner")
            rev = self.c.evidence.add_revision(document_id=doc["id"], content=b"synthetic ACH debit authorization", note="signed authorization", actor="owner")
            self.c.receivables.record_mandate(self.customer["id"], "MANDATE-SIM-CLOSE", rev["content_hash"], actor="owner")
        return self.c.receivables.record_collection(prime_bill_id=prime["id"], period_id=period, amount=amount, fee=fee, provider_ref=ref, actor="owner")

    def journal(self, lines, *, period="P1", source_type="test_setup"):
        self._ref += 1
        return self.c.ledger.post(period_id=period, description="synthetic setup", lines=lines, source_type=source_type,
                                  source_id=f"setup-{self._ref}", source_version="1", posted_by="owner")

    def owner_contribution(self, amount, *, period="P1"):
        return self.journal([{"account": "1000", "debit": amount}, {"account": "3000", "credit": amount}], period=period, source_type="owner_contribution")

    def cost(self, amount, *, period="P1"):
        """Reimbursable project cost paid straight from the bank (touches no subledger control)."""
        return self.journal([{"account": "5100", "debit": amount, "project_id": self.pid}, {"account": "1000", "credit": amount, "project_id": self.pid}], period=period, source_type="expense_paid")

    def checks(self, period="P1"):
        return {ch["check"]: ch for ch in self.close.checklist(period)}

    def wip_ready(self, contract="150000"):
        """45,000 cost on a 100,000 forecast, 60,000 billed, contract value set."""
        cmt = self.commitment()
        self.supplier_bill(cmt, "45000")
        self.prime_bill("60000")
        self.close.set_contract_value(self.pid, contract, actor="owner")
        return cmt


class CloseGoldenTests(unittest.TestCase):
    def test_golden_close_sequence(self):
        s = Scenario()
        c, cl = s.c, s.close
        cmt = s.commitment()
        cv = cl.set_contract_value(s.pid, "150000.00", actor="owner")
        self.assertEqual((cv["version"], cv["contract_value"]), (1, "150000.00"))

        # a draft supplier bill in P1 blocks the close
        bill = s.supplier_bill(cmt, "45000", post=False)
        checks = s.checks()
        for ch in checks.values():
            self.assertEqual(set(ch), {"check", "ok", "detail", "source"})
            self.assertIsInstance(ch["ok"], bool)
        self.assertFalse(checks["no_draft_supplier_bills"]["ok"])
        self.assertIn(bill["id"], checks["no_draft_supplier_bills"]["detail"])
        self.assertEqual(cl.checklist_report("P1")["failing"], ["no_draft_supplier_bills"])
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(c.ledger.period("P1")["status"], "open")

        c.approve_and_execute("bill.approve", bill["id"])
        self.assertTrue(cl.checklist_report("P1")["all_ok"])

        # a draft prime bill blocks it too
        prime = s.prime_bill("60000", post=False)
        self.assertEqual(cl.checklist_report("P1")["failing"], ["no_draft_prime_bills"])
        c.approve_and_execute("prime_bill.approve", prime["id"])
        s.send(prime)
        s.ach_collection(prime, "54000", fee="5", ref="ach_sim_rcv_0001")
        s.owner_contribution("10000")
        checks = s.checks()
        for name in ("trial_balance_balanced", "earlier_periods_closed", "ap_reconciled", "ar_reconciled", "no_draft_supplier_bills", "no_draft_prime_bills",
                     "no_unresolved_payments", "no_draft_wip_adjustments", "wip_reconciled", "employee_payable_reconciled", "bank_reconciliation"):
            self.assertTrue(checks[name]["ok"], name)
        self.assertIn("not configured", checks["bank_reconciliation"]["detail"])

        # WIP: 45,000 / 100,000 = 0.4500 of 150,000 = 67,500 earned against 60,000 billed
        w = cl.wip(s.pid, "P1")
        self.assertEqual(w["contract_value"], "150000.00")
        self.assertEqual(w["estimated_total_cost"], "100000.00")
        self.assertEqual(w["estimated_total_cost_basis"], "forecast_at_completion")
        self.assertEqual(w["cost_to_date"], "45000.00")
        self.assertEqual(w["percent_complete"], "0.4500")
        self.assertEqual(w["earned_revenue"], "67500.00")
        self.assertEqual(w["billed_to_date"], "60000.00")
        self.assertEqual(w["over_under"], "-7500.00")
        self.assertEqual(w["position"], "underbilled")
        self.assertEqual(w["label"], "SHADOW - not authoritative")

        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        self.assertEqual((row["status"], row["direction"], row["amount"]), ("draft", "underbilled", "7500.00"))
        self.assertEqual((row["debit_account"], row["credit_account"]), ("1160", "4000"))
        self.assertEqual(row["inputs_hash"], w["inputs_hash"])
        res = c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        self.assertEqual(res.result["status"], "posted")
        j = c.ledger.journal(res.result["journal_id"])
        self.assertEqual(j["source_type"], "wip_adjustment")
        self.assertEqual([(ln["account_code"], ln["debit"], ln["credit"]) for ln in j["lines"]], [("1160", "7500.00", "0.00"), ("4000", "0.00", "7500.00")])
        self.assertEqual(c.ledger.balance("1160"), D("7500.00"))
        self.assertEqual(c.ledger.balance("4000"), D("67500.00"))
        self.assertEqual(cl.wip(s.pid, "P1")["billed_to_date"], "60000.00")  # adjustment journals are not billings
        self.assertTrue(cl.wip_reconciliation(s.pid)["reconciled"])

        # statements
        st = cl.statements("P1")
        inc = st["income_statement"]
        self.assertEqual((inc["revenue"], inc["expense"], inc["net"]), ("67500.00", "45005.00", "22495.00"))
        self.assertEqual(D(inc["net"]), D(inc["revenue"]) - D(inc["expense"]))
        self.assertEqual({ln["code"]: ln["amount"] for ln in inc["expense_lines"]}, {"5000": "45000.00", "6000": "5.00"})
        bs = st["balance_sheet"]
        self.assertEqual({ln["code"]: ln["amount"] for ln in bs["assets"]}, {"1000": "63995.00", "1100": "0.00", "1150": "6000.00", "1160": "7500.00"})
        self.assertEqual({ln["code"]: ln["amount"] for ln in bs["liabilities"]}, {"2000": "40500.00", "2050": "4500.00"})
        self.assertEqual(bs["total_assets"], "77495.00")
        self.assertEqual(bs["total_liabilities"], "45000.00")
        self.assertEqual(bs["total_equity"], "10000.00")
        self.assertEqual(bs["current_earnings"], "22495.00")
        self.assertEqual(bs["total_liabilities_and_equity"], "77495.00")
        self.assertTrue(bs["balanced"])
        cash = st["cash"]
        self.assertEqual({m["source_type"]: (m["inflow"], m["outflow"]) for m in cash["movements"]},
                         {"collection": ("53995.00", "0.00"), "owner_contribution": ("10000.00", "0.00")})
        self.assertEqual((cash["opening"], cash["net_change"], cash["closing"]), ("0.00", "63995.00", "63995.00"))
        self.assertEqual(st["label"], "SHADOW - not authoritative")

        # close P1 through an approval; the run keeps the checklist and statements snapshot
        res = c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(res.result["status"], "closed")
        self.assertEqual(res.result["net_income"], "22495.00")
        self.assertEqual(c.ledger.period("P1")["status"], "closed")
        run = cl.close_run(res.result["close_run_id"])
        self.assertEqual(run["action"], "close")
        self.assertTrue(all(ch["ok"] for ch in run["checklist"]))
        self.assertEqual(run["statements"]["balance_sheet"]["total_assets"], "77495.00")
        self.assertEqual(run["statements_hash"], res.result["statements_hash"])
        with self.assertRaises(PeriodNotOpen):
            s.owner_contribution("1.00")

        # reversal into P2 restores the contract asset
        res = c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P2")
        self.assertEqual(res.result["status"], "reversed")
        self.assertEqual(c.ledger.balance("1160"), D("0.00"))
        self.assertEqual(c.ledger.journal(res.result["reversal_journal_id"])["reversal_of"], res.result["journal_id"])
        self.assertEqual(c.ledger.journal(res.result["reversal_journal_id"])["period_id"], "P2")
        self.assertEqual(cl.wip_adjustment(row["id"])["status"], "reversed")
        rec = cl.wip_reconciliation(s.pid)
        self.assertTrue(rec["reconciled"])
        by_period = {p["period_id"]: p for p in rec["periods"]}
        self.assertEqual((by_period["P1"]["underbillings_register"], by_period["P1"]["underbillings_ledger"], by_period["P1"]["live_adjustments"]),
                         ("7500.00", "7500.00", [row["id"]]))  # still on P1's books
        self.assertEqual((by_period["P2"]["underbillings_register"], by_period["P2"]["underbillings_ledger"], by_period["P2"]["live_adjustments"]),
                         ("0.00", "0.00", []))
        self.assertEqual(cl.wip_reconciliation(s.pid, "P1")["underbillings_ledger"], "7500.00")

        # aging ties to the subledgers
        aging = cl.aging(bill["created_at"][:10])
        self.assertEqual((aging["ap"]["total"], aging["ap"]["subledger_total"]), ("40500.00", "40500.00"))
        self.assertEqual(aging["ap"]["buckets"], {"current": "40500.00", "1_30": "0.00", "31_60": "0.00", "61_90": "0.00", "over_90": "0.00"})
        self.assertTrue(aging["ap"]["ties_to_subledger"] and aging["ar"]["ties_to_subledger"])
        self.assertEqual(aging["ar"]["total"], "0.00")

        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_golden_close_with_every_registered_plugin(self):
        """The close sequence with banking, labor, procurement, field and the rest loaded."""
        s = Scenario(isolate=False)
        c, cl = s.c, s.close
        cmt = s.commitment()
        cl.set_contract_value(s.pid, "150000.00", actor="owner")
        bill = s.supplier_bill(cmt, "45000", post=False)
        self.assertIn("no_draft_supplier_bills", cl.checklist_report("P1")["failing"])
        c.approve_and_execute("bill.approve", bill["id"])
        prime = s.prime_bill("60000")
        s.send(prime)
        s.ach_collection(prime, "54000", fee="5", ref="ach_sim_rcv_0001")
        s.owner_contribution("10000")

        bank = c._plugins.get("banking")
        if bank is not None:  # bank activity in P1 needs a locked bank reconciliation
            self.assertIn("bank reconciliation", cl.checklist_report("P1")["failing"])
            st = bank.import_statement(
                statement_ref="SIM-STMT-2026-10", period_id="P1", opening_balance="0.00", closing_balance="63995.00", actor="owner",
                lines=[{"date": "2026-10-15", "amount": "53995.00", "description": "ACH receipt", "reference": "ach_sim_rcv_0001"},
                       {"date": "2026-10-20", "amount": "10000.00", "description": "Owner contribution", "reference": "OWN-1"}],
            )
            bank.auto_match(st["id"], actor="owner")
            c.approve_and_execute("banking.lock_reconciliation", st["id"], period_id="P1")
        report = cl.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        sources = {ch["source"] for ch in report["checks"]}
        for name, plugin in c._plugins.items():
            if name != PLUGIN_NAME and callable(getattr(plugin, "close_checks", None)) and plugin.close_checks("P1"):
                self.assertIn(name, sources)

        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        self.assertEqual((row["direction"], row["amount"]), ("underbilled", "7500.00"))
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        self.assertEqual(c.ledger.balance("1160"), D("7500.00"))

        # a close approval goes stale with every plugin loaded too (non-cash entry: the bank reconciliation stays valid)
        ap = c.request_approval("close.close_period", "P1")
        c.approve(ap["id"])
        s.journal([{"account": "5100", "debit": "100", "project_id": s.pid}, {"account": "3000", "credit": "100"}], source_type="owner_paid_expense")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"])
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")

        res = c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(res.result["status"], "closed")
        self.assertEqual(res.result["net_income"], "22395.00")  # 67,500 - (45,000 + 5 + 100)
        st = cl.statements("P1")
        self.assertTrue(st["balance_sheet"]["balanced"])
        self.assertEqual(D(st["income_statement"]["net"]), D(st["income_statement"]["revenue"]) - D(st["income_statement"]["expense"]))
        with self.assertRaises(PeriodNotOpen):
            s.owner_contribution("1.00")
        c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P2")
        self.assertEqual(c.ledger.balance("1160"), D("0.00"))
        self.assertTrue(cl.wip_reconciliation(s.pid)["reconciled"])
        res = c.approve_and_execute("close.lock_period", "P1")
        self.assertEqual(res.result["status"], "locked")
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])
        json.dumps(c.project_state(s.pid), default=str)


class PeriodCloseTests(unittest.TestCase):
    def test_close_approval_goes_stale_when_a_journal_or_checklist_changes(self):
        s = Scenario()
        c = s.c
        s.owner_contribution("5000")
        ap = c.request_approval("close.close_period", "P1")
        self.assertEqual(ap["manifest"]["amounts"], {"total_debit": "5000.00", "total_credit": "5000.00"})
        self.assertTrue(ap["manifest"]["bindings"]["checklist_ok"])
        c.approve(ap["id"])
        s.owner_contribution("250")  # posted after the grant
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"])
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.ledger.period("P1")["status"], "open")

        # a checklist change alone (a new draft bill, no journal) also invalidates
        cmt = s.commitment()
        ap2 = c.request_approval("close.close_period", "P1")
        c.approve(ap2["id"])
        draft = s.supplier_bill(cmt, "1000", post=False)
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap2["id"])
        self.assertEqual(c.approvals.get(ap2["id"])["status"], "invalidated")

        c.bills.void(draft["id"], actor="owner", reason="entered in error")
        res = c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(res.result["status"], "closed")
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_execution_refuses_while_the_checklist_fails(self):
        s = Scenario()
        c = s.c
        cmt = s.commitment()
        s.supplier_bill(cmt, "10000", post=False)
        ap = c.request_approval("close.close_period", "P1")
        self.assertFalse(ap["manifest"]["bindings"]["checklist_ok"])
        self.assertEqual(ap["manifest"]["bindings"]["failing_checks"], ["no_draft_supplier_bills"])
        c.approve(ap["id"])
        with self.assertRaises(CloseError):
            c.execute(ap["id"])
        self.assertEqual(c.ledger.period("P1")["status"], "open")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")  # the command rolled back; nothing consumed
        self.assertEqual(s.close.close_runs("P1"), [])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_unresolved_payment_blocks_close_until_reconciled(self):
        s = Scenario()
        c = s.c
        cmt = s.commitment()
        bill = s.supplier_bill(cmt, "20000")
        ap = c.request_approval("payment.release", bill["id"], actor_role="treasury")
        c.approve(ap["id"])
        c.execute(ap["id"], actor="treasury")
        self.assertTrue(s.checks()["no_unresolved_payments"]["ok"])  # queued is not yet in doubt
        c.provider.mode = "timeout_after_accept"
        c.dispatch_payments()
        check = s.checks()["no_unresolved_payments"]
        self.assertFalse(check["ok"])
        self.assertIn("outcome_unknown", check["detail"])
        self.assertEqual(check["source"], "payments")
        c.provider.mode = "accept"
        c.reconcile_payments()
        report = s.close.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_other_plugins_close_checks_are_aggregated(self):
        s = Scenario()
        c = s.c
        self.assertFalse(hasattr(s.close, "close_checks"))  # the close module never checks itself

        class FakeBank:
            def __init__(self):
                self.ok = False
                self.calls = []

            def close_checks(self, period_id):
                self.calls.append(period_id)
                return [{"check": "bank_statement_reconciled", "ok": self.ok, "detail": f"statement for {period_id}"}]

        class Broken:
            def close_checks(self, period_id):
                raise ValueError("bank feed offline")

        class Malformed:
            def close_checks(self, period_id):
                return [{"detail": "no check name"}]

        class Truthy:
            def close_checks(self, period_id):
                return [{"check": "loose_flag", "ok": 1, "detail": ""}]

        bank = FakeBank()
        c.register_plugin("banking", bank)
        checks = s.checks()
        self.assertNotIn("bank_reconciliation", checks)  # a banking plugin is registered now
        self.assertEqual((checks["bank_statement_reconciled"]["ok"], checks["bank_statement_reconciled"]["source"]), (False, "banking"))
        self.assertEqual(bank.calls, ["P1"])
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.close_period", "P1")
        bank.ok = True
        self.assertTrue(s.close.checklist_report("P1")["all_ok"])

        for name, plugin, expected in (("brokenmod", Broken(), "bank feed offline"), ("oddmod", Malformed(), "malformed"), ("loosemod", Truthy(), "")):
            c.register_plugin(name, plugin)
            failing = [ch for ch in s.close.checklist("P1") if not ch["ok"]]
            self.assertEqual(len(failing), 1, failing)
            self.assertEqual(failing[0]["source"], name)
            self.assertIn(expected, failing[0]["detail"])
            del c._plugins[name]
        self.assertTrue(s.close.checklist_report("P1")["all_ok"])
        res = c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(res.result["status"], "closed")

    def test_employee_payable_check_uses_the_reimbursement_plugin(self):
        s = Scenario()
        c = s.c
        emp = c.add_party(kind="employee", name="Field Engineer", destination="ACH-EMP-1")
        r = c.plugin("reimbursement")
        claim = r.submit_claim(project_id=s.pid, employee_id=emp["id"], description="Mileage to site", amount="120.00", receipt_hash="rcpt-0001", actor="emp")
        c.approve_and_execute("reimbursement.approve", claim["id"], period_id="P1")
        self.assertTrue(s.checks()["employee_payable_reconciled"]["ok"])
        bad = s.journal([{"account": "5100", "debit": "50", "project_id": s.pid}, {"account": "2100", "credit": "50", "project_id": s.pid}])
        check = s.checks()["employee_payable_reconciled"]
        self.assertFalse(check["ok"])
        self.assertIn(s.pid, check["detail"])
        self.assertEqual(check["source"], "reimbursement")
        c.ledger.reverse(bad["id"], period_id="P1", posted_by="owner", reason="direct control-account entry")
        self.assertTrue(s.checks()["employee_payable_reconciled"]["ok"])

        # a 2100 posting with no project is invisible per project but not company-wide
        stray = s.journal([{"account": "6000", "debit": "75"}, {"account": "2100", "credit": "75"}])
        check = s.checks()["employee_payable_reconciled"]
        self.assertFalse(check["ok"])
        self.assertIn("company-wide", check["detail"])
        self.assertIn("75.00", check["detail"])
        self.assertFalse(s.close.checklist_report("P1")["all_ok"])
        c.ledger.reverse(stray["id"], period_id="P1", posted_by="owner", reason="direct control-account entry")
        self.assertTrue(s.checks()["employee_payable_reconciled"]["ok"])

    def test_reopen_and_lock_through_approvals(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.owner_contribution("1000")
        c.approve_and_execute("close.close_period", "P1")
        with self.assertRaises(PeriodNotOpen):
            s.owner_contribution("1")
        with self.assertRaises(CloseError):  # a project role cannot reopen the books
            c.request_approval("close.reopen_period", "P1", actor_role="pm")
        with self.assertRaises(CloseError):  # reopening needs a controller approval, not an accountant's
            c.request_approval("close.reopen_period", "P1", actor_role="accountant")
        ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        self.assertEqual(ap["manifest"]["actor_role"], "controller")
        self.assertEqual(ap["manifest"]["bindings"]["approval_scope"], "controller reopen of a closed (not locked) period")
        c.approve(ap["id"], approver="controller")
        res = c.execute(ap["id"], actor="controller")
        self.assertEqual(res.result["status"], "open")
        self.assertEqual(c.ledger.period("P1")["status"], "open")
        s.owner_contribution("1")  # posting works again
        c.approve_and_execute("close.close_period", "P1")

        pending_reopen = c.request_approval("close.reopen_period", "P1")
        res = c.approve_and_execute("close.lock_period", "P1")
        self.assertEqual(res.result["status"], "locked")
        self.assertEqual(c.approvals.get(pending_reopen["id"])["status"], "invalidated")
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.reopen_period", "P1")
        with self.assertRaises(PeriodNotOpen):
            s.owner_contribution("1")
        runs = cl.close_runs("P1")
        self.assertEqual([r["action"] for r in runs], ["close", "reopen", "close", "lock"])
        self.assertEqual(runs[-1]["statements"]["balance_sheet"]["total_assets"], "1001.00")
        self.assertIsNone(runs[1]["checklist"])
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("DELETE FROM close_runs")
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("UPDATE close_runs SET actor='someone else'")
        # open periods cannot be locked or reopened
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.lock_period", "P2")
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.reopen_period", "P2")
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_invalid_close_requests_are_rejected(self):
        s = Scenario()
        c = s.c
        with self.assertRaises(CloseError):
            c.request_approval("close.close_period", "P1", actor_role="pm")
        with self.assertRaises(CloseError):
            c.request_approval("close.close_period", "P-unknown")
        with self.assertRaises(CloseError):
            c.request_approval("close.bogus", "P1")
        with self.assertRaises(CloseError):
            c.request_approval("close.post_wip_adjustment", "wip_missing")
        with self.assertRaises(CloseError):
            s.close.checklist("P-unknown")
        with self.assertRaises(CloseError):
            s.close.statements("")

    def test_periods_close_lock_and_reopen_in_order(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.owner_contribution("100", period="P2")
        check = s.checks("P2")["earlier_periods_closed"]
        self.assertFalse(check["ok"])
        self.assertIn("P1", check["detail"])
        with self.assertRaises(CloseError):  # P2's balance sheet still moves with P1
            c.approve_and_execute("close.close_period", "P2")
        self.assertEqual(c.ledger.period("P2")["status"], "open")

        c.approve_and_execute("close.close_period", "P1")
        self.assertTrue(s.checks("P2")["earlier_periods_closed"]["ok"])
        res = c.approve_and_execute("close.close_period", "P2")
        self.assertEqual(res.result["status"], "closed")
        with self.assertRaises(CloseError):  # P1 is only closed: it could still be reopened under a locked P2
            c.approve_and_execute("close.lock_period", "P2")
        with self.assertRaises(CloseError):  # reopening P1 would move the closed P2 balance sheet
            c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        self.assertEqual(c.ledger.period("P1")["status"], "closed")

        # a lock approval granted while P1 was closed goes stale once P1 is locked
        lock_p2 = c.request_approval("close.lock_period", "P2")
        self.assertEqual(lock_p2["manifest"]["bindings"]["earlier_periods"], [["P1", "closed"]])
        c.approve(lock_p2["id"])
        c.approve_and_execute("close.lock_period", "P1")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(lock_p2["id"])
        res = c.approve_and_execute("close.lock_period", "P2")
        self.assertEqual(res.result["status"], "locked")
        snapshot = cl.close_runs("P2")[-1]["statements"]
        with self.assertRaises(PeriodNotOpen):
            s.owner_contribution("5000", period="P1")
        self.assertEqual(cl.statements("P2"), snapshot)
        self.assertEqual(snapshot["balance_sheet"]["total_assets"], "100.00")
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_lock_refuses_a_period_closed_outside_the_checklist(self):
        s = Scenario()
        c, cl = s.c, s.close
        cmt = s.commitment()
        draft = s.supplier_bill(cmt, "5000", post=False)
        self.assertEqual(cl.checklist_report("P1")["failing"], ["no_draft_supplier_bills"])
        c.close_period("P1")  # straight through the ledger, bypassing the checklist
        ap = c.request_approval("close.lock_period", "P1")
        self.assertIsNone(ap["manifest"]["bindings"]["checklist_close_run"])
        c.approve(ap["id"])
        with self.assertRaises(CloseError):
            c.execute(ap["id"])
        self.assertEqual(c.ledger.period("P1")["status"], "closed")
        self.assertEqual(cl.close_runs("P1"), [])

        # reopen and close through the checklist; then a governed reopen followed by a direct
        # re-close (outside the checklist) is caught too, with or without a change in between
        c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        c.bills.void(draft["id"], actor="owner", reason="entered in error")
        s.owner_contribution("500")
        c.approve_and_execute("close.close_period", "P1")
        c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        s.owner_contribution("1")
        c.close_period("P1")
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.lock_period", "P1")
        c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        c.close_period("P1")  # re-closed directly with no change in between: still not a checklist close
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.lock_period", "P1")

        c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        c.approve_and_execute("close.close_period", "P1")
        res = c.approve_and_execute("close.lock_period", "P1")
        self.assertEqual(res.result["status"], "locked")
        self.assertEqual([r["action"] for r in cl.close_runs("P1")], ["reopen", "close", "reopen", "reopen", "reopen", "close", "lock"])
        # every reopen rode on its own consumed controller approval, recorded by the ledger too
        reopen_runs = [r for r in cl.close_runs("P1") if r["action"] == "reopen"]
        self.assertEqual(len({r["approval_id"] for r in reopen_runs}), 4)
        for run in reopen_runs:
            ap = c.approvals.get(run["approval_id"])
            self.assertEqual((ap["operation"], ap["subject_id"], ap["status"], ap["actor_role"]), ("close.reopen_period", "P1", "consumed", "controller"))
        payloads = [json.loads(e["payload_json"]) for e in c.audit.entries(entity_type="period", entity_id="P1") if e["action"] == "period.reopened"]
        self.assertEqual([p.get("approval_ref") or p.get("approval_id") for p in payloads], [r["approval_id"] for r in reopen_runs])
        self.assertTrue(c.audit.verify_chain()["ok"])


class StatementTests(unittest.TestCase):
    def test_income_is_per_period_and_balance_sheet_is_cumulative(self):
        s = Scenario()
        s.owner_contribution("20000")
        s.journal([{"account": "1000", "debit": "5000", "project_id": s.pid}, {"account": "4000", "credit": "5000", "project_id": s.pid}], source_type="cash_sale")
        s.cost("1200")
        s.journal([{"account": "1000", "debit": "3000", "project_id": s.pid}, {"account": "4000", "credit": "3000", "project_id": s.pid}], period="P2", source_type="cash_sale")
        s.journal([{"account": "6000", "debit": "25"}, {"account": "1000", "credit": "25"}], period="P2", source_type="bank_fee")

        p1 = s.close.statements("P1")
        self.assertEqual((p1["income_statement"]["revenue"], p1["income_statement"]["expense"], p1["income_statement"]["net"]), ("5000.00", "1200.00", "3800.00"))
        self.assertEqual(p1["balance_sheet"]["periods_included"], ["P1"])
        self.assertEqual(p1["balance_sheet"]["total_assets"], "23800.00")
        self.assertTrue(p1["balance_sheet"]["balanced"])
        self.assertEqual({m["source_type"]: m["net"] for m in p1["cash"]["movements"]}, {"cash_sale": "5000.00", "expense_paid": "-1200.00", "owner_contribution": "20000.00"})

        p2 = s.close.statements("P2")
        inc = p2["income_statement"]
        self.assertEqual((inc["revenue"], inc["expense"], inc["net"]), ("3000.00", "25.00", "2975.00"))
        bs = p2["balance_sheet"]
        self.assertEqual(bs["periods_included"], ["P1", "P2"])
        self.assertEqual((bs["total_assets"], bs["total_equity"], bs["current_earnings"]), ("26775.00", "20000.00", "6775.00"))
        self.assertTrue(bs["balanced"])
        self.assertEqual((p2["cash"]["opening"], p2["cash"]["net_change"], p2["cash"]["closing"]), ("23800.00", "2975.00", "26775.00"))
        self.assertEqual(p2["cash"]["closing"], f"{s.c.ledger.balance('1000'):f}")
        self.assertEqual(json.loads(json.dumps(p2)), p2)  # plain JSON: money as strings


class WipTests(unittest.TestCase):
    def test_percent_complete_rounding_and_cap(self):
        self.assertEqual(percent_complete("1.00", "3.00"), D("0.3333"))
        self.assertEqual(percent_complete("2.00", "3.00"), D("0.6667"))
        self.assertEqual(percent_complete("45000", "100000"), D("0.4500"))
        self.assertEqual(percent_complete("120", "100"), D("1.0000"))
        self.assertEqual(percent_complete("0", "100"), D("0.0000"))
        self.assertEqual(percent_complete("5", "0"), D("0.0000"))

    def test_overbilling_posts_to_contract_liability(self):
        s = Scenario()
        c, cl = s.c, s.close
        cmt = s.commitment()
        s.supplier_bill(cmt, "20000")
        s.prime_bill("30000")
        cl.set_contract_value(s.pid, "100000", actor="owner")
        w = cl.wip(s.pid, "P1")
        self.assertEqual((w["percent_complete"], w["earned_revenue"], w["billed_to_date"], w["over_under"], w["position"]),
                         ("0.2000", "20000.00", "30000.00", "10000.00", "overbilled"))
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        self.assertEqual((row["direction"], row["amount"], row["debit_account"], row["credit_account"]), ("overbilled", "10000.00", "4000", "2300"))
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        self.assertEqual(c.ledger.balance("2300"), D("10000.00"))
        self.assertEqual(c.ledger.balance("4000"), D("20000.00"))  # revenue now equals earned
        self.assertEqual(cl.wip(s.pid, "P1")["billed_to_date"], "30000.00")
        rec = cl.wip_reconciliation(s.pid)
        self.assertEqual((rec["overbillings_register"], rec["overbillings_ledger"], rec["reconciled"]), ("10000.00", "10000.00", True))
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_estimate_falls_back_to_cost_and_percent_caps_at_one(self):
        s = Scenario()
        cl = s.close
        s.cost("12000")
        cl.set_contract_value(s.pid, "50000", actor="owner")
        w = cl.wip(s.pid, "P1")  # no commitments: forecast is zero, cost to date is the estimate
        self.assertEqual((w["estimated_total_cost_basis"], w["estimated_total_cost"], w["percent_complete"], w["earned_revenue"]),
                         ("cost_to_date", "12000.00", "1.0000", "50000.00"))
        s.commitment(amounts=("10000",))  # forecast 10,000 now, below cost: capped
        w = cl.wip(s.pid, "P1")
        self.assertEqual((w["estimated_total_cost_basis"], w["estimated_total_cost"], w["percent_complete"]), ("forecast_at_completion", "10000.00", "1.0000"))
        self.assertEqual(w["over_under"], "-50000.00")

    def test_zero_adjustment_and_missing_contract_value_are_rejected(self):
        s = Scenario()
        cl = s.close
        cmt = s.commitment()
        s.supplier_bill(cmt, "45000")
        s.prime_bill("45000")
        with self.assertRaises(CloseError):
            cl.wip(s.pid, "P1")  # no contract value yet
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        cl.set_contract_value(s.pid, "100000", actor="owner")
        w = cl.wip(s.pid, "P1")
        self.assertEqual((w["over_under"], w["position"], w["adjustment"]), ("0.00", "even", None))
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        with self.assertRaises(CloseError):
            cl.wip("prj_missing", "P1")
        with self.assertRaises(CloseError):
            cl.wip(s.pid, "P9")

    def test_duplicates_one_live_adjustment_cancel_and_schema_guards(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")  # identical draft
        check = s.checks()["no_draft_wip_adjustments"]
        self.assertFalse(check["ok"])
        self.assertIn(row["id"], check["detail"])

        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")  # one live adjustment per project per period
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P2", actor="owner")  # the P1 adjustment is still live
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted, CloseError)):
            c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")  # posting twice
        self.assertEqual(c.ledger.balance("1160"), D("7500.00"))
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("UPDATE close_wip SET amount='1.00' WHERE id=?", (row["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("UPDATE close_wip SET status='draft' WHERE id=?", (row["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("DELETE FROM close_wip")

        c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P2")
        again = cl.prepare_wip_adjustment(s.pid, "P2", actor="owner")
        self.assertEqual((again["period_id"], again["amount"]), ("P2", "7500.00"))
        ap = c.request_approval("close.post_wip_adjustment", again["id"])
        c.approve(ap["id"])
        canceled = cl.cancel_wip_adjustment(again["id"], actor="owner", reason="not needed")
        self.assertEqual(canceled["status"], "cancelled")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(CloseError):
            cl.cancel_wip_adjustment(again["id"], actor="owner")
        with self.assertRaises(ApprovalNotGranted):
            c.execute(ap["id"])
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_wip_approval_goes_stale_when_inputs_change(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        ap = c.request_approval("close.post_wip_adjustment", row["id"])
        self.assertEqual(ap["manifest"]["amounts"]["amount"], "7500.00")
        self.assertEqual(ap["manifest"]["bindings"]["inputs_hash"], row["inputs_hash"])
        c.approve(ap["id"])
        s.cost("1000")  # more cost after the grant changes percent complete
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"], period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(cl.wip_adjustment(row["id"])["status"], "draft")
        self.assertEqual(c.ledger.balance("1160"), D("0.00"))
        with self.assertRaises(CloseError):  # a fresh approval of the stale draft still refuses
            c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")

        row2 = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        self.assertEqual(cl.wip_adjustment(row["id"])["status"], "superseded")
        self.assertEqual((row2["percent_complete"], row2["earned_revenue"], row2["amount"]), ("0.4600", "69000.00", "9000.00"))
        c.approve_and_execute("close.post_wip_adjustment", row2["id"], period_id="P1")
        self.assertEqual(c.ledger.balance("1160"), D("9000.00"))
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_contract_value_is_versioned_validated_and_supersedes_drafts(self):
        s = Scenario()
        c, cl = s.c, s.close
        v1 = cl.set_contract_value(s.pid, "100000", actor="owner")
        self.assertEqual((v1["version"], v1["contract_value"], v1["previous_value"]), (1, "100000.00", None))
        v2 = cl.set_contract_value(s.pid, "150000.00", actor="owner")
        self.assertEqual((v2["version"], v2["contract_value"], v2["previous_value"]), (2, "150000.00", "100000.00"))
        self.assertEqual([r["contract_value"] for r in cl.contract_values(s.pid)], ["100000.00", "150000.00"])
        with self.assertRaises(CloseError):
            cl.set_contract_value(s.pid, "150000", actor="owner")  # duplicate of the current value
        for bad in ("0", "-5", 1.5, "abc", None, True, "NaN", "sNaN", "Infinity", "-Infinity", "1e30", "150000.004", "0.001"):
            with self.assertRaises(CloseError, msg=repr(bad)):
                cl.set_contract_value(s.pid, bad, actor="owner")
        self.assertEqual(len(cl.contract_values(s.pid)), 2)  # nothing stored, nothing silently rounded
        with self.assertRaises(CloseError):
            cl.set_contract_value("prj_missing", "1000", actor="owner")
        with self.assertRaises(CloseError):
            cl.set_contract_value(s.pid, "1000", actor="")

        cmt = s.commitment()
        s.supplier_bill(cmt, "45000")
        s.prime_bill("60000")
        self.assertEqual(cl.wip(s.pid, "P1")["earned_revenue"], "67500.00")  # latest version wins
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        ap = c.request_approval("close.post_wip_adjustment", row["id"])
        c.approve(ap["id"])
        cl.set_contract_value(s.pid, "160000", actor="owner")
        self.assertEqual(cl.wip_adjustment(row["id"])["status"], "superseded")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"], period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(cl.wip(s.pid, "P1")["earned_revenue"], "72000.00")
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute("UPDATE close_contract_values SET contract_value='1.00'")

    def test_posting_into_a_closed_period_is_rejected(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        c.close_period("P1")  # closed directly through the ledger, bypassing the checklist
        with self.assertRaises(PeriodNotOpen):
            c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        with self.assertRaises(PeriodNotOpen):
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        self.assertEqual(cl.wip_adjustment(row["id"])["status"], "draft")
        self.assertEqual(c.ledger.balance("1160"), D("0.00"))

    def test_reversal_needs_an_open_later_period(self):
        s = Scenario()
        c, cl = s.c, s.close
        c.open_period("P0", "P0", "2026-09-01", "2026-09-30")
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        for target in (None, "P1", "P0"):
            with self.assertRaises(CloseError):
                c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id=target)
        c.close_period("P2")
        with self.assertRaises(PeriodNotOpen):
            c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P2")
        c.open_period("P3", "P3", "2026-12-01", "2026-12-31")
        res = c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P3")
        self.assertEqual(res.result["period_id"], "P3")
        self.assertEqual(c.ledger.balance("1160"), D("0.00"))
        self.assertEqual(cl.wip_adjustment(row["id"])["reversal_period_id"], "P3")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted, CloseError)):
            c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P3")  # already reversed
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_reprepare_after_a_reversal_cannot_double_count(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P2")
        self.assertEqual(c.ledger.period("P1")["status"], "open")
        with self.assertRaises(CloseError):  # reversed only in P2, so it is still on P1's books
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")

        def assets(pid):
            return {ln["code"]: ln["amount"] for ln in cl.statements(pid)["balance_sheet"]["assets"]}

        self.assertEqual(assets("P1")["1160"], "7500.00")
        self.assertEqual(cl.statements("P1")["income_statement"]["revenue"], "67500.00")  # earned, not more
        self.assertTrue(cl.checklist_report("P1")["all_ok"])

        # the next adjustment belongs to P2, where the earlier one is reversed
        again = cl.prepare_wip_adjustment(s.pid, "P2", actor="owner")
        self.assertEqual(again["amount"], "7500.00")
        c.approve_and_execute("close.post_wip_adjustment", again["id"], period_id="P2")
        self.assertEqual((assets("P1")["1160"], assets("P2")["1160"]), ("7500.00", "7500.00"))
        self.assertEqual(cl.statements("P2")["income_statement"]["revenue"], "0.00")  # reversal and re-accrual net out
        rec = cl.wip_reconciliation(s.pid)
        self.assertTrue(rec["reconciled"])
        self.assertEqual({p["period_id"]: p["live_adjustments"] for p in rec["periods"]}, {"P1": [row["id"]], "P2": [again["id"]]})
        with self.assertRaises(CloseError):  # P2's adjustment is live from P2 onwards, overlapping P1's
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P2", actor="owner")
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_reversal_target_is_bound_to_the_first_open_later_period(self):
        s = Scenario()
        c, cl = s.c, s.close
        c.open_period("P3", "P3", "2026-12-01", "2026-12-31")
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        ap = c.request_approval("close.reverse_wip_adjustment", row["id"])
        self.assertEqual(ap["manifest"]["bindings"]["target_period"], "P2")
        c.approve(ap["id"])
        with self.assertRaises(CloseError):  # skipping P2 would leave the contract asset on P2's books
            c.execute(ap["id"], period_id="P3")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")  # the command rolled back
        self.assertEqual(c.ledger.balance("1160"), D("7500.00"))

        c.close_period("P2")  # the first open later period is now P3: the approval no longer matches
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"], period_id="P2")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        res = c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P3")
        self.assertEqual(res.result["period_id"], "P3")

        # P2 reopened (a governed controller reopen): the P1 adjustment is still on its books, so P2 takes no second one
        c.approve_and_execute("close.reopen_period", "P2", actor_role="controller", actor="controller")
        self.assertEqual(c.ledger.period("P2")["status"], "open")
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P2", actor="owner")
        p2_assets = {ln["code"]: ln["amount"] for ln in cl.statements("P2")["balance_sheet"]["assets"]}
        self.assertEqual(p2_assets["1160"], "7500.00")
        rec = cl.wip_reconciliation(s.pid, "P2")
        self.assertEqual((rec["live_adjustments"], rec["underbillings_register"], rec["underbillings_ledger"], rec["reconciled"]),
                         ([row["id"]], "7500.00", "7500.00", True))
        again = cl.prepare_wip_adjustment(s.pid, "P3", actor="owner")
        self.assertEqual(again["period_id"], "P3")
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_contract_asset_postings_outside_the_register_block_wip_and_close(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        manual = s.journal([{"account": "1160", "debit": "500", "project_id": s.pid}, {"account": "4000", "credit": "500", "project_id": s.pid}])
        rec = cl.wip_reconciliation(s.pid, "P1")
        self.assertEqual((rec["underbillings_register"], rec["underbillings_ledger"], rec["reconciled"]), ("0.00", "500.00", False))
        self.assertEqual(cl.wip_reconciliation(s.pid)["unreconciled_periods"], ["P1", "P2", "all-time"])
        check = s.checks()["wip_reconciled"]
        self.assertFalse(check["ok"])
        self.assertIn(s.pid, check["detail"])
        with self.assertRaises(CloseError):
            cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.close_period", "P1")
        c.ledger.reverse(manual["id"], period_id="P1", posted_by="owner", reason="manual contract asset entry")
        self.assertTrue(s.checks()["wip_reconciled"]["ok"])

        stray = s.journal([{"account": "4000", "debit": "40"}, {"account": "2300", "credit": "40"}])  # no project
        check = s.checks()["wip_reconciled"]
        self.assertFalse(check["ok"])
        self.assertIn("company", check["detail"])
        c.ledger.reverse(stray["id"], period_id="P1", posted_by="owner", reason="manual contract liability entry")
        self.assertTrue(cl.checklist_report("P1")["all_ok"])
        self.assertEqual(cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")["amount"], "7500.00")


BUCKETS = ("current", "1_30", "31_60", "61_90", "over_90")


def expected_bucket(days_past_due):
    """The aging bucket for whole days past due (current while not yet past due)."""
    if days_past_due <= 0:
        return "current"
    return "1_30" if days_past_due <= 30 else "31_60" if days_past_due <= 60 else "61_90" if days_past_due <= 90 else "over_90"


class AgingAndStateTests(unittest.TestCase):
    def test_aging_buckets_by_due_date_tie_to_subledgers(self):
        s = Scenario()
        c, cl = s.c, s.close
        cmt = s.commitment()
        bill = s.supplier_bill(cmt, "20000")  # 18,000 payable, 2,000 retained
        prime = s.prime_bill("30000")  # 27,000 receivable, invoiced today, due in 30 days (default terms)
        c.commitments.close(cmt["id"], actor="owner")
        c.approve_and_execute("retainage.release", cmt["id"], period_id="P1")  # 2,000 retainage now payable
        invoice = dt.date.fromisoformat(prime["invoice_date"])
        due = dt.date.fromisoformat(prime["due_date"])
        self.assertEqual((due - invoice).days, 30)
        # the AP bill is aged from its own due date when the bills subledger dates it, else from its created date
        ap_bill = next(it for it in c.bills.ap_open_items()["items"] if it.get("bill_id") == bill["id"])
        ap_basis = dt.date.fromisoformat((ap_bill.get("due_date") or bill["created_at"])[:10])
        bill_date = dt.date.fromisoformat((ap_bill.get("invoice_date") or bill["created_at"])[:10])
        for offset, bucket in ((-31, "after_as_of"), (-30, "current"), (-1, "current"), (0, "current"), (1, "1_30"), (30, "1_30"), (31, "31_60"),
                               (60, "31_60"), (61, "61_90"), (90, "61_90"), (91, "over_90"), (400, "over_90")):
            as_of = due + dt.timedelta(days=offset)
            ag = cl.aging(as_of.isoformat())
            ap, ar = ag["ap"], ag["ar"]
            self.assertEqual(ag["buckets"], list(BUCKETS))
            # AR: the prime bill is aged from its due date
            self.assertEqual((ar["total"], ar["subledger_total"]), ("27000.00", "27000.00"))
            self.assertTrue(ar["ties_to_subledger"] and ar["reconciled"])
            self.assertEqual(set(ar["buckets"]), set(BUCKETS))
            item = ar["items"][0]
            self.assertEqual((item["ref"], item["bucket"], item["open"], item["due_date"]), (prime["id"], bucket, "27000.00", prime["due_date"]))
            if bucket == "after_as_of":  # dated after as_of: never aged, never current
                self.assertEqual((item["days_past_due"], item["basis"], ar["aged_total"], ar["after_as_of"]), (None, None, "0.00", "27000.00"))
            else:
                self.assertEqual((item["days_past_due"], item["basis"], item["days"]), (max(0, offset), "due_date", offset + 30))
                self.assertEqual(ar["buckets"][bucket], "27000.00")
                self.assertEqual(sum(D(v) for v in ar["buckets"].values()), D("27000.00"))
            # AP ties the same way, whichever basis its items carry
            self.assertEqual((ap["total"], ap["subledger_total"]), ("20000.00", "20000.00"))
            self.assertTrue(ap["ties_to_subledger"] and ap["reconciled"])
            self.assertEqual(sum(D(v) for v in ap["buckets"].values()) + D(ap["after_as_of"]) + D(ap["undated"]), D("20000.00"))
            bill_item = next(it for it in ap["items"] if it["ref"] == bill["id"])
            if as_of < bill_date:
                self.assertEqual(bill_item["bucket"], "after_as_of")
            else:
                self.assertEqual((bill_item["bucket"], bill_item["open"]), (expected_bucket((as_of - ap_basis).days), "18000.00"))
                self.assertEqual(bill_item["basis"], "due_date" if ap_bill.get("due_date") else "document_date")
            self.assertTrue(any(it["kind"] == "retainage_release" and it["open"] == "2000.00" for it in ap["items"]))
            self.assertEqual(ag["warning"] is not None, as_of < dt.date.fromisoformat(prime["created_at"][:10]))  # a historical as_of is flagged
        for bad in ("2026-02-30", "2026/10/01", 20261001, ""):
            with self.assertRaises(CloseError):
                cl.aging(bad)

    def test_aging_uses_each_items_due_date_and_falls_back_to_document_dates(self):
        """Items carrying a due date (AP from the bills subledger, AR from any source) are
        aged from it; items without one from their invoice date, else their created date,
        as if due that day; an item nothing dates is undated, never current."""
        s = Scenario()
        cl = s.close
        as_of = "2027-03-31"
        ap_rows = [
            {"kind": "supplier_bill", "bill_id": "bil_due", "supplier_id": "sup", "sequence": 1, "invoice_date": "2027-01-15", "due_date": "2027-02-14", "open": "100.00"},
            {"kind": "supplier_bill", "bill_id": "bil_fresh", "supplier_id": "sup", "sequence": 2, "invoice_date": "2027-03-20", "due_date": "2027-04-19", "open": "50.00"},
            {"kind": "supplier_bill", "bill_id": "bil_undue", "supplier_id": "sup", "sequence": 3, "created_at": "2027-03-01T08:00:00Z", "open": "25.00"},
            {"kind": "supplier_bill", "bill_id": "bil_later", "supplier_id": "sup", "sequence": 4, "invoice_date": "2027-04-02", "due_date": "2027-05-02", "open": "10.00"},
        ]
        ar_rows = [
            {"source": "prime_bill", "kind": "prime_bill_like", "id": "ar_due", "customer_id": "cus", "invoice_date": "2026-11-01", "due_date": "2026-12-01", "open": "1000.00"},
            {"source": "labor", "kind": "labor_like", "id": "ar_invoice_only", "customer_id": "cus", "invoice_date": "2027-02-27", "open": "200.00"},
            {"source": "reimbursement", "kind": "reimb_like", "id": "ar_created_only", "customer_id": "cus", "created_at": "2027-03-31T23:00:00Z", "open": "30.00"},
            {"source": "mystery", "kind": "mystery", "id": "ar_undated", "customer_id": "cus", "open": "7.00"},
        ]
        ap_total, ar_total = "185.00", "1237.00"
        with mock.patch.object(s.c.bills, "ap_open_items", return_value={"items": ap_rows, "subledger_total": ap_total, "control_balance": ap_total, "reconciled": True}), \
             mock.patch.object(s.c.receivables, "ar_open_items", return_value={"items": ar_rows, "subledger_total": ar_total, "control_balance": ar_total, "reconciled": True}):
            ag = cl.aging(as_of)
        ap = {it["ref"]: (it["basis"], it["days_past_due"], it["bucket"]) for it in ag["ap"]["items"]}
        self.assertEqual(ap, {
            "bil_due": ("due_date", 45, "31_60"),           # 2027-02-14 to 2027-03-31
            "bil_fresh": ("due_date", 0, "current"),        # not yet due
            "bil_undue": ("document_date", 30, "1_30"),     # no due date: aged from its created date
            "bil_later": (None, None, "after_as_of"),       # invoiced after as_of
        })
        self.assertEqual(ag["ap"]["buckets"], {"current": "50.00", "1_30": "25.00", "31_60": "100.00", "61_90": "0.00", "over_90": "0.00"})
        self.assertEqual((ag["ap"]["after_as_of"], ag["ap"]["undated"], ag["ap"]["total"], ag["ap"]["ties_to_subledger"]), ("10.00", "0.00", "185.00", True))
        ar = {it["ref"]: (it["basis"], it["days_past_due"], it["bucket"]) for it in ag["ar"]["items"]}
        self.assertEqual(ar, {
            "ar_due": ("due_date", 120, "over_90"),
            "ar_invoice_only": ("document_date", 32, "31_60"),
            "ar_created_only": ("document_date", 0, "current"),
            "ar_undated": (None, None, "undated"),
        })
        self.assertEqual(ag["ar"]["buckets"], {"current": "30.00", "1_30": "0.00", "31_60": "200.00", "61_90": "0.00", "over_90": "1000.00"})
        self.assertEqual((ag["ar"]["undated"], ag["ar"]["after_as_of"], ag["ar"]["total"], ag["ar"]["ties_to_subledger"]), ("7.00", "0.00", "1237.00", True))
        self.assertIn("due date", ag["basis"])

    def test_aging_follows_credit_memos_write_offs_and_deposit_applications(self):
        """AR aging is drawn from the receivables subledger after every credit; customer
        deposits (2400) are not receivables and never appear in it."""
        s = Scenario()
        c, cl = s.c, s.close
        r = c.receivables
        today = r.today()
        r.today = lambda: today  # one calendar day for the whole scenario, even across midnight UTC
        # an explicit invoice date is never before its bill's period, so the old bill is billed
        # in an earlier period, closed before P1 (whose checklist needs every earlier period closed)
        c.open_period("P0", "P0", "2025-01-01", "2026-09-30")
        old = s.c.receivables.certify(project_id=s.pid, period_id="P0", certified_cumulative="10000", retainage_rate="0.10", actor="owner",
                                      invoice_date=(today - dt.timedelta(days=150)).isoformat())
        c.approve_and_execute("prime_bill.approve", old["id"])
        c.close_period("P0")
        old = r.get(old["id"])  # 9,000 due, 120 days past due
        doc = c.evidence.register_document(project_id=s.pid, kind="credit_memo_evidence", title="Agreed concession (synthetic)", actor="owner")
        rev = c.evidence.add_revision(document_id=doc["id"], content=b"synthetic concession letter", note="signed", actor="owner")
        memo = r.prepare_credit_memo(old["id"], "1000", "agreed concession on pay item 3", rev["content_hash"], "accountant")
        c.approve_and_execute("prime_bill.credit_memo", memo["id"], actor_role="accountant", period_id="P1")
        wo = r.prepare_write_off(old["id"], "2000", "customer insolvent for this portion (synthetic)", "controller")
        c.approve_and_execute("receivable.write_off", wo["id"], actor_role="controller", period_id="P1")
        dep = r.record_deposit(s.customer["id"], s.pid, "1500", "WIRE-DEP-AGING-1", "wire", "treasury", period_id="P1")
        app = r.prepare_deposit_application(dep["id"], old["id"], "1500", "accountant")
        c.approve_and_execute("receivable.apply_deposit", app["id"], actor_role="accountant", period_id="P1")
        self.assertEqual(r.get(old["id"])["open"], "4500.00")  # 9,000 - 1,000 - 2,000 - 1,500
        ag = cl.aging(today.isoformat())
        self.assertEqual((ag["ar"]["total"], ag["ar"]["subledger_total"], ag["ar"]["ties_to_subledger"], ag["ar"]["reconciled"]), ("4500.00", "4500.00", True, True))
        self.assertEqual(ag["ar"]["buckets"], {"current": "0.00", "1_30": "0.00", "31_60": "0.00", "61_90": "0.00", "over_90": "4500.00"})
        self.assertEqual([(it["ref"], it["days_past_due"]) for it in ag["ar"]["items"]], [(old["id"], 120)])
        self.assertEqual(c.ledger.balance("2400"), D("0.00"))
        self.assertTrue(cl.checklist_report("P1")["all_ok"], cl.checklist_report("P1")["failing"])
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_state_shape_and_project_state(self):
        s = Scenario()
        c, cl = s.c, s.close
        st = cl.state(s.pid)
        self.assertIsNone(st["contract_value"])
        self.assertIn("contract value", st["wip_error"])
        s.wip_ready()
        st = cl.state(s.pid)
        self.assertEqual(set(st), {"project_id", "label", "contract_value", "contract_version", "contract_value_history", "checklists", "wip_period_id",
                                   "wip", "wip_error", "wip_adjustments", "wip_reconciliation", "close_runs"})
        self.assertEqual((st["contract_value"], st["contract_version"]), ("150000.00", 1))
        self.assertEqual(set(st["checklists"]), {"P1", "P2"})
        self.assertTrue(st["checklists"]["P1"]["all_ok"])
        self.assertEqual(st["wip_period_id"], "P2")  # latest open period, cumulative through it
        self.assertEqual((st["wip"]["percent_complete"], st["wip"]["over_under"]), ("0.4500", "-7500.00"))
        self.assertIsNone(st["wip_error"])
        self.assertTrue(st["wip_reconciliation"]["reconciled"])
        self.assertEqual(st["label"], "SHADOW - not authoritative")
        json.dumps(st)
        c.approve_and_execute("close.close_period", "P1")
        st = cl.state(s.pid)
        self.assertEqual(set(st["checklists"]), {"P2"})
        self.assertEqual([r["action"] for r in st["close_runs"]], ["close"])
        full = c.project_state(s.pid)
        self.assertIn(PLUGIN_NAME, full)
        json.dumps(full, default=str)

    def test_checklist_shape_with_every_registered_plugin(self):
        s = Scenario(isolate=False)
        checks = s.close.checklist("P1")
        names = [ch["check"] for ch in checks]
        for core in ("trial_balance_balanced", "ap_reconciled", "ar_reconciled", "no_draft_supplier_bills", "no_draft_prime_bills", "no_unresolved_payments", "no_draft_wip_adjustments"):
            self.assertIn(core, names)
        for ch in checks:
            self.assertEqual(set(ch), {"check", "ok", "detail", "source"})
            self.assertIsInstance(ch["ok"], bool)
            self.assertIsInstance(ch["detail"], str)
        sources = {ch["source"] for ch in checks}
        for name, plugin in s.c._plugins.items():
            if name == PLUGIN_NAME or not hasattr(plugin, "close_checks"):
                continue
            try:
                contributed = bool(plugin.close_checks("P1"))
            except Exception:
                contributed = True  # a raising hook still yields a failing check naming it
            if contributed:
                self.assertIn(name, sources)
        json.dumps(s.close.state(s.pid))

    def test_schema_tables_and_accounts(self):
        s = Scenario()
        c = s.c
        accounts = {a["code"]: a for a in c.ledger.accounts()}
        self.assertEqual((accounts["1160"]["name"], accounts["1160"]["type"]), ("Contract asset - underbillings", "asset"))
        self.assertEqual((accounts["2300"]["name"], accounts["2300"]["type"]), ("Contract liability - overbillings", "liability"))
        status = c.db.schema_status()
        names = [v["name"] for v in status["versions"]]
        self.assertIn(SCHEMA_NAME, names)
        self.assertLess(names.index(SCHEMA_NAME), names.index(GUARDS_SCHEMA_NAME))  # the guards sit after the tables they guard
        # the reopen authority entries follow, each after the objects it changes
        self.assertLess(names.index(GUARDS_SCHEMA_NAME), names.index(REOPEN_GRANTS_SCHEMA_NAME))
        self.assertLess(names.index(REOPEN_GRANTS_SCHEMA_NAME), names.index(REOPEN_GOVERNANCE_SCHEMA_NAME))
        self.assertEqual(status["pending"], [])
        tables = {r["name"] for r in c.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"close_contract_values", "close_runs", "close_wip", "close_reopen_grants"} <= tables)
        triggers = {r["name"]: r["tbl_name"] for r in c.db.query("SELECT name, tbl_name FROM sqlite_master WHERE type='trigger'")}
        self.assertNotIn("close_reopen_grants_granted_reopen_only", triggers)  # replaced: a grant is claimed while pending
        for name, table in (("close_reopen_grants_recorded_at_grant", "close_reopen_grants"), ("close_runs_reopen_needs_controller_grant", "close_runs"),
                            ("close_reopen_approval_granted_with_grant", "approvals"), ("close_periods_no_reopen_under_a_locked_period", "periods"),
                            ("close_periods_reopen_through_close_only", "periods")):
            self.assertEqual(triggers.get(name), table, name)
        self.assertIn("role_basis", {r["name"] for r in c.db.query("PRAGMA table_info(close_reopen_grants)")})
        self.assertEqual(c.ledger.trial_balance()["journal_count"], 0)

    def test_audit_export_lists_close_runs_and_wip_rows(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        closed = c.approve_and_execute("close.close_period", "P1")
        c.approve_and_execute("close.reverse_wip_adjustment", row["id"], period_id="P2")
        self.assertEqual(cl.audit_export()["reopen_grants"], [])
        # a governed controller reopen: the export carries who granted it and under which role
        reopen_ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        c.approve(reopen_ap["id"], approver="controller-1", approver_role="controller")
        reopened = c.execute(reopen_ap["id"], actor="controller-1")
        exp = cl.audit_export()
        self.assertEqual(json.loads(json.dumps(exp)), exp)  # plain JSON, money as strings
        self.assertEqual(set(exp), {"label", "posting_rule", "wip_policy", "close_runs", "reopen_grants", "wip_adjustments", "contract_values", "wip_reconciliation"})
        self.assertEqual(exp["label"], "SHADOW - not authoritative")
        self.assertEqual([(r["id"], r["action"], r["period_id"]) for r in exp["close_runs"]],
                         [(closed.result["close_run_id"], "close", "P1"), (reopened.result["close_run_id"], "reopen", "P1")])
        self.assertEqual([(g["approval_id"], g["period_id"], g["approver"], g["approver_role"], g["role_basis"]) for g in exp["reopen_grants"]],
                         [(reopen_ap["id"], "P1", "controller-1", "controller", "declared")])
        self.assertEqual(exp["close_runs"][1]["approval_id"], exp["reopen_grants"][0]["approval_id"])
        run = exp["close_runs"][0]
        self.assertTrue(run["checklist"] and all(ch["ok"] for ch in run["checklist"]))
        self.assertEqual((run["statements_hash"], run["checklist_hash"]), (hash_json(run["statements"]), hash_json(run["checklist"])))  # re-performable
        self.assertEqual(run["statements"]["balance_sheet"]["total_assets"], cl.statements("P1")["balance_sheet"]["total_assets"])
        self.assertEqual([(w["id"], w["status"], w["amount"], w["reversal_period_id"]) for w in exp["wip_adjustments"]], [(row["id"], "reversed", "7500.00", "P2")])
        self.assertEqual(hash_json(exp["wip_adjustments"][0]["inputs"]), exp["wip_adjustments"][0]["inputs_hash"])
        self.assertEqual([(v["version"], v["contract_value"]) for v in exp["contract_values"]], [(1, "150000.00")])
        self.assertTrue(exp["wip_reconciliation"][s.pid]["reconciled"])
        self.assertEqual(c.audit_export()["modules"][PLUGIN_NAME]["close_runs"][0]["id"], closed.result["close_run_id"])


class CoreSubledgerCheckTests(unittest.TestCase):
    def test_core_subledger_checks_are_listed_once_and_block_the_close(self):
        s = Scenario()
        c, cl = s.c, s.close
        cmt = s.commitment()
        s.supplier_bill(cmt, "20000")  # 2,000 retainage payable
        s.prime_bill("30000")  # 3,000 retainage receivable
        s.owner_contribution("1000")
        expected = [label for label, domain, method in CoreReconciliationChecks.CHECKS if hasattr(getattr(c, domain), method)]
        report = cl.checklist_report("P1")
        self.assertEqual([ch["check"] for ch in report["checks"] if ch["source"] == CORE_SOURCE], expected)
        names = [ch["check"] for ch in report["checks"]]
        self.assertEqual(len(names), len(set(names)), names)  # nothing is reported twice
        self.assertTrue(report["all_ok"], report["failing"])
        # the same hook registered under a second name is still reported once
        c.register_plugin("core_reconciliation_alias", c.plugin(CORE_SOURCE))
        self.assertEqual(cl.checklist_report("P1")["checks"], report["checks"])
        del c._plugins["core_reconciliation_alias"]

        # a core subledger that stops tying out fails its check (wherever the method lives),
        # makes a granted close approval stale and blocks the close
        label = CoreReconciliationChecks.CHECKS[0][0]  # retainage payable (2050)
        ap = c.request_approval("close.close_period", "P1")
        c.approve(ap["id"])
        c.bills.retainage_open_items = lambda: {"reconciled": False, "subledger_total": "2000.00", "control_balance": "2000.01"}
        try:
            report = cl.checklist_report("P1")
            self.assertEqual(report["failing"], [label])
            failing = next(ch for ch in report["checks"] if ch["check"] == label)
            self.assertEqual(failing["source"], CORE_SOURCE)
            self.assertIn("2000.01", failing["detail"])
            with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
                c.execute(ap["id"])
            self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
            with self.assertRaises(CloseError):
                c.approve_and_execute("close.close_period", "P1")
            self.assertEqual(c.ledger.period("P1")["status"], "open")
        finally:
            del c.bills.retainage_open_items

        res = c.approve_and_execute("close.close_period", "P1")
        run = cl.close_run(res.result["close_run_id"])
        self.assertEqual([ch["check"] for ch in run["checklist"] if ch["source"] == CORE_SOURCE], expected)
        st = cl.statements("P1")
        self.assertTrue(st["balance_sheet"]["balanced"])
        self.assertEqual(D(st["income_statement"]["net"]), D(st["income_statement"]["revenue"]) - D(st["income_statement"]["expense"]))
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_ar_with_labor_invoices_reconciles_in_the_checklist(self):
        s = Scenario(keep=("labor",))
        c, cl = s.c, s.close
        lab = c.plugin("labor")
        emp = c.add_party(kind="employee", name="Design Engineer")
        lab.set_rate(emp["id"], "2026-10-01", "50.00", "120.00", actor="owner")
        phase = lab.add_phase(s.pid, "DD", "Design development", "100", "6000.00", True, actor="pm")
        lab.log_time(emp["id"], s.pid, phase["id"], "2026-10-15", "8", "", actor="emp")  # cost 400.00, bill 960.00
        ts = lab.submit_timesheet(emp["id"], "P1", actor="emp")
        c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        inv = lab.prepare_invoice(s.pid, "P1", actor="pm")
        c.approve_and_execute("labor.bill", inv["id"], period_id="P1")
        prime = s.prime_bill("30000")  # 27,000 receivable + 3,000 retainage
        self.assertEqual(c.ledger.balance("1100"), D("27960.00"))

        ar = s.checks()["ar_reconciled"]
        self.assertTrue(ar["ok"], ar["detail"])
        self.assertEqual(ar["detail"], "AR subledger 27960.00 vs control 1100 27960.00")
        self.assertTrue(cl.checklist_report("P1")["all_ok"], cl.checklist_report("P1")["failing"])
        # without the labor source the same 1100 balance no longer ties
        del c._plugins["labor"]
        try:
            ar = s.checks()["ar_reconciled"]
            self.assertFalse(ar["ok"])
            self.assertEqual(ar["detail"], "AR subledger 27000.00 vs control 1100 27960.00")
        finally:
            c.register_plugin("labor", lab)

        # WIP and statements count the labor cost (5300) and fee revenue (4100)
        s.commitment()  # forecast at completion 100,000
        cl.set_contract_value(s.pid, "100000", actor="owner")
        w = cl.wip(s.pid, "P1")
        self.assertEqual((w["cost_to_date"], w["percent_complete"], w["earned_revenue"], w["billed_to_date"], w["over_under"], w["position"]),
                         ("400.00", "0.0040", "400.00", "30960.00", "30560.00", "overbilled"))
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        c.approve_and_execute("close.post_wip_adjustment", row["id"], period_id="P1")
        st = cl.statements("P1")
        inc = st["income_statement"]
        self.assertEqual((inc["revenue"], inc["expense"], inc["net"]), ("400.00", "400.00", "0.00"))
        self.assertEqual({ln["code"]: ln["amount"] for ln in inc["revenue_lines"]}, {"4000": "-560.00", "4100": "960.00"})
        bs = st["balance_sheet"]
        self.assertEqual({ln["code"]: ln["amount"] for ln in bs["assets"]}, {"1100": "27960.00", "1150": "3000.00"})
        self.assertEqual({ln["code"]: ln["amount"] for ln in bs["liabilities"]}, {"2200": "400.00", "2300": "30560.00"})
        self.assertTrue(bs["balanced"])

        report = cl.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        res = c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(res.result["status"], "closed")
        aging = cl.aging(prime["created_at"][:10])
        self.assertEqual((aging["ar"]["total"], aging["ar"]["subledger_total"], aging["ar"]["ties_to_subledger"]), ("27960.00", "27960.00", True))
        self.assertEqual(sorted((it["kind"], it["ref"], it["open"]) for it in aging["ar"]["items"]),
                         sorted([("prime_bill", prime["id"], "27000.00"), ("labor_invoice", inv["id"], "960.00")]))
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])


class GovernedReopenTests(unittest.TestCase):
    def test_reopen_runs_only_against_its_own_consumed_approval(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.owner_contribution("100")
        closed = c.approve_and_execute("close.close_period", "P1")
        close_approval = cl.close_run(closed.result["close_run_id"])["approval_id"]

        # a direct call with a fabricated, empty or foreign (consumed close) approval reopens nothing
        for ref in ("apr_fabricated", "", close_approval):
            with self.subTest(ref=ref), self.assertRaises(CloseError):
                cl.apply("close.reopen_period", "P1", approval_id=ref, manifest={}, actor="x", period_id=None)
        # nor does the ledger take a bare reference
        with self.assertRaises((RuntimeError, sqlite3.DatabaseError)):
            c.ledger.reopen_period("P1", actor="x", approval_ref="apr_fabricated")
        self.assertEqual(c.ledger.period("P1")["status"], "closed")

        # a granted but not yet consumed reopen approval is not enough either
        ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        with self.assertRaises(RoleNotAuthorized):  # a project role cannot grant it
            c.approve(ap["id"], approver="pm-user", approver_role="pm")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        with self.assertRaises(CloseError):
            cl.apply("close.reopen_period", "P1", approval_id=ap["id"], manifest=ap["manifest"], actor="controller", period_id=None)
        self.assertEqual(c.ledger.period("P1")["status"], "closed")

        # the governed path consumes it and reopens, once
        res = c.execute(ap["id"], actor="controller")
        self.assertEqual(res.result["status"], "open")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "consumed")
        run = cl.close_run(res.result["close_run_id"])
        self.assertEqual((run["action"], run["approval_id"], run["status_before"], run["status_after"]), ("reopen", ap["id"], "closed", "open"))
        self.assertTrue(c.execute(ap["id"], actor="controller").replayed)  # the replay returns the stored result
        c.approve_and_execute("close.close_period", "P1")
        with self.assertRaises(ApprovalConsumed):  # the consumed approval cannot reopen the period a second time
            c.execute(ap["id"], actor="controller", op_id="reopen-again")
        with self.assertRaises(CloseError):
            cl.apply("close.reopen_period", "P1", approval_id=ap["id"], manifest=ap["manifest"], actor="controller", period_id=None)
        self.assertEqual(c.ledger.period("P1")["status"], "closed")
        self.assertEqual([r["action"] for r in cl.close_runs("P1")], ["close", "reopen", "close"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_database_guards_on_close_runs_and_wip_postings(self):
        s = Scenario()
        c, cl = s.c, s.close
        s.wip_ready()
        run_sql = ("INSERT INTO close_runs (id, period_id, action, status_before, status_after, approval_id, actor, total_debit, total_credit, journal_count, created_at) "
                   "VALUES (?, ?, ?, 'open', 'closed', ?, 'raw', '0.00', '0.00', 0, 't')")
        row = cl.prepare_wip_adjustment(s.pid, "P1", actor="owner")
        post_ap = c.request_approval("close.post_wip_adjustment", row["id"])
        c.approve(post_ap["id"])  # granted, not consumed
        for approval_id in (None, "apr_fabricated", post_ap["id"]):
            with self.subTest(approval_id=approval_id), self.assertRaisesRegex(sqlite3.IntegrityError, "consumed close approval"):
                c.db.execute(run_sql, ("crun_raw", "P1", "close", approval_id))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "consumed close.post_wip_adjustment approval"):
            c.db.execute("UPDATE close_wip SET status='posted', approval_id=?, version=version+1 WHERE id=?", (post_ap["id"], row["id"]))
        self.assertEqual(c.ledger.balance("1160"), D("0.00"))
        c.execute(post_ap["id"], period_id="P1")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "consumed close.reverse_wip_adjustment approval"):
            c.db.execute("UPDATE close_wip SET status='reversed', reversal_approval_id=?, version=version+1 WHERE id=?", (post_ap["id"], row["id"]))
        res = c.approve_and_execute("close.close_period", "P1")
        used = cl.close_run(res.result["close_run_id"])["approval_id"]
        with self.assertRaises(sqlite3.IntegrityError):  # a consumed close approval yields one run, not two
            c.db.execute(run_sql, ("crun_raw2", "P1", "close", used))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "consumed close approval"):  # nor a run of another action or period
            c.db.execute(run_sql, ("crun_raw3", "P2", "close", used))
        self.assertEqual([r["action"] for r in cl.close_runs()], ["close"])
        self.assertEqual(cl.wip_adjustment(row["id"])["status"], "posted")
        self.assertTrue(c.ledger.trial_balance()["balanced"])


RAW_REOPEN = "UPDATE periods SET status='open', closed_at=NULL, closed_by=NULL, reopen_approval_id=? WHERE id=?"
GRANT_SQL = "INSERT INTO close_reopen_grants (approval_id, period_id, approver, approver_role, granted_at, role_basis) VALUES (?,?,?,?,?,?)"


class ReopenAuthorityTests(unittest.TestCase):
    """Who may grant a reopen, what is recorded about it, and the database paths around it."""

    def closed_p1(self):
        s = Scenario()
        s.owner_contribution("1000")
        s.c.approve_and_execute("close.close_period", "P1")
        return s, s.c, s.close

    def test_grant_role_is_recorded_and_an_accountant_cannot_grant(self):
        s, c, cl = self.closed_p1()
        ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        with self.assertRaises(ReopenAuthorityError):  # the core lets an accountant approve a reopen; this module does not
            c.approve(ap["id"], approver="accountant-amy", approver_role="accountant")
        with self.assertRaises(RoleNotAuthorized):  # a project role has no reopen authority at all
            c.approve(ap["id"], approver="pm-paul", approver_role="pm")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        self.assertIsNone(cl.reopen_grant(ap["id"]))
        self.assertEqual([e for e in c.audit.entries(entity_type="approval", entity_id=ap["id"]) if e["action"] == "close.reopen_grant_recorded"], [])

        granted = c.approve(ap["id"], approver="controller-1", approver_role="controller")
        self.assertEqual((granted["status"], granted["approver"]), ("granted", "controller-1"))
        g = cl.reopen_grant(ap["id"])
        self.assertEqual((g["period_id"], g["approver"], g["approver_role"], g["role_basis"]), ("P1", "controller-1", "controller", "declared"))
        res = c.execute(ap["id"], actor="controller-1")
        self.assertEqual((res.result["status"], res.result["granted_by"], res.result["granted_as"], res.result["role_basis"]),
                         ("open", "controller-1", "controller", "declared"))

        # approve_and_execute names no approver role: the grant is recorded under the core's default
        # approver role and says so, rather than passing for a declared owner or controller grant
        c.approve_and_execute("close.close_period", "P1")
        res = c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="accountant-bob")
        self.assertEqual((res.result["granted_by"], res.result["granted_as"], res.result["role_basis"]), ("accountant-bob", "owner", "core_default"))
        self.assertEqual([(r["approver"], r["approver_role"], r["role_basis"]) for r in cl.reopen_grants("P1")],
                         [("controller-1", "controller", "declared"), ("accountant-bob", "owner", "core_default")])
        payloads = [json.loads(e["payload_json"]) for e in c.audit.entries() if e["action"] == "close.reopen_grant_recorded"]
        self.assertEqual([(p["period_id"], p["approver_role"], p["role_basis"]) for p in payloads], [("P1", "controller", "declared"), ("P1", "owner", "core_default")])
        reopened = [json.loads(e["payload_json"]) for e in c.audit.entries(entity_type="accounting_period", entity_id="P1") if e["action"] == "close.period_reopened"]
        self.assertEqual([(p["granted_by"], p["granted_as"], p["role_basis"]) for p in reopened],
                         [("controller-1", "controller", "declared"), ("accountant-bob", "owner", "core_default")])
        for sql in ("UPDATE close_reopen_grants SET approver_role='controller'", "DELETE FROM close_reopen_grants"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                c.db.execute(sql)
        self.assertEqual([r["action"] for r in cl.close_runs("P1")], ["close", "reopen", "close", "reopen"])
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_an_approval_granted_around_cipher_approve_never_reopens(self):
        s, c, cl = self.closed_p1()
        ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        # it cannot even be granted outside Cipher.approve: not through Approvals.grant, not by a raw UPDATE
        with self.assertRaisesRegex(sqlite3.IntegrityError, "granted only through Cipher.approve"):
            c.approvals.grant(ap["id"], approver="controller")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "granted only through Cipher.approve"):
            c.db.execute("UPDATE approvals SET status='granted', approver='controller', granted_at='t' WHERE id=?", (ap["id"],))
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")

        # raw role claims: never for an accountant, never without a basis, never for another period
        for label, params, message in (
            ("accountant", (ap["id"], "P1", "accountant-amy", "accountant", "t", "declared"), "CHECK constraint"),
            ("no basis", (ap["id"], "P1", "controller", "controller", "t", None), "recorded only by Cipher.approve"),
            ("other period", (ap["id"], "P2", "controller", "controller", "t", "declared"), "recorded only by Cipher.approve"),
        ):
            with self.subTest(claim=label), self.assertRaisesRegex(sqlite3.IntegrityError, message):
                c.db.execute(GRANT_SQL, params)
        self.assertIsNone(cl.reopen_grant(ap["id"]))

        # granted properly; no second claim can be attached afterwards, nor one to an approval that is not pending
        c.approve(ap["id"], approver="controller-1", approver_role="controller")
        with self.assertRaises(sqlite3.IntegrityError):
            c.db.execute(GRANT_SQL, (ap["id"], "P1", "controller-2", "controller", "t", "declared"))
        withdrawn = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        c.reject(withdrawn["id"], approver="owner", reason="not needed")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "recorded only by Cipher.approve"):
            c.db.execute(GRANT_SQL, (withdrawn["id"], "P1", "controller", "controller", "t", "declared"))

        # consumed outside Cipher.execute: the ledger and a raw UPDATE are both refused, because
        # one of this module's approvals reopens only through its execution (the reopen run)
        c.approvals.consume(ap["id"], current_manifest=ap["manifest"], consumer="controller-1")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "only through its execution"):
            c.ledger.reopen_period("P1", actor="controller-1", approval_ref=ap["id"])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "only through its execution"):
            c.db.execute(RAW_REOPEN, (ap["id"], "P1"))
        with self.assertRaises(ApprovalConsumed):
            c.execute(ap["id"], actor="controller-1")
        self.assertEqual(c.ledger.period("P1")["status"], "closed")
        self.assertEqual(c.ledger.reopens(), [])
        self.assertEqual([r["action"] for r in cl.close_runs("P1")], ["close"])

        # the governed path still reopens, against a fresh approval, and the ledger logs that approval
        res = c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        self.assertEqual(c.ledger.period("P1")["status"], "open")
        run = cl.close_run(res.result["close_run_id"])
        self.assertEqual([r["approval_id"] for r in c.ledger.reopens("P1")], [run["approval_id"]])
        self.assertEqual(cl.reopen_grant(run["approval_id"])["period_id"], "P1")
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_no_reopen_under_a_closed_or_locked_later_period_on_any_path(self):
        s, c, cl = self.closed_p1()
        c.approve_and_execute("close.close_period", "P2")
        # a granted (controller) close approval consumed outside Cipher.execute, with a raw reopen run:
        # the closed P2 still blocks P1's reopen on the ledger and raw paths, as on the governed one
        ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
        c.approve(ap["id"], approver="controller-1", approver_role="controller")
        c.approvals.consume(ap["id"], current_manifest=ap["manifest"], consumer="controller-1")
        c.db.execute(
            "INSERT INTO close_runs (id, period_id, action, status_before, status_after, approval_id, actor, total_debit, total_credit, journal_count, created_at) "
            "VALUES ('crun_raw_reopen', 'P1', 'reopen', 'closed', 'open', ?, 'raw', '1000.00', '1000.00', 1, 't')", (ap["id"],))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "every later period is open"):
            c.db.execute(RAW_REOPEN, (ap["id"], "P1"))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "every later period is open"):
            c.ledger.reopen_period("P1", actor="controller-1", approval_ref=ap["id"])
        with self.assertRaises(CloseError):
            c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        self.assertEqual(c.ledger.period("P1")["status"], "closed")

        # P2 locked straight through the ledger while P1 is only closed: no approval the core accepts,
        # not even a fabricated non-close "*.reopen_period" one, reopens P1 under the locked P2
        c.ledger.lock_period("P2", actor="owner")
        m = build_manifest(operation="zz.reopen_period", subject_type="accounting_period", subject_id="P1", actor_role="controller", bindings={"probe": "fabricated"})
        fake = c.approvals.request(m, requested_by="probe")
        c.approvals.grant(fake["id"], approver="probe")
        c.approvals.consume(fake["id"], current_manifest=m, consumer="probe")
        for label, attempt in (("raw", lambda ref: c.db.execute(RAW_REOPEN, (ref, "P1"))),
                               ("ledger", lambda ref: c.ledger.reopen_period("P1", actor="probe", approval_ref=ref))):
            for ref in (fake["id"], ap["id"]):
                with self.subTest(path=label, approval=ref), self.assertRaisesRegex(sqlite3.IntegrityError, "later period is locked"):
                    attempt(ref)
        self.assertEqual([c.ledger.period(p)["status"] for p in ("P1", "P2")], ["closed", "locked"])
        self.assertEqual(c.ledger.reopens(), [])
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_the_grant_record_is_atomic_with_the_core_grant(self):
        s, c, cl = self.closed_p1()
        ap = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")

        def core_down(*args, **kwargs):
            raise RuntimeError("approval store unavailable")

        c.approvals.grant = core_down
        try:
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                c.approve(ap["id"], approver="controller-1", approver_role="controller")
        finally:
            del c.approvals.grant
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        self.assertIsNone(cl.reopen_grant(ap["id"]))  # the grant row rolled back with the failed core grant

        # an expired approval: the core records the expiry and refuses; no grant is recorded
        c.db.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (ap["id"],))
        with self.assertRaises(ApprovalExpired):
            c.approve(ap["id"], approver="controller-1", approver_role="controller")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "expired")
        with self.assertRaises(RuntimeError):  # no longer pending
            c.approve(ap["id"], approver="controller-1", approver_role="controller")
        self.assertEqual(cl.reopen_grants(), [])
        self.assertEqual(c.ledger.period("P1")["status"], "closed")
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_workspace_with_the_original_reopen_grants_upgrades_in_place(self):
        """A file-backed workspace that applied the first reopen-grant entry (grant row written after the core
        grant) keeps its rows and its granted reopen approval, and gains the reopen governance on reopening
        (applied catalog entries are append-only)."""
        from apps.cipher.core import db as core_db
        path = os.path.join(tempfile.mkdtemp(), "close-upgrade.sqlite")
        legacy_catalog = [entry for entry in core_db.SCHEMA_CATALOG if entry[1] != REOPEN_GOVERNANCE_SCHEMA_NAME]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy_catalog):
            old = Cipher(path)
            try:
                applied = [v["name"] for v in old.db.schema_status()["versions"]]
                self.assertIn(REOPEN_GRANTS_SCHEMA_NAME, applied)
                self.assertNotIn(REOPEN_GOVERNANCE_SCHEMA_NAME, applied)
                old.open_period("P1", "P1", "2026-10-01", "2026-10-31")
                old.close_period("P1")
                ap = old.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
                # what the original guard did: the core grant first, the grant row after it
                old.approvals.grant(ap["id"], approver="controller-1")
                old.db.execute("INSERT INTO close_reopen_grants (approval_id, period_id, approver, approver_role, granted_at) VALUES (?,?,?,?,?)",
                               (ap["id"], "P1", "controller-1", "controller", "2026-10-31T00:00:00Z"))
            finally:
                old.db.close()
        c = Cipher(path)
        try:
            status = c.db.schema_status()
            self.assertEqual(status["pending"], [])
            applied = [v["name"] for v in status["versions"] if v["applied"]]
            self.assertLess(applied.index(REOPEN_GRANTS_SCHEMA_NAME), applied.index(REOPEN_GOVERNANCE_SCHEMA_NAME))
            cl = c.plugin(PLUGIN_NAME)
            legacy = cl.reopen_grant(ap["id"])
            self.assertEqual((legacy["approver"], legacy["approver_role"], legacy["role_basis"]), ("controller-1", "controller", None))
            res = c.execute(ap["id"], actor="controller-1")  # granted before the upgrade, with its grant: it still executes
            self.assertEqual((res.result["status"], res.result["granted_as"], res.result["role_basis"]), ("open", "controller", None))
            c.close_period("P1")
            fresh = c.request_approval("close.reopen_period", "P1", actor_role="controller", requested_by="controller")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "granted only through Cipher.approve"):  # the upgraded workspace refuses the old order
                c.approvals.grant(fresh["id"], approver="controller-1")
            res = c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
            self.assertEqual((res.result["status"], res.result["role_basis"]), ("open", "core_default"))
            self.assertEqual([r["action"] for r in cl.close_runs("P1")], ["reopen", "reopen"])
            self.assertEqual(len(c.ledger.reopens("P1")), 2)
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            c.db.close()


if __name__ == "__main__":
    unittest.main()
