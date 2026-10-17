"""One literal independent grant creates a bounded durable Company mandate."""
from datetime import datetime
import json
from uuid import uuid4

import frappe

from cipher_aec.api.contracts import canonical_json, digest, utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company, session_authority_reference, trusted_write
from . import distribution as service, distribution_contracts as rules


def _scope(scope_type, project):
    if scope_type != "Company" or project is not None:
        raise DomainError("not_found", "This distribution action is not available.", 404)


def authorize_subject(*, actor, company, project, subject_id, phase, lock=False, manifest=None, scope_type):
    _scope(scope_type, project)
    value = service.read("instruction", subject_id, company, actor, lock=lock)
    if manifest is not None and (manifest["effect"]["instruction_digest"] != digest(value) or manifest["effect"]["instruction_id"] != subject_id):
        raise DomainError("distribution_integrity", "The original dispatch authorization cannot be verified.", 409)
    if phase in {"request", "execute"}:
        require_company(company, ability="commercial.distribute", actor=actor, lock=lock)
        if value["author_person"] != actor.person_id:
            raise DomainError("distribution_author_required", "The instruction author must request and execute its dispatch.", 403)
    if phase == "review" and value["author_person"] == actor.person_id:
        raise DomainError("independent_review_required", "Another canonical person must review the exact distribution instruction.", 403)
    return value


def approval_manifest(*, actor, company, project, subject_id, expected_version, lock=False, scope_type):
    value = authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id, phase="read", lock=lock, scope_type=scope_type)
    selected_profile = service.profile()
    if selected_profile != value["profile"] or rules.moment(value["valid_until"]) <= rules.utc_now():
        raise DomainError("distribution_mandate_expired", "The instruction or selected profile expired. Create a new instruction.", 412)
    if expected_version != digest(value):
        raise DomainError("stale_distribution", "Review the exact immutable distribution instruction.", 412)
    if frappe.db.sql("SELECT name FROM `tabCipher Distribution Dispatch` WHERE instruction_id=%s" + (" FOR UPDATE" if lock else ""), (subject_id,)):
        raise DomainError("distribution_already_dispatched", "This instruction already has its exact dispatch.", 409)
    return {"subject": {"doctype": service.TYPES["instruction"], "name": subject_id, "label": f"Issue {value['issue_id']} · {len(value['recipients'])} recipient(s) · {value['message']['subject']}"},
        "sources": [{"issue_id": value["issue_id"], "issue_digest": value["issue_digest"], "attachment": value["attachment"]}],
        "effect": {"action": rules.ACTION, "instruction_id": subject_id, "instruction_digest": digest(value),
            "recipients": value["recipients"], "message_digest": value["message_digest"], "cover_digest": value["cover_digest"],
            "profile": value["profile"], "valid_until": value["valid_until"]},
        "summary": {"mode": "fixture", "recipient_count": len(value["recipients"]), "subject": value["message"]["subject"],
            "live_transmission": False, "durable_authorization": True, "in_flight_may_complete_after_revocation": True}}


def apply_dispatch(*, actor, company, project, manifest, packet_id, decision_id, operation_id, scope_type):
    _scope(scope_type, project)
    from cipher_aec.governance.approvals import require_approval_effect
    subject_id = manifest["effect"]["instruction_id"]
    require_approval_effect(action=rules.ACTION, subject_id=subject_id, packet_id=packet_id, scope_type="Company")
    value = authorize_subject(actor=actor, company=company, project=None, subject_id=subject_id, phase="execute", lock=True, manifest=manifest, scope_type="Company")
    current = approval_manifest(actor=actor, company=company, project=None, subject_id=subject_id, expected_version=digest(value), lock=True, scope_type="Company")
    if current != manifest:
        raise DomainError("stale_distribution", "The exact reviewed instruction changed. Obtain fresh independent review.", 412)
    packet = frappe.get_doc("Cipher Approval Packet", packet_id, for_update=True)
    decision = frappe.get_doc("Cipher Approval Decision", decision_id, for_update=True)
    if decision.packet != packet_id or decision.decision != "Grant" or decision.actor_person == actor.person_id:
        raise DomainError("independent_review_required", "An independent person's exact grant is required.", 403)
    until = min(rules.moment(value["valid_until"]), rules.moment(packet.expires_at))
    dispatch = {"id": str(uuid4()), "scope_type": "Company", "company": company, "project": None,
        "instruction_id": subject_id, "instruction_digest": digest(value), "issue_id": value["issue_id"],
        "packet_id": packet_id, "decision_id": decision_id, "packet_manifest_hash": packet.manifest_hash,
        "requester_person": actor.person_id, "requester_user": actor.user,
        "reviewer_person": decision.actor_person, "reviewer_user": decision.owner,
        "request_session_reference": value["session_reference"], "execute_session_reference": session_authority_reference(actor),
        "review_session_reference": decision.session_reference,
        "policy_revision": packet.policy_revision, "created_at": utc_timestamp(rules.utc_now()),
        "valid_until": utc_timestamp(until), "profile": value["profile"], "mode": "fixture"}
    service.insert("dispatch", dispatch)
    for recipient in value["recipients"]:
        logical = rules.logical_key(dispatch["id"], recipient["id"])
        payload = {"schema": "cipher.distribution.payload.v1", "company": company, "dispatch_id": dispatch["id"],
            "instruction_id": subject_id, "instruction_digest": digest(value), "issue_id": value["issue_id"],
            "recipient": recipient, "attachment": value["attachment"], "message": value["message"],
            "profile": value["profile"], "mode": "fixture"}
        with trusted_write():
            frappe.get_doc({"doctype": "Cipher Integration Operation", "scope_type": "Company", "company": company, "project": None,
                "actor_user": actor.user, "actor_person": actor.person_id, "logical_id": logical, "effect_operation_id": str(uuid4()),
                "distribution_dispatch": dispatch["id"], "recipient_id": recipient["id"],
                "kind": rules.KIND, "state": "Queued", "payload_json": canonical_json(payload), "payload_hash": digest(payload),
                "fencing_token": 0, "attempt_count": 0}).insert(ignore_permissions=True)
    service.event(actor, dispatch, operation_id, "distribution.dispatch.authorized", "dispatch")
    from .outbox import _schedule
    names = frappe.db.sql("SELECT name FROM `tabCipher Integration Operation` WHERE kind=%s AND company=%s AND distribution_dispatch=%s", (rules.KIND, company, dispatch["id"]))
    for (name,) in names:
        frappe.db.after_commit.add(lambda name=name: _schedule(name))
    return {"dispatch": dispatch, "mode": "fixture", "delivery_status": "Queued"}
