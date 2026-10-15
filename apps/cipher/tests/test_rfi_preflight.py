"""Real issued-source RFI reviews, independent response and separate distribution."""
from datetime import timedelta
import unittest
from unittest.mock import patch
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import parse_iso
from apps.cipher.rfi_contract import RFIContract
from apps.cipher.rfi_preflight import RFIPreflight
from apps.cipher.rfi_practice_fixture import make_rfi_practice_fixture, STAFF_LOGIN, PM_LOGIN, REVIEWER_LOGIN, BOOTSTRAP_LOGIN

class RFIPreflightTests(unittest.TestCase):
    def setUp(self):
        self.c=make_rfi_practice_fixture();self.addCleanup(self.c.db.close);self.domain=self.c.plugin('rfi_controls')
        self.records=self.c.rfi_practice_records;self.project=self.records['project_id'];self.people=self.c.rfi_practice_persona_people
        self.staff,self.pm,self.reviewer=(self.people[key]['person_id'] for key in ('staff','pm','reviewer'))
        self.secret=b'rfi-original-review-key-with-thirty-two-bytes'
        self.contract=RFIContract(self.c,secret=self.secret);self.preflight=RFIPreflight(self.c,self.contract,secret=self.secret)
        self.body={'subject':'Synthetic drain alignment','question':'Confirm the authored drain detail at grid C4.',
                   'drawingRevisionIds':[self.records['drawing_revision_id']],'documentRevisionIds':[self.records['document_revision_id']]}
        self.response={'responseText':'Use the documented alignment pending separate change review.','costImpact':'1234.56','scheduleImpactDays':3}
    def snapshot(self):return tuple(self.c.db.conn.iterdump()),self.c.db.conn.total_changes,tuple(self.c.provider.submissions)
    def reviewed(self,person,action,resource,body):
        before=self.snapshot();review=self.preflight.review(person,action,resource,body);self.assertEqual(self.snapshot(),before)
        self.assertTrue(review['allowed'],review);self.assertEqual(review,self.preflight.review(person,action,resource,body))
        context=self.preflight.verify(person,action,resource,{**body,'fingerprint':review['fingerprint']},review['resourceVersion']);self.assertEqual(self.snapshot(),before)
        self.assertEqual(context['typed'],body);self.assertEqual(context['operationRole'],None if action in ('rfi.create','rfi.draftResponse') else 'pm')
        effects=review['safeEffects']
        for key in ('journalDelta','changeDraftDelta','changeExecutionDelta','commitmentDelta','contractValueDeltaCents','budgetDeltaCents','scheduleBaselineDeltaDays'):self.assertEqual(effects[key],0)
        for key in ('externalDistribution','engineeringCertification','adoptsPotentialImpacts'):self.assertIs(effects[key],False)
        self.assertIs(effects['mailSinkOnly'],True)
        return review,context
    def created(self):return self.domain.create(self.project,self.body,actor=STAFF_LOGIN)['id']
    def requested(self):
        rid=self.created();self.domain.draft_response(rid,self.response,actor=STAFF_LOGIN)
        approval=self.c.request_approval('field.respond_rfi',rid,actor_role='pm',requested_by=PM_LOGIN)
        return rid,approval
    def test_all_nine_reviews_are_pure_and_only_exact_original_native_acts_have_effects(self):
        review,_=self.reviewed(self.staff,'rfi.create',self.project,self.body);self.assertEqual(review['safeEffects']['rfisDelta'],1);self.assertEqual(review['safeEffects']['drawingReferencesDelta'],1)
        rid=self.created();review,_=self.reviewed(self.staff,'rfi.draftResponse',rid,self.response)
        self.assertEqual(review['preview']['costImpactCents'],123456);self.assertEqual(review['safeEffects']['responseRevisionsDelta'],1)
        self.domain.draft_response(rid,self.response,actor=STAFF_LOGIN)
        review,_=self.reviewed(self.pm,'rfi.requestResponse',rid,{});self.assertEqual(review['safeEffects']['approvalStatus'],'pending')
        response=self.c.request_approval('field.respond_rfi',rid,actor_role='pm',requested_by=PM_LOGIN)
        review,_=self.reviewed(self.reviewer,'rfi.approveResponse',response['id'],{});self.assertEqual(review['safeEffects']['approvalStatus'],'granted')
        self.c.approve(response['id'],approver=REVIEWER_LOGIN,approver_role='pm');self.assertEqual(self.c.plugin('field').rfi(rid)['status'],'open')
        review,_=self.reviewed(self.pm,'rfi.applyResponse',response['id'],{});self.assertEqual(review['safeEffects']['rfiStatus'],'answered');self.c.execute(response['id'],actor=PM_LOGIN)
        body={'recipients':[self.records['allowed_recipients'][0]]};self.reviewed(self.pm,'rfi.setDistribution',rid,body);self.domain.set_distribution_list(rid,body,actor=PM_LOGIN)
        self.reviewed(self.pm,'rfi.requestDistribution',rid,{});distribution=self.c.request_approval('field.distribute_rfi',rid,actor_role='pm',requested_by=PM_LOGIN)
        self.reviewed(self.reviewer,'rfi.approveDistribution',distribution['id'],{});self.c.approve(distribution['id'],approver=REVIEWER_LOGIN,approver_role='pm')
        review,_=self.reviewed(self.pm,'rfi.distribute',distribution['id'],{});self.assertEqual(review['safeEffects']['syntheticDistributionsDelta'],1);self.c.execute(distribution['id'],actor=PM_LOGIN)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfi_distributions'),1);self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM journals'),0);self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM changes'),0)
    def test_changed_typed_body_record_version_or_private_key_cannot_apply_old_review(self):
        review=self.preflight.review(self.staff,'rfi.create',self.project,self.body);before=self.snapshot()
        for body,version,preflight in (({**self.body,'question':self.body['question']+' Altered.'},review['resourceVersion'],self.preflight),(self.body,'different-version',self.preflight),(self.body,review['resourceVersion'],RFIPreflight(self.c,self.contract,secret=b'another-rfi-private-server-key-at-least-32-bytes'))):
            with self.assertRaises(APRefusal) as error:preflight.verify(self.staff,'rfi.create',self.project,{**body,'fingerprint':review['fingerprint']},version)
            self.assertEqual(error.exception.status,412);self.assertEqual(self.snapshot(),before)
    def test_hidden_and_staff_pm_denials_precede_private_native_source_checks(self):
        rid=self.created();before=self.snapshot()
        with patch.object(self.domain,'create_preflight',side_effect=AssertionError('Hidden sources read')) as read:
            with self.assertRaises(APRefusal) as error:self.preflight.review(self.staff,'rfi.create',self.records['hidden_project_id'],self.body)
            self.assertEqual(error.exception.status,404);read.assert_not_called()
        with patch.object(self.domain,'response_request_preflight',side_effect=AssertionError('PM sources read')) as read:
            with self.assertRaises(APRefusal) as error:self.preflight.review(self.staff,'rfi.requestResponse',rid,{})
            self.assertEqual(error.exception.status,403);read.assert_not_called()
        self.assertEqual(self.snapshot(),before)
    def test_original_response_author_and_requester_cannot_grant_and_pending_is_not_duplicated(self):
        rid,approval=self.requested();before=self.snapshot()
        for action,resource in (('rfi.requestResponse',rid),('rfi.approveResponse',approval['id'])):
            review=self.preflight.review(self.pm,action,resource,{});self.assertFalse(review['allowed']);self.assertIsNone(review['fingerprint'])
        self.assertEqual(self.snapshot(),before)
    def test_draft_review_discloses_every_native_open_approval_invalidation(self):
        rid,approval=self.requested();body={**self.response,'responseText':'A genuinely later response draft.'}
        review,_=self.reviewed(self.staff,'rfi.draftResponse',rid,body);self.assertEqual(review['safeEffects']['invalidatedApprovalsDelta'],1)
        self.domain.draft_response(rid,body,actor=STAFF_LOGIN);self.assertEqual(self.c.approvals.get(approval['id'])['status'],'invalidated')
    def test_original_native_deadline_is_rechecked_purely(self):
        rid,approval=self.requested();self.c.approve(approval['id'],approver=REVIEWER_LOGIN,approver_role='pm');deadline=parse_iso(approval['expires_at'])+timedelta(seconds=1);before=self.snapshot()
        with patch('apps.cipher.domain.rfi_controls.utcnow',return_value=deadline):
            review=self.preflight.review(self.pm,'rfi.applyResponse',approval['id'],{});self.assertFalse(review['allowed']);self.assertIsNone(review['fingerprint'])
        self.assertEqual(self.snapshot(),before)
    def test_genuine_supporting_head_change_refuses_old_create_definitively_before_fresh_current_review(self):
        review=self.preflight.review(self.staff,'rfi.create',self.project,self.body)
        revision=self.c.evidence.add_revision(document_id=self.records['document_id'],content='Genuinely later synthetic supporting specification.',actor=PM_LOGIN)
        before=self.snapshot()
        with self.assertRaises(APRefusal) as error:
            self.preflight.verify(self.staff,'rfi.create',self.project,{**self.body,'fingerprint':review['fingerprint']},review['resourceVersion'])
        self.assertEqual(error.exception.status,412);self.assertEqual(error.exception.code,'record_changed');self.assertEqual(self.snapshot(),before)
        body={**self.body,'documentRevisionIds':[revision['id']]};fresh,_=self.reviewed(self.staff,'rfi.create',self.project,body)
        self.assertNotEqual(fresh['resourceVersion'],review['resourceVersion']);self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfis'),0)

    def test_actual_pm_membership_ending_revokes_old_review_before_native_source(self):
        rid=self.created();self.domain.draft_response(rid,self.response,actor=STAFF_LOGIN);review=self.preflight.review(self.pm,'rfi.requestResponse',rid,{})
        self.c.plugin('people').end_membership(PM_LOGIN,self.project,reason='Synthetic ended RFI assignment',actor=BOOTSTRAP_LOGIN);before=self.snapshot()
        with patch.object(self.domain,'response_request_preflight',side_effect=AssertionError('Revoked PM read source')) as read:
            with self.assertRaises(APRefusal):self.preflight.verify(self.pm,'rfi.requestResponse',rid,{'fingerprint':review['fingerprint']},review['resourceVersion'])
            read.assert_not_called()
        self.assertEqual(self.snapshot(),before)

if __name__=='__main__':unittest.main()
