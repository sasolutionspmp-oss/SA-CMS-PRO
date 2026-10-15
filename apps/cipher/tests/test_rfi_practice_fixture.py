"""A fresh native source workspace with independently owned project duties."""
import unittest
from unittest.mock import patch

from apps.cipher.domain.rfi_controls import RFIError,require_rfi_duty
from apps.cipher.rfi_practice_fixture import (
    make_rfi_practice_fixture,BOOTSTRAP_LOGIN,STAFF_LOGIN,PM_LOGIN,REVIEWER_LOGIN,
    HIDDEN_PM_LOGIN,INACTIVE_LOGIN,EXTERNAL_LOGIN,SERVICE_LOGIN,
)
from apps.cipher.service import Cipher


class RFIPracticeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.c=make_rfi_practice_fixture();self.records=self.c.rfi_practice_records
        self.pid=self.records['project_id'];self.r=self.c.plugin('rfi_controls')

    def tearDown(self):self.c.db.close()

    def test_new_memory_native_service_reuses_required_plugin_and_has_no_adopted_effects(self):
        self.assertIs(type(self.c),Cipher);self.assertTrue(self.c.db.in_memory)
        self.assertIs(self.r,self.c._plugins['rfi_controls'])
        for table in ('field_rfis','rfi_sources','field_rfi_distributions','journals','changes','commitments'):
            with self.subTest(table=table):self.assertEqual(self.c.db.scalar('SELECT COUNT(*) FROM '+table),0)
        self.assertEqual(self.r.close_checks('2026-10'),[])

    def test_staff_and_two_distinct_owned_pms_with_hidden_and_inactive_controls(self):
        self.assertEqual(require_rfi_duty(self.c,STAFF_LOGIN,self.pid,'staff')['login'],STAFF_LOGIN)
        with self.assertRaises(RFIError):require_rfi_duty(self.c,STAFF_LOGIN,self.pid,'pm')
        pm=require_rfi_duty(self.c,PM_LOGIN,self.pid,'pm');reviewer=require_rfi_duty(self.c,REVIEWER_LOGIN,self.pid,'pm')
        self.assertNotEqual(pm['personId'],reviewer['personId'])
        for actor in (BOOTSTRAP_LOGIN,HIDDEN_PM_LOGIN,INACTIVE_LOGIN,EXTERNAL_LOGIN,SERVICE_LOGIN):
            with self.subTest(actor=actor),self.assertRaises(RFIError):require_rfi_duty(self.c,actor,self.pid,'staff')

    def test_issued_choice_remains_valid_with_newer_unissued_drawing_and_disabled_document(self):
        choices=self.r.preparation_sources(self.pid,actor=STAFF_LOGIN)
        self.assertEqual([p['revision']['id'] for p in choices['drawings']],[self.records['drawing_revision_id']])
        drawing=choices['drawings'][0]
        self.assertEqual(drawing['current']['workingRevisionId'],self.records['working_drawing_revision_id'])
        self.assertNotEqual(drawing['evidence']['revision']['id'],drawing['evidence']['currentRevision']['id'])
        support=next(p for p in choices['documents'] if p['document']['id']==self.records['document_id'])
        disabled=next(p for p in choices['documents'] if p['document']['id']==self.records['drawing_document_id'])
        self.assertTrue(support['citable']);self.assertIsNone(support['citationHold'])
        self.assertFalse(disabled['citable']);self.assertEqual(disabled['citationHold']['code'],'issued_drawing_required')

    def test_unknown_and_hidden_people_fail_before_source_inventory_reads(self):
        from apps.cipher.domain import rfi_controls
        with patch.object(rfi_controls,'owned_revision_proof',side_effect=AssertionError('private document proof read')):
            for actor,project in ((HIDDEN_PM_LOGIN,self.pid),(PM_LOGIN,self.records['hidden_project_id']),('unknown',self.pid)):
                with self.subTest(actor=actor),self.assertRaises(RFIError):self.r.preparation_sources(project,actor=actor)

    def test_separate_factories_have_no_shared_ids_or_mutated_source_state(self):
        other=make_rfi_practice_fixture()
        try:
            self.assertNotEqual(self.pid,other.rfi_practice_records['project_id'])
            body={'subject':'Independent synthetic question','question':'Which alignment should be used?',
                  'drawingRevisionIds':[self.records['drawing_revision_id']],
                  'documentRevisionIds':[self.records['document_revision_id']]}
            self.r.create(self.pid,body,actor=STAFF_LOGIN)
            self.assertEqual(other.db.scalar('SELECT COUNT(*) FROM field_rfis'),0)
            self.assertEqual(set(self.c.rfi_practice_persona_people),{'staff','pm','reviewer'})
            self.assertTrue(all(recipient.endswith('@synthetic-rfi.invalid') for recipient in self.records['allowed_recipients']))
        finally:other.db.close()

    def test_empty_qualified_source_governor_does_not_change_native_legacy_rfi_close_material(self):
        legacy=self.c.plugin('field').create_rfi(self.pid,'Legacy synthetic question','Which legacy alignment applies?',actor=STAFF_LOGIN,
            drawing_revision_ids=[self.records['drawing_revision_id']],document_revision_ids=[self.records['document_revision_id']])
        self.assertFalse(self.r.is_modern(legacy['id']));self.assertEqual(self.r.close_checks('2026-10'),[])

    def test_surviving_actual_receipt_schema_cannot_hide_lost_source_admission(self):
        from apps.cipher.rfi_receipts import register_rfi_receipts_schema
        register_rfi_receipts_schema();self.c.db.migrate()
        for table in ('rfi_approval_sources','rfi_distribution_revisions','rfi_response_revisions','rfi_sources'):
            self.c.db.execute('DROP TABLE '+table)
        self.c.db.execute("DELETE FROM schema_version WHERE name='rfi_sources_and_review_contexts'")
        with self.assertRaises(RFIError):self.r.is_modern('unknown-rfi')

    def test_extreme_admission_integers_refuse_without_allocating_from_raw_metadata(self):
        from apps.cipher.domain import rfi_controls
        for value in (9223372036854775807,-9223372036854775808):
            with self.subTest(version=value):
                self.c.db.execute("UPDATE schema_version SET version=? WHERE name='rfi_sources_and_review_contexts'",(value,))
                try:
                    with patch.object(rfi_controls,'range',side_effect=AssertionError('raw metadata controls allocation'),create=True):
                        with self.assertRaises(RFIError):self.r._schema_installed()
                finally:self.c.db.execute("UPDATE schema_version SET version=78 WHERE name='rfi_sources_and_review_contexts'")


if __name__=='__main__':unittest.main()
