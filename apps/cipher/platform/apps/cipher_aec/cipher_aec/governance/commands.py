import json
import uuid
from contextlib import nullcontext

import frappe

from cipher_aec.api.contracts import canonical_json, digest, operation_id as parse_operation_id, text
from cipher_aec.api.errors import DomainError
from .context import assert_synthetic_site, current_actor, require_project, require_company, trusted_write, require_effects_enabled


def run_command(*, company, project, operation_id, command, payload, ability, effect, guard=None, participant_people=()):
    return _run_scoped_command(company=company, project=project, scope_type="Project", operation_id=operation_id,
        command=command, payload=payload, ability=ability, effect=effect, guard=guard, participant_people=participant_people)


def run_company_command(*, company, operation_id, command, payload, ability, effect, guard=None, participant_people=()):
    return _run_scoped_command(company=company, project=None, scope_type="Company", operation_id=operation_id,
        command=command, payload=payload, ability=ability, effect=effect, guard=guard, participant_people=participant_people)


def _run_scoped_command(*, company, project, scope_type, operation_id, command, payload, ability, effect, guard, participant_people):
    """One Frappe request transaction: no commits or remote effects inside this service.

    Person locking serializes the UUID namespace across commands and projects. Project
    locking serializes source checks, task creation and the immutable history chain.
    Exceptions are rolled back by the transport or the surrounding worker transaction.
    """
    if scope_type == "Company":
        from cipher_aec.documents.provenance import logical_operation, logical_operation_stats
        # Helpers may share one logical lifetime, but a recursive command must
        # never acquire new locks or replace the outer command's savepoint.
        if logical_operation_stats() is not None:
            raise DomainError("nested_company_command", "Company commands cannot execute inside another Company command.", 409)
    assert_synthetic_site()
    operation_id = parse_operation_id(operation_id)
    company = text(company, "Company")
    if scope_type == "Project":
        project = text(project, "Project")
        authorize = lambda actor, lock=False: require_project(company, project, ability=ability, actor=actor, lock=lock)
    elif scope_type == "Company" and project is None:
        authorize = lambda actor, lock=False: require_company(company, ability=ability, actor=actor, lock=lock)
    else:
        raise DomainError("invalid_scope", "Declare an exact Company or Project scope.", 422)
    actor = current_actor()
    authorize(actor)
    # All participating people precede any identity/user or Project lock. This
    # prevents independent reviewer commands and grant consumption inverting
    # actor->Project ordering. Participant IDs are server-owned immutable data.
    people = sorted(set(participant_people) | {actor.person_id})
    placeholders = ",".join(["%s"] * len(people))
    frappe.db.sql("SELECT name FROM `tabCipher Person` WHERE name IN (" + placeholders + ") ORDER BY name FOR UPDATE", people)
    if participant_people:
        frappe.db.sql("SELECT b.name,b.user,u.name FROM `tabCipher Identity Binding` b JOIN `tabUser` u ON u.name=b.user WHERE b.person IN (" + placeholders + ") ORDER BY b.name FOR UPDATE", people)
    actor = current_actor(lock=True)
    locked_project = authorize(actor, lock=True)
    if scope_type == "Company":
        for prefix, read_ability in (("document.", "document.read"), ("estimate.", "estimate.read"), ("takeoff.", "estimate.read")):
            if command.startswith(prefix):
                require_company(company, ability=read_ability, actor=actor, lock=True)
    if scope_type == "Company" and command.startswith("commercial."):
        require_company(company, ability="commercial.read", actor=actor, lock=True)
    if scope_type == "Company" and command.startswith("distribution."):
        require_company(company, ability="commercial.read", actor=actor, lock=True)
        require_company(company, ability="document.read", actor=actor, lock=True)
    if scope_type == "Project" and command.startswith("contract."):
        require_project(company, project, ability="contract.read", actor=actor, lock=True)
    if scope_type == "Project" and command.startswith("takeoff."):
        require_project(company, project, ability="estimate.read", actor=actor, lock=True)
    if scope_type == "Project" and command.startswith("estimate."):
        require_project(company, project, ability="estimate.read", actor=actor, lock=True)
    if scope_type == "Project" and command.startswith("document."):
        # A write grant does not permit reading or replaying revoked source data.
        require_project(company, project, ability="document.read", actor=actor, lock=True)
    request_hash = digest({"command": command, "company": company, "project": project, "payload": payload})
    if scope_type == "Company":
        request_hash = digest({"scope_type": "Company", "command": command, "company": company, "project": None, "payload": payload})
    receipt_name = digest({"person": actor.person_id, "operation_id": operation_id})
    receipts = frappe.db.sql("SELECT request_hash,result_json,result_hash,scope_type,company,project FROM `tabCipher Command Receipt` WHERE name=%s FOR UPDATE", (receipt_name,), as_dict=True)
    existing = receipts[0] if receipts else None
    if existing:
        if existing.request_hash != request_hash or (existing.scope_type or "Project") != scope_type or existing.company != company or (existing.project or None) != (project or None):
            raise DomainError("operation_conflict", "This operation ID already belongs to a different request.", 409)
        result = json.loads(existing.result_json)
        if digest(result) != existing.result_hash:
            raise DomainError("receipt_integrity", "The original command receipt cannot be verified.", 409)
        with logical_operation(company, command, operation_id) if scope_type == "Company" else nullcontext():
            authorize_receipt(actor, command, company, project, result, scope_type=scope_type)
        result["operation"] = {"id": operation_id, "status": "succeeded", "replayed": True}
        return result
    # Access is current for replay; lifecycle/source checks govern only a new effect.
    require_effects_enabled()
    if scope_type == "Project" and ability in {"project.write", "task.create", "document.write", "estimate.write", "contract.write"} and locked_project.status in {"Completed", "Cancelled"}:
        raise DomainError("project_closed", "This project is closed for new work.", 409)
    savepoint = "cipher_company_" + uuid.uuid4().hex if scope_type == "Company" else "cipher_command"
    frappe.db.savepoint(savepoint)
    try:
        # The memo grants no source admission. Domain guards/controllers still
        # acquire their complete current source union. Exit before either
        # rollback branch so no success memo survives a failed local effect.
        with logical_operation(company, command, operation_id) if scope_type == "Company" else nullcontext(), trusted_write():
            if guard is not None:
                guard(actor, locked_project)
            result = effect(actor, locked_project)
            if not isinstance(result, dict) or "operation" in result:
                raise RuntimeError("Domain commands must return a result object without operation metadata")
            record = frappe.get_doc({"doctype": "Cipher Command Receipt", "name": receipt_name,
                "person": actor.person_id, "operation_id": operation_id, "company": company,
                "project": project, "scope_type": scope_type, "command": command, "request_hash": request_hash,
                "result_json": canonical_json(result), "result_hash": digest(result), "state": "Succeeded"})
            record.insert(ignore_permissions=True, set_name=receipt_name)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        # The database can have discarded the entire transaction on a deadlock;
        # rolling back to a now-missing savepoint would mask the real conflict.
        frappe.db.rollback()
        raise
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
    return {**result, "operation": {"id": operation_id, "status": "succeeded", "replayed": False}}


def read_operation(company, project, operation_id):
    actor = current_actor()
    require_project(company, project, actor=actor)
    operation_id = parse_operation_id(operation_id)
    name = digest({"person": actor.person_id, "operation_id": operation_id})
    row = frappe.db.get_value("Cipher Command Receipt", name, ["company", "project", "scope_type", "command", "result_json", "result_hash"], as_dict=True)
    if not row or row.company != company or row.project != project or (row.scope_type or "Project") != "Project":
        raise DomainError("not_found", "This operation is not available.", 404)
    result = json.loads(row.result_json)
    if digest(result) != row.result_hash:
        raise DomainError("receipt_integrity", "The original command receipt cannot be verified.", 409)
    authorize_receipt(actor, row.command, company, project, result)
    return {**result, "operation": {"id": operation_id, "status": "succeeded", "replayed": True}}


def authorize_receipt(actor, command, company, project, result, scope_type="Project"):
    """A receipt is not a permanent entitlement to private sources or model output."""
    if scope_type == "Company":
        require_company(company, actor=actor, lock=True)
        if command.startswith("commercial."):
            require_company(company, ability="commercial.read", actor=actor, lock=True)
            from cipher_aec.commercial.service import authorize_receipt as authorize_commercial
            authorize_commercial(actor, company, result, lock=True)
        elif command.startswith("document."):
            from cipher_aec.documents.service import authorize_company_receipt
            authorize_company_receipt(actor, company, result, lock=True)
        elif command.startswith("estimate."):
            from cipher_aec.estimating.service import authorize_receipt as authorize_estimate
            authorize_estimate(actor, company, None, result, scope_type="Company")
        elif command.startswith("takeoff."):
            from cipher_aec.takeoff.service import authorize_receipt as authorize_takeoff
            authorize_takeoff(actor, company, None, result, scope_type="Company")
        elif command.startswith("approval."):
            from cipher_aec.governance.approvals import authorize_receipt as authorize_approval
            authorize_approval(actor, company, None, result, scope_type="Company")
        elif command.startswith("distribution."):
            from cipher_aec.integrations.distribution import authorize_receipt as authorize_distribution
            authorize_distribution(actor, company, result, lock=True)
        return
    if command.startswith("document."):
        require_project(company, project, ability="document.read", actor=actor)
        from cipher_aec.documents.service import get_document
        document = result.get("document", {})
        identifier = document.get("id") if isinstance(document, dict) else document
        if identifier:
            get_document(company, identifier, actor=actor)
    elif command.startswith("estimate."):
        require_project(company, project, ability="estimate.read", actor=actor)
        from cipher_aec.estimating.service import authorize_receipt as authorize_estimate
        authorize_estimate(actor, company, project, result)
    elif command.startswith("takeoff."):
        require_project(company, project, ability="estimate.read", actor=actor, lock=True)
        from cipher_aec.takeoff.service import authorize_receipt as authorize_takeoff
        authorize_takeoff(actor, company, project, result)
    elif command.startswith("contract."):
        require_project(company, project, ability="contract.read", actor=actor, lock=True)
        from cipher_aec.construction_finance.service import authorize_receipt as authorize_contract
        authorize_contract(actor, company, project, result)
    elif command.startswith("approval."):
        require_project(company, project, actor=actor)
        from cipher_aec.governance.approvals import authorize_receipt as authorize_approval
        authorize_approval(actor, company, project, result)
    elif command.startswith("ricky."):
        require_project(company, project, ability="ricky.run", actor=actor)
        identifier = result.get("id")
        if identifier:
            from cipher_aec.ricky.api import build_service
            build_service().get_run(identifier)


def read_company_operation(company, operation_id):
    actor = current_actor()
    require_company(company, actor=actor)
    operation_id = parse_operation_id(operation_id)
    name = digest({"person": actor.person_id, "operation_id": operation_id})
    row = frappe.db.get_value("Cipher Command Receipt", name, ["company", "project", "scope_type", "command", "result_json", "result_hash"], as_dict=True)
    if not row or row.company != company or row.project or row.scope_type != "Company":
        raise DomainError("not_found", "This operation is not available.", 404)
    result = json.loads(row.result_json)
    if digest(result) != row.result_hash:
        raise DomainError("receipt_integrity", "The original command receipt cannot be verified.", 409)
    from cipher_aec.documents.provenance import logical_operation
    with logical_operation(company, row.command, operation_id):
        authorize_receipt(actor, row.command, company, None, result, scope_type="Company")
    return {**result, "operation": {"id": operation_id, "status": "succeeded", "replayed": True}}
