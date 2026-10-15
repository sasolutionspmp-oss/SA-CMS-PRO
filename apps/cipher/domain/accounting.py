"""Source-proved synthetic accounting handoff from original bill postings.

This first route emits a synthetic aggregate JournalEntry obligation from the
original installed-work PostingReceipt. It never contacts QuickBooks, infers an
accounting date, nets a correction, pays a bill, or changes Cipher's ledger.
Schema registration is intentionally explicit and must occur after version 69.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import re
import secrets
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ..core.approvals import build_manifest, material_hash
from ..core.db import register_schema_version, SCHEMA_CATALOG
from ..core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow, utcnow_iso
from .bills import CREDIT_NOTE_SOURCE, CREDIT_NOTE_SUBJECT, OP_CREDIT_NOTE, UNPAID_FINAL_INTENT_STATES
from .ledger import lines_fingerprint

SCHEMA_NAME = "accounting_practice_delivery"
DEFER_SCHEMA_REGISTRATION = True
PLUGIN_NAME = "accounting"
OP_QUEUE = "accounting.queue"
SUBJECT_TYPE = "accounting_plan"
ROUTE = "practice.simulated-journal-entry.v1"
ADAPTER = {"name": "simulated-journal-entry", "version": "1"}
DATE_POLICY = "synthetic.period-end.v1"
CONTRACT_VERSION = "cipher.accounting-obligation.v1"
ACCOUNT_MAP = {"5000": "sim-account-installed-cost", "2000": "sim-account-accounts-payable",
               "2050": "sim-account-retainage-payable"}
GOVERNOR = True

class AccountingError(RuntimeError):
    pass

_SPECS = {
    "mapping_versions": ("route TEXT NOT NULL, entity TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0)",
                         "UNIQUE(route,entity,version)", ("route", "entity", "version")),
    "plans": ("project_id TEXT NOT NULL REFERENCES projects(id), bill_id TEXT NOT NULL REFERENCES bills(id), journal_id TEXT NOT NULL REFERENCES journals(id), mapping_id TEXT NOT NULL REFERENCES accounting_mapping_versions(id), logical_operation_id TEXT NOT NULL",
              "UNIQUE(journal_id,mapping_id)", ("project_id", "bill_id", "journal_id", "mapping_id", "logical_operation_id")),
    "intents": ("plan_id TEXT NOT NULL UNIQUE REFERENCES accounting_plans(id), logical_operation_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK(status IN ('queued','submitting','outcome_unknown','simulated_accepted','reconciled','refused'))",
                "", ("plan_id", "logical_operation_id", "status")),
    "leases": ("intent_id TEXT NOT NULL REFERENCES accounting_intents(id)", "", ("intent_id",)),
    "attempts": ("intent_id TEXT NOT NULL REFERENCES accounting_intents(id), lease_id TEXT NOT NULL UNIQUE REFERENCES accounting_leases(id), attempt_no INTEGER NOT NULL CHECK(attempt_no>0)",
                 "UNIQUE(intent_id,attempt_no)", ("intent_id", "lease_id", "attempt_no")),
    "attempt_results": ("intent_id TEXT NOT NULL REFERENCES accounting_intents(id), attempt_id TEXT NOT NULL UNIQUE REFERENCES accounting_attempts(id)",
                        "", ("intent_id", "attempt_id")),
    "acceptances": ("intent_id TEXT NOT NULL UNIQUE REFERENCES accounting_intents(id), provider_ref TEXT NOT NULL UNIQUE",
                    "", ("intent_id", "provider_ref")),
    "reconciliations": ("intent_id TEXT NOT NULL REFERENCES accounting_intents(id), attempt_id TEXT NOT NULL UNIQUE REFERENCES accounting_attempts(id)",
                        "", ("intent_id", "attempt_id")),
}
_BIRTH = {kind: f"accounting.{kind}_recorded" for kind in _SPECS}
_BIRTH["intents"] = "accounting.intent_queued"
SCHEMA_STATEMENTS = []
for _kind, (_extra, _unique, _projected) in _SPECS.items():
    _checks = ", ".join(f"CHECK(json_extract(body_json,'$.{key}') IS {key})" for key in ("id", *_projected))
    SCHEMA_STATEMENTS.append(f"CREATE TABLE accounting_{_kind} (id TEXT PRIMARY KEY, {_extra}, body_json TEXT NOT NULL CHECK(json_valid(body_json)), row_hash TEXT NOT NULL, {_checks}{', '+_unique if _unique else ''})")
for _kind in _SPECS:
    _table = f"accounting_{_kind}"
    SCHEMA_STATEMENTS += [
        f"CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT,'accounting records are append-only'); END",
        f"CREATE TRIGGER {_table}_birth_guard BEFORE INSERT ON {_table} WHEN NOT EXISTS (SELECT 1 FROM audit_log WHERE action='{_BIRTH[_kind]}' AND entity_type='{_table}' AND entity_id=NEW.id AND json_extract(payload_json,'$.rowHash')=NEW.row_hash) BEGIN SELECT RAISE(ABORT,'accounting record requires its original audit'); END",
    ]
    if _kind == "intents":
        SCHEMA_STATEMENTS.append("CREATE TRIGGER accounting_intents_change_guard BEFORE UPDATE ON accounting_intents WHEN NEW.id IS NOT OLD.id OR NEW.plan_id IS NOT OLD.plan_id OR NEW.logical_operation_id IS NOT OLD.logical_operation_id OR NOT EXISTS (SELECT 1 FROM audit_log WHERE action='accounting.intent_changed' AND entity_type='accounting_intents' AND entity_id=NEW.id AND json_extract(payload_json,'$.rowHash')=NEW.row_hash) BEGIN SELECT RAISE(ABORT,'accounting intent changes require their audit'); END")
    else:
        SCHEMA_STATEMENTS.append(f"CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN SELECT RAISE(ABORT,'accounting records are immutable'); END")

def register_accounting_schema() -> int:
    """Explicit registrar; loader must verify the historical 1..69 prefix first."""
    existing = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if existing is not None and existing[0] == 70:
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 69:
        raise AccountingError("accounting schema requires the complete unchanged historical 69-entry catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)

def _cents(value: Any) -> int:
    if isinstance(value, (float, bool)):
        raise AccountingError("binary floating point and booleans are not exact money")
    try:
        d = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise AccountingError("source amounts must be exact finite cents") from exc
    if not d.is_finite() or d * 100 != (d * 100).to_integral_value():
        raise AccountingError("source amounts must be exact finite cents")
    return int(d * 100)

def _money(value: int) -> str:
    return f"{Decimal(value)/100:.2f}"

class Plugin:
    GOVERNOR = True

    def __init__(self, cipher):
        self.c, self.db, self.audit, self.approvals = cipher, cipher.db, cipher.audit, cipher.approvals
        self._savepoint_number = 0
        self._invocations = None
        self._invocation_worker_capability = None

    def bind_invocations(self, store, *, worker_capability):
        """Pin the server's exact initialized invocation store, without effects."""
        from ..ap_accounting_actions import require_invocation_store
        self._worker_capability(worker_capability)
        try:
            require_invocation_store(store, domain=self, worker_capability=worker_capability)
        except Exception as exc:
            raise AccountingError("accounting API invocations require their exact initialized store") from exc
        if self._invocations is not None and self._invocations is not store:
            raise AccountingError("accounting invocation store cannot be replaced in this runtime")
        self._invocations = store
        self._invocation_worker_capability = worker_capability

    def _require_invocation(self, intent, *, invocation_id, actor, purpose, worker_capability):
        if self._invocations is None:
            if invocation_id is not None:
                raise AccountingError("accounting invocation cannot be selected without its bound store")
            return {"invocation_id": None, "invocation_hash": None}
        from ..ap_accounting_actions import require_invocation_store
        require_invocation_store(self._invocations, domain=self, worker_capability=worker_capability)
        if not isinstance(invocation_id, str) or not invocation_id:
            raise AccountingError("accounting API worker requires its original committed invocation")
        reservation = self._invocations.require_claim(invocation_id, intent_id=intent["id"], actor_login=actor,
                                                       logical_operation_id=intent["logical_operation_id"], payload_hash=intent["payload_hash"],
                                                       purpose=purpose, worker_capability=worker_capability)
        binding_hash = reservation.get("binding_hash")
        if not isinstance(binding_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", binding_hash):
            raise AccountingError("the accounting invocation lacks its original binding hash")
        return {"invocation_id": invocation_id, "invocation_hash": binding_hash}

    def _observe_invocation(self, intent, attempt, *, result_id, acceptance_id=None, reconciliation_id=None):
        invocation_id = attempt.get("invocation_id")
        if invocation_id is None:
            if self._invocations is not None:
                raise AccountingError("accounting API observation requires its original invocation-bound attempt")
            return
        if self._invocations is None:
            raise AccountingError("accounting API observation has lost its original bound store")
        from ..ap_accounting_actions import require_invocation_store
        require_invocation_store(self._invocations, domain=self, worker_capability=self._invocation_worker_capability)
        proof = {"intentId": intent["id"], "attemptId": attempt["id"], "invocationId": invocation_id,
                 "payloadHash": intent["payload_hash"], "logicalOperationId": intent["logical_operation_id"],
                 "attemptResultId": result_id, "acceptanceId": acceptance_id, "reconciliationId": reconciliation_id}
        self._invocations.record_observation(invocation_id, attempt_id=attempt["id"], source_proof=proof, safe_result=None)

    def _begin_invocation_observation(self, attempt):
        if attempt.get("invocation_id") is None:
            if self._invocations is not None:
                raise AccountingError("accounting API outcome requires its invocation-bound original attempt")
            return
        if self._invocations is None:
            raise AccountingError("accounting outcome lost its original initialized invocation store")
        from ..ap_accounting_actions import require_invocation_store
        require_invocation_store(self._invocations, domain=self, worker_capability=self._invocation_worker_capability)
        self._invocations.begin_observation(attempt["invocation_id"], attempt_id=attempt["id"])

    @contextmanager
    def _atomic(self):
        self.db.require_practice_mode()
        self.db.require_write_authority()
        with self.db.transaction() as conn:
            self._savepoint_number += 1
            name = f"accounting_act_{self._savepoint_number}"
            conn.execute(f"SAVEPOINT {name}")
            try:
                yield conn
            except BaseException:
                conn.execute(f"ROLLBACK TO {name}")
                conn.execute(f"RELEASE {name}")
                raise
            else:
                conn.execute(f"RELEASE {name}")

    def _guards(self):
        stamp = (self.db.conn.total_changes, self.db.scalar("PRAGMA data_version"), self.db.scalar("PRAGMA schema_version"))
        if stamp == getattr(self, "_verified_stamp", None):
            return
        if not self.audit.verify_chain()["ok"]:
            raise AccountingError("accounting source audit chain is broken")
        for sql in SCHEMA_STATEMENTS:
            match = re.match(r"CREATE TRIGGER (\w+)", sql)
            if match:
                actual = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (match[1],))
                normalize = lambda s: re.sub(r"\s+", " ", s.strip())
                if actual is None or normalize(actual["sql"]) != normalize(sql):
                    raise AccountingError("accounting source storage guards are missing or changed")
        self._verified_stamp = stamp

    def _record(self, kind: str, body: dict[str, Any], *, actor: str):
        table = f"accounting_{kind}"
        row = {"id": body["id"], **{key: body[key] for key in _SPECS[kind][2]}, "body_json": canonical_json(body)}
        row["row_hash"] = hash_json(row)
        self.audit.record(actor, _BIRTH[kind], table, row["id"], {"rowHash": row["row_hash"]})
        keys = list(row)
        self.db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(row[key] for key in keys))
        return body

    def _proof(self, kind: str, identifier: str):
        self._guards()
        table = f"accounting_{kind}"
        row = self.db.one(f"SELECT * FROM {table} WHERE id=?", (identifier,))
        if row is None:
            raise AccountingError(f"missing audited accounting {kind}")
        body = loads(row["body_json"])
        if not isinstance(body, dict) or canonical_json(body) != row["body_json"] or any(body.get(key) != row[key] for key in ("id", *_SPECS[kind][2])):
            raise AccountingError("accounting record differs from its canonical source")
        expected = hash_json({key: value for key, value in row.items() if key != "row_hash"})
        history = self.db.query("SELECT * FROM audit_log WHERE entity_type=? AND entity_id=? AND action IN (?,?) ORDER BY seq", (table, identifier, _BIRTH[kind], "accounting.intent_changed" if kind == "intents" else _BIRTH[kind]))
        if not history or history[0]["action"] != _BIRTH[kind] or row["row_hash"] != expected or loads(history[-1]["payload_json"]).get("rowHash") != expected:
            raise AccountingError("accounting record differs from its original audited source")
        if kind != "intents" and len(history) != 1:
            raise AccountingError("immutable accounting record has repeated birth")
        if kind == "intents":
            previous = None
            legal = {None: {"queued"}, "queued": {"submitting"}, "submitting": {"submitting", "outcome_unknown", "queued", "simulated_accepted", "reconciled", "refused"},
                     "outcome_unknown": {"submitting"}, "simulated_accepted": {"simulated_accepted", "submitting"}, "reconciled": set(), "refused": set()}
            for number, event in enumerate(history):
                snap = loads(event["payload_json"]).get("state")
                if not isinstance(snap, dict) or snap.get("revision") != number or snap.get("status") not in legal[previous] or hash_json(snap) != loads(event["payload_json"]).get("stateHash"):
                    raise AccountingError("accounting intent lifecycle is not its audited chronology")
                if snap.get("plan_id") != body["plan_id"] or snap.get("logical_operation_id") != body["logical_operation_id"]:
                    raise AccountingError("accounting intent original identity changed")
                previous = snap["status"]
            if canonical_json(snap) != canonical_json(body):
                raise AccountingError("accounting intent current state was rolled back")
        return body

    def _inventory(self, kind: str):
        self._guards()
        table = f"accounting_{kind}"
        rows = self.db.query(f"SELECT id FROM {table}")
        births = self.db.query("SELECT entity_id FROM audit_log WHERE action=? AND entity_type=? ORDER BY seq", (_BIRTH[kind], table))
        ids = [row["entity_id"] for row in births]
        if len(ids) != len(set(ids)) or set(ids) != {row["id"] for row in rows}:
            raise AccountingError("accounting record inventory differs from audited births")
        return [self._proof(kind, identifier) for identifier in ids]

    def require_accountant(self, actor: str, project_id: str):
        people = self.c.plugin("people")
        people._require_intact()
        person = people._person_row(actor)
        if (not person or person["kind"] != "person" or person["status"] != "active"
                or people._membership(person["id"], project_id) is None):
            raise AccountingError("accounting delivery requires an active registered project accountant")
        grants = [grant for grant in people._live_grants(person["id"], people._today())
                  if grant["role"] == "accountant" and grant["scope"] == "project" and grant["project_id"] == project_id]
        if not grants:
            raise AccountingError("accounting delivery requires its own actual project accountant grant")
        return {"personId": person["id"], "login": person["login"], "projectId": project_id,
                "grantIds": [grant["id"] for grant in grants]}

    def prepare_synthetic_mapping(self, project_id: str, *, actor: str, reason: str):
        """Append only fixed synthetic refs; never adopts a production chart policy."""
        with self._atomic():
            duty = self.require_accountant(actor, project_id)
            project = self.c.project(project_id)
            existing = [row for row in self._inventory("mapping_versions") if row["entity"] == project["entity"] and row["route"] == ROUTE]
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
                raise AccountingError("a bounded synthetic mapping reason is required")
            body = {"id": new_id("acmap"), "route": ROUTE, "entity": project["entity"], "currency": "USD",
                    "version": len(existing)+1, "previous_id": existing[-1]["id"] if existing else None,
                    "accounts": dict(ACCOUNT_MAP), "projectRefPolicy": "synthetic.project-id.v1", "vendorRefPolicy": "synthetic.party-id.v1",
                    "adapter": dict(ADAPTER), "datePolicy": DATE_POLICY, "mode": "practice", "synthetic": True,
                    "prepared_by": duty["login"], "prepared_at": utcnow_iso(), "reason": reason.strip()}
            body["mapping_hash"] = hash_json(body)
            self._record("mapping_versions", body, actor=duty["login"])
            return body

    def mapping(self, mapping_id: str, *, current: bool = True):
        inventory = self._inventory("mapping_versions")
        selected = next((row for row in inventory if row["id"] == mapping_id), None)
        if selected is None:
            raise AccountingError("the accounting mapping is missing")
        group = [row for row in inventory if row["entity"] == selected["entity"] and row["route"] == selected["route"]]
        previous = None
        for number, row in enumerate(group, 1):
            if (row["version"] != number or row["previous_id"] != previous or row["route"] != ROUTE or row["currency"] != "USD"
                    or row["accounts"] != ACCOUNT_MAP or row["datePolicy"] != DATE_POLICY or row["adapter"] != ADAPTER
                    or row["mode"] != "practice" or row["synthetic"] is not True
                    or row["mapping_hash"] != hash_json({key: value for key, value in row.items() if key != "mapping_hash"})):
                raise AccountingError("accounting synthetic mapping history is invalid")
            previous = row["id"]
        if current and selected["id"] != group[-1]["id"]:
            raise AccountingError("the prepared accounting mapping was superseded")
        return selected

    def _original_invoice_binding(self, approved, bill_id):
        supplier_invoice = approved["bindings"].get("supplier_invoice")
        if supplier_invoice is None:
            return None
        intake = self.c.plugin("ap_intake")
        intake.invoice_proof(supplier_invoice["id"])
        intake.approval_proof(supplier_invoice["approval_id"])
        match = self.approvals.get(supplier_invoice["approval_id"])
        bound = match["manifest"]["bindings"]
        if (match["status"] != "consumed" or match["subject_id"] != supplier_invoice["id"]
                or bound.get("invoice_hash") != supplier_invoice["invoice_hash"]
                or bound.get("invoice_version") != supplier_invoice["current"]["version"]
                or bound.get("evidence_hash") != supplier_invoice["evidence_hash"]
                or (bound.get("bill") or {}).get("id") != bill_id):
            raise AccountingError("original approved supplier invoice binding differs from its consumed matching source")
        return supplier_invoice

    def source(self, bill_id: str, *, require_current: bool = True):
        self.db.require_practice_mode()
        self._guards()
        bill = self.c.bills.get(bill_id)
        checks = self.c.bills.lifecycle_integrity_checks(bill_id)
        if not checks or any(not check["ok"] for check in checks):
            raise AccountingError("the original bill lifecycle source cannot be verified")
        receipt = self.c.bills.posting_receipt(bill_id)
        if receipt is None or len(receipt["journal_ids"]) != 1:
            raise AccountingError("this route requires one original modern PostingReceipt journal")
        business = self.c.bills._business_record(bill)
        approved = loads(business["snapshot_json"])
        immutable = approved["bindings"]["bill_immutable"]
        supplier_invoice = self._original_invoice_binding(approved, bill_id)
        journal = self.c.ledger.journal(receipt["journal_ids"][0])
        project = self.c.project(bill["project_id"])
        original_supplier = approved["bindings"]["supplier_identity"]["party_id"]
        if (approved["bindings"]["project_id"] != bill["project_id"] or original_supplier != bill["supplier_id"]
                or project["entity"] != approved["entity"] or (project.get("currency") or "USD") != approved["currency"]
                or approved["currency"] != "USD" or journal["reversal_of"] is not None
                or any(_cents(immutable[key]) != 0 for key in ("stored_added_this_period", "stored_transferred_this_period"))):
            raise AccountingError("this route supports the original USD installed-work source only")
        if require_current and (bill["status"] != "posted" or journal["reversed_by"] is not None):
            raise AccountingError("corrected, reversed or paid sources cannot start accounting delivery")
        if require_current:
            try:
                self.c.bills._correction_obligation_sources(bill_id)
                intents = self.c.bills._intents(bill_id)
                credits = self.c.bills.credit_notes(bill_id)
            except RuntimeError as exc:
                raise AccountingError("the unpaid/uncredited original source inventory cannot be verified") from exc
            if any(intent["status"] not in UNPAID_FINAL_INTENT_STATES for intent in intents):
                raise AccountingError("the original source has a material payment or active payment intent; this route requires an unpaid bill")
            if any(note["status"] != "cancelled" for note in credits):
                raise AccountingError("the original source has an active supplier credit; this route requires an uncredited bill")
        period = self.c.ledger.period(receipt["period_id"])
        period_birth = self.db.query("SELECT payload_json FROM audit_log WHERE action='period.opened' AND entity_type='period' AND entity_id=?", (period["id"],))
        if (len(period_birth) != 1 or loads(period_birth[0]["payload_json"]) != {
                "name": period["name"], "start": period["start_date"], "end": period["end_date"]}):
            raise AccountingError("the synthetic date policy requires the original audited posting-period dates")
        gross, ap, retainage = (_cents(immutable[key]) for key in ("installed_this_period", "amount_due", "retainage_this_period"))
        if gross <= 0 or ap < 0 or retainage < 0 or ap+retainage != gross:
            raise AccountingError("the original this-period obligation does not balance exactly")
        expected = {"5000": (gross, 0), "2000": (0, ap), "2050": (0, retainage)}
        got = {}
        for line in journal["lines"]:
            code = line["account_code"]
            if code not in expected or code in got or line["project_id"] != bill["project_id"] or line["party_id"] != original_supplier:
                raise AccountingError("the original posting has unsupported accounts or dimensions")
            got[code] = (_cents(line["debit"]), _cents(line["credit"]))
        if got != {code: amounts for code, amounts in expected.items() if any(amounts)}:
            raise AccountingError("the original journal differs from the exact obligation")
        source = {"kind": "bill_posting", "billId": bill_id, "contentHash": immutable["content_hash"],
                  "sourceVersion": journal["source_version"], "postingReceiptId": receipt["id"], "postingReceiptHash": receipt["receipt_hash"],
                  "journalId": journal["id"], "businessApprovalId": business["approval_id"], "businessApprovalRecordId": business["id"],
                  "supplierInvoice": supplier_invoice}
        return {"source": source, "bill": bill, "journal": journal, "approvedSource": approved, "period": period,
                "entity": approved["entity"], "project_id": bill["project_id"], "supplier_id": original_supplier,
                "gross_cost_cents": gross, "net_ap_cents": ap, "retainage_cents": retainage}

    def _payload(self, source, mapping):
        workspace_id = self.db.workspace()["workspace_id"]
        operation_id = str(uuid5(NAMESPACE_URL, f"cipher:{workspace_id}:{ROUTE}:{source['journal']['id']}"))
        return {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "route": ROUTE,
                "logicalOperationId": operation_id, "adapter": dict(ADAPTER),
                "mapping": {"id": mapping["id"], "version": mapping["version"], "hash": mapping["mapping_hash"]},
                "source": source["source"], "entity": source["entity"], "currency": "USD", "datePolicy": DATE_POLICY,
                "transactionDate": source["period"]["end_date"],
                "period": {"id": source["period"]["id"], "startDate": source["period"]["start_date"], "endDate": source["period"]["end_date"]},
                "lines": [{"sourceAccountCode": line["account_code"], "account": mapping["accounts"][line["account_code"]],
                           "debitCents": _cents(line["debit"]), "creditCents": _cents(line["credit"]),
                           "projectRef": f"sim-project-{line['project_id']}", "vendorRef": f"sim-vendor-{line['party_id']}", "memo": line["memo"]}
                          for line in source["journal"]["lines"]]}

    def preparation_preflight(self, bill_id: str, mapping_id: str, *, actor: str):
        """Pure: no new ID, audit, SQL write, simulator or authorization change."""
        with self.db._lock:
            minimal = self.db.one("SELECT commitment_id FROM bills WHERE id=?", (bill_id,))
            if minimal is None:
                raise AccountingError("unknown bill")
            project_id = self.db.scalar("SELECT project_id FROM commitments WHERE id=?", (minimal["commitment_id"],))
            self.require_accountant(actor, project_id)
            source, mapping = self.source(bill_id), self.mapping(mapping_id)
            if mapping["entity"] != source["entity"]:
                raise AccountingError("mapping entity differs from the approved source")
            payload = self._payload(source, mapping)
            intents = self._inventory("intents")
            if any(intent["logical_operation_id"] == payload["logicalOperationId"] for intent in intents):
                raise AccountingError("this original source already has its one accounting delivery intent")
            return {"source": source, "mapping": mapping, "payload": payload, "payload_hash": hash_json(payload)}

    def prepare(self, bill_id: str, mapping_id: str, *, actor: str):
        with self._atomic():
            pre = self.preparation_preflight(bill_id, mapping_id, actor=actor)
            existing = next((plan for plan in self._inventory("plans") if plan["journal_id"] == pre["source"]["journal"]["id"] and plan["mapping_id"] == mapping_id), None)
            if existing:
                return self.plan(existing["id"])
            body = {"id": new_id("acplan"), "workspace_id": self.db.workspace()["workspace_id"], "project_id": pre["source"]["project_id"],
                    "bill_id": bill_id, "journal_id": pre["source"]["journal"]["id"], "mapping_id": mapping_id,
                    "logical_operation_id": pre["payload"]["logicalOperationId"], "payload": pre["payload"], "payload_hash": pre["payload_hash"],
                    "prepared_by": actor, "prepared_at": utcnow_iso()}
            self._record("plans", body, actor=actor)
            return self.plan(body["id"])

    def plan_scope(self, plan_id: str):
        row = self.db.one("SELECT project_id,bill_id FROM accounting_plans WHERE id=?", (plan_id,))
        if row is None:
            raise AccountingError("unknown accounting plan")
        return {"projectId": row["project_id"], "billId": row["bill_id"]}

    def intent_scope(self, intent_id: str):
        row = self.db.one("SELECT p.project_id,p.bill_id,p.id AS plan_id FROM accounting_intents i JOIN accounting_plans p ON p.id=i.plan_id WHERE i.id=?", (intent_id,))
        if row is None:
            raise AccountingError("unknown accounting intent")
        return {"projectId": row["project_id"], "billId": row["bill_id"], "planId": row["plan_id"]}

    def current_mapping(self, project_id: str, *, actor: str):
        self.require_accountant(actor, project_id)
        project = self.c.project(project_id)
        candidates = [mapping for mapping in self._inventory("mapping_versions") if mapping["entity"] == project["entity"] and mapping["route"] == ROUTE]
        if not candidates:
            raise AccountingError("no audited synthetic mapping has been declared for this entity")
        return self.mapping(candidates[-1]["id"])

    def plan_inventory(self, *, project_ids):
        scope = frozenset(project_ids)
        return [self.plan(row["id"]) for row in self._inventory("plans") if row["project_id"] in scope]

    def intent_inventory(self, *, project_ids):
        scope = frozenset(project_ids)
        return [self.intent(row["id"]) for row in self._inventory("intents") if self.plan_scope(row["plan_id"])["projectId"] in scope]

    def approval_inventory(self, *, project_ids):
        self._guards()
        scope = frozenset(project_ids)
        # A deleted original approval must not disappear from the review queue.
        births = []
        for event in self.db.query("SELECT entity_id,payload_json FROM audit_log WHERE action='approval.requested' AND entity_type='approval' ORDER BY seq"):
            payload = loads(event["payload_json"])
            if payload.get("operation") == OP_QUEUE:
                if (payload.get("subject") or {}).get("type") != SUBJECT_TYPE:
                    raise AccountingError("accounting approval has an unsupported original subject")
                births.append((event["entity_id"], payload["subject"]["id"]))
        current = self.db.query("SELECT id FROM approvals WHERE operation=?", (OP_QUEUE,))
        if len({identifier for identifier, _ in births}) != len(births) or {identifier for identifier, _ in births} != {row["id"] for row in current}:
            raise AccountingError("accounting approval inventory differs from its original audited requests")
        self._inventory("plans")
        out = []
        for identifier, plan_id in births:
            if self.plan_scope(plan_id)["projectId"] in scope:
                self.plan(plan_id)
                self.approval_proof(identifier)
                out.append(self.approvals.get(identifier))
        return out

    def plan(self, plan_id: str):
        with self.db._lock:
            row = self._proof("plans", plan_id)
            source, mapping = self.source(row["bill_id"], require_current=False), self.mapping(row["mapping_id"], current=False)
            payload = self._payload(source, mapping)
            if (row["workspace_id"] != self.db.workspace()["workspace_id"] or row["project_id"] != source["project_id"]
                    or row["journal_id"] != source["journal"]["id"] or row["logical_operation_id"] != payload["logicalOperationId"]
                    or row["payload_hash"] != hash_json(payload) or row["payload"] != payload):
                raise AccountingError("accounting plan differs from its immutable original posting and mapping")
            return row

    def queue_preflight(self, plan_id: str):
        with self.db._lock:
            plan = self.plan(plan_id)
            source, mapping = self.source(plan["bill_id"]), self.mapping(plan["mapping_id"])
            if any(intent["logical_operation_id"] == plan["logical_operation_id"] for intent in self._inventory("intents")):
                raise AccountingError("this original source already has its one accounting delivery intent")
            return {"plan": plan, "source": source, "mapping": mapping, "payload": plan["payload"], "payload_hash": plan["payload_hash"]}

    def approval_policy(self, operation, manifest):
        if operation != OP_QUEUE:
            return None
        return {"version": "synthetic.accounting-queue-policy.v1", "route": ROUTE, "adapter": dict(ADAPTER),
                "actualProjectAccountants": True, "distinctRequesterReviewer": True, "datePolicy": DATE_POLICY,
                "providerAdmission": "disposable-memory-practice-only"}

    def check_request(self, operation, manifest, *, actor_role, requested_by):
        if operation != OP_QUEUE:
            return
        if actor_role != "accountant":
            raise AccountingError("accounting queue requires the actual accountant duty")
        self.require_accountant(requested_by, self.plan_scope(manifest["subject"]["id"])["projectId"])
        self.queue_preflight(manifest["subject"]["id"])

    def check_grant(self, approval, *, approver, approver_role):
        if approval["operation"] != OP_QUEUE:
            return
        self.approval_proof(approval["id"])
        if approver_role != "accountant":
            raise AccountingError("accounting queue review requires the actual accountant duty")
        self.require_accountant(approver, self.plan_scope(approval["subject_id"])["projectId"])
        self.require_accountant(approval["requested_by"], self.plan_scope(approval["subject_id"])["projectId"])
        if self.c.plugin("people").same_person(approver, approval["requested_by"]):
            raise AccountingError("accounting queue requires an independent accounting reviewer")
        current = self.c._manifest(OP_QUEUE, approval["subject_id"], "accountant")
        if material_hash(current) != approval["material_hash"] or current.get("governance") != approval["manifest"].get("governance"):
            raise AccountingError("accounting source or governance changed before review")

    def check_execute_preflight(self, approval, manifest, *, actor):
        if approval["operation"] != OP_QUEUE:
            return
        self.approval_proof(approval["id"])
        self.require_accountant(actor, self.plan_scope(approval["subject_id"])["projectId"])
        self.require_accountant(approval["approver"], self.plan_scope(approval["subject_id"])["projectId"])
        if self.c.plugin("people").same_person(approval["requested_by"], approval["approver"]):
            raise AccountingError("accounting queue requires an independent accounting reviewer")
        self.queue_preflight(approval["subject_id"])

    def check_execute(self, approval, manifest, *, actor):
        return self.check_execute_preflight(approval, manifest, actor=actor)

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str):
        if operation != OP_QUEUE or actor_role != "accountant":
            raise AccountingError("only fixed accounting.queue under the accountant duty is available")
        pre = self.queue_preflight(subject_id)
        plan, source, mapping = pre["plan"], pre["source"], pre["mapping"]
        return build_manifest(operation=OP_QUEUE, subject_type=SUBJECT_TYPE, subject_id=subject_id, actor_role=actor_role,
                              amounts={"gross_cost": _money(source["gross_cost_cents"]), "net_ap": _money(source["net_ap_cents"]), "retainage": _money(source["retainage_cents"])},
                              bindings={"project_id": plan["project_id"], "source": source["source"], "plan_id": plan["id"], "payload_hash": plan["payload_hash"],
                                        "logical_operation_id": plan["logical_operation_id"], "mapping_id": mapping["id"], "mapping_hash": mapping["mapping_hash"], "mapping_version": mapping["version"],
                                        "route": ROUTE, "adapter": dict(ADAPTER), "date_policy": DATE_POLICY, "transaction_date": plan["payload"]["transactionDate"],
                                        "effect": "queues one synthetic accounting journal; provider contact is a separate leased worker step"},
                              destination={"kind": "synthetic-simulator", "route": ROUTE, "version": "1"}, entity=source["entity"], currency="USD")

    def approval_proof(self, approval_id: str):
        """Fixed-op original request and complete legal audit chronology."""
        with self.db._lock:
            self._guards()
            ap = self.approvals.get(approval_id)
            manifest = ap["manifest"]
            try:
                expiry, original = parse_iso(ap["expires_at"]), parse_iso(manifest["expires_at"])
                if (expiry.utcoffset() is None or original.utcoffset() is None or expiry > original
                        or ap["operation"] != OP_QUEUE or ap["subject_type"] != SUBJECT_TYPE or ap["actor_role"] != "accountant"
                        or manifest.get("operation") != OP_QUEUE or manifest.get("subject") != {"type": SUBJECT_TYPE, "id": ap["subject_id"]}
                        or manifest.get("actor_role") != "accountant" or manifest.get("nonce") != ap["nonce"] or manifest.get("policy_version") != ap["policy_version"]
                        or hash_json(manifest) != ap["manifest_hash"] or material_hash(manifest) != ap["material_hash"]):
                    raise ValueError("altered original authorization")
                lifecycle = {"approval.requested": "pending", "approval.granted": "granted", "approval.consumed": "consumed", "approval.expired": "expired", "approval.invalidated": "invalidated"}
                legal = {None: {"pending"}, "pending": {"granted", "expired", "invalidated"}, "granted": {"consumed", "expired", "invalidated"}, "consumed": set(), "expired": {"invalidated"}, "invalidated": {"invalidated"}}
                status, request, grant, consume, terminal = None, None, None, None, None
                for event in self.audit.entries(entity_type="approval", entity_id=approval_id):
                    if event["action"] not in lifecycle:
                        continue
                    next_status, payload = lifecycle[event["action"]], loads(event["payload_json"])
                    if next_status not in legal[status]:
                        raise ValueError("illegal authorization lifecycle")
                    status, terminal = next_status, event
                    if status == "pending":
                        request = event
                        if event["actor"] != ap["requested_by"] or payload != {"operation": OP_QUEUE, "subject": manifest["subject"], "manifest_hash": ap["manifest_hash"]}:
                            raise ValueError("altered original request")
                    elif status in ("granted", "consumed"):
                        actor = ap["approver"] if status == "granted" else ap["consumed_by"]
                        if event["actor"] != actor or payload != {"operation": OP_QUEUE, "material_hash": ap["material_hash"]}:
                            raise ValueError("altered human decision")
                        if status == "granted":
                            grant = event
                        else:
                            consume = event
                if request is None or status != ap["status"]:
                    raise ValueError("altered current authorization")
                for event, actor_field, time_field in ((grant, "approver", "granted_at"), (consume, "consumed_by", "consumed_at")):
                    if event is None and (ap[actor_field] is not None or ap[time_field] is not None) or event is not None and (not ap[actor_field] or not ap[time_field]):
                        raise ValueError("altered decision attribution")
                if status == "invalidated":
                    payload = loads(terminal["payload_json"])
                    expected = f"subject changed after approval: {payload['diff']}" if "diff" in payload else payload.get("reason")
                    if expected is None or ap["invalidated_reason"] != expected:
                        raise ValueError("altered invalidation reason")
                elif ap["invalidated_reason"] is not None:
                    raise ValueError("unrecorded invalidation reason")
                for key in ("requested_at", "granted_at", "consumed_at"):
                    if ap[key] is not None and parse_iso(ap[key]).utcoffset() is None:
                        raise ValueError("invalid authorization time")
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise AccountingError("accounting authorization differs from its original audit") from exc
            return {"auditSeq": request["seq"], "auditHash": request["entry_hash"], "manifestHash": ap["manifest_hash"], "materialHash": ap["material_hash"], "requestedBy": ap["requested_by"], "requestedAt": ap["requested_at"]}

    def _intent_change(self, intent, *, actor: str, **changes):
        body = {**intent, **changes, "revision": intent["revision"]+1, "updated_by": actor, "updated_at": utcnow_iso()}
        row = {"id": body["id"], "plan_id": body["plan_id"], "logical_operation_id": body["logical_operation_id"], "status": body["status"], "body_json": canonical_json(body)}
        row["row_hash"] = hash_json(row)
        self.audit.record(actor, "accounting.intent_changed", "accounting_intents", body["id"], {"rowHash": row["row_hash"], "state": body, "stateHash": hash_json(body)})
        self.db.execute("UPDATE accounting_intents SET status=?,body_json=?,row_hash=? WHERE id=?", (body["status"], row["body_json"], row["row_hash"], body["id"]))
        return body

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id=None):
        if operation != OP_QUEUE or period_id is not None:
            raise AccountingError("only fixed queue effect with its original period is available")
        with self._atomic():
            self.require_accountant(actor, self.plan_scope(subject_id)["projectId"])
            pre = self.queue_preflight(subject_id)
            self.approval_proof(approval_id)
            approval = self.approvals.get(approval_id)
            if (approval["status"] != "consumed" or approval["subject_id"] != subject_id or approval["consumed_by"] != actor
                    or approval["material_hash"] != material_hash(manifest) or approval["material_hash"] != material_hash(self.manifest_for(OP_QUEUE, subject_id, actor_role="accountant"))):
                raise AccountingError("queue requires its own consumed exact accounting authorization")
            self.require_accountant(approval["approver"], pre["plan"]["project_id"])
            people = self.c.plugin("people")
            if people.same_person(approval["requested_by"], approval["approver"]):
                raise AccountingError("accounting queue requires an independent registered accounting reviewer")
            body = {"id": new_id("acintent"), "plan_id": subject_id, "logical_operation_id": pre["plan"]["logical_operation_id"],
                    "status": "queued", "revision": 0, "approval_id": approval_id, "payload_hash": pre["payload_hash"],
                    "queued_by": actor, "queued_at": utcnow_iso(), "updated_by": actor, "updated_at": utcnow_iso(),
                    "last_lease_id": None, "active_attempt_id": None, "lookup_required": False, "acceptance_id": None}
            row = {"id": body["id"], "plan_id": subject_id, "logical_operation_id": body["logical_operation_id"], "status": "queued", "body_json": canonical_json(body)}
            row["row_hash"] = hash_json(row)
            self.audit.record(actor, _BIRTH["intents"], "accounting_intents", body["id"], {"rowHash": row["row_hash"], "state": body, "stateHash": hash_json(body)})
            self.db.execute("INSERT INTO accounting_intents(id,plan_id,logical_operation_id,status,body_json,row_hash) VALUES(?,?,?,?,?,?)", tuple(row[key] for key in ("id", "plan_id", "logical_operation_id", "status", "body_json", "row_hash")))
            return {"intent_id": body["id"], "logical_operation_id": body["logical_operation_id"], "status": "queued", "mode": "practice", "synthetic": True}

    def intent(self, intent_id: str):
        row = self._proof("intents", intent_id)
        plan = self.plan(row["plan_id"])
        self.approval_proof(row["approval_id"])
        ap = self.approvals.get(row["approval_id"])
        if (ap["status"] != "consumed" or ap["subject_id"] != plan["id"] or ap["consumed_by"] != row["queued_by"]
                or ap["manifest"]["bindings"].get("payload_hash") != plan["payload_hash"] or row["payload_hash"] != plan["payload_hash"]
                or row["logical_operation_id"] != plan["logical_operation_id"]):
            raise AccountingError("accounting intent is not bound to its original consumed plan")
        self._delivery_history(row)
        return row

    def _delivery_history(self, intent):
        """Complete surviving delivery inventory and final-state source proof.

        Original audited births are checked independently of current pointers,
        including leases that expired without a result. An accepted/reconciled
        label requires its actual recorded acceptance/readback to survive.
        """
        related = {kind: [row for row in self._inventory(kind) if row["intent_id"] == intent["id"]]
                   for kind in ("leases", "attempts", "attempt_results", "acceptances", "reconciliations")}
        leases = {row["id"]: row for row in related["leases"]}
        attempts = related["attempts"]
        invocations = {row["id"]: row for row in self._invocation_inventory()}
        by_attempt = {row["id"]: row for row in attempts}
        results = {row["attempt_id"]: row for row in related["attempt_results"]}
        if len(results) != len(related["attempt_results"]):
            raise AccountingError("an accounting attempt has repeated outcomes")
        if len(leases) != len(attempts) or {row["lease_id"] for row in attempts} != set(leases):
            raise AccountingError("accounting attempt and lease inventory disagree")
        for number, attempt in enumerate(attempts, 1):
            lease = leases.get(attempt["lease_id"])
            if (attempt["attempt_no"] != number or lease is None or attempt["payload_hash"] != intent["payload_hash"]
                    or attempt["created_by"] != lease["claimed_by"] or attempt["purpose"] not in ("submit", "lookup", "read_record")
                    or attempt.get("worker_purpose") not in ("delivery", "lookup", "reconciliation")
                    or attempt["worker_purpose"] == "lookup" and attempt["purpose"] != "lookup"
                    or attempt["worker_purpose"] == "reconciliation" and attempt["purpose"] != "read_record"
                    or attempt["worker_purpose"] == "delivery" and attempt["purpose"] == "read_record"
                    or lease["purpose"] != ("reconciliation" if attempt["purpose"] == "read_record" else "delivery")
                    or parse_iso(lease["expires_at"]) <= parse_iso(lease["claimed_at"])):
                raise AccountingError("accounting attempt differs from its original lease/source")
            invocation_id, invocation_hash = attempt.get("invocation_id"), attempt.get("invocation_hash")
            if invocation_id is None:
                if invocation_hash is not None:
                    raise AccountingError("standalone accounting attempt has an unproven API binding")
            else:
                invocation = invocations.get(invocation_id)
                expected_action = {"delivery": "accounting.deliver", "lookup": "accounting.lookup", "reconciliation": "accounting.reconcile"}[attempt["worker_purpose"]]
                if (invocation is None or invocation["binding_hash"] != invocation_hash or invocation["resource_id"] != intent["id"]
                        or invocation["actor_login"] != attempt["created_by"] or invocation["fixed_action"] != expected_action
                        or invocation["plan_id"] != intent["plan_id"] or invocation["logical_operation_id"] != intent["logical_operation_id"]
                        or invocation["payload_hash"] != intent["payload_hash"] or attempt["id"] not in invocation["attempt_ids"]):
                    raise AccountingError("accounting attempt lost its original audited API invocation")
        if any(result["attempt_id"] not in by_attempt or result["recorded_by"] != by_attempt[result["attempt_id"]]["created_by"] for result in related["attempt_results"]):
            raise AccountingError("accounting outcome has no matching original worker attempt")
        latest = attempts[-1] if attempts else None
        if (intent["last_lease_id"] != (latest["lease_id"] if latest else None)
                or intent["active_attempt_id"] != (latest["id"] if latest and intent["status"] == "submitting" else None)):
            raise AccountingError("accounting intent points outside its latest audited attempt")
        if intent["status"] == "submitting" and (latest is None or latest["id"] in results):
            raise AccountingError("a completed accounting attempt cannot remain submitting")
        accepted = related["acceptances"]
        if len(accepted) > 1 or intent["acceptance_id"] != (accepted[0]["id"] if accepted else None):
            raise AccountingError("accounting intent lost or altered its original acceptance")
        if accepted:
            acceptance = accepted[0]
            self._provider_result(intent, acceptance["result"], expected_status="simulated_accepted")
            if (acceptance["payload_hash"] != intent["payload_hash"] or acceptance["provider_ref"] != acceptance["result"]["recordId"]
                    or acceptance["result_hash"] != hash_json(self._acceptance_facts(acceptance["result"]))):
                raise AccountingError("accounting acceptance differs from the immutable provider record proof")
            accepted_results = [row for row in related["attempt_results"] if row["outcome"] == "simulated_accepted"]
            if (len(accepted_results) != 1 or accepted_results[0]["recorded_by"] != acceptance["recorded_by"]
                    or canonical_json(accepted_results[0]["provider_result"]) != canonical_json(acceptance["result"])):
                raise AccountingError("accounting acceptance has no original successful attempt outcome")
            if intent["status"] not in ("simulated_accepted", "reconciled", "submitting"):
                raise AccountingError("accepted accounting source cannot return to another delivery state")
        elif intent["status"] in ("simulated_accepted", "reconciled"):
            raise AccountingError("accepted accounting intent requires its surviving provider receipt")
        reconciliation_by_attempt = {}
        for reconciliation in related["reconciliations"]:
            attempt = by_attempt.get(reconciliation["attempt_id"])
            result = results.get(reconciliation["attempt_id"])
            if (attempt is None or attempt["purpose"] != "read_record" or result is None or not accepted
                    or reconciliation["acceptance_id"] != accepted[0]["id"] or reconciliation["recorded_by"] != attempt["created_by"]
                    or reconciliation["attempt_id"] in reconciliation_by_attempt):
                raise AccountingError("accounting reconciliation lost its original acceptance/readback attempt")
            reconciliation_by_attempt[reconciliation["attempt_id"]] = reconciliation
            if reconciliation["outcome"] == "matched":
                readback = reconciliation["readback"]
                self._provider_result(intent, readback, expected_status="simulated_accepted")
                if ("payload" not in readback or reconciliation["readback_hash"] != hash_json(readback)
                        or hash_json(self._acceptance_facts(readback)) != accepted[0]["result_hash"]
                        or result["outcome"] != "reconciliation_matched" or canonical_json(result["provider_result"]) != canonical_json(readback)):
                    raise AccountingError("accounting reconciled state differs from its immutable exact readback")
            elif reconciliation["outcome"] == "unavailable":
                if reconciliation["readback"] is not None or result["outcome"] != "reconciliation_unavailable":
                    raise AccountingError("accounting failed readback differs from its preserved disposition")
            elif reconciliation["outcome"] != "conflict":
                raise AccountingError("unknown accounting reconciliation disposition")
        if any(result["outcome"].startswith("reconciliation_") and result["attempt_id"] not in reconciliation_by_attempt for result in related["attempt_results"]):
            raise AccountingError("accounting readback outcome lost its reconciliation checkpoint")
        if latest:
            final = results.get(latest["id"])
            if intent["status"] == "reconciled" and (final is None or final["outcome"] != "reconciliation_matched"):
                raise AccountingError("reconciled accounting intent requires the final exact readback")
            if intent["status"] == "queued" and (final is None or final["outcome"] != "confirmed_missing" or intent["lookup_required"]):
                raise AccountingError("a retry queue requires authoritative original-UUID absence")
            if intent["status"] == "outcome_unknown" and (final is None or final["outcome"] != "outcome_unknown" or not intent["lookup_required"]):
                raise AccountingError("unknown accounting outcome cannot conceal lookup-required recovery")
            if intent["status"] == "refused" and (final is None or final["outcome"] != "refused"):
                raise AccountingError("refused accounting intent lacks its original provider disposition")

    def _invocation_inventory(self):
        exists = self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='ap_accounting_invocations'")
        if exists is None:
            if self.db.one("SELECT 1 AS x FROM audit_log WHERE action='ap.accounting_invocation_reserved' LIMIT 1"):
                raise AccountingError("audited accounting API invocation table disappeared")
            return []
        from ..ap_accounting_actions import invocation_inventory_proof
        try:
            return invocation_inventory_proof(self.db, self.audit)
        except Exception as exc:
            raise AccountingError("accounting API invocation inventory/source cannot be verified") from exc

    def _worker_capability(self, capability):
        from ..accounting_worker import require_worker_capability
        try:
            return require_worker_capability(capability, domain=self)
        except Exception as exc:
            raise AccountingError("worker method requires its private initialized fixed simulator capability") from exc

    def _worker_result(self, capability, intent, result):
        from ..accounting_worker import verify_worker_result
        plan = self.plan(intent["plan_id"])
        try:
            verify_worker_result(capability, domain=self, result=result, payload=plan["payload"],
                                 payload_hash=plan["payload_hash"], logical_id=plan["logical_operation_id"])
        except Exception as exc:
            raise AccountingError("accounting result lacks the retained initialized simulator-store proof") from exc

    def current_guard(self, intent_id: str, *, actor: str, purpose="submit"):
        self.db.require_practice_mode()
        self.db.require_write_authority()
        intent = self.intent(intent_id)
        plan = self.plan(intent["plan_id"])
        duty = self.require_accountant(actor, plan["project_id"])
        approval = self.approvals.get(intent["approval_id"])
        if purpose == "submit":
            self.source(plan["bill_id"])
            self.mapping(plan["mapping_id"])
            self.require_accountant(approval["approver"], plan["project_id"])
            if self.c.plugin("people").same_person(approval["requested_by"], approval["approver"]):
                raise AccountingError("the delivery lacks its independent original reviewer")
            governance = {}
            for name, governor in self.c._governors():
                policy = getattr(governor, "approval_policy", None)
                if policy is not None:
                    facts = policy(OP_QUEUE, approval["manifest"])
                    if facts is not None:
                        governance[name] = facts
            if (governance or None) != approval["manifest"].get("governance"):
                raise AccountingError("the queued accounting source no longer matches its current approval policy")
        elif purpose not in ("lookup", "read_record"):
            raise AccountingError("unknown fixed delivery purpose")
        authority = self.db.authority_status()
        guard = {"workspace": {key: authority[key] for key in ("workspace_id", "authority_epoch", "recovery_epoch", "reconciled_epoch")},
                 "duty": duty, "intentHash": hash_json(intent), "payloadHash": plan["payload_hash"], "purpose": purpose}
        return {"intent": intent, "plan": plan, "payload": plan["payload"], "payload_hash": plan["payload_hash"],
                "logical_operation_id": plan["logical_operation_id"], "guard_fingerprint": hash_json(guard)}

    def worker_preflight(self, intent_id: str, *, actor: str, purpose="delivery"):
        """Exact pure claim eligibility; public DTOs must omit private internals."""
        if purpose not in ("delivery", "lookup", "reconciliation"):
            raise AccountingError("unknown fixed accounting worker purpose")
        with self.db._lock:
            intent = self.intent(intent_id)
            last = self._proof("leases", intent["last_lease_id"]) if intent["last_lease_id"] else None
            if intent["active_attempt_id"] and (last is None or parse_iso(last["expires_at"]) > utcnow()):
                raise AccountingError("the accounting intent still has an active worker lease")
            if purpose == "reconciliation":
                if not intent["acceptance_id"] or intent["status"] not in ("simulated_accepted", "submitting"):
                    raise AccountingError("only a simulated accepted intent can be reconciled")
                provider_purpose, lookup_required = "read_record", False
            else:
                if intent["status"] not in ("queued", "submitting", "outcome_unknown") or intent["acceptance_id"]:
                    raise AccountingError("the accounting intent is not awaiting delivery")
                lookup_required = intent["lookup_required"] or intent["status"] in ("submitting", "outcome_unknown")
                if purpose == "lookup" and not lookup_required:
                    raise AccountingError("only an unresolved original accounting outcome can be looked up")
                provider_purpose = "lookup" if lookup_required else "submit"
            guard = self.current_guard(intent_id, actor=actor, purpose=provider_purpose)
            return {**guard, "worker_purpose": purpose, "provider_purpose": provider_purpose, "lookup_required": lookup_required}

    def claim_intent(self, intent_id: str, *, actor: str, lease_seconds=30, purpose="delivery", worker_capability=None, invocation_id=None):
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 60 or purpose not in ("delivery", "lookup", "reconciliation"):
            raise AccountingError("a bounded fixed worker lease is required")
        with self._atomic():
            self._worker_capability(worker_capability)
            preflight = self.worker_preflight(intent_id, actor=actor, purpose=purpose)
            intent = preflight["intent"]
            invocation = self._require_invocation(intent, invocation_id=invocation_id, actor=actor, purpose=purpose, worker_capability=worker_capability)
            leases = self._inventory("leases")
            attempts = self._inventory("attempts")
            self._inventory("attempt_results")
            self._inventory("acceptances")
            self._inventory("reconciliations")
            provider_purpose, lookup_required, guard = preflight["provider_purpose"], preflight["lookup_required"], preflight
            now = utcnow_iso()
            lease = {"id": new_id("aclease"), "intent_id": intent_id, "token": secrets.token_hex(24), "purpose": "reconciliation" if purpose == "reconciliation" else "delivery",
                     "claimed_by": actor, "claimed_at": now, "expires_at": (utcnow()+timedelta(seconds=lease_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")}
            self._record("leases", lease, actor=actor)
            number = len([attempt for attempt in attempts if attempt["intent_id"] == intent_id])+1
            attempt = {"id": new_id("acattempt"), "intent_id": intent_id, "lease_id": lease["id"], "attempt_no": number,
                       "purpose": provider_purpose, "worker_purpose": purpose, "payload_hash": guard["payload_hash"], "created_by": actor, "created_at": now, **invocation}
            self._record("attempts", attempt, actor=actor)
            intent = self._intent_change(intent, actor=actor, status="submitting", last_lease_id=lease["id"], active_attempt_id=attempt["id"], lookup_required=lookup_required)
            if self._invocations is not None:
                self._invocations.record_claim(invocation["invocation_id"], attempt_id=attempt["id"], phase=provider_purpose, lease_id=lease["id"])
            current = self.current_guard(intent_id, actor=actor, purpose=provider_purpose)
            return {"intent_id": intent_id, "lease_token": lease["token"], "attempt_id": attempt["id"], "state": "simulated_accepted" if provider_purpose == "read_record" else intent["status"],
                    "lookup_required": lookup_required, "payload": current["payload"], "payload_hash": current["payload_hash"],
                    "logical_operation_id": current["logical_operation_id"], "guard_fingerprint": current["guard_fingerprint"], "actor": actor, **invocation}

    def _lease_context(self, intent_id, token, actor):
        intent = self.intent(intent_id)
        if not intent["last_lease_id"] or not intent["active_attempt_id"]:
            raise AccountingError("intent has no active leased attempt")
        lease = self._proof("leases", intent["last_lease_id"])
        attempt = self._proof("attempts", intent["active_attempt_id"])
        if (lease["intent_id"] != intent_id or attempt["intent_id"] != intent_id or attempt["lease_id"] != lease["id"]
                or lease["claimed_by"] != actor or not isinstance(token, str) or not secrets.compare_digest(lease["token"], token)):
            raise AccountingError("worker lease does not belong to this exact attempt and actor")
        return intent, lease, attempt

    def recheck_lease(self, intent_id: str, lease_token: str):
        try:
            intent = self.intent(intent_id)
            lease = self._proof("leases", intent["last_lease_id"])
            return bool(intent["active_attempt_id"] and secrets.compare_digest(lease["token"], lease_token) and parse_iso(lease["expires_at"]) > utcnow())
        except (AccountingError, TypeError, KeyError):
            return False

    def delivery_preflight(self, intent_id: str, *, actor: str, lease_token: str, purpose="submit"):
        with self.db._lock:
            guard = self.current_guard(intent_id, actor=actor, purpose=purpose)
            intent, lease, attempt = self._lease_context(intent_id, lease_token, actor)
            invocation = self._require_invocation(intent, invocation_id=attempt.get("invocation_id"), actor=actor,
                                                  purpose=attempt["worker_purpose"],
                                                  worker_capability=self._invocation_worker_capability) if self._invocations is not None else {"invocation_id": None, "invocation_hash": None}
            if (attempt.get("invocation_id"), attempt.get("invocation_hash")) != (invocation["invocation_id"], invocation["invocation_hash"]):
                raise AccountingError("worker attempt lost its original API invocation binding")
            if (parse_iso(lease["expires_at"]) <= utcnow() or attempt["purpose"] != purpose
                    or intent["status"] != "submitting" or purpose == "submit" and intent["lookup_required"]
                    or purpose == "lookup" and not intent["lookup_required"]
                    or purpose == "read_record" and not intent["acceptance_id"]):
                raise AccountingError("worker purpose, unresolved outcome or lease changed")
            return {"intent_id": intent_id, "attempt_id": attempt["id"], "lease_token": lease_token,
                    "state": "simulated_accepted" if purpose == "read_record" else intent["status"], "lookup_required": intent["lookup_required"],
                    "payload": guard["payload"], "payload_hash": guard["payload_hash"], "logical_operation_id": guard["logical_operation_id"],
                    "guard_fingerprint": guard["guard_fingerprint"], "purpose": purpose, "actor": actor, "mode": "practice", "synthetic": True,
                    "writable": True, "restored_quarantine": False, **invocation}

    def transaction_open(self):
        return bool(self.db.in_transaction or self.db.conn.in_transaction)

    @contextmanager
    def delivery_boundary(self, intent_id: str, *, actor: str, lease_token: str, purpose="submit"):
        """Bounded simulator-only, single-memory-runtime reservation.

        A Python lock does not reserve another process's SQLite connection. Until
        a real shared reservation exists this provider admission is memory-only.
        """
        if not self.db.in_memory:
            raise AccountingError("this first simulator worker admits disposable memory practice workspaces only")
        with self.db._lock:
            if self.db.in_transaction or self.db.conn.in_transaction:
                raise AccountingError("provider calls require committed queue and no SQLite transaction")
            context = self.delivery_preflight(intent_id, actor=actor, lease_token=lease_token, purpose=purpose)
            yield context

    def _provider_result(self, intent, result, *, expected_status):
        plan = self.plan(intent["plan_id"])
        expected_keys = {"status", "mode", "synthetic", "simulation", "route", "logicalOperationId", "payloadHash", "quickBooksAccepted"}
        if expected_status == "simulated_accepted":
            expected_keys |= {"recordId", "recordVersion", "recordHash", "duplicateAcknowledgement"}
            if isinstance(result, dict) and "payload" in result:
                expected_keys.add("payload")
        if (not isinstance(result, dict) or result.get("status") != expected_status or result.get("mode") != "practice"
                or set(result) != expected_keys or result.get("quickBooksAccepted") is not False
                or result.get("synthetic") is not True or result.get("simulation") is not True
                or result.get("route") != ROUTE or result.get("logicalOperationId") != plan["logical_operation_id"]
                or result.get("payloadHash") != plan["payload_hash"]):
            raise AccountingError("provider result does not identify this exact synthetic operation")
        if expected_status == "simulated_accepted":
            record_id = "SIM-JE-"+sha256(plan["logical_operation_id"].encode()).hexdigest()[:24]
            record_hash = hash_json({"logicalOperationId": plan["logical_operation_id"], "payloadHash": plan["payload_hash"], "recordVersion": "1", "payload": plan["payload"]})
            if (result.get("recordId") != record_id or result.get("recordVersion") != "1" or result.get("recordHash") != record_hash
                    or type(result.get("duplicateAcknowledgement")) is not bool or "payload" in result and canonical_json(result["payload"]) != canonical_json(plan["payload"])):
                raise AccountingError("provider acceptance differs from this exact synthetic record")
        return result

    @staticmethod
    def _acceptance_facts(result):
        return {key: value for key, value in result.items() if key not in ("payload", "duplicateAcknowledgement")}

    def finish_attempt(self, intent_id: str, lease_token: str, *, outcome: str, provider_result=None, error_code="", actor: str, worker_capability=None):
        """Record the original external fact in a separate local transaction.

        Does not re-require current source eligibility: a correction after a call
        cannot erase an actual simulator acceptance or justify a second UUID.
        Superseded lease completions are refused and recovered by UUID lookup.
        """
        if outcome not in ("simulated_accepted", "outcome_unknown", "confirmed_missing", "refused") or not isinstance(error_code, str) or len(error_code) > 100:
            raise AccountingError("unknown or unsafe worker disposition")
        with self._atomic():
            self._worker_capability(worker_capability)
            intent, lease, attempt = self._lease_context(intent_id, lease_token, actor)
            self.require_accountant(actor, self.plan(intent["plan_id"])["project_id"])
            self._begin_invocation_observation(attempt)
            if attempt["purpose"] == "read_record":
                if outcome not in ("outcome_unknown", "refused") or not intent["acceptance_id"]:
                    raise AccountingError("accepted readback failures cannot create another delivery disposition")
                reconciliation = self._record("reconciliations", {"id": new_id("acreconcile"), "intent_id": intent_id, "attempt_id": attempt["id"],
                                                  "acceptance_id": intent["acceptance_id"], "outcome": "unavailable", "readback": None,
                                                  "error_code": error_code, "recorded_by": actor, "recorded_at": utcnow_iso()}, actor=actor)
                result = self._record("attempt_results", {"id": new_id("acresult"), "intent_id": intent_id, "attempt_id": attempt["id"], "outcome": "reconciliation_unavailable",
                                                  "provider_result": None, "error_code": error_code, "recorded_by": actor, "recorded_at": utcnow_iso()}, actor=actor)
                updated = self._intent_change(intent, actor=actor, status="simulated_accepted", active_attempt_id=None)
                self._observe_invocation(updated, attempt, result_id=result["id"], acceptance_id=intent["acceptance_id"], reconciliation_id=reconciliation["id"])
                return updated
            if outcome == "simulated_accepted":
                self._worker_result(worker_capability, intent, provider_result)
                result = self._provider_result(intent, provider_result, expected_status="simulated_accepted")
                accepted = {"id": new_id("acaccept"), "intent_id": intent_id, "provider_ref": result["recordId"], "payload_hash": intent["payload_hash"],
                            "result": result, "result_hash": hash_json(self._acceptance_facts(result)), "recorded_by": actor, "recorded_at": utcnow_iso()}
                self._record("acceptances", accepted, actor=actor)
                status, lookup_required, acceptance_id = "simulated_accepted", False, accepted["id"]
            elif outcome == "confirmed_missing":
                if attempt["purpose"] != "lookup":
                    raise AccountingError("only bounded lookup may confirm missing; submit is never presumed absent")
                result = self._provider_result(intent, provider_result, expected_status="simulated_missing")
                self._worker_result(worker_capability, intent, provider_result)
                status, lookup_required, acceptance_id = "queued", False, None
            elif outcome == "outcome_unknown":
                result = None
                status, lookup_required, acceptance_id = "outcome_unknown", True, None
            else:
                result = None
                status, lookup_required, acceptance_id = "refused", False, None
            body = {"id": new_id("acresult"), "intent_id": intent_id, "attempt_id": attempt["id"], "outcome": outcome,
                    "provider_result": result, "error_code": error_code, "recorded_by": actor, "recorded_at": utcnow_iso()}
            self._record("attempt_results", body, actor=actor)
            updated = self._intent_change(intent, actor=actor, status=status, lookup_required=lookup_required, acceptance_id=acceptance_id, active_attempt_id=None)
            self._observe_invocation(updated, attempt, result_id=body["id"], acceptance_id=acceptance_id)
            return updated

    def reconcile(self, intent_id: str, *, provider_result: dict, actor: str, lease_token: str, worker_capability=None):
        with self._atomic():
            self._worker_capability(worker_capability)
            intent, lease, attempt = self._lease_context(intent_id, lease_token, actor)
            self.require_accountant(actor, self.plan(intent["plan_id"])["project_id"])
            self._begin_invocation_observation(attempt)
            if attempt["purpose"] != "read_record" or not intent["acceptance_id"]:
                raise AccountingError("reconciliation requires its own accepted record readback lease")
            acceptance = self._proof("acceptances", intent["acceptance_id"])
            result = self._provider_result(intent, provider_result, expected_status="simulated_accepted")
            self._worker_result(worker_capability, intent, result)
            if "payload" not in result or hash_json(self._acceptance_facts(result)) != acceptance["result_hash"]:
                outcome, status = "conflict", "simulated_accepted"
            else:
                outcome, status = "matched", "reconciled"
            body = {"id": new_id("acreconcile"), "intent_id": intent_id, "attempt_id": attempt["id"], "acceptance_id": acceptance["id"],
                    "outcome": outcome, "readback": result, "readback_hash": hash_json(result), "recorded_by": actor, "recorded_at": utcnow_iso()}
            self._record("reconciliations", body, actor=actor)
            result_body = self._record("attempt_results", {"id": new_id("acresult"), "intent_id": intent_id, "attempt_id": attempt["id"], "outcome": f"reconciliation_{outcome}",
                                              "provider_result": result, "error_code": "", "recorded_by": actor, "recorded_at": utcnow_iso()}, actor=actor)
            updated = self._intent_change(intent, actor=actor, status=status, active_attempt_id=None)
            self._observe_invocation(updated, attempt, result_id=result_body["id"], acceptance_id=acceptance["id"], reconciliation_id=body["id"])
            return updated

    def _journal_inventory(self):
        """Audited births anchor periods/source attribution before close filters."""
        events = self.db.query("SELECT * FROM audit_log WHERE action='journal.posted' AND entity_type='journal' ORDER BY seq")
        ids = [event["entity_id"] for event in events]
        rows = self.db.query("SELECT id FROM journals")
        if len(ids) != len(set(ids)) or set(ids) != {row["id"] for row in rows}:
            raise AccountingError("accounting journal inventory differs from its original audited postings")
        journals = []
        for event in events:
            journal, payload = self.c.ledger.journal(event["entity_id"]), loads(event["payload_json"])
            fields = ("period_id", "source_type", "source_id", "source_version", "approval_id", "reversal_of", "line_count")
            debit = sum(_cents(line["debit"]) for line in journal["lines"])
            credit = sum(_cents(line["credit"]) for line in journal["lines"])
            if (any(payload.get(field) != journal.get(field) for field in fields) or event["actor"] != journal["posted_by"]
                    or not journal["lines"] or debit <= 0 or debit != credit or _cents(payload["total"]) != debit
                    or journal["line_count"] is not None and journal["line_count"] != len(journal["lines"])):
                raise AccountingError("accounting journal period/source differs from its original posting")
            journals.append(journal)
        return journals

    def _bill_scope_source(self, bill_id):
        """Original financial scope; unsupported adjustments never use a new entity."""
        bill = self.c.bills.get(bill_id)
        if any(not check["ok"] for check in self.c.bills.lifecycle_integrity_checks(bill_id)):
            raise AccountingError("the adjustment's original bill lifecycle cannot be verified")
        self.c.bills.posting_receipt(bill_id)
        if bill.get("business_approval_id"):
            approved = loads(self.c.bills._business_record(bill)["snapshot_json"])
            self._original_invoice_binding(approved, bill_id)
            entity = approved["entity"]
        else:
            project_birth = self.db.query("SELECT payload_json FROM audit_log WHERE action='project.created' AND entity_type='project' AND entity_id=?", (bill["project_id"],))
            if len(project_birth) != 1:
                raise AccountingError("the legacy adjustment needs its original project entity proof")
            entity = loads(project_birth[0]["payload_json"])["entity"]
        if self.c.project(bill["project_id"])["entity"] != entity:
            raise AccountingError("the adjustment's current project differs from its original entity")
        return bill, entity

    def _credit_adjustment_proof(self, note_id, journal):
        """Verify an unsupported credit's actual posting, without authorizing one."""
        note = self.c.bills.credit_note(note_id)
        bill, entity = self._bill_scope_source(note["bill_id"])
        self.c.bills._correction_obligation_sources(bill["id"])
        ap = self.approvals.get(note["approval_id"])
        manifest, bound = ap["manifest"], ap["manifest"].get("bindings", {})
        events = self.audit.entries(entity_type="approval", entity_id=ap["id"])
        lifecycle = [event for event in events if event["action"] in ("approval.requested", "approval.granted", "approval.consumed", "approval.expired", "approval.invalidated")]
        if (tuple(event["action"] for event in lifecycle) != ("approval.requested", "approval.granted", "approval.consumed")
                or ap["status"] != "consumed" or ap["operation"] != OP_CREDIT_NOTE or ap["subject_type"] != CREDIT_NOTE_SUBJECT or ap["subject_id"] != note_id
                or manifest.get("operation") != OP_CREDIT_NOTE or manifest.get("subject") != {"type": CREDIT_NOTE_SUBJECT, "id": note_id}
                or hash_json(manifest) != ap["manifest_hash"] or material_hash(manifest) != ap["material_hash"]
                or manifest.get("nonce") != ap["nonce"] or manifest.get("actor_role") != ap["actor_role"] or manifest.get("policy_version") != ap["policy_version"]
                or parse_iso(ap["expires_at"]) > parse_iso(manifest["expires_at"])):
            raise AccountingError("the credit adjustment lacks its original consumed authorization")
        for event, actor, payload in (
                (lifecycle[0], ap["requested_by"], {"operation": OP_CREDIT_NOTE, "subject": manifest["subject"], "manifest_hash": ap["manifest_hash"]}),
                (lifecycle[1], ap["approver"], {"operation": OP_CREDIT_NOTE, "material_hash": ap["material_hash"]}),
                (lifecycle[2], ap["consumed_by"], {"operation": OP_CREDIT_NOTE, "material_hash": ap["material_hash"]})):
            if event["actor"] != actor or loads(event["payload_json"]) != payload:
                raise AccountingError("the credit adjustment authorization differs from its original decision")
        posted = self.db.query("SELECT * FROM audit_log WHERE action='bill.credit_note_posted' AND entity_type=? AND entity_id=?", (CREDIT_NOTE_SUBJECT, note_id))
        if (len(posted) != 1 or note["status"] != "posted" or note["journal_id"] != journal["id"] or note["period_id"] != journal["period_id"]
                or note["posted_by"] != ap["consumed_by"] or journal["posted_by"] != note["posted_by"] or posted[0]["actor"] != note["posted_by"]
                or manifest.get("entity") != entity or bound.get("bill_id") != bill["id"] or bound.get("bill_hash") != bill["content_hash"]
                or manifest.get("amounts", {}).get("credit") != note["amount"]
                or any(bound.get(field) != note[field] for field in ("reason", "evidence_hash", "evidence_document_id", "evidence_revision_id"))
                or journal["approval_id"] != note["approval_id"] or journal["source_version"] != "1" or journal["reversal_of"] is not None):
            raise AccountingError("the credit adjustment differs from its original approved posting")
        payload = loads(posted[0]["payload_json"])
        if any(payload.get(field) != value for field, value in {"bill_id": bill["id"], "amount": note["amount"], "journal_id": journal["id"], "period_id": journal["period_id"], "approval_id": note["approval_id"]}.items()):
            raise AccountingError("the credit adjustment period/source differs from its audited posting")
        expected = [{"line_no": number, "account_code": line["account"], **{field: line[field] for field in ("debit", "credit", "project_id", "party_id", "memo")}}
                    for number, line in enumerate(bound.get("journal_preview", []), 1)]
        if not expected or lines_fingerprint(journal["lines"]) != lines_fingerprint(expected):
            raise AccountingError("the credit adjustment journal differs from its approved lines")
        return note, bill, entity

    def _period_adjustments(self, period_id, active_entities):
        unsupported = []
        journals = self._journal_inventory()
        # Cross-period obligations belong to their own actual journal period,
        # even when the original bill's prior-period handoff is reconciled.
        for journal in journals:
            if journal["period_id"] != period_id:
                continue
            if journal["source_type"] == "bill" and journal["reversal_of"] is not None:
                bill, entity = self._bill_scope_source(journal["source_id"])
                correction = self.c.bills.corrected_bill_proof(bill["id"])
                if journal["id"] not in correction["reversal_journals"] or correction["period_id"] != period_id:
                    raise AccountingError("the adjustment is not its own governed bill reversal")
                if entity in active_entities:
                    unsupported.append({"kind": "bill_correction", "sourceId": correction["id"], "billId": bill["id"], "journalId": journal["id"], "periodId": period_id,
                                        "originalJournalId": journal["reversal_of"], "requiresReview": True, "reason": "the practice route cannot deliver an inverse obligation; original delivery is retained"})
            elif journal["source_type"] == CREDIT_NOTE_SOURCE:
                note, bill, entity = self._credit_adjustment_proof(journal["source_id"], journal)
                if entity in active_entities:
                    unsupported.append({"kind": "supplier_credit_note", "sourceId": note["id"], "billId": bill["id"], "journalId": journal["id"], "periodId": period_id,
                                        "requiresReview": True, "reason": "the practice route cannot deliver a supplier credit obligation; original delivery is retained"})
        return unsupported

    def close_checks(self, period_id: str):
        checks = []
        try:
            inventory = {kind: self._inventory(kind) for kind in _SPECS}
            self._invocation_inventory()
            # Installing an empty practice plugin does not adopt an external
            # accounting close policy. Audited declarations activate only their
            # local synthetic entity scope; deleted declarations cannot hide it.
            if not inventory["mapping_versions"] and not inventory["plans"]:
                if any(inventory[kind] for kind in ("intents", "leases", "attempts", "attempt_results", "acceptances", "reconciliations")):
                    raise AccountingError("accounting delivery records exist without their original mapping/plan")
                return []
            active_entities = {mapping["entity"] for mapping in inventory["mapping_versions"]}
            self.approval_inventory(project_ids=tuple(project["id"] for project in self.c.projects()))
            for mapping in inventory["mapping_versions"]:
                self.mapping(mapping["id"], current=False)
            for plan in inventory["plans"]:
                self.plan(plan["id"])
            for intent in inventory["intents"]:
                self.intent(intent["id"])
            # Audit birth inventory catches deletion of a bill/receipt even if no
            # accounting plan has been prepared for it yet.
            receipts = self.db.query("SELECT bill_id FROM bill_posting_receipts WHERE period_id=?", (period_id,))
            events = self.db.query("SELECT entity_id,payload_json FROM audit_log WHERE action='bill.posting_receipt_recorded' AND entity_type='bill'")
            receipt_ids = {row["bill_id"] for row in receipts}
            audited_ids = set()
            for event in events:
                payload = loads(event["payload_json"])
                receipt = self.db.one("SELECT bill_id,period_id FROM bill_posting_receipts WHERE id=?", (payload.get("receipt_id"),))
                if receipt is None:
                    raise AccountingError("an audited posting receipt disappeared before accounting preparation")
                if receipt["period_id"] == period_id:
                    audited_ids.add(event["entity_id"])
            if receipt_ids != audited_ids:
                raise AccountingError("accounting original posting inventory differs from its audit")
            mapped_sources, unsupported = set(), self._period_adjustments(period_id, active_entities)
            for bill_id in sorted(receipt_ids):
                bill = self.c.bills.get(bill_id)
                business = self.c.bills._business_record(bill)
                approved = loads(business["snapshot_json"])
                if approved["entity"] not in active_entities:
                    continue
                mapped_sources.add(bill_id)
                try:
                    self.source(bill_id)
                except (AccountingError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                    unsupported.append({"billId": bill_id, "state": bill["status"], "reason": str(exc), "requiresReview": True})
            relevant = [intent for intent in inventory["intents"] if self.plan(intent["plan_id"])["payload"]["period"]["id"] == period_id]
            pending = [intent["id"] for intent in relevant if intent["status"] != "reconciled"]
            covered = {self.plan(intent["plan_id"])["bill_id"] for intent in relevant}
            unprepared = sorted(mapped_sources-covered)
            checks += [{"check": "synthetic accounting source integrity", "ok": True, "detail": "immutable source, mapping, plan and delivery audit inventories agree"},
                       {"check": "synthetic accounting delivery disposition", "ok": not pending and not unprepared and not unsupported,
                        "detail": {"pendingIntentIds": pending, "postedSourcesWithoutIntent": unprepared, "unsupportedSources": unsupported, "mode": "practice", "synthetic": True}}]
        except (AccountingError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            checks.append({"check": "synthetic accounting source integrity", "ok": False, "detail": str(exc)})
        return checks

    def state(self, project_id: str):
        plans = [self.plan(row["id"]) for row in self._inventory("plans") if row["project_id"] == project_id]
        plan_ids = {plan["id"] for plan in plans}
        intents = [self.intent(row["id"]) for row in self._inventory("intents") if row["plan_id"] in plan_ids]
        return {"mode": "practice", "synthetic": True, "route": ROUTE, "plans": plans, "intents": intents,
                "deliveryAdmission": "disposable-memory-practice-only"}

    def export(self):
        # Leases intentionally exclude their private token from ordinary exports.
        out = {kind: self._inventory(kind) for kind in _SPECS}
        self._invocation_inventory()
        for mapping in out["mapping_versions"]:
            self.mapping(mapping["id"], current=False)
        for plan in out["plans"]:
            self.plan(plan["id"])
        for intent in out["intents"]:
            self.intent(intent["id"])
        out["leases"] = [{key: value for key, value in row.items() if key != "token"} for row in out["leases"]]
        diagnostics = {period["id"]: self.close_checks(period["id"]) for period in self.c.ledger.periods()}
        return {"mode": "practice", "synthetic": True, "route": ROUTE, "records": out, "diagnostics": diagnostics}
