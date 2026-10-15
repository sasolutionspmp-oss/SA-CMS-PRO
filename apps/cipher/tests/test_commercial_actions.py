"""Real isolated source/approval/handoff/receipt journeys and fault boundaries."""
import copy
import threading
import datetime
import time
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.service import Cipher
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import canonical_json
from apps.cipher.domain.commercial import register_commercial_schema
from apps.cipher.commercial_receipts import register_commercial_receipts_schema, commercial_receipt_inventory_proof
register_commercial_schema()
register_commercial_receipts_schema()
from apps.cipher.commercial_practice_fixture import make_commercial_practice_fixture, ESTIMATOR_LOGIN, REVIEWER_LOGIN, PM_LOGIN, BOOTSTRAP_LOGIN
from apps.cipher.commercial_preflight import CommercialPreflight
from apps.cipher.commercial_actions import CommercialActionRunner
from apps.cipher.commercial_contract import CommercialContract


class CommercialActionTests(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("commercial")
        self.r = self.c.commercial_practice_records
        self.person, self.reviewer, self.pm = (self.c.commercial_practice_persona_people[key]["person_id"] for key in ("preparer", "reviewer", "pm"))
        secret = b"commercial-actions-real-source-private-key"
        self.contract = CommercialContract(self.c, secret=secret)
        self.preflight = CommercialPreflight(self.c, self.contract, secret=secret)
        self.runner = CommercialActionRunner(self.c, self.contract, self.preflight)

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def input(self, *, previous=None, description="Manual distinct commercial scope"):
        body = {"documentRevisionId": self.r["current_drawing_revision_id"], "lines": [{
            "description": description, "quantity": "13.125", "unit": "LF", "unitPriceCents": 2500,
            "sourceLocator": "A-101, manual measured run 4", "costCode": "33-110"}],
            "priceBookRef": "Synthetic fixed practice rates v1", "inclusions": ["Manual scoped installation"],
            "exclusions": ["Excavation"], "contingencyRate": "0", "measurementBasis": "Manual source; geometry unverified"}
        if previous is not None:
            body["lines"][0]["previousLineId"] = self.domain.source(previous)["lines"][0]["estimate_line_id"]
            body["removedExclusions"] = []
        return body

    def prepared(self, person, action, resource_id, typed=None):
        typed = {} if typed is None else typed
        review = self.preflight.review(person, action, resource_id, typed)
        self.assertTrue(review["allowed"], review)
        return (person, action, resource_id, {**typed, "fingerprint": review["fingerprint"]}), {"repeatability_key": str(uuid4()), "if_match": review["resourceVersion"]}

    def act(self, person, action, resource_id, typed=None):
        args, kwargs = self.prepared(person, action, resource_id, typed)
        result = self.runner.run(*args, **kwargs)
        return result, (args, kwargs)

    def replay(self, original, request):
        before = self.state()
        replay = self.runner.run(*request[0], **request[1])
        self.assertEqual(replay, {**original, "replayed": True, "effectApplied": False})
        self.assertEqual(before, self.state())

    def accepted(self, estimate_id):
        requested, request = self.act(self.person, "estimate.request", estimate_id)
        approval = requested["result"]["approvalId"]
        granted, grant_request = self.act(self.reviewer, "estimate.accept", approval)
        applied, apply_request = self.act(self.person, "estimate.apply", approval)
        return approval, [(requested, request), (granted, grant_request), (applied, apply_request)]

    def test_all_seven_actual_actions_replay_original_after_successors_and_commitment_execution(self):
        created, create_request = self.act(self.person, "estimate.create", self.r["project_id"], self.input())
        first = created["result"]["estimateId"]
        revised, revise_request = self.act(self.person, "estimate.revise", first, self.input(previous=first))
        estimate = revised["result"]["estimateId"]
        approval, receipts = self.accepted(estimate)
        handoff, handoff_request = self.act(self.person, "estimate.prepareHandoff", estimate)
        committed, commitment_request = self.act(self.pm, "estimate.createCommitment", handoff["result"]["handoffId"])
        commitment_id = committed["result"]["commitmentId"]
        self.assertEqual(self.c.commitments.get(commitment_id)["status"], "draft")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(len(commercial_receipt_inventory_proof(self.c.db, self.c.audit)), 7)
        # A later genuine separate governed execution must not rewrite the API's
        # original created-draft result or require a second creation.
        execute = self.c.request_approval("commitment.execute", commitment_id, actor_role="pm", requested_by=ESTIMATOR_LOGIN)
        self.c.approve(execute["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.execute(execute["id"], actor=PM_LOGIN)
        next_input = self.input(previous=estimate)
        next_input["lines"][0]["quantity"] = "15"
        self.domain.revise(estimate, next_input, actor=ESTIMATOR_LOGIN)
        for original, request in [(created, create_request), (revised, revise_request), *receipts, (handoff, handoff_request), (committed, commitment_request)]:
            self.replay(original, request)
        self.assertTrue(self.runner.integrity_checks()["ok"])

    def test_simultaneous_identical_create_commits_one_original_effect(self):
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        barrier = threading.Barrier(2)
        def run():
            barrier.wait()
            return self.runner.run(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = tuple(executor.map(lambda _: run(), range(2)))
        self.assertEqual(first["receiptId"], second["receiptId"])
        self.assertEqual(sum(response["effectApplied"] for response in (first, second)), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM commercial_action_receipts"), 1)

    def test_late_receipt_failure_restores_entire_source_and_caught_outer_transaction(self):
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        record = self.c.audit.record
        def late(*values, **options):
            result = record(*values, **options)
            if values[1] == "commercial.practice_action_recorded":
                raise RuntimeError("Injected actual receipt response-loss boundary")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=late), self.assertRaises(APRefusal) as caught:
                self.runner.run(*args, **kwargs)
            self.assertEqual(caught.exception.status, 500)
            self.assertEqual(before, self.state())
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_current_duty_precedes_completed_receipt_lookup(self):
        completed, request = self.act(self.person, "estimate.create", self.r["project_id"], self.input())
        self.c.plugin("people").end_membership(ESTIMATOR_LOGIN, self.r["project_id"], reason="Synthetic commercial duty ended", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.runner.receipts, "find", side_effect=AssertionError("Private receipt disclosed")), self.assertRaises(APRefusal) as caught:
            self.runner.run(*request[0], **request[1])
        self.assertIn(caught.exception.status, (403, 404))
        self.assertEqual(before, self.state())

    def test_changed_body_and_cross_action_same_uuid_refuse_before_effects(self):
        completed, request = self.act(self.person, "estimate.create", self.r["project_id"], self.input())
        args, kwargs = request
        changed = copy.deepcopy(args[3]); changed["lines"][0]["sourceLocator"] = "A-101, altered original locator"
        before = self.state()
        with self.assertRaises(APRefusal) as body_conflict:
            self.runner.run(args[0], args[1], args[2], changed, **kwargs)
        self.assertEqual(body_conflict.exception.status, 409)
        other_args, other_kwargs = self.prepared(self.person, "estimate.request", completed["result"]["estimateId"])
        other_kwargs["repeatability_key"] = kwargs["repeatability_key"]
        with self.assertRaises(APRefusal) as action_conflict:
            self.runner.run(*other_args, **other_kwargs)
        self.assertEqual(action_conflict.exception.status, 409)
        self.assertEqual(before, self.state())

    def test_false_success_labels_or_unreviewed_genuine_second_source_roll_back(self):
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        apply = self.runner._apply
        def false_result(*values):
            result, source = apply(*values)
            result["providerCallsDelta"] = 1
            return result, source
        before = self.state()
        with patch.object(self.runner, "_apply", side_effect=false_result), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())
        def extra_source(*values):
            result, source = apply(*values)
            self.domain.create(self.r["project_id"], self.input(description="Unreviewed genuine second scope"), actor=ESTIMATOR_LOGIN)
            return result, source
        with patch.object(self.runner, "_apply", side_effect=extra_source), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())

    def test_deleted_original_receipt_or_later_source_refuses_original_creation_replay(self):
        completed, request = self.act(self.person, "estimate.create", self.r["project_id"], self.input())
        estimate = completed["result"]["estimateId"]
        later = self.domain.revise(estimate, self.input(previous=estimate), actor=ESTIMATOR_LOGIN)
        # Retain the exact original guards, remove the audited later estimate,
        # then restore guards. The surviving creation cannot become current.
        tables = ("commercial_line_sources", "commercial_estimate_sources", "estimate_lines", "estimates")
        with self.c.db.transaction():
            for table in tables:
                triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
                for trigger in triggers:
                    self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
                key = "id" if table == "estimates" else "estimate_id"
                self.c.db.execute(f"DELETE FROM {table} WHERE {key}=?", (later["estimateId"],))
                for trigger in triggers:
                    self.c.db.execute(trigger["sql"])
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_real_expiry_during_grant_records_only_terminal_control_and_original_refusal(self):
        from apps.cipher.domain import estimates as engine
        from apps.cipher.core.ids import utcnow, parse_iso
        build = engine.build_manifest
        def short_lived(**kwargs):
            manifest = build(**kwargs)
            manifest["expires_at"] = (utcnow() + datetime.timedelta(seconds=1.2)).isoformat()
            return manifest
        with patch.object(engine, "build_manifest", side_effect=short_lived):
            requested, _ = self.act(self.person, "estimate.request", self.r["current_estimate_id"])
        approval_id = requested["result"]["approvalId"]
        args, kwargs = self.prepared(self.reviewer, "estimate.accept", approval_id)
        grant = self.c.approvals.grant
        def after_deadline(*values, **options):
            deadline = parse_iso(self.c.approvals.get(approval_id)["expires_at"])
            time.sleep(max(0, (deadline - utcnow()).total_seconds()) + 0.02)
            return grant(*values, **options)
        with patch.object(self.c.approvals, "grant", side_effect=after_deadline), self.assertRaises(APRefusal) as first:
            self.runner.run(*args, **kwargs)
        self.assertEqual(first.exception.status, 423)
        self.assertTrue(first.exception.receipt_id)
        self.assertEqual(self.c.approvals.get(approval_id)["status"], "expired")
        self.assertEqual(self.c.estimates.get(self.r["current_estimate_id"])["status"], "draft")
        before = self.state()
        with self.assertRaises(APRefusal) as retry:
            self.runner.run(*args, **kwargs)
        self.assertEqual(retry.exception.receipt_id, first.exception.receipt_id)
        self.assertTrue(retry.exception.replayed)
        self.assertEqual(before, self.state())

    def test_unexpected_schema_or_financial_effect_and_false_typed_stale_roll_back(self):
        from apps.cipher.core.approvals import StaleApprovalError
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        apply = self.runner._apply
        def extra_schema(*values):
            result = apply(*values)
            self.c.db.execute("CREATE TABLE unreviewed_commercial_side_effect (id TEXT)")
            return result
        before = self.state()
        with patch.object(self.runner, "_apply", side_effect=extra_schema), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())
        def false_stale(*values):
            apply(*values)
            raise StaleApprovalError("Injected false typed refusal after creation")
        with patch.object(self.runner, "_apply", side_effect=false_stale), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())

    def test_response_assembly_fault_rolls_back_and_committed_response_loss_replays_once(self):
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        before = self.state()
        with patch.object(self.runner, "_response", side_effect=RuntimeError("Injected response assembly failure")), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())
        # Simulate a caller losing the returned response after commit. Its only
        # recovery is this exact body/version/fingerprint/UUID request.
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_original_acceptance_retry_refuses_forged_command_cache(self):
        estimate = self.r["current_estimate_id"]
        approval, receipts = self.accepted(estimate)
        row = self.c.db.one("SELECT * FROM idempotency WHERE op_id=?", (f"exec:{approval}",))
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='idempotency'")
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
            self.c.db.execute("UPDATE idempotency SET payload_hash='forged-original-command' WHERE op_id=?", (row["op_id"],))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])
        before = self.state()
        original, request = receipts[-1]
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_missing_receipt_birth_inventory_or_guard_refuses_completed_replay(self):
        original, request = self.act(self.person, "estimate.create", self.r["project_id"], self.input())
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='commercial_action_receipts'")
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
            self.c.db.execute("DELETE FROM commercial_action_receipts WHERE id=?", (original["receiptId"],))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_late_acceptance_receipt_fault_restores_grant_command_and_baseline(self):
        requested, _ = self.act(self.person, "estimate.request", self.r["current_estimate_id"])
        approval = requested["result"]["approvalId"]
        self.act(self.reviewer, "estimate.accept", approval)
        args, kwargs = self.prepared(self.person, "estimate.apply", approval)
        record = self.c.audit.record
        def late(*values, **options):
            result = record(*values, **options)
            if values[1] == "commercial.practice_action_recorded":
                raise RuntimeError("Injected late accepted-baseline receipt failure")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=late), self.assertRaises(APRefusal):
                self.runner.run(*args, **kwargs)
            self.assertEqual(before, self.state())
            self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
            self.assertIsNone(self.c.db.one("SELECT * FROM idempotency WHERE op_id=?", (f"exec:{approval}",)))
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_outer_commit_failure_restores_local_effect_and_receipt_before_retry(self):
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        execute = self.c.db.conn.execute
        def fail_commit(sql, *values, **options):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("Injected SQLite commit failure")
            return execute(sql, *values, **options)
        before = self.state()
        with patch.object(self.c.db.conn, "execute", side_effect=fail_commit), self.assertRaises(APRefusal) as caught:
            self.runner.run(*args, **kwargs)
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(before, self.state())
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_pure_metadata_inventory_initializes_no_domain_or_ap_lookup(self):
        original, _ = self.act(self.person, "estimate.create", self.r["project_id"], self.input())
        from apps.cipher.core.api_receipts import APIActionReceipts
        before = self.state(), self.c.db.conn.total_changes
        with patch.object(self.domain, "source", side_effect=AssertionError("Domain initialization forbidden")), patch.object(APIActionReceipts, "find", side_effect=AssertionError("AP recursion forbidden")):
            rows = commercial_receipt_inventory_proof(self.c.db, self.c.audit)
        self.assertEqual([row["id"] for row in rows], [original["receiptId"]])
        self.assertEqual(before, (self.state(), self.c.db.conn.total_changes))

    def test_existing_audited_ap_namespace_is_not_available_for_commercial_effect(self):
        from apps.cipher.core.api_receipts import APIActionReceipts
        args, kwargs = self.prepared(self.person, "estimate.create", self.r["project_id"], self.input())
        # Namespace ownership is metadata-only. Even an AP entry whose business
        # source is unavailable cannot be recycled into a commercial creation.
        binding = {"contractVersion": "cipher.ap-practice.v1", "fixedAction": "bill.requestApproval", "resourceId": "prior-ap-resource",
                   "canonicalTypedBody": {"fingerprint": "original-ap-review"}, "originalIfMatch": "original-ap-version", "preflightFingerprint": "original-ap-review"}
        with self.c.db.transaction():
            APIActionReceipts(self.c.db, self.c.audit).record(person_id=self.person, actor_login=ESTIMATOR_LOGIN,
                repeatability_uuid=kwargs["repeatability_key"], contract_version="cipher.ap-practice.v1", action="bill.requestApproval",
                resource_id="prior-ap-resource", binding=binding, outcome="success", http_status=200,
                result={"status": "pending"}, source={"kind": "unavailable-prior-source"})
        before = self.state()
        with self.assertRaises(APRefusal) as caught:
            self.runner.run(*args, **kwargs)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
