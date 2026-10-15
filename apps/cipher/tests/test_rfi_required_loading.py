"""Real cold admission after the frozen library prefix; no arbitrary deferral."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.core import db
from apps.cipher.domain import rfi_controls


class RFIRequiredLoadingTests(unittest.TestCase):
    def module(self):
        class Plugin:
            GOVERNOR=True
            def __init__(self,cipher):pass
            def manifest_for(self,*args,**kwargs):return None
            def apply(self,*args,**kwargs):raise RuntimeError('Native field owns the effect')
            def state(self,*args,**kwargs):return {}
        return SimpleNamespace(__name__='apps.cipher.domain.rfi_controls',SCHEMA_NAME=rfi_controls.SCHEMA_NAME,
            SCHEMA_STATEMENTS=list(rfi_controls.SCHEMA_STATEMENTS),PLUGIN_NAME='rfi_controls',Plugin=Plugin,
            DEFER_SCHEMA_REGISTRATION=True,register_rfi_controls_schema=lambda:None)

    def test_known_rfi_requires_exact_namespace_prefix_boolean_governor_and_defer(self):
        for field,value in (('__name__','apps.cipher.domain.other'),('PLUGIN_NAME','other'),('GOVERNOR',1),('DEFER_SCHEMA_REGISTRATION',1)):
            with self.subTest(field=field):
                mod=self.module();setattr(mod.Plugin if field=='GOVERNOR' else mod,field,value)
                before=tuple((v,n,tuple(sql)) for v,n,sql in db.SCHEMA_CATALOG)
                with patch.object(service,'PLUGIN_MODULES',['apps.cipher.domain.rfi_controls']),patch.object(service,'_LOADED_PLUGIN_MODULES',[]),patch.object(service.importlib,'import_module',return_value=mod),patch.object(service,'register_schema_version') as register:
                    with self.assertRaises(service.PluginLoadError):service._load_plugin_modules()
                    register.assert_not_called()
                self.assertEqual(before,tuple((v,n,tuple(sql)) for v,n,sql in db.SCHEMA_CATALOG))

    def test_unrelated_module_cannot_copy_deferred_contract(self):
        mod=self.module();mod.__name__='apps.cipher.domain.other'
        with patch.object(service,'PLUGIN_MODULES',[mod.__name__]),patch.object(service,'_LOADED_PLUGIN_MODULES',[]),patch.object(service.importlib,'import_module',return_value=mod):
            with self.assertRaises(service.PluginLoadError):service._load_plugin_modules()

    def test_cold_real_required_loader_has_inert_import_and_exact_original_77_prefix(self):
        # Independently recorded from frozen genuine library76/77, never synthesized entries.
        code="""
from apps.cipher.core import db
before=tuple((v,n,tuple(sql)) for v,n,sql in db.SCHEMA_CATALOG)
from apps.cipher.domain import rfi_controls
assert before==tuple((v,n,tuple(sql)) for v,n,sql in db.SCHEMA_CATALOG)
from apps.cipher import service
from apps.cipher.core.ids import canonical_json,sha256_hex
assert service.PLUGIN_MODULES[-1]=='apps.cipher.domain.rfi_controls'
assert sha256_hex(canonical_json(db.SCHEMA_CATALOG[:77]))=='19d15d425da704d8df3e9c8a343687ddd1fe52aafecdad6c0446c7dd64a30dda'
assert db.SCHEMA_CATALOG[77]==(78,rfi_controls.SCHEMA_NAME,rfi_controls.SCHEMA_STATEMENTS)
from apps.cipher import rfi_receipts
assert db.SCHEMA_CATALOG[78]==(79,rfi_receipts.SCHEMA_NAME,rfi_receipts.SCHEMA_STATEMENTS)
c=service.Cipher(':memory:')
assert c.plugin('rfi_controls').c is c
assert c.db.one('SELECT statement_count FROM schema_version WHERE name=?',(rfi_controls.SCHEMA_NAME,))['statement_count']==16
assert c.plugin('rfi_controls').close_checks('none')==[]
c.db.close()
"""
        root=Path(__file__).resolve().parents[3]
        result=subprocess.run([sys.executable,'-c',code],cwd=root,env=dict(os.environ),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
