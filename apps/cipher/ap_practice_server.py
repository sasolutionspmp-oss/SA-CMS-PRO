"""Isolated human AP practice API and Fluent host on the loopback interface.

The server owns fresh synthetic records and registered practice people. It has
no selectable workspace, production identity, provider, or old console routes.
The existing read-only practice server remains a separate application.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

from .core.db import WorkspaceModeError
from .practice_server import MIME_TYPES


API_PREFIX = "/api/ap-practice/v1/"
COOKIE_NAME = "cipher_ap_practice"
DEFAULT_WEBROOT = Path(__file__).parent / "web" / "dist-ap"
MAX_BODY_BYTES = 16_384
_RESOURCE = r"([A-Za-z0-9_-]{1,128})"
_ACTION_ROUTES = (
    (re.compile(r"^bills/" + _RESOURCE + r"/request-approval(:preflight)?$"), "bill.requestApproval"),
    (re.compile(r"^approvals/" + _RESOURCE + r"/approve(:preflight)?$"), "bill.approve"),
    (re.compile(r"^bills/" + _RESOURCE + r"/post(:preflight)?$"), "bill.post"),
)
_INTAKE_ACTION_ROUTES = (
    (re.compile(r"^commitments/" + _RESOURCE + r"/prepare-bill(:preflight)?$"), "bill.prepare"),
    (re.compile(r"^commitments/" + _RESOURCE + r"/receive-invoice(:preflight)?$"), "invoice.receive"),
    (re.compile(r"^invoices/" + _RESOURCE + r"/compute-match(:preflight)?$"), "invoice.computeMatch"),
    (re.compile(r"^invoices/" + _RESOURCE + r"/request-match-approval(:preflight)?$"), "invoice.requestMatchApproval"),
    (re.compile(r"^match-approvals/" + _RESOURCE + r"/approve(:preflight)?$"), "invoice.approveMatch"),
    (re.compile(r"^match-approvals/" + _RESOURCE + r"/execute(:preflight)?$"), "invoice.executeMatch"),
)
_INTAKE_BODY_FIELDS = {
    "bill.prepare": frozenset(("periodId", "installed")),
    "invoice.receive": frozenset(("invoiceNumber", "invoiceDate", "amountCents", "evidenceRevisionId")),
    "invoice.computeMatch": frozenset(),
    "invoice.requestMatchApproval": frozenset(),
    "invoice.approveMatch": frozenset(),
    "invoice.executeMatch": frozenset(),
}
_MAX_CENTS = 9_007_199_254_740_991
_READ_PARAMETERS = {
    "projects": frozenset(("top", "cursor", "search")),
    "commitments": frozenset(("projectId", "top", "cursor")),
    "bills": frozenset(("projectId", "status", "search", "top", "cursor")),
    "approvals": frozenset(("projectId", "status", "top", "cursor")),
    "posting-queue": frozenset(("projectId", "ready", "top", "cursor")),
}
_INTAKE_READ_PARAMETERS = {
    "invoices": frozenset(("projectId", "status", "search", "top", "cursor")),
    "invoice-evidence": frozenset(("projectId", "status", "search", "top", "cursor")),
    "match-approvals": frozenset(("projectId", "status", "search", "top", "cursor")),
}


class APPracticeHTTPServer(ThreadingHTTPServer):
    """Owns one writable in-memory practice fixture and volatile sessions."""

    def __init__(self, port: int, webroot: Path):
        from .ap_contract import APContract
        from .ap_preflight import APPreflight
        from .ap_practice_fixture import make_ap_practice_fixture
        from .ap_sessions import APPracticeSessions
        from .ap_actions import APActionRunner
        from .ap_intake_contract import APIntakeContract
        from .ap_intake_preflight import APIntakePreflight
        from .ap_intake_actions import APIntakeActionRunner

        self.webroot = webroot.resolve()
        self.cipher = make_ap_practice_fixture()
        self.cipher_lock = threading.RLock()
        try:
            self.require_practice()
            secret = secrets.token_bytes(32)
            self.contract = APContract(self.cipher, secret=secret)
            self.preflight = APPreflight(self.cipher, self.contract, secret=secret)
            self.actions = APActionRunner(self.cipher, self.contract, self.preflight)
            self.cipher.register_plugin("ap_action_sources", self.actions)
            self.intake_contract = APIntakeContract(self.cipher, self.contract, secret=secret)
            self.intake_preflight = APIntakePreflight(self.cipher, self.intake_contract, secret=secret)
            self.intake_actions = APIntakeActionRunner(self.cipher, self.intake_contract, self.intake_preflight)
            self.cipher.register_plugin("ap_intake_sources", self.intake_actions)
            self.sessions = APPracticeSessions(self.cipher)
            super().__init__(("127.0.0.1", port), APPracticeHandler)
        except BaseException:
            self.cipher.db.close()
            raise

    def require_practice(self):
        """Check the immutable declaration and physical memory boundary."""
        self.cipher.db.require_practice_mode()
        if not self.cipher.db.in_memory or any(
            row[2] for row in self.cipher.db.conn.execute("PRAGMA database_list")
        ):
            raise WorkspaceModeError("The AP practice server requires an in-memory workspace.")

    def server_close(self):
        try:
            super().server_close()
        finally:
            self.cipher.db.close()


class APPracticeHandler(BaseHTTPRequestHandler):
    server: APPracticeHTTPServer
    server_version = "CipherAPPractice"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass  # Never log URLs, credentials, headers, bodies, or tokens.

    def _respond(self, status, payload: bytes, content_type, *, nonce=None, cache="no-store", allow=None, cookie=None, etag=None):
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
        if cookie:
            # This is an HTTP loopback development cookie, not an Entra cookie.
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={cookie}; HttpOnly; SameSite=Strict; Path=/")
        if etag:
            self.send_header("ETag", '"' + etag + '"')
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            # Navigation or a lost response does not undo an already committed
            # action. Its same-person repeatability receipt supports a retry.
            self.close_connection = True

    def _json(self, status, data, **kwargs):
        self._respond(status, json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(),
                      "application/json; charset=utf-8", **kwargs)

    def _error(self, status, code, message, target=None, *, receipt=None, **kwargs):
        value = {"contractVersion": "cipher.ap-practice.v1", "mode": "practice",
                 "synthetic": True, "currency": "USD",
                 "error": {"code": code, "target": target, "message": message, "fix": None, "details": None}}
        if receipt is not None:
            value.update(receipt)
        self._json(status, value, **kwargs)

    def _one_header(self, name, *, required=False):
        from .ap_contract import APRefusal
        values = self.headers.get_all(name, [])
        if len(values) > 1 or (required and len(values) != 1):
            raise APRefusal(400, "invalid_headers", "Use each required request header exactly once.", name)
        return values[0] if values else None

    def _same_origin(self, *, unsafe=False):
        from .ap_contract import APRefusal
        host = self._one_header("Host", required=True)
        port = self.server.server_address[1]
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            raise APRefusal(403, "host_refused", "Open this practice server on its local address.")
        origin = self._one_header("Origin")
        if (unsafe and origin is None) or (origin is not None and origin != f"http://{host}"):
            raise APRefusal(403, "origin_refused", "Use the same local origin for this practice request.")
        fetch_site = self._one_header("Sec-Fetch-Site")
        if fetch_site not in (None, "same-origin", "none"):
            raise APRefusal(403, "origin_refused", "Use the same local origin for this practice request.")

    def _url(self):
        from .ap_contract import APRefusal
        if len(self.path) > 4096 or re.search(r"%(?![0-9A-Fa-f]{2})", self.path):
            raise APRefusal(400, "invalid_url", "Use a valid local practice URL.")
        try:
            url = urlsplit(self.path)
            path = unquote(url.path, errors="strict")
        except (ValueError, UnicodeError):
            raise APRefusal(400, "invalid_url", "Use a valid local practice URL.") from None
        if url.scheme or url.netloc or url.fragment or "\x00" in path or "\\" in path or ".." in path.split("/"):
            raise APRefusal(400, "invalid_url", "Use a local practice URL without parent paths.")
        return path, url.query

    def _query(self, query, allowed):
        from .ap_contract import APRefusal
        try:
            parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
            if parsed.keys() - allowed or any(len(values) != 1 for values in parsed.values()):
                raise ValueError
            values = {key: items[0] for key, items in parsed.items()}
            if any(not value or len(value) > 2048 for value in values.values()):
                raise ValueError
            if "top" in values and not re.fullmatch(r"[0-9]{1,3}", values["top"]):
                raise ValueError
            top = int(values.get("top", "50"))
            if not 1 <= top <= 100:
                raise ValueError
            if "ready" in values and values["ready"] not in ("true", "false"):
                raise ValueError
        except ValueError:
            raise APRefusal(400, "invalid_query", "Use each supported filter once and a page size from 1 to 100.", "query") from None
        result = {"top": top}
        for wire, key in (("projectId", "project_id"), ("status", "status"), ("search", "search"), ("cursor", "cursor")):
            if wire in values:
                result[key] = values[wire]
        if "ready" in values:
            result["ready"] = values["ready"] == "true"
        return result

    def _session(self):
        from .ap_contract import APRefusal
        cookie = self._one_header("Cookie")
        token = None
        if cookie:
            values = []
            for part in cookie.split(";"):
                key, separator, value = part.strip().partition("=")
                if key == COOKIE_NAME:
                    if not separator or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", value):
                        raise APRefusal(401, "session_required", "Start a practice session.", "session")
                    values.append(value)
            if len(values) > 1:
                raise APRefusal(400, "invalid_headers", "Use one practice session cookie.", "Cookie")
            token = values[0] if values else None
        return self.server.sessions.get(token)

    def _authenticated(self, session):
        return self.server.sessions.require(session)

    def _body(self, *, allowed, required=(), intake_action=None):
        from .ap_contract import APRefusal
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
            raise APRefusal(413, "body_too_large", "Keep the practice request body within 16 KB.", "body")
        if not size:
            raise APRefusal(422, "invalid_body", "Send a JSON object with the supported fields.", "body")

        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError
                value[key] = item
            return value

        try:
            payload = self.rfile.read(size)
            if len(payload) != size:
                raise ValueError
            value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if type(value) is not dict or value.keys() - allowed or set(required) - value.keys():
                raise ValueError
            if intake_action is None:
                # Preserve the original API's string-only body contract. New
                # integer/array fields are accepted only on fixed intake routes.
                if any(type(item) is not str or (not item and key != "reason") or len(item) > 2048
                       for key, item in value.items()):
                    raise ValueError
            else:
                self._intake_body(value, intake_action)
        except (ValueError, UnicodeError, RecursionError, OSError):
            raise APRefusal(422, "invalid_body", "Send a JSON object with each supported field once.", "body") from None
        return value

    @staticmethod
    def _intake_body(body, action):
        """Validate the bounded wire shape without accepting caller authority."""
        def reference(value):
            return type(value) is str and re.fullmatch(_RESOURCE, value) is not None

        fingerprint = body.get("fingerprint")
        if "fingerprint" in body and (type(fingerprint) is not str or not fingerprint or len(fingerprint) > 2048):
            raise ValueError
        if action == "bill.prepare":
            if not reference(body["periodId"]):
                raise ValueError
            installed = body["installed"]
            if type(installed) is not list or not 1 <= len(installed) <= 100:
                raise ValueError
            seen = set()
            for row in installed:
                if type(row) is not dict or row.keys() != {"sovLineId", "cumulativeInstalledCents"}:
                    raise ValueError
                sov_id, cents = row["sovLineId"], row["cumulativeInstalledCents"]
                if not reference(sov_id) or sov_id in seen or type(cents) is not int or not 0 <= cents <= _MAX_CENTS:
                    raise ValueError
                seen.add(sov_id)
        elif action == "invoice.receive":
            number, date, amount = body["invoiceNumber"], body["invoiceDate"], body["amountCents"]
            if (type(number) is not str or not number.strip() or len(number) > 64
                    or any(ord(char) < 32 for char in number)
                    or type(date) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date) is None
                    or type(amount) is not int or not 0 < amount <= _MAX_CENTS
                    or not reference(body["evidenceRevisionId"])):
                raise ValueError
        elif action not in _INTAKE_BODY_FIELDS:
            raise ValueError

    def _boundary(self, *, unsafe=False):
        self._same_origin(unsafe=unsafe)
        self.server.require_practice()
        return self._url()

    def _handle_error(self, exc):
        from .ap_contract import APRefusal
        from .ap_sessions import APIdentityRefusal
        if isinstance(exc, (APRefusal, APIdentityRefusal)):
            receipt = None
            if isinstance(exc, APRefusal) and getattr(exc, "receipt_id", None) is not None:
                receipt = {"receiptId": exc.receipt_id, "replayed": exc.replayed,
                           "effectApplied": exc.effect_applied}
            self._error(exc.status, exc.code, exc.message, exc.target, receipt=receipt)
        elif isinstance(exc, WorkspaceModeError):
            self._error(503, "workspace_mode_unavailable", "A verified in-memory practice workspace is required.")
        else:
            self._error(500, "practice_request_failed", "The practice request could not be completed. Refresh and review the current records.")

    def do_GET(self):
        try:
            with self.server.cipher_lock:
                path, query = self._boundary()
                if path.startswith(API_PREFIX):
                    self._read_api(path.removeprefix(API_PREFIX), query)
                elif path.startswith("/api"):
                    from .ap_contract import APRefusal
                    raise APRefusal(404, "route_not_found", "This practice route is not available.")
                else:
                    if query:
                        self._query(query, frozenset())
                    self._static(path)
        except Exception as exc:
            self._handle_error(exc)

    do_HEAD = do_GET

    def _read_api(self, route, query):
        from .ap_contract import APRefusal
        if route in ("session", "personas"):
            self._query(query, frozenset())
            if route == "personas":
                self._json(200, {"contractVersion": "cipher.ap-practice.v1", "mode": "practice",
                                 "synthetic": True, "currency": "USD", "value": self.server.sessions.personas()})
                return
            session = self._session()
            if session is None:
                session = self.server.sessions.anonymous()
            self._json(200, self.server.sessions.dto(session), cookie=session.cookie_token)
            return
        if route in _READ_PARAMETERS:
            params = self._query(query, _READ_PARAMETERS[route])
            authority = self._authenticated(self._session())
            if route == "posting-queue":
                result = self.server.contract.posting_queue(authority.person_id, **params)
            else:
                result = self.server.contract.read(authority.person_id, route, **params)
            self._json(200, result)
            return
        if route in _INTAKE_READ_PARAMETERS:
            params = self._query(query, _INTAKE_READ_PARAMETERS[route])
            authority = self._authenticated(self._session())
            result = self.server.intake_contract.read(authority.person_id, route, **params)
            self._json(200, result)
            return
        bill = re.fullmatch(r"bills/" + _RESOURCE, route)
        packet = re.fullmatch(r"approvals/" + _RESOURCE + r"/packet", route)
        preparation = re.fullmatch(r"commitments/" + _RESOURCE + r"/preparation", route)
        invoice = re.fullmatch(r"invoices/" + _RESOURCE, route)
        match_packet = re.fullmatch(r"match-approvals/" + _RESOURCE + r"/packet", route)
        if bill or packet or preparation or invoice or match_packet:
            self._query(query, frozenset())
            authority = self._authenticated(self._session())
            if bill:
                result = self.server.contract.detail(authority.person_id, bill[1])
            elif packet:
                result = self.server.contract.packet(authority.person_id, packet[1])
            elif preparation:
                result = self.server.intake_contract.preparation(authority.person_id, preparation[1])
            elif invoice:
                result = self.server.intake_contract.invoice(authority.person_id, invoice[1])
            else:
                result = self.server.intake_contract.packet(authority.person_id, match_packet[1])
            self._json(200, result, etag=result.get("version"))
            return
        raise APRefusal(404, "route_not_found", "This practice route is not available.")

    def do_POST(self):
        from .ap_contract import APRefusal
        try:
            with self.server.cipher_lock:
                path, query = self._boundary(unsafe=True)
                self._query(query, frozenset())
                if not path.startswith(API_PREFIX):
                    raise APRefusal(404, "route_not_found", "This practice route is not available.")
                route = path.removeprefix(API_PREFIX)
                match = next(((pattern.fullmatch(route), action) for pattern, action in (*_ACTION_ROUTES, *_INTAKE_ACTION_ROUTES)
                              if pattern.fullmatch(route)), None)
                if route not in ("session", "session/logout") and match is None:
                    raise APRefusal(404, "route_not_found", "This practice route is not available.")
                session = self._session()
                if session is None:
                    raise APRefusal(401, "session_required", "Start a practice session.", "session")
                csrf = self._one_header("X-CSRF-Token")
                if not self.server.sessions.validate_csrf(session, csrf):
                    raise APRefusal(403, "csrf_refused", "Refresh the practice session before continuing.", "session")
                if route == "session":
                    body = self._body(allowed={"personaId"}, required={"personaId"})
                    selected = self.server.sessions.select(session, body["personaId"])
                    self._json(200, self.server.sessions.dto(selected), cookie=selected.cookie_token)
                    return
                if route == "session/logout":
                    self._body(allowed=set())
                    anonymous = self.server.sessions.logout(session)
                    self._json(200, self.server.sessions.dto(anonymous), cookie=anonymous.cookie_token)
                    return
                authority = self._authenticated(session)
                route_match, action = match
                resource_id, is_preflight = route_match[1], route_match[2] is not None
                is_intake = action in _INTAKE_BODY_FIELDS
                fields = set(_INTAKE_BODY_FIELDS[action]) if is_intake else {"periodId", "reason"} if action == "bill.post" else set()
                if not is_preflight:
                    fields.add("fingerprint")
                required = set(_INTAKE_BODY_FIELDS[action]) if is_intake else {"periodId", "reason"} if action == "bill.post" else set()
                if not is_preflight:
                    required.add("fingerprint")
                body = self._body(allowed=fields, required=required, intake_action=action if is_intake else None)
                if is_preflight:
                    authority = self._authenticated(session)
                    preflight = self.server.intake_preflight if is_intake else self.server.preflight
                    result = preflight.review(authority.person_id, action, resource_id, body)
                else:
                    repeatability_key = self._one_header("Repeatability-Request-ID", required=True)
                    try:
                        if str(uuid.UUID(repeatability_key)) != repeatability_key.lower():
                            raise ValueError
                    except (ValueError, AttributeError):
                        raise APRefusal(422, "invalid_repeatability_key", "Use a UUID for this action request.", "Repeatability-Request-ID") from None
                    if_match = self._one_header("If-Match", required=True)
                    if not re.fullmatch(r'"[A-Za-z0-9_.:-]{1,256}"', if_match):
                        raise APRefusal(422, "invalid_record_version", "Use the quoted record version from the current review.", "If-Match")
                    authority = self._authenticated(session)
                    runner = self.server.intake_actions if is_intake else self.server.actions
                    result = runner.run(authority.person_id, action, resource_id, body,
                                        repeatability_key=repeatability_key, if_match=if_match[1:-1])
                self._json(200, {"contractVersion": "cipher.ap-practice.v1", "mode": "practice",
                                 "synthetic": True, "currency": "USD", **result})
        except Exception as exc:
            self._handle_error(exc)

    def _static(self, path):
        root = self.server.webroot
        relative = path.lstrip("/") or "ap-practice.html"
        try:
            candidate = (root / relative).resolve()
            candidate.relative_to(root)
            if not candidate.is_file() and "." not in path and not path.startswith("/assets/"):
                candidate = (root / "ap-practice.html").resolve()
            candidate.relative_to(root)
            mime = MIME_TYPES.get(candidate.suffix)
            if not candidate.is_file() or not mime:
                self._error(404, "web_build_missing", "Build the Fluent AP practice app in apps/cipher/web before opening this page.")
                return
            payload = candidate.read_bytes()
            if candidate.suffix == ".html":
                nonce = secrets.token_urlsafe(24)
                payload = payload.replace(b"__CIPHER_STYLE_NONCE__", nonce.encode())
                self._respond(200, payload, mime, nonce=nonce)
            else:
                hashed = re.search(r"-[A-Za-z0-9_-]{8,}\.", candidate.name)
                self._respond(200, payload, mime, cache="public, max-age=31536000, immutable" if hashed else "no-cache")
        except (OSError, ValueError, RuntimeError):
            self._error(404, "route_not_found", "This practice resource is not available.")

    def _method_refused(self):
        try:
            with self.server.cipher_lock:
                self._boundary(unsafe=self.command not in ("GET", "HEAD"))
            self._error(405, "method_refused", "Use an explicitly supported practice route.", allow="GET, HEAD, POST")
        except Exception as exc:
            self._handle_error(exc)

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = _method_refused


def make_ap_practice_server(*, port=8767, webroot: Path | None = None) -> APPracticeHTTPServer:
    """No host, file database, actor, credentials, mode, or provider selection."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Use a port from 0 to 65535.")
    return APPracticeHTTPServer(port, DEFAULT_WEBROOT if webroot is None else Path(webroot))


def serve_ap_practice(*, port=8767):
    server = make_ap_practice_server(port=port)
    print(f"Cipher Fluent AP practice: http://127.0.0.1:{server.server_address[1]} (synthetic people and records)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
