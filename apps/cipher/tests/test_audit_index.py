"""Audit lookups use indexes without rewriting schema history or audit entries."""
import os
import tempfile
import unittest
from unittest import mock

from apps.cipher.core import db as core_db
from apps.cipher.core.audit import Audit
from apps.cipher.core.db import Database, catalog_checksum
from apps.cipher.core.ids import canonical_json, sha256_hex
from apps.cipher.service import Cipher, PLUGIN_MODULES
import apps.cipher.ricky_sdk  # register the last historical schema entries


HISTORICAL_ENTRY_COUNT = 63
HISTORICAL_CATALOG_HASH = "94bff45645a25b93f8a15d709d3d76b69dfa93ece111c5f285238a01ff607a4e"
INDEX_SCHEMA_NAME = "audit_log_lookup_indexes"


class AuditIndexTests(unittest.TestCase):
    def test_historical_schema_checksums_and_plugin_order_are_unchanged(self):
        # Tests can import domain modules before the service. Catalog positions
        # then differ, while named entries and the configured plugin order stay fixed.
        history = sorted([[name, catalog_checksum(statements)]
                          for _, name, statements in core_db.SCHEMA_CATALOG[:HISTORICAL_ENTRY_COUNT]])
        self.assertEqual(sha256_hex(canonical_json(history)), HISTORICAL_CATALOG_HASH)
        self.assertEqual(PLUGIN_MODULES, [f"apps.cipher.domain.{name}" for name in (
            "assets", "schedule", "drawings", "reimbursements", "banking", "labor", "procurement", "field",
            "close", "handoff", "rights", "ap_intake", "people", "payment_policy", "contracts",
        )])

    def test_governor_lookup_plans_use_indexes_in_sequence_order(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        cases = (
            ("SELECT * FROM audit_log WHERE entity_type=? AND entity_id=? ORDER BY seq",
             ("people_person", "person_test"), "audit_log_entity_seq"),
            ("SELECT entity_id, payload_json FROM audit_log WHERE action=? ORDER BY seq",
             ("people.policy_adopted",), "audit_log_action_seq"),
            ("SELECT entity_id FROM audit_log WHERE action=? AND seq>? ORDER BY seq",
             ("payment.queued", 10), "audit_log_action_seq"),
        )
        for sql, params, index in cases:
            with self.subTest(sql=sql):
                plan = " ".join(row["detail"] for row in c.db.query("EXPLAIN QUERY PLAN " + sql, params))
                self.assertIn(index, plan)
                self.assertNotIn("SCAN audit_log", plan)
                self.assertNotIn("TEMP B-TREE", plan)
        indexes = {row["name"]: [column["name"] for column in c.db.query(f"PRAGMA index_info('{row['name']}')")]
                   for row in c.db.query("PRAGMA index_list('audit_log')")}
        self.assertIn("audit_log_entity_seq", indexes)
        self.assertIn("audit_log_action_seq", indexes)
        self.assertEqual(indexes["audit_log_entity_seq"], ["entity_type", "entity_id", "seq"])
        self.assertEqual(indexes["audit_log_action_seq"], ["action", "seq"])

    def _historical_workspace(self, directory):
        path = os.path.join(directory, "workspace.sqlite")
        with mock.patch.object(core_db, "SCHEMA_CATALOG", core_db.SCHEMA_CATALOG[:HISTORICAL_ENTRY_COUNT]):
            db = Database(path)
            try:
                audit = Audit(db)
                audit.record("owner", "people.policy_adopted", "people_policy", "policy_test", {"version": 1})
                audit.record("owner", "people.person_added", "people_person", "person_test", {"name": "Synthetic Person"})
                audit.record("owner", "people.person_deactivated", "people_person", "person_test", {"reason": "Test"})
                return path, db.query("SELECT * FROM schema_version ORDER BY version"), audit.entries()
            finally:
                db.close()

    def test_persistent_workspace_upgrade_preserves_history_and_chain(self):
        with tempfile.TemporaryDirectory(prefix="cipher-audit-upgrade-") as directory:
            path, history, entries = self._historical_workspace(directory)
            db = Database(path)
            try:
                self.assertEqual(db.query("SELECT * FROM schema_version WHERE version<=? ORDER BY version",
                                          (HISTORICAL_ENTRY_COUNT,)), history)
                index_entry = db.one("SELECT * FROM schema_version WHERE name=?", (INDEX_SCHEMA_NAME,))
                self.assertIsNotNone(index_entry)
                self.assertGreater(index_entry["version"], HISTORICAL_ENTRY_COUNT)
                audit = Audit(db)
                self.assertEqual(audit.entries(), entries)
                self.assertTrue(audit.verify_chain()["ok"])
                self.assertEqual(audit.entries(entity_type="people_person", entity_id="person_test", limit=1), entries[1:2])
                self.assertEqual(db.schema_status()["pending"], [])
                self.assertEqual(db.migrate(), [])
                self.assertTrue(db.has_write_authority())
            finally:
                db.close()

    def test_historical_copy_upgrade_keeps_write_authority_quarantined(self):
        with tempfile.TemporaryDirectory(prefix="cipher-audit-copy-upgrade-") as directory:
            path, history, entries = self._historical_workspace(directory)
            source = Database(path, migrate=False)
            copy_path = os.path.join(directory, "copied.sqlite")
            try:
                source.snapshot(copy_path)
            finally:
                source.close()
            copied = Database(copy_path)
            try:
                self.assertEqual(copied.query("SELECT * FROM schema_version WHERE version<=? ORDER BY version",
                                              (HISTORICAL_ENTRY_COUNT,)), history)
                self.assertIsNotNone(copied.one("SELECT name FROM schema_version WHERE name=?", (INDEX_SCHEMA_NAME,)))
                audit = Audit(copied)
                self.assertEqual(audit.entries()[:len(entries)], entries)
                self.assertTrue(audit.verify_chain()["ok"])
                self.assertEqual(audit.entries()[-1]["action"], "workspace.schema_migrated_without_authority")
                self.assertFalse(copied.has_write_authority())
                self.assertTrue(copied.read_only)
            finally:
                copied.close()


if __name__ == "__main__":
    unittest.main()
