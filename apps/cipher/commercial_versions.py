"""Scratch pure private resource versions, shared with scoped read inventories.

Everything returned here is private signing material, never a product DTO.
Scope precedes target facts and scoped inventories; IDs/messages stay opaque.
"""
from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.approvals import material_part
from apps.cipher.core.ids import loads
from .commercial_wire import PROVENANCE


def _missing():
    raise APRefusal(404, "not_found", "The record is unavailable in this commercial session.", "record")


def drawing_inventory(cipher, project_ids):
    """Prove registrations too, so a deleted unused source cannot disappear."""
    scopes = frozenset(project_ids)
    if not scopes:
        return []
    marks = ",".join("?" for _ in scopes)
    rows = {row["id"]: row for row in cipher.db.query(
        f"SELECT * FROM documents WHERE kind='drawing' AND project_id IN ({marks}) ORDER BY id", tuple(scopes))}
    births = []
    for event in cipher.db.query("SELECT * FROM audit_log WHERE action='document.registered' AND entity_type='document' ORDER BY seq"):
        payload = loads(event["payload_json"])
        if type(payload) is dict and payload.get("project_id") in scopes and payload.get("kind") == "drawing":
            births.append((event, payload))
    identifiers = [event["entity_id"] for event, _ in births]
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != set(rows):
        raise APRefusal(423, "commercial_source_unavailable", "The drawing source inventory cannot be verified.", "source")
    out = []
    for event, payload in births:
        row = rows[event["entity_id"]]
        if payload != {key: row[key] for key in ("project_id", "kind", "title")}:
            raise APRefusal(423, "commercial_source_unavailable", "The drawing source registration cannot be verified.", "source")
        revisions = cipher.db.query("SELECT id FROM document_revisions WHERE document_id=? ORDER BY revision", (row["id"],))
        audited = cipher.db.query("SELECT payload_json FROM audit_log WHERE action='document.revised' AND entity_type='document' AND entity_id=? ORDER BY seq", (row["id"],))
        if [revision["id"] for revision in revisions] != [loads(item["payload_json"]).get("revision_id") for item in audited]:
            raise APRefusal(423, "commercial_source_unavailable", "The drawing revision inventory cannot be verified.", "source")
        proofs = [cipher.estimates.source_revision_proof(revision["id"]) for revision in revisions]
        out.append({"document": row, "birth": {"seq": event["seq"], "hash": event["entry_hash"]}, "revisions": proofs})
    return out


def version_material(cipher, authority, resource_id, resource_type):
    with cipher.db._lock:
        lookups = {
            "project": "SELECT id AS project_id FROM projects WHERE id=?",
            "estimate": "SELECT project_id FROM estimates WHERE id=?",
            "approval": "SELECT e.project_id FROM approvals a JOIN estimates e ON e.id=a.subject_id WHERE a.id=? AND a.operation='estimate.approve' AND a.subject_type='estimate'",
            "handoff": "SELECT project_id FROM commercial_handoffs WHERE id=?",
        }
        query = lookups.get(resource_type)
        if query is None:
            raise APRefusal(422, "unsupported_resource", "Choose a supported commercial record.", "resource")
        scope = cipher.db.one(query, (resource_id,))
        if scope is None or scope["project_id"] not in authority.project_ids:
            _missing()
        project_id = scope["project_id"]
        domain = cipher.plugin("commercial")
        project = domain._project(project_id)
        drawings = drawing_inventory(cipher, (project_id,))
        sources = domain.source_inventory(project_ids=(project_id,))
        approvals = cipher.estimates.estimate_approval_inventory((project_id,))
        packages = [domain.package(row["id"]) for row in domain._inventory("packages") if row["project_id"] == project_id]
        handoffs = domain.handoff_inventory(project_ids=(project_id,))
        commitments = [domain.commitment_proof(row["commitment_id"]) for row in domain._inventory("commitment_sources") if row["project_id"] == project_id]
        if resource_type == "project":
            target = project
        elif resource_type == "estimate":
            target = domain.source(resource_id)
        elif resource_type == "handoff":
            target = domain.handoff(resource_id)
        else:
            cipher.estimates.estimate_approval_proof(resource_id)
            target = cipher.approvals.get(resource_id)
        current = []
        for source in sources:
            try:
                manifest = cipher._manifest("estimate.approve", source["estimateId"], "estimator")
                facts = {"material": material_part(manifest), "governance": manifest.get("governance")}
            except (RuntimeError, ValueError, TypeError, KeyError):
                facts = {"available": False}
            current.append({"estimateId": source["estimateId"], "facts": facts})
        return {"provenance": PROVENANCE, "workspace": cipher.db.mode_status(), "authority": cipher.db.authority_status(),
                "personId": authority.person_id, "scopeHash": authority.scope_hash, "policy": cipher.plugin("people").current_policy(),
                "resourceType": resource_type, "resourceId": resource_id, "target": target, "project": project,
                "drawings": drawings, "sources": sources, "approvals": approvals, "packages": packages,
                "handoffs": handoffs, "commitments": commitments, "currentMaterial": current}
