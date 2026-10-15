"""Independent regressions for truthful accounting results and command provenance."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_accounting_actions import APAccountingActionRunner
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.api_receipts import APIReceiptIntegrityError
from apps.cipher.core.ids import loads
from apps.cipher.tests.test_ap_accounting_contract import AccountingWorld


class APAccountingIndependentReviewTests(AccountingWorld, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.runner = APAccountingActionRunner(self.c, self.contract, self.preflight, worker=self.worker)

    def reviewed(self, action, resource, *, person=None):
        person = person or self.person
        review = self.preflight.review(person, action, resource, {})
        self.assertTrue(review["allowed"], review)
        return {"person_id": person, "action": action, "resource_id": resource,
                "body": {"fingerprint": review["fingerprint"]}, "repeatability_key": str(uuid4()),
                "if_match": review["resourceVersion"]}

    def test_same_source_cannot_record_false_quickbooks_or_journal_result(self):
        self.domain.prepare_synthetic_mapping(self.plan["project_id"], actor="practice.accountant", reason="Synthetic next mapping version")
        args = self.reviewed("accounting.prepare", self.bill_id)
        before = self.snapshot()
        original = self.runner._human_act

        def misreport(*values):
            result, source = original(*values)
            return {**result, "quickBooksAccepted": True, "journalCountDelta": 1}, source

        with patch.object(self.runner, "_human_act", side_effect=misreport):
            with self.assertRaises(APRefusal):
                self.runner.run(**args)
        after = self.snapshot()
        # SQLite total_changes counts writes subsequently undone by a savepoint.
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[2:], before[2:])

    def test_exact_queue_retry_refuses_changed_original_command_payload_hash(self):
        request = self.runner.run(**self.reviewed("accounting.request", self.plan["id"]))
        approval_id = request["result"]["approvalId"]
        self.runner.run(**self.reviewed("accounting.approve", approval_id, person=self.reviewer))
        args = self.reviewed("accounting.queue", approval_id)
        receipt = self.runner.run(**args)
        source = loads(self.c.db.one("SELECT source_json FROM ap_action_receipts WHERE id=?", (receipt["receiptId"],))["source_json"])
        self.c.db.conn.execute("UPDATE idempotency SET payload_hash=? WHERE op_id=?", ("altered-original-command-payload", source["commandId"]))
        before = self.snapshot()
        with self.assertRaises(APRefusal):
            self.runner.run(**args)
        self.assertEqual(self.snapshot(), before)

    def test_original_outcome_requires_exact_json_number_and_boolean_types(self):
        self.domain.prepare_synthetic_mapping(self.plan["project_id"], actor="practice.accountant", reason="Synthetic exact outcome type review")
        args = self.reviewed("accounting.prepare", self.bill_id)
        original = self.runner._human_act
        for field, value in (("journalCountDelta", 0.0), ("apBalanceDeltaCents", False),
                             ("quickBooksAccepted", 0), ("simulation", 1)):
            with self.subTest(field=field, value=value):
                before = self.snapshot()

                def misreport(*values):
                    result, source = original(*values)
                    return {**result, field: value}, source

                with patch.object(self.runner, "_human_act", side_effect=misreport):
                    with self.assertRaises(APRefusal):
                        self.runner.run(**args)
                after = self.snapshot()
                self.assertEqual(after[0], before[0])
                self.assertEqual(after[2:], before[2:])
        outcome = self.runner.run(**args)
        self.assertIs(type(outcome["result"]["journalCountDelta"]), int)
        self.assertIs(type(outcome["result"]["apBalanceDeltaCents"]), int)
        self.assertIs(outcome["result"]["quickBooksAccepted"], False)
        self.assertIs(outcome["result"]["simulation"], True)

    def test_core_receipt_cannot_take_a_pending_worker_invocation_key(self):
        intent_id = self.queue()
        args = self.reviewed("accounting.deliver", intent_id)
        key, binding = self.runner._shape(args["action"], intent_id, args["body"], args["repeatability_key"], args["if_match"])
        checked = self.preflight.verify(self.person, args["action"], intent_id, args["body"], args["if_match"])
        with self.c.db.transaction():
            self.runner.invocations.reserve(person_id=self.person, actor_login="practice.accountant", action=args["action"],
                intent_id=intent_id, repeatability_uuid=key, binding=binding, reviewed_source=checked["plan"])
        before = self.snapshot()
        with self.c.db.transaction():
            with self.assertRaises(APIReceiptIntegrityError):
                self.runner.receipts.record(person_id=self.person, actor_login="practice.accountant", repeatability_uuid=key,
                    contract_version="cipher.ap-practice.v1", action="bill.requestApproval", resource_id=self.bill_id,
                    binding={}, outcome="success", http_status=200, result={}, source={})
        self.assertEqual(self.snapshot(), before)

    def test_original_grant_and_queue_event_references_require_integer_sequences(self):
        request = self.runner.run(**self.reviewed("accounting.request", self.plan["id"]))
        approval_id = request["result"]["approvalId"]
        original = self.runner._human_act
        for action, field, person in (("accounting.approve", "event", self.reviewer),
                                      ("accounting.queue", "birth", self.person)):
            with self.subTest(action=action):
                args = self.reviewed(action, approval_id, person=person)
                before = self.snapshot()

                def misreport(*values):
                    result, source = original(*values)
                    return result, {**source, field: {**source[field], "seq": float(source[field]["seq"])}}

                with patch.object(self.runner, "_human_act", side_effect=misreport):
                    with self.assertRaises(APRefusal):
                        self.runner.run(**args)
                after = self.snapshot()
                self.assertEqual(after[0], before[0])
                self.assertEqual(after[2:], before[2:])
                outcome = self.runner.run(**args)
                receipt = self.runner.receipts.find(person, args["repeatability_key"])
                self.assertIs(type(loads(receipt["source_json"])[field]["seq"]), int)
                self.assertEqual(outcome["result"]["status"], "granted" if action == "accounting.approve" else "queued")


if __name__ == "__main__":
    unittest.main()
