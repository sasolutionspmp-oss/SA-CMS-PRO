import json

import frappe

from cipher_aec.api.contracts import canonical_json, digest, utc_timestamp
from .context import require_trusted_write


def append_event(*, actor, company, project, event, subject_type, subject_id, operation_id, details):
    """Caller holds the project lock; serializes the per-project append-only history."""
    require_trusted_write()
    previous = frappe.db.get_value("Cipher History Event", {"project": project}, ["name", "event_hash"], order_by="creation desc, name desc", as_dict=True)
    body = {"actor": actor.person_id, "company": company, "project": project, "event": event, "subject_type": subject_type, "subject_id": subject_id, "operation_id": operation_id, "details": details, "previous_hash": previous.event_hash if previous else ""}
    record = frappe.get_doc({"doctype": "Cipher History Event", "company": company, "project": project,
        "actor_person": actor.person_id, "event": event, "subject_type": subject_type, "subject_id": subject_id,
        "operation_id": operation_id, "details_json": canonical_json(details), "previous_hash": body["previous_hash"],
        "event_hash": digest(body), "event_payload": canonical_json(body)})
    record.insert(ignore_permissions=True)
    return record.name


def present_event(record):
    from frappe.utils import get_system_timezone
    return {"id": record.name, "event": record.event, "actor": frappe.db.get_value("Cipher Person", record.actor_person, "display_name") or "Registered person",
        "at": utc_timestamp(record.creation, source_timezone=get_system_timezone()), "subject_type": record.subject_type, "subject_id": record.subject_id,
        "details": json.loads(record.details_json)}
