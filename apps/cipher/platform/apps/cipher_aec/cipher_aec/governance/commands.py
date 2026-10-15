import json

import frappe

from cipher_aec.api.contracts import canonical_json, digest, operation_id as parse_operation_id, text
from cipher_aec.api.errors import DomainError
from .context import assert_synthetic_site, current_actor, require_project, trusted_write, require_effects_enabled


def run_command(*, company, project, operation_id, command, payload, ability, effect, guard=None, participant_people=()):
    """One Frappe request transaction: no commits or remote effects inside this service.

    Person locking serializes the UUID namespace across commands and projects. Project
    locking serializes source checks, task creation and the immutable history chain.
    Exceptions are rolled back by the transport or the surrounding worker transaction.
    """
    assert_synthetic_site()
    operation_id = parse_operation_id(operation_id)
    company, project = text(company, "Company"), text(project, "Project")
    actor = current_actor()
    require_project(company, project, ability=ability, actor=actor)
    # All participating people precede any identity/user or Project lock. This
    # prevents independent reviewer commands and grant consumption inverting
    # actor->Project ordering. Participant IDs are server-owned immutable data.
    people = sorted(set(participant_people) | {actor.person_id})
    placeholders = ",".join(["%s"] * len(people))
    frappe.db.sql("SELECT name FROM `tabCipher Person` WHERE name IN (" + placeholders + ") ORDER BY name FOR UPDATE", people)
    if participant_people:
        frappe.db.sql("SELECT b.name,b.user,u.name FROM `tabCipher Identity Binding` b JOIN `tabUser` u ON u.name=b.user WHERE b.person IN (" + placeholders + ") ORDER BY b.name FOR UPDATE", people)
    actor = current_actor(lock=True)
    locked_project = require_project(company, project, ability=ability, actor=actor, lock=True)
    if command.startswith("estimate."):
        require_project(company, project, ability="estimate.read", actor=actor, lock=True)
    if command.startswith("document."):
        # A write grant does not permit reading or replaying revoked source data.
        require_project(company, project, ability="document.read", actor=actor, lock=True)
    request_hash = digest({"command": command, "company": company, "project": project, "payload": payload})
    receipt_name = digest({"person": actor.person_id, "operation_id": operation_id})
    receipts = frappe.db.sql("SELECT request_hash,result_json,result_hash FROM `tabCipher Command Receipt` WHERE name=%s FOR UPDATE", (receipt_name,), as_dict=True)
    existing = receipts[0] if receipts else None
    if existing:
        if existing.request_hash != request_hash:
            raise DomainError("operation_conflict", "This operation ID already belongs to a different request.", 409)
        result = json.loads(existing.result_json)
        if digest(result) != existing.result_hash:
            raise DomainError("receipt_integrity", "The original command receipt cannot be verified.", 409)
        authorize_receipt(actor, command, company, project, result)
        result["operation"] = {"id": operation_id, "status": "succeeded", "replayed": True}
        return result
    # Access is current for replay; lifecycle/source checks govern only a new effect.
    require_effects_enabled()
    if ability in {"project.write", "task.create", "document.write", "estimate.write"} and locked_project.status in {"Completed", "Cancelled"}:
        raise DomainError("project_closed", "This project is closed for new work.", 409)
    savepoint = "cipher_command"
    frappe.db.savepoint(savepoint)
    try:
        with trusted_write():
            if guard is not None:
                guard(actor, locked_project)
            result = effect(actor, locked_project)
            if not isinstance(result, dict) or "operation" in result:
                raise RuntimeError("Domain commands must return a result object without operation metadata")
            record = frappe.get_doc({"doctype": "Cipher Command Receipt", "name": receipt_name,
                "person": actor.person_id, "operation_id": operation_id, "company": company,
                "project": project, "command": command, "request_hash": request_hash,
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
    row = frappe.db.get_value("Cipher Command Receipt", name, ["company", "project", "command", "result_json", "result_hash"], as_dict=True)
    if not row or row.company != company or row.project != project:
        raise DomainError("not_found", "This operation is not available.", 404)
    result = json.loads(row.result_json)
    if digest(result) != row.result_hash:
        raise DomainError("receipt_integrity", "The original command receipt cannot be verified.", 409)
    authorize_receipt(actor, row.command, company, project, result)
    return {**result, "operation": {"id": operation_id, "status": "succeeded", "replayed": True}}


def authorize_receipt(actor, command, company, project, result):
    """A receipt is not a permanent entitlement to private sources or model output."""
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
    elif command.startswith("approval."):
        require_project(company, project, actor=actor)
    elif command.startswith("ricky."):
        require_project(company, project, ability="ricky.run", actor=actor)
        identifier = result.get("id")
        if identifier:
            from cipher_aec.ricky.api import build_service
            build_service().get_run(identifier)
