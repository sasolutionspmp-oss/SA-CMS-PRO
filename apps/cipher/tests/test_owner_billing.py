"""Owned AR sources, original authorization and separate native posting."""
import unittest
from unittest.mock import patch

from apps.cipher.ar_practice_fixture import (
    make_ar_practice_fixture, PM_LOGIN, REVIEWER_LOGIN, POSTER_LOGIN, CONTROLLER_LOGIN, BOOTSTRAP_LOGIN,
)
from apps.cipher.core.approvals import ApprovalError, StaleApprovalError
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.core import db as core_db
from apps.cipher.core.ids import hash_json
from apps.cipher.domain.owner_billing import Plugin, OwnerBillingError, require_owner_billing_duty
from apps.cipher.domain.receivables import ReceivableError
from apps.cipher.service import Cipher


def preparation_body(c):
    records = c.ar_practice_records
    return {"claimRevisionId": records["claim_revision_id"], "reviewRevisionId": records["review_revision_id"],
            "periodId": records["period_id"], "lines": [
                {"lineId": "U1", "claimedCumulative": "12", "reviewedCumulative": "10", "differenceReason": "Two piles are not verified installed.",
                 "claimSourceLocator": "Owner claim / item U1", "reviewSourceLocator": "PM certification / item U1"},
                {"lineId": "L2", "claimedCumulative": "15000", "reviewedCumulative": "12500", "differenceReason": "Testing has not been performed.",
                 "claimSourceLocator": "Owner claim / item L2", "reviewSourceLocator": "PM certification / item L2"},
            ]}


def dump(c):
    return "\n".join(c.db.conn.iterdump())


class OwnerBillingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ar_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.o = self.c.plugin("owner_billing")
        self.r = self.c.ar_practice_records

    def prepare(self):
        return self.o.prepare(self.r["basis_id"], preparation_body(self.c), actor=PM_LOGIN)["primeBillId"]

    def request(self, bill_id):
        plan = self.o.business_request_preflight(bill_id, actor=PM_LOGIN)
        return self.c.approvals.request(plan["manifest"], requested_by=PM_LOGIN)

    def grant(self, bill_id):
        approval = self.request(bill_id)
        self.o.business_grant_preflight(bill_id, approval_id=approval["id"], actor=REVIEWER_LOGIN)
        self.c.approvals.grant(approval["id"], approver=REVIEWER_LOGIN)
        self.o.record_business_approval(bill_id, approval_id=approval["id"], actor=REVIEWER_LOGIN)
        return approval["id"]

    def test_genuine73_prefix_is_preserved_and_owner_schema_appends_without_import_registration(self):
        self.assertEqual(hash_json(SCHEMA_CATALOG[:73]), "f6396239c845928a66c8ba93c6563641fdb75555914906c8aff71a531d64ab69")
        applied = self.c.db.query("SELECT version,name,statement_count,checksum FROM schema_version ORDER BY version")
        self.assertEqual(hash_json(applied[:73]), "2893010c7a7f44367828a73aafc6d89bc7df753371a2947ad3075fc9fedbe223")
        self.assertEqual(applied[73]["name"], "owner_billing_sources_and_posting")

    def test_owned_claim_review_source_and_pure_preflight_preserve_no_financial_effect(self):
        before = dump(self.c)
        plan = self.o.prepare_preflight(self.r["basis_id"], preparation_body(self.c), actor=PM_LOGIN)
        self.assertEqual(dump(self.c), before)
        self.assertEqual(plan["calculation"]["reviewedCertifiedCents"], 2_250_000)
        self.assertEqual(plan["calculation"]["amountDueCents"], 2_025_000)
        bill = self.prepare()
        source = self.o.source_proof(bill, current=True)
        self.assertNotEqual(source["record"]["claim"]["document"]["id"], source["record"]["review"]["document"]["id"])
        self.assertEqual(source["bill"]["status"], "draft")
        self.assertEqual(self.c.ledger.journals(), [])
        self.assertTrue(all(check["ok"] for check in self.o.integrity_checks()))

    def test_journal_free_original_grant_and_independent_post_consume_same_authorization(self):
        bill = self.prepare()
        approval = self.grant(bill)
        self.assertEqual(self.c.approvals.get(approval)["status"], "granted")
        self.assertEqual(self.c.receivables.get(bill)["status"], "draft")
        self.assertEqual(self.c.ledger.journals(), [])
        before = dump(self.c)
        with self.assertRaises(OwnerBillingError):
            self.o.post(bill, approval_id=approval, actor=REVIEWER_LOGIN)
        self.assertEqual(dump(self.c), before)
        plan = self.o.posting_preflight(bill, approval_id=approval, actor=POSTER_LOGIN)
        self.assertEqual(dump(self.c), before)
        result = self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        self.assertEqual(result["status"], "posted")
        self.assertEqual(self.c.approvals.get(approval)["status"], "consumed")
        self.assertEqual([(line["account_code"], line["debit"], line["credit"]) for line in self.c.ledger.journal(result["journalId"])["lines"]],
                         [("1100", "20250.00", "0.00"), ("1150", "2250.00", "0.00"), ("4000", "0.00", "22500.00")])
        self.assertEqual(self.o.posting_receipt(bill)["approval_id"], approval)
        self.assertEqual(plan["postingPeriodId"], "2026-10")
        self.assertTrue(self.c.receivables.ar_open_items(self.r["project_id"])["reconciled"])
        self.assertTrue(self.c.receivables.retainage_receivable_items(self.r["project_id"])["reconciled"])

    def test_direct_aggregate_certification_and_combined_native_post_refuse_modern_source(self):
        with self.assertRaises(ReceivableError):
            self.c.receivables.certify(project_id=self.r["project_id"], period_id="2026-10", certified_cumulative="22500", actor=PM_LOGIN)
        bill = self.prepare()
        approval = self.grant(bill)
        before = dump(self.c)
        with self.assertRaises(ReceivableError):
            self.c.receivables.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        self.assertEqual(dump(self.c), before)

    def test_actual_internal_project_duties_precede_preparation_or_financial_authority(self):
        before = dump(self.c)
        for actor in (BOOTSTRAP_LOGIN, "unknown", REVIEWER_LOGIN, CONTROLLER_LOGIN):
            with self.subTest(actor=actor), self.assertRaises(OwnerBillingError):
                self.o.prepare(self.r["basis_id"], preparation_body(self.c), actor=actor)
        self.assertEqual(dump(self.c), before)
        self.assertIn("controller", require_owner_billing_duty(self.c, CONTROLLER_LOGIN, self.r["project_id"], "accounting")["roles"])
        with self.assertRaises(OwnerBillingError):
            require_owner_billing_duty(self.c, BOOTSTRAP_LOGIN, self.r["project_id"], "accounting")

    def test_forged_foreign_claim_review_line_or_date_shape_refuses_without_side_effects(self):
        body = preparation_body(self.c)
        changes = (
            {"claimRevisionId": self.r["hidden_claim_revision_id"]},
            {"reviewRevisionId": body["claimRevisionId"]}, {"periodId": "2026-11"},
            {"invoiceDate": "2026-10-14"}, {"retainageRate": "0"},
        )
        before = dump(self.c)
        for change in changes:
            with self.subTest(change=change), self.assertRaises((OwnerBillingError, StaleApprovalError)):
                self.o.prepare(self.r["basis_id"], {**body, **change}, actor=PM_LOGIN)
        self.assertEqual(dump(self.c), before)

    def test_source_deletion_does_not_turn_modern_bill_into_legacy(self):
        bill = self.prepare()
        source = self.o.source_proof(bill)
        original_guard = self.c.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='owner_billing_sources_no_delete'")["sql"]
        self.c.db.execute("DROP TRIGGER owner_billing_sources_no_delete")
        self.c.db.execute("DELETE FROM owner_billing_sources WHERE id=?", (source["record"]["id"],))
        self.c.db.execute(original_guard)
        self.assertTrue(self.o.is_modern(bill))
        with self.assertRaises(OwnerBillingError):
            self.o.source_proof(bill)
        with self.assertRaises(ReceivableError):
            self.c.receivables.post(bill, approval_id="forged", actor=POSTER_LOGIN)
        self.assertFalse(self.o.integrity_checks()[0]["ok"])

    def test_deleted_pending_request_cannot_disappear_from_authorization_inventory(self):
        bill = self.prepare()
        approval = self.request(bill)
        guard = self.c.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='approvals_no_delete'")
        if guard:
            self.c.db.execute("DROP TRIGGER approvals_no_delete")
        self.c.db.execute("DELETE FROM approvals WHERE id=?", (approval["id"],))
        if guard:
            self.c.db.execute(guard["sql"])
        with self.assertRaises(OwnerBillingError):
            self.o.approval_inventory(project_ids=(self.r["project_id"],))

    def test_late_source_write_failure_rolls_back_native_draft_and_audit_inside_caught_outer_transaction(self):
        original = self.o._record
        before = dump(self.c)
        def failed_record(kind, body, actor):
            result = original(kind, body, actor)
            if kind == "sources":
                raise RuntimeError("synthetic source storage completion fault")
            return result
        with self.c.db.transaction(), patch.object(self.o, "_record", side_effect=failed_record):
            with self.assertRaises(RuntimeError):
                self.prepare()
            self.assertEqual(dump(self.c), before)

    def test_late_posting_receipt_failure_rolls_back_consumption_journal_and_native_status(self):
        bill = self.prepare()
        approval = self.grant(bill)
        original = self.o._record
        before = dump(self.c)
        def failed_record(kind, body, actor):
            result = original(kind, body, actor)
            if kind == "postings":
                raise RuntimeError("synthetic posting receipt storage completion fault")
            return result
        with self.c.db.transaction(), patch.object(self.o, "_record", side_effect=failed_record):
            with self.assertRaises(RuntimeError):
                self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
            self.assertEqual(dump(self.c), before)
        result = self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        self.assertEqual(result["status"], "posted")

    def test_extra_prime_bill_journal_cannot_hide_behind_an_original_valid_posting_receipt(self):
        bill = self.prepare()
        approval = self.grant(bill)
        self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        tags = {"project_id": self.r["project_id"], "party_id": self.r["customer_id"]}
        self.c.ledger.post(period_id="2026-10", description="Unexpected second source effect (synthetic)",
            source_type="prime_bill", source_id=bill, source_version="unauthorized-second", posted_by=POSTER_LOGIN,
            lines=[{"account": "1100", "debit": "1.00", **tags}, {"account": "4000", "credit": "1.00", **tags}])
        with self.assertRaises(OwnerBillingError):
            self.o.posting_receipt(bill)

    def test_genuine_draft_has_no_send_and_a_forged_send_cannot_be_hidden_by_its_draft_status(self):
        bill = self.prepare()
        self.assertIsNone(self.o.send_proof(bill))
        self.c.audit.record(PM_LOGIN, "prime_bill.sent", "prime_bill", bill,
                            {"channel": "mail-sink", "send_id": "forged", "message_hash": "forged"})
        with self.assertRaises(OwnerBillingError):
            self.o.send_proof(bill)

    def test_uninstalled_owner_module_is_inert_for_genuine73_but_lost_admission_with_history_fails_closed(self):
        with patch.object(core_db, "SCHEMA_CATALOG", list(SCHEMA_CATALOG[:73])):
            old = Cipher()
        try:
            owner = Plugin(old)
            self.assertEqual(owner.basis_inventory(), [])
            self.assertEqual(owner.source_inventory(), [])
            self.assertEqual(owner.integrity_checks(), [])
        finally:
            old.db.close()
        self.c.db.execute("DELETE FROM schema_version WHERE name='owner_billing_sources_and_posting'")
        with self.assertRaises(OwnerBillingError):
            self.o.basis_inventory()
        self.assertFalse(self.o.integrity_checks()[0]["ok"])

    def test_original_event_sequence_requires_exact_integer_type_and_whole_source_rollback(self):
        before = dump(self.c)
        original = self.o._record
        def malformed(kind, body, actor):
            if kind == "sources":
                body["certifiedEvent"]["seq"] = float(body["certifiedEvent"]["seq"])
            return original(kind, body, actor)
        with patch.object(self.o, "_record", side_effect=malformed):
            with self.assertRaises(OwnerBillingError):
                self.prepare()
        self.assertEqual(dump(self.c), before)

    def test_original_send_proof_remains_exact_after_a_genuine_later_partial_collection(self):
        bill = self.prepare()
        financial = self.grant(bill)
        self.o.post(bill, approval_id=financial, actor=POSTER_LOGIN)
        manifest = self.c._manifest("prime_bill.send", bill, "pm")
        send = self.c.approvals.request(manifest, requested_by=PM_LOGIN)
        self.c.approvals.grant(send["id"], approver=REVIEWER_LOGIN)
        current = self.c._manifest("prime_bill.send", bill, "pm")
        self.c.approvals.consume(send["id"], current_manifest=current, consumer=PM_LOGIN)
        self.c.receivables.apply("prime_bill.send", bill, approval_id=send["id"], manifest=current, actor=PM_LOGIN, period_id=None)
        original = self.o.send_proof(bill)
        self.assertEqual(original["originalMessage"]["balance_due"], "20250.00")
        self.c.receivables.record_collection(prime_bill_id=bill, period_id="2026-10", amount="100.00", fee="0", method="check",
            provider_ref="AR-PARTIAL-SYNTHETIC-1", actor=POSTER_LOGIN, settlement_date="2026-10-01")
        self.assertEqual(self.c.receivables.get(bill)["open"], "20150.00")
        self.assertEqual(self.o.send_proof(bill), original)
        self.assertTrue(all(check["ok"] for check in self.o.integrity_checks()))

    def test_next_certification_requires_the_previous_original_posting_receipt(self):
        bill = self.prepare()
        approval = self.grant(bill)
        self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        guard = self.c.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='owner_billing_postings_no_delete'")["sql"]
        self.c.db.execute("DROP TRIGGER owner_billing_postings_no_delete")
        self.c.db.execute("DELETE FROM owner_billing_postings WHERE prime_bill_id=?", (bill,))
        self.c.db.execute(guard)
        next_body = preparation_body(self.c)
        next_body["lines"][0].update(claimedCumulative="20", reviewedCumulative="20", differenceReason="")
        next_body["lines"][1].update(claimedCumulative="20000", reviewedCumulative="20000", differenceReason="")
        before = dump(self.c)
        with self.assertRaises(OwnerBillingError):
            self.o.prepare(self.r["basis_id"], next_body, actor=PM_LOGIN)
        self.assertEqual(dump(self.c), before)

    def test_native_posting_fault_cannot_override_the_original_reviewed_rule_description_or_audit(self):
        bill = self.prepare()
        approval = self.grant(bill)
        original_post, original_audit = self.c.ledger.post, self.c.audit.record
        before = dump(self.c)
        for fault in ("rule", "description", "journalAudit", "billAudit"):
            def modified_post(**kwargs):
                if fault == "rule":
                    kwargs["rule_version"] = "unreviewed-owner-billing-rule"
                elif fault == "description":
                    kwargs["description"] = "An unreviewed owner billing purpose"
                return original_post(**kwargs)
            def modified_audit(actor, action, entity_type, entity_id, payload=None):
                payload = dict(payload or {})
                if fault == "journalAudit" and action == "journal.posted":
                    payload["total"] = "1.00"
                elif fault == "billAudit" and action == "prime_bill.posted":
                    payload["payment_terms_version"] = 999
                return original_audit(actor, action, entity_type, entity_id, payload)
            with self.subTest(fault=fault), patch.object(self.c.ledger, "post", side_effect=modified_post), patch.object(self.c.audit, "record", side_effect=modified_audit):
                with self.assertRaises(OwnerBillingError):
                    self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
            self.assertEqual(dump(self.c), before)

    def test_raw_posted_marker_without_original_grant_receipt_or_journal_fails_source_reads(self):
        bill = self.prepare()
        guards = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='prime_bills'")
        for guard in guards:
            self.c.db.execute(f"DROP TRIGGER {guard['name']}")
        self.c.db.execute("UPDATE prime_bills SET status='posted' WHERE id=?", (bill,))
        for guard in guards:
            self.c.db.execute(guard["sql"])
        with self.assertRaises(OwnerBillingError):
            self.o.source_proof(bill)
        self.assertFalse(self.o.integrity_checks()[0]["ok"])

    def test_original_granted_and_consumed_deadline_cannot_be_rewritten_without_authority(self):
        bill = self.prepare()
        approval = self.grant(bill)
        self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        guards = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='approvals'")
        for guard in guards:
            self.c.db.execute(f"DROP TRIGGER {guard['name']}")
        self.c.db.execute("UPDATE approvals SET expires_at='1900-01-01T00:00:00+00:00' WHERE id=?", (approval,))
        for guard in guards:
            self.c.db.execute(guard["sql"])
        with self.assertRaises(OwnerBillingError):
            self.o.posting_receipt(bill)

    def test_original_receipt_survives_genuine_later_contract_terms_and_recipient_versions(self):
        bill = self.prepare()
        approval = self.grant(bill)
        self.o.post(bill, approval_id=approval, actor=POSTER_LOGIN)
        original = self.o.posting_receipt(bill)
        self.c.receivables.set_prime_contract(self.r["project_id"], "260000", "0.10", actor=PM_LOGIN)
        self.c.plugin("close").set_contract_value(self.r["project_id"], "260000", actor=PM_LOGIN,
                                                 note="Separate later synthetic source version")
        self.c.receivables.set_customer_terms(self.r["customer_id"], 45, actor=PM_LOGIN)
        self.c.receivables.set_billing_recipients(self.r["customer_id"], ["revised-billing@synthetic-owner.invalid"], actor=PM_LOGIN)
        self.assertEqual(self.o.posting_receipt(bill), original)
        with self.assertRaises(StaleApprovalError):
            self.o.basis_proof(self.r["basis_id"], current=True)


if __name__ == "__main__":
    unittest.main()
