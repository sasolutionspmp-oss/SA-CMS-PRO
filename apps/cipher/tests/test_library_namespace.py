"""Actual same-person library/AP/AR/estimating/worker command namespaces."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.tests import test_ar_namespace as ar_tests
from apps.cipher.ap_contract import APRefusal
from apps.cipher.accounting_worker import WorkerHeld
from apps.cipher.core.api_receipts import APIActionReceipts, APIRepeatabilityConflict
from apps.cipher.core.ids import loads
from apps.cipher.domain import library
from apps.cipher.library_actions import LibraryActionRunner
from apps.cipher.library_contract import LibraryContract
from apps.cipher.library_preflight import LibraryPreflight
from apps.cipher.library_receipts import library_receipt_inventory_proof


class LibraryNamespaceTests(unittest.TestCase):
    secret = b"actual-one-person-library-AR-AP-estimating-private-key"
    state = ar_tests.ARNamespaceTests.state
    ap_request = ar_tests.ARNamespaceTests.ap_request
    commercial_request = ar_tests.ARNamespaceTests.commercial_request
    accounting_request = ar_tests.ARNamespaceTests.accounting_request
    ar_request = ar_tests.ARNamespaceTests.ar_request
    assert_conflict_without_change = ar_tests.ARNamespaceTests.assert_conflict_without_change
    remove_with_original_guards = ar_tests.ARNamespaceTests.remove_with_original_guards

    def setUp(self):
        # This composes original real people grants under the current enforcing
        # policy. It neither resets policy nor manufactures a receipt or role.
        ar_tests.ARNamespaceTests.setUp(self)
        self.library_project = self.c.create_project(name="Synthetic shared-person authored library project",
            entity="Synthetic shared entity", budget="1000", actor="practice.bootstrap")["id"]
        people = self.c.plugin("people")
        people.add_membership("practice.accountant", self.library_project, actor="practice.bootstrap")
        draft = people.request_grant("practice.accountant", "pm", project_id=self.library_project,
            reason="Synthetic same-person owned library PM assignment", actor="practice.bootstrap")
        approval = self.c.request_approval("people.grant_role", draft["id"], actor_role="owner", requested_by="practice.reviewer")
        self.c.approve(approval["id"], approver="practice.bootstrap", approver_role="owner")
        self.c.execute(approval["id"], actor="practice.bootstrap")
        self.library_contract = LibraryContract(self.c, secret=self.secret)
        self.library_preflight = LibraryPreflight(self.c, self.library_contract, secret=self.secret)
        self.library = LibraryActionRunner(self.c, self.library_contract, self.library_preflight)
        self.assertEqual(people.person_for("practice.accountant")["id"], self.person)

    def library_request(self, key=None):
        body = {"kind": "contract_clause", "title": "Synthetic shared-person clause",
            "text": "Practice-authored exact internal clause.\r\n  Preserve spaces — café.\n",
            "sourceLocator": "Practice editor / project specifications / paragraph 1"}
        review = self.library_preflight.review(self.person, "library.create", self.library_project, body)
        self.assertTrue(review["allowed"], review)
        return {"person_id": self.person, "action": "library.create", "resource_id": self.library_project,
            "body": {**body, "fingerprint": review["fingerprint"]}, "repeatability_key": key or str(uuid4()),
            "if_match": review["resourceVersion"]}

    def other_requests(self, key=None):
        return ((self.ap, self.ap_request(key)), (self.runner, self.commercial_request(key)),
                (self.ar, self.ar_request(key)))

    def test_library_original_key_blocks_ap_commercial_and_ar_and_replays_exactly(self):
        request = self.library_request()
        original = self.library.run(**request)
        for runner, args in self.other_requests(request["repeatability_key"]):
            with self.subTest(action=args["action"]):
                self.assert_conflict_without_change(runner, args)
        before = self.state()
        self.assertEqual(self.library.run(**request), {**original, "replayed": True, "effectApplied": False})
        self.assertEqual(before, self.state())

    def test_original_ap_key_blocks_library_and_replays_ap(self):
        self._other_blocks_library(self.ap, self.ap_request())

    def test_original_commercial_key_blocks_library_and_replays_commercial(self):
        self._other_blocks_library(self.runner, self.commercial_request())

    def test_original_ar_key_blocks_library_and_replays_ar(self):
        self._other_blocks_library(self.ar, self.ar_request())

    def _other_blocks_library(self, runner, request):
        original = runner.run(**request)
        self.assert_conflict_without_change(self.library, self.library_request(request["repeatability_key"]))
        before = self.state()
        self.assertEqual(runner.run(**request), {**original, "replayed": True, "effectApplied": False})
        self.assertEqual(before, self.state())

    def test_library_key_cannot_reserve_or_submit_accounting_worker(self):
        request = self.library_request()
        original = self.library.run(**request)
        worker = self.accounting_request(request["repeatability_key"])
        self.assert_conflict_without_change(self.accounting, worker)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ap_accounting_invocations"), 0)
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})
        self.assertEqual(self.worker._adapter._store.effect_count, 0)
        self.assertEqual(self.library.run(**request)["result"], original["result"])

    def test_pending_worker_reservation_blocks_library_without_provider_attempt(self):
        request = self.accounting_request()
        with patch("apps.cipher.accounting_worker.invoke_bound_worker", side_effect=WorkerHeld("Synthetic pending library namespace worker")):
            pending = self.accounting.run(**request)
        self.assertEqual(pending["state"], "reserved")
        self.assert_conflict_without_change(self.library, self.library_request(request["repeatability_key"]))
        before = self.state()
        with patch("apps.cipher.accounting_worker.invoke_bound_worker", side_effect=WorkerHeld("Synthetic pending library namespace worker")):
            self.assertEqual(self.accounting.run(**request), pending)
        self.assertEqual(before, self.state())
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})

    def test_completed_accounting_key_blocks_library_without_second_submission(self):
        request = self.accounting_request()
        original = self.accounting.run(**request)
        self.assert_conflict_without_change(self.library, self.library_request(request["repeatability_key"]))
        before = self.state(), dict(self.worker._adapter.calls), self.worker._adapter._store.effect_count
        self.assertEqual(self.accounting.run(**request)["result"], original["result"])
        self.assertEqual(before, (self.state(), dict(self.worker._adapter.calls), self.worker._adapter._store.effect_count))

    def test_deleted_pending_worker_reservation_holds_fresh_library(self):
        request = self.accounting_request()
        with patch("apps.cipher.accounting_worker.invoke_bound_worker", side_effect=WorkerHeld("Synthetic pending source")):
            self.accounting.run(**request)
        library_request = self.library_request()
        row = self.c.db.one("SELECT id FROM ap_accounting_invocations WHERE repeatability_uuid=?", (request["repeatability_key"],))
        self.remove_with_original_guards("ap_accounting_invocations", "id", row["id"])
        before = self.state()
        with self.assertRaises(APRefusal) as refusal:
            self.library.run(**library_request)
        self.assertEqual(refusal.exception.status, 500)
        self.assertEqual(before, self.state())
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})

    def test_current_worker_duty_precedes_private_library_namespace_lookup(self):
        request = self.library_request()
        self.library.run(**request)
        worker = self.accounting_request(request["repeatability_key"])
        project = self.c.bills.get(self.c.ap_practice_records["approved_bill_id"])["project_id"]
        self.c.plugin("people").end_membership("practice.accountant", project,
            reason="Synthetic accounting project reassignment", actor="practice.bootstrap")
        before = self.state()
        with patch.object(APIActionReceipts, "require_repeatability_namespace", side_effect=AssertionError("Private library key disclosed")) as metadata:
            with self.assertRaises(APRefusal) as refusal:
                self.accounting.run(**worker)
            self.assertIn(refusal.exception.status, (403, 404))
            metadata.assert_not_called()
        self.assertEqual(before, self.state())
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})

    def test_current_library_duty_precedes_original_or_private_namespace_lookup(self):
        request = self.library_request()
        self.library.run(**request)
        self.c.plugin("people").end_membership("practice.accountant", self.library_project,
            reason="Synthetic library project reassignment", actor="practice.bootstrap")
        before = self.state()
        with patch.object(APIActionReceipts, "require_repeatability_namespace", side_effect=AssertionError("Private namespace disclosed")) as metadata, \
             patch.object(self.library.receipts, "find", side_effect=AssertionError("Original receipt disclosed")) as lookup:
            with self.assertRaises(APRefusal) as refusal:
                self.library.run(**request)
            self.assertIn(refusal.exception.status, (403, 404))
            metadata.assert_not_called()
            lookup.assert_not_called()
        self.assertEqual(before, self.state())

    def test_current_other_duties_precede_lookup_of_private_library_key(self):
        request = self.library_request()
        self.library.run(**request)
        requests = self.other_requests(request["repeatability_key"])
        people = self.c.plugin("people")
        for project in (self.project, self.ar_project):
            people.end_membership("practice.accountant", project, reason="Synthetic other project reassignment", actor="practice.bootstrap")
        before = self.state()
        with patch.object(APIActionReceipts, "require_repeatability_namespace", side_effect=AssertionError("Private library key disclosed")) as metadata:
            for runner, args in requests:
                with self.subTest(action=args["action"]), self.assertRaises(APRefusal) as refusal:
                    runner.run(**args)
                self.assertIn(refusal.exception.status, (403, 404))
            metadata.assert_not_called()
        self.assertEqual(before, self.state())

    def test_namespace_proof_initializes_no_library_domain_worker_or_provider(self):
        request = self.library_request()
        self.library.run(**request)
        row = self.c.db.one("SELECT * FROM library_action_receipts WHERE repeatability_uuid=?", (request["repeatability_key"],))
        metadata = APIActionReceipts(self.c.db, self.c.audit)
        before = self.state(), self.c.db.conn.total_changes
        with patch.object(self.c, "plugin", side_effect=AssertionError("Domain fetched")), \
             patch.object(library.Plugin, "__init__", side_effect=AssertionError("Library initialized")), \
             patch("apps.cipher.accounting_worker.create_practice_accounting_worker", side_effect=AssertionError("Worker initialized")), \
             patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Provider initialized")):
            self.assertIsNone(metadata.require_repeatability_namespace(self.person, request["repeatability_key"], "library.create", loads(row["binding_json"])))
            self.assertIsNone(metadata.require_repeatability_namespace(self.person, str(uuid4()), "bill.requestApproval", {}))
            with self.assertRaises(APIRepeatabilityConflict):
                metadata.require_repeatability_namespace(self.person, request["repeatability_key"], "bill.requestApproval", {})
            self.assertEqual(len(library_receipt_inventory_proof(self.c.db, self.c.audit)), 1)
        self.assertEqual(before, (self.state(), self.c.db.conn.total_changes))

    def _others_held(self, args):
        before = self.state()
        for runner, request in args:
            with self.subTest(action=request["action"]):
                with self.assertRaises(APRefusal) as refusal:
                    runner.run(**request)
                self.assertEqual(refusal.exception.status, 500)
        self.assertEqual(before, self.state())

    def test_deleted_original_library_receipt_holds_fresh_other_actions(self):
        original = self.library.run(**self.library_request())
        args = self.other_requests()
        self.remove_with_original_guards("library_action_receipts", "id", original["receiptId"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        self._others_held(args)

    def test_deleted_library_birth_holds_others_even_with_valid_truncated_audit(self):
        original = self.library.run(**self.library_request())
        args = self.other_requests()
        last = self.c.db.one("SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1")
        self.assertEqual(last["entity_id"], original["receiptId"])
        self.remove_with_original_guards("audit_log", "seq", last["seq"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        self._others_held(args)

    def test_missing_library_receipt_admission_holds_other_actions_without_writes(self):
        self.library.run(**self.library_request())
        args = self.other_requests()
        self.c.db.execute("DELETE FROM schema_version WHERE name='library_practice_action_receipts'")
        self._others_held(args)

    def test_original_library_birth_alone_prevents_legacy_namespace_fallback(self):
        self.library.run(**self.library_request())
        args = self.other_requests()
        with self.c.db.transaction():
            self.c.db.execute("DROP TABLE library_action_receipts")
            self.c.db.execute("DELETE FROM schema_version WHERE name='library_practice_action_receipts'")
        self._others_held(args)

    def test_same_uuid_belongs_to_each_canonical_person_separately(self):
        request = self.library_request()
        first = self.library.run(**request)
        people = self.c.plugin("people")
        people.add_membership("practice.reviewer", self.library_project, actor="practice.bootstrap")
        draft = people.request_grant("practice.reviewer", "pm", project_id=self.library_project,
            reason="Synthetic independent second library person", actor="practice.bootstrap")
        grant = self.c.request_approval("people.grant_role", draft["id"], actor_role="owner", requested_by="practice.accountant")
        self.c.approve(grant["id"], approver="practice.bootstrap", approver_role="owner")
        self.c.execute(grant["id"], actor="practice.bootstrap")
        person = people.person_for("practice.reviewer")["id"]
        body = {key: value for key, value in request["body"].items() if key != "fingerprint"}
        review = self.library_preflight.review(person, "library.create", self.library_project, body)
        self.assertTrue(review["allowed"], review)
        second_request = {**request, "person_id": person, "body": {**body, "fingerprint": review["fingerprint"]}, "if_match": review["resourceVersion"]}
        second = self.library.run(**second_request)
        self.assertNotEqual(first["receiptId"], second["receiptId"])
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM library_action_receipts WHERE repeatability_uuid=?", (request["repeatability_key"],)), 2)
        before = self.state()
        self.assertEqual(self.library.run(**request), {**first, "replayed": True, "effectApplied": False})
        self.assertEqual(self.library.run(**second_request), {**second, "replayed": True, "effectApplied": False})
        self.assertEqual(before, self.state())

    def test_deleted_original_ap_receipt_holds_fresh_library(self):
        self._deleted_other_holds_library(self.ap, self.ap_request(), "ap_action_receipts")

    def test_deleted_original_commercial_receipt_holds_fresh_library(self):
        self._deleted_other_holds_library(self.runner, self.commercial_request(), "commercial_action_receipts")

    def test_deleted_original_ar_receipt_holds_fresh_library(self):
        self._deleted_other_holds_library(self.ar, self.ar_request(), "ar_action_receipts")

    def _deleted_other_holds_library(self, runner, request, table):
        original = runner.run(**request)
        library_request = self.library_request()
        self.remove_with_original_guards(table, "id", original["receiptId"])
        before = self.state()
        with self.assertRaises(APRefusal) as refusal:
            self.library.run(**library_request)
        self.assertEqual(refusal.exception.status, 500)
        self.assertEqual(before, self.state())

    def test_nested_ap_key_claim_during_library_create_rolls_back_both_effects(self):
        request = self.library_request()
        nested = self.ap_request(request["repeatability_key"])
        create = self.c.plugin("library").create
        observed = []
        def claimed(*args, **kwargs):
            observed.append(self.ap.run(**nested))
            return create(*args, **kwargs)
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.plugin("library"), "create", side_effect=claimed), self.assertRaises(APRefusal) as refusal:
                self.library.run(**request)
            self.assertEqual(refusal.exception.status, 409)
            self.assertEqual(len(observed), 1)
            self.assertTrue(observed[0]["effectApplied"])
            self.assertEqual(before, self.state())
        self.assertTrue(self.library.run(**request)["effectApplied"])
        self.assert_conflict_without_change(self.ap, nested)

    def test_nested_library_key_claim_during_ap_request_rolls_back_both_effects(self):
        request = self.ap_request()
        nested = self.library_request(request["repeatability_key"])
        original = self.c.request_approval
        observed = []
        def claimed(operation, *args, **kwargs):
            if operation == "bill.approve":
                observed.append(self.library.run(**nested))
            return original(operation, *args, **kwargs)
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c, "request_approval", side_effect=claimed), self.assertRaises(APRefusal) as refusal:
                self.ap.run(**request)
            self.assertEqual(refusal.exception.status, 409)
            self.assertEqual(len(observed), 1)
            self.assertTrue(observed[0]["effectApplied"])
            self.assertEqual(before, self.state())
        self.assertTrue(self.ap.run(**request)["effectApplied"])
        self.assert_conflict_without_change(self.library, nested)


if __name__ == "__main__":
    unittest.main()
