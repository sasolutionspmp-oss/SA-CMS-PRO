"""Durable R0 local-effect outbox. No financial/external provider is enabled."""

from datetime import timedelta
import json
import uuid

import frappe
from frappe.utils import now_datetime

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_project, require_trusted_write, trusted_write, assert_synthetic_site, require_effects_enabled, execution_quarantined

KINDS = {"project.task.create": "task.create"}


def enqueue_operation(*, actor, company, project, logical_id, kind, payload):
    """Called within an authorized command; persistence and business changes are atomic."""
    require_trusted_write()
    require_effects_enabled()
    if kind not in KINDS:
        raise DomainError("integration_unavailable", "This delivery capability is not configured.", 503)
    require_project(company, project, ability=KINDS[kind], actor=actor)
    old = frappe.db.get_value("Cipher Integration Operation", {"logical_id": logical_id}, ["name", "payload_hash", "kind", "company", "project", "actor_person"], as_dict=True)
    if old:
        if old.payload_hash != digest(payload) or old.kind != kind or old.company != company or old.project != project or old.actor_person != actor.person_id:
            raise DomainError("operation_conflict", "This operation already identifies a different delivery.", 409)
        return old.name
    doc = frappe.get_doc({"doctype": "Cipher Integration Operation", "company": company, "project": project,
        "actor_user": actor.user, "actor_person": actor.person_id, "logical_id": logical_id,
        "effect_operation_id": str(uuid.uuid4()), "kind": kind, "state": "Queued", "payload_json": canonical_json(payload),
        "payload_hash": digest(payload), "fencing_token": 0, "attempt_count": 0})
    doc.insert(ignore_permissions=True)
    # The scheduler is the durable fallback if post-commit queue publication fails.
    frappe.db.after_commit.add(lambda: _schedule(doc.name))
    return doc.name


def _schedule(name):
    if execution_quarantined():
        return
    try:
        if frappe.db.get_value("Cipher Integration Operation", name, "kind") == "company.proposal.fixture.v1":
            from .distribution import require_current_effects_enabled
            require_current_effects_enabled()
            frappe.enqueue("cipher_aec.integrations.outbox.deliver", queue="cipher_distribution", timeout=120,
                operation=name, job_id="cipher-outbox-" + name, deduplicate=True)
            return
        frappe.enqueue("cipher_aec.integrations.outbox.deliver", queue="short", operation=name, job_id="cipher-outbox-" + name, deduplicate=True)
    except Exception:
        frappe.logger("cipher_outbox").warning("Queue unavailable; durable operation awaits scheduler")


def dispatch_pending():
    assert_synthetic_site()
    if execution_quarantined():
        return 0
    names = frappe.get_all("Cipher Integration Operation", or_filters={"state": "Queued", "lease_until": ["<", now_datetime()]}, filters={"state": ["in", ["Queued", "Claimed"]]}, pluck="name", limit_page_length=100)
    # Company transport ambiguity requires observational readback/recovery.
    names += frappe.get_all("Cipher Integration Operation", filters={"kind": "company.proposal.fixture.v1", "state": "Unknown", "lease_until": ["<", now_datetime()]}, pluck="name", limit_page_length=100)
    for name in names:
        _schedule(name)
    return len(names)


def deliver(operation):
    """A local Task effect and final receipt commit together; expired claims recover."""
    if frappe.db.get_value("Cipher Integration Operation", operation, "kind") == "company.proposal.fixture.v1":
        from .distribution_worker import deliver as deliver_company
        return deliver_company(operation)
    require_effects_enabled()
    original_user = frappe.session.user
    try:
        doc = frappe.get_doc("Cipher Integration Operation", operation, for_update=True)
        if doc.state not in {"Queued", "Claimed"}:
            return {"state": doc.state}
        if doc.state == "Claimed" and doc.lease_until and doc.lease_until > now_datetime():
            return {"state": "Claimed"}
        with trusted_write():
            doc.state = "Claimed"
            doc.fencing_token = (doc.fencing_token or 0) + 1
            doc.attempt_count = (doc.attempt_count or 0) + 1
            doc.lease_until = now_datetime() + timedelta(minutes=5)
            doc.save(ignore_permissions=True)
        fence = doc.fencing_token
        frappe.db.commit()
        # Holding the row lock across the local transaction makes the final state
        # atomic with its effect. No HTTP/provider call occurs in this R0 worker.
        doc = frappe.get_doc("Cipher Integration Operation", operation, for_update=True)
        if doc.state != "Claimed" or doc.fencing_token != fence:
            frappe.db.rollback()
            return {"state": "superseded"}
        if doc.kind not in KINDS:
            raise DomainError("integration_unavailable", "This delivery capability is unavailable.", 503)
        frappe.set_user(doc.actor_user)
        actor = current_actor()
        if actor.person_id != doc.actor_person:
            raise DomainError("identity_changed", "The original operation identity is no longer active.", 403)
        require_project(doc.company, doc.project, ability=KINDS[doc.kind], actor=actor)
        payload = json.loads(doc.payload_json)
        if digest(payload) != doc.payload_hash:
            raise DomainError("operation_integrity", "The operation source no longer agrees with its receipt.", 409)
        from cipher_aec.projects.service import create_task
        result = create_task(company=doc.company, project=doc.project, operation_id=doc.effect_operation_id,
            expected_version=payload["expected_version"], subject=payload["subject"], description=payload.get("description", ""))
        with trusted_write():
            doc.state, doc.result_json, doc.lease_until = "Succeeded", canonical_json(result), None
            doc.save(ignore_permissions=True)
            _attempt(doc, fence, "Succeeded", {"effect_operation_id": doc.effect_operation_id})
        frappe.db.commit()
        return {"state": "Succeeded"}
    except Exception as error:
        frappe.db.rollback()
        # Local effects roll back with failure. Preserve safe classification only.
        code = error.code if isinstance(error, DomainError) else "local_delivery_failed"
        doc = frappe.get_doc("Cipher Integration Operation", operation, for_update=True)
        if doc.state == "Claimed" and doc.fencing_token == locals().get("fence"):
            with trusted_write():
                doc.state, doc.last_error_code, doc.lease_until = "Failed", code, None
                doc.save(ignore_permissions=True)
                _attempt(doc, doc.fencing_token, "Failed", {"code": code})
            frappe.db.commit()
        return {"state": doc.state, "code": code}
    finally:
        frappe.set_user(original_user)


def _attempt(doc, fence, outcome, details):
    frappe.get_doc({"doctype": "Cipher Delivery Attempt", "operation": doc.name, "fencing_token": fence,
        "outcome": outcome, "company": doc.company, "project": doc.project, "safe_details": canonical_json(details)}).insert(ignore_permissions=True)
