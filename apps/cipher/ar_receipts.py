"""Explicit schema75 and immutable receipts for seven local ar actions.

Importing this module never registers a schema or changes a workspace.
"""
from .core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow_iso
CONTRACT_VERSION = "cipher.ar-practice.v1"
AR_ACTIONS = ("ownerBill.prepare", "ownerBill.requestApproval", "ownerBill.approve", "ownerBill.post",
              "ownerBill.requestSend", "ownerBill.approveSend", "ownerBill.send")
ACTIONS = frozenset(AR_ACTIONS)

SCHEMA_NAME = "ar_practice_action_receipts"
RECEIPT_ACTION = "ar.practice_action_recorded"
RECEIPT_ENTITY = "ar_action_receipt"
SCHEMA_STATEMENTS = [
    """CREATE TABLE ar_action_receipts (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN ('ownerBill.prepare','ownerBill.requestApproval','ownerBill.approve','ownerBill.post','ownerBill.requestSend','ownerBill.approveSend','ownerBill.send')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
        outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')), http_status INTEGER NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)), source_json TEXT NOT NULL CHECK(json_valid(source_json)),
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "CREATE TRIGGER ar_action_receipts_no_update BEFORE UPDATE ON ar_action_receipts BEGIN SELECT RAISE(ABORT,'ar action receipts are immutable'); END",
    "CREATE TRIGGER ar_action_receipts_no_delete BEFORE DELETE ON ar_action_receipts BEGIN SELECT RAISE(ABORT,'ar action receipts are append-only'); END",
    """CREATE TRIGGER ar_action_receipts_birth BEFORE INSERT ON ar_action_receipts BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM ar_action_receipts WHERE id=NEW.id
            OR (canonical_person_id=NEW.canonical_person_id AND repeatability_uuid=NEW.repeatability_uuid))
            THEN RAISE(ABORT,'ar action receipts cannot be replaced') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='ar.practice_action_recorded'
            AND entity_type='ar_action_receipt' AND entity_id=NEW.id AND actor=NEW.actor_login
            AND json_extract(payload_json,'$.receipt_hash')=NEW.receipt_hash)
            THEN RAISE(ABORT,'ar action receipts require their original audit proof') END;
    END""",
]


def register_ar_receipts_schema():
    """Explicit late registration after the unchanged schema74 manual sources."""
    existing = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if existing is not None:
        if existing[0] != 75:
            raise ARReceiptError("AR receipt schema lost its original75 position")
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 74 or SCHEMA_CATALOG[-1][1] != "owner_billing_sources_and_posting":
        raise ARReceiptError("AR receipts require the unchanged74-entry owner-source catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)


class ARReceiptError(RuntimeError):
    pass


class ARReceipts:
    def __init__(self, db, audit):
        self.db, self.audit = db, audit

    def verify_integrity(self):
        admission = self.db.one("SELECT version,statement_count,checksum FROM schema_version WHERE name=?", (SCHEMA_NAME,))
        version = admission["version"] if admission is not None else 0
        versions = [row["version"] for row in self.db.query("SELECT version FROM schema_version WHERE version<=? ORDER BY version", (version,))]
        if (admission is None or version < 1 or version != len(versions)
                or any(value != index for index, value in enumerate(versions, 1))
                or admission["statement_count"] != len(SCHEMA_STATEMENTS)
                or admission["checksum"] != catalog_checksum(SCHEMA_STATEMENTS)):
            raise ARReceiptError("AR receipt history lost its exact registered admission")
        for statement in SCHEMA_STATEMENTS[1:]:
            row = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (statement.split()[2],))
            if row is None or " ".join(row["sql"].split()) != " ".join(statement.split()):
                raise ARReceiptError("AR receipt storage guards changed")
        if not self.audit.verify_chain()["ok"]:
            raise ARReceiptError("AR receipt audit chain is broken")
        workspace_id = self.db.mode_status()["workspace_id"]
        rows = {row["id"]: row for row in self.db.query("SELECT * FROM ar_action_receipts")}
        events = self.db.query("SELECT * FROM audit_log WHERE action=? ORDER BY seq", (RECEIPT_ACTION,))
        if len(events) != len(rows) or {event["entity_id"] for event in events} != set(rows):
            raise ARReceiptError("AR receipt birth inventory changed")
        for event in events:
            row = rows[event["entity_id"]]
            expected = hash_json({key: value for key, value in row.items() if key != "receipt_hash"})
            try:
                binding = loads(row["binding_json"])
                result, source = loads(row["result_json"]), loads(row["source_json"])
                binding_fields = {"contractVersion", "fixedAction", "resourceId", "canonicalTypedBody", "originalIfMatch", "preflightFingerprint"}
                shape = (type(binding) is dict and set(binding) == binding_fields and type(result) is dict and type(source) is dict
                         and type(binding["canonicalTypedBody"]) is dict
                         and type(binding["originalIfMatch"]) is str and 0 < len(binding["originalIfMatch"]) <= 256
                         and type(binding["preflightFingerprint"]) is str and binding["preflightFingerprint"].isascii()
                         and 0 < len(binding["preflightFingerprint"]) <= 256
                         and binding["canonicalTypedBody"].get("fingerprint") == binding["preflightFingerprint"])
                created, audited = parse_iso(row["created_at"]), parse_iso(event["ts"])
                clock = created.utcoffset() is not None and audited.utcoffset() is not None and 0 <= (audited-created).total_seconds() <= 1
                canonical = all(row[field] == canonical_json(loads(row[field])) for field in ("binding_json", "result_json", "source_json"))
                valid = (shape and clock and canonical and row["workspace_id"] == workspace_id and row["contract_version"] == CONTRACT_VERSION
                         and row["fixed_action"] in ACTIONS and row["receipt_hash"] == expected
                         and event["entity_type"] == RECEIPT_ENTITY and event["actor"] == row["actor_login"]
                         and loads(event["payload_json"]) == {"receipt_hash": expected, "canonical_person_id": row["canonical_person_id"],
                              "fixed_action": row["fixed_action"], "resource_id": row["resource_id"], "outcome": row["outcome"]}
                         and binding["contractVersion"] == CONTRACT_VERSION and binding["fixedAction"] == row["fixed_action"]
                         and binding["resourceId"] == row["resource_id"])
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                raise ARReceiptError("AR receipt differs from its canonical original audit")

    def find(self, person_id, key):
        self.verify_integrity()
        return self.db.one("SELECT * FROM ar_action_receipts WHERE canonical_person_id=? AND repeatability_uuid=?", (person_id, key))

    def record(self, *, person_id, actor_login, repeatability_uuid, action, resource_id, binding, result, source,
               outcome="success", http_status=200):
        if not self.db.in_transaction or action not in ACTIONS:
            raise ARReceiptError("AR receipt must join its fixed local effect transaction")
        self.db.require_practice_mode()
        self.db.require_write_authority()
        self.verify_integrity()
        # A second metadata-only guard catches a nested callback trying to
        # reserve this key in the AP namespace after the human review.
        from .core.api_receipts import APIActionReceipts, APIRepeatabilityConflict
        ap = APIActionReceipts(self.db, self.audit)
        ap.require_repeatability_namespace(person_id, repeatability_uuid, action, binding)
        if ap.find(person_id, repeatability_uuid) is not None:
            raise APIRepeatabilityConflict("This key belongs to its original AP request")
        row = {"id": new_id("arapi"), "workspace_id": self.db.mode_status()["workspace_id"],
               "canonical_person_id": person_id, "actor_login": actor_login, "repeatability_uuid": repeatability_uuid,
               "contract_version": CONTRACT_VERSION, "fixed_action": action, "resource_id": resource_id,
               "binding_json": canonical_json(binding), "outcome": outcome, "http_status": http_status,
               "result_json": canonical_json(result), "source_json": canonical_json(source), "created_at": utcnow_iso()}
        row["receipt_hash"] = hash_json(row)
        self.audit.record(actor_login, RECEIPT_ACTION, RECEIPT_ENTITY, row["id"],
                          {"receipt_hash": row["receipt_hash"], "canonical_person_id": person_id,
                           "fixed_action": action, "resource_id": resource_id, "outcome": outcome})
        self.db.execute(f"INSERT INTO ar_action_receipts ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        self.verify_integrity()
        return row


def ar_receipt_inventory_proof(db, audit):
    """Pure complete metadata/audit inventory; no domain, AP or provider calls."""
    ARReceipts(db, audit).verify_integrity()
    return db.query("SELECT * FROM ar_action_receipts ORDER BY created_at,id")
