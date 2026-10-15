"""Real75 financial/source receipts survive native76/77 and copy quarantine."""
from contextlib import closing
import hashlib
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
from apps.cipher.core.api_receipts import APIActionReceipts
from apps.cipher.ar_receipts import ar_receipt_inventory_proof
from apps.cipher.commercial_receipts import commercial_receipt_inventory_proof
from apps.cipher.library_receipts import library_receipt_inventory_proof
from apps.cipher.tests.ar_history_helpers import inventory
from apps.cipher.tests.library_history_helpers import (ORIGINAL75_HASH, original75_catalog, produce_genuine75_history)
from apps.cipher.tests.test_workspace_mode import legacy_file

NEW_TABLES = ("library_entries", "library_revisions", "library_heads", "library_plans", "library_adoptions", "library_action_receipts",
              "rfi_sources", "rfi_response_revisions", "rfi_distribution_revisions", "rfi_approval_sources", "rfi_action_receipts")


class LibraryHistoryUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="cipher-genuine75-library-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.source = cls.root / "owned75.sqlite"
        output = cls.root / "baseline.json"
        produce_genuine75_history(cls.source, output)
        cls.before = json.loads(output.read_text())
        cls.pristine = cls.root / "pristine75.sqlite"
        with closing(sqlite3.connect(cls.source)) as source, closing(sqlite3.connect(cls.pristine)) as destination:
            source.backup(destination)
        cls.authority_bytes = Path(str(cls.source) + ".authority").read_bytes()
        cls.assert_catalog = hash_json(original75_catalog()) == ORIGINAL75_HASH
        assert cls.assert_catalog

    def copy_original(self, label):
        target = self.root / (label + ".sqlite")
        with closing(sqlite3.connect(self.pristine)) as source, closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
        return target

    def assert_history(self, c, *, migration_audit=False):
        current = inventory(c)
        last_seq = max(row["seq"] for row in self.before["tables"]["audit_log"])
        for table, rows in self.before["tables"].items():
            if table == "schema_version":
                self.assertEqual([row for row in current[table] if row["version"] <= 75], rows)
            elif table == "audit_log" and migration_audit:
                self.assertEqual([row for row in current[table] if row["seq"] <= last_seq], rows)
            else:
                self.assertEqual(current[table], rows, table)
        for original in self.before["objects"]:
            self.assertEqual(c.db.one("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name=?", (original["name"],)), original)
        billing = c.plugin("owner_billing")
        self.assertEqual(c.receivables.get(self.before["billId"]), self.before["nativeBill"])
        self.assertEqual(billing.source_proof(self.before["billId"]), self.before["ownerSource"])
        self.assertEqual(billing.posting_receipt(self.before["billId"]), self.before["posting"])
        self.assertEqual(billing.send_proof(self.before["billId"]), self.before["send"])
        self.assertEqual(c.db.query("SELECT * FROM ap_accounting_invocations"), self.before["workerReservation"])
        self.assertEqual(len(ar_receipt_inventory_proof(c.db, c.audit)), 7)
        self.assertEqual(len(commercial_receipt_inventory_proof(c.db, c.audit)), 1)
        APIActionReceipts(c.db, c.audit).verify_integrity()
        self.assertEqual(c.plugin("library").state(), {"entries": [], "references": [], "checks": []})
        self.assertEqual(library_receipt_inventory_proof(c.db, c.audit), [])
        for table in NEW_TABLES:
            self.assertEqual(c.db.scalar(f"SELECT COUNT(*) FROM {table}"), 0, table)
        self.assertTrue(c.audit.verify_chain()["ok"])
        self.assertEqual(c.provider.submissions, [])

    def assert_read_only(self, c):
        self.assertTrue(c.db.read_only)
        self.assertFalse(c.db.has_write_authority())
        self.assertEqual(c.db.scalar("PRAGMA query_only"), 1)
        with self.assertRaises(core_db.WriteAuthorityError):
            c.db.execute("DELETE FROM library_action_receipts")

    def test_owned75_upgrade_preserves_financial_and_pending_worker_histories(self):
        sidecar = Path(str(self.source) + ".authority")
        with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Upgrade initialized adapter")) as adapter:
            c = Cipher(str(self.source))
        try:
            adapter.assert_not_called()
            self.assertTrue(c.db.has_write_authority())
            self.assert_history(c)
            self.assertEqual(sidecar.read_bytes(), self.authority_bytes)
            self.assertEqual([(r["version"], r["name"]) for r in c.db.query("SELECT version,name FROM schema_version WHERE version>75 ORDER BY version")],
                [(76, "library_authored_text_and_reference_adoptions"), (77, "library_practice_action_receipts"),
                 (78, "rfi_sources_and_review_contexts"), (79, "rfi_practice_action_receipts")])
        finally:
            c.db.close()

    def test_pending75_copy_appends_only_real76_77_and_one_migration_audit(self):
        target = self.copy_original("pending75-copy")
        with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Copy initialized adapter")) as adapter:
            c = Cipher(str(target))
        try:
            adapter.assert_not_called()
            self.assert_read_only(c)
            self.assert_history(c, migration_audit=True)
            last = max(row["seq"] for row in self.before["tables"]["audit_log"])
            events = c.db.query("SELECT * FROM audit_log WHERE seq>? ORDER BY seq", (last,))
            self.assertEqual([event["action"] for event in events], ["workspace.schema_migrated_without_authority"])
            payload = json.loads(events[0]["payload_json"])
            self.assertEqual([(row["version"], row["name"]) for row in payload["entries"]],
                [(76, "library_authored_text_and_reference_adoptions"), (77, "library_practice_action_receipts"),
                 (78, "rfi_sources_and_review_contexts"), (79, "rfi_practice_action_receipts")])
            self.assertFalse(Path(str(target) + ".authority").exists())
        finally:
            c.db.close()

    def test_current77_copy_reopens_twice_without_byte_changes_or_adapter(self):
        target = self.copy_original("current77-copy")
        first = Cipher(str(target))
        first.db.close()
        before = target.read_bytes()
        with closing(sqlite3.connect(target)) as source:
            dump = tuple(source.iterdump())
        for _ in range(2):
            with patch("apps.cipher.accounting_simulator.SimulatedAccountingAdapter", side_effect=AssertionError("Diagnostic initialized adapter")):
                c = Cipher(str(target))
            try:
                self.assert_read_only(c)
                self.assert_history(c, migration_audit=True)
                self.assertEqual(tuple(c.db.conn.iterdump()), dump)
            finally:
                c.db.close()
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), hashlib.sha256(before).hexdigest())
            self.assertFalse(Path(str(target) + ".authority").exists())
            self.assertFalse(Path(str(target) + "-wal").exists())

    def test_genuine75_unmigrated_diagnostic_remains_inert_and_unchanged(self):
        target = self.copy_original("unchanged75")
        before = target.read_bytes()
        database = core_db.Database
        with patch.object(service, "Database", side_effect=lambda path: database(path, migrate=False)):
            c = Cipher(str(target))
        try:
            self.assertTrue(c.db.read_only)
            self.assertEqual(c.db.scalar("SELECT MAX(version) FROM schema_version"), 75)
            self.assertEqual(c.plugin("library").state(), {"entries": [], "references": [], "checks": []})
            self.assertEqual(library_receipt_inventory_proof(c.db, c.audit), [])
            self.assertEqual(c.db.query("SELECT name FROM sqlite_master WHERE name GLOB 'library_*'"), [])
            self.assertEqual(c.plugin("owner_billing").posting_receipt(self.before["billId"]), self.before["posting"])
        finally:
            c.db.close()
        self.assertEqual(target.read_bytes(), before)

    def test_failure_in_actual77_storage_guard_rolls_back_real76_77_together(self):
        target = self.copy_original("failed-real77")
        with closing(sqlite3.connect(target)) as source:
            before = tuple(source.iterdump())
        execute = core_db.AuthorityConnection.execute
        def fail(connection, sql, *args, **kwargs):
            if sql.startswith("CREATE TRIGGER library_action_receipts_birth"):
                raise sqlite3.OperationalError("Injected failure in genuine77 final guard")
            return execute(connection, sql, *args, **kwargs)
        with patch.object(core_db.AuthorityConnection, "execute", new=fail), self.assertRaises(sqlite3.OperationalError):
            core_db.Database(str(target))
        with closing(sqlite3.connect(target)) as source:
            self.assertEqual(tuple(source.iterdump()), before)
            self.assertEqual(source.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 75)
            self.assertEqual(source.execute("SELECT name FROM sqlite_master WHERE name GLOB 'library_*'").fetchall(), [])

    def test_pre_mode_copy_claim_preserves_true_shifted_named76_77_admissions(self):
        source = self.root / "pre-mode65.sqlite"
        target = self.root / "pre-mode65-copy.sqlite"
        legacy_file(source)
        with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(target)) as destination:
            original.backup(destination)
        c = Cipher(str(target))
        try:
            self.assertEqual(c.db.mode_status()["state"], "pending_practice_declaration")
            self.assert_read_only(c)
            rows = c.db.query("SELECT version,name FROM schema_version ORDER BY version")
            self.assertEqual([r["version"] for r in rows], list(range(1, 79)))
            self.assertNotIn("workspace_mode", {r["name"] for r in rows})
            self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='library_authored_text_and_reference_adoptions'")["version"], 75)
            self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='library_practice_action_receipts'")["version"], 76)
            self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='rfi_sources_and_review_contexts'")["version"], 77)
            self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='rfi_practice_action_receipts'")["version"], 78)
            c.db.claim_write_authority(approver="synthetic.library.upgrade.owner", reason="Attested synthetic pre-mode library restore",
                approval_ref="SYNTHETIC-PRE-MODE-LIBRARY")
            self.assertEqual(c.db.mode_status()["state"], "declared")
            self.assertEqual(c.db.one("SELECT version FROM schema_version WHERE name='workspace_mode'")["version"], 79)
            self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM schema_version"), 79)
            self.assertEqual(c.plugin("library").state(), {"entries": [], "references": [], "checks": []})
            self.assertEqual(library_receipt_inventory_proof(c.db, c.audit), [])
            self.assertEqual(ar_receipt_inventory_proof(c.db, c.audit), [])
            self.assertEqual(hash_json(original75_catalog()), ORIGINAL75_HASH)
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            c.db.close()


if __name__ == "__main__":
    unittest.main()
