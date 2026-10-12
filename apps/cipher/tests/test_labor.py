"""AEC practice management (labor): golden sequence and adversarial variants."""
import json
import sqlite3
import unittest
from decimal import Decimal
from unittest import mock

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.labor import PLUGIN_NAME, SCHEMA_NAME, LaborError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher


class Scenario:
    """Fresh in-memory workspace: employee, customer, supplier, project with a billable
    (DD) and a non-billable (ADM) phase, open period P1 = October 2026."""

    def __init__(self, *, with_customer: bool = True):
        self.c = Cipher()
        self.lab = self.c.plugin(PLUGIN_NAME)
        self.emp = self.c.add_party(kind="employee", name="Design Engineer", destination="ACH-EMP-1")
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic Subcontractor")
        self.project = self.c.create_project(
            name="Synthetic WWTP design", entity="S&A Solutions LLC (synthetic)", budget="100000",
            customer_id=self.customer["id"] if with_customer else None,
        )
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.dd = self.lab.add_phase(self.project["id"], "DD", "Design development", "100", "6000.00", True, actor="pm")
        self.adm = self.lab.add_phase(self.project["id"], "ADM", "Project administration", "10", "500.00", False, actor="pm")

    def standard_rates(self, emp=None):
        emp = emp or self.emp
        self.lab.set_rate(emp["id"], "2026-10-01", "50.00", "120.00", actor="owner")
        self.lab.set_rate(emp["id"], "2026-10-16", "55.00", "130.00", actor="owner")

    def log(self, work_date, hours, *, phase=None, emp=None, project=None, note=""):
        return self.lab.log_time((emp or self.emp)["id"], (project or self.project)["id"], (phase or self.dd)["id"], work_date, hours, note, actor="emp")

    def golden_entries(self):
        self.standard_rates()
        return [self.log("2026-10-15", "8"), self.log("2026-10-16", "8"), self.log("2026-10-17", "4", phase=self.adm)]

    def approved_timesheet(self):
        entries = self.golden_entries()
        ts = self.lab.submit_timesheet(self.emp["id"], "P1", actor="emp")
        self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        return self.lab.timesheet(ts["id"]), entries

    def bal(self, code, **filters) -> Decimal:
        return self.c.ledger.balance(code, **filters)


def _assert_books_ok(test: unittest.TestCase, c: Cipher) -> None:
    test.assertTrue(c.ledger.trial_balance()["balanced"])
    test.assertTrue(c.audit.verify_chain()["ok"])


class LaborGoldenTests(unittest.TestCase):
    def test_golden_sequence(self):
        s = Scenario()
        c, lab, emp = s.c, s.lab, s.emp["id"]
        s.standard_rates()

        e1 = s.log("2026-10-15", "8")
        self.assertEqual((e1["status"], e1["hours"], e1["cost_rate"], e1["bill_rate"], e1["cost_amount"], e1["bill_amount"]),
                         ("draft", "8.00", "50.00", "120.00", "400.00", "960.00"))
        e2 = s.log("2026-10-16", "8")
        self.assertEqual((e2["cost_rate"], e2["cost_amount"], e2["bill_amount"]), ("55.00", "440.00", "1040.00"))
        e3 = s.log("2026-10-17", "4", phase=s.adm)
        self.assertEqual(e3["cost_amount"], "220.00")
        self.assertFalse(e3["billable"])
        # 25 hours in a day are rejected, whether in one entry or across entries
        with self.assertRaises(LaborError):
            s.log("2026-10-15", "17")
        with self.assertRaises(LaborError):
            s.log("2026-10-18", "25")
        self.assertEqual(s.bal("5300"), Decimal("0.00"))  # nothing posts before approval

        ts = lab.submit_timesheet(emp, "P1", actor="emp")
        self.assertEqual((ts["status"], ts["version"], ts["entry_count"], ts["total_hours"], ts["total_cost"]), ("submitted", 1, 3, "20.00", "1060.00"))

        # an approval is granted; the entry can no longer be edited because it is not a draft
        ap = c.request_approval("labor.approve_timesheet", ts["id"])
        c.approve(ap["id"])
        self.assertEqual(ap["manifest"]["amounts"]["total_cost"], "1060.00")
        with self.assertRaises(LaborError):
            lab.update_entry(e1["id"], actor="emp", note="late edit")
        with self.assertRaises(LaborError):
            lab.delete_entry(e1["id"], actor="emp")

        # reject + edit + resubmit: the old granted approval is stale
        lab.reject_timesheet(ts["id"], "add the task reference to the 15th", actor="pm")
        self.assertEqual(lab.entry(e1["id"])["status"], "draft")
        lab.update_entry(e1["id"], actor="emp", note="task 3.2 pump station layout")
        ts2 = lab.submit_timesheet(emp, "P1", actor="emp")
        self.assertEqual(ts2["id"], ts["id"])
        self.assertEqual(ts2["version"], 2)
        self.assertNotEqual(ts2["content_hash"], ts["content_hash"])
        self.assertEqual(ts2["total_cost"], "1060.00")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            c.execute(ap["id"], period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(s.bal("5300"), Decimal("0.00"))

        res = c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        self.assertEqual((res.result["status"], res.result["total_cost"], res.result["total_hours"]), ("approved", "1060.00", "20.00"))
        self.assertEqual(s.bal("5300"), Decimal("1060.00"))
        self.assertEqual(s.bal("5300", project_id=s.project["id"]), Decimal("1060.00"))
        self.assertEqual(s.bal("2200"), Decimal("1060.00"))
        self.assertEqual(s.bal("2200", party_id=emp), Decimal("1060.00"))
        self.assertEqual({lab.entry(e["id"])["status"] for e in (e1, e2, e3)}, {"approved"})

        # payroll above the accrual is rejected; payroll settles the accrual only
        with self.assertRaises(LaborError):
            lab.record_payroll("P1", emp, "1060.01", "PR-2026-10", actor="payroll")
        pr = lab.record_payroll("P1", emp, "1060.00", "PR-2026-10", actor="payroll")
        res = c.approve_and_execute("labor.post_payroll", pr["id"], actor_role="treasury", period_id="P1")
        self.assertEqual(res.result["status"], "posted")
        self.assertEqual(s.bal("2200"), Decimal("0.00"))
        self.assertEqual(s.bal("5300"), Decimal("1060.00"))
        self.assertEqual(s.bal("1000"), Decimal("-1060.00"))
        with self.assertRaisesRegex(LaborError, "reference"):
            lab.record_payroll("P1", emp, "1.00", "PR-2026-10", actor="payroll")

        # T&M invoice: billable phases only, at bill amounts
        inv = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        self.assertEqual((inv["status"], inv["total"], inv["line_count"], inv["total_hours"]), ("draft", "2000.00", 2, "16.00"))
        self.assertEqual({ln["entry_id"] for ln in inv["lines"]}, {e1["id"], e2["id"]})
        res = c.approve_and_execute("labor.bill", inv["id"], period_id="P1")
        self.assertEqual((res.result["status"], res.result["total"]), ("billed", "2000.00"))
        self.assertEqual(s.bal("1100"), Decimal("2000.00"))
        self.assertEqual(s.bal("1100", party_id=s.customer["id"]), Decimal("2000.00"))
        self.assertEqual(s.bal("4100"), Decimal("2000.00"))
        self.assertEqual(lab.ar_open_items()["subledger_total"], "2000.00")
        self.assertEqual(lab.entry(e1["id"])["status"], "billed")
        self.assertEqual(lab.entry(e3["id"])["status"], "approved")
        with self.assertRaises(LaborError):
            lab.prepare_invoice(s.project["id"], "P1", actor="pm")

        u = lab.utilization("P1")
        self.assertEqual(len(u["employees"]), 1)
        row = u["employees"][0]
        self.assertEqual((row["total_hours"], row["billable_hours"], row["utilization_percent"]), ("20.00", "16.00", "80.00"))

        self.assertTrue(all(chk["ok"] for chk in lab.close_checks("P1")))
        _assert_books_ok(self, c)


class LaborRateTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.lab = self.s.lab

    def test_effective_dated_rate_lookup(self):
        self.s.standard_rates()
        emp = self.s.emp["id"]
        self.assertEqual(self.lab.rate_for(emp, "2026-10-01")["cost_rate"], "50.00")
        self.assertEqual(self.lab.rate_for(emp, "2026-10-15")["bill_rate"], "120.00")
        self.assertEqual(self.lab.rate_for(emp, "2026-10-16")["cost_rate"], "55.00")
        self.assertEqual(self.lab.rate_for(emp, "2026-12-31")["bill_rate"], "130.00")
        with self.assertRaises(LaborError):
            self.lab.rate_for(emp, "2026-09-30")
        with self.assertRaises(LaborError):
            self.s.log("2026-09-30", "8")  # no rate effective that day
        other = self.s.c.add_party(kind="employee", name="Unrated Drafter")
        with self.assertRaises(LaborError):
            self.s.log("2026-10-15", "8", emp=other)

    def test_duplicate_and_invalid_rates_rejected(self):
        emp = self.s.emp["id"]
        self.lab.set_rate(emp, "2026-10-01", "50.00", "120.00", actor="owner")
        with self.assertRaises(LaborError):
            self.lab.set_rate(emp, "2026-10-01", "51.00", "121.00", actor="owner")
        bad = [
            (self.s.supplier["id"], "2026-10-05", "50.00", "120.00"),   # not an employee
            ("pty_missing", "2026-10-05", "50.00", "120.00"),
            (emp, "2026-13-01", "50.00", "120.00"),
            (emp, "10/05/2026", "50.00", "120.00"),
            (emp, "2026-10-05", "0.00", "120.00"),                      # cost rate must be positive
            (emp, "2026-10-05", "50.00", "-1.00"),
            (emp, "2026-10-05", 50.0, "120.00"),                         # binary float
            (emp, "2026-10-05", "50.005", "120.00"),                     # sub-cent
            (emp, "2026-10-05", "abc", "120.00"),
            (emp, "2026-10-05", "9999999999999999999999999.99", "120.00"),  # would overflow exact pricing
            (emp, "2026-10-05", "50.00", "1000000.01"),                  # above the per-hour range limit
        ]
        for args in bad:
            with self.assertRaises(LaborError, msg=repr(args)):
                self.lab.set_rate(*args, actor="owner")
        self.assertEqual(len(self.lab.rates(emp)), 1)

    def test_rate_immutable_once_used(self):
        emp = self.s.emp["id"]
        r = self.lab.set_rate(emp, "2026-10-01", "50.00", "120.00", actor="owner")
        self.assertFalse(r["used"])
        r = self.lab.update_rate(r["id"], actor="owner", cost_rate="52.00")
        self.assertEqual((r["cost_rate"], r["version"]), ("52.00", 2))
        with self.assertRaises(LaborError):
            self.lab.update_rate(r["id"], actor="owner")
        e = self.s.log("2026-10-15", "8")
        self.assertEqual(e["cost_amount"], "416.00")
        self.assertTrue(self.lab.rate(r["id"])["used"])
        with self.assertRaises(LaborError):
            self.lab.update_rate(r["id"], actor="owner", cost_rate="60.00")
        # voiding the only entry does NOT free the rate: the void entry still shows it was priced at 52.00
        self.lab.delete_entry(e["id"], actor="emp", reason="logged in error")
        with self.assertRaises(LaborError):
            self.lab.update_rate(r["id"], actor="owner", cost_rate="53.00")
        db = self.s.c.db
        for sql in (
            "UPDATE labor_rates SET cost_rate='1.00' WHERE id=?",
            "UPDATE labor_rates SET used=0 WHERE id=?",                    # the used flag is sticky
            "UPDATE labor_rates SET effective_from='2026-10-02' WHERE id=?",  # the effective date never changes
            "DELETE FROM labor_rates WHERE id=?",
        ):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql, (r["id"],))
        self.assertEqual((self.lab.rate(r["id"])["cost_rate"], self.lab.entry(e["id"])["cost_rate"]), ("52.00", "52.00"))

        # a rate whose only draft was re-rated onto a newer rate stays frozen too
        moved = self.s.log("2026-10-20", "8")
        b = self.lab.set_rate(emp, "2026-10-18", "60.00", "140.00", actor="owner")
        c = self.lab.set_rate(emp, "2026-10-19", "61.00", "141.00", actor="owner")
        self.assertEqual(self.lab.entry(moved["id"])["rate_id"], c["id"])
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM labor_entries WHERE rate_id=?", (b["id"],)), 0)
        with self.assertRaises(LaborError):
            self.lab.update_rate(b["id"], actor="owner", cost_rate="59.00")
        # a rate no time was ever priced at can still be corrected
        d = self.lab.set_rate(emp, "2026-12-01", "70.00", "150.00", actor="owner")
        d = self.lab.update_rate(d["id"], actor="owner", bill_rate="155.00")
        self.assertEqual((d["bill_rate"], d["version"], d["used"]), ("155.00", 2, False))

    def test_retroactive_rate_rerates_drafts_refuses_submitted_and_keeps_approved(self):
        s = self.s
        emp = s.emp["id"]
        self.lab.set_rate(emp, "2026-10-01", "50.00", "120.00", actor="owner")
        early = s.log("2026-10-10", "8")
        late = s.log("2026-10-20", "8")
        self.assertEqual(late["cost_amount"], "400.00")
        self.lab.set_rate(emp, "2026-10-18", "60.00", "140.00", actor="owner")
        late = self.lab.entry(late["id"])
        self.assertEqual((late["cost_rate"], late["cost_amount"], late["bill_amount"], late["version"]), ("60.00", "480.00", "1120.00", 2))
        self.assertEqual(self.lab.entry(early["id"])["version"], 1)  # dated before the new rate: untouched

        ts = self.lab.submit_timesheet(emp, "P1", actor="emp")
        with self.assertRaisesRegex(LaborError, "reject"):
            self.lab.set_rate(emp, "2026-10-19", "70.00", "150.00", actor="owner")  # would govern submitted time on the 20th
        with self.assertRaises(LaborError):
            self.lab.set_rate(emp, "2026-10-05", "70.00", "150.00", actor="owner")  # would govern the 10th
        self.lab.set_rate(emp, "2026-11-01", "70.00", "150.00", actor="owner")  # prospective: fine

        # once approved, the cost is posted: a backdated raise is accepted and applies to new time only
        s.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        raise_ = self.lab.set_rate(emp, "2026-10-19", "65.00", "150.00", actor="owner")
        self.assertEqual(self.lab.rate_for(emp, "2026-10-20")["id"], raise_["id"])
        kept = self.lab.entry(late["id"])
        self.assertEqual((kept["status"], kept["cost_rate"], kept["cost_amount"]), ("approved", "60.00", "480.00"))
        new = s.log("2026-10-21", "2")
        self.assertEqual((new["cost_rate"], new["cost_amount"], new["bill_amount"]), ("65.00", "130.00", "300.00"))
        self.assertEqual([r["effective_from"] for r in self.lab.rates(emp)], ["2026-10-01", "2026-10-18", "2026-10-19", "2026-11-01"])
        self.assertEqual(s.bal("5300"), Decimal("880.00"))
        _assert_books_ok(self, s.c)


class LaborPhaseTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.lab = self.s.lab

    def test_phase_code_unique_per_project_and_validated(self):
        pid = self.s.project["id"]
        with self.assertRaises(LaborError):
            self.lab.add_phase(pid, "DD", "Duplicate", "1", "1.00", actor="pm")
        with self.assertRaises(LaborError):
            self.lab.add_phase(pid, "dd", "Duplicate, other case", "1", "1.00", actor="pm")
        other = self.s.c.create_project(name="Other", entity="E", budget="1000", customer_id=self.s.customer["id"])
        ph = self.lab.add_phase(other["id"], "DD", "Same code, other project", "5", "250.00", actor="pm")
        self.assertTrue(ph["billable"])
        bad = [
            dict(project_id="prj_missing", code="X1", name="n", fee_budget_hours="1", fee_budget_amount="1.00"),
            dict(project_id=pid, code="  ", name="n", fee_budget_hours="1", fee_budget_amount="1.00"),
            dict(project_id=pid, code="X2", name="", fee_budget_hours="1", fee_budget_amount="1.00"),
            dict(project_id=pid, code="X3", name="n", fee_budget_hours="-1", fee_budget_amount="1.00"),
            dict(project_id=pid, code="X4", name="n", fee_budget_hours="1", fee_budget_amount="100.505"),
            dict(project_id=pid, code="X5", name="n", fee_budget_hours="1", fee_budget_amount="1.00", billable="yes"),
            dict(project_id=pid, code="X6", name="n", fee_budget_hours="1e30", fee_budget_amount="1.00"),
            dict(project_id=pid, code="X7", name="n", fee_budget_hours="1", fee_budget_amount="1000000000000.01"),
        ]
        for kwargs in bad:
            with self.assertRaises(LaborError, msg=repr(kwargs)):
                self.lab.add_phase(actor="pm", **kwargs)
        self.assertEqual([p["code"] for p in self.lab.phases(pid)], ["ADM", "DD"])

    def test_update_phase_budget_only(self):
        ph = self.lab.update_phase(self.s.adm["id"], actor="pm", fee_budget_hours="12.5", fee_budget_amount="650.00", name="PM and admin")
        self.assertEqual((ph["fee_budget_hours"], ph["fee_budget_amount"], ph["name"], ph["version"], ph["billable"]), ("12.50", "650.00", "PM and admin", 2, False))
        with self.assertRaises(LaborError):
            self.lab.update_phase(self.s.adm["id"], actor="pm")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.c.db.execute("UPDATE labor_phases SET billable=1 WHERE id=?", (self.s.adm["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.c.db.execute("DELETE FROM labor_phases WHERE id=?", (self.s.adm["id"],))
        self.assertFalse(self.lab.phase(self.s.adm["id"])["billable"])


class LaborTimeEntryTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.lab = self.s.lab
        self.s.standard_rates()

    def test_log_time_validation(self):
        other = self.s.c.create_project(name="Other", entity="E", budget="1000")
        foreign_phase = self.lab.add_phase(other["id"], "PD", "Predesign", "10", "1000.00", actor="pm")
        bad_hours = ["0", "-1", 8.0, "24.01", "abc", "7.333", True]
        for h in bad_hours:
            with self.assertRaises(LaborError, msg=repr(h)):
                self.s.log("2026-10-15", h)
        with self.assertRaises(LaborError):
            self.s.log("2026-10-32", "8")
        with self.assertRaises(LaborError):
            self.s.log("15-10-2026", "8")
        with self.assertRaises(LaborError):
            self.s.log("2026-10-15", "8", emp=self.s.supplier)
        with self.assertRaises(LaborError):
            self.s.log("2026-10-15", "8", phase=foreign_phase)  # phase of another project
        with self.assertRaises(LaborError):
            self.lab.log_time(self.s.emp["id"], self.s.project["id"], "lphs_missing", "2026-10-15", "8", actor="emp")
        with self.assertRaises(LaborError):
            self.lab.log_time(self.s.emp["id"], self.s.project["id"], self.s.dd["id"], "2026-10-15", "8", note=7, actor="emp")
        self.assertEqual(self.lab.entries(self.s.project["id"]), [])
        e = self.s.log("2026-10-15", "24")
        self.assertEqual((e["hours"], e["cost_amount"]), ("24.00", "1200.00"))
        q = self.s.log("2026-10-14", "0.25")
        self.assertEqual((q["hours"], q["cost_amount"], q["bill_amount"]), ("0.25", "12.50", "30.00"))

    def test_time_cannot_be_logged_into_a_closed_period(self):
        c = self.s.c
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        nov = self.s.log("2026-11-03", "8")
        c.close_period("P1")
        with self.assertRaisesRegex(LaborError, "P1 \\(closed\\)"):
            self.s.log("2026-10-15", "8")
        with self.assertRaises(LaborError):
            self.lab.update_entry(nov["id"], actor="emp", work_date="2026-10-30")  # nor moved into it
        self.assertEqual(self.lab.entry(nov["id"])["work_date"], "2026-11-03")
        self.s.log("2026-12-01", "4")  # no period covers December yet: allowed
        c.ledger.reopen_period("P1", actor="controller", approval_ref="ctl-reopen-002")
        self.assertEqual(self.s.log("2026-10-15", "8")["status"], "draft")

    def test_daily_cap_spans_projects_and_edits(self):
        p2 = self.s.c.create_project(name="Second project", entity="E", budget="1000", customer_id=self.s.customer["id"])
        ph2 = self.lab.add_phase(p2["id"], "DD", "Design", "50", "5000.00", actor="pm")
        a = self.s.log("2026-10-20", "10")
        b = self.s.log("2026-10-20", "14", phase=ph2, project=p2)
        with self.assertRaises(LaborError):
            self.s.log("2026-10-20", "0.25")
        with self.assertRaises(LaborError):
            self.lab.update_entry(a["id"], actor="emp", hours="10.25")
        moved = self.lab.update_entry(a["id"], actor="emp", hours="9.75")
        self.assertEqual(moved["hours"], "9.75")
        self.s.log("2026-10-20", "0.25")
        self.lab.delete_entry(b["id"], actor="emp", reason="wrong project")
        self.s.log("2026-10-20", "14")  # voided time frees the day's capacity

    def test_update_and_delete_only_while_draft(self):
        e = self.s.log("2026-10-15", "8")
        e = self.lab.update_entry(e["id"], actor="emp", hours="6")
        self.assertEqual((e["cost_amount"], e["bill_amount"], e["version"]), ("300.00", "720.00", 2))
        e = self.lab.update_entry(e["id"], actor="emp", work_date="2026-10-16")  # crosses into the 55.00 / 130.00 rate
        self.assertEqual((e["cost_rate"], e["cost_amount"], e["bill_amount"], e["version"]), ("55.00", "330.00", "780.00", 3))
        e = self.lab.update_entry(e["id"], actor="emp", phase_id=self.s.adm["id"])
        self.assertFalse(e["billable"])
        with self.assertRaises(LaborError):
            self.lab.update_entry(e["id"], actor="emp")
        other = self.s.c.create_project(name="Other", entity="E", budget="1000")
        foreign = self.lab.add_phase(other["id"], "X", "Other", "1", "1.00", actor="pm")
        with self.assertRaises(LaborError):
            self.lab.update_entry(e["id"], actor="emp", phase_id=foreign["id"])

        gone = self.lab.delete_entry(e["id"], actor="emp", reason="duplicate")
        self.assertEqual(gone["status"], "void")
        self.assertIn(e["id"], [x["id"] for x in self.lab.entries(self.s.project["id"])])  # history kept
        with self.assertRaises(LaborError):
            self.lab.update_entry(e["id"], actor="emp", hours="1")
        with self.assertRaises(LaborError):
            self.lab.delete_entry(e["id"], actor="emp")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.c.db.execute("DELETE FROM labor_entries WHERE id=?", (e["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.c.db.execute("UPDATE labor_entries SET status='draft' WHERE id=?", (e["id"],))

        f = self.s.log("2026-10-15", "8")
        self.lab.submit_timesheet(self.s.emp["id"], "P1", actor="emp")
        with self.assertRaises(LaborError):
            self.lab.update_entry(f["id"], actor="emp", hours="7")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.c.db.execute("UPDATE labor_entries SET hours='1.00' WHERE id=?", (f["id"],))
        self.assertEqual(self.lab.entry(f["id"])["hours"], "8.00")


class LaborTimesheetTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.lab = self.s.lab

    def test_submit_groups_only_the_employees_period_drafts(self):
        s = self.s
        s.standard_rates()
        emp2 = self.c.add_party(kind="employee", name="CAD Technician")
        self.lab.set_rate(emp2["id"], "2026-10-01", "35.00", "90.00", actor="owner")
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        a = s.log("2026-10-15", "8")
        b = s.log("2026-11-02", "8")
        other = s.log("2026-10-15", "6", emp=emp2)
        ts = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.assertEqual([ln["entry_id"] for ln in ts["lines"]], [a["id"]])
        self.assertEqual([e["id"] for e in ts["entries"]], [a["id"]])
        self.assertEqual(self.lab.entry(b["id"])["status"], "draft")
        self.assertEqual(self.lab.entry(other["id"])["status"], "draft")
        with self.assertRaises(LaborError):
            self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")  # nothing left to submit
        d = s.log("2026-10-20", "4")
        with self.assertRaises(LaborError):
            self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")  # previous timesheet still awaits approval
        with self.assertRaises(LaborError):
            self.lab.submit_timesheet(s.emp["id"], "P9", actor="emp")
        with self.assertRaises(LaborError):
            self.lab.submit_timesheet(s.supplier["id"], "P1", actor="emp")
        self.c.close_period("P2")
        with self.assertRaises(LaborError):
            self.lab.submit_timesheet(s.emp["id"], "P2", actor="emp")  # closed period
        self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        ts2 = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.assertNotEqual(ts2["id"], ts["id"])
        self.assertEqual([ln["entry_id"] for ln in ts2["lines"]], [d["id"]])

    def test_approval_posts_labor_cost_per_project_and_phase(self):
        s = self.s
        s.standard_rates()
        p2 = self.c.create_project(name="Second project", entity="E", budget="1000", customer_id=s.customer["id"])
        pd = self.lab.add_phase(p2["id"], "PD", "Predesign", "20", "2000.00", actor="pm")
        s.log("2026-10-15", "8")
        s.log("2026-10-17", "4", phase=s.adm)
        s.log("2026-10-16", "2", phase=pd, project=p2)
        ts = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.assertEqual(ts["total_cost"], "730.00")

        with self.assertRaises(LaborError):  # a timesheet posts in its own period only
            self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P2")
        stray = [a for a in self.c.approvals.list(status="granted") if a["subject_id"] == ts["id"]]
        self.assertEqual(len(stray), 1)

        res = self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        j = self.c.ledger.journal(res.result["journal_id"])
        self.assertEqual((j["source_type"], j["source_id"], j["source_version"], j["period_id"]), ("labor_timesheet", ts["id"], "1", "P1"))
        self.assertIsNotNone(j["approval_id"])
        debits = sorted((ln["project_id"], ln["memo"].split(":")[0], ln["debit"], ln["party_id"]) for ln in j["lines"] if ln["account_code"] == "5300")
        self.assertEqual(debits, sorted([
            (s.project["id"], "labor phase ADM", "220.00", s.emp["id"]),
            (s.project["id"], "labor phase DD", "400.00", s.emp["id"]),
            (p2["id"], "labor phase PD", "110.00", s.emp["id"]),
        ]))
        credits = [ln for ln in j["lines"] if ln["account_code"] == "2200"]
        self.assertEqual(len(credits), 1)
        self.assertEqual((credits[0]["credit"], credits[0]["party_id"]), ("730.00", s.emp["id"]))
        self.assertEqual(s.bal("5300", project_id=s.project["id"]), Decimal("620.00"))
        self.assertEqual(s.bal("5300", project_id=p2["id"]), Decimal("110.00"))
        self.assertEqual(s.bal("2200"), Decimal("730.00"))
        self.assertEqual(self.c.approvals.get(stray[0]["id"])["status"], "invalidated")  # the leftover approval cannot post again
        self.assertEqual({e["status"] for e in self.lab.entries(employee_id=s.emp["id"])}, {"approved"})
        _assert_books_ok(self, self.c)

    def test_reject_rules(self):
        s = self.s
        s.golden_entries()
        ts = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        with self.assertRaises(LaborError):
            self.lab.reject_timesheet(ts["id"], "  ", actor="pm")
        rejected = self.lab.reject_timesheet(ts["id"], "hours on the 17th belong to DD", actor="pm")
        self.assertEqual((rejected["status"], rejected["reject_reason"]), ("rejected", "hours on the 17th belong to DD"))
        self.assertEqual(rejected["entries"], [])
        with self.assertRaises(LaborError):
            self.c.request_approval("labor.approve_timesheet", ts["id"])  # nothing to approve while returned
        with self.assertRaises(LaborError):
            self.lab.reject_timesheet(ts["id"], "again", actor="pm")
        self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        with self.assertRaises(LaborError):
            self.lab.reject_timesheet(ts["id"], "too late", actor="pm")
        self.assertEqual(self.lab.timesheet(ts["id"])["version"], 2)

    def test_timesheet_manifest_bindings_alone_make_the_approval_stale(self):
        s = self.s
        e1, _, _ = s.golden_entries()
        ts = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        ap = self.c.request_approval("labor.approve_timesheet", ts["id"])
        m = ap["manifest"]
        self.assertEqual(m["amounts"], {"total_cost": "1060.00"})
        b = m["bindings"]
        self.assertEqual((b["employee_id"], b["period_id"], b["total_hours"], b["timesheet_version"], b["content_hash"], b["entry_count"]),
                         (s.emp["id"], "P1", "20.00", 1, ts["content_hash"], 3))
        self.assertEqual([(a["phase_code"], a["hours"], a["cost"]) for a in b["allocation"]], [("ADM", "4.00", "220.00"), ("DD", "16.00", "840.00")])
        self.c.approve(ap["id"])

        # switch off the eager invalidation reject_timesheet performs, so only the manifest bindings stand guard
        with mock.patch.object(self.c.approvals, "invalidate_for_subject", return_value=0):
            self.lab.reject_timesheet(ts["id"], "split the 15th", actor="pm")
            self.lab.update_entry(e1["id"], actor="emp", hours="7.5")
            ts2 = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.assertEqual((ts2["version"], ts2["total_hours"], ts2["total_cost"]), (2, "19.50", "1035.00"))
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # nothing invalidated it early
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], period_id="P1")
        stale = self.c.approvals.get(ap["id"])
        self.assertEqual(stale["status"], "invalidated")
        self.assertIn("amounts", stale["invalidated_reason"])
        self.assertIn("bindings", stale["invalidated_reason"])

        # even an unchanged resubmission is a new version the approver has not seen
        ap2 = self.c.request_approval("labor.approve_timesheet", ts["id"])
        self.c.approve(ap2["id"])
        with mock.patch.object(self.c.approvals, "invalidate_for_subject", return_value=0):
            self.lab.reject_timesheet(ts["id"], "recheck", actor="pm")
            ts3 = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.assertEqual((ts3["version"], ts3["content_hash"]), (3, ts2["content_hash"]))
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap2["id"], period_id="P1")
        self.assertEqual(s.bal("5300"), Decimal("0.00"))
        res = self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        self.assertEqual(res.result["total_cost"], "1035.00")

    def test_closed_period_blocks_timesheet_posting(self):
        s = self.s
        s.golden_entries()
        ts = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        ap = self.c.request_approval("labor.approve_timesheet", ts["id"])
        self.c.approve(ap["id"])
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(s.bal("5300"), Decimal("0.00"))
        self.assertEqual(self.lab.timesheet(ts["id"])["status"], "submitted")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # nothing was consumed
        self.c.ledger.reopen_period("P1", actor="controller", approval_ref="ctl-reopen-001")
        res = self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(res.result["total_cost"], "1060.00")
        self.assertEqual(s.bal("2200"), Decimal("1060.00"))

    def test_replay_posts_once_and_no_second_approval(self):
        s = self.s
        s.golden_entries()
        ts = self.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        ap = self.c.request_approval("labor.approve_timesheet", ts["id"])
        self.c.approve(ap["id"])
        first = self.c.execute(ap["id"], period_id="P1")
        replay = self.c.execute(ap["id"], period_id="P1")
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, first.result)
        with self.assertRaises(LaborError):
            self.c.request_approval("labor.approve_timesheet", ts["id"])
        self.assertEqual(len(self.c.ledger.journals(source_type="labor_timesheet")), 1)
        self.assertEqual(s.bal("5300"), Decimal("1060.00"))


class LaborPayrollTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c = self.s.c
        self.lab = self.s.lab
        self.emp = self.s.emp["id"]

    def test_payroll_settles_accrual_without_double_counting_cost(self):
        self.s.approved_timesheet()
        for amount, ref in (("600.00", "PR-1"), ("460.00", "PR-2")):
            p = self.lab.record_payroll("P1", self.emp, amount, ref, actor="payroll")
            self.c.approve_and_execute("labor.post_payroll", p["id"], period_id="P1")
        self.assertEqual(self.s.bal("5300"), Decimal("1060.00"))  # labor cost counted once
        self.assertEqual(self.s.bal("2200"), Decimal("0.00"))
        self.assertEqual(self.s.bal("1000"), Decimal("-1060.00"))
        payroll_journals = self.c.ledger.journals(source_type="labor_payroll")
        self.assertEqual(len(payroll_journals), 2)
        for j in payroll_journals:
            self.assertEqual({ln["account_code"] for ln in j["lines"]}, {"2200", "1000"})
        self.assertEqual(len(self.c.ledger.journals(source_type="labor_timesheet")), 1)
        self.assertEqual(self.c.ledger.income_statement()["expense"], "1060.00")
        rec = self.lab.accrued_payroll_reconciliation()
        self.assertTrue(rec["reconciled"])
        self.assertEqual((rec["items"][0]["approved_cost"], rec["items"][0]["posted_payroll"], rec["items"][0]["accrued"]), ("1060.00", "1060.00", "0.00"))
        with self.assertRaises(LaborError):
            self.lab.record_payroll("P1", self.emp, "0.01", "PR-3", actor="payroll")  # nothing left to settle
        _assert_books_ok(self, self.c)

    def test_payroll_validation_reservation_and_cancel(self):
        self.s.golden_entries()
        ts = self.lab.submit_timesheet(self.emp, "P1", actor="emp")
        with self.assertRaises(LaborError):
            self.lab.record_payroll("P1", self.emp, "100.00", "PR-EARLY", actor="payroll")  # submitted time is not yet accrued
        self.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        d1 = self.lab.record_payroll("P1", self.emp, "600.00", "PR-A", actor="payroll")
        self.assertEqual(d1["status"], "draft")
        self.assertEqual(self.s.bal("2200"), Decimal("1060.00"))  # a draft posts nothing
        with self.assertRaises(LaborError):
            self.lab.record_payroll("P1", self.emp, "500.00", "PR-B", actor="payroll")  # 1060 - 600 drafted = 460 available
        bad = [
            ("P1", self.emp, "100.00", "pr-a"),                   # duplicate reference, any case
            ("P1", self.s.supplier["id"], "100.00", "PR-C"),
            ("P1", self.emp, "0.00", "PR-D"),
            ("P1", self.emp, 100.0, "PR-E"),
            ("P9", self.emp, "100.00", "PR-F"),
            ("P1", self.emp, "100.00", "  "),
        ]
        for args in bad:
            with self.assertRaises(LaborError, msg=repr(args)):
                self.lab.record_payroll(*args, actor="payroll")

        ap = self.c.request_approval("labor.post_payroll", d1["id"], actor_role="treasury")
        self.c.approve(ap["id"])
        self.lab.cancel_payroll(d1["id"], actor="payroll", reason="wrong gross")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError, LaborError)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(LaborError):
            self.c.request_approval("labor.post_payroll", d1["id"])
        self.assertEqual(self.s.bal("2200"), Decimal("1060.00"))

        with self.assertRaisesRegex(LaborError, "never reused"):
            self.lab.record_payroll("P1", self.emp, "1060.00", "PR-A", actor="payroll")  # a canceled draft keeps its reference
        d2 = self.lab.record_payroll("P1", self.emp, "1060.00", "PR-A2", actor="payroll")  # the canceled draft released its accrual
        self.c.approve_and_execute("labor.post_payroll", d2["id"], period_id="P1")
        with self.assertRaises(LaborError):
            self.lab.cancel_payroll(d2["id"], actor="payroll")
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.db.execute("UPDATE labor_payroll SET gross_amount='1.00' WHERE id=?", (d2["id"],))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE"):  # the reference index holds even against raw SQL
            self.c.db.execute(
                "INSERT INTO labor_payroll (id, period_id, employee_id, gross_amount, reference, status, version, created_by, created_at) VALUES ('lpay_raw','P1',?,'1.00','pr-a','draft',1,'x','2026-10-12T00:00:00Z')",
                (self.emp,),
            )

    def test_payroll_approval_goes_stale_when_accrual_changes(self):
        self.s.approved_timesheet()
        d1 = self.lab.record_payroll("P1", self.emp, "500.00", "PR-A", actor="payroll")
        d2 = self.lab.record_payroll("P1", self.emp, "500.00", "PR-B", actor="payroll")
        ap1 = self.c.request_approval("labor.post_payroll", d1["id"], actor_role="treasury")
        self.c.approve(ap1["id"])
        self.c.approve_and_execute("labor.post_payroll", d2["id"], period_id="P1")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap1["id"], period_id="P1")  # the accrual it was approved against moved
        self.assertEqual(self.c.approvals.get(ap1["id"])["status"], "invalidated")
        self.assertEqual(self.lab.payroll(d1["id"])["status"], "draft")
        self.c.approve_and_execute("labor.post_payroll", d1["id"], period_id="P1")
        self.assertEqual(self.s.bal("2200"), Decimal("60.00"))
        self.assertEqual(self.lab.accrued_payroll(self.emp), Decimal("60.00"))

    def test_payroll_is_cut_off_at_its_period(self):
        c, lab, emp = self.c, self.lab, self.emp
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.s.standard_rates()
        self.s.log("2026-10-15", "8")  # 400.00, October
        self.s.log("2026-11-02", "8")  # 440.00, November (55.00 rate)
        for pid in ("P1", "P2"):
            ts = lab.submit_timesheet(emp, pid, actor="emp")
            c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id=pid)
        self.assertEqual((lab.accrued_payroll(emp), lab.accrued_payroll(emp, "P1"), lab.accrued_payroll(emp, "P2")),
                         (Decimal("840.00"), Decimal("400.00"), Decimal("840.00")))
        self.assertEqual(lab.payroll_available(emp, "P1"), Decimal("400.00"))

        # October payroll cannot settle November time (the review probe: 440.00 recorded in P1)
        with self.assertRaisesRegex(LaborError, "period P1"):
            lab.record_payroll("P1", emp, "440.00", "PR-OCT-X", actor="payroll")
        with self.assertRaises(LaborError):
            lab.record_payroll("P1", emp, "400.01", "PR-OCT-Y", actor="payroll")
        # November payroll may settle October time too (paid in arrears): 400.00 + 440.00
        nov = lab.record_payroll("P2", emp, "840.00", "PR-NOV-1", actor="payroll")
        ap = c.request_approval("labor.post_payroll", nov["id"], actor_role="treasury")
        self.assertEqual(ap["manifest"]["amounts"], {"gross_amount": "840.00", "accrued_payroll": "840.00", "available_in_period": "840.00"})
        c.approve(ap["id"])
        c.execute(ap["id"], period_id="P2")
        # October's accrual is settled by November's payroll, so October has nothing left to pay:
        # a further October payroll would leave November's cumulative 2200 balance a debit
        self.assertEqual((lab.payroll_available(emp, "P1"), lab.payroll_available(emp, "P2")), (Decimal("0.00"), Decimal("0.00")))
        with self.assertRaises(LaborError):
            lab.record_payroll("P1", emp, "1.00", "PR-OCT-Z", actor="payroll")

        # by period end the cumulative 2200 balance is never a debit, and it reconciles period by period
        for pid, expected in (("P1", "400.00"), ("P2", "0.00")):
            rec = lab.accrued_payroll_reconciliation(pid)
            self.assertEqual((rec["subledger_total"], rec["control_balance"], rec["reconciled"], rec["overdrawn"]), (expected, expected, True, []), pid)
            self.assertTrue(all(chk["ok"] for chk in lab.close_checks(pid)), pid)
        self.assertEqual(self.s.bal("2200", period_id="P1"), Decimal("400.00"))
        self.assertEqual(self.s.bal("2200", period_id="P2"), Decimal("-400.00"))  # November activity: 440.00 accrued, 840.00 paid
        self.assertEqual(self.s.bal("5300"), Decimal("840.00"))
        _assert_books_ok(self, c)


class LaborInvoiceTests(unittest.TestCase):
    def test_entry_reserved_by_one_live_invoice(self):
        s = Scenario()
        c, lab = s.c, s.lab
        _, (e1, e2, e3) = s.approved_timesheet()
        a = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        self.assertEqual((a["sequence"], a["total"]), (1, "2000.00"))
        self.assertEqual(lab.entry(e1["id"])["invoice_id"], a["id"])

        emp2 = c.add_party(kind="employee", name="CAD Technician")
        lab.set_rate(emp2["id"], "2026-10-01", "40.00", "100.00", actor="owner")
        e4 = s.log("2026-10-20", "2", emp=emp2)
        ts2 = lab.submit_timesheet(emp2["id"], "P1", actor="emp")
        c.approve_and_execute("labor.approve_timesheet", ts2["id"], period_id="P1")
        b = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        self.assertEqual((b["sequence"], b["total"], [ln["entry_id"] for ln in b["lines"]]), (2, "200.00", [e4["id"]]))

        # the partial unique index refuses a second live reservation even through raw SQL
        with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE"):
            c.db.execute(
                "INSERT INTO labor_invoice_lines (id, invoice_id, entry_id, phase_id, employee_id, work_date, hours, bill_rate, amount, released) VALUES (?,?,?,?,?,?,?,?,?,0)",
                ("lnvl_raw", b["id"], e1["id"], s.dd["id"], s.emp["id"], "2026-10-15", "8.00", "120.00", "960.00"),
            )
        with self.assertRaises(sqlite3.DatabaseError):  # lines are released only by voiding their invoice
            c.db.execute("UPDATE labor_invoice_lines SET released=1 WHERE invoice_id=?", (a["id"],))

        voided = lab.void_invoice(a["id"], actor="pm", reason="customer asked for one invoice per month")
        self.assertEqual(voided["status"], "void")
        self.assertTrue(all(ln["released"] for ln in voided["lines"]))
        self.assertIsNone(lab.entry(e1["id"])["invoice_id"])
        again = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        self.assertEqual((again["sequence"], again["total"]), (3, "2000.00"))
        self.assertEqual({ln["entry_id"] for ln in again["lines"]}, {e1["id"], e2["id"]})
        c.approve_and_execute("labor.bill", again["id"], period_id="P1")
        with self.assertRaises(LaborError):
            lab.void_invoice(again["id"], actor="pm")
        with self.assertRaises(LaborError):
            lab.void_invoice(a["id"], actor="pm")
        self.assertEqual(s.bal("1100"), Decimal("2000.00"))
        self.assertEqual(lab.invoice(b["id"])["status"], "draft")
        _assert_books_ok(self, c)

    def test_invoice_needs_customer_and_approved_billable_time(self):
        nocust = Scenario(with_customer=False)
        nocust.approved_timesheet()
        with self.assertRaises(LaborError):
            nocust.lab.prepare_invoice(nocust.project["id"], "P1", actor="pm")

        s = Scenario()
        s.standard_rates()
        s.log("2026-10-15", "8")
        with self.assertRaises(LaborError):
            s.lab.prepare_invoice(s.project["id"], "P1", actor="pm")  # draft time is not billable yet
        ts = s.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        with self.assertRaises(LaborError):
            s.lab.prepare_invoice(s.project["id"], "P1", actor="pm")  # nor is submitted time
        s.lab.reject_timesheet(ts["id"], "move it to admin", actor="pm")
        entry = s.lab.entries(s.project["id"])[0]
        s.lab.update_entry(entry["id"], actor="emp", phase_id=s.adm["id"])
        s.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        s.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        with self.assertRaises(LaborError):
            s.lab.prepare_invoice(s.project["id"], "P1", actor="pm")  # approved, but non-billable
        with self.assertRaises(LaborError):
            s.lab.prepare_invoice(s.project["id"], "P9", actor="pm")
        self.assertEqual(s.bal("1100"), Decimal("0.00"))

    def test_bill_approval_stale_after_void(self):
        s = Scenario()
        s.approved_timesheet()
        inv = s.lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        ap = s.c.request_approval("labor.bill", inv["id"])
        self.assertEqual(ap["manifest"]["amounts"]["total"], "2000.00")
        self.assertEqual(ap["manifest"]["bindings"]["customer_id"], s.customer["id"])
        s.c.approve(ap["id"])
        s.lab.void_invoice(inv["id"], actor="pm", reason="re-cut")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError, LaborError)):
            s.c.execute(ap["id"], period_id="P1")
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(s.bal("1100"), Decimal("0.00"))
        self.assertEqual(s.bal("4100"), Decimal("0.00"))

    def test_bill_customer_must_be_a_customer_and_a_swap_makes_the_approval_stale(self):
        s = Scenario()
        c, lab = s.c, s.lab
        s.approved_timesheet()
        # a project whose "customer" is a supplier party is never invoiced
        p2 = c.create_project(name="Mis-set project", entity="E", budget="1000", customer_id=s.supplier["id"])
        ph = lab.add_phase(p2["id"], "DD", "Design", "10", "1000.00", actor="pm")
        s.log("2026-10-20", "2", phase=ph, project=p2)
        ts = lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        with self.assertRaisesRegex(LaborError, "not a customer"):
            lab.prepare_invoice(p2["id"], "P1", actor="pm")

        inv = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        ap = c.request_approval("labor.bill", inv["id"])
        b = ap["manifest"]["bindings"]
        self.assertEqual((b["customer_id"], b["customer_kind"], b["invoice_customer_id"], b["line_count"], b["total_hours"], b["invoice_version"]),
                         (s.customer["id"], "customer", s.customer["id"], 2, "16.00", 1))
        c.approve(ap["id"])
        # the project's customer is swapped after the grant (no void, so no eager invalidation): the bindings catch it
        successor = c.add_party(kind="customer", name="Successor Agency")
        c.db.execute("UPDATE projects SET customer_id=? WHERE id=?", (successor["id"], s.project["id"]))
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(LaborError):  # the draft was prepared for the old customer: void and prepare again
            c.approve_and_execute("labor.bill", inv["id"], period_id="P1")
        lab.void_invoice(inv["id"], actor="pm", reason="customer changed")
        again = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        c.approve_and_execute("labor.bill", again["id"], period_id="P1")
        self.assertEqual(s.bal("1100", party_id=successor["id"]), Decimal("2000.00"))
        self.assertEqual(s.bal("1100", party_id=s.customer["id"]), Decimal("0.00"))
        _assert_books_ok(self, c)

    def test_collections_clear_the_labor_receivable(self):
        s = Scenario()
        c, lab = s.c, s.lab
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        s.approved_timesheet()
        inv = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        with self.assertRaises(LaborError):
            lab.record_collection(inv["id"], "P1", "100.00", "ACH-0", actor="ar")  # a draft invoice is not a receivable
        c.approve_and_execute("labor.bill", inv["id"], period_id="P1")
        labor_ar = lab.ar_open_items(s.project["id"])
        self.assertEqual((labor_ar["subledger_total"], [(i["invoice_id"], i["open"]) for i in labor_ar["items"]]), ("2000.00", [(inv["id"], "2000.00")]))
        # the core receivables subledger counts prime bills only; adding the labor subledger ties 1100 out
        core = c.receivables.ar_open_items()
        self.assertEqual((core["subledger_total"], core["control_balance"]), ("0.00", "2000.00"))
        self.assertEqual(Decimal(core["subledger_total"]) + Decimal(lab.ar_open_items()["subledger_total"]), Decimal(core["control_balance"]))

        c.close_period("P1")
        with self.assertRaises(LaborError):
            lab.record_collection(inv["id"], "P1", "100.00", "ACH-1", actor="ar")  # closed period
        col = lab.record_collection(inv["id"], "P2", "1500.00", "ACH-1", fee="5.00", actor="ar")
        self.assertEqual((col["amount"], col["fee"], col["period_id"]), ("1500.00", "5.00", "P2"))
        j = c.ledger.journal(col["journal_id"])
        self.assertEqual(sorted((ln["account_code"], ln["debit"], ln["credit"]) for ln in j["lines"]),
                         [("1000", "1495.00", "0.00"), ("1100", "0.00", "1500.00"), ("6000", "5.00", "0.00")])
        self.assertEqual((s.bal("1000"), s.bal("6000"), s.bal("1100"), s.bal("1100", party_id=s.customer["id"])),
                         (Decimal("1495.00"), Decimal("5.00"), Decimal("500.00"), Decimal("500.00")))
        after = lab.invoice(inv["id"])
        self.assertEqual((after["status"], after["collected"], after["open"]), ("billed", "1500.00", "500.00"))

        bad = [
            dict(amount="500.01", provider_ref="ACH-2"),             # above the open balance
            dict(amount="100.00", provider_ref="ach-1"),             # duplicate receipt, any case
            dict(amount="10.00", provider_ref="ACH-3", fee="10.00"),  # fee must be less than the receipt
            dict(amount="0.00", provider_ref="ACH-4"),
            dict(amount=100.0, provider_ref="ACH-5"),
            dict(amount="100.00", provider_ref="  "),
        ]
        for kwargs in bad:
            with self.assertRaises(LaborError, msg=repr(kwargs)):
                lab.record_collection(inv["id"], "P2", actor="ar", **kwargs)
        with self.assertRaises(LaborError):
            lab.record_collection("linv_missing", "P2", "1.00", "ACH-6", actor="ar")

        lab.record_collection(inv["id"], "P2", "500.00", "ACH-7", actor="ar")
        self.assertEqual((lab.invoice(inv["id"])["open"], lab.ar_open_items()["subledger_total"], s.bal("1100")), ("0.00", "0.00", Decimal("0.00")))
        self.assertTrue(c.receivables.ar_open_items()["reconciled"])
        with self.assertRaises(LaborError):
            lab.record_collection(inv["id"], "P2", "0.01", "ACH-8", actor="ar")
        for sql in ("UPDATE labor_collections SET amount='1.00' WHERE id=?", "DELETE FROM labor_collections WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                c.db.execute(sql, (col["id"],))
        self.assertEqual(len(c.ledger.journals(source_type="labor_collection")), 2)
        _assert_books_ok(self, c)

    def test_invoice_covers_only_its_period(self):
        s = Scenario()
        s.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        s.standard_rates()
        oct_entry = s.log("2026-10-15", "8")
        nov_entry = s.log("2026-11-03", "8")
        t1 = s.lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        t2 = s.lab.submit_timesheet(s.emp["id"], "P2", actor="emp")
        s.c.approve_and_execute("labor.approve_timesheet", t1["id"], period_id="P1")
        s.c.approve_and_execute("labor.approve_timesheet", t2["id"], period_id="P2")
        self.assertEqual(s.bal("5300", period_id="P2"), Decimal("440.00"))
        i1 = s.lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        i2 = s.lab.prepare_invoice(s.project["id"], "P2", actor="pm")
        self.assertEqual(([ln["entry_id"] for ln in i1["lines"]], i1["total"]), ([oct_entry["id"]], "960.00"))
        self.assertEqual(([ln["entry_id"] for ln in i2["lines"]], i2["total"]), ([nov_entry["id"]], "1040.00"))
        s.c.approve_and_execute("labor.bill", i2["id"], period_id="P2")
        self.assertEqual(s.bal("4100", period_id="P2"), Decimal("1040.00"))
        self.assertEqual(s.bal("4100", period_id="P1"), Decimal("0.00"))


class LaborAnalyticsTests(unittest.TestCase):
    def test_utilization(self):
        s = Scenario()
        lab = s.lab
        s.approved_timesheet()
        s.log("2026-10-20", "8")  # draft: not counted
        emp2 = s.c.add_party(kind="employee", name="Office Manager")
        lab.set_rate(emp2["id"], "2026-10-01", "30.00", "0.00", actor="owner")
        s.log("2026-10-21", "5", phase=s.adm, emp=emp2)
        lab.submit_timesheet(emp2["id"], "P1", actor="emp")  # submitted: counted
        emp3 = s.c.add_party(kind="employee", name="New Hire")

        u = lab.utilization("P1")
        rows = {r["employee_id"]: r for r in u["employees"]}
        self.assertEqual((rows[s.emp["id"]]["total_hours"], rows[s.emp["id"]]["billable_hours"], rows[s.emp["id"]]["utilization_percent"]), ("20.00", "16.00", "80.00"))
        self.assertEqual((rows[emp2["id"]]["total_hours"], rows[emp2["id"]]["utilization_percent"]), ("5.00", "0.00"))
        self.assertNotIn(emp3["id"], rows)
        self.assertEqual(u["total"], {"total_hours": "25.00", "billable_hours": "16.00", "utilization_percent": "64.00"})

        one = lab.utilization("P1", employee_id=s.emp["id"])
        self.assertEqual([r["employee_id"] for r in one["employees"]], [s.emp["id"]])
        idle = lab.utilization("P1", employee_id=emp3["id"])
        self.assertEqual(idle["employees"][0]["total_hours"], "0.00")
        self.assertEqual(idle["employees"][0]["utilization_percent"], "0.00")
        with self.assertRaises(LaborError):
            lab.utilization("P1", employee_id=s.supplier["id"])
        with self.assertRaises(LaborError):
            lab.utilization("P9")

    def test_fee_status(self):
        s = Scenario()
        lab = s.lab
        zero = lab.add_phase(s.project["id"], "ZERO", "Unbudgeted extra", "0", "0.00", actor="pm")
        s.golden_entries()
        s.log("2026-10-14", "1", phase=zero)
        ts = lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        s.c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        s.log("2026-10-20", "8")  # draft: not actual cost

        fs = {p["code"]: p for p in lab.fee_status(s.project["id"])["phases"]}
        dd = fs["DD"]
        self.assertEqual((dd["actual_hours"], dd["actual_cost"], dd["actual_bill_value"], dd["percent_spent"], dd["percent_hours"], dd["over_budget"]),
                         ("16.00", "840.00", "2000.00", "14.00", "16.00", False))
        adm = fs["ADM"]
        self.assertEqual((adm["actual_cost"], adm["percent_spent"], adm["percent_hours"], adm["over_budget"]), ("220.00", "44.00", "40.00", False))
        self.assertEqual((fs["ZERO"]["actual_cost"], fs["ZERO"]["percent_spent"], fs["ZERO"]["over_budget"]), ("50.00", None, True))

        lab.update_phase(s.adm["id"], actor="pm", fee_budget_hours="3", fee_budget_amount="200.00")
        status = lab.fee_status(s.project["id"])
        adm = {p["code"]: p for p in status["phases"]}["ADM"]
        self.assertEqual((adm["percent_spent"], adm["remaining_amount"], adm["over_budget_amount"], adm["over_budget_hours"], adm["over_budget"]),
                         ("110.00", "-20.00", True, True, True))
        t = status["total"]
        self.assertEqual((t["budget_hours"], t["budget_amount"], t["actual_hours"], t["actual_cost"], t["percent_spent"], t["percent_hours"]),
                         ("103.00", "6200.00", "21.00", "1110.00", "17.90", "20.39"))
        self.assertEqual((t["over_budget"], t["phases_over_budget"]), (False, 2))
        with self.assertRaises(LaborError):
            lab.fee_status("prj_missing")


class LaborCloseAndStateTests(unittest.TestCase):
    def test_close_checks_block_and_clear(self):
        s = Scenario()
        c, lab = s.c, s.lab
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        s.golden_entries()
        ALL = [True] * 6

        def oks(period):
            # order: timesheets awaiting approval, draft time, draft invoices, draft payroll, 2200 reconciliation, overdrawn accrual
            checks = lab.close_checks(period)
            for chk in checks:
                self.assertEqual(set(chk), {"check", "ok", "detail"})
            return [chk["ok"] for chk in checks]

        self.assertEqual(oks("P1"), [True, False, True, True, True, True])  # unsubmitted draft time dated in October
        self.assertIn("3 draft time entries", lab.close_checks("P1")[1]["detail"])
        ts = lab.submit_timesheet(s.emp["id"], "P1", actor="emp")
        self.assertEqual(oks("P1"), [False, True, True, True, True, True])
        self.assertEqual(oks("P2"), ALL)  # the pending timesheet belongs to P1
        brief = c.ricky.brief(s.project["id"], actor_role="owner")
        self.assertTrue(any(it["kind"] == "close_check" and "labor" in it["text"] for it in brief["items"]))

        c.approve_and_execute("labor.approve_timesheet", ts["id"], period_id="P1")
        self.assertEqual(oks("P1"), ALL)
        # a draft payroll left in the period would hold the accrual after close and could never post there
        pr = lab.record_payroll("P1", s.emp["id"], "400.00", "PR-CLOSE-1", actor="payroll")
        self.assertEqual(oks("P1"), [True, True, True, False, True, True])
        self.assertIn(pr["id"], lab.close_checks("P1")[3]["detail"])
        self.assertEqual(oks("P2"), ALL)
        lab.cancel_payroll(pr["id"], actor="payroll", reason="belongs to the November run")
        self.assertEqual(oks("P1"), ALL)
        inv = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        self.assertEqual(oks("P1"), [True, True, False, True, True, True])
        c.approve_and_execute("labor.bill", inv["id"], period_id="P1")
        self.assertEqual(oks("P1"), ALL)

        # a direct control-account journal that bypasses the subledger breaks the reconciliation
        c.ledger.post(period_id="P1", description="manual accrual (bypasses labor subledger)",
                      lines=[{"account": "3000", "debit": "10.00"}, {"account": "2200", "credit": "10.00", "party_id": s.emp["id"]}],
                      source_type="manual", source_id="manual-1", source_version="1", posted_by="owner")
        self.assertEqual(oks("P1"), [True, True, True, True, False, True])
        self.assertIn("1070.00", lab.close_checks("P1")[4]["detail"])
        self.assertFalse(lab.accrued_payroll_reconciliation()["reconciled"])
        # a payment that debits another employee's accrual with nothing approved leaves it overdrawn
        emp2 = c.add_party(kind="employee", name="CAD Technician")
        c.ledger.post(period_id="P1", description="manual payroll (bypasses labor subledger)",
                      lines=[{"account": "2200", "debit": "25.00", "party_id": emp2["id"]}, {"account": "1000", "credit": "25.00"}],
                      source_type="manual", source_id="manual-2", source_version="1", posted_by="owner")
        self.assertEqual(oks("P1"), [True, True, True, True, False, False])
        self.assertIn(emp2["id"], lab.close_checks("P1")[5]["detail"])
        self.assertEqual(lab.accrued_payroll_reconciliation("P1")["overdrawn"], [emp2["id"]])

    def test_state_shape_and_project_state(self):
        s = Scenario()
        s.approved_timesheet()
        s.log("2026-10-20", "2")
        s.lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        full = s.c.project_state(s.project["id"])
        self.assertIn(PLUGIN_NAME, full)
        st = full[PLUGIN_NAME]
        json.dumps(st)  # JSON-serialisable
        self.assertEqual(set(st), {"phases", "fee_total", "entries", "timesheets", "invoices", "utilization", "accrued_payroll", "receivables", "ledger"})
        self.assertEqual((st["receivables"]["subledger_total"], st["receivables"]["items"]), ("0.00", []))  # the invoice is still a draft
        self.assertEqual([p["code"] for p in st["phases"]], ["ADM", "DD"])
        self.assertEqual(st["fee_total"]["actual_cost"], "1060.00")
        self.assertEqual(st["entries"]["by_status"]["approved"], {"count": 3, "hours": "20.00", "cost": "1060.00", "bill_value": "2520.00"})
        self.assertEqual(st["entries"]["by_status"]["draft"]["count"], 1)
        self.assertEqual(len(st["entries"]["items"]), 4)
        self.assertEqual([(t["status"], t["total_cost"]) for t in st["timesheets"]], [("approved", "1060.00")])
        self.assertEqual([(i["status"], i["total"]) for i in st["invoices"]], [("draft", "2000.00")])
        self.assertEqual([u["period_id"] for u in st["utilization"]], ["P1"])
        self.assertEqual(st["utilization"][0]["total"]["utilization_percent"], "80.00")
        self.assertEqual((st["accrued_payroll"]["subledger_total"], st["accrued_payroll"]["control_balance"], st["accrued_payroll"]["reconciled"]), ("1060.00", "1060.00", True))
        self.assertEqual(st["ledger"], {"labor_cost_5300": "1060.00", "fee_revenue_4100": "0.00"})
        _assert_books_ok(self, s.c)


class LaborIntegrityTests(unittest.TestCase):
    def test_schema_and_reserved_accounts(self):
        c = Cipher()
        self.assertIn(SCHEMA_NAME, [v["name"] for v in c.db.schema_status()["versions"] if v["applied"]])
        accounts = {a["code"]: a for a in c.ledger.accounts()}
        self.assertEqual((accounts["2200"]["name"], accounts["2200"]["type"], accounts["2200"]["control_kind"]), ("Accrued payroll", "liability", "accrued_payroll"))
        self.assertEqual((accounts["4100"]["name"], accounts["4100"]["type"]), ("Fee revenue", "revenue"))
        self.assertEqual((accounts["5300"]["name"], accounts["5300"]["type"]), ("Project cost - labor", "expense"))
        with self.assertRaises(LaborError):
            c.request_approval("labor.unknown", "x")

    def test_raw_sql_cannot_rewrite_labor_history(self):
        s = Scenario()
        c, lab = s.c, s.lab
        ts, (e1, e2, e3) = s.approved_timesheet()
        pay = lab.record_payroll("P1", s.emp["id"], "100.00", "PR-RAW", actor="payroll")
        inv = lab.prepare_invoice(s.project["id"], "P1", actor="pm")
        rate_id = e1["rate_id"]
        attempts = [
            ("UPDATE labor_timesheets SET total_cost='1.00' WHERE id=?", (ts["id"],)),
            ("UPDATE labor_timesheets SET status='rejected' WHERE id=?", (ts["id"],)),
            ("UPDATE labor_entries SET status='draft' WHERE id=?", (e1["id"],)),
            ("UPDATE labor_entries SET cost_amount='1.00' WHERE id=?", (e3["id"],)),
            ("UPDATE labor_entries SET status='void' WHERE id=?", (e3["id"],)),
            ("UPDATE labor_payroll SET gross_amount='99.00' WHERE id=?", (pay["id"],)),
            ("UPDATE labor_invoices SET total='1.00' WHERE id=?", (inv["id"],)),
            ("UPDATE labor_invoice_lines SET amount='1.00' WHERE invoice_id=?", (inv["id"],)),
            ("DELETE FROM labor_entries WHERE id=?", (e1["id"],)),
            ("DELETE FROM labor_timesheets WHERE id=?", (ts["id"],)),
            ("DELETE FROM labor_rates WHERE id=?", (rate_id,)),
            ("DELETE FROM labor_phases WHERE id=?", (s.dd["id"],)),
            ("DELETE FROM labor_payroll WHERE id=?", (pay["id"],)),
            ("DELETE FROM labor_invoices WHERE id=?", (inv["id"],)),
            ("DELETE FROM labor_invoice_lines WHERE invoice_id=?", (inv["id"],)),
            (
                """INSERT INTO labor_entries (id, employee_id, project_id, phase_id, work_date, hours, note, rate_id, cost_rate, bill_rate,
                       cost_amount, bill_amount, status, version, created_by, created_at, updated_at)
                   VALUES ('ltim_raw', ?, ?, ?, '2026-10-22', '1.00', '', ?, '55.00', '130.00', '55.00', '130.00', 'approved', 1, 'x', 'now', 'now')""",
                (s.emp["id"], s.project["id"], s.dd["id"], rate_id),
            ),
            (
                """INSERT INTO labor_timesheets (id, employee_id, period_id, status, version, content_hash, lines_json, entry_count, total_hours,
                       total_cost, total_bill, submitted_by, submitted_at)
                   VALUES ('ltsh_raw', ?, 'P1', 'approved', 1, 'h', '[]', 0, '0.00', '0.00', '0.00', 'x', 'now')""",
                (s.emp["id"],),
            ),
        ]
        for sql, params in attempts:
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                c.db.execute(sql, params)
        self.assertEqual(lab.timesheet(ts["id"])["total_cost"], "1060.00")
        self.assertEqual(lab.entry(e1["id"])["status"], "approved")
        self.assertEqual(lab.entry(e3["id"])["cost_amount"], "220.00")
        self.assertEqual(lab.payroll(pay["id"])["gross_amount"], "100.00")
        self.assertEqual(lab.invoice(inv["id"])["total"], "2000.00")
        self.assertEqual(len(lab.entries(s.project["id"])), 3)
        _assert_books_ok(self, c)


if __name__ == "__main__":
    unittest.main()
