"""Admission is proved separately from real native original-outcome evidence.

These regression cases create genuine current actions first, then remove/change
only the migration admission. No receipt, checksum history or outcome is forged.
"""
import copy
import unittest
from uuid import uuid4

from apps.cipher.ap_contract import APRefusal
from apps.cipher.ar_receipts import ARReceiptError, ar_receipt_inventory_proof
from apps.cipher.core.ids import loads
from apps.cipher.domain.owner_billing import OwnerBillingError
from apps.cipher.tests import test_ar_actions as journeys


class ARAdmissionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.journey = journeys.ARActionTests("runTest")
        self.journey.setUp()
        self.addCleanup(self.journey.doCleanups)
        self.c = self.journey.c
        self.bill, self.approval, self.receipts = self.journey.posted()
        self.assertEqual(len(ar_receipt_inventory_proof(self.c.db, self.c.audit)), 4)
        self.original_posting = copy.deepcopy(self.journey.domain.posting_receipt(self.bill))

    def corrupt75(self, kind):
        if kind == "missing":
            self.c.db.execute("DELETE FROM schema_version WHERE version=75")
        elif kind == "checksum":
            self.c.db.execute("UPDATE schema_version SET checksum=? WHERE version=75", ("0" * 64,))
        elif kind == "version":
            self.c.db.execute("UPDATE schema_version SET version=175 WHERE version=75")
        elif kind == "statementCount":
            self.c.db.execute("UPDATE schema_version SET statement_count=0 WHERE version=75")
        else:
            raise AssertionError(kind)

    def assert_native_original_retained(self):
        # Native schema74 proof does not make a claim about schema75 API history.
        self.assertEqual(self.journey.domain.posting_receipt(self.bill), self.original_posting)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_missing75_refuses_complete_api_inventory_but_keeps_native_original_posting(self):
        self.corrupt75("missing")
        self.assert_native_original_retained()
        with self.assertRaises(ARReceiptError):
            ar_receipt_inventory_proof(self.c.db, self.c.audit)

    def test_changed75_checksum_refuses_complete_api_inventory(self):
        self.corrupt75("checksum")
        self.assert_native_original_retained()
        with self.assertRaises(ARReceiptError):
            ar_receipt_inventory_proof(self.c.db, self.c.audit)

    def test_changed75_version_refuses_complete_api_inventory(self):
        self.corrupt75("version")
        with self.assertRaises(ARReceiptError):
            ar_receipt_inventory_proof(self.c.db, self.c.audit)

    def test_changed75_statement_count_refuses_complete_api_inventory(self):
        self.corrupt75("statementCount")
        with self.assertRaises(ARReceiptError):
            ar_receipt_inventory_proof(self.c.db, self.c.audit)

    def test_missing75_refuses_exact_original_replay_without_new_effect(self):
        self.corrupt75("missing")
        before = self.journey.state()
        _original, (args, kwargs) = self.receipts[-1]
        with self.assertRaises(APRefusal):
            self.journey.runner.run(*args, **kwargs)
        self.assertEqual(self.journey.state(), before)

    def test_missing75_refuses_new_previously_reviewed_command_without_effect(self):
        args, kwargs = self.journey.prepared(self.journey.person, "ownerBill.requestSend", self.bill)
        self.corrupt75("missing")
        before = self.journey.state()
        with self.assertRaises(APRefusal):
            self.journey.runner.run(*args, **kwargs)
        self.assertEqual(self.journey.state(), before)

    def test_missing75_holds_current_public_api_bill_but_not_native_historical_proof(self):
        self.corrupt75("missing")
        self.assert_native_original_retained()
        before = self.journey.state()
        with self.assertRaises(APRefusal) as caught:
            self.journey.contract.bill(self.journey.person, self.bill)
        self.assertEqual(caught.exception.status, 423)
        self.assertEqual(self.journey.state(), before)

    def test_missing74_with_real_source_receipt_and_journal_history_is_not_clean_legacy(self):
        self.c.db.execute("DELETE FROM schema_version WHERE version=74")
        before = self.journey.state()
        self.assertTrue(self.journey.domain.is_modern(self.bill))
        with self.assertRaises(OwnerBillingError):
            self.journey.domain.source_proof(self.bill)
        with self.assertRaises(APRefusal):
            self.journey.contract.bill(self.journey.person, self.bill)
        self.assertEqual(self.journey.state(), before)

    def test_unrecognized_current_action_namespace_refuses_before_audit_or_receipt(self):
        row = self.c.db.one("SELECT * FROM ar_action_receipts ORDER BY created_at,id LIMIT 1")
        before = self.journey.state()
        with self.c.db.transaction(), self.assertRaises(ARReceiptError):
            self.journey.runner.receipts.record(person_id=row["canonical_person_id"], actor_login=row["actor_login"],
                repeatability_uuid=str(uuid4()), action="ownerBill.genericWrite", resource_id=row["resource_id"],
                binding=loads(row["binding_json"]), result=loads(row["result_json"]), source=loads(row["source_json"]))
        self.assertEqual(self.journey.state(), before)


if __name__ == "__main__":
    unittest.main()
