"""Independent fail-first estimate/commitment review, scratch only.

Run with PYTHONPATH=/workspace/SA-CMS-PRO. Every test uses a fresh disposable
workspace and real scoped people/independent decisions; no schema is registered.
"""
from __future__ import annotations
import unittest
from apps.cipher.service import Cipher
from apps.cipher.core.approvals import ApprovalError
from apps.cipher.domain.estimates import EstimateError
from apps.cipher.domain.commitments import CommitmentError
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.core.ids import loads

OWNER = "commercial.bootstrap"
ESTIMATOR = "commercial.estimator"
REVIEWER = "commercial.reviewer"
PM = "commercial.pm"
ACCOUNTANT = "commercial.accountant"


class World(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.addCleanup(self.c.db.close)
        people = self.c.plugin("people")
        people.bootstrap_owner(OWNER, "Synthetic commercial bootstrap owner")
        self.project = self.c.create_project(name="Synthetic commercial source review", entity="Synthetic practice entity", budget="10000", actor=OWNER)
        for login, role in ((ESTIMATOR, "estimator"), (REVIEWER, "estimator"), (PM, "pm"), (ACCOUNTANT, "accountant")):
            people.register_person(login, "Synthetic "+role, actor=OWNER)
            people.add_membership(login, self.project["id"], actor=OWNER)
            request = people.request_grant(login, role, project_id=self.project["id"], reason="Synthetic commercial project assignment", actor=OWNER)
            self.govern("people.grant_role", request["id"])
        policy = people.prepare_policy(enforce=True, segregate=True, solo_owner_self_approval=False,
                                      reason="Synthetic independent commercial review", actor=OWNER)
        self.govern("people.set_policy", policy["id"])
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic piping supplier", actor=OWNER)
        self.document = self.c.evidence.register_document(project_id=self.project["id"], kind="drawing", title="Synthetic manual source drawing", actor=ESTIMATOR)
        self.revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic manual drawing revision1", actor=ESTIMATOR)

    def govern(self, operation, resource):
        approval = self.c.request_approval(operation, resource, actor_role="owner", requested_by=OWNER)
        self.c.approve(approval["id"], approver=OWNER, approver_role="owner")
        return self.c.execute(approval["id"], actor=OWNER)

    def estimate(self, *, revision=None, supersedes=None, quantity="10", description="Synthetic piping"):
        return self.c.estimates.create(project_id=self.project["id"], document_revision_id=(revision or self.revision)["id"],
            lines=[{"description": description, "quantity": quantity, "unit": "LF", "unit_price": "10.00"}],
            measurement_basis="Manually entered quantity; synthetic drawing revision, page A1, scale reference checked by estimator",
            actor=ESTIMATOR, supersedes=supersedes)

    def granted(self, estimate):
        approval = self.c.request_approval("estimate.approve", estimate["id"], actor_role="estimator", requested_by=ESTIMATOR)
        self.c.approve(approval["id"], approver=REVIEWER, approver_role="estimator")
        return self.c.approvals.get(approval["id"])

    def accepted(self):
        estimate = self.estimate()
        approval = self.granted(estimate)
        self.c.execute(approval["id"], actor=ESTIMATOR)
        return self.c.estimates.get(estimate["id"]), self.c.approvals.get(approval["id"])

    def commitment(self, estimate, *, amount="100.00", description="Synthetic piping"):
        return self.c.commitments.create(project_id=self.project["id"], supplier_id=self.supplier["id"], title="Synthetic accepted-source package",
            sov_lines=[{"description": description, "amount": amount, "cost_code": "SYN-PIPE"}], retainage_rate="0.05",
            estimate_id=estimate["id"], actor=ESTIMATOR)

    def execute(self, commitment):
        approval = self.c.request_approval("commitment.execute", commitment["id"], actor_role="pm", requested_by=ESTIMATOR)
        self.c.approve(approval["id"], approver=PM, approver_role="pm")
        return self.c.execute(approval["id"], actor=PM)

    def tamper(self, table, sql, params):
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.conn.execute("DROP TRIGGER "+trigger["name"])
            self.c.db.conn.execute(sql, params)
            for trigger in triggers:
                self.c.db.conn.execute(trigger["sql"])


class CurrentGaps(World):
    def test_current_draft_estimate_cannot_back_executed_commitment(self):
        estimate = self.estimate()
        commitment = self.commitment(estimate)
        with self.assertRaises((CommitmentError, EstimateError, ApprovalError)):
            self.execute(commitment)

    def test_consumed_authorization_alone_is_not_an_audited_estimate_acceptance(self):
        estimate = self.estimate()
        approval = self.granted(estimate)
        self.c.approvals.consume(approval["id"], current_manifest=approval["manifest"], consumer=ESTIMATOR)
        # The existing status trigger accepts this because the authorization is
        # genuinely consumed. No estimate.approved business event was applied.
        self.c.db.execute("UPDATE estimates SET status='approved',approval_id=? WHERE id=?", (approval["id"], estimate["id"]))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='estimate.approved' AND entity_id=?", (estimate["id"],)), 0)
        with self.assertRaises((CommitmentError, EstimateError, ApprovalError)):
            self.execute(self.commitment(estimate))

    def test_accepted_source_rejects_changed_original_authorization_material_hash(self):
        estimate, approval = self.accepted()
        self.tamper("approvals", "UPDATE approvals SET material_hash=? WHERE id=?", ("altered-original-acceptance-material", approval["id"]))
        with self.assertRaises((CommitmentError, EstimateError, ApprovalError)):
            self.execute(self.commitment(estimate))

    def test_duplicate_created_birth_cannot_remain_trusted_acceptance_source(self):
        estimate, approval = self.accepted()
        event = self.c.db.one("SELECT * FROM audit_log WHERE action='estimate.created' AND entity_id=?", (estimate["id"],))
        self.c.audit.record(REVIEWER, "estimate.created", "estimate", estimate["id"], loads(event["payload_json"]))
        with self.assertRaises((CommitmentError, EstimateError, ApprovalError)):
            self.execute(self.commitment(estimate))

    def test_estimate_request_cannot_manufacture_estimator_duty_from_role_parameter(self):
        estimate = self.estimate()
        self.assertFalse(self.c.plugin("people").holds(ACCOUNTANT, "estimator", project_id=self.project["id"]))
        with self.assertRaises((IdentityRefused, PermissionError, ApprovalError)):
            self.c.request_approval("estimate.approve", estimate["id"], actor_role="estimator", requested_by=ACCOUNTANT)

    def test_current_source_detects_deleted_audited_later_estimate_revision(self):
        estimate, _ = self.accepted()
        revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic revised drawing", actor=ESTIMATOR)
        successor = self.estimate(revision=revision, supersedes=estimate["id"], quantity="12")
        # Restore every original guard after deleting both row inventories; the
        # surviving audited successor birth must remain independently checkable.
        self.tamper("estimate_lines", "DELETE FROM estimate_lines WHERE estimate_id=?", (successor["id"],))
        self.tamper("estimates", "DELETE FROM estimates WHERE id=?", (successor["id"],))
        with self.assertRaises(EstimateError):
            self.c.estimates.get(estimate["id"])


class GenuineBaseline(World):
    def test_genuine_independent_acceptance_and_linked_commitment_execute(self):
        estimate, approval = self.accepted()
        self.assertEqual(estimate["status"], "approved")
        self.assertEqual(approval["requested_by"], ESTIMATOR)
        self.assertEqual(approval["approver"], REVIEWER)
        self.assertEqual(approval["consumed_by"], ESTIMATOR)
        self.execute(self.commitment(estimate))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_historical_acceptance_remains_readable_after_genuine_successor(self):
        estimate, approval = self.accepted()
        revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic revised drawing", actor=ESTIMATOR)
        successor = self.estimate(revision=revision, supersedes=estimate["id"], quantity="12")
        original = self.c.estimates.get(estimate["id"])
        self.assertEqual(original["status"], "superseded")
        self.assertEqual(original["approval_id"], approval["id"])
        self.assertEqual(original["superseded_by"], successor["id"])
        self.assertEqual(original["total"], "100.00")

    def test_legacy_estimate_reference_has_no_line_preserving_mapping(self):
        estimate, _ = self.accepted()
        commitment = self.commitment(estimate, amount="999.00", description="Unrelated synthetic scope")
        self.execute(commitment)
        self.assertEqual(commitment["original_amount"], "999.00")
        self.assertEqual(estimate["total"], "100.00")
        self.assertNotIn("estimate_line_id", commitment["sov"][0])


if __name__ == "__main__":
    unittest.main()
