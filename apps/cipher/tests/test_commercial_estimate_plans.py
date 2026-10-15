"""Native estimate source planning and atomicity controls."""
from unittest.mock import patch
from apps.cipher.tests.test_commercial_estimate_sources import World, ESTIMATOR
from apps.cipher.core.ids import canonical_json
from apps.cipher.domain.estimates import EstimateError


class EstimateSourcePrototype(World):
    def stored(self):
        return tuple(self.c.db.conn.iterdump())

    def test_creation_preview_has_no_effect_and_matches_entire_actual_content(self):
        params = dict(project_id=self.project["id"], document_revision_id=self.revision["id"],
            lines=[{"description": "Synthetic measured portion", "quantity": "0.125", "unit": "LF", "unit_price": "12.34"},
                   {"description": "Synthetic fittings", "quantity": "7.5", "unit": "EA", "unit_price": "1.23"}],
            contingency_rate="0.125", price_book_ref="SYNTHETIC-RATE-REFERENCE", inclusions=["Synthetic stated scope"],
            exclusions=["Synthetic excluded scope"], measurement_basis="Manual quantity entry; A1 source reference")
        before = self.stored(), self.c.db.conn.total_changes
        first = self.c.estimates.creation_preflight(**params)
        second = self.c.estimates.creation_preflight(**params)
        self.assertEqual(first, second)
        self.assertEqual((self.stored(), self.c.db.conn.total_changes), before)
        self.assertEqual((first["subtotal"], first["contingency"], first["total"]), ("10.77", "1.35", "12.12"))
        actual = self.c.estimates.create(**params, actor=ESTIMATOR)
        self.assertEqual(actual["content_hash"], first["content_hash"])
        self.assertEqual(actual["total"], first["total"])
        self.assertEqual([{key: line[key] for key in first["lines"][0]} for line in actual["lines"]], first["lines"])

    def test_nested_caught_creation_audit_failure_restores_predecessor_and_inventory(self):
        original, _ = self.accepted()
        revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic revised source", actor=ESTIMATOR)
        before = self.stored()
        record = self.c.audit.record
        def fail(actor, action, *args, **kwargs):
            result = record(actor, action, *args, **kwargs)
            if action == "estimate.created":
                raise RuntimeError("Synthetic late creation audit failure")
            return result
        with self.c.db.transaction():
            with patch.object(self.c.audit, "record", side_effect=fail):
                with self.assertRaises(RuntimeError):
                    self.estimate(revision=revision, supersedes=original["id"], quantity="12")
        self.assertEqual(self.stored(), before)
        self.assertEqual(self.c.estimates.get(original["id"])["status"], "approved")

    def test_original_accepted_proof_stays_identical_after_genuine_successor(self):
        original, approval = self.accepted()
        before = self.c.estimates.estimate_proof(original["id"], accepted=True)
        revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic revised source", actor=ESTIMATOR)
        self.estimate(revision=revision, supersedes=original["id"], quantity="12")
        after = self.c.estimates.estimate_proof(original["id"], accepted=True)
        self.assertEqual(canonical_json(before), canonical_json(after))
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_proof(original["id"], accepted=True, current=True)

    def test_accepted_source_rejects_changed_original_grant_time(self):
        original, approval = self.accepted()
        self.tamper("approvals", "UPDATE approvals SET granted_at=? WHERE id=?", ("2099-12-31T00:00:00Z", approval["id"]))
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_proof(original["id"], accepted=True)

    def test_accepted_source_status_rewind_cannot_look_like_new_draft(self):
        original, approval = self.accepted()
        self.tamper("estimates", "UPDATE estimates SET status='draft',approval_id=NULL WHERE id=?", (original["id"],))
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_proof(original["id"])

    def test_genuine_no_estimate_commitment_keeps_existing_pm_execution(self):
        commitment = self.c.commitments.create(project_id=self.project["id"], supplier_id=self.supplier["id"],
            title="Synthetic independent no-estimate scope", sov_lines=[{"description": "Explicit standalone scope", "amount": "123.45"}], actor=ESTIMATOR)
        self.execute(commitment)
        self.assertIsNone(self.c.commitments.get(commitment["id"])["estimate"])
        self.assertEqual(self.c.commitments.get(commitment["id"])["status"], "executed")

    def test_original_baseline_refuses_deleted_later_acceptance_request_inventory(self):
        original, _ = self.accepted()
        revision = self.c.evidence.add_revision(document_id=self.document["id"], content="Synthetic revised source", actor=ESTIMATOR)
        successor = self.estimate(revision=revision, supersedes=original["id"], quantity="12")
        request = self.c.request_approval("estimate.approve", successor["id"], actor_role="estimator", requested_by=ESTIMATOR)
        self.tamper("approvals", "DELETE FROM approvals WHERE id=?", (request["id"],))
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_proof(original["id"], accepted=True)

    def test_acceptance_inventory_refuses_changed_pending_request_operation(self):
        draft = self.estimate()
        request = self.c.request_approval("estimate.approve", draft["id"], actor_role="estimator", requested_by=ESTIMATOR)
        self.tamper("approvals", "UPDATE approvals SET operation='commitment.execute' WHERE id=?", (request["id"],))
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_approval_inventory((self.project["id"],))

    def test_original_accepted_proof_refuses_missing_source_storage_guard(self):
        original, _ = self.accepted()
        self.c.db.conn.execute("DROP TRIGGER estimate_lines_no_update")
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_proof(original["id"], accepted=True)

    def test_invalidated_authorization_reason_must_match_latest_genuine_terminal_event(self):
        estimate = self.estimate()
        approval = self.granted(estimate)
        self.c.approvals.invalidate(approval["id"], reason="Synthetic original estimator scope withdrawn", actor=ESTIMATOR)
        self.c.estimates.estimate_approval_proof(approval["id"])
        # Rejection of an already invalidated authorization is a genuine domain
        # operation. Its latest reason must remain attributable to that event.
        self.c.approvals.invalidate(approval["id"], reason="Synthetic later independent rejection", actor=ESTIMATOR)
        self.c.estimates.estimate_approval_proof(approval["id"])
        self.tamper("approvals", "UPDATE approvals SET invalidated_reason='Unrecorded replacement reason' WHERE id=?", (approval["id"],))
        with self.assertRaises(EstimateError):
            self.c.estimates.estimate_approval_proof(approval["id"])
