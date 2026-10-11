"""Idempotent command execution and the durable outbox.

A command is identified by a *logical operation id* chosen by the caller
(for example ``bill-approve:<bill id>:<version>``).  Replaying the same id with
the same payload returns the stored result without re-executing anything.
The same id with a different payload is a conflict and fails, which is the
behaviour the plan requires for payment commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .audit import Audit
from .db import Database
from .ids import canonical_json, hash_json, loads, new_id, utcnow_iso


class IdempotencyConflict(RuntimeError):
    """Same logical operation id, different payload."""


@dataclass
class CommandResult:
    op_id: str
    replayed: bool
    result: Any


class Commands:
    def __init__(self, db: Database, audit: Audit):
        self.db = db
        self.audit = audit

    def run(self, op_id: str, payload: dict[str, Any], handler: Callable[[], Any], *, actor: str) -> CommandResult:
        payload_hash = hash_json(payload)
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            row = conn.execute("SELECT payload_hash, result_json FROM idempotency WHERE op_id = ?", (op_id,)).fetchone()
            if row is not None:
                if row["payload_hash"] != payload_hash:
                    self.audit.record(actor, "command.conflict", "command", op_id, {"stored_hash": row["payload_hash"], "attempted_hash": payload_hash})
                    raise IdempotencyConflict(f"logical operation {op_id} was already executed with a different payload")
                self.audit.record(actor, "command.replayed", "command", op_id, {"payload_hash": payload_hash})
                return CommandResult(op_id=op_id, replayed=True, result=loads(row["result_json"]))
            result = handler()
            conn.execute(
                "INSERT INTO idempotency (op_id, payload_hash, result_json, created_at) VALUES (?,?,?,?)",
                (op_id, payload_hash, canonical_json(result), utcnow_iso()),
            )
            self.audit.record(actor, "command.executed", "command", op_id, {"payload_hash": payload_hash})
            return CommandResult(op_id=op_id, replayed=False, result=result)

    # ---- outbox ----------------------------------------------------------- #

    def enqueue(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an outbox row inside the caller's transaction.  Only a committed
        outbox row can later be dispatched."""
        if not self.db.in_transaction:
            raise RuntimeError("outbox rows must be created inside the transaction that commits the business state")
        outbox_id = new_id("obx")
        self.db.execute(
            "INSERT INTO outbox (id, kind, payload_json, status, attempts, created_at) VALUES (?,?,?,'pending',0,?)",
            (outbox_id, kind, canonical_json(payload), utcnow_iso()),
        )
        return {"id": outbox_id, "kind": kind, "payload": payload, "status": "pending"}

    def pending(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.query("SELECT * FROM outbox WHERE status='pending' AND kind=? ORDER BY created_at", (kind,))
        else:
            rows = self.db.query("SELECT * FROM outbox WHERE status='pending' ORDER BY created_at")
        for r in rows:
            r["payload"] = loads(r.pop("payload_json"))
        return rows

    def get(self, outbox_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM outbox WHERE id=?", (outbox_id,))
        if row is None:
            raise KeyError(outbox_id)
        row["payload"] = loads(row.pop("payload_json"))
        return row

    def mark_dispatched(self, outbox_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE outbox SET status='dispatched', attempts=attempts+1, dispatched_at=? WHERE id=?", (utcnow_iso(), outbox_id))

    def mark_failed(self, outbox_id: str, error: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE outbox SET status='failed', attempts=attempts+1, last_error=? WHERE id=?", (error, outbox_id))
