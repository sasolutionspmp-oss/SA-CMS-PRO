"""EPC field controls: RFIs, submittals, hold points, punch list and closeout."""
import json
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import sha256_hex
from apps.cipher.domain.commitments import CommitmentError
from apps.cipher.domain.field import CLOSEOUT_ITEMS, PLUGIN_NAME, SCHEMA_NAME, FieldError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher

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

    def submittal(self, title="Pinch valves", tag="PV-101"):
        return self.f.create_submittal(self.pid, "40 05 61", title, "pm", equipment_tag=tag)

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

        # distribution is a separate step to the mail sink; nothing is queued for sending
        dist = f.distribute_rfi(rfi["id"], ["Synthetic Engineer of Record", "Synthetic Owner Rep"], actor="pm")
        self.assertEqual((dist["channel"], dist["recipients"], dist["response_hash"]), ("mail-sink", ["Synthetic Engineer of Record", "Synthetic Owner Rep"], rfi["response_hash"]))
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

        # before acceptance Ricky abstains on retainage release
        self.assertEqual(c.ricky.propose("retainage.release", actor_role="owner", context={"commitment_id": cm["id"]})["decision"], "abstained")
        res = c.approve_and_execute("field.accept_closeout", cm["id"], actor_role="pm", period_id="P1")
        self.assertEqual((res.result["status"], res.result["commitment_status"], res.result["period_id"]), ("accepted", "closed", "P1"))
        self.assertEqual(c.commitments.get(cm["id"])["status"], "closed")
        self.assertEqual(f.closeout(cm["id"])["status"], "accepted")

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
        self.assertIn(SCHEMA_NAME, [v["name"] for v in status["versions"]])
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

    def test_distribution_only_after_answer_and_never_duplicated(self):
        r = self.s.rfi()
        self.f.draft_response(r["id"], "Use detail 4.", actor="pm")
        with self.assertRaises(FieldError):
            self.f.distribute_rfi(r["id"], ["EOR"], actor="pm")
        self.c.approve_and_execute("field.respond_rfi", r["id"], actor_role="pm")
        for bad in ([], "EOR", ["EOR", " eor "], ["EOR", 7], [""]):
            with self.subTest(bad=bad), self.assertRaises(FieldError):
                self.f.distribute_rfi(r["id"], bad, actor="pm")
        d1 = self.f.distribute_rfi(r["id"], ["EOR", "Owner rep"], actor="pm")
        with self.assertRaises(FieldError):  # same recipients again, any order or case
            self.f.distribute_rfi(r["id"], ["owner rep", "eor"], actor="pm")
        d2 = self.f.distribute_rfi(r["id"], ["Superintendent"], actor="pm")
        rfi = self.f.rfi(r["id"])
        self.assertEqual([d["id"] for d in rfi["distributions"]], [d1["id"], d2["id"]])
        self.assertEqual(rfi["version"], 3)  # distribution does not edit the RFI
        self.assertEqual(self.c.commands.pending(), [])
        self.assertIn("field.rfi_distributed", [e["action"] for e in self.c.audit.entries(entity_type="field_rfi", entity_id=r["id"])])

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
            self.f.create_submittal(self.s.pid, "40 05 61", "pinch VALVES", "pm", equipment_tag="pv-101")
        with self.assertRaises(FieldError):
            self.f.create_submittal(self.s.pid, "", "T", "pm")
        with self.assertRaises(FieldError):
            self.f.create_submittal(self.s.pid, "40 05 61", None, "pm")
        with self.assertRaises(FieldError):
            self.f.create_submittal("prj_missing", "40 05 61", "T", "pm")
        self.assertEqual(self.f.create_submittal(self.s.pid, "40 05 61", "Pinch valves", "pm", equipment_tag="PV-102")["number"], "SUB-003")

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
        self.assertTrue(all(set(ch) == {"check", "ok", "detail"} for ch in checks))


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
        self.f.distribute_rfi(rfi["id"], ["EOR"], actor="pm")
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
            "field.rfi_created", "field.rfi_response_drafted", "field.rfi_answered", "field.rfi_distributed", "field.rfi_change_linked",
            "field.submittal_created", "field.submittal_revision_added", "field.submittal_decision_drafted", "field.submittal_decided",
            "field.hold_point_added", "field.punch_item_added", "field.closeout_requirements_set",
        } <= actions)


if __name__ == "__main__":
    unittest.main()
