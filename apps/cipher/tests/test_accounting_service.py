"""The human accounting queue consumes one verified grant and no money."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, BOOTSTRAP_LOGIN, PM_LOGIN, REVIEWER_LOGIN, make_ap_practice_fixture
from apps.cipher.core.approvals import ApprovalError, StaleApprovalError
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.ricky_sdk import operation_class, operation_route
from apps.cipher.service import Cipher


class AccountingServiceTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.module = self.c.plugin("accounting")
        self.bill_id = self.c.ap_practice_records["approved_bill_id"]
        self.c.post_bill(self.bill_id, actor=ACCOUNTANT_LOGIN, period_id="2026-10", reason="Synthetic accounting source")
        bill = self.c.bills.get(self.bill_id)
        mapping = self.module.prepare_synthetic_mapping(bill["project_id"], actor=ACCOUNTANT_LOGIN, reason="Synthetic practice mapping")
        self.plan = self.module.prepare(self.bill_id, mapping["id"], actor=ACCOUNTANT_LOGIN)

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def request(self):
        return self.c.request_approval("accounting.queue", self.plan["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)

    def grant(self):
        approval = self.request()
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        return approval["id"]

    def test_request_and_grant_and_execute_checks_are_pure(self):
        before, changes = self.state(), self.c.db.conn.total_changes
        checked = self.c.check_accounting_queue_request(self.plan["id"], requested_by=ACCOUNTANT_LOGIN)
        self.assertEqual(checked["manifest"]["operation"], "accounting.queue")
        self.assertEqual(before, self.state())
        self.assertEqual(changes, self.c.db.conn.total_changes)
        approval = self.request()
        before, changes = self.state(), self.c.db.conn.total_changes
        self.c.check_accounting_queue_grant(approval["id"], approver=REVIEWER_LOGIN)
        self.assertEqual(before, self.state())
        self.assertEqual(changes, self.c.db.conn.total_changes)
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        before, changes = self.state(), self.c.db.conn.total_changes
        self.c.check_accounting_queue_execution(approval["id"], actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.state())
        self.assertEqual(changes, self.c.db.conn.total_changes)

    def test_distinct_actual_accountant_grants_then_original_queues_one_ledger_free_intent(self):
        approval_id = self.grant()
        journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        result = self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result.result["status"], "queued")
        self.assertEqual(self.c.approvals.get(approval_id)["status"], "consumed")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.assertEqual(self.c.provider.submissions, [])
        repeat = self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        self.assertTrue(repeat.replayed)
        self.assertEqual(repeat.result, result.result)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 1)

    def test_self_grant_and_pm_grant_are_refused_without_writes(self):
        approval = self.request()
        for login, role in ((ACCOUNTANT_LOGIN, "accountant"), (PM_LOGIN, "pm"), (PM_LOGIN, "accountant")):
            before = self.state()
            with self.subTest(login=login, role=role), self.assertRaises(IdentityRefused):
                self.c.approve(approval["id"], approver=login, approver_role=role)
            self.assertEqual(before, self.state())

    def test_owner_wildcard_and_controller_text_do_not_supply_actual_accounting_authority(self):
        for login, role in ((BOOTSTRAP_LOGIN, "owner"), (BOOTSTRAP_LOGIN, "accountant"), (ACCOUNTANT_LOGIN, "controller")):
            before = self.state()
            with self.subTest(login=login, role=role), self.assertRaises(IdentityRefused):
                self.c.request_approval("accounting.queue", self.plan["id"], actor_role=role, requested_by=login)
            self.assertEqual(before, self.state())

    def test_ricky_has_no_request_execute_or_delivery_route(self):
        self.assertEqual(operation_class("accounting.queue"), "restricted")
        self.assertFalse(operation_route("accounting.queue")["reachable"])
        self.assertEqual(operation_route("accounting.queue")["tools"], [])

    def test_mapping_change_blocks_pure_grant_then_actual_grant_invalidates_only_old_approval(self):
        approval = self.request()
        self.module.prepare_synthetic_mapping(self.plan["project_id"], actor=ACCOUNTANT_LOGIN, reason="New fixed synthetic mapping")
        before = self.state()
        with self.assertRaises(StaleApprovalError):
            self.c.check_accounting_queue_grant(approval["id"], approver=REVIEWER_LOGIN)
        self.assertEqual(before, self.state())
        with self.assertRaises(StaleApprovalError):
            self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.assertEqual(self.c.approvals.get(approval["id"])["status"], "invalidated")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 0)

    def test_corrected_source_blocks_granted_queue_and_leaves_original_posting_untouched(self):
        approval_id = self.grant()
        original_receipt = self.c.bills.posting_receipt(self.bill_id)
        self.c.bills.prepare_correction(self.bill_id, "Synthetic original source correction", ACCOUNTANT_LOGIN)
        correction = self.c.request_approval("bill.correct", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(correction["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        self.c.execute(correction["id"], actor=ACCOUNTANT_LOGIN, period_id="2026-11")
        journals = self.c.db.scalar("SELECT COUNT(*) FROM journals")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(self.c.approvals.get(approval_id)["status"], "invalidated")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 0)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"), journals)
        self.assertEqual(self.c.bills.posting_receipt(self.bill_id), original_receipt)

    def test_whole_queue_command_rolls_back_late_failure_caught_by_outer_transaction(self):
        approval_id = self.grant()
        original = self.c.audit.record
        def late_fault(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == "command.executed":
                raise RuntimeError("Injected accounting bookkeeping failure")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=late_fault), self.assertRaises(RuntimeError):
                self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
            self.assertEqual(before, self.state())
            self.assertEqual(self.c.approvals.get(approval_id)["status"], "granted")
        result = self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(result.result["status"], "queued")

    def test_request_audit_failure_caught_by_outer_transaction_leaves_no_unreceipted_approval(self):
        original = self.c.audit.record
        def request_fault(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == "approval.requested":
                raise RuntimeError("Injected accounting request audit failure")
            return result
        with self.c.db.transaction():
            before = self.state()
            with patch.object(self.c.audit, "record", side_effect=request_fault), self.assertRaises(RuntimeError):
                self.request()
            self.assertEqual(before, self.state())

    def test_explicit_period_and_foreign_person_cache_replay_are_refused(self):
        approval_id = self.grant()
        before = self.state()
        with self.assertRaises(ApprovalError):
            self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN, period_id="2026-11")
        self.assertEqual(before, self.state())
        self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        before = self.state()
        with self.assertRaises(Exception):
            self.c.execute(approval_id, actor=REVIEWER_LOGIN)
        self.assertEqual(before, self.state())

    def test_consumed_queue_cache_cannot_hide_deleted_original_intent(self):
        approval_id = self.grant()
        self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='accounting_intents'"):
            self.c.db.execute('DROP TRIGGER "' + trigger["name"] + '"')
        self.c.db.execute("DELETE FROM accounting_intents")
        before = self.state()
        with self.assertRaises(Exception):
            self.c.execute(approval_id, actor=ACCOUNTANT_LOGIN)
        self.assertEqual(before, self.state())


class DormantAccountingTests(unittest.TestCase):
    def test_required_plugin_does_not_seed_mapping_intent_or_close_obligation(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        c.ledger.open_period("2026-10", name="October", start_date="2026-10-01", end_date="2026-10-31", actor="owner")
        accounting = c.plugin("accounting")
        for kind in ("mapping_versions", "plans", "intents", "leases", "attempts", "attempt_results", "acceptances", "reconciliations"):
            self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM accounting_" + kind), 0)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'accounting.%'"), 0)
        self.assertEqual(accounting.close_checks("2026-10"), [])
        self.assertEqual(c.provider.submissions, [])
