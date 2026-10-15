"""Seven real source-bound AR reviews, current scope and no-effect verification."""
import copy
from datetime import timedelta
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.ar_contract import ARContract
from apps.cipher.ar_preflight import ARPreflight
from apps.cipher.ar_practice_fixture import (make_ar_practice_fixture, PM_LOGIN, REVIEWER_LOGIN, POSTER_LOGIN, CONTROLLER_LOGIN, BOOTSTRAP_LOGIN)
from apps.cipher.ar_sessions import ARIdentityRefusal
from apps.cipher.core.ids import parse_iso
from apps.cipher.tests.test_ar_service import preparation_body


class ARPreflightTests(unittest.TestCase):
    def setUp(self):
        self.c=make_ar_practice_fixture();self.addCleanup(self.c.db.close)
        self.r=self.c.ar_practice_records;self.domain=self.c.plugin("owner_billing")
        self.secret=b"actual-ar-preflight-private-server-secret-key"
        self.contract=ARContract(self.c,secret=self.secret);self.preflight=ARPreflight(self.c,self.contract,secret=self.secret)
        self.person,self.reviewer,self.poster,self.controller=(self.c.ar_practice_persona_people[key]["person_id"] for key in ("preparer","reviewer","poster","controller"))
    def state(self):return tuple(self.c.db.conn.iterdump()),self.c.db.conn.total_changes,tuple(self.c.provider.submissions)
    def review(self,person,action,resource,body=None):
        body={} if body is None else body;before=self.state()
        first=self.preflight.review(person,action,resource,body);second=self.preflight.review(person,action,resource,body)
        self.assertTrue(first["allowed"],first);self.assertEqual(first,second);self.assertEqual(before,self.state())
        context=self.preflight.verify(person,action,resource,{**body,"fingerprint":first["fingerprint"]},first["resourceVersion"])
        self.assertEqual(before,self.state());self.assertEqual(context["review"],first)
        self.assertNotIn("calculationHash",first["preview"]["calculation"]);self.assertNotIn("event",first["preview"]["period"])
        self.assertFalse(first["safeEffects"]["quickBooksAccepted"]);self.assertFalse(first["safeEffects"]["externalDelivery"])
        return first
    def prepared(self):return self.domain.prepare(self.r["basis_id"],preparation_body(self.c),actor=PM_LOGIN)["primeBillId"]
    def granted(self,bill):
        request=self.c.request_approval("prime_bill.approve",bill,actor_role="accountant",requested_by=PM_LOGIN)
        self.c.approve(request["id"],approver=REVIEWER_LOGIN,approver_role="accountant");return request["id"]

    def test_all_seven_reviews_are_stable_pure_and_describe_exact_actual_consequences(self):
        reviewed=self.review(self.person,"ownerBill.prepare",self.r["basis_id"],preparation_body(self.c))
        self.assertTrue(reviewed["safeEffects"]["createsDraft"]);self.assertEqual(reviewed["safeEffects"]["workingLedgerJournalDelta"],0)
        self.assertEqual(reviewed["preview"]["calculation"]["reviewedCertifiedCents"],2250000)
        bill=self.prepared();self.review(self.person,"ownerBill.requestApproval",bill)
        approval=self.c.request_approval("prime_bill.approve",bill,actor_role="accountant",requested_by=PM_LOGIN)
        reviewed=self.review(self.reviewer,"ownerBill.approve",approval["id"])
        self.assertTrue(reviewed["safeEffects"]["grantsApproval"]);self.assertEqual(reviewed["safeEffects"]["billStatus"],"draft")
        self.c.approve(approval["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        reviewed=self.review(self.poster,"ownerBill.post",bill)
        self.assertEqual(reviewed["safeEffects"]["workingLedgerJournalDelta"],1)
        self.assertEqual(reviewed["safeEffects"]["arReceivableDeltaCents"],2025000)
        self.assertEqual(reviewed["safeEffects"]["retainedARDeltaCents"],225000)
        self.c.post_prime_bill(bill,actor=POSTER_LOGIN)
        reviewed=self.review(self.person,"ownerBill.requestSend",bill)
        self.assertEqual(reviewed["preview"]["delivery"]["channel"],"mail-sink")
        approval=self.c.request_approval("prime_bill.send",bill,actor_role="pm",requested_by=PM_LOGIN)
        self.review(self.reviewer,"ownerBill.approveSend",approval["id"])
        self.c.approve(approval["id"],approver=REVIEWER_LOGIN,approver_role="accountant")
        reviewed=self.review(self.poster,"ownerBill.send",approval["id"])
        self.assertEqual(reviewed["safeEffects"]["syntheticSendDelta"],1)
        self.assertEqual(reviewed["safeEffects"]["workingLedgerJournalDelta"],0)

    def test_exact_input_or_source_change_cannot_reuse_original_review(self):
        body=preparation_body(self.c);review=self.review(self.person,"ownerBill.prepare",self.r["basis_id"],body)
        changed=copy.deepcopy(body);changed["lines"][0]["reviewedCumulative"]="11"
        before=self.state()
        with self.assertRaises(APRefusal) as caught:self.preflight.verify(self.person,"ownerBill.prepare",self.r["basis_id"],{**changed,"fingerprint":review["fingerprint"]},review["resourceVersion"])
        self.assertEqual(caught.exception.status,412);self.assertEqual(before,self.state())
        claim=self.c.evidence.revision(self.r["claim_revision_id"])
        self.c.evidence.add_revision(document_id=claim["document_id"],content="Synthetic genuine later claimed source",actor=PM_LOGIN)
        before=self.state();blocked=self.preflight.review(self.person,"ownerBill.prepare",self.r["basis_id"],body)
        self.assertFalse(blocked["allowed"]);self.assertIsNone(blocked["fingerprint"]);self.assertEqual(before,self.state())

    def test_hidden_basis_and_foreign_claim_review_are_scoped_before_private_entry_plan(self):
        before=self.state()
        with patch.object(self.domain,"prepare_preflight",side_effect=AssertionError("must scope before private plan")):
            with self.assertRaises(APRefusal) as caught:self.preflight.review(self.person,"ownerBill.prepare",self.r["hidden_basis_id"],preparation_body(self.c))
            self.assertEqual(caught.exception.status,404)
            for field,reference in (("claimRevisionId",self.r["hidden_claim_revision_id"]),("reviewRevisionId",self.r["hidden_review_revision_id"])):
                body=preparation_body(self.c);body[field]=reference
                with self.assertRaises(APRefusal) as caught:self.preflight.review(self.person,"ownerBill.prepare",self.r["basis_id"],body)
                self.assertEqual(caught.exception.status,404)
        self.assertEqual(before,self.state())

    def test_owner_role_or_controller_send_cannot_replace_actual_current_route_duty(self):
        bill=self.prepared();approval=self.granted(bill)
        owner=self.c.plugin("people").person_for(BOOTSTRAP_LOGIN)["id"]
        before=self.state()
        for person,action,resource in ((owner,"ownerBill.requestApproval",bill),(self.reviewer,"ownerBill.post",bill),
                                       (self.controller,"ownerBill.requestSend",bill)):
            try:
                review=self.preflight.review(person,action,resource,{})
            except (APRefusal,ARIdentityRefusal):
                pass
            else:self.assertFalse(review["allowed"])
        self.assertEqual(before,self.state())
        self.c.plugin("people").end_membership(POSTER_LOGIN,self.r["project_id"],reason="Synthetic current poster left",actor=BOOTSTRAP_LOGIN)
        with patch.object(self.domain,"posting_preflight",side_effect=AssertionError("must scope before private posting source")),self.assertRaises((APRefusal,ARIdentityRefusal)):
            self.preflight.review(self.poster,"ownerBill.post",bill,{})

    def test_expiry_advances_to_blocked_without_committing_terminal_bookkeeping(self):
        bill=self.prepared();approval=self.c.request_approval("prime_bill.approve",bill,actor_role="accountant",requested_by=PM_LOGIN)
        self.review(self.reviewer,"ownerBill.approve",approval["id"])
        after=parse_iso(approval["expires_at"])+timedelta(seconds=1);before=self.state()
        with patch("apps.cipher.domain.owner_billing.utcnow",return_value=after),patch("apps.cipher.ar_preflight.utcnow",return_value=after):
            blocked=self.preflight.review(self.reviewer,"ownerBill.approve",approval["id"],{})
        self.assertFalse(blocked["allowed"]);self.assertIsNone(blocked["fingerprint"])
        self.assertEqual(blocked["checks"][-1]["code"],"owner_authorization_expired")
        self.assertEqual(before,self.state());self.assertEqual(self.c.approvals.get(approval["id"])["status"],"pending")

    def test_bounded_exact_body_rejects_aliases_unknown_selectors_and_unreasoned_difference(self):
        for field,value in (("claimedCumulative",True),("reviewedCumulative",10.0),("claimedCumulative","1e2")):
            body=preparation_body(self.c);body["lines"][0][field]=value;before=self.state()
            with self.assertRaises(APRefusal):self.preflight.review(self.person,"ownerBill.prepare",self.r["basis_id"],body)
            self.assertEqual(before,self.state())
        for extra in ({"actor":POSTER_LOGIN},{"invoiceDate":"2026-10-01"},{"supplierId":"foreign"},{"retainageRate":"0"}):
            body={**preparation_body(self.c),**extra};before=self.state()
            with self.assertRaises(APRefusal):self.preflight.review(self.person,"ownerBill.prepare",self.r["basis_id"],body)
            self.assertEqual(before,self.state())
        body=preparation_body(self.c);body["lines"][0]["differenceReason"]="";before=self.state()
        self.assertFalse(self.preflight.review(self.person,"ownerBill.prepare",self.r["basis_id"],body)["allowed"])
        self.assertEqual(before,self.state())


if __name__=="__main__":unittest.main()
