"""Actual77→79 history, copied-file claims and real migration rollback."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.core import db as core_db
from apps.cipher.core.ids import canonical_json,loads
from apps.cipher.domain.rfi_controls import SCHEMA_NAME as SOURCE_SCHEMA
from apps.cipher.domain.drawing_sources import consumed_approval_proof,issued_drawing_proof
from apps.cipher.domain.owned_sources import owned_revision_proof
from apps.cipher.rfi_contract import RFIContract
from apps.cipher.rfi_receipts import SCHEMA_NAME as RECEIPT_SCHEMA,RFIReceipts
from apps.cipher.rfi_practice_fixture import BOOTSTRAP_LOGIN,STAFF_LOGIN,PM_LOGIN
from apps.cipher.service import Cipher
from apps.cipher.tests.rfi_upgrade_helpers import (
    HistoricalRFI77,SECRET,genuine_catalog,historical_catalog,library_runner,storage_snapshot,
)


class RFIUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cipher-rfi-upgrade-');self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)

    def world(self):
        world=HistoricalRFI77();self.addCleanup(world.c.db.close);return world

    def assert_original_storage(self,db,before,*,mutable=()):
        objects={row['name']:row for row in storage_snapshot(db)['objects']}
        for original in before['objects']:
            with self.subTest(object=original['name']):self.assertEqual(objects[original['name']],original)
        for name,rows in before['tables'].items():
            if name in mutable:continue
            actual=sorted(db.query('SELECT * FROM "'+name.replace('"','""')+'"'),key=canonical_json)
            with self.subTest(table=name):self.assertEqual(actual,rows)

    def assert_no_legacy_adoption(self,c,world):
        controls=c.plugin('rfi_controls');self.assertFalse(controls.is_modern(world.rfi['id']))
        self.assertEqual(controls.source_inventory((world.pid,)),[]);self.assertEqual(controls.close_checks('2026-10'),[])
        self.assertEqual(c.db.scalar('SELECT COUNT(*) FROM rfi_action_receipts'),0)
        contract=RFIContract(c,secret=SECRET)
        with self.assertRaises(APRefusal) as missing:contract.rfi(world.staff,world.rfi['id'])
        self.assertEqual(missing.exception.status,404)
        self.assertEqual(contract.read(world.staff,'rfis')['count'],0)
        self.assertEqual(c.plugin('field').rfi(world.rfi['id'])['status'],'answered')
        self.assertEqual(c.plugin('field').rfi(world.rfi['id'])['response'],world.official_response)

    def test_real_77_history_upgrades_exactly_and_old_rfi_is_never_auto_attested(self):
        w=self.world();c=w.c;before=storage_snapshot(c.db)
        self.assertEqual(c.db.schema_status()['current_version'],77)
        self.assertEqual(c.db.scalar('SELECT COUNT(*) FROM journals'),1)
        self.assertEqual(c.db.scalar('SELECT COUNT(*) FROM library_action_receipts'),6)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('rfi_sources','rfi_action_receipts')"),0)
        original_reference=w.library.original_reference_proof(w.reference_id)
        original_proofs={
            'drawing':issued_drawing_proof(c,w.pid,w.records['drawing_revision_id']),
            'document':owned_revision_proof(c,w.pid,w.records['document_revision_id']),
            'response':consumed_approval_proof(c,w.response_id,'field.respond_rfi','field_rfi',w.rfi['id']),
            'distribution':consumed_approval_proof(c,w.distribution_id,'field.distribute_rfi','field_rfi',w.rfi['id']),
        }
        applied=c.db.migrate()
        self.assertEqual([(row['version'],row['name']) for row in applied],[(78,SOURCE_SCHEMA),(79,RECEIPT_SCHEMA)])
        self.assert_original_storage(c.db,before,mutable=('schema_version',))
        self.assertEqual(c.db.query('SELECT * FROM schema_version WHERE version<=77 ORDER BY version'),
                         sorted(before['tables']['schema_version'],key=lambda row:row['version']))
        self.assertEqual(w.library.original_reference_proof(w.reference_id),original_reference)
        self.assertEqual(original_proofs,{
            'drawing':issued_drawing_proof(c,w.pid,w.records['drawing_revision_id']),
            'document':owned_revision_proof(c,w.pid,w.records['document_revision_id']),
            'response':consumed_approval_proof(c,w.response_id,'field.respond_rfi','field_rfi',w.rfi['id']),
            'distribution':consumed_approval_proof(c,w.distribution_id,'field.distribute_rfi','field_rfi',w.rfi['id']),
        })
        self.assert_no_legacy_adoption(c,w)
        self.assertTrue(c.audit.verify_chain()['ok']);self.assertEqual(c.provider.submissions,[])
        # New qualified work is explicit and gets a new question/source, without
        # adopting the genuine preexisting legacy answer or its native grant.
        modern=c.plugin('rfi_controls').create(w.pid,{'subject':'New qualified source after upgrade',
            'question':'Which new connection needs independent review?','drawingRevisionIds':[w.records['drawing_revision_id']],
            'documentRevisionIds':[w.records['document_revision_id']]},actor=STAFF_LOGIN)
        self.assertNotEqual(modern['id'],w.rfi['id']);self.assertTrue(c.plugin('rfi_controls').is_modern(modern['id']))
        self.assertFalse(c.plugin('rfi_controls').is_modern(w.rfi['id']))
        self.assertEqual(c.db.scalar('SELECT COUNT(*) FROM journals'),1)

    def test_six_genuine_library_receipts_replay_original_after_rfi_admission(self):
        w=self.world();w.c.db.migrate();before=storage_snapshot(w.c.db)
        for request,original in w.requests:
            replay=w.runner.run(*request[:4],repeatability_key=request[4],if_match=request[5])
            self.assertEqual(replay,{**original,'replayed':True,'effectApplied':False})
        self.assertEqual(storage_snapshot(w.c.db),before)
        self.assertTrue(w.runner.integrity_checks()['ok'])
        self.assertEqual(w.c.execute(w.response_id,actor=PM_LOGIN).result,w.answer.result)
        self.assertEqual(w.c.execute(w.distribution_id,actor=PM_LOGIN).result,w.distribution.result)

    def test_owned_physical_77_copy_upgrades_quarantined_then_requires_attested_claim(self):
        w=self.world();owned_path=self.directory/'owned77.sqlite';copy_path=self.directory/'copied79.sqlite'
        w.c.snapshot(str(owned_path))
        with historical_catalog():owned=Cipher(str(owned_path))
        self.addCleanup(owned.db.close)
        owner_secret='synthetic-rfi-upgrade-owner-secret'
        with patch.dict(os.environ,{'CIPHER_OWNER_SECRET':owner_secret}):
            owned.claim_write_authority(actor=BOOTSTRAP_LOGIN,reason='Synthetic original physical77 ownership',
                claim_code=owned.db.expected_claim_code(owner_secret))
        self.assertTrue(owned.db.has_write_authority());self.assertEqual(owned.db.schema_status()['current_version'],77)
        before=storage_snapshot(owned.db);owned.snapshot(str(copy_path))
        self.assertFalse(Path(str(copy_path)+'.authority').exists())
        upgraded=Cipher.open_restored(str(copy_path));self.addCleanup(upgraded.db.close)
        self.assertTrue(upgraded.db.read_only);self.assertFalse(upgraded.db.has_write_authority())
        self.assertEqual(upgraded.db.scalar('PRAGMA query_only'),1)
        self.assert_original_storage(upgraded.db,before,mutable=('schema_version','audit_log'))
        original_audit=sorted(before['tables']['audit_log'],key=lambda row:row['seq'])
        self.assertEqual(upgraded.db.query('SELECT * FROM audit_log WHERE seq<=? ORDER BY seq',(original_audit[-1]['seq'],)),original_audit)
        migration=upgraded.audit.entries()[-1]
        self.assertEqual(migration['action'],'workspace.schema_migrated_without_authority')
        self.assertEqual([row['name'] for row in loads(migration['payload_json'])['entries']],[SOURCE_SCHEMA,RECEIPT_SCHEMA])
        self.assert_no_legacy_adoption(upgraded,w)
        self.assertTrue(library_runner(upgraded).integrity_checks()['ok'])
        with self.assertRaises(core_db.WriteAuthorityError):upgraded.db.execute('DELETE FROM field_rfis')
        RFIReceipts(upgraded.db,upgraded.audit).verify_integrity()
        before_claim=storage_snapshot(upgraded.db);old_workspace=upgraded.db.workspace()
        with patch.dict(os.environ,{'CIPHER_OWNER_SECRET':owner_secret}):
            with self.assertRaises(core_db.WriteAuthorityError):
                upgraded.claim_write_authority(actor=BOOTSTRAP_LOGIN,reason='Synthetic wrong claim',claim_code='wrong')
            self.assertEqual(storage_snapshot(upgraded.db),before_claim)
            upgraded.claim_write_authority(actor=BOOTSTRAP_LOGIN,reason='Synthetic attested copied-file claim',
                claim_code=upgraded.db.expected_claim_code(owner_secret))
        self.assertFalse(upgraded.db.read_only);self.assertTrue(upgraded.db.has_write_authority())
        self.assertTrue(upgraded.db.authority_status()['release_quarantined'])
        self.assertEqual(upgraded.db.workspace()['workspace_id'],old_workspace['workspace_id'])
        self.assertEqual(upgraded.db.workspace()['recovery_epoch'],old_workspace['recovery_epoch']+1)
        self.assertEqual(Path(str(copy_path)+'.authority').read_text(),upgraded.db.workspace()['instance_token'])
        claimed=upgraded.audit.entries()[-1]
        self.assertEqual(claimed['action'],'workspace.claim_write_authority')
        self.assertEqual(loads(claimed['payload_json'])['owner_claim_code'],'verified')
        self.assert_original_storage(upgraded.db,before_claim,mutable=('workspace','audit_log'))
        self.assert_no_legacy_adoption(upgraded,w);self.assertEqual(upgraded.provider.submissions,[])

    def test_failure_in_actual_78_or_79_statement_rolls_back_both_new_admissions(self):
        w=self.world();before=tuple(w.c.db.conn.iterdump());actual=list(core_db.SCHEMA_CATALOG)
        original_execute=core_db.AuthorityConnection.execute
        for version in (78,79):
            with self.subTest(failed_version=version):
                path=self.directory/f'failed-{version}.sqlite';w.c.snapshot(str(path));failed=[]
                statement=actual[version-1][2][-1]
                def execute(conn,sql,*args,**kwargs):
                    if sql==statement:
                        failed.append(sql);raise sqlite3.OperationalError('Injected actual RFI migration statement failure')
                    return original_execute(conn,sql,*args,**kwargs)
                with patch.object(core_db.AuthorityConnection,'execute',new=execute):
                    with self.assertRaisesRegex(sqlite3.OperationalError,'Injected actual RFI'):
                        Cipher(str(path))
                self.assertEqual(failed,[statement]);self.assertFalse(Path(str(path)+'.authority').exists())
                with sqlite3.connect(path) as check:
                    self.assertEqual(tuple(check.iterdump()),before)
                    self.assertEqual(check.execute('SELECT MAX(version) FROM schema_version').fetchone()[0],77)
                    self.assertEqual(check.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'rfi_%'").fetchone()[0],0)
                recovered=Cipher(str(path))
                try:
                    self.assertEqual(recovered.db.schema_status()['current_version'],79)
                    self.assertTrue(recovered.db.read_only);self.assert_no_legacy_adoption(recovered,w)
                    self.assertTrue(library_runner(recovered).integrity_checks()['ok'])
                finally:recovered.db.close()

    def test_pre_mode_copy_uses_real_named_physical_shift_then_claims_original_mode_last(self):
        # A native pre-mode65 Database, not a current database with mode removed.
        with historical_catalog(65):original=core_db.Database(':memory:')
        self.addCleanup(original.close);path=self.directory/'pre-mode-copy.sqlite'
        original.snapshot(str(path));upgraded=Cipher(str(path));self.addCleanup(upgraded.db.close)
        self.assertEqual(upgraded.db.mode_status()['state'],'pending_practice_declaration')
        self.assertTrue(upgraded.db.read_only);self.assertFalse(upgraded.db.has_write_authority())
        self.assertIsNone(upgraded.db.one('SELECT version FROM schema_version WHERE name=?',(core_db.MODE_SCHEMA_NAME,)))
        self.assertEqual(upgraded.db.one('SELECT version FROM schema_version WHERE name=?',(SOURCE_SCHEMA,))['version'],77)
        self.assertEqual(upgraded.db.one('SELECT version FROM schema_version WHERE name=?',(RECEIPT_SCHEMA,))['version'],78)
        self.assertTrue(upgraded.plugin('rfi_controls')._schema_installed())
        self.assertEqual(upgraded.db.scalar('SELECT COUNT(*) FROM rfi_sources'),0)
        before=storage_snapshot(upgraded.db);owner_secret='synthetic-rfi-pre-mode-owner-secret'
        with patch.dict(os.environ,{'CIPHER_OWNER_SECRET':owner_secret}):
            code=upgraded.db.expected_claim_code(owner_secret)
            with patch.object(upgraded.db,'_write_sidecar',side_effect=OSError('Synthetic claim publication fault')):
                with self.assertRaises(OSError):upgraded.claim_write_authority(actor='owner',reason='Synthetic failed pre-mode claim',claim_code=code)
            self.assertEqual(storage_snapshot(upgraded.db),before)
            self.assertFalse(Path(str(path)+'.authority').exists());self.assertTrue(upgraded.db.read_only)
            upgraded.claim_write_authority(actor='owner',reason='Synthetic attested pre-mode adoption',claim_code=code)
        self.assertEqual(upgraded.db.one('SELECT version FROM schema_version WHERE name=?',(core_db.MODE_SCHEMA_NAME,))['version'],79)
        self.assertEqual(upgraded.db.one('SELECT version FROM schema_version WHERE name=?',(SOURCE_SCHEMA,))['version'],77)
        self.assertEqual(upgraded.db.one('SELECT version FROM schema_version WHERE name=?',(RECEIPT_SCHEMA,))['version'],78)
        self.assertTrue(upgraded.db.mode_status()['verified']);self.assertFalse(upgraded.db.read_only)
        self.assertTrue(upgraded.plugin('rfi_controls')._schema_installed())
        RFIReceipts(upgraded.db,upgraded.audit).verify_integrity()
        self.assertEqual(len([entry for entry in upgraded.audit.entries() if entry['action']==core_db.MODE_ACTION]),1)
        self.assertEqual(upgraded.plugin('rfi_controls').close_checks('none'),[])
        self.assertTrue(upgraded.audit.verify_chain()['ok'])


if __name__=='__main__':unittest.main()
