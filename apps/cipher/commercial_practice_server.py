"""Fixed human commercial practice API and Fluent host on loopback.

Every server owns fresh memory records, registered synthetic people and seven
local actions. Manual quantities are source facts, not geometric measurements.
No file workspace, production identity or external provider can be selected.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import threading
from http.server import ThreadingHTTPServer
import uuid

from .ap_contract import APRefusal
from .ap_practice_server import APPracticeHandler
from .core.db import WorkspaceModeError
from .practice_server import MIME_TYPES
from .commercial_wire import (COLLECTIONS, MAX_BODY_BYTES, PROVENANCE, WireRefusal,
                              collection_query, decode_action_body, parse_json, resolve_action_route)


API_PREFIX = "/api/commercial-practice/v1/"
COOKIE_NAME = "cipher_commercial_practice"
DEFAULT_WEBROOT = Path(__file__).parent / "web" / "dist-commercial"
_RESOURCE = r"([A-Za-z0-9][A-Za-z0-9_.:-]{0,127})"
_DETAILS = (
    (re.compile(r"projects/" + _RESOURCE + r"/estimate-preparation"), "preparation"),
    (re.compile(r"estimates/" + _RESOURCE), "estimate"),
    (re.compile(r"estimates/" + _RESOURCE + r"/comparison"), "comparison"),
    (re.compile(r"estimate-approvals/" + _RESOURCE + r"/packet"), "packet"),
    (re.compile(r"estimates/" + _RESOURCE + r"/handoff-preparation"), "handoff_preparation"),
    (re.compile(r"estimate-handoffs/" + _RESOURCE), "handoff"),
    (re.compile(r"commercial-commitments/" + _RESOURCE), "commitment"),
)


class CommercialPracticeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, webroot: Path):
        from .commercial_actions import CommercialActionRunner
        from .commercial_contract import CommercialContract
        from .commercial_preflight import CommercialPreflight
        from .commercial_practice_fixture import make_commercial_practice_fixture
        from .commercial_receipts import register_commercial_receipts_schema
        from .commercial_sessions import CommercialPracticeSessions
        from .domain.commercial import register_commercial_schema

        self.webroot = webroot.resolve()
        self.cipher_lock = threading.RLock()
        register_commercial_schema()
        register_commercial_receipts_schema()
        self.cipher = make_commercial_practice_fixture()
        try:
            self.require_practice()
            secret = secrets.token_bytes(32)
            self.contract = CommercialContract(self.cipher, secret=secret)
            self.preflight = CommercialPreflight(self.cipher, self.contract, secret=secret)
            self.actions = CommercialActionRunner(self.cipher, self.contract, self.preflight)
            self.cipher.register_plugin("commercial_api_sources", self.actions)
            self.sessions = CommercialPracticeSessions(self.cipher)
            super().__init__(("127.0.0.1", port), CommercialPracticeHandler)
        except BaseException:
            self.cipher.db.close()
            raise

    def require_practice(self):
        self.cipher.db.require_practice_mode()
        if not self.cipher.db.in_memory or any(row[2] for row in self.cipher.db.conn.execute("PRAGMA database_list")):
            raise WorkspaceModeError("Commercial practice requires an in-memory workspace.")

    def server_close(self):
        try:
            super().server_close()
        finally:
            self.cipher.db.close()


class CommercialPracticeHandler(APPracticeHandler):
    """Reuse transport checks without sharing AP sessions, records or routes."""
    server: CommercialPracticeHTTPServer
    server_version = "CipherCommercialPractice"

    def _respond(self, status, payload: bytes, content_type, *, nonce=None, cache="no-store", allow=None, cookie=None, etag=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "; ".join((
            "default-src 'none'", "script-src 'self'", "style-src 'self'" + (f" 'nonce-{nonce}'" if nonce else ""),
            "connect-src 'self'", "img-src 'self' data:", "font-src 'self'",
            "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
        )))
        if allow:
            self.send_header("Allow", allow)
        if cookie:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={cookie}; HttpOnly; SameSite=Strict; Path=/")
        if etag:
            self.send_header("ETag", '"' + etag + '"')
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            # Original local receipts survive a lost response.
            self.close_connection = True

    def _error(self, status, code, message, target=None, *, receipt=None, **kwargs):
        value = {**PROVENANCE, "error": {"code": code, "target": target, "message": message,
                                        "fix": None, "details": None}}
        if receipt is not None:
            value.update(receipt)
        self._json(status, value, **kwargs)

    def _session(self):
        cookie = self._one_header("Cookie")
        values = []
        if cookie:
            for part in cookie.split(";"):
                key, separator, value = part.strip().partition("=")
                if key == COOKIE_NAME:
                    if not separator or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", value):
                        raise APRefusal(401, "session_required", "Start a commercial practice session.", "session")
                    values.append(value)
        if len(values) > 1:
            raise APRefusal(400, "invalid_headers", "Use one commercial session cookie.", "Cookie")
        return self.server.sessions.get(values[0] if values else None)

    def _raw_body(self):
        if self._one_header("Transfer-Encoding") is not None:
            raise APRefusal(400, "invalid_body", "Send one bounded JSON request body.", "body")
        content_type = self._one_header("Content-Type", required=True)
        if not re.fullmatch(r"application/json(?:\s*;\s*charset=utf-8)?", content_type, re.IGNORECASE):
            raise APRefusal(415, "invalid_content_type", "Send application/json using UTF-8.", "Content-Type")
        length = self._one_header("Content-Length", required=True)
        if not re.fullmatch(r"[0-9]{1,6}", length):
            raise APRefusal(400, "invalid_body", "Send one bounded JSON request body.", "body")
        size = int(length)
        if size > MAX_BODY_BYTES:
            raise APRefusal(413, "body_too_large", "Keep this commercial request within 16 KB.", "body")
        if not size:
            raise APRefusal(422, "invalid_body", "Send one JSON object.", "body")
        try:
            raw = self.rfile.read(size)
        except OSError:
            raise APRefusal(422, "invalid_body", "Send one complete JSON request body.", "body") from None
        if len(raw) != size:
            raise APRefusal(422, "invalid_body", "Send one complete JSON request body.", "body")
        return raw

    def _handle_error(self, exc):
        from .commercial_sessions import CommercialIdentityRefusal
        if isinstance(exc, (APRefusal, WireRefusal, CommercialIdentityRefusal)):
            receipt = None
            if getattr(exc, "receipt_id", None) is not None:
                receipt = {"receiptId": exc.receipt_id, "replayed": exc.replayed, "effectApplied": exc.effect_applied}
            self._error(exc.status, exc.code, exc.message, exc.target, receipt=receipt)
        elif isinstance(exc, WorkspaceModeError):
            self._error(503, "workspace_mode_unavailable", "A verified in-memory commercial practice workspace is required.")
        else:
            self._error(500, "practice_request_failed", "This commercial request could not be completed. Refresh and review the current records.")

    def do_GET(self):
        try:
            with self.server.cipher_lock:
                path, query = self._boundary()
                if path.startswith(API_PREFIX):
                    self._read_api(path.removeprefix(API_PREFIX), query)
                elif path.startswith("/api"):
                    raise APRefusal(404, "route_not_found", "This commercial route is unavailable.")
                else:
                    self._query(query, frozenset())
                    self._static(path)
        except Exception as exc:
            self._handle_error(exc)

    do_HEAD = do_GET

    def _read_api(self, route, query):
        if route in ("session", "personas"):
            self._query(query, frozenset())
            if route == "personas":
                self._json(200, {**PROVENANCE, "value": self.server.sessions.personas()})
            else:
                session = self._session() or self.server.sessions.anonymous()
                self._json(200, self.server.sessions.dto(session), cookie=session.cookie_token)
            return
        if route in COLLECTIONS:
            values = collection_query(route, query)
            params = {"top": int(values.pop("top", "50"))}
            params.update({"project_id" if key == "projectId" else key: value for key, value in values.items()})
            authority = self._authenticated(self._session())
            self._json(200, self.server.contract.read(authority.person_id, route, **params))
            return
        match = next(((pattern.fullmatch(route), method) for pattern, method in _DETAILS if pattern.fullmatch(route)), None)
        if match is None:
            raise APRefusal(404, "route_not_found", "This commercial route is unavailable.")
        self._query(query, frozenset())
        authority = self._authenticated(self._session())
        resource, method = match
        result = getattr(self.server.contract, method)(authority.person_id, resource[1])
        self._json(200, result, etag=result.get("version"))

    def do_POST(self):
        try:
            with self.server.cipher_lock:
                path, query = self._boundary(unsafe=True)
                self._query(query, frozenset())
                if not path.startswith(API_PREFIX):
                    raise APRefusal(404, "route_not_found", "This commercial route is unavailable.")
                route = path.removeprefix(API_PREFIX)
                definition = None
                if route not in ("session", "session/logout"):
                    definition, resource_id, is_preflight = resolve_action_route(route)
                session = self._session()
                if session is None:
                    raise APRefusal(401, "session_required", "Start a commercial practice session.", "session")
                if not self.server.sessions.validate_csrf(session, self._one_header("X-CSRF-Token")):
                    raise APRefusal(403, "csrf_refused", "Refresh this commercial session before continuing.", "session")
                if definition is None:
                    body = parse_json(self._raw_body())
                    expected = {"personaId"} if route == "session" else set()
                    if set(body) != expected:
                        raise APRefusal(422, "invalid_body", "Use the fixed commercial session fields.", "body")
                    selected = (self.server.sessions.select(session, body["personaId"]) if route == "session"
                                else self.server.sessions.logout(session))
                    self._json(200, self.server.sessions.dto(selected), cookie=selected.cookie_token)
                    return
                self._authenticated(session)
                body = decode_action_body(definition.action, self._raw_body(), effect=not is_preflight)
                if is_preflight:
                    authority = self._authenticated(session)
                    result = self.server.preflight.review(authority.person_id, definition.action, resource_id, body)
                else:
                    key = self._one_header("Repeatability-Request-ID", required=True)
                    try:
                        if str(uuid.UUID(key)) != key.lower():
                            raise ValueError
                    except (ValueError, AttributeError):
                        raise APRefusal(422, "invalid_repeatability_key", "Use a UUID for this commercial request.", "Repeatability-Request-ID") from None
                    version = self._one_header("If-Match", required=True)
                    if not re.fullmatch(r'"[A-Za-z0-9_.:-]{1,256}"', version):
                        raise APRefusal(422, "invalid_record_version", "Use the quoted record version from the review.", "If-Match")
                    authority = self._authenticated(session)
                    result = self.server.actions.run(authority.person_id, definition.action, resource_id, body,
                                                     repeatability_key=key, if_match=version[1:-1])
                self._json(200, {**PROVENANCE, **result})
        except Exception as exc:
            self._handle_error(exc)

    def _static(self, path):
        root = self.server.webroot
        relative = path.lstrip("/") or "commercial-practice.html"
        try:
            candidate = (root / relative).resolve()
            candidate.relative_to(root)
            if not candidate.is_file() and "." not in path and not path.startswith("/assets/"):
                candidate = (root / "commercial-practice.html").resolve()
            candidate.relative_to(root)
            mime = MIME_TYPES.get(candidate.suffix)
            if not candidate.is_file() or not mime:
                self._error(404, "web_build_missing", "Build the Fluent commercial practice app in apps/cipher/web before opening this page.")
                return
            payload = candidate.read_bytes()
            if candidate.suffix == ".html":
                nonce = secrets.token_urlsafe(24)
                self._respond(200, payload.replace(b"__CIPHER_STYLE_NONCE__", nonce.encode()), mime, nonce=nonce)
            else:
                hashed = re.search(r"-[A-Za-z0-9_-]{8,}\.", candidate.name)
                self._respond(200, payload, mime, cache="public, max-age=31536000, immutable" if hashed else "no-cache")
        except (OSError, ValueError, RuntimeError):
            self._error(404, "route_not_found", "This commercial resource is unavailable.")


def make_commercial_practice_server(*, port=8768, webroot: Path | None = None) -> CommercialPracticeHTTPServer:
    """No host, file database, actor, credentials, mode or provider selection."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Use a port from 0 to 65535.")
    return CommercialPracticeHTTPServer(port, DEFAULT_WEBROOT if webroot is None else Path(webroot))


def serve_commercial_practice(*, port=8768):
    server = make_commercial_practice_server(port=port)
    print(f"Cipher Fluent commercial practice: http://127.0.0.1:{server.server_address[1]} (synthetic people and records)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    serve_commercial_practice(port=parser.parse_args().port)
