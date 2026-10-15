"""One actual person's reviewed UUID cannot cross commercial and AP actions."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.ap_actions import APActionRunner
from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_preflight import APPreflight
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_exception_contract import APExceptionContract
from apps.cipher.ap_accounting_actions import APAccountingActionRunner
from apps.cipher.ap_accounting_contract import APAccountingContract
from apps.cipher.ap_accounting_preflight import APAccountingPreflight
from apps.cipher.ap_practice_fixture import make_ap_practice_fixture
from apps.cipher.accounting_worker import WorkerHeld, create_practice_accounting_worker
from apps.cipher.commercial_actions import CommercialActionRunner
from apps.cipher.commercial_contract import CommercialContract
from apps.cipher.commercial_preflight import CommercialPreflight
from apps.cipher.core.api_receipts import APIActionReceipts, APIRepeatabilityConflict
from apps.cipher.core.ids import loads
from apps.cipher.domain import commercial


class CommercialNamespaceTests(unittest.TestCase):
    secret = b"shared-person-commercial-AP-namespace-private-key"

    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        if "commercial" not in self.c._plugins:
            self.c.register_plugin("commercial", commercial.Plugin(self.c))
        self.person = self.c.ap_practice_persona_people["accountant"]["person_id"]
        self.bill = self.c.ap_practice_records["draft_bill_id"]
        self.project = self.c.bills.get(self.bill)["project_id"]
        people = self.c.plugin("people")
        grant = people.request_grant("practice.accountant", "estimator", project_id=self.project,
                                     reason="Synthetic same-person commercial/AP composition", actor="practice.bootstrap")
        approval = self.c.request_approval("people.grant_role", grant["id"], actor_role="owner", requested_by="practice.reviewer")
        self.c.approve(approval["id"], approver="practice.bootstrap", approver_role="owner")
        self.c.execute(approval["id"], actor="practice.bootstrap")
        document = self.c.evidence.register_document(project_id=self.project, kind="drawing",
            title="Synthetic mixed-workspace manual source", actor="practice.accountant")
        drawing = self.c.evidence.add_revision(document_id=document["id"], content="Synthetic manual source 11LF",
            note="Manual quantity only; geometry unverified", actor="practice.accountant")
        self.input = {"documentRevisionId": drawing["id"], "lines": [{"description": "Manual namespace proof",
            "quantity": "11", "unit": "LF", "unitPriceCents": 2500, "sourceLocator": "A-101 / manual run1", "costCode": "33-110"}],
            "priceBookRef": "Synthetic fixed rate", "inclusions": ["Manual installation"], "exclusions": [],
            "contingencyRate": "0", "measurementBasis": "Manual quantity; geometry unverified"}
        self.ap_contract = APContract(self.c, secret=self.secret)
        self.ap_preflight = APPreflight(self.c, self.ap_contract, secret=self.secret)
        self.ap = APActionRunner(self.c, self.ap_contract, self.ap_preflight)
        self.contract = CommercialContract(self.c, secret=self.secret)
        self.preflight = CommercialPreflight(self.c, self.contract, secret=self.secret)
        self.runner = CommercialActionRunner(self.c, self.contract, self.preflight)
        # Both duties are original audited project grants owned by this canonical
        # human. No supplied-role, wildcard, alias or delegated authority is used.
        roles = [row["role"] for row in people._live_grants(self.person, people._today()) if row["project_id"] == self.project]
        self.assertIn("accountant", roles)
        self.assertIn("estimator", roles)

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def commercial_request(self, key=None):
        reviewed = self.preflight.review(self.person, "estimate.create", self.project, self.input)
        self.assertTrue(reviewed["allowed"], reviewed)
        return {"person_id": self.person, "action": "estimate.create", "resource_id": self.project,
                "body": {**self.input, "fingerprint": reviewed["fingerprint"]},
                "repeatability_key": key or str(uuid4()), "if_match": reviewed["resourceVersion"]}

    def ap_request(self, key=None):
        reviewed = self.ap_preflight.review(self.person, "bill.requestApproval", self.bill, {})
        self.assertTrue(reviewed["allowed"], reviewed)
        return {"person_id": self.person, "action": "bill.requestApproval", "resource_id": self.bill,
                "body": {"fingerprint": reviewed["fingerprint"]}, "repeatability_key": key or str(uuid4()),
                "if_match": reviewed["resourceVersion"]}

    def accounting_request(self, key=None):
        bill = self.c.ap_practice_records["approved_bill_id"]
        self.c.post_bill(bill, actor="practice.accountant", period_id="2026-10", reason="Synthetic namespace source")
        domain = self.c.plugin("accounting")
        mapping = domain.prepare_synthetic_mapping(self.c.bills.get(bill)["project_id"], actor="practice.accountant",
                                                    reason="Synthetic namespace mapping")
        plan = domain.prepare(bill, mapping["id"], actor="practice.accountant")
        approval = self.c.request_approval("accounting.queue", plan["id"], actor_role="accountant", requested_by="practice.accountant")
        self.c.approve(approval["id"], approver="practice.reviewer", approver_role="accountant")
        intent = self.c.execute(approval["id"], actor="practice.accountant").result["intent_id"]
        self.worker = create_practice_accounting_worker(self.c)
        intake = APIntakeContract(self.c, self.ap_contract, secret=self.secret)
        exceptions = APExceptionContract(self.c, self.ap_contract, intake, secret=self.secret)
        contract = APAccountingContract(self.c, self.ap_contract, intake, exceptions, secret=self.secret, worker=self.worker)
        preflight = APAccountingPreflight(self.c, contract, secret=self.secret, worker=self.worker)
        self.accounting = APAccountingActionRunner(self.c, contract, preflight, worker=self.worker)
        review = preflight.review(self.person, "accounting.deliver", intent, {})
        self.assertTrue(review["allowed"], review)
        return {"person_id": self.person, "action": "accounting.deliver", "resource_id": intent,
                "body": {"fingerprint": review["fingerprint"]}, "repeatability_key": key or str(uuid4()),
                "if_match": review["resourceVersion"]}

    def assert_conflict_without_change(self, runner, args):
        before = self.state()
        with self.assertRaises(APRefusal) as refusal:
            runner.run(**args)
        self.assertEqual(refusal.exception.status, 409)
        self.assertEqual(refusal.exception.code, "repeatability_conflict")
        self.assertEqual(self.state(), before)

    def test_commercial_receipt_key_cannot_be_taken_by_actual_ap_action(self):
        request = self.commercial_request()
        original = self.runner.run(**request)
        self.assert_conflict_without_change(self.ap, self.ap_request(request["repeatability_key"]))
        before = self.state()
        self.assertEqual(self.runner.run(**request), {**original, "replayed": True, "effectApplied": False})
        self.assertEqual(self.state(), before)

    def test_commercial_receipt_key_cannot_reserve_or_submit_worker_invocation(self):
        request = self.commercial_request()
        original = self.runner.run(**request)
        args = self.accounting_request(request["repeatability_key"])
        self.assert_conflict_without_change(self.accounting, args)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM ap_accounting_invocations"), 0)
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})
        self.assertEqual(self.worker._adapter._store.effect_count, 0)
        self.assertEqual(self.runner.run(**request)["result"], original["result"])

    def test_actual_ap_receipt_blocks_commercial_key_and_retains_exact_ap_replay(self):
        request = self.ap_request()
        original = self.ap.run(**request)
        self.assert_conflict_without_change(self.runner, self.commercial_request(request["repeatability_key"]))
        before = self.state()
        self.assertEqual(self.ap.run(**request), {**original, "replayed": True, "effectApplied": False})
        self.assertEqual(self.state(), before)

    def test_actual_unfinished_worker_reservation_blocks_commercial_and_replays_same_key(self):
        request = self.accounting_request()
        with patch("apps.cipher.accounting_worker.invoke_bound_worker", side_effect=WorkerHeld("Synthetic temporarily held worker")):
            pending = self.accounting.run(**request)
        self.assertEqual(pending["state"], "reserved")
        self.assert_conflict_without_change(self.runner, self.commercial_request(request["repeatability_key"]))
        before = self.state()
        with patch("apps.cipher.accounting_worker.invoke_bound_worker", side_effect=WorkerHeld("Synthetic temporarily held worker")):
            self.assertEqual(self.accounting.run(**request), pending)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})

    def test_current_project_duties_precede_both_domain_namespace_disclosures(self):
        commercial_request = self.commercial_request()
        self.runner.run(**commercial_request)
        ap_request = self.ap_request(commercial_request["repeatability_key"])
        accounting_request = self.accounting_request(commercial_request["repeatability_key"])
        people = self.c.plugin("people")
        people.end_membership("practice.accountant", self.project, reason="Synthetic first project departure", actor="practice.bootstrap")
        second = self.c.bills.get(self.c.ap_practice_records["approved_bill_id"])["project_id"]
        people.end_membership("practice.accountant", second, reason="Synthetic second project departure", actor="practice.bootstrap")
        before = self.state()
        with patch.object(APIActionReceipts, "require_repeatability_namespace", side_effect=AssertionError("Private cross-domain history disclosed")) as lookup:
            for runner, args in ((self.ap, ap_request), (self.runner, commercial_request), (self.accounting, accounting_request)):
                with self.subTest(action=args["action"]), self.assertRaises(APRefusal) as refusal:
                    runner.run(**args)
                self.assertIn(refusal.exception.status, (403, 404))
            lookup.assert_not_called()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.worker._adapter.calls, {"submit": 0, "lookup": 0, "read_record": 0})

    def remove_with_original_guards(self, table, key, value):
        with self.c.db.transaction():
            triggers = self.c.db.query("SELECT sql,name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
            for trigger in triggers:
                self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
            self.c.db.execute(f"DELETE FROM {table} WHERE {key}=?", (value,))
            for trigger in triggers:
                self.c.db.execute(trigger["sql"])

    def test_deleted_commercial_receipt_row_refuses_fresh_ap_action(self):
        original = self.runner.run(**self.commercial_request())
        args = self.ap_request()
        self.remove_with_original_guards("commercial_action_receipts", "id", original["receiptId"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        before = self.state()
        with self.assertRaises(APRefusal) as refusal:
            self.ap.run(**args)
        self.assertEqual(refusal.exception.status, 500)
        self.assertEqual(self.state(), before)

    def test_deleted_last_commercial_birth_refuses_fresh_ap_with_intact_audit_chain(self):
        original = self.runner.run(**self.commercial_request())
        args = self.ap_request()
        last = self.c.db.one("SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1")
        self.assertEqual(last["entity_id"], original["receiptId"])
        self.remove_with_original_guards("audit_log", "seq", last["seq"])
        # A truncated valid chain alone cannot prove the surviving receipt birth.
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        before = self.state()
        with self.assertRaises(APRefusal) as refusal:
            self.ap.run(**args)
        self.assertEqual(refusal.exception.status, 500)
        self.assertEqual(self.state(), before)

    def test_shared_namespace_proof_reads_metadata_without_domain_worker_or_provider(self):
        request = self.commercial_request()
        self.runner.run(**request)
        receipt = self.c.db.one("SELECT * FROM commercial_action_receipts WHERE repeatability_uuid=?", (request["repeatability_key"],))
        before = self.state(), self.c.db.conn.total_changes
        metadata = APIActionReceipts(self.c.db, self.c.audit)
        with patch.object(self.c, "plugin", side_effect=AssertionError("Domain initialized or fetched")), \
             patch.object(commercial.Plugin, "__init__", side_effect=AssertionError("Commercial domain initialized")), \
             patch("apps.cipher.accounting_worker.create_practice_accounting_worker", side_effect=AssertionError("Worker initialized")), \
             patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Provider initialized")):
            self.assertIsNone(metadata.require_repeatability_namespace(self.person, request["repeatability_key"], "estimate.create", loads(receipt["binding_json"])))
            self.assertIsNone(metadata.require_repeatability_namespace(self.person, str(uuid4()), "bill.requestApproval", {}))
            with self.assertRaises(APIRepeatabilityConflict):
                metadata.require_repeatability_namespace(self.person, request["repeatability_key"], "bill.requestApproval", {})
        self.assertEqual((self.state(), self.c.db.conn.total_changes), before)


if __name__ == "__main__":
    unittest.main()
