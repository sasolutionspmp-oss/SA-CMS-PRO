"""A configured module must never disappear from Cipher's controls silently."""
import sqlite3
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.core import db


def module(name):
    class Plugin:
        def __init__(self, cipher):
            self.cipher = cipher

        def manifest_for(self, *args, **kwargs):
            return {}

        def apply(self, *args, **kwargs):
            return {}

        def state(self, *args, **kwargs):
            return {}

    return SimpleNamespace(
        __name__=name,
        SCHEMA_NAME=name.rsplit(".", 1)[-1],
        SCHEMA_STATEMENTS=[f"CREATE TABLE {name.rsplit('.', 1)[-1]} (id TEXT)"],
        PLUGIN_NAME=name.rsplit(".", 1)[-1],
        Plugin=Plugin,
    )


class PluginLoadingTests(unittest.TestCase):
    def test_configured_import_failures_abort_with_module_and_cause(self):
        name = "apps.cipher.domain.required_plugin"
        failures = (
            ModuleNotFoundError("configured module absent", name=name),
            ModuleNotFoundError("parent package absent", name="apps.cipher.domain"),
            ModuleNotFoundError("dependency absent", name="required_dependency"),
            SyntaxError("broken module syntax"),
            RuntimeError("module initialization broke"),
        )
        for failure in failures:
            with self.subTest(failure=failure), patch.object(service, "PLUGIN_MODULES", [name]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, name + ".*import") as raised:
                    service._load_plugin_modules()
                self.assertIs(raised.exception.__cause__, failure)
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])

    def test_schema_registration_failure_aborts_with_module_and_cause(self):
        name = "apps.cipher.domain.required_plugin"
        failure = db.SchemaError("registered twice with different statements")
        with patch.object(service, "PLUGIN_MODULES", [name]), \
                patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", return_value=module(name)), \
                patch.object(service, "register_schema_version", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, name + ".*schema") as raised:
                service._load_plugin_modules()
            self.assertIs(raised.exception.__cause__, failure)
            self.assertEqual(service._LOADED_PLUGIN_MODULES, [])

    def test_missing_schema_contract_aborts(self):
        name = "apps.cipher.domain.required_plugin"
        with patch.object(service, "PLUGIN_MODULES", [name]), \
                patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", return_value=SimpleNamespace(__name__=name)):
            with self.assertRaisesRegex(RuntimeError, name + ".*schema") as raised:
                service._load_plugin_modules()
            self.assertIsInstance(raised.exception.__cause__, AttributeError)

    def test_malformed_schema_contract_is_rejected_before_registration(self):
        name = "apps.cipher.domain.required_plugin"
        for field, value in (("SCHEMA_NAME", ""), ("SCHEMA_NAME", None),
                             ("SCHEMA_STATEMENTS", "CREATE TABLE bad (id TEXT)"),
                             ("SCHEMA_STATEMENTS", [None]), ("SCHEMA_STATEMENTS", [""])):
            mod = module(name)
            setattr(mod, field, value)
            with self.subTest(field=field, value=value), patch.object(service, "PLUGIN_MODULES", [name]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=mod), \
                    patch.object(service, "register_schema_version") as register:
                with self.assertRaisesRegex(RuntimeError, name + ".*schema"):
                    service._load_plugin_modules()
                register.assert_not_called()

    def test_malformed_plugin_contract_aborts(self):
        name = "apps.cipher.domain.required_plugin"
        for field, value in (("PLUGIN_NAME", ""), ("PLUGIN_NAME", None),
                             ("PLUGIN_NAME", "loader.bad"), ("PLUGIN_NAME", "loader bad"),
                             ("PLUGIN_NAME", "loader\nbad"), ("PLUGIN_NAME", "lоader"),
                             ("PLUGIN_NAME", "core_reconciliation"), ("PLUGIN_NAME", "ricky_sdk"),
                             ("Plugin", object), ("Plugin", None)):
            mod = module(name)
            setattr(mod, field, value)
            with self.subTest(field=field, value=value), patch.object(service, "PLUGIN_MODULES", [name]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=mod), \
                    patch.object(service, "register_schema_version"):
                with self.assertRaisesRegex(RuntimeError, name + ".*initializ"):
                    service._load_plugin_modules()

    def test_duplicate_plugin_prefix_aborts_instead_of_replacing_a_governor(self):
        names = ["apps.cipher.domain.loader_first", "apps.cipher.domain.loader_second"]
        mods = [module(name) for name in names]
        mods[0].PLUGIN_NAME = mods[1].PLUGIN_NAME = "people"
        with patch.object(service, "PLUGIN_MODULES", names), \
                patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", side_effect=mods), \
                patch.object(service, "register_schema_version"):
            with self.assertRaisesRegex(RuntimeError, names[1] + ".*initializ"):
                service._load_plugin_modules()
            self.assertEqual(service._LOADED_PLUGIN_MODULES, [])

    def test_failed_import_does_not_cache_a_partial_module_list_and_retry_keeps_schema_order(self):
        names = ["apps.cipher.domain.loader_first", "apps.cipher.domain.loader_second", "apps.cipher.domain.loader_third"]
        mods = [module(name) for name in names]
        original_catalog = list(db.SCHEMA_CATALOG)
        failure = RuntimeError("second module broke")
        with patch.object(service, "PLUGIN_MODULES", names), \
                patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(db, "SCHEMA_CATALOG", list(original_catalog)), \
                patch.object(service.importlib, "import_module", side_effect=[mods[0], failure]) as importer:
            with self.assertRaisesRegex(RuntimeError, names[1] + ".*import"):
                service._load_plugin_modules()
            self.assertEqual(importer.call_args_list, [unittest.mock.call(names[0]), unittest.mock.call(names[1])])
            self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
            first_registration = db.SCHEMA_CATALOG[-1]
            self.assertEqual(first_registration[1], mods[0].SCHEMA_NAME)
            importer.reset_mock(side_effect=True)
            importer.side_effect = mods
            self.assertEqual(service._load_plugin_modules(), mods)
            self.assertEqual([entry[1] for entry in db.SCHEMA_CATALOG[len(original_catalog):]],
                             [mod.SCHEMA_NAME for mod in mods])
            self.assertEqual(db.SCHEMA_CATALOG[len(original_catalog)], first_registration)
            self.assertEqual([entry[0] for entry in db.SCHEMA_CATALOG],
                             list(range(1, len(db.SCHEMA_CATALOG) + 1)))
            importer.reset_mock()
            self.assertEqual(service._load_plugin_modules(), mods)
            importer.assert_not_called()

    def test_failed_schema_registration_is_retried_instead_of_caching_successful_siblings(self):
        names = ["apps.cipher.domain.loader_first", "apps.cipher.domain.loader_second"]
        mods = [module(name) for name in names]
        failure = db.SchemaError("schema rejected")
        with patch.object(service, "PLUGIN_MODULES", names), \
                patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", side_effect=mods) as importer, \
                patch.object(service, "register_schema_version", side_effect=[1, failure]) as register:
            with self.assertRaisesRegex(RuntimeError, names[1] + ".*schema"):
                service._load_plugin_modules()
            self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
            importer.reset_mock(side_effect=True)
            importer.side_effect = mods
            register.reset_mock(side_effect=True)
            register.side_effect = [1, 2]
            self.assertEqual(service._load_plugin_modules(), mods)
            self.assertEqual(importer.call_count, 2)
            self.assertEqual(register.call_count, 2)

    def test_module_failure_prevents_opening_or_migrating_a_workspace(self):
        failure = RuntimeError("configured plugin failed to import")
        with patch.object(service, "_load_plugin_modules", side_effect=failure), \
                patch.object(service, "Database", wraps=service.Database) as database:
            with self.assertRaisesRegex(RuntimeError, "configured plugin"):
                service.Cipher()
            database.assert_not_called()

    def test_reloading_registered_modules_preserves_all_schema_versions_and_checksums(self):
        before = [(version, name, db.catalog_checksum(statements))
                  for version, name, statements in db.SCHEMA_CATALOG]
        with patch.object(service, "_LOADED_PLUGIN_MODULES", []):
            loaded = service._load_plugin_modules()
            self.assertEqual([mod.__name__ for mod in loaded], service.PLUGIN_MODULES)
        after = [(version, name, db.catalog_checksum(statements))
                 for version, name, statements in db.SCHEMA_CATALOG]
        self.assertEqual(after, before)


class PluginInitializationTests(unittest.TestCase):
    def test_failed_initialization_rolls_back_all_plugin_writes_to_existing_workspace(self):
        first = module("apps.cipher.domain.first_plugin")
        broken = module("apps.cipher.domain.broken_plugin")
        first_class = first.Plugin

        def write_then_return(cipher):
            cipher.add_party(kind="supplier", name="Startup write")
            return first_class(cipher)

        first.Plugin = write_then_return

        def write_then_fail(cipher):
            cipher.add_party(kind="supplier", name="Broken startup write")
            raise RuntimeError("initialization broke after a write")

        broken.Plugin = write_then_fail
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "workspace.sqlite")
            existing = service.Cipher(path)
            before = (existing.parties(), existing.audit.entries())
            existing.db.close()
            with patch.object(service, "_load_plugin_modules", return_value=[first, broken]):
                with self.assertRaisesRegex(RuntimeError, broken.__name__ + ".*initializ"):
                    service.Cipher(path)
            reopened = service.Cipher(path)
            try:
                self.assertEqual((reopened.parties(), reopened.audit.entries()), before)
            finally:
                reopened.db.close()

    def test_each_governor_initialization_failure_aborts_and_closes_the_workspace(self):
        for name in ("people", "payment_policy", "contracts"):
            mod = next(mod for mod in service._load_plugin_modules() if mod.__name__.endswith("." + name))
            cipher = service.Cipher.__new__(service.Cipher)
            failure = RuntimeError("governor initialization broke")
            with self.subTest(governor=name), patch.object(mod, "Plugin", side_effect=failure):
                self.addCleanup(lambda c=cipher: c.db.close())
                with self.assertRaisesRegex(RuntimeError, mod.__name__ + ".*initializ") as raised:
                    cipher.__init__()
                self.assertIs(raised.exception.__cause__, failure)
                self.assertEqual(cipher._plugins, {})
                with self.assertRaises(sqlite3.ProgrammingError):
                    cipher.db.conn.execute("SELECT 1")

    def test_missing_plugin_initialization_contract_aborts(self):
        name = "apps.cipher.domain.required_plugin"
        cipher = service.Cipher.__new__(service.Cipher)
        with patch.object(service, "_load_plugin_modules", return_value=[SimpleNamespace(__name__=name)]):
            self.addCleanup(lambda: cipher.db.close())
            with self.assertRaisesRegex(RuntimeError, name + ".*initializ") as raised:
                cipher.__init__()
            self.assertIsInstance(raised.exception.__cause__, AttributeError)
            self.assertEqual(cipher._plugins, {})


if __name__ == "__main__":
    unittest.main()
