"""Fenced Company transport outside Frappe locks; Unknown reconciles by key."""
from datetime import timedelta
import json

import frappe
from frappe.utils import now_datetime

from cipher_aec.api.contracts import canonical_json, digest, utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_company, require_effects_enabled, trusted_write, execution_quarantined
from . import distribution as service, distribution_contracts as rules, distribution_transport as transport
from .distribution_records import operation_write


def _save(doc):
    with trusted_write(), operation_write(doc.name, doc.fencing_token):
        doc.save(ignore_permissions=True)


def _attempt(doc, outcome, details):
    with trusted_write(), operation_write(doc.name, doc.fencing_token):
        frappe.get_doc({"doctype": "Cipher Delivery Attempt", "scope_type": "Company", "operation": doc.name,
            "fencing_token": doc.fencing_token, "outcome": outcome, "company": doc.company, "project": None,
            "safe_details": canonical_json(details)}).insert(ignore_permissions=True)


def _verify_ack(ack, doc, payload):
    if (not isinstance(ack, dict) or ack.get("mode") != "fixture" or ack.get("logical_key") != doc.logical_id or
            ack.get("payload_hash") != doc.payload_hash or ack.get("attachment_sha256") != payload["attachment"]["sha256"] or
            ack.get("byte_length") != payload["attachment"]["byte_length"] or not ack.get("acknowledgment_id")):
        raise DomainError("distribution_integrity", "The acknowledgment differs from the exact authorized payload.", 409)


def _record(identifier, fence, state, *, receipt=None, code=None):
    doc = frappe.get_doc("Cipher Integration Operation", identifier, for_update=True)
    if doc.fencing_token != fence or doc.state not in {"Claimed", "Unknown"}:
        frappe.db.rollback()
        return {"state": "superseded"}
    doc.state, doc.last_error_code = state, code
    if receipt is not None:
        doc.result_json = canonical_json({"receipt": receipt, "mode": "fixture"})
    doc.lease_until = now_datetime() + timedelta(seconds=rules.LEASE_SECONDS) if state == "Unknown" else None
    _save(doc)
    _attempt(doc, state, {"code": code, "mode": "fixture", "acknowledgment_id": receipt.get("acknowledgment_id") if receipt else None})
    frappe.db.commit()
    return {"state": state, "mode": "fixture", "code": code}


def _authorize(doc, payload):
    """Current authority/sources after Person→identity→Company locks."""
    from cipher_aec.governance.approvals import _policy
    from cipher_aec.commercial.outputs import issue_source_reference
    dispatch = service.raw("dispatch", payload["dispatch_id"], doc.company)
    people = sorted({dispatch["requester_person"], dispatch["reviewer_person"]})
    if len(people) != 2:
        raise DomainError("independent_review_required", "Dispatch requires an independent reviewer.", 403)
    frappe.db.sql("SELECT name FROM `tabCipher Person` WHERE name IN (%s,%s) ORDER BY name FOR UPDATE", people)
    actors = []
    for prefix in ("requester", "reviewer"):
        actor = current_actor(dispatch[prefix + "_user"], lock=True)
        if actor.person_id != dispatch[prefix + "_person"]:
            raise DomainError("identity_changed", "The original dispatch identity changed.", 403)
        actors.append(actor)
    requester, reviewer = actors
    kinds = frappe.db.sql("SELECT name,identity_kind FROM `tabCipher Person` WHERE name IN (%s,%s) ORDER BY name FOR UPDATE", people)
    if len(kinds) != 2 or any(kind != "Human" for name, kind in kinds):
        raise DomainError("human_review_required", "Dispatch requires current human identities.", 403)
    require_company(doc.company, ability="commercial.distribute", actor=requester, lock=True)
    require_company(doc.company, ability="approval.execute", actor=requester, lock=True)
    require_company(doc.company, ability="approval.decide", actor=reviewer, lock=True)
    dispatch = service.raw("dispatch", dispatch["id"], doc.company, lock=True)
    instruction = service.read("instruction", dispatch["instruction_id"], doc.company, requester, lock=True)
    service.read("instruction", dispatch["instruction_id"], doc.company, reviewer, lock=True)
    if service.cancellation(dispatch["id"], doc.company, lock=True):
        raise DomainError("distribution_cancelled", "The remaining dispatch was cancelled.", 409)
    if rules.moment(dispatch["valid_until"]) <= rules.utc_now():
        raise DomainError("distribution_mandate_expired", "The durable dispatch mandate expired.", 409)
    if service.profile() != dispatch["profile"]:
        raise DomainError("distribution_profile_changed", "The authorized delivery profile changed.", 409)
    packet = frappe.get_doc("Cipher Approval Packet", dispatch["packet_id"], for_update=True)
    decision = frappe.get_doc("Cipher Approval Decision", dispatch["decision_id"], for_update=True)
    policy = _policy(True, rules.ACTION, "Company")
    outer = json.loads(packet.manifest_json)
    consumed = frappe.db.sql("SELECT decision,actor_person,company,scope_type,project FROM `tabCipher Approval Consumption` WHERE packet=%s FOR UPDATE", (packet.name,), as_dict=True)
    if (packet.manifest_hash != dispatch["packet_manifest_hash"] or digest(outer) != packet.manifest_hash or
            packet.action != rules.ACTION or packet.scope_type != "Company" or packet.company != doc.company or packet.project or
            packet.requester_person != requester.person_id or packet.subject_id != instruction["id"] or
            packet.policy_revision != policy.name or outer["policy_hash"] != digest(json.loads(policy.definition_json)) or
            outer["domain"]["effect"]["instruction_digest"] != digest(instruction) or
            decision.packet != packet.name or decision.actor_person != reviewer.person_id or decision.owner != reviewer.user or
            decision.manifest_hash != packet.manifest_hash or decision.decision != "Grant" or
            len(consumed) != 1 or consumed[0].decision != decision.name or consumed[0].actor_person != requester.person_id or
            consumed[0].scope_type != "Company" or consumed[0].company != doc.company or consumed[0].project):
        raise DomainError("distribution_grant_changed", "The original durable grant is no longer valid.", 403)
    if digest(instruction) != payload["instruction_digest"] or digest(payload) != doc.payload_hash:
        raise DomainError("distribution_integrity", "The durable recipient payload failed verification.", 409)
    source = issue_source_reference(doc.company, instruction["issue_id"], requester, lock=True)["source"]
    content = source["content"]
    rules.verify_bytes(content, instruction["attachment"])
    return content, dispatch


def deliver(operation):
    if execution_quarantined():
        return {"state": "Quarantined"}
    require_effects_enabled()
    original_user, fence, uncertain = frappe.session.user, None, False
    try:
        doc = frappe.get_doc("Cipher Integration Operation", operation, for_update=True)
        if doc.kind != rules.KIND or doc.scope_type != "Company" or doc.project:
            raise DomainError("integration_unavailable", "This is not a registered Company delivery.", 403)
        if doc.state in {"Succeeded", "Failed", "Cancelled"}:
            frappe.db.rollback()
            return {"state": doc.state}
        if doc.lease_until and doc.lease_until > now_datetime():
            frappe.db.rollback()
            return {"state": doc.state}
        uncertain = bool(doc.result_json) or doc.state == "Unknown"
        doc.state, doc.fencing_token = "Claimed", (doc.fencing_token or 0) + 1
        doc.attempt_count = (doc.attempt_count or 0) + 1
        doc.lease_until = now_datetime() + timedelta(seconds=rules.LEASE_SECONDS)
        fence = doc.fencing_token
        _save(doc)
        payload = json.loads(doc.payload_json)
        if digest(payload) != doc.payload_hash:
            raise DomainError("distribution_integrity", "The persisted payload failed verification.", 409)
        frappe.db.commit()
        # Readback remains observational after expiry, cancel or revocation.
        uncertain = True
        acknowledgment = transport.readback(doc.logical_id)
        if acknowledgment is not None:
            _verify_ack(acknowledgment, doc, payload)
            return _record(operation, fence, "Succeeded", receipt=acknowledgment)
        previous = json.loads(doc.result_json) if doc.result_json else {}
        if previous.get("attempt_not_after") and rules.moment(previous["attempt_not_after"]) > rules.utc_now():
            return _record(operation, fence, "Unknown", code="distribution_attempt_in_flight")
        uncertain = False
        content, dispatch = _authorize(doc, payload)
        current = frappe.get_doc("Cipher Integration Operation", operation, for_update=True)
        if current.fencing_token != fence or current.state != "Claimed":
            frappe.db.rollback()
            return {"state": "superseded"}
        not_after = min(rules.utc_now() + timedelta(seconds=rules.ATTEMPT_SECONDS), rules.moment(dispatch["valid_until"]))
        current.state = "Unknown"
        current.result_json = canonical_json({"attempt_not_after": utc_timestamp(not_after), "mode": "fixture"})
        _save(current)
        _attempt(current, "Unknown", {"phase": "authorized_attempt", "attempt_not_after": utc_timestamp(not_after), "mode": "fixture"})
        service.require_current_effects_enabled()
        frappe.db.commit()
        # Committed irrevocable in-flight boundary: no Frappe locks held here.
        uncertain = True
        acknowledgment = transport.accept(doc.logical_id, payload, content, utc_timestamp(not_after))
        _verify_ack(acknowledgment, doc, payload)
        return _record(operation, fence, "Succeeded", receipt=acknowledgment)
    except Exception as error:
        frappe.db.rollback()
        if fence is None:
            raise
        code = error.code if isinstance(error, DomainError) else "fixture_delivery_unavailable"
        state = "Unknown" if uncertain else "Cancelled" if code == "distribution_cancelled" else "Failed"
        return _record(operation, fence, state, code=code)
    finally:
        frappe.set_user(original_user)
