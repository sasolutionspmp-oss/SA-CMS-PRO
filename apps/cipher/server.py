"""HTTP boundary for the owner console.  Standard library only.

GET  /                      owner console
GET  /api/health            liveness and workspace authority
GET  /api/projects          projects
GET  /api/state?project=ID  full project state (defaults to the first project)
GET  /api/audit-export      audit export with schema manifest
GET  /api/schema            schema lifecycle status
POST /api/action/<name>     JSON body; names listed in ACTIONS

Every action maps to one service method with an explicit argument allowlist;
nothing on this surface can bypass approvals or post to the ledger directly.
"""
from __future__ import annotations

import hmac
import inspect
import json
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from .core.words import us_text
from .service import Cipher, run_golden_fixture
from .ricky_sdk import RickySDK
from .ricky_served import ServedRicky, ServedRickyRefused

CONSOLE_PATH = os.path.join(os.path.dirname(__file__), "console", "index.html")


def _actions(c: Cipher) -> dict[str, Callable[[dict[str, Any]], Any]]:
    served_ricky = ServedRicky(c.sdk)

    def p(d, *keys):
        missing = [k for k in keys if k not in d]
        if missing:
            raise ValueError(f"missing fields: {', '.join(missing)}")
        return [d[k] for k in keys]

    return {
        "add_party": lambda d: c.add_party(kind=d["kind"], name=d["name"], destination=d.get("destination")),
        # A payee destination change is never one call on this surface: request it, record the
        # independent verification (a different person, a stored evidence revision), then open
        # the party.verify_destination approval (bank_admin) and execute it once granted.
        "request_destination_change": lambda d: c.payments.request_destination_change(
            *p(d, "party_id", "new_destination"), d.get("requested_by", d.get("actor", "owner")), d.get("reason", ""), d.get("actor", "owner")),
        "record_verification_evidence": lambda d: c.payments.record_verification_evidence(
            *p(d, "change_id", "channel", "verified_by", "evidence_hash"), d.get("actor", "owner")),
        "withdraw_destination_change": lambda d: c.payments.withdraw_destination_change(*p(d, "change_id"), d.get("reason", ""), d.get("actor", "owner")),
        "request_destination_approval": lambda d: c.request_approval("party.verify_destination", *p(d, "change_id"), actor_role=d.get("actor_role", "bank_admin"), requested_by=d.get("actor", "owner")),
        "destination_changes": lambda d: c.payments.change_history(*p(d, "party_id")),
        "create_project": lambda d: c.create_project(name=d["name"], entity=d.get("entity", "S&A Solutions LLC (synthetic)"), budget=d.get("budget", "0"), customer_id=d.get("customer_id")),
        "set_budget": lambda d: c.set_budget(*p(d, "project_id", "budget")),
        "open_period": lambda d: c.open_period(*p(d, "period_id", "name", "start_date", "end_date")),
        "close_period": lambda d: _governed_close(c, d),
        "register_document": lambda d: c.evidence.register_document(project_id=d["project_id"], kind=d.get("kind", "drawing"), title=d["title"], actor=d.get("actor", "owner")),
        "add_revision": lambda d: c.evidence.add_revision(document_id=d["document_id"], content=str(d.get("content", "")), note=d.get("note", ""), actor=d.get("actor", "owner")),
        "create_estimate": lambda d: c.estimates.create(project_id=d["project_id"], document_revision_id=d["document_revision_id"], lines=d["lines"], actor=d.get("actor", "owner"), supersedes=d.get("supersedes")),
        "create_commitment": lambda d: c.commitments.create(project_id=d["project_id"], supplier_id=d["supplier_id"], title=d["title"], sov_lines=d["sov_lines"], retainage_rate=d.get("retainage_rate", "0.10"), estimate_id=d.get("estimate_id"), actor=d.get("actor", "owner")),
        "propose_change": lambda d: c.commitments.propose_change(d["commitment_id"], amount=d["amount"], reason=d.get("reason", ""), sov_line_id=d.get("sov_line_id"), actor=d.get("actor", "owner")),
        "reject_change": lambda d: c.commitments.reject_change(d["change_id"], actor=d.get("actor", "owner"), reason=d.get("reason", "")),
        "close_commitment": lambda d: c.close_commitment(d["commitment_id"], actor=d.get("actor", "owner")),
        "add_stored_material": lambda d: c.bills.add_stored_material(commitment_id=d["commitment_id"], sov_line_id=d["sov_line_id"], description=d.get("description", ""), eligible_amount=d["eligible_amount"], evidence_hash=d.get("evidence_hash", ""), location=d.get("location", ""), actor=d.get("actor", "owner")),
        "certify_bill": lambda d: c.bills.certify(commitment_id=d["commitment_id"], period_id=d["period_id"], installed=d["installed"], transfers=d.get("transfers"), actor=d.get("actor", "owner")),
        "void_bill": lambda d: c.bills.void(d["bill_id"], actor=d.get("actor", "owner"), reason=d.get("reason", "")),
        # drafts only: each becomes effective through its approval (bill.credit_note / bill.correct)
        "prepare_credit_note": lambda d: c.bills.prepare_credit_note(*p(d, "bill_id", "amount", "reason", "evidence_hash"), d.get("actor", "owner")),
        "prepare_bill_correction": lambda d: c.bills.prepare_correction(*p(d, "bill_id", "reason"), d.get("actor", "owner")),
        "certify_prime_bill": lambda d: c.receivables.certify(project_id=d["project_id"], period_id=d["period_id"], certified_cumulative=d["certified_cumulative"], retainage_rate=d.get("retainage_rate", "0.10"), actor=d.get("actor", "owner")),
        # sending is its own authority: this opens the prime_bill.send approval
        "send_prime_bill": lambda d: c.request_approval("prime_bill.send", d["prime_bill_id"], actor_role=d.get("actor_role", "owner"), requested_by=d.get("actor", "owner")),
        "record_collection": lambda d: c.receivables.record_collection(
            prime_bill_id=d.get("prime_bill_id"), retainage_invoice_id=d.get("retainage_invoice_id"), period_id=d["period_id"], amount=d["amount"],
            fee=d.get("fee", "0"), provider_ref=d["provider_ref"], actor=d.get("actor", "owner"), method=d.get("method", "ach"), mandate_ref=d.get("mandate_ref")),
        "record_mandate": lambda d: c.receivables.record_mandate(d["customer_id"], d["mandate_ref"], d["evidence_hash"], actor=d.get("actor", "owner")),
        "revoke_mandate": lambda d: c.receivables.revoke_mandate(d["customer_id"], d["mandate_ref"], actor=d.get("actor", "owner"), reason=d.get("reason", "")),
        "set_customer_terms": lambda d: c.receivables.set_customer_terms(*p(d, "customer_id", "days"), d.get("actor", "owner")),
        "record_deposit": lambda d: c.receivables.record_deposit(
            *p(d, "customer_id", "project_id", "amount", "provider_ref"), d.get("method", "ach"), d.get("actor", "owner"),
            period_id=d.get("period_id"), settlement_date=d.get("settlement_date"), mandate_ref=d.get("mandate_ref")),
        # drafts only: receivable.* approvals apply them
        "prepare_deposit_application": lambda d: c.receivables.prepare_deposit_application(*p(d, "deposit_id", "prime_bill_id", "amount"), d.get("actor", "owner")),
        "prepare_credit_memo": lambda d: c.receivables.prepare_credit_memo(*p(d, "prime_bill_id", "amount", "reason", "evidence_hash"), d.get("actor", "owner")),
        "prepare_write_off": lambda d: c.receivables.prepare_write_off(*p(d, "prime_bill_id", "amount", "reason"), d.get("actor", "owner")),
        "set_initial_budget": lambda d: c.forecast.set_initial_budget(*p(d, "project_id", "lines"), d.get("actor", "owner"), reason=d.get("reason", "initial budget")),
        # a draft only: the budget.revise approval applies it
        "prepare_budget_revision": lambda d: c.forecast.prepare_budget_revision(*p(d, "project_id", "lines", "reason"), d.get("actor", "owner")),
        "forecast_snapshot": lambda d: c.forecast.snapshot(*p(d, "project_id"), d.get("actor", "owner"), d.get("label", "")),
        "stale_payments": lambda d: c.payments.stale_processing(int(d["days"])) if "days" in d else c.payments.stale_processing(),
        "record_return": lambda d: c.receivables.record_return(collection_id=d["collection_id"], period_id=d["period_id"], reason=d.get("reason", ""), actor=d.get("actor", "owner")),
        "request_approval": lambda d: c.request_approval(d["operation"], d["subject_id"], actor_role=d.get("actor_role", "owner"), requested_by=d.get("actor", "owner")),
        "approve": lambda d: c.approve(d["approval_id"], approver=d.get("actor", "owner"), approver_role=d.get("approver_role", "owner")),
        "reject": lambda d: c.reject(d["approval_id"], approver=d.get("actor", "owner"), reason=d.get("reason", "")),
        "execute": lambda d: c.execute(d["approval_id"], actor=d.get("actor", "owner"), op_id=d.get("op_id"), period_id=d.get("period_id")).__dict__,
        "dispatch_payments": lambda d: c.dispatch_payments(),
        "reconcile_payments": lambda d: c.reconcile_payments(),
        "set_provider_mode": lambda d: _set_mode(c, d["mode"]),
        "settle_payment": lambda d: c.payments.ingest_event(c.provider.settle(c.payments.get(d["intent_id"])["logical_op_id"]), actor="webhook"),
        "return_payment": lambda d: c.payments.ingest_event(c.provider.return_payment(c.payments.get(d["intent_id"])["logical_op_id"], d.get("reason", "returned")), actor="webhook"),
        "replay_last_event": lambda d: _replay_last_event(c, d["intent_id"]),
        "ricky_propose": lambda d: c.ricky.propose(d["workflow"], actor_role=d.get("actor_role", "owner"), context=d.get("context", {})),
        "ricky_brief": lambda d: c.ricky.brief(d["project_id"], actor_role=d.get("actor_role", "owner")),
        "run_demo": lambda d: _run_demo(c),
        "snapshot": lambda d: {"path": _snapshot(c, d.get("name", ""))},
        "claim_challenge": lambda d: _claim_challenge(c),
        "claim_authority": lambda d: c.claim_write_authority(approval_ref=d.get("approval_ref"), actor=d.get("actor", "owner"), reason=d.get("reason"), claim_code=d.get("claim_code")),
        "ricky_tools": lambda d: served_ricky.catalog(),
        "ricky_tool": lambda d: served_ricky.invoke(d["tool"], d.get("args", {}), actor=d.get("actor", "owner"), actor_role=d.get("actor_role", "owner"), idempotency_key=d.get("idempotency_key")),
        "complete_recovery": lambda d: c.complete_recovery(actor=d.get("actor", "owner")),
        "selftest_report": lambda d: _store_selftest(c, d),
        "module_call": lambda d: _module_call(c, d),
    }


def _module_methods(plugin: Any) -> list[str]:
    if isinstance(plugin, RickySDK):
        return []  # the synthetic SDK is available only through the served adapter
    reserved = {"manifest_for", "apply", "state"}
    return sorted(
        name for name in dir(plugin)
        if not name.startswith("_") and name not in reserved and callable(getattr(plugin, name))
    )


def _module_call(c: Cipher, d: dict[str, Any]) -> Any:
    """Call a public record method on a registered v2 module, e.g.
    {"plugin": "asset", "method": "register_asset", "kwargs": {...}}.
    Approval-bound operations are not reachable here; they go through request_approval/execute."""
    plugin = c._plugins.get(d.get("plugin", ""))
    if d.get("plugin") == "ricky_sdk" or isinstance(plugin, RickySDK):
        raise ServedRickyRefused("Ricky's synthetic SDK cannot be called through module_call. Use Ricky's served read and draft tools.")
    if plugin is None:
        raise ValueError(f"unknown module {d.get('plugin')!r}; available: {', '.join(sorted(c._plugins))}")
    method = d.get("method", "")
    if method not in _module_methods(plugin):
        raise ValueError(f"unknown method {method!r} on module {d['plugin']}; available: {', '.join(_module_methods(plugin))}")
    kwargs = d.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        raise ValueError("kwargs must be a JSON object")
    fn = getattr(plugin, method)
    params = inspect.signature(fn).parameters
    accepts_actor = "actor" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_actor:
        kwargs.setdefault("actor", d.get("actor", "owner"))
    else:
        kwargs.pop("actor", None)
    unknown = [k for k in kwargs if k not in params and not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())]
    if unknown:
        raise ValueError(f"unknown arguments for {d['plugin']}.{method}: {', '.join(unknown)}; accepted: {', '.join(params)}")
    return fn(**kwargs)


def _store_selftest(c: Cipher, report: dict[str, Any]) -> dict[str, Any]:
    """The console's browser self-test posts its outcome here so a headless run can be read back."""
    setattr(c, "_selftest_report", {"result": report.get("result"), "nonce": report.get("nonce"), "steps": report.get("steps", []), "user_agent": report.get("user_agent", "")})
    return {"stored": True}


SNAPSHOT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def _run_demo(c: Cipher) -> dict[str, Any]:
    """Seed the golden fixture, but only into an empty workspace."""
    if c.projects():
        raise ValueError("the demo fixture can only be seeded into an empty workspace")
    return {k: v for k, v in run_golden_fixture(c).items() if k in ("project_id", "commitment_id", "executed_amount", "bill1", "bill2", "payment", "prime")}


def _snapshot(c: Cipher, name: str) -> str:
    """Snapshot into a 'snapshots' folder beside the workspace file.  The request names
    the file only; it can never choose a path elsewhere on the machine."""
    if c.db.in_memory:
        raise ValueError("an in-memory workspace has no file to snapshot")
    if not SNAPSHOT_NAME.match(name or "") or ".." in name:
        raise ValueError("snapshot name must be a plain file name (letters, digits, '.', '_', '-')")
    folder = os.path.join(os.path.dirname(os.path.abspath(c.db.path)), "snapshots")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name if name.endswith(".sqlite") else name + ".sqlite")
    if os.path.exists(target):
        raise ValueError("a snapshot with that name already exists")
    return c.snapshot(target)


def _claim_challenge(c: Cipher) -> dict[str, Any]:
    """The values an owner needs to compute this copy's claim code offline with the
    owner secret.  The code itself is never returned by the server."""
    ws = c.db.workspace()
    return {
        "workspace_id": ws["workspace_id"],
        "authority_epoch": ws["authority_epoch"],
        "challenge": c.db.claim_challenge(),
        "code_required": bool(os.environ.get("CIPHER_OWNER_SECRET")),
        "how": "claim code = hex(hmac_sha256(owner_secret, f'{workspace_id}:{authority_epoch}:{challenge}')); `python -m apps.cipher claim-code --db PATH` computes it with CIPHER_OWNER_SECRET set",
    }


def _governed_close(c: Cipher, d: dict[str, Any]) -> dict[str, Any]:
    """Interactive period close never bypasses the checklist: it opens a
    close.close_period approval when the close module is registered."""
    period_id = d["period_id"]
    if "close" in c._plugins:
        ap = c.request_approval("close.close_period", period_id, actor_role=d.get("actor_role", "owner"), requested_by=d.get("actor", "owner"))
        return {"approval_requested": ap["id"], "operation": "close.close_period", "checklist": c.plugin("close").checklist(period_id)}
    return c.close_period(period_id, actor=d.get("actor", "owner"))


def _set_mode(c: Cipher, mode: str) -> dict[str, Any]:
    if mode not in ("accept", "timeout_after_accept", "reject", "unavailable"):
        raise ValueError("unknown provider mode")
    c.provider.mode = mode
    return {"mode": mode}


def _replay_last_event(c: Cipher, intent_id: str) -> dict[str, Any]:
    intent = c.payments.get(intent_id)
    if not intent["events"]:
        raise ValueError("no provider event to replay")
    last = json.loads(intent["events"][-1]["payload_json"])
    return c.payments.ingest_event(last, actor="webhook-replay")


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
COOKIE_NAME = "cipher_token"
MAX_BODY_BYTES = 1_000_000
MAX_DRAIN_BYTES = 8_000_000  # oversized bodies up to this size are read and discarded before the 413

LOGIN_PAGE = b"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cipher sign-in</title><style>body{font:15px system-ui,sans-serif;background:#f4f6f8;color:#13202e;display:grid;place-items:center;min-height:100vh;margin:0}
form{background:#fff;border:1px solid #d9dfe6;border-radius:10px;padding:24px;display:grid;gap:10px;min-width:300px}h1{font-size:18px;margin:0;color:#0B2341}
input,button{font:inherit;padding:8px;border-radius:6px;border:1px solid #d9dfe6}button{background:#0B2341;color:#fff;border-color:#0B2341}</style></head>
<body><form method="get" action="/"><h1>Cipher owner console</h1><label>Access token<br><input name="token" type="password" autocomplete="current-password" required></label><button>Sign in</button></form></body></html>"""


def _is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS


class CipherHandler(BaseHTTPRequestHandler):
    """Request boundary.

    * Token mode (``token`` set): every API call needs ``Authorization: Bearer <token>``
      or the HttpOnly, SameSite=Strict session cookie set by ``GET /?token=...``.
    * Loopback mode (no token): the server only binds to loopback and only answers
      requests whose Host header is a loopback name (blocks DNS rebinding).
    * Every POST must be ``application/json`` and, when the browser sends an Origin,
      it must match the Host.  Cross-site form or ``text/plain`` posts are refused,
      so another web page cannot drive the console (CSRF).
    """

    cipher: Cipher
    actions: dict[str, Callable[[dict[str, Any]], Any]]
    token: str | None = None
    server_version = "Cipher/0.3"

    def log_message(self, fmt, *args):  # quiet by default
        if os.environ.get("CIPHER_HTTP_LOG"):
            super().log_message(fmt, *args)

    def _json(self, status: HTTPStatus, body: Any, extra_headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _html(self, status: HTTPStatus, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    # ---- boundary checks -------------------------------------------------- #

    def _host_name(self) -> str:
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):
            return host[: host.find("]") + 1] if "]" in host else host
        return host.rsplit(":", 1)[0] if ":" in host else host

    def _host_allowed(self) -> bool:
        if self.token:
            return True
        return _is_loopback(self._host_name())

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                return value
        return None

    def _authorized(self) -> bool:
        if not self.token:
            return True
        auth = self.headers.get("Authorization") or ""
        presented = auth[7:].strip() if auth.lower().startswith("bearer ") else self._cookie_token()
        return bool(presented) and hmac.compare_digest(presented.encode("utf-8"), self.token.encode("utf-8"))

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # non-browser clients (curl, tests) do not send Origin
        parsed = urlparse(origin)
        return parsed.netloc == (self.headers.get("Host") or "")

    def _reject_boundary(self) -> bool:
        """Send an error and return True when the request must not proceed."""
        if not self._host_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "host not allowed"})
            return True
        return False

    def do_GET(self):
        if self._reject_boundary():
            return
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                q = parse_qs(url.query)
                if self.token and "token" in q:
                    presented = q["token"][0]
                    if not hmac.compare_digest(presented.encode("utf-8"), self.token.encode("utf-8")):
                        return self._html(HTTPStatus.UNAUTHORIZED, LOGIN_PAGE)
                    rest = {k: v for k, v in q.items() if k != "token"}
                    location = "/" + (("?" + urlencode(rest, doseq=True)) if rest else "")
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self.send_header("Set-Cookie", f"{COOKIE_NAME}={presented}; HttpOnly; SameSite=Strict; Path=/")
                    self.send_header("Location", location)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if not self._authorized():
                    return self._html(HTTPStatus.UNAUTHORIZED, LOGIN_PAGE)
                with open(CONSOLE_PATH, "rb") as fh:
                    data = fh.read()
                return self._html(HTTPStatus.OK, data)
            if url.path == "/api/health":
                if not self._authorized():
                    return self._json(HTTPStatus.OK, {"ok": True})
                return self._json(HTTPStatus.OK, {"ok": True, "authority": self.cipher.db.authority_status(), "schema": self.cipher.db.schema_status()["current_version"]})
            if not self._authorized():
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
            if url.path == "/api/projects":
                return self._json(HTTPStatus.OK, self.cipher.projects())
            if url.path == "/api/schema":
                return self._json(HTTPStatus.OK, self.cipher.db.schema_status())
            if url.path == "/api/selftest":
                return self._json(HTTPStatus.OK, getattr(self.cipher, "_selftest_report", None) or {"result": None})
            if url.path == "/api/modules":
                return self._json(HTTPStatus.OK, {name: _module_methods(p) for name, p in sorted(self.cipher._plugins.items())})
            if url.path == "/api/audit-export":
                return self._json(HTTPStatus.OK, self.cipher.audit_export())
            if url.path == "/api/state":
                q = parse_qs(url.query)
                project_id = q.get("project", [None])[0]
                if not project_id:
                    projects = self.cipher.projects()
                    if not projects:
                        return self._json(HTTPStatus.OK, {"project": None, "authority": self.cipher.db.authority_status(), "parties": self.cipher.parties(), "periods": self.cipher.ledger.periods(), "approvals": []})
                    project_id = projects[0]["id"]
                return self._json(HTTPStatus.OK, self.cipher.project_state(project_id))
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self._json(HTTPStatus.BAD_REQUEST, {"error": us_text(str(exc)), "type": type(exc).__name__})

    def do_POST(self):
        # Read the body before any response so a rejected request never leaves unread
        # bytes on the socket (which makes some clients see a connection reset).
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            if 0 < length <= MAX_DRAIN_BYTES:
                remaining = length
                while remaining > 0:  # discard so the client can read the 413 instead of a reset
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_BODY_BYTES else HTTPStatus.BAD_REQUEST, {"error": f"body must be 0..{MAX_BODY_BYTES} bytes"})
        raw = self.rfile.read(length) if length else b"{}"
        if self._reject_boundary():
            return
        if not self._authorized():
            return self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
        if not self._origin_ok():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "cross-origin request refused"})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Content-Type must be application/json"})
        url = urlparse(self.path)
        if not url.path.startswith("/api/action/"):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        name = url.path[len("/api/action/"):]
        action = self.actions.get(name)
        if action is None:
            return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown action {name}"})
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            result = action(body)
            return self._json(HTTPStatus.OK, {"ok": True, "result": result})
        except ServedRickyRefused as exc:
            return self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": str(exc), "type": type(exc).__name__, "code": exc.code})
        except Exception as exc:
            # people read this text; stored codes inside messages are shown in American spelling
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": us_text(str(exc)), "type": type(exc).__name__})


class InsecureBindError(RuntimeError):
    """Binding beyond loopback without an access token is refused."""


def make_server(cipher: Cipher, host: str = "127.0.0.1", port: int = 8765, *, token: str | None = None) -> ThreadingHTTPServer:
    if token is not None and len(token) < 16:
        raise InsecureBindError("CIPHER_TOKEN must be at least 16 characters")
    if not _is_loopback(host) and not token:
        raise InsecureBindError(
            f"refusing to serve on {host} without an access token; set CIPHER_TOKEN (or bind 127.0.0.1)"
        )
    handler = type("BoundCipherHandler", (CipherHandler,), {"cipher": cipher, "actions": _actions(cipher), "token": token})
    return ThreadingHTTPServer((host, port), handler)


def serve(path: str = ":memory:", host: str = "127.0.0.1", port: int = 8765, *, demo: bool = False, token: str | None = None) -> None:
    token = token or os.environ.get("CIPHER_TOKEN") or None
    cipher = Cipher(path)
    if demo and not cipher.projects():
        run_golden_fixture(cipher)
    httpd = make_server(cipher, host, port, token=token)
    mode = "token required" if token else "loopback only, no token"
    print(f"Cipher console: http://{host}:{httpd.server_address[1]}/  (workspace {path}; {mode})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


class BackgroundServer:
    """Run the server on a thread; used by the HTTP tests and the browser check."""

    def __init__(self, cipher: Cipher, host: str = "127.0.0.1", port: int = 0, *, token: str | None = None):
        self.httpd = make_server(cipher, host, port, token=token)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
