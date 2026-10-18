#!/usr/bin/env python3
"""Prepared UNRUN: explicit loopback FLD02 HTTP diagnostic, Python standard library.

This is a private plaintext operator artifact, not the encrypted browser vault.
No native application imports, login, token authentication, background work or
financial routes. Never run this source as part of static preparation/review.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import hmac
import http.client
import http.cookiejar
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCHEMA = "cipher.api.v1"
JOURNAL_SCHEMA = "cipher.fld02.http-diagnostic.journal.v1"
MODULE = "cipher_aec.field_offline.api."
SESSION = "cipher_aec.api.v1.session"
# Exact frozen API surface. Only the explicitly supported subset below is callable.
ROUTES = {
    "register_device": ("POST", ("company", "project", "operation_id", "device_id", "label")),
    "revoke_device": ("POST", ("company", "project", "operation_id", "device_id", "expected_version", "reason")),
    "stage_capture": ("POST", ("company", "project", "operation_id", "envelope")),
    "get_capture": ("GET", ("company", "project", "capture_id")),
    "inspect_capture": ("GET", ("company", "project", "capture_id")),
    "apply_capture": ("POST", ("company", "project", "operation_id", "capture_id", "expected_version")),
    "discard_capture": ("POST", ("company", "project", "operation_id", "capture_id", "expected_version", "reason")),
    "resolve_capture": ("POST", ("company", "project", "operation_id", "capture_id", "expected_version", "replacement_envelope", "reason")),
}
SUPPORTED = frozenset({"stage_capture", "get_capture", "inspect_capture", "apply_capture", "discard_capture"})
MAX_ENVELOPE = 262144
MAX_RESPONSE = 4 * 1024 * 1024
MAX_JOURNAL = 32 * 1024 * 1024
# A single deliberate retry is permitted, always using the original saved bytes.
MAX_ATTEMPTS = 2
FROZEN_SCHEMA_SHA256 = "99e32521ba518224b327cdeb0643e5d91342406a41ee8e24ec617953d4602d84"
SECRET_KEYS = {"csrf_token", "x-frappe-csrf-token", "cookie", "cookies", "set-cookie", "authorization", "password", "passwd", "sid", "api_key", "api_secret", "token"}


class Refusal(Exception):
    """A fixed, credential-free operator diagnostic."""


class RemoteFailure(Refusal):
    def __init__(self, status, code="untrusted_response"):
        self.status = status
        self.code = code if type(code) is str and re.fullmatch(r"[a-z_]{1,80}", code) else "untrusted_response"
        super().__init__("HTTP request did not yield a verified result; inspect/recover before any new command.")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest(value):
    return sha(canonical(value))


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(value):
    if type(value) is not str or len(value) > 40:
        raise Refusal("Use an ISO timestamp with an explicit UTC offset.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result
    except ValueError:
        raise Refusal("Use an ISO timestamp with an explicit UTC offset.") from None


def uuid4(value):
    try:
        parsed = uuid.UUID(value)
        if type(value) is not str or str(parsed) != value or parsed.version != 4:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise Refusal("Use an unchanged canonical UUID version 4.") from None
    return value


def checksum(value):
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise Refusal("An exact SHA-256 value is required.")
    return value


def text(value, maximum=140, blank=False):
    if type(value) is not str or len(value) > maximum or "\0" in value or (not blank and not value.strip()):
        raise Refusal("A bounded declared text value is required.")
    return value


def reject_secrets(value):
    if type(value) is dict:
        if any(k.lower() in SECRET_KEYS for k in value):
            raise Refusal("Authentication or secret fields cannot enter a journal or capture.")
        for child in value.values():
            reject_secrets(child)
    elif type(value) is list:
        for child in value:
            reject_secrets(child)


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refusal("Duplicate JSON keys are not accepted.")
            result[key] = value
        return result
    def constant(_):
        raise Refusal("Use finite standard JSON values.")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal("The bounded JSON document could not be parsed.") from None


def private_read(path, maximum):
    """Read a regular, owner-only, nonsymlink file without printing its contents."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise Refusal("A private regular file owned by this operator is required (mode 0600 or stricter).")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise Refusal("The local file exceeds its bounded size.")
        return raw
    finally:
        os.close(fd)


def origin(value):
    try:
        if type(value) is not str or value != value.strip() or any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
            raise ValueError
        url = urllib.parse.urlsplit(value)
        hostname = url.hostname or ""
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        local_name = re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*localhost", hostname) is not None
        port = url.port
        if url.scheme not in {"http", "https"} or not (address.is_loopback if address is not None else local_name) or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError
        host = ("[" + address.compressed + "]" if address.version == 6 else address.compressed) if address is not None else hostname
        return url.scheme + "://" + host + (":" + str(port) if port is not None else "")
    except ValueError:
        raise Refusal("Use an HTTP(S) loopback IP or localhost origin without credentials, path, query or fragment.") from None


def loopback_socket(hostname, port, timeout):
    """Resolve only admitted local names, reject mixed answers, pin numeric peers.

    Each connection resolves once. HTTP never resolves the name again between
    checking its answers and connecting; original Host/cookie/TLS names remain.
    """
    checked = origin("http://" + ("[" + hostname + "]" if ":" in hostname else hostname) + ":" + str(port))
    if urllib.parse.urlsplit(checked).hostname != hostname:
        raise Refusal("The connection hostname differs from its admitted origin.")
    answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    if not answers or any(not ipaddress.ip_address(answer[4][0]).is_loopback for answer in answers):
        raise Refusal("Every resolved localhost address must be loopback.")
    for family, kind, proto, _, sockaddr in answers:
        connection = socket.socket(family, kind, proto)
        try:
            connection.settimeout(timeout)
            connection.connect(sockaddr)
            if not ipaddress.ip_address(connection.getpeername()[0]).is_loopback:
                raise Refusal("The connected peer is not loopback.")
            return connection
        except OSError:
            connection.close()
        except Exception:
            connection.close()
            raise
    raise RemoteFailure(0, "loopback_unavailable")


class LoopbackHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        if self._tunnel_host:
            raise Refusal("HTTP tunnels are not supported.")
        self.sock = loopback_socket(self.host, self.port, self.timeout)


class LoopbackHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._tunnel_host:
            raise Refusal("HTTP tunnels are not supported.")
        self.sock = loopback_socket(self.host, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
        except Exception:
            self.sock.close()
            raise


class LoopbackHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(LoopbackHTTPConnection, request)


class LoopbackHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(LoopbackHTTPSConnection, request, context=self._context)


@contextmanager
def locked_journal(path, *, creating=False):
    path = Path(path).absolute()
    parent = path.parent
    if creating:
        parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Refusal("The journal must be inside an operator-owned private 0700 directory.")
    # A process lock covers local transitions and HTTP, preventing two driver
    # processes from creating fresh operations around an unresolved request.
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        lock_info = os.fstat(fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid() or lock_info.st_mode & 0o077:
            raise Refusal("The journal lock is not private.")
        fcntl.flock(fd, fcntl.LOCK_EX)
        if creating:
            if path.exists() or path.is_symlink():
                raise Refusal("Init never replaces an existing journal.")
            data = None
        else:
            data = parse_json(private_read(path, MAX_JOURNAL))
            verify_journal(data)
        yield path, data
    finally:
        os.close(fd)


def save(path, data):
    """Fail closed: same-directory 0600 temp, fsync, atomic replace, directory fsync."""
    reject_secrets(data)
    encoded = (canonical(data) + "\n").encode("utf-8")
    if len(encoded) > MAX_JOURNAL:
        raise Refusal("Journal quota exceeded; no request was authorized by this write.")
    fd, temporary = tempfile.mkstemp(prefix=".fld02-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_journal(journal):
    if type(journal) is not dict or journal.get("schema") != JOURNAL_SCHEMA:
        raise Refusal("Use this driver's exact journal format.")
    reject_secrets(journal)
    profile = journal["profile"]
    if origin(profile["origin"]) != profile["origin"]:
        raise Refusal("The journal origin changed.")
    uuid4(profile["device_id"])
    timestamp(profile["expires_at"])
    for key in ("company", "project", "person", "user"):
        text(profile[key])
    for capture_id, record in journal["captures"].items():
        uuid4(capture_id)
        checksum(record["envelope_sha256"])
        sealed = record.get("sealed_json")
        if sealed is not None:
            envelope = parse_json(sealed)
            if canonical(envelope) != sealed or sha(sealed) != record["envelope_sha256"] or envelope["capture_id"] != capture_id:
                raise Refusal("The sealed capture bytes or UUID changed; no sync is permitted.")
            match_profile(envelope, profile)
    for operation_id, request in journal["requests"].items():
        uuid4(operation_id)
        checksum(request["body_sha256"])
        if request["route"] not in SUPPORTED or ROUTES[request["route"]][0] != "POST":
            raise Refusal("The journal contains an unsupported request.")
        body = request.get("body_json")
        if body is not None:
            values = parse_json(body)
            if canonical(values) != body or sha(body) != request["body_sha256"] or values["operation_id"] != operation_id:
                raise Refusal("A saved UUID request payload changed; no sync is permitted.")
            exact_route(request["route"], values)
            if (values["company"], values["project"]) != (profile["company"], profile["project"]):
                raise Refusal("The saved operation scope changed.")
            if request["route"] == "stage_capture":
                capture_id = values["envelope"]["capture_id"]
                if digest(values["envelope"]) != journal["captures"][capture_id]["envelope_sha256"] or operation_id == capture_id:
                    raise Refusal("The immutable staging payload changed.")
            elif values["capture_id"] != request["capture_id"]:
                raise Refusal("The saved operation target changed.")
            if request["route"] == "apply_capture" and operation_id != values["capture_id"]:
                raise Refusal("Apply must retain its original capture UUID.")
        if request["state"] not in {"prepared", "unknown", "retry_eligible", "acknowledged", "effect_observed", "committed", "locally_abandoned"} or type(request["attempts"]) is not int or not 0 <= request["attempts"] <= MAX_ATTEMPTS:
            raise Refusal("The journal operation state is unsupported.")


def schema_validate(value, schema, definitions):
    """Small fail-closed validator for the bundled frozen *input* schema only."""
    supported = {"$ref", "type", "const", "enum", "properties", "required", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "format", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "description", "title", "x-max-json-bytes"}
    if set(schema) - supported:
        raise Refusal("The bundled input schema uses an unsupported constraint.")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/$defs/") or reference.count("/") != 2:
            raise Refusal("Only local frozen input schema references are permitted.")
        schema_validate(value, definitions[reference.rsplit("/", 1)[1]], definitions)
    def accepts(child):
        try:
            schema_validate(value, child, definitions)
            return True
        except Refusal:
            return False
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise Refusal("The input differs from a frozen schema constant.")
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        raise Refusal("The input is outside its frozen schema choices.")
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}
    if "type" in schema:
        choices = schema["type"] if type(schema["type"]) is list else [schema["type"]]
        if not any(type(value) in (types[t] if type(types[t]) is tuple else (types[t],)) for t in choices):
            raise Refusal("The input has the wrong frozen schema type.")
    for child in schema.get("allOf", []):
        schema_validate(value, child, definitions)
    if "anyOf" in schema and not any(accepts(child) for child in schema["anyOf"]):
        raise Refusal("The input does not satisfy its frozen input alternatives.")
    if "oneOf" in schema and sum(accepts(child) for child in schema["oneOf"]) != 1:
        raise Refusal("The input does not satisfy exactly one frozen input alternative.")
    if "not" in schema and accepts(schema["not"]):
        raise Refusal("A forbidden input shape was supplied.")
    if "if" in schema:
        schema_validate(value, schema.get("then" if accepts(schema["if"]) else "else", {}), definitions)
    if type(value) is dict:
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value) or schema.get("additionalProperties") is False and set(value) - set(properties):
            raise Refusal("Supply exactly the frozen input fields.")
        for key in set(value) & set(properties):
            schema_validate(value[key], properties[key], definitions)
    if type(value) is list:
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", MAX_ENVELOPE):
            raise Refusal("The input list exceeds its frozen bounds.")
        if schema.get("uniqueItems") and len({canonical(item) for item in value}) != len(value):
            raise Refusal("The input list repeats an exact entry.")
        for item in value:
            schema_validate(item, schema.get("items", {}), definitions)
    if type(value) is str:
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", MAX_ENVELOPE) or "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise Refusal("The input text violates its frozen bounds or pattern.")
        if schema.get("format") == "date":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise Refusal("Use an exact ISO calendar date.") from None
        elif schema.get("format") == "date-time":
            timestamp(value)
        elif schema.get("format") == "uuid":
            try:
                if str(uuid.UUID(value)) != value:
                    raise ValueError
            except (ValueError, AttributeError):
                raise Refusal("Use an exact canonical UUID.") from None
        elif "format" in schema:
            raise Refusal("The bundled input format is unsupported.")
    if type(value) in {int, float}:
        if type(value) is float and not math.isfinite(value):
            raise Refusal("Use finite JSON values.")
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf) or "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"] or "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise Refusal("The input number violates its frozen bounds.")


def validate_frozen(value, definition):
    raw = Path(__file__).with_name("frozen-api-v1.schema.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SCHEMA_SHA256:
        raise Refusal("The frozen contract schema changed.")
    definitions = parse_json(raw)["$defs"]
    schema_validate(value, definitions[definition], definitions)


def validate_envelope(envelope):
    reject_secrets(envelope)
    nodes = 0
    def bounded(value, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 20000:
            raise Refusal("The capture exceeds its frozen structural budget.")
        if type(value) is dict:
            for key, child in value.items():
                bounded(key, depth + 1)
                bounded(child, depth + 1)
        elif type(value) is list:
            for child in value:
                bounded(child, depth + 1)
    bounded(envelope)
    if len(canonical(envelope).encode("utf-8")) > MAX_ENVELOPE:
        raise Refusal("The capture exceeds the 256 KiB canonical JSON budget.")
    validate_frozen(envelope, "FoEnvelope")
    uuid4(envelope["capture_id"])
    uuid4(envelope["device_id"])
    # Cross-field source uniqueness and positive quantities supplement JSON Schema.
    command = envelope["command"]
    source_lists = []
    if command["family"] == "daily":
        source_lists.append(command["definition"]["weather_sources"])
    else:
        for line in command["definition"]["lines"]:
            source_lists.append(line["sources"])
            if Decimal(line["quantity"]) <= 0:
                raise Refusal("Documentary quantities must be positive exact decimal strings.")
    events = set()
    for quantity in command["quantities"]:
        if quantity["original_event_id"] in events or Decimal(quantity["quantity"]) <= 0:
            raise Refusal("Use unique original quantity events and positive exact decimals.")
        events.add(quantity["original_event_id"])
        source_lists.append(quantity["sources"])
    for sources in source_lists:
        if len({(row["revision_id"], row["page"], row["locator"]) for row in sources}) != len(sources):
            raise Refusal("Each exact source locator may appear only once in its list.")


def match_profile(envelope, profile):
    if (envelope["company"], envelope["project"], envelope["actor_person"], envelope["actor_user"], envelope["device_id"]) != (profile["company"], profile["project"], profile["person"], profile["user"], profile["device_id"]):
        raise Refusal("The immutable capture belongs to another exact profile.")


def exact_route(route, values):
    if route not in SUPPORTED or set(values) != set(ROUTES[route][1]):
        raise Refusal("Only exact supported FLD02 route arguments are permitted.")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RemoteFailure(code, "redirect_refused")


class Client:
    def __init__(self, profile, credential_path):
        # Fixed KEY=value input, no shell sourcing, substitution, CLI/environment
        # secret values, password, API key, automatic sign-in or cookie persistence.
        if credential_path is None:
            raise Refusal("Supply a private credentials file for an existing session.")
        raw = private_read(credential_path, 16384).decode("utf-8")
        credentials = {}
        for line in raw.splitlines():
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise Refusal("Use the documented private credentials file format.")
            key, value = line.split("=", 1)
            if key in credentials:
                raise Refusal("Duplicate credential settings are refused.")
            credentials[key] = value
        if set(credentials) != {"COOKIE_JAR", "CSRF_TOKEN"}:
            raise Refusal("Credentials accept COOKIE_JAR and CSRF_TOKEN only.")
        if not credentials["CSRF_TOKEN"] or any(ch in credentials["CSRF_TOKEN"] for ch in "\r\n\0"):
            raise Refusal("The supplied current session CSRF value is invalid.")
        cookie_path = Path(credentials["COOKIE_JAR"])
        if not cookie_path.is_absolute():
            raise Refusal("COOKIE_JAR must name an absolute private file.")
        private_read(cookie_path, 65536)
        jar = http.cookiejar.MozillaCookieJar()
        # Parse the already-checked bytes, avoiding CookieJar's second path open.
        import io
        jar._really_load(io.StringIO(private_read(cookie_path, 65536).decode("utf-8")), str(cookie_path), False, False)
        self.profile = profile
        self.csrf = credentials["CSRF_TOKEN"]
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), LoopbackHTTPHandler(), LoopbackHTTPSHandler(), urllib.request.HTTPCookieProcessor(jar))
        session = self._request(SESSION, "GET", {})
        person = session.get("person")
        if session.get("authenticated") is not True or session.get("site_mode") != "synthetic" or session.get("user") != profile["user"] or type(person) is not dict or person.get("id") != profile["person"]:
            raise Refusal("The actual current synthetic session does not match this journal profile.")
        server_csrf = session.get("csrf_token")
        if type(server_csrf) is not str or not server_csrf or not hmac.compare_digest(server_csrf, self.csrf):
            raise Refusal("The supplied CSRF value differs from the current session endpoint.")
        # Only this in-memory value is used, never the session response in a journal.
        self.csrf = server_csrf

    def _request(self, method, verb, values, *, body_json=None, operation_id=None):
        url = self.profile["origin"] + "/api/method/" + method
        headers = {"Accept": "application/json", "User-Agent": "Cipher-FLD02-Prepared-Diagnostic/1"}
        body = None
        if verb == "GET":
            if values:
                url += "?" + urllib.parse.urlencode(values)
        else:
            body = body_json.encode("utf-8")
            headers.update({"Content-Type": "application/json; charset=utf-8", "X-Frappe-CSRF-Token": self.csrf, "Idempotency-Key": operation_id})
        request = urllib.request.Request(url, data=body, headers=headers, method=verb)
        try:
            response = self.opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            raise RemoteFailure(0, "transport_unknown") from None
        try:
            with response:
                status = response.status
                if response.geturl() != url or not 200 <= status < 600:
                    raise RemoteFailure(status)
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    raise RemoteFailure(status)
                raw = response.read(MAX_RESPONSE + 1)
        except (OSError, http.client.HTTPException):
            raise RemoteFailure(0, "transport_unknown") from None
        if len(raw) > MAX_RESPONSE:
            raise RemoteFailure(status, "response_limit")
        try:
            outer = parse_json(raw)
            # Frappe's message wrapping is normalized exactly once; bare domain
            # or recursively wrapped responses are not silently accepted.
            wrapped = outer["message"]
            if type(wrapped) is not dict or wrapped.get("schema") != SCHEMA or type(wrapped.get("meta")) is not dict or wrapped["meta"].get("api_version") != "v1" or wrapped.get("request_id") != wrapped["meta"].get("request_id"):
                raise KeyError
            uuid.UUID(wrapped["request_id"])
            if "error" in wrapped:
                error = wrapped["error"]
                raise RemoteFailure(status, error.get("code") if type(error) is dict else "untrusted_response")
            if not 200 <= status < 300 or "data" not in wrapped or type(wrapped["data"]) is not dict:
                raise KeyError
            return wrapped["data"]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise RemoteFailure(status) from None

    def get(self, route, values):
        exact_route(route, values)
        if ROUTES[route][0] != "GET":
            raise Refusal("This read route is not supported.")
        return self._request(MODULE + route, "GET", values)

    def post_exact(self, route, body_json, operation_id):
        values = parse_json(body_json)
        exact_route(route, values)
        if ROUTES[route][0] != "POST" or values["operation_id"] != operation_id:
            raise Refusal("The original saved operation identity is required.")
        return self._request(MODULE + route, "POST", values, body_json=body_json, operation_id=operation_id)


def blocked(journal):
    return [key for key, request in journal["requests"].items() if request["state"] in {"unknown", "retry_eligible"}]


def no_barrier(journal):
    if blocked(journal):
        raise Refusal("An unknown request blocks fresh commands. Use recover on that capture; never replace its UUID.")


def check_expiry(journal):
    if datetime.now(timezone.utc) >= timestamp(journal["profile"]["expires_at"]):
        raise Refusal("This diagnostic profile expired. Local discard remains available; no sync is permitted.")


def capture_record(journal, capture_id, *, payload=False):
    uuid4(capture_id)
    if capture_id not in journal["captures"]:
        raise Refusal("This journal does not own that capture UUID.")
    record = journal["captures"][capture_id]
    if payload and record.get("sealed_json") is None:
        raise Refusal("The local sealed payload was discarded; never reseal this UUID.")
    return record


def read_summary(journal, capture_id, result):
    record = capture_record(journal, capture_id)
    summary = result.get("capture")
    expected = {"capture_id", "device_id", "company", "project", "actor_person", "actor_user", "envelope_digest", "status", "payload_retained", "replaces_capture_id", "replacement_capture_id"}
    if type(summary) is not dict or set(summary) != expected or summary["capture_id"] != capture_id or summary["envelope_digest"] != record["envelope_sha256"] or type(summary["payload_retained"]) is not bool or summary["status"] not in {"staged", "committed", "discarded", "superseded"}:
        raise Refusal("The server capture summary does not match this immutable capture.")
    match_profile({**summary, "actor_person": summary["actor_person"], "actor_user": summary["actor_user"]}, journal["profile"])
    if summary["replaces_capture_id"] is not None or summary["replacement_capture_id"] is not None:
        raise Refusal("This minimal driver cannot adopt replacement lineage; preserve it for a qualified resolver.")
    checksum(result.get("capture_version"))
    return summary


def receipt_reference(journal, capture_id, original):
    if original is None:
        return None
    validate_frozen(original, "FoCreateRecordResponse")
    record = capture_record(journal, capture_id)
    envelope = parse_json(record["sealed_json"]) if record.get("sealed_json") is not None else None
    if type(original) is not dict or type(original.get("operation")) is not dict or original["operation"].get("id") != capture_id or original["operation"].get("status") != "succeeded" or type(original["operation"].get("replayed")) is not bool or original.get("family") not in {"daily", "ticket"}:
        raise Refusal("The server did not return the original canonical field receipt.")
    header, revision = original.get("header"), original.get("revision")
    if type(header) is not dict or type(revision) is not dict or header.get("id") != revision.get("parent_id"):
        raise Refusal("The original canonical receipt lineage is invalid.")
    for item in (header, revision):
        if (item.get("company"), item.get("project"), item.get("scope_type")) != (journal["profile"]["company"], journal["profile"]["project"], "Project"):
            raise Refusal("The original receipt belongs to another scope.")
        text(item.get("id"))
    if header["current_revision"] != revision["id"] or revision["author_person"] != journal["profile"]["person"]:
        raise Refusal("The original field revision and canonical author do not agree.")
    if envelope is not None:
        command = envelope["command"]
        if original["family"] != command["family"] or command["action"] == "revise" and header["id"] != command["record_id"]:
            raise Refusal("The original receipt target differs from the sealed command.")
        def source_input(source):
            return {key: source[key] for key in ("revision_id", "source_sha256", "page", "locator")}
        definition = {**revision["definition"]}
        if command["family"] == "daily":
            definition["weather_sources"] = [source_input(source) for source in definition["weather_sources"]]
        else:
            definition["lines"] = [{**line, "sources": [source_input(source) for source in line["sources"]]} for line in definition["lines"]]
        photos = [{**photo, "source": source_input(photo["source"])} for photo in revision["photos"]]
        if canonical(definition) != canonical(command["definition"]) or canonical(photos) != canonical(command["photos"]):
            raise Refusal("The original receipt changed the exact sealed documentary facts or source references.")
        quantities = original["quantities"]
        if len(quantities) != len(command["quantities"]):
            raise Refusal("The original receipt has a different quantity count.")
        for actual, expected in zip(quantities, command["quantities"]):
            qdefinition = {**actual["definition"], "sources": [source_input(source) for source in actual["definition"]["sources"]]}
            if canonical(qdefinition) != canonical(expected) or actual["parent_id"] != header["id"] or actual["source_revision"] != revision["id"] or actual["original_event_id"] != expected["original_event_id"] or actual["supersedes_event_id"] != expected["supersedes_event_id"] or actual["author_person"] != journal["profile"]["person"]:
                raise Refusal("The original quantity facts, exact decimals or immutable lineage differ from the seal.")
        if command["family"] == "daily" and revision["quantity_ids"] != [quantity["id"] for quantity in quantities]:
            raise Refusal("The original revision quantity indexes differ from its original receipt.")
        if command["action"] == "revise" and (revision["predecessor"] != command["base_revision_id"] or revision["amendment_reason"] != command["amendment_reason"]):
            raise Refusal("The original revision differs from the sealed base or amendment reason.")
        if command["action"] == "create" and (revision["predecessor"] is not None or revision["amendment_reason"] != ""):
            raise Refusal("The original create receipt contains unexpected revision lineage.")
    reference = {"operation_id": capture_id, "family": original["family"], "original_header_id": header["id"], "original_header_status": header.get("status"), "original_revision_id": revision["id"], "result_sha256_excluding_operation": digest({k: v for k, v in original.items() if k != "operation"})}
    previous_hash = record.get("original_result_sha256")
    if previous_hash is not None and previous_hash != reference["result_sha256_excluding_operation"]:
        raise Refusal("The immutable original result hash changed.")
    previous = record.get("original_committed_receipt")
    if previous is not None and previous != reference:
        raise Refusal("The original committed receipt changed; current projections cannot replace it.")
    return reference


def observe_pair(client, journal, capture_id):
    profile = journal["profile"]
    values = {"company": profile["company"], "project": profile["project"], "capture_id": capture_id}
    got = client.get("get_capture", values)
    inspected = client.get("inspect_capture", values)
    validate_frozen(got, "FoGetCaptureResponse")
    validate_frozen(inspected, "FoInspectCaptureResponse")
    gs, ins = read_summary(journal, capture_id, got), read_summary(journal, capture_id, inspected)
    if set(got) != {"capture", "capture_version", "envelope", "original_receipt"} or set(inspected) != {"capture", "capture_version", "disposition", "conflict", "original_receipt"}:
        raise Refusal("The exact get/inspect response shape was not returned.")
    if gs != ins or got["capture_version"] != inspected["capture_version"]:
        raise Refusal("Capture state changed during readback; perform another explicit inspection.")
    record = capture_record(journal, capture_id)
    if got["envelope"] is not None and digest(got["envelope"]) != record["envelope_sha256"] or (got["envelope"] is not None) != gs["payload_retained"]:
        raise Refusal("The server envelope differs from the exact seal.")
    first = receipt_reference(journal, capture_id, got["original_receipt"])
    second = receipt_reference(journal, capture_id, inspected["original_receipt"])
    if first != second:
        raise Refusal("The original receipt changed during readback; inspect again.")
    disposition = inspected["disposition"]
    if disposition not in {"ready", "conflict", "committed", "discarded", "superseded"} or (disposition == "committed") != (first is not None) or (disposition == "conflict") != (type(inspected["conflict"]) is dict):
        raise Refusal("The inspection disposition is inconsistent with its original receipt.")
    observation = {"observed_at": now(), "capture_version": got["capture_version"], "current_projection_status": gs["status"], "payload_retained": gs["payload_retained"], "disposition": disposition, "original_committed_receipt": first}
    observation["readback_sha256"] = digest(observation)
    record["last_observation"] = observation
    if first is not None:
        record["original_committed_receipt"] = first
        record["original_result_sha256"] = first["result_sha256_excluding_operation"]
    return observation


def prepare_request(journal, capture_id, route, values, operation_id):
    no_barrier(journal)
    uuid4(operation_id)
    exact_route(route, values)
    if operation_id in journal["requests"]:
        raise Refusal("This UUID already has an immutable request; use explicit recovery.")
    if route != "apply_capture" and operation_id == capture_id:
        raise Refusal("The capture UUID is reserved for its original field command.")
    encoded = canonical(values)
    journal["requests"][operation_id] = {"route": route, "capture_id": capture_id, "body_json": encoded, "body_sha256": sha(encoded), "state": "prepared", "attempts": 0, "prepared_at": now()}
    return operation_id


def transmit(path, journal, client, operation_id):
    request = journal["requests"][operation_id]
    if request["body_json"] is None or request["attempts"] >= MAX_ATTEMPTS:
        raise Refusal("The exact payload is unavailable or its single explicit retry was already used.")
    # DURABILITY BARRIER: unknown and identical request bytes reach fsynced disk
    # before a socket can be opened for this POST. An interrupted save sends none.
    request["state"] = "unknown"
    request["attempts"] += 1
    request["last_attempt_at"] = now()
    save(path, journal)
    result = client.post_exact(request["route"], request["body_json"], operation_id)
    validate_frozen(result, "FoApplyCaptureResponse" if request["route"] == "apply_capture" else "FoCaptureMutationResponse")
    read_summary(journal, request["capture_id"], result)
    if request["route"] == "apply_capture":
        if set(result) != {"capture", "capture_version", "original_receipt", "replayed"} or type(result["replayed"]) is not bool:
            raise Refusal("The exact apply result was not returned; recover the original UUID.")
        reference = receipt_reference(journal, request["capture_id"], result["original_receipt"])
        if reference is None:
            raise Refusal("Apply did not return its original canonical receipt; recover.")
        journal["captures"][request["capture_id"]]["original_committed_receipt"] = reference
        journal["captures"][request["capture_id"]]["original_result_sha256"] = reference["result_sha256_excluding_operation"]
        request["state"] = "committed"
    else:
        if set(result) != {"capture", "capture_version", "operation"} or type(result["operation"]) is not dict or result["operation"].get("id") != operation_id or result["operation"].get("status") != "succeeded":
            raise Refusal("The original summary command receipt was not returned; recover.")
        request["state"] = "acknowledged"
    request["acknowledged_at"] = now()
    request["response_data_sha256"] = digest(result)
    save(path, journal)
    return {"capture_id": request["capture_id"], "operation_id": operation_id, "state": request["state"], "body_sha256": request["body_sha256"], "current_projection_status": result["capture"]["status"], "original_committed_receipt": journal["captures"][request["capture_id"]].get("original_committed_receipt")}


def init(args):
    if not args.ack_private_plaintext:
        raise Refusal("Init requires explicit acknowledgment of the private plaintext diagnostic journal.")
    profile = {"origin": origin(args.origin), "company": text(args.company), "project": text(args.project), "person": text(args.person), "user": text(args.user), "device_id": uuid4(args.device), "expires_at": args.expires_at}
    if datetime.now(timezone.utc) >= timestamp(args.expires_at):
        raise Refusal("Use a finite future diagnostic profile expiry.")
    with locked_journal(args.journal, creating=True) as (path, _):
        journal = {"schema": JOURNAL_SCHEMA, "prepared_source_unrun": True, "created_at": now(), "profile": profile, "captures": {}, "requests": {}}
        save(path, journal)
    return {"state": "initialized_locally", "network_performed": False, "device_registration": "must_already_exist"}


def stage(args, path, journal, client):
    no_barrier(journal)
    if args.envelope is None:
        raise Refusal("Stage requires an explicit private envelope JSON file.")
    envelope = parse_json(private_read(args.envelope, MAX_ENVELOPE))
    validate_envelope(envelope)
    match_profile(envelope, journal["profile"])
    capture_id = envelope["capture_id"]
    if capture_id in journal["captures"] or capture_id in journal["requests"]:
        raise Refusal("This capture UUID is already sealed or reserved. Inspect/recover; never alter or reseal it.")
    sealed = canonical(envelope)
    journal["captures"][capture_id] = {"sealed_json": sealed, "envelope_sha256": sha(sealed), "sealed_at": now(), "original_committed_receipt": None, "last_observation": None}
    operation_id = str(uuid.uuid4())
    values = {"company": envelope["company"], "project": envelope["project"], "operation_id": operation_id, "envelope": envelope}
    prepare_request(journal, capture_id, "stage_capture", values, operation_id)
    save(path, journal)
    return transmit(path, journal, client, operation_id)


def apply(args, path, journal, client):
    no_barrier(journal)
    record = capture_record(journal, args.capture, payload=True)
    observation = observe_pair(client, journal, args.capture)
    save(path, journal)
    if observation["original_committed_receipt"] is not None:
        return {"state": "already_committed_original_receipt_read", "capture_id": args.capture, "observation": observation, "post_performed": False}
    if observation["disposition"] != "ready" or observation["current_projection_status"] != "staged":
        raise Refusal("Apply requires a current ready inspection; this driver does not resolve conflicts.")
    if not args.confirm_original_uuid:
        raise Refusal("Apply requires --confirm-original-uuid to authorize this selected business command.")
    values = {"company": journal["profile"]["company"], "project": journal["profile"]["project"], "operation_id": args.capture, "capture_id": args.capture, "expected_version": observation["capture_version"]}
    prepare_request(journal, args.capture, "apply_capture", values, args.capture)
    save(path, journal)
    return transmit(path, journal, client, args.capture)


def recover(args, path, journal, client):
    capture_record(journal, args.capture)
    # A prepared request with attempts=0 is durably known never to have reached
    # POST: transmit always fsyncs unknown before network. Its first send is
    # explicit, uses saved bytes, and must not be confused with unknown retry.
    prepared = [(key, request) for key, request in journal["requests"].items() if request["capture_id"] == args.capture and request["state"] == "prepared"]
    if prepared:
        if args.retry_operation is None:
            return {"capture_id": args.capture, "prepared_not_sent": [{"operation_id": key, "body_sha256": request["body_sha256"]} for key, request in prepared], "post_performed": False}
        request = journal["requests"].get(args.retry_operation)
        if not args.confirm_exact_retry or request is None or request["state"] != "prepared" or request["attempts"] != 0 or request["capture_id"] != args.capture:
            raise Refusal("Resume requires the exact prepared UUID and --confirm-exact-retry.")
        no_barrier(journal)
        return transmit(path, journal, client, args.retry_operation)
    pending = [(key, request) for key, request in journal["requests"].items() if request["capture_id"] == args.capture and request["state"] in {"unknown", "retry_eligible"}]
    observation = observe_pair(client, journal, args.capture)
    for operation_id, request in pending:
        request["last_recovery_readback"] = observation
        if request["route"] == "apply_capture" and observation["original_committed_receipt"] is not None:
            request["state"] = "committed"
        elif request["route"] == "stage_capture":
            # Existence + identical envelope is sufficient to observe staging's
            # immutable effect, but is not called its original operation receipt.
            request["state"] = "effect_observed"
        elif request["route"] == "discard_capture" and not observation["payload_retained"]:
            request["state"] = "effect_observed"
        elif request["body_json"] is not None:
            values = parse_json(request["body_json"])
            # No 404/denial/network error reaches here. Two authorized exact
            # successful reads must agree, with no original business receipt for
            # apply; retained payload proves redaction has not happened.
            same_version = values.get("expected_version") == observation["capture_version"]
            not_committed = request["route"] == "apply_capture" and observation["original_committed_receipt"] is None and observation["disposition"] == "ready" and observation["current_projection_status"] == "staged"
            not_redacted = request["route"] == "discard_capture" and observation["payload_retained"]
            if same_version and (not_committed or not_redacted) and request["attempts"] < MAX_ATTEMPTS:
                request["state"] = "retry_eligible"
    save(path, journal)
    if args.retry_operation is not None:
        uuid4(args.retry_operation)
        request = journal["requests"].get(args.retry_operation)
        if not args.confirm_exact_retry or request is None or request["capture_id"] != args.capture or request["state"] != "retry_eligible" or any(key != args.retry_operation for key in blocked(journal)):
            raise Refusal("Retry requires this exact eligible saved UUID, --confirm-exact-retry, and no other unresolved operation.")
        # Never refresh expected_version, payload, route, target or operation ID.
        return transmit(path, journal, client, args.retry_operation)
    return {"capture_id": args.capture, "observation": observation, "pending_operations": [{"operation_id": key, "state": request["state"], "attempts": request["attempts"]} for key, request in pending], "post_performed": False}


def discard(args, path, journal, client=None):
    record = capture_record(journal, args.capture)
    if args.local:
        # Local-only, no credential/session/expiry requirement. Preserve UUID/hash
        # tombstones and unknown barriers, remove all copies of capture content.
        record["sealed_json"] = None
        record["last_observation"] = None
        record["original_committed_receipt"] = None
        record["local_discarded_at"] = now()
        for request in journal["requests"].values():
            if request["capture_id"] == args.capture:
                request["body_json"] = None
                request.pop("last_recovery_readback", None)
                if request["state"] == "prepared":
                    request["state"] = "locally_abandoned"
        save(path, journal)
        return {"capture_id": args.capture, "state": "local_payload_removed", "network_performed": False, "unresolved_barrier_retained": bool(blocked(journal)), "secure_erasure_claim": False}
    no_barrier(journal)
    if not args.server or args.expected_version is None or args.reason is None or not args.confirm_redaction:
        raise Refusal("Server discard requires --server, --expected-version, --reason and --confirm-redaction.")
    # Do not demand source read access before redaction. Server discard has its
    # own current Project field.write and capture-version checks. The version is
    # an explicit operator input copied unchanged from a prior authorized read.
    checksum(args.expected_version)
    text(args.reason, 2000)
    operation_id = str(uuid.uuid4())
    values = {"company": journal["profile"]["company"], "project": journal["profile"]["project"], "operation_id": operation_id, "capture_id": args.capture, "expected_version": args.expected_version, "reason": args.reason}
    prepare_request(journal, args.capture, "discard_capture", values, operation_id)
    save(path, journal)
    return transmit(path, journal, client, operation_id)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--journal", required=True, help="0600 journal in an operator-owned 0700 directory")
    root.add_argument("--credentials", help="private file with COOKIE_JAR and current CSRF_TOKEN; never journaled")
    commands = root.add_subparsers(dest="command", required=True)
    command = commands.add_parser("init", help="local profile only; device must already be registered")
    for name in ("origin", "company", "project", "person", "user", "device", "expires-at"):
        command.add_argument("--" + name, required=True)
    command.add_argument("--ack-private-plaintext", action="store_true")
    command = commands.add_parser("stage", help="seal exact private input and explicitly stage it; never apply")
    command.add_argument("--envelope", required=True)
    for name in ("inspect", "apply", "recover", "discard"):
        command = commands.add_parser(name)
        command.add_argument("--capture", required=True)
        if name == "apply":
            command.add_argument("--confirm-original-uuid", action="store_true")
        elif name == "recover":
            command.add_argument("--retry-operation")
            command.add_argument("--confirm-exact-retry", action="store_true")
        elif name == "discard":
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument("--local", action="store_true")
            group.add_argument("--server", action="store_true")
            command.add_argument("--expected-version")
            command.add_argument("--reason")
            command.add_argument("--confirm-redaction", action="store_true")
    return root


def main():
    args = parser().parse_args()
    if args.command == "init":
        result = init(args)
    else:
        with locked_journal(args.journal) as (path, journal):
            if args.command == "discard" and args.local:
                result = discard(args, path, journal)
            else:
                check_expiry(journal)
                # No network for blocked fresh commands, including session GET.
                if args.command in {"stage", "apply", "discard"}:
                    no_barrier(journal)
                client = Client(journal["profile"], args.credentials)
                if args.command == "stage":
                    result = stage(args, path, journal, client)
                elif args.command == "apply":
                    result = apply(args, path, journal, client)
                elif args.command == "recover":
                    result = recover(args, path, journal, client)
                elif args.command == "discard":
                    result = discard(args, path, journal, client)
                else:
                    capture_record(journal, args.capture)
                    observation = observe_pair(client, journal, args.capture)
                    save(path, journal)
                    result = {"capture_id": args.capture, "observation": observation, "post_performed": False, "unresolved_barrier_retained": bool(blocked(journal))}
    # Only fixed metadata and projected/receipt references, never raw HTTP,
    # session response, payload, secret credentials or exception tracebacks.
    print(canonical(result))


if __name__ == "__main__":
    try:
        main()
    except RemoteFailure as error:
        print(canonical({"error": "request_unverified", "status": error.status, "code": error.code, "action": "Keep the journal; recover the same capture UUID. No automatic retry occurred."}), file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print(canonical({"error": "operator_interrupted", "action": "Preserve the journal and recover any unknown original request."}), file=sys.stderr)
        raise SystemExit(130)
    except Exception:
        # OS paths, HTTP messages, unexpected server data and tracebacks may
        # contain private information; emit no exception interpolation.
        print(canonical({"error": "local_or_contract_refusal", "action": "Check the private inputs and source contract. Preserve UUIDs and inspect/recover unresolved requests."}), file=sys.stderr)
        raise SystemExit(2)
