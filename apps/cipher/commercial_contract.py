"""Scratch scoped presenter for a genuine commercial-created commitment draft.

Read-only: calls the emerging commercial domain's full original correspondence
proof after scoped minimal SQL references. No AP identity/workspace inheritance.
"""
from __future__ import annotations

import base64
import json
from functools import wraps
from hashlib import sha256
import hmac
from urllib.parse import quote

from apps.cipher.ap_contract import APRefusal, _money
from apps.cipher.core.ids import canonical_json, hash_json, parse_iso, utcnow
from .commercial_sessions import authority_for
from .commercial_wire import ACTION_ROUTES, COLLECTIONS, PROVENANCE

API_PREFIX = "/api/commercial-practice/v1/"


def _unavailable():
    raise APRefusal(404, "not_found", "The record is unavailable in this commercial session.", "record")


def _read(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.cipher.db._lock:
            try:
                return method(self, *args, **kwargs)
            except APRefusal:
                raise
            except Exception:
                raise APRefusal(423, "commercial_source_unavailable", "The current commercial source could not be verified.", "record") from None
    return wrapped


class CommercialContract:
    def __init__(self, cipher, *, secret):
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("Commercial contract requires an owned private signing key")
        self.cipher, self.secret = cipher, secret
        self._versions = {}

    def _authority(self, person_id):
        self.cipher.db.require_practice_mode()
        return authority_for(self.cipher, person_id)

    def _metadata(self):
        from .commercial_receipts import CommercialReceipts
        try:
            CommercialReceipts(self.cipher.db, self.cipher.audit).verify_integrity()
        except Exception:
            raise APRefusal(423, "commercial_source_unavailable", "Commercial action history could not be verified.", "record") from None

    def authorize(self, person_id, action, resource_id):
        with self.cipher.db._lock:
            authority = self._authority(person_id)
            definition = next((item for item in ACTION_ROUTES if item.action == action), None)
            if definition is None:
                raise APRefusal(422, "unsupported_action", "Choose a supported commercial action.", "action")
            queries = {
                "project": "SELECT id,id AS project_id FROM projects WHERE id=?",
                "estimate": "SELECT id,project_id FROM estimates WHERE id=?",
                "approval": "SELECT a.id,e.project_id FROM approvals a JOIN estimates e ON e.id=a.subject_id WHERE a.id=? AND a.operation='estimate.approve' AND a.subject_type='estimate'",
                "handoff": "SELECT id,project_id FROM commercial_handoffs WHERE id=?",
            }
            record = self.cipher.db.one(queries[definition.resource_type], (resource_id,))
            if record is None or record["project_id"] not in authority.project_ids:
                _unavailable()
            authority.require(record["project_id"], definition.duty)
            self._metadata()
            return {"personId": authority.person_id, "login": authority.login, "duty": definition.duty,
                    "authority": authority, "projectId": record["project_id"], "record": record}

    def version(self, person_id, resource_id, resource_type):
        from .commercial_versions import version_material
        with self.cipher.db._lock:
            authority = self._authority(person_id)
            try:
                if resource_type not in ("project", "estimate", "approval", "handoff"):
                    raise APRefusal(422, "unsupported_resource", "Choose a supported commercial record.", "resource")
                self._scope(authority, resource_id, resource_type)
                stamp = (self.cipher.db.conn.total_changes, self.cipher.db.scalar("PRAGMA data_version"), self.cipher.db.scalar("PRAGMA schema_version"))
                key = (stamp, authority.person_id, authority.scope_hash, resource_id, resource_type)
                if key not in self._versions:
                    value = version_material(self.cipher, authority, resource_id, resource_type)
                    if len(self._versions) > 256:
                        self._versions.clear()
                    self._versions[key] = self._token(value)
                return self._versions[key]
            except APRefusal:
                raise
            except Exception:
                raise APRefusal(423, "commercial_source_unavailable",
                                "This record's current commercial source could not be verified.", "record") from None

    def _version(self, authority, resource_id, proof, current_source):
        value = {"personId": authority.person_id, "scopeHash": authority.scope_hash,
                 "type": "commercial-commitment", "id": resource_id,
                 "proof": proof, "currentSource": current_source}
        return "cmv1:" + hmac.new(self.secret, canonical_json(value).encode(), sha256).hexdigest()

    def _token(self, value):
        return "cmv1:" + hmac.new(self.secret, canonical_json(value).encode(), sha256).hexdigest()

    def _scope(self, authority, identifier, kind):
        queries = {
            "project": "SELECT id AS project_id FROM projects WHERE id=?",
            "estimate": "SELECT project_id FROM estimates WHERE id=?",
            "approval": "SELECT e.project_id FROM approvals a JOIN estimates e ON e.id=a.subject_id WHERE a.id=? AND a.operation='estimate.approve' AND a.subject_type='estimate'",
            "handoff": "SELECT project_id FROM commercial_handoffs WHERE id=?",
        }
        row = self.cipher.db.one(queries[kind], (identifier,))
        if row is None or row["project_id"] not in authority.project_ids:
            _unavailable()
        self._metadata()
        return row["project_id"]

    def _person(self, login):
        if login is None:
            return None
        person = self.cipher.plugin("people").person_for(login)
        if person is None:
            raise ValueError("Original person is unavailable")
        return {"id": person["id"], "displayName": person["display_name"]}

    def _project(self, identifier):
        value = self.cipher.plugin("commercial")._project(identifier)
        return {"id": value["id"], "name": value["name"]}

    def _actions(self, authority, project_id, candidates, identifier):
        from .commercial_preflight import CommercialPreflight
        preflight = CommercialPreflight(self.cipher, self, secret=self.secret)
        result = []
        for action in candidates:
            duty = "pm" if action == "estimate.createCommitment" else "estimator"
            if not authority.allows(project_id, duty):
                continue
            review = preflight.review(authority.person_id, action, identifier, {})
            blocked = next((item for item in review["checks"] if item["status"] == "blocked"), None)
            result.append({"action": action, "allowed": review["allowed"],
                           "reason": None if blocked is None else blocked["message"],
                           "target": None if blocked is None else blocked["target"]})
        return result

    def _line(self, fact):
        line = fact["engine_line"]
        return {"id": line["id"], "lineNo": line["line_no"], "description": line["description"],
                "quantity": line["quantity"], "unit": line["unit"], "unitPriceCents": _money(line["unit_price"]),
                "amountCents": _money(line["amount"]), "sourceLocator": fact["source_locator"],
                "costCode": fact["cost_code"], "stableLineId": fact["stable_line_id"],
                "previousLineId": fact["previous_line_id"], "measurementMethod": fact["method"],
                "verifiedGeometry": fact["verified_geometry"]}

    def _drawing(self, drawing):
        revision = self.cipher.estimates.source_revision_proof(drawing["revisionId"])["revision"]
        return {"documentId": drawing["documentId"], "documentRevisionId": drawing["revisionId"],
                "title": drawing["title"], "revision": drawing["revision"], "current": revision["is_current"]}

    def _approval_effective(self, approval):
        if approval["status"] not in ("pending", "granted"):
            return approval["status"]
        if parse_iso(approval["expires_at"]) <= utcnow():
            return "expired"
        from .core.approvals import material_hash
        try:
            manifest = self.cipher._manifest("estimate.approve", approval["subject_id"], "estimator")
            if (material_hash(manifest) != approval["material_hash"]
                    or manifest.get("governance") != approval["manifest"].get("governance")):
                return "stale"
        except (RuntimeError, ValueError):
            return "stale"
        return approval["status"]

    def _approval_row(self, authority, approval):
        source = self.cipher.plugin("commercial").source(approval["subject_id"])
        original = self.cipher.estimates.estimate_approval_proof(approval["id"])
        requested = self.cipher.db.one("SELECT ts FROM audit_log WHERE seq=?", (original["auditSeq"],))
        grants = self.cipher.db.query("SELECT ts FROM audit_log WHERE entity_type='approval' AND entity_id=? AND action='approval.granted'", (approval["id"],))
        return {"id": approval["id"], "version": self.version(authority.person_id, approval["id"], "approval"),
                "project": self._project(source["projectId"]), "estimateId": source["estimateId"],
                "estimateRevision": source["baseline"]["revision"], "status": approval["status"],
                "effectiveStatus": self._approval_effective(approval), "totalCents": _money(source["baseline"]["total"]),
                "requestedBy": self._person(approval["requested_by"]), "approvedBy": self._person(approval["approver"]),
                "requestedAt": requested["ts"], "grantedAt": grants[0]["ts"] if grants else None,
                "expiresAt": approval["expires_at"], "availableActions": self._actions(authority, source["projectId"],
                    ("estimate.accept",) if approval["status"] == "pending" else ("estimate.apply",) if approval["status"] == "granted" else (), approval["id"])}

    @_read
    def estimate(self, person_id, estimate_id):
        authority = self._authority(person_id)
        project_id = self._scope(authority, estimate_id, "estimate")
        source = self.cipher.plugin("commercial").source(estimate_id)
        value = self.cipher.estimates.get(estimate_id)
        approvals = self.cipher.estimates.estimate_approval_inventory((project_id,), (estimate_id,))
        latest = next((item for item in approvals if item["id"] == value["approval_id"]), approvals[-1] if approvals else None)
        acceptance = None
        if latest is not None:
            presented = self._approval_row(authority, latest)
            consumed = self.cipher.db.query("SELECT actor,ts FROM audit_log WHERE entity_type='approval' AND entity_id=? AND action='approval.consumed'", (latest["id"],))
            acceptance = {"approvalId": latest["id"], "requestedBy": presented["requestedBy"],
                "acceptedBy": presented["approvedBy"], "appliedBy": self._person(latest["consumed_by"]),
                "requestedAt": presented["requestedAt"], "acceptedAt": presented["grantedAt"],
                "appliedAt": consumed[0]["ts"] if consumed else None, "expiresAt": latest["expires_at"],
                "status": latest["status"], "effectiveStatus": presented["effectiveStatus"]}
        effective = "superseded" if value["status"] == "superseded" else "stale" if value["stale"] else "accepted" if value["status"] == "approved" else "under_review" if latest and latest["status"] in ("pending", "granted") else "draft"
        candidates = []
        if value["status"] != "superseded" and authority.allows(project_id, "estimator"):
            candidates.append({"action": "estimate.revise", "allowed": True, "reason": None, "target": None})
        candidates += self._actions(authority, project_id, ("estimate.request",) if value["status"] == "draft" else ("estimate.prepareHandoff",) if value["status"] == "approved" else (), estimate_id)
        def related(identifier):
            if identifier is None:
                return None
            self._scope(authority, identifier, "estimate")
            related_source = self.cipher.plugin("commercial").source(identifier)
            return {"id": identifier, "revision": related_source["baseline"]["revision"]}
        return {**PROVENANCE, "id": estimate_id, "version": self.version(person_id, estimate_id, "estimate"),
                "project": self._project(project_id), "revision": value["revision"], "status": value["status"],
                "effectiveStatus": effective, "source": self._drawing(source["drawing"]),
                "subtotalCents": _money(value["subtotal"]), "contingencyCents": _money(value["contingency"]),
                "totalCents": _money(value["total"]), "lines": [self._line(line) for line in source["lines"]],
                "priceBookRef": value["price_book_ref"], "inclusions": value["inclusions"], "exclusions": value["exclusions"],
                "contingencyRate": value["contingency_rate"], "measurementBasis": value["measurement_basis"],
                "predecessor": related(value["supersedes"]), "successor": related(value["superseded_by"]),
                "acceptance": acceptance, "availableActions": candidates,
                "markers": [{"code": "source_stale", "message": "This revision remains in history. A new handoff requires a current accepted source."}] if value["stale"] else []}

    @_read
    def comparison(self, person_id, estimate_id):
        authority = self._authority(person_id)
        self._scope(authority, estimate_id, "estimate")
        domain = self.cipher.plugin("commercial")
        value = domain.comparison(estimate_id)
        current = domain.source(estimate_id)
        previous = domain.source(value["predecessorId"]) if value["predecessorId"] else None
        field_names = {"unit_price": "unitPriceCents", "amount": "amountCents", "source_locator": "sourceLocator", "cost_code": "costCode"}
        differences = [{"stableLineId": item["stableLineId"], "kind": item["kind"],
                        "before": self._line(item["before"]) if item["before"] else None,
                        "after": self._line(item["after"]) if item["after"] else None,
                        "changedFields": [field_names.get(name, name) for name in item["changedFields"]]} for item in value["lines"]]
        before_scope, after_scope = value["beforeScope"] or {}, value["afterScope"]
        def changed(name):
            old, new = before_scope.get(name, []), after_scope[name]
            return [item for item in new if item not in old], [item for item in old if item not in new]
        added_i, removed_i = changed("inclusions")
        added_e, removed_e = changed("exclusions")
        totals = {"afterCents": value["afterCents"]}
        totals.update({key: value[key] for key in ("beforeCents", "deltaCents") if value[key] is not None})
        return {**PROVENANCE, "version": self.version(person_id, estimate_id, "estimate"), "estimateId": estimate_id,
                "predecessorId": value["predecessorId"], "lines": differences, "totals": totals,
                "scope": {"addedInclusions": added_i, "removedInclusions": removed_i, "addedExclusions": added_e, "removedExclusions": removed_e},
                "sourceChanged": previous is not None and previous["drawing"]["revisionId"] != current["drawing"]["revisionId"],
                "priceBookChanged": previous is not None and before_scope.get("price_book_ref") != after_scope["price_book_ref"]}

    def _drawing_rows(self, authority, project_ids):
        from .commercial_versions import drawing_inventory
        result = []
        inventory = drawing_inventory(self.cipher, project_ids)
        for entry in inventory:
            document = entry["document"]
            project = self._project(document["project_id"])
            for proof in entry["revisions"]:
                revision = proof["revision"]
                result.append({"id": revision["id"], "version": self._token({"person": authority.person_id,
                    "scope": authority.scope_hash, "inventory": inventory, "revision": revision["id"]}),
                    "projectId": project["id"], "projectName": project["name"], "documentId": document["id"],
                    "documentRevisionId": revision["id"], "title": document["title"], "revision": revision["revision"],
                    "current": revision["is_current"]})
        return result

    @_read
    def preparation(self, person_id, project_id):
        authority = self._authority(person_id)
        self._scope(authority, project_id, "project")
        drawings = [row for row in self._drawing_rows(authority, (project_id,)) if row["current"]]
        actions = []
        if authority.allows(project_id, "estimator"):
            actions = [{"action": "estimate.create", "allowed": bool(drawings), "reason": None if drawings else "A current owned drawing is required.", "target": None if drawings else "source"}]
        return {**PROVENANCE, "version": self.version(person_id, project_id, "project"), "project": self._project(project_id),
                "drawingRevisions": drawings, "units": self.cipher.estimates.units(), "inputMode": "manual_entry",
                "verifiedGeometry": False, "availableActions": actions}

    @_read
    def packet(self, person_id, approval_id):
        authority = self._authority(person_id)
        project_id = self._scope(authority, approval_id, "approval")
        self.cipher.estimates.estimate_approval_inventory((project_id,))
        self.cipher.estimates.estimate_approval_proof(approval_id)
        approval = self.cipher.approvals.get(approval_id)
        row = self._approval_row(authority, approval)
        from .commercial_preflight import CommercialPreflight
        action = "estimate.accept" if approval["status"] == "pending" else "estimate.apply"
        checks = []
        if authority.allows(project_id, "estimator") and approval["status"] in ("pending", "granted"):
            checks = CommercialPreflight(self.cipher, self, secret=self.secret).review(person_id, action, approval_id, {})["checks"]
        return {**PROVENANCE, "version": row["version"], "approval": row,
                "estimate": self.estimate(person_id, approval["subject_id"]), "comparison": self.comparison(person_id, approval["subject_id"]),
                "summary": "Review the exact priced quantities, drawing source and declared scope for this estimate revision.",
                "consequence": "Authorizing acceptance leaves the estimate draft until an estimator explicitly accepts it." if approval["status"] == "pending" else "Acceptance consumes this authorization and records the exact estimate baseline.",
                "checks": checks, "availableActions": row["availableActions"]}

    def _handoff_lines(self, source):
        return [{"estimateLineId": fact["estimate_line_id"], "stableLineId": fact["stable_line_id"],
                 "description": fact["engine_line"]["description"], "quantity": fact["engine_line"]["quantity"],
                 "unit": fact["engine_line"]["unit"], "unitPriceCents": _money(fact["engine_line"]["unit_price"]),
                 "amountCents": _money(fact["engine_line"]["amount"]), "costCode": fact["cost_code"], "sourceLocator": fact["source_locator"],
                 "measurementBasis": fact["measurement_basis"], "measurementMethod": fact["method"], "verifiedGeometry": fact["verified_geometry"],
                 "sovLineId": None} for fact in source["lines"]]

    @_read
    def handoff_preparation(self, person_id, estimate_id):
        authority = self._authority(person_id)
        project_id = self._scope(authority, estimate_id, "estimate")
        domain = self.cipher.plugin("commercial")
        source = domain.source(estimate_id)
        packages = [row for row in domain._inventory("packages") if row["project_id"] == project_id]
        if not packages:
            raise APRefusal(423, "handoff_package_unavailable", "An audited synthetic subcontract package is required.", "package")
        package = domain.package(packages[-1]["id"])
        candidates = self._actions(authority, project_id, ("estimate.prepareHandoff",), estimate_id)
        from .commercial_preflight import CommercialPreflight
        checks = CommercialPreflight(self.cipher, self, secret=self.secret).review(person_id, "estimate.prepareHandoff", estimate_id, {})["checks"] if authority.allows(project_id, "estimator") else []
        handoffs = [row for row in domain.handoff_inventory(project_ids=(project_id,)) if row["source"]["estimateId"] == estimate_id and row["package"]["id"] == package["id"]]
        return {**PROVENANCE, "version": self.version(person_id, estimate_id, "estimate"), "project": self._project(project_id),
                "estimate": self.estimate(person_id, estimate_id), "package": {"id": package["id"], "title": package["title"],
                    "supplier": {"id": package["supplier_id"], "name": package["supplier"]["name"]}, "retainageRate": package["retainage_rate"]},
                "lines": self._handoff_lines(source), "subtotalCents": _money(source["baseline"]["subtotal"]),
                "contingencyCents": _money(source["baseline"]["contingency"]), "totalCents": _money(source["baseline"]["total"]),
                "existingHandoffId": handoffs[0]["handoffId"] if handoffs else None,
                "checks": checks, "availableActions": candidates,
                "consequence": "Prepare the accepted source for one subcontract draft. Contract execution remains separate."}

    @_read
    def handoff(self, person_id, handoff_id):
        authority = self._authority(person_id)
        project_id = self._scope(authority, handoff_id, "handoff")
        domain = self.cipher.plugin("commercial")
        value = domain.handoff(handoff_id)
        source, package = value["source"], value["package"]
        estimate = self.cipher.estimates.get(source["estimateId"])
        packages = [row for row in domain._inventory("packages") if row["project_id"] == project_id]
        lines = self._handoff_lines(source)
        if value["commitmentId"]:
            proof = domain.commitment_proof(value["commitmentId"])
            mapping = {item["source_line_id"]: item["sov_line_id"] for item in proof["lineage"]}
            for line in lines:
                line["sovLineId"] = mapping[line["estimateLineId"]]
        return {**PROVENANCE, "id": handoff_id, "version": self.version(person_id, handoff_id, "handoff"),
                "project": self._project(project_id), "estimateId": source["estimateId"], "estimateRevision": source["baseline"]["revision"],
                "acceptanceApprovalId": source["baseline"]["acceptance"]["approvalId"], "source": self._drawing(source["drawing"]),
                "status": value["status"], "effectiveStatus": "stale" if estimate["stale"] or packages[-1]["id"] != package["id"] else value["status"],
                "supplier": {"id": package["supplier_id"], "name": package["supplier"]["name"]}, "commitmentTitle": package["title"],
                "retainageRate": package["retainage_rate"], "subtotalCents": _money(source["baseline"]["subtotal"]), "contingencyCents": 0,
                "totalCents": _money(value["total"]), "lines": lines, "commitmentId": value["commitmentId"],
                "availableActions": self._actions(authority, project_id, ("estimate.createCommitment",), handoff_id),
                "consequence": "This handoff creates a subcontract draft. Contract review and execution remain separate."}

    @_read
    def read(self, person_id, collection, *, project_id=None, status=None, search=None, top=50, cursor=None):
        if collection not in COLLECTIONS:
            raise APRefusal(404, "route_not_found", "This commercial collection is unavailable.")
        if type(top) is not int or not 1 <= top <= 50 or (search is not None and (type(search) is not str or len(search) > 200)):
            raise APRefusal(422, "invalid_query", "Use bounded commercial filters.", "query")
        authority = self._authority(person_id)
        if project_id is not None:
            self._scope(authority, project_id, "project")
        elif not authority.project_ids:
            raise APRefusal(403, "commercial_duty_required", "Your current project duties do not permit these commercial records.", "duty")
        scopes = (project_id,) if project_id is not None else authority.project_ids
        self._metadata()
        domain = self.cipher.plugin("commercial")
        sources = domain.source_inventory(project_ids=scopes)
        if collection == "projects":
            self._drawing_rows(authority, scopes)
            handoffs = domain.handoff_inventory(project_ids=scopes)
            items = [{**self._project(project), "entity": domain._project(project)["entity"], "currency": "USD",
                      "estimateCount": sum(source["projectId"] == project for source in sources),
                      "handoffCount": sum(item["projectId"] == project for item in handoffs)} for project in scopes]
        elif collection == "drawing-revisions":
            items = self._drawing_rows(authority, scopes)
        elif collection == "estimates":
            fields = ("id", "version", "project", "revision", "status", "effectiveStatus", "source", "subtotalCents", "contingencyCents", "totalCents")
            items = [{key: value[key] for key in fields} for value in (self.estimate(person_id, source["estimateId"]) for source in sources)]
        elif collection == "estimate-approvals":
            known = {source["estimateId"] for source in sources}
            items = [self._approval_row(authority, approval) for approval in self.cipher.estimates.estimate_approval_inventory(scopes) if approval["subject_id"] in known]
        else:
            items = [self.handoff(person_id, value["handoffId"]) for value in domain.handoff_inventory(project_ids=scopes)]
        allowed_statuses = {"projects": (), "drawing-revisions": ("current", "superseded"), "estimates": ("draft", "approved", "superseded"),
                            "estimate-approvals": ("pending", "granted", "consumed", "expired", "invalidated"), "estimate-handoffs": ("prepared", "draft_created")}
        if status is not None and status not in allowed_statuses[collection]:
            raise APRefusal(422, "invalid_query", "Choose a listed commercial status.", "status")
        def item_status(item):
            return ("current" if item["current"] else "superseded") if collection == "drawing-revisions" else item.get("status")
        if search:
            term = search.strip().casefold()
            items = [item for item in items if term in canonical_json(item).casefold()]
        facets = [{"value": value, "count": sum(item_status(item) == value for item in items)} for value in sorted({item_status(item) for item in items if item_status(item) is not None})]
        if status is not None:
            items = [item for item in items if item_status(item) == status]
        items.sort(key=lambda item: item["id"])
        binding = hash_json({"person": authority.person_id, "scope": authority.scope_hash, "collection": collection,
                             "project": project_id, "status": status, "search": search, "top": top, "items": items})
        offset = 0
        if cursor is not None:
            try:
                encoded, signature = cursor.split(".")
                payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                expected = hmac.new(self.secret, payload, sha256).hexdigest()
                value = json.loads(payload)
                if not hmac.compare_digest(signature, expected) or value["binding"] != binding or type(value["offset"]) is not int or not 0 <= value["offset"] <= len(items):
                    raise ValueError
                offset = value["offset"]
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise APRefusal(422, "invalid_cursor", "Refresh this commercial view before paging.", "cursor") from None
        totals = {field: sum(item[field] for item in items) for field in ("subtotalCents", "contingencyCents", "totalCents") if any(field in item for item in items)}
        if any(abs(value) > 9_007_199_254_740_991 for value in totals.values()):
            raise APRefusal(422, "invalid_total", "The selected exact total exceeds the display range.", "totals")
        next_cursor = None
        if offset + top < len(items):
            payload = canonical_json({"binding": binding, "offset": offset + top}).encode()
            encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
            next_cursor = encoded + "." + hmac.new(self.secret, payload, sha256).hexdigest()
        return {**PROVENANCE, "items": items[offset:offset + top], "count": len(items), "nextCursor": next_cursor,
                "facets": {"statuses": facets}, "totals": totals}

    def commitment(self, person_id, commitment_id):
        with self.cipher.db._lock:
            authority = self._authority(person_id)
            # Never load a supplier/source/handoff or unscoped SOV before this.
            row = self.cipher.db.one("SELECT id,project_id FROM commitments WHERE id=?", (commitment_id,))
            if row is None or row["project_id"] not in authority.project_ids:
                _unavailable()
            correspondence = self.cipher.db.one(
                "SELECT id,commitment_id,project_id,handoff_id FROM commercial_commitment_sources WHERE commitment_id=?",
                (commitment_id,))
            if correspondence is None or correspondence["project_id"] != row["project_id"]:
                _unavailable()
            self._metadata()
            try:
                domain = self.cipher.plugin("commercial")
                proof = domain.commitment_proof(commitment_id, current=False)
                value = proof["commitment"]
                handoff = proof["handoff"]
                source = handoff["source"]
                baseline = source["baseline"]
                acceptance = baseline["acceptance"]
                if (proof["commitmentId"] != commitment_id or proof["projectId"] != row["project_id"]
                        or handoff["projectId"] != row["project_id"] or source["projectId"] != row["project_id"]
                        or handoff["handoffId"] != correspondence["handoff_id"]
                        or value["project_id"] != row["project_id"] or value["status"] not in ("draft", "executed", "closed")
                        or proof["currentCorrespondence"] is not True or acceptance is None):
                    raise ValueError("The scoped original draft correspondence is unavailable")
                estimate = self.cipher.estimates.get(source["estimateId"])
                project = self.cipher.project(row["project_id"])
                drawing = source["drawing"]
                revision = self.cipher.evidence.revision(drawing["revisionId"])
                source_status = "stale" if estimate["stale"] or estimate["status"] != "approved" else "current"
                sov = {line["id"]: line for line in value["sov"]}
                lines = []
                for link in proof["lineage"]:
                    fact, sov_line = link["source"], sov[link["sov_line_id"]]
                    lines.append({"estimateLineId": fact["source_line_id"], "stableLineId": fact["stable_line_id"],
                                  "sovLineId": sov_line["id"], "sovLineNo": sov_line["line_no"],
                                  "description": fact["description"], "quantity": fact["quantity"],
                                  "unit": fact["unit"], "unitPriceCents": _money(fact["unit_price"]),
                                  "amountCents": _money(fact["amount"]), "costCode": fact["cost_code"],
                                  "sourceLocator": fact["source_locator"], "measurementBasis": fact["measurement_basis"],
                                  "measurementMethod": fact["method"], "verifiedGeometry": fact["verified_geometry"]})
                if (len(lines) != len(sov) or any(line["measurementMethod"] != "manual_entry"
                                                or line["verifiedGeometry"] is not False for line in lines)):
                    raise ValueError("The complete original manual line correspondence is unavailable")
                version = self._version(authority, commitment_id, proof,
                                        {"stale": estimate["stale"], "status": estimate["status"],
                                         "supersededBy": estimate["superseded_by"], "drawingCurrent": revision["is_current"]})
                return {**PROVENANCE, "id": commitment_id, "version": version,
                        "project": {"id": project["id"], "name": project["name"]},
                        "title": value["title"], "status": value["status"], "creationStatus": "draft",
                        "effectiveSourceStatus": source_status,
                        "supplier": {"id": value["supplier_id"], "name": value["supplier"]["name"]},
                        "retainageRate": value["retainage_rate"], "originalAmountCents": _money(value["original_amount"]),
                        "handoffId": handoff["handoffId"], "estimate": {"id": source["estimateId"],
                            "revision": baseline["revision"], "acceptanceApprovalId": acceptance["approvalId"]},
                        "source": {"documentId": drawing["documentId"], "documentRevisionId": drawing["revisionId"],
                                   "title": drawing["title"], "revision": drawing["revision"], "current": revision["is_current"]},
                        "lines": lines, "executionAvailableHere": False, "availableActions": [],
                        "consequence": "This handoff created a subcontract draft. Contract review and execution use separate approvals.",
                        "relatedRecords": [
                            {"type": "estimate", "id": source["estimateId"], "title": "Accepted estimate",
                             "apiRoute": API_PREFIX + "estimates/" + quote(source["estimateId"], safe="")},
                            {"type": "handoff", "id": handoff["handoffId"], "title": "Estimate handoff",
                             "apiRoute": API_PREFIX + "estimate-handoffs/" + quote(handoff["handoffId"], safe="")},
                        ]}
            except APRefusal:
                raise
            except Exception:
                raise APRefusal(423, "commercial_source_unavailable",
                                "This draft's original source correspondence could not be verified.", "record") from None


# Temporary compatibility for the scratch presenter checks; main class naming is
# the frozen CommercialContract constructor expected by preflight and runner.
CommercialContractDraft = CommercialContract
