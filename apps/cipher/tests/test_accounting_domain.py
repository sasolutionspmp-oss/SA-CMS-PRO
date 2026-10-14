"""Original-source, governed queue, delivery recovery and reconciliation checks."""
from __future__ import annotations
import unittest
from unittest.mock import patch

from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, PM_LOGIN, REVIEWER_LOGIN, BOOTSTRAP_LOGIN, make_ap_practice_fixture
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.core.ids import hash_json
from apps.cipher.domain import accounting
from apps.cipher.accounting_simulator import SimulatedAccountingRecordStore, SimulatedAccountingAdapter, Fault, validate_payload
from apps.cipher.accounting_worker import SimulatedAccountingWorker, WorkerHeld, WorkerLocalPersistenceError

class AccountingDomainTests(unittest.TestCase):

    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("accounting")
        self.bill_id = self.c.ap_practice_records["draft_bill_id"]
        ap = self.c.request_approval("bill.approve", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.post_bill(self.bill_id, actor=ACCOUNTANT_LOGIN, period_id="2026-11", reason="Synthetic reviewed later posting")
        self.bill = self.c.bills.get(self.bill_id)
        self.mapping = self.domain.prepare_synthetic_mapping(self.bill["project_id"], actor=ACCOUNTANT_LOGIN, reason="Synthetic practice accounts only")
        self.plan = self.domain.prepare(self.bill_id, self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.store = SimulatedAccountingRecordStore()
        self.adapter = SimulatedAccountingAdapter(self.store)
        self.worker = SimulatedAccountingWorker(self.domain, self.adapter)

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, dict(self.adapter.calls), self.store.effect_count

    def queue(self):
        ap = self.c.request_approval(accounting.OP_QUEUE, self.plan["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        done = self.c.execute(ap["id"], actor=ACCOUNTANT_LOGIN)
        return done.result["intent_id"], ap["id"]

    def correct(self):
        self.c.bills.prepare_correction(self.bill_id, "Synthetic replacement must be prepared separately", ACCOUNTANT_LOGIN)
        ap = self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(ap["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(ap["id"], actor=ACCOUNTANT_LOGIN, period_id="2026-11")

    def test_exact_original_this_period_cost_ap_retainage_and_actual_posting_date(self):
        payload = self.plan["payload"]
        validate_payload(payload["logicalOperationId"], payload, self.plan["payload_hash"])
        self.assertEqual(payload["transactionDate"], "2026-11-30")
        self.assertEqual(payload["datePolicy"], "synthetic.period-end.v1")
        self.assertEqual([(line["sourceAccountCode"], line["debitCents"], line["creditCents"]) for line in payload["lines"]],
                         [("5000", 1234567, 0), ("2000", 0, 1111110), ("2050", 0, 123457)])
        receipt = self.c.bills.posting_receipt(self.bill_id)
        self.assertEqual(payload["source"]["postingReceiptHash"], receipt["receipt_hash"])
        self.assertEqual(payload["source"]["journalId"], self.bill["journal_id"])
        self.assertEqual(payload["period"]["id"], "2026-11")

    def test_previews_have_zero_sql_and_provider_effect(self):
        before = self.snapshot()
        self.domain.preparation_preflight(self.bill_id, self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.domain.queue_preflight(self.plan["id"])
        self.domain.manifest_for(accounting.OP_QUEUE, self.plan["id"], actor_role="accountant")
        self.assertEqual(before, self.snapshot())

    def test_owner_wildcard_and_pm_do_not_manufacture_accountant_duty(self):
        for actor in (BOOTSTRAP_LOGIN, PM_LOGIN):
            with self.subTest(actor=actor), self.assertRaises(accounting.AccountingError):
                self.domain.require_accountant(actor, self.bill["project_id"])

    def test_requester_cannot_grant_own_queue(self):
        ap = self.c.request_approval(accounting.OP_QUEUE, self.plan["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        before = self.snapshot()
        with self.assertRaises(Exception):
            self.c.approve(ap["id"], approver=ACCOUNTANT_LOGIN, approver_role="accountant")
        self.assertEqual(before, self.snapshot())

    def test_mapping_supersession_preserves_uuid_but_stales_old_plan(self):
        new_mapping = self.domain.prepare_synthetic_mapping(self.bill["project_id"], actor=ACCOUNTANT_LOGIN, reason="New synthetic mapping declaration")
        new_plan = self.domain.prepare(self.bill_id, new_mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.assertEqual(new_plan["logical_operation_id"], self.plan["logical_operation_id"])
        self.assertNotEqual(new_plan["payload_hash"], self.plan["payload_hash"])
        with self.assertRaises(accounting.AccountingError):
            self.domain.queue_preflight(self.plan["id"])

    def test_one_approved_queue_no_provider_call_or_second_intent(self):
        before_journals = self.c.ledger.trial_balance()["journal_count"]
        intent_id, ap = self.queue()
        self.assertEqual(self.domain.intent(intent_id)["status"], "queued")
        self.assertEqual(self.c.approvals.get(ap)["status"], "consumed")
        self.assertEqual(self.store.effect_count, 0)
        self.assertEqual(self.adapter.calls["submit"], 0)
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], before_journals)
        with self.assertRaises(accounting.AccountingError):
            self.domain.queue_preflight(self.plan["id"])

    def test_submit_then_separate_readback_reconciles_without_extra_ledger_journal(self):
        intent_id, _ = self.queue()
        before_journals = self.c.ledger.trial_balance()["journal_count"]
        result = self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result["status"], "simulated_accepted")
        self.assertEqual(self.store.effect_count, 1)
        result = self.worker.reconcile_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result["status"], "reconciled")
        self.assertEqual(self.adapter.calls, {"submit": 1, "lookup": 0, "read_record": 1})
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], before_journals)

    def test_unknown_after_acceptance_lookup_resolves_same_uuid_without_resubmit(self):
        intent_id, _ = self.queue()
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.assertEqual(self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "outcome_unknown")
        self.assertEqual(self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)
        self.assertEqual(self.adapter.calls["lookup"], 1)
        self.assertEqual(self.store.effect_count, 1)

    def test_confirmed_missing_is_one_tick_then_same_uuid_submit(self):
        intent_id, _ = self.queue()
        self.adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
        self.assertEqual(self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "outcome_unknown")
        self.assertEqual(self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "queued")
        self.assertEqual(self.adapter.calls["submit"], 1)
        self.assertEqual(self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "simulated_accepted")
        self.assertEqual(self.store.effect_count, 1)

    def test_corrected_source_is_readable_and_cannot_start_new_delivery(self):
        intent_id, _ = self.queue()
        self.correct()
        self.assertEqual(self.domain.plan(self.plan["id"])["payload_hash"], self.plan["payload_hash"])
        with self.assertRaises(WorkerHeld):
            self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(self.store.effect_count, 0)

    def test_unknown_original_acceptance_survives_correction_without_netting(self):
        intent_id, _ = self.queue()
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.correct()
        result = self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)
        self.assertEqual(self.store.effect_count, 1)
        self.assertEqual(self.worker.reconcile_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "reconciled")

    def test_readback_failure_keeps_acceptance_and_allows_separate_retry(self):
        intent_id, _ = self.queue()
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.adapter.queue_fault("read_record", Fault.READBACK_MISMATCH)
        result = self.worker.reconcile_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result["status"], "simulated_accepted")
        self.assertEqual(self.worker.reconcile_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "reconciled")
        self.assertEqual(self.store.effect_count, 1)

    def test_failed_local_finish_leaves_independent_provider_record_and_forces_lookup(self):
        intent_id, _ = self.queue()
        with patch.object(self.domain, "finish_attempt", side_effect=RuntimeError("synthetic local rollback")):
            with self.assertRaises(WorkerLocalPersistenceError):
                self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(self.store.effect_count, 1)
        # Advance the test clock to expire the abandoned original claim; no DB
        # status/token edits simulate the recovery.
        from apps.cipher.core.ids import utcnow
        from datetime import timedelta
        with patch.object(accounting, "utcnow", return_value=utcnow()+timedelta(seconds=61)):
            result = self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)
        self.assertEqual(self.store.effect_count, 1)

    def test_no_provider_boundary_inside_outer_sql_transaction(self):
        intent_id, _ = self.queue()
        before = self.snapshot()
        with self.c.db.transaction():
            with self.assertRaises(WorkerHeld):
                self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_original_period_date_and_missing_accounting_births_fail_source_proof(self):
        self.c.db.execute("UPDATE periods SET end_date='2026-11-29' WHERE id='2026-11'")
        before = self.snapshot()
        with self.assertRaises(accounting.AccountingError):
            self.domain.plan(self.plan["id"])
        self.assertEqual(before, self.snapshot())

    def test_exports_drop_private_lease_tokens_and_report_simulation(self):
        intent_id, _ = self.queue()
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        export = self.domain.export()
        self.assertTrue(export["synthetic"])
        self.assertEqual(export["mode"], "practice")
        self.assertTrue(export["records"]["leases"])
        self.assertNotIn("token", export["records"]["leases"][0])
        checks = self.domain.close_checks("2026-11")
        self.assertTrue(next(check for check in checks if check["check"] == "synthetic accounting source integrity")["ok"])
        self.assertFalse(next(check for check in checks if check["check"] == "synthetic accounting delivery disposition")["ok"])

    def drop_guards(self, table):
        original = []
        for trigger in self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)):
            original.append(trigger["sql"])
            self.c.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
        return original

    def test_deleted_acceptance_is_rejected_by_current_intent_read(self):
        intent_id, _ = self.queue()
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        sql = self.drop_guards("accounting_acceptances")
        self.c.db.execute("DELETE FROM accounting_acceptances")
        for statement in sql:
            self.c.db.execute(statement)
        with self.assertRaises(accounting.AccountingError):
            self.domain.intent(intent_id)

    def test_deleted_readback_is_rejected_by_reconciled_intent_read(self):
        intent_id, _ = self.queue()
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.worker.reconcile_once(intent_id, actor=ACCOUNTANT_LOGIN)
        sql = self.drop_guards("accounting_reconciliations")
        self.c.db.execute("DELETE FROM accounting_reconciliations")
        for statement in sql:
            self.c.db.execute(statement)
        with self.assertRaises(accounting.AccountingError):
            self.domain.intent(intent_id)

    def test_direct_readback_cannot_alias_integer_cents_to_float(self):
        intent_id, _ = self.queue()
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        claim = self.domain.claim_intent(intent_id, actor=ACCOUNTANT_LOGIN, purpose="reconciliation", worker_capability=self.worker._capability)
        acceptance = self.domain._inventory("acceptances")[0]
        readback = self.adapter.read_record(acceptance["provider_ref"])
        readback["payload"]["lines"][0]["debitCents"] = float(readback["payload"]["lines"][0]["debitCents"])
        before = self.snapshot()
        with self.assertRaises(accounting.AccountingError):
            self.domain.reconcile(intent_id, provider_result=readback, actor=ACCOUNTANT_LOGIN, lease_token=claim["lease_token"], worker_capability=self.worker._capability)
        self.assertEqual(before, self.snapshot())

    def test_uncovered_posted_source_reports_unresolved_accounting_disposition(self):
        checks = self.domain.close_checks("2026-11")
        disposition = next(check for check in checks if check["check"] == "synthetic accounting delivery disposition")
        self.assertFalse(disposition["ok"])
        self.assertIn(self.bill_id, disposition["detail"]["postedSourcesWithoutIntent"])

    def test_definite_provider_refusal_is_unresolved_accounting_not_reconciled(self):
        intent_id, _ = self.queue()
        self.adapter.queue_fault("submit", Fault.CREDENTIAL_EXPIRED)
        self.assertEqual(self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "refused")
        checks = self.domain.close_checks("2026-11")
        disposition = next(check for check in checks if check["check"] == "synthetic accounting delivery disposition")
        self.assertFalse(disposition["ok"])
        self.assertIn(intent_id, disposition["detail"]["pendingIntentIds"])

    def test_empty_plugin_is_inert_and_deleted_mapping_cannot_restore_inert_state(self):
        other = make_ap_practice_fixture()
        self.addCleanup(other.db.close)
        plugin = other.plugin("accounting")
        self.assertEqual(plugin.close_checks("2026-10"), [])
        project_id = other.ap_practice_records["visible_project_ids"][0]
        plugin.prepare_synthetic_mapping(project_id, actor=ACCOUNTANT_LOGIN, reason="Synthetic unplanned declaration")
        sql = []
        for trigger in other.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='accounting_mapping_versions'"):
            sql.append(trigger["sql"])
            other.db.execute('DROP TRIGGER "'+trigger["name"]+'"')
        other.db.execute("DELETE FROM accounting_mapping_versions")
        for statement in sql:
            other.db.execute(statement)
        checks = plugin.close_checks("2026-10")
        self.assertFalse(checks[0]["ok"])

    def test_worker_preflight_is_pure_and_lookup_cannot_submit_a_new_queue(self):
        intent_id, _ = self.queue()
        before = self.snapshot()
        pre = self.domain.worker_preflight(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(pre["provider_purpose"], "submit")
        with self.assertRaises(accounting.AccountingError):
            self.domain.worker_preflight(intent_id, actor=ACCOUNTANT_LOGIN, purpose="lookup")
        self.assertEqual(before, self.snapshot())

    def test_original_matched_invoice_binding_survives_correction_and_genuine_revision(self):
        commitment_id = self.c.ap_practice_records["prep_commitment_id"]
        commitment = self.c.commitments.get(commitment_id)
        bill = self.c.bills.certify(commitment_id=commitment_id, period_id="2026-10", actor=ACCOUNTANT_LOGIN,
                                   installed=[{"sov_line_id": commitment["sov"][0]["id"], "cumulative_installed": "10000.00"}])
        revision_id = self.c.ap_practice_records["visible_invoice_evidence_revision_ids"][0]
        revision = self.c.db.one("SELECT * FROM document_revisions WHERE id=?", (revision_id,))
        intake = self.c.plugin("ap_intake")
        invoice = intake.receive_invoice(bill["supplier_id"], "SYNTHETIC-ORIGINAL-001", "2026-10-14", bill["amount_due"], revision["content_hash"], ACCOUNTANT_LOGIN,
                                         project_id=bill["project_id"], commitment_id=commitment_id)
        intake.match(invoice["id"], ACCOUNTANT_LOGIN)
        match = self.c.request_approval("ap_intake.match_invoice", invoice["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(match["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(match["id"], actor=ACCOUNTANT_LOGIN)
        business = self.c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(business["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.post_bill(bill["id"], actor=ACCOUNTANT_LOGIN)
        approved = self.c.approvals.get(business["id"])["manifest"]["bindings"]["supplier_invoice"]
        plan = self.domain.prepare(bill["id"], self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.assertEqual(plan["payload"]["source"]["supplierInvoice"], approved)
        self.assertEqual(approved["id"], invoice["id"])
        self.assertEqual(approved["evidence_hash"], revision["content_hash"])
        self.assertEqual(approved["approval_id"], match["id"])
        self.c.bills.prepare_correction(bill["id"], "Synthetic measured quantity correction", ACCOUNTANT_LOGIN)
        correction = self.c.request_approval("bill.correct", bill["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(correction["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(correction["id"], actor=ACCOUNTANT_LOGIN, period_id="2026-11")
        intake.revise_invoice(invoice["id"], actor=ACCOUNTANT_LOGIN, reason="Synthetic amended invoice source", invoice_number="SYNTHETIC-REVISED-002")
        historic = self.domain.plan(plan["id"])
        self.assertEqual(historic["payload"]["source"]["supplierInvoice"], approved)
        self.assertEqual(historic["payload_hash"], plan["payload_hash"])
        with self.assertRaises(accounting.AccountingError):
            self.domain.queue_preflight(plan["id"])

    def payment(self):
        self.c.verify_destination(self.bill["supplier_id"], destination="SIM-PRACTICE-NO-DELIVERY", verified_by=BOOTSTRAP_LOGIN)
        approval = self.c.request_approval("payment.release", self.bill_id, actor_role="owner", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver=BOOTSTRAP_LOGIN, approver_role="owner")
        self.c.execute(approval["id"], actor=BOOTSTRAP_LOGIN)
        return self.c.db.one("SELECT * FROM payment_intents WHERE bill_id=?", (self.bill_id,))

    def credit(self, bill_id=None, *, post=False, period="2026-11"):
        bill_id = bill_id or self.bill_id
        bill = self.c.bills.get(bill_id)
        document = self.c.evidence.register_document(project_id=bill["project_id"], kind="supplier_credit_note", title="Synthetic accounting source credit", actor=ACCOUNTANT_LOGIN)
        revision = self.c.evidence.add_revision(document_id=document["id"], content="Synthetic accounting source credit", actor=ACCOUNTANT_LOGIN)
        note = self.c.bills.prepare_credit_note(bill_id, "100.00", "Synthetic measured work credit", revision["content_hash"], ACCOUNTANT_LOGIN)
        if post:
            approval = self.c.request_approval("bill.credit_note", note["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
            self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
            self.c.execute(approval["id"], actor=ACCOUNTANT_LOGIN, period_id=period)
        return self.c.bills.credit_note(note["id"])

    def test_active_genuine_payment_intent_blocks_current_source_and_new_submit(self):
        intent_id, _ = self.queue()
        payment = self.payment()
        self.assertEqual(payment["status"], "queued")
        self.assertEqual(self.c.bills.get(self.bill_id)["status"], "posted")
        before = self.snapshot()
        with self.assertRaises(accounting.AccountingError):
            self.domain.source(self.bill_id)
        with self.assertRaises(WorkerHeld):
            self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_active_genuine_credit_draft_blocks_current_source_and_new_submit(self):
        intent_id, _ = self.queue()
        self.credit()
        before = self.snapshot()
        with self.assertRaises(accounting.AccountingError):
            self.domain.source(self.bill_id)
        with self.assertRaises(WorkerHeld):
            self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_posted_partial_credit_blocks_current_source_while_bill_remains_posted(self):
        self.credit(post=True)
        self.assertEqual(self.c.bills.get(self.bill_id)["status"], "posted")
        self.assertEqual(str(self.c.bills.open_payable(self.bill_id)), "11011.10")
        before = self.snapshot()
        with self.assertRaises(accounting.AccountingError):
            self.domain.preparation_preflight(self.bill_id, self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_cancelled_payment_and_credit_leave_genuine_unpaid_source_eligible(self):
        payment = self.payment()
        self.c.payments.cancel_intent(payment["id"], "Synthetic unused payment withdrawal", BOOTSTRAP_LOGIN)
        credit = self.credit()
        self.c.bills.cancel_credit_note(credit["id"], "Synthetic unused credit withdrawal", ACCOUNTANT_LOGIN)
        before = self.snapshot()
        preflight = self.domain.preparation_preflight(self.bill_id, self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.assertEqual(preflight["source"]["net_ap_cents"], 1111110)
        self.assertEqual(before, self.snapshot())

    def test_returned_payment_leaves_original_unpaid_source_eligible(self):
        payment = self.payment()
        self.c.dispatch_payments(actor=BOOTSTRAP_LOGIN)
        event = self.c.provider.return_payment(payment["logical_op_id"], "Synthetic transfer returned")
        self.c.payments.ingest_event(event, actor=BOOTSTRAP_LOGIN)
        self.assertEqual(self.c.bills.get(self.bill_id)["status"], "posted")
        before = self.snapshot()
        self.domain.preparation_preflight(self.bill_id, self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.snapshot())

    def test_unknown_original_lookup_retains_obligation_after_genuine_partial_credit(self):
        intent_id, _ = self.queue()
        self.adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.credit(post=True)
        original = self.domain.plan(self.plan["id"])
        self.assertEqual(original["payload_hash"], self.plan["payload_hash"])
        self.assertEqual(self.worker.lookup_once(intent_id, actor=ACCOUNTANT_LOGIN)["status"], "simulated_accepted")
        self.assertEqual(self.adapter.calls["submit"], 1)

    def reconcile_original(self, plan):
        approval = self.c.request_approval(accounting.OP_QUEUE, plan["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        intent_id = self.c.execute(approval["id"], actor=ACCOUNTANT_LOGIN).result["intent_id"]
        self.worker.deliver_once(intent_id, actor=ACCOUNTANT_LOGIN)
        self.worker.reconcile_once(intent_id, actor=ACCOUNTANT_LOGIN)
        return intent_id

    def october_original(self):
        self.reconcile_original(self.plan)
        commitment = self.c.commitments.get(self.c.ap_practice_records["prep_commitment_id"])
        bill = self.c.bills.certify(commitment_id=commitment["id"], period_id="2026-10", actor=ACCOUNTANT_LOGIN,
                                   installed=[{"sov_line_id": commitment["sov"][0]["id"], "cumulative_installed": "10000.00"}])
        approval = self.c.request_approval("bill.approve", bill["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.post_bill(bill["id"], actor=ACCOUNTANT_LOGIN)
        plan = self.domain.prepare(bill["id"], self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        intent = self.reconcile_original(plan)
        return self.c.bills.get(bill["id"]), plan, intent

    def test_november_correction_reports_actual_reversal_period_after_october_reconciliation(self):
        bill, plan, intent = self.october_original()
        self.assertTrue(next(check for check in self.domain.close_checks("2026-11") if check["check"] == "synthetic accounting delivery disposition")["ok"])
        correction = self.c.bills.prepare_correction(bill["id"], "Synthetic October measurement correction in November", ACCOUNTANT_LOGIN)
        approval = self.c.request_approval("bill.correct", bill["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(approval["id"], actor=ACCOUNTANT_LOGIN, period_id="2026-11")
        check = next(check for check in self.domain.close_checks("2026-11") if check["check"] == "synthetic accounting delivery disposition")
        self.assertFalse(check["ok"])
        inverse = next(source for source in check["detail"]["unsupportedSources"] if source.get("kind") == "bill_correction")
        self.assertEqual(inverse["sourceId"], correction["id"])
        self.assertEqual(inverse["periodId"], "2026-11")
        self.assertEqual(self.domain.intent(intent)["status"], "reconciled")
        self.assertEqual(self.domain.plan(plan["id"])["payload_hash"], plan["payload_hash"])

    def test_november_credit_reports_actual_credit_period_after_october_reconciliation(self):
        bill, plan, intent = self.october_original()
        credit = self.credit(bill["id"], post=True)
        check = next(check for check in self.domain.close_checks("2026-11") if check["check"] == "synthetic accounting delivery disposition")
        self.assertFalse(check["ok"])
        adjustment = next(source for source in check["detail"]["unsupportedSources"] if source.get("kind") == "supplier_credit_note")
        self.assertEqual(adjustment["sourceId"], credit["id"])
        self.assertEqual(adjustment["journalId"], credit["journal_id"])
        self.assertEqual(adjustment["periodId"], "2026-11")
        self.assertEqual(self.domain.intent(intent)["status"], "reconciled")
        self.assertEqual(self.domain.plan(plan["id"])["payload_hash"], plan["payload_hash"])

if __name__ == "__main__":
    unittest.main()
