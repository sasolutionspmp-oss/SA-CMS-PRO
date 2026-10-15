"""Separate exact synthetic owner-bill send and current owned human duties."""
import unittest
from unittest.mock import patch

from apps.cipher.tests.test_ar_service import preparation_body
from apps.cipher.ar_practice_fixture import (make_ar_practice_fixture, PM_LOGIN, REVIEWER_LOGIN, POSTER_LOGIN,
    CONTROLLER_LOGIN, BOOTSTRAP_LOGIN)
from apps.cipher.core.approvals import ApprovalError, StaleApprovalError, material_hash
from apps.cipher.core.ids import canonical_json, loads


class ARSendServiceTests(unittest.TestCase):
    def setUp(self):
        self.c=make_ar_practice_fixture();self.addCleanup(self.c.db.close)
        self.domain=self.c.plugin("owner_billing")
        self.bill=self.domain.prepare(self.c.ar_practice_records["basis_id"],preparation_body(self.c),actor=PM_LOGIN)["primeBillId"]
        request=self.c.request_approval("prime_bill.approve",self.bill,actor_role="accountant",requested_by=PM_LOGIN)
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.original_post=self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
    def state(self):return tuple(self.c.db.conn.iterdump()),tuple(self.c.provider.submissions)
    def request(self):return self.c.request_approval("prime_bill.send",self.bill,actor_role="pm",requested_by=PM_LOGIN)
    def grant(self):
        request=self.request();self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant");return request

    def test_separate_request_grant_and_send_reviews_are_pure_and_synthetic_send_adds_no_AR(self):
        before=self.state();first=self.c.check_prime_bill_send_request(self.bill,requested_by=PM_LOGIN,actor_role="pm")
        second=self.c.check_prime_bill_send_request(self.bill,requested_by=PM_LOGIN,actor_role="pm")
        self.assertEqual(material_hash(first["manifest"]),material_hash(second["manifest"]));self.assertEqual(before,self.state())
        request=self.request();before=self.state()
        self.c.check_prime_bill_send_grant(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.assertEqual(before,self.state())
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"),0)
        before=self.state();self.c.check_prime_bill_send_execution(request["id"],actor=POSTER_LOGIN);self.assertEqual(before,self.state())
        completed=self.c.execute(request["id"],actor=POSTER_LOGIN)
        self.assertEqual(completed.result["channel"],"mail-sink");self.assertEqual(completed.result["status"],"sent")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"),1)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM outbox"),0)
        self.assertEqual(tuple(self.c.provider.submissions),())
        proof=self.domain.send_proof(self.bill)
        self.assertEqual(proof["originalMessage"]["balance_due"],"20250.00")
        self.assertEqual(proof["record"]["sent_by"],POSTER_LOGIN)

    def test_send_reviewer_is_independent_and_controller_owner_or_PM_role_label_cannot_supply_duty(self):
        request=self.request()
        for actor,role in ((PM_LOGIN,"pm"),(CONTROLLER_LOGIN,"pm"),(BOOTSTRAP_LOGIN,"pm"),(BOOTSTRAP_LOGIN,"owner")):
            before=self.state()
            with self.assertRaises(ApprovalError):self.c.approve(request["id"],approver=actor,approver_role=role)
            self.assertEqual(before,self.state())
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        for actor in (CONTROLLER_LOGIN,BOOTSTRAP_LOGIN):
            before=self.state()
            with self.assertRaises(ApprovalError):self.c.execute(request["id"],actor=actor)
            self.assertEqual(before,self.state())
        self.c.execute(request["id"],actor=PM_LOGIN)
        self.assertEqual(self.domain.send_proof(self.bill)["record"]["sent_by"],PM_LOGIN)

    def test_changed_real_partial_receipt_makes_original_send_review_stale_without_new_delivery(self):
        request=self.grant()
        self.c.receivables.record_collection(prime_bill_id=self.bill,period_id="2026-10",amount="1000.00",fee="0",method="check",
            provider_ref="SYNTHETIC-LEGACY-RECEIPT-CONTROL",actor=POSTER_LOGIN)
        before=self.state()
        with self.assertRaises(StaleApprovalError):self.c.check_prime_bill_send_execution(request["id"],actor=PM_LOGIN)
        self.assertEqual(before,self.state())
        with self.assertRaises(StaleApprovalError):self.c.execute(request["id"],actor=PM_LOGIN)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"),0)
        self.assertEqual(self.c.approvals.get(request["id"])["status"],"invalidated")

    def test_original_send_reviewer_current_own_duty_is_required_before_first_send(self):
        request=self.grant()
        self.c.plugin("people").end_membership(REVIEWER_LOGIN,self.c.ar_practice_records["project_id"],reason="Synthetic send reviewer left",actor=BOOTSTRAP_LOGIN)
        before=self.state()
        with self.assertRaises(ApprovalError):self.c.check_prime_bill_send_execution(request["id"],actor=PM_LOGIN)
        self.assertEqual(before,self.state())
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"),0)

    def test_caught_late_send_command_failure_restores_approval_message_and_command_bookkeeping(self):
        request=self.grant();record=self.c.audit.record
        def late(*values,**options):
            result=record(*values,**options)
            if values[1]=="command.executed":raise RuntimeError("Synthetic late owner send command fault")
            return result
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.c.audit,"record",side_effect=late),self.assertRaises(RuntimeError):self.c.execute(request["id"],actor=PM_LOGIN)
            self.assertEqual(before,self.state())
        self.c.execute(request["id"],actor=PM_LOGIN)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"),1)

    def test_current_send_duty_is_rechecked_inside_command_lock_after_original_approval_lookup(self):
        request=self.grant();self.c.execute(request["id"],actor=PM_LOGIN)
        original=self.domain.approval_proof;changed=False
        def ended_after_original_approval(*args,**kwargs):
            nonlocal changed
            proof=original(*args,**kwargs)
            if not changed:
                changed=True
                self.c.plugin("people").end_membership(PM_LOGIN,self.c.ar_practice_records["project_id"],
                    reason="Synthetic sender assignment ended before command lock",actor=BOOTSTRAP_LOGIN)
            return proof
        with patch.object(self.domain,"approval_proof",side_effect=ended_after_original_approval),self.assertRaises(ApprovalError):
            self.c.execute(request["id"],actor=PM_LOGIN)
        self.assertTrue(changed)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends"),1)

    def test_original_sent_command_replays_after_actual_partial_collection_and_refuses_forged_cached_channel(self):
        request=self.grant();completed=self.c.execute(request["id"],actor=PM_LOGIN)
        self.c.receivables.record_collection(prime_bill_id=self.bill,period_id="2026-10",amount="500.00",fee="0",method="check",
            provider_ref="SYNTHETIC-LATER-LEGACY-RECEIPT",actor=POSTER_LOGIN)
        replayed=self.c.execute(request["id"],actor=PM_LOGIN)
        self.assertTrue(replayed.replayed);self.assertEqual(replayed.result,completed.result)
        self.assertEqual(self.domain.send_proof(self.bill)["originalMessage"]["balance_due"],"20250.00")
        self.assertEqual(self.c.receivables.get(self.bill)["open"],"19750.00")
        row=self.c.db.one("SELECT * FROM idempotency WHERE op_id=?",("exec:"+request["id"],))
        forged=loads(row["result_json"]);forged["channel"]="unqualified-external-channel"
        self.c.db.execute("UPDATE idempotency SET result_json=? WHERE op_id=?",(canonical_json(forged),row["op_id"]))
        before=self.state()
        with self.assertRaises(ApprovalError):self.c.execute(request["id"],actor=PM_LOGIN)
        self.assertEqual(before,self.state())


if __name__=="__main__":unittest.main()
