"""Native current-person owner billing request, grant and separate posting."""
import unittest
from unittest.mock import patch

from apps.cipher.ar_practice_fixture import (make_ar_practice_fixture, PM_LOGIN, REVIEWER_LOGIN,
    POSTER_LOGIN, CONTROLLER_LOGIN, BOOTSTRAP_LOGIN)
from apps.cipher.core.approvals import ApprovalError, material_hash
from apps.cipher.domain.owner_billing import OwnerBillingError


def preparation_body(c):
    r=c.ar_practice_records
    return {"claimRevisionId":r["claim_revision_id"],"reviewRevisionId":r["review_revision_id"],"periodId":r["period_id"],
        "lines":[{"lineId":"U1","claimedCumulative":"12","reviewedCumulative":"10",
                  "differenceReason":"Two claimed units await the stated source verification.",
                  "claimSourceLocator":"Claim page 1 / owner item U1","reviewSourceLocator":"PM review page 1 / owner item U1"},
                 {"lineId":"L2","claimedCumulative":"15000.00","reviewedCumulative":"12500.00",
                  "differenceReason":"Reviewed documented lump-sum work excludes the incomplete portion.",
                  "claimSourceLocator":"Claim page 2 / owner item L2","reviewSourceLocator":"PM review page 2 / owner item L2"}]}


class ARNativeServiceTests(unittest.TestCase):
    def setUp(self):
        self.c=make_ar_practice_fixture();self.addCleanup(self.c.db.close)
        self.domain=self.c.plugin("owner_billing")
        prepared=self.domain.prepare(self.c.ar_practice_records["basis_id"],preparation_body(self.c),actor=PM_LOGIN)
        self.bill=prepared["primeBillId"]
    def state(self):return tuple(self.c.db.conn.iterdump()),tuple(self.c.provider.submissions)
    def request(self):return self.c.request_approval("prime_bill.approve",self.bill,actor_role="accountant",requested_by=PM_LOGIN)
    def grant(self,reviewer=REVIEWER_LOGIN,role="accountant"):
        request=self.request();self.c.approve(request["id"],approver=reviewer,approver_role=role);return request

    def test_actual_request_grant_and_post_reviews_are_pure_and_real_grant_has_no_journal(self):
        before=self.state()
        first=self.c.check_prime_bill_request(self.bill,requested_by=PM_LOGIN,actor_role="accountant")
        second=self.c.check_prime_bill_request(self.bill,requested_by=PM_LOGIN,actor_role="accountant")
        self.assertEqual(material_hash(first["manifest"]),material_hash(second["manifest"]))
        self.assertEqual(before,self.state())
        request=self.request();before=self.state()
        checked=self.c.check_prime_bill_grant(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.assertEqual(checked["approval"]["id"],request["id"]);self.assertEqual(before,self.state())
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),0)
        self.assertEqual(self.c.receivables.get(self.bill)["status"],"draft")
        self.assertEqual(self.domain.grant_proof(self.bill)["record"]["approval_id"],request["id"])
        before=self.state();post=self.c.check_prime_bill_post(self.bill,actor=POSTER_LOGIN)
        self.assertEqual(post["postingPeriodId"],"2026-10");self.assertEqual(before,self.state())
        completed=self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        self.assertEqual(completed.result["status"],"posted")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),1)
        self.assertEqual(self.c.approvals.get(request["id"])["status"],"consumed")
        self.assertEqual(self.c.receivables.ar_open_items(self.c.ar_practice_records["project_id"])["subledger_total"],"20250.00")

    def test_review_and_post_need_actual_accounting_and_distinct_original_reviewer(self):
        request=self.request()
        for actor,role in ((PM_LOGIN,"accountant"),(BOOTSTRAP_LOGIN,"controller"),(BOOTSTRAP_LOGIN,"owner")):
            before=self.state()
            with self.assertRaises(ApprovalError):self.c.approve(request["id"],approver=actor,approver_role=role)
            self.assertEqual(before,self.state())
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        before=self.state()
        with self.assertRaises(ApprovalError):self.c.post_prime_bill(self.bill,actor=REVIEWER_LOGIN)
        with self.assertRaises(ApprovalError):self.c.execute(request["id"],actor=POSTER_LOGIN)
        self.assertEqual(before,self.state())
        self.c.post_prime_bill(self.bill,actor=CONTROLLER_LOGIN)
        self.assertEqual(self.domain.posting_receipt(self.bill)["actor"],CONTROLLER_LOGIN)

    def test_explicit_controller_can_grant_but_cannot_post_own_grant(self):
        request=self.grant(CONTROLLER_LOGIN,"controller")
        before=self.state()
        with self.assertRaises(ApprovalError):self.c.check_prime_bill_post(self.bill,actor=CONTROLLER_LOGIN)
        self.assertEqual(before,self.state())
        self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        self.assertEqual(self.c.approvals.get(request["id"])["consumed_by"],POSTER_LOGIN)

    def test_post_completed_cache_requires_current_own_duty_and_original_result_proof(self):
        self.grant();completed=self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        tables=[row["name"] for row in self.c.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name!='audit_log' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        before={table:self.c.db.query('SELECT * FROM "'+table+'"') for table in tables}
        audit_count=self.c.db.scalar("SELECT COUNT(*) FROM audit_log")
        replayed=self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        self.assertTrue(replayed.replayed);self.assertEqual(replayed.result,completed.result)
        self.assertEqual(before,{table:self.c.db.query('SELECT * FROM "'+table+'"') for table in tables})
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM audit_log"),audit_count+1)
        self.assertEqual(self.c.audit.entries()[-1]["action"],"command.replayed")
        self.c.plugin("people").end_membership(POSTER_LOGIN,self.c.ar_practice_records["project_id"],reason="Synthetic posting duty ended",actor=BOOTSTRAP_LOGIN)
        before=self.state()
        with patch.object(self.c.commands,"run",side_effect=AssertionError("must not probe original command")),self.assertRaises(ApprovalError):
            self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        self.assertEqual(before,self.state())

    def test_actual_dual_role_requester_and_login_alias_cannot_review_their_own_financial_request(self):
        people=self.c.plugin("people")
        role=people.request_grant(PM_LOGIN,"accountant",project_id=self.c.ar_practice_records["project_id"],
            reason="Synthetic dual-duty separation control",actor=REVIEWER_LOGIN)
        authorization=self.c.request_approval("people.grant_role",role["id"],actor_role="owner",requested_by=REVIEWER_LOGIN)
        self.c.approve(authorization["id"],approver=BOOTSTRAP_LOGIN,approver_role="owner")
        self.c.execute(authorization["id"],actor=BOOTSTRAP_LOGIN)
        request=self.request();before=self.state()
        with self.assertRaises(ApprovalError):self.c.check_prime_bill_grant(request["id"],approver=PM_LOGIN.upper(),approver_role="accountant")
        with self.assertRaises(ApprovalError):self.c.approve(request["id"],approver=PM_LOGIN.upper(),approver_role="accountant")
        self.assertEqual(before,self.state())
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.c.post_prime_bill(self.bill,actor=PM_LOGIN)
        self.assertEqual(self.domain.posting_receipt(self.bill)["actor"],PM_LOGIN)

    def test_current_posting_duty_is_rechecked_inside_command_lock_after_original_source_lookup(self):
        self.grant();self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        original=self.domain.grant_proof;changed=False
        def ended_after_original_source(*args,**kwargs):
            nonlocal changed
            proof=original(*args,**kwargs)
            if not changed:
                changed=True
                self.c.plugin("people").end_membership(POSTER_LOGIN,self.c.ar_practice_records["project_id"],
                    reason="Synthetic assignment ended between source review and command lock",actor=BOOTSTRAP_LOGIN)
            return proof
        with patch.object(self.domain,"grant_proof",side_effect=ended_after_original_source),self.assertRaises(ApprovalError):
            self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        self.assertTrue(changed)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),1)

    def test_caught_late_post_command_failure_rolls_back_grant_journal_source_and_cache(self):
        request=self.grant();record=self.c.audit.record
        def late(*values,**options):
            result=record(*values,**options)
            if values[1]=="command.executed":raise RuntimeError("Synthetic late owner posting command audit failure")
            return result
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.c.audit,"record",side_effect=late),self.assertRaises(RuntimeError):self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
            self.assertEqual(before,self.state())
            self.assertEqual(self.c.approvals.get(request["id"])["status"],"granted")
        self.c.post_prime_bill(self.bill,actor=POSTER_LOGIN)
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),1)

    def test_caught_late_business_grant_record_failure_rolls_back_human_grant(self):
        request=self.request();record=self.c.audit.record
        def late(*values,**options):
            result=record(*values,**options)
            if values[1]=="owner_billing.grants_recorded":raise RuntimeError("Synthetic late owner business grant failure")
            return result
        with self.c.db.transaction():
            before=self.state()
            with patch.object(self.c.audit,"record",side_effect=late),self.assertRaises(RuntimeError):
                self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
            self.assertEqual(before,self.state())
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journals"),0)


if __name__=="__main__":unittest.main()
