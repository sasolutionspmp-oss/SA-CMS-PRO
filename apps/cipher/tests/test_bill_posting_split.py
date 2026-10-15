"""One bill business grant, followed by an independent explicit posting act."""
import datetime
import os
import tempfile
import unittest
from unittest.mock import patch

from apps.cipher.core.approvals import ApprovalExpired, build_manifest
from apps.cipher.core import db
from apps.cipher.core.ids import canonical_json, hash_json, utcnow
from apps.cipher.domain.bills import BillError, register_bill_posting_schema
from apps.cipher.service import Cipher

register_bill_posting_schema()


class BillPostingSplitTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.addCleanup(self.c.db.close)
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic subcontractor", destination="SIM-ORIGINAL")
        self.project = self.c.create_project(name="Synthetic split", entity="Synthetic LLC", budget="10000")
        self.c.open_period("P1", "October", "2026-10-01", "2026-10-31")
        self.c.open_period("P2", "November", "2026-11-01", "2026-11-30")
        self.commitment = self.c.commitments.create(project_id=self.project["id"], supplier_id=self.supplier["id"], title="Synthetic piping",
                                                   sov_lines=[{"description": "Piping", "amount": "10000"}], actor="pm")
        self.c.approve_and_execute("commitment.execute", self.commitment["id"])
        self.line = self.commitment["sov"][0]["id"]
        self.bill = self.certify("1000")
        # Isolate domain invariants. Service integration supplies real people/governor checks.
        self.c.bills.posting_authorizer = lambda approval, manifest, actor, period_id, **kwargs: None
        self.c.bills.cancellation_authorizer = lambda approval, manifest, actor: None
        self.c.bills.business_manifest_builder = lambda bill_id, actor_role: self.c.bills.manifest(bill_id, actor_role=actor_role)

    def certify(self, value):
        return self.c.bills.certify(commitment_id=self.commitment["id"], period_id="P1",
                                    installed=[{"sov_line_id": self.line, "cumulative_installed": value}], actor="preparer")

    def grant(self, bill=None):
        bill = bill or self.bill
        manifest = self.c.bills.manifest(bill["id"], actor_role="pm")
        approval = self.c.approvals.request(manifest, requested_by="preparer")
        self.c.approvals.grant(approval["id"], approver="pm-approver")
        self.c.bills.record_business_approval(bill["id"], approval_id=approval["id"], actor="pm-approver")
        return self.c.approvals.get(approval["id"])

    def post(self, approval, *, bill=None, period_id="P1", reason="", actor="bookkeeper"):
        return self.c.bills.post((bill or self.bill)["id"], approval_id=approval["id"], actor=actor,
                                 period_id=period_id, reason=reason)

    def test_business_grant_records_approved_without_consumption_journals_or_payable(self):
        before = self.c.ledger.trial_balance()["journal_count"]
        approval = self.grant()
        current = self.c.bills.get(self.bill["id"])
        self.assertEqual(current["status"], "approved")
        self.assertEqual(current["business_approval_id"], approval["id"])
        self.assertIsNone(current["approval_id"])
        self.assertIsNone(current["journal_id"])
        self.assertEqual(approval["status"], "granted")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], before)
        self.assertEqual(self.c.bills.open_payable(self.bill["id"]), 0)
        self.assertEqual(self.c.bills.retainage_open_items()["subledger_total"], "0.00")
        self.assertEqual(self.c.bills.stored_material_items()["subledger_total"], "0.00")
        with self.assertRaises(Exception):
            self.c.payments.manifest_for_bill(self.bill["id"], actor_role="treasury")

    def test_chosen_period_receipt_preserves_certification_and_original_business_authorization(self):
        approval = self.grant()
        before_hash = self.bill["content_hash"]
        result = self.post(approval, period_id="P2", reason="November accounting close")
        self.assertEqual((result["status"], result["period_id"], result["posting_period_id"]), ("posted", "P1", "P2"))
        self.assertEqual(result["content_hash"], before_hash)
        self.assertEqual(result["approval_id"], approval["id"])
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "consumed")
        receipt = self.c.bills.posting_receipt(result["id"])
        self.assertEqual(receipt["period_id"], "P2")
        self.assertEqual(receipt["reason"], "November accounting close")
        self.assertEqual(receipt["posted_by"], "bookkeeper")
        journals = self.c.db.query("SELECT * FROM journals WHERE source_type='bill' AND source_id=?", (result["id"],))
        self.assertTrue(journals)
        self.assertEqual({j["period_id"] for j in journals}, {"P2"})
        self.assertEqual({j["approval_id"] for j in journals}, {approval["id"]})
        self.assertTrue(all(check["ok"] for check in self.c.bills.lifecycle_integrity_checks(result["id"])))

    def test_cross_period_reason_and_same_person_and_unconfigured_authorizer_refuse(self):
        approval = self.grant()
        for kwargs in ({"period_id": "P2"}, {"actor": " PM-APPROVER "}):
            with self.subTest(kwargs=kwargs), self.assertRaises(BillError):
                self.post(approval, **kwargs)
        self.c.bills.posting_authorizer = None
        with self.assertRaises(BillError):
            self.post(approval)
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "granted")

    def test_bank_destination_change_does_not_change_business_approval(self):
        approval = self.grant()
        self.c.db.execute("UPDATE parties SET destination='SIM-REPLACED', destination_version=destination_version+1 WHERE id=?", (self.supplier["id"],))
        self.assertEqual(self.post(approval)["status"], "posted")

    def test_supplier_identity_change_blocks_posting(self):
        approval = self.grant()
        self.c.db.execute("UPDATE parties SET name='Synthetic revised supplier' WHERE id=?", (self.supplier["id"],))
        with self.assertRaises(BillError):
            self.post(approval)
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "granted")

    def test_expired_business_grant_cannot_post(self):
        approval = self.grant()
        self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?", ((utcnow() - datetime.timedelta(days=1)).isoformat(), approval["id"]))
        with self.assertRaises(ApprovalExpired):
            self.post(approval)
        self.assertEqual(self.c.bills.get(self.bill["id"])["status"], "approved")

    def test_extending_expiry_cannot_increase_original_business_authority(self):
        approval = self.grant()
        self.c.db.execute("DROP TRIGGER approvals_request_immutable")
        self.c.db.execute("UPDATE approvals SET expires_at='2099-12-31T00:00:00Z' WHERE id=?", (approval["id"],))
        later = utcnow() + datetime.timedelta(days=2)
        with patch("apps.cipher.domain.bills.utcnow", return_value=later), patch("apps.cipher.core.approvals.utcnow", return_value=later):
            with self.assertRaises(BillError):
                self.post(approval)
        self.assertEqual(self.c.bills.get(self.bill["id"])["status"], "approved")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "granted")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)

    def test_malformed_or_naive_expiry_is_a_typed_bill_refusal(self):
        approval = self.grant()
        self.c.db.execute("DROP TRIGGER approvals_request_immutable")
        for expiry in ("not-a-date", "2026-10-14T00:00:00", ""):
            with self.subTest(expiry=expiry):
                self.c.db.execute("UPDATE approvals SET expires_at=? WHERE id=?", (expiry, approval["id"]))
                with self.assertRaises(BillError):
                    self.post(approval)

    def test_billed_line_tampering_changes_bound_business_facts(self):
        approval = self.grant()
        self.c.db.execute("UPDATE bill_lines SET cumulative_installed='900.00' WHERE bill_id=?", (self.bill["id"],))
        with self.assertRaises(BillError):
            self.post(approval)

    def test_approved_cancel_preserves_history_and_replacement_number(self):
        approval = self.grant()
        canceled = self.c.bills.void(self.bill["id"], actor="pm-approver", reason="Synthetic revised claim")
        self.assertEqual(canceled["status"], "void")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "invalidated")
        replacement = self.certify("1000")
        self.assertEqual(replacement["sequence"], self.bill["sequence"] + 1)
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertTrue(all(check["ok"] for check in self.c.bills.lifecycle_integrity_checks()))

    def test_approved_stored_transfer_cancel_restores_reservations_and_subledgers(self):
        self.c.bills.void(self.bill["id"], actor="preparer", reason="Synthetic stored claim replacement")
        document = self.c.evidence.register_document(project_id=self.project["id"], kind="stored_material_evidence", title="Synthetic stored pipe", actor="preparer")
        revision = self.c.evidence.add_revision(document_id=document["id"], content=b"synthetic title, insurance, delivery", actor="preparer")
        lot = self.c.bills.add_stored_material(commitment_id=self.commitment["id"], sov_line_id=self.line, description="Synthetic pipe",
                                               eligible_amount="1000", evidence_hash=revision["content_hash"], location="Synthetic yard", actor="preparer")
        first = self.certify("1000")
        self.post(self.grant(first), bill=first)
        successor = self.c.bills.certify(commitment_id=self.commitment["id"], period_id="P1",
                                        installed=[{"sov_line_id": self.line, "cumulative_installed": "1500"}],
                                        transfers=[{"lot_id": lot["id"], "amount": "500"}], actor="preparer")
        self.grant(successor)
        self.assertEqual(self.c.bills.lot(lot["id"])["remaining_amount"], "500.00")
        self.c.bills.void(successor["id"], actor="pm-approver", reason="Synthetic revised stored transfer")
        self.assertEqual(self.c.bills.lot(lot["id"])["remaining_amount"], "1000.00")
        self.assertTrue(self.c.bills.stored_material_items()["reconciled"])
        self.assertTrue(self.c.bills.retainage_open_items()["reconciled"])

    def test_real_service_coverage_is_rechecked_at_independent_posting(self):
        from apps.cipher.tests.test_contracts import GL, World
        from apps.cipher.domain.contracts import CoverageError
        world = World()
        self.addCleanup(world.c.db.close)
        world.certificate(expiry=0)
        commitment = world.signed_commitment(requirements=GL)
        bill = world.certify(commitment)
        approval = world.request_post(bill["id"])
        self.assertEqual(world.c.bills.get(bill["id"])["status"], "approved")
        world.clock(1)
        with self.assertRaises(CoverageError):
            world.c.post_bill(bill["id"], actor="accountant")
        self.assertEqual(world.c.approvals.get(approval["id"])["status"], "granted")
        self.assertIsNone(world.c.bills.get(bill["id"])["journal_id"])
        self.assertEqual(world.c.bills.open_payable(bill["id"]), 0)

    def test_posting_receipt_tampering_after_trigger_removal_fails_integrity(self):
        approval = self.grant()
        self.post(approval)
        receipt = self.c.bills.posting_receipt(self.bill["id"])
        self.c.db.execute("DROP TRIGGER bill_posting_receipts_no_update")
        self.c.db.execute("UPDATE bill_posting_receipts SET reason='rewritten reason' WHERE id=?", (receipt["id"],))
        with self.assertRaises(BillError):
            self.c.bills.posting_receipt(self.bill["id"])
        self.assertFalse(all(check["ok"] for check in self.c.bills.lifecycle_integrity_checks(self.bill["id"])))

    def test_financial_subledgers_refuse_altered_posted_source_facts(self):
        self.post(self.grant())
        self.c.db.execute("DROP TRIGGER bills_posted_figures_immutable")
        self.c.db.execute("UPDATE bills SET amount_due='1800.00',retainage_this_period='100.00',cumulative_stored='1.00' WHERE id=?", (self.bill["id"],))
        for read in (self.c.bills.ap_open_items, self.c.bills.retainage_open_items, self.c.bills.stored_material_items):
            with self.subTest(read=read.__name__), self.assertRaises(BillError):
                read()

    def test_correction_cannot_precede_actual_posting_period(self):
        approval = self.grant()
        self.post(approval, period_id="P2", reason="Synthetic accounting period")
        self.c.bills.prepare_correction(self.bill["id"], reason="Synthetic replacement", actor="bookkeeper")
        manifest = self.c.bills.manifest_for("bill.correct", self.bill["id"], actor_role="accountant")
        correction = self.c.approvals.request(manifest, requested_by="bookkeeper")
        self.c.approvals.grant(correction["id"], approver="controller")
        self.c.approvals.consume(correction["id"], current_manifest=manifest, consumer="bookkeeper")
        with self.assertRaises(BillError):
            self.c.bills.apply("bill.correct", self.bill["id"], approval_id=correction["id"], manifest=manifest, actor="bookkeeper", period_id="P1")

    def test_schema_64_upgrade_preserves_historical_posted_bill_journals_and_audit(self):
        historical = [entry for entry in db.SCHEMA_CATALOG if entry[1] != "bills_business_approval_posting"]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "old.sqlite")
            with patch.object(db, "SCHEMA_CATALOG", historical):
                old = Cipher(path)
                try:
                    sup = old.add_party(kind="supplier", name="Synthetic old supplier")
                    job = old.create_project(name="Synthetic schema64", entity="Synthetic LLC", budget="2000")
                    old.open_period("P1", "October", "2026-10-01", "2026-10-31")
                    commitment = old.commitments.create(project_id=job["id"], supplier_id=sup["id"], title="Synthetic old",
                                                        sov_lines=[{"description": "Old", "amount": "2000"}], actor="owner")
                    old.approve_and_execute("commitment.execute", commitment["id"])
                    bill = old.bills.certify(commitment_id=commitment["id"], period_id="P1",
                                             installed=[{"sov_line_id": commitment["sov"][0]["id"], "cumulative_installed": "1000"}], actor="owner")
                    # Historical fixture only: faithfully seed the former combined act.
                    plan = old.bills.journal_preview(bill["id"])
                    manifest = build_manifest(operation="bill.approve", subject_type="bill", subject_id=bill["id"], actor_role="accountant",
                                              bindings={"journal_preview": plan})
                    ap = old.approvals.request(manifest, requested_by="owner")
                    old.approvals.grant(ap["id"], approver="owner")
                    old.approvals.consume(ap["id"], current_manifest=manifest, consumer="owner")
                    journals = [old.ledger.post(period_id=j["period_id"], description=j["description"], lines=j["lines"], source_type="bill",
                                                source_id=bill["id"], source_version=j["source_version"], posted_by="owner", approval_id=ap["id"]) for j in plan]
                    old.db.execute("UPDATE bills SET status='posted',approval_id=?,journal_id=? WHERE id=?", (ap["id"], journals[-1]["id"], bill["id"]))
                    old.audit.record("owner", "bill.posted", "bill", bill["id"], {"approval_id": ap["id"], "journals": [j["id"] for j in journals], "amount_due": bill["amount_due"]})
                    before_schema = old.db.query("SELECT * FROM schema_version ORDER BY version")
                    before_audit = old.audit.entries()
                    before_journals = old.db.query("SELECT * FROM journals ORDER BY id")
                finally:
                    old.db.close()
            reopened = Cipher(path)
            try:
                self.assertEqual(reopened.db.query("SELECT * FROM schema_version ORDER BY version")[:len(before_schema)], before_schema)
                self.assertEqual(reopened.audit.entries(), before_audit)
                self.assertEqual(reopened.db.query("SELECT * FROM journals ORDER BY id"), before_journals)
                self.assertEqual(reopened.bills.get(bill["id"])["status"], "posted")
                self.assertIsNone(reopened.bills.posting_receipt(bill["id"]))
            finally:
                reopened.db.close()

    def test_cumulative_successor_waits_for_predecessor_posting(self):
        first = self.grant()
        successor = self.certify("2000")
        second = self.grant(successor)
        with self.assertRaises(BillError):
            self.post(second, bill=successor)
        self.post(first)
        self.assertEqual(self.post(second, bill=successor)["status"], "posted")
        self.assertEqual(str(self.c.ledger.balance("2000")), "1800.00")

    def test_cumulative_successor_period_cannot_precede_predecessor_actual_posting(self):
        first = self.grant()
        successor = self.certify("2000")
        second = self.grant(successor)
        self.post(first, period_id="P2", reason="Synthetic late accounting")
        with self.assertRaises(BillError):
            self.post(second, bill=successor, period_id="P1")
        self.assertEqual(self.post(second, bill=successor, period_id="P2", reason="Same accounting period as predecessor")["status"], "posted")

    def test_old_combined_consumed_authorization_cannot_post_directly(self):
        old = build_manifest(operation="bill.approve", subject_type="bill", subject_id=self.bill["id"], actor_role="accountant")
        approval = self.c.approvals.request(old, requested_by="preparer")
        self.c.approvals.grant(approval["id"], approver="pm-approver")
        self.c.approvals.consume(approval["id"], current_manifest=old, consumer="legacy")
        with self.assertRaises(BillError):
            self.post(approval)
        self.assertEqual(self.c.bills.get(self.bill["id"])["status"], "draft")

    def test_failed_posting_rolled_back_even_when_refusal_is_caught_in_outer_transaction(self):
        approval = self.grant()
        before = tuple(self.c.db.conn.iterdump())
        with self.c.db.transaction():
            with patch.object(self.c.ledger, "post", side_effect=RuntimeError("synthetic journal refusal")):
                with self.assertRaises(RuntimeError):
                    self.post(approval)
        self.assertEqual(tuple(self.c.db.conn.iterdump()), before)

    def test_business_record_tampering_is_detected_after_its_triggers_are_removed(self):
        approval = self.grant()
        record = self.c.db.one("SELECT * FROM bill_business_approvals WHERE approval_id=?", (approval["id"],))
        self.c.db.execute("DROP TRIGGER bill_business_approvals_no_update")
        self.c.db.execute("UPDATE bill_business_approvals SET approved_by='different-approver' WHERE id=?", (record["id"],))
        with self.assertRaises(BillError):
            self.post(approval)

    def test_superseded_business_record_deletion_stops_posting_and_closing(self):
        first = self.grant()
        original_record = self.c.bills.get(self.bill["id"])["approval_record_id"]
        second = self.grant()
        self.assertEqual(self.c.approvals.get(first["id"])["status"], "invalidated")
        self.c.db.execute("DROP TRIGGER bill_business_approvals_no_delete")
        self.c.db.execute("DELETE FROM bill_business_approvals WHERE id=?", (original_record,))
        with self.assertRaises(BillError):
            self.post(second)
        self.assertFalse(all(check["ok"] for check in self.c.bills.lifecycle_integrity_checks(self.bill["id"])))

    def test_superseded_business_record_deletion_stops_posted_receipt_verification(self):
        self.grant()
        original_record = self.c.bills.get(self.bill["id"])["approval_record_id"]
        second = self.grant()
        self.post(second)
        self.c.db.execute("DROP TRIGGER bill_business_approvals_no_delete")
        self.c.db.execute("DELETE FROM bill_business_approvals WHERE id=?", (original_record,))
        with self.assertRaises(BillError):
            self.c.bills.posting_receipt(self.bill["id"])


if __name__ == "__main__":
    unittest.main()
