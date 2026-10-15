"""Cold required-module admission preserves every genuine schema1–75 statement."""
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from apps.cipher import service
from apps.cipher.core import db
from apps.cipher.domain import library


class LibraryLoadingTests(unittest.TestCase):
    def test_cold_import_is_inert_and_native_loader_appends76(self):
        script = r'''
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.core.ids import hash_json
before = hash_json(SCHEMA_CATALOG)
from apps.cipher.domain import library
assert hash_json(SCHEMA_CATALOG)==before
assert library.DEFER_SCHEMA_REGISTRATION is True
assert library.Plugin.GOVERNOR is True
from apps.cipher.service import Cipher, PLUGIN_MODULES
assert PLUGIN_MODULES[-3:]==['apps.cipher.domain.owner_billing','apps.cipher.domain.library','apps.cipher.domain.rfi_controls']
assert hash_json(SCHEMA_CATALOG[:75])=='0b65915a8926593f21dbd2881166fb1ddff2684aac6ccdf955750fa5c5dac479'
assert SCHEMA_CATALOG[75][1]=='library_authored_text_and_reference_adoptions'
assert SCHEMA_CATALOG[76][1]=='library_practice_action_receipts'
assert SCHEMA_CATALOG[77][1]=='rfi_sources_and_review_contexts'
assert SCHEMA_CATALOG[78][1]=='rfi_practice_action_receipts'
assert hash_json(SCHEMA_CATALOG[:77])=='19d15d425da704d8df3e9c8a343687ddd1fe52aafecdad6c0446c7dd64a30dda'
c=Cipher(':memory:')
assert c.plugin('library').state()['entries']==[]
assert c.db.scalar('SELECT count(*) FROM schema_version')==79
assert all(check['ok'] for check in c.plugin('library').close_checks('2026-10'))
c.db.close()
'''
        result = subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_genuine75_workspace_stays_inert_then_upgrades_by_name(self):
        script = r'''
from apps.cipher.service import Cipher
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.core.ids import hash_json
catalog=list(SCHEMA_CATALOG)
SCHEMA_CATALOG[:]=catalog[:75]
c=Cipher(':memory:')
assert c.plugin('library').state()=={'entries':[],'references':[],'checks':[]}
original=c.db.query('SELECT version,name,statement_count,checksum FROM schema_version ORDER BY version')
SCHEMA_CATALOG[:]=catalog
c.db.migrate()
assert c.db.query('SELECT version,name,statement_count,checksum FROM schema_version ORDER BY version')[:75]==original
assert c.db.scalar("SELECT count(*) FROM schema_version WHERE name='library_authored_text_and_reference_adoptions'")==1
assert c.plugin('library').state()['entries']==[]
c.db.close()
'''
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_known_library_must_keep_exact_namespace_defer_prefix_governor_and_registrar(self):
        name='apps.cipher.domain.library'
        for key,value in (('__name__','apps.cipher.domain.alias'),('DEFER_SCHEMA_REGISTRATION',1),
                          ('PLUGIN_NAME','other'),('register_library_schema',None),('SCHEMA_NAME','other')):
            mod=SimpleNamespace(__name__=name,SCHEMA_NAME=library.SCHEMA_NAME,SCHEMA_STATEMENTS=library.SCHEMA_STATEMENTS,
                                DEFER_SCHEMA_REGISTRATION=True,PLUGIN_NAME='library',Plugin=library.Plugin,register_library_schema=library.register_library_schema)
            setattr(mod,key,value)
            with self.subTest(key=key),patch.object(service,'PLUGIN_MODULES',[name]),patch.object(service,'_LOADED_PLUGIN_MODULES',[]),patch.object(service.importlib,'import_module',return_value=mod):
                with self.assertRaises(service.PluginLoadError):service._load_plugin_modules()
                self.assertEqual(service._LOADED_PLUGIN_MODULES,[])
        class InvalidGovernor(library.Plugin):GOVERNOR=1
        mod=SimpleNamespace(__name__=name,SCHEMA_NAME=library.SCHEMA_NAME,SCHEMA_STATEMENTS=library.SCHEMA_STATEMENTS,
                            DEFER_SCHEMA_REGISTRATION=True,PLUGIN_NAME='library',Plugin=InvalidGovernor,register_library_schema=library.register_library_schema)
        with patch.object(service,'PLUGIN_MODULES',[name]),patch.object(service,'_LOADED_PLUGIN_MODULES',[]),patch.object(service.importlib,'import_module',return_value=mod):
            with self.assertRaises(service.PluginLoadError):service._load_plugin_modules()

    def test_known_library_cannot_mutate_catalog_during_import(self):
        before=list(db.SCHEMA_CATALOG)
        def mutate(name):
            db.SCHEMA_CATALOG.append((999,'forged_library_import',[]))
            return library
        try:
            with patch.object(service,'PLUGIN_MODULES',['apps.cipher.domain.library']),patch.object(service,'_LOADED_PLUGIN_MODULES',[]),patch.object(service.importlib,'import_module',side_effect=mutate):
                with self.assertRaisesRegex(service.PluginLoadError,'import'):service._load_plugin_modules()
        finally:
            db.SCHEMA_CATALOG[:]=before

    def test_restricted_human_reference_operation_is_not_ricky_routable(self):
        from apps.cipher.ricky_sdk import RESTRICTED_OPERATIONS,ROUTABLE_OPERATIONS
        self.assertIn(library.OPERATION,RESTRICTED_OPERATIONS)
        self.assertNotIn(library.OPERATION,ROUTABLE_OPERATIONS)


if __name__=='__main__':unittest.main()
