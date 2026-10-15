"""Practice runtime isolation from an unqualified external provider."""
import os
import http.client
import json
import tempfile
import threading
import unittest
import subprocess
import sys
from pathlib import Path

from apps.cipher.service import Cipher
from apps.cipher.core.db import WorkspaceModeError, WriteAuthorityError
from apps.cipher.api_contract import PracticeReadRefusal, contract_snapshot, practice_read
from apps.cipher.server import BackgroundServer, _actions, make_server
from apps.cipher.practice_server import make_practice_server


class ExternalProviderProbe:
    """No external calls: this is an unqualified duck-typed test double."""

    webhook_secret = "synthetic-unqualified-test-secret"
    synthetic = True
    live = False


class WorkspaceRuntimeTests(unittest.TestCase):
    @staticmethod
    def alter_mode(cipher):
        # Model file-level corruption, outside the normal guarded SQL path.
        with cipher.db._internal() as conn:
            conn.execute("DROP TRIGGER workspace_mode_immutable")
            conn.execute("DROP TRIGGER workspace_mode_declaration_required")
            conn.execute("UPDATE workspace SET mode='live' WHERE id=1")

    def test_unqualified_provider_is_refused_before_a_new_file_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "practice.sqlite")
            with self.assertRaises(PermissionError):
                cipher = Cipher(path, provider=ExternalProviderProbe())
                self.addCleanup(cipher.db.close)
            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(path + ".authority"))

    def test_unqualified_provider_cannot_open_or_migrate_an_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "existing.sqlite")
            cipher = Cipher(path)
            cipher.db.close()
            with open(path, "rb") as stream:
                original = stream.read()
            with open(path + ".authority", "rb") as stream:
                authority = stream.read()
            with self.assertRaises(PermissionError):
                reopened = Cipher(path, provider=ExternalProviderProbe())
                self.addCleanup(reopened.db.close)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), original)
            with open(path + ".authority", "rb") as stream:
                self.assertEqual(stream.read(), authority)

    def test_mode_cache_does_not_preserve_lost_physical_write_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "practice.sqlite")
            cipher = Cipher(path)
            self.addCleanup(cipher.db.close)
            cipher.add_party(kind="supplier", name="Synthetic first supplier")
            before = cipher.db.scalar("SELECT COUNT(*) FROM parties")
            os.unlink(path + ".authority")
            self.assertFalse(cipher.db.has_write_authority())
            with self.assertRaises(WriteAuthorityError):
                cipher.db.execute("INSERT INTO parties(id,kind,name,created_at) VALUES('blocked','supplier','Synthetic','t')")
            self.assertEqual(cipher.db.scalar("SELECT COUNT(*) FROM parties"), before)

    def test_schema_command_loads_the_full_registered_cipher_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "practice.sqlite")
            cipher = Cipher(path)
            expected = cipher.db.schema_status()["current_version"]
            cipher.db.close()
            result = subprocess.run([sys.executable, "-m", "apps.cipher", "schema", "--db", path],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            status = json.loads(result.stdout)
            self.assertEqual(status["current_version"], expected)
            self.assertIn("workspace_mode", [version["name"] for version in status["versions"]])

    def test_schema_command_refuses_a_foreign_file_without_changes(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "foreign.sqlite")
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE unrelated (value TEXT)")
            original = Path(path).read_bytes()
            result = subprocess.run([sys.executable, "-m", "apps.cipher", "schema", "--db", path],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("cipher:", result.stderr)
            self.assertEqual(Path(path).read_bytes(), original)
            self.assertFalse(os.path.exists(path + ".authority"))

    def test_changed_mode_refuses_service_actions_before_subject_lookup_or_effects(self):
        cipher = Cipher()
        self.addCleanup(cipher.db.close)
        self.alter_mode(cipher)
        before = cipher.db.scalar("SELECT COUNT(*) FROM audit_log")
        for invoke in (
            lambda: cipher.request_approval("bill.approve", "missing"),
            lambda: cipher.approve("missing"),
            lambda: cipher.execute("missing"),
            lambda: cipher.post_bill("missing", actor="poster"),
        ):
            with self.subTest(invoke=invoke):
                with self.assertRaises(WorkspaceModeError):
                    invoke()
        self.assertEqual(cipher.db.scalar("SELECT COUNT(*) FROM audit_log"), before)

    def test_changed_mode_refuses_server_binding_and_direct_console_callbacks(self):
        cipher = Cipher()
        self.addCleanup(cipher.db.close)
        callbacks = _actions(cipher)
        self.alter_mode(cipher)
        with self.assertRaises(WorkspaceModeError):
            make_server(cipher, port=0)
        for action in ("create_project", "claim_authority", "set_provider_mode", "module_call"):
            with self.subTest(action=action):
                with self.assertRaises(WorkspaceModeError):
                    callbacks[action]({})
        self.assertEqual(cipher.db.scalar("SELECT COUNT(*) FROM projects"), 0)

    def test_running_console_refuses_get_and_post_after_mode_change(self):
        cipher = Cipher()
        self.addCleanup(cipher.db.close)
        with BackgroundServer(cipher) as server:
            self.alter_mode(cipher)
            host, port = server.httpd.server_address[:2]
            for method, path, body in (
                ("GET", "/api/projects", None),
                ("GET", "/api/health", None),
                ("POST", "/api/action/create_project", json.dumps({"name": "Must not be created"})),
            ):
                with self.subTest(method=method, path=path):
                    conn = http.client.HTTPConnection(host, port, timeout=10)
                    try:
                        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
                        response = conn.getresponse()
                        self.assertEqual(response.status, 503)
                        self.assertEqual(json.loads(response.read())["code"], "workspace_mode_unavailable")
                    finally:
                        conn.close()
        self.assertEqual(cipher.db.scalar("SELECT COUNT(*) FROM projects"), 0)

    def test_practice_contract_requires_persisted_verified_mode_as_well_as_memory(self):
        cipher = Cipher()
        self.addCleanup(cipher.db.close)
        self.alter_mode(cipher)
        for read in (lambda: contract_snapshot(cipher), lambda: practice_read(cipher, "projects")):
            with self.assertRaises(PracticeReadRefusal) as refusal:
                read()
            self.assertEqual(refusal.exception.code, "unsupported_workspace")

    def test_frozen_fluent_surface_refuses_static_and_api_reads_after_mode_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<!doctype html><title>Practice</title>")
            server = make_practice_server(port=0, webroot=root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                server.cipher.db._set_query_only(False)
                self.alter_mode(server.cipher)
                server.cipher.db._set_query_only(True)
                for path in ("/", "/api/practice/v1/health", "/api/practice/v1/projects"):
                    with self.subTest(path=path):
                        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                        try:
                            conn.request("GET", path)
                            response = conn.getresponse()
                            self.assertEqual(response.status, 503)
                            self.assertEqual(json.loads(response.read())["error"]["code"], "workspace_mode_unavailable")
                        finally:
                            conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
