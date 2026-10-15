"""Actual native response and separately authorized synthetic distribution."""
import unittest
from unittest.mock import patch

from apps.cipher.core.approvals import ApprovalError,StaleApprovalError
from apps.cipher.core.ids import utcnow_iso
from apps.cipher.domain.rfi_controls import RFIError,RECIPIENTS
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.tests.rfi_helpers import RFIWorld,OWNER,STAFF,PM,REVIEWER,OTHER


class RFIWorkflowTests(unittest.TestCase):
    def setUp(self):self.w=RFIWorld();self.c=self.w.c;self.r=self.w.module;self.rid=self.w.rfi['id']
    def tearDown(self):self.c.db.close()

    def test_native_full_response_and_separate_distribution_leave_books_unchanged(self):
        self.w.draft();ap=self.w.request_response()
        self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        self.assertEqual(self.r.source_proof(self.rid)['native']['status'],'open')
        answer=self.c.execute(ap['id'],actor=PM)
        self.assertEqual(answer.result['status'],'answered')
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfi_distributions'),0)
        self.r.set_distribution_list(self.rid,{'recipients':list(RECIPIENTS[:2])},actor=PM)
        send=self.c.request_approval('field.distribute_rfi',self.rid,actor_role='pm',requested_by=PM)
        self.c.approve(send['id'],approver=REVIEWER,approver_role='pm')
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfi_distributions'),0)
        distributed=self.c.execute(send['id'],actor=PM)
        self.assertEqual(distributed.result['channel'],'mail-sink')
        self.assertEqual(distributed.result['recipients'],list(RECIPIENTS[:2]))
        for table in ('journals','changes','commitments'):
            self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM '+table),0)

    def test_staff_can_draft_but_cannot_request_or_answer(self):
        self.w.draft()
        with self.assertRaises(ApprovalError):self.c.request_approval('field.respond_rfi',self.rid,actor_role='pm',requested_by=STAFF)
        ap=self.w.request_response();self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        with self.assertRaises(ApprovalError):self.c.execute(ap['id'],actor=STAFF)

    def test_response_author_and_requester_both_cannot_be_reviewer(self):
        self.w.draft(actor=REVIEWER);ap=self.w.request_response()
        for actor in (PM,REVIEWER):
            with self.subTest(actor=actor),self.assertRaises((ApprovalError,IdentityRefused)):self.c.approve(ap['id'],approver=actor,approver_role='pm')

    def test_entity_owner_and_hidden_pm_do_not_gain_rfi_decision_authority(self):
        self.w.draft();ap=self.w.request_response()
        for actor,role in ((OWNER,'owner'),(OTHER,'pm')):
            with self.subTest(actor=actor),self.assertRaises((ApprovalError,IdentityRefused)):self.c.approve(ap['id'],approver=actor,approver_role=role)

    def test_genuine_source_head_change_stales_old_grant_and_new_review_retains_exact_citation(self):
        self.w.draft();ap=self.w.request_response();self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        newer=self.c.evidence.add_revision(document_id=self.w.support_doc,content='Genuine later drainage note',actor=STAFF)
        with self.assertRaises(StaleApprovalError):self.c.execute(ap['id'],actor=PM)
        fresh=self.w.request_response();self.c.approve(fresh['id'],approver=REVIEWER,approver_role='pm');self.c.execute(fresh['id'],actor=PM)
        proof=self.r.source_proof(self.rid)
        self.assertEqual(proof['documents'][0]['revision']['id'],self.w.support['id'])
        self.assertEqual(proof['documents'][0]['currentRevision']['id'],newer['id'])

    def test_genuine_new_drawing_issue_requires_fresh_review_retaining_original_issued_citation(self):
        self.w.draft();ap=self.w.request_response();self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        evidence=self.c.evidence.add_revision(document_id=self.w.drawing_doc,content='Genuine synthetic drawing B',actor=PM)
        drawings=self.c.plugin('drawing');revision=drawings.add_revision(self.w.drawing_id,'B',evidence['id'],actor=PM)
        issue=self.c.request_approval('drawing.issue',revision['id'],actor_role='pm',requested_by=PM)
        self.c.approve(issue['id'],approver=REVIEWER,approver_role='pm');self.c.execute(issue['id'],actor=PM,period_id='RFI1')
        with self.assertRaises(StaleApprovalError):self.c.execute(ap['id'],actor=PM)
        fresh=self.w.request_response();self.c.approve(fresh['id'],approver=REVIEWER,approver_role='pm');self.c.execute(fresh['id'],actor=PM)
        source=self.r.source_proof(self.rid);drawing=source['drawings'][0]
        self.assertEqual(drawing['revision']['id'],self.w.drawing['id'])
        self.assertEqual(drawing['current']['issuedRevisionId'],revision['id'])

    def test_original_answer_proof_survives_genuine_later_rights_withdrawal(self):
        rights=self.c.plugin('rights');license=rights.register_license('Synthetic','Later source use withdrawal','1','Holder',['project_use'],actor=OWNER)
        rights.tag_document(self.w.support_doc,license['id'],actor=OWNER)
        approval,result=self.w.answer()
        rights.update_license(license['id'],permitted_uses=['internal_reference'],note='Synthetic later permission withdrawal',actor=OWNER)
        self.assertEqual(self.r.effect_proof(approval['id'])['result'],result.result)
        self.assertEqual(self.c.execute(approval['id'],actor=PM).result,result.result)
        with self.assertRaises(ApprovalError):self.r.source_proof(self.rid,current=True)

    def test_original_answer_replay_survives_genuine_new_head_and_recipient_version(self):
        ap,result=self.w.answer();self.r.set_distribution_list(self.rid,{'recipients':[RECIPIENTS[0]]},actor=PM)
        self.c.evidence.add_revision(document_id=self.w.support_doc,content='Later genuine source',actor=STAFF)
        replay=self.c.execute(ap['id'],actor=PM)
        self.assertTrue(replay.replayed);self.assertEqual(replay.result,result.result)

    def test_distribution_requires_native_distribution_rights_and_independent_pm(self):
        self.w.answer();self.r.set_distribution_list(self.rid,{'recipients':[RECIPIENTS[0]]},actor=PM)
        rights=self.c.plugin('rights');lic=rights.register_license('Synthetic','No distribution','1','Holder',['project_use'],actor=OWNER)
        rights.tag_document(self.w.support_doc,lic['id'],actor=OWNER)
        with self.assertRaises(ApprovalError):self.c.request_approval('field.distribute_rfi',self.rid,actor_role='pm',requested_by=PM)

    def test_genuine_project_use_revocation_holds_native_response_draft(self):
        rights=self.c.plugin('rights')
        license=rights.register_license('Synthetic','Revocable source use','1','Holder',['project_use'],actor=OWNER)
        rights.tag_document(self.w.support_doc,license['id'],actor=OWNER)
        self.assertTrue(rights.check_use(self.w.support_doc,'project_use')['allowed'])
        rights.update_license(license['id'],permitted_uses=['internal_reference'],note='Synthetic project use withdrawn',actor=OWNER)
        self.assertFalse(rights.check_use(self.w.support_doc,'project_use')['allowed'])
        before=self.c.db.conn.total_changes
        with self.assertRaises(ApprovalError):self.c.plugin('field').draft_response(self.rid,'A response after project-use withdrawal',actor=STAFF)
        self.assertEqual(self.c.db.conn.total_changes,before)
        self.assertIsNone(self.r.source_proof(self.rid)['native']['draft_response'])

    def test_fixed_recipient_list_is_authored_draft_with_distribution_hold_disclosed(self):
        self.w.answer();rights=self.c.plugin('rights')
        license=rights.register_license('Synthetic','Project-use-only source','1','Holder',['project_use'],actor=OWNER)
        rights.tag_document(self.w.support_doc,license['id'],actor=OWNER)
        body={'recipients':[RECIPIENTS[0]]};before=self.c.db.conn.total_changes
        checked=self.r.distribution_list_preflight(self.rid,body,actor=PM)
        self.assertEqual(self.c.db.conn.total_changes,before)
        held=next(p for p in checked['distributionRights'] if p['documentId']==self.w.support_doc)
        self.assertFalse(held['allowed']);self.assertTrue(all(p['allowed'] for p in checked['source']['currentRights']))
        self.r.set_distribution_list(self.rid,body,actor=PM)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfi_distributions'),0)
        with self.assertRaises(ApprovalError):self.c.request_approval('field.distribute_rfi',self.rid,actor_role='pm',requested_by=PM)
        rights.update_license(license['id'],permitted_uses=['internal_reference'],note='Synthetic project use withdrawn',actor=OWNER)
        with self.assertRaises(ApprovalError):self.c.plugin('field').set_distribution_list(self.rid,[RECIPIENTS[1]],actor=PM)

    def test_failed_source_recording_rolls_back_original_native_request_when_caught(self):
        self.w.draft();before=self.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE operation='field.respond_rfi'")
        with self.c.db.transaction():
            with patch.object(self.r,'record_approval_source',side_effect=RuntimeError('late source fault')),self.assertRaises(RuntimeError):self.w.request_response()
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE operation='field.respond_rfi'"),before)
        self.assertEqual(len(self.r.source_proof(self.rid)['approvals']),0)

    def test_direct_native_application_late_audit_failure_does_not_leave_partial_answer(self):
        self.w.draft();ap=self.w.request_response();self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        manifest=self.c._manifest('field.respond_rfi',self.rid,'pm');record=self.c.audit.record
        def fail(actor,action,*args,**kwargs):
            if action=='field.rfi_answered':raise RuntimeError('native answer audit failure')
            return record(actor,action,*args,**kwargs)
        with self.c.db.transaction():
            self.c.approvals.consume(ap['id'],current_manifest=manifest,consumer=PM)
            with patch.object(self.c.audit,'record',side_effect=fail),self.assertRaises(RuntimeError):
                self.c.plugin('field').apply('field.respond_rfi',self.rid,approval_id=ap['id'],manifest=manifest,actor=PM,period_id=None)
        self.assertEqual(self.c.db.one('SELECT status FROM field_rfis WHERE id=?',(self.rid,))['status'],'open')
        with self.assertRaises(ApprovalError):self.r.source_proof(self.rid)  # The caller's separate consumed grant remains an explicit hold.

    def test_original_receipt_survives_genuine_reviewer_departure_but_new_execution_does_not(self):
        ap,result=self.w.answer()
        self.w.people.end_membership(REVIEWER,self.w.pid,reason='Synthetic later staff departure',actor=OWNER)
        self.assertEqual(self.r.effect_proof(ap['id'])['result'],result.result)
        self.assertTrue(self.c.execute(ap['id'],actor=PM).replayed)

    def test_raw_native_grant_bypass_has_no_original_qualified_review(self):
        self.w.draft(actor=REVIEWER);ap=self.w.request_response()
        self.c.approvals.grant(ap['id'],approver=REVIEWER)
        with self.assertRaises(ApprovalError):self.r.approval_proof(ap['id'])
        with self.assertRaises(ApprovalError):self.c.execute(ap['id'],actor=PM)
        self.assertEqual(self.c.db.one('SELECT status FROM field_rfis WHERE id=?',(self.rid,))['status'],'open')

    def test_source_creation_failure_is_atomic_inside_caught_outer_transaction(self):
        body={**self.w.body,'subject':'New synthetic question','question':'Which alternate connection should be used?'}
        before=self.c.db.scalar('SELECT COUNT(*) FROM field_rfis')
        with self.c.db.transaction():
            with patch.object(self.r,'_put',side_effect=RuntimeError('source creation failed')),self.assertRaises(RuntimeError):
                self.r.create(self.w.pid,body,actor=STAFF)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM field_rfis'),before)
        self.assertEqual(len(self.r.source_inventory((self.w.pid,))),1)

    def test_raw_answer_by_unregistered_consumer_is_not_an_authorized_original_effect(self):
        self.w.draft();ap=self.w.request_response();self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        manifest=self.c._manifest('field.respond_rfi',self.rid,'pm')
        self.c.approvals.consume(ap['id'],current_manifest=manifest,consumer='unregistered-consumer')
        for row in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='field_rfis'"):
            self.c.db.execute('DROP TRIGGER "'+row['name'].replace('"','""')+'"')
        now=utcnow_iso();row=self.c.db.one('SELECT * FROM field_rfis WHERE id=?',(self.rid,))
        self.c.db.execute("UPDATE field_rfis SET status='answered',version=version+1,response=draft_response,cost_impact=draft_cost_impact,schedule_impact_days=draft_schedule_impact_days,response_hash=draft_response_hash,approval_id=?,answered_by=?,answered_at=?,updated_at=? WHERE id=?",(ap['id'],'unregistered-consumer',now,now,self.rid))
        self.c.audit.record('unregistered-consumer','field.rfi_answered','field_rfi',self.rid,
            {'number':row['number'],'approval_id':ap['id'],'response_hash':row['draft_response_hash'],'cost_impact':row['draft_cost_impact'],'schedule_impact_days':row['draft_schedule_impact_days'],'version':row['version']+1})
        with self.assertRaises(ApprovalError):self.r.source_proof(self.rid)

    def test_pure_grant_and_execution_honor_other_configured_governor_holds(self):
        class Hold:
            GOVERNOR=True
            def check_grant(self,approval,**kwargs):raise ApprovalError('Synthetic other-governor review hold')
        self.w.draft();ap=self.w.request_response();self.c.register_plugin('test_rfi_hold',Hold())
        with self.assertRaises(ApprovalError):self.r.grant_preflight(ap['id'],actor=REVIEWER)
        self.c._plugins.pop('test_rfi_hold');self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        class ExecutionHold:
            GOVERNOR=True
            def check_execute(self,approval,manifest,**kwargs):raise ApprovalError('Synthetic other-governor execution hold')
            check_execute_preflight=check_execute
        self.c.register_plugin('test_rfi_hold',ExecutionHold())
        with self.assertRaises(ApprovalError):self.r.execution_preflight(ap['id'],actor=PM)

    def test_completed_native_replay_still_requires_current_own_pm_before_cache(self):
        ap,result=self.w.answer()
        self.w.people.end_membership(PM,self.w.pid,reason='Synthetic later departure',actor=OWNER)
        self.assertEqual(self.r.effect_proof(ap['id'])['result'],result.result)
        with patch.object(self.c.commands,'run',side_effect=AssertionError('command cache read before current duty')):
            with self.assertRaises(ApprovalError):self.c.execute(ap['id'],actor=PM)

    def test_tampered_cached_response_is_refused_against_exact_original_native_effect(self):
        from apps.cipher.core.ids import canonical_json
        ap,result=self.w.answer()
        for row in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='idempotency'"):
            self.c.db.execute('DROP TRIGGER "'+row['name'].replace('"','""')+'"')
        self.c.db.execute('UPDATE idempotency SET result_json=? WHERE op_id=?',(canonical_json({'status':'answered','falseResult':True}),'exec:'+ap['id']))
        with self.assertRaises(ApprovalError):self.c.execute(ap['id'],actor=PM)
        self.assertEqual(self.r.effect_proof(ap['id'])['result'],result.result)


if __name__=='__main__':unittest.main()
