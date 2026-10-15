"""Actual scratch source/approval prototype: fixed temporary service integration.

Run only against commercial-draft/source before the repository path. The shared
checks and actual branches live in that isolated copy, not the repository app.
"""
import unittest
from unittest.mock import patch

from apps.cipher.core.approvals import StaleApprovalError
from apps.cipher.core.approvals import ApprovalError
from apps.cipher.core.ids import canonical_json
from apps.cipher.core.money import money
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.commercial_practice_fixture import (make_commercial_practice_fixture, ESTIMATOR_LOGIN,
                                        REVIEWER_LOGIN, ACCOUNTANT_LOGIN, BOOTSTRAP_LOGIN)


class ActualEstimatorAcceptancePrototype(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.estimate = self.c.commercial_practice_records["current_estimate_id"]
        self.project = self.c.commercial_practice_records["project_id"]

    def state(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, tuple(self.c.provider.submissions)

    def request(self):
        return self.c.request_approval("estimate.approve", self.estimate, actor_role="estimator", requested_by=ESTIMATOR_LOGIN)

    def granted(self):
        approval = self.request()
        self.c.check_estimate_grant(approval["id"], approver=REVIEWER_LOGIN)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        return approval["id"]

    def test_actual_request_guard_closes_accountant_role_selector_bypass(self):
        before = self.state()
        with self.assertRaises(IdentityRefused):
            self.c.request_approval("estimate.approve", self.estimate, actor_role="estimator", requested_by=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.state())

    def test_actual_shared_source_request_grant_application_checks_are_pure(self):
        before = self.state()
        self.c.check_estimate_request(self.estimate, requested_by=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.state())
        approval = self.request()
        before = self.state()
        self.c.check_estimate_grant(approval["id"], approver=REVIEWER_LOGIN)
        self.assertEqual(before, self.state())
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        before = self.state()
        self.c.check_estimate_application(approval["id"], actor=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.state())

    def test_independent_grant_and_original_requester_application_prove_baseline(self):
        approval_id = self.granted()
        self.c.check_estimate_application(approval_id, actor=ESTIMATOR_LOGIN)
        self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
        baseline = self.c.estimates.estimate_proof(self.estimate, accepted=True)
        self.assertEqual(baseline["acceptance"]["approvalId"], approval_id)
        self.assertEqual(baseline["acceptance"]["consumedBy"], ESTIMATOR_LOGIN)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commitments"), 0)
        self.assertEqual(self.c.provider.submissions, [])

    def test_current_estimator_reviewer_may_apply_under_existing_people_policy(self):
        approval_id = self.granted()
        self.c.check_estimate_application(approval_id, actor=REVIEWER_LOGIN)
        self.c.execute(approval_id, actor=REVIEWER_LOGIN)
        self.assertEqual(self.c.estimates.estimate_proof(self.estimate, accepted=True)["acceptance"]["consumedBy"], REVIEWER_LOGIN)

    def test_ended_original_reviewer_membership_blocks_pure_application(self):
        approval_id = self.granted()
        self.c.plugin("people").end_membership(REVIEWER_LOGIN, self.project,
            reason="Synthetic ended acceptance reviewer assignment", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with self.assertRaises(StaleApprovalError):
            self.c.check_estimate_application(approval_id, actor=ESTIMATOR_LOGIN)
        self.assertEqual(before, self.state())

    def test_actual_grant_refuses_changed_parallel_source_before_authorizing_acceptance(self):
        requested = self.request()
        source = self.c.plugin("commercial").source(self.estimate)
        body = {"documentRevisionId": source["drawing"]["revisionId"], "lines": [{
            "description": "Parallel manual piping", "quantity": "1", "unit": "LS", "unitPriceCents": 100,
            "sourceLocator": "A-101, parallel manual source", "costCode": "33-110"}],
            "priceBookRef": None, "inclusions": ["Parallel manual scope"], "exclusions": [],
            "contingencyRate": "0", "measurementBasis": "Manual parallel source; geometry unverified"}
        parallel = self.c.plugin("commercial").create(self.project, body, actor=ESTIMATOR_LOGIN)
        before = self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='approval.granted'")
        with self.assertRaises(StaleApprovalError):
            self.c.approve(requested["id"], approver=REVIEWER_LOGIN, approver_role="estimator")
        self.assertEqual(self.c.approvals.get(requested["id"])["status"], "invalidated")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='approval.granted'"), before)
        self.assertEqual(self.c.estimates.get(self.estimate)["status"], "draft")
        self.assertEqual(self.c.estimates.get(parallel["estimateId"])["status"], "draft")

    def test_actual_execute_restores_entire_command_after_caught_late_fault(self):
        approval_id = self.granted()
        original = self.c.audit.record

        def late_fault(*args, **kwargs):
            outcome = original(*args, **kwargs)
            if args[1] == "command.executed":
                raise RuntimeError("Injected scratch actual acceptance bookkeeping failure")
            return outcome

        with self.c.db.transaction():
            before_dump = tuple(self.c.db.conn.iterdump())
            with patch.object(self.c.audit, "record", side_effect=late_fault), self.assertRaises(RuntimeError):
                self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
            self.assertEqual(before_dump, tuple(self.c.db.conn.iterdump()))
            self.assertEqual(self.c.approvals.get(approval_id)["status"], "granted")
            self.assertEqual(self.c.estimates.get(self.estimate)["status"], "draft")
        self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
        self.assertEqual(self.c.estimates.estimate_proof(self.estimate, accepted=True)["acceptance"]["approvalId"], approval_id)

    def test_original_actual_acceptance_replays_after_genuine_successor(self):
        approval_id = self.granted()
        first = self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
        domain = self.c.plugin("commercial")
        source = domain.source(self.estimate)
        body = {"documentRevisionId": source["drawing"]["revisionId"], "lines": [{
            "description": line["engine_line"]["description"], "quantity": line["engine_line"]["quantity"],
            "unit": line["engine_line"]["unit"], "unitPriceCents": int(money(line["engine_line"]["unit_price"]) * 100),
            "sourceLocator": line["source_locator"], "costCode": line["cost_code"],
            "previousLineId": line["estimate_line_id"]} for line in source["lines"]],
            "priceBookRef": source["baseline"]["scope"]["price_book_ref"],
            "inclusions": source["baseline"]["scope"]["inclusions"], "exclusions": source["baseline"]["scope"]["exclusions"],
            "contingencyRate": "0", "measurementBasis": source["baseline"]["scope"]["measurement_basis"],
            "removedExclusions": []}
        successor = domain.revise(self.estimate, body, actor=ESTIMATOR_LOGIN)
        baseline = self.c.estimates.estimate_proof(self.estimate, accepted=True)
        replay = self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, first.result)
        self.assertEqual(self.c.estimates.estimate_proof(self.estimate, accepted=True), baseline)
        self.assertEqual(self.c.estimates.get(successor["estimateId"])["status"], "draft")

    def test_actual_completed_cache_cannot_replace_original_accepted_result(self):
        approval_id = self.granted()
        self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
        self.c.db.execute("UPDATE idempotency SET result_json=? WHERE op_id=?",
                          (canonical_json({"estimate": "unrecorded-wrong-estimate", "status": "approved"}), "exec:" + approval_id))
        before = tuple(self.c.db.conn.iterdump())
        with self.assertRaises(ApprovalError):
            self.c.execute(approval_id, actor=ESTIMATOR_LOGIN)
        self.assertEqual(tuple(self.c.db.conn.iterdump()), before)

    def test_whole_acceptance_command_restores_consumption_and_effect_after_caught_late_fault(self):
        approval_id = self.granted()
        original = self.c.audit.record

        def late_fault(*args, **kwargs):
            outcome = original(*args, **kwargs)
            if args[1] == "command.executed":
                raise RuntimeError("Injected scratch acceptance bookkeeping failure")
            return outcome

        def apply():
            checked = self.c.check_estimate_application(approval_id, actor=ESTIMATOR_LOGIN)
            self.c.approvals.consume(approval_id, current_manifest=checked["manifest"], consumer=ESTIMATOR_LOGIN)
            return self.c.estimates.approve(self.estimate, approval_id=approval_id, actor=ESTIMATOR_LOGIN)["id"]

        with self.c.db.transaction():
            before_dump = tuple(self.c.db.conn.iterdump())
            with patch.object(self.c.audit, "record", side_effect=late_fault), self.assertRaises(RuntimeError):
                self.c._estimate_acceptance_command("scratch-estimate-acceptance", {"approvalId": approval_id}, apply, actor=ESTIMATOR_LOGIN)
            self.assertEqual(before_dump, tuple(self.c.db.conn.iterdump()))
            self.assertEqual(self.c.approvals.get(approval_id)["status"], "granted")
            self.assertEqual(self.c.estimates.get(self.estimate)["status"], "draft")
        self.c._estimate_acceptance_command("scratch-estimate-acceptance", {"approvalId": approval_id}, apply, actor=ESTIMATOR_LOGIN)
        self.assertEqual(self.c.estimates.estimate_proof(self.estimate, accepted=True)["acceptance"]["approvalId"], approval_id)


if __name__ == "__main__":
    unittest.main()
