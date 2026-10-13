"""EPC procurement: equipment register, bid tabs, award, long-lead tracking and receiving."""
import datetime as _dt
import json
import sqlite3
import unittest
from unittest import mock

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import utcnow
from apps.cipher.domain import procurement as procurement_module
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.procurement import PLUGIN_NAME, ProcurementError
from apps.cipher.service import Cipher

FUTURE = "2099-12-31"
JUSTIFICATION = "schedule: 10 weeks shorter lead"


def today() -> str:
    return utcnow().date().isoformat()


class Scenario:
    """Fresh in-memory workspace: three verified suppliers, a customer, a project and open period P1."""

    def __init__(self):
        self.c = Cipher()
        self.p = self.c.plugin(PLUGIN_NAME)
        self.sup = {}
        for key, dest in (("A", "ACH-SIM-A"), ("B", "ACH-SIM-B"), ("C", "ACH-SIM-C")):
            party = self.c.add_party(kind="supplier", name=f"Pump Supplier {key}", destination=dest)
            self.c.verify_destination(party["id"], destination=dest, verified_by="owner")
            self.sup[key] = party["id"]
        self.customer = self.c.add_party(kind="customer", name="Synthetic Water Authority")
        self.project = self.c.create_project(name="Raw water intake", entity="S&A (synthetic)", budget="500000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")

    def equipment(self, tag, required="2027-03-01", *, description="Raw water pump", long_lead=True, project_id=None):
        return self.p.add_equipment(project_id or self.pid, tag, description, "XX 21 13", required, long_lead=long_lead, actor="pm")

    def golden_requisition(self):
        """Two pumps, three quotes: 52,000 non-compliant, 55,000 compliant 30 wk, 58,000 compliant 20 wk."""
        e1 = self.equipment("P-101", "2027-03-01")
        e2 = self.equipment("P-102", "2027-04-01", description="Raw water pump (standby)")
        req = self.p.create_requisition(self.pid, "Raw water pumps", [e1["id"], e2["id"]], actor="pm")
        qa = self.p.add_quote(req["id"], self.sup["A"], "52000.00", 16, FUTURE, False, exceptions="motor efficiency below spec", actor="buyer")
        qb = self.p.add_quote(req["id"], self.sup["B"], "55000.00", 30, FUTURE, True, actor="buyer")
        qc = self.p.add_quote(req["id"], self.sup["C"], "58000.00", 20, FUTURE, True, actor="buyer")
        return e1, e2, req, qa, qb, qc

    def awarded(self):
        e1, e2, req, qa, qb, qc = self.golden_requisition()
        self.p.select_quote(req["id"], qc["id"], JUSTIFICATION, actor="pm")
        res = self.c.approve_and_execute("procurement.award", req["id"], actor_role="pm", period_id="P1")
        return e1, e2, req, qc, res


class ProcurementGoldenTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.p = self.s.c, self.s.p

    def test_golden_bid_tab_award_long_lead_and_receiving(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.assertEqual(req["status"], "draft")

        # receiving before award is rejected
        with self.assertRaises(ProcurementError):
            self.p.receive(e1["id"], today(), "ok", "sha-delivery-ticket", actor="field")

        tab = self.p.bid_tab(req["id"])
        self.assertEqual([q["amount"] for q in tab["quotes"]], ["52000.00", "55000.00", "58000.00"])
        self.assertEqual([q["lowest_compliant"] for q in tab["quotes"]], [False, True, False])
        self.assertEqual(tab["lowest_compliant_amount"], "55000.00")
        self.assertEqual(tab["lowest_compliant_quote_ids"], [qb["id"]])
        self.assertEqual(tab["spread"], "3000.00")
        self.assertEqual(tab["count"], 3)
        self.assertEqual((tab["compliant_count"], tab["eligible_count"]), (2, 2))

        # non-compliant cannot be selected; non-lowest needs a justification
        with self.assertRaises(ProcurementError):
            self.p.select_quote(req["id"], qa["id"], "cheapest", actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.select_quote(req["id"], qc["id"], "", actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.select_quote(req["id"], qc["id"], "   ", actor="pm")
        before = self.p.requisition(req["id"])["version"]
        sel = self.p.select_quote(req["id"], qc["id"], JUSTIFICATION, actor="pm")
        self.assertEqual(sel["selected_quote_id"], qc["id"])
        self.assertEqual(sel["justification"], JUSTIFICATION)
        self.assertGreater(sel["version"], before)

        # revising the selected quote after the award approval was granted makes it stale
        ap = self.c.request_approval("procurement.award", req["id"], actor_role="pm", requested_by="pm")
        self.assertEqual(ap["manifest"]["amounts"]["award"], "58000.00")
        self.assertEqual(ap["manifest"]["bindings"]["supplier_id"], self.s.sup["C"])
        self.assertEqual(ap["manifest"]["destination"]["party_id"], self.s.sup["C"])
        self.c.approve(ap["id"], approver="owner")
        revised = self.p.revise_quote(qc["id"], "buyer", exceptions="freight FOB origin")
        self.assertEqual(revised["version"], 2)
        self.assertIsNone(self.p.requisition(req["id"])["selected_quote_id"])  # the selection described the old quote
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")

        # re-select and award: a DRAFT commitment, not an executed one
        self.p.select_quote(req["id"], qc["id"], JUSTIFICATION, actor="pm")
        res = self.c.approve_and_execute("procurement.award", req["id"], actor_role="pm", period_id="P1").result
        self.assertEqual(res["status"], "awarded")
        self.assertEqual(res["amount"], "58000.00")
        self.assertEqual(res["sov"], ["29000.00", "29000.00"])
        self.assertEqual(res["commitment_status"], "draft")
        cm = self.c.commitments.get(res["commitment"])
        self.assertEqual(cm["status"], "draft")
        self.assertEqual(cm["supplier_id"], self.s.sup["C"])
        self.assertEqual(cm["title"], "PO - Raw water pumps")
        self.assertEqual(cm["original_amount"], "58000.00")
        self.assertEqual(cm["sov_total"], "58000.00")
        self.assertEqual(cm["retainage_rate"], "0.000000")
        self.assertIsNone(cm["estimate_id"])
        self.assertEqual([s["description"] for s in cm["sov"]], ["P-101 - Raw water pump", "P-102 - Raw water pump (standby)"])
        self.assertEqual([s["amount"] for s in cm["sov"]], ["29000.00", "29000.00"])
        award = self.p.award(req["id"])
        self.assertEqual(award["commitment_id"], cm["id"])
        self.assertEqual(award["justification"], JUSTIFICATION)
        self.assertEqual(award["period_id"], "P1")
        self.assertEqual(self.p.requisition(req["id"])["status"], "awarded")
        # the award posts nothing: a commitment alone does not create a payable
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)

        # contract execution is the separate core authority
        self.c.approve_and_execute("commitment.execute", cm["id"], actor_role="owner")
        self.assertEqual(self.c.commitments.get(cm["id"])["status"], "executed")

        # long lead: required on site 2027-03-01, planned delivery 2027-03-15 -> 14 days late
        self.p.set_milestone_plan(e1["id"], [
            {"name": "submittal", "planned": "2026-11-01"}, {"name": "approval", "planned": "2026-11-20"},
            {"name": "fabrication", "planned": "2026-12-01"}, {"name": "factory_test", "planned": "2027-02-15"},
            {"name": "ship", "planned": "2027-03-01"}, {"name": "delivery", "planned": "2027-03-15"},
        ], actor="pm")
        row = next(r for r in self.p.long_lead_report(self.s.pid) if r["tag"] == "P-101")
        self.assertEqual(row["forecast_delivery"], "2027-03-15")
        self.assertEqual(row["float_days"], -14)
        self.assertTrue(row["late"])
        self.assertEqual(row["award_status"], "awarded")
        self.assertEqual(row["commitment_id"], cm["id"])

        # receiving after award sets the delivery actual
        rc = self.p.receive(e2["id"], today(), "ok", "sha-delivery-ticket-102", note="set on pad", actor="field")
        self.assertEqual(rc["condition"], "ok")
        e2_now = self.p.equipment(e2["id"])
        self.assertTrue(e2_now["received"])
        self.assertEqual(e2_now["forecast"]["forecast_basis"], "actual")
        self.assertEqual(e2_now["forecast"]["forecast_delivery"], today())

        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class EquipmentAndRequisitionTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.p = self.s.c, self.s.p

    def test_equipment_tag_unique_per_project_case_insensitive(self):
        e = self.s.equipment("P-101")
        self.assertEqual(e["version"], 1)
        self.assertTrue(e["long_lead"])
        self.assertEqual(e["award_status"], "not_requisitioned")
        with self.assertRaises(ProcurementError):
            self.s.equipment("p-101")
        # case folding is Unicode-aware, not only ASCII
        self.s.equipment("PÜMPE-1")
        for variant in ("pümpe-1", "Pümpe-1"):
            with self.subTest(variant=variant), self.assertRaises(ProcurementError):
                self.s.equipment(variant)
        other = self.c.create_project(name="Other plant", entity="S&A (synthetic)", budget="1000")
        self.assertEqual(self.s.equipment("P-101", project_id=other["id"])["tag"], "P-101")

    def test_equipment_input_validation(self):
        for bad in ("2027-02-30", "03/01/2027", "2027-3-1", None):
            with self.assertRaises(ProcurementError):
                self.s.equipment("P-1", bad)
        with self.assertRaises(ProcurementError):
            self.s.equipment("   ")
        with self.assertRaises(ProcurementError):
            self.p.add_equipment(self.s.pid, "P-2", "Pump", "XX 21 13", "2027-03-01", long_lead="yes")
        with self.assertRaises(ProcurementError):
            self.p.add_equipment(self.s.pid, "P-3", "Pump", "", "2027-03-01")
        with self.assertRaises(ProcurementError):
            self.p.add_equipment("prj_missing", "P-4", "Pump", "XX 21 13", "2027-03-01")
        self.assertEqual(self.p.state(self.s.pid)["summary"]["equipment"], 0)

    def test_requisition_rules_and_cancellation(self):
        e1, e2 = self.s.equipment("P-101"), self.s.equipment("P-102")
        other = self.c.create_project(name="Other plant", entity="S&A (synthetic)", budget="1000")
        foreign = self.s.equipment("X-1", project_id=other["id"])
        with self.assertRaises(ProcurementError):
            self.p.create_requisition(self.s.pid, "Pumps", [], actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.create_requisition(self.s.pid, "Pumps", [e1["id"], e1["id"]], actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.create_requisition(self.s.pid, "Pumps", [e1["id"], foreign["id"]], actor="pm")
        req = self.p.create_requisition(self.s.pid, "Pumps", [e1["id"], e2["id"]], actor="pm")
        self.assertEqual((req["status"], req["version"]), ("draft", 1))
        self.assertEqual(req["equipment_tags"], ["P-101", "P-102"])
        self.assertEqual(self.p.equipment(e1["id"])["award_status"], "requisitioned")
        # an item may be on only one open requisition
        with self.assertRaises(ProcurementError):
            self.p.create_requisition(self.s.pid, "Pump again", [e1["id"]], actor="pm")
        canceled = self.p.cancel_requisition(req["id"], "re-scoped", actor="pm")
        self.assertEqual(canceled["status"], "cancelled")
        self.assertIsNone(self.p.equipment(e1["id"])["requisition_id"])
        with self.assertRaises(ProcurementError):
            self.p.add_quote(req["id"], self.s.sup["A"], "1000.00", 4, FUTURE, True)
        with self.assertRaises(ProcurementError):
            self.p.cancel_requisition(req["id"], "again", actor="pm")
        again = self.p.create_requisition(self.s.pid, "Pump again", [e1["id"]], actor="pm")
        self.assertEqual(self.p.equipment(e1["id"])["requisition_id"], again["id"])


class QuoteAndSelectionTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.p = self.s.c, self.s.p
        e = self.s.equipment("P-101")
        self.req = self.p.create_requisition(self.s.pid, "Pumps", [e["id"]], actor="pm")

    def test_quote_input_validation(self):
        rid, sup = self.req["id"], self.s.sup["A"]
        cases = [
            dict(supplier_id=self.s.customer["id"]),
            dict(supplier_id="pty_missing"),
            dict(amount="0.00"), dict(amount="-5"), dict(amount=55000.0), dict(amount="abc"),
            dict(amount="NaN"), dict(amount="Infinity"), dict(amount="sNaN"), dict(amount="1E+30"),
            dict(amount="55000.005"), dict(amount="55000.004"),  # sub-cent input is rejected, not rounded
            dict(lead_time_weeks=0), dict(lead_time_weeks=True), dict(lead_time_weeks="20"), dict(lead_time_weeks=9999),
            dict(valid_until="2099-02-30"), dict(compliant="yes"), dict(exceptions=5),
        ]
        for override in cases:
            args = dict(supplier_id=sup, amount="55000.00", lead_time_weeks=20, valid_until=FUTURE, compliant=True, exceptions="")
            args.update(override)
            with self.subTest(override=override), self.assertRaises(ProcurementError):
                self.p.add_quote(rid, args["supplier_id"], args["amount"], args["lead_time_weeks"], args["valid_until"], args["compliant"], args["exceptions"], actor="buyer")
        self.assertEqual(self.p.bid_tab(rid)["count"], 0)
        # trailing zeros are still whole cents; revisions get the same validation
        q = self.p.add_quote(rid, sup, "55000.000", 20, FUTURE, True, actor="buyer")
        self.assertEqual(q["amount"], "55000.00")
        for bad in ("NaN", "Infinity", "1E+30", "54999.995"):
            with self.subTest(revise=bad), self.assertRaises(ProcurementError):
                self.p.revise_quote(q["id"], "buyer", amount=bad)
        self.assertEqual(self.p.quote(q["id"])["version"], 1)

    def test_one_live_quote_per_supplier_and_withdrawal(self):
        q = self.p.add_quote(self.req["id"], self.s.sup["A"], "55000.00", 20, FUTURE, True, actor="buyer")
        with self.assertRaises(ProcurementError):
            self.p.add_quote(self.req["id"], self.s.sup["A"], "54000.00", 20, FUTURE, True, actor="buyer")
        w = self.p.withdraw_quote(q["id"], "supplier withdrew", actor="buyer")
        self.assertEqual((w["status"], w["version"]), ("withdrawn", 2))
        with self.assertRaises(ProcurementError):
            self.p.revise_quote(q["id"], "buyer", amount="50000.00")
        q2 = self.p.add_quote(self.req["id"], self.s.sup["A"], "54000.00", 20, FUTURE, True, actor="buyer")
        tab = self.p.bid_tab(self.req["id"])
        self.assertEqual([x["id"] for x in tab["quotes"]], [q2["id"]])
        self.assertEqual(len(self.p.requisition(self.req["id"])["quotes"]), 2)  # history kept

    def test_revise_quote_bumps_quote_and_requisition_versions(self):
        q = self.p.add_quote(self.req["id"], self.s.sup["B"], "55000.00", 30, FUTURE, True, actor="buyer")
        v_req = self.p.requisition(self.req["id"])["version"]
        r = self.p.revise_quote(q["id"], "buyer", amount="54500.00", lead_time_weeks=28)
        self.assertEqual((r["version"], r["amount"], r["lead_time_weeks"]), (2, "54500.00", 28))
        self.assertNotEqual(r["content_hash"], q["content_hash"])
        self.assertEqual(self.p.requisition(self.req["id"])["version"], v_req + 1)
        with self.assertRaises(ProcurementError):
            self.p.revise_quote(q["id"], "buyer")
        with self.assertRaises(ProcurementError):
            self.p.revise_quote(q["id"], "buyer", amount="54500.00")  # changes nothing
        with self.assertRaises(ProcurementError):
            self.p.revise_quote(q["id"], "buyer", amount="0")

    def test_expired_quote_cannot_be_selected_and_is_not_lowest(self):
        stale = self.p.add_quote(self.req["id"], self.s.sup["A"], "50000.00", 10, "2020-01-01", True, actor="buyer")
        fresh = self.p.add_quote(self.req["id"], self.s.sup["B"], "55000.00", 30, FUTURE, True, actor="buyer")
        tab = self.p.bid_tab(self.req["id"])
        by_id = {q["id"]: q for q in tab["quotes"]}
        self.assertTrue(by_id[stale["id"]]["expired"])
        self.assertFalse(by_id[stale["id"]]["lowest_compliant"])
        self.assertTrue(by_id[fresh["id"]]["lowest_compliant"])
        # spread is over every compliant quote (the spec); the selection basis excludes the expired one
        self.assertEqual(tab["spread"], "5000.00")
        self.assertEqual(tab["eligible_spread"], "0.00")
        self.assertEqual((tab["compliant_count"], tab["eligible_count"]), (2, 1))
        self.assertEqual(tab["lowest_compliant_amount"], "55000.00")
        with self.assertRaises(ProcurementError) as ctx:
            self.p.select_quote(self.req["id"], stale["id"], "cheapest", actor="pm")
        self.assertIn("expired", str(ctx.exception))
        self.p.select_quote(self.req["id"], fresh["id"], actor="pm")  # lowest eligible: no justification needed
        with self.assertRaises(ProcurementError):
            self.p.select_quote(self.req["id"], fresh["id"], actor="pm")  # duplicate selection

    def test_selection_cleared_when_undercut_without_justification(self):
        qb = self.p.add_quote(self.req["id"], self.s.sup["B"], "55000.00", 30, FUTURE, True, actor="buyer")
        qc = self.p.add_quote(self.req["id"], self.s.sup["C"], "58000.00", 20, FUTURE, True, actor="buyer")
        self.p.select_quote(self.req["id"], qb["id"], actor="pm")
        # a justified selection of a non-lowest quote survives a revision elsewhere
        self.p.revise_quote(qc["id"], "buyer", lead_time_weeks=19)
        self.assertEqual(self.p.requisition(self.req["id"])["selected_quote_id"], qb["id"])
        # an unjustified selection is cleared once it is no longer the lowest
        self.p.revise_quote(qc["id"], "buyer", amount="54000.00")
        req = self.p.requisition(self.req["id"])
        self.assertIsNone(req["selected_quote_id"])
        self.assertEqual(self.p.equipment(req["equipment_ids"][0])["award_status"], "bidding")
        with self.assertRaises(ProcurementError):
            self.c.request_approval("procurement.award", self.req["id"])
        cleared = self.c.audit.entries(entity_type="procurement_requisition", entity_id=self.req["id"])
        self.assertIn("procurement.selection_cleared", [e["action"] for e in cleared])


class AwardTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.p = self.s.c, self.s.p

    def test_award_allocation_sums_exactly(self):
        ids = [self.s.equipment(f"P-{n}")["id"] for n in (1, 2, 3)]
        req = self.p.create_requisition(self.s.pid, "Three pumps", ids, actor="pm")
        q = self.p.add_quote(req["id"], self.s.sup["A"], "100000.00", 12, FUTURE, True, actor="buyer")
        self.p.select_quote(req["id"], q["id"], actor="pm")
        res = self.c.approve_and_execute("procurement.award", req["id"], period_id="P1").result
        self.assertEqual(res["sov"], ["33333.34", "33333.33", "33333.33"])
        cm = self.c.commitments.get(res["commitment"])
        self.assertEqual(cm["original_amount"], "100000.00")
        self.assertEqual(cm["sov_total"], "100000.00")
        self.assertTrue(self.p.award(req["id"])["lowest_compliant"])

    def test_every_po_line_positive_and_odd_cent_leads(self):
        ids = [self.s.equipment(f"P-{n}")["id"] for n in (1, 2)]
        req = self.p.create_requisition(self.s.pid, "Two pumps", ids, actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.add_quote(req["id"], self.s.sup["A"], "0.01", 4, FUTURE, True, actor="buyer")  # would give a 0.00 line
        q = self.p.add_quote(req["id"], self.s.sup["A"], "0.02", 4, FUTURE, True, actor="buyer")
        with self.assertRaises(ProcurementError):
            self.p.revise_quote(q["id"], "buyer", amount="0.01")
        self.p.revise_quote(q["id"], "buyer", amount="58000.01")
        self.p.select_quote(req["id"], q["id"], actor="pm")
        res = self.c.approve_and_execute("procurement.award", req["id"], period_id="P1").result
        self.assertEqual(res["sov"], ["29000.01", "29000.00"])  # the odd cent goes on the first line
        self.assertEqual(self.c.commitments.get(res["commitment"])["sov_total"], "58000.01")

    def _granted_award(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.p.select_quote(req["id"], qc["id"], JUSTIFICATION, actor="pm")
        before = self.p.manifest_for("procurement.award", req["id"], actor_role="owner")["bindings"]
        ap = self.c.request_approval("procurement.award", req["id"])
        self.c.approve(ap["id"])
        return e1, req, qc, ap, before

    def _assert_stale_at_consume(self, ap, req, expect_in_diff):
        # no module method ran, so nothing was invalidated eagerly: only the manifest comparison can stop it
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], period_id="P1")
        after = self.c.approvals.get(ap["id"])
        self.assertEqual(after["status"], "invalidated")
        for key in expect_in_diff:
            self.assertIn(key, after["invalidated_reason"])
        self.assertIsNone(self.p.award(req["id"]))
        self.assertEqual(self.c.commitments.list(self.s.pid), [])

    def test_manifest_binds_justification(self):
        e1, req, qc, ap, before = self._granted_award()
        self.c.db.execute("UPDATE procurement_requisitions SET justification=?, version=version+1 WHERE id=?", ("cheaper freight", req["id"]))
        after = self.p.manifest_for("procurement.award", req["id"], actor_role="owner")["bindings"]
        self.assertEqual({k for k in before if before[k] != after[k]}, {"justification", "requisition_version"})
        self._assert_stale_at_consume(ap, req, ["bindings"])

    def test_manifest_binds_equipment_descriptions_through_sov(self):
        e1, req, qc, ap, before = self._granted_award()
        self.c.db.execute("UPDATE procurement_equipment SET description=?, version=version+1 WHERE id=?", ("Raw water pump, VFD", e1["id"]))
        after = self.p.manifest_for("procurement.award", req["id"], actor_role="owner")["bindings"]
        self.assertEqual({k for k in before if before[k] != after[k]}, {"sov_lines", "sov_hash"})
        self._assert_stale_at_consume(ap, req, ["bindings"])

    def test_manifest_binds_quote_amount_and_version(self):
        e1, req, qc, ap, before = self._granted_award()
        self.c.db.execute("UPDATE procurement_quotes SET amount='57000.00', version=version+1 WHERE id=?", (qc["id"],))
        self._assert_stale_at_consume(ap, req, ["amounts", "bindings"])

    def test_award_into_closed_period_rejected(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.p.select_quote(req["id"], qb["id"], actor="pm")
        ap = self.c.request_approval("procurement.award", req["id"])
        self.c.approve(ap["id"])
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.assertIsNone(self.p.award(req["id"]))
        self.assertEqual(self.c.commitments.list(self.s.pid), [])  # the drafted commitment rolled back too
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        res = self.c.execute(ap["id"], period_id="P2").result
        self.assertEqual(res["period_id"], "P2")
        self.assertEqual(res["amount"], "55000.00")
        self.assertEqual(res["sov"], ["27500.00", "27500.00"])

    def test_award_requires_valid_selection(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        with self.assertRaises(ProcurementError):
            self.c.request_approval("procurement.award", req["id"])
        with self.assertRaises(ProcurementError):
            self.c.request_approval("procurement.award", "preq_missing")
        with self.assertRaises(ProcurementError):
            self.p.select_quote(req["id"], "pqt_missing", actor="pm")

    def test_second_award_and_post_award_edits_rejected(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.p.select_quote(req["id"], qb["id"], actor="pm")
        ap1 = self.c.request_approval("procurement.award", req["id"])
        ap2 = self.c.request_approval("procurement.award", req["id"])
        self.c.approve(ap1["id"])
        self.c.approve(ap2["id"])
        self.c.execute(ap1["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap2["id"], period_id="P1")
        self.assertEqual(len(self.c.commitments.list(self.s.pid)), 1)
        with self.assertRaises(ProcurementError):
            self.c.request_approval("procurement.award", req["id"])
        with self.assertRaises(ProcurementError):
            self.p.revise_quote(qb["id"], "buyer", amount="1.00")
        with self.assertRaises(ProcurementError):
            self.p.add_quote(req["id"], self.s.sup["C"], "1.00", 1, FUTURE, True)
        with self.assertRaises(ProcurementError):
            self.p.select_quote(req["id"], qc["id"], JUSTIFICATION, actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.cancel_requisition(req["id"], "too late", actor="pm")

    def test_supplier_destination_change_invalidates_award_approval(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.p.select_quote(req["id"], qc["id"], JUSTIFICATION, actor="pm")
        ap = self.c.request_approval("procurement.award", req["id"])
        self.c.approve(ap["id"])
        self.c.verify_destination(self.s.sup["C"], destination="ACH-SIM-C-NEW", verified_by="owner")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.p.requisition(req["id"])["status"], "draft")

    def test_quote_expiring_after_grant_makes_award_stale(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        valid_until = procurement_module._today() + _dt.timedelta(days=30)  # relative to the module clock: no calendar time bomb
        self.p.revise_quote(qb["id"], "buyer", valid_until=valid_until.isoformat())
        self.p.select_quote(req["id"], qb["id"], actor="pm")
        ap = self.c.request_approval("procurement.award", req["id"])
        self.c.approve(ap["id"])
        with mock.patch.object(procurement_module, "_today", return_value=valid_until + _dt.timedelta(days=1)):
            with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
                self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertIsNone(self.p.award(req["id"]))

    def test_ricky_previews_award_by_role(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.p.select_quote(req["id"], qb["id"], actor="pm")
        proposed = self.c.ricky.propose("procurement.award", actor_role="pm", context={"requisition_id": req["id"]})
        self.assertEqual(proposed["decision"], "proposed")
        self.assertEqual(proposed["manifest"]["amounts"]["award"], "55000.00")
        abstained = self.c.ricky.propose("procurement.award", actor_role="estimator", context={"requisition_id": req["id"]})
        self.assertEqual(abstained["decision"], "abstained")

    def test_database_guards(self):
        e1, e2, req, qc, res = self.s.awarded()
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE procurement_awards SET amount='1.00' WHERE requisition_id=?", (req["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("DELETE FROM procurement_quotes WHERE id=?", (qc["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE procurement_requisitions SET status='draft', version=version+1 WHERE id=?", (req["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE procurement_equipment SET description='edited' WHERE id=?", (e1["id"],))  # no version bump


class MilestoneAndReceivingTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.p = self.s.c, self.s.p

    def test_milestone_plan_validation(self):
        e = self.s.equipment("P-101")
        bad_plans = [
            [],
            [{"name": "install", "planned": "2027-01-01"}],
            [{"name": "ship", "planned": "2027-01-01"}, {"name": "ship", "planned": "2027-01-02"}],
            [{"name": "submittal", "planned": "2027-01-10"}, {"name": "approval", "planned": "2027-01-05"}],
            [{"name": "ship", "planned": "2027-03-01"}, {"name": "delivery", "planned": "2027-02-28"}],
            [{"name": "delivery", "planned": "15/03/2027"}],
            ["delivery"],
        ]
        for plan in bad_plans:
            with self.subTest(plan=plan), self.assertRaises(ProcurementError):
                self.p.set_milestone_plan(e["id"], plan, actor="pm")
        ok = self.p.set_milestone_plan(e["id"], [{"name": "delivery", "planned": "2027-02-20"}, {"name": "ship", "planned": "2027-02-20"}], actor="pm")
        self.assertEqual([m["name"] for m in ok["milestones"]], ["ship", "delivery"])
        self.assertEqual(ok["forecast"]["float_days"], 9)
        self.assertFalse(ok["forecast"]["late"])

    def test_forecast_shifts_by_slip_of_latest_actual(self):
        e = self.s.equipment("P-201", "2025-06-01")
        self.p.set_milestone_plan(e["id"], [
            {"name": "submittal", "planned": "2025-01-06"}, {"name": "approval", "planned": "2025-01-20"},
            {"name": "fabrication", "planned": "2025-02-03"}, {"name": "ship", "planned": "2025-05-01"},
            {"name": "delivery", "planned": "2025-05-15"},
        ], actor="pm")
        self.p.record_actual(e["id"], "submittal", "2025-01-11", actor="pm")  # +5
        f = self.p.record_actual(e["id"], "approval", "2025-01-30", actor="pm")["forecast"]  # +10
        self.assertEqual((f["slip_days"], f["slip_basis"]), (10, "approval"))
        self.assertEqual(f["forecast_delivery"], "2025-05-25")
        self.assertEqual(f["float_days"], 7)
        f = self.p.record_actual(e["id"], "fabrication", "2025-02-06", actor="pm")["forecast"]  # +3, furthest along
        self.assertEqual((f["slip_days"], f["forecast_delivery"], f["float_days"]), (3, "2025-05-18", 14))
        with self.assertRaises(ProcurementError):
            self.p.record_actual(e["id"], "fabrication", "2025-02-07", actor="pm")  # recorded once
        with self.assertRaises(ProcurementError):
            self.p.record_actual(e["id"], "ship", "2099-01-01", actor="pm")  # future
        with self.assertRaises(ProcurementError):
            self.p.record_actual(e["id"], "delivery", "2025-05-20", actor="pm")  # delivery needs an award first
        with self.assertRaises(ProcurementError):
            self.p.record_actual(e["id"], "install", "2025-05-20", actor="pm")
        # a re-plan keeps recorded actuals even when the milestone is dropped from the plan
        again = self.p.set_milestone_plan(e["id"], [{"name": "delivery", "planned": "2025-05-30"}], actor="pm")
        names = {m["name"]: m for m in again["milestones"]}
        self.assertEqual(set(names), {"submittal", "approval", "fabrication", "delivery"})
        self.assertIsNone(names["fabrication"]["planned"])
        self.assertEqual(names["fabrication"]["actual"], "2025-02-06")
        self.assertEqual(again["forecast"]["forecast_delivery"], "2025-05-30")  # no actual has a plan to slip against

    def test_actuals_must_follow_milestone_order(self):
        e = self.s.equipment("P-301", "2025-09-01")
        self.p.set_milestone_plan(e["id"], [
            {"name": "submittal", "planned": "2025-01-02"}, {"name": "approval", "planned": "2025-02-01"},
            {"name": "fabrication", "planned": "2025-03-01"}, {"name": "ship", "planned": "2025-06-01"},
            {"name": "delivery", "planned": "2025-07-01"},
        ], actor="pm")
        self.p.record_actual(e["id"], "approval", "2025-01-15", actor="pm")  # 17 days early
        with self.assertRaises(ProcurementError) as ctx:
            self.p.record_actual(e["id"], "submittal", "2025-03-01", actor="pm")  # after the later milestone's actual
        self.assertIn("after the recorded approval actual", str(ctx.exception))
        with self.assertRaises(ProcurementError):
            self.p.record_actual(e["id"], "fabrication", "2025-01-14", actor="pm")  # before the earlier milestone's actual
        self.p.record_actual(e["id"], "submittal", "2025-01-15", actor="pm")  # same day is in order
        f = self.p.record_actual(e["id"], "fabrication", "2025-03-11", actor="pm")["forecast"]
        self.assertEqual((f["slip_basis"], f["slip_days"], f["forecast_delivery"]), ("fabrication", 10, "2025-07-11"))
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_delivery_actual_and_receipt_dates_bounded_by_award(self):
        e1, e2, req, qc, res = self.s.awarded()
        awarded_on = _dt.date.fromisoformat(self.p.award(req["id"])["created_at"][:10])
        # neither path may date delivery before the award was recorded
        with self.assertRaises(ProcurementError) as ctx:
            self.p.receive(e1["id"], "1999-01-01", "ok", "sha-ticket", actor="field")
        self.assertIn("before equipment P-101 was awarded", str(ctx.exception))
        with self.assertRaises(ProcurementError):
            self.p.record_actual(e1["id"], "delivery", (awarded_on - _dt.timedelta(days=1)).isoformat(), actor="pm")
        self.assertFalse(self.p.equipment(e1["id"])["received"])
        # record_actual("delivery") reports the arrival; the later receipt keeps it and may not predate it
        later = awarded_on + _dt.timedelta(days=5)
        with mock.patch.object(procurement_module, "_today", return_value=later):
            arrived = (awarded_on + _dt.timedelta(days=3)).isoformat()
            eq = self.p.record_actual(e1["id"], "delivery", arrived, actor="pm")
            self.assertEqual((eq["forecast"]["forecast_basis"], eq["forecast"]["forecast_delivery"]), ("actual", arrived))
            with self.assertRaises(ProcurementError):
                self.p.record_actual(e1["id"], "ship", (awarded_on + _dt.timedelta(days=4)).isoformat(), actor="pm")  # ship after delivery
            with self.assertRaises(ProcurementError) as ctx:
                self.p.receive(e1["id"], (awarded_on + _dt.timedelta(days=1)).isoformat(), "ok", "sha-ticket", actor="field")
            self.assertIn("before the recorded delivery actual", str(ctx.exception))
            rc = self.p.receive(e1["id"], later.isoformat(), "ok", "sha-ticket", actor="field")
        self.assertEqual(rc["received_date"], later.isoformat())
        eq = self.p.equipment(e1["id"])
        delivery = next(m for m in eq["milestones"] if m["name"] == "delivery")
        self.assertEqual((delivery["actual"], delivery["actual_source"]), (arrived, "record"))
        self.assertTrue(eq["received"])
        self.assertEqual(eq["forecast"]["forecast_delivery"], arrived)
        received = self.c.audit.entries(entity_type="procurement_receipt", entity_id=rc["id"])
        self.assertEqual(received[-1]["action"], "procurement.received")
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_receive_rules_and_damaged_flag(self):
        e1, e2, req, qc, res = self.s.awarded()
        for kwargs in (
            dict(received_date="2099-01-01", condition="ok", evidence_hash="sha-1"),
            dict(received_date=today(), condition="broken", evidence_hash="sha-1"),
            dict(received_date=today(), condition="ok", evidence_hash=""),
            dict(received_date=today(), condition="ok", evidence_hash=None),
            dict(received_date="2026-13-01", condition="ok", evidence_hash="sha-1"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProcurementError):
                self.p.receive(e1["id"], actor="field", **kwargs)
        rc = self.p.receive(e1["id"], today(), "damaged", "sha-photo-crate", note="impeller housing cracked", actor="field")
        self.assertTrue(rc["damaged"])
        with self.assertRaises(ProcurementError):
            self.p.receive(e1["id"], today(), "ok", "sha-photo-2", actor="field")
        st = self.p.state(self.s.pid)
        eq = next(x for x in st["equipment"] if x["id"] == e1["id"])
        self.assertTrue(eq["damaged"])
        self.assertEqual(next(m for m in eq["milestones"] if m["name"] == "delivery")["actual_source"], "receipt")
        self.assertEqual(st["summary"]["damaged_receipts"], 1)
        self.assertEqual(st["summary"]["received"], 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_receive_requires_award_even_with_selection(self):
        e1, e2, req, qa, qb, qc = self.s.golden_requisition()
        self.p.select_quote(req["id"], qb["id"], actor="pm")
        with self.assertRaises(ProcurementError):
            self.p.receive(e1["id"], today(), "ok", "sha-ticket", actor="field")
        self.assertEqual(self.p.equipment(e1["id"])["award_status"], "selected")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.c, self.p = self.s.c, self.s.p

    def test_state_shape_and_project_state(self):
        e1, e2, req, qc, res = self.s.awarded()
        self.s.equipment("V-301", "2027-06-01", description="Butterfly valve", long_lead=False)
        st = self.p.state(self.s.pid)
        json.dumps(st)  # JSON-serializable
        self.assertEqual(set(st), {"equipment", "requisitions", "long_lead_report", "summary"})
        self.assertEqual(st["summary"], {
            "equipment": 3, "long_lead": 2, "late": 0, "requisitions": 1, "open_requisitions": 0,
            "awarded": 1, "received": 0, "damaged_receipts": 0,
        })
        r = st["requisitions"][0]
        self.assertEqual(r["status"], "awarded")
        self.assertEqual(r["bid_tab"]["count"], 3)
        self.assertEqual(r["award"]["commitment"]["status"], "draft")
        self.assertEqual(r["award"]["commitment"]["original_amount"], "58000.00")
        e = next(x for x in st["equipment"] if x["tag"] == "P-101")
        self.assertEqual(set(e["forecast"]), {"required_on_site", "planned_delivery", "slip_days", "slip_basis", "forecast_delivery", "forecast_basis", "float_days", "late"})
        self.assertEqual(e["forecast"]["forecast_basis"], "none")
        statuses = {row["tag"]: row["award_status"] for row in st["long_lead_report"]}
        self.assertEqual(statuses, {"P-101": "awarded", "P-102": "awarded", "V-301": "not_requisitioned"})
        full = self.c.project_state(self.s.pid)
        self.assertIn("procurement", full)
        self.assertEqual(full["procurement"]["summary"]["awarded"], 1)

    def test_close_checks_are_informational(self):
        e1, e2, req, qc, res = self.s.awarded()
        self.p.set_milestone_plan(e1["id"], [{"name": "delivery", "planned": "2027-03-15"}], actor="pm")
        checks = self.p.close_checks("P1")
        self.assertTrue(checks)
        self.assertTrue(all(c["ok"] is True for c in checks))
        self.assertTrue(all(set(c) == {"check", "ok", "detail"} for c in checks))
        self.assertIn("1 award(s) recorded in P1", checks[0]["detail"])
        self.assertIn("1 equipment item(s)", checks[1]["detail"])
        closed = self.c.close_period("P1")
        self.assertEqual(closed["status"], "closed")


if __name__ == "__main__":
    unittest.main()
