"""Drawing register: issued versus working revisions, exact references, stale approvals."""
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.drawings import PLUGIN_NAME, SCHEMA_NAME, DrawingError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher, CipherError


class Scene:
    """Project with an open period, one evidence document and one registered drawing."""

    def __init__(self):
        self.c = Cipher()
        self.customer = self.c.add_party(kind="customer", name="Owner agency")
        self.project = self.c.create_project(name="Pump station", entity="E", budget="250000", customer_id=self.customer["id"])
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.plugin = self.c.plugin(PLUGIN_NAME)
        self.doc = self.c.evidence.register_document(project_id=self.project["id"], kind="drawing", title="C-101 site plan", actor="o")
        self.dwg = self.plugin.register_drawing(self.project["id"], "C-101", "Site plan", "Civil", actor="o")

    def evidence(self, content: bytes, note: str = "") -> dict:
        return self.c.evidence.add_revision(document_id=self.doc["id"], content=content, note=note, actor="o")

    def issue(self, revision_id: str, period_id: str = "P1"):
        return self.c.approve_and_execute("drawing.issue", revision_id, period_id=period_id)


class DrawingRegisterTests(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.p = self.s.plugin
        self.dwg_id = self.s.dwg["id"]

    # ---- registration ---------------------------------------------------------- #

    def test_register_drawing_starts_at_version_one(self):
        status = self.c.db.schema_status()
        self.assertIn(SCHEMA_NAME, [v["name"] for v in status["versions"]])
        self.assertTrue(all(v["applied"] for v in status["versions"]))
        self.assertIs(self.c.plugin("drawing"), self.p)
        d = self.s.dwg
        self.assertEqual((d["number"], d["title"], d["discipline"], d["version"]), ("C-101", "Site plan", "Civil", 1))
        self.assertTrue(d["id"].startswith("dwg_"))
        self.assertIsNone(self.p.usable_revision(d["id"]))
        self.assertIsNone(self.p.working_revision(d["id"]))
        self.assertEqual(self.p.by_number(self.s.project["id"], "c-101")["id"], d["id"])
        self.assertEqual([e["action"] for e in self.c.audit.entries(entity_type="drawing", entity_id=d["id"])], ["drawing.registered"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_duplicate_drawing_number_rejected_per_project(self):
        with self.assertRaises(DrawingError):
            self.p.register_drawing(self.s.project["id"], "C-101", "Again", "Civil", actor="o")
        with self.assertRaises(DrawingError):  # case-insensitive
            self.p.register_drawing(self.s.project["id"], " c-101 ", "Again", "Civil", actor="o")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        self.assertEqual(self.p.register_drawing(other["id"], "C-101", "Other site", "Civil", actor="o")["number"], "C-101")
        self.assertEqual(len(self.p.register(self.s.project["id"])), 1)

    def test_register_drawing_validates_input(self):
        with self.assertRaises(DrawingError):
            self.p.register_drawing("prj_missing", "C-102", "T", "Civil", actor="o")
        with self.assertRaises(DrawingError):
            self.p.register_drawing(self.s.project["id"], "  ", "T", "Civil", actor="o")
        with self.assertRaises(DrawingError):
            self.p.register_drawing(self.s.project["id"], "C-102", "", "Civil", actor="o")
        with self.assertRaises(DrawingError):
            self.p.register_drawing(self.s.project["id"], "C-102", "T", None, actor="o")
        with self.assertRaises(DrawingError):
            self.p.register_drawing(self.s.project["id"], 101, "T", "Civil", actor="o")
        with self.assertRaises(DrawingError):
            self.p.get("dwg_missing")

    # ---- revisions ---------------------------------------------------------------- #

    def test_add_revision_binds_existing_evidence_of_same_project(self):
        ev = self.s.evidence(b"c101 r1", note="IFC")
        r1 = self.p.add_revision(self.dwg_id, "R1", ev["id"], "issued for construction", actor="o")
        self.assertEqual(r1["status"], "working")
        self.assertEqual(r1["label"], "R1")
        self.assertEqual(r1["document_revision_id"], ev["id"])
        self.assertEqual(r1["content_hash"], ev["content_hash"])
        self.assertTrue(r1["evidence_is_current"])
        self.assertEqual(r1["sequence"], 1)
        self.assertEqual(self.p.get(self.dwg_id)["version"], 2)
        self.assertEqual(self.p.working_revision(self.dwg_id)["id"], r1["id"])
        self.assertIsNone(self.p.usable_revision(self.dwg_id))

    def test_add_revision_rejects_missing_or_foreign_evidence(self):
        with self.assertRaises(DrawingError):
            self.p.add_revision(self.dwg_id, "R1", "rev_missing", "", actor="o")
        with self.assertRaises(DrawingError):
            self.p.add_revision(self.dwg_id, "R1", None, "", actor="o")
        other = self.c.create_project(name="Other", entity="E", budget="1000")
        other_doc = self.c.evidence.register_document(project_id=other["id"], kind="drawing", title="X", actor="o")
        foreign = self.c.evidence.add_revision(document_id=other_doc["id"], content=b"foreign", actor="o")
        with self.assertRaises(DrawingError):
            self.p.add_revision(self.dwg_id, "R1", foreign["id"], "", actor="o")
        with self.assertRaises(DrawingError):
            self.p.add_revision(self.dwg_id, "", self.s.evidence(b"x")["id"], "", actor="o")
        self.assertEqual(self.p.revisions(self.dwg_id), [])

    def test_only_one_working_revision_at_a_time(self):
        self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        with self.assertRaises(DrawingError):
            self.p.add_revision(self.dwg_id, "R2", self.s.evidence(b"r2")["id"], "", actor="o")
        self.assertEqual(len(self.p.revisions(self.dwg_id)), 1)

    def test_same_evidence_cannot_be_bound_twice_while_live(self):
        ev = self.s.evidence(b"r1")
        r1 = self.p.add_revision(self.dwg_id, "R1", ev["id"], "", actor="o")
        self.s.issue(r1["id"])
        with self.assertRaises(DrawingError):
            self.p.add_revision(self.dwg_id, "R2", ev["id"], "", actor="o")

    def test_replace_working_withdraws_and_bumps_version(self):
        ev1, ev2 = self.s.evidence(b"r1 draft"), self.s.evidence(b"r1 corrected")
        r1 = self.p.add_revision(self.dwg_id, "R1", ev1["id"], "", actor="o")
        before = self.p.get(self.dwg_id)["version"]
        with self.assertRaises(DrawingError):  # the working revision already holds ev1
            self.p.replace_working(self.dwg_id, ev1["id"], actor="o")
        r1b = self.p.replace_working(self.dwg_id, ev2["id"], actor="o")
        old = self.p.revision(r1["id"])
        self.assertEqual(old["status"], "withdrawn")
        self.assertIsNotNone(old["withdrawn_at"])
        self.assertEqual(old["replaced_by"], r1b["id"])
        self.assertEqual((r1b["label"], r1b["status"], r1b["sequence"]), ("R1", "working", 2))
        self.assertEqual(r1b["document_revision_id"], ev2["id"])
        self.assertEqual(r1b["content_hash"], ev2["content_hash"])
        self.assertEqual(self.p.get(self.dwg_id)["version"], before + 1)
        self.assertEqual(self.p.working_revision(self.dwg_id)["id"], r1b["id"])
        self.assertIsNone(self.p.usable_revision(self.dwg_id))
        with self.assertRaises(DrawingError):  # withdrawn revisions are never issued
            self.s.issue(r1["id"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_replace_working_requires_a_working_revision(self):
        with self.assertRaises(DrawingError):
            self.p.replace_working(self.dwg_id, self.s.evidence(b"x")["id"], actor="o")
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        self.s.issue(r1["id"])
        with self.assertRaises(DrawingError):
            self.p.replace_working(self.dwg_id, self.s.evidence(b"y")["id"], actor="o")

    # ---- golden flow ----------------------------------------------------------------- #

    def test_golden_issue_supersede_and_reference_flow(self):
        ev1 = self.s.evidence(b"c101 r1")
        r1 = self.p.add_revision(self.dwg_id, "R1", ev1["id"], "IFC", actor="o")
        res = self.s.issue(r1["id"])
        self.assertFalse(res.replayed)
        self.assertEqual(res.result["status"], "issued")
        self.assertEqual(res.result["period_id"], "P1")
        self.assertEqual(res.result["superseded"], [])
        r1 = self.p.revision(r1["id"])
        self.assertEqual(r1["status"], "issued")
        self.assertIsNotNone(r1["issued_at"])
        self.assertEqual(r1["issued_period_id"], "P1")
        self.assertIsNotNone(r1["approval_id"])
        self.assertEqual(self.p.usable_revision(self.dwg_id)["id"], r1["id"])

        # R2 is added as working: R1 stays the usable revision
        ev2 = self.s.evidence(b"c101 r2")
        r2 = self.p.add_revision(self.dwg_id, "R2", ev2["id"], "revised grading", actor="o")
        self.assertEqual(r2["status"], "working")
        self.assertFalse(self.p.revision(r1["id"])["evidence_is_current"])
        self.assertEqual(self.p.usable_revision(self.dwg_id)["id"], r1["id"])
        self.assertEqual(self.p.working_revision(self.dwg_id)["id"], r2["id"])

        # references bind only to the issued revision, exactly
        with self.assertRaises(DrawingError):
            self.p.reference(r2["id"], "commitment", "cmt_1", actor="o")
        ref = self.p.reference(r1["id"], "commitment", "cmt_1", actor="o")
        self.assertEqual(ref["drawing_revision_id"], r1["id"])
        self.assertEqual(ref["content_hash"], ev1["content_hash"])
        self.assertEqual([x["id"] for x in self.p.references(r1["id"])], [ref["id"]])
        self.assertEqual(self.p.references(r2["id"]), [])

        # issuing R2 supersedes R1; R2 becomes usable; R1's reference is untouched
        res2 = self.s.issue(r2["id"])
        self.assertEqual(res2.result["superseded"], [r1["id"]])
        r1, r2 = self.p.revision(r1["id"]), self.p.revision(r2["id"])
        self.assertEqual(r1["status"], "superseded")
        self.assertEqual(r1["superseded_by"], r2["id"])
        self.assertIsNotNone(r1["superseded_at"])
        self.assertEqual(r2["status"], "issued")
        self.assertEqual(self.p.usable_revision(self.dwg_id)["id"], r2["id"])
        self.assertIsNone(self.p.working_revision(self.dwg_id))
        with self.assertRaises(DrawingError):  # superseded revisions take no new references
            self.p.reference(r1["id"], "commitment", "cmt_2", actor="o")
        self.assertEqual([x["id"] for x in self.p.references(r1["id"])], [ref["id"]])
        self.p.reference(r2["id"], "commitment", "cmt_1", actor="o")

        # register / state shape
        reg = self.p.register(self.s.project["id"])
        self.assertEqual(len(reg), 1)
        entry = reg[0]
        self.assertEqual(entry["number"], "C-101")
        self.assertEqual(entry["usable_revision"]["id"], r2["id"])
        self.assertIsNone(entry["working_revision"])
        self.assertEqual([h["label"] for h in entry["issue_history"]], ["R1", "R2"])
        self.assertEqual([h["status"] for h in entry["issue_history"]], ["superseded", "issued"])
        self.assertEqual(entry["reference_count"], 2)
        state = self.p.state(self.s.project["id"])
        self.assertEqual(set(state), {"register", "summary"})
        self.assertEqual(state["summary"], {"drawings": 1, "issued": 1, "working": 0, "references": 2})
        self.assertEqual(self.c.project_state(self.s.project["id"])["drawing"]["summary"]["issued"], 1)

        # drawings move no money; books stay balanced and the audit chain intact
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertEqual(self.c.ledger.balance("5000"), Decimal("0.00"))
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        actions = [e["action"] for e in self.c.audit.entries(entity_type="drawing_revision")]
        self.assertEqual(actions.count("drawing.issued"), 2)
        self.assertEqual(actions.count("drawing.revision_superseded"), 1)

    def test_issue_replay_returns_stored_result_without_reissuing(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        ap = self.c.request_approval("drawing.issue", r1["id"])
        self.c.approve(ap["id"])
        first = self.c.execute(ap["id"], period_id="P1")
        again = self.c.execute(ap["id"], period_id="P1")
        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(self.p.get(self.dwg_id)["version"], first.result["drawing_version"])

    # ---- stale approvals ------------------------------------------------------------------ #

    def test_issue_approval_stale_after_replace_working(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        ap = self.c.request_approval("drawing.issue", r1["id"])
        self.c.approve(ap["id"])
        bindings = ap["manifest"]["bindings"]
        self.assertEqual((bindings["drawing_version"], bindings["revision_label"], bindings["revision_status"]), (2, "R1", "working"))
        self.assertEqual(bindings["evidence_content_hash"], r1["content_hash"])
        self.assertTrue(bindings["evidence_is_current"])
        r1b = self.p.replace_working(self.dwg_id, self.s.evidence(b"r1 corrected")["id"], actor="o")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.p.revision(r1["id"])["status"], "withdrawn")
        self.assertIsNone(self.p.usable_revision(self.dwg_id))
        # the replacement issues on its own, fresh approval
        self.s.issue(r1b["id"])
        self.assertEqual(self.p.usable_revision(self.dwg_id)["id"], r1b["id"])

    def test_issue_approval_stale_after_drawing_edit(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        ap = self.c.request_approval("drawing.issue", r1["id"])
        self.c.approve(ap["id"])
        self.p.update_drawing(self.dwg_id, title="Site plan and grading", actor="o")
        self.assertEqual(self.p.get(self.dwg_id)["version"], 3)
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.p.revision(r1["id"])["status"], "working")
        with self.assertRaises(DrawingError):
            self.p.update_drawing(self.dwg_id, title="Site plan and grading", actor="o")  # no-op edit

    def test_issue_approval_stale_when_evidence_is_superseded(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        ap = self.c.request_approval("drawing.issue", r1["id"])
        self.c.approve(ap["id"])
        self.s.evidence(b"newer scan of the same sheet")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        # a fresh approval shows the fact to the approver and may still be granted knowingly
        ap2 = self.c.request_approval("drawing.issue", r1["id"])
        self.assertFalse(ap2["manifest"]["bindings"]["evidence_is_current"])
        self.c.approve(ap2["id"])
        self.c.execute(ap2["id"], period_id="P1")
        self.assertEqual(self.p.revision(r1["id"])["status"], "issued")
        self.assertFalse(self.p.revision(r1["id"])["evidence_is_current"])

    # ---- periods and operations ------------------------------------------------------------ #

    def test_issue_into_closed_period_rejected(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        self.c.close_period("P1")
        ap = self.c.request_approval("drawing.issue", r1["id"])
        self.c.approve(ap["id"])
        with self.assertRaises(PeriodNotOpen):
            self.c.execute(ap["id"], period_id="P1")
        with self.assertRaises(CipherError):  # no open period to default to
            self.c.execute(ap["id"])
        self.assertEqual(self.p.revision(r1["id"])["status"], "working")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        res = self.c.execute(ap["id"], period_id="P2")
        self.assertEqual(res.result["period_id"], "P2")
        self.assertEqual(self.p.revision(r1["id"])["issued_period_id"], "P2")
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_issue_requires_a_working_revision(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        self.s.issue(r1["id"])
        with self.assertRaises(DrawingError):
            self.s.issue(r1["id"])  # already issued
        self.assertEqual(self.p.revision(r1["id"])["status"], "issued")
        with self.assertRaises(DrawingError):
            self.c.request_approval("drawing.issue", "dwr_missing")

    def test_unknown_drawing_operation_rejected(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        with self.assertRaises(DrawingError):
            self.p.manifest_for("drawing.withdraw", r1["id"], actor_role="owner")
        with self.assertRaises(DrawingError):
            self.c.request_approval("drawing.withdraw", r1["id"])
        with self.assertRaises(DrawingError):
            self.p.apply("drawing.withdraw", r1["id"], approval_id="apr_x", manifest={}, actor="o", period_id="P1")

    # ---- references ---------------------------------------------------------------------------- #

    def test_reference_rejects_duplicates_and_invalid_input(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        self.s.issue(r1["id"])
        self.p.reference(r1["id"], "bill", "bill_1", actor="o")
        with self.assertRaises(DrawingError):
            self.p.reference(r1["id"], "bill", "bill_1", actor="o")
        with self.assertRaises(DrawingError):
            self.p.reference(r1["id"], "", "bill_2", actor="o")
        with self.assertRaises(DrawingError):
            self.p.reference(r1["id"], "bill", "   ", actor="o")
        with self.assertRaises(DrawingError):
            self.p.reference("dwr_missing", "bill", "bill_2", actor="o")
        with self.assertRaises(DrawingError):
            self.p.references("dwr_missing")
        self.p.reference(r1["id"], "bill", "bill_2", actor="o")  # a different referrer is fine
        self.assertEqual(len(self.p.references(r1["id"])), 2)
        self.assertEqual(self.p.revision(r1["id"])["reference_count"], 2)

    def test_database_guards_hold_without_the_plugin(self):
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        with self.assertRaises(sqlite3.IntegrityError):  # references only on issued revisions
            self.c.db.execute(
                "INSERT INTO drawing_references (id, drawing_id, drawing_revision_id, referenced_by_type, referenced_by_id, content_hash, created_at) VALUES ('x', ?, ?, 'bill', 'b', 'h', 't')",
                (self.dwg_id, r1["id"]),
            )
        self.s.issue(r1["id"])
        ref = self.p.reference(r1["id"], "bill", "bill_1", actor="o")
        with self.assertRaises(sqlite3.IntegrityError):  # append-only references
            self.c.db.execute("DELETE FROM drawing_references WHERE id=?", (ref["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE drawing_references SET referenced_by_id='other' WHERE id=?", (ref["id"],))
        with self.assertRaises(sqlite3.IntegrityError):  # status machine
            self.c.db.execute("UPDATE drawing_revisions SET status='working' WHERE id=?", (r1["id"],))
        with self.assertRaises(sqlite3.IntegrityError):  # immutable binding
            self.c.db.execute("UPDATE drawing_revisions SET content_hash='tampered' WHERE id=?", (r1["id"],))
        with self.assertRaises(sqlite3.IntegrityError):  # no silent edits: the version must bump
            self.c.db.execute("UPDATE drawing_register SET title='quiet edit' WHERE id=?", (self.dwg_id,))
        with self.assertRaises(sqlite3.IntegrityError):  # identity immutable
            self.c.db.execute("UPDATE drawing_register SET number='C-999', version=version+1 WHERE id=?", (self.dwg_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("DELETE FROM drawing_revisions WHERE id=?", (r1["id"],))
        self.assertEqual(self.p.revision(r1["id"])["status"], "issued")
        self.assertEqual(self.p.get(self.dwg_id)["title"], "Site plan")

    def test_register_lists_drawings_in_number_order_with_shape(self):
        d2 = self.p.register_drawing(self.s.project["id"], "A-201", "Elevations", "Architectural", actor="o")
        r1 = self.p.add_revision(self.dwg_id, "R1", self.s.evidence(b"r1")["id"], "", actor="o")
        self.s.issue(r1["id"])
        self.p.add_revision(self.dwg_id, "R2", self.s.evidence(b"r2")["id"], "", actor="o")
        reg = self.p.register(self.s.project["id"])
        self.assertEqual([d["number"] for d in reg], ["A-201", "C-101"])
        a201 = next(d for d in reg if d["id"] == d2["id"])
        self.assertEqual((a201["usable_revision"], a201["working_revision"], a201["issue_history"], a201["revisions"]), (None, None, [], []))
        c101 = next(d for d in reg if d["id"] == self.dwg_id)
        self.assertEqual(c101["usable_revision"]["label"], "R1")
        self.assertEqual(c101["working_revision"]["label"], "R2")
        self.assertEqual([r["label"] for r in c101["revisions"]], ["R1", "R2"])
        self.assertEqual(self.p.state(self.s.project["id"])["summary"], {"drawings": 2, "issued": 1, "working": 1, "references": 0})
        with self.assertRaises(DrawingError):
            self.p.register("prj_missing")


if __name__ == "__main__":
    unittest.main()
