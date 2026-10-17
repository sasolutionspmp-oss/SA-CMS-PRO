"""Immutable, independently reviewed Project status changes.

The static action registry intentionally contains no financial submit, payment,
import, arbitrary method, or model approval. A grant is consumed with its exact
local effect/receipt/history in the same database transaction.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import json

import frappe

from cipher_aec.api.contracts import canonical_json, digest, expected_version as parse_expected_version, text, utc_timestamp, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import decode_cursor, page_options, page_result, signing_secret
from cipher_aec.governance.commands import run_command, run_company_command
from cipher_aec.governance.context import current_actor, duty_rows, company_duty_rows, require_project, require_company, company_authority_fingerprint, require_session_authority, session_authority_reference, trusted_write
from cipher_aec.governance.history import append_event, append_company_event
from cipher_aec.projects.service import _exact_count, _page_scope, _query_page, present_project
from . import domain_approvals

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

    for action, spec in domain_approvals.ACTIONS.items():
        if not spec.enabled:
            continue
        for scope_type in spec.scopes:
            policy_id = spec.policy_id + ("-COMPANY" if scope_type == "Company" else "")
            if frappe.db.exists("DocType", spec.subject_type) and not frappe.db.exists("Cipher Approval Policy Revision", policy_id):
                with trusted_write():
                    frappe.get_doc({"doctype": "Cipher Approval Policy Revision", "action": action, "scope_type": scope_type, "version": 1,
                        "enabled": 1, "label": spec.label, "lifetime_seconds": 86400,
                        "definition_json": canonical_json(domain_approvals.definition(action, scope_type))}).insert(ignore_permissions=True, set_name=policy_id)


def _policy(lock=False, action=ACTION, scope_type="Project"):
    if action == ACTION and scope_type != "Project":
        raise DomainError("approval_action_unqualified", "This approval action requires Project scope.", 403)
    rows = frappe.db.sql("SELECT * FROM `tabCipher Approval Policy Revision` WHERE action=%s AND scope_type=%s ORDER BY version DESC,name DESC LIMIT 1" + (" FOR UPDATE" if lock else ""), (action, scope_type), as_dict=True)
    expected_definition = POLICY_DEFINITION if action == ACTION else domain_approvals.definition(action, scope_type)
    if not rows or not rows[0].enabled or json.loads(rows[0].definition_json) != expected_definition:
        raise DomainError("approval_policy_unavailable", "This action has no active qualified approval policy.", 409)
    return rows[0]


def _scope(company, project, scope_type, actor=None, ability=None, lock=False):
    if scope_type == "Project":
        return require_project(company, project, ability=ability or "project.read", actor=actor, lock=lock)
    if scope_type == "Company" and project is None:
        return require_company(company, ability=ability or "company.read", actor=actor, lock=lock)
    raise DomainError("invalid_scope", "Declare an exact Company or Project scope.", 422)


def _command(*, scope_type="Project", company, project, **kwargs):
    if scope_type == "Project":
        from cipher_aec.document_control.locking import for_approval
        context=for_approval(company,project,kwargs.get('payload',{}))
        if context is not None:kwargs['document_context']=context
        return run_command(company=company, project=project, **kwargs)
    if scope_type == "Company" and project is None:
        return run_company_command(company=company, **kwargs)
    raise DomainError("invalid_scope", "Declare an exact Company or Project scope.", 422)


def _duties(actor, company, project, scope_type, lock=False):
    return company_duty_rows(actor, company, lock=lock) if scope_type == "Company" else duty_rows(actor, company, project, lock=lock)


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


def _load(company, project, packet_id, lock=False, *, scope_type="Project"):
    name = text(packet_id, "Approval packet", 140)
    if scope_type == "Project" and project:
        condition, args = "project=%s", (name, company, scope_type, project)
    elif scope_type == "Company" and project is None:
        condition, args = "(project IS NULL OR project='')", (name, company, scope_type)
    else:
        raise DomainError("invalid_scope", "Declare an exact Company or Project scope.", 422)
    rows = frappe.db.sql("SELECT * FROM `tabCipher Approval Packet` WHERE name=%s AND company=%s AND scope_type=%s AND " + condition + (" FOR UPDATE" if lock else ""), args, as_dict=True)
    if not rows:
        raise DomainError("not_found", "This approval packet is not available.", 404)
    packet = rows[0]
    if packet.action != ACTION:
        domain_approvals.spec_for(packet.action, scope_type)
    elif scope_type != "Project":
        raise DomainError("approval_integrity", "The approval action does not match its declared scope.", 409)
    manifest = json.loads(packet.manifest_json)
    if manifest.get("scope_type", "Project") != scope_type or manifest.get("company") != company or (manifest.get("project") or None) != (project or None):
        raise DomainError("approval_integrity", "The approval manifest does not match its declared scope.", 409)
    if digest(json.loads(packet.manifest_json)) != packet.manifest_hash:
        raise DomainError("approval_integrity", "This approval packet cannot be verified.", 409)
    return packet


def _decisions(packet, lock=False):
    return frappe.db.sql("SELECT * FROM `tabCipher Approval Decision` WHERE packet=%s ORDER BY creation,name" + (" FOR UPDATE" if lock else ""), (packet.name,), as_dict=True)


def _consumption(packet, lock=False):
    rows = frappe.db.sql("SELECT * FROM `tabCipher Approval Consumption` WHERE packet=%s" + (" FOR UPDATE" if lock else ""), (packet.name,), as_dict=True)
    return rows[0] if rows else None


def _state(packet, record, lock=False, actor=None):
    decisions = _decisions(packet, lock)
    if _consumption(packet, lock):
        return "Consumed", decisions
    if decisions and decisions[-1].decision in {"Reject", "Withdraw"}:
        return {"Reject": "Rejected", "Withdraw": "Withdrawn"}[decisions[-1].decision], decisions
    if datetime.fromisoformat(packet.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        return "Expired", decisions
    try:
        policy = _policy(lock, packet.action, packet.scope_type or "Project")
    except DomainError:
        return "Stale", decisions
    manifest = json.loads(packet.manifest_json)
    if packet.policy_revision != policy.name or manifest["policy_hash"] != digest(json.loads(policy.definition_json)):
        return "Stale", decisions
    if packet.action == ACTION:
        if packet.source_version != version_of(record) or manifest["tasks"] != _tasks(record.name, lock):
            return "Stale", decisions
    else:
        try:
            if domain_approvals.current_manifest(packet, actor or current_actor(), lock=lock) != manifest["domain"]:
                return "Stale", decisions
        except DomainError as error:
            if error.status in {401, 403, 404}:
                raise
            return "Stale", decisions
    return ("Granted" if decisions and decisions[-1].decision == "Grant" else "Pending"), decisions


def _person(identifier):
    return {"id": identifier, "display_name": frappe.db.get_value("Cipher Person", identifier, "display_name") or "Registered person"}


def present(packet, record, actor, lock=False):
    if packet.action != ACTION:
        domain_approvals.authorize(packet, actor, lock=lock)
    state, decisions = _state(packet, record, lock, actor=actor)
    manifest = json.loads(packet.manifest_json)
    capabilities = {row.ability for row in _duties(actor, packet.company, packet.project or None, packet.scope_type or "Project", lock=lock)}
    independent = actor.person_id != packet.requester_person
    can_decide = state == "Pending" and independent and "approval.decide" in capabilities
    write_ability = "project.write" if packet.action == ACTION else domain_approvals.ACTIONS[packet.action].write_ability
    can_execute = state == "Granted" and not independent and "approval.execute" in capabilities and write_ability in capabilities and decisions[-1].actor_person != actor.person_id
    review_reason = None
    if can_decide and packet.action != ACTION:
        try:
            domain_approvals.authorize(packet, actor, phase="review", lock=lock)
        except DomainError as error:
            can_decide = False
            review_reason = error.message
    if packet.action != ACTION and (packet.scope_type or "Project") == "Project" and record.status in {"Completed", "Cancelled"}:
        can_execute = False
    can_withdraw = state in {"Pending", "Granted"} and not independent and "approval.request" in capabilities
    reason = review_reason
    if not any((can_decide, can_execute, can_withdraw)):
        reason = review_reason or {"Pending": "An independent person with review duty must review this packet.", "Granted": "The requester must execute the independently granted packet.", "Consumed": "This packet has already been executed.", "Stale": "The source or policy changed. Request a new packet.", "Expired": "The review period expired. Request a new packet.", "Rejected": "The reviewer rejected this packet.", "Withdrawn": "The requester withdrew this packet."}[state]
    result = {"id": packet.name, "company": packet.company, "project": packet.project, "action": packet.action,
        "subject": {"id": packet.subject_id, "type": packet.subject_type, "label": record.project_name if packet.action == ACTION else domain_approvals.subject_label(manifest)},
        "requester": _person(packet.requester_person), "created_at": packet.created_at, "expires_at": packet.expires_at,
        "manifest_hash": packet.manifest_hash, "source_version": packet.source_version,
        "policy": {"id": packet.policy_revision, "label": frappe.db.get_value("Cipher Approval Policy Revision", packet.policy_revision, "label"), "synthetic": True},
        "state": state, "decisions": [{"id": d.name, "decision": d.decision, "actor": _person(d.actor_person), "at": d.decided_at, "reason": d.reason or ""} for d in decisions],
        "actions": {"can_decide": can_decide, "can_execute": can_execute, "can_withdraw": can_withdraw, "disabled_reason": reason}}
    if packet.action == ACTION:
        result.update(changes={"status": {"from": manifest["project_fields"]["status"], "to": manifest["requested_status"]}},
            native_completion=manifest["native_completion"], task_effects={"count": len(manifest["tasks"]), "changes": []})
    else:
        result["review_manifest"] = manifest["domain"]
    if packet.action in {"document.issue.v1","document.library.adopt.v1","document.transmit.v1","document.clause.apply.v1","document.lifecycle.v1"}:
        result["schema"] = "cipher.document.approval.v1"
    if packet.action in {"engineering.basis.check.v1", "engineering.calculation.check.v1", "engineering.deliverable.check.v1"}:
        result["schema"] = "cipher.engineering.package-approval.v1"
    if packet.action in {"engineering.rfi.authorize.v1", "engineering.submittal.authorize.v1", "engineering.distribute.v1"}:
        result["schema"] = "cipher.engineering.approval.v1"
    if (packet.scope_type or "Project") == "Company":
        result.update(scope_type="Company", project=None)
    return result


def read_packet(company, project, packet_id, *, scope_type="Project"):
    actor = current_actor()
    record = _scope(company, project, scope_type, actor=actor)
    packet = _load(company, project, packet_id, scope_type=scope_type)
    if scope_type == "Company":
        from cipher_aec.documents.provenance import read_graph, read_graph_eligible
        with read_graph(actor, company) if read_graph_eligible(actor, company) else nullcontext():
            return present(packet, record, actor)
    return present(packet, record, actor)


def authorize_history_packet(company, project, packet_id, *, actor, scope_type="Project"):
    """Authorize the exact stored history source without rebuilding UI actions.

    Current source rights still apply. Later working bindings, current approval
    eligibility, decisions and presentation are not evidence for an old event.
    """
    _scope(company, project, scope_type, actor=actor)
    packet = _load(company, project, packet_id, scope_type=scope_type)
    if packet.action != ACTION:
        domain_approvals.authorize(packet, actor, phase="read", lock=False)


def list_packets(company, project, limit=50, cursor=None, count_mode="none", *, scope_type="Project"):
    actor = current_actor()
    record = _scope(company, project, scope_type, actor=actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = _page_scope(actor, company, project, "approval_packets") if scope_type == "Project" else {"selector":"company_approval_packets", "count_mode":count_mode, "company":company,"person":actor.person_id,"user":actor.user,"authority":company_authority_fingerprint(actor,company)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    capabilities = {row.ability for row in _duties(actor, company, project, scope_type)}
    allowed_actions = ([ACTION] if scope_type == "Project" else []) + [action for action, spec in domain_approvals.ACTIONS.items() if spec.enabled and scope_type in spec.scopes and spec.read_ability in capabilities]
    if not allowed_actions:
        return page_result([], has_more=False, last=None, scope=scope, limit=limit, count_mode=count_mode, total=0 if count_mode == "exact" else None)
    if scope_type == "Company":
        from cipher_aec.documents.provenance import read_graph, read_graph_eligible
        from .approval_listing import list_company_packets
        with read_graph(actor, company) if read_graph_eligible(actor, company) else nullcontext():
            return list_company_packets(company=company, actor=actor, record=record,
                allowed_actions=allowed_actions, scope=scope, limit=limit, last=last, count_mode=count_mode)
    filters = {"company": company, "project": project if scope_type == "Project" else ["is", "not set"], "scope_type": scope_type, "action": ["in", allowed_actions]}
    def visible(start=None):
        seek = start
        scanned = 0
        while True:
            rows = _query_page("Cipher Approval Packet", filters=filters, order_field="creation", ascending=False, limit=200, last=seek, native_permissions=False)
            # The query requests one lookahead row; process only the bounded chunk.
            chunk = rows[:200]
            scanned += len(chunk)
            if scanned > 10000:
                raise DomainError("authorization_scan_limit", "Narrow this approval scope before listing it.", 409)
            for row in chunk:
                try:
                    value = present(_load(company, project, row.name, scope_type=scope_type), record, actor)
                except DomainError as error:
                    if error.status in {401, 403, 404}:
                        continue
                    raise
                yield row, value
            if len(rows) <= 200 or not chunk:
                return
            seek = [str(chunk[-1].creation), chunk[-1].name]
    selected = []
    for row, value in visible(last):
        selected.append((row, value))
        if len(selected) > limit:
            break
    page = selected[:limit]
    total = sum(1 for _ in visible()) if count_mode == "exact" else None
    return page_result([value for _, value in page], has_more=len(selected)>limit,
        last=[str(page[-1][0].creation), page[-1][0].name] if page else None,
        scope=scope, limit=limit, count_mode=count_mode, total=total)


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
    append = append_company_event if (packet.scope_type or "Project") == "Company" else append_event
    scope_args = {} if (packet.scope_type or "Project") == "Company" else {"project": packet.project}
    append(actor=actor, company=packet.company, **scope_args, event=event,
        subject_type="Cipher Approval Packet", subject_id=packet.name, operation_id=operation_id, details=details)


def _decision(actor, packet, decision, reason):
    doc = frappe.get_doc({"doctype": "Cipher Approval Decision", "company": packet.company, "project": packet.project,
        "scope_type": packet.scope_type or "Project", "packet": packet.name, "actor_person": actor.person_id, "decision": decision, "reason": reason,
        "manifest_hash": packet.manifest_hash, "decided_at": utc_timestamp()})
    if packet.action == "proposal.distribute.v1":
        doc.session_reference = session_authority_reference(actor)
    doc.insert(ignore_permissions=True)
    return doc


def _award_packet_people(company,project,packet_id,scope_type):
    if scope_type == "Project" and project is not None:
        _scope(company,project,"Project")
        packet=_load(company,project,packet_id,scope_type="Project")
        if packet.action == "engineering.distribute.v1":
            return domain_approvals.participant_people(packet.action,company,packet.subject_id,scope_type="Project")
        return ()
    if scope_type != "Company" or project is not None:return ()
    rows=frappe.db.sql("SELECT action,subject_id FROM `tabCipher Approval Packet` WHERE name=%s AND company=%s AND scope_type='Company' AND (project IS NULL OR project='')",(packet_id,company))
    if not rows or rows[0][0]!="award.project.create.v1":return ()
    _scope(company,None,"Company")
    packet=_load(company,None,packet_id,scope_type="Company")
    return domain_approvals.participant_people(packet.action,company,packet.subject_id,scope_type="Company")


def decide_packet(company, project, packet_id, manifest_hash, decision, operation_id, reason="", *, scope_type="Project"):
    if decision not in {"Grant", "Reject"}:
        raise DomainError("invalid_decision", "Choose Grant or Reject.", 422)
    reason = text(reason, "Review reason", 2000, required=False)
    participants=_award_packet_people(company,project,packet_id,scope_type)
    def effect(actor, record):
        packet = _load(company, project, packet_id, True, scope_type=scope_type)
        domain_approvals.require_participants(packet.action,company,packet.subject_id,participants,scope_type=scope_type)
        _check_hash(packet, manifest_hash)
        _human_review(actor)
        if packet.action != ACTION:
            domain_approvals.authorize(packet, actor, phase="review", lock=True)
        if actor.person_id == packet.requester_person:
            raise DomainError("independent_review_required", "Another person must review your request, including when you use an alias account.", 403)
        state, _ = _state(packet, record, True, actor=actor)
        if state != "Pending":
            raise DomainError("approval_not_pending", "This packet is no longer awaiting review.", 409, {"state": state})
        _decision(actor, packet, decision, reason)
        _event(actor, packet, operation_id, "approval.decided", {"decision": decision, "manifest_hash": manifest_hash, "reason": reason})
        return {"packet": present(packet, record, actor, True)}
    return _command(scope_type=scope_type, company=company, project=project, operation_id=operation_id, command="approval.decide", payload={"packet_id": packet_id,"manifest_hash": manifest_hash,"decision": decision,"reason": reason}, ability="approval.decide", effect=effect, participant_people=participants)


def withdraw_packet(company, project, packet_id, manifest_hash, operation_id, reason="", *, scope_type="Project"):
    reason = text(reason, "Withdrawal reason", 2000, required=False)
    participants=_award_packet_people(company,project,packet_id,scope_type)
    def effect(actor, record):
        packet = _load(company, project, packet_id, True, scope_type=scope_type)
        domain_approvals.require_participants(packet.action,company,packet.subject_id,participants,scope_type=scope_type)
        _check_hash(packet, manifest_hash)
        if packet.action != ACTION:
            domain_approvals.authorize(packet, actor, lock=True)
        if actor.person_id != packet.requester_person:
            raise DomainError("requester_required", "Only the requester may withdraw this packet.", 403)
        state, _ = _state(packet, record, True, actor=actor)
        if state not in {"Pending", "Granted"}:
            raise DomainError("approval_not_withdrawable", "This packet cannot be withdrawn.", 409)
        _decision(actor, packet, "Withdraw", reason)
        _event(actor, packet, operation_id, "approval.withdrawn", {"reason": reason})
        return {"packet": present(packet, record, actor, True)}
    return _command(scope_type=scope_type, company=company, project=project, operation_id=operation_id, command="approval.withdraw", payload={"packet_id": packet_id,"manifest_hash": manifest_hash,"reason": reason}, ability="approval.request", effect=effect, participant_people=participants)


@contextmanager
def _exact_effect(packet, manifest):
    token = _effect.set({"packet": packet.name, "scope_type": packet.scope_type or "Project", "action": packet.action, "company": packet.company, "project": packet.project or None, "subject_id": packet.subject_id, "source_version": packet.source_version, "status": manifest.get("requested_status"), "manifest_hash": packet.manifest_hash})
    try:
        yield
    finally:
        _effect.reset(token)


def require_project_status_grant(doc, old):
    grant = _effect.get()
    if not grant or grant["action"] != ACTION or grant["project"] != doc.name or grant["source_version"] != version_of(old) or grant["status"] != doc.status:
        raise DomainError("approval_required", "Request and independently approve this exact Project status change before executing it.", 403)


def execute_packet(company, project, packet_id, manifest_hash, operation_id, *, scope_type="Project"):
    _scope(company, project, scope_type)
    snapshot = _load(company, project, packet_id, scope_type=scope_type)
    decisions_before_lock = _decisions(snapshot)
    award_people=domain_approvals.participant_people(snapshot.action,company,snapshot.subject_id,scope_type=scope_type)
    if snapshot.action == "award.project.create.v1":
        reviewers = {decisions_before_lock[-1].actor_person} if decisions_before_lock and decisions_before_lock[-1].decision == "Grant" else set()
    else:
        reviewers = {d.actor_person for d in decisions_before_lock if d.decision == "Grant"}
    participants = tuple(sorted(set(award_people) | {snapshot.requester_person} | reviewers))
    def effect(actor, record):
        packet = _load(company, project, packet_id, True, scope_type=scope_type)
        if packet.action == "award.project.create.v1":
            domain_approvals.spec_for(packet.action, scope_type)
            domain_approvals.require_participants(packet.action,company,packet.subject_id,award_people,scope_type=scope_type)
            _check_hash(packet,manifest_hash)
            from cipher_aec.awards.preallocation import stage
            allocation = stage(packet,actor,operation_id,participants)
        else:
            allocation = nullcontext()
        with allocation:
            write_ability = "project.write" if packet.action == ACTION else domain_approvals.ACTIONS[packet.action].write_ability
            _scope(company, project, scope_type, ability=write_ability, actor=actor, lock=True)
            if packet.action != ACTION:
                domain_approvals.authorize(packet, actor, phase="execute", lock=True)
                if scope_type == "Project" and record.status in {"Completed", "Cancelled"}:
                    raise DomainError("project_closed", "This Project is closed for new effects.", 409)
            _check_hash(packet, manifest_hash)
            state, decisions = _state(packet, record, True, actor=actor)
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
                    _scope(company, project, scope_type, ability="approval.decide", actor=reviewer, lock=True)
                    if packet.action != ACTION:
                        domain_approvals.authorize(packet, reviewer, phase="review", lock=True)
                    break
                except DomainError:
                    reviewer = None
            kinds = frappe.db.sql("SELECT identity_kind FROM `tabCipher Person` WHERE name=%s FOR UPDATE", (decisions[-1].actor_person,))
            if reviewer is None or not kinds or kinds[0][0] != "Human":
                raise DomainError("reviewer_authority_revoked", "The reviewer's authority changed. Obtain a fresh review.", 403)
            manifest = json.loads(packet.manifest_json)
            if packet.action == ACTION:
                # Reconstruct transition eligibility with current locked masters.
                _manifest(record, manifest["requested_status"], _policy(True), actor, _tasks(project, True))
                with _exact_effect(packet, manifest):
                    record.status = manifest["requested_status"]
                    record.save(ignore_permissions=True)
                if record.status != manifest["requested_status"] or record.percent_complete_method != manifest["native_completion"]["percent_complete_method"] or float(record.percent_complete or 0) != float(manifest["native_completion"]["percent_complete"]) or _tasks(project, True) != manifest["tasks"]:
                    raise DomainError("unexpected_native_effect", "Native Project validation changed the approved outcome. No change was saved.", 409)
                result = {"project": present_project(record, actor)}
            else:
                _, _, apply_effect = domain_approvals.callbacks(packet.action, scope_type)
                with _exact_effect(packet, manifest):
                    result = apply_effect(actor=actor, company=company, project=project, manifest=manifest["domain"],
                        packet_id=packet.name, decision_id=decisions[-1].name, operation_id=operation_id, **domain_approvals.scope_kwargs(packet.action, scope_type))
                if not isinstance(result, dict):
                    raise RuntimeError("Registered approval effect must return an object")
            consumed = frappe.get_doc({"doctype": "Cipher Approval Consumption", "company": company, "project": project,
                "scope_type": scope_type, "packet": packet.name, "decision": decisions[-1].name, "actor_person": actor.person_id,
                "operation_id": operation_id, "result_hash": digest(result), "consumed_at": utc_timestamp()})
            from cipher_aec.awards.runtime import quiet_award_write
            quiet_award_write(consumed)
            consumed.insert(ignore_permissions=True)
            _event(actor, packet, operation_id, "approval.executed", {"manifest_hash": packet.manifest_hash, "action": packet.action, "result_hash": digest(result), "status": record.status if scope_type == "Project" else None, "task_changes": []})
            return {"packet": present(packet, record, actor, True), "effect": result}
    return _command(scope_type=scope_type, company=company, project=project, operation_id=operation_id, command="approval.execute", payload={"packet_id": packet_id,"manifest_hash": manifest_hash}, ability="approval.execute", effect=effect, participant_people=participants)


def prevent_unsupported_financial_transition(doc, method=None):
    if doc.doctype == "Sales Order":
        from cipher_aec.awards.effect import native_order_active, validate_native_order
        if native_order_active():
            return validate_native_order(doc, method)
    """No financial/admission writer is qualified in the current release.

    This includes drafts and deletion, closing the initial-admission scan race.
    Opportunity/Quotation draft composition is a separate guarded COM domain.
    Host administration/raw SQL is outside application concurrency guarantees.
    Future qualified writers must use their exact reviewed server effect context
    and acquire the same declared admission aggregate lock before any write.
    """
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return
    raise DomainError("financial_action_unqualified", "This native financial or obligation writer is not qualified in this release.", 403)


def require_approval_effect(*, action, subject_id, packet_id, scope_type="Project"):
    grant = _effect.get()
    if not grant or grant["action"] != action or grant["subject_id"] != subject_id or grant["packet"] != packet_id or grant["scope_type"] != scope_type:
        raise DomainError("approval_required", "This exact registered action requires its independently granted packet.", 403)
    return dict(grant)


def request_action(company, project, action, subject_id, expected_version, operation_id, *, scope_type="Project"):
    action = text(action, "Approval action", 100)
    domain_approvals.definition(action, scope_type)
    subject_id = text(subject_id, "Approval subject", 140)
    source_version = parse_expected_version(expected_version)
    spec = domain_approvals.ACTIONS[action]
    participants = domain_approvals.participant_people(action, company, subject_id, scope_type=scope_type)
    def effect(actor, record):
        domain_approvals.require_participants(action, company, subject_id, participants, scope_type=scope_type)
        if scope_type == "Project" and record.status in {"Completed", "Cancelled"}:
            raise DomainError("project_closed", "This Project is closed for new approval requests.", 409)
        builder, authorize_subject, _ = domain_approvals.callbacks(action, scope_type)
        authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id, phase="request", lock=True, **domain_approvals.scope_kwargs(action, scope_type))
        domain = builder(actor=actor, company=company, project=project, subject_id=subject_id, expected_version=source_version, lock=True, **domain_approvals.scope_kwargs(action, scope_type))
        if set(domain) != {"subject", "sources", "effect", "summary"} or domain["subject"]["doctype"] != spec.subject_type or domain["subject"]["name"] != subject_id:
            raise RuntimeError("Registered action returned an invalid subject/manifest")
        policy = _policy(True, action, scope_type)
        manifest = {"action": action, "action_version": 1, "company": company, "project": project,
            "source_version": source_version, "requester_person": actor.person_id, "policy_revision": policy.name,
            "policy_hash": digest(json.loads(policy.definition_json)), "domain": domain}
        if scope_type == "Company":
            manifest["scope_type"] = "Company"
        presentation = domain_approvals.new_presentation(action=action, actor=actor, company=company,
            project=project, subject_id=subject_id, scope_type=scope_type, lock=True)
        if presentation is not None:
            manifest["presentation"] = presentation
        now = datetime.now(timezone.utc)
        packet = frappe.get_doc({"doctype": "Cipher Approval Packet", "scope_type": scope_type, "company": company, "project": project,
            "action": action, "subject_type": spec.subject_type, "subject_id": subject_id, "requester_person": actor.person_id,
            "policy_revision": policy.name, "manifest_json": canonical_json(manifest), "manifest_hash": digest(manifest),
            "source_version": source_version, "created_at": utc_timestamp(now), "expires_at": utc_timestamp(now+timedelta(seconds=policy.lifetime_seconds))})
        packet.insert(ignore_permissions=True)
        _event(actor, packet, operation_id, "approval.requested", {"action": action, "manifest_hash": packet.manifest_hash, "subject_id": subject_id})
        return {"packet": present(packet, record, actor, True)}
    return _command(scope_type=scope_type, company=company, project=project, operation_id=operation_id, command="approval.request_action", payload={"action": action, "subject_id": subject_id, "expected_version": source_version}, ability="approval.request", effect=effect, participant_people=participants)


def authorize_receipt(actor, company, project, result, *, scope_type="Project"):
    identifier = result.get("packet", {}).get("id")
    if not identifier:
        return
    actor = current_actor(actor.user, lock=True)
    _scope(company, project, scope_type, actor=actor, lock=True)
    packet = _load(company, project, identifier, True, scope_type=scope_type)
    if packet.action != ACTION:
        domain_approvals.authorize(packet, actor, phase="receipt", lock=True)
        if packet.action in {"document.issue.v1","document.library.adopt.v1","document.transmit.v1","document.clause.apply.v1","document.lifecycle.v1"} and "effect" in result:
            from cipher_aec.document_control.service import authorize_receipt as authorize_documentary
            authorize_documentary(actor,company,project,result["effect"],lock=True)
        if packet.action in {"engineering.basis.check.v1", "engineering.calculation.check.v1", "engineering.deliverable.check.v1"} and "effect" in result:
            from cipher_aec.engineering_packages.service import authorize_receipt as authorize_package
            authorize_package(actor,company,project,result["effect"],lock=True)
        if packet.action in {"engineering.rfi.authorize.v1", "engineering.submittal.authorize.v1", "engineering.distribute.v1"} and "effect" in result:
            from cipher_aec.engineering.service import authorize_receipt as authorize_engineering
            authorize_engineering(actor,company,project,result["effect"],lock=True)
