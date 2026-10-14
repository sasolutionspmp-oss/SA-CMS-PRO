"""Actual HTTP synthetic accounting handoff and separate worker invocations."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest
from unittest.mock import patch
import uuid

import apps.cipher.tests.test_ap_exception_http as fixtures
import apps.cipher.accounting_worker as worker_module
from apps.cipher.accounting_simulator import Fault


class APAccountingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.APExceptionHTTPTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        self.server = self.fx.server
        self.c = self.server.cipher
        self.accountant, self.reviewer, self.pm = self.fx.accountant, self.fx.reviewer, self.fx.pm
        self.records = self.fx.records

    def snapshot(self):
        return (self.fx.snapshot(), self.server.accounting_store.effect_count, dict(self.server.accounting_adapter.calls))

    def preflight(self, route, headers):
        before = self.snapshot()
        status, _, review = self.fx.request(route + ":preflight", method="POST", headers=headers, body="{}")
        self.assertEqual(status, 200, review)
        self.assertEqual(self.snapshot(), before)
        return review

    def reviewed_request(self, route, headers):
        review = self.preflight(route, headers)
        self.assertTrue(review["allowed"], review)
        return ({**headers, "If-Match": '"' + review["resourceVersion"] + '"', "Repeatability-Request-ID": str(uuid.uuid4())},
                json.dumps({"fingerprint": review["fingerprint"]}))

    def action(self, route, headers, *, replay=True):
        request_headers, body = self.reviewed_request(route, headers)
        status, _, result = self.fx.request(route, method="POST", headers=request_headers, body=body)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["replayed"], result)
        self.assertTrue(result["effectApplied"], result)
        if replay:
            before = self.snapshot()
            status, _, repeated = self.fx.request(route, method="POST", headers=request_headers, body=body)
            self.assertEqual(status, 200, repeated)
            self.assertTrue(repeated["replayed"])
            self.assertFalse(repeated["effectApplied"])
            self.assertEqual(repeated["receiptId"], result["receiptId"])
            self.assertEqual(repeated["result"], result["result"])
            self.assertEqual(self.snapshot(), before)
        return result, request_headers, body

    def posted_bill(self):
        bill_id = self.records["approved_bill_id"]
        self.fx.action("bills/" + bill_id + "/post", self.accountant, {"periodId": "2026-10", "reason": ""})
        return bill_id

    def queued(self):
        bill_id = self.posted_bill()
        prepared, _, _ = self.action("bills/" + bill_id + "/prepare-accounting", self.accountant)
        plan_id = prepared["result"]["planId"]
        requested, _, _ = self.action("accounting-plans/" + plan_id + "/request-approval", self.accountant)
        approval_id = requested["result"]["approvalId"]
        self.action("accounting-approvals/" + approval_id + "/approve", self.reviewer)
        queued, _, _ = self.action("accounting-approvals/" + approval_id + "/queue", self.accountant)
        return bill_id, plan_id, approval_id, queued["result"]["intentId"]

    def test_owned_factory_declares_one_mapping_per_entity_and_no_selectors(self):
        domain = self.c.plugin("accounting")
        mappings = [domain.current_mapping(project, actor="practice.accountant") for project in self.records["visible_project_ids"]]
        self.assertEqual(mappings[0]["id"], mappings[1]["id"])
        self.assertEqual(mappings[0]["version"], 1)
        self.assertEqual(self.server.accounting_store.effect_count, 0)
        self.assertEqual(self.server.accounting_adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})
        from apps.cipher.ap_practice_server import make_ap_practice_server
        for key, value in (("provider", object()), ("worker", object()), ("accounting_store", object()),
                           ("mapping", {}), ("realm", "realm"), ("date", "2026-10-01")):
            with self.assertRaises(TypeError):
                make_ap_practice_server(port=0, **{key: value})

    def test_complete_handoff_delivery_and_readback_preserve_working_ledger_and_payment(self):
        bill_id, plan_id, approval_id, intent_id = self.queued()
        journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        payable = str(self.c.bills.open_payable(bill_id))
        for route in ("bills/" + bill_id + "/accounting-preparation", "accounting-plans/" + plan_id + "/review",
                      "accounting-approvals/" + approval_id + "/packet", "accounting-intents/" + intent_id + "/review"):
            status, headers, value = self.fx.request(route, headers=self.accountant)
            self.assertEqual(status, 200, value)
            self.assertEqual(headers["ETag"], '"' + value["version"] + '"')
            self.assertFalse(value.get("quickBooksAccepted", False))
        delivered, _, _ = self.action("accounting-intents/" + intent_id + "/deliver", self.accountant)
        self.assertEqual(delivered["result"]["status"], "simulated_accepted")
        self.assertFalse(delivered["result"]["quickBooksAccepted"])
        self.assertEqual(self.server.accounting_store.effect_count, 1)
        reconciled, _, _ = self.action("accounting-intents/" + intent_id + "/reconcile", self.accountant)
        self.assertEqual(reconciled["result"]["status"], "reconciled")
        self.assertFalse(reconciled["result"]["quickBooksAccepted"])
        self.assertEqual(self.server.accounting_adapter.calls, {"submit": 1, "lookup": 0, "read_record": 1})
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.assertEqual(str(self.c.bills.open_payable(bill_id)), payable)
        self.assertFalse(self.c.provider.submissions)
        self.assertFalse(self.c.provider.transfers)
        status, _, inv = self.fx.request("accounting-invocations/" + delivered["result"]["invocationId"], headers=self.accountant)
        self.assertEqual(status, 200, inv)
        self.assertEqual(inv["receiptId"], delivered["receiptId"])
        self.assertTrue(inv["replayed"])

    def test_unknown_after_acceptance_is_recovered_by_lookup_without_second_submit(self):
        _, _, _, intent_id = self.queued()
        route = "accounting-intents/" + intent_id + "/deliver"
        self.server.accounting_adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        unknown, original_headers, original_body = self.action(route, self.accountant)
        self.assertEqual(unknown["result"]["status"], "outcome_unknown")
        self.assertEqual(self.server.accounting_store.effect_count, 1)
        looked_up, _, _ = self.action("accounting-intents/" + intent_id + "/lookup", self.accountant)
        self.assertEqual(looked_up["result"]["status"], "simulated_accepted")
        self.action("accounting-intents/" + intent_id + "/reconcile", self.accountant)
        before = self.snapshot()
        status, _, replay = self.fx.request(route, method="POST", headers=original_headers, body=original_body)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["result"], unknown["result"])
        self.assertEqual(replay["result"]["status"], "outcome_unknown")
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.server.accounting_adapter.calls, {"submit": 1, "lookup": 1, "read_record": 1})

    def test_worker_call_has_no_sql_transaction_or_http_lock(self):
        _, _, _, intent_id = self.queued()
        route = "accounting-intents/" + intent_id + "/deliver"
        headers, body = self.reviewed_request(route, self.accountant)
        entered, released = threading.Event(), threading.Event()
        transaction_states = []
        original = worker_module.invoke_simulator

        def paused_call(adapter, operation, *args):
            self.assertIs(adapter, self.server.accounting_adapter)
            self.assertEqual(operation, "submit")
            transaction_states.append(self.c.db.conn.in_transaction)
            entered.set()
            if not released.wait(5):
                raise RuntimeError("Test release was not received")
            return original(adapter, operation, *args)

        with patch.object(worker_module, "invoke_simulator", side_effect=paused_call):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(self.fx.request, route, method="POST", headers=headers, body=body)
                self.assertTrue(entered.wait(5))
                try:
                    self.assertFalse(transaction_states[0])
                    acquired = self.server.cipher_lock.acquire(blocking=False)
                    self.assertTrue(acquired, "The worker call must not retain the HTTP application's lock.")
                    if acquired:
                        self.server.cipher_lock.release()
                finally:
                    released.set()
                status, _, result = future.result(timeout=5)
                self.assertEqual(status, 200, result)
        self.assertEqual(self.server.accounting_store.effect_count, 1)

    def test_confirmed_missing_lookup_never_submits_and_fresh_delivery_keeps_original_uuid(self):
        _, _, _, intent_id = self.queued()
        self.server.accounting_adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
        unknown, _, _ = self.action("accounting-intents/" + intent_id + "/deliver", self.accountant)
        self.assertEqual(unknown["result"]["status"], "outcome_unknown")
        self.assertEqual(self.server.accounting_store.effect_count, 0)
        looked_up, _, _ = self.action("accounting-intents/" + intent_id + "/lookup", self.accountant)
        self.assertEqual(looked_up["result"]["status"], "confirmed_missing")
        status, _, current = self.fx.request("accounting-intents/" + intent_id + "/review", headers=self.accountant)
        self.assertEqual(status, 200, current)
        self.assertEqual(current["intent"]["status"], "queued")
        self.assertEqual(self.server.accounting_store.effect_count, 0)
        self.assertEqual(self.server.accounting_adapter.calls, {"submit": 1, "lookup": 1, "read_record": 0})
        delivered, _, _ = self.action("accounting-intents/" + intent_id + "/deliver", self.accountant)
        self.assertEqual(delivered["result"]["status"], "simulated_accepted")
        self.assertEqual(delivered["result"]["logicalOperationId"], unknown["result"]["logicalOperationId"])
        self.assertEqual(self.server.accounting_store.effect_count, 1)

    def test_concurrent_same_worker_request_has_one_effect_and_owned_pending_status(self):
        _, _, _, intent_id = self.queued()
        route = "accounting-intents/" + intent_id + "/deliver"
        headers, body = self.reviewed_request(route, self.accountant)
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: self.fx.request(route, method="POST", headers=headers, body=body), range(4)))
        self.assertTrue(all(status in (200, 202) for status, _, _ in outcomes), outcomes)
        completed = [value for status, _, value in outcomes if status == 200]
        self.assertTrue(completed, outcomes)
        self.assertEqual(len({value["receiptId"] for value in completed}), 1)
        self.assertEqual(self.server.accounting_store.effect_count, 1)
        self.assertEqual(self.server.accounting_adapter.calls["submit"], 1)
        pending = [value for status, _, value in outcomes if status == 202]
        for value in pending:
            self.assertNotIn("receiptId", value)
            self.assertFalse(value["effectApplied"])
            self.assertTrue(value["retrySameRequest"])
            status, _, current = self.fx.request("accounting-invocations/" + value["invocationId"], headers=self.accountant)
            self.assertEqual(status, 200, current)
            self.assertEqual(current["receiptId"], completed[0]["receiptId"])

    def test_hidden_reads_current_duties_and_other_person_invocation_are_refused(self):
        bill_id, plan_id, _, intent_id = self.queued()
        delivered, _, _ = self.action("accounting-intents/" + intent_id + "/deliver", self.accountant)
        invocation = delivered["result"]["invocationId"]
        before = self.snapshot()
        for collection in ("accounting-plans", "accounting-approvals", "accounting-intents"):
            status, _, value = self.fx.request(collection, headers=self.accountant)
            self.assertEqual(status, 200, value)
            self.assertNotIn(self.records["hidden_project_id"], json.dumps(value))
            self.assertEqual(self.fx.request(collection + "?projectId=" + self.records["hidden_project_id"], headers=self.accountant)[0], 404)
        self.assertEqual(self.fx.request("bills/" + self.records["hidden_bill_id"] + "/accounting-preparation", headers=self.accountant)[0], 404)
        self.assertEqual(self.fx.request("accounting-invocations/" + invocation, headers=self.reviewer)[0], 404)
        self.assertEqual(self.fx.request("accounting-plans/unreadable/review", headers=self.accountant)[0], 404)
        for route in ("bills/" + bill_id + "/prepare-accounting", "accounting-plans/" + plan_id + "/request-approval",
                      "accounting-intents/" + intent_id + "/reconcile"):
            self.assertEqual(self.fx.request(route + ":preflight", method="POST", headers=self.pm, body="{}")[0], 403)
        self.assertEqual(self.snapshot(), before)

    def test_all_seven_commands_reject_actor_provider_mapping_date_and_worker_forgery(self):
        routes = ("bills/unreadable/prepare-accounting", "accounting-plans/unreadable/request-approval",
                  "accounting-approvals/unreadable/approve", "accounting-approvals/unreadable/queue",
                  "accounting-intents/unreadable/deliver", "accounting-intents/unreadable/lookup",
                  "accounting-intents/unreadable/reconcile")
        before = self.snapshot()
        for route in routes:
            for selector in ("actor", "role", "personId", "provider", "worker", "phase", "leaseToken", "mappingId", "realmId", "datePolicy", "periodId"):
                status, _, refusal = self.fx.request(route + ":preflight", method="POST", headers=self.accountant,
                                                      body=json.dumps({selector: "forged"}))
                self.assertEqual(status, 422, (route, refusal))
            for malformed in ({"If-Match": "unquoted", "Repeatability-Request-ID": str(uuid.uuid4())},
                              {"If-Match": '"version"', "Repeatability-Request-ID": "bad-key"}):
                self.assertEqual(self.fx.request(route, method="POST", headers={**self.accountant, **malformed},
                                                body='{"fingerprint":"unreviewed"}')[0], 422)
        self.assertEqual(self.snapshot(), before)

    def test_stale_record_or_review_has_no_domain_or_simulator_effect(self):
        bill_id = self.posted_bill()
        route = "bills/" + bill_id + "/prepare-accounting"
        review = self.preflight(route, self.accountant)
        self.assertTrue(review["allowed"], review)
        before = self.snapshot()
        for version, fingerprint in (("stale-version", review["fingerprint"]), (review["resourceVersion"], "changed-fingerprint")):
            headers = {**self.accountant, "If-Match": '"' + version + '"', "Repeatability-Request-ID": str(uuid.uuid4())}
            status, _, refused = self.fx.request(route, method="POST", headers=headers, body=json.dumps({"fingerprint": fingerprint}))
            self.assertEqual(status, 412, refused)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
