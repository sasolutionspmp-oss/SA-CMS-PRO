"""The Fluent practice surface owns synthetic data and cannot reach action APIs."""
import errno
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from apps.cipher.practice_server import make_practice_server
from apps.cipher.core.db import WriteAuthorityError


class PracticeServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "assets").mkdir()
        (root / "index.html").write_text(
            '<!doctype html><meta name="cipher-style-nonce" content="__CIPHER_STYLE_NONCE__">'
            '<div id="root"></div><script type="module" src="/assets/app.js"></script>',
            encoding="utf-8",
        )
        (root / "assets" / "app.js").write_text("export const practice = true;", encoding="utf-8")
        (root / "assets" / "app.css").write_text("body { color: navy; }", encoding="utf-8")
        cls.server = make_practice_server(port=0, webroot=root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.temp.cleanup()

    def request(self, path, *, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_health_identifies_in_memory_read_only_practice(self):
        status, headers, raw = self.request("/api/practice/v1/health")
        self.assertEqual(status, 200)
        body = json.loads(raw)
        self.assertEqual(body["mode"], "practice")
        self.assertTrue(body["synthetic"])
        self.assertFalse(body["writesEnabled"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.server.cipher.db.conn.execute("PRAGMA database_list").fetchone()[2], "")

    def test_backend_projects_are_read_through_the_versioned_contract(self):
        status, _, raw = self.request("/api/practice/v1/projects?top=1")
        self.assertEqual(status, 200, raw)
        body = json.loads(raw)
        self.assertEqual(body["mode"], "practice")
        self.assertEqual(len(body["value"]), 1)
        self.assertEqual(body["value"][0]["id"], self.server.cipher.projects()[0]["id"])
        self.assertEqual(body["currency"], "USD")

    def test_reads_do_not_change_database_or_audit(self):
        before = "\n".join(self.server.cipher.db.conn.iterdump())
        for collection in ("projects", "commitments", "bills", "approvals", "contract", "health"):
            status, _, raw = self.request("/api/practice/v1/" + collection)
            self.assertEqual(status, 200, raw)
        self.assertEqual(before, "\n".join(self.server.cipher.db.conn.iterdump()))

    def test_workspace_is_frozen_at_sqlite_boundary(self):
        with self.assertRaises(WriteAuthorityError):
            self.server.cipher.db.conn.execute("DELETE FROM projects")

    def test_old_actions_and_state_are_absent(self):
        for route in ("/api/action/run_demo", "/api/state", "/api/audit-export", "/api/modules"):
            status, _, raw = self.request(route)
            self.assertEqual(status, 404, (route, raw))
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            status, headers, raw = self.request("/api/practice/v1/projects", method=method, body="{}")
            self.assertEqual(status, 405, (method, raw))
            self.assertEqual(headers["Allow"], "GET, HEAD")

    def test_forged_identity_unknown_and_duplicate_query_are_refused(self):
        for query in ("actor=owner", "role=owner", "top=1&top=2", "top=NaN", "top=1.0", "top=-1"):
            status, _, raw = self.request("/api/practice/v1/projects?" + query)
            self.assertEqual(status, 400, (query, raw))
            self.assertIn("code", json.loads(raw)["error"])

    def test_foreign_and_ambiguous_host_or_origin_are_refused(self):
        for headers in (
            {"Host": "attacker.example"},
            {"Host": "127.0.0.1:1"},
            {"Origin": "https://attacker.example"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            status, _, _ = self.request("/api/practice/v1/projects", headers=headers)
            self.assertEqual(status, 403, headers)
        status, _, _ = self.request("/api/practice/v1/projects", headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)

    def test_html_uses_fresh_matching_style_nonce_and_self_only_scripts(self):
        documents = []
        for path in ("/", "/projects/synthetic-job"):
            status, headers, raw = self.request(path)
            self.assertEqual(status, 200)
            html = raw.decode()
            nonce = html.split('name="cipher-style-nonce" content="', 1)[1].split('"', 1)[0]
            self.assertNotEqual(nonce, "__CIPHER_STYLE_NONCE__")
            self.assertIn("'nonce-" + nonce + "'", headers["Content-Security-Policy"])
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
            self.assertNotIn("'unsafe-inline'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Cache-Control"], "no-store")
            documents.append(nonce)
        self.assertNotEqual(*documents)

    def test_static_assets_have_explicit_mime_and_missing_assets_are_not_html(self):
        for path, mime in (("/assets/app.js", "text/javascript"), ("/assets/app.css", "text/css")):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(mime))
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, _, raw = self.request("/assets/missing.js")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "web_build_missing")

    def test_encoded_traversal_and_symlink_escape_are_refused(self):
        secret = Path(self.temp.name).parent / (Path(self.temp.name).name + "-secret.txt")
        secret.write_text("unexposed-test-source", encoding="utf-8")
        link = Path(self.temp.name) / "assets" / "escape.js"
        link.symlink_to(secret)
        try:
            for path in ("/%2e%2e/secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/assets/escape.js", "/%00", "/%ZZ"):
                status, _, raw = self.request(path)
                self.assertIn(status, (400, 404), (path, raw))
                self.assertNotIn(b"unexposed-test-source", raw)
        finally:
            link.unlink()
            secret.unlink()

    def test_head_and_unknown_collection_have_no_side_effects(self):
        status, headers, raw = self.request("/api/practice/v1/projects", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(raw, b"")
        self.assertGreater(int(headers["Content-Length"]), 0)
        status, _, raw = self.request("/api/practice/v1/payments")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "route_not_found")

    def test_cyclic_static_symlink_is_a_typed_refusal(self):
        link = Path(self.temp.name) / "loop.js"
        link.symlink_to("loop.js")
        try:
            status, _, raw = self.request("/loop.js")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(raw)["error"]["code"], "route_not_found")
            self.assertNotIn(str(link).encode(), raw)
        finally:
            link.unlink()

    def test_static_stat_error_is_a_typed_refusal(self):
        with patch.object(Path, "stat", side_effect=OSError(errno.ELOOP, "synthetic symlink loop")):
            status, _, raw = self.request("/assets/app.js")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "route_not_found")
        self.assertNotIn(b"synthetic symlink loop", raw)

    def test_cli_exposes_no_file_workspace_or_host_option(self):
        from apps.cipher.__main__ import main
        for option in (("--db", "live.sqlite"), ("--host", "0.0.0.0")):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                main(["practice-web", *option])


if __name__ == "__main__":
    unittest.main()
