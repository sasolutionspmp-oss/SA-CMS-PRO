"""Explicit schema73 and immutable receipts for seven local commercial actions.

Importing this module never registers a schema or changes a workspace.
"""
from .core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from .core.ids import canonical_json, hash_json, loads, new_id, utcnow_iso
from .commercial_wire import ACTIONS, CONTRACT_VERSION

SCHEMA_NAME = "commercial_practice_action_receipts"
RECEIPT_ACTION = "commercial.practice_action_recorded"
RECEIPT_ENTITY = "commercial_action_receipt"
SCHEMA_STATEMENTS = [
    """CREATE TABLE commercial_action_receipts (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        canonical_person_id TEXT NOT NULL REFERENCES people_persons(id), actor_login TEXT NOT NULL,
        repeatability_uuid TEXT NOT NULL, contract_version TEXT NOT NULL,
        fixed_action TEXT NOT NULL CHECK(fixed_action IN ('estimate.create','estimate.revise','estimate.request','estimate.accept','estimate.apply','estimate.prepareHandoff','estimate.createCommitment')),
        resource_id TEXT NOT NULL, binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
        outcome TEXT NOT NULL CHECK(outcome IN ('success','refused')), http_status INTEGER NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)), source_json TEXT NOT NULL CHECK(json_valid(source_json)),
        created_at TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        UNIQUE(canonical_person_id,repeatability_uuid)
    )""",
    "CREATE TRIGGER commercial_action_receipts_no_update BEFORE UPDATE ON commercial_action_receipts BEGIN SELECT RAISE(ABORT,'commercial action receipts are immutable'); END",
    "CREATE TRIGGER commercial_action_receipts_no_delete BEFORE DELETE ON commercial_action_receipts BEGIN SELECT RAISE(ABORT,'commercial action receipts are append-only'); END",
    """CREATE TRIGGER commercial_action_receipts_birth BEFORE INSERT ON commercial_action_receipts BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM commercial_action_receipts WHERE id=NEW.id
            OR (canonical_person_id=NEW.canonical_person_id AND repeatability_uuid=NEW.repeatability_uuid))
            THEN RAISE(ABORT,'commercial action receipts cannot be replaced') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='commercial.practice_action_recorded'
            AND entity_type='commercial_action_receipt' AND entity_id=NEW.id AND actor=NEW.actor_login
            AND json_extract(payload_json,'$.receipt_hash')=NEW.receipt_hash)
            THEN RAISE(ABORT,'commercial action receipts require their original audit proof') END;
    END""",
]


def register_commercial_receipts_schema():
    """Explicit late registration after the unchanged schema72 manual sources."""
    existing = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if existing is not None:
        if existing[0] != 73:
            raise CommercialReceiptError("Commercial receipt schema lost its original73 position")
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 72 or SCHEMA_CATALOG[-1][1] != "commercial_manual_sources_and_handoffs":
        raise CommercialReceiptError("Commercial receipts require the unchanged72-entry source catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)


class CommercialReceiptError(RuntimeError):
    pass


class CommercialReceipts:
    def __init__(self, db, audit):
        self.db, self.audit = db, audit

    def _installed(self):
        admission = self.db.one("SELECT version,statement_count,checksum FROM schema_version WHERE name=?", (SCHEMA_NAME,))
        table = self.db.one("SELECT sql FROM sqlite_master WHERE type='table' AND name='commercial_action_receipts'")
        history = self.db.one("SELECT seq FROM audit_log WHERE action=? LIMIT 1", (RECEIPT_ACTION,))
        if admission is None:
            if table is not None or history is not None:
                raise CommercialReceiptError("Commercial receipts lost their original named admission")
            return False
        physical = self.db.query("SELECT version FROM schema_version WHERE version<=? ORDER BY version", (admission["version"],))
        if (admission["version"] < 1 or admission["version"] != len(physical)
                or any(row["version"] != index for index, row in enumerate(physical, 1))
                or admission["statement_count"] != len(SCHEMA_STATEMENTS)
                or admission["checksum"] != catalog_checksum(SCHEMA_STATEMENTS)):
            raise CommercialReceiptError("Commercial receipts differ from their original named admission")
        for statement in SCHEMA_STATEMENTS:
            kind, name = statement.split()[1:3]
            row = self.db.one("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind.lower(), name))
            if row is None or " ".join(row["sql"].split()) != " ".join(statement.split()):
                raise CommercialReceiptError("Commercial receipt storage or guards changed")
        return True

    def verify_integrity(self, *, required=True):
        if not self._installed():
            if required:
                raise CommercialReceiptError("Commercial receipt schema has not been admitted")
            return
        if not self.audit.verify_chain()["ok"]:
            raise CommercialReceiptError("Commercial receipt audit chain is broken")
        workspace_id = self.db.mode_status()["workspace_id"]
        rows = {row["id"]: row for row in self.db.query("SELECT * FROM commercial_action_receipts")}
        events = self.db.query("SELECT * FROM audit_log WHERE action=? ORDER BY seq", (RECEIPT_ACTION,))
        if len(events) != len(rows) or {event["entity_id"] for event in events} != set(rows):
            raise CommercialReceiptError("Commercial receipt birth inventory changed")
        for event in events:
            row = rows[event["entity_id"]]
            expected = hash_json({key: value for key, value in row.items() if key != "receipt_hash"})
            try:
                binding = loads(row["binding_json"])
                canonical = all(row[field] == canonical_json(loads(row[field])) for field in ("binding_json", "result_json", "source_json"))
                valid = (canonical and row["workspace_id"] == workspace_id and row["contract_version"] == CONTRACT_VERSION
                         and row["fixed_action"] in ACTIONS and row["receipt_hash"] == expected
                         and event["entity_type"] == RECEIPT_ENTITY and event["actor"] == row["actor_login"]
                         and loads(event["payload_json"]) == {"receipt_hash": expected, "canonical_person_id": row["canonical_person_id"],
                              "fixed_action": row["fixed_action"], "resource_id": row["resource_id"], "outcome": row["outcome"]}
                         and binding["contractVersion"] == CONTRACT_VERSION and binding["fixedAction"] == row["fixed_action"]
                         and binding["resourceId"] == row["resource_id"])
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                raise CommercialReceiptError("Commercial receipt differs from its canonical original audit")

    def find(self, person_id, key):
        self.verify_integrity()
        return self.db.one("SELECT * FROM commercial_action_receipts WHERE canonical_person_id=? AND repeatability_uuid=?", (person_id, key))

    def record(self, *, person_id, actor_login, repeatability_uuid, action, resource_id, binding, result, source,
               outcome="success", http_status=200):
        if not self.db.in_transaction or action not in ACTIONS:
            raise CommercialReceiptError("Commercial receipt must join its fixed local effect transaction")
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
        row = {"id": new_id("cmapi"), "workspace_id": self.db.mode_status()["workspace_id"],
               "canonical_person_id": person_id, "actor_login": actor_login, "repeatability_uuid": repeatability_uuid,
               "contract_version": CONTRACT_VERSION, "fixed_action": action, "resource_id": resource_id,
               "binding_json": canonical_json(binding), "outcome": outcome, "http_status": http_status,
               "result_json": canonical_json(result), "source_json": canonical_json(source), "created_at": utcnow_iso()}
        row["receipt_hash"] = hash_json(row)
        self.audit.record(actor_login, RECEIPT_ACTION, RECEIPT_ENTITY, row["id"],
                          {"receipt_hash": row["receipt_hash"], "canonical_person_id": person_id,
                           "fixed_action": action, "resource_id": resource_id, "outcome": outcome})
        self.db.execute(f"INSERT INTO commercial_action_receipts ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        return row


def commercial_receipt_inventory_proof(db, audit):
    """Pure complete metadata/audit inventory; no domain, AP or provider calls."""
    receipts = CommercialReceipts(db, audit)
    receipts.verify_integrity(required=False)
    if not receipts._installed():
        return []
    return db.query("SELECT * FROM commercial_action_receipts ORDER BY created_at,id")
