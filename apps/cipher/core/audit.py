"""Append-only, hash-chained audit log and audit export."""
from __future__ import annotations

from typing import Any

from .db import Database
from .ids import canonical_json, sha256_hex, utcnow_iso

GENESIS = "0" * 64


class Audit:
    def __init__(self, db: Database):
        self.db = db

    def record(self, actor: str, action: str, entity_type: str, entity_id: str, payload: dict | None = None) -> dict[str, Any]:
        payload = payload or {}
        payload_json = canonical_json(payload)
        payload_hash = sha256_hex(payload_json)
        with self.db.transaction() as conn:
            prev = conn.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = prev[0] if prev else GENESIS
            ts = utcnow_iso()
            entry_hash = sha256_hex("|".join([prev_hash, ts, actor, action, entity_type, entity_id, payload_hash]))
            cur = conn.execute(
                "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash),
            )
            return {
                "seq": cur.lastrowid,
                "ts": ts,
                "actor": actor,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload_hash": payload_hash,
                "prev_hash": prev_hash,
                "entry_hash": entry_hash,
            }

    def entries(self, *, entity_type: str | None = None, entity_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit_log"
        clauses, params = [], []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY seq"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.db.query(sql, tuple(params))

    def verify_chain(self) -> dict[str, Any]:
        prev_hash = GENESIS
        count = 0
        for row in self.db.query("SELECT * FROM audit_log ORDER BY seq"):
            expected = sha256_hex("|".join([prev_hash, row["ts"], row["actor"], row["action"], row["entity_type"], row["entity_id"], row["payload_hash"]]))
            if row["prev_hash"] != prev_hash or row["entry_hash"] != expected or sha256_hex(row["payload_json"]) != row["payload_hash"]:
                return {"ok": False, "entries": count, "broken_at_seq": row["seq"]}
            prev_hash = row["entry_hash"]
            count += 1
        return {"ok": True, "entries": count, "head": prev_hash}

    def export(self) -> dict[str, Any]:
        entries = self.db.query("SELECT * FROM audit_log ORDER BY seq")
        return {
            "generated_at": utcnow_iso(),
            "chain": self.verify_chain(),
            "entries": entries,
        }
