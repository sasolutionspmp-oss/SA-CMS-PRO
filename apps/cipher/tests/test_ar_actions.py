"""Actual owner source, split grant/post, synthetic send and atomic API receipts."""
import copy
import sqlite3
import threading
import datetime
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from apps.cipher import service
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import canonical_json
from apps.cipher.domain.owner_billing import register_owner_billing_schema
from apps.cipher.ar_receipts import register_ar_receipts_schema, ar_receipt_inventory_proof
register_owner_billing_schema()
register_ar_receipts_schema()
from apps.cipher.ar_practice_fixture import (make_ar_practice_fixture, PM_LOGIN, REVIEWER_LOGIN, POSTER_LOGIN, BOOTSTRAP_LOGIN)
from apps.cipher.ar_contract import ARContract
from apps.cipher.ar_preflight import ARPreflight
from apps.cipher.ar_actions import ARActionRunner


class ARActionTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ar_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("owner_billing")
        self.r = self.c.ar_practice_records
        self.person, self.reviewer, self.poster, self.controller = (self.c.ar_practice_persona_people[key]["person_id"] for key in ("preparer", "reviewer", "poster", "controller"))
        secret = b"owner-billing-actions-real-source-private-key"
        self.contract = ARContract(self.c, secret=secret)
        self.preflight = ARPreflight(self.c, self.contract, secret=secret)
        self.runner = ARActionRunner(self.c, self.contract, self.preflight)

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def input(self):
        return {"claimRevisionId": self.r["claim_revision_id"], "reviewRevisionId": self.r["review_revision_id"], "periodId": self.r["period_id"],
                "lines": [{"lineId": "U1", "claimedCumulative": "12", "reviewedCumulative": "10", "differenceReason": "Synthetic independently reviewed installed count",
                           "claimSourceLocator": "Owner claim, line U1", "reviewSourceLocator": "PM review, verified count U1"},
                          {"lineId": "L2", "claimedCumulative": "15000", "reviewedCumulative": "12500", "differenceReason": "Synthetic reviewed lump sum progress",
                           "claimSourceLocator": "Owner claim, line L2", "reviewSourceLocator": "PM review, earned value L2"}]}

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

    def granted(self):
        prepared, prepare_request = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        bill = prepared["result"]["billId"]
        requested, request = self.act(self.person, "ownerBill.requestApproval", bill)
        approval = requested["result"]["approvalId"]
        granted, grant_request = self.act(self.reviewer, "ownerBill.approve", approval)
        return bill, approval, [(prepared, prepare_request), (requested, request), (granted, grant_request)]

    def posted(self):
        bill, approval, receipts = self.granted()
        posted, request = self.act(self.poster, "ownerBill.post", bill)
        return bill, approval, [*receipts, (posted, request)]

    def test_all_seven_actions_preserve_original_outcomes_after_send_collection_and_source_successor(self):
        bill, approval, receipts = self.granted()
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.c.receivables.get(bill)["recorded_status"], "draft")
        posted, post_request = self.act(self.poster, "ownerBill.post", bill)
        receipts.append((posted, post_request))
        self.assertEqual(posted["result"]["approvalId"], approval)
        self.assertEqual(posted["result"]["journalCountDelta"], 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)
        self.assertEqual(self.c.approvals.get(approval)["status"], "consumed")
        requested, request = self.act(self.person, "ownerBill.requestSend", bill)
        send_approval = requested["result"]["approvalId"]
        granted, grant_request = self.act(self.reviewer, "ownerBill.approveSend", send_approval)
        sent, send_request = self.act(self.person, "ownerBill.send", send_approval)
        receipts += [(requested, request), (granted, grant_request), (sent, send_request)]
        self.assertTrue(sent["result"]["syntheticMailSink"])
        self.assertEqual(sent["result"]["externalDelivery"], "not_attempted")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)
        self.c.receivables.record_collection(prime_bill_id=bill, period_id=self.r["period_id"], amount="100.00", fee="0", method="check",
                                           provider_ref="SIM-AR-ORIGINAL-ACTION-READBACK", actor=POSTER_LOGIN)
        review = self.c.evidence.revision(self.r["review_revision_id"])
        self.c.evidence.add_revision(document_id=review["document_id"], content="Synthetic later owner certification source", actor=PM_LOGIN)
        for original, request in receipts:
            self.replay(original, request)
        self.assertEqual(len(ar_receipt_inventory_proof(self.c.db, self.c.audit)), 7)
        self.assertTrue(self.runner.integrity_checks()["ok"])

    def test_financial_reviewer_cannot_post_and_controller_may_post_same_original_grant(self):
        bill, approval, _ = self.granted()
        blocked = self.preflight.review(self.reviewer, "ownerBill.post", bill, {})
        self.assertFalse(blocked["allowed"])
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(self.reviewer, "ownerBill.post", bill, {"fingerprint": "unqualified-review"}, repeatability_key=str(uuid4()), if_match=blocked["version"])
        self.assertEqual(before, self.state())
        posted, request = self.act(self.controller, "ownerBill.post", bill)
        self.assertEqual(posted["result"]["approvalId"], approval)
        self.replay(posted, request)
        with self.assertRaises(APRefusal) as no_send:
            self.preflight.review(self.controller, "ownerBill.requestSend", bill, {})
        self.assertEqual(no_send.exception.status, 403)

    def test_concurrent_identical_post_creates_one_journal_receipt_and_consumption(self):
        bill, approval, _ = self.granted()
        args, kwargs = self.prepared(self.poster, "ownerBill.post", bill)
        barrier = threading.Barrier(2)
        def run(_):
            barrier.wait()
            return self.runner.run(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = tuple(executor.map(run, range(2)))
        self.assertEqual(responses[0]["receiptId"], responses[1]["receiptId"])
        self.assertEqual(sum(item["effectApplied"] for item in responses), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM owner_billing_postings"), 1)

    def test_caught_late_post_receipt_fault_restores_grant_journal_and_command(self):
        bill, approval, _ = self.granted()
        args, kwargs = self.prepared(self.poster, "ownerBill.post", bill)
        record = self.c.audit.record
        def late(*values, **options):
            result = record(*values, **options)
            if values[1] == "ar.practice_action_recorded":
                raise RuntimeError("Injected late original owner-post receipt failure")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=late), self.assertRaises(APRefusal):
                self.runner.run(*args, **kwargs)
            self.assertEqual(before, self.state())
            self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
            self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_outer_commit_failure_rolls_back_preparation_source_and_receipt(self):
        args, kwargs = self.prepared(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        execute = self.c.db.conn.execute
        def fail_commit(sql, *values, **options):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("Injected SQLite owner-bill commit fault")
            return execute(sql, *values, **options)
        before = self.state()
        with patch.object(self.c.db.conn, "execute", side_effect=fail_commit), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_exact_result_types_and_unreviewed_second_source_or_schema_roll_back(self):
        args, kwargs = self.prepared(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        apply = self.runner._apply
        before = self.state()
        def false_result(*values):
            result, source = apply(*values)
            result["journalCountDelta"] = 0.0
            return result, source
        with patch.object(self.runner, "_apply", side_effect=false_result), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())
        def extra_schema(*values):
            result = apply(*values)
            self.c.db.execute("CREATE TABLE unrelated_ar_effect(id TEXT)")
            return result
        with patch.object(self.runner, "_apply", side_effect=extra_schema), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())

    def test_current_own_duty_precedes_completed_receipt_lookup(self):
        completed, request = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        self.c.plugin("people").end_membership(PM_LOGIN, self.r["project_id"], reason="Synthetic departed owner-billing PM", actor=BOOTSTRAP_LOGIN)
        before = self.state()
        with patch.object(self.runner.receipts, "find", side_effect=AssertionError("Receipt disclosed before current duty")), self.assertRaises(APRefusal) as caught:
            self.runner.run(*request[0], **request[1])
        self.assertIn(caught.exception.status, (403, 404))
        self.assertEqual(before, self.state())

    def test_changed_typed_claim_and_cross_action_uuid_conflict_before_effect(self):
        prepared, request = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        args, kwargs = request
        changed = copy.deepcopy(args[3]); changed["lines"][0]["claimSourceLocator"] = "Changed original claim locator"
        before = self.state()
        with self.assertRaises(APRefusal) as body_conflict:
            self.runner.run(args[0], args[1], args[2], changed, **kwargs)
        self.assertEqual(body_conflict.exception.status, 409)
        other, other_options = self.prepared(self.person, "ownerBill.requestApproval", prepared["result"]["billId"])
        other_options["repeatability_key"] = kwargs["repeatability_key"]
        with self.assertRaises(APRefusal) as action_conflict:
            self.runner.run(*other, **other_options)
        self.assertEqual(action_conflict.exception.status, 409)
        self.assertEqual(before, self.state())

    def test_pure_receipt_inventory_calls_no_domain_or_ap_lookup_and_has_no_writes(self):
        completed, _ = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        from apps.cipher.core.api_receipts import APIActionReceipts
        before = self.state(), self.c.db.conn.total_changes
        with patch.object(self.domain, "source_proof", side_effect=AssertionError("Source callback forbidden")), patch.object(APIActionReceipts, "find", side_effect=AssertionError("AP callback forbidden")):
            rows = ar_receipt_inventory_proof(self.c.db, self.c.audit)
        self.assertEqual([row["id"] for row in rows], [completed["receiptId"]])
        self.assertEqual(before, (self.state(), self.c.db.conn.total_changes))

    def test_post_cannot_override_original_reviewed_journal_rule_or_line_scope(self):
        bill, _, _ = self.granted()
        args, kwargs = self.prepared(self.poster, "ownerBill.post", bill)
        post = self.c.ledger.post
        def changed_rule(**values):
            values["rule_version"] = "unreviewed-owner-billing-rule"
            return post(**values)
        before = self.state()
        with patch.object(self.c.ledger, "post", side_effect=changed_rule), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())

    def test_prepare_retry_refuses_unaudited_current_posting_lifecycle(self):
        completed, request = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        bill = completed["result"]["billId"]
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='prime_bills'")
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
            self.c.db.execute("UPDATE prime_bills SET status='posted' WHERE id=?", (bill,))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def ready_send(self):
        bill, _, receipts = self.posted()
        requested, request = self.act(self.person, "ownerBill.requestSend", bill)
        approval = requested["result"]["approvalId"]
        granted, grant_request = self.act(self.reviewer, "ownerBill.approveSend", approval)
        return bill, approval, [*receipts, (requested, request), (granted, grant_request)]

    def test_concurrent_identical_send_records_one_original_synthetic_message(self):
        bill, approval, _ = self.ready_send()
        args, kwargs = self.prepared(self.person, "ownerBill.send", approval)
        barrier = threading.Barrier(2)
        def run(_):
            barrier.wait()
            return self.runner.run(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = tuple(executor.map(run, range(2)))
        self.assertEqual(responses[0]["receiptId"], responses[1]["receiptId"])
        self.assertEqual(sum(item["effectApplied"] for item in responses), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)
        self.assertEqual(self.c.approvals.get(approval)["status"], "consumed")

    def test_caught_late_send_receipt_fault_restores_grant_message_and_command(self):
        bill, approval, _ = self.ready_send()
        args, kwargs = self.prepared(self.person, "ownerBill.send", approval)
        record = self.c.audit.record
        def late(*values, **options):
            result = record(*values, **options)
            if values[1] == "ar.practice_action_recorded":
                raise RuntimeError("Injected late original synthetic-send receipt fault")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=late), self.assertRaises(APRefusal):
                self.runner.run(*args, **kwargs)
            self.assertEqual(before, self.state())
            self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
            self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"), 0)
        completed = self.runner.run(*args, **kwargs)
        self.replay(completed, (args, kwargs))

    def test_unreviewed_genuine_second_authorization_rolls_back_first_request(self):
        prepared, _ = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        bill = prepared["result"]["billId"]
        args, kwargs = self.prepared(self.person, "ownerBill.requestApproval", bill)
        apply = self.runner._apply
        def second_request(*values):
            result = apply(*values)
            self.c.request_approval("prime_bill.approve", bill, actor_role="accountant", requested_by=PM_LOGIN)
            return result
        before = self.state()
        with patch.object(self.runner, "_apply", side_effect=second_request), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())

    def test_original_post_retry_refuses_tampered_command_payload_hash(self):
        bill, approval, receipts = self.posted()
        original, request = receipts[-1]
        op_id = f"prime_bill.post:{bill}:{approval}"
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='idempotency'")
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
            self.c.db.execute("UPDATE idempotency SET payload_hash='forged-owner-post-payload' WHERE op_id=?", (op_id,))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_deleted_original_receipt_birth_cannot_be_recreated_under_same_request(self):
        original, request = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        triggers = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='ar_action_receipts'")
        with self.c.db.transaction():
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
            self.c.db.execute("DELETE FROM ar_action_receipts WHERE id=?", (original["receiptId"],))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])
        before = self.state()
        with self.assertRaises(APRefusal):
            self.runner.run(*request[0], **request[1])
        self.assertEqual(before, self.state())

    def test_genuine_grant_expiry_commits_only_control_and_replays_after_later_rejection(self):
        from apps.cipher.domain import receivables as engine
        from apps.cipher.core.ids import parse_iso, utcnow
        prepared, _ = self.act(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        build = engine.build_manifest
        def short_lived(**kwargs):
            manifest = build(**kwargs)
            manifest["expires_at"] = (utcnow() + datetime.timedelta(seconds=1.2)).isoformat()
            return manifest
        with patch.object(engine, "build_manifest", side_effect=short_lived):
            requested, _ = self.act(self.person, "ownerBill.requestApproval", prepared["result"]["billId"])
        approval = requested["result"]["approvalId"]
        args, kwargs = self.prepared(self.reviewer, "ownerBill.approve", approval)
        grant = self.c.approvals.grant
        def after_deadline(*values, **options):
            deadline = parse_iso(self.c.approvals.get(approval)["expires_at"])
            time.sleep(max(0, (deadline-utcnow()).total_seconds())+0.02)
            return grant(*values, **options)
        with patch.object(self.c.approvals, "grant", side_effect=after_deadline), self.assertRaises(APRefusal) as first:
            self.runner.run(*args, **kwargs)
        self.assertEqual(first.exception.status, 423)
        self.assertTrue(first.exception.receipt_id)
        self.assertEqual(self.c.approvals.get(approval)["status"], "expired")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM owner_billing_grants"), 0)
        self.c.approvals.invalidate(approval, reason="Synthetic later independent rejection", actor=REVIEWER_LOGIN)
        before = self.state()
        with self.assertRaises(APRefusal) as retry:
            self.runner.run(*args, **kwargs)
        self.assertEqual(retry.exception.receipt_id, first.exception.receipt_id)
        self.assertTrue(retry.exception.replayed)
        self.assertEqual(before, self.state())

    def test_post_response_assembly_failure_rolls_back_and_lost_completed_response_replays_once(self):
        bill, approval, _ = self.granted()
        args, kwargs = self.prepared(self.poster, "ownerBill.post", bill)
        before = self.state()
        with patch.object(self.runner, "_response", side_effect=RuntimeError("Injected original posting response assembly fault")), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        completed = self.runner.run(*args, **kwargs)
        # The client may lose this already committed response. Repeating exactly
        # the original key/body/version returns its outcome with no new journal.
        self.replay(completed, (args, kwargs))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), 1)

    def test_generated_api_receipt_time_requires_its_original_audit_clock(self):
        from apps.cipher import ar_receipts
        args, kwargs = self.prepared(self.person, "ownerBill.prepare", self.r["basis_id"], self.input())
        before = self.state()
        with patch.object(ar_receipts, "utcnow_iso", return_value="2099-12-31T00:00:00Z"), self.assertRaises(APRefusal):
            self.runner.run(*args, **kwargs)
        self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
