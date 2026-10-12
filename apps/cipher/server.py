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

import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .service import Cipher, run_golden_fixture

CONSOLE_PATH = os.path.join(os.path.dirname(__file__), "console", "index.html")


def _actions(c: Cipher) -> dict[str, Callable[[dict[str, Any]], Any]]:
    def p(d, *keys):
        missing = [k for k in keys if k not in d]
        if missing:
            raise ValueError(f"missing fields: {', '.join(missing)}")
        return [d[k] for k in keys]

    return {
        "add_party": lambda d: c.add_party(kind=d["kind"], name=d["name"], destination=d.get("destination")),
        "verify_destination": lambda d: c.verify_destination(*p(d, "party_id"), destination=d["destination"], verified_by=d.get("actor", "owner")),
        "create_project": lambda d: c.create_project(name=d["name"], entity=d.get("entity", "S&A Solutions LLC (synthetic)"), budget=d.get("budget", "0"), customer_id=d.get("customer_id")),
        "set_budget": lambda d: c.set_budget(*p(d, "project_id", "budget")),
        "open_period": lambda d: c.open_period(*p(d, "period_id", "name", "start_date", "end_date")),
        "close_period": lambda d: c.close_period(*p(d, "period_id")),
        "register_document": lambda d: c.evidence.register_document(project_id=d["project_id"], kind=d.get("kind", "drawing"), title=d["title"], actor=d.get("actor", "owner")),
        "add_revision": lambda d: c.evidence.add_revision(document_id=d["document_id"], content=str(d.get("content", "")), note=d.get("note", ""), actor=d.get("actor", "owner")),
        "create_estimate": lambda d: c.estimates.create(project_id=d["project_id"], document_revision_id=d["document_revision_id"], lines=d["lines"], actor=d.get("actor", "owner"), supersedes=d.get("supersedes")),
        "create_commitment": lambda d: c.commitments.create(project_id=d["project_id"], supplier_id=d["supplier_id"], title=d["title"], sov_lines=d["sov_lines"], retainage_rate=d.get("retainage_rate", "0.10"), estimate_id=d.get("estimate_id"), actor=d.get("actor", "owner")),
        "propose_change": lambda d: c.commitments.propose_change(d["commitment_id"], amount=d["amount"], reason=d.get("reason", ""), sov_line_id=d.get("sov_line_id"), actor=d.get("actor", "owner")),
        "reject_change": lambda d: c.commitments.reject_change(d["change_id"], actor=d.get("actor", "owner"), reason=d.get("reason", "")),
        "close_commitment": lambda d: c.commitments.close(d["commitment_id"], actor=d.get("actor", "owner")),
        "add_stored_material": lambda d: c.bills.add_stored_material(commitment_id=d["commitment_id"], sov_line_id=d["sov_line_id"], description=d.get("description", ""), eligible_amount=d["eligible_amount"], evidence_hash=d.get("evidence_hash", ""), location=d.get("location", ""), actor=d.get("actor", "owner")),
        "certify_bill": lambda d: c.bills.certify(commitment_id=d["commitment_id"], period_id=d["period_id"], installed=d["installed"], transfers=d.get("transfers"), actor=d.get("actor", "owner")),
        "void_bill": lambda d: c.bills.void(d["bill_id"], actor=d.get("actor", "owner"), reason=d.get("reason", "")),
        "certify_prime_bill": lambda d: c.receivables.certify(project_id=d["project_id"], period_id=d["period_id"], certified_cumulative=d["certified_cumulative"], retainage_rate=d.get("retainage_rate", "0.10"), actor=d.get("actor", "owner")),
        "send_prime_bill": lambda d: c.receivables.send(d["prime_bill_id"], actor=d.get("actor", "owner")),
        "record_collection": lambda d: c.receivables.record_collection(prime_bill_id=d["prime_bill_id"], period_id=d["period_id"], amount=d["amount"], fee=d.get("fee", "0"), provider_ref=d["provider_ref"], actor=d.get("actor", "owner")),
        "record_return": lambda d: c.receivables.record_return(collection_id=d["collection_id"], period_id=d["period_id"], reason=d.get("reason", ""), actor=d.get("actor", "owner")),
        "request_approval": lambda d: c.request_approval(d["operation"], d["subject_id"], actor_role=d.get("actor_role", "owner"), requested_by=d.get("actor", "owner")),
        "approve": lambda d: c.approve(d["approval_id"], approver=d.get("actor", "owner")),
        "reject": lambda d: c.reject(d["approval_id"], approver=d.get("actor", "owner"), reason=d.get("reason", "")),
        "execute": lambda d: c.execute(d["approval_id"], actor=d.get("actor", "owner"), op_id=d.get("op_id"), period_id=d.get("period_id")).__dict__,
        "dispatch_payments": lambda d: c.dispatch_payments(),
        "reconcile_payments": lambda d: c.reconcile_payments(),
        "set_provider_mode": lambda d: _set_mode(c, d["mode"]),
        "settle_payment": lambda d: c.payments.ingest_event(c.provider.settle(c.payments.get(d["intent_id"])["logical_op_id"]), actor="webhook"),
        "return_payment": lambda d: c.payments.ingest_event(c.provider.return_payment(c.payments.get(d["intent_id"])["logical_op_id"], d.get("reason", "returned")), actor="webhook"),
        "replay_last_event": lambda d: _replay_last_event(c, d["intent_id"]),
        "ricky_propose": lambda d: c.ricky.propose(d["workflow"], actor_role=d.get("actor_role", "owner"), context=d.get("context", {})),
        "run_demo": lambda d: {k: v for k, v in run_golden_fixture(c).items() if k in ("project_id", "commitment_id", "executed_amount", "bill1", "bill2", "payment", "prime")},
        "snapshot": lambda d: {"path": c.snapshot(d["path"])},
        "claim_authority": lambda d: c.claim_write_authority(approval_ref=d["approval_ref"], actor=d.get("actor", "owner")),
        "complete_recovery": lambda d: c.complete_recovery(actor=d.get("actor", "owner")),
        "selftest_report": lambda d: _store_selftest(c, d),
    }


def _store_selftest(c: Cipher, report: dict[str, Any]) -> dict[str, Any]:
    """The console's browser self-test posts its outcome here so a headless run can be read back."""
    setattr(c, "_selftest_report", {"result": report.get("result"), "steps": report.get("steps", []), "user_agent": report.get("user_agent", "")})
    return {"stored": True}


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


class CipherHandler(BaseHTTPRequestHandler):
    cipher: Cipher
    actions: dict[str, Callable[[dict[str, Any]], Any]]
    server_version = "Cipher/0.2"

    def log_message(self, fmt, *args):  # quiet by default
        if os.environ.get("CIPHER_HTTP_LOG"):
            super().log_message(fmt, *args)

    def _json(self, status: HTTPStatus, body: Any) -> None:
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                with open(CONSOLE_PATH, "rb") as fh:
                    data = fh.read()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if url.path == "/api/health":
                return self._json(HTTPStatus.OK, {"ok": True, "authority": self.cipher.db.authority_status(), "schema": self.cipher.db.schema_status()["current_version"]})
            if url.path == "/api/projects":
                return self._json(HTTPStatus.OK, self.cipher.projects())
            if url.path == "/api/schema":
                return self._json(HTTPStatus.OK, self.cipher.db.schema_status())
            if url.path == "/api/selftest":
                return self._json(HTTPStatus.OK, getattr(self.cipher, "_selftest_report", None) or {"result": None})
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
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "type": type(exc).__name__})

    def do_POST(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/action/"):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        name = url.path[len("/api/action/"):]
        action = self.actions.get(name)
        if action is None:
            return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown action {name}"})
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            result = action(body)
            return self._json(HTTPStatus.OK, {"ok": True, "result": result})
        except Exception as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc), "type": type(exc).__name__})


def make_server(cipher: Cipher, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = type("BoundCipherHandler", (CipherHandler,), {"cipher": cipher, "actions": _actions(cipher)})
    return ThreadingHTTPServer((host, port), handler)


def serve(path: str = ":memory:", host: str = "127.0.0.1", port: int = 8765, *, demo: bool = False) -> None:
    cipher = Cipher(path)
    if demo and not cipher.projects():
        run_golden_fixture(cipher)
    httpd = make_server(cipher, host, port)
    print(f"Cipher console: http://{host}:{httpd.server_address[1]}/  (workspace {path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


class BackgroundServer:
    """Run the server on a thread; used by the HTTP tests and the browser check."""

    def __init__(self, cipher: Cipher, host: str = "127.0.0.1", port: int = 0):
        self.httpd = make_server(cipher, host, port)
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
