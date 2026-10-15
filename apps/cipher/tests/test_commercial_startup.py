"""Required deferred commercial schema preserves the complete accounting history."""
import copy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from apps.cipher import service
from apps.cipher.core import db
from apps.cipher.domain import accounting, commercial
from apps.cipher import commercial_receipts
from apps.cipher.tests.test_accounting_startup import HISTORICAL_69


COMMERCIAL_MODULE = "apps.cipher.domain.commercial"
HISTORICAL_71 = HISTORICAL_69 + (
    (70, "accounting_practice_delivery", "b6f4c6a974b3246776df2f3e46817aa7585ffdc62b2f55d7dd562f2631f1e8db"),
    (71, "ap_practice_accounting_action_receipts", "1d8c066eb9a33e3002a0a0d0e36029f8d6fce73f7835711caf07025af79cf664"),
)
COMMERCIAL_TAIL = (
    (72, "commercial_manual_sources_and_handoffs", "f6cf329361ced5bfc78bb96b57f81bff7d4d74acd14ccb3d2556883163d1d3f7"),
    (73, "commercial_practice_action_receipts", "a7f97fa4c298fa5ef13a632b38c3ab7bcfb9e158fd5c392844a8957256857ca9"),
)
HISTORICAL_MODULES = tuple("apps.cipher.domain." + name for name in (
    "assets", "schedule", "drawings", "reimbursements", "banking", "labor", "procurement", "field",
    "close", "handoff", "rights", "ap_intake", "people", "payment_policy", "contracts",
))


def fake_module():
    return SimpleNamespace(__name__=COMMERCIAL_MODULE, SCHEMA_NAME=commercial.SCHEMA_NAME,
        SCHEMA_STATEMENTS=list(commercial.SCHEMA_STATEMENTS), PLUGIN_NAME="commercial", Plugin=commercial.Plugin,
        DEFER_SCHEMA_REGISTRATION=True, register_commercial_schema=Mock(wraps=commercial.register_commercial_schema))


class CommercialLateLoaderTests(unittest.TestCase):
    def test_original_71_schema_checksums_and_bytes_keep_their_exact_positions(self):
        actual = tuple((number, name, db.catalog_checksum(sql)) for number, name, sql in db.SCHEMA_CATALOG[:71])
        self.assertEqual(actual, HISTORICAL_71)
        self.assertEqual(db.SCHEMA_CATALOG[69], (70, accounting.SCHEMA_NAME, accounting.SCHEMA_STATEMENTS))
        self.assertEqual(db.SCHEMA_CATALOG[70][1], "ap_practice_accounting_action_receipts")

    def test_original_modules_accounting_and_commercial_keep_their_exact_order(self):
        self.assertEqual(tuple(service.PLUGIN_MODULES[:15]), HISTORICAL_MODULES)
        self.assertEqual(service.PLUGIN_MODULES[15:17], ["apps.cipher.domain.accounting", COMMERCIAL_MODULE])

    def test_sources_72_and_receipts_73_follow_accounting_71_without_intervening_entries(self):
        actual = tuple((number, name, db.catalog_checksum(sql)) for number, name, sql in db.SCHEMA_CATALOG[71:73])
        self.assertEqual(actual, COMMERCIAL_TAIL)
        self.assertEqual(db.SCHEMA_CATALOG[71], (72, commercial.SCHEMA_NAME, commercial.SCHEMA_STATEMENTS))
        self.assertEqual(db.SCHEMA_CATALOG[72], (73, commercial_receipts.SCHEMA_NAME, commercial_receipts.SCHEMA_STATEMENTS))

    def test_real_cold_domain_import_does_not_move_forecast_or_any_schema_earlier(self):
        script = """
import importlib
from apps.cipher.core import db
before = tuple((v,n,tuple(s)) for v,n,s in db.SCHEMA_CATALOG)
domain = importlib.import_module('apps.cipher.domain.commercial')
after = tuple((v,n,tuple(s)) for v,n,s in db.SCHEMA_CATALOG)
assert before == after, (before,after)
assert domain.DEFER_SCHEMA_REGISTRATION is True
assert domain.PLUGIN_NAME == 'commercial'
"""
        completed = subprocess.run([sys.executable, "-c", script], cwd=Path(service.__file__).parents[2],
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_deferred_loader_validates_without_registration_or_database_open(self):
        module = fake_module()
        before = copy.deepcopy(db.SCHEMA_CATALOG)
        with patch.object(service, "PLUGIN_MODULES", [COMMERCIAL_MODULE]), patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", return_value=module), \
                patch.object(service, "register_schema_version") as registration, patch.object(service, "Database") as database:
            self.assertEqual(service._load_plugin_modules(), [module])
            registration.assert_not_called()
            module.register_commercial_schema.assert_not_called()
            database.assert_not_called()
            self.assertEqual(db.SCHEMA_CATALOG, before)

    def test_missing_required_module_or_dependency_aborts_before_workspace_open(self):
        failures = (ModuleNotFoundError("commercial absent", name=COMMERCIAL_MODULE),
                    ModuleNotFoundError("commercial dependency absent", name="commercial_required_dependency"),
                    SyntaxError("commercial source unavailable"), RuntimeError("commercial import failed"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(service, "PLUGIN_MODULES", [COMMERCIAL_MODULE]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", side_effect=failure), \
                    patch.object(service, "Database") as database:
                with self.assertRaises(service.PluginLoadError) as caught:
                    service.Cipher()
                self.assertIs(caught.exception.__cause__, failure)
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
                database.assert_not_called()

    def test_wrong_imported_module_identity_cannot_supply_the_fixed_domain(self):
        for identity in ("apps.cipher.domain.foreign_commercial", "apps.cipher.domain.accounting", ""):
            module = fake_module()
            module.__name__ = identity
            with self.subTest(identity=identity), patch.object(service, "PLUGIN_MODULES", [COMMERCIAL_MODULE]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=module), \
                    patch.object(service, "register_schema_version") as registration, \
                    patch.object(service, "Database", side_effect=AssertionError("Wrong deferred module reached workspace opening")) as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
                module.register_commercial_schema.assert_not_called()
                registration.assert_not_called()
                database.assert_not_called()

    def test_wrong_schema_prefix_empty_ddl_registrar_or_defer_flag_aborts_before_database_open(self):
        invalid = (("SCHEMA_NAME", "commercial_placeholder"), ("SCHEMA_NAME", ""),
                   ("SCHEMA_STATEMENTS", []), ("SCHEMA_STATEMENTS", [""]), ("SCHEMA_STATEMENTS", [None]),
                   ("SCHEMA_STATEMENTS", "CREATE TABLE wrong (id TEXT)"),
                   ("PLUGIN_NAME", "foreign_commercial"), ("PLUGIN_NAME", "commercial.bad"),
                   ("register_commercial_schema", None), ("DEFER_SCHEMA_REGISTRATION", False),
                   ("DEFER_SCHEMA_REGISTRATION", 1), ("DEFER_SCHEMA_REGISTRATION", None))
        for field, value in invalid:
            module = fake_module()
            setattr(module, field, value)
            with self.subTest(field=field, value=value), patch.object(service, "PLUGIN_MODULES", [COMMERCIAL_MODULE]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=module), \
                    patch.object(service, "register_schema_version") as registration, patch.object(service, "Database") as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
                registration.assert_not_called()
                database.assert_not_called()

    def test_missing_named_registrar_and_governor_contract_are_required(self):
        class FalseGovernor(commercial.Plugin):
            GOVERNOR = False

        class NumberGovernor(commercial.Plugin):
            GOVERNOR = 1

        class MissingApply(commercial.Plugin):
            apply = None

        modules = []
        missing = fake_module()
        del missing.register_commercial_schema
        modules.append(missing)
        for plugin in (FalseGovernor, NumberGovernor, MissingApply, None, object):
            module = fake_module()
            module.Plugin = plugin
            modules.append(module)
        for module in modules:
            with self.subTest(module=module), patch.object(service, "PLUGIN_MODULES", [COMMERCIAL_MODULE]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=module), \
                    patch.object(service, "register_schema_version") as registration, patch.object(service, "Database") as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
                registration.assert_not_called()
                database.assert_not_called()

    def test_import_cannot_append_delete_reorder_or_mutate_historical_schema(self):
        for mutation in ("append", "delete", "reorder", "mutate"):
            module = fake_module()
            def importer(name):
                if mutation == "append":
                    db.register_schema_version("commercial_import_bad", ["CREATE TABLE commercial_import_bad (id TEXT)"])
                elif mutation == "delete":
                    del db.SCHEMA_CATALOG[0]
                elif mutation == "reorder":
                    db.SCHEMA_CATALOG[0], db.SCHEMA_CATALOG[1] = db.SCHEMA_CATALOG[1], db.SCHEMA_CATALOG[0]
                else:
                    db.SCHEMA_CATALOG[0][2][0] += " /* altered before late commercial registration */"
                return module
            with self.subTest(mutation=mutation), patch.object(db, "SCHEMA_CATALOG", copy.deepcopy(db.SCHEMA_CATALOG)), \
                    patch.object(service, "PLUGIN_MODULES", [COMMERCIAL_MODULE]), patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", side_effect=importer), \
                    patch.object(service, "Database") as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
                module.register_commercial_schema.assert_not_called()
                database.assert_not_called()

    def test_unknown_or_historical_plugin_cannot_claim_deferred_registration(self):
        for name in ("apps.cipher.domain.unknown_deferred", "apps.cipher.domain.assets"):
            module = fake_module()
            module.__name__ = name
            module.PLUGIN_NAME = "unknown_deferred" if name.endswith("unknown_deferred") else "asset"
            with self.subTest(name=name), patch.object(service, "PLUGIN_MODULES", [name]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=module), \
                    patch.object(service, "register_schema_version") as registration, patch.object(service, "Database") as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])
                registration.assert_not_called()
                database.assert_not_called()

    def test_real_explicit_registration_appends_only_72_then_73_and_is_idempotent(self):
        historical = copy.deepcopy(db.SCHEMA_CATALOG[:71])
        before = copy.deepcopy(historical)
        with patch.object(db, "SCHEMA_CATALOG", historical), patch.object(commercial, "SCHEMA_CATALOG", historical), \
                patch.object(commercial_receipts, "SCHEMA_CATALOG", historical):
            with self.assertRaises(commercial_receipts.CommercialReceiptError):
                commercial_receipts.register_commercial_receipts_schema()
            commercial.register_commercial_schema()
            self.assertEqual(db.SCHEMA_CATALOG[:71], before)
            self.assertEqual(db.SCHEMA_CATALOG[71], (72, commercial.SCHEMA_NAME, commercial.SCHEMA_STATEMENTS))
            commercial_receipts.register_commercial_receipts_schema()
            complete = copy.deepcopy(db.SCHEMA_CATALOG)
            commercial.register_commercial_schema()
            commercial_receipts.register_commercial_receipts_schema()
            self.assertEqual(db.SCHEMA_CATALOG, complete)
            self.assertEqual(tuple((v,n,db.catalog_checksum(s)) for v,n,s in complete), HISTORICAL_71 + COMMERCIAL_TAIL)

    def test_missing_historical_entry_prevents_early_commercial_schema_registration(self):
        for end in (69, 70):
            historical = copy.deepcopy(db.SCHEMA_CATALOG[:end])
            before = copy.deepcopy(historical)
            with self.subTest(end=end), patch.object(db, "SCHEMA_CATALOG", historical), patch.object(commercial, "SCHEMA_CATALOG", historical):
                with self.assertRaises(commercial.CommercialError):
                    commercial.register_commercial_schema()
                self.assertEqual(db.SCHEMA_CATALOG, before)

    def test_complete_real_loader_reload_does_not_change_any_registered_entry(self):
        before = copy.deepcopy(db.SCHEMA_CATALOG)
        with patch.object(service, "_LOADED_PLUGIN_MODULES", []):
            modules = service._load_plugin_modules()
            self.assertEqual([module.__name__ for module in modules], service.PLUGIN_MODULES)
        self.assertEqual(db.SCHEMA_CATALOG, before)

    def test_empty_commercial_plugin_initializes_with_no_sources_seed_or_financial_effects(self):
        c = service.Cipher()
        try:
            self.assertEqual(c.db.scalar("SELECT MAX(version) FROM schema_version"), len(db.SCHEMA_CATALOG))
            self.assertIsInstance(c.plugin("commercial"), commercial.Plugin)
            for table in ("commercial_estimate_sources", "commercial_line_sources", "commercial_packages",
                          "commercial_handoffs", "commercial_commitment_sources", "commercial_action_receipts"):
                self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM " + table), 0, table)
            self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'commercial.%'"), 0)
            self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), 0)
            self.assertEqual(c.provider.submissions, [])
            self.assertTrue(all(check["ok"] for check in c.plugin("commercial").close_checks("not-a-period")))
        finally:
            c.db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
