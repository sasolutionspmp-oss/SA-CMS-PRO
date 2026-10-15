"""Missing deferred-contract cases beyond existing namespace/governor tests."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.core import db
from apps.cipher.domain import owner_billing


class ARLoadingIntegrationTests(unittest.TestCase):
    def module(self):
        class Plugin:
            GOVERNOR = True
            def __init__(self, cipher):
                pass
            def manifest_for(self, *args, **kwargs):
                return None
            def apply(self, *args, **kwargs):
                raise RuntimeError("No generic effect")
            def state(self, *args, **kwargs):
                return {}
        return SimpleNamespace(__name__="apps.cipher.domain.owner_billing", SCHEMA_NAME=owner_billing.SCHEMA_NAME,
            SCHEMA_STATEMENTS=list(owner_billing.SCHEMA_STATEMENTS), PLUGIN_NAME="owner_billing", Plugin=Plugin,
            DEFER_SCHEMA_REGISTRATION=True, register_owner_billing_schema=lambda: None)

    def rejected(self, mod, *, importer=None):
        before = tuple((version, name, tuple(sql)) for version, name, sql in db.SCHEMA_CATALOG)
        with patch.object(service, "PLUGIN_MODULES", ["apps.cipher.domain.owner_billing"]), \
             patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
             patch.object(service.importlib, "import_module", side_effect=importer, return_value=mod), \
             patch.object(service, "register_schema_version") as register, \
             patch.object(service, "Database", side_effect=AssertionError("Database opened before required module admission")) as database:
            with self.assertRaises(service.PluginLoadError):
                service.Cipher()
            register.assert_not_called()
            database.assert_not_called()
        self.assertEqual(before, tuple((version, name, tuple(sql)) for version, name, sql in db.SCHEMA_CATALOG))

    def test_owner_deferred_contract_refuses_wrong_schema_empty_ddl_missing_registrar_and_nontrue_defer(self):
        for field, value in (("SCHEMA_NAME", "unrelated_owner_schema"), ("SCHEMA_STATEMENTS", []),
                ("SCHEMA_STATEMENTS", [" "]), ("SCHEMA_STATEMENTS", [1]),
                ("register_owner_billing_schema", None), ("DEFER_SCHEMA_REGISTRATION", False),
                ("DEFER_SCHEMA_REGISTRATION", 1), ("PLUGIN_NAME", "owner_bill_generic")):
            with self.subTest(field=field, value=value):
                mod = self.module()
                setattr(mod, field, value)
                self.rejected(mod)

    def test_required_owner_import_failure_refuses_before_database_open(self):
        def missing(_name):
            raise ModuleNotFoundError("Synthetic configured owner module is missing")
        self.rejected(self.module(), importer=missing)

    def test_deferred_import_cannot_change_existing_schema_text_before_admission(self):
        mod = self.module()
        # Patch a disposable list so even the deliberate negative import cannot
        # mutate the process's real global catalog.
        disposable = [(v, n, list(sql)) for v, n, sql in db.SCHEMA_CATALOG]
        def mutate(_name):
            disposable[0][2].append("SELECT 1")
            return mod
        with patch.object(db, "SCHEMA_CATALOG", disposable):
            with patch.object(service, "PLUGIN_MODULES", ["apps.cipher.domain.owner_billing"]), \
                 patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                 patch.object(service.importlib, "import_module", side_effect=mutate), \
                 patch.object(service, "Database", side_effect=AssertionError("Database opened after import mutation")) as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                database.assert_not_called()
        self.assertNotEqual(disposable[0][2], db.SCHEMA_CATALOG[0][2])


if __name__ == "__main__":
    unittest.main()
