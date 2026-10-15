"""Real shipped73 histories survive required74/75 and physical-copy quarantine.

The helper pins all original73 names, order and raw SQL hash before normal
database migration and genuine native actions. It requires no archived checkout
and manufactures no migration, source or receipt histories.
"""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from apps.cipher import service
from apps.cipher.service import Cipher
from apps.cipher.core import db as core_db
from apps.cipher.core.ids import hash_json
from apps.cipher.commercial_receipts import commercial_receipt_inventory_proof
from apps.cipher.ar_receipts import ar_receipt_inventory_proof
from apps.cipher.tests.test_workspace_mode import legacy_file
from apps.cipher.tests.ar_history_helpers import produce_genuine73_history, original73_catalog

ORIGINAL73_HASH = "f6396239c845928a66c8ba93c6563641fdb75555914906c8aff71a531d64ab69"
NEW_TABLES = ("owner_billing_bases", "owner_billing_sources", "owner_billing_grants", "owner_billing_postings", "ar_action_receipts",
             "library_entries", "library_revisions", "library_heads", "library_plans", "library_adoptions", "library_action_receipts",
             "rfi_sources", "rfi_response_revisions", "rfi_distribution_revisions", "rfi_approval_sources", "rfi_action_receipts")


def inventory(c):
    tables = [row["name"] for row in c.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {table: sorted(c.db.query(f'SELECT * FROM "{table}"'), key=lambda row: json.dumps(row, sort_keys=True)) for table in tables}


class ARHistoryUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="cipher-real73-ar-upgrade-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.original = cls.root / "owned73.sqlite"
        cls.baseline = cls.root / "original.json"
        produce_genuine73_history(cls.original, cls.baseline)
        cls.before = json.loads(cls.baseline.read_text())
        assert cls.before["catalogHash"] == ORIGINAL73_HASH
        assert cls.before["schemaCount"] == 73
        cls.pending_copy = cls.root / "pending73-copy.sqlite"
        with sqlite3.connect(cls.original) as original, sqlite3.connect(cls.pending_copy) as copy:
            original.backup(copy)

    def assert_original(self, c, *, migration_audit=False):
        current = inventory(c)
        for table, rows in self.before["tables"].items():
            if table == "schema_version":
                self.assertEqual([row for row in current[table] if row["version"] <= 73], rows)
            elif table == "audit_log" and migration_audit:
                last_seq = max(row["seq"] for row in rows)
                self.assertEqual([row for row in current[table] if row["seq"] <= last_seq], rows)
            else:
                self.assertEqual(current[table], rows, table)
        for obj in self.before["objects"]:
            self.assertEqual(c.db.one("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name=?", (obj["name"],)), obj)
        self.assertEqual(c.receivables.get(self.before["billId"]), self.before["nativeBill"])
        self.assertEqual(len(commercial_receipt_inventory_proof(c.db, c.audit)), 7)
        self.assertTrue(c.audit.verify_chain()["ok"])
        self.assertEqual(c.provider.submissions, [])
        for table in NEW_TABLES:
            self.assertEqual(c.db.scalar(f"SELECT COUNT(*) FROM {table}"), 0, table)

    def assert_quarantined(self, c, *, target="ar_action_receipts"):
        self.assertTrue(c.db.read_only)
        self.assertFalse(c.db.has_write_authority())
        self.assertEqual(c.db.scalar("PRAGMA query_only"), 1)
        with self.assertRaises(core_db.WriteAuthorityError):
            c.db.execute(f"DELETE FROM {target}")

    def test_owned_genuine73_reopens_as75_preserving_native_and_receipt_histories(self):
        self.assertEqual(hash_json(original73_catalog()), ORIGINAL73_HASH)
        sidecar = Path(str(self.original) + ".authority")
        authority_bytes = sidecar.read_bytes()
        with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Upgrade initialized an accounting adapter")) as adapter:
            c = Cipher(str(self.original))
        try:
            adapter.assert_not_called()
            self.assertTrue(c.db.has_write_authority())
            self.assertFalse(c.db.read_only)
            self.assert_original(c)
            self.assertEqual(sidecar.read_bytes(), authority_bytes)
            self.assertEqual([(row["version"], row["name"]) for row in c.db.query("SELECT version,name FROM schema_version WHERE version>73 ORDER BY version")],
                    [(74, "owner_billing_sources_and_posting"), (75, "ar_practice_action_receipts"),
                     (76, "library_authored_text_and_reference_adoptions"), (77, "library_practice_action_receipts"),
                     (78, "rfi_sources_and_review_contexts"), (79, "rfi_practice_action_receipts")])
            self.assertEqual(c.plugin("owner_billing").state(), {"bases": [], "sources": [], "integrity": []})
            self.assertEqual(ar_receipt_inventory_proof(c.db, c.audit), [])
            copied = self.root / "current75-copy.sqlite"
            with closing(sqlite3.connect(copied)) as destination:
                c.db.conn.backup(destination)
                destination.execute("PRAGMA journal_mode=DELETE")
        finally:
            c.db.close()
        before_bytes = copied.read_bytes()
        before_hash = hashlib.sha256(before_bytes).hexdigest()
        with closing(sqlite3.connect(copied)) as diagnostic:
            dump = tuple(diagnostic.iterdump())
        for _ in range(2):
            with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Diagnostic copy initialized an adapter")) as adapter:
                diagnostic = Cipher(str(copied))
            try:
                adapter.assert_not_called()
                self.assert_quarantined(diagnostic)
                self.assert_original(diagnostic)
                self.assertEqual(tuple(diagnostic.db.conn.iterdump()), dump)
            finally:
                diagnostic.db.close()
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), before_hash)
            self.assertEqual(copied.read_bytes(), before_bytes)
            self.assertFalse(Path(str(copied) + ".authority").exists())
            self.assertFalse(Path(str(copied) + "-wal").exists())

    def test_genuine_pending73_copy_appends_only_two_entries_and_migration_audit(self):
        c = Cipher(str(self.pending_copy))
        try:
            self.assert_quarantined(c, target="commercial_action_receipts")
            self.assert_original(c, migration_audit=True)
            audit = c.db.query("SELECT * FROM audit_log WHERE seq>? ORDER BY seq", (max(row["seq"] for row in self.before["tables"]["audit_log"]),))
            self.assertEqual([event["action"] for event in audit], ["workspace.schema_migrated_without_authority"])
            payload = json.loads(audit[0]["payload_json"])
            self.assertEqual([(row["version"], row["name"]) for row in payload["entries"]],
                    [(74, "owner_billing_sources_and_posting"), (75, "ar_practice_action_receipts"),
                     (76, "library_authored_text_and_reference_adoptions"), (77, "library_practice_action_receipts"),
                     (78, "rfi_sources_and_review_contexts"), (79, "rfi_practice_action_receipts")])
        finally:
            c.db.close()

    def test_genuine_clean73_diagnostic_has_no_installed_owner_or_ar_history(self):
        target = self.root / "unchanged73-diagnostic.sqlite"
        produce_genuine73_history(target, self.root / "diagnostic-baseline.json")
        copy = self.root / "unchanged73-diagnostic-copy.sqlite"
        with sqlite3.connect(target) as source, sqlite3.connect(copy) as destination:
            source.backup(destination)
        before_bytes = copy.read_bytes()
        database = core_db.Database
        with patch.object(service, "Database", side_effect=lambda path: database(path, migrate=False)):
            c = Cipher(str(copy))
        try:
            self.assert_quarantined(c, target="commercial_action_receipts")
            self.assertEqual(c.db.scalar("SELECT MAX(version) FROM schema_version"), 73)
            self.assertEqual(c.plugin("owner_billing").state(), {"bases": [], "sources": [], "integrity": []})
            own_before = json.loads((self.root / "diagnostic-baseline.json").read_text())
            self.assertFalse(c.plugin("owner_billing").is_modern(own_before["billId"]))
            self.assertEqual(c.db.query("SELECT name FROM sqlite_master WHERE name GLOB 'owner_billing_*' OR name='ar_action_receipts'"), [])
        finally:
            c.db.close()
        self.assertEqual(copy.read_bytes(), before_bytes)

    def test_failed_next_entry_rolls_back74_75_and_all_actual73_history(self):
        target = self.root / "failed-upgrade.sqlite"
        # The pristine73 copy is independent of test ordering and owned upgrades.
        produce_genuine73_history(target, self.root / "rollback-baseline.json")
        with sqlite3.connect(target) as original:
            before = tuple(original.iterdump())
        catalog = list(core_db.SCHEMA_CATALOG) + [(len(core_db.SCHEMA_CATALOG) + 1, "ar_upgrade_failure_test_only", ["CREATE TABLE ar_upgrade_partial_test_only (id INTEGER)", "SELECT * FROM absent_ar_upgrade_test_table"])]
        with patch.object(core_db, "SCHEMA_CATALOG", catalog), self.assertRaises(sqlite3.OperationalError):
            core_db.Database(str(target))
        with sqlite3.connect(target) as original:
            self.assertEqual(tuple(original.iterdump()), before)
            self.assertEqual(original.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 73)
            self.assertEqual(original.execute("SELECT name FROM sqlite_master WHERE name GLOB 'owner_billing_*' OR name='ar_action_receipts' OR name='ar_upgrade_partial_test_only'").fetchall(), [])

    def test_real_pre_mode_copy_and_attested_claim_preserve_shifted_actual_admission_sequence(self):
        source = self.root / "historical65.sqlite"
        copied = self.root / "historical65-copy.sqlite"
        # This shipped helper applies the actual unchanged1–65 SQL and records
        # the original known workspace birth. It creates no financial receipts.
        legacy_file(source)
        with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(copied)) as destination:
            original.backup(destination)
            original_schemas = original.execute("SELECT * FROM schema_version ORDER BY version").fetchall()
            original_audit = original.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
        self.assertFalse(Path(str(copied) + ".authority").exists())
        c = Cipher(str(copied))
        try:
            self.assertEqual(c.db.mode_status()["state"], "pending_practice_declaration")
            self.assert_quarantined(c)
            self.assertEqual([tuple(row.values()) for row in c.db.query("SELECT * FROM schema_version WHERE version<=65 ORDER BY version")], original_schemas)
            self.assertEqual([tuple(row.values()) for row in c.db.query("SELECT * FROM audit_log WHERE seq<=? ORDER BY seq", (len(original_audit),))], original_audit)
            rows = c.db.query("SELECT version,name,statement_count,checksum FROM schema_version ORDER BY version")
            self.assertEqual([row["version"] for row in rows], list(range(1, len(core_db.SCHEMA_CATALOG))))
            by_name = {row["name"]: row for row in rows}
            self.assertNotIn("workspace_mode", by_name)
            self.assertEqual(by_name["owner_billing_sources_and_posting"]["version"], 73)
            self.assertEqual(by_name["ar_practice_action_receipts"]["version"], 74)
            c.db.claim_write_authority(approver="synthetic.upgrade.owner", reason="Attested synthetic pre-mode restore qualification",
                                       approval_ref="SYNTHETIC-PRE-MODE-RESTORE")
            self.assertEqual(c.db.mode_status()["state"], "declared")
            self.assertEqual(c.db.mode_status()["origin"], "legacy_adopted")
            self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='workspace_mode'")["version"], len(core_db.SCHEMA_CATALOG))
            self.assertEqual([row["version"] for row in c.db.query("SELECT version FROM schema_version ORDER BY version")], list(range(1, len(core_db.SCHEMA_CATALOG) + 1)))
            self.assertEqual(hash_json(original73_catalog()), ORIGINAL73_HASH)
            self.assertEqual(core_db.SCHEMA_CATALOG[73][1], "owner_billing_sources_and_posting")
            self.assertEqual(core_db.SCHEMA_CATALOG[74][1], "ar_practice_action_receipts")
            self.assertEqual(c.plugin("owner_billing").state(), {"bases": [], "sources": [], "integrity": []})
            self.assertEqual(ar_receipt_inventory_proof(c.db, c.audit), [])
            self.assertEqual(commercial_receipt_inventory_proof(c.db, c.audit), [])
            self.assertTrue(c.audit.verify_chain()["ok"])
            self.assertEqual(c.provider.submissions, [])
        finally:
            c.db.close()


if __name__ == "__main__":
    unittest.main()
