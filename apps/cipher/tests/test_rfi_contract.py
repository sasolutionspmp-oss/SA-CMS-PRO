"""Actual scoped RFI source disclosures, original review snapshots and current holds."""
import json
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.rfi_contract import RFIContract
from apps.cipher.rfi_practice_fixture import make_rfi_practice_fixture, STAFF_LOGIN, PM_LOGIN, REVIEWER_LOGIN, BOOTSTRAP_LOGIN, HIDDEN_STAFF_LOGIN
from apps.cipher.rfi_receipts import register_rfi_receipts_schema


class RFIContractTests(unittest.TestCase):
    def setUp(self):
        register_rfi_receipts_schema()
        self.c = make_rfi_practice_fixture(); self.addCleanup(self.c.db.close)
        self.d = self.c.plugin('rfi_controls'); self.k = RFIContract(self.c, secret=b'actual-rfi-contract-private-key-for-tests')
        self.records = self.c.rfi_practice_records; self.project = self.records['project_id']
        self.people = {key: value['person_id'] for key, value in self.c.rfi_practice_persona_people.items()}

    def state(self):
        return tuple(self.c.db.conn.iterdump()), tuple(self.c.provider.submissions)

    def create(self, *, hidden=False, subject='Drain alignment clarification'):
        prefix = 'hidden_' if hidden else ''
        return self.d.create(self.records[prefix + 'project_id'], {'subject': subject, 'question': 'Which alignment should the crew use?',
            'drawingRevisionIds': [self.records[prefix + 'drawing_revision_id']],
            'documentRevisionIds': [self.records[prefix + 'document_revision_id']]}, actor=HIDDEN_STAFF_LOGIN if hidden else STAFF_LOGIN)

    def requested(self):
        row = self.create(); self.d.draft_response(row['id'], {'responseText': 'Use the east alignment.\nPotential impacts only.', 'costImpact': '1250.05', 'scheduleImpactDays': 3}, actor=STAFF_LOGIN)
        approval = self.c.request_approval('field.respond_rfi', row['id'], actor_role='pm', requested_by=PM_LOGIN)
        return row['id'], approval['id']

    def answered(self):
        rfi, approval = self.requested(); self.c.approve(approval, approver=REVIEWER_LOGIN, approver_role='pm')
        self.c.execute(approval, actor=PM_LOGIN)
        return rfi, approval

    def test_real_empty_preparation_is_pure_and_separates_issued_working_and_disabled_drawing_evidence(self):
        before = self.state(); prep = self.k.preparation(self.people['staff'], self.project)
        issued = prep['sources']['drawings'][0]
        self.assertEqual(issued['revisionId'], self.records['drawing_revision_id'])
        self.assertEqual(issued['current']['workingRevisionId'], self.records['working_drawing_revision_id'])
        self.assertEqual(issued['current']['issuedRevisionId'], issued['revisionId'])
        self.assertNotEqual(issued['documentRevisionId'], issued['current']['evidenceHeadRevisionId'])
        disabled = next(p for p in prep['sources']['documents'] if p['kind'] == 'drawing')
        self.assertFalse(disabled['citable']); self.assertEqual(disabled['citationHold']['code'], 'issued_drawing_required')
        self.assertEqual(self.k.read(self.people['staff'], 'rfis')['count'], 0)
        self.assertEqual(self.state(), before)

    def test_staff_can_read_and_draft_but_pm_authority_is_required_before_private_review_source(self):
        row = self.create(); context = self.k.authorize(self.people['staff'], 'rfi.draftResponse', row['id'])
        self.assertEqual(context['operationRole'], None)
        with patch.object(self.k, '_materials', side_effect=AssertionError('private source was read')) as facts:
            with self.assertRaises(APRefusal) as caught: self.k.authorize(self.people['staff'], 'rfi.requestResponse', row['id'])
            self.assertEqual(caught.exception.status, 403); facts.assert_not_called()
        self.assertEqual(self.k.rfi(self.people['staff'], row['id'])['status'], 'open')

    def test_hidden_nonexistent_and_wrong_approval_kinds_are_scoped_before_private_inventory(self):
        row = self.create(hidden=True)
        with patch.object(self.k, '_materials', side_effect=AssertionError('hidden aggregate')) as facts:
            for identifier in (row['id'], 'rfi_missing'):
                with self.subTest(identifier=identifier), self.assertRaises(APRefusal) as caught: self.k.rfi(self.people['staff'], identifier)
                self.assertEqual(caught.exception.status, 404)
            with self.assertRaises(APRefusal): self.k.read(self.people['staff'], 'rfis', project_id=self.records['hidden_project_id'])
            facts.assert_not_called()
        _, approval = self.requested()
        with self.assertRaises(APRefusal) as caught: self.k.distribution_packet(self.people['staff'], approval)
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.k.read(self.people['staff'], 'rfis')['count'], 1)

    def test_ended_membership_cannot_reach_global_metadata_or_record_facts(self):
        row = self.create(); self.c.plugin('people').end_membership(STAFF_LOGIN, self.project, reason='Synthetic project ended', actor=BOOTSTRAP_LOGIN)
        with patch.object(self.k, '_materials', side_effect=AssertionError('private metadata')) as facts:
            for call in (lambda: self.k.read(self.people['staff'], 'rfis'), lambda: self.k.rfi(self.people['staff'], row['id'])):
                with self.assertRaises(APRefusal) as caught: call()
                self.assertEqual(caught.exception.status, 403)
            facts.assert_not_called()

    def test_draft_and_official_response_keep_exact_cents_and_original_grant_separate_from_current_consumption(self):
        rfi, approval = self.answered(); before = self.state(); dto = self.k.rfi(self.people['staff'], rfi)
        self.assertEqual(dto['status'], 'answered'); self.assertEqual(dto['officialResponse']['costImpactCents'], 125005)
        self.assertEqual(dto['officialResponse']['author']['id'], self.people['staff'])
        self.assertEqual(dto['officialResponse']['reviewer']['id'], self.people['reviewer'])
        self.assertFalse(dto['officialResponse']['adopted']); self.assertFalse(dto['officialResponse']['engineeringCertification'])
        self.assertEqual(dto['responseApproval']['status'], 'consumed'); self.assertEqual(dto['responseApproval']['originalGrantStatus'], 'granted')
        self.assertEqual(dto['version'], self.k.version(self.people['staff'], rfi, 'rfi'))
        self.assertEqual(self.k.response_packet(self.people['staff'], approval)['reviewedResponse']['costImpactCents'], 125005)
        self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM journals'), 0); self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM changes'), 0)
        self.assertEqual(self.state(), before)

    def test_later_owned_revision_preserves_original_citation_and_sealed_review_heads(self):
        rfi, approval = self.requested(); old = self.k.response_packet(self.people['staff'], approval)
        later = self.c.evidence.add_revision(document_id=self.records['document_id'], content='Genuine later authored specification', actor=PM_LOGIN)
        before = self.state(); packet = self.k.response_packet(self.people['staff'], approval)
        cited = packet['currentCitations']['documents'][0]; original = packet['reviewedCitations']['documents'][0]
        self.assertEqual(cited['revisionId'], self.records['document_revision_id']); self.assertEqual(cited['currentRevisionId'], later['id'])
        self.assertTrue(cited['sourceChangedSinceReview']); self.assertEqual(original['currentRevisionId'], old['reviewedCitations']['documents'][0]['currentRevisionId'])
        self.assertEqual(packet['authorizationStatus'], 'stale'); self.assertEqual(self.state(), before)

    def test_current_permission_hold_discloses_original_facts_but_disables_new_source_choice(self):
        row = self.create(); rights = self.c.plugin('rights')
        license = rights.register_license('Synthetic', 'Restricted authored reference', '1', 'Holder', ['internal_reference'], actor=BOOTSTRAP_LOGIN)
        rights.tag_document(self.records['document_id'], license['id'], actor=BOOTSTRAP_LOGIN)
        before = self.state(); dto = self.k.rfi(self.people['staff'], row['id'])
        held = dto['citations']['documents'][0]; self.assertEqual(held['revisionId'], self.records['document_revision_id'])
        self.assertFalse(held['sourceContentAvailable']); self.assertTrue(all(not p['allowed'] for p in held['rights']))
        choice = next(p for p in self.k.preparation(self.people['staff'], self.project)['sources']['documents'] if p['documentId'] == self.records['document_id'])
        self.assertFalse(choice['citable']); self.assertEqual(choice['citationHold']['code'], 'project_use_required')
        self.assertEqual(self.state(), before)

    def test_raw_source_substitution_fails_closed_without_serving_question_or_counts(self):
        row = self.create()
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='field_rfis'"):
            self.c.db.execute('DROP TRIGGER "' + trigger['name'] + '"')
        self.c.db.execute('UPDATE field_rfis SET question=? WHERE id=?', ('Substituted private question', row['id']))
        for call in (lambda: self.k.rfi(self.people['staff'], row['id']), lambda: self.k.read(self.people['staff'], 'rfis')):
            with self.assertRaises(APRefusal) as caught: call()
            self.assertEqual((caught.exception.status, caught.exception.code), (423, 'rfi_source_unavailable'))

    def test_cursor_binds_person_query_and_actual_source_inventory(self):
        self.create(subject='A question'); self.create(subject='B question'); page = self.k.read(self.people['staff'], 'rfis', top=1)
        self.assertEqual(page['count'], 2); self.assertIsNotNone(page['nextCursor'])
        self.assertEqual(len(self.k.read(self.people['staff'], 'rfis', top=1, cursor=page['nextCursor'])['items']), 1)
        for person, kwargs in ((self.people['pm'], {}), (self.people['staff'], {'search': 'question'})):
            with self.assertRaises(APRefusal): self.k.read(person, 'rfis', top=1, cursor=page['nextCursor'], **kwargs)
        self.create(subject='C question')
        with self.assertRaises(APRefusal): self.k.read(self.people['staff'], 'rfis', top=1, cursor=page['nextCursor'])

    def test_public_projection_never_leaks_private_audit_hashes_or_source_bytes(self):
        row = self.create(); dto = self.k.rfi(self.people['staff'], row['id']); text = json.dumps(dto)
        for forbidden in ('proofHash', 'rowHash', 'sourceHash', 'payload_json', 'content_hash', 'manifest', 'documentBirth', 'revisionBirth'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(dto['citations']['documents'][0]['revisionId'], self.records['document_revision_id'])

    def test_missing_original_native_rfi_holds_owned_reads_and_keeps_hidden_resource_uniform(self):
        visible = self.create(); hidden = self.create(hidden=True)
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='field_rfis'"):
            self.c.db.execute('DROP TRIGGER "' + trigger['name'] + '"')
        # Model an offline file editor beyond the normal connection's guarded pragmas.
        with self.c.db._internal() as conn: conn.execute('PRAGMA foreign_keys=OFF')
        self.c.db.execute('DELETE FROM field_rfis WHERE id IN (?,?)', (visible['id'], hidden['id']))
        with self.c.db._internal() as conn: conn.execute('PRAGMA foreign_keys=ON')
        with self.assertRaises(APRefusal) as caught: self.k.rfi(self.people['staff'], visible['id'])
        self.assertEqual(caught.exception.status, 423)
        with patch.object(self.k, '_materials', side_effect=AssertionError('hidden deletion read proof')) as facts:
            with self.assertRaises(APRefusal) as caught: self.k.rfi(self.people['staff'], hidden['id'])
            self.assertEqual(caught.exception.status, 404); facts.assert_not_called()

    def test_missing_original_approval_holds_owned_packet_before_result_and_keeps_hidden_scope_uniform(self):
        rfi, approval = self.requested()
        for trigger in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='approvals'"):
            self.c.db.execute('DROP TRIGGER "' + trigger['name'] + '"')
        with self.c.db._internal() as conn: conn.execute('PRAGMA foreign_keys=OFF')
        self.c.db.execute('DELETE FROM approvals WHERE id=?', (approval,))
        with self.c.db._internal() as conn: conn.execute('PRAGMA foreign_keys=ON')
        with self.assertRaises(APRefusal) as caught: self.k.response_packet(self.people['staff'], approval)
        self.assertEqual(caught.exception.status, 423)

    def test_native_oversized_optional_days_are_held_before_public_json_number_projection(self):
        row = self.create()
        self.d.draft_response(row['id'], {'responseText': 'Synthetic native draft with unrepresentable browser days', 'costImpact': None, 'scheduleImpactDays': 9007199254740992}, actor=STAFF_LOGIN)
        with self.assertRaises(APRefusal) as caught: self.k.rfi(self.people['staff'], row['id'])
        self.assertEqual(caught.exception.status, 423)

    def test_departed_requester_holds_current_authorization_while_preserving_original_pending_status(self):
        rfi, approval = self.requested()
        self.c.plugin('people').end_membership(PM_LOGIN, self.project, reason='Synthetic requesting PM departure', actor=BOOTSTRAP_LOGIN)
        before = self.state(); packet = self.k.response_packet(self.people['staff'], approval)
        self.assertEqual(packet['status'], 'pending'); self.assertEqual(packet['authorizationStatus'], 'stale')
        self.assertEqual(packet['requester']['id'], self.people['pm']); self.assertIsNone(packet['originalGrantStatus'])
        self.assertEqual(self.state(), before)

    def test_departed_reviewer_holds_current_grant_and_preserves_original_grant(self):
        rfi, approval = self.requested(); self.c.approve(approval, approver=REVIEWER_LOGIN, approver_role='pm')
        self.c.plugin('people').end_membership(REVIEWER_LOGIN, self.project, reason='Synthetic reviewing PM departure', actor=BOOTSTRAP_LOGIN)
        before = self.state(); packet = self.k.response_packet(self.people['staff'], approval)
        self.assertEqual(packet['status'], 'granted'); self.assertEqual(packet['authorizationStatus'], 'stale')
        self.assertEqual(packet['originalGrantStatus'], 'granted'); self.assertEqual(self.state(), before)

    def test_later_requester_and_reviewer_departures_do_not_rewrite_consumed_original_response(self):
        rfi, approval = self.answered()
        for login in (PM_LOGIN, REVIEWER_LOGIN):
            self.c.plugin('people').end_membership(login, self.project, reason='Synthetic later original PM departure', actor=BOOTSTRAP_LOGIN)
        before = self.state(); packet = self.k.response_packet(self.people['staff'], approval)
        self.assertEqual(packet['status'], 'consumed'); self.assertEqual(packet['authorizationStatus'], 'consumed')
        self.assertEqual(packet['originalGrantStatus'], 'granted'); self.assertEqual(packet['rfi']['officialResponse']['status'], 'answered')
        self.assertEqual(self.state(), before)

    def test_resource_version_binds_current_original_pm_eligibility_used_by_authorization_disclosure(self):
        rfi, approval = self.requested(); before = self.k.version(self.people['staff'], approval, 'responseApproval')
        self.c.plugin('people').end_membership(PM_LOGIN, self.project, reason='Synthetic current original requester duty ended', actor=BOOTSTRAP_LOGIN)
        self.assertEqual(self.k.response_packet(self.people['staff'], approval)['authorizationStatus'], 'stale')
        self.assertNotEqual(self.k.version(self.people['staff'], approval, 'responseApproval'), before)

    def test_genuine_current_drawing_title_change_marks_review_disclosure_changed_without_replacing_citation(self):
        rfi, approval = self.requested()
        self.c.plugin('drawing').update_drawing(self.records['drawing_id'], title='Genuine revised drainage register title', actor=PM_LOGIN)
        packet = self.k.response_packet(self.people['staff'], approval)
        original = packet['reviewedCitations']['drawings'][0]; current = packet['currentCitations']['drawings'][0]
        self.assertEqual(current['revisionId'], original['revisionId']); self.assertNotEqual(current['title'], original['title'])
        self.assertEqual(packet['authorizationStatus'], 'stale'); self.assertTrue(current['sourceChangedSinceReview'])
