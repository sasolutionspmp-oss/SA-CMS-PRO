"""Read-only, loopback Fluent practice server; always a fresh in-memory fixture.

This is a local design/test harness, not the authenticated production API.
It mounts no owner console, action route, selectable workspace or integration.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
from stat import S_ISREG
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .service import Cipher, run_golden_fixture
from .core.db import WorkspaceModeError


API_PREFIX = "/api/practice/v1/"
COLLECTIONS = frozenset(("projects", "commitments", "bills", "approvals"))
DEFAULT_WEBROOT = Path(__file__).parent / "web" / "dist"
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def _is_static_file(path: Path) -> bool:
    """Keep filesystem errors visible instead of suppressing them in is_file()."""
    try:
        return S_ISREG(path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


class PracticeHTTPServer(ThreadingHTTPServer):
    """Owns and freezes its synthetic fixture before serving any requests."""

    def __init__(self, port: int, webroot: Path):
        self.webroot = webroot.resolve()
        self.cipher = Cipher(":memory:")
        self.cipher_lock = threading.Lock()
        try:
            run_golden_fixture(self.cipher)
            # The Database authorizer deliberately rejects raw pragma assignment.
            # Freeze this owned ephemeral connection through its managed guard;
            # it has no file authority/claim lifecycle or mutation routes.
            with self.cipher.db._lock:
                self.cipher.db._set_query_only(True)
            super().__init__(("127.0.0.1", port), PracticeHandler)
        except BaseException:
            self.cipher.db.close()
            raise

    def server_close(self):
        try:
            super().server_close()
        finally:
            self.cipher.db.close()


class PracticeHandler(BaseHTTPRequestHandler):
    server: PracticeHTTPServer
    server_version = "CipherPractice"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass  # do not put query contents or local paths into logs

    def _respond(self, status, payload: bytes, content_type, *, nonce=None, cache="no-store", allow=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        style = "style-src 'self'" + (f" 'nonce-{nonce}'" if nonce else "")
        self.send_header("Content-Security-Policy", "; ".join((
            "default-src 'none'", "script-src 'self'", style,
            "connect-src 'self'", "img-src 'self' data:", "font-src 'self'",
            "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
        )))
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, status, data, *, allow=None):
        self._respond(status, json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode(),
                      "application/json; charset=utf-8", allow=allow)

    def _error(self, status, code, message, target=None, *, allow=None):
        self._json(status, {"mode": "practice", "synthetic": True,
                           "error": {"code": code, "target": target, "message": message}}, allow=allow)

    def _same_origin(self):
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_address[1]
        allowed = (f"127.0.0.1:{port}", f"localhost:{port}")
        if len(hosts) != 1 or hosts[0] not in allowed:
            self._error(403, "host_refused", "Open this practice server on its local address.")
            return False
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0] != f"http://{hosts[0]}"):
            self._error(403, "origin_refused", "Read practice data from the same local origin.")
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            self._error(403, "origin_refused", "Read practice data from the same local origin.")
            return False
        return True

    def do_GET(self):
        if not self._same_origin():
            return
        try:
            self.server.cipher.db.require_practice_mode()
        except WorkspaceModeError:
            self._error(503, "workspace_mode_unavailable", "A verified practice workspace is required.")
            return
        if len(self.path) > 4096 or re.search(r"%(?![0-9A-Fa-f]{2})", self.path):
            self._error(400, "invalid_url", "Use a valid practice URL.")
            return
        try:
            url = urlsplit(self.path)
            path = unquote(url.path, errors="strict")
        except (ValueError, UnicodeError):
            self._error(400, "invalid_url", "Use a valid practice URL.")
            return
        if url.scheme or url.netloc or url.fragment or "\x00" in path or "\\" in path or ".." in path.split("/"):
            self._error(400, "invalid_url", "Use a local practice URL without parent paths.")
            return
        if path.startswith(API_PREFIX):
            self._read_api(path.removeprefix(API_PREFIX), url.query)
        elif path.startswith("/api"):
            self._error(404, "route_not_found", "This practice route is not available.")
        else:
            self._static(path)

    do_HEAD = do_GET

    def _read_api(self, collection, query):
        from .api_contract import PracticeReadRefusal, contract_snapshot, practice_read
        if collection not in COLLECTIONS | {"health", "contract"}:
            self._error(404, "route_not_found", "This practice collection is not available.")
            return
        try:
            params = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=6)
            allowed = {"projectId", "status", "search", "top", "cursor"} if collection in COLLECTIONS else set()
            if params.keys() - allowed or any(len(values) != 1 for values in params.values()):
                raise ValueError("unknown or repeated parameter")
            values = {key: value[0] for key, value in params.items()}
            if "top" in values and not re.fullmatch(r"[0-9]{1,3}", values["top"]):
                raise ValueError("top must be an integer")
            kwargs = {"project_id": values.get("projectId"), "status": values.get("status"),
                      "search": values.get("search"), "cursor": values.get("cursor"),
                      "top": int(values.get("top", "50"))}
        except ValueError:
            self._error(400, "invalid_query", "Use each supported filter once and an integer page size from 1 to 100.", "query")
            return
        try:
            with self.server.cipher_lock:
                if collection == "health":
                    result = {"mode": "practice", "synthetic": True, "writesEnabled": False,
                              "accountingIntegration": "none"}
                elif collection == "contract":
                    result = contract_snapshot(self.server.cipher)
                else:
                    result = practice_read(self.server.cipher, collection, **kwargs)
            self._json(200, result)
        except PracticeReadRefusal as exc:
            self._error(400, exc.code, exc.message, exc.target)
        except Exception:
            self._error(500, "practice_read_failed", "Practice data could not be read. Restart the local practice server.")

    def _static(self, path):
        root = self.server.webroot
        relative = path.lstrip("/") or "index.html"
        try:
            candidate = (root / relative).resolve()
            candidate.relative_to(root)
            # Missing assets never fall back to the shell.
            if not _is_static_file(candidate) and "." not in path and not path.startswith("/assets/"):
                candidate = (root / "index.html").resolve()
            candidate.relative_to(root)
            mime = MIME_TYPES.get(candidate.suffix)
            if not _is_static_file(candidate) or not mime:
                self._error(404, "web_build_missing", "Build the Fluent practice app in apps/cipher/web before opening this page.")
                return
            payload = candidate.read_bytes()
            if candidate.suffix == ".html":
                nonce = secrets.token_urlsafe(24)
                payload = payload.replace(b"__CIPHER_STYLE_NONCE__", nonce.encode())
                self._respond(200, payload, mime, nonce=nonce)
            else:
                # Vite names production assets by content hash; other fixtures revalidate.
                hashed = re.search(r"-[A-Za-z0-9_-]{8,}\.", candidate.name)
                self._respond(200, payload, mime, cache="public, max-age=31536000, immutable" if hashed else "no-cache")
        except (OSError, ValueError, RuntimeError):
            self._error(404, "route_not_found", "This practice resource is not available.")

    def _method_refused(self):
        if self._same_origin():
            self._error(405, "read_only_practice", "This practice interface only reads synthetic data.", allow="GET, HEAD")

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = _method_refused


def make_practice_server(*, port=8766, webroot: Path | None = None) -> PracticeHTTPServer:
    """No host, file database, actor, credentials or provider can be selected."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Use a port from 0 to 65535.")
    return PracticeHTTPServer(port, DEFAULT_WEBROOT if webroot is None else Path(webroot))


def serve_practice(*, port=8766):
    server = make_practice_server(port=port)
    print(f"Cipher Fluent practice: http://127.0.0.1:{server.server_address[1]} (synthetic, read-only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
