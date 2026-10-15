"""Required late accounting schema preserves every historical migration."""
import copy
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.core import db
from apps.cipher.domain import accounting

# Frozen from published AP milestone cf51882d, before schema70 existed. These
# checksums cover actual SQL bytes and order, rather than newly planted DB rows.
HISTORICAL_69 = (
    (1, 'foundation', '295e0a70db010fa9c6e6ba6f1c8c15695cda9dde38c789d2852711639286066d'),
    (2, 'ledger_integrity', 'e731812b47c65e3ebab686995f2b8571fa49795e888266d84e139ecf4477aa0e'),
    (3, 'period_integrity', '9ddd664991c32969971502bc9c2b2e4f9cb6edfbd8cd3e1ea130178595554114'),
    (4, 'integrity_hardening', 'e983fdf237c82201990101914dbb6e0450a0d1156e42ecc4a806aa6dee1b91d5'),
    (5, 'assets', 'd0affa6f7652d76cee9298a1e8938bc2c3590f2d44b87abbf06257fe4b798dd3'),
    (6, 'schedule', '66153dd64ded031d0ac920a9c0539b43e9c1f5e3af6efb31c132c7f1abf0d728'),
    (7, 'drawings', '45009667581e57b6f3d16ec8f267a171fc0daffdae58d33a4e87a58f5cb561b1'),
    (8, 'payments_scope', '9b9e2dbf5414a9d53568f616ea2a79b650b32279394191eae10d8b1d3d15f13a'),
    (9, 'payments_controls', '02432d68ec055dfe164348ae87795096c216c760af645afc1b427fce3ba35164'),
    (10, 'payments_terms', 'd728e4a5d75110e75015a8b279329947fe07d0c87fb660a2c80a5382741d6b40'),
    (11, 'payments_controls_guards', '618207537961b93457a94a1c1b42d868857cf10efe99084d59fc33bd97c41471'),
    (12, 'payments_controls_resume_binding', '79bdd796ef9086e0e52aa1a8dc744f9a45128e4b2c5599973780bac1cd4f14ce'),
    (13, 'payments_lifecycle', 'cbaf1e76d92ab7f4216d904bf63220871ef322dca15652f45b720424e4044d6e'),
    (14, 'payments_destination_changes', 'e331a2e88975454567f9589ce7dec589ca504302a477a34873b5b4d54e108a69'),
    (15, 'payments_destination_verification', '36543501bbd2a52daabde3c5838944ca1171120e5cc5efb852ce8477b1a99ce0'),
    (16, 'payments_lifecycle_bank_proof', '495e64921601e5f4cefbc3f6d92ebc8a12b70dc3b12ee36d5413abacace24a79'),
    (17, 'reimbursements', 'b75e65c2958d94e827dcd9ee99890ec3cd43bf8d78c9a3f48770b8e12f10e1d6'),
    (18, 'reimbursements_outbox', 'cdaff945a4c213d9ea69154457e7d133238ac9fb94886c5b1e4fbcca53827c05'),
    (19, 'reimbursements_outbox_guards', '0ff7f7f486f263a6f508a8d89731bebed00bc4ae40179a288c79b12fe7f582d5'),
    (20, 'reimbursements_billing_collections', '05defba436d0e3a4fbcd11a74a1299bed7140499d111694de59b1b65b376dd3c'),
    (21, 'reimbursements_no_replace', '2e29122aeb547342d769a2bfab9c1e7a2ace1c608dd8b997ca43fe3686d7f61a'),
    (22, 'reimbursements_cancel_reopens', 'dfb56be5dd9199f2fa63762173173850bdd4c3f8712965d8237af8534c16e232'),
    (23, 'banking', '5f0372372f5b54bc7c234764bb11ec50867b100b2cb589246228d061250d8136'),
    (24, 'banking_payment_reconciled_guard', '58f6f53ec58701740a73c07153860910e0d83959acf191d17a2a275846c91587'),
    (25, 'labor', '37f1b13a7b052744a1c2e7f4a59b3064b2a6daf96d9b9e7eda3b0caf6b532e9b'),
    (26, 'labor_collection_guards', '90774dc42273671fee134102b0208952fdbdd3875a1b2dbed7c775dca9378adc'),
    (27, 'labor_rebill_after_reversal', 'd8449a636df02f5163d3990696f836958349e8226536212153f4f34b78d7bd60'),
    (28, 'procurement', '0e8c1a9ddbbf48516140921b4b460ee3ecf1bef5a86f7d0fc4f3d3185a376b3b'),
    (29, 'estimates_structured', 'f7d1d5367f22b7e5dc335acbe32171fcbd92a02ac6eb65a5371723cb9239b592'),
    (30, 'estimates_lifecycle_guards', '7e060a600086cc5a7a0059c1fbc02c1027926ac27d9b61bd2ca92d694fb3b0d9'),
    (31, 'estimates_no_replace_guards', 'e3e75893629e5e395d1d82609ee461eba77f641e9b467c75608a5c4c47ad2716'),
    (32, 'commitment_closure_controls', 'c54e8dbda596be67fb69f0dbfba5ea52c94d9329d525d61b0d8656a0d2bbdbf1'),
    (33, 'field', 'b5c1828d148b3cd48f72771357947d16597070d02ea6ff104c4110525f232cba'),
    (34, 'field_rfi_distribution_approvals', '3ba9e400fe85214e8b46859b57b828a1caf3323802bfcbb95cb13568e8626e58'),
    (35, 'bills_stored_material_controls', '677b3a723f0acf47cfcb5847535ad2b17972e05b623137347f11adbfb6032cc3'),
    (36, 'bills_controls_hardening', 'c42ae1429c572250fc5d71e50f48ebb18664dda2f07312b4e1d948000d9b0958'),
    (37, 'bills_invoices_credits_corrections', '6d65a74635f65f71fb8e4fd21dc4ddd7946ded47699cb23be31490ba93939996'),
    (38, 'bills_invoice_link_and_credit_payment_guards', '31f9c5821b6c7a39c7c5b7206f12b77e8b3ec0690234591a698369010cd611cc'),
    (39, 'receivables_controls', 'cd087748ba2dcd6853f0592fef2a3410aaceb85d8f8044f925c2846f141327b6'),
    (40, 'receivables_controls_guards', 'e04f1f323b07d89ce4804bbbdaf2e5ad26e4aa65ce5992d5e586d02e354fb3f5'),
    (41, 'receivables_dates_credits', 'cd9ba29fc82ca8f46f53a8a410b43a99c07f4395e3d74c9db91213e0551b2bc4'),
    (42, 'receivables_dates_credits_guards', '34052b02e2e2bfe1896b413cd8923993d6d4824f7058835db2e320a60e7566f9'),
    (43, 'close', 'b70fec15c5cb364b5ac5860707890253ab80e2e63a8aa2a693e0215c8769a5ea'),
    (44, 'close_approval_guards', '6058916b482518cc410eb074475c7729aefff6dfc57620b8549142b76fbd7c06'),
    (45, 'close_reopen_grant_roles', '825a6a18b80c98ca665343ece1ac871decc61c7b9835780464440c9167056d21'),
    (46, 'close_reopen_governance', 'b14fdd0a9b50ea2c0c7a290053558f44070a22af820d8bc65a8ff094c18dcf69'),
    (47, 'handoff', '4899b5cf62380ce3ca589491b1c37aa90b3309ef547f5b5b831eeeded8678cee'),
    (48, 'handoff_integrity_guards', 'c2ea6beb6384066d0ab4541e56aee234f3b5b164c0c625e6e011af7db142ea35'),
    (49, 'handoff_acknowledgement_guards', 'bd9aa18d452b18cbc28ba5be6bb472b5d6bbea9df44d55866717e53a4e544190'),
    (50, 'rights', '502e53cc8f45beb62bacb746fc12bac052c61ed350fdcc7842015b8296d9b454'),
    (51, 'rights_integrity_guards', 'd520f348a1b4a0dd70a34933fac2ed4d74c6b729214656ccc297c61fbe0e8ef8'),
    (52, 'rights_registry_hardening', '4ef1780803d8abf0533b75a5a37f119bdfcd42e1cf26545e87184f4023eb4d43'),
    (53, 'ap_intake', 'cc252055543f61ef220d18a5aae1263b4327d9813ef89c9c0dba6cdf7e1de7b6'),
    (54, 'ap_intake_integrity_guards', '748481796f42fb84d65183e5f3e99d328daa24846446ba6640e5e40e164390fe'),
    (55, 'people', '389aa3429e7e0ae572b48cba7a10ca92197c539c1b712537de11eae3c99fd715'),
    (56, 'payment_policy', '4bc22a6472dd8aa605a5d950a8ed5430d5782a01860c9fd684c238fb9bc25781'),
    (57, 'contracts', '12329446b50935d02c3870c5e10c8f93872722717528e58c5f1ac8ee43107f2e'),
    (58, 'forecast_budget_versions', '207751995c2abf70979ffabb3bc8f032e355902191b219fe5b1f79ecacc8e4f9'),
    (59, 'forecast_budget_guards', '093046c76245c8e896df652a8623d6e3e829662bb334aa61b30b40eb785cd979'),
    (60, 'ricky_sdk', 'c7386b16d76d8dabb60436bd4f37644db1d121b49224b70af0f2998ee7ddd7d7'),
    (61, 'ricky_sdk_receipt_guards', 'b871ea6d322ce68ead735f9984e1a0fe4d8940e84f3a86a657907c417008fd1f'),
    (62, 'ricky_sdk_key_reservations', 'e7a0881b39eb8d051e2b5db6f697f2662a6ebb2d0fe4ba92c58f715222f868d4'),
    (63, 'ricky_sdk_redaction_key', '67cd2a4b3222177d76cb2aa7449d7dfc588dd6629a3ba0f7e0e18573c032963c'),
    (64, 'audit_log_lookup_indexes', '429d12db822c15596c19715b759173742e4fa96ef580d5892a3c30e4978f35af'),
    (65, 'bills_business_approval_posting', '847918d350ef1461739c8534feabbe95601d70f7356bb62134bf3ae23674b53a'),
    (66, 'workspace_mode', '063992fddabfa7718e2bfe29c2652da33d06a8da49b89bfe54f2d5838d14015f'),
    (67, 'ap_practice_action_receipts', '02930bb0e9e10899a4b656f6be945f20a05123ad52dbff273f641b4dd0387437'),
    (68, 'ap_practice_preparation_action_receipts', '1e0577d947c84387ef68233e8c0e89764c628404ee56cab3fc472984fd4e7bc9'),
    (69, 'ap_practice_exception_action_receipts', 'd8f6fc38f5f00176c91bde625a8afffb4a916455ac7387fc41c7cc34ee4ad2d6'),
)


def fake_module():
    return SimpleNamespace(__name__="apps.cipher.domain.accounting", SCHEMA_NAME=accounting.SCHEMA_NAME,
                           SCHEMA_STATEMENTS=list(accounting.SCHEMA_STATEMENTS), PLUGIN_NAME="accounting",
                           Plugin=accounting.Plugin, DEFER_SCHEMA_REGISTRATION=True,
                           register_accounting_schema=accounting.register_accounting_schema)


class AccountingLateLoaderTests(unittest.TestCase):
    def test_historical_catalog_sql_checksums_and_registration_order_are_exact(self):
        actual = tuple((version, name, db.catalog_checksum(statements)) for version, name, statements in db.SCHEMA_CATALOG[:69])
        self.assertEqual(actual, HISTORICAL_69)
        self.assertEqual(db.SCHEMA_CATALOG[69], (70, accounting.SCHEMA_NAME, accounting.SCHEMA_STATEMENTS))
        self.assertEqual(service.PLUGIN_MODULES[15], "apps.cipher.domain.accounting")
        self.assertEqual(service.PLUGIN_MODULES[16:], ["apps.cipher.domain.commercial", "apps.cipher.domain.owner_billing", "apps.cipher.domain.library", "apps.cipher.domain.rfi_controls"])
        self.assertEqual(db.SCHEMA_CATALOG[68][1], "ap_practice_exception_action_receipts")

    def test_accounting_import_and_loader_validate_without_registering(self):
        module = fake_module()
        before = copy.deepcopy(db.SCHEMA_CATALOG)
        with patch.object(service, "PLUGIN_MODULES", [module.__name__]), patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", return_value=module), \
                patch.object(service, "register_schema_version") as registration:
            self.assertEqual(service._load_plugin_modules(), [module])
            registration.assert_not_called()
            self.assertEqual(db.SCHEMA_CATALOG, before)

    def test_empty_schema_wrong_name_missing_registrar_or_prefix_abort_loader(self):
        for key, value in (("SCHEMA_STATEMENTS", []), ("SCHEMA_NAME", "empty_accounting_placeholder"),
                           ("register_accounting_schema", None), ("DEFER_SCHEMA_REGISTRATION", False),
                           ("PLUGIN_NAME", "other_accounting")):
            module = fake_module()
            setattr(module, key, value)
            with self.subTest(key=key), patch.object(service, "PLUGIN_MODULES", [module.__name__]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", return_value=module), \
                    patch.object(service, "register_schema_version") as registration:
                with self.assertRaises(service.PluginLoadError):
                    service._load_plugin_modules()
                registration.assert_not_called()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])

    def test_missing_required_module_or_dependency_aborts_before_workspace_opens(self):
        for failure in (ModuleNotFoundError("Required accounting absent", name="apps.cipher.domain.accounting"),
                        ModuleNotFoundError("Required accounting dependency absent", name="missing_dependency")):
            with self.subTest(failure=failure), patch.object(service, "PLUGIN_MODULES", ["apps.cipher.domain.accounting"]), \
                    patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", side_effect=failure), \
                    patch.object(service, "Database") as database:
                with self.assertRaises(service.PluginLoadError):
                    service.Cipher()
                database.assert_not_called()

    def test_accounting_import_cannot_append_or_mutate_catalog(self):
        for mutation in ("append", "mutate"):
            module = fake_module()
            def importer(name):
                if mutation == "append":
                    db.register_schema_version("unapproved_accounting_import", ["CREATE TABLE bad_accounting_import (id TEXT)"])
                else:
                    db.SCHEMA_CATALOG[0][2][0] += " /* forbidden accounting import mutation */"
                return module
            with self.subTest(mutation=mutation), patch.object(db, "SCHEMA_CATALOG", copy.deepcopy(db.SCHEMA_CATALOG)), \
                    patch.object(service, "PLUGIN_MODULES", [module.__name__]), patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                    patch.object(service.importlib, "import_module", side_effect=importer):
                with self.assertRaises(service.PluginLoadError):
                    service._load_plugin_modules()
                self.assertEqual(service._LOADED_PLUGIN_MODULES, [])

    def test_foreign_plugin_cannot_defer_schema(self):
        module = fake_module()
        module.__name__, module.PLUGIN_NAME = "apps.cipher.domain.foreign_deferred", "foreign_deferred"
        with patch.object(service, "PLUGIN_MODULES", [module.__name__]), patch.object(service, "_LOADED_PLUGIN_MODULES", []), \
                patch.object(service.importlib, "import_module", return_value=module), \
                patch.object(service, "register_schema_version") as registration:
            with self.assertRaises(service.PluginLoadError):
                service._load_plugin_modules()
            registration.assert_not_called()

    def test_real_late_registration_remains_idempotent_after_schema71(self):
        before = copy.deepcopy(db.SCHEMA_CATALOG)
        accounting.register_accounting_schema()
        with patch.object(service, "_LOADED_PLUGIN_MODULES", []):
            service._load_plugin_modules()
        self.assertEqual(db.SCHEMA_CATALOG, before)

    def test_authentic_schema69_owned_and_copied_files_upgrade_without_seed_or_history_change(self):
        historical = copy.deepcopy(db.SCHEMA_CATALOG[:69])
        with tempfile.TemporaryDirectory(prefix="cipher-accounting-schema69-") as directory:
            owned = Path(directory) / "owned.sqlite"
            copied = Path(directory) / "copied.sqlite"
            with patch.object(db, "SCHEMA_CATALOG", historical):
                old = service.Cipher(str(owned))
            try:
                old.plugin("people").bootstrap_owner("historical.practice.owner", "Historical synthetic owner")
                schemas = old.db.query("SELECT * FROM schema_version ORDER BY version")
                audit = old.db.query("SELECT * FROM audit_log ORDER BY seq")
                person = old.plugin("people").person_for("historical.practice.owner")
                with sqlite3.connect(copied) as destination:
                    old.db.conn.backup(destination)
            finally:
                old.db.close()
            for target in (owned, copied):
                upgraded = service.Cipher(str(target))
                try:
                    self.assertEqual(upgraded.db.query("SELECT * FROM schema_version WHERE version<=69 ORDER BY version"), schemas)
                    self.assertEqual(upgraded.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (audit[-1]["seq"],)), audit)
                    self.assertEqual(upgraded.plugin("people").person_for("historical.practice.owner"), person)
                    self.assertTrue(upgraded.audit.verify_chain()["ok"])
                    self.assertEqual(upgraded.db.scalar("SELECT COUNT(*) FROM accounting_mapping_versions"), 0)
                    self.assertEqual(upgraded.db.scalar("SELECT COUNT(*) FROM accounting_intents"), 0)
                    self.assertEqual(upgraded.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'accounting.%'"), 0)
                    self.assertEqual(upgraded.provider.submissions, [])
                    if target == copied:
                        self.assertTrue(upgraded.db.read_only)
                        self.assertFalse(upgraded.db.has_write_authority())
                finally:
                    upgraded.db.close()
