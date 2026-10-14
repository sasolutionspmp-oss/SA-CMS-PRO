"""Audited immutable receipts for the disposable human AP practice API.

Registration is explicit and late: importing this module never changes the
historical schema catalog.  The core verifies stored metadata against the
original audit chain; the AP action runner additionally verifies domain proof.
"""
from __future__ import annotations

from typing import Any

from .audit import Audit
from .db import Database, register_schema_version
from .ids import canonical_json, hash_json, loads, new_id, utcnow_iso

AP_RECEIPTS_SCHEMA_NAME = "ap_practice_action_receipts"
AP_RECEIPT_ACTION = "ap.practice_action_recorded"
AP_RECEIPT_ENTITY = "ap_action_receipt"
AP_RECEIPTS_SCHEMA_STATEMENTS = [
    """CREATE TABLE ap_action_receipts (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN ('bill.requestApproval','bill.approve','bill.post')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')),
        http_status INTEGER NOT NULL, result_json TEXT NOT NULL, source_json TEXT NOT NULL,
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "CREATE TRIGGER ap_action_receipts_no_update BEFORE UPDATE ON ap_action_receipts BEGIN SELECT RAISE(ABORT,'AP action receipts are immutable'); END",
    "CREATE TRIGGER ap_action_receipts_no_delete BEFORE DELETE ON ap_action_receipts BEGIN SELECT RAISE(ABORT,'AP action receipts are append-only'); END",
    """CREATE TRIGGER ap_action_receipts_insert BEFORE INSERT ON ap_action_receipts BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM ap_action_receipts WHERE id=NEW.id
            OR (canonical_person_id=NEW.canonical_person_id AND repeatability_uuid=NEW.repeatability_uuid))
            THEN RAISE(ABORT,'AP action receipts cannot be replaced') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='ap.practice_action_recorded'
            AND entity_type='ap_action_receipt' AND entity_id=NEW.id AND actor=NEW.actor_login
            AND json_extract(payload_json,'$.receipt_hash')=NEW.receipt_hash)
            THEN RAISE(ABORT,'AP action receipts require their original audit proof') END;
    END""",
]


def register_api_receipts_schema() -> int:
    """Append after the immutable workspace-mode entry, never on import."""
    return register_schema_version(AP_RECEIPTS_SCHEMA_NAME, AP_RECEIPTS_SCHEMA_STATEMENTS)


class APIReceiptIntegrityError(RuntimeError):
    """Receipt metadata is missing, counterfeit, or inconsistent with its audit."""


class APIActionReceipts:
    def __init__(self, db: Database, audit: Audit):
        self.db = db
        self.audit = audit

    def _guards(self) -> None:
        for statement in AP_RECEIPTS_SCHEMA_STATEMENTS[1:]:
            name = statement.split()[2]
            row = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,))
            if row is None or " ".join(row["sql"].split()) != " ".join(statement.split()):
                raise APIReceiptIntegrityError("AP action receipt storage guards are unavailable")

    def verify_integrity(self) -> None:
        # Known pre-mode copies remain diagnostic only.  Reading empty receipt
        # history does not declare their mode or grant runtime write authority.
        workspace_id = self.db.require_practice_mode(allow_pending=True)["workspace_id"]
        self._guards()
        if not self.audit.verify_chain()["ok"]:
            raise APIReceiptIntegrityError("AP action receipts require an intact audit chain")
        rows = {r["id"]: r for r in self.db.query("SELECT * FROM ap_action_receipts")}
        evidence: dict[str, dict[str, Any]] = {}
        for event in self.db.query("SELECT * FROM audit_log WHERE action=? ORDER BY seq", (AP_RECEIPT_ACTION,)):
            receipt_id = event["entity_id"]
            if event["entity_type"] != AP_RECEIPT_ENTITY or receipt_id in evidence:
                raise APIReceiptIntegrityError("AP action receipt history is malformed")
            evidence[receipt_id] = event
        if rows.keys() != evidence.keys():
            raise APIReceiptIntegrityError("AP action receipt history has missing or unaudited records")
        for receipt_id, row in rows.items():
            event = evidence[receipt_id]
            try:
                payload = loads(event["payload_json"])
                expected = hash_json({k: v for k, v in row.items() if k != "receipt_hash"})
                canonical = (row["binding_json"] == canonical_json(loads(row["binding_json"]))
                             and row["result_json"] == canonical_json(loads(row["result_json"]))
                             and row["source_json"] == canonical_json(loads(row["source_json"])))
            except (TypeError, ValueError, KeyError):
                raise APIReceiptIntegrityError("AP action receipt contains malformed facts") from None
            if (not canonical or row["workspace_id"] != workspace_id or row["receipt_hash"] != expected
                    or payload != {"receipt_hash": expected, "canonical_person_id": row["canonical_person_id"],
                                   "fixed_action": row["fixed_action"], "resource_id": row["resource_id"], "outcome": row["outcome"]}
                    or event["actor"] != row["actor_login"]):
                raise APIReceiptIntegrityError("AP action receipt differs from its original audited facts")

    def integrity_checks(self) -> list[dict[str, Any]]:
        try:
            self.verify_integrity()
        except (APIReceiptIntegrityError, ValueError, TypeError) as exc:
            return [{"ok": False, "code": "ap_action_receipts_integrity", "message": str(exc)}]
        return [{"ok": True, "code": "ap_action_receipts_integrity", "message": "AP action receipts match their immutable audited history"}]

    def find(self, person_id: str, repeatability_uuid: str) -> dict[str, Any] | None:
        self.verify_integrity()
        return self.db.one("SELECT * FROM ap_action_receipts WHERE canonical_person_id=? AND repeatability_uuid=?",
                           (person_id, repeatability_uuid))

    def record(self, *, person_id: str, actor_login: str, repeatability_uuid: str, contract_version: str,
               action: str, resource_id: str, binding: dict[str, Any], outcome: str, http_status: int,
               result: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        if not self.db.in_transaction:
            raise RuntimeError("AP action receipts must join the transaction committing their action")
        self.db.require_practice_mode()
        self.verify_integrity()
        row = {"id": new_id("api"), "workspace_id": self.db.mode_status()["workspace_id"],
               "canonical_person_id": person_id, "actor_login": actor_login, "repeatability_uuid": repeatability_uuid,
               "contract_version": contract_version, "fixed_action": action, "resource_id": resource_id,
               "binding_json": canonical_json(binding), "outcome": outcome, "http_status": http_status,
               "result_json": canonical_json(result), "source_json": canonical_json(source), "created_at": utcnow_iso()}
        row["receipt_hash"] = hash_json(row)
        self.audit.record(actor_login, AP_RECEIPT_ACTION, AP_RECEIPT_ENTITY, row["id"],
                          {"receipt_hash": row["receipt_hash"], "canonical_person_id": person_id,
                           "fixed_action": action, "resource_id": resource_id, "outcome": outcome})
        columns = ",".join(row)
        self.db.execute(f"INSERT INTO ap_action_receipts ({columns}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        return row
