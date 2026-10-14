"""Audit lookups use indexes without rewriting schema history or audit entries."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from apps.cipher.core import db as core_db
from apps.cipher.core.audit import Audit
from apps.cipher.core.db import MODE_ACTION, MODE_SCHEMA_NAME, Database, catalog_checksum
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
        stamp = "2026-10-14T00:00:00Z"
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            # Seed genuine pre-index/pre-mode history with the original SQL,
            # workspace and hash chain, without today's constructor adopting it.
            conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, statement_count INTEGER NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
            conn.execute("CREATE UNIQUE INDEX schema_version_name ON schema_version(name)")
            for version, name, statements in core_db.SCHEMA_CATALOG[:HISTORICAL_ENTRY_COUNT]:
                for statement in statements:
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_version VALUES (?,?,?,?,?)",
                             (version, name, len(statements), catalog_checksum(statements), stamp))
            conn.execute("INSERT INTO workspace VALUES (1,'ws_audit_legacy','inst_audit_legacy',1,1,0,0,?,?)", (stamp, stamp))
            previous = "0" * 64
            for action, entity_type, entity_id, payload in (
                ("people.policy_adopted", "people_policy", "policy_test", {"version": 1}),
                ("people.person_added", "people_person", "person_test", {"name": "Synthetic Person"}),
                ("people.person_deactivated", "people_person", "person_test", {"reason": "Test"}),
            ):
                encoded = canonical_json(payload)
                payload_hash = sha256_hex(encoded)
                entry_hash = sha256_hex("|".join([previous, stamp, "owner", action, entity_type, entity_id, payload_hash]))
                conn.execute("INSERT INTO audit_log (ts,actor,action,entity_type,entity_id,payload_json,payload_hash,prev_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                             (stamp, "owner", action, entity_type, entity_id, encoded, payload_hash, previous, entry_hash))
                previous = entry_hash
            conn.commit()
            history = [dict(row) for row in conn.execute("SELECT * FROM schema_version ORDER BY version")]
            entries = [dict(row) for row in conn.execute("SELECT * FROM audit_log ORDER BY seq")]
            workspace = dict(conn.execute("SELECT * FROM workspace").fetchone())
        finally:
            conn.close()
        with open(path + ".authority", "w", encoding="utf-8") as sidecar:
            sidecar.write("inst_audit_legacy")
        return path, history, entries, workspace

    def test_persistent_workspace_upgrade_preserves_history_and_chain(self):
        with tempfile.TemporaryDirectory(prefix="cipher-audit-upgrade-") as directory:
            path, history, entries, workspace = self._historical_workspace(directory)
            db = Database(path)
            try:
                self.assertEqual(db.query("SELECT * FROM schema_version WHERE version<=? ORDER BY version",
                                          (HISTORICAL_ENTRY_COUNT,)), history)
                index_entry = db.one("SELECT * FROM schema_version WHERE name=?", (INDEX_SCHEMA_NAME,))
                self.assertIsNotNone(index_entry)
                self.assertGreater(index_entry["version"], HISTORICAL_ENTRY_COUNT)
                audit = Audit(db)
                adopted_entries = audit.entries()
                self.assertEqual(adopted_entries[:-1], entries)
                declaration = adopted_entries[-1]
                self.assertEqual(declaration["action"], MODE_ACTION)
                self.assertEqual(declaration["entity_id"], workspace["workspace_id"])
                self.assertEqual(declaration["payload_json"], canonical_json({
                    "workspace_id": workspace["workspace_id"], "mode": "practice", "created_at": workspace["created_at"],
                    "origin": "legacy_adopted",
                }))
                self.assertEqual(declaration["prev_hash"], entries[-1]["entry_hash"])
                self.assertEqual({key: db.workspace()[key] for key in workspace}, workspace)
                self.assertEqual(db.workspace()["mode_declaration_seq"], declaration["seq"])
                self.assertTrue(db.mode_status()["verified"])
                self.assertTrue(audit.verify_chain()["ok"])
                self.assertEqual(audit.entries(entity_type="people_person", entity_id="person_test", limit=1), entries[1:2])
                self.assertEqual(db.schema_status()["pending"], [])
                self.assertEqual(db.migrate(), [])
                self.assertEqual(audit.entries(), adopted_entries)
                self.assertTrue(db.has_write_authority())
            finally:
                db.close()
            reopened = Database(path)
            try:
                self.assertEqual(Audit(reopened).entries(), adopted_entries)
                self.assertEqual(reopened.query("SELECT * FROM schema_version WHERE version<=? ORDER BY version",
                                                (HISTORICAL_ENTRY_COUNT,)), history)
            finally:
                reopened.close()

    def test_historical_copy_upgrade_keeps_write_authority_quarantined(self):
        with tempfile.TemporaryDirectory(prefix="cipher-audit-copy-upgrade-") as directory:
            path, history, entries, workspace = self._historical_workspace(directory)
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
                copied_entries = audit.entries()
                self.assertEqual(copied_entries[:-1], entries)
                self.assertTrue(audit.verify_chain()["ok"])
                self.assertEqual(copied_entries[-1]["action"], "workspace.schema_migrated_without_authority")
                self.assertEqual(copied_entries[-1]["prev_hash"], entries[-1]["entry_hash"])
                self.assertEqual(copied.query("SELECT * FROM audit_log WHERE action=?", (MODE_ACTION,)), [])
                self.assertEqual(copied.schema_status()["pending"], [MODE_SCHEMA_NAME])
                self.assertEqual(copied.mode_status()["state"], "pending_practice_declaration")
                self.assertIsNone(copied.mode_status()["mode"])
                self.assertFalse(copied.mode_status()["verified"])
                self.assertEqual(copied.workspace(), workspace)
                self.assertFalse(copied.has_write_authority())
                self.assertTrue(copied.read_only)
                self.assertFalse(os.path.exists(copy_path + ".authority"))
                # An invalid claim must not declare a mode or alter the prefix.
                with self.assertRaises(core_db.WriteAuthorityError):
                    copied.claim_write_authority(approver="owner", reason="")
                self.assertEqual(audit.entries(), copied_entries)
                with mock.patch.dict(os.environ):
                    os.environ.pop("CIPHER_OWNER_SECRET", None)
                    claimed = copied.claim_write_authority(approver="owner", reason="Synthetic legacy restore drill")
                self.assertTrue(claimed["effective_write_authority"])
                self.assertTrue(claimed["release_quarantined"])
                self.assertFalse(copied.read_only)
                self.assertEqual(copied.schema_status()["pending"], [])
                self.assertEqual(copied.workspace()["workspace_id"], workspace["workspace_id"])
                self.assertEqual(copied.workspace()["created_at"], workspace["created_at"])
                claimed_entries = audit.entries()
                self.assertEqual(claimed_entries[:len(copied_entries)], copied_entries)
                self.assertEqual([entry["action"] for entry in claimed_entries[len(copied_entries):]],
                                 ["workspace.claim_write_authority", MODE_ACTION])
                self.assertTrue(copied.mode_status()["verified"])
                self.assertEqual(copied.mode_status()["origin"], "legacy_adopted")
                self.assertTrue(audit.verify_chain()["ok"])
                self.assertEqual(copied.query("SELECT * FROM schema_version WHERE version<=? ORDER BY version",
                                              (HISTORICAL_ENTRY_COUNT,)), history)
            finally:
                copied.close()
            # Claiming the copy never upgrades or declares the original source.
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM audit_log ORDER BY seq")], entries)
                self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM schema_version ORDER BY version")], history)
                self.assertEqual(dict(conn.execute("SELECT * FROM workspace").fetchone()), workspace)


if __name__ == "__main__":
    unittest.main()
