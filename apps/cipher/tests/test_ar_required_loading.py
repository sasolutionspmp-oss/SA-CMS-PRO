"""Only the exact required owner module may supply deferred source controls."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.core import db
from apps.cipher.domain import owner_billing


class ARRequiredLoadingTests(unittest.TestCase):
    def module(self):
        class Plugin:
            GOVERNOR=True
            def __init__(self,cipher):pass
            def manifest_for(self,*args,**kwargs):return None
            def apply(self,*args,**kwargs):raise RuntimeError("No generic effect")
            def state(self,*args,**kwargs):return {}
        return SimpleNamespace(__name__="apps.cipher.domain.owner_billing",SCHEMA_NAME=owner_billing.SCHEMA_NAME,
            SCHEMA_STATEMENTS=list(owner_billing.SCHEMA_STATEMENTS),PLUGIN_NAME="owner_billing",Plugin=Plugin,
            DEFER_SCHEMA_REGISTRATION=True,register_owner_billing_schema=lambda:None)

    def test_known_owner_source_requires_exact_module_identity_and_boolean_governor(self):
        name="apps.cipher.domain.owner_billing"
        for field,value in (("__name__","apps.cipher.domain.unrelated_source"),("GOVERNOR",False),("GOVERNOR",1)):
            with self.subTest(field=field,value=value):
                mod=self.module()
                setattr(mod.Plugin if field=="GOVERNOR" else mod,field,value)
                before=tuple((v,n,tuple(sql)) for v,n,sql in db.SCHEMA_CATALOG)
                with patch.object(service,"PLUGIN_MODULES",[name]),patch.object(service,"_LOADED_PLUGIN_MODULES",[]), \
                     patch.object(service.importlib,"import_module",return_value=mod),patch.object(service,"register_schema_version") as register:
                    with self.assertRaises(service.PluginLoadError):service._load_plugin_modules()
                    register.assert_not_called()
                self.assertEqual(before,tuple((v,n,tuple(sql)) for v,n,sql in db.SCHEMA_CATALOG))

    def test_unrelated_module_cannot_defer_even_when_it_copies_owner_schema_and_prefix(self):
        name="apps.cipher.domain.unrelated_source";mod=self.module();mod.__name__=name
        with patch.object(service,"PLUGIN_MODULES",[name]),patch.object(service,"_LOADED_PLUGIN_MODULES",[]), \
             patch.object(service.importlib,"import_module",return_value=mod),patch.object(service,"register_schema_version") as register:
            with self.assertRaises(service.PluginLoadError):service._load_plugin_modules()
            register.assert_not_called()


if __name__=="__main__":unittest.main()
