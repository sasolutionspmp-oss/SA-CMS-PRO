"""Explicit schema79 and immutable receipts for nine local rfi actions.

Import is inert. The inventory proof reads only local metadata and the audit
chain; it never initializes a domain, identity provider or external adapter.
"""
from uuid import UUID

from .core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow_iso

CONTRACT_VERSION = "cipher.rfi-practice.v1"
RFI_ACTIONS = ("rfi.create", "rfi.draftResponse", "rfi.requestResponse", "rfi.approveResponse", "rfi.applyResponse",
               "rfi.setDistribution", "rfi.requestDistribution", "rfi.approveDistribution", "rfi.distribute")
ACTIONS = frozenset(RFI_ACTIONS)
SCHEMA_NAME = "rfi_practice_action_receipts"
RECEIPT_ACTION = "rfi.practice_action_recorded"
RECEIPT_ENTITY = "rfi_action_receipt"
SCHEMA_STATEMENTS = [
    """CREATE TABLE rfi_action_receipts (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN ('rfi.create','rfi.draftResponse','rfi.requestResponse','rfi.approveResponse','rfi.applyResponse','rfi.setDistribution','rfi.requestDistribution','rfi.approveDistribution','rfi.distribute')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
        outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')), http_status INTEGER NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)), source_json TEXT NOT NULL CHECK(json_valid(source_json)),
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "CREATE TRIGGER rfi_action_receipts_no_update BEFORE UPDATE ON rfi_action_receipts BEGIN SELECT RAISE(ABORT,'rfi action receipts are immutable'); END",
    "CREATE TRIGGER rfi_action_receipts_no_delete BEFORE DELETE ON rfi_action_receipts BEGIN SELECT RAISE(ABORT,'rfi action receipts are append-only'); END",
    """CREATE TRIGGER rfi_action_receipts_birth BEFORE INSERT ON rfi_action_receipts BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM rfi_action_receipts WHERE id=NEW.id
            OR (canonical_person_id=NEW.canonical_person_id AND repeatability_uuid=NEW.repeatability_uuid))
            THEN RAISE(ABORT,'rfi action receipts cannot be replaced') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='rfi.practice_action_recorded'
            AND entity_type='rfi_action_receipt' AND entity_id=NEW.id AND actor=NEW.actor_login
            AND json_extract(payload_json,'$.receipt_hash')=NEW.receipt_hash)
            THEN RAISE(ABORT,'rfi action receipts require their original audit proof') END;
    END""",
]


class RFIReceiptError(RuntimeError):
    pass


def register_rfi_receipts_schema():
    """Append79 only after the actual unchanged78 rfi source entry."""
    existing = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if existing is not None:
        if existing[0] != 79:
            raise RFIReceiptError("RFI receipts lost their original79 catalog position")
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 78 or SCHEMA_CATALOG[-1][1] != "rfi_sources_and_review_contexts":
        raise RFIReceiptError("RFI receipts require the genuine unchanged78-entry catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)


def require_other_namespaces(db, audit, person_id, key, action, binding):
    """Metadata-only collision checks, called after current person admission."""
    from .core.api_receipts import APIActionReceipts, APIRepeatabilityConflict
    receipts = APIActionReceipts(db, audit)
    receipts.require_repeatability_namespace(person_id, key, action, binding)
    if receipts.find(person_id, key) is not None:
        raise APIRepeatabilityConflict("This key belongs to its original AP request")
    # Older factories may not yet install the reciprocal core AR guard. Keep
    # composition safe without asking AR to interpret a rfi source.
    ar_exists = db.one("SELECT name FROM schema_version WHERE name='ar_practice_action_receipts'")
    ar_table = db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='ar_action_receipts'")
    ar_history = db.one("SELECT seq FROM audit_log WHERE action='ar.practice_action_recorded' LIMIT 1")
    if ar_exists or ar_table or ar_history:
        from .ar_receipts import ar_receipt_inventory_proof
        if any(row["canonical_person_id"] == person_id and row["repeatability_uuid"] == key
               for row in ar_receipt_inventory_proof(db, audit)):
            raise APIRepeatabilityConflict("This key belongs to its original owner-billing request")
    library_exists = db.one("SELECT name FROM schema_version WHERE name='library_practice_action_receipts'")
    library_table = db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='library_action_receipts'")
    library_history = db.one("SELECT seq FROM audit_log WHERE action='library.practice_action_recorded' LIMIT 1")
    if library_exists or library_table or library_history:
        from .library_receipts import library_receipt_inventory_proof
        if any(row["canonical_person_id"] == person_id and row["repeatability_uuid"] == key
               for row in library_receipt_inventory_proof(db, audit)):
            raise APIRepeatabilityConflict("This key belongs to its original library request")


class RFIReceipts:
    def __init__(self, db, audit):
        self.db, self.audit = db, audit

    def _installed(self):
        admission = self.db.one("SELECT version,statement_count,checksum FROM schema_version WHERE name=?", (SCHEMA_NAME,))
        table = self.db.one("SELECT sql FROM sqlite_master WHERE type='table' AND name='rfi_action_receipts'")
        history = self.db.one("SELECT seq FROM audit_log WHERE action=? LIMIT 1", (RECEIPT_ACTION,))
        if not admission:
            if table or history:
                raise RFIReceiptError("RFI receipts lost their named schema admission")
            return False
        physical = [row["version"] for row in self.db.query("SELECT version FROM schema_version WHERE version<=? ORDER BY version", (admission["version"],))]
        if (admission["version"] < 1 or admission["version"] != len(physical)
                or any(value != index for index, value in enumerate(physical, 1)) or admission["statement_count"] != len(SCHEMA_STATEMENTS)
                or admission["checksum"] != catalog_checksum(SCHEMA_STATEMENTS) or table is None):
            raise RFIReceiptError("RFI receipt schema differs from its original named admission")
        for statement in SCHEMA_STATEMENTS:
            kind, name = statement.split()[1:3]
            row = self.db.one("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind.lower(), name))
            if row is None or " ".join(row["sql"].split()) != " ".join(statement.split()):
                raise RFIReceiptError("RFI receipt storage guards changed")
        return True

    def verify_integrity(self, *, required=True):
        if not self.audit.verify_chain()["ok"]:
            raise RFIReceiptError("RFI receipt audit chain is broken")
        if not self._installed():
            if required:
                raise RFIReceiptError("RFI receipt schema has not been admitted")
            return
        workspace_id = self.db.mode_status()["workspace_id"]
        rows = {row["id"]: row for row in self.db.query("SELECT * FROM rfi_action_receipts")}
        events = self.db.query("SELECT * FROM audit_log WHERE action=? ORDER BY seq", (RECEIPT_ACTION,))
        if len(events) != len(rows) or {event["entity_id"] for event in events} != set(rows):
            raise RFIReceiptError("RFI receipt birth inventory changed")
        for event in events:
            row = rows[event["entity_id"]]
            expected = hash_json({key: value for key, value in row.items() if key != "receipt_hash"})
            try:
                binding, result, source = (loads(row[field]) for field in ("binding_json", "result_json", "source_json"))
                fields = {"contractVersion", "fixedAction", "resourceId", "canonicalTypedBody", "originalIfMatch", "preflightFingerprint"}
                shape = (type(binding) is dict and set(binding) == fields and type(result) is dict and type(source) is dict
                         and type(binding["canonicalTypedBody"]) is dict
                         and type(binding["originalIfMatch"]) is str and 0 < len(binding["originalIfMatch"]) <= 256
                         and type(binding["preflightFingerprint"]) is str and binding["preflightFingerprint"].isascii()
                         and 0 < len(binding["preflightFingerprint"]) <= 256
                         and binding["canonicalTypedBody"].get("fingerprint") == binding["preflightFingerprint"])
                created, audited = parse_iso(row["created_at"]), parse_iso(event["ts"])
                clock = created.utcoffset() is not None and audited.utcoffset() is not None and 0 <= (audited-created).total_seconds() <= 1
                canonical = all(row[field] == canonical_json(loads(row[field])) for field in ("binding_json", "result_json", "source_json"))
                payload = {"receipt_hash": expected, "canonical_person_id": row["canonical_person_id"], "fixed_action": row["fixed_action"],
                           "resource_id": row["resource_id"], "outcome": row["outcome"]}
                valid = (shape and clock and canonical and str(UUID(row["repeatability_uuid"])) == row["repeatability_uuid"]
                         and row["workspace_id"] == workspace_id and row["contract_version"] == CONTRACT_VERSION
                         and row["fixed_action"] in ACTIONS and row["receipt_hash"] == expected
                         and row["outcome"] in ("success", "refused") and type(row["http_status"]) is int
                         and (row["http_status"] == 200 if row["outcome"] == "success" else 400 <= row["http_status"] <= 499)
                         and event["entity_type"] == RECEIPT_ENTITY and event["actor"] == row["actor_login"]
                         and canonical_json(loads(event["payload_json"])) == canonical_json(payload)
                         and binding["contractVersion"] == CONTRACT_VERSION and binding["fixedAction"] == row["fixed_action"]
                         and binding["resourceId"] == row["resource_id"])
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                valid = False
            if not valid:
                raise RFIReceiptError("RFI receipt differs from its canonical original audit")

    def find(self, person_id, key):
        self.verify_integrity()
        return self.db.one("SELECT * FROM rfi_action_receipts WHERE canonical_person_id=? AND repeatability_uuid=?", (person_id, key))

    def record(self, *, person_id, actor_login, repeatability_uuid, action, resource_id, binding, result, source,
               outcome="success", http_status=200):
        if not self.db.in_transaction or action not in ACTIONS:
            raise RFIReceiptError("RFI receipt must join its fixed local effect transaction")
        self.db.require_practice_mode()
        self.db.require_write_authority()
        self.verify_integrity()
        require_other_namespaces(self.db, self.audit, person_id, repeatability_uuid, action, binding)
        row = {"id": new_id("rfiapi"), "workspace_id": self.db.mode_status()["workspace_id"], "canonical_person_id": person_id,
               "actor_login": actor_login, "repeatability_uuid": repeatability_uuid, "contract_version": CONTRACT_VERSION,
               "fixed_action": action, "resource_id": resource_id, "binding_json": canonical_json(binding), "outcome": outcome,
               "http_status": http_status, "result_json": canonical_json(result), "source_json": canonical_json(source), "created_at": utcnow_iso()}
        row["receipt_hash"] = hash_json(row)
        self.audit.record(actor_login, RECEIPT_ACTION, RECEIPT_ENTITY, row["id"],
            {"receipt_hash": row["receipt_hash"], "canonical_person_id": person_id, "fixed_action": action, "resource_id": resource_id, "outcome": outcome})
        self.db.execute(f"INSERT INTO rfi_action_receipts ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        self.verify_integrity()
        return row


def rfi_receipt_inventory_proof(db, audit):
    """Pure complete original metadata inventory, including schema admission."""
    receipts = RFIReceipts(db, audit)
    receipts.verify_integrity(required=False)
    if not receipts._installed():
        return []
    return db.query("SELECT * FROM rfi_action_receipts ORDER BY created_at,id")
