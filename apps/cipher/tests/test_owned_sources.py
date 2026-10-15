"""Pure source proofs compare native rows with their original audited inventory."""
import json
import unittest

from apps.cipher.core.ids import new_id, utcnow_iso
from apps.cipher.domain.owned_sources import OwnedSourceError, owned_revision_proof, document_rights_proof
from apps.cipher.service import Cipher


class OwnedSourceTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher(':memory:')
        self.project = self.c.create_project(name='Source proof project', entity='Synthetic', budget='0')
        self.pid = self.project['id']
        self.doc = self.c.evidence.register_document(project_id=self.pid, kind='specification', title='Authored specification', actor='author')
        self.one = self.c.evidence.add_revision(document_id=self.doc['id'], content='Original authored text', note='First', actor='author')
        self.rights = self.c.plugin('rights')

    def tearDown(self):
        self.c.db.close()

    def drop_guards(self, table):
        for row in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)):
            self.c.db.execute('DROP TRIGGER "'+row['name'].replace('"','""')+'"')

    def license(self, **extra):
        return self.rights.register_license('Synthetic licensor','Reference work','1','Synthetic holder',
            ['internal_reference','project_use','distribution'],actor='rights-person',**extra)

    def test_historical_revision_and_current_head_are_separate_pure_facts(self):
        second = self.c.evidence.add_revision(document_id=self.doc['id'],content='Later text',note='Second',actor='editor')
        before = self.c.db.conn.total_changes
        proof = owned_revision_proof(self.c,self.pid,self.one['id'])
        self.assertEqual(proof['revision']['id'],self.one['id'])
        self.assertEqual(proof['currentRevision']['id'],second['id'])
        self.assertEqual(len(proof['revisions']),2)
        self.assertEqual(before,self.c.db.conn.total_changes)
        with self.assertRaises(OwnedSourceError):
            owned_revision_proof(self.c,self.pid,self.one['id'],current=True)

    def test_same_id_revision_hash_and_note_edit_is_not_a_new_source(self):
        self.drop_guards('document_revisions')
        self.c.db.execute('UPDATE document_revisions SET content_hash=?,note=? WHERE id=?',('0'*64,'Edited',self.one['id']))
        with self.assertRaises(OwnedSourceError):owned_revision_proof(self.c,self.pid,self.one['id'])

    def test_deleted_original_head_does_not_make_earlier_revision_current(self):
        second = self.c.evidence.add_revision(document_id=self.doc['id'],content='Later',actor='editor')
        self.drop_guards('document_revisions')
        self.c.db.execute('DELETE FROM document_revisions WHERE id=?',(second['id'],))
        with self.assertRaises(OwnedSourceError):owned_revision_proof(self.c,self.pid,self.one['id'],current=True)

    def test_document_identity_and_inventory_are_bound_to_original_birth(self):
        self.drop_guards('documents')
        self.c.db.execute('UPDATE documents SET title=? WHERE id=?',('Substituted work',self.doc['id']))
        with self.assertRaises(OwnedSourceError):owned_revision_proof(self.c,self.pid,self.one['id'])

    def test_duplicate_audited_revision_birth_is_not_an_extra_valid_revision(self):
        self.c.audit.record('author','document.revised','document',self.doc['id'],
            {'revision_id':self.one['id'],'revision':1,'content_hash':self.one['content_hash'],'note':'First'})
        with self.assertRaises(OwnedSourceError):owned_revision_proof(self.c,self.pid,self.one['id'])

    def test_cross_project_revision_refused_before_private_source_is_returned(self):
        other=self.c.create_project(name='Other project',entity='Synthetic',budget='0')
        with self.assertRaises(OwnedSourceError):owned_revision_proof(self.c,other['id'],self.one['id'])

    def test_deleted_license_tag_does_not_become_unlicensed_company_content(self):
        lic=self.license();tag=self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        self.drop_guards('rights_document_tags')
        self.c.db.execute('DELETE FROM rights_document_tags WHERE id=?',(tag['id'],))
        self.assertTrue(self.rights.check_use(self.doc['id'],'project_use')['allowed'])
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')

    def test_changed_terms_with_recomputed_hash_still_fail_original_audit(self):
        lic=self.license();self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        self.drop_guards('rights_license_versions')
        uses=['project_use']
        identity={key:lic[key] for key in ('licensor','work','edition','holder')}
        forged=self.rights._terms_hash(identity,uses,[],None,False)
        self.c.db.execute('UPDATE rights_license_versions SET permitted_uses=?,terms_hash=? WHERE license_id=?',
            (json.dumps(uses),forged,lic['id']))
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')

    def test_genuine_version_and_untag_retain_license_history(self):
        lic=self.license();self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        self.rights.update_license(lic['id'],permitted_uses=['project_use'],actor='rights-person')
        self.rights.untag_document(self.doc['id'],lic['id'],actor='rights-person',reason='Reference removed')
        before=self.c.db.conn.total_changes
        proof=document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')
        self.assertTrue(proof['allowed']);self.assertTrue(proof['hadLicenseHistory'])
        self.assertEqual(proof['tags'][0]['status'],'removed')
        self.assertEqual(len(proof['licenses'][0]['versions']),2)
        self.assertEqual(before,self.c.db.conn.total_changes)

    def test_deleted_terms_version_or_license_header_is_an_integrity_hold(self):
        lic=self.license();self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        self.rights.update_license(lic['id'],permitted_uses=['project_use'],actor='rights-person')
        self.drop_guards('rights_license_versions')
        self.c.db.execute('DELETE FROM rights_license_versions WHERE license_id=? AND version=1',(lic['id'],))
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')

    def test_purge_inventory_is_original_even_when_current_permission_is_denied(self):
        lic=self.license(expires_on='2000-01-01',purge_on_expiry=True)
        self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        purge=self.rights.record_purge(self.doc['id'],lic['id'],actor='rights-person',note='Synthetic attestation')
        proof=document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')
        self.assertFalse(proof['allowed']);self.assertEqual(proof['purges'][0]['id'],purge['id'])
        self.drop_guards('rights_purges')
        self.c.db.execute('DELETE FROM rights_purges WHERE id=?',(purge['id'],))
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')

    def test_default_processor_settings_cannot_be_rewritten_or_deleted(self):
        lic=self.rights.register_license('Synthetic','AI reference','1','Holder',['ai_retrieval'],processors=['local'],actor='rights-person')
        self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        setting=self.rights.set_default_processor('local',actor='rights-person')
        self.assertTrue(document_rights_proof(self.c,self.pid,self.doc['id'],'ai_retrieval')['allowed'])
        self.drop_guards('rights_ai_processor_settings')
        self.c.db.execute('DELETE FROM rights_ai_processor_settings WHERE version=?',(setting['version'],))
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'ai_retrieval')

    def test_pending_unadopted_terms_hold_until_genuine_native_repair(self):
        lic=self.license();self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        identity={key:lic[key] for key in ('licensor','work','edition','holder')}
        terms_hash=self.rights._terms_hash(identity,['distribution'],[],None,False)
        self.c.db.execute('INSERT INTO rights_license_versions (id,license_id,version,permitted_uses,processors,expires_on,purge_on_expiry,note,terms_hash,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (new_id('licv'),lic['id'],2,json.dumps(['distribution']),'[]',None,0,'Unaudited pending row',terms_hash,'raw-writer',utcnow_iso()))
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')
        fixed=self.rights.supersede_unadopted_version(lic['id'],actor='rights-person',note='Restore original qualified terms')
        proof=document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')
        self.assertEqual(fixed['version'],3);self.assertTrue(proof['allowed'])
        self.assertEqual([v['unadopted'] for v in proof['licenses'][0]['versions']],[False,True,False])

    def test_rewinding_current_license_head_does_not_hide_genuine_update(self):
        lic=self.license();self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        self.rights.update_license(lic['id'],permitted_uses=['distribution'],actor='rights-person')
        self.drop_guards('rights_licenses')
        self.c.db.execute('UPDATE rights_licenses SET version=1 WHERE id=?',(lic['id'],))
        with self.assertRaises(OwnedSourceError):document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')

    def test_pure_permission_change_retains_original_source_and_reports_new_rights(self):
        lic=self.license();self.rights.tag_document(self.doc['id'],lic['id'],actor='rights-person')
        original=document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')
        self.rights.update_license(lic['id'],permitted_uses=['distribution'],actor='rights-person')
        current=document_rights_proof(self.c,self.pid,self.doc['id'],'project_use')
        self.assertTrue(original['allowed']);self.assertFalse(current['allowed'])
        self.assertNotEqual(original['proofHash'],current['proofHash'])
        self.assertEqual(original['tags'],current['tags'])


if __name__=='__main__':unittest.main()
