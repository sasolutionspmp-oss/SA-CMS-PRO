"""Project-owned authored text and independently reviewed reference adoption.

This module stores actual UTF-8 text. Core Evidence only attests its hash.
Import is inert; schema76 registers after the unchanged actual75 catalog.
Adoption is an internal project reference, never execution, signature or issue.
"""
from __future__ import annotations

from contextlib import contextmanager
import re
from typing import Any

from ..core.approvals import (ApprovalError, ApprovalExpired, StaleApprovalError,
                              build_manifest, material_hash)
from ..core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, parse_iso, sha256_hex, utcnow

PLUGIN_NAME = "library"
SCHEMA_NAME = "library_authored_text_and_reference_adoptions"
DEFER_SCHEMA_REGISTRATION = True
OPERATION = "library.adopt_reference"
SOURCE_KIND = "practice-authored-editor-text/1"
EFFECT_KIND = "project-reference-only/1"
KINDS = ("specification_template", "contract_clause")
_SPECS = {
    "entries": ("document_id TEXT NOT NULL UNIQUE REFERENCES documents(id)", ("document_id",), ""),
    "revisions": ("entry_id TEXT NOT NULL REFERENCES library_entries(id), evidence_revision_id TEXT NOT NULL UNIQUE REFERENCES document_revisions(id), revision INTEGER NOT NULL CHECK(revision>0), text TEXT NOT NULL", ("entry_id", "evidence_revision_id", "revision", "text"), ", UNIQUE(entry_id,revision)"),
    "heads": ("entry_id TEXT NOT NULL REFERENCES library_entries(id), revision_id TEXT NOT NULL UNIQUE REFERENCES library_revisions(id)", ("entry_id", "revision_id"), ""),
    "plans": ("entry_id TEXT NOT NULL REFERENCES library_entries(id), revision_id TEXT NOT NULL REFERENCES library_revisions(id)", ("entry_id", "revision_id"), ""),
    "adoptions": ("plan_id TEXT NOT NULL UNIQUE REFERENCES library_plans(id), revision_id TEXT NOT NULL REFERENCES library_revisions(id), approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id), text TEXT NOT NULL", ("plan_id", "revision_id", "approval_id", "text"), ""),
}
SCHEMA_STATEMENTS = []
for _kind, (_fields, _keys, _unique) in _SPECS.items():
    _checks = ", ".join(f"CHECK(json_extract(body_json,'$.{key}') IS {key})" for key in ("id", "project_id", *_keys))
    SCHEMA_STATEMENTS.append(f"CREATE TABLE library_{_kind} (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), {_fields}, body_json TEXT NOT NULL CHECK(json_valid(body_json)), row_hash TEXT NOT NULL, {_checks}{_unique})")
for _kind in _SPECS:
    _table = f"library_{_kind}"
    SCHEMA_STATEMENTS.extend((
        f"CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN SELECT RAISE(ABORT,'library originals are immutable'); END",
        f"CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT,'library history is append-only'); END",
        f"CREATE TRIGGER {_table}_birth BEFORE INSERT ON {_table} BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM {_table} WHERE id=NEW.id) THEN RAISE(ABORT,'library original cannot be replaced') END; SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='library.{_kind}_recorded' AND entity_type='{_table}' AND entity_id=NEW.id AND json_extract(payload_json,'$.rowHash')=NEW.row_hash) THEN RAISE(ABORT,'library original needs its audited birth') END; END",
    ))


class LibraryError(ApprovalError):
    pass


def register_library_schema():
    old = next((entry for entry in SCHEMA_CATALOG if entry[1] == SCHEMA_NAME), None)
    if old is not None:
        if old[0] != 76:
            raise LibraryError("library must retain schema76")
        return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
    if len(SCHEMA_CATALOG) != 75 or SCHEMA_CATALOG[-1][1] != "ar_practice_action_receipts":
        raise LibraryError("library requires the genuine unchanged75-entry catalog")
    return register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)


def _same(left, right):
    return canonical_json(left) == canonical_json(right)


def _ref(event):
    return {"seq": event["seq"], "hash": event["entry_hash"]}


def _plain(value, name, maximum=1000):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise LibraryError(f"{name} must be bounded plain text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise LibraryError(f"{name} must be valid UTF-8") from exc
    return value.strip()


def _text(value):
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise LibraryError("text must contain authored UTF-8 text without NUL")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise LibraryError("text must be valid UTF-8") from exc
    if len(raw) > 65536:
        raise LibraryError("authored text exceeds the first-slice 64 KiB limit")
    return {"text": value, "contentHash": sha256_hex(raw), "byteCount": len(raw), "encoding": "UTF-8"}


def _body(body, fields):
    if type(body) is not dict or set(body) != set(fields):
        raise LibraryError("the authored text body must contain exactly " + ", ".join(fields))
    return body


def require_library_pm(cipher, actor, project_id):
    """Pure, actual same-project PM authority; owner/delegations never substitute."""
    cipher.db.require_practice_mode()
    people = cipher.plugin("people")
    people._require_intact()
    policy = people.current_policy()
    if not policy or not policy["intact"] or not policy["enforce"] or not policy["segregate"] or policy["solo_owner_self_approval"]:
        raise LibraryError("library requires segregated registered practice people")
    person = people._person_row(actor)
    if (not person or person["kind"] != "person" or person["status"] != "active" or person.get("external")
            or not people._membership(person["id"], project_id)):
        raise LibraryError("library requires an active internal registered project person")
    grants = [g for g in people._live_grants(person["id"], people._today())
              if g["role"] == "pm" and g["scope"] == "project" and g["project_id"] == project_id]
    if not grants:
        raise LibraryError("library requires its own actual project PM grant")
    return {"personId": person["id"], "login": person["login"], "projectId": project_id,
            "role": "pm", "grantIds": sorted(g["id"] for g in grants)}


class Plugin:
    GOVERNOR = True

    def __init__(self, cipher):
        self.c, self.db, self.audit = cipher, cipher.db, cipher.audit

    @contextmanager
    def atomic(self):
        self.db.require_practice_mode()
        self.db.require_write_authority()
        if not self.db.in_memory:
            raise LibraryError("authored library writes require owned memory practice")
        with self.db.transaction() as conn:
            name = new_id("library_act")
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

    def _installed(self):
        admission = self.db.one("SELECT version,statement_count,checksum FROM schema_version WHERE name=?", (SCHEMA_NAME,))
        tables = {r["name"] for r in self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'library_*'")}
        source_tables = tables - {"library_action_receipts"}
        if admission:
            physical = [r["version"] for r in self.db.query("SELECT version FROM schema_version WHERE version<=? ORDER BY version", (admission["version"],))]
            if (admission["version"] < 1 or admission["version"] != len(physical)
                    or any(value != index for index, value in enumerate(physical, 1)) or admission["statement_count"] != len(SCHEMA_STATEMENTS)
                    or admission["checksum"] != catalog_checksum(SCHEMA_STATEMENTS)
                    or source_tables != {"library_" + k for k in _SPECS}):
                raise LibraryError("library schema differs from its original admission")
            return True
        receipts = self.db.one("SELECT name FROM schema_version WHERE name='library_practice_action_receipts'")
        if tables or receipts or self.db.one("SELECT seq FROM audit_log WHERE action GLOB 'library.*' LIMIT 1"):
            raise LibraryError("library history lost its source admission")
        return False

    def _guards(self):
        if not self._installed() or not self.audit.verify_chain()["ok"]:
            raise LibraryError("library source schema or audit chain is unavailable")
        self.c.plugin("people")._require_intact()
        normalize = lambda s: re.sub(r"\s+", " ", s.strip())
        for sql in SCHEMA_STATEMENTS:
            match = re.match(r"CREATE TRIGGER (\w+)", sql)
            if match:
                actual = self.db.one("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (match[1],))
                if not actual or normalize(actual["sql"]) != normalize(sql):
                    raise LibraryError("library storage guard changed")

    def _inventory(self, kind, project_ids=None):
        if not self._installed():
            return []
        self._guards()
        if kind not in _SPECS:
            raise LibraryError("unknown library inventory")
        allowed = None if project_ids is None else set(project_ids)
        events = self.db.query("SELECT * FROM audit_log WHERE action=? ORDER BY seq", (f"library.{kind}_recorded",))
        expected = {}
        for event in events:
            payload = loads(event["payload_json"])
            record = payload.get("record", {})
            if allowed is None or record.get("project_id") in allowed:
                if event["entity_id"] in expected:
                    raise LibraryError("library original has duplicate births")
                expected[event["entity_id"]] = (event, payload)
        rows = self.db.query(f"SELECT * FROM library_{kind}")
        rows = {r["id"]: r for r in rows if allowed is None or r["project_id"] in allowed}
        if set(rows) != set(expected):
            raise LibraryError("library original inventory lost a birth or gained an unaudited row")
        result = []
        for identifier, (event, payload) in expected.items():
            row = rows[identifier]
            body = loads(row["body_json"])
            keys = ("id", "project_id", *_SPECS[kind][1])
            if (row["body_json"] != canonical_json(body) or row["row_hash"] != hash_json(body)
                    or not _same(payload, {"rowHash": row["row_hash"], "record": body})
                    or event["entity_type"] != f"library_{kind}" or event["entity_id"] != body.get("id")
                    or event["actor"] != body.get("actor", {}).get("login")
                    or any(not _same(row[k], body.get(k)) for k in keys)):
                raise LibraryError("library original differs from its audited birth")
            actor = body.get("actor", {})
            original_actor = self._original_pm(event["actor"], body["project_id"], event)
            if (actor.get("personId") != original_actor["personId"] or actor.get("projectId") != body["project_id"]
                    or actor.get("role") != "pm" or not _same(actor.get("grantIds"), original_actor["grantIds"])):
                raise LibraryError("library original lost its actual project PM provenance")
            result.append({"record": body, "rowHash": row["row_hash"], "birth": _ref(event)})
        return result

    def _record(self, kind, identifier):
        scope = self._scope(kind, identifier)
        if scope is None:
            raise LibraryError("unknown library record")
        found = [p for p in self._inventory(kind, (scope["projectId"],)) if p["record"]["id"] == identifier]
        if len(found) != 1:
            raise LibraryError("library original is missing")
        return found[0]

    def _scope(self, kind, identifier):
        if not self._installed():
            return None
        row = self.db.one(f"SELECT project_id FROM library_{kind} WHERE id=?", (identifier,))
        if row:
            return {"projectId": row["project_id"]}
        event = self.db.one("SELECT payload_json FROM audit_log WHERE action=? AND entity_id=? ORDER BY seq LIMIT 1", (f"library.{kind}_recorded", identifier))
        return {"projectId": loads(event["payload_json"])["record"]["project_id"]} if event else None

    def entry_scope(self, entry_id):
        return self._scope("entries", entry_id)

    def revision_scope(self, revision_id):
        return self._scope("revisions", revision_id)

    def plan_scope(self, plan_id):
        return self._scope("plans", plan_id)

    def adoption_scope(self, adoption_id):
        return self._scope("adoptions", adoption_id)

    def _put(self, kind, body):
        row_hash = hash_json(body)
        self.audit.record(body["actor"]["login"], f"library.{kind}_recorded", f"library_{kind}", body["id"], {"rowHash": row_hash, "record": body})
        keys = ("id", "project_id", *_SPECS[kind][1], "body_json", "row_hash")
        values = [body[k] for k in keys[:-2]] + [canonical_json(body), row_hash]
        self.db.execute(f"INSERT INTO library_{kind} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(values))
        return body

    def _source(self, revision):
        from .owned_sources import OwnedSourceError, owned_revision_proof
        try:
            owned = owned_revision_proof(self.c, revision["project_id"], revision["evidence_revision_id"])
        except OwnedSourceError as exc:
            raise LibraryError("authored owned evidence is unavailable: " + str(exc)) from exc
        entry = self._record("entries", revision["entry_id"])["record"]
        if (owned["document"]["id"] != entry["document_id"] or owned["document"]["kind"] != "library_" + entry["kind"]
                or owned["document"]["title"] != entry["title"] or owned["revision"]["content_hash"] != revision["contentHash"]
                or owned["revision"]["revision"] != revision["revision"]):
            raise LibraryError("authored text differs from its original owned evidence")
        return owned

    def entry_proof(self, entry_id, *, current=False):
        entry = self._record("entries", entry_id)
        body = entry["record"]
        revisions = [r for r in self._inventory("revisions", (body["project_id"],)) if r["record"]["entry_id"] == entry_id]
        heads = [r for r in self._inventory("heads", (body["project_id"],)) if r["record"]["entry_id"] == entry_id]
        previous_revision, previous_head = None, None
        for index, (revision, head) in enumerate(zip(revisions, heads), 1):
            r, h = revision["record"], head["record"]
            exact_text = _text(r["text"])
            if (r["revision"] != index or r["previousRevisionId"] != previous_revision
                    or h["revision_id"] != r["id"] or h["previousHeadId"] != previous_head
                    or h["revisionHash"] != revision["rowHash"] or not _same(r["actor"], h["actor"])
                    or not all(_same(r[k], v) for k, v in exact_text.items())
                    or r["sourceKind"] != SOURCE_KIND or not entry["birth"]["seq"] < revision["birth"]["seq"] < head["birth"]["seq"]):
                raise LibraryError("authored revision/current-pointer lineage is broken")
            self._source(r)
            previous_revision, previous_head = r["id"], h["id"]
        if (not revisions or len(revisions) != len(heads) or revisions[0]["record"]["id"] != body["initialRevisionId"]
                or body["sourceKind"] != SOURCE_KIND or body["kind"] not in KINDS):
            raise LibraryError("authored entry lost its original revision/current pointer")
        native_revisions = self.db.query("SELECT id FROM document_revisions WHERE document_id=? ORDER BY revision", (body["document_id"],))
        if [r["id"] for r in native_revisions] != [r["record"]["evidence_revision_id"] for r in revisions]:
            raise LibraryError("authored entry has an unowned native evidence revision")
        proof = {"entry": entry, "revisions": revisions, "heads": heads,
                 "currentRevisionId": previous_revision, "currentRevision": revisions[-1], "currentHead": heads[-1]}
        if current:
            proof["rights"] = self._rights(body)
        return proof

    def revision_proof(self, revision_id, *, current=False):
        revision = self._record("revisions", revision_id)
        entry = self.entry_proof(revision["record"]["entry_id"], current=current)
        if current and entry["currentRevisionId"] != revision_id:
            raise StaleApprovalError("a fresh library reference requires the current authored revision")
        return {"revision": revision, "entry": entry["entry"], "currentRevisionId": entry["currentRevisionId"],
                "currentHead": entry["currentHead"], **({"rights": entry["rights"]} if current else {})}

    def _rights(self, entry):
        from .owned_sources import OwnedSourceError, document_rights_proof
        try:
            proof = document_rights_proof(self.c, entry["project_id"], entry["document_id"], "project_use")
        except OwnedSourceError as exc:
            raise LibraryError("authored current rights are unavailable: " + str(exc)) from exc
        if not proof["allowed"]:
            raise LibraryError("current content rights refuse project use")
        if proof["hadLicenseHistory"]:
            raise LibraryError("licensed text history requires the later licensed-content ingestion workflow; untagging cannot reinterpret this authored source")
        return proof

    def require_project_integrity(self, project_id):
        """Reconcile the complete scoped source/request/copy inventories first."""
        for entry in self._inventory("entries", (project_id,)):
            self.entry_proof(entry["record"]["id"])
        for plan in self._inventory("plans", (project_id,)):
            self.plan_proof(plan["record"]["id"])
        self.approval_inventory(project_ids=(project_id,))
        self.adoption_inventory(project_ids=(project_id,))
        return {"projectId": project_id, "intact": True}

    def entry_inventory(self, *, project_ids):
        project_ids = tuple(project_ids)
        for project_id in project_ids:
            self.require_project_integrity(project_id)
        return [self.entry_proof(p["record"]["id"], current=True) for p in self._inventory("entries", project_ids)]

    def search(self, *, project_ids, query=""):
        if type(query) is not str or len(query) > 200:
            raise LibraryError("query must be bounded text")
        needle = query.casefold()
        result = []
        for proof in self.entry_inventory(project_ids=project_ids):
            entry, revision = proof["entry"]["record"], proof["currentRevision"]["record"]
            if needle in (entry["title"] + "\n" + revision["text"]).casefold():
                result.append({"entryId": entry["id"], "projectId": entry["project_id"], "kind": entry["kind"], "title": entry["title"],
                    "sourceKind": SOURCE_KIND, "currentRevisionId": revision["id"], "revision": revision["revision"],
                    "text": revision["text"], "contentHash": revision["contentHash"], "effectKind": EFFECT_KIND})
        return result

    def detail(self, entry_id, *, project_ids):
        scope = self.entry_scope(entry_id)
        if not scope or scope["projectId"] not in set(project_ids):
            raise LibraryError("library entry is outside the current project scope")
        self.require_project_integrity(scope["projectId"])
        return self.entry_proof(entry_id, current=True)

    def create_preflight(self, project_id, body, *, actor):
        person = require_library_pm(self.c, actor, project_id)
        self._guards()
        _body(body, ("kind", "title", "text", "sourceLocator"))
        if body["kind"] not in KINDS:
            raise LibraryError("only authored specification templates and contract clauses are supported")
        self.require_project_integrity(project_id)
        return {"person": person, "projectId": project_id, "kind": body["kind"], "title": _plain(body["title"], "title", 200),
                "sourceLocator": _plain(body["sourceLocator"], "sourceLocator"), **_text(body["text"]), "sourceKind": SOURCE_KIND}

    def create(self, project_id, body, *, actor):
        with self.atomic():
            plan = self.create_preflight(project_id, body, actor=actor)
            entry_id, revision_id = new_id("lib"), new_id("librev")
            document = self.c.evidence.register_document(project_id=project_id, kind="library_" + plan["kind"], title=plan["title"], actor=actor)
            evidence = self.c.evidence.add_revision(document_id=document["id"], content=plan["text"], note=plan["sourceLocator"], actor=actor)
            self._put("entries", {"id": entry_id, "project_id": project_id, "document_id": document["id"], "kind": plan["kind"],
                "title": plan["title"], "initialRevisionId": revision_id, "sourceKind": SOURCE_KIND, "actor": plan["person"]})
            self._revision(entry_id, revision_id, evidence, plan, 1, None, None, "Initial authored text")
            return self.entry_proof(entry_id, current=True)

    def _revision(self, entry_id, revision_id, evidence, plan, number, previous_revision, previous_head, reason):
        revision = self._put("revisions", {"id": revision_id, "project_id": plan["projectId"], "entry_id": entry_id,
            "evidence_revision_id": evidence["id"], "revision": number, "previousRevisionId": previous_revision,
            **{k: plan[k] for k in ("text", "contentHash", "byteCount", "encoding", "sourceLocator")},
            "changeReason": reason, "sourceKind": SOURCE_KIND, "actor": plan["person"]})
        self._put("heads", {"id": new_id("libhead"), "project_id": plan["projectId"], "entry_id": entry_id,
            "revision_id": revision_id, "revisionHash": hash_json(revision), "previousHeadId": previous_head, "actor": plan["person"]})

    def revise_preflight(self, entry_id, body, *, actor):
        scope = self.entry_scope(entry_id)
        if not scope:
            raise LibraryError("unknown authored entry")
        person = require_library_pm(self.c, actor, scope["projectId"])
        self.require_project_integrity(scope["projectId"])
        _body(body, ("previousRevisionId", "text", "sourceLocator", "changeReason"))
        original = self.entry_proof(entry_id, current=True)
        if body["previousRevisionId"] != original["currentRevisionId"]:
            raise StaleApprovalError("authored text changed; review the current revision before editing")
        return {"person": person, "projectId": scope["projectId"], "original": original, **_text(body["text"]),
                "sourceLocator": _plain(body["sourceLocator"], "sourceLocator"), "changeReason": _plain(body["changeReason"], "changeReason")}

    def revise(self, entry_id, body, *, actor):
        with self.atomic():
            plan = self.revise_preflight(entry_id, body, actor=actor)
            old = plan["original"]
            evidence = self.c.evidence.add_revision(document_id=old["entry"]["record"]["document_id"], content=plan["text"], note=plan["sourceLocator"], actor=actor)
            self._revision(entry_id, new_id("librev"), evidence, plan, old["currentRevision"]["record"]["revision"] + 1,
                           old["currentRevisionId"], old["currentHead"]["record"]["id"], plan["changeReason"])
            return self.entry_proof(entry_id, current=True)

    def reference_preflight(self, revision_id, body, *, actor):
        scope = self.revision_scope(revision_id)
        if not scope:
            raise LibraryError("unknown authored revision")
        person = require_library_pm(self.c, actor, scope["projectId"])
        self.require_project_integrity(scope["projectId"])
        _body(body, ("targetLocator", "purpose"))
        source = self.revision_proof(revision_id, current=True)
        return {"person": person, "source": source, "targetLocator": _plain(body["targetLocator"], "targetLocator"),
                "purpose": _plain(body["purpose"], "purpose"), "effectKind": EFFECT_KIND}

    def prepare_reference(self, revision_id, body, *, actor):
        with self.atomic():
            plan = self.reference_preflight(revision_id, body, actor=actor)
            source = plan["source"]
            return self._put("plans", {"id": new_id("libplan"), "project_id": plan["person"]["projectId"],
                "entry_id": source["entry"]["record"]["id"], "revision_id": revision_id,
                "revisionHash": source["revision"]["rowHash"], "sourceHeadId": source["currentHead"]["record"]["id"],
                "targetLocator": plan["targetLocator"], "purpose": plan["purpose"], "effectKind": EFFECT_KIND, "actor": plan["person"]})

    def plan_proof(self, plan_id, *, current=False):
        plan = self._record("plans", plan_id)
        p = plan["record"]
        source = self.revision_proof(p["revision_id"], current=current)
        if (source["entry"]["record"]["id"] != p["entry_id"] or source["entry"]["record"]["project_id"] != p["project_id"]
                or source["revision"]["rowHash"] != p["revisionHash"] or p["effectKind"] != EFFECT_KIND
                or not source["revision"]["birth"]["seq"] < plan["birth"]["seq"]):
            raise LibraryError("reference plan differs from the exact original authored revision")
        if current and source["currentHead"]["record"]["id"] != p["sourceHeadId"]:
            raise StaleApprovalError("fresh reference review requires the current authored revision")
        return {"plan": plan, "source": source}

    def plan_inventory(self, *, project_ids):
        return [self.plan_proof(p["record"]["id"]) for p in self._inventory("plans", project_ids)]

    def manifest_for(self, operation, subject_id, *, actor_role):
        if operation != OPERATION or actor_role != "pm":
            raise LibraryError("library reference adoption requires the fixed actual PM operation")
        proof = self.plan_proof(subject_id, current=True)
        plan, source = proof["plan"], proof["source"]
        project = self.c.project(plan["record"]["project_id"])
        rights = source["rights"]
        # Day is an expiry check, not a changing material input for untouched authored text.
        rights_material = {k: rights[k] for k in ("documentId", "use", "hadLicenseHistory", "allowed", "tags", "licenses", "purges", "events")}
        return build_manifest(operation=OPERATION, subject_type="library_reference_plan", subject_id=subject_id, actor_role="pm", entity=project["entity"],
            bindings={"project_id": project["id"], "plan_hash": plan["rowHash"], "entry_hash": source["entry"]["rowHash"],
                "revision_hash": source["revision"]["rowHash"], "content_hash": source["revision"]["record"]["contentHash"],
                "head_hash": source["currentHead"]["rowHash"], "rights_hash": hash_json(rights_material), "effect_kind": EFFECT_KIND})

    def _require_available_plan(self, plan_id, project_id):
        self.require_project_integrity(project_id)
        if any(a["record"]["plan_id"] == plan_id for a in self._inventory("adoptions", (project_id,))):
            raise LibraryError("reference plan is already adopted")

    def adoption_request_preflight(self, plan_id, *, actor, actor_role="pm"):
        scope = self.plan_scope(plan_id)
        if not scope:
            raise LibraryError("unknown library reference plan")
        person = require_library_pm(self.c, actor, scope["projectId"])
        self._require_available_plan(plan_id, scope["projectId"])
        plan = self.plan_proof(plan_id, current=True)
        if person["personId"] != plan["plan"]["record"]["actor"]["personId"]:
            raise LibraryError("the actual preparing PM must request the reference review")
        if actor_role != "pm":
            raise LibraryError("reference requests use the fixed PM role")
        return {**plan, "person": person, "manifest": self.c._manifest(OPERATION, plan_id, "pm")}

    def _original_pm(self, login, project_id, event):
        """Actual own duty at an audited act, independent of later revocation."""
        people = self.c.plugin("people")
        person = people._person_row(login)
        if not person or person["kind"] != "person" or person.get("external"):
            raise LibraryError("original library act lacks its registered internal person")
        def before(action, entity_type, identifier):
            return self.db.one("SELECT seq FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? AND seq<? LIMIT 1",
                               (action, entity_type, identifier, event["seq"])) is not None
        if (not before("people.person_registered", "people_person", person["id"])
                or before("people.person_deactivated", "people_person", person["id"])):
            raise LibraryError("original library actor was not active at its audited act")
        memberships = self.db.query("SELECT id FROM people_memberships WHERE person_id=? AND project_id=?", (person["id"], project_id))
        if not any(before("people.membership_added", "people_membership", m["id"])
                   and not before("people.membership_ended", "people_membership", m["id"]) for m in memberships):
            raise LibraryError("original library actor lacked actual project membership")
        day = parse_iso(event["ts"]).date().isoformat()
        grants = self.db.query("SELECT * FROM people_grants WHERE person_id=? AND role='pm' AND scope='project' AND project_id=?", (person["id"], project_id))
        own = [g for g in grants if g["effective_from"] <= day and (g["effective_to"] is None or g["effective_to"] >= day)
               and before("people.role_granted", "people_grant", g["id"]) and not before("people.role_revoked", "people_grant", g["id"])]
        if not own:
            raise LibraryError("original library actor lacked its own actual project PM grant")
        return {"personId": person["id"], "login": person["login"], "grantIds": sorted(g["id"] for g in own)}

    def approval_proof(self, approval_id):
        self._guards()
        ap = self.c.approvals.get(approval_id)
        m = ap["manifest"]
        if (ap["operation"] != OPERATION or ap["subject_type"] != "library_reference_plan" or ap["actor_role"] != "pm"
                or m.get("operation") != OPERATION or m.get("subject") != {"type": ap["subject_type"], "id": ap["subject_id"]}
                or m.get("actor_role") != "pm" or m.get("bindings", {}).get("effect_kind") != EFFECT_KIND
                or hash_json(m) != ap["manifest_hash"] or material_hash(m) != ap["material_hash"]
                or m.get("policy_version") != ap["policy_version"] or m.get("nonce") != ap["nonce"]
                or m.get("expires_at") != ap["expires_at"]):
            raise LibraryError("library authorization differs from its original manifest")
        plan = self.plan_proof(ap["subject_id"])
        if (m["bindings"].get("plan_hash") != plan["plan"]["rowHash"]
                or m["bindings"].get("revision_hash") != plan["source"]["revision"]["rowHash"]
                or ap["requested_by"] != plan["plan"]["record"]["actor"]["login"]):
            raise LibraryError("library authorization changed its original preparing PM/source")
        events = self.db.query("SELECT * FROM audit_log WHERE entity_type='approval' AND entity_id=? ORDER BY seq", (approval_id,))
        status, request, grant, consumed, reason = None, None, None, None, None
        transitions = {None: {"pending"}, "pending": {"granted", "expired", "invalidated"}, "granted": {"consumed", "expired", "invalidated"},
                       "expired": {"invalidated"}, "invalidated": {"invalidated"}, "consumed": set()}
        codes = {"approval.requested": "pending", "approval.granted": "granted", "approval.consumed": "consumed", "approval.expired": "expired", "approval.invalidated": "invalidated"}
        for event in events:
            next_status = codes.get(event["action"])
            if next_status is None:
                continue
            if next_status not in transitions[status]:
                raise LibraryError("library authorization lifecycle is broken")
            status, payload = next_status, loads(event["payload_json"])
            if status == "pending":
                request = event
                expected = {"operation": OPERATION, "subject": m["subject"], "manifest_hash": ap["manifest_hash"]}
            elif status in ("granted", "consumed"):
                expected = {"operation": OPERATION, "material_hash": ap["material_hash"]}
                if status == "granted":
                    grant = event
                else:
                    consumed = event
            else:
                expected = payload
                if status == "invalidated":
                    reason = f"subject changed after approval: {payload['diff']}" if set(payload) == {"reason", "diff"} and payload.get("reason") == "material change" else payload.get("reason")
            if not _same(payload, expected):
                raise LibraryError("library authorization original event changed")
        if (status != ap["status"] or request is None or request["actor"] != ap["requested_by"]
                or (grant["actor"] if grant else None) != ap["approver"] or (consumed["actor"] if consumed else None) != ap["consumed_by"]
                or status == "invalidated" and reason != ap["invalidated_reason"]
                or status != "invalidated" and ap["invalidated_reason"] is not None):
            raise LibraryError("library authorization row changed its audited lifecycle")
        try:
            deadline = parse_iso(ap["expires_at"])
            for field, event in (("requested_at", request), ("granted_at", grant), ("consumed_at", consumed)):
                if event is None:
                    if ap[field] is not None:
                        raise ValueError("unaudited attribution")
                elif not 0 <= (parse_iso(event["ts"]) - parse_iso(ap[field])).total_seconds() <= 1 or (field != "requested_at" and parse_iso(event["ts"]) >= deadline):
                    raise ValueError("invalid original chronology")
        except (TypeError, ValueError, AttributeError, OverflowError) as exc:
            raise LibraryError("library authorization original chronology changed") from exc
        requester = self._original_pm(ap["requested_by"], plan["plan"]["record"]["project_id"], request)
        if grant:
            reviewer = self._original_pm(ap["approver"], plan["plan"]["record"]["project_id"], grant)
            if requester["personId"] == reviewer["personId"]:
                raise LibraryError("original reference grant lacked independent actual PM review")
        if consumed:
            self._original_pm(ap["consumed_by"], plan["plan"]["record"]["project_id"], consumed)
        return {"approval": ap, "plan": plan, "requestEvent": _ref(request), "grantEvent": _ref(grant) if grant else None,
                "consumptionEvent": _ref(consumed) if consumed else None}

    def approval_inventory(self, *, project_ids):
        allowed = set(project_ids)
        expected = {}
        for event in self.db.query("SELECT * FROM audit_log WHERE action='approval.requested' ORDER BY seq"):
            payload = loads(event["payload_json"])
            if payload.get("operation") == OPERATION:
                scope = self.plan_scope(payload["subject"]["id"])
                if not scope:
                    raise LibraryError("library authorization lost its plan birth")
                if scope["projectId"] in allowed:
                    expected[event["entity_id"]] = event
        actual = {r["id"] for r in self.db.query("SELECT a.id,p.project_id FROM approvals a JOIN library_plans p ON p.id=a.subject_id WHERE a.operation=?", (OPERATION,)) if r["project_id"] in allowed}
        if actual != set(expected):
            raise LibraryError("library authorization inventory lost an original request")
        return [self.approval_proof(identifier) for identifier in expected]

    def _current_approval(self, approval_id, status):
        proof = self.approval_proof(approval_id)
        ap = proof["approval"]
        if ap["status"] != status:
            raise LibraryError(f"library authorization is not {status}")
        if parse_iso(ap["expires_at"]) <= utcnow():
            raise ApprovalExpired("library reference authorization expired")
        current = self.c._manifest(OPERATION, ap["subject_id"], "pm")
        if material_hash(current) != ap["material_hash"] or not _same(current.get("governance"), ap["manifest"].get("governance")):
            raise StaleApprovalError("authored reference source or governed facts changed after review")
        return {**proof, "manifest": current}

    def adoption_grant_preflight(self, approval_id, *, actor, actor_role="pm"):
        ap = self.c.approvals.get(approval_id)
        scope = self.plan_scope(ap["subject_id"])
        person = require_library_pm(self.c, actor, scope["projectId"] if scope else None)
        if actor_role != "pm":
            raise LibraryError("a distinct actual PM must review the reference")
        self._require_available_plan(ap["subject_id"], person["projectId"])
        checked = self._current_approval(approval_id, "pending")
        requester = require_library_pm(self.c, checked["approval"]["requested_by"], person["projectId"])
        if requester["personId"] == person["personId"]:
            raise LibraryError("a different actual PM must review the project reference")
        return {**checked, "person": person, "requester": requester, "governors": []}

    def adoption_execution_preflight(self, approval_id, *, actor):
        ap = self.c.approvals.get(approval_id)
        scope = self.plan_scope(ap["subject_id"])
        person = require_library_pm(self.c, actor, scope["projectId"] if scope else None)
        self._require_available_plan(ap["subject_id"], person["projectId"])
        checked = self._current_approval(approval_id, "granted")
        requester = require_library_pm(self.c, ap["requested_by"], person["projectId"])
        reviewer = require_library_pm(self.c, ap["approver"], person["projectId"])
        if requester["personId"] == reviewer["personId"]:
            raise LibraryError("reference reviewer must be independent of its preparing PM")
        return {**checked, "person": person, "requester": requester, "reviewer": reviewer}

    def apply(self, operation, subject_id, *, approval_id, manifest, actor, period_id=None):
        if operation != OPERATION or period_id is not None:
            raise LibraryError("reference adoption has no financial period or other effect")
        with self.atomic():
            proof = self.approval_proof(approval_id)
            ap = proof["approval"]
            p = proof["plan"]["plan"]["record"]
            person = require_library_pm(self.c, actor, p["project_id"])
            if ap["status"] != "consumed" or ap["subject_id"] != subject_id or ap["consumed_by"] != person["login"] or material_hash(manifest) != ap["material_hash"]:
                raise LibraryError("reference effect needs its exact originally consumed approval")
            if any(a["record"]["approval_id"] == approval_id for a in self._inventory("adoptions", (p["project_id"],))):
                raise LibraryError("reference approval was already applied")
            requester = require_library_pm(self.c, ap["requested_by"], p["project_id"])
            reviewer = require_library_pm(self.c, ap["approver"], p["project_id"])
            if requester["personId"] == reviewer["personId"]:
                raise LibraryError("a different actual PM must review the reference before adoption")
            current = self.c._manifest(OPERATION, subject_id, "pm")
            if material_hash(current) != ap["material_hash"] or not _same(current.get("governance"), ap["manifest"].get("governance")):
                raise StaleApprovalError("consumed reference no longer matches its original reviewed source")
            for name, governor in self.c._governors():
                if name == "people" or getattr(governor, "check_execute", None) is None:
                    continue
                check = getattr(governor, "check_execute_preflight", None)
                if check is None:
                    raise LibraryError("a configured governor lacks a pure reference application check")
                check(ap, current, actor=person["login"])
            source = self.plan_proof(subject_id, current=True)["source"]
            r = source["revision"]["record"]
            body = self._put("adoptions", {"id": new_id("libref"), "project_id": p["project_id"], "plan_id": subject_id,
                "revision_id": r["id"], "approval_id": approval_id, "text": r["text"], "contentHash": r["contentHash"],
                "revisionHash": source["revision"]["rowHash"], "planHash": hash_json(p), "targetLocator": p["targetLocator"], "purpose": p["purpose"],
                "effectKind": EFFECT_KIND, "manifest": ap["manifest"], "requestEvent": proof["requestEvent"], "grantEvent": proof["grantEvent"],
                "consumptionEvent": proof["consumptionEvent"], "requester": requester, "reviewer": reviewer, "actor": person})
            return self._result(body)

    @staticmethod
    def _result(body):
        return {"referenceId": body["id"], "planId": body["plan_id"], "projectId": body["project_id"],
                "revisionId": body["revision_id"], "contentHash": body["contentHash"], "effectKind": EFFECT_KIND, "status": "adopted_reference"}

    def adoption_proof(self, adoption_id):
        original = self._record("adoptions", adoption_id)
        body = original["record"]
        proof = self.approval_proof(body["approval_id"])
        ap = proof["approval"]
        p, source = proof["plan"]["plan"]["record"], proof["plan"]["source"]
        r = source["revision"]["record"]
        people = self.c.plugin("people")
        for key, login in (("requester", ap["requested_by"]), ("reviewer", ap["approver"]), ("actor", ap["consumed_by"])):
            person = people._person_row(login)
            recorded = body.get(key, {})
            if (not person or person["kind"] != "person" or person.get("external") or recorded.get("personId") != person["id"]
                    or recorded.get("login") != person["login"] or recorded.get("projectId") != p["project_id"] or recorded.get("role") != "pm"):
                raise LibraryError("reference lost its original actual person provenance")
        if body["requester"]["personId"] == body["reviewer"]["personId"]:
            raise LibraryError("reference lost independent original PM review")
        if (ap["status"] != "consumed" or ap["subject_id"] != body["plan_id"] or body["revision_id"] != r["id"]
                or body["text"] != r["text"] or body["contentHash"] != r["contentHash"] or body["revisionHash"] != source["revision"]["rowHash"]
                or body["planHash"] != hash_json(p) or body["targetLocator"] != p["targetLocator"] or body["purpose"] != p["purpose"]
                or body["effectKind"] != EFFECT_KIND or body["project_id"] != p["project_id"] or body["actor"]["login"] != ap["consumed_by"]
                or not _same(body["manifest"], ap["manifest"]) or any(not _same(body[k], proof[k]) for k in ("requestEvent", "grantEvent", "consumptionEvent"))
                or proof["consumptionEvent"]["seq"] >= original["birth"]["seq"]):
            raise LibraryError("adopted project reference differs from its original reviewed copy")
        return {**original, "approval": proof, "originalRevision": source["revision"], "effectKind": EFFECT_KIND}

    def original_reference_proof(self, adoption_id):
        """Immutable original copy and acts; no current pointer or rights decision."""
        proof = self.adoption_proof(adoption_id)
        approval = proof["approval"]
        ap = approval["approval"]
        return {"record": proof["record"], "rowHash": proof["rowHash"], "birth": proof["birth"],
                "originalRevision": proof["originalRevision"], "plan": approval["plan"]["plan"],
                "originalApproval": {k: ap[k] for k in ("id", "operation", "subject_type", "subject_id", "actor_role", "manifest",
                    "manifest_hash", "material_hash", "policy_version", "nonce", "requested_by", "requested_at", "expires_at",
                    "approver", "granted_at", "consumed_by", "consumed_at")},
                "requestEvent": approval["requestEvent"], "grantEvent": approval["grantEvent"], "consumptionEvent": approval["consumptionEvent"],
                "effectKind": EFFECT_KIND}

    def adoption_inventory(self, *, project_ids):
        return [self.adoption_proof(p["record"]["id"]) for p in self._inventory("adoptions", project_ids)]

    def execute_reference(self, approval_id, *, actor, op_id=None, period_id=None):
        if period_id is not None:
            raise LibraryError("reference adoption has no posting period")
        with self.atomic():
            proof = self.approval_proof(approval_id)
            ap = proof["approval"]
            person = require_library_pm(self.c, actor, proof["plan"]["plan"]["record"]["project_id"])
            op_id = op_id or f"exec:{approval_id}"
            payload = {"approval_id": approval_id, "operation": OPERATION, "subject_id": ap["subject_id"], "person_id": person["personId"]}
            cached = self.db.one("SELECT * FROM idempotency WHERE op_id=?", (op_id,))
            if cached:
                self._command_proof(op_id, payload, cached)
            def handler():
                checked = self.c.check_library_reference_execution(approval_id, actor=actor)
                self.c.approvals.consume(approval_id, current_manifest=checked["manifest"], consumer=actor)
                return self.apply(OPERATION, ap["subject_id"], approval_id=approval_id, manifest=checked["manifest"], actor=actor)
            result = self.c.commands.run(op_id, payload, handler, actor=actor)
            cached = self.db.one("SELECT * FROM idempotency WHERE op_id=?", (op_id,))
            expected = self._command_proof(op_id, payload, cached)
            if not _same(result.result, expected):
                raise LibraryError("reference command changed its exact original result")
            return result

    def _command_proof(self, op_id, payload, cached):
        if not cached or cached["payload_hash"] != hash_json(payload):
            raise LibraryError("reference repeatability identifier changed its actual person or request")
        events = self.db.query("SELECT * FROM audit_log WHERE action='command.executed' AND entity_type='command' AND entity_id=?", (op_id,))
        if len(events) != 1 or not _same(loads(events[0]["payload_json"]), {"payload_hash": hash_json(payload)}):
            raise LibraryError("reference command lost its original executed event")
        candidates = [p for p in self.adoption_inventory(project_ids=(self.plan_scope(payload["subject_id"])["projectId"],))
                      if p["record"]["approval_id"] == payload["approval_id"]]
        if len(candidates) != 1:
            raise LibraryError("reference command lost its original adoption")
        original = candidates[0]
        if (events[0]["actor"] != original["record"]["actor"]["login"]
                or payload["person_id"] != original["record"]["actor"]["personId"] or events[0]["seq"] <= original["birth"]["seq"]
                or not _same(loads(cached["result_json"]), self._result(original["record"]))):
            raise LibraryError("reference command differs from its original copied source")
        return self._result(original["record"])

    def integrity_checks(self):
        try:
            if not self._installed():
                return []
            inventory = {kind: self._inventory(kind) for kind in _SPECS}
            self.approval_inventory(project_ids=())  # classify every original request before empty admission
            if not any(inventory.values()):
                return []
            projects = {p["record"]["project_id"] for p in inventory["entries"]}
            for p in inventory["entries"]:
                self.entry_proof(p["record"]["id"])
            for p in inventory["plans"]:
                self.plan_proof(p["record"]["id"])
            self.approval_inventory(project_ids=projects)
            self.adoption_inventory(project_ids=projects)
            return [{"check": "library_original_integrity", "ok": True, "detail": "Exact authored text, current revision lineage and original reference copies agree with audited births."}]
        except Exception as exc:
            return [{"check": "library_original_integrity", "ok": False, "detail": str(exc)}]

    def close_checks(self, period_id):
        return self.integrity_checks()

    def state(self, project_id=None):
        if not self._installed():
            return {"entries": [], "references": [], "checks": []}
        projects = (project_id,) if project_id else tuple(p["record"]["project_id"] for p in self._inventory("entries"))
        return {"entries": self.search(project_ids=projects), "references": self.adoption_inventory(project_ids=projects), "checks": self.integrity_checks()}
