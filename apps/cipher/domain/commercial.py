"""Review prototype: manual estimate facts and exact draft subcontract handoff.

Import registers no schema. The fixed practice entry appends schema72 after71.
This module has no provider, send, signature, execution or geometry operation.
"""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal, localcontext
import re
from typing import Any

from ..core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow_iso
from ..core.money import D, fmt, money, rate, total
from ..core.approvals import material_hash

PLUGIN_NAME = "commercial"
SCHEMA_NAME = "commercial_manual_sources_and_handoffs"
DEFER_SCHEMA_REGISTRATION = True
METHOD = "manual_entry"
GEOMETRY_VERIFIED = False
CONTRACT_VERSION = "cipher.commercial-practice.v1"
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")

class CommercialError(RuntimeError):
    pass

_SPECS = {
    "estimate_sources": ("estimate_id TEXT NOT NULL UNIQUE REFERENCES estimates(id), project_id TEXT NOT NULL REFERENCES projects(id), document_revision_id TEXT NOT NULL REFERENCES document_revisions(id)", "", ("estimate_id", "project_id", "document_revision_id")),
    "line_sources": ("estimate_id TEXT NOT NULL REFERENCES estimates(id), estimate_line_id TEXT NOT NULL UNIQUE REFERENCES estimate_lines(id), stable_line_id TEXT NOT NULL, previous_line_id TEXT REFERENCES estimate_lines(id)", "UNIQUE(estimate_id,stable_line_id), UNIQUE(estimate_id,previous_line_id)", ("estimate_id", "estimate_line_id", "stable_line_id", "previous_line_id")),
    "packages": ("project_id TEXT NOT NULL REFERENCES projects(id), supplier_id TEXT NOT NULL REFERENCES parties(id), version INTEGER NOT NULL CHECK(version>0)", "UNIQUE(project_id,version)", ("project_id", "supplier_id", "version")),
    "handoffs": ("estimate_id TEXT NOT NULL REFERENCES estimates(id), project_id TEXT NOT NULL REFERENCES projects(id), package_id TEXT NOT NULL REFERENCES commercial_packages(id)", "UNIQUE(estimate_id,package_id)", ("estimate_id", "project_id", "package_id")),
    "commitment_sources": ("handoff_id TEXT NOT NULL UNIQUE REFERENCES commercial_handoffs(id), commitment_id TEXT NOT NULL UNIQUE REFERENCES commitments(id), project_id TEXT NOT NULL REFERENCES projects(id)", "", ("handoff_id", "commitment_id", "project_id")),
}
_BIRTH = {kind: f"commercial.{kind}_recorded" for kind in _SPECS}
SCHEMA_STATEMENTS = []
for _kind, (_fields, _unique, _keys) in _SPECS.items():
    _checks = ", ".join(f"CHECK(json_extract(body_json,'$.{key}') IS {key})" for key in ("id", *_keys))
    SCHEMA_STATEMENTS.append(f"CREATE TABLE commercial_{_kind} (id TEXT PRIMARY KEY, {_fields}, body_json TEXT NOT NULL CHECK(json_valid(body_json)), row_hash TEXT NOT NULL, {_checks}{', '+_unique if _unique else ''})")
for _kind in _SPECS:
    _table = f"commercial_{_kind}"
    SCHEMA_STATEMENTS += [
        f"CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN SELECT RAISE(ABORT,'commercial source records are immutable'); END",
        f"CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT,'commercial source records are append-only'); END",
        f"CREATE TRIGGER {_table}_birth BEFORE INSERT ON {_table} BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM {_table} WHERE id=NEW.id) THEN RAISE(ABORT,'commercial source cannot be replaced') END; SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='{_BIRTH[_kind]}' AND entity_type='{_table}' AND entity_id=NEW.id AND json_extract(payload_json,'$.rowHash')=NEW.row_hash) THEN RAISE(ABORT,'commercial source requires its original audit') END; END",
    ]

def register_commercial_schema():
    old = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if old is not None and old[0] == 72:
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 71:
        raise CommercialError("commercial schema requires the unchanged historical71-entry catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)

def _text(value, name, *, limit=500):
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise CommercialError(f"{name} must be bounded plain text")
    return value.strip()

def _decimal(value, name):
    if type(value) is not str or len(value) > 64 or not _DECIMAL.fullmatch(value):
        raise CommercialError(f"{name} must be exact plain decimal text")
    return D(value)

def _cents(value):
    parsed = D(value)
    with localcontext() as ctx:
        ctx.prec = 32
        cents = parsed*100
        if cents != cents.to_integral_value():
            raise CommercialError("source money must be exact cents")
        return int(cents)



def _recorded_time(value, event, what):
    try:
        if type(value) is not str:
            raise ValueError("missing original attribution time")
        recorded, audited = parse_iso(value), parse_iso(event["ts"])
        if recorded.utcoffset() is None or not 0 <= (audited-recorded).total_seconds() <= 1:
            raise ValueError("changed original attribution time")
    except (ValueError, TypeError) as exc:
        raise CommercialError(f"{what} time differs from its original audited act") from exc
    return recorded


def require_commercial_duty(cipher, actor, project_id, duty):
    if duty not in ("estimator", "pm"):
        raise CommercialError("unsupported fixed commercial duty")
    people = cipher.plugin("people")
    people._require_intact()
    person = people._person_row(actor)
    if (person is None or person["kind"] != "person" or person["status"] != "active"
            or people._membership(person["id"], project_id) is None):
        raise CommercialError("commercial action needs an active registered project person")
    grants = [grant for grant in people._live_grants(person["id"], people._today()) if grant["role"] == duty and grant["scope"] == "project" and grant["project_id"] == project_id]
    if not grants:
        raise CommercialError(f"commercial action needs its own actual project {duty} grant")
    return {"personId": person["id"], "login": person["login"], "projectId": project_id, "duty": duty, "grantIds": [grant["id"] for grant in grants]}

class Plugin:
    GOVERNOR = True
    def __init__(self, cipher):
        self.c, self.db, self.audit = cipher, cipher.db, cipher.audit
        self._savepoint = 0

    @contextmanager
    def _atomic(self):
        self.db.require_practice_mode()
        self.db.require_write_authority()
        if not self.db.in_memory:
            raise CommercialError("this first manual commercial practice entry writes disposable memory workspaces only")
        with self.db.transaction() as conn:
            self._savepoint += 1
            name = f"commercial_act_{self._savepoint}"
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
        if not self._schema_installed():
            raise CommercialError("commercial source schema is not installed")
        stamp = (self.db.conn.total_changes, self.db.scalar("PRAGMA data_version"), self.db.scalar("PRAGMA schema_version"))
        if stamp == getattr(self, "_verified_stamp", None):
            return
        if not self.audit.verify_chain()["ok"]:
            raise CommercialError("commercial source audit chain is broken")
        for sql in SCHEMA_STATEMENTS:
            match = re.match(r"CREATE TRIGGER (\w+)", sql)
            if match:
                row = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (match[1],))
                normalize = lambda value: re.sub(r"\s+", " ", value.strip())
                if row is None or normalize(row["sql"]) != normalize(sql):
                    raise CommercialError("commercial source storage guards changed")
        self._verified_stamp = stamp

    def _schema_installed(self):
        installed = self.db.one("SELECT version,statement_count,checksum FROM schema_version WHERE name=?", (SCHEMA_NAME,))
        if installed is not None:
            # Catalog ordinals fix registration order; database versions record
            # actual application order. A pre-mode copy installs its declared
            # mode only after an attested owner claim, shifting these positions.
            versions = [row["version"] for row in self.db.query("SELECT version FROM schema_version WHERE version<=? ORDER BY version", (installed["version"],))]
            if (installed["version"] < 1 or installed["version"] != len(versions)
                    or any(value != index for index, value in enumerate(versions, 1))
                    or installed["statement_count"] != len(SCHEMA_STATEMENTS)
                    or installed["checksum"] != catalog_checksum(SCHEMA_STATEMENTS)):
                raise CommercialError("commercial source schema differs from its original admission")
            return True
        tables = self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'commercial_*'")
        receipt_schema = self.db.one("SELECT version FROM schema_version WHERE name='commercial_practice_action_receipts'")
        births = self.db.one("SELECT seq FROM audit_log WHERE action IN (" + ",".join("?" for _ in _BIRTH) + ") LIMIT 1", tuple(_BIRTH.values()))
        if tables is not None or receipt_schema is not None or births is not None:
            raise CommercialError("commercial history lost its registered source admission")
        return False

    def _record(self, kind, body, *, actor):
        row = {"id": body["id"], **{key: body[key] for key in _SPECS[kind][2]}, "body_json": canonical_json(body)}
        row["row_hash"] = hash_json(row)
        self.audit.record(actor, _BIRTH[kind], f"commercial_{kind}", body["id"], {"rowHash": row["row_hash"]})
        keys = tuple(row)
        self.db.execute(f"INSERT INTO commercial_{kind} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(row[key] for key in keys))
        return body

    def _proof(self, kind, identifier):
        self._guards()
        row = self.db.one(f"SELECT * FROM commercial_{kind} WHERE id=?", (identifier,))
        if row is None:
            raise CommercialError("an audited commercial source disappeared")
        body = loads(row["body_json"])
        expected = hash_json({key: value for key, value in row.items() if key != "row_hash"})
        events = self.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=?", (_BIRTH[kind], f"commercial_{kind}", identifier))
        if (type(body) is not dict or canonical_json(body) != row["body_json"] or expected != row["row_hash"] or len(events) != 1
                or loads(events[0]["payload_json"]) != {"rowHash": expected}
                or canonical_json({key: body.get(key) for key in ("id", *_SPECS[kind][2])}) != canonical_json({key: row[key] for key in ("id", *_SPECS[kind][2])})
                or events[0]["actor"] != body["created_by"]):
            raise CommercialError("commercial source differs from its original canonical audited birth")
        return body

    def _inventory(self, kind):
        if not self._schema_installed():
            return []
        self._guards()
        events = self.db.query("SELECT entity_id FROM audit_log WHERE action=? AND entity_type=? ORDER BY seq", (_BIRTH[kind], f"commercial_{kind}"))
        ids = [event["entity_id"] for event in events]
        current = self.db.query(f"SELECT id FROM commercial_{kind}")
        if len(set(ids)) != len(ids) or set(ids) != {row["id"] for row in current}:
            raise CommercialError("commercial source inventory differs from its audited births")
        return [self._proof(kind, identifier) for identifier in ids]

    def require_duty(self, actor, project_id, duty):
        return require_commercial_duty(self.c, actor, project_id, duty)

    def _drawing(self, project_id, revision_id, *, current):
        revision = self.c.evidence.revision(revision_id)
        document = self.c.evidence.document(revision["document_id"])
        if document["project_id"] != project_id or document["kind"] != "drawing":
            raise CommercialError("manual facts need an owned drawing revision on their project")
        births = self.db.query("SELECT payload_json FROM audit_log WHERE action='document.registered' AND entity_type='document' AND entity_id=?", (document["id"],))
        if len(births) != 1 or loads(births[0]["payload_json"]) != {"project_id": project_id, "kind": "drawing", "title": document["title"]}:
            raise CommercialError("manual drawing metadata differs from its original registered source")
        rows = self.db.query("SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision", (document["id"],))
        events = self.db.query("SELECT payload_json FROM audit_log WHERE action='document.revised' AND entity_type='document' AND entity_id=? ORDER BY seq", (document["id"],))
        if not rows or len(rows) != len(events):
            raise CommercialError("manual drawing revision inventory differs from its audit")
        for number, (row, event) in enumerate(zip(rows, events), 1):
            if row["revision"] != number or loads(event["payload_json"]) != {"revision_id": row["id"], "revision": number, "content_hash": row["content_hash"], "note": row["note"]}:
                raise CommercialError("manual drawing revision differs from its original audited source")
        if current and rows[-1]["id"] != revision_id:
            raise CommercialError("the manual estimate needs the current owned drawing revision")
        return {"documentId": document["id"], "revisionId": revision_id, "contentHash": revision["content_hash"], "revision": revision["revision"], "title": document["title"]}

    def _input(self, body, *, revised):
        # The shared normalizer is loaded only after the historical catalog.
        # Importing this deferred governor must not register forecast schemas.
        from .forecast import normalize_cost_code
        fields = {"documentRevisionId", "lines", "priceBookRef", "inclusions", "exclusions", "contingencyRate", "measurementBasis"}
        if revised:
            fields.add("removedExclusions")
        if type(body) is not dict or set(body) != fields or type(body["lines"]) is not list or not 1 <= len(body["lines"]) <= 50:
            raise CommercialError("manual estimate input must contain its fixed complete typed fields")
        basis = _text(body["measurementBasis"], "manual measurement basis", limit=1000)
        _decimal(body["contingencyRate"], "contingency rate")
        engine, facts = [], []
        line_fields = {"description", "quantity", "unit", "unitPriceCents", "sourceLocator", "costCode"}
        if revised:
            line_fields.add("previousLineId")
        for number, raw in enumerate(body["lines"], 1):
            if type(raw) is not dict or set(raw) != line_fields:
                raise CommercialError("manual line input has unsupported or missing fields")
            quantity = _decimal(raw["quantity"], "manual quantity")
            if type(raw["unitPriceCents"]) is not int or not 0 <= raw["unitPriceCents"] < 10**15:
                raise CommercialError("manual unit price must be bounded exact integer cents")
            previous = raw.get("previousLineId")
            if previous is not None and (type(previous) is not str or not previous or len(previous)>160):
                raise CommercialError("previous line must identify the exact predecessor or be null")
            engine.append({"description": _text(raw["description"], "line description"), "quantity": quantity, "unit": _text(raw["unit"], "registered unit", limit=16), "unit_price": fmt(Decimal(raw["unitPriceCents"])/100)})
            facts.append({"line_no": number, "source_locator": _text(raw["sourceLocator"], "drawing/page locator", limit=256),
                          "cost_code": normalize_cost_code(_text(raw["costCode"], "mapped cost code", limit=64)), "method": METHOD, "verified_geometry": False,
                          "measurement_basis": basis, "previous_line_id": previous})
        return engine, facts, basis

    def _preparation(self, project_id, body, actor, *, previous=None):
        duty = self.require_duty(actor, project_id, "estimator")
        project = self._project(project_id)
        engine, facts, basis = self._input(body, revised=previous is not None)
        drawing = self._drawing(project_id, body["documentRevisionId"], current=True)
        previous_source = self.source(previous) if previous is not None else None
        if previous_source and previous_source["projectId"] != project_id:
            raise CommercialError("revision predecessor belongs to another project")
        continued = []
        for fact in facts:
            old_id = fact["previous_line_id"]
            old = None if old_id is None else next((line for line in previous_source["lines"] if line["estimate_line_id"] == old_id), None)
            if old_id is not None and (old is None or old_id in continued):
                raise CommercialError("manual line lineage must use a distinct immediate predecessor line")
            if old_id is not None:
                continued.append(old_id)
            fact["stable_line_id"] = old["stable_line_id"] if old is not None else None
        kwargs = {"supersedes": previous, "price_book_ref": body["priceBookRef"], "inclusions": body["inclusions"], "exclusions": body["exclusions"],
                  "contingency_rate": body["contingencyRate"], "measurement_basis": basis, "removed_exclusions": body.get("removedExclusions", ())}
        calculated = self.c.estimates.creation_preflight(project_id, body["documentRevisionId"], engine, **kwargs)
        return {"projectId": project_id, "project": {key: project[key] for key in ("id", "entity", "currency")}, "actor": duty, "input": loads(canonical_json(body)), "drawing": drawing,
                "previousId": previous, "previousSourceHash": None if previous_source is None else previous_source["sourceHash"],
                "engineLines": calculated["lines"], "manualFacts": facts, "estimatePlan": calculated, "engineOptions": kwargs}

    def create_preflight(self, project_id, body, *, actor):
        with self.db._lock:
            return self._preparation(project_id, body, actor)

    def revise_preflight(self, estimate_id, body, *, actor):
        with self.db._lock:
            project = self.db.scalar("SELECT project_id FROM estimates WHERE id=?", (estimate_id,))
            if project is None:
                raise CommercialError("unknown estimate predecessor")
            return self._preparation(project, body, actor, previous=estimate_id)

    def _create(self, plan):
        estimate = self.c.estimates.create(plan["projectId"], plan["drawing"]["revisionId"], plan["engineLines"], plan["actor"]["login"], **plan["engineOptions"])
        baseline = self.c.estimates.baseline_proof(estimate["id"])
        if canonical_json([{key: line[key] for key in ("line_no", "description", "quantity", "unit", "unit_price", "amount")} for line in baseline["lines"]]) != canonical_json(plan["engineLines"]):
            raise CommercialError("created estimate differs from its exact reviewed line plan")
        created_at = utcnow_iso()
        lines = []
        for engine_line, fact in zip(baseline["lines"], plan["manualFacts"]):
            line = {"id": new_id("cmlsource"), "estimate_id": estimate["id"], "estimate_line_id": engine_line["id"],
                    "stable_line_id": fact["stable_line_id"] or new_id("cmlstable"), "previous_line_id": fact["previous_line_id"],
                    "engine_line": engine_line, "drawing": plan["drawing"], **{key: fact[key] for key in ("source_locator", "cost_code", "method", "verified_geometry", "measurement_basis")},
                    "created_by": plan["actor"]["login"], "created_at": created_at}
            self._record("line_sources", line, actor=line["created_by"])
            lines.append(line)
        source = {"id": new_id("cmsource"), "estimate_id": estimate["id"], "project_id": plan["projectId"], "document_revision_id": plan["drawing"]["revisionId"],
                  "baseline": {key: value for key, value in baseline.items() if key != "acceptance"}, "drawing": plan["drawing"],
                  "project": plan["project"],
                  "line_source_ids": [line["id"] for line in lines], "line_facts_hash": hash_json(lines),
                  "previous_source_hash": plan["previousSourceHash"], "method": METHOD, "verified_geometry": False,
                  "created_by": plan["actor"]["login"], "created_at": created_at}
        self._record("estimate_sources", source, actor=source["created_by"])
        return self.source(estimate["id"])

    def create(self, project_id, body, *, actor):
        with self._atomic():
            return self._create(self.create_preflight(project_id, body, actor=actor))

    def revise(self, estimate_id, body, *, actor):
        with self._atomic():
            return self._create(self.revise_preflight(estimate_id, body, actor=actor))

    def source_scope(self, estimate_id):
        row = self.db.one("SELECT project_id FROM estimates WHERE id=?", (estimate_id,))
        if row is None:
            raise CommercialError("unknown estimate")
        return {"projectId": row["project_id"]}

    def source(self, estimate_id, *, current=False, accepted=False):
        with self.db._lock:
            sources, line_inventory = self._inventory("estimate_sources"), self._inventory("line_sources")
            row = next((source for source in sources if source["estimate_id"] == estimate_id), None)
            if row is None:
                raise CommercialError("this estimate has no original manual commercial source")
            baseline = self.c.estimates.baseline_proof(estimate_id, require_current=current, require_accepted=accepted)
            immutable = {key: value for key, value in baseline.items() if key != "acceptance"}
            project = self._project(row["project_id"])
            drawing = self._drawing(row["project_id"], row["document_revision_id"], current=current)
            lines = [line for line in line_inventory if line["estimate_id"] == estimate_id]
            if (canonical_json(row["baseline"]) != canonical_json(immutable) or canonical_json(row["project"]) != canonical_json({key: project[key] for key in ("id", "entity", "currency")})
                    or row["created_by"] != baseline["creation"]["actor"] or canonical_json(row["drawing"]) != canonical_json(drawing) or row["method"] != METHOD or row["verified_geometry"] is not False
                    or [line["id"] for line in lines] != row["line_source_ids"] or hash_json(lines) != row["line_facts_hash"]
                    or canonical_json([line["engine_line"] for line in lines]) != canonical_json(baseline["lines"])):
                raise CommercialError("manual source differs from its exact original estimate line inventory")
            for line in lines:
                if (line["method"] != METHOD or line["verified_geometry"] is not False or canonical_json(line["drawing"]) != canonical_json(drawing)
                        or line["created_by"] != row["created_by"] or line["created_at"] != row["created_at"]
                        or line["engine_line"]["id"] != line["estimate_line_id"] or line["measurement_basis"] != baseline["scope"]["measurement_basis"]):
                    raise CommercialError("manual drawing/page/method fact differs from its original source")
            estimate = self.c.estimates.get(estimate_id)
            if estimate["supersedes"]:
                previous = self.source(estimate["supersedes"])
                if row["previous_source_hash"] != previous["sourceHash"]:
                    raise CommercialError("manual revision lost its original predecessor source")
                for line in lines:
                    if line["previous_line_id"]:
                        old = next((old for old in previous["lines"] if old["estimate_line_id"] == line["previous_line_id"]), None)
                        if old is None or old["stable_line_id"] != line["stable_line_id"]:
                            raise CommercialError("manual revision line lost its exact predecessor lineage")
            elif row["previous_source_hash"] is not None or any(line["previous_line_id"] is not None for line in lines):
                raise CommercialError("initial manual source cannot reference another estimate line")
            return {"estimateId": estimate_id, "projectId": row["project_id"], "sourceHash": hash_json(row), "record": row,
                    "baseline": baseline, "drawing": drawing, "lines": lines, "manual": True, "verifiedGeometry": False}

    def source_inventory(self, *, project_ids):
        scopes = frozenset(project_ids)
        return [self.source(row["estimate_id"]) for row in self._inventory("estimate_sources") if row["project_id"] in scopes]

    def comparison(self, estimate_id):
        current = self.source(estimate_id)
        est = self.c.estimates.get(estimate_id)
        previous = self.source(est["supersedes"]) if est["supersedes"] else None
        old = {} if previous is None else {line["stable_line_id"]: line for line in previous["lines"]}
        new = {line["stable_line_id"]: line for line in current["lines"]}
        fields = ("description", "quantity", "unit", "unit_price", "amount")
        differences = []
        for stable in dict.fromkeys([*old, *new]):
            before, after = old.get(stable), new.get(stable)
            changed = []
            if before and after:
                changed = [field for field in fields if before["engine_line"][field] != after["engine_line"][field]]
                changed += [field for field in ("source_locator", "cost_code") if before[field] != after[field]]
            kind = "added" if before is None else "removed" if after is None else "changed" if changed else "unchanged"
            differences.append({"stableLineId": stable, "kind": kind, "before": before, "after": after, "changedFields": changed})
        before_cents = None if previous is None else _cents(previous["baseline"]["total"])
        return {"estimateId": estimate_id, "predecessorId": est["supersedes"], "lines": differences,
                "beforeCents": before_cents, "afterCents": _cents(current["baseline"]["total"]),
                "deltaCents": None if before_cents is None else _cents(current["baseline"]["total"])-before_cents,
                "beforeScope": None if previous is None else previous["baseline"]["scope"], "afterScope": current["baseline"]["scope"]}

    def _project(self, project_id):
        project = self.c.project(project_id)
        births = self.db.query("SELECT payload_json FROM audit_log WHERE action='project.created' AND entity_type='project' AND entity_id=?", (project_id,))
        # Historical project.created did not bind entity/currency. The explicit
        # synthetic package declaration and original acceptance manifest bind
        # those facts here; no absent old audit field is invented.
        if len(births) != 1 or loads(births[0]["payload_json"]).get("name") != project["name"] or project["currency"] != "USD":
            raise CommercialError("commercial handoff requires a registered synthetic USD project")
        return project

    def _supplier(self, supplier_id):
        supplier = self.c.party(supplier_id)
        births = self.db.query("SELECT * FROM audit_log WHERE action='party.created' AND entity_type='party' AND entity_id=?", (supplier_id,))
        if supplier["kind"] != "supplier" or len(births) != 1 or loads(births[0]["payload_json"]) != {"kind": "supplier", "name": supplier["name"]}:
            raise CommercialError("handoff supplier identity differs from its original registered source")
        return {"id": supplier["id"], "name": supplier["name"], "kind": "supplier", "auditSeq": births[0]["seq"], "auditHash": births[0]["entry_hash"]}

    def declare_package(self, project_id, supplier_id, title, retainage_rate, *, actor, reason):
        """Fixed fixture setup, explicit synthetic terms; no owner default policy."""
        with self._atomic():
            duty = self.require_duty(actor, project_id, "pm")
            project, supplier = self._project(project_id), self._supplier(supplier_id)
            parsed_rate = _decimal(retainage_rate, "explicit synthetic retainage rate")
            if not 0 <= parsed_rate <= 1 or parsed_rate.as_tuple().exponent < -6:
                raise CommercialError("explicit retainage must be in0..1 with at most six decimal places")
            rows = [package for package in self._inventory("packages") if package["project_id"] == project_id]
            body = {"id": new_id("cmpackage"), "project_id": project_id, "supplier_id": supplier_id, "version": len(rows)+1,
                    "previous_id": rows[-1]["id"] if rows else None, "title": _text(title, "subcontract package title"),
                    "retainage_rate": f"{rate(parsed_rate):f}", "entity": project["entity"], "currency": "USD", "supplier": supplier,
                    "mode": "practice", "synthetic": True, "reason": _text(reason, "synthetic package declaration reason"),
                    "created_by": duty["login"], "created_at": utcnow_iso()}
            self._record("packages", body, actor=duty["login"])
            return self.package(body["id"])

    def package(self, package_id, *, current=False):
        rows = self._inventory("packages")
        package = next((row for row in rows if row["id"] == package_id), None)
        if package is None:
            raise CommercialError("unknown audited handoff package")
        group = [row for row in rows if row["project_id"] == package["project_id"]]
        previous = None
        for version, row in enumerate(group, 1):
            if (row["version"] != version or row["previous_id"] != previous or row["mode"] != "practice" or row["synthetic"] is not True
                    or row["currency"] != "USD" or row["entity"] != self._project(row["project_id"])["entity"]
                    or row["supplier"] != self._supplier(row["supplier_id"])):
                raise CommercialError("handoff package lost its original declaration/terms chain")
            previous = row["id"]
        if current and group[-1]["id"] != package_id:
            raise CommercialError("the handoff package terms were superseded")
        return package

    def current_package(self, project_id, *, actor):
        self.require_duty(actor, project_id, "estimator")
        rows = [row for row in self._inventory("packages") if row["project_id"] == project_id]
        if not rows:
            raise CommercialError("no explicit audited synthetic handoff terms have been declared")
        return self.package(rows[-1]["id"], current=True)

    def _handoff_snapshot(self, estimate_id, package_id, *, current):
        source, package = self.source(estimate_id, current=current, accepted=True), self.package(package_id, current=current)
        baseline = source["baseline"]
        if source["projectId"] != package["project_id"]:
            raise CommercialError("handoff package belongs to another project")
        accepted_manifest = self.c.approvals.get(baseline["acceptance"]["approvalId"])["manifest"]
        if accepted_manifest["entity"] != package["entity"] or accepted_manifest["currency"] != package["currency"]:
            raise CommercialError("accepted estimate and handoff package have different original financial scopes")
        if _cents(baseline["contingency"]) != 0 or _cents(baseline["subtotal"]) != _cents(baseline["total"]):
            raise CommercialError("this all-line handoff requires zero contingency; allocating contingency needs a separate reviewed rule")
        lines = []
        for line in source["lines"]:
            engine = line["engine_line"]
            lines.append({"source_line_id": engine["id"], "stable_line_id": line["stable_line_id"], "line_no": engine["line_no"],
                          "description": engine["description"], "cost_code": line["cost_code"], "quantity": engine["quantity"],
                          "unit": engine["unit"], "unit_price": engine["unit_price"], "amount": engine["amount"],
                          "drawing": line["drawing"], "source_locator": line["source_locator"], "method": METHOD,
                          "verified_geometry": False, "measurement_basis": line["measurement_basis"]})
        if fmt(total(line["amount"] for line in lines)) != baseline["total"]:
            raise CommercialError("handoff must preserve every complete source line and exact accepted total")
        return {"estimateId": estimate_id, "projectId": source["projectId"], "source": source, "package": package,
                "lines": lines, "total": baseline["total"], "currency": "USD", "mode": "practice", "synthetic": True,
                "consequence": "creates one source-preserving draft subcontract only; approval, agreement, signature and execution remain separate"}

    def handoff_preflight(self, estimate_id, package_id, *, actor):
        with self.db._lock:
            self.require_duty(actor, self.source_scope(estimate_id)["projectId"], "estimator")
            snapshot = self._handoff_snapshot(estimate_id, package_id, current=True)
            rows = [row for row in self._inventory("handoffs") if row["estimate_id"] == estimate_id and row["package_id"] == package_id]
            if rows:
                raise CommercialError("this accepted source/package already has its immutable handoff")
            return snapshot

    def prepare_handoff(self, estimate_id, package_id, *, actor):
        with self._atomic():
            snapshot = self.handoff_preflight(estimate_id, package_id, actor=actor)
            duty = self.require_duty(actor, snapshot["projectId"], "estimator")
            row = {"id": new_id("cmhandoff"), "estimate_id": estimate_id, "project_id": snapshot["projectId"], "package_id": package_id,
                   "snapshot": snapshot, "snapshot_hash": hash_json(snapshot), "created_by": duty["login"], "created_at": utcnow_iso()}
            self._record("handoffs", row, actor=duty["login"])
            return self.handoff(row["id"])

    def handoff_scope(self, handoff_id):
        row = self.db.one("SELECT project_id,estimate_id FROM commercial_handoffs WHERE id=?", (handoff_id,))
        if row is None:
            raise CommercialError("unknown commercial handoff")
        return {"projectId": row["project_id"], "estimateId": row["estimate_id"]}

    def handoff(self, handoff_id, *, current=False):
        self._inventory("handoffs")
        row = self._proof("handoffs", handoff_id)
        expected = self._handoff_snapshot(row["estimate_id"], row["package_id"], current=current)
        if row["snapshot_hash"] != hash_json(expected) or canonical_json(row["snapshot"]) != canonical_json(expected) or row["project_id"] != expected["projectId"]:
            raise CommercialError("handoff differs from its immutable accepted estimate/package/line source")
        link = next((link for link in self._inventory("commitment_sources") if link["handoff_id"] == handoff_id), None)
        return {"handoffId": handoff_id, "projectId": row["project_id"], "record": row, "source": expected["source"],
                "package": expected["package"], "lines": expected["lines"], "total": expected["total"],
                "commitmentId": None if link is None else link["commitment_id"], "status": "prepared" if link is None else "draft_created"}

    def handoff_inventory(self, *, project_ids):
        scope = frozenset(project_ids)
        return [self.handoff(row["id"]) for row in self._inventory("handoffs") if row["project_id"] in scope]

    def commitment_preflight(self, handoff_id, *, actor):
        with self.db._lock:
            self.require_duty(actor, self.handoff_scope(handoff_id)["projectId"], "pm")
            handoff = self.handoff(handoff_id, current=True)
            if handoff["commitmentId"] is not None:
                raise CommercialError("this immutable handoff already created its one subcontract draft")
            package = handoff["package"]
            return {"handoff": handoff, "project_id": handoff["projectId"], "supplier_id": package["supplier_id"], "estimate_id": handoff["source"]["estimateId"],
                    "title": package["title"], "retainage_rate": package["retainage_rate"],
                    "sov_lines": [{"description": line["description"], "cost_code": line["cost_code"], "amount": line["amount"]} for line in handoff["lines"]],
                    "total": handoff["total"], "status": "draft"}

    def create_commitment(self, handoff_id, *, actor):
        with self._atomic():
            plan = self.commitment_preflight(handoff_id, actor=actor)
            duty = self.require_duty(actor, plan["project_id"], "pm")
            commitment = self.c.commitments.create(**{key: plan[key] for key in ("project_id", "supplier_id", "estimate_id", "title", "retainage_rate", "sov_lines")}, actor=duty["login"])
            snapshot = {key: commitment[key] for key in ("id", "project_id", "supplier_id", "estimate_id", "title", "original_amount", "retainage_rate", "created_at")}
            sov = [{key: line[key] for key in ("id", "commitment_id", "line_no", "description", "cost_code", "amount")} for line in commitment["sov"]]
            expected = [{"line_no": number, **line} for number, line in enumerate(plan["sov_lines"], 1)]
            if commitment["status"] != "draft" or canonical_json([{key: line[key] for key in ("line_no", "description", "cost_code", "amount")} for line in sov]) != canonical_json(expected) or commitment["original_amount"] != plan["total"]:
                raise CommercialError("draft subcontract differs from its exact reviewed source handoff")
            row = {"id": new_id("cmcommitment"), "handoff_id": handoff_id, "commitment_id": commitment["id"], "project_id": plan["project_id"],
                   "handoff_hash": hash_json(plan["handoff"]["record"]), "commitment": snapshot, "sov": sov,
                   "lineage": [{"source_line_id": source["source_line_id"], "stable_line_id": source["stable_line_id"], "sov_line_id": dest["id"], "source": source}
                               for source, dest in zip(plan["handoff"]["lines"], sov)],
                   "created_by": duty["login"], "created_at": utcnow_iso()}
            self._record("commitment_sources", row, actor=duty["login"])
            return self.commitment_proof(commitment["id"])

    def commitment_scope(self, commitment_id):
        row = self.db.one("SELECT project_id,handoff_id FROM commercial_commitment_sources WHERE commitment_id=?", (commitment_id,))
        if row is None:
            raise CommercialError("unknown commercial subcontract draft")
        return {"projectId": row["project_id"], "handoffId": row["handoff_id"]}

    def _commitment_lifecycle(self, commitment, handoff):
        if commitment["executed_amount"] != commitment["original_amount"]:
            raise CommercialError("this original handoff cannot attest an unrecorded or separately amended executed amount")
        events = self.db.query("SELECT * FROM audit_log WHERE entity_type='commitment' AND entity_id=? AND action IN ('commitment.executed','commitment.closed') ORDER BY seq", (commitment["id"],))
        if commitment["status"] == "draft":
            if (events or commitment["version"] != 1 or commitment.get("approval_id") is not None
                    or commitment.get("executed_at") is not None or commitment.get("closed_at") is not None):
                raise CommercialError("the original draft subcontract has unrecorded execution/closure facts")
            return
        if commitment["status"] not in ("executed", "closed") or not events or events[0]["action"] != "commitment.executed":
            raise CommercialError("the subcontract status has no original separate application")
        approval = self.c.approvals.get(commitment["approval_id"])
        manifest = approval["manifest"]
        lifecycle = [event for event in self.audit.entries(entity_type="approval", entity_id=approval["id"])
                     if event["action"] in ("approval.requested", "approval.granted", "approval.consumed", "approval.expired", "approval.invalidated")]
        if (tuple(event["action"] for event in lifecycle) != ("approval.requested", "approval.granted", "approval.consumed")
                or approval["operation"] != "commitment.execute" or approval["subject_type"] != "commitment" or approval["subject_id"] != commitment["id"]
                or approval["status"] != "consumed" or hash_json(manifest) != approval["manifest_hash"] or material_hash(manifest) != approval["material_hash"]
                or manifest.get("subject") != {"type": "commitment", "id": commitment["id"]} or manifest.get("operation") != "commitment.execute"
                or manifest.get("nonce") != approval["nonce"] or manifest.get("actor_role") != approval["actor_role"]
                or manifest.get("policy_version") != approval["policy_version"] or parse_iso(approval["expires_at"]) > parse_iso(manifest["expires_at"])):
            raise CommercialError("the subcontract application lost its original consumed authorization")
        for event, actor, payload in (
                (lifecycle[0], approval["requested_by"], {"operation": "commitment.execute", "subject": manifest["subject"], "manifest_hash": approval["manifest_hash"]}),
                (lifecycle[1], approval["approver"], {"operation": "commitment.execute", "material_hash": approval["material_hash"]}),
                (lifecycle[2], approval["consumed_by"], {"operation": "commitment.execute", "material_hash": approval["material_hash"]})):
            if event["actor"] != actor or loads(event["payload_json"]) != payload:
                raise CommercialError("the subcontract application differs from its original human decision")
        for event, field in zip(lifecycle, ("requested_at", "granted_at", "consumed_at")):
            _recorded_time(approval[field], event, "subcontract authorization")
        try:
            deadline = parse_iso(approval["expires_at"])
            if deadline.utcoffset() is None or deadline <= max(parse_iso(event["ts"]) for event in lifecycle[1:]):
                raise ValueError("expired original authorization")
        except (ValueError, TypeError) as exc:
            raise CommercialError("subcontract authorization deadline contradicts its original decisions") from exc
        expected = {"approval_id": approval["id"], "amount": commitment["original_amount"], "version": 2}
        bound = manifest.get("bindings", {})
        if (loads(events[0]["payload_json"]) != expected or events[0]["actor"] != approval["consumed_by"]
                or events[0]["seq"] <= lifecycle[2]["seq"] or commitment["executed_at"] is None
                or manifest.get("amounts", {}).get("total") != commitment["original_amount"]
                or bound.get("sov_hash") != self.c.commitments.sov_hash(commitment["id"])
                or bound.get("estimate_id") != handoff["source"]["estimateId"]
                or bound.get("estimate_hash") != handoff["source"]["baseline"]["contentHash"]):
            raise CommercialError("the subcontract application changed its original accepted source/SOV")
        _recorded_time(commitment["executed_at"], events[0], "subcontract execution")
        if commitment["status"] == "executed":
            if len(events) != 1 or commitment["version"] != 2 or commitment.get("closed_at") is not None or self.c.commitments.closure(commitment["id"]) is not None:
                raise CommercialError("subcontract execution lost its exact current lifecycle")
        else:
            closure = self.c.commitments.closure(commitment["id"])
            if (len(events) != 2 or events[1]["action"] != "commitment.closed" or commitment["version"] != 3 or closure is None
                    or closure["closed_at"] != commitment["closed_at"] or closure["closed_by"] != events[1]["actor"]
                    or loads(events[1]["payload_json"]) != {"version": 3, "basis": closure["basis"], "closeout_approval_id": closure["closeout_approval_id"], "executed_amount": commitment["executed_amount"]}):
                raise CommercialError("subcontract closure lost its original separate recorded act")

    def commitment_proof(self, commitment_id, *, current=False):
        rows = self._inventory("commitment_sources")
        row = next((row for row in rows if row["commitment_id"] == commitment_id), None)
        if row is None:
            raise CommercialError("subcontract has no original commercial handoff correspondence")
        handoff = self.handoff(row["handoff_id"], current=current)
        commitment = self.c.commitments.get(commitment_id)
        births = self.db.query("SELECT * FROM audit_log WHERE action='commitment.created' AND entity_type='commitment' AND entity_id=?", (commitment_id,))
        original = row["commitment"]
        if (len(births) != 1 or births[0]["actor"] != row["created_by"] or row["handoff_hash"] != hash_json(handoff["record"])
                or any(commitment[key] != value for key, value in original.items()) or row["project_id"] != handoff["projectId"]
                or loads(births[0]["payload_json"]) != {"project_id": original["project_id"], "supplier_id": original["supplier_id"], "estimate_id": original["estimate_id"], "original_amount": original["original_amount"]}):
            raise CommercialError("subcontract differs from its original handoff/header creation source")
        actual = [{key: line[key] for key in ("id", "commitment_id", "line_no", "description", "cost_code", "amount")} for line in commitment["sov"]]
        if canonical_json(actual) != canonical_json(row["sov"]) or len(row["lineage"]) != len(handoff["lines"]):
            raise CommercialError("this original handoff cannot attest an altered or separately amended SOV")
        for link, source, target in zip(row["lineage"], handoff["lines"], actual):
            if (canonical_json(link["source"]) != canonical_json(source) or link["source_line_id"] != source["source_line_id"] or link["stable_line_id"] != source["stable_line_id"]
                    or link["sov_line_id"] != target["id"] or any(source[key] != target[key] for key in ("line_no", "description", "cost_code", "amount"))):
                raise CommercialError("subcontract SOV lost its exact original priced/manual line correspondence")
        self._commitment_lifecycle(commitment, handoff)
        return {"commitmentId": commitment_id, "projectId": row["project_id"], "record": row, "handoff": handoff,
                "commitment": commitment, "lineage": row["lineage"], "status": commitment["status"], "currentCorrespondence": True}

    def approval_policy(self, operation, manifest):
        if operation == "estimate.approve":
            estimate_id = manifest["subject"]["id"]
            row = next((row for row in self._inventory("estimate_sources") if row["estimate_id"] == estimate_id), None)
            if row is None:
                return None
            source = self.source(estimate_id)
            return {"version": "manual-estimate-source.v1", "sourceHash": source["sourceHash"], "lineFactsHash": row["line_facts_hash"], "method": METHOD, "verifiedGeometry": False}
        if operation == "commitment.execute":
            row = next((row for row in self._inventory("commitment_sources") if row["commitment_id"] == manifest["subject"]["id"]), None)
            if row is None:
                return None
            proof = self.commitment_proof(row["commitment_id"], current=True)
            return {"version": "manual-handoff-correspondence.v1", "handoffHash": row["handoff_hash"], "sourceHash": proof["handoff"]["source"]["sourceHash"], "lineageHash": hash_json(row["lineage"])}
        return None

    def check_request(self, operation, manifest, *, actor_role, requested_by):
        if operation == "estimate.approve" and self.approval_policy(operation, manifest) is not None:
            if actor_role != "estimator":
                raise CommercialError("manual estimate acceptance requires the actual estimator duty")
            self.require_duty(requested_by, manifest["bindings"]["project_id"], "estimator")

    def check_grant(self, approval, *, approver, approver_role):
        if approval["operation"] == "estimate.approve" and self.approval_policy(approval["operation"], approval["manifest"]) is not None:
            if approver_role != "estimator":
                raise CommercialError("manual estimate review requires an actual estimator")
            self.require_duty(approver, approval["manifest"]["bindings"]["project_id"], "estimator")
            self.require_duty(approval["requested_by"], approval["manifest"]["bindings"]["project_id"], "estimator")
            if self.c.plugin("people").same_person(approval["requested_by"], approver):
                raise CommercialError("manual estimate acceptance needs a different estimator reviewer")

    def check_execute_preflight(self, approval, manifest, *, actor):
        if approval["operation"] == "estimate.approve" and self.approval_policy(approval["operation"], manifest) is not None:
            self.require_duty(actor, manifest["bindings"]["project_id"], "estimator")
            self.require_duty(approval["approver"], manifest["bindings"]["project_id"], "estimator")
            if self.c.plugin("people").same_person(approval["requested_by"], approval["approver"]):
                raise CommercialError("manual estimate application lost its independent reviewer")

    def check_execute(self, approval, manifest, *, actor):
        return self.check_execute_preflight(approval, manifest, actor=actor)

    def close_checks(self, period_id):
        try:
            inventory = {kind: self._inventory(kind) for kind in _SPECS}
            if not any(inventory.values()):
                return []
            for row in inventory["estimate_sources"]:
                self.source(row["estimate_id"])
            for row in inventory["handoffs"]:
                self.handoff(row["id"])
            for row in inventory["commitment_sources"]:
                self.commitment_proof(row["commitment_id"])
            return [{"check": "manual commercial source integrity", "ok": True, "detail": "original priced/manual lines and draft handoffs retain their audited source correspondence"}]
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            return [{"check": "manual commercial source integrity", "ok": False, "detail": str(exc)}]

    def export(self):
        inventory = {kind: self._inventory(kind) for kind in _SPECS}
        return {"mode": "practice", "synthetic": True, "method": METHOD, "verifiedGeometry": False,
                "sources": [self.source(row["estimate_id"]) for row in inventory["estimate_sources"]],
                "handoffs": [self.handoff(row["id"]) for row in inventory["handoffs"]],
                "commitments": [self.commitment_proof(row["commitment_id"]) for row in inventory["commitment_sources"]]}

    def manifest_for(self, operation, subject_id, *, actor_role):
        raise CommercialError("commercial drafts expose no generic consequential operation")

    def apply(self, operation, subject_id, **kwargs):
        raise CommercialError("commercial drafts expose no generic consequential operation")

    def state(self, project_id):
        return {"mode": "practice", "synthetic": True, "sources": self.source_inventory(project_ids=(project_id,)),
                "handoffs": self.handoff_inventory(project_ids=(project_id,))}
