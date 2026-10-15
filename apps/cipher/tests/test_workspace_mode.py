"""Immutable audited workspace mode, legacy adoption and fail-closed file admission.

Every workspace/provider scenario is synthetic. Historical SQL fixtures preserve
original catalog text and do not bypass current runtime mode admission.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from apps.cipher.core import db as core_db
from apps.cipher.core.ids import canonical_json, sha256_hex
from apps.cipher.service import Cipher

MODE_ACTION = "workspace.mode_declared"


def legacy_file(path):
    """Build the actual historical schema directly, not a current constructor with policy disabled."""
    conn = sqlite3.connect(path)
    stamp = "2026-10-14T00:00:00Z"
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, statement_count INTEGER NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
        conn.execute("CREATE UNIQUE INDEX schema_version_name ON schema_version(name)")
        for version, name, statements in core_db.SCHEMA_CATALOG:
            if version > 65:
                break
            for statement in statements:
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version VALUES (?,?,?,?,?)", (version, name, len(statements), core_db.catalog_checksum(statements), stamp))
        conn.execute("INSERT INTO workspace VALUES (1,'ws_b03_legacy','inst_b03_legacy',1,1,0,0,?,?)", (stamp, stamp))
        payload = canonical_json({"synthetic": True, "fixture": "known historical schema"})
        payload_hash = sha256_hex(payload)
        prev = "0" * 64
        entry = sha256_hex("|".join([prev, stamp, "owner", "b03.legacy_fixture", "workspace", "ws_b03_legacy", payload_hash]))
        conn.execute("INSERT INTO audit_log (ts,actor,action,entity_type,entity_id,payload_json,payload_hash,prev_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                     (stamp,"owner","b03.legacy_fixture","workspace","ws_b03_legacy",payload,payload_hash,prev,entry))
        conn.commit()
    finally:
        conn.close()
    Path(str(path) + ".authority").write_text("inst_b03_legacy")


def declarations(db):
    return db.query("SELECT * FROM audit_log WHERE action=? ORDER BY seq", (MODE_ACTION,))


class WorkspaceModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cipher-b03-proposal-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_new_memory_and_file_are_declared_practice_and_bound_to_original_workspace(self):
        for path in (":memory:", str(self.directory / "new.sqlite")):
            with self.subTest(path_kind="memory" if path == ":memory:" else "file"):
                cipher = Cipher(path)
                self.addCleanup(cipher.db.close)
                workspace = cipher.db.workspace()
                self.assertEqual(workspace.get("mode"), "practice")
                mode = cipher.db.mode_status()
                self.assertTrue(mode["verified"])
                self.assertEqual(mode["origin"], "created")
                self.assertEqual(mode["mode"], "practice")
                rows = declarations(cipher.db)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["entity_id"], workspace["workspace_id"])
                self.assertTrue(cipher.audit.verify_chain()["ok"])

    def test_writable_known_legacy_adopts_once_and_preserves_original_history(self):
        path = self.directory / "legacy.sqlite"
        legacy_file(path)
        cipher = Cipher(str(path))
        self.addCleanup(cipher.db.close)
        self.assertEqual(cipher.db.workspace()["workspace_id"], "ws_b03_legacy")
        self.assertEqual(cipher.db.workspace().get("mode"), "practice")
        self.assertEqual(len(declarations(cipher.db)), 1)
        self.assertEqual(cipher.audit.entries()[0]["action"], "b03.legacy_fixture")
        before = cipher.audit.entries()
        cipher.db.close()
        again = Cipher(str(path))
        self.addCleanup(again.db.close)
        self.assertEqual(again.audit.entries(), before)

    def test_known_legacy_copy_is_pending_read_only_and_declares_only_in_claim(self):
        source = self.directory / "source.sqlite"
        target = self.directory / "copy.sqlite"
        legacy_file(source)
        with sqlite3.connect(source) as a, sqlite3.connect(target) as b:
            a.backup(b)
        db = core_db.Database(str(target))
        self.addCleanup(db.close)
        self.assertFalse(db.has_write_authority())
        self.assertTrue(db.read_only)
        self.assertEqual(db.mode_status()["state"], "pending_practice_declaration")
        self.assertIsNone(db.mode_status()["mode"])
        self.assertEqual(declarations(db), [])
        self.assertFalse(Path(str(target) + ".authority").exists())
        with mock.patch.dict(os.environ, {"CIPHER_OWNER_SECRET": "synthetic-owner-secret-b03"}):
            code = db.expected_claim_code("synthetic-owner-secret-b03")
            with self.assertRaises(core_db.WriteAuthorityError):
                db.claim_write_authority(approver="owner",reason="Synthetic restore drill",claim_code="wrong-code")
            self.assertEqual(declarations(db), [])
            db.claim_write_authority(approver="owner",reason="Synthetic restore drill",claim_code=code)
        self.assertEqual(db.workspace()["workspace_id"], "ws_b03_legacy")
        self.assertEqual(db.mode_status()["mode"], "practice")
        self.assertTrue(db.mode_status()["verified"])
        self.assertEqual(len(declarations(db)), 1)
        self.assertTrue(db.authority_status()["release_quarantined"])

    def test_foreign_sqlite_is_refused_before_any_migration_or_authority_file(self):
        path = self.directory / "foreign.sqlite"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER)")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(core_db.SchemaError):
            Cipher(str(path))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(path) + ".authority").exists())
        self.assertFalse(Path(str(path) + ".claim-challenge").exists())

    def test_missing_core_workspace_is_not_recreated_or_given_authority(self):
        path = self.directory / "missing-workspace.sqlite"
        legacy_file(path)
        with sqlite3.connect(path) as conn:
            conn.execute("DELETE FROM workspace")
        original_authority = Path(str(path) + ".authority").read_text()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(core_db.SchemaError):
            Cipher(str(path))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertEqual(Path(str(path) + ".authority").read_text(), original_authority)

    def test_mode_and_workspace_identity_cannot_change_or_be_replaced(self):
        cipher = Cipher()
        self.addCleanup(cipher.db.close)
        for sql in ("UPDATE workspace SET mode='live'", "UPDATE workspace SET workspace_id='ws_changed'", "DELETE FROM workspace"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                cipher.db.execute(sql)

    def test_dropped_guards_and_changed_workspace_id_do_not_rebind_a_mode_proof(self):
        path = self.directory / "changed-id.sqlite"
        cipher = Cipher(str(path))
        cipher.db.close()
        with sqlite3.connect(path) as raw:
            for row in raw.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='workspace'").fetchall():
                raw.execute('DROP TRIGGER "' + row[0].replace('"','""') + '"')
            raw.execute("UPDATE workspace SET workspace_id='ws_counterfeit'")
        with self.assertRaises(core_db.SchemaError):
            Cipher(str(path))
    def test_existing_empty_file_is_not_treated_as_new(self):
        path = self.directory / "empty.sqlite"
        path.touch()
        with self.assertRaises(core_db.SchemaError):
            Cipher(str(path))
        self.assertEqual(path.read_bytes(), b"")
        self.assertFalse(Path(str(path) + ".authority").exists())

    def test_planted_matching_catalog_hash_does_not_prove_installed_schema(self):
        path = self.directory / "counterfeit.sqlite"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY,name TEXT,statement_count INTEGER,checksum TEXT,applied_at TEXT)")
            _, name, statements = core_db.SCHEMA_CATALOG[0]
            conn.execute("INSERT INTO schema_version VALUES (1,?,?,?,'t')", (name,len(statements),core_db.catalog_checksum(statements)))
            conn.execute("CREATE TABLE workspace (id INTEGER,workspace_id TEXT)")
            conn.execute("INSERT INTO workspace VALUES (1,'ws_counterfeit')")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(core_db.SchemaError):
            Cipher(str(path))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(path) + ".authority").exists())

    def test_same_connection_memory_tamper_blocks_the_next_sql_write(self):
        cipher = Cipher()
        self.addCleanup(cipher.db.close)
        # A stronger attacker bypasses the managed connection's pre-statement guard.
        with cipher.db._internal() as raw:
            for row in raw.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='workspace'").fetchall():
                raw.execute('DROP TRIGGER "' + row[0].replace('"','""') + '"')
            raw.execute("UPDATE workspace SET mode='live'")
        with self.assertRaises(core_db.WorkspaceModeError):
            cipher.db.execute("INSERT INTO parties (id,kind,name,created_at) VALUES ('blocked','supplier','Synthetic','t')")
        with self.assertRaises(core_db.WorkspaceModeError):
            cipher.db.require_practice_mode()
        self.assertIsNone(cipher.db.one("SELECT id FROM parties WHERE id='blocked'"))

    def test_claim_rollback_does_not_leave_mode_or_authority(self):
        source = self.directory / "source-rollback.sqlite"
        target = self.directory / "copy-rollback.sqlite"
        legacy_file(source)
        with sqlite3.connect(source) as a, sqlite3.connect(target) as b:
            a.backup(b)
        db = core_db.Database(str(target))
        self.addCleanup(db.close)
        before = db.query("SELECT * FROM audit_log ORDER BY seq")
        with mock.patch.dict(os.environ, {"CIPHER_OWNER_SECRET": ""}), \
                mock.patch.object(db, "_write_sidecar", side_effect=OSError("synthetic sidecar failure")):
            with self.assertRaises(OSError):
                db.claim_write_authority(approver="owner",reason="Synthetic failed restore drill")
        self.assertEqual(db.query("SELECT * FROM audit_log ORDER BY seq"), before)
        self.assertEqual(db.mode_status()["state"], "pending_practice_declaration")
        self.assertTrue(db.read_only)
        self.assertFalse(db.has_write_authority())
        self.assertFalse(Path(str(target) + ".authority").exists())

    def test_valid_future_live_file_is_refused_before_writable_open_or_initializer(self):
        path = self.directory / "future-live.sqlite"
        cipher = Cipher(str(path))
        cipher.db.close()
        # Model a valid future live-mode file, preserving the full installed DDL
        # and a canonical, internally consistent audit chain. This is distinct
        # from an invalid tag on a currently declared practice workspace.
        with sqlite3.connect(path) as raw:
            triggers = raw.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('workspace','audit_log')").fetchall()
            for name, _ in triggers:
                raw.execute('DROP TRIGGER "' + name.replace('"','""') + '"')
            raw.execute("UPDATE workspace SET mode='live'")
            previous = "0" * 64
            rows = raw.execute("SELECT seq,ts,actor,action,entity_type,entity_id,payload_json FROM audit_log ORDER BY seq").fetchall()
            for seq, ts, actor, action, entity_type, entity_id, text in rows:
                payload = json.loads(text)
                if action == core_db.MODE_ACTION:
                    payload["mode"] = "live"
                text = canonical_json(payload)
                payload_hash = sha256_hex(text)
                entry_hash = sha256_hex("|".join([previous,ts,actor,action,entity_type,entity_id,payload_hash]))
                raw.execute("UPDATE audit_log SET payload_json=?,payload_hash=?,prev_hash=?,entry_hash=? WHERE seq=?", (text,payload_hash,previous,entry_hash,seq))
                previous = entry_hash
            for _, sql in triggers:
                raw.execute(sql)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        connect = sqlite3.connect
        def read_only_inspection(*args, **kwargs):
            if args[0] == str(path):
                raise AssertionError("live file reached writable SQLite opening")
            return connect(*args, **kwargs)
        with mock.patch.object(core_db.sqlite3, "connect", side_effect=read_only_inspection), \
                mock.patch.object(core_db.Database, "_migrate", side_effect=AssertionError("live initializer ran")) as migrate:
            with self.assertRaises(core_db.WorkspaceModeError):
                core_db.Database(str(path))
            migrate.assert_not_called()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_existing_declared_and_legacy_copies_are_read_only_without_migration(self):
        for legacy in (False,True):
            with self.subTest(legacy=legacy):
                source = self.directory / ("legacy-inspect.sqlite" if legacy else "declared-inspect.sqlite")
                target = self.directory / ("legacy-copy-inspect.sqlite" if legacy else "declared-copy-inspect.sqlite")
                if legacy:
                    legacy_file(source)
                else:
                    cipher = Cipher(str(source))
                    cipher.db.close()
                with sqlite3.connect(source) as a, sqlite3.connect(target) as b:
                    a.backup(b)
                db = core_db.Database(str(target), migrate=False)
                self.addCleanup(db.close)
                self.assertFalse(db.has_write_authority())
                self.assertTrue(db.read_only)
                self.assertEqual(db.scalar("PRAGMA query_only"),1)
                with self.assertRaises(core_db.WriteAuthorityError):
                    db.execute("INSERT INTO parties (id,kind,name,created_at) VALUES ('blocked','supplier','Synthetic','t')")
                self.assertFalse(Path(str(target)+".authority").exists())
                if legacy:
                    self.assertEqual(declarations(db),[])

    def test_owned_legacy_diagnostic_does_not_authorize_runtime_writes(self):
        path = self.directory / "owned-legacy-diagnostic.sqlite"
        legacy_file(path)
        db = core_db.Database(str(path),migrate=False)
        self.addCleanup(db.close)
        self.assertTrue(db.has_write_authority())
        self.assertTrue(db.read_only)
        with self.assertRaises(core_db.WorkspaceModeError):
            db.require_practice_mode(allow_pending=True)
        with self.assertRaises(core_db.WriteAuthorityError):
            db.execute("INSERT INTO parties (id,kind,name,created_at) VALUES ('blocked','supplier','Synthetic','t')")
        db.migrate()
        self.assertEqual(db.mode_status()["mode"],"practice")
        self.assertFalse(db.read_only)
        self.assertEqual(len(declarations(db)),1)

    def test_nested_claim_is_refused_before_any_owner_or_mode_effect(self):
        source = self.directory / "source-nested.sqlite"
        target = self.directory / "copy-nested.sqlite"
        legacy_file(source)
        with sqlite3.connect(source) as a, sqlite3.connect(target) as b:
            a.backup(b)
        db = core_db.Database(str(target))
        self.addCleanup(db.close)
        before = db.query("SELECT * FROM audit_log ORDER BY seq")
        original = db.workspace()
        with mock.patch.dict(os.environ, {"CIPHER_OWNER_SECRET": ""}), \
                mock.patch.object(db,"_write_sidecar",side_effect=OSError("synthetic sidecar failure")) as sidecar:
            with db.transaction():
                with self.assertRaises(core_db.WriteAuthorityError):
                    db.claim_write_authority(approver="owner",reason="Synthetic nested claim")
            sidecar.assert_not_called()
        self.assertEqual(db.query("SELECT * FROM audit_log ORDER BY seq"),before)
        self.assertEqual(db.workspace(),original)
        self.assertEqual(db.mode_status()["state"],"pending_practice_declaration")
        self.assertTrue(db.read_only)
        self.assertFalse(Path(str(target)+".authority").exists())



if __name__ == "__main__":
    unittest.main()
