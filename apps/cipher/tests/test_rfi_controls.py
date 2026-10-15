"""Native current RFI duties and pure citation preparation."""
import unittest

from apps.cipher.ar_practice_fixture import make_ar_practice_fixture,PM_LOGIN,REVIEWER_LOGIN,BOOTSTRAP_LOGIN
from apps.cipher.domain.rfi_controls import RFIError,require_rfi_duty


class RFIPreparationTests(unittest.TestCase):
    def setUp(self):
        self.c=make_ar_practice_fixture();self.pid=self.c.ar_practice_records['project_id'];self.module=self.c.plugin('rfi_controls')
        evidence=self.c.evidence
        doc=evidence.register_document(project_id=self.pid,kind='drawing',title='C-101',actor=PM_LOGIN)
        ev=evidence.add_revision(document_id=doc['id'],content='Synthetic issued drainage detail',actor=PM_LOGIN)
        drawings=self.c.plugin('drawing');header=drawings.register_drawing(self.pid,'C-101','Drainage','Civil',actor=PM_LOGIN)
        self.rev=drawings.add_revision(header['id'],'A',ev['id'],actor=PM_LOGIN)
        approval=self.c.request_approval('drawing.issue',self.rev['id'],actor_role='pm',requested_by=PM_LOGIN)
        self.c.approve(approval['id'],approver=BOOTSTRAP_LOGIN,approver_role='owner');self.c.execute(approval['id'],actor=PM_LOGIN,period_id='2026-10')
        support=evidence.register_document(project_id=self.pid,kind='specification',title='Drainage note',actor=PM_LOGIN)
        self.support=evidence.add_revision(document_id=support['id'],content='Synthetic authored drainage specification',actor=PM_LOGIN)
        self.body={'subject':'Drain clash at grid C4','question':'Which drain routing should the crew use?',
                   'drawingRevisionIds':[self.rev['id']],'documentRevisionIds':[self.support['id']]}

    def tearDown(self):self.c.db.close()

    def test_actual_membership_permits_staff_draft_but_not_pm_decision(self):
        staff=require_rfi_duty(self.c,REVIEWER_LOGIN,self.pid,'staff')
        self.assertEqual(staff['login'],REVIEWER_LOGIN)
        with self.assertRaises(RFIError):require_rfi_duty(self.c,REVIEWER_LOGIN,self.pid,'pm')
        self.assertEqual(require_rfi_duty(self.c,PM_LOGIN,self.pid,'pm')['role'],'pm')

    def test_entity_owner_without_own_membership_cannot_draft(self):
        with self.assertRaises(RFIError):require_rfi_duty(self.c,BOOTSTRAP_LOGIN,self.pid,'staff')

    def test_hidden_project_refused_before_private_source_plan(self):
        with self.assertRaises(RFIError):self.module.create_preflight(self.c.ar_practice_records['hidden_project_id'],self.body,actor=PM_LOGIN)

    def test_current_sources_prepare_without_ids_or_audit_writes(self):
        before=self.c.db.conn.total_changes
        plan=self.module.create_preflight(self.pid,self.body,actor=REVIEWER_LOGIN)
        self.assertEqual(plan['person']['login'],REVIEWER_LOGIN)
        self.assertEqual(plan['nativeInput']['drawing_revision_ids'],[self.rev['id']])
        self.assertEqual(plan['source']['documents'][0]['revision']['id'],self.support['id'])
        self.assertEqual(self.c.db.conn.total_changes,before)

    def test_stale_supporting_revision_is_not_silently_replaced_at_creation(self):
        self.c.evidence.add_revision(document_id=self.support['document_id'],content='Genuine newer note',actor=PM_LOGIN)
        with self.assertRaises(RFIError):self.module.create_preflight(self.pid,self.body,actor=PM_LOGIN)

    def test_caller_cannot_choose_actor_role_provider_or_rights_use(self):
        for key,value in [('actor',BOOTSTRAP_LOGIN),('role','owner'),('provider','smtp'),('use','distribution')]:
            with self.subTest(key=key),self.assertRaises(RFIError):self.module.create_preflight(self.pid,{**self.body,key:value},actor=PM_LOGIN)

    def test_initial_rfi_requires_both_source_kinds_and_unique_citations(self):
        for change in ({'drawingRevisionIds':[]},{'documentRevisionIds':[]},{'drawingRevisionIds':[self.rev['id'],self.rev['id']]}):
            with self.subTest(change=change),self.assertRaises(RFIError):self.module.create_preflight(self.pid,{**self.body,**change},actor=PM_LOGIN)

    def test_current_project_use_rights_are_checked_in_the_engine(self):
        rights=self.c.plugin('rights')
        lic=rights.register_license('Synthetic','Restricted reference','1','Holder',['internal_reference'],actor=BOOTSTRAP_LOGIN)
        rights.tag_document(self.support['document_id'],lic['id'],actor=BOOTSTRAP_LOGIN)
        with self.assertRaises(RFIError):self.module.create_preflight(self.pid,self.body,actor=PM_LOGIN)

    def test_unissued_drawing_evidence_cannot_bypass_register_as_supporting_document(self):
        drawing_doc=self.rev['evidence_document_id'] if 'evidence_document_id' in self.rev else self.c.evidence.revision(self.rev['document_revision_id'])['document_id']
        working=self.c.evidence.add_revision(document_id=drawing_doc,content='Unissued working drawing',actor=PM_LOGIN)
        with self.assertRaises(RFIError):self.module.create_preflight(self.pid,{**self.body,'documentRevisionIds':[working['id']]},actor=PM_LOGIN)
        choices=self.module.preparation_sources(self.pid,actor=PM_LOGIN)
        choice=next(p for p in choices['documents'] if p['revision']['id']==working['id'])
        self.assertFalse(choice['citable']);self.assertEqual(choice['citationHold']['code'],'issued_drawing_required')
        legacy=self.c.plugin('field').create_rfi(self.pid,'Legacy document citation','Exact historical legacy citation?',actor=PM_LOGIN,
            drawing_revision_ids=[self.rev['id']],document_revision_ids=[working['id']])
        self.assertEqual(legacy['document_revision_ids'],[working['id']])
        self.assertFalse(self.module.is_modern(legacy['id']))


def admit_actual_rfi_sources():
    from apps.cipher.core.db import SCHEMA_CATALOG
    from apps.cipher.domain.library import register_library_schema
    from apps.cipher.library_receipts import register_library_receipts_schema
    from apps.cipher.domain.rfi_controls import register_rfi_controls_schema
    register_library_schema();register_library_receipts_schema()
    original=tuple((v,n,tuple(sql)) for v,n,sql in SCHEMA_CATALOG[:77])
    register_rfi_controls_schema()
    assert original==tuple((v,n,tuple(sql)) for v,n,sql in SCHEMA_CATALOG[:77])


class RFINativeSourceTests(unittest.TestCase):
    def setUp(self):
        admit_actual_rfi_sources();RFIPreparationTests.setUp(self)
        self.rfi=self.module.create(self.pid,self.body,actor=REVIEWER_LOGIN)

    tearDown=RFIPreparationTests.tearDown

    def drop_guards(self,table):
        for row in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,)):
            self.c.db.execute('DROP TRIGGER "'+row['name'].replace('"','""')+'"')

    def test_actual_78_admission_preserves_genuine_library_76_77(self):
        from apps.cipher.core.db import SCHEMA_CATALOG
        self.assertEqual(SCHEMA_CATALOG[75][1],'library_authored_text_and_reference_adoptions')
        self.assertEqual(SCHEMA_CATALOG[76][1],'library_practice_action_receipts')
        self.assertEqual(SCHEMA_CATALOG[77][1],'rfi_sources_and_review_contexts')
        source=self.module.source_proof(self.rfi['id'])
        self.assertEqual(source['record']['person']['login'],REVIEWER_LOGIN)
        self.assertEqual(source['native']['status'],'open')
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM journals'),0)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM changes'),0)

    def test_direct_native_response_records_exact_author_revision_in_same_transaction(self):
        self.c.plugin('field').draft_response(self.rfi['id'],'Use the east alignment.','1250.00',3,actor=REVIEWER_LOGIN)
        source=self.module.source_proof(self.rfi['id'])
        self.assertEqual(source['latestResponse']['record']['person']['login'],REVIEWER_LOGIN)
        self.assertEqual(source['latestResponse']['record']['response'],'Use the east alignment.')
        self.assertEqual(source['latestResponse']['record']['costImpact'],'1250.00')
        self.assertEqual(source['native']['status'],'open')

    def test_direct_native_unknown_person_cannot_bypass_draft_staff_check(self):
        with self.assertRaises(RFIError):self.c.plugin('field').draft_response(self.rfi['id'],'Unauthenticated response',actor='unknown-person')

    def test_deleted_source_birth_still_classifies_modern_and_fails_closed(self):
        self.drop_guards('rfi_sources');self.c.db.execute('DELETE FROM rfi_sources WHERE rfi_id=?',(self.rfi['id'],))
        self.assertTrue(self.module.is_modern(self.rfi['id']))
        with self.assertRaises(RFIError):self.module.source_proof(self.rfi['id'])
        self.assertFalse(self.module.close_checks('2026-10')[0]['ok'])

    def test_original_native_source_survives_only_later_receipt_admission_loss(self):
        from apps.cipher.rfi_receipts import register_rfi_receipts_schema,RFIReceipts,RFIReceiptError
        register_rfi_receipts_schema();self.c.db.migrate()
        original=self.module.source_proof(self.rfi['id'])
        self.c.db.execute("DELETE FROM schema_version WHERE name='rfi_practice_action_receipts'")
        self.assertEqual(original,self.module.source_proof(self.rfi['id']))
        with self.assertRaises(RFIReceiptError):RFIReceipts(self.c.db,self.c.audit).verify_integrity()

    def test_same_id_question_and_hash_substitution_fails_original_source(self):
        self.drop_guards('field_rfis');self.c.db.execute('UPDATE field_rfis SET question=? WHERE id=?',('A substituted question',self.rfi['id']))
        with self.assertRaises(RFIError):self.module.source_proof(self.rfi['id'])

    def test_source_version_failure_rolls_back_native_draft_even_when_caught(self):
        from unittest.mock import patch
        original=self.module._put
        def failed(kind,body,actor):
            if kind=='response_revisions':raise RuntimeError('source recording failed')
            return original(kind,body,actor)
        with self.c.db.transaction():
            with patch.object(self.module,'_put',side_effect=failed),self.assertRaises(RuntimeError):
                self.c.plugin('field').draft_response(self.rfi['id'],'A response that must roll back',actor=REVIEWER_LOGIN)
        self.assertIsNone(self.module.source_proof(self.rfi['id'])['native']['draft_response'])


if __name__=='__main__':unittest.main()
