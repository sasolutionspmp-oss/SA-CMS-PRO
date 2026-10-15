"""Owned synthetic owner billing sources and independent AR posting.

Import registers no SQL. Schema74 follows the actual unchanged73-entry catalog.
The fixed basis is a synthetic declaration, never owner award or engineer adoption.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
import re
from typing import Any

from ..core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from ..core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow, utcnow_iso
from ..core.money import fmt
from .owner_billing_calculation import OwnerSOVLine, OwnerProgressLine, calculate_owner_pay_app

PLUGIN_NAME = "owner_billing"
SCHEMA_NAME = "owner_billing_sources_and_posting"
DEFER_SCHEMA_REGISTRATION = True
APPROVAL_FLOW = "owner-bill.business-grant-independent-post/1"
DATE_POLICY = "practice.invoice-date.period-start.v1"
FIXED_SOV = (
    OwnerSOVLine("U1", "Installed owner bid-item sheet piles", "unitPrice", 10_000_000,
                 unit="EA", contract_quantity="100", unit_price_cents=100_000),
    OwnerSOVLine("L2", "Owner dewatering lump sum", "lumpSum", 15_000_000),
)
_SPECS = {
    "bases": ("project_id TEXT NOT NULL REFERENCES projects(id), customer_id TEXT NOT NULL REFERENCES parties(id), version INTEGER NOT NULL CHECK(version>0)",
              ("project_id", "customer_id", "version"), "UNIQUE(project_id,version)"),
    "sources": ("prime_bill_id TEXT NOT NULL UNIQUE REFERENCES prime_bills(id), project_id TEXT NOT NULL REFERENCES projects(id), basis_id TEXT NOT NULL REFERENCES owner_billing_bases(id)",
                ("prime_bill_id", "project_id", "basis_id"), ""),
    "grants": ("prime_bill_id TEXT NOT NULL REFERENCES prime_bills(id), project_id TEXT NOT NULL REFERENCES projects(id), approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id)",
               ("prime_bill_id", "project_id", "approval_id"), ""),
    "postings": ("prime_bill_id TEXT NOT NULL UNIQUE REFERENCES prime_bills(id), project_id TEXT NOT NULL REFERENCES projects(id), approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id)",
                 ("prime_bill_id", "project_id", "approval_id"), ""),
}
SCHEMA_STATEMENTS = []
for _kind, (_fields, _keys, _unique) in _SPECS.items():
    _checks = ", ".join(f"CHECK(json_extract(body_json,'$.{key}') IS {key})" for key in ("id", *_keys))
    SCHEMA_STATEMENTS.append(f"CREATE TABLE owner_billing_{_kind} (id TEXT PRIMARY KEY, {_fields}, body_json TEXT NOT NULL CHECK(json_valid(body_json)), row_hash TEXT NOT NULL, {_checks}{', '+_unique if _unique else ''})")
for _kind in _SPECS:
    _table = f"owner_billing_{_kind}"
    SCHEMA_STATEMENTS.extend((
        f"CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN SELECT RAISE(ABORT,'owner billing sources are immutable'); END",
        f"CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT,'owner billing sources are append-only'); END",
        f"CREATE TRIGGER {_table}_birth BEFORE INSERT ON {_table} BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM {_table} WHERE id=NEW.id) THEN RAISE(ABORT,'owner billing source cannot be replaced') END; SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='owner_billing.{_kind}_recorded' AND entity_type='{_table}' AND entity_id=NEW.id AND json_extract(payload_json,'$.rowHash')=NEW.row_hash) THEN RAISE(ABORT,'owner billing source needs its original audit') END; END",
    ))


class OwnerBillingError(ApprovalError):
    pass


def register_owner_billing_schema():
    existing = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if existing is not None:
        if existing[0] != 74:
            raise OwnerBillingError("owner billing must retain catalog position74")
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 73 or SCHEMA_CATALOG[-1][1] != "commercial_practice_action_receipts":
        raise OwnerBillingError("owner billing requires the actual unchanged73-entry catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)


def _same(left, right):
    return canonical_json(left) == canonical_json(right)


def _text(value, label, maximum=1000, *, empty=False):
    if type(value) is not str or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise OwnerBillingError(f"{label} must be bounded plain text")
    value = value.strip()
    if not value and not empty:
        raise OwnerBillingError(f"{label} is required")
    return value


def _ref(event):
    return {"seq": event["seq"], "hash": event["entry_hash"]}


def require_owner_billing_duty(cipher, actor, project_id, duty):
    """Pure actual-person authority; no owner wildcard or delegation inheritance."""
    if duty not in ("pm", "accounting", "send"):
        raise OwnerBillingError("unsupported fixed owner billing duty")
    cipher.db.require_practice_mode()
    people = cipher.plugin("people")
    people._require_intact()
    policy = people.current_policy()
    if not policy or not policy["intact"] or not policy["enforce"] or not policy["segregate"] or policy["solo_owner_self_approval"]:
        raise OwnerBillingError("owner billing requires segregated registered practice people")
    person = people._person_row(actor)
    if (person is None or person["kind"] != "person" or person["status"] != "active"
            or person.get("external") or people._membership(person["id"], project_id) is None):
        raise OwnerBillingError("owner billing requires an active internal registered project person")
    roles = {"pm"} if duty == "pm" else {"accountant", "controller"} if duty == "accounting" else {"pm", "accountant"}
    grants = [row for row in people._live_grants(person["id"], people._today())
              if row["role"] in roles and row["scope"] == "project" and row["project_id"] == project_id]
    if not grants:
        raise OwnerBillingError(f"owner billing requires its own actual project {duty} grant")
    return {"personId": person["id"], "login": person["login"], "projectId": project_id,
            "duty": duty, "roles": sorted({row["role"] for row in grants}), "grantIds": [row["id"] for row in grants]}


class Plugin:
    GOVERNOR = True
    def __init__(self, cipher):
        self.c, self.db, self.audit = cipher, cipher.db, cipher.audit
        self.c.receivables.owner_billing = self

    @contextmanager
    def atomic(self):
        self.db.require_practice_mode()
        self.db.require_write_authority()
        if not self.db.in_memory:
            raise OwnerBillingError("this first owner billing entry writes owned memory practice only")
        with self.db.transaction() as conn:
            name = new_id("owner_billing_act")
            conn.execute(f"SAVEPOINT {name}")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute(f"ROLLBACK TO {name}")
                raise
            finally:
                if conn.in_transaction:
                    conn.execute(f"RELEASE {name}")

    def require_duty(self, actor, project_id, duty):
        return require_owner_billing_duty(self.c, actor, project_id, duty)

    def _guards(self):
        if not self._schema_installed():
            raise OwnerBillingError("owner billing source schema is not installed")
        if not self.audit.verify_chain()["ok"]:
            raise OwnerBillingError("owner billing audit chain is broken")
        self.c.plugin("people")._require_intact()
        for statement in SCHEMA_STATEMENTS:
            match = re.match(r"CREATE TRIGGER (\w+)", statement)
            if match:
                row = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (match[1],))
                normalize = lambda sql: re.sub(r"\s+", " ", sql.strip())
                if row is None or normalize(row["sql"]) != normalize(statement):
                    raise OwnerBillingError("owner billing storage guards changed")

    def _schema_installed(self):
        admission = self.db.one("SELECT version,statement_count,checksum FROM schema_version WHERE name=?", (SCHEMA_NAME,))
        tables = {row["name"] for row in self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'owner_billing_*'")}
        if admission is not None:
            versions = [row["version"] for row in self.db.query("SELECT version FROM schema_version WHERE version<=? ORDER BY version", (admission["version"],))]
            if (admission["version"] < 1 or admission["version"] != len(versions)
                    or any(value != index for index, value in enumerate(versions, 1)) or admission["statement_count"] != len(SCHEMA_STATEMENTS)
                    or admission["checksum"] != catalog_checksum(SCHEMA_STATEMENTS)
                    or tables != {f"owner_billing_{kind}" for kind in _SPECS}):
                raise OwnerBillingError("owner billing source schema differs from its original admission")
            return True
        births = self.db.one("SELECT seq FROM audit_log WHERE action GLOB 'owner_billing.*' LIMIT 1")
        receipts = self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'ar_*' LIMIT 1")
        receipt_admission = self.db.one("SELECT name FROM schema_version WHERE name='ar_practice_action_receipts'")
        receipt_birth = self.db.one("SELECT seq FROM audit_log WHERE action='ar.practice_action_recorded' LIMIT 1")
        if tables or births is not None or receipts is not None or receipt_admission is not None or receipt_birth is not None:
            raise OwnerBillingError("owner billing history lost its registered source admission")
        return False

    def _event(self, action, entity_type, entity_id):
        rows = self.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? ORDER BY seq",
                             (action, entity_type, entity_id))
        if len(rows) != 1:
            raise OwnerBillingError("an original owner source event is missing or duplicated")
        return rows[0]

    def _reference(self, reference, *, action=None, entity_type=None, entity_id=None):
        if (type(reference) is not dict or set(reference) != {"seq", "hash"}
                or type(reference["seq"]) is not int or reference["seq"] <= 0
                or type(reference["hash"]) is not str):
            raise OwnerBillingError("an original owner event reference has changed types or shape")
        row = self.db.one("SELECT * FROM audit_log WHERE seq=?", (reference["seq"],))
        if row is None or not _same(reference, _ref(row)) or any(
            expected is not None and row[key] != expected for key, expected in
            (("action", action), ("entity_type", entity_type), ("entity_id", entity_id))
        ):
            raise OwnerBillingError("an owner source reference differs from its original event")
        return row

    def _record(self, kind, body, actor):
        row = {"id": body["id"], **{key: body[key] for key in _SPECS[kind][1]}, "body_json": canonical_json(body)}
        row["row_hash"] = hash_json(row)
        payload = {"rowHash": row["row_hash"], "projectId": body["project_id"]}
        if "prime_bill_id" in body:
            payload["primeBillId"] = body["prime_bill_id"]
        self.audit.record(actor, f"owner_billing.{kind}_recorded", f"owner_billing_{kind}", body["id"], payload)
        keys = tuple(row)
        self.db.execute(f"INSERT INTO owner_billing_{kind} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                        tuple(row[key] for key in keys))
        return body

    def _proof(self, kind, identifier):
        self._guards()
        row = self.db.one(f"SELECT * FROM owner_billing_{kind} WHERE id=?", (identifier,))
        if row is None:
            raise OwnerBillingError("an original owner billing source disappeared")
        body = loads(row["body_json"])
        expected_hash = hash_json({key: value for key, value in row.items() if key != "row_hash"})
        event = self._event(f"owner_billing.{kind}_recorded", f"owner_billing_{kind}", identifier)
        expected_payload = {"rowHash": expected_hash, "projectId": row["project_id"]}
        if "prime_bill_id" in row:
            expected_payload["primeBillId"] = row["prime_bill_id"]
        if (type(body) is not dict or canonical_json(body) != row["body_json"] or row["row_hash"] != expected_hash
                or not _same(loads(event["payload_json"]), expected_payload)
                or not _same({key: body.get(key) for key in ("id", *_SPECS[kind][1])},
                             {key: row[key] for key in ("id", *_SPECS[kind][1])})
                or body.get("actor") != event["actor"]):
            raise OwnerBillingError("owner billing source differs from its original audited birth")
        return body

    def _inventory(self, kind, project_ids=None):
        if not self._schema_installed():
            return []
        self._guards()
        allowed = None if project_ids is None else set(project_ids)
        births = self.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? ORDER BY seq",
                              (f"owner_billing.{kind}_recorded", f"owner_billing_{kind}"))
        expected = {}
        for event in births:
            payload = loads(event["payload_json"])
            if type(payload) is not dict or type(payload.get("projectId")) is not str or event["entity_id"] in expected:
                raise OwnerBillingError("owner billing inventory has a malformed original birth")
            if allowed is None or payload["projectId"] in allowed:
                expected[event["entity_id"]] = event
        rows = self.db.query(f"SELECT id,project_id FROM owner_billing_{kind}")
        actual = {row["id"] for row in rows if allowed is None or row["project_id"] in allowed}
        if actual != set(expected):
            raise OwnerBillingError("owner billing inventory lost an original source or gained an unaudited source")
        return [self._proof(kind, identifier) for identifier in expected]

    def project_is_modern(self, project_id):
        return self.db.one("SELECT 1 FROM audit_log WHERE action='owner_billing.bases_recorded' AND entity_type='owner_billing_bases' AND json_extract(payload_json,'$.projectId')=?", (project_id,)) is not None

    def source_scope(self, bill_id):
        event = self.db.one("SELECT payload_json FROM audit_log WHERE action='owner_billing.sources_recorded' AND json_extract(payload_json,'$.primeBillId')=? ORDER BY seq LIMIT 1", (bill_id,))
        if event:
            return {"projectId": loads(event["payload_json"])["projectId"]}
        row = self.db.one("SELECT project_id FROM prime_bills WHERE id=?", (bill_id,))
        if row:
            return {"projectId": row["project_id"]}
        raise OwnerBillingError("unknown owner bill")

    def basis_scope(self, basis_id):
        event = self.db.one("SELECT payload_json FROM audit_log WHERE action='owner_billing.bases_recorded' AND entity_type='owner_billing_bases' AND entity_id=?", (basis_id,))
        if event:
            return {"projectId": loads(event["payload_json"])["projectId"]}
        row = self.db.one("SELECT project_id FROM owner_billing_bases WHERE id=?", (basis_id,))
        if row:
            return {"projectId": row["project_id"]}
        raise OwnerBillingError("unknown owner billing basis")

    def is_modern(self, bill_id):
        if self.db.one("SELECT 1 FROM audit_log WHERE action='owner_billing.sources_recorded' AND json_extract(payload_json,'$.primeBillId')=?", (bill_id,)):
            return True
        row = self.db.one("SELECT project_id FROM prime_bills WHERE id=?", (bill_id,))
        return bool(row and self.project_is_modern(row["project_id"]))

    def _document(self, revision_id, project_id, kind, *, current=False):
        revision = self.db.one("SELECT * FROM document_revisions WHERE id=?", (revision_id,))
        document = self.db.one("SELECT * FROM documents WHERE id=?", (revision["document_id"],)) if revision else None
        if document is None or document["project_id"] != project_id or document["kind"] != kind:
            raise OwnerBillingError("owner source must be an owned document of the required kind")
        birth = self._event("document.registered", "document", document["id"])
        if not _same(loads(birth["payload_json"]), {"project_id": project_id, "kind": kind, "title": document["title"]}):
            raise OwnerBillingError("owner document differs from its original registration")
        rows = self.db.query("SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision", (document["id"],))
        events = self.db.query("SELECT * FROM audit_log WHERE action='document.revised' AND entity_type='document' AND entity_id=? ORDER BY seq", (document["id"],))
        if len(rows) != len(events) or not rows:
            raise OwnerBillingError("an original owner document revision disappeared")
        selected = None
        for number, (row, event) in enumerate(zip(rows, events), start=1):
            expected = {"revision_id": row["id"], "revision": number, "content_hash": row["content_hash"], "note": row["note"]}
            if type(row["revision"]) is not int or row["revision"] != number or not _same(loads(event["payload_json"]), expected):
                raise OwnerBillingError("owner document revision lineage differs from its original audit")
            if not 0 <= (parse_iso(event["ts"]) - parse_iso(row["created_at"])).total_seconds() <= 1:
                raise OwnerBillingError("owner revision attribution time changed")
            if row["id"] == revision_id:
                selected = {"document": document, "revision": row, "registrationEvent": _ref(birth), "revisionEvent": _ref(event)}
        if selected is None or current and rows[-1]["id"] != revision_id:
            raise StaleApprovalError("the owner source document was superseded")
        return selected

    def _contract(self, project_id, version=None):
        rows = self.db.query("SELECT * FROM prime_contracts WHERE project_id=? ORDER BY version", (project_id,))
        events = self.db.query("SELECT * FROM audit_log WHERE action='prime_contract.set' AND entity_type='prime_contract' AND json_extract(payload_json,'$.project_id')=? ORDER BY seq", (project_id,))
        if not rows or len(rows) != len(events):
            raise OwnerBillingError("owner prime contract inventory is incomplete")
        selected = None
        for number, (row, event) in enumerate(zip(rows, events), start=1):
            payload = loads(event["payload_json"])
            hashed = {key: row[key] for key in ("project_id", "version", "contract_value", "retainage_rate")}
            if (type(row["version"]) is not int or row["version"] != number or row["id"] != event["entity_id"]
                    or row["created_by"] != event["actor"] or hash_json(hashed) != row["content_hash"]
                    or not _same({key: payload.get(key) for key in (*hashed, "content_hash")}, {**hashed, "content_hash": row["content_hash"]})
                    or payload.get("previous_version") != (number - 1 if number > 1 else None)):
                raise OwnerBillingError("owner prime contract differs from its original version history")
            if not 0 <= (parse_iso(event["ts"]) - parse_iso(row["created_at"])).total_seconds() <= 1:
                raise OwnerBillingError("owner prime contract attribution time changed")
            if version is None or row["version"] == version:
                selected = {"record": row, "event": _ref(event)}
        if selected is None:
            raise OwnerBillingError("original owner contract version disappeared")
        return selected

    def _scope(self, project_id):
        project = self.c.project(project_id)
        customer = self.c.party(project["customer_id"]) if project["customer_id"] else None
        if customer is None or customer["kind"] != "customer" or project["currency"] != "USD":
            raise OwnerBillingError("practice owner billing requires an explicit USD project customer")
        project_birth = self._event("project.created", "project", project_id)
        customer_birth = self._event("party.created", "party", customer["id"])
        if (loads(project_birth["payload_json"]).get("name") != project["name"]
                or not _same(loads(customer_birth["payload_json"]), {"kind": "customer", "name": customer["name"]})):
            raise OwnerBillingError("owner project/customer birth is not intact")
        return {"projectId": project_id, "entity": project["entity"], "currency": project["currency"],
                "customerId": customer["id"], "projectName": project["name"], "customerName": customer["name"],
                "projectBirth": _ref(project_birth), "customerBirth": _ref(customer_birth)}

    def _settings_history(self, customer_id):
        result = {}
        for key, table, action in (("terms", "customer_payment_terms", "payment_terms.set"),
                                   ("recipients", "customer_billing_recipients", "billing_recipients.set")):
            rows = self.db.query(f"SELECT * FROM {table} WHERE customer_id=? ORDER BY version", (customer_id,))
            events = self.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type='party' AND entity_id=? ORDER BY seq", (action, customer_id))
            if len(rows) != len(events) or not rows:
                raise OwnerBillingError("owner terms/recipient history requires its explicit original audited records")
            history = []
            for number, (row, event) in enumerate(zip(rows, events), start=1):
                expected = {"version": number, "previous_version": number - 1}
                expected.update({"days": row["days"], "previous_days": rows[number - 2]["days"] if number > 1 else 30}
                                if key == "terms" else {"recipients": loads(row["recipients_json"])})
                if (type(row["version"]) is not int or row["version"] != number or not _same(loads(event["payload_json"]), expected)
                        or event["actor"] != row["created_by"]
                        or not 0 <= (parse_iso(event["ts"]) - parse_iso(row["created_at"])).total_seconds() <= 1):
                    raise OwnerBillingError("owner terms/recipient record differs from its original audited version")
                history.append({"record": row, "event": _ref(event)})
            result[key] = history
        return result

    def _close_contract(self, project_id, identifier=None):
        row = (self.db.one("SELECT * FROM close_contract_values WHERE id=? AND project_id=?", (identifier, project_id))
               if identifier is not None else self.c.plugin("close").contract_value(project_id))
        if row is None:
            raise OwnerBillingError("the explicit synthetic owner basis requires its matching close contract source")
        events = self.db.query("SELECT * FROM audit_log WHERE action='close.contract_value_set' AND entity_type='project' AND entity_id=? AND json_extract(payload_json,'$.version')=?", (project_id, row["version"]))
        if len(events) != 1:
            raise OwnerBillingError("the owner close contract source has no exact original event")
        event = events[0]
        payload = loads(event["payload_json"])
        if (not _same({key: payload.get(key) for key in ("contract_value", "version", "previous_value")},
                      {key: row[key] for key in ("contract_value", "version", "previous_value")})
                or row["set_by"] != event["actor"]
                or not 0 <= (parse_iso(event["ts"]) - parse_iso(row["created_at"])).total_seconds() <= 1):
            raise OwnerBillingError("the owner close contract source differs from its original declaration")
        return {"record": row, "event": _ref(event)}

    def declare_practice_basis(self, project_id, *, contract_revision_id, actor):
        with self.atomic():
            person = self.require_duty(actor, project_id, "pm")
            if self.project_is_modern(project_id) or self.c.receivables.list(project_id):
                raise OwnerBillingError("a fixed practice owner basis is declared once before owner billing")
            self._guards()
            scope, contract = self._scope(project_id), self._contract(project_id)
            if contract["record"]["contract_value"] != "250000.00" or Decimal(contract["record"]["retainage_rate"]) != Decimal("0.10"):
                raise OwnerBillingError("this fixed synthetic owner basis requires its explicit250000 contract and10%retainage")
            agreement = self._document(contract_revision_id, project_id, "owner_agreement", current=True)
            close_contract = self._close_contract(project_id)
            if close_contract["record"]["contract_value"] != contract["record"]["contract_value"]:
                raise OwnerBillingError("the fixed owner prime and close sources must agree before declaration")
            terms = self.c.receivables.payment_terms(scope["customerId"])
            recipients = self.c.receivables.billing_recipients(scope["customerId"])
            if terms["days"] != 30 or recipients["recipients"] not in (["owner-billing@synthetic-owner.invalid"], ["hidden-billing@synthetic-owner.invalid"]):
                raise OwnerBillingError("this fixed practice basis requires30-day terms and its synthetic mail sink")
            body = {"id": new_id("obasis"), "project_id": project_id, "customer_id": scope["customerId"], "version": 1,
                    "scope": scope, "contract": contract, "closeContract": close_contract, "agreement": agreement, "sov": [asdict(line) for line in FIXED_SOV],
                    "terms": terms, "recipients": recipients, "settingsHistory": self._settings_history(scope["customerId"]), "datePolicy": DATE_POLICY,
                    "declaration": "Fixed synthetic owner billing basis; no legal award or engineer adoption",
                    "mode": "practice", "synthetic": True, "personId": person["personId"], "actor": person["login"], "createdAt": utcnow_iso()}
            self._record("bases", body, person["login"])
            return body

    def basis_proof(self, basis_id, *, current=False):
        body = self._proof("bases", basis_id)
        if not _same(body["scope"], self._scope(body["project_id"])):
            raise OwnerBillingError("owner basis project/customer scope changed")
        contract = self._contract(body["project_id"], body["contract"]["record"]["version"])
        agreement = self._document(body["agreement"]["revision"]["id"], body["project_id"], "owner_agreement", current=current)
        if not _same(contract, body["contract"]) or not _same(agreement, body["agreement"]):
            raise OwnerBillingError("owner basis source differs from its original declared facts")
        if not _same(self._close_contract(body["project_id"], body["closeContract"]["record"]["id"]), body["closeContract"]):
            raise OwnerBillingError("the original owner close contract source changed")
        if not _same(body["sov"], [asdict(line) for line in FIXED_SOV]) or body["datePolicy"] != DATE_POLICY:
            raise OwnerBillingError("fixed owner basis calculation/date policy changed")
        settings = self._settings_history(body["customer_id"])
        if any(not _same(settings[key][:len(body["settingsHistory"][key])], body["settingsHistory"][key]) for key in settings):
            raise OwnerBillingError("owner original terms/recipients were changed or deleted")
        if current and (not _same(self._contract(body["project_id"]), contract)
                        or not _same(self.c.receivables.payment_terms(body["customer_id"]), body["terms"])
                        or not _same(self.c.receivables.billing_recipients(body["customer_id"]), body["recipients"])):
            raise StaleApprovalError("the owner contract, terms or recipients changed after the basis declaration")
        close_value = self.c.plugin("close").contract_value(body["project_id"])
        if current and close_value is not None and close_value["contract_value"] != contract["record"]["contract_value"]:
            raise OwnerBillingError("owner prime and close contract values diverge")
        return {"record": body, "basisHash": hash_json(body), "projectId": body["project_id"]}

    def basis_inventory(self, project_ids=None):
        return [self.basis_proof(body["id"]) for body in self._inventory("bases", project_ids)]

    @staticmethod
    def _native_facts(bill):
        keys = ("id", "project_id", "customer_id", "period_id", "sequence", "certified_cumulative", "retainage_rate",
                "retainage_cumulative", "prior_net", "amount_due", "revenue_this_period", "content_hash", "created_at",
                "contract_version", "invoice_date")
        return {key: bill[key] for key in keys}

    def _period(self, period_id, *, current=False):
        row = self.c.ledger.require_open(period_id) if current else self.c.ledger.period(period_id)
        event = self._event("period.opened", "period", period_id)
        if not _same(loads(event["payload_json"]), {"name": row["name"], "start": row["start_date"], "end": row["end_date"]}):
            raise OwnerBillingError("owner posting period differs from its original definition")
        return {"id": row["id"], "name": row["name"], "startDate": row["start_date"], "endDate": row["end_date"], "event": _ref(event)}

    def prepare_preflight(self, basis_id, body, *, actor):
        basis_row = self.db.one("SELECT project_id FROM owner_billing_bases WHERE id=?", (basis_id,))
        if basis_row is None:
            raise OwnerBillingError("unknown owner billing basis")
        person = self.require_duty(actor, basis_row["project_id"], "pm")
        basis = self.basis_proof(basis_id, current=True)
        record = basis["record"]
        self.require_current_project_finance(record["project_id"])
        if type(body) is not dict or set(body) != {"claimRevisionId", "reviewRevisionId", "periodId", "lines"}:
            raise OwnerBillingError("owner preparation needs only its exact owned evidence, period and line facts")
        claim = self._document(_text(body["claimRevisionId"], "Claim revision", 100), record["project_id"], "owner_claim", current=True)
        review = self._document(_text(body["reviewRevisionId"], "Review revision", 100), record["project_id"], "owner_certification", current=True)
        if claim["document"]["id"] == review["document"]["id"]:
            raise OwnerBillingError("owner claim and reviewed certification require separate original documents")
        period = self._period(_text(body["periodId"], "Period", 100), current=True)
        invoice_date = period["startDate"]
        if invoice_date > self.c.receivables._today().isoformat():
            raise OwnerBillingError("this fixed practice invoice date cannot be in the future")
        all_sources = self.source_inventory(project_ids=(record["project_id"],))
        native_bills = self.c.receivables.list(record["project_id"])
        if {bill["id"] for bill in native_bills} != {source["bill"]["id"] for source in all_sources}:
            raise OwnerBillingError("modern owner project has a bill without its original line source")
        if any(bill["status"] in ("draft", "void", "reversed") for bill in native_bills):
            raise OwnerBillingError("the prior owner bill must have a proven standing posting before another certification")
        for source in all_sources:
            self.require_posted_proof(source["bill"]["id"])
        prior = max(all_sources, key=lambda source: source["bill"]["sequence"]) if all_sources else None
        previous = {line["lineId"]: line for line in prior["calculation"]["lines"]} if prior else {}
        if type(body["lines"]) is not list or len(body["lines"]) != len(FIXED_SOV):
            raise OwnerBillingError("every fixed owner SOV line is required")
        progress, locators, seen = [], [], set()
        for line in body["lines"]:
            if type(line) is not dict or set(line) != {"lineId", "claimedCumulative", "reviewedCumulative", "differenceReason", "claimSourceLocator", "reviewSourceLocator"}:
                raise OwnerBillingError("owner progress line shape changed")
            identifier = _text(line["lineId"], "Owner line", 64)
            sov = next((item for item in FIXED_SOV if item.line_id == identifier), None)
            if sov is None or identifier in seen:
                raise OwnerBillingError("owner progress must match each fixed SOV line exactly once")
            seen.add(identifier)
            older = previous.get(identifier)
            previous_measure = (older["reviewedQuantity"] if sov.basis == "unitPrice" else fmt(Decimal(older["reviewedAmountCents"]) / 100)) if older else "0"
            progress.append(OwnerProgressLine(identifier, previous_measure, line["claimedCumulative"], line["reviewedCumulative"],
                                              _text(line["differenceReason"], "Difference reason", empty=True)))
            locators.append({"lineId": identifier, "claimSourceLocator": _text(line["claimSourceLocator"], "Claim locator", 500),
                             "reviewSourceLocator": _text(line["reviewSourceLocator"], "Review locator", 500)})
        calculation = calculate_owner_pay_app(sov_lines=FIXED_SOV, progress_lines=progress, prime_contract_value_cents=25_000_000,
                                             prior_retained_cents=prior["calculation"]["retainedCumulativeCents"] if prior else 0,
                                             retainage_released_cents=int(self.c.receivables._released_to_date(record["project_id"]) * 100),
                                             retainage_rate="0.10").as_dict()
        return {"basis": basis, "person": person, "claim": claim, "review": review, "period": period,
                "invoiceDate": invoice_date, "datePolicy": DATE_POLICY, "calculation": calculation,
                "locators": locators, "previousSourceId": prior["record"]["id"] if prior else None,
                "previousSourceHash": prior["sourceHash"] if prior else None,
                "consequence": "Prepare a synthetic owner bill from reviewed quantities; no journal or receivable is created."}

    def prepare(self, basis_id, body, *, actor):
        with self.atomic():
            plan = self.prepare_preflight(basis_id, body, actor=actor)
            basis = plan["basis"]["record"]
            bill = self.c.receivables._certify_legacy(project_id=basis["project_id"], period_id=plan["period"]["id"],
                        certified_cumulative=fmt(Decimal(plan["calculation"]["reviewedCertifiedCents"]) / 100),
                        actor=plan["person"]["login"], invoice_date=plan["invoiceDate"])
            event = self._event("prime_bill.certified", "prime_bill", bill["id"])
            record = {"id": new_id("osource"), "prime_bill_id": bill["id"], "project_id": basis["project_id"], "basis_id": basis_id,
                      "basisHash": plan["basis"]["basisHash"], "nativeOriginal": self._native_facts(bill), "certifiedEvent": _ref(event),
                      "claim": plan["claim"], "review": plan["review"], "period": plan["period"], "invoiceDate": plan["invoiceDate"],
                      "datePolicy": DATE_POLICY, "calculation": plan["calculation"], "locators": plan["locators"],
                      "measurementBasis": "Manual claim/certification entry; no source parsing or independent external certification asserted",
                      "previousSourceId": plan["previousSourceId"], "previousSourceHash": plan["previousSourceHash"],
                      "personId": plan["person"]["personId"], "actor": plan["person"]["login"], "createdAt": utcnow_iso()}
            self._record("sources", record, plan["person"]["login"])
            proof = self.source_proof(bill["id"], current=True)
            return {"primeBillId": bill["id"], "sourceId": record["id"], "projectId": record["project_id"],
                    "sourceHash": proof["sourceHash"], "status": "draft", "mode": "practice", "synthetic": True}

    def source_proof(self, bill_id, *, current=False):
        rows = self._inventory("sources", (self.source_scope(bill_id)["projectId"],))
        selected = [body for body in rows if body["prime_bill_id"] == bill_id]
        if len(selected) != 1:
            raise OwnerBillingError("owner bill has no exact original certification source")
        body = selected[0]
        basis = self.basis_proof(body["basis_id"], current=current)
        bill = self.c.receivables.get(bill_id)
        if not _same(body["nativeOriginal"], self._native_facts(bill)) or body["basisHash"] != basis["basisHash"]:
            raise OwnerBillingError("owner bill differs from its immutable native/source correspondence")
        if not _same(body["period"], self._period(bill["period_id"], current=current)) or body["datePolicy"] != DATE_POLICY or body["invoiceDate"] != body["period"]["startDate"]:
            raise OwnerBillingError("owner bill original posting period/date policy changed")
        event = self._reference(body["certifiedEvent"], action="prime_bill.certified", entity_type="prime_bill", entity_id=bill_id)
        calculation = body["calculation"]
        expected = {"project_id": bill["project_id"], "sequence": bill["sequence"], "certified": bill["certified_cumulative"],
                    "amount_due": bill["amount_due"], "retainage_this_period": bill["retainage_this_period"],
                    "contract_version": bill["contract_version"], "content_hash": bill["content_hash"],
                    "prior_billed_certified": fmt(Decimal(calculation["priorCertifiedCents"]) / 100),
                    "prior_net": bill["prior_net"], "invoice_date": body["invoiceDate"]}
        if not _same(loads(event["payload_json"]), expected) or event["actor"] != body["actor"]:
            raise OwnerBillingError("owner certification differs from its original audited act")
        for key, kind in (("claim", "owner_claim"), ("review", "owner_certification")):
            if not _same(body[key], self._document(body[key]["revision"]["id"], body["project_id"], kind, current=current)):
                raise OwnerBillingError("owner claimed/reviewed evidence differs from its original source")
        progress = [OwnerProgressLine(line["lineId"], line["previousQuantity"] if line["basis"] == "unitPrice" else fmt(Decimal(line["previousAmountCents"]) / 100),
                                     line["claimedQuantity"] if line["basis"] == "unitPrice" else fmt(Decimal(line["claimedAmountCents"]) / 100),
                                     line["reviewedQuantity"] if line["basis"] == "unitPrice" else fmt(Decimal(line["reviewedAmountCents"]) / 100), line["differenceReason"])
                    for line in calculation["lines"]]
        rebuilt = calculate_owner_pay_app(sov_lines=FIXED_SOV, progress_lines=progress, prime_contract_value_cents=25_000_000,
                    prior_retained_cents=calculation["priorRetainedCents"], retainage_released_cents=calculation["retainageReleasedCents"],
                    retainage_rate="0.10").as_dict()
        if not _same(rebuilt, calculation) or not _same(
            [bill["certified_cumulative"], bill["amount_due"], bill["revenue_this_period"], bill["retainage_this_period"]],
            [fmt(Decimal(calculation[key]) / 100) for key in ("reviewedCertifiedCents", "amountDueCents", "revenueThisPeriodCents", "retainageThisPeriodCents")]):
            raise OwnerBillingError("owner line calculation differs from its native aggregate")
        if body["previousSourceId"] is not None:
            previous = self._proof("sources", body["previousSourceId"])
            if hash_json(previous) != body["previousSourceHash"] or previous["project_id"] != body["project_id"]:
                raise OwnerBillingError("owner previous certification lineage changed")
        source = {"record": body, "sourceHash": hash_json(body), "basis": basis, "bill": bill, "calculation": calculation,
                  "projectId": body["project_id"]}
        self._current_native_lifecycle(source)
        return source

    def source_inventory(self, project_ids=None):
        return [self.source_proof(body["prime_bill_id"]) for body in self._inventory("sources", project_ids)]

    def manifest(self, bill_id, *, actor_role):
        source = self.source_proof(bill_id, current=True)
        manifest = self.c.receivables._legacy_manifest(bill_id, actor_role=actor_role)
        manifest["bindings"].update({"approval_flow": APPROVAL_FLOW, "owner_source_hash": source["sourceHash"],
            "owner_basis_hash": source["basis"]["basisHash"], "owner_calculation_hash": source["calculation"]["calculationHash"],
            "owner_date_policy": DATE_POLICY})
        return manifest

    def business_request_preflight(self, bill_id, *, actor, actor_role="accountant"):
        person = self.require_duty(actor, self.source_scope(bill_id)["projectId"], "pm")
        if actor_role not in ("accountant", "controller"):
            raise OwnerBillingError("owner financial authorization requires accounting decision authority")
        source = self.source_proof(bill_id, current=True)
        manifest = self.c._manifest("prime_bill.approve", bill_id, actor_role)
        return {"source": source, "manifest": manifest, "person": person}

    def approval_proof(self, approval_id):
        self._guards()
        ap = self.c.approvals.get(approval_id)
        manifest = ap["manifest"]
        financial = ap["operation"] == "prime_bill.approve"
        try:
            deadline = parse_iso(ap["expires_at"])
            original_deadline = parse_iso(manifest["expires_at"])
            if deadline.utcoffset() is None or original_deadline.utcoffset() is None:
                raise ValueError("owner authorization expiry needs a time zone")
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
            raise OwnerBillingError("owner authorization original expiry is invalid") from exc
        if (ap["operation"] not in ("prime_bill.approve", "prime_bill.send") or ap["subject_type"] != "prime_bill"
                or manifest.get("subject") != {"type": "prime_bill", "id": ap["subject_id"]}
                or manifest.get("operation") != ap["operation"] or manifest.get("actor_role") != ap["actor_role"]
                or ap["actor_role"] not in (("accountant", "controller") if financial else ("pm", "accountant")) or ap["manifest_hash"] != hash_json(manifest)
                or ap["material_hash"] != material_hash(manifest) or ap["nonce"] != manifest.get("nonce")
                or ap["policy_version"] != manifest.get("policy_version")
                or financial and (manifest.get("bindings") or {}).get("approval_flow") != APPROVAL_FLOW
                or not financial and not (manifest.get("bindings") or {}).get("owner_posting_hash")
                or ap["expires_at"] != manifest["expires_at"]):
            raise OwnerBillingError("owner authorization differs from its original bounded manifest")
        events = self.db.query("SELECT * FROM audit_log WHERE entity_type='approval' AND entity_id=? ORDER BY seq", (approval_id,))
        status, request, grant, consumption, latest_reason = None, None, None, None, None
        transitions = {None: {"pending"}, "pending": {"granted", "expired", "invalidated"}, "granted": {"consumed", "expired", "invalidated"},
                       "expired": {"invalidated"}, "invalidated": {"invalidated"}, "consumed": set()}
        states = {"approval.requested": "pending", "approval.granted": "granted", "approval.consumed": "consumed",
                  "approval.expired": "expired", "approval.invalidated": "invalidated"}
        for event in events:
            if event["action"] not in states:
                continue
            next_status = states[event["action"]]
            if next_status not in transitions[status]:
                raise OwnerBillingError("owner authorization audited lifecycle is invalid")
            status = next_status
            payload = loads(event["payload_json"])
            if status == "pending":
                request = event
                if not _same(payload, {"operation": ap["operation"], "subject": manifest["subject"], "manifest_hash": ap["manifest_hash"]}) or event["actor"] != ap["requested_by"]:
                    raise OwnerBillingError("owner authorization request changed")
            elif status in ("granted", "consumed"):
                if not _same(payload, {"operation": ap["operation"], "material_hash": ap["material_hash"]}):
                    raise OwnerBillingError("owner authorization grant/consumption changed")
                if status == "granted":
                    grant = event
                else:
                    consumption = event
            elif status == "invalidated":
                latest_reason = (f"subject changed after approval: {payload['diff']}"
                                 if set(payload) == {"reason", "diff"} and payload.get("reason") == "material change"
                                 and type(payload.get("diff")) is str else payload.get("reason"))
        if (status != ap["status"] or request is None or grant is not None and grant["actor"] != ap["approver"]
                or grant is None and (ap["approver"] is not None or ap["granted_at"] is not None)
                or consumption is not None and consumption["actor"] != ap["consumed_by"]
                or consumption is None and (ap["consumed_by"] is not None or ap["consumed_at"] is not None)
                or status == "invalidated" and latest_reason != ap["invalidated_reason"]):
            raise OwnerBillingError("owner authorization row differs from its original audited lifecycle")
        for field, event in (("requested_at", request), ("granted_at", grant), ("consumed_at", consumption)):
            if event and not 0 <= (parse_iso(event["ts"]) - parse_iso(ap[field])).total_seconds() <= 1:
                raise OwnerBillingError("owner authorization attribution time changed")
            if event is not None and field != "requested_at" and parse_iso(event["ts"]) >= deadline:
                raise OwnerBillingError("owner authorization was decided or consumed after its original deadline")
        return {"approval": ap, "requestEvent": _ref(request), "grantEvent": _ref(grant) if grant else None,
                "consumptionEvent": _ref(consumption) if consumption else None}

    def approval_inventory(self, project_ids=None):
        allowed = None if project_ids is None else set(project_ids)
        births = self.db.query("SELECT * FROM audit_log WHERE action='approval.requested' AND entity_type='approval' ORDER BY seq")
        expected = {}
        for event in births:
            payload = loads(event["payload_json"])
            if payload.get("operation") not in ("prime_bill.approve", "prime_bill.send"):
                continue
            subject = payload.get("subject") or {}
            bill_id = subject.get("id")
            if not self.is_modern(bill_id):
                continue
            project_id = self.source_scope(bill_id)["projectId"]
            if allowed is None or project_id in allowed:
                expected[event["entity_id"]] = bill_id
        rows = self.db.query("SELECT a.id,b.project_id FROM approvals a JOIN prime_bills b ON b.id=a.subject_id WHERE a.subject_type='prime_bill' AND a.operation IN ('prime_bill.approve','prime_bill.send')")
        actual = {row["id"] for row in rows if (allowed is None or row["project_id"] in allowed)
                  and self.project_is_modern(row["project_id"])}
        if actual != set(expected):
            raise OwnerBillingError("owner authorization inventory lost an original request or gained an unaudited request")
        return [self.approval_proof(identifier) for identifier in expected]

    def _current_approval(self, bill_id, approval_id, status):
        proof = self.approval_proof(approval_id)
        ap = proof["approval"]
        if ap["subject_id"] != bill_id or ap["status"] != status:
            raise OwnerBillingError("the original owner authorization is not in its required state")
        if parse_iso(ap["expires_at"]) <= utcnow():
            raise ApprovalExpired("the owner billing authorization expired")
        current = self.c._manifest("prime_bill.approve", bill_id, ap["actor_role"])
        if material_hash(current) != ap["material_hash"] or not _same(current.get("governance"), ap["manifest"].get("governance")):
            raise StaleApprovalError("owner billing source or governed facts changed after review")
        return {**proof, "manifest": current, "source": self.source_proof(bill_id, current=True)}

    def business_grant_preflight(self, bill_id, *, approval_id, actor):
        person = self.require_duty(actor, self.source_scope(bill_id)["projectId"], "accounting")
        checked = self._current_approval(bill_id, approval_id, "pending")
        requester = self.require_duty(checked["approval"]["requested_by"], person["projectId"], "pm")
        if requester["personId"] == person["personId"]:
            raise OwnerBillingError("a different actual accounting person must review owner billing")
        return {**checked, "person": person, "requester": requester}

    def record_business_approval(self, bill_id, *, approval_id, actor):
        with self.atomic():
            person = self.require_duty(actor, self.source_scope(bill_id)["projectId"], "accounting")
            checked = self._current_approval(bill_id, approval_id, "granted")
            ap = checked["approval"]
            if ap["approver"] != person["login"]:
                raise OwnerBillingError("the actual original reviewer records the owner grant")
            requester = self.require_duty(ap["requested_by"], person["projectId"], "pm")
            if requester["personId"] == person["personId"]:
                raise OwnerBillingError("owner review requires a different actual person")
            grants = self._inventory("grants", (person["projectId"],))
            same = [row for row in grants if row["approval_id"] == approval_id]
            if same:
                return self.grant_proof(bill_id, approval_id=approval_id)
            if any(row["prime_bill_id"] == bill_id and self.c.approvals.get(row["approval_id"])["status"] in ("pending", "granted", "consumed") for row in grants):
                raise OwnerBillingError("owner bill already has an active original business grant")
            body = {"id": new_id("ogrant"), "prime_bill_id": bill_id, "project_id": person["projectId"], "approval_id": approval_id,
                    "sourceHash": checked["source"]["sourceHash"], "originalManifest": ap["manifest"],
                    "requestEvent": checked["requestEvent"], "grantEvent": checked["grantEvent"],
                    "requesterPersonId": requester["personId"], "reviewerPersonId": person["personId"],
                    "reviewedBy": person["login"], "actor": person["login"], "createdAt": utcnow_iso()}
            self._record("grants", body, person["login"])
            return self.grant_proof(bill_id, approval_id=approval_id)

    def grant_proof(self, bill_id, approval_id=None):
        return self._grant_proof_for_source(self.source_proof(bill_id), approval_id=approval_id)

    def _grant_proof_for_source(self, source, approval_id=None):
        bill_id = source["bill"]["id"]
        grants = [body for body in self._inventory("grants", (source["projectId"],)) if body["prime_bill_id"] == bill_id
                  and (approval_id is None or body["approval_id"] == approval_id)]
        if not grants:
            raise OwnerBillingError("owner bill has no original business grant")
        body = grants[-1]
        proof = self.approval_proof(body["approval_id"])
        if (proof["approval"]["subject_id"] != bill_id or not _same(body["originalManifest"], proof["approval"]["manifest"])
                or body["sourceHash"] != source["sourceHash"] or not _same(body["requestEvent"], proof["requestEvent"])
                or not _same(body["grantEvent"], proof["grantEvent"]) or body["reviewedBy"] != proof["approval"]["approver"]):
            raise OwnerBillingError("owner business grant differs from its original approval/source")
        requester = self.c.plugin("people")._person_row(proof["approval"]["requested_by"])
        reviewer = self.c.plugin("people")._person_row(proof["approval"]["approver"])
        if (requester is None or reviewer is None or requester["id"] != body["requesterPersonId"]
                or reviewer["id"] != body["reviewerPersonId"] or requester["id"] == reviewer["id"]):
            raise OwnerBillingError("owner business grant original person separation changed")
        return {"record": body, "grantHash": hash_json(body), "approval": proof["approval"], "source": source}

    def grant_inventory(self, project_ids=None):
        return [self.grant_proof(body["prime_bill_id"], approval_id=body["approval_id"])
                for body in self._inventory("grants", project_ids)]

    def posting_preflight(self, bill_id, *, approval_id, actor, period_id=None):
        person = self.require_duty(actor, self.source_scope(bill_id)["projectId"], "accounting")
        checked = self._current_approval(bill_id, approval_id, "granted")
        grant = self.grant_proof(bill_id, approval_id=approval_id)
        reviewer = self.require_duty(grant["record"]["reviewedBy"], person["projectId"], "accounting")
        if reviewer["personId"] == person["personId"]:
            raise OwnerBillingError("the actual owner billing reviewer cannot post the same bill")
        bill = checked["source"]["bill"]
        if bill["status"] != "draft" or period_id is not None and period_id != bill["period_id"]:
            raise OwnerBillingError("owner billing posts once in its exact original open period")
        return {**checked, "grant": grant, "person": person, "postingPeriodId": bill["period_id"],
                "invoiceDate": bill["invoice_date"], "datePolicy": DATE_POLICY,
                "preview": checked["manifest"]["bindings"]["journal_preview"]}

    def post(self, bill_id, *, approval_id, actor, period_id=None):
        with self.atomic():
            plan = self.posting_preflight(bill_id, approval_id=approval_id, actor=actor, period_id=period_id)
            self.c.approvals.consume(approval_id, current_manifest=plan["manifest"], consumer=plan["person"]["login"])
            bill = self.c.receivables._post_legacy(bill_id, approval_id=approval_id, actor=plan["person"]["login"], manifest=plan["manifest"])
            journal = self.c.ledger.journal(bill["journal_id"])
            header = {key: value for key, value in journal.items() if key not in ("lines", "reversed_by")}
            body = {"id": new_id("opost"), "prime_bill_id": bill_id, "project_id": bill["project_id"], "approval_id": approval_id,
                    "sourceHash": plan["source"]["sourceHash"], "grantHash": plan["grant"]["grantHash"],
                    "journal": {"header": header, "lines": journal["lines"]}, "journalEvent": _ref(self._event("journal.posted", "journal", journal["id"])),
                    "postedEvent": _ref(self._event("prime_bill.posted", "prime_bill", bill_id)),
                    "approvalConsumption": self.approval_proof(approval_id)["consumptionEvent"],
                    "invoiceDate": bill["invoice_date"], "dueDate": bill["due_date"], "termsDays": bill["payment_terms_days"],
                    "period": plan["source"]["record"]["period"], "datePolicy": DATE_POLICY,
                    "posterPersonId": plan["person"]["personId"], "actor": plan["person"]["login"], "createdAt": utcnow_iso()}
            self._record("postings", body, plan["person"]["login"])
            self.posting_receipt(bill_id)
            return {"primeBillId": bill_id, "postingReceiptId": body["id"], "journalId": journal["id"],
                    "periodId": bill["period_id"], "status": "posted", "mode": "practice", "synthetic": True}

    def posting_receipt(self, bill_id):
        return self._posting_receipt_for_source(self.source_proof(bill_id))

    def _posting_receipt_for_source(self, source):
        bill_id = source["bill"]["id"]
        rows = [body for body in self._inventory("postings", (source["projectId"],)) if body["prime_bill_id"] == bill_id]
        if not rows:
            if source["bill"]["recorded_status"] != "draft":
                raise OwnerBillingError("modern posted owner bill lost its original posting receipt")
            return None
        if len(rows) != 1:
            raise OwnerBillingError("owner bill has duplicate original postings")
        body = rows[0]
        grant = self._grant_proof_for_source(source, approval_id=body["approval_id"])
        approval = self.approval_proof(body["approval_id"])
        bill = source["bill"]
        journal = self.c.ledger.journal(body["journal"]["header"]["id"])
        actual = {"header": {key: value for key, value in journal.items() if key not in ("lines", "reversed_by")}, "lines": journal["lines"]}
        native_journals = self.db.query("SELECT id FROM journals WHERE source_type='prime_bill' AND source_id=? AND reversal_of IS NULL ORDER BY id", (bill_id,))
        native_births = self.db.query("SELECT entity_id FROM audit_log WHERE action='journal.posted' AND entity_type='journal' AND json_extract(payload_json,'$.source_type')='prime_bill' AND json_extract(payload_json,'$.source_id')=? AND json_extract(payload_json,'$.reversal_of') IS NULL ORDER BY seq", (bill_id,))
        if {row["id"] for row in native_journals} != {journal["id"]} or [row["entity_id"] for row in native_births] != [journal["id"]]:
            raise OwnerBillingError("owner original posting has an extra or missing native source journal")
        preview = [{"account": line["account_code"], "debit": line["debit"], "credit": line["credit"], "memo": line["memo"]} for line in journal["lines"]]
        original_manifest = grant["record"]["originalManifest"]
        if (not _same(preview, original_manifest["bindings"]["journal_preview"])
                or journal["source_type"] != "prime_bill" or journal["source_id"] != bill_id or journal["source_version"] != "1"
                or journal["rule_version"] != original_manifest["bindings"]["posting_rule"]
                or journal["description"] != f"Prime bill {bill['sequence']}" or journal["reversal_of"] is not None
                or type(journal["line_count"]) is not int or journal["line_count"] != len(preview)
                or journal["period_id"] != source["record"]["period"]["id"] or journal["approval_id"] != body["approval_id"]
                or any(line["project_id"] != source["projectId"] or line["party_id"] != bill["customer_id"] for line in journal["lines"])
                or body["termsDays"] != original_manifest["bindings"]["payment_terms_days"]
                or body["dueDate"] != self.c.receivables._plus_days(body["invoiceDate"], body["termsDays"])):
            raise OwnerBillingError("owner posting journal/date terms differ from its original approved plan")
        if (body["sourceHash"] != source["sourceHash"] or body["grantHash"] != grant["grantHash"] or not _same(actual, body["journal"])
                or approval["approval"]["status"] != "consumed" or not _same(body["approvalConsumption"], approval["consumptionEvent"])
                or bill["approval_id"] != body["approval_id"] or bill["journal_id"] != journal["id"]
                or not _same([bill["invoice_date"], bill["due_date"], bill["payment_terms_days"]], [body["invoiceDate"], body["dueDate"], body["termsDays"]])
                or body["actor"] != journal["posted_by"] or body["actor"] != approval["approval"]["consumed_by"]):
            raise OwnerBillingError("owner posting receipt differs from its original journal/authorization")
        person = self.c.plugin("people")._person_row(body["actor"])
        if person is None or person["id"] != body["posterPersonId"] or person["id"] == grant["record"]["reviewerPersonId"]:
            raise OwnerBillingError("owner posting lost original actual-person separation")
        journal_event = self._reference(body["journalEvent"], action="journal.posted", entity_type="journal", entity_id=journal["id"])
        posted_event = self._reference(body["postedEvent"], action="prime_bill.posted", entity_type="prime_bill", entity_id=bill_id)
        expected_journal_event = {"period_id": journal["period_id"], "source_type": "prime_bill", "source_id": bill_id, "source_version": "1",
                                  "total": fmt(sum(Decimal(line["debit"]) for line in journal["lines"])),
                                  "approval_id": body["approval_id"], "reversal_of": None, "line_count": len(preview)}
        expected_posted_event = {"approval_id": body["approval_id"], "journal_id": journal["id"], "contract_version": bill["contract_version"],
                                "invoice_date": body["invoiceDate"], "due_date": body["dueDate"], "payment_terms_days": body["termsDays"],
                                "payment_terms_version": original_manifest["bindings"]["payment_terms_version"]}
        if (not _same(loads(journal_event["payload_json"]), expected_journal_event)
                or not _same(loads(posted_event["payload_json"]), expected_posted_event)
                or journal_event["actor"] != body["actor"] or posted_event["actor"] != body["actor"]
                or not 0 <= (parse_iso(journal_event["ts"]) - parse_iso(journal["posted_at"])).total_seconds() <= 1):
            raise OwnerBillingError("owner posting audit differs from its exact original approved journal and terms")
        if not _same(body["period"], source["record"]["period"]) or body["datePolicy"] != DATE_POLICY:
            raise OwnerBillingError("owner posting period/date lineage changed")
        return body

    def require_posted_proof(self, bill_id):
        receipt = self.posting_receipt(bill_id)
        if receipt is None:
            raise OwnerBillingError("owner bill requires its separate independent posting before sending")
        return receipt

    def _unsupported_current_contributors(self, source):
        bill = source["bill"]
        for table, action in (("prime_bill_credit_memos", "prime_bill_credit_memo.prepared"),
                              ("receivable_write_offs", "receivable_write_off.prepared"),
                              ("deposit_applications", "deposit_application.prepared")):
            row = self.db.one(f"SELECT id FROM {table} WHERE prime_bill_id=? LIMIT 1", (bill["id"],))
            birth = self.db.one("SELECT seq FROM audit_log WHERE action=? AND json_extract(payload_json,'$.prime_bill_id')=? LIMIT 1", (action, bill["id"]))
            if row is not None or birth is not None:
                raise OwnerBillingError("Owner credits, write-offs and deposit applications need their separately qualified current source route")
        self._unsupported_current_project(bill["project_id"])
        inverse = self.db.one("SELECT id FROM journals WHERE reversal_of=?", (bill["journal_id"],)) if bill["journal_id"] else None
        reversed_event = self.db.one("SELECT seq FROM audit_log WHERE action='journal.reversed' AND entity_type='journal' AND entity_id=? LIMIT 1", (bill["journal_id"],)) if bill["journal_id"] else None
        if inverse is not None or reversed_event is not None or bill["reversed"]:
            raise OwnerBillingError("Owner original-bill inverses need their separately qualified current source route")

    def _unsupported_current_project(self, project_id):
        for table, action in (("customer_deposits", "deposit.recorded"), ("prime_retainage_invoices", "prime_retainage.released")):
            row = self.db.one(f"SELECT id FROM {table} WHERE project_id=? LIMIT 1", (project_id,))
            birth = self.db.one("SELECT seq FROM audit_log WHERE action=? AND json_extract(payload_json,'$.project_id')=? LIMIT 1", (action, project_id))
            if row is not None or birth is not None:
                raise OwnerBillingError("Owner deposit and retainage-release contributors need their separately qualified current source route")

    def current_ar_proof(self, bill_id):
        """Qualify current native balances without rewriting original receipts.

        Supported check/wire collections and late returns remain explicitly
        historical synthetic bookkeeping, never external settlement evidence.
        """
        from .owner_billing_contributors import prove_collections
        source = self.source_proof(bill_id)
        self._unsupported_current_contributors(source)
        collections = prove_collections(self, source)
        bill = source["bill"]
        expected_open = Decimal(bill["amount_due"]) - Decimal(collections["received"]) if bill["recorded_status"] != "draft" else Decimal("0")
        if not _same([bill["open"], bill["received"], bill["credited_by_memo"], bill["written_off"], bill["deposits_applied"], bill["credited_by_reversal"]],
                     [fmt(expected_open), collections["received"], "0.00", "0.00", "0.00", "0.00"]):
            raise OwnerBillingError("Owner current AR totals differ from the proven original contributor inventory")
        return {"source": source, "currentBill": bill, "collections": collections,
                "qualification": "working_ledger_historical_synthetic_contributors"}

    def require_current_project_finance(self, project_id):
        self._unsupported_current_project(project_id)
        sources = self.source_inventory(project_ids=(project_id,))
        native_ids = {row["id"] for row in self.db.query("SELECT id FROM prime_bills WHERE project_id=?", (project_id,))}
        if native_ids != {source["bill"]["id"] for source in sources}:
            raise OwnerBillingError("Owner current project includes an unclassified native owner bill")
        current = [self.current_ar_proof(source["bill"]["id"]) for source in sources]
        # The first route cannot make unrelated labor/reimbursement AR or a
        # deleted retainage invoice disappear from its project totals.
        ar = self.c.receivables.ar_open_items(project_id)
        if any(item.get("source") != "prime_bill" or item.get("prime_bill_id") not in native_ids for item in ar["items"]):
            raise OwnerBillingError("Owner current project includes a separately unqualified AR source")
        if not ar["reconciled"]:
            raise OwnerBillingError("Owner proven current project AR does not reconcile to its native control")
        return {"projectId": project_id, "bills": current, "ar": ar}

    def send_source_preflight(self, bill_id):
        standing = self.current_ar_proof(bill_id)
        basis = standing["source"]["basis"]["record"]
        if (not _same(self.c.receivables.payment_terms(basis["customer_id"]), basis["terms"])
                or not _same(self.c.receivables.billing_recipients(basis["customer_id"]), basis["recipients"])):
            raise StaleApprovalError("Changed owner terms/recipients require a separately qualified source declaration before a fresh send")
        return standing

    def send_proof(self, bill_id):
        source = self.source_proof(bill_id)
        return self._send_proof_for_source(source)

    def _send_proof_for_source(self, source, posting=None):
        bill_id = source["bill"]["id"]
        records = self.db.query("SELECT * FROM prime_bill_sends WHERE prime_bill_id=?", (bill_id,))
        events = self.db.query("SELECT * FROM audit_log WHERE action='prime_bill.sent' AND entity_type='prime_bill' AND entity_id=? ORDER BY seq", (bill_id,))
        if not records and not events:
            return None
        posting = posting or self._posting_receipt_for_source(source)
        if posting is None:
            raise OwnerBillingError("owner send requires its original independent posting")
        if len(records) != 1 or len(events) != 1:
            raise OwnerBillingError("owner send original inventory changed")
        record, event = records[0], events[0]
        proof = self.approval_proof(record["approval_id"])
        approval = proof["approval"]
        bindings = approval["manifest"]["bindings"]
        keys = ("bill_hash", "sequence", "received", "credited_by_memo", "written_off", "deposits_applied", "balance_due", "customer_id", "channel", "recipients")
        message = {"prime_bill_id": bill_id, "amount_due": approval["manifest"]["amounts"]["amount_due"], **{key: bindings[key] for key in keys}}
        if bindings.get("invoice_date"):
            message.update(invoice_date=bindings["invoice_date"], due_date=bindings["due_date"])
        original = {**record, "recipients": loads(record["recipients_json"])}
        del original["recipients_json"]
        expected_event = {"channel": record["channel"], "customer_id": source["bill"]["customer_id"], "recipients": original["recipients"],
                          "approval_id": record["approval_id"], "send_id": record["id"], "message_hash": record["message_hash"]}
        if (approval["operation"] != "prime_bill.send" or approval["subject_id"] != bill_id or approval["status"] != "consumed"
                or approval["consumed_by"] != record["sent_by"] or event["actor"] != record["sent_by"]
                or not _same(loads(event["payload_json"]), expected_event)
                or bindings.get("owner_source_hash") != source["sourceHash"] or bindings.get("owner_posting_hash") != hash_json(posting)
                or hash_json(message) != record["message_hash"] or bindings.get("message_hash") != record["message_hash"]
                or record["bill_hash"] != source["bill"]["content_hash"] or record["channel"] != "mail-sink"
                or not _same(original["recipients"], bindings["recipients"])):
            raise OwnerBillingError("owner send differs from its original exact message, source or authorization")
        if not 0 <= (parse_iso(event["ts"]) - parse_iso(record["sent_at"])).total_seconds() <= 1:
            raise OwnerBillingError("owner send attribution time changed")
        return {"record": original, "approval": approval, "originalMessage": message, "sendEvent": _ref(event)}

    def _current_native_lifecycle(self, source):
        bill = source["bill"]
        for grant in self._inventory("grants", (source["projectId"],)):
            if grant["prime_bill_id"] == bill["id"]:
                self._grant_proof_for_source(source, approval_id=grant["approval_id"])
        receipt = self._posting_receipt_for_source(source)
        send = self._send_proof_for_source(source, receipt)
        if receipt is None:
            posted_events = self.db.one("SELECT seq FROM audit_log WHERE action='prime_bill.posted' AND entity_type='prime_bill' AND entity_id=? LIMIT 1", (bill["id"],))
            journals = self.db.one("SELECT id FROM journals WHERE source_type='prime_bill' AND source_id=? LIMIT 1", (bill["id"],))
            if (bill["recorded_status"] != "draft" or bill["approval_id"] is not None or bill["journal_id"] is not None
                    or bill["due_date"] is not None or bill["payment_terms_days"] is not None
                    or posted_events is not None or journals is not None or send is not None):
                raise OwnerBillingError("owner native draft has an unaudited financial or sent lifecycle")
            return
        if bill["recorded_status"] not in ("posted", "sent", "collected"):
            raise OwnerBillingError("owner native lifecycle lost its original independent posting")
        if bill["recorded_status"] == "sent" and send is None or bill["recorded_status"] == "posted" and send is not None:
            raise OwnerBillingError("owner sent status differs from its original exact send record")
        covered = Decimal(bill["received"]) >= Decimal(bill["amount_due"]) and Decimal(bill["amount_due"]) > 0
        if (bill["recorded_status"] == "collected") != covered:
            raise OwnerBillingError("owner collected status differs from standing original native collection amounts")

    def integrity_checks(self):
        try:
            if not self._schema_installed():
                return []
            if self.db.one("SELECT 1 FROM audit_log WHERE action LIKE 'owner_billing.%' LIMIT 1") is None:
                return []
            self.basis_inventory()
            for source in self.source_inventory():
                receipt = self.posting_receipt(source["bill"]["id"])
                if receipt:
                    self.send_proof(source["bill"]["id"])
            for body in self._inventory("grants"):
                self.grant_proof(body["prime_bill_id"], approval_id=body["approval_id"])
            self._inventory("postings")
            self.approval_inventory()
            return [{"check": "Owner billing original sources and posting intact", "ok": True, "detail": "Original owner basis, certifications, grants and postings match their audited history"}]
        except Exception as exc:
            return [{"check": "Owner billing original sources and posting intact", "ok": False, "detail": str(exc)}]

    def close_checks(self, period_id):
        return [{**check, "check": "Global owner source-integrity prerequisite",
                 "detail": f"Global source integrity; not a posting or adjustment attributed to period {period_id}. {check['detail']}"}
                for check in self.integrity_checks()]

    def manifest_for(self, operation, subject_id, *, actor_role):
        return None

    def apply(self, operation, subject_id, *, approval_id, manifest, actor, period_id):
        raise OwnerBillingError("owner billing exposes separate native preparation, grant and posting only")

    def state(self, project_id=None):
        project_ids = (project_id,) if project_id is not None else None
        return {"bases": self.basis_inventory(project_ids), "sources": self.source_inventory(project_ids), "integrity": self.integrity_checks()}

    def audit_export(self):
        return {"bases": self.basis_inventory(), "sources": self.source_inventory(),
                "grants": self.grant_inventory(), "postings": self._inventory("postings"),
                "approvals": self.approval_inventory(), "integrity": self.integrity_checks(),
                "currentContributorBoundary": "Historical synthetic check/wire collections and returns; other contributor routes require separate qualification"}
