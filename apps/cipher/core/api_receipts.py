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


AP_PREPARATION_ACTIONS = (
    "bill.prepare", "invoice.receive", "invoice.computeMatch",
    "invoice.requestMatchApproval", "invoice.approveMatch", "invoice.executeMatch",
)
AP_EXCEPTION_ACTIONS = (
    "invoice.revise", "invoice.reject", "invoice.reviewDuplicate", "bill.cancel",
    "bill.prepareCorrection", "bill.requestCorrection", "bill.approveCorrection", "bill.executeCorrection",
)
AP_ACCOUNTING_ACTIONS = (
    "accounting.prepare", "accounting.request", "accounting.approve", "accounting.queue",
    "accounting.deliver", "accounting.lookup", "accounting.reconcile",
)
AP_KNOWN_ACTIONS = frozenset(("bill.requestApproval", "bill.approve", "bill.post", *AP_PREPARATION_ACTIONS, *AP_EXCEPTION_ACTIONS, *AP_ACCOUNTING_ACTIONS))
AP_PREPARATION_RECEIPTS_SCHEMA_NAME = "ap_practice_preparation_action_receipts"
AP_PREPARATION_RECEIPTS_SCHEMA_STATEMENTS = [
    "DROP TRIGGER ap_action_receipts_insert",
    "DROP TRIGGER ap_action_receipts_no_update",
    "DROP TRIGGER ap_action_receipts_no_delete",
    """CREATE TABLE ap_action_receipts_expanded (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN (
            'bill.requestApproval','bill.approve','bill.post','bill.prepare','invoice.receive',
            'invoice.computeMatch','invoice.requestMatchApproval','invoice.approveMatch','invoice.executeMatch')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')),
        http_status INTEGER NOT NULL, result_json TEXT NOT NULL, source_json TEXT NOT NULL,
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "INSERT INTO ap_action_receipts_expanded SELECT * FROM ap_action_receipts",
    "DROP TABLE ap_action_receipts",
    "ALTER TABLE ap_action_receipts_expanded RENAME TO ap_action_receipts",
    *AP_RECEIPTS_SCHEMA_STATEMENTS[1:],
]


def register_api_preparation_receipts_schema() -> int:
    """Expand only the fixed action set; preserve every existing receipt byte.

    The original named schema and guard text remain unchanged. No columns are
    added to old rows, because doing so would change their original row hashes.
    """
    return register_schema_version(AP_PREPARATION_RECEIPTS_SCHEMA_NAME, AP_PREPARATION_RECEIPTS_SCHEMA_STATEMENTS)


AP_EXCEPTION_RECEIPTS_SCHEMA_NAME = "ap_practice_exception_action_receipts"
AP_EXCEPTION_RECEIPTS_SCHEMA_STATEMENTS = [
    "DROP TRIGGER ap_action_receipts_insert",
    "DROP TRIGGER ap_action_receipts_no_update",
    "DROP TRIGGER ap_action_receipts_no_delete",
    """CREATE TABLE ap_action_receipts_exceptions_expanded (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN (
            'bill.requestApproval','bill.approve','bill.post','bill.prepare','invoice.receive',
            'invoice.computeMatch','invoice.requestMatchApproval','invoice.approveMatch','invoice.executeMatch',
            'invoice.revise','invoice.reject','invoice.reviewDuplicate','bill.cancel',
            'bill.prepareCorrection','bill.requestCorrection','bill.approveCorrection','bill.executeCorrection')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')),
        http_status INTEGER NOT NULL, result_json TEXT NOT NULL, source_json TEXT NOT NULL,
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "INSERT INTO ap_action_receipts_exceptions_expanded SELECT * FROM ap_action_receipts",
    "DROP TABLE ap_action_receipts",
    "ALTER TABLE ap_action_receipts_exceptions_expanded RENAME TO ap_action_receipts",
    *AP_RECEIPTS_SCHEMA_STATEMENTS[1:],
]


def register_api_exception_receipts_schema() -> int:
    """Append exception receipts without altering any original receipt facts."""
    return register_schema_version(AP_EXCEPTION_RECEIPTS_SCHEMA_NAME, AP_EXCEPTION_RECEIPTS_SCHEMA_STATEMENTS)



AP_ACCOUNTING_RECEIPTS_SCHEMA_NAME = "ap_practice_accounting_action_receipts"
AP_ACCOUNTING_INVOCATION_SCHEMA_STATEMENTS = [
    """CREATE TABLE ap_accounting_invocations (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN ('accounting.deliver','accounting.lookup','accounting.reconcile')),
        resource_id TEXT NOT NULL REFERENCES accounting_intents(id), binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
        binding_hash TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('reserved','claimed','awaiting_observation','observed','completed')),
        revision INTEGER NOT NULL CHECK(revision>=0), body_json TEXT NOT NULL CHECK(json_valid(body_json)),
        row_hash TEXT NOT NULL, audit_seq INTEGER NOT NULL UNIQUE REFERENCES audit_log(seq),
        CHECK(json_extract(body_json,'$.id') IS id), CHECK(json_extract(body_json,'$.workspace_id') IS workspace_id),
        CHECK(json_extract(body_json,'$.canonical_person_id') IS canonical_person_id),
        CHECK(json_extract(body_json,'$.actor_login') IS actor_login), CHECK(json_extract(body_json,'$.repeatability_uuid') IS repeatability_uuid),
        CHECK(json_extract(body_json,'$.contract_version') IS contract_version), CHECK(json_extract(body_json,'$.fixed_action') IS fixed_action),
        CHECK(json_extract(body_json,'$.resource_id') IS resource_id), CHECK(json_extract(body_json,'$.binding_hash') IS binding_hash),
        CHECK(json_extract(body_json,'$.state') IS state), CHECK(json_extract(body_json,'$.revision') IS revision),
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    """CREATE TRIGGER ap_accounting_invocations_no_delete BEFORE DELETE ON ap_accounting_invocations
        BEGIN SELECT RAISE(ABORT,'accounting API invocations are append-only'); END""",
    """CREATE TRIGGER ap_accounting_invocations_birth BEFORE INSERT ON ap_accounting_invocations BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM ap_accounting_invocations WHERE id=NEW.id
            OR (canonical_person_id=NEW.canonical_person_id AND repeatability_uuid=NEW.repeatability_uuid))
            THEN RAISE(ABORT,'accounting API invocations cannot be replaced') END;
        SELECT CASE WHEN NEW.revision<>0 OR NEW.state<>'reserved' OR NOT EXISTS(
            SELECT 1 FROM audit_log WHERE seq=NEW.audit_seq AND action='ap.accounting_invocation_reserved'
              AND entity_type='ap_accounting_invocation' AND entity_id=NEW.id AND actor=NEW.actor_login
              AND json_extract(payload_json,'$.rowHash')=NEW.row_hash)
            THEN RAISE(ABORT,'accounting API reservation requires its original audited binding') END;
    END""",
    """CREATE TRIGGER ap_accounting_invocations_change BEFORE UPDATE ON ap_accounting_invocations BEGIN
        SELECT CASE WHEN NEW.id IS NOT OLD.id OR NEW.workspace_id IS NOT OLD.workspace_id
            OR NEW.canonical_person_id IS NOT OLD.canonical_person_id OR NEW.actor_login IS NOT OLD.actor_login
            OR NEW.repeatability_uuid IS NOT OLD.repeatability_uuid OR NEW.contract_version IS NOT OLD.contract_version
            OR NEW.fixed_action IS NOT OLD.fixed_action OR NEW.resource_id IS NOT OLD.resource_id
            OR NEW.binding_json IS NOT OLD.binding_json OR NEW.binding_hash IS NOT OLD.binding_hash
            OR NEW.revision<>OLD.revision+1 OR OLD.state='completed'
            THEN RAISE(ABORT,'accounting API original binding and completed result are immutable') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE seq=NEW.audit_seq
            AND action='ap.accounting_invocation_changed' AND entity_type='ap_accounting_invocation'
            AND entity_id=NEW.id AND actor=NEW.actor_login AND json_extract(payload_json,'$.rowHash')=NEW.row_hash)
            THEN RAISE(ABORT,'accounting API invocation change requires its exact audit revision') END;
    END""",
]
AP_ACCOUNTING_RECEIPTS_SCHEMA_STATEMENTS = [
    "DROP TRIGGER ap_action_receipts_insert",
    "DROP TRIGGER ap_action_receipts_no_update",
    "DROP TRIGGER ap_action_receipts_no_delete",
    """CREATE TABLE ap_action_receipts_accounting_expanded (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN (
            'bill.requestApproval','bill.approve','bill.post','bill.prepare','invoice.receive',
            'invoice.computeMatch','invoice.requestMatchApproval','invoice.approveMatch','invoice.executeMatch',
            'invoice.revise','invoice.reject','invoice.reviewDuplicate','bill.cancel',
            'bill.prepareCorrection','bill.requestCorrection','bill.approveCorrection','bill.executeCorrection',
            'accounting.prepare','accounting.request','accounting.approve','accounting.queue',
            'accounting.deliver','accounting.lookup','accounting.reconcile')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')),
        http_status INTEGER NOT NULL, result_json TEXT NOT NULL, source_json TEXT NOT NULL,
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "INSERT INTO ap_action_receipts_accounting_expanded SELECT * FROM ap_action_receipts",
    "DROP TABLE ap_action_receipts",
    "ALTER TABLE ap_action_receipts_accounting_expanded RENAME TO ap_action_receipts",
    *AP_RECEIPTS_SCHEMA_STATEMENTS[1:],
    *AP_ACCOUNTING_INVOCATION_SCHEMA_STATEMENTS,
]


def register_api_accounting_receipts_schema() -> int:
    """Append fixed handoff receipts and audited worker reservations after 70.

    Original receipt rows and named schema entries retain their exact text and
    hashes. Reservations precede external observation and never imply delivery.
    """
    return register_schema_version(AP_ACCOUNTING_RECEIPTS_SCHEMA_NAME, AP_ACCOUNTING_RECEIPTS_SCHEMA_STATEMENTS)


class APIReceiptIntegrityError(RuntimeError):
    """Receipt metadata is missing, counterfeit, or inconsistent with its audit."""


class APIRepeatabilityConflict(APIReceiptIntegrityError):
    """The reviewed key belongs to a different immutable worker invocation."""


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
            if (not canonical or row["fixed_action"] not in AP_KNOWN_ACTIONS
                    or row["workspace_id"] != workspace_id or row["receipt_hash"] != expected
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

    def require_repeatability_namespace(self, person_id: str, repeatability_uuid: str,
                                        action: str, binding: dict[str, Any]) -> dict[str, Any] | None:
        """Keep all fixed actions in the same person/key namespace.

        Current caller scope is established by the action runner before this
        pure check. Old workspaces without worker admission retain their original
        behavior; an installed or audited reservation store must verify fully.
        """
        self.verify_integrity()
        installed = self.db.one("SELECT version FROM schema_version WHERE name=?", (AP_ACCOUNTING_RECEIPTS_SCHEMA_NAME,))
        table = self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='ap_accounting_invocations'")
        births = self.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='ap.accounting_invocation_reserved'")
        if installed is None:
            if table is not None or births:
                raise APIReceiptIntegrityError("Accounting reservation history lost its registered admission schema")
            return None
        # This proof reads storage/audit metadata only. It initializes no worker
        # and neither retrieves nor invokes a simulator or domain adapter.
        from ..ap_accounting_actions import invocation_inventory_proof
        reservations = invocation_inventory_proof(self.db, self.audit)
        matches = [body for body in reservations if body["canonical_person_id"] == person_id
                   and body["repeatability_uuid"] == repeatability_uuid]
        if len(matches) > 1:
            raise APIReceiptIntegrityError("A reviewed key has multiple accounting reservations")
        if not matches:
            return None
        body = matches[0]
        if body["fixed_action"] != action or canonical_json(body["binding"]) != canonical_json(binding):
            raise APIRepeatabilityConflict("This repeatability key belongs to its original reviewed worker invocation")
        return body

    def record(self, *, person_id: str, actor_login: str, repeatability_uuid: str, contract_version: str,
               action: str, resource_id: str, binding: dict[str, Any], outcome: str, http_status: int,
               result: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        if not self.db.in_transaction:
            raise RuntimeError("AP action receipts must join the transaction committing their action")
        if action not in AP_KNOWN_ACTIONS:
            raise APIReceiptIntegrityError("This AP action has no fixed receipt contract")
        self.db.require_practice_mode()
        self.verify_integrity()
        reservation = self.require_repeatability_namespace(person_id, repeatability_uuid, action, binding)
        if reservation is not None and (reservation["state"] != "observed"
                or reservation["resource_id"] != resource_id or reservation["actor_login"] != actor_login
                or reservation["contract_version"] != contract_version):
            raise APIReceiptIntegrityError("A worker receipt requires its original observed invocation")
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
