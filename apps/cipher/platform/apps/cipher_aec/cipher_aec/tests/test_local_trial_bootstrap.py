"""Host tests for operator admission and recovery; no native runtime claim."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api.errors import DomainError


class LocalTrialBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cipher-local-trial-v1.json"
        self.frappe = SimpleNamespace(conf={"cipher_allow_unscanned_documents": 1},
            session=SimpleNamespace(user="Administrator"), local=SimpleNamespace(site="cipher.localhost"),
            db=SimpleNamespace(exists=Mock(return_value=True)), get_site_path=lambda *parts: str(self.path))
        context = SimpleNamespace(assert_synthetic_site=Mock(), trusted_write=nullcontext)
        self.modules = patch.dict("sys.modules", {"frappe": self.frappe, "cipher_aec.governance.context": context})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("cipher_trial_bootstrap_host_test", Path(__file__).parents[1] / "trial.py")
        self.trial = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.trial)
        self.manifest = {"schema": self.trial.SCHEMA, "site": "cipher.localhost", "company": "Synthetic Company",
            "project": "PROJ-1", "source": {"revision": "REV-1"}, "rate_source": "RATE-1", "credentials_recorded": False}

    def test_repeated_setup_returns_manifest_without_loading_installer(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        result = self.trial.seed_local_trial()
        self.assertTrue(result["already_initialized"])
        self.assertFalse(result["credentials_recorded"])
        self.assertEqual(result["project"], "PROJ-1")
        # The fake exposes no write or password API: any accidental seed fails.
        self.assertEqual(self.frappe.db.exists.call_count, 4)

    def test_pending_committed_manifest_is_recovered_without_reseed(self):
        pending = self.path.with_suffix(".pending.json")
        pending.write_text(json.dumps(self.manifest), encoding="utf-8")
        result = self.trial.seed_local_trial()
        self.assertTrue(result["already_initialized"])
        self.assertTrue(self.path.exists())
        self.assertFalse(pending.exists())

    def test_incomplete_pending_setup_refuses_without_reseeding_or_removing_evidence(self):
        pending = self.path.with_suffix(".pending.json")
        pending.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.frappe.db.exists.return_value = False
        with self.assertRaises(DomainError) as error:
            self.trial.seed_local_trial()
        self.assertEqual(error.exception.code, "trial_fixture_incomplete")
        self.assertTrue(pending.exists())
        self.assertFalse(self.path.exists())

    def test_manifest_from_another_site_refuses_before_database_access(self):
        self.manifest["site"] = "another.localhost"
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(DomainError) as error:
            self.trial.seed_local_trial()
        self.assertEqual(error.exception.code, "trial_fixture_conflict")
        self.frappe.db.exists.assert_not_called()

    def test_missing_credentials_refuses_before_loading_installer(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(DomainError) as error:
            self.trial.seed_local_trial()
        self.assertEqual(error.exception.code, "trial_credentials_required")
        self.frappe.db.exists.assert_not_called()

    def test_wrong_actor_or_document_policy_refuses_existing_manifest(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.frappe.session.user = "morgan@cipher.example"
        with self.assertRaises(DomainError) as error:
            self.trial.seed_local_trial()
        self.assertEqual(error.exception.code, "administrator_required")
        self.frappe.session.user = "Administrator"
        self.frappe.conf["cipher_allow_unscanned_documents"] = 0
        with self.assertRaises(DomainError) as error:
            self.trial.seed_local_trial()
        self.assertEqual(error.exception.code, "trial_document_policy_required")
        self.frappe.db.exists.assert_not_called()

    def test_native_customer_setup_uses_leaf_group_and_territory_and_reuses_year(self):
        records = {("Customer Group", "All Customer Groups"): {"is_group": 1},
            ("Territory", "All Territories"): {"is_group": 1}}
        names = {"Customer Group": "customer_group_name", "Territory": "territory_name", "Customer": "customer_name", "Price List": "price_list_name", "UOM": "uom_name"}
        class NativeDocument(dict):
            def __getattr__(self, key):
                return self.get(key)
            def insert(inner, **kwargs):
                doctype = inner["doctype"]
                if doctype == "Customer":
                    # Model the native failure that rejected the original root
                    # selection; parent groups are never valid Customer leaves.
                    if records[("Customer Group", inner["customer_group"])]["is_group"]:
                        raise ValueError("Cannot select a Group type Customer Group")
                    if records[("Territory", inner["territory"])]["is_group"]:
                        raise ValueError("Choose a leaf trial territory")
                inner["name"] = inner[names[doctype]]
                records[(doctype, inner["name"])] = inner
                return inner
        def get_doc(doctype, name=None):
            if isinstance(doctype, dict):
                return NativeDocument(doctype)
            if doctype == "Fiscal Year":
                return NativeDocument(name=name, companies=[])
            return NativeDocument(records[(doctype, name)])
        def get_value(doctype, filters, field):
            return next((name for (kind, name), values in records.items() if kind == doctype and all(values.get(key) == value for key, value in filters.items())), None)
        self.frappe.utils = SimpleNamespace(nowdate=lambda: "2026-10-17")
        self.frappe.get_all = Mock(return_value=["2026"])
        self.frappe.get_doc = get_doc
        self.frappe.db.get_value = get_value
        result = self.trial._native_masters("Synthetic Company")
        customer = records[("Customer", result["customer"])]
        self.assertEqual(customer["customer_group"], "Cipher Local Trial Customers")
        self.assertEqual(customer["territory"], "Cipher Local Trial Territory")
        self.assertEqual(result["fiscal_year"], "2026")
        self.assertEqual(self.trial._native_masters("Synthetic Company"), result)
