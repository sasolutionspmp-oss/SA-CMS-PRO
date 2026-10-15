"""Issued-at-birth drawing proof stays distinct from a genuine newer head."""
import unittest

from apps.cipher.core.ids import new_id,utcnow_iso
from apps.cipher.domain.drawing_sources import issued_drawing_proof
from apps.cipher.domain.owned_sources import OwnedSourceError
from apps.cipher.service import Cipher


class DrawingSourceTests(unittest.TestCase):
    def setUp(self):
        self.c=Cipher(':memory:');self.drawing=self.c.plugin('drawing')
        self.pid=self.c.create_project(name='Drawing source',entity='Synthetic',budget='0')['id']
        self.c.open_period('D1','Drawing period','2026-10-01','2026-10-31')
        self.doc=self.c.evidence.register_document(project_id=self.pid,kind='drawing',title='Authored drawing',actor='author')
        self.ev=self.c.evidence.add_revision(document_id=self.doc['id'],content='Drawing first revision',actor='author')
        self.header=self.drawing.register_drawing(self.pid,'C-101','Drainage detail','Civil',actor='author')
        self.one=self.drawing.add_revision(self.header['id'],'A',self.ev['id'],note='First issue',actor='author')
        self.ap=self.c.request_approval('drawing.issue',self.one['id'],actor_role='pm',requested_by='requester')
        self.c.approve(self.ap['id'],approver='reviewer',approver_role='pm')
        self.c.execute(self.ap['id'],actor='issuer',period_id='D1')

    def tearDown(self):self.c.db.close()

    def drop_guards(self,table):
        for row in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,)):
            self.c.db.execute('DROP TRIGGER "'+row['name'].replace('"','""')+'"')

    def later_working(self):
        ev=self.c.evidence.add_revision(document_id=self.doc['id'],content='Drawing working B',actor='author')
        return self.drawing.add_revision(self.header['id'],'B',ev['id'],actor='author')

    def test_new_working_evidence_does_not_make_issued_source_unusable(self):
        later=self.later_working();before=self.c.db.conn.total_changes
        proof=issued_drawing_proof(self.c,self.pid,self.one['id'],current=True)
        self.assertEqual(proof['current']['issuedRevisionId'],self.one['id'])
        self.assertEqual(proof['current']['workingRevisionId'],later['id'])
        self.assertFalse(proof['evidence']['revision']['id']==proof['evidence']['currentRevision']['id'])
        self.assertEqual(proof['issuedAtBirth']['approval']['record']['id'],self.ap['id'])
        self.assertEqual(before,self.c.db.conn.total_changes)

    def test_genuine_supersession_preserves_original_issued_proof(self):
        later=self.later_working()
        ap=self.c.request_approval('drawing.issue',later['id'],actor_role='pm',requested_by='requester')
        self.c.approve(ap['id'],approver='reviewer',approver_role='pm');self.c.execute(ap['id'],actor='issuer',period_id='D1')
        proof=issued_drawing_proof(self.c,self.pid,self.one['id'])
        self.assertEqual(proof['revision']['status'],'superseded')
        self.assertEqual(proof['current']['issuedRevisionId'],later['id'])
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'],current=True)

    def test_working_revision_has_no_issued_birth_even_with_forged_status(self):
        later=self.later_working();self.drop_guards('drawing_revisions')
        self.c.db.execute("UPDATE drawing_revisions SET status='superseded',superseded_at='2000-01-01',superseded_by=? WHERE id=?",(later['id'],self.one['id']))
        self.c.db.execute("UPDATE drawing_revisions SET status='issued',approval_id=?,issued_period_id='D1',issued_at='2000-01-01' WHERE id=?",(self.ap['id'],later['id']))
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,later['id'])

    def test_same_id_binding_and_note_edit_is_refused(self):
        self.drop_guards('drawing_revisions');self.c.db.execute('UPDATE drawing_revisions SET note=? WHERE id=?',('Replaced source note',self.one['id']))
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'])

    def test_deleted_later_revision_does_not_hide_drawing_inventory(self):
        later=self.later_working();self.drop_guards('drawing_revisions')
        self.c.db.execute('DELETE FROM drawing_revisions WHERE id=?',(later['id'],))
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'])

    def test_exact_rfi_reference_and_deleted_birth_are_proved(self):
        rfi=self.c.plugin('field').create_rfi(self.pid,'Clash','Resolve the clash?',actor='author',drawing_revision_ids=[self.one['id']])
        link=rfi['links'][0]
        proof=issued_drawing_proof(self.c,self.pid,self.one['id'],reference_id=link['reference_id'],referenced_by_id=rfi['id'])
        self.assertEqual(proof['reference']['record']['referenced_by_id'],rfi['id'])
        self.drop_guards('drawing_references');self.c.db.execute('DELETE FROM drawing_references WHERE id=?',(link['reference_id'],))
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'],reference_id=link['reference_id'],referenced_by_id=rfi['id'])

    def test_foreign_reference_cannot_be_relabelled_for_another_rfi(self):
        ref=self.drawing.reference(self.one['id'],'rfi','original-rfi',actor='author')
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'],reference_id=ref['id'],referenced_by_id='other-rfi')

    def test_audited_raw_reference_after_supersession_is_not_issued_at_citation(self):
        later=self.later_working()
        ap=self.c.request_approval('drawing.issue',later['id'],actor_role='pm',requested_by='requester')
        self.c.approve(ap['id'],approver='reviewer',approver_role='pm');self.c.execute(ap['id'],actor='issuer',period_id='D1')
        self.drop_guards('drawing_references');identifier=new_id('dref')
        self.c.db.execute('INSERT INTO drawing_references (id,drawing_id,drawing_revision_id,referenced_by_type,referenced_by_id,content_hash,created_at) VALUES (?,?,?,?,?,?,?)',
            (identifier,self.header['id'],self.one['id'],'rfi','late-rfi',self.ev['content_hash'],utcnow_iso()))
        self.c.audit.record('author','drawing.referenced','drawing_reference',identifier,
            {'drawing_id':self.header['id'],'number':'C-101','drawing_revision_id':self.one['id'],'label':'A',
             'referenced_by_type':'rfi','referenced_by_id':'late-rfi','content_hash':self.ev['content_hash']})
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'],reference_id=identifier,referenced_by_id='late-rfi')

    def test_consumed_issue_grant_identity_and_deadline_are_original(self):
        self.drop_guards('approvals')
        self.c.db.execute("UPDATE approvals SET expires_at='2999-01-01T00:00:00Z' WHERE id=?",(self.ap['id'],))
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'])

    def test_raw_register_version_or_metadata_is_not_an_update(self):
        self.drop_guards('drawing_register')
        self.c.db.execute('UPDATE drawing_register SET title=?,version=version+1 WHERE id=?',('Unaudited title',self.header['id']))
        with self.assertRaises(OwnedSourceError):issued_drawing_proof(self.c,self.pid,self.one['id'])

    def test_genuine_metadata_and_working_replacement_history_are_supported(self):
        working=self.later_working();ev=self.c.evidence.add_revision(document_id=self.doc['id'],content='Corrected working B',actor='author')
        replacement=self.drawing.replace_working(self.header['id'],ev['id'],actor='author',note='Corrected')
        self.drawing.update_drawing(self.header['id'],title='Drainage and grading detail',actor='author')
        proof=issued_drawing_proof(self.c,self.pid,self.one['id'],current=True)
        self.assertEqual(proof['current']['workingRevisionId'],replacement['id'])
        old=next(r for r in proof['revisions'] if r['record']['id']==working['id'])
        self.assertEqual(old['record']['status'],'withdrawn')


if __name__=='__main__':unittest.main()
