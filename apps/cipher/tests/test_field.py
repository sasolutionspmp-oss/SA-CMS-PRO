"""EPC field controls: RFIs, submittals, hold points, punch list and closeout."""
import json
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import sha256_hex
from apps.cipher.domain.commitments import CommitmentError
from apps.cipher.domain.field import CLOSEOUT_ITEMS, DISTRIBUTION_SCHEMA_NAME, PLUGIN_NAME, SCHEMA_NAME, FieldError
from apps.cipher.domain.field import _recipients as field_recipients
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher, CipherError, RoleNotAuthorised

STALE = (StaleApprovalError, ApprovalNotGranted)


def ev_hash(label: str) -> str:
    return sha256_hex(f"synthetic closeout evidence: {label}".encode())


class Scene:
    """Fresh in-memory workspace: verified supplier, customer, project, open period P1, one evidence document."""

    def __init__(self):
        self.c = Cipher()
        self.f = self.c.plugin(PLUGIN_NAME)
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic Mechanical Sub", destination="ACH-SIM-FLD-1")
        self.c.verify_destination(self.supplier["id"], destination="ACH-SIM-FLD-1", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Synthetic Utility Board")
        self.project = self.c.create_project(name="Synthetic lift station", entity="S&A Solutions LLC (synthetic)", budget="250000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.doc = self.c.evidence.register_document(project_id=self.pid, kind="submittal", title="Product data", actor="o")
        self._n = 0

    def evidence(self, project_id=None):
        self._n += 1
        doc = self.doc
        if project_id is not None and project_id != self.pid:
            doc = self.c.evidence.register_document(project_id=project_id, kind="submittal", title="Foreign", actor="o")
        return self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic evidence {self._n}".encode(), actor="o")

    def commitment(self, *, project_id=None, execute=True):
        cm = self.c.commitments.create(
            project_id=project_id or self.pid, supplier_id=self.supplier["id"], title="Subcontract - mechanical",
            sov_lines=[{"description": "Piping", "amount": "60000"}, {"description": "Valves", "amount": "40000"}], retainage_rate="0.10", actor="o",
        )
        if execute:
            self.c.approve_and_execute("commitment.execute", cm["id"])
        return self.c.commitments.get(cm["id"])

    def drawing(self, number="D-101"):
        """Drawing with R1 issued and R2 working."""
        dp = self.c.plugin("drawing")
        doc = self.c.evidence.register_document(project_id=self.pid, kind="drawing", title=number, actor="o")
        dwg = dp.register_drawing(self.pid, number, "Process piping", "Mechanical", actor="o")
        ev1 = self.c.evidence.add_revision(document_id=doc["id"], content=f"{number} r1".encode(), actor="o")
        r1 = dp.add_revision(dwg["id"], "R1", ev1["id"], "IFC", actor="o")
        self.c.approve_and_execute("drawing.issue", r1["id"], period_id="P1")
        ev2 = self.c.evidence.add_revision(document_id=doc["id"], content=f"{number} r2".encode(), actor="o")
        r2 = dp.add_revision(dwg["id"], "R2", ev2["id"], "", actor="o")
        return dwg, dp.revision(r1["id"]), r2

    def rfi(self, subject="Pipe clash at grid C4", question="Reroute the 8 inch line around the beam?", **kw):
        return self.f.create_rfi(self.pid, subject, question, "pm", **kw)

    def answered_rfi(self, cost="10000", days=5, subject="Pipe clash at grid C4"):
        r = self.rfi(subject=subject)
        self.f.draft_response(r["id"], "Reroute below the beam per sketch SK-1.", cost_impact=cost, schedule_impact_days=days, actor="pm")
        self.c.approve_and_execute("field.respond_rfi", r["id"], actor_role="pm")
        return self.f.rfi(r["id"])

    def distribute(self, rfi_id, recipients):
        """Record the list, then distribute through the approval; returns the distribution row."""
        self.f.set_distribution_list(rfi_id, recipients, "pm")
        return self.c.approve_and_execute("field.distribute_rfi", rfi_id, actor_role="pm").result

    def submittal(self, title="Pinch valves", tag="PV-101"):
        return self.f.create_submittal(self.pid, "XX 05 61", title, "pm", equipment_tag=tag)

    def decide(self, revision_id, decision, comments=""):
        self.f.set_decision(revision_id, decision, comments, "eor")
        return self.c.approve_and_execute("field.decide_submittal", revision_id, actor_role="pm")

    def approved_submittal(self, **kw):
        s = self.submittal(**kw)
        rev = self.f.add_submittal_revision(s["id"], self.evidence()["id"], "pm")
        self.decide(rev["id"], "approved")
        return self.f.submittal(s["id"])

    def ready_closeout(self, cm_id, items=("as_builts", "om_manuals", "warranties", "final_lien_release")):
        self.f.set_closeout_requirements(cm_id, list(items), "pm")
        for item in items:
            self.f.submit_closeout_item(cm_id, item, ev_hash(f"{cm_id}:{item}"), "pm")
        return self.f.closeout(cm_id)


class FieldGoldenTests(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.f = self.s.f

    def test_golden_rfi_change_submittal_hold_point_and_closeout_flow(self):
        c, f, pid = self.c, self.f, self.s.pid
        dp = c.plugin("drawing")
        # drawing D-101: R1 issued, R2 working
        dwg, r1, r2 = self.s.drawing("D-101")
        self.assertEqual((r1["status"], r2["status"]), ("issued", "working"))

        # an RFI citing the working revision is rejected and leaves nothing behind
        with self.assertRaises(FieldError):
            self.s.rfi(drawing_revision_ids=[r2["id"]])
        self.assertEqual(f.rfis(pid), [])
        self.assertEqual(dp.references(r2["id"]), [])

        # citing the issued revision succeeds; the register lists the exact reference
        rfi = self.s.rfi(drawing_revision_ids=[r1["id"]], document_revision_ids=[r1["document_revision_id"]])
        self.assertEqual((rfi["number"], rfi["status"], rfi["version"]), ("RFI-001", "open", 1))
        self.assertEqual(rfi["drawing_revision_ids"], [r1["id"]])
        refs = dp.references(r1["id"])
        self.assertEqual(len(refs), 1)
        self.assertEqual((refs[0]["referenced_by_type"], refs[0]["referenced_by_id"], refs[0]["content_hash"]), ("rfi", rfi["id"], r1["content_hash"]))
        self.assertEqual(rfi["links"][0]["reference_id"], refs[0]["id"])

        # draft, request and grant; editing the draft afterwards makes the granted approval stale
        f.draft_response(rfi["id"], "Reroute below the beam.", cost_impact="10000", schedule_impact_days=5, actor="pm")
        ap = c.request_approval("field.respond_rfi", rfi["id"], actor_role="pm")
        self.assertEqual(ap["manifest"]["amounts"], {"cost_impact": "10000.00"})
        self.assertEqual(ap["manifest"]["bindings"]["schedule_impact_days"], 5)
        c.approve(ap["id"])
        f.draft_response(rfi["id"], "Reroute below the beam per sketch SK-1.", cost_impact="10000.00", schedule_impact_days=5, actor="pm")
        with self.assertRaises(STALE):
            c.execute(ap["id"])
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(f.rfi(rfi["id"])["status"], "open")

        res = c.approve_and_execute("field.respond_rfi", rfi["id"], actor_role="pm")
        self.assertEqual(res.result["status"], "answered")
        self.assertEqual((res.result["cost_impact"], res.result["schedule_impact_days"]), ("10000.00", 5))
        rfi = f.rfi(rfi["id"])
        self.assertEqual((rfi["status"], rfi["response"], rfi["cost_impact"], rfi["schedule_impact_days"]), ("answered", "Reroute below the beam per sketch SK-1.", "10000.00", 5))
        self.assertEqual(rfi["version"], 4)

        # distribution is its own approval-bound step to the mail sink; nothing is queued for sending
        recipients = ["Synthetic Engineer of Record", "Synthetic Owner Rep"]
        rfi = f.set_distribution_list(rfi["id"], recipients, actor="pm")
        self.assertEqual((rfi["version"], rfi["distribution_list"], rfi["distribution_pending"]), (5, recipients, True))
        res = c.approve_and_execute("field.distribute_rfi", rfi["id"], actor_role="pm")
        dist = res.result
        self.assertEqual((dist["channel"], dist["recipients"], dist["response_hash"], dist["rfi_version"]), ("mail-sink", recipients, rfi["response_hash"], 5))
        self.assertEqual(c.approvals.get(dist["approval_id"])["operation"], "field.distribute_rfi")
        self.assertFalse(f.rfi(rfi["id"])["distribution_pending"])
        self.assertEqual(c.commands.pending(), [])

        # the cost impact becomes a pending change; only change.execute moves the commitment
        cm = self.s.commitment()
        self.assertEqual(cm["executed_amount"], "100000.00")
        line1 = cm["sov"][0]["id"]
        ch = f.link_change(rfi["id"], cm["id"], "pm", sov_line_id=line1)
        self.assertEqual((ch["status"], ch["amount"], ch["reason"]), ("pending", "10000.00", "RFI-001: Pipe clash at grid C4"))
        fc = c.forecast.project(pid)
        self.assertEqual((fc["executed_commitments"], fc["pending_exposure"], fc["forecast_at_completion"]), ("100000.00", "10000.00", "110000.00"))
        self.assertEqual(c.commitments.get(cm["id"])["executed_amount"], "100000.00")
        c.approve_and_execute("change.execute", ch["id"])
        cm = c.commitments.get(cm["id"])
        self.assertEqual(cm["executed_amount"], "110000.00")
        self.assertEqual([s["amount"] for s in cm["sov"]], ["70000.00", "40000.00"])
        self.assertEqual(c.forecast.project(pid)["pending_exposure"], "0.00")
        self.assertEqual(f.rfi(rfi["id"])["change"]["status"], "executed")

        # submittal: R1 revise and resubmit, R2 approved; the hold point waits for approval
        journals_before = c.db.scalar("SELECT COUNT(*) FROM journals")
        sub = self.s.submittal()
        self.assertEqual((sub["number"], sub["status"]), ("SUB-001", "open"))
        hp = f.add_hold_point(pid, "Do not set PV-101 until the submittal is approved", sub["id"], "super")
        sr1 = f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        self.assertEqual((sr1["revision"], sr1["status"]), (1, "under_review"))
        with self.assertRaises(FieldError):
            f.release_hold_point(hp["id"], "super")
        self.s.decide(sr1["id"], "revise_resubmit", "Provide the pressure rating for the sleeve")
        self.assertEqual(f.submittal(sub["id"])["status"], "revise_resubmit")
        with self.assertRaises(FieldError):
            f.release_hold_point(hp["id"], "super")
        sr2 = f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        self.assertEqual(sr2["revision"], 2)
        res = self.s.decide(sr2["id"], "approved")
        self.assertEqual((res.result["submittal_status"], res.result["journals_posted"], res.result["authorizes_scope_or_payment"]), ("approved", 0, False))
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), journals_before)
        self.assertEqual(c.commitments.get(cm["id"])["executed_amount"], "110000.00")
        hp = f.release_hold_point(hp["id"], "super")
        self.assertEqual((hp["status"], hp["released_revision_id"]), ("released", sr2["id"]))

        # progress bill so that retainage is actually held
        bill = c.bills.certify(commitment_id=cm["id"], period_id="P1", installed=[{"sov_line_id": line1, "cumulative_installed": "20000"}], actor="o")
        c.approve_and_execute("bill.approve", bill["id"])
        self.assertEqual(c.ledger.balance("2050"), Decimal("2000.00"))

        # closeout: blocked by an open punch item and a missing item
        items = ["as_builts", "om_manuals", "warranties", "final_lien_release", "training"]
        co = f.set_closeout_requirements(cm["id"], items, "pm")
        self.assertEqual((co["status"], co["version"], co["required_items"]), ("open", 1, items))
        for item in items[:-1]:
            f.submit_closeout_item(cm["id"], item, ev_hash(item), "pm")
        punch = f.add_punch_item(pid, cm["id"], "Touch-up coating on PV-101 flange", "super")
        self.assertEqual((punch["number"], punch["status"]), ("PUNCH-001", "open"))
        with self.assertRaises(FieldError):
            c.request_approval("field.accept_closeout", cm["id"], actor_role="pm")
        f.close_punch_item(punch["id"], ev_hash("punch photo"), "super")
        with self.assertRaises(FieldError):  # training is still missing
            c.request_approval("field.accept_closeout", cm["id"], actor_role="pm")
        self.assertEqual(f.closeout(cm["id"])["missing"], ["training"])
        f.submit_closeout_item(cm["id"], "training", ev_hash("training sign-in sheet"), "pm")
        self.assertTrue(f.closeout(cm["id"])["ready_for_acceptance"])

        # before acceptance Ricky abstains on retainage release and the commitment cannot be closed directly
        self.assertEqual(c.ricky.propose("retainage.release", actor_role="owner", context={"commitment_id": cm["id"]})["decision"], "abstained")
        self.assertFalse(f.closeout_accepted(cm["id"]))
        with self.assertRaises(CipherError):
            c.close_commitment(cm["id"])
        self.assertEqual(c.commitments.get(cm["id"])["status"], "executed")
        res = c.approve_and_execute("field.accept_closeout", cm["id"], actor_role="pm", period_id="P1")
        self.assertEqual((res.result["status"], res.result["commitment_status"], res.result["period_id"]), ("accepted", "closed", "P1"))
        self.assertEqual(c.commitments.get(cm["id"])["status"], "closed")
        self.assertEqual(f.closeout(cm["id"])["status"], "accepted")
        self.assertTrue(f.closeout_accepted(cm["id"]))
        self.assertEqual(c.close_commitment(cm["id"])["status"], "closed")  # the interactive close now finds the accepted closeout

        prop = c.ricky.propose("retainage.release", actor_role="owner", context={"commitment_id": cm["id"]})
        self.assertEqual(prop["decision"], "proposed")
        self.assertEqual(prop["manifest"]["amounts"]["retainage_held"], "2000.00")
        c.approve_and_execute("retainage.release", cm["id"], actor_role="treasury", period_id="P1")
        self.assertEqual(c.ledger.balance("2050"), Decimal("0.00"))
        self.assertEqual(c.ledger.balance("2000"), Decimal("20000.00"))

        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])
        state = c.project_state(pid)["field"]
        self.assertEqual(state["summary"]["rfis_answered"], 1)
        self.assertEqual(state["summary"]["submittals_approved"], 1)
        self.assertEqual(state["summary"]["closeouts_accepted"], 1)
        json.dumps(state)


class RfiTests(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.f = self.s.f

    def test_schema_registered_and_empty_state_shape(self):
        status = self.c.db.schema_status()
        names = [v["name"] for v in status["versions"]]
        self.assertIn(SCHEMA_NAME, names)
        self.assertIn(DISTRIBUTION_SCHEMA_NAME, names)
        self.assertLess(names.index(SCHEMA_NAME), names.index(DISTRIBUTION_SCHEMA_NAME))  # the follow-on entry sits after the tables it alters
        self.assertTrue(all(v["applied"] for v in status["versions"]))
        tables = {r["name"] for r in self.c.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'field_%'")}
        self.assertEqual(tables, {
            "field_rfis", "field_rfi_links", "field_rfi_distributions", "field_submittals", "field_submittal_revisions",
            "field_hold_points", "field_punch_items", "field_closeout_requirements", "field_closeouts",
        })
        self.assertIs(self.c.plugin("field"), self.f)
        state = self.f.state(self.s.pid)
        self.assertEqual(set(state), {"rfis", "submittals", "hold_points", "punch_items", "closeouts", "summary"})
        self.assertEqual(state["rfis"], [])
        with self.assertRaises(FieldError):
            self.f.state("prj_missing")

    def test_rfi_numbers_are_sequential_per_project(self):
        a = self.s.rfi(subject="A")
        b = self.s.rfi(subject="B")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        o = self.f.create_rfi(other["id"], "A", "Reroute the 8 inch line around the beam?", "pm")
        self.assertEqual((a["number"], b["number"], o["number"]), ("RFI-001", "RFI-002", "RFI-001"))
        self.assertTrue(a["id"].startswith("rfi_"))
        self.assertEqual([e["action"] for e in self.c.audit.entries(entity_type="field_rfi", entity_id=a["id"])], ["field.rfi_created"])

    def test_create_rfi_validates_input_and_rejects_duplicates(self):
        with self.assertRaises(FieldError):
            self.f.create_rfi("prj_missing", "S", "Q", "pm")
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "  ", "Q", "pm")
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "S", None, "pm")
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "S", "Q", "")
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "S", "Q", "pm", document_revision_ids="rev_x")
        ev = self.s.evidence()
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "S", "Q", "pm", document_revision_ids=[ev["id"], ev["id"]])
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "S", "Q", "pm", document_revision_ids=["rev_missing"])
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        with self.assertRaises(FieldError):
            self.f.create_rfi(self.s.pid, "S", "Q", "pm", document_revision_ids=[self.s.evidence(project_id=other["id"])["id"]])
        r = self.f.create_rfi(self.s.pid, "S", "Q", "pm", document_revision_ids=[ev["id"]])
        self.assertEqual(r["document_revision_ids"], [ev["id"]])
        self.assertEqual(r["links"][0]["target_hash"], ev["content_hash"])
        with self.assertRaises(FieldError):  # same question again, case-insensitively
            self.f.create_rfi(self.s.pid, "s", " q ", "pm")
        self.assertEqual(len(self.f.rfis(self.s.pid)), 1)

    def test_rfi_cites_only_the_issued_revision_of_its_own_project(self):
        dp = self.c.plugin("drawing")
        dwg, r1, r2 = self.s.drawing("D-101")
        self.c.approve_and_execute("drawing.issue", r2["id"], period_id="P1")  # R1 is now superseded
        with self.assertRaises(FieldError):
            self.s.rfi(drawing_revision_ids=[r1["id"]])
        with self.assertRaises(FieldError):
            self.s.rfi(drawing_revision_ids=["dwr_missing"])
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        odoc = self.c.evidence.register_document(project_id=other["id"], kind="drawing", title="X", actor="o")
        odwg = dp.register_drawing(other["id"], "X-1", "Other", "Civil", actor="o")
        orev = dp.add_revision(odwg["id"], "R1", self.c.evidence.add_revision(document_id=odoc["id"], content=b"x1", actor="o")["id"], "", actor="o")
        self.c.approve_and_execute("drawing.issue", orev["id"], period_id="P1")
        with self.assertRaises(FieldError):
            self.s.rfi(drawing_revision_ids=[orev["id"]])
        self.assertEqual(self.f.rfis(self.s.pid), [])
        r = self.s.rfi(drawing_revision_ids=[r2["id"]])
        self.assertEqual([x["referenced_by_id"] for x in dp.references(r2["id"])], [r["id"]])
        self.assertEqual(dp.references(r1["id"]), [])

    def test_without_the_drawing_register_rfis_cannot_cite_drawings(self):
        dwg, r1, r2 = self.s.drawing("D-101")
        del self.c._plugins["drawing"]  # simulate a workspace without the drawing module
        with self.assertRaises(FieldError):
            self.s.rfi(drawing_revision_ids=[r1["id"]])
        r = self.s.rfi()
        self.assertEqual((r["number"], r["drawing_revision_ids"]), ("RFI-001", []))

    def test_draft_response_validates_and_bumps_the_version(self):
        r = self.s.rfi()
        for bad in (dict(cost_impact="-1"), dict(cost_impact=1.5), dict(cost_impact="abc"), dict(cost_impact=True),
                    dict(cost_impact="-0.001"), dict(cost_impact="-0.004"), dict(cost_impact=Decimal("-0.004")),
                    dict(cost_impact="NaN"), dict(cost_impact="Infinity"), dict(cost_impact="-Infinity"), dict(cost_impact="1e40"),
                    dict(schedule_impact_days=-1), dict(schedule_impact_days=True), dict(schedule_impact_days="5"), dict(schedule_impact_days=2.0)):
            with self.subTest(bad=bad), self.assertRaises(FieldError):
                self.f.draft_response(r["id"], "Text", actor="pm", **bad)
        with self.assertRaises(FieldError):
            self.f.draft_response(r["id"], "  ", actor="pm")
        with self.assertRaises(FieldError):
            self.f.draft_response(r["id"], "Text")  # no actor
        with self.assertRaises(FieldError):
            self.f.draft_response("rfi_missing", "Text", actor="pm")
        d = self.f.draft_response(r["id"], "No cost, no time.", actor="pm")
        self.assertEqual((d["version"], d["draft_cost_impact"], d["draft_schedule_impact_days"]), (2, None, None))
        with self.assertRaises(FieldError):  # identical redraft is a duplicate
            self.f.draft_response(r["id"], "No cost, no time.", actor="pm")
        d = self.f.draft_response(r["id"], "Add a sleeve.", cost_impact="1234.5", schedule_impact_days=0, actor="pm")
        self.assertEqual((d["version"], d["draft_cost_impact"], d["draft_schedule_impact_days"]), (3, "1234.50", 0))
        # a signed zero is stored and bound as the canonical "0.00", never "-0.00"
        d = self.f.draft_response(r["id"], "No cost after all.", cost_impact="-0", actor="pm")
        self.assertEqual((d["version"], d["draft_cost_impact"]), (4, "0.00"))
        d = self.f.draft_response(r["id"], "No cost, confirmed.", cost_impact=Decimal("-0.00"), actor="pm")
        self.assertEqual((d["version"], d["draft_cost_impact"]), (5, "0.00"))
        ap = self.c.request_approval("field.respond_rfi", r["id"], actor_role="pm")
        self.assertEqual((ap["manifest"]["amounts"], ap["manifest"]["bindings"]["cost_impact"]), ({"cost_impact": "0.00"}, "0.00"))

    def test_respond_requires_a_draft_and_an_open_rfi(self):
        r = self.s.rfi()
        with self.assertRaises(FieldError):
            self.c.request_approval("field.respond_rfi", r["id"], actor_role="pm")
        with self.c.db.transaction():  # the proposal gate does not depend on the caller's transaction state
            with self.assertRaises(FieldError):
                self.c.request_approval("field.respond_rfi", r["id"], actor_role="pm")
        self.assertEqual([a for a in self.c.approvals.list() if a["subject_id"] == r["id"]], [])
        self.assertEqual(self.c.ricky.propose("field.respond_rfi", actor_role="pm", context={"rfi_id": r["id"]})["decision"], "abstained")
        self.f.draft_response(r["id"], "Use detail 4.", actor="pm")
        self.assertEqual(self.c.ricky.propose("field.respond_rfi", actor_role="viewer", context={"rfi_id": r["id"]})["decision"], "abstained")
        self.assertEqual(self.c.ricky.propose("field.respond_rfi", actor_role="pm", context={"rfi_id": r["id"]})["decision"], "proposed")
        self.c.approve_and_execute("field.respond_rfi", r["id"], actor_role="pm")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.respond_rfi", r["id"], actor_role="pm")
        with self.assertRaises(FieldError):  # an answered RFI takes no new draft
            self.f.draft_response(r["id"], "Changed my mind.", actor="pm")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.unknown", r["id"])

    def test_second_respond_approval_is_invalidated_once_the_first_executes(self):
        r = self.s.rfi()
        self.f.draft_response(r["id"], "Use detail 4.", cost_impact="250", actor="pm")
        a1 = self.c.request_approval("field.respond_rfi", r["id"], actor_role="pm")
        a2 = self.c.request_approval("field.respond_rfi", r["id"], actor_role="pm")
        self.c.approve(a1["id"])
        self.c.approve(a2["id"])
        self.c.execute(a1["id"])
        with self.assertRaises(STALE):
            self.c.execute(a2["id"])
        self.assertEqual(self.c.approvals.get(a2["id"])["status"], "invalidated")
        self.assertEqual(self.f.rfi(r["id"])["approval_id"], a1["id"])

    def test_direct_distribution_is_retired_and_points_to_the_approval(self):
        r = self.s.answered_rfi()
        for args in ((r["id"], ["EOR"], "pm"), (r["id"],), ("rfi_missing", ["EOR"], "pm")):
            with self.subTest(args=args), self.assertRaisesRegex(FieldError, "field.distribute_rfi"):
                self.f.distribute_rfi(*args)
        self.assertEqual(self.f.rfi(r["id"])["distributions"], [])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM field_rfi_distributions"), 0)

    def test_distribution_only_after_answer_and_never_duplicated(self):
        r = self.s.rfi()
        self.f.draft_response(r["id"], "Use detail 4.", actor="pm")
        with self.assertRaises(FieldError):  # an open RFI has no distribution list yet
            self.f.set_distribution_list(r["id"], ["EOR"], "pm")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.c.approve_and_execute("field.respond_rfi", r["id"], actor_role="pm")
        with self.assertRaises(FieldError):  # answered, but nobody to send it to yet
            self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.assertEqual(self.c.ricky.propose("field.distribute_rfi", actor_role="pm", context={"rfi_id": r["id"]})["decision"], "abstained")
        for bad in ([], "EOR", ["EOR", " eor "], ["EOR", 7], [""], None, ("EOR", "EOR")):
            with self.subTest(bad=bad), self.assertRaises(FieldError):
                self.f.set_distribution_list(r["id"], bad, "pm")
        with self.assertRaises(FieldError):
            self.f.set_distribution_list(r["id"], ["EOR"], "")
        with self.assertRaises(FieldError):
            self.f.set_distribution_list("rfi_missing", ["EOR"], "pm")
        self.assertEqual(self.f.rfi(r["id"])["version"], 3)  # nothing invalid was recorded

        d1 = self.s.distribute(r["id"], ["EOR", "Owner rep"])
        self.assertEqual((d1["rfi_version"], d1["recipients"], d1["channel"]), (4, ["EOR", "Owner rep"], "mail-sink"))
        with self.assertRaises(FieldError):  # the same list again is not a change
            self.f.set_distribution_list(r["id"], ["owner rep", "EOR"], "pm")
        with self.assertRaises(FieldError):  # already distributed to exactly this list: nothing to approve
            self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        d2 = self.s.distribute(r["id"], ["Superintendent"])
        self.assertEqual(d2["rfi_version"], 5)
        with self.assertRaises(FieldError):  # back to a list that already received this response, any order or case
            self.f.set_distribution_list(r["id"], ["owner rep", "eor"], "pm")
        rfi = self.f.rfi(r["id"])
        self.assertEqual([d["id"] for d in rfi["distributions"]], [d1["id"], d2["id"]])
        self.assertEqual((rfi["version"], rfi["status"], rfi["distribution_list"], rfi["distribution_pending"]), (5, "answered", ["Superintendent"], False))
        self.assertEqual(len({d["approval_id"] for d in rfi["distributions"]}), 2)  # one approval per distribution
        self.assertEqual(self.c.commands.pending(), [])
        actions = [e["action"] for e in self.c.audit.entries(entity_type="field_rfi", entity_id=r["id"])]
        self.assertEqual(actions.count("field.rfi_distribution_list_set"), 2)
        self.assertEqual(actions.count("field.rfi_distributed"), 2)

    def test_distribution_approval_binds_version_response_and_recipients(self):
        r = self.s.answered_rfi()
        rfi = self.f.set_distribution_list(r["id"], ["EOR", "Owner rep"], "pm")
        ap = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        b = ap["manifest"]["bindings"]
        self.assertEqual((b["rfi_version"], b["response_hash"], b["recipients_hash"], b["recipients"], b["channel"]),
                         (rfi["version"], rfi["response_hash"], rfi["distribution_recipients_hash"], ["EOR", "Owner rep"], "mail-sink"))
        self.assertEqual((ap["manifest"]["amounts"], ap["manifest"]["entity"]), ({}, self.s.project["entity"]))
        self.c.approve(ap["id"])

        # a recipients change after the grant makes the approval stale (proactively and at execution)
        self.f.set_distribution_list(r["id"], ["EOR", "Owner rep", "Superintendent"], "pm")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(STALE):
            self.c.execute(ap["id"])
        self.assertEqual(self.f.rfi(r["id"])["distributions"], [])

        # a raw edit that bumps the version without telling anyone is still caught: the list is
        # rebuilt and re-hashed from the stored JSON, so a hash that is not its own refuses it
        ap2 = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.c.approve(ap2["id"])
        self.c.db.execute("UPDATE field_rfis SET distribution_recipients_json=?, distribution_recipients_hash='forged', version=version+1 WHERE id=?", ('["Someone else"]', r["id"]))
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "granted")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap2["id"])
        ap2 = self.c.approvals.get(ap2["id"])
        self.assertEqual(ap2["status"], "invalidated")
        self.assertIn("does not match its recipients hash", ap2["invalidated_reason"])
        self.assertEqual(self.f.rfi(r["id"])["distributions"], [])
        # a consistent raw edit (the list's own hash, version bumped) is caught by the bound version and list
        self.f.set_distribution_list(r["id"], ["EOR", "Owner rep"], "pm")
        ap2b = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.c.approve(ap2b["id"])
        _, other_hash = field_recipients(["Owner rep"])
        self.c.db.execute("UPDATE field_rfis SET distribution_recipients_json=?, distribution_recipients_hash=?, version=version+1 WHERE id=?", ('["Owner rep"]', other_hash, r["id"]))
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap2b["id"])
        self.assertIn("bindings", self.c.approvals.get(ap2b["id"])["invalidated_reason"])
        self.assertEqual(self.f.rfi(r["id"])["distributions"], [])

        # roles: the pm and the owner hold the authority; a viewer or estimator does not
        self.f.set_distribution_list(r["id"], ["EOR"], "pm")
        for role in ("viewer", "estimator", "treasury"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorised):
                self.c.request_approval("field.distribute_rfi", r["id"], actor_role=role)
        ap3 = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        with self.assertRaises(RoleNotAuthorised):
            self.c.approve(ap3["id"], approver="someone", approver_role="estimator")
        self.c.approve(ap3["id"], approver="pm-user", approver_role="pm")
        dist = self.c.execute(ap3["id"], actor="pm").result
        self.assertEqual((dist["recipients"], dist["approval_id"]), (["EOR"], ap3["id"]))
        replay = self.c.execute(ap3["id"], actor="pm")  # same op id: the stored result, no second row
        self.assertTrue(replay.replayed)
        self.assertEqual(len(self.f.rfi(r["id"])["distributions"]), 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_second_distribution_approval_on_the_same_list_goes_stale(self):
        r = self.s.answered_rfi()
        self.f.set_distribution_list(r["id"], ["EOR"], "pm")
        a1 = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        a2 = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.c.approve(a1["id"])
        self.c.approve(a2["id"])
        self.c.execute(a1["id"])
        self.assertEqual(self.c.approvals.get(a2["id"])["status"], "invalidated")
        with self.assertRaises(STALE):
            self.c.execute(a2["id"])
        self.assertEqual(len(self.f.rfi(r["id"])["distributions"]), 1)

    def test_forged_or_malformed_stored_list_is_never_distributed(self):
        """The once-only rule rests on the stored recipients hash, which SQLite cannot verify;
        the module rebuilds the list and its hash from the stored JSON and refuses a mismatch."""
        r = self.s.answered_rfi()
        d1 = self.s.distribute(r["id"], ["EOR"])
        forge = "UPDATE field_rfis SET distribution_recipients_json=?, distribution_recipients_hash=?, version=version+1 WHERE id=?"

        # the probe: the same recipients under a hash that is not theirs (every trigger accepts it)
        self.f.set_distribution_list(r["id"], ["Superintendent"], "pm")
        granted = self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.c.approve(granted["id"])
        self.c.db.execute(forge, ('["EOR"]', "forged-x", r["id"]))
        rfi = self.f.rfi(r["id"])
        self.assertEqual((rfi["distribution_list"], rfi["distribution_list_intact"], rfi["distribution_pending"]), (["EOR"], False, False))
        with self.assertRaisesRegex(FieldError, "does not match its recipients hash"):
            self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        with self.assertRaises(STALE):  # the approval granted before the forgery cannot use it either
            self.c.execute(granted["id"])
        self.assertEqual(self.c.approvals.get(granted["id"])["status"], "invalidated")
        self.assertEqual([d["id"] for d in self.f.rfi(r["id"])["distributions"]], [d1["id"]])
        with self.assertRaisesRegex(FieldError, "already distributed"):  # and the list cannot be "repaired" into a second copy
            self.f.set_distribution_list(r["id"], ["eor"], "pm")

        # a value that is not a recipient list at all, and a non-canonical list under its own hash
        _, owner_hash = field_recipients(["Owner rep"])
        for raw, h, why in (('"not a list"', "forged-y", "not a valid recipient list"), ("{not json", "forged-z", "not a valid recipient list"),
                            ('["  Owner rep "]', owner_hash, "does not match its recipients hash"), ('["Owner rep","owner REP"]', "forged-w", "not a valid recipient list")):
            with self.subTest(raw=raw):
                self.c.db.execute(forge, (raw, h, r["id"]))
                self.assertFalse(self.f.rfi(r["id"])["distribution_list_intact"])
                with self.assertRaisesRegex(FieldError, why):
                    self.c.request_approval("field.distribute_rfi", r["id"], actor_role="pm")
        self.assertEqual(self.f.rfi(r["id"])["distribution_list"], ["Owner rep", "owner REP"])
        json.dumps(self.f.audit_export())  # the export still renders a tampered list, flagged
        self.assertEqual([x["distribution_list_intact"] for x in self.f.audit_export()["rfis"]], [False])

        # recording a proper list through the module repairs it; the distribution goes to exactly that list
        self.f.set_distribution_list(r["id"], ["Owner rep"], "pm")
        d2 = self.c.approve_and_execute("field.distribute_rfi", r["id"], actor_role="pm").result
        self.assertEqual((d2["recipients"], d2["recipients_hash"]), (["Owner rep"], owner_hash))
        rows = self.c.db.query("SELECT recipients_json, recipients_hash FROM field_rfi_distributions WHERE rfi_id=? ORDER BY distributed_at, id", (r["id"],))
        self.assertEqual([(x["recipients_json"], x["recipients_hash"]) for x in rows],
                         [('["EOR"]', field_recipients(["EOR"])[1]), ('["Owner rep"]', owner_hash)])
        self.assertEqual(self.c.commands.pending(), [])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_link_change_guards(self):
        cm = self.s.commitment()
        open_rfi = self.s.rfi(subject="Open one")
        with self.assertRaises(FieldError):
            self.f.link_change(open_rfi["id"], cm["id"], "pm")
        no_cost = self.s.answered_rfi(cost=None, subject="No cost")
        zero_cost = self.s.answered_rfi(cost="0", subject="Zero cost")
        for r in (no_cost, zero_cost):
            with self.assertRaises(FieldError):
                self.f.link_change(r["id"], cm["id"], "pm")
        rfi = self.s.answered_rfi(cost="10000", subject="Costed")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        with self.assertRaises(FieldError):
            self.f.link_change(rfi["id"], self.s.commitment(project_id=other["id"])["id"], "pm")
        with self.assertRaises(FieldError):
            self.f.link_change(rfi["id"], self.s.commitment(execute=False)["id"], "pm")
        with self.assertRaises(FieldError):
            self.f.link_change(rfi["id"], "cmt_missing", "pm")
        foreign_line = self.s.commitment()["sov"][0]["id"]
        with self.assertRaises(FieldError):  # SOV line of another commitment
            self.f.link_change(rfi["id"], cm["id"], "pm", sov_line_id=foreign_line)
        self.assertEqual(self.c.commitments.pending_exposure(self.s.pid), Decimal("0.00"))
        ch = self.f.link_change(rfi["id"], cm["id"], "pm")
        self.assertEqual((ch["status"], ch["amount"], ch["rfi_number"]), ("pending", "10000.00", rfi["number"]))
        with self.assertRaises(FieldError):  # one change per RFI
            self.f.link_change(rfi["id"], cm["id"], "pm")
        self.assertEqual(self.c.commitments.pending_exposure(self.s.pid), Decimal("10000.00"))
        self.assertEqual(self.c.commitments.get(cm["id"])["executed_amount"], "100000.00")
        self.assertEqual(self.f.rfi(rfi["id"])["change"]["id"], ch["id"])


class SubmittalTests(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.f = self.s.f

    def test_submittal_numbering_validation_and_duplicates(self):
        a = self.s.submittal()
        b = self.s.submittal(title="Check valves", tag=None)
        self.assertEqual((a["number"], b["number"], a["equipment_tag"], b["equipment_tag"]), ("SUB-001", "SUB-002", "PV-101", None))
        with self.assertRaises(FieldError):
            self.f.create_submittal(self.s.pid, "XX 05 61", "pinch VALVES", "pm", equipment_tag="pv-101")
        with self.assertRaises(FieldError):
            self.f.create_submittal(self.s.pid, "", "T", "pm")
        with self.assertRaises(FieldError):
            self.f.create_submittal(self.s.pid, "XX 05 61", None, "pm")
        with self.assertRaises(FieldError):
            self.f.create_submittal("prj_missing", "XX 05 61", "T", "pm")
        self.assertEqual(self.f.create_submittal(self.s.pid, "XX 05 61", "Pinch valves", "pm", equipment_tag="PV-102")["number"], "SUB-003")

    def test_one_revision_under_review_and_evidence_of_same_project(self):
        sub = self.s.submittal()
        ev = self.s.evidence()
        r1 = self.f.add_submittal_revision(sub["id"], ev["id"], "pm")
        self.assertEqual((r1["revision"], r1["status"], r1["version"], r1["document_hash"]), (1, "under_review", 1, ev["content_hash"]))
        self.assertEqual(self.f.submittal(sub["id"])["status"], "under_review")
        with self.assertRaises(FieldError):
            self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        sub2 = self.s.submittal(title="Other", tag=None)
        with self.assertRaises(FieldError):
            self.f.add_submittal_revision(sub2["id"], self.s.evidence(project_id=other["id"])["id"], "pm")
        with self.assertRaises(FieldError):
            self.f.add_submittal_revision(sub2["id"], "rev_missing", "pm")
        self.s.decide(r1["id"], "revise_resubmit", "Add the coating data")
        with self.assertRaises(FieldError):  # the same evidence cannot be resubmitted
            self.f.add_submittal_revision(sub["id"], ev["id"], "pm")
        r2 = self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        self.assertEqual(r2["revision"], 2)

    def test_set_decision_validation_and_version(self):
        sub = self.s.submittal()
        rev = self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        for decision, comments, actor in (("maybe", "", "eor"), (None, "", "eor"), ("approved", 5, "eor"), ("approved", "", " ")):
            with self.subTest(decision=decision, comments=comments, actor=actor), self.assertRaises(FieldError):
                self.f.set_decision(rev["id"], decision, comments, actor)
        with self.assertRaises(FieldError):
            self.f.set_decision("subr_missing", "approved", "", "eor")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.decide_submittal", rev["id"], actor_role="pm")  # nothing recorded yet
        # comments are optional for every decision, as the spec's set_decision signature has it
        d = self.f.set_decision(rev["id"], "revise_resubmit", "", "eor")
        self.assertEqual((d["version"], d["draft_decision"], d["draft_comments"]), (2, "revise_resubmit", ""))
        d = self.f.set_decision(rev["id"], "approved_as_noted", "Field verify the flange rating", "eor")
        self.assertEqual((d["version"], d["draft_decision"], d["status"]), (3, "approved_as_noted", "under_review"))
        with self.assertRaises(FieldError):
            self.f.set_decision(rev["id"], "approved_as_noted", "Field verify the flange rating", "eor")
        res = self.c.approve_and_execute("field.decide_submittal", rev["id"], actor_role="pm")
        self.assertEqual(res.result["submittal_status"], "approved")
        rev = self.f.submittal_revision(rev["id"])
        self.assertEqual((rev["status"], rev["decision"], rev["comments"], rev["version"]), ("approved_as_noted", "approved_as_noted", "Field verify the flange rating", 4))
        with self.assertRaises(FieldError):
            self.f.set_decision(rev["id"], "rejected", "too late", "eor")
        with self.assertRaises(FieldError):  # approved is final
            self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")

    def test_decision_approval_goes_stale_when_the_decision_changes(self):
        sub = self.s.submittal()
        rev = self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        self.f.set_decision(rev["id"], "approved", "", "eor")
        ap = self.c.request_approval("field.decide_submittal", rev["id"], actor_role="pm")
        self.assertEqual(ap["manifest"]["bindings"]["decision"], "approved")
        self.assertFalse(ap["manifest"]["bindings"]["authorizes_scope_or_payment"])
        self.c.approve(ap["id"])
        self.f.set_decision(rev["id"], "rejected", "Wrong body material", "eor")
        with self.assertRaises(STALE):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.f.submittal(sub["id"])["status"], "under_review")
        self.c.approve_and_execute("field.decide_submittal", rev["id"], actor_role="pm")  # the recorded "rejected" decision
        self.assertEqual(self.f.submittal(sub["id"])["status"], "rejected")
        with self.assertRaises(FieldError):  # rejected is final
            self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")

    def test_hold_point_release_waits_for_approval(self):
        sub = self.s.submittal()
        hp = self.f.add_hold_point(self.s.pid, "Hold pump base grout", sub["id"], "super")
        self.assertEqual((hp["status"], hp["version"]), ("held", 1))
        with self.assertRaises(FieldError):  # duplicate hold
            self.f.add_hold_point(self.s.pid, "hold pump base GROUT", sub["id"], "super")
        with self.assertRaises(FieldError):
            self.f.add_hold_point(self.s.pid, "", sub["id"], "super")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        with self.assertRaises(FieldError):
            self.f.add_hold_point(other["id"], "Hold", sub["id"], "super")
        with self.assertRaises(FieldError):
            self.f.add_hold_point(self.s.pid, "Hold", "sub_missing", "super")
        with self.assertRaises(FieldError):
            self.f.release_hold_point(hp["id"], "super")
        rev = self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        with self.assertRaises(FieldError):
            self.f.release_hold_point(hp["id"], "super")
        self.s.decide(rev["id"], "approved")
        hp = self.f.release_hold_point(hp["id"], "super")
        self.assertEqual((hp["status"], hp["released_revision_id"], hp["version"]), ("released", rev["id"], 2))
        with self.assertRaises(FieldError):
            self.f.release_hold_point(hp["id"], "super")
        rejected = self.s.submittal(title="Rejected one", tag=None)
        rrev = self.f.add_submittal_revision(rejected["id"], self.s.evidence()["id"], "pm")
        self.s.decide(rrev["id"], "rejected", "Not the specified product")
        with self.assertRaises(FieldError):
            self.f.add_hold_point(self.s.pid, "Hold", rejected["id"], "super")


class CloseoutTests(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.f = self.s.f
        self.cm = self.s.commitment()

    def test_punch_items_validation_and_closure(self):
        pid = self.s.pid
        p = self.f.add_punch_item(pid, self.cm["id"], "Label valve V-3", "super")
        self.assertEqual((p["number"], p["status"], p["version"]), ("PUNCH-001", "open", 1))
        with self.assertRaises(FieldError):
            self.f.add_punch_item(pid, self.cm["id"], " label VALVE v-3 ", "super")
        with self.assertRaises(FieldError):
            self.f.add_punch_item(pid, self.cm["id"], "", "super")
        with self.assertRaises(FieldError):
            self.f.add_punch_item(pid, self.s.commitment(execute=False)["id"], "Item", "super")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        with self.assertRaises(FieldError):
            self.f.add_punch_item(other["id"], self.cm["id"], "Item", "super")
        with self.assertRaises(FieldError):
            self.f.close_punch_item(p["id"], "  ", "super")
        with self.assertRaises(FieldError):
            self.f.close_punch_item(p["id"], None, "super")
        closed = self.f.close_punch_item(p["id"], ev_hash("label photo"), "super")
        self.assertEqual((closed["status"], closed["evidence_hash"], closed["version"]), ("closed", ev_hash("label photo"), 2))
        with self.assertRaises(FieldError):
            self.f.close_punch_item(p["id"], ev_hash("again"), "super")
        self.assertEqual(self.f.add_punch_item(pid, self.cm["id"], "Label valve V-3", "super")["number"], "PUNCH-002")

    def test_closeout_requirements_validation_and_versions(self):
        cid = self.cm["id"]
        for bad in ([], "as_builts", ["as_builts", "as_builts"], ["as_builts", "photos"], [None]):
            with self.subTest(bad=bad), self.assertRaises(FieldError):
                self.f.set_closeout_requirements(cid, bad, "pm")
        with self.assertRaises(FieldError):
            self.f.set_closeout_requirements(self.s.commitment(execute=False)["id"], ["as_builts"], "pm")
        with self.assertRaises(FieldError):
            self.f.submit_closeout_item(cid, "as_builts", ev_hash("ab"), "pm")  # no requirements yet
        co = self.f.set_closeout_requirements(cid, ["warranties", "as_builts"], "pm")
        self.assertEqual((co["version"], co["required_items"], co["status"]), (1, ["as_builts", "warranties"], "open"))
        with self.assertRaises(FieldError):  # unchanged list
            self.f.set_closeout_requirements(cid, ["as_builts", "warranties"], "pm")
        with self.assertRaises(FieldError):
            self.f.submit_closeout_item(cid, "training", ev_hash("t"), "pm")  # not required
        with self.assertRaises(FieldError):
            self.f.submit_closeout_item(cid, "bogus", ev_hash("t"), "pm")
        with self.assertRaises(FieldError):
            self.f.submit_closeout_item(cid, "as_builts", "", "pm")
        co = self.f.submit_closeout_item(cid, "as_builts", ev_hash("ab"), "pm")
        self.assertEqual(co["version"], 2)
        with self.assertRaises(FieldError):  # duplicate submission
            self.f.submit_closeout_item(cid, "as_builts", ev_hash("ab"), "pm")
        with self.assertRaises(FieldError):  # same evidence for another item
            self.f.submit_closeout_item(cid, "warranties", ev_hash("ab"), "pm")
        co = self.f.set_closeout_requirements(cid, list(CLOSEOUT_ITEMS), "pm")
        self.assertEqual((co["version"], co["missing"]), (3, ["om_manuals", "warranties", "final_lien_release", "training", "attic_stock"]))
        co = self.f.set_closeout_requirements(cid, ["as_builts"], "pm")
        self.assertEqual((co["version"], co["missing"], co["required_items"]), (4, [], ["as_builts"]))
        self.assertTrue(co["ready_for_acceptance"])
        self.assertEqual(len(co["requirements"]), 6)  # history of every item ever required is kept

    def test_acceptance_blocked_by_open_punch_or_missing_item(self):
        cid = self.cm["id"]
        with self.assertRaises(FieldError):  # no requirements at all
            self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.f.set_closeout_requirements(cid, ["as_builts", "om_manuals"], "pm")
        self.f.submit_closeout_item(cid, "as_builts", ev_hash("ab"), "pm")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.assertEqual(self.c.ricky.propose("field.accept_closeout", actor_role="pm", context={"commitment_id": cid})["decision"], "abstained")
        self.f.submit_closeout_item(cid, "om_manuals", ev_hash("om"), "pm")
        p = self.f.add_punch_item(self.s.pid, cid, "Missing nameplate", "super")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.f.close_punch_item(p["id"], ev_hash("nameplate"), "super")
        self.assertEqual(self.c.ricky.propose("field.accept_closeout", actor_role="pm", context={"commitment_id": cid})["decision"], "proposed")
        self.assertEqual(self.c.commitments.get(cid)["status"], "executed")

    def test_acceptance_approval_goes_stale_when_a_punch_item_is_added(self):
        cid = self.cm["id"]
        self.s.ready_closeout(cid)
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.assertEqual(ap["manifest"]["bindings"]["open_punch_count"], 0)
        self.c.approve(ap["id"])
        self.f.add_punch_item(self.s.pid, cid, "Leak at union", "super")
        with self.assertRaises(STALE):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.commitments.get(cid)["status"], "executed")
        self.assertEqual(self.f.closeout(cid)["status"], "open")

    def test_acceptance_approval_goes_stale_when_the_commitment_changes(self):
        """No field record changes here: a core change proposed and executed
        after the grant bumps the commitment version and amount, so the
        re-derived manifest no longer matches and the core's material
        comparison invalidates the approval."""
        cid = self.cm["id"]
        self.s.ready_closeout(cid)
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.c.approve(ap["id"])
        ch = self.c.commitments.propose_change(cid, amount="500", reason="late extra", actor="pm")
        self.c.approve_and_execute("change.execute", ch["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # nothing told the field module
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], period_id="P1")
        ap = self.c.approvals.get(ap["id"])
        self.assertEqual(ap["status"], "invalidated")
        self.assertIn("amounts", ap["invalidated_reason"])
        self.assertEqual(self.c.commitments.get(cid)["status"], "executed")
        res = self.c.approve_and_execute("field.accept_closeout", cid, actor_role="pm", period_id="P1")
        self.assertEqual(res.result["commitment_status"], "closed")
        self.assertEqual(self.c.commitments.get(cid)["executed_amount"], "100500.00")

    def test_pending_change_blocks_acceptance_and_link_change_invalidates_the_approval(self):
        """A commitment must not close while a change on it is still pending,
        whether an answered RFI raised it or the core did; otherwise it could
        grow through change.execute after retainage is released."""
        cid = self.cm["id"]
        self.s.ready_closeout(cid)
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.assertEqual((ap["manifest"]["bindings"]["pending_changes"], ap["manifest"]["amounts"]["pending_change_exposure"]), ([], "0.00"))
        self.c.approve(ap["id"])
        rfi = self.s.answered_rfi(cost="5000")
        ch = self.f.link_change(rfi["id"], cid, "pm")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        linked = [json.loads(e["payload_json"]) for e in self.c.audit.entries(entity_type="field_rfi", entity_id=rfi["id"]) if e["action"] == "field.rfi_change_linked"]
        self.assertEqual(linked[0]["closeout_approvals_invalidated"], 1)
        with self.assertRaises(STALE):
            self.c.execute(ap["id"], period_id="P1")
        co = self.f.closeout(cid)
        self.assertEqual((co["status"], co["ready_for_acceptance"], co["pending_change_exposure"]), ("open", False, "5000.00"))
        self.assertEqual([p["id"] for p in co["pending_changes"]], [ch["id"]])
        self.assertTrue(any("pending change" in b for b in co["blockers"]))
        with self.assertRaises(FieldError):
            self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.assertEqual(self.c.ricky.propose("field.accept_closeout", actor_role="pm", context={"commitment_id": cid})["decision"], "abstained")

        # once the change is executed the closeout is proposable again; a change proposed in the core then stales the grant
        self.c.approve_and_execute("change.execute", ch["id"])
        ap2 = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.assertEqual(ap2["manifest"]["amounts"]["commitment_executed_amount"], "105000.00")
        self.c.approve(ap2["id"])
        ch2 = self.c.commitments.propose_change(cid, amount="750", reason="core extra", actor="pm")
        with self.assertRaises(STALE):
            self.c.execute(ap2["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        self.assertEqual((self.c.commitments.get(cid)["status"], self.f.closeout(cid)["status"]), ("executed", "open"))

        self.c.commitments.reject_change(ch2["id"], actor="pm", reason="withdrawn")
        res = self.c.approve_and_execute("field.accept_closeout", cid, actor_role="pm", period_id="P1")
        self.assertEqual((res.result["status"], res.result["commitment_status"]), ("accepted", "closed"))
        cm = self.c.commitments.get(cid)
        self.assertEqual((cm["status"], cm["executed_amount"]), ("closed", "105000.00"))
        self.assertEqual(self.c.commitments.pending_exposure(self.s.pid), Decimal("0.00"))
        with self.assertRaises(CommitmentError):  # the core refuses a change on a closed commitment
            self.c.commitments.propose_change(cid, amount="1", reason="after close", actor="pm")
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_acceptance_approval_goes_stale_when_evidence_is_resubmitted(self):
        cid = self.cm["id"]
        self.s.ready_closeout(cid)
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.c.approve(ap["id"])
        self.f.submit_closeout_item(cid, "warranties", ev_hash("corrected warranty"), "pm")
        with self.assertRaises(STALE):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        res = self.c.approve_and_execute("field.accept_closeout", cid, actor_role="pm", period_id="P1")
        self.assertEqual(res.result["status"], "accepted")
        self.assertEqual(self.f.closeout(cid)["acceptance_hash"], res.result["acceptance_hash"])
        with self.assertRaises(FieldError):  # accepted closeouts are frozen
            self.f.submit_closeout_item(cid, "warranties", ev_hash("late"), "pm")
        with self.assertRaises(FieldError):
            self.f.add_punch_item(self.s.pid, cid, "Late item", "super")
        with self.assertRaises(FieldError):
            self.c.request_approval("field.accept_closeout", cid, actor_role="pm")

    def test_acceptance_into_a_closed_period_is_rejected(self):
        cid = self.cm["id"]
        self.s.ready_closeout(cid)
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        self.c.close_period("P1")
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.c.approve(ap["id"])
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.assertEqual(self.c.commitments.get(cid)["status"], "executed")
        self.assertEqual(self.f.closeout(cid)["status"], "open")
        res = self.c.execute(ap["id"], period_id="P2")
        self.assertEqual((res.result["status"], res.result["period_id"]), ("accepted", "P2"))
        self.assertEqual(self.c.commitments.get(cid)["status"], "closed")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "consumed")

    def test_close_checks_are_informational(self):
        self.s.rfi()
        sub = self.s.submittal()
        self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        self.f.add_hold_point(self.s.pid, "Hold", sub["id"], "super")
        self.f.add_punch_item(self.s.pid, self.cm["id"], "Item", "super")
        self.f.set_closeout_requirements(self.cm["id"], ["as_builts"], "pm")
        checks = self.f.close_checks("P1")
        self.assertTrue(all(ch["ok"] is True for ch in checks))
        details = {ch["check"]: ch["detail"] for ch in checks}
        self.assertTrue(details["field.open_rfis"].startswith("1 "))
        self.assertTrue(details["field.submittals_under_review"].startswith("1 "))
        self.assertTrue(details["field.open_punch_items"].startswith("1 "))
        self.assertTrue(details["field.rfis_awaiting_distribution"].startswith("0 "))
        self.assertTrue(all(set(ch) == {"check", "ok", "detail"} for ch in checks))
        answered = self.s.answered_rfi(subject="Answered one")
        self.assertTrue({ch["check"]: ch["detail"] for ch in self.f.close_checks("P1")}["field.rfis_awaiting_distribution"].startswith("1 "))
        self.s.distribute(answered["id"], ["EOR"])
        self.assertTrue({ch["check"]: ch["detail"] for ch in self.f.close_checks("P1")}["field.rfis_awaiting_distribution"].startswith("0 "))

    def test_closeout_accepted_only_after_the_acceptance_approval(self):
        cid = self.cm["id"]
        for bad in (None, "", "   ", 7, "cmt_missing"):
            with self.subTest(bad=bad):
                self.assertFalse(self.f.closeout_accepted(bad))
        self.assertFalse(self.f.closeout_accepted(cid))  # closeout not started
        self.s.ready_closeout(cid)
        self.assertTrue(self.f.closeout(cid)["ready_for_acceptance"])
        self.assertFalse(self.f.closeout_accepted(cid))  # ready is not accepted
        with self.assertRaisesRegex(CipherError, "field.accept_closeout"):
            self.c.close_commitment(cid)
        # a granted approval that goes stale does not accept anything
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.c.approve(ap["id"])
        self.assertFalse(self.f.closeout_accepted(cid))
        self.f.submit_closeout_item(cid, "warranties", ev_hash("corrected"), "pm")
        with self.assertRaises(STALE):
            self.c.execute(ap["id"], period_id="P1")
        self.assertFalse(self.f.closeout_accepted(cid))
        # raw SQL cannot fake an acceptance either
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE field_closeouts SET status='accepted', approval_id=?, accepted_by='x', accepted_at='t', acceptance_hash='h', "
                              "accepted_period_id='P1', version=version+1 WHERE commitment_id=?", (ap["id"], cid))
        self.assertFalse(self.f.closeout_accepted(cid))
        self.assertEqual(self.c.commitments.get(cid)["status"], "executed")

        self.c.approve_and_execute("field.accept_closeout", cid, actor_role="pm", period_id="P1")
        self.assertTrue(self.f.closeout_accepted(cid))
        self.assertTrue(self.f.closeout_accepted(f"  {cid} "))
        self.assertEqual(self.c.close_commitment(cid)["status"], "closed")
        other = self.s.commitment()
        self.assertFalse(self.f.closeout_accepted(other["id"]))  # per commitment


class FieldIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.f = self.s.f

    def test_database_guards_without_the_plugin(self):
        db = self.c.db
        r = self.s.rfi()
        self.f.draft_response(r["id"], "Use detail 4.", actor="pm")
        with self.assertRaises(sqlite3.IntegrityError):  # answering without a consumed approval
            db.execute("UPDATE field_rfis SET status='answered', response=draft_response, response_hash=draft_response_hash, answered_at='t', version=version+1 WHERE id=?", (r["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE field_rfis SET question='edited', version=version+1 WHERE id=?", (r["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM field_rfis WHERE id=?", (r["id"],))
        self.c.approve_and_execute("field.respond_rfi", r["id"], actor_role="pm")
        with self.assertRaises(sqlite3.IntegrityError):  # answered RFIs are immutable
            db.execute("UPDATE field_rfis SET updated_at='x', version=version+1 WHERE id=?", (r["id"],))
        sub = self.s.submittal()
        hp = self.f.add_hold_point(self.s.pid, "Hold", sub["id"], "super")
        with self.assertRaises(sqlite3.IntegrityError):  # release before approval
            db.execute("UPDATE field_hold_points SET status='released', released_by='x', released_at='t', version=version+1 WHERE id=?", (hp["id"],))
        cm = self.s.commitment()
        p = self.f.add_punch_item(self.s.pid, cm["id"], "Item", "super")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "completion evidence"):  # closing without evidence
            db.execute("UPDATE field_punch_items SET status='closed', closed_by='x', closed_at='t', version=version+1 WHERE id=?", (p["id"],))
        self.s.ready_closeout(cm["id"])
        accept = ("UPDATE field_closeouts SET status='accepted', approval_id=?, accepted_by='x', accepted_at='t', acceptance_hash='h', accepted_period_id='P1', "
                  "version=version+1 WHERE commitment_id=?")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "zero open punch items"):
            db.execute(accept, (None, cm["id"]))
        self.f.close_punch_item(p["id"], ev_hash("done"), "super")
        # with the punch item closed only the approval guard is left, and it refuses on its own
        with self.assertRaisesRegex(sqlite3.IntegrityError, "consumed field.accept_closeout approval for that commitment"):
            db.execute(accept, (None, cm["id"]))
        # consumed approvals of another commitment or another operation do not count
        other = self.s.commitment()
        self.s.ready_closeout(other["id"])
        self.c.approve_and_execute("field.accept_closeout", other["id"], actor_role="pm", period_id="P1")
        foreign = (self.f.closeout(other["id"])["approval_id"], self.f.rfi(r["id"])["approval_id"], cm["approval_id"])
        for approval_id in foreign:
            self.assertEqual(self.c.approvals.get(approval_id)["status"], "consumed")
            with self.subTest(approval_id=approval_id), self.assertRaisesRegex(sqlite3.IntegrityError, "consumed field.accept_closeout approval for that commitment"):
                db.execute(accept, (approval_id, cm["id"]))
        # a pending change on the commitment blocks acceptance by itself
        self.c.commitments.propose_change(cm["id"], amount="100", reason="raw probe", actor="pm")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "no pending change on the commitment"):
            db.execute(accept, (None, cm["id"]))
        self.assertEqual(self.f.rfi(r["id"])["status"], "answered")
        self.assertEqual(self.f.hold_point(hp["id"])["status"], "held")
        self.assertEqual(self.f.closeout(cm["id"])["status"], "open")
        self.assertEqual(self.c.commitments.get(cm["id"])["status"], "executed")

    def test_database_guards_on_submittal_decisions_and_closeout_requirements(self):
        db = self.c.db
        approved = self.s.approved_submittal(title="Approved one", tag=None)
        foreign_approval = approved["revisions"][0]["approval_id"]
        sub = self.s.submittal()
        set_approved = "UPDATE field_submittals SET status='approved', version=version+1 WHERE id=?"
        with self.assertRaisesRegex(sqlite3.IntegrityError, "illegal submittal status transition"):  # open -> approved
            db.execute(set_approved, (sub["id"],))
        rev = self.f.add_submittal_revision(sub["id"], self.s.evidence()["id"], "pm")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "only once its revision is decided"):
            db.execute(set_approved, (sub["id"],))
        self.f.set_decision(rev["id"], "approved", "", "eor")
        decide = ("UPDATE field_submittal_revisions SET status=?, decision=?, comments=draft_comments, comments_hash=draft_comments_hash, approval_id=?, "
                  "decided_by='x', decided_at='t', version=version+1 WHERE id=?")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "exactly its recorded decision"):
            db.execute(decide, ("rejected", "rejected", None, rev["id"]))
        for approval_id in (None, foreign_approval):  # no approval, or another revision's consumed one
            with self.subTest(approval_id=approval_id), self.assertRaisesRegex(sqlite3.IntegrityError, "consumed field.decide_submittal approval for that revision"):
                db.execute(decide, ("approved", "approved", approval_id, rev["id"]))
        self.assertEqual((self.f.submittal_revision(rev["id"])["status"], self.f.submittal(sub["id"])["status"]), ("under_review", "under_review"))

        # closeout requirement rows are written only at the current closeout version and change only on a version bump
        cid = self.s.commitment()["id"]
        co = self.f.set_closeout_requirements(cid, ["as_builts", "om_manuals"], "pm")
        self.f.submit_closeout_item(cid, "as_builts", ev_hash("ab"), "pm")
        for sql in ("UPDATE field_closeout_requirements SET required=0 WHERE commitment_id=? AND item='om_manuals'",
                    "UPDATE field_closeout_requirements SET evidence_hash='forged' WHERE commitment_id=? AND item='as_builts'"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "rides on a closeout version bump"):
                db.execute(sql, (cid,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "written at the current closeout version"):
            db.execute(
                """INSERT INTO field_closeout_requirements (id, closeout_id, commitment_id, item, required, status, closeout_version, created_at, updated_at)
                   VALUES ('fcr_raw', ?, ?, 'training', 1, 'pending', 1, 't', 't')""",
                (co["closeout_id"], cid),
            )
        self.assertEqual(self.f.closeout(cid)["required_items"], ["as_builts", "om_manuals"])
        # a raw edit that does bump the closeout version is still caught by a granted approval
        self.f.submit_closeout_item(cid, "om_manuals", ev_hash("om"), "pm")
        ap = self.c.request_approval("field.accept_closeout", cid, actor_role="pm")
        self.c.approve(ap["id"])
        db.execute("UPDATE field_closeouts SET version=version+1 WHERE commitment_id=?", (cid,))
        bumped = db.scalar("SELECT version FROM field_closeouts WHERE commitment_id=?", (cid,))
        db.execute("UPDATE field_closeout_requirements SET evidence_hash='forged', closeout_version=? WHERE commitment_id=? AND item='as_builts'", (bumped, cid))
        with self.assertRaises(STALE):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.commitments.get(cid)["status"], "executed")

    def test_state_is_json_serialisable_and_audit_chain_holds(self):
        cm = self.s.commitment()
        dwg, r1, r2 = self.s.drawing()
        rfi = self.s.rfi(drawing_revision_ids=[r1["id"]])
        self.f.draft_response(rfi["id"], "Answer", cost_impact="500", schedule_impact_days=1, actor="pm")
        self.c.approve_and_execute("field.respond_rfi", rfi["id"], actor_role="pm")
        self.s.distribute(rfi["id"], ["EOR"])
        self.f.link_change(rfi["id"], cm["id"], "pm")
        sub = self.s.approved_submittal()
        self.f.add_hold_point(self.s.pid, "Hold", sub["id"], "super")
        self.f.add_punch_item(self.s.pid, cm["id"], "Item", "super")
        self.f.set_closeout_requirements(cm["id"], ["as_builts"], "pm")
        state = self.c.project_state(self.s.pid)
        fs = state["field"]
        text = json.dumps(fs)
        self.assertIn("RFI-001", text)
        self.assertEqual(fs["rfis"][0]["change"]["amount"], "500.00")
        self.assertEqual(fs["rfis"][0]["distributions"][0]["recipients"], ["EOR"])
        self.assertEqual([r["revision"] for r in fs["submittals"][0]["revisions"]], [1])
        self.assertEqual(fs["closeouts"][0]["status"], "open")
        self.assertEqual(fs["closeouts"][0]["open_punch_count"], 1)
        self.assertFalse(fs["closeouts"][0]["ready_for_acceptance"])
        self.assertEqual(fs["summary"]["punch_open"], 1)
        self.assertTrue(state["trial_balance"]["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        actions = {e["action"] for e in self.c.audit.entries() if e["action"].startswith("field.")}
        self.assertTrue({
            "field.rfi_created", "field.rfi_response_drafted", "field.rfi_answered", "field.rfi_distribution_list_set", "field.rfi_distributed",
            "field.rfi_change_linked", "field.submittal_created", "field.submittal_revision_added", "field.submittal_decision_drafted",
            "field.submittal_decided", "field.hold_point_added", "field.punch_item_added", "field.closeout_requirements_set",
        } <= actions)

    def test_audit_export_lists_every_field_record(self):
        cm = self.s.commitment()
        rfi = self.s.answered_rfi(cost="500")
        dist = self.s.distribute(rfi["id"], ["EOR", "Owner rep"])
        self.f.link_change(rfi["id"], cm["id"], "pm")
        sub = self.s.approved_submittal()
        self.f.add_hold_point(self.s.pid, "Hold", sub["id"], "super")
        self.f.add_punch_item(self.s.pid, cm["id"], "Item", "super")
        self.f.set_closeout_requirements(cm["id"], ["as_builts"], "pm")
        exp = self.f.audit_export()
        self.assertEqual(json.loads(json.dumps(exp)), exp)  # plain JSON
        self.assertEqual(set(exp), {"rfis", "rfi_links", "rfi_distributions", "submittals", "submittal_revisions", "hold_points",
                                    "punch_items", "closeouts", "closeout_requirements"})
        self.assertEqual([(r["number"], r["status"], r["distribution_list"]) for r in exp["rfis"]], [("RFI-001", "answered", ["EOR", "Owner rep"])])
        self.assertEqual([(d["id"], d["recipients"], d["approval_id"]) for d in exp["rfi_distributions"]], [(dist["id"], ["EOR", "Owner rep"], dist["approval_id"])])
        self.assertEqual([l["link_type"] for l in exp["rfi_links"]], ["change"])
        self.assertEqual((len(exp["submittals"]), len(exp["submittal_revisions"]), len(exp["hold_points"]), len(exp["punch_items"])), (1, 1, 1, 1))
        self.assertEqual([(co["commitment_id"], co["status"]) for co in exp["closeouts"]], [(cm["id"], "open")])
        self.assertEqual([r["item"] for r in exp["closeout_requirements"]], ["as_builts"])
        whole = self.c.audit_export()
        self.assertEqual(whole["modules"][PLUGIN_NAME]["rfi_distributions"][0]["id"], dist["id"])

    def test_workspace_with_the_original_field_schema_upgrades_in_place(self):
        """A file-backed workspace created before the distribution entry existed keeps its
        legacy distribution row and gains the approval-bound path on reopening."""
        from apps.cipher.core import db as core_db
        path = os.path.join(tempfile.mkdtemp(), "field-upgrade.sqlite")
        legacy_catalog = [entry for entry in core_db.SCHEMA_CATALOG if entry[1] != DISTRIBUTION_SCHEMA_NAME]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy_catalog):
            old = Cipher(path)
            self.assertNotIn(DISTRIBUTION_SCHEMA_NAME, [v["name"] for v in old.db.schema_status()["versions"]])
            customer = old.add_party(kind="customer", name="Synthetic Utility Board")
            project = old.create_project(name="Upgrade project", entity="S&A Solutions LLC (synthetic)", budget="1000", customer_id=customer["id"])
            f_old = old.plugin(PLUGIN_NAME)
            r = f_old.create_rfi(project["id"], "Legacy RFI", "Answered before the upgrade?", "pm")
            f_old.draft_response(r["id"], "Yes.", actor="pm")
            old.approve_and_execute("field.respond_rfi", r["id"], actor_role="pm")
            row = old.db.one("SELECT version, response_hash FROM field_rfis WHERE id=?", (r["id"],))
            old.db.execute(  # the old direct path wrote rows like this one
                "INSERT INTO field_rfi_distributions (id, rfi_id, rfi_version, response_hash, recipients_json, recipients_hash, channel, distributed_by, distributed_at) "
                "VALUES ('rfid_legacy', ?, ?, ?, '[\"EOR\"]', 'legacy-hash', 'mail-sink', 'pm', 't')", (r["id"], row["version"], row["response_hash"]))
            old.db.close()
        c = Cipher(path)
        try:
            status = c.db.schema_status()
            self.assertEqual(status["pending"], [])
            self.assertTrue(all(v["checksum_matches"] for v in status["versions"] if v["applied"]))
            f = c.plugin(PLUGIN_NAME)
            rfi = f.rfi(r["id"])
            self.assertEqual([(d["id"], d["approval_id"]) for d in rfi["distributions"]], [("rfid_legacy", None)])
            self.assertIsNone(rfi["distribution_list"])
            f.set_distribution_list(r["id"], ["Owner rep"], "pm")
            dist = c.approve_and_execute("field.distribute_rfi", r["id"], actor_role="pm").result
            self.assertEqual(dist["recipients"], ["Owner rep"])
            self.assertEqual(len(f.rfi(r["id"])["distributions"]), 2)
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            c.db.close()

    def test_database_guards_on_distribution(self):
        db = self.c.db
        open_rfi = self.s.rfi(subject="Still open")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "only on an answered RFI"):
            db.execute("UPDATE field_rfis SET distribution_recipients_json='[\"x\"]', distribution_recipients_hash='h', version=version+1 WHERE id=?", (open_rfi["id"],))
        r = self.s.answered_rfi()
        rfi = self.f.set_distribution_list(r["id"], ["EOR"], "pm")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "bump the RFI version"):  # a list change rides on a version bump
            db.execute("UPDATE field_rfis SET distribution_recipients_json='[\"x\"]', distribution_recipients_hash='h2' WHERE id=?", (r["id"],))
        # the response stays fixed, and a list is never cleared (either guard may fire first)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "except for a new distribution list|written once"):
            db.execute("UPDATE field_rfis SET response='edited', distribution_recipients_hash='h3', version=version+1 WHERE id=?", (r["id"],))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "except for a new distribution list|never cleared"):
            db.execute("UPDATE field_rfis SET distribution_recipients_json=NULL, distribution_recipients_hash=NULL, version=version+1 WHERE id=?", (r["id"],))
        self.assertEqual(self.f.rfi(r["id"])["distribution_list"], ["EOR"])

        insert = ("INSERT INTO field_rfi_distributions (id, rfi_id, rfi_version, response_hash, recipients_json, recipients_hash, channel, distributed_by, distributed_at, approval_id) "
                  "VALUES (?,?,?,?,?,?,'mail-sink','x','t',?)")
        row = (r["id"], rfi["version"], rfi["response_hash"], '["EOR"]', rfi["distribution_recipients_hash"])
        # no approval, or a consumed approval of another operation on this RFI
        for approval_id in (None, rfi["approval_id"]):
            with self.subTest(approval_id=approval_id), self.assertRaisesRegex(sqlite3.IntegrityError, "consumed field.distribute_rfi approval for that RFI"):
                db.execute(insert, ("rfid_raw1",) + row + (approval_id,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "current distribution list"):
            db.execute(insert, ("rfid_raw2", r["id"], rfi["version"], rfi["response_hash"], '["Someone else"]', "other-hash", None))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "official response"):
            db.execute(insert, ("rfid_raw3", r["id"], rfi["version"] - 1, rfi["response_hash"], '["EOR"]', rfi["distribution_recipients_hash"], None))

        # a consumed distribution approval cannot be reused for a second row, nor stretched to another list
        dist = self.c.approve_and_execute("field.distribute_rfi", r["id"], actor_role="pm").result
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(insert, ("rfid_raw4",) + row + (dist["approval_id"],))
        rfi = self.f.set_distribution_list(r["id"], ["Superintendent"], "pm")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "its approval bound"):
            db.execute(insert, ("rfid_raw5", r["id"], rfi["version"], rfi["response_hash"], '["Superintendent"]', rfi["distribution_recipients_hash"], dist["approval_id"]))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE field_rfi_distributions SET recipients_json='[]' WHERE id=?", (dist["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM field_rfi_distributions WHERE id=?", (dist["id"],))
        self.assertEqual([d["id"] for d in self.f.rfi(r["id"])["distributions"]], [dist["id"]])


if __name__ == "__main__":
    unittest.main()
