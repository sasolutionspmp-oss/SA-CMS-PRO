"""Original accounting API outcomes, committed reservations and recovery faults."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import datetime as dt
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_accounting_actions import APAccountingActionRunner, invocation_inventory_proof
from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APRefusal
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_intake_actions import APIntakeActionRunner
from apps.cipher.ap_intake_preflight import APIntakePreflight
from apps.cipher.ap_exception_actions import APExceptionActionRunner
from apps.cipher.ap_exception_preflight import APExceptionPreflight
from apps.cipher.accounting_simulator import Fault
from apps.cipher.accounting_worker import WorkerHeld
from apps.cipher.core.ids import loads, utcnow
from apps.cipher.tests.test_ap_accounting_contract import AccountingWorld


class APAccountingActionsTests(AccountingWorld, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.runner = APAccountingActionRunner(self.c, self.contract, self.preflight, worker=self.worker)

    def stored(self):
        return tuple(self.c.db.conn.iterdump())

    def reviewed(self, action, resource, *, person=None, key=None):
        person = person or self.person
        review = self.preflight.review(person, action, resource, {})
        self.assertTrue(review["allowed"], review)
        return {"person_id": person, "action": action, "resource_id": resource,
                "body": {"fingerprint": review["fingerprint"]}, "repeatability_key": key or str(uuid4()), "if_match": review["resourceVersion"]}

    def action(self, action, resource, *, person=None):
        args = self.reviewed(action, resource, person=person)
        return self.runner.run(**args), args

    def queued_api(self):
        requested, request = self.action("accounting.request", self.plan["id"])
        approval = requested["result"]["approvalId"]
        granted, grant = self.action("accounting.approve", approval, person=self.reviewer)
        queued, queue = self.action("accounting.queue", approval)
        return queued["result"]["intentId"], [(requested, request), (granted, grant), (queued, queue)]

    def correct(self):
        self.c.bills.prepare_correction(self.bill_id, "Synthetic original source correction", "practice.accountant")
        approval = self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by="practice.accountant")
        self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        self.c.execute(approval["id"], actor="practice.accountant", period_id="2026-11")

    def reserve(self, args):
        key, binding = self.runner._shape(args["action"], args["resource_id"], args["body"], args["repeatability_key"], args["if_match"])
        checked = self.preflight.verify(self.person, args["action"], args["resource_id"], args["body"], args["if_match"])
        with self.c.db.transaction():
            return self.runner.invocations.reserve(person_id=self.person, actor_login="practice.accountant", action=args["action"],
                intent_id=args["resource_id"], repeatability_uuid=key, binding=binding, reviewed_source=checked["plan"])

    def test_four_human_actions_then_three_worker_outcomes_and_original_replays(self):
        self.domain.prepare_synthetic_mapping(self.plan["project_id"], actor="practice.accountant", reason="New fixed synthetic mapping")
        prepared, args = self.action("accounting.prepare", self.bill_id)
        self.plan = self.domain.plan(prepared["result"]["planId"])
        intent, calls = self.queued_api()
        calls.insert(0, (prepared, args))
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        unknown, args = self.action("accounting.deliver", intent)
        calls.append((unknown, args))
        accepted, args = self.action("accounting.lookup", intent)
        calls.append((accepted, args))
        reconciled, args = self.action("accounting.reconcile", intent)
        calls.append((reconciled, args))
        self.assertEqual(unknown["result"]["status"], "outcome_unknown")
        self.assertEqual(accepted["result"]["status"], "simulated_accepted")
        self.assertEqual(reconciled["result"]["status"], "reconciled")
        self.correct()
        before = self.stored(), dict(self.adapter.calls), self.store.effect_count
        for original, args in calls:
            replay = self.runner.run(**args)
            self.assertTrue(replay["replayed"])
            self.assertFalse(replay["effectApplied"])
            self.assertEqual(replay["result"], original["result"])
            self.assertEqual(replay["receiptId"], original["receiptId"])
        self.assertEqual((self.stored(), dict(self.adapter.calls), self.store.effect_count), before)
        self.assertEqual(self.adapter.calls, {"submit": 1, "lookup": 1, "read_record": 1})
        self.assertEqual(self.store.effect_count, 1)
        self.assertEqual(self.runner.integrity_checks(), [])

    def test_receipt_failure_after_acceptance_resumes_completion_without_provider_call(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        original = self.runner.receipts.record
        def fail(*values, **fields):
            original(*values, **fields)
            raise RuntimeError("Synthetic API projection failure")
        with patch.object(self.runner.receipts, "record", side_effect=fail):
            pending = self.runner.run(**args)
        self.assertNotIn("receiptId", pending)
        self.assertEqual(pending["state"], "observed")
        self.assertEqual(self.domain.intent(intent)["status"], "simulated_accepted")
        calls = dict(self.adapter.calls)
        completed = self.runner.run(**args)
        self.assertEqual(completed["result"]["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls, calls)
        self.assertEqual(self.store.effect_count, 1)

    def test_api_completion_commit_failure_retains_observation_and_original_uuid(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        original = self.c.db.transaction
        failed = []
        @contextmanager
        def failing_commit():
            with original() as conn:
                count = self.c.db.scalar("SELECT COUNT(*) FROM ap_action_receipts")
                yield conn
                if not failed and self.c.db.scalar("SELECT COUNT(*) FROM ap_action_receipts") > count:
                    failed.append(True)
                    raise RuntimeError("Synthetic completion commit failure")
        with patch.object(self.c.db, "transaction", side_effect=failing_commit):
            pending = self.runner.run(**args)
        self.assertTrue(failed)
        self.assertEqual(pending["state"], "observed")
        self.assertEqual(self.store.effect_count, 1)
        before = dict(self.adapter.calls)
        completed = self.runner.run(**args)
        self.assertEqual(completed["result"]["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls, before)

    def test_only_genuine_expiry_transition_can_commit_typed_refusal(self):
        request, _ = self.action("accounting.request", self.plan["id"])
        args = self.reviewed("accounting.approve", request["result"]["approvalId"], person=self.reviewer)
        future = utcnow()+dt.timedelta(days=7)
        before_journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        with patch("apps.cipher.core.approvals.utcnow", return_value=future):
            with self.assertRaises(APRefusal) as failure:
                self.runner.run(**args)
        self.assertEqual(failure.exception.status, 423)
        self.assertEqual(self.c.approvals.get(args["resource_id"])["status"], "expired")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), before_journals)
        before = self.stored()
        with self.assertRaises(APRefusal) as replay:
            self.runner.run(**args)
        self.assertTrue(replay.exception.replayed)
        self.assertEqual(self.stored(), before)

    def test_false_stale_exception_rolls_back_all_effects_and_records_no_refusal(self):
        from apps.cipher.core.approvals import StaleApprovalError
        request, _ = self.action("accounting.request", self.plan["id"])
        args = self.reviewed("accounting.approve", request["result"]["approvalId"], person=self.reviewer)
        before = self.stored()
        with patch.object(self.c, "approve", side_effect=StaleApprovalError("Synthetic false stale")), self.assertRaises(APRefusal) as failure:
            self.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(self.stored(), before)

    def test_local_finish_failure_recovers_original_uuid_by_lookup_only_after_lease(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        with patch.object(self.domain, "finish_attempt", side_effect=RuntimeError("Synthetic local persistence failure")):
            pending = self.runner.run(**args)
        self.assertEqual(pending["state"], "claimed")
        self.assertEqual(self.store.effect_count, 1)
        repeated = self.runner.run(**args)
        self.assertNotIn("receiptId", repeated)
        self.assertEqual(self.adapter.calls["submit"], 1)
        future = utcnow()+dt.timedelta(seconds=120)
        with patch("apps.cipher.domain.accounting.utcnow", return_value=future), patch("apps.cipher.ap_accounting_actions.utcnow", return_value=future):
            completed = self.runner.run(**args)
        self.assertEqual(completed["result"]["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls, {"submit": 1, "lookup": 1, "read_record": 0})
        self.assertEqual(self.store.effect_count, 1)

    def test_unknown_before_acceptance_then_missing_lookup_and_explicit_later_delivery(self):
        intent, _ = self.queued_api()
        self.adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
        unknown, original_args = self.action("accounting.deliver", intent)
        missing, missing_args = self.action("accounting.lookup", intent)
        self.assertEqual(missing["result"]["status"], "confirmed_missing")
        self.assertEqual(self.store.effect_count, 0)
        accepted, _ = self.action("accounting.deliver", intent)
        self.assertEqual(accepted["result"]["logicalOperationId"], unknown["result"]["logicalOperationId"])
        self.assertEqual(self.runner.run(**original_args)["result"], unknown["result"])
        self.assertEqual(self.runner.run(**missing_args)["result"], missing["result"])
        self.assertEqual(self.store.effect_count, 1)

    def test_concurrent_same_invocation_has_one_submit_and_one_completion(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: self.runner.run(**args), range(4)))
        completed = [row for row in outcomes if "receiptId" in row]
        self.assertTrue(completed)
        self.assertEqual(len({row["receiptId"] for row in completed}), 1)
        self.assertEqual(self.adapter.calls["submit"], 1)
        self.assertEqual(self.store.effect_count, 1)
        self.assertEqual(len(invocation_inventory_proof(self.c.db, self.c.audit)), 1)

    def test_reserved_invocation_body_or_version_change_conflicts_without_provider(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        self.reserve(args)
        before = self.stored()
        for changed in ({"if_match": "changed"}, {"body": {"fingerprint": "changed"}}, {"action": "accounting.lookup"}):
            with self.subTest(changed=changed), self.assertRaises(APRefusal) as failure:
                self.runner.run(**{**args, **changed})
            self.assertEqual(failure.exception.status, 409)
        self.assertEqual(self.stored(), before)
        self.assertEqual(self.adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})

    def test_pending_worker_key_refuses_all_earlier_fixed_action_namespaces(self):
        intent, _ = self.queued_api()
        worker_args = self.reviewed("accounting.deliver", intent)
        self.reserve(worker_args)
        old = APActionRunner(self.c, self.base, APPreflight(self.c, self.base, secret=self.secret))
        intake = APIntakeActionRunner(self.c, self.intake, APIntakePreflight(self.c, self.intake, secret=self.secret))
        exceptions = APExceptionActionRunner(self.c, self.exception, APExceptionPreflight(self.c, self.exception, secret=self.secret))
        pending_bill = self.c.ap_practice_records["prepared_bill_id"] if "prepared_bill_id" in self.c.ap_practice_records else self.c.ap_practice_records["draft_bill_id"]
        # Authorizers must run first; use actual scoped resources even where a
        # fresh review would be ineligible. The namespace precedes eligibility.
        options = [(old, "bill.requestApproval", pending_bill, {"fingerprint": "synthetic"}),
                   (intake, "invoice.receive", self.c.ap_practice_records["prep_commitment_id"],
                    {"fingerprint": "synthetic", "invoiceNumber": "SYNTHETIC-COLLISION", "invoiceDate": "2026-10-14", "amountCents": 100,
                     "evidenceRevisionId": self.c.ap_practice_records["visible_invoice_evidence_revision_ids"][0]}),
                   (exceptions, "bill.prepareCorrection", self.bill_id, {"fingerprint": "synthetic", "reason": "Synthetic correction"})]
        before = self.stored()
        for runner, action, resource, body in options:
            with self.subTest(action=action), self.assertRaises(APRefusal) as failure:
                runner.run(self.person, action, resource, body, repeatability_key=worker_args["repeatability_key"], if_match="synthetic")
            self.assertEqual(failure.exception.status, 409)
        self.assertEqual(self.stored(), before)

    def test_pending_worker_uuid_has_one_namespace_across_all_twenty_four_actions(self):
        intent, _ = self.queued_api()
        worker_args = self.reviewed("accounting.deliver", intent)
        self.reserve(worker_args)
        old = APActionRunner(self.c, self.base, APPreflight(self.c, self.base, secret=self.secret))
        intake = APIntakeActionRunner(self.c, self.intake, APIntakePreflight(self.c, self.intake, secret=self.secret))
        exceptions = APExceptionActionRunner(self.c, self.exception, APExceptionPreflight(self.c, self.exception, secret=self.secret))
        commitment_id = self.c.ap_practice_records["prep_commitment_id"]
        commitment = self.c.commitments.get(commitment_id)
        prepare_body = {"periodId": "2026-10", "installed": [{"sovLineId": line["id"], "cumulativeInstalledCents": 10000 if index == 0 else 0}
                        for index, line in enumerate(commitment["sov"])]}
        def real_intake(action, resource, body):
            review = intake.preflight.review(self.person, action, resource, body)
            self.assertTrue(review["allowed"], review)
            return intake.run(self.person, action, resource, {**body, "fingerprint": review["fingerprint"]},
                              repeatability_key=str(uuid4()), if_match=review["resourceVersion"])["result"]
        bill = real_intake("bill.prepare", commitment_id, prepare_body)
        evidence = self.c.ap_practice_records["visible_invoice_evidence_revision_ids"][0]
        receive_body = {"invoiceNumber": "SYNTHETIC-ALL-NAMESPACES", "invoiceDate": "2026-10-14", "amountCents": bill["amountDueCents"], "evidenceRevisionId": evidence}
        invoice = real_intake("invoice.receive", commitment_id, receive_body)
        real_intake("invoice.computeMatch", invoice["invoiceId"], {})
        match = real_intake("invoice.requestMatchApproval", invoice["invoiceId"], {})
        business = self.c.request_approval("bill.approve", bill["billId"], actor_role="accountant", requested_by="practice.accountant")
        self.c.bills.prepare_correction(self.bill_id, "Synthetic namespace correction", "practice.accountant")
        correction = self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by="practice.accountant")
        accounting_approval = self.c.approvals.get(self.domain.intent(intent)["approval_id"])
        fp, reason = {"fingerprint": "different-original-binding"}, "Synthetic namespace refusal"
        cases = [(old, "bill.requestApproval", bill["billId"], fp), (old, "bill.approve", business["id"], fp),
                 (old, "bill.post", self.bill_id, {**fp, "periodId": "2026-11", "reason": reason}),
                 (intake, "bill.prepare", commitment_id, {**fp, **prepare_body}),
                 (intake, "invoice.receive", commitment_id, {**fp, **receive_body}),
                 *[(intake, action, invoice["invoiceId"], fp) for action in ("invoice.computeMatch", "invoice.requestMatchApproval")],
                 *[(intake, action, match["approvalId"], fp) for action in ("invoice.approveMatch", "invoice.executeMatch")],
                 (exceptions, "invoice.revise", invoice["invoiceId"], {**fp, **receive_body, "reason": reason}),
                 *[(exceptions, action, invoice["invoiceId"], {**fp, "reason": reason}) for action in ("invoice.reject", "invoice.reviewDuplicate")],
                 (exceptions, "bill.cancel", bill["billId"], {**fp, "reason": reason}),
                 (exceptions, "bill.prepareCorrection", self.bill_id, {**fp, "reason": reason}),
                 (exceptions, "bill.requestCorrection", self.bill_id, fp),
                 (exceptions, "bill.approveCorrection", correction["id"], fp),
                 (exceptions, "bill.executeCorrection", correction["id"], {**fp, "periodId": "2026-11"}),
                 (self.runner, "accounting.prepare", self.bill_id, fp), (self.runner, "accounting.request", self.plan["id"], fp),
                 *[(self.runner, action, accounting_approval["id"], fp) for action in ("accounting.approve", "accounting.queue")],
                 *[(self.runner, action, intent, fp) for action in ("accounting.deliver", "accounting.lookup", "accounting.reconcile")]]
        self.assertEqual(len(cases), 24)
        before = self.stored(), dict(self.adapter.calls), self.store.effect_count
        for runner, action, resource, body in cases:
            with self.subTest(action=action), self.assertRaises(APRefusal) as failure:
                runner.run(self.person, action, resource, body, repeatability_key=worker_args["repeatability_key"], if_match="different-original-version")
            # The old business grant requires the distinct PM duty and refuses
            # this accountant before consulting any person's reservation.
            self.assertEqual(failure.exception.status, 403 if action == "bill.approve" else 409, action)
        self.assertEqual((self.stored(), dict(self.adapter.calls), self.store.effect_count), before)

    def test_human_success_with_unreviewed_schema_effect_rolls_back_everything(self):
        args = self.reviewed("accounting.request", self.plan["id"])
        original = self.c.request_approval
        def corrupt(*values, **fields):
            approval = original(*values, **fields)
            self.c.db.conn.execute("CREATE TABLE synthetic_unreviewed_effect(id TEXT)")
            return approval
        before = self.stored()
        with patch.object(self.c, "request_approval", side_effect=corrupt), self.assertRaises(APRefusal):
            self.runner.run(**args)
        self.assertEqual(self.stored(), before)

    def test_worker_claim_unreviewed_schema_effect_cannot_call_provider(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        original = self.domain._record
        def corrupt(kind, body, **fields):
            result = original(kind, body, **fields)
            if kind == "attempts":
                self.c.db.conn.execute("CREATE TABLE synthetic_unreviewed_claim(id TEXT)")
            return result
        with patch.object(self.domain, "_record", side_effect=corrupt):
            pending = self.runner.run(**args)
        self.assertEqual(pending["state"], "reserved")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM accounting_attempts"), 0)
        self.assertIsNone(self.c.db.one("SELECT name FROM sqlite_master WHERE name='synthetic_unreviewed_claim'"))
        self.assertEqual(self.store.effect_count, 0)
        self.assertEqual(self.adapter.calls["submit"], 0)

    def test_worker_observation_unreviewed_source_effect_rolls_back_to_claim(self):
        intent, _ = self.queued_api()
        args = self.reviewed("accounting.deliver", intent)
        original = self.domain._record
        def corrupt(kind, body, **fields):
            result = original(kind, body, **fields)
            if kind == "attempt_results":
                self.c.db.conn.execute("CREATE TABLE synthetic_unreviewed_observation(id TEXT)")
            return result
        with patch.object(self.domain, "_record", side_effect=corrupt):
            pending = self.runner.run(**args)
        self.assertEqual(pending["state"], "claimed")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM accounting_attempt_results"), 0)
        self.assertIsNone(self.c.db.one("SELECT name FROM sqlite_master WHERE name='synthetic_unreviewed_observation'"))
        self.assertEqual(self.store.effect_count, 1)

    def test_current_accountant_duty_precedes_completed_result_replay(self):
        intent, _ = self.queued_api()
        _, args = self.action("accounting.deliver", intent)
        self.c.plugin("people").deactivate_person("practice.accountant", reason="Synthetic current authority revoked", actor="practice.bootstrap")
        before = self.stored(), dict(self.adapter.calls)
        with self.assertRaises(APRefusal):
            self.runner.run(**args)
        self.assertEqual((self.stored(), dict(self.adapter.calls)), before)

    def test_deleted_audited_invocation_refuses_original_receipt_and_close(self):
        intent, _ = self.queued_api()
        completed, args = self.action("accounting.deliver", intent)
        sql = self.c.db.one("SELECT sql FROM sqlite_master WHERE name='ap_accounting_invocations_no_delete'")["sql"]
        self.c.db.conn.execute("DROP TRIGGER ap_accounting_invocations_no_delete")
        self.c.db.conn.execute("DELETE FROM ap_accounting_invocations WHERE id=?", (completed["result"]["invocationId"],))
        self.c.db.conn.execute(sql)
        before = self.stored()
        with self.assertRaises(APRefusal):
            self.runner.run(**args)
        self.assertEqual(self.stored(), before)
        self.assertTrue(self.runner.integrity_checks())

    def test_human_cannot_invoke_private_worker_without_original_reservation(self):
        intent, _ = self.queued_api()
        before = self.stored(), dict(self.adapter.calls)
        with self.assertRaises(WorkerHeld):
            self.worker.deliver_once(intent, actor="practice.accountant")
        self.assertEqual((self.stored(), dict(self.adapter.calls)), before)

    def test_copied_file_proves_original_invocations_without_initializing_worker(self):
        from apps.cipher.service import Cipher
        from apps.cipher.accounting_worker import create_practice_accounting_worker
        intent, _ = self.queued_api()
        completed, _ = self.action("accounting.deliver", intent)
        with tempfile.TemporaryDirectory(prefix="cipher-accounting-copy-") as directory:
            path = Path(directory)/"synthetic.sqlite"
            with sqlite3.connect(path) as target:
                self.c.db.conn.backup(target)
            before = path.read_bytes()
            copied = Cipher(str(path))
            try:
                self.assertTrue(copied.db.read_only)
                inventory = invocation_inventory_proof(copied.db, copied.audit)
                self.assertEqual(inventory[0]["id"], completed["result"]["invocationId"])
                self.assertEqual(copied.plugin("accounting").intent(intent)["status"], "simulated_accepted")
                copied.audit_export()
                with self.assertRaises(WorkerHeld):
                    create_practice_accounting_worker(copied)
            finally:
                copied.db.close()
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(Path(str(path)+".authority").exists())


if __name__ == "__main__":
    unittest.main()
