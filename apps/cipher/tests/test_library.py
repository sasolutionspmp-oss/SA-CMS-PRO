"""Native authored text/reference behavior against the actual required facade."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from apps.cipher.library_practice_fixture import (make_library_practice_fixture, BOOTSTRAP_LOGIN, PM_LOGIN, REVIEWER_LOGIN,
    POSTER_LOGIN, HIDDEN_PM_LOGIN, INACTIVE_LOGIN)
from apps.cipher.core.approvals import ApprovalError, StaleApprovalError
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.core.ids import hash_json
from apps.cipher.domain.library import LibraryError, OPERATION, SOURCE_KIND, EFFECT_KIND, require_library_pm
from apps.cipher.service import Cipher


def dump(c):
    return '\n'.join(c.db.conn.iterdump())


def editor_body(text='Practice-authored concrete clause.\r\n  Keep exact spacing — café 🏗.\n'):
    return {'kind': 'contract_clause', 'title': 'Practice-authored concrete quality clause', 'text': text,
            'sourceLocator': 'Practice editor / QA concrete / paragraph 1'}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.c = make_library_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.l = self.c.plugin('library')
        self.p = self.c.library_practice_records['project_id']

    def create(self, text=None):
        body = editor_body() if text is None else editor_body(text)
        return self.l.create(self.p, body, actor=PM_LOGIN)

    def plan(self, entry=None):
        entry = entry or self.create()
        return self.l.prepare_reference(entry['currentRevisionId'], {'targetLocator':'Project specifications / 03 30 00 / draft reference',
            'purpose':'Internal specification preparation; no signature or legal acceptance'}, actor=PM_LOGIN)

    def request(self, plan=None):
        return self.c.request_approval(OPERATION, (plan or self.plan())['id'], actor_role='pm', requested_by=PM_LOGIN)

    def grant(self, plan=None):
        ap = self.request(plan)
        self.c.approve(ap['id'], approver=REVIEWER_LOGIN, approver_role='pm')
        return ap

    def adopt(self, plan=None, op_id=None):
        ap = self.grant(plan)
        return ap, self.c.execute(ap['id'], actor=PM_LOGIN, op_id=op_id)

    def revise(self, entry):
        return self.l.revise(entry['entry']['record']['id'], {'previousRevisionId':entry['currentRevisionId'],
            'text':'Practice-authored concrete clause revision two.\n', 'sourceLocator':'Practice editor / QA concrete / paragraph 2',
            'changeReason':'Clarify internal inspection reference'}, actor=PM_LOGIN)

    def tamper(self, table, sql, params=()):
        guards = self.c.db.query("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))
        with self.c.db.transaction() as conn:
            for guard in guards:
                conn.execute('DROP TRIGGER '+guard['name'])
            conn.execute(sql, params)
            for guard in guards:
                conn.execute(guard['sql'])

    def test_exact_utf8_text_is_stored_with_creator_locator_and_immutable_original(self):
        body = editor_body()
        before = dump(self.c)
        self.l.create_preflight(self.p, body, actor=PM_LOGIN)
        self.assertEqual(dump(self.c), before)
        created = self.create()
        revision = created['currentRevision']['record']
        self.assertEqual(revision['text'], body['text'])
        self.assertEqual(revision['byteCount'], len(body['text'].encode('utf-8')))
        self.assertEqual(revision['actor']['login'], PM_LOGIN)
        self.assertEqual(revision['sourceKind'], SOURCE_KIND)
        row = self.c.db.one('SELECT text FROM library_revisions WHERE id=?', (revision['id'],))
        self.assertEqual(row['text'].encode('utf-8'), body['text'].encode('utf-8'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute('UPDATE library_revisions SET text=? WHERE id=?', ('changed',revision['id']))
        self.assertEqual(self.c.ledger.journals(), [])

    def test_native_independent_pm_review_and_reference_only_effect(self):
        plan = self.plan()
        before = dump(self.c)
        self.c.check_library_reference_request(plan['id'], requested_by=PM_LOGIN)
        self.assertEqual(dump(self.c), before)
        approval = self.request(plan)
        before = dump(self.c)
        with self.assertRaises(LibraryError):
            self.c.approve(approval['id'], approver=PM_LOGIN, approver_role='pm')
        self.assertEqual(dump(self.c), before)
        self.c.check_library_reference_grant(approval['id'], approver=REVIEWER_LOGIN)
        self.assertEqual(dump(self.c), before)
        self.c.approve(approval['id'], approver=REVIEWER_LOGIN, approver_role='pm')
        self.assertEqual(self.c.ledger.journals(), [])
        before = dump(self.c)
        self.c.check_library_reference_execution(approval['id'], actor=PM_LOGIN)
        self.assertEqual(dump(self.c), before)
        result = self.c.execute(approval['id'], actor=PM_LOGIN)
        self.assertFalse(result.replayed)
        self.assertEqual(result.result['effectKind'], EFFECT_KIND)
        self.assertEqual(result.result['status'],'adopted_reference')
        proof = self.l.adoption_proof(result.result['referenceId'])
        self.assertEqual(proof['record']['text'], editor_body()['text'])
        self.assertEqual(proof['record']['reviewer']['login'], REVIEWER_LOGIN)
        self.assertEqual(self.c.approvals.get(approval['id'])['status'],'consumed')
        self.assertEqual(self.c.ledger.journals(), [])
        self.assertEqual(self.c.commands.pending(), [])
        self.assertTrue(all(p['ok'] for p in self.l.integrity_checks()))

    def test_current_revision_is_separate_from_original_adopted_text_and_retry(self):
        entry = self.create()
        plan = self.plan(entry)
        approval, original = self.adopt(plan, op_id='library-original')
        revised = self.revise(entry)
        self.assertNotEqual(entry['currentRevisionId'], revised['currentRevisionId'])
        self.assertEqual(len(revised['revisions']),2)
        self.assertEqual(revised['currentRevision']['record']['previousRevisionId'], entry['currentRevisionId'])
        proof = self.l.adoption_proof(original.result['referenceId'])
        self.assertEqual(proof['record']['text'], editor_body()['text'])
        self.assertNotEqual(proof['record']['text'], revised['currentRevision']['record']['text'])
        replay = self.c.execute(approval['id'], actor=PM_LOGIN, op_id='library-original')
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, original.result)
        with self.assertRaises(StaleApprovalError):
            self.l.prepare_reference(entry['currentRevisionId'], {'targetLocator':'Draft section','purpose':'Use old text'}, actor=PM_LOGIN)
        newer = self.plan(revised)
        fresh = self.request(newer)
        self.assertEqual(fresh['status'],'pending')

    def test_changed_head_makes_pending_grant_stale_and_requires_new_review(self):
        entry = self.create()
        approval = self.request(self.plan(entry))
        self.revise(entry)
        with self.assertRaises(StaleApprovalError):
            self.c.approve(approval['id'], approver=REVIEWER_LOGIN, approver_role='pm')
        self.assertEqual(self.c.approvals.get(approval['id'])['status'],'invalidated')
        self.assertEqual(self.l.adoption_inventory(project_ids=(self.p,)), [])

    def test_changed_head_makes_granted_execution_stale_without_effect(self):
        entry = self.create()
        approval = self.grant(self.plan(entry))
        self.revise(entry)
        with self.assertRaises(StaleApprovalError):
            self.c.execute(approval['id'], actor=PM_LOGIN)
        self.assertEqual(self.l.adoption_inventory(project_ids=(self.p,)), [])
        self.assertEqual(self.c.approvals.get(approval['id'])['status'],'invalidated')

    def test_own_pm_duty_rejects_owner_other_roles_hidden_and_delegated(self):
        for login in (BOOTSTRAP_LOGIN, POSTER_LOGIN, HIDDEN_PM_LOGIN, INACTIVE_LOGIN):
            with self.subTest(login=login), self.assertRaises((LibraryError, ApprovalError)):
                self.l.create(self.p, editor_body(), actor=login)
        self.assertEqual(self.l.search(project_ids=(self.p,)), [])

    def test_scope_is_applied_before_detail_and_search_original_inventory(self):
        visible = self.create()
        hidden_project = self.c.library_practice_records['hidden_project_id']
        hidden = self.l.create(hidden_project, editor_body('Hidden practice-authored technical clause'), actor=HIDDEN_PM_LOGIN)
        self.assertEqual(len(self.l.search(project_ids=(self.p,), query='café')),1)
        self.assertEqual(self.l.search(project_ids=(self.p,), query='hidden'), [])
        with self.assertRaises(LibraryError):
            self.l.detail(hidden['entry']['record']['id'], project_ids=(self.p,))
        self.assertEqual(self.l.detail(visible['entry']['record']['id'], project_ids=(self.p,))['entry']['record']['project_id'],self.p)

    def test_deleted_original_revision_and_head_fail_closed(self):
        entry = self.create()
        rid = entry['currentRevisionId']
        self.tamper('library_heads','DELETE FROM library_heads WHERE revision_id=?',(rid,))
        with self.assertRaises(LibraryError):
            self.l.search(project_ids=(self.p,))
        self.assertFalse(self.l.integrity_checks()[0]['ok'])

    def test_same_id_text_edit_with_restored_guards_cannot_become_current(self):
        entry = self.create()
        body = copy.deepcopy(entry['currentRevision']['record'])
        body['text'] = 'Forged text'
        from apps.cipher.core.ids import canonical_json
        self.tamper('library_revisions', 'UPDATE library_revisions SET text=?,body_json=? WHERE id=?', ('Forged text',canonical_json(body),entry['currentRevisionId']))
        with self.assertRaises(LibraryError):
            self.l.detail(entry['entry']['record']['id'],project_ids=(self.p,))

    def test_deleted_pending_approval_birth_cannot_disappear_from_inventory(self):
        approval = self.request()
        self.tamper('approvals','DELETE FROM approvals WHERE id=?',(approval['id'],))
        with self.assertRaises(LibraryError):
            self.l.approval_inventory(project_ids=(self.p,))

    def test_reference_text_and_cached_result_tampering_are_refused(self):
        approval, result = self.adopt(op_id='library-cache')
        self.tamper('idempotency','UPDATE idempotency SET result_json=? WHERE op_id=?', ('{"status":"executed_contract"}','library-cache'))
        before = dump(self.c)
        with self.assertRaises(LibraryError):
            self.c.execute(approval['id'],actor=PM_LOGIN,op_id='library-cache')
        self.assertEqual(dump(self.c),before)

    def test_current_authority_is_rechecked_before_original_retry(self):
        approval, result = self.adopt(op_id='library-revoked')
        self.c.plugin('people').deactivate_person(PM_LOGIN,reason='Synthetic staff departure',actor=BOOTSTRAP_LOGIN)
        before = dump(self.c)
        with self.assertRaises(LibraryError):
            self.c.execute(approval['id'],actor=PM_LOGIN,op_id='library-revoked')
        self.assertEqual(dump(self.c),before)
        self.assertEqual(self.l.adoption_proof(result.result['referenceId'])['record']['text'],editor_body()['text'])

    def test_caught_late_command_failure_rolls_back_consumption_copy_and_command(self):
        approval = self.grant()
        original = self.c.audit.record
        def fail(actor, action, *args, **kwargs):
            if action == 'command.executed':
                raise RuntimeError('late command receipt fault')
            return original(actor,action,*args,**kwargs)
        with self.c.db.transaction():
            before = dump(self.c)
            with patch.object(self.c.audit,'record',side_effect=fail), self.assertRaises(RuntimeError):
                self.c.execute(approval['id'],actor=PM_LOGIN,op_id='library-late')
            self.assertEqual(dump(self.c),before)
        self.assertEqual(self.c.approvals.get(approval['id'])['status'],'granted')

    def test_caught_late_revision_fault_rolls_back_core_evidence_and_pointer(self):
        entry = self.create()
        original = self.c.audit.record
        def fail(actor, action, *args, **kwargs):
            if action == 'library.heads_recorded':
                raise RuntimeError('late pointer fault')
            return original(actor,action,*args,**kwargs)
        with self.c.db.transaction():
            before = dump(self.c)
            with patch.object(self.c.audit,'record',side_effect=fail), self.assertRaises(RuntimeError):
                self.revise(entry)
            self.assertEqual(dump(self.c),before)

    def test_direct_consumed_self_review_cannot_bypass_native_reference_authority(self):
        approval = self.request()
        self.c.approvals.grant(approval['id'],approver=PM_LOGIN)
        manifest = self.c._manifest(OPERATION,approval['subject_id'],'pm')
        with self.c.db.transaction():
            self.c.approvals.consume(approval['id'], current_manifest=manifest, consumer=PM_LOGIN)
            before = dump(self.c)
            with self.assertRaises(LibraryError):
                self.l.apply(OPERATION,approval['subject_id'],approval_id=approval['id'],manifest=manifest,actor=PM_LOGIN)
            self.assertEqual(dump(self.c),before)

    def test_invalid_text_and_ownership_flags_cannot_select_other_ingestion(self):
        for text in ('', '\x00', '\ud800', 'a'*65537):
            body = editor_body(text)
            with self.subTest(text=repr(text)[:20]), self.assertRaises(LibraryError):
                self.l.create(self.p,body,actor=PM_LOGIN)
        body = editor_body()
        body['owned'] = True
        with self.assertRaises(LibraryError):
            self.l.create(self.p,body,actor=PM_LOGIN)
        self.assertEqual(self.l.search(project_ids=(self.p,)),[])

    def test_adoption_has_no_posting_period_and_no_second_actor_retry(self):
        approval = self.grant()
        before = dump(self.c)
        with self.assertRaises(LibraryError):
            self.c.execute(approval['id'],actor=PM_LOGIN,period_id='2026-10')
        self.assertEqual(dump(self.c),before)
        self.c.execute(approval['id'],actor=PM_LOGIN,op_id='library-person')
        before = dump(self.c)
        with self.assertRaises(LibraryError):
            self.c.execute(approval['id'],actor=REVIEWER_LOGIN,op_id='library-person')
        self.assertEqual(dump(self.c),before)

    def test_past_unaudited_deadline_cannot_qualify_original_adoption(self):
        approval, result = self.adopt()
        self.tamper('approvals','UPDATE approvals SET expires_at=? WHERE id=?',('1900-01-01T00:00:00Z',approval['id']))
        with self.assertRaises(LibraryError):
            self.l.adoption_proof(result.result['referenceId'])

    def test_tagged_and_later_untagged_text_cannot_reinterpret_authored_only_ingestion(self):
        entry = self.create()
        plan = self.plan(entry)
        approval, result = self.adopt(plan,op_id='library-before-rights')
        rights = self.c.plugin('rights')
        license = rights.register_license('Synthetic standards publisher','Synthetic restricted text','Practice edition',
            'Synthetic holder',['project_use'],actor=BOOTSTRAP_LOGIN)
        doc_id = entry['entry']['record']['document_id']
        rights.tag_document(doc_id,license['id'],actor=BOOTSTRAP_LOGIN)
        with self.assertRaises(LibraryError):
            self.l.detail(entry['entry']['record']['id'],project_ids=(self.p,))
        # Original adoption is historical provenance, not a new permission to distribute.
        self.assertEqual(self.l.adoption_proof(result.result['referenceId'])['record']['text'],editor_body()['text'])
        self.assertTrue(self.c.execute(approval['id'],actor=PM_LOGIN,op_id='library-before-rights').replayed)
        rights.untag_document(doc_id,license['id'],actor=BOOTSTRAP_LOGIN,reason='Synthetic tag history remains relevant')
        with self.assertRaisesRegex(LibraryError,'untagging'):
            self.l.prepare_reference(entry['currentRevisionId'],{'targetLocator':'New section','purpose':'Use as reference'},actor=PM_LOGIN)

    def test_original_tag_deletion_cannot_restore_current_text_access(self):
        entry = self.create()
        rights=self.c.plugin('rights')
        license=rights.register_license('Synthetic publisher','Restricted source','Practice','Holder',['internal_reference'],actor=BOOTSTRAP_LOGIN)
        tag=rights.tag_document(entry['entry']['record']['document_id'],license['id'],actor=BOOTSTRAP_LOGIN)
        self.tamper('rights_document_tags','DELETE FROM rights_document_tags WHERE id=?',(tag['id'],))
        with self.assertRaises(LibraryError):
            self.l.detail(entry['entry']['record']['id'],project_ids=(self.p,))

    def test_deleted_native_evidence_revision_cannot_hide_behind_stored_text(self):
        entry=self.create()
        native=entry['currentRevision']['record']['evidence_revision_id']
        self.tamper('document_revisions','UPDATE document_revisions SET content_hash=? WHERE id=?',('0'*64,native))
        with self.assertRaises(LibraryError):
            self.l.revision_proof(entry['currentRevisionId'])

    def test_schema_admission_loss_and_sequence_holes_are_not_legacy_fallback(self):
        self.create()
        self.tamper('schema_version','UPDATE schema_version SET version=999 WHERE name=?',('library_authored_text_and_reference_adoptions',))
        with self.assertRaises(LibraryError):
            self.l.search(project_ids=(self.p,))

    def test_scoped_current_reads_refuse_deleted_original_reference_birth(self):
        approval,result=self.adopt()
        self.tamper('library_adoptions','DELETE FROM library_adoptions WHERE id=?',(result.result['referenceId'],))
        with self.assertRaises(LibraryError):
            self.l.search(project_ids=(self.p,))

    def test_original_self_review_grant_cannot_qualify_as_library_authorization(self):
        approval=self.request()
        self.c.approvals.grant(approval['id'],approver=PM_LOGIN)
        with self.assertRaises(LibraryError):
            self.l.approval_proof(approval['id'])

    def test_native_request_grant_and_apply_honor_other_configured_governor_holds(self):
        plan=self.plan()
        contracts=self.c.plugin('contract')
        before=dump(self.c)
        with patch.object(contracts,'check_request',side_effect=ApprovalError('Synthetic contract governor hold')):
            with self.assertRaises(ApprovalError):self.request(plan)
        self.assertEqual(dump(self.c),before)
        approval=self.request(plan)
        before=dump(self.c)
        with patch.object(contracts,'check_grant',side_effect=ApprovalError('Synthetic contract governor hold')):
            with self.assertRaises(ApprovalError):self.c.approve(approval['id'],approver=REVIEWER_LOGIN,approver_role='pm')
        self.assertEqual(dump(self.c),before)
        self.c.approve(approval['id'],approver=REVIEWER_LOGIN,approver_role='pm')
        before=dump(self.c)
        with patch.object(contracts,'check_execute_preflight',side_effect=ApprovalError('Synthetic contract governor hold')):
            with self.assertRaises(ApprovalError):self.c.execute(approval['id'],actor=PM_LOGIN)
        self.assertEqual(dump(self.c),before)

    def test_already_adopted_plan_cannot_receive_another_fresh_grant(self):
        plan=self.plan()
        first=self.request(plan)
        second=self.request(plan)
        self.c.approve(first['id'],approver=REVIEWER_LOGIN,approver_role='pm')
        self.c.execute(first['id'],actor=PM_LOGIN)
        before=dump(self.c)
        with self.assertRaises(LibraryError):
            self.c.check_library_reference_grant(second['id'],approver=REVIEWER_LOGIN)
        self.assertEqual(dump(self.c),before)

    def test_original_reference_projection_stays_exact_after_later_revision_and_current_rights_change(self):
        entry=self.create()
        approval,result=self.adopt(self.plan(entry),op_id='library-stable-original')
        original=hash_json(self.l.original_reference_proof(result.result['referenceId']))
        self.revise(entry)
        rights=self.c.plugin('rights')
        license=rights.register_license('Synthetic laterpublisher','Synthetic laterrestriction','Practice','Holder',[],actor=BOOTSTRAP_LOGIN)
        rights.tag_document(entry['entry']['record']['document_id'],license['id'],actor=BOOTSTRAP_LOGIN)
        self.assertEqual(hash_json(self.l.original_reference_proof(result.result['referenceId'])),original)
        self.assertTrue(self.c.execute(approval['id'],actor=PM_LOGIN,op_id='library-stable-original').replayed)

    def test_metadata_must_be_valid_utf8_before_any_authoring_effect(self):
        body=editor_body()
        body['title']='Invalid surrogate \ud800'
        before=dump(self.c)
        with self.assertRaises(LibraryError):
            self.l.create_preflight(self.p,body,actor=PM_LOGIN)
        self.assertEqual(dump(self.c),before)

    def test_empty_installed_library_is_inert_for_existing_native_close_checklists(self):
        self.assertEqual(self.l.close_checks('2026-10'),[])
        self.assertEqual(self.l.integrity_checks(),[])

    def test_empty_library_cannot_hide_an_original_orphaned_library_authorization(self):
        from apps.cipher.core.approvals import build_manifest
        self.c.approvals.request(build_manifest(operation=OPERATION,subject_type='library_reference_plan',
            subject_id='missing_original_plan',actor_role='pm'),requested_by=PM_LOGIN)
        self.assertFalse(self.l.integrity_checks()[0]['ok'])

    def test_original_native_reference_survives_lost_later_api_admission_while_api_holds(self):
        from apps.cipher.library_receipts import LibraryReceipts,LibraryReceiptError
        approval,result=self.adopt()
        original=self.l.original_reference_proof(result.result['referenceId'])
        self.c.db.execute("DELETE FROM schema_version WHERE name='library_practice_action_receipts'")
        self.assertEqual(self.l.original_reference_proof(result.result['referenceId']),original)
        with self.assertRaises(LibraryReceiptError):
            LibraryReceipts(self.c.db,self.c.audit).verify_integrity()
