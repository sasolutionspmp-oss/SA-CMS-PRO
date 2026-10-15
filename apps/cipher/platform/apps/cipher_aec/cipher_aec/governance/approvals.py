"""Immutable, independently reviewed Project status changes.

The static action registry intentionally contains no financial submit, payment,
import, arbitrary method, or model approval. A grant is consumed with its exact
local effect/receipt/history in the same database transaction.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import json

import frappe

from cipher_aec.api.contracts import canonical_json, digest, expected_version as parse_expected_version, text, utc_timestamp, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import decode_cursor, page_options, page_result, signing_secret
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.context import current_actor, duty_rows, require_project, require_session_authority, session_authority_reference, trusted_write
from cipher_aec.governance.history import append_event
from cipher_aec.projects.service import _exact_count, _page_scope, _query_page, present_project

ACTION = "project.status.change.v1"
POLICY = "CIPHER-PROJECT-STATUS-POLICY-V1"
POLICY_DEFINITION = {"action": ACTION, "request_ability": "approval.request", "review_ability": "approval.decide", "execute_ability": "approval.execute", "independent_person": True, "executor_must_be_requester": True, "human_review": True, "synthetic": True, "task_changes": "none"}
TRANSITIONS = {"Open": frozenset({"On hold", "Completed", "Cancelled"}), "On hold": frozenset({"Open", "Completed", "Cancelled"})}
_effect = ContextVar("cipher_exact_approval_effect", default=None)


def install_policy():
    if not frappe.db.exists("Cipher Approval Policy Revision", POLICY):
        with trusted_write():
            frappe.get_doc({"doctype": "Cipher Approval Policy Revision", "action": ACTION, "version": 1,
                "enabled": 1, "label": "Synthetic independent Project status review", "lifetime_seconds": 86400,
                "definition_json": canonical_json(POLICY_DEFINITION)}).insert(ignore_permissions=True, set_name=POLICY)


def _policy(lock=False):
    rows = frappe.db.sql("SELECT * FROM `tabCipher Approval Policy Revision` WHERE action=%s ORDER BY version DESC,name DESC LIMIT 1" + (" FOR UPDATE" if lock else ""), (ACTION,), as_dict=True)
    if not rows or not rows[0].enabled or json.loads(rows[0].definition_json) != POLICY_DEFINITION:
        raise DomainError("approval_policy_unavailable", "This action has no active qualified approval policy.", 409)
    return rows[0]


def _tasks(project, lock=False):
    rows = frappe.db.sql("SELECT name,status,modified,progress,task_weight FROM `tabTask` WHERE project=%s ORDER BY name" + (" FOR UPDATE" if lock else ""), (project,), as_dict=True)
    return [{"id": row.name, "status": row.status, "version": version_of(row), "progress": str(row.progress or 0), "weight": str(row.task_weight or 0)} for row in rows]


def _native_completion(record, status, tasks):
    # Mirror only the pinned native percentage calculation, and verify it against
    # the real controller before the transaction can commit. These are progress
    # percentages; commercial money never uses binary floating point.
    from frappe.utils import flt
    method = record.percent_complete_method
    percent = flt(record.percent_complete)
    if status == "Completed" and not tasks:
        method, percent = "Manual", 100.0
    if method == "Manual":
        percent = 100.0 if status == "Completed" else percent
    elif not tasks:
        percent = 0.0
    elif not method or method == "Task Completion":
        percent = flt(sum(t["status"] in {"Completed", "Cancelled"} for t in tasks) / len(tasks) * 100, 2)
    elif method in {"Task Progress", "Task Weight"}:
        weights = [flt(t["weight"]) for t in tasks]
        if method != "Task Weight" or not sum(weights):
            weights = [1] * len(tasks)
        progress = [100 if t["status"] in {"Completed", "Cancelled"} else flt(t["progress"]) for t in tasks]
        percent = flt(sum(a*b for a,b in zip(progress, weights)) / sum(weights), 2)
    resulting_status = status if method == "Manual" or status in {"On hold", "Cancelled"} else ("Completed" if percent == 100 else "Open")
    if resulting_status != status:
        raise DomainError("native_transition_conflict", "Native Task progress prevents this exact Project status. Adjust the work status before requesting review.", 409)
    return {"percent_complete_method": method, "percent_complete": str(percent)}


def _manifest(record, status, policy, actor, tasks):
    if status not in TRANSITIONS.get(record.status, ()):
        raise DomainError("transition_unsupported", "This Project status transition is not supported.", 422)
    if status == "Completed" and any(t["status"] not in {"Completed", "Cancelled"} for t in tasks):
        raise DomainError("tasks_incomplete", "Complete or cancel remaining Tasks before requesting Project completion.", 409)
    return {"action": ACTION, "action_version": 1, "company": record.company, "project": record.name,
        "subject": {"doctype": "Project", "name": record.name}, "source_version": version_of(record),
        "project_fields": {"status": record.status, "percent_complete_method": record.percent_complete_method, "percent_complete": str(record.percent_complete or 0)},
        "requested_status": status, "native_completion": _native_completion(record, status, tasks), "tasks": tasks, "task_changes": [], "requester_person": actor.person_id,
        "policy_revision": policy.name, "policy_hash": digest(json.loads(policy.definition_json))}


def _load(company, project, packet_id, lock=False):
    name = text(packet_id, "Approval packet", 140)
    rows = frappe.db.sql("SELECT * FROM `tabCipher Approval Packet` WHERE name=%s AND company=%s AND project=%s" + (" FOR UPDATE" if lock else ""), (name, company, project), as_dict=True)
    if not rows:
        raise DomainError("not_found", "This approval packet is not available.", 404)
    packet = rows[0]
    if digest(json.loads(packet.manifest_json)) != packet.manifest_hash:
        raise DomainError("approval_integrity", "This approval packet cannot be verified.", 409)
    return packet


def _decisions(packet, lock=False):
    return frappe.db.sql("SELECT * FROM `tabCipher Approval Decision` WHERE packet=%s ORDER BY creation,name" + (" FOR UPDATE" if lock else ""), (packet.name,), as_dict=True)


def _consumption(packet, lock=False):
    rows = frappe.db.sql("SELECT * FROM `tabCipher Approval Consumption` WHERE packet=%s" + (" FOR UPDATE" if lock else ""), (packet.name,), as_dict=True)
    return rows[0] if rows else None


def _state(packet, record, lock=False):
    decisions = _decisions(packet, lock)
    if _consumption(packet, lock):
        return "Consumed", decisions
    if decisions and decisions[-1].decision in {"Reject", "Withdraw"}:
        return {"Reject": "Rejected", "Withdraw": "Withdrawn"}[decisions[-1].decision], decisions
    if datetime.fromisoformat(packet.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        return "Expired", decisions
    try:
        policy = _policy(lock)
    except DomainError:
        return "Stale", decisions
    manifest = json.loads(packet.manifest_json)
    if packet.policy_revision != policy.name or manifest["policy_hash"] != digest(json.loads(policy.definition_json)) or packet.source_version != version_of(record) or manifest["tasks"] != _tasks(record.name, lock):
        return "Stale", decisions
    return ("Granted" if decisions and decisions[-1].decision == "Grant" else "Pending"), decisions


def _person(identifier):
    return {"id": identifier, "display_name": frappe.db.get_value("Cipher Person", identifier, "display_name") or "Registered person"}


def present(packet, record, actor, lock=False):
    state, decisions = _state(packet, record, lock)
    manifest = json.loads(packet.manifest_json)
    capabilities = {row.ability for row in duty_rows(actor, packet.company, packet.project, lock=lock)}
    independent = actor.person_id != packet.requester_person
    can_decide = state == "Pending" and independent and "approval.decide" in capabilities
    can_execute = state == "Granted" and not independent and "approval.execute" in capabilities and "project.write" in capabilities and decisions[-1].actor_person != actor.person_id
    can_withdraw = state in {"Pending", "Granted"} and not independent and "approval.request" in capabilities
    reason = None
    if not any((can_decide, can_execute, can_withdraw)):
        reason = {"Pending": "An independent person with review duty must review this packet.", "Granted": "The requester must execute the independently granted packet.", "Consumed": "This packet has already been executed.", "Stale": "The source or policy changed. Request a new packet.", "Expired": "The review period expired. Request a new packet.", "Rejected": "The reviewer rejected this packet.", "Withdrawn": "The requester withdrew this packet."}[state]
    return {"id": packet.name, "company": packet.company, "project": packet.project, "action": packet.action,
        "subject": {"id": packet.subject_id, "type": packet.subject_type, "label": record.project_name},
        "requester": _person(packet.requester_person), "created_at": packet.created_at, "expires_at": packet.expires_at,
        "manifest_hash": packet.manifest_hash, "source_version": packet.source_version,
        "changes": {"status": {"from": manifest["project_fields"]["status"], "to": manifest["requested_status"]}},
        "native_completion": manifest["native_completion"],
        "task_effects": {"count": len(manifest["tasks"]), "changes": []},
        "policy": {"id": packet.policy_revision, "label": frappe.db.get_value("Cipher Approval Policy Revision", packet.policy_revision, "label"), "synthetic": True},
        "state": state, "decisions": [{"id": d.name, "decision": d.decision, "actor": _person(d.actor_person), "at": d.decided_at, "reason": d.reason or ""} for d in decisions],
        "actions": {"can_decide": can_decide, "can_execute": can_execute, "can_withdraw": can_withdraw, "disabled_reason": reason}}


def read_packet(company, project, packet_id):
    actor = current_actor()
    record = require_project(company, project, actor=actor)
    return present(_load(company, project, packet_id), record, actor)


def list_packets(company, project, limit=50, cursor=None, count_mode="none"):
    actor = current_actor()
    record = require_project(company, project, actor=actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = _page_scope(actor, company, project, "approval_packets")
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    filters = {"company": company, "project": project}
    rows = _query_page("Cipher Approval Packet", filters=filters, order_field="creation", ascending=False, limit=limit, last=last, native_permissions=False)
    page = rows[:limit]
    return page_result([present(_load(company, project, row.name), record, actor) for row in page], has_more=len(rows)>limit,
        last=[str(page[-1].creation), page[-1].name] if page else None, scope=scope, limit=limit, count_mode=count_mode,
        total=_exact_count("Cipher Approval Packet", filters, False) if count_mode == "exact" else None)


def request_project_status(company, project, status, expected_version, operation_id):
    status = text(status, "Requested status", 30)
    source_version = parse_expected_version(expected_version)
    def effect(actor, record):
        if version_of(record) != source_version:
            raise DomainError("stale_version", "The Project changed. Refresh it before requesting review.", 412)
        policy = _policy(True)
        manifest = _manifest(record, status, policy, actor, _tasks(project, True))
        now = datetime.now(timezone.utc)
        packet = frappe.get_doc({"doctype": "Cipher Approval Packet", "company": company, "project": project,
            "action": ACTION, "subject_type": "Project", "subject_id": project, "requester_person": actor.person_id,
            "policy_revision": policy.name, "manifest_json": canonical_json(manifest), "manifest_hash": digest(manifest),
            "source_version": source_version, "created_at": utc_timestamp(now), "expires_at": utc_timestamp(now+timedelta(seconds=policy.lifetime_seconds))})
        packet.insert(ignore_permissions=True)
        _event(actor, packet, operation_id, "approval.requested", {"manifest_hash": packet.manifest_hash, "requested_status": status})
        return {"packet": present(packet, record, actor, True)}
    return run_command(company=company, project=project, operation_id=operation_id, command="approval.request", payload={"status": status, "expected_version": source_version}, ability="approval.request", effect=effect)


def _human_review(actor):
    # A worker/model API token cannot stand in for an independent human decision.
    kinds = frappe.db.sql("SELECT identity_kind FROM `tabCipher Person` WHERE name=%s FOR UPDATE", (actor.person_id,))
    if not kinds or kinds[0][0] != "Human":
        raise DomainError("human_review_required", "A registered human reviewer must decide this packet.", 403)
    request = getattr(frappe.local, "request", None)
    sid = getattr(frappe.session, "sid", None)
    if not request or request.method != "POST" or not sid or request.cookies.get("sid") != sid:
        raise DomainError("interactive_review_required", "Review this packet from your active signed-in session.", 403)
    reference = session_authority_reference(actor)
    require_session_authority(actor, reference, lock=True)


def _check_hash(packet, manifest_hash):
    if text(manifest_hash, "Manifest hash", 64) != packet.manifest_hash:
        raise DomainError("manifest_changed", "The reviewed manifest does not match this packet.", 409)


def _event(actor, packet, operation_id, event, details):
    append_event(actor=actor, company=packet.company, project=packet.project, event=event,
        subject_type="Cipher Approval Packet", subject_id=packet.name, operation_id=operation_id, details=details)


def _decision(actor, packet, decision, reason):
    doc = frappe.get_doc({"doctype": "Cipher Approval Decision", "company": packet.company, "project": packet.project,
        "packet": packet.name, "actor_person": actor.person_id, "decision": decision, "reason": reason,
        "manifest_hash": packet.manifest_hash, "decided_at": utc_timestamp()})
    doc.insert(ignore_permissions=True)
    return doc


def decide_packet(company, project, packet_id, manifest_hash, decision, operation_id, reason=""):
    if decision not in {"Grant", "Reject"}:
        raise DomainError("invalid_decision", "Choose Grant or Reject.", 422)
    reason = text(reason, "Review reason", 2000, required=False)
    def effect(actor, record):
        packet = _load(company, project, packet_id, True)
        _check_hash(packet, manifest_hash)
        _human_review(actor)
        if actor.person_id == packet.requester_person:
            raise DomainError("independent_review_required", "Another person must review your request, including when you use an alias account.", 403)
        state, _ = _state(packet, record, True)
        if state != "Pending":
            raise DomainError("approval_not_pending", "This packet is no longer awaiting review.", 409, {"state": state})
        _decision(actor, packet, decision, reason)
        _event(actor, packet, operation_id, "approval.decided", {"decision": decision, "manifest_hash": manifest_hash, "reason": reason})
        return {"packet": present(packet, record, actor, True)}
    return run_command(company=company, project=project, operation_id=operation_id, command="approval.decide", payload={"packet_id": packet_id,"manifest_hash": manifest_hash,"decision": decision,"reason": reason}, ability="approval.decide", effect=effect)


def withdraw_packet(company, project, packet_id, manifest_hash, operation_id, reason=""):
    reason = text(reason, "Withdrawal reason", 2000, required=False)
    def effect(actor, record):
        packet = _load(company, project, packet_id, True)
        _check_hash(packet, manifest_hash)
        if actor.person_id != packet.requester_person:
            raise DomainError("requester_required", "Only the requester may withdraw this packet.", 403)
        state, _ = _state(packet, record, True)
        if state not in {"Pending", "Granted"}:
            raise DomainError("approval_not_withdrawable", "This packet cannot be withdrawn.", 409)
        _decision(actor, packet, "Withdraw", reason)
        _event(actor, packet, operation_id, "approval.withdrawn", {"reason": reason})
        return {"packet": present(packet, record, actor, True)}
    return run_command(company=company, project=project, operation_id=operation_id, command="approval.withdraw", payload={"packet_id": packet_id,"manifest_hash": manifest_hash,"reason": reason}, ability="approval.request", effect=effect)


@contextmanager
def _exact_effect(packet, manifest):
    token = _effect.set({"packet": packet.name, "action": packet.action, "project": packet.project, "source_version": packet.source_version, "status": manifest["requested_status"]})
    try:
        yield
    finally:
        _effect.reset(token)


def require_project_status_grant(doc, old):
    grant = _effect.get()
    if not grant or grant["action"] != ACTION or grant["project"] != doc.name or grant["source_version"] != version_of(old) or grant["status"] != doc.status:
        raise DomainError("approval_required", "Request and independently approve this exact Project status change before executing it.", 403)


def execute_packet(company, project, packet_id, manifest_hash, operation_id):
    require_project(company, project)
    snapshot = _load(company, project, packet_id)
    decisions_before_lock = _decisions(snapshot)
    participants = tuple(sorted({snapshot.requester_person} | {d.actor_person for d in decisions_before_lock if d.decision == "Grant"}))
    def effect(actor, record):
        require_project(company, project, ability="project.write", actor=actor, lock=True)
        packet = _load(company, project, packet_id, True)
        _check_hash(packet, manifest_hash)
        state, decisions = _state(packet, record, True)
        if state != "Granted":
            raise DomainError("approval_not_executable", "This exact packet has no current unconsumed grant.", 409, {"state": state})
        if actor.person_id != packet.requester_person or decisions[-1].actor_person == actor.person_id:
            raise DomainError("requester_required", "The requester must execute a different person's grant.", 403)
        if decisions[-1].actor_person not in participants:
            raise DomainError("concurrent_change", "The review changed concurrently. Retry this original operation.", 503)
        # All participant identity/person/User locks were acquired before Project.
        # The reviewer must still have live scoped review authority at consumption.
        reviewer_users = frappe.db.sql("SELECT user FROM `tabCipher Identity Binding` WHERE person=%s AND active=1 ORDER BY name FOR UPDATE", (decisions[-1].actor_person,), as_dict=True)
        reviewer = None
        for candidate in reviewer_users:
            try:
                reviewer = current_actor(candidate.user, lock=True)
                require_project(company, project, ability="approval.decide", actor=reviewer, lock=True)
                break
            except DomainError:
                reviewer = None
        kinds = frappe.db.sql("SELECT identity_kind FROM `tabCipher Person` WHERE name=%s FOR UPDATE", (decisions[-1].actor_person,))
        if reviewer is None or not kinds or kinds[0][0] != "Human":
            raise DomainError("reviewer_authority_revoked", "The reviewer's authority changed. Obtain a fresh review.", 403)
        manifest = json.loads(packet.manifest_json)
        # Reconstruct transition eligibility with current locked standard masters.
        _manifest(record, manifest["requested_status"], _policy(True), actor, _tasks(project, True))
        with _exact_effect(packet, manifest):
            record.status = manifest["requested_status"]
            record.save(ignore_permissions=True)
        if record.status != manifest["requested_status"] or record.percent_complete_method != manifest["native_completion"]["percent_complete_method"] or float(record.percent_complete or 0) != float(manifest["native_completion"]["percent_complete"]) or _tasks(project, True) != manifest["tasks"]:
            raise DomainError("unexpected_native_effect", "Native Project validation changed the approved outcome. No change was saved.", 409)
        result = {"project": present_project(record, actor)}
        frappe.get_doc({"doctype": "Cipher Approval Consumption", "company": company, "project": project,
            "packet": packet.name, "decision": decisions[-1].name, "actor_person": actor.person_id,
            "operation_id": operation_id, "result_hash": digest(result), "consumed_at": utc_timestamp()}).insert(ignore_permissions=True)
        _event(actor, packet, operation_id, "approval.executed", {"manifest_hash": packet.manifest_hash, "status": record.status, "task_changes": []})
        return {"packet": present(packet, record, actor, True), "effect": result}
    return run_command(company=company, project=project, operation_id=operation_id, command="approval.execute", payload={"packet_id": packet_id,"manifest_hash": manifest_hash}, ability="approval.execute", effect=effect, participant_people=participants)


def prevent_unsupported_financial_transition(doc, method=None):
    """Catalogued native financial workflows remain disabled until domain-qualified."""
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return
    old = doc.get_doc_before_save()
    # Import/REST creation with docstatus=1 must hit the same guard as submit().
    if method in {"before_submit", "before_cancel"} or int(doc.docstatus or 0) != int(old.docstatus if old else 0):
        raise DomainError("financial_action_unqualified", "This financial submit or cancellation action is not qualified in this release.", 403)
