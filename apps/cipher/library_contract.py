"""Scoped authored UTF-8 text, exact revisions and internal reference copies."""
from __future__ import annotations

import base64
from functools import wraps
from hashlib import sha256
import hmac
import json

from .ap_contract import APRefusal
from .core.approvals import material_hash
from .core.ids import canonical_json, parse_iso, utcnow
from .library_sessions import LibraryIdentityRefusal, authority_for
from .library_wire import ACTION_ROUTES, COLLECTIONS, KINDS, MAX_TEXT_BYTES, PROVENANCE

API_PREFIX = "/api/library-practice/v1/"
SOURCE_KIND = "practice-authored-editor-text/1"
EFFECT_KIND = "project-reference-only/1"


def _missing():
    raise APRefusal(404, "not_found", "The record is unavailable in this library session.", "record")


def _read(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.cipher.db._lock:
            try:
                return method(self, *args, **kwargs)
            except APRefusal:
                raise
            except LibraryIdentityRefusal as exc:
                raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
            except Exception:
                raise APRefusal(423, "library_source_unavailable", "The authored library source could not be verified.", "record") from None
    return wrapped


class LibraryContract:
    def __init__(self, cipher, *, secret):
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("Library contract requires an owned private signing key")
        self.cipher, self.secret = cipher, secret

    @property
    def domain(self):
        return self.cipher.plugin("library")

    def _authority(self, person_id):
        self.cipher.db.require_practice_mode()
        authority = authority_for(self.cipher, person_id)
        if not authority.project_ids:
            raise APRefusal(403, "library_duty_required", "This library view requires the person's own current project PM duty.", "duty")
        return authority

    def _scope(self, authority, resource_id, kind):
        if kind == "project":
            record = {"projectId": resource_id} if resource_id in authority.project_ids else None
        elif kind in ("entry", "revision", "plan", "reference"):
            method = {"entry": "entry_scope", "revision": "revision_scope", "plan": "plan_scope", "reference": "adoption_scope"}[kind]
            record = getattr(self.domain, method)(resource_id)
        elif kind == "adoptionApproval":
            # Resolve only the minimal owned scope before a private proof/read.
            record = self.cipher.db.one("SELECT p.project_id AS projectId,a.subject_id AS planId FROM approvals a JOIN library_plans p ON p.id=a.subject_id WHERE a.id=? AND a.operation='library.adopt_reference' AND a.subject_type='library_reference_plan'", (resource_id,))
            if record is None:
                birth = self.cipher.db.one("SELECT payload_json FROM audit_log WHERE action='approval.requested' AND entity_id=? ORDER BY seq LIMIT 1", (resource_id,))
                if birth is not None:
                    payload = json.loads(birth["payload_json"])
                    if payload.get("operation") == "library.adopt_reference":
                        record = self.domain.plan_scope(payload["subject"]["id"])
        else:
            raise APRefusal(422, "unsupported_resource", "Choose a fixed library record.", "record")
        if record is None or record["projectId"] not in authority.project_ids:
            _missing()
        authority.require(record["projectId"], "pm")
        return {"id": resource_id, **record}

    @_read
    def authorize(self, person_id, action, resource_id):
        authority = self._authority(person_id)
        definition = next((route for route in ACTION_ROUTES if route.action == action), None)
        if definition is None:
            raise APRefusal(422, "unsupported_action", "Choose a fixed library action.", "action")
        record = self._scope(authority, resource_id, definition.resource_type)
        return {"personId": authority.person_id, "login": authority.login, "duty": "pm", "operationRole": "pm",
                "authority": authority, "projectId": record["projectId"], "record": record}

    def _project(self, project_id):
        project = self.cipher.project(project_id)
        return {"id": project["id"], "name": project["name"]}

    def _person(self, recorded):
        if recorded is None:
            return None
        login = recorded["login"] if type(recorded) is dict else recorded
        person = self.cipher.plugin("people").person_for(login)
        if person is None or type(recorded) is dict and person["id"] != recorded["personId"]:
            raise ValueError("The original library person is unavailable")
        return {"id": person["id"], "displayName": person["display_name"]}

    def _metadata(self):
        # Separate API-history admission from native original source proof.
        from .library_receipts import library_receipt_inventory_proof
        return library_receipt_inventory_proof(self.cipher.db, self.cipher.audit)

    def _materials(self, project_ids):
        projects = tuple(project_ids)
        approvals = self.domain.approval_inventory(project_ids=projects)
        return {"projectIds": projects, "entries": self.domain.entry_inventory(project_ids=projects),
                "plans": self.domain.plan_inventory(project_ids=projects),
                "approvals": approvals,
                "authorizationClock": [{"id": proof["approval"]["id"],
                    "expired": proof["approval"]["status"] in ("pending", "granted") and parse_iso(proof["approval"]["expires_at"]) <= utcnow()}
                    for proof in approvals],
                "references": self.domain.adoption_inventory(project_ids=projects),
                "receipts": self._metadata()}

    def _token(self, value):
        return "libv1:" + hmac.new(self.secret, canonical_json(value).encode(), sha256).hexdigest()

    def _version(self, authority, identifier, resource_type, materials):
        project_id = self._scope(authority, identifier, resource_type)["projectId"]
        if tuple(materials["projectIds"]) != (project_id,):
            materials = self._materials((project_id,))
        return self._token({"personId": authority.person_id, "scopeHash": authority.scope_hash,
            "resourceId": identifier, "resourceType": resource_type, "records": materials,
            "workspace": self.cipher.db.mode_status(), "authority": self.cipher.db.authority_status()})

    @_read
    def version(self, person_id, resource_id, resource_type):
        authority = self._authority(person_id)
        scope = self._scope(authority, resource_id, resource_type)
        return self._version(authority, resource_id, resource_type, self._materials((scope["projectId"],)))

    def _revision(self, proof, *, entry, current_revision_id):
        body = proof["record"]
        return {"id": body["id"], "entryId": body["entry_id"], "documentRevisionId": body["evidence_revision_id"],
            "number": body["revision"], "text": body["text"], "contentHash": body["contentHash"],
            "byteCount": body["byteCount"], "encoding": body["encoding"], "sourceLocator": body["sourceLocator"],
            "changeReason": body["changeReason"], "previousRevisionId": body["previousRevisionId"],
            "isCurrent": body["id"] == current_revision_id, "currentRevisionId": current_revision_id,
            "author": self._person(body["actor"]), "sourceKind": SOURCE_KIND,
            "kind": entry["kind"], "title": entry["title"]}

    def _entry(self, authority, proof, materials, *, history=False):
        entry = proof["entry"]["record"]
        current = self._revision(proof["currentRevision"], entry=entry, current_revision_id=proof["currentRevisionId"])
        value = {**PROVENANCE, "id": entry["id"], "project": self._project(entry["project_id"]), "kind": entry["kind"],
            "title": entry["title"], "documentId": entry["document_id"], "sourceKind": SOURCE_KIND,
            "currentRevision": current, "revisionCount": len(proof["revisions"]),
            "version": self._version(authority, entry["id"], "entry", materials)}
        if history:
            value["revisions"] = [self._revision(revision, entry=entry, current_revision_id=proof["currentRevisionId"]) for revision in proof["revisions"]]
        return value

    def _approval(self, authority, proof, materials):
        ap, plan = proof["approval"], proof["plan"]["plan"]["record"]
        source = proof["plan"]["source"]
        status = ap["status"]
        authorization = status
        if status in ("pending", "granted"):
            if parse_iso(ap["expires_at"]) <= utcnow():
                authorization = "expired"
            else:
                try:
                    current = self.cipher._manifest("library.adopt_reference", ap["subject_id"], "pm")
                    if (material_hash(current) != ap["material_hash"] or current.get("governance") != ap["manifest"].get("governance")):
                        authorization = "stale"
                except Exception:
                    authorization = "stale"
        return {**PROVENANCE, "id": ap["id"], "project": self._project(plan["project_id"]), "planId": plan["id"],
            "entryId": plan["entry_id"], "revisionId": plan["revision_id"], "title": source["entry"]["record"]["title"],
            "kind": source["entry"]["record"]["kind"], "status": status, "authorizationStatus": authorization,
            "requester": self._person(ap["requested_by"]), "reviewer": self._person(ap["approver"]),
            "appliedBy": self._person(ap["consumed_by"]), "expiresAt": ap["expires_at"],
            "requestedAt": ap["requested_at"], "grantedAt": ap["granted_at"], "appliedAt": ap["consumed_at"],
            "effectKind": EFFECT_KIND, "version": self._version(authority, ap["id"], "adoptionApproval", materials)}

    def _plan(self, authority, proof, materials):
        body, source = proof["plan"]["record"], proof["source"]
        approvals = [p for p in materials["approvals"] if p["approval"]["subject_id"] == body["id"]]
        references = [p for p in materials["references"] if p["record"]["plan_id"] == body["id"]]
        latest = approvals[-1] if approvals else None
        status = "adopted_reference" if references else latest["approval"]["status"] if latest else "prepared"
        effective = ("stale" if source["currentRevisionId"] != body["revision_id"] and not references
                     else self._approval(authority, latest, materials)["authorizationStatus"] if latest and not references else status)
        return {**PROVENANCE, "id": body["id"], "project": self._project(body["project_id"]), "entryId": body["entry_id"],
            "revisionId": body["revision_id"], "currentRevisionId": source["currentRevisionId"],
            "title": source["entry"]["record"]["title"], "kind": source["entry"]["record"]["kind"],
            "targetLocator": body["targetLocator"], "purpose": body["purpose"], "author": self._person(body["actor"]),
            "creationStatus": "prepared", "status": status, "effectiveStatus": effective, "effectKind": EFFECT_KIND,
            "approvalId": latest["approval"]["id"] if latest else None, "referenceId": references[0]["record"]["id"] if references else None,
            "sourceRevision": self._revision(source["revision"], entry=source["entry"]["record"], current_revision_id=source["currentRevisionId"]),
            "version": self._version(authority, body["id"], "plan", materials)}

    def _reference(self, authority, proof, materials):
        body = proof["record"]
        original = self.domain.original_reference_proof(body["id"])
        entry = proof["approval"]["plan"]["source"]["entry"]["record"]
        current_id = proof["approval"]["plan"]["source"]["currentRevisionId"]
        return {**PROVENANCE, "id": body["id"], "project": self._project(body["project_id"]), "entryId": entry["id"],
            "title": entry["title"], "kind": entry["kind"], "planId": body["plan_id"], "approvalId": body["approval_id"],
            "revisionId": body["revision_id"], "currentRevisionId": current_id, "sourceCurrent": current_id == body["revision_id"],
            "text": original["record"]["text"], "contentHash": body["contentHash"], "targetLocator": body["targetLocator"],
            "purpose": body["purpose"], "status": "adopted_reference", "effectKind": EFFECT_KIND,
            "requester": self._person(body["requester"]), "reviewer": self._person(body["reviewer"]),
            "appliedBy": self._person(body["actor"]), "sourceKind": SOURCE_KIND,
            "version": self._version(authority, body["id"], "reference", materials)}

    @_read
    def preparation(self, person_id, project_id):
        authority = self._authority(person_id)
        self._scope(authority, project_id, "project")
        materials = self._materials((project_id,))
        return {**PROVENANCE, "project": self._project(project_id), "kinds": list(KINDS), "maxTextBytes": MAX_TEXT_BYTES,
                "encoding": "UTF-8", "sourceKind": SOURCE_KIND, "effectKind": EFFECT_KIND,
                "version": self._version(authority, project_id, "project", materials)}

    @_read
    def entry(self, person_id, entry_id):
        authority = self._authority(person_id)
        scoped = self._scope(authority, entry_id, "entry")
        materials = self._materials((scoped["projectId"],))
        proof = self.domain.detail(entry_id, project_ids=(scoped["projectId"],))
        return self._entry(authority, proof, materials, history=True)

    @_read
    def revision(self, person_id, revision_id):
        authority = self._authority(person_id)
        scoped = self._scope(authority, revision_id, "revision")
        materials = self._materials((scoped["projectId"],))
        proof = self.domain.revision_proof(revision_id)
        return {**PROVENANCE, "project": self._project(scoped["projectId"]),
            **self._revision(proof["revision"], entry=proof["entry"]["record"], current_revision_id=proof["currentRevisionId"]),
            "version": self._version(authority, revision_id, "revision", materials)}

    @_read
    def plan(self, person_id, plan_id):
        authority = self._authority(person_id)
        scoped = self._scope(authority, plan_id, "plan")
        materials = self._materials((scoped["projectId"],))
        return self._plan(authority, self.domain.plan_proof(plan_id), materials)

    @_read
    def packet(self, person_id, approval_id):
        authority = self._authority(person_id)
        scoped = self._scope(authority, approval_id, "adoptionApproval")
        materials = self._materials((scoped["projectId"],))
        proof = self.domain.approval_proof(approval_id)
        return {**self._approval(authority, proof, materials), "plan": self._plan(authority, proof["plan"], materials)}

    @_read
    def reference(self, person_id, reference_id):
        authority = self._authority(person_id)
        scoped = self._scope(authority, reference_id, "reference")
        materials = self._materials((scoped["projectId"],))
        return self._reference(authority, self.domain.adoption_proof(reference_id), materials)

    def _page(self, authority, collection, items, materials, *, project_id=None, status=None, kind=None, search=None, top=50, cursor=None):
        if type(top) is not int or not 1 <= top <= 50:
            raise APRefusal(422, "invalid_query", "Choose a page size from 1 through 50.", "top")
        if search is not None and (type(search) is not str or len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise APRefusal(422, "invalid_query", "Use a search of at most 200 characters.", "search")
        facets = sorted({item.get("effectiveStatus", item.get("authorizationStatus", item.get("status"))) for item in items} - {None})
        allowed_status = {"reference-plans": {"prepared", "pending", "granted", "consumed", "expired", "invalidated", "stale", "adopted_reference"},
                          "adoption-approvals": {"pending", "granted", "consumed", "expired", "invalidated", "stale"}}.get(collection, set())
        if status is not None and status not in allowed_status or kind is not None and (collection != "library-entries" or kind not in KINDS):
            raise APRefusal(422, "invalid_query", "Choose a listed library filter.", "query")
        if status is not None:
            items = [item for item in items if item.get("effectiveStatus", item.get("authorizationStatus", item.get("status"))) == status]
        if kind is not None:
            items = [item for item in items if item.get("kind") == kind]
        if search:
            def searchable(item):
                text = item.get("currentRevision", {}).get("text", item.get("text", item.get("sourceRevision", {}).get("text", "")))
                return "\n".join(str(item.get(key, "")) for key in ("title", "name", "kind", "targetLocator", "purpose")) + "\n" + text
            items = [item for item in items if search.casefold() in searchable(item).casefold()]
        items = sorted(items, key=lambda item: (item.get("title", item.get("name", "")).casefold(), item["id"]))
        binding = self._token({"personId": authority.person_id, "scopeHash": authority.scope_hash, "collection": collection,
            "projectId": project_id, "status": status, "kind": kind, "search": search, "top": top, "records": materials})
        offset = 0
        if cursor is not None:
            try:
                encoded, signature = cursor.split(".")
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                value = json.loads(raw)
                if (not hmac.compare_digest(signature, hmac.new(self.secret, raw, sha256).hexdigest()) or value["binding"] != binding
                        or type(value["offset"]) is not int or value["offset"] < 0):
                    raise ValueError
                offset = value["offset"]
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise APRefusal(422, "invalid_cursor", "Refresh this library view before paging.", "cursor") from None
        next_cursor = None
        if offset + top < len(items):
            raw = canonical_json({"binding": binding, "offset": offset + top}).encode()
            next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + hmac.new(self.secret, raw, sha256).hexdigest()
        return {**PROVENANCE, "items": items[offset:offset + top], "count": len(items), "nextCursor": next_cursor,
                "facets": {"statuses": facets, "kinds": list(KINDS) if collection == "library-entries" else []}}

    @_read
    def read(self, person_id, collection, *, project_id=None, status=None, kind=None, search=None, top=50, cursor=None):
        authority = self._authority(person_id)
        if collection not in COLLECTIONS:
            raise APRefusal(404, "route_not_found", "This library view is unavailable.")
        if project_id is not None and project_id not in authority.project_ids:
            _missing()
        projects = (project_id,) if project_id is not None else authority.project_ids
        for identifier in projects:
            authority.require(identifier, "pm")
        materials = self._materials(projects)
        if collection == "projects":
            items = [{**PROVENANCE, **self._project(identifier)} for identifier in projects]
        elif collection == "library-entries":
            items = [self._entry(authority, proof, materials) for proof in materials["entries"]]
        elif collection == "reference-plans":
            items = [self._plan(authority, proof, materials) for proof in materials["plans"]]
        elif collection == "adoption-approvals":
            items = [self._approval(authority, proof, materials) for proof in materials["approvals"]]
        else:
            items = [self._reference(authority, proof, materials) for proof in materials["references"]]
        return self._page(authority, collection, items, materials, project_id=project_id, status=status, kind=kind,
                          search=search, top=top, cursor=cursor)
