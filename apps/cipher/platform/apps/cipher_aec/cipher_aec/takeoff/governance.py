"""Static calibration verification adapter; governance owns the grant engine."""
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_project
from . import repository, service

ACTION = "calibration.verify.v1"


def authorize_subject(*, actor, company, project, subject_id, phase, lock=False, manifest=None):
    require_project(company, project, ability="estimate.read", actor=actor, lock=lock)
    if phase in {"request", "execute"}:
        require_project(company, project, ability="estimate.write", actor=actor, lock=lock)
    value = service._read("calibration", subject_id, company, project, actor, lock=lock,
                          new_use=phase in {"request", "review", "execute", "manifest"})
    if phase == "review" and actor.person_id == value["author_person"]:
        raise DomainError("independent_calibration_required", "A calibration author cannot independently verify their own work through another identity.", 403)
    if manifest is not None:
        # Old packets still require permission to the original exact byte source.
        if manifest.get("effect", {}).get("calibration_id") != value["id"]:
            raise DomainError("approval_integrity", "This calibration packet has a different subject.", 409)
        if manifest.get("effect", {}).get("calibration_digest") != digest(value):
            raise DomainError("approval_integrity", "The original calibration packet cannot be verified.", 409)
    return value


def approval_manifest(*, actor, company, project, subject_id, expected_version, lock=False):
    value = authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id, phase="manifest", lock=lock)
    if expected_version != digest(value):
        raise DomainError("stale_calibration", "Refresh the exact immutable calibration before requesting verification.", 412)
    if repository.verification(subject_id, lock=lock):
        raise DomainError("calibration_already_verified", "This exact calibration is already independently verified.", 409)
    return {"subject": {"doctype": "Cipher Calibration", "name": value["id"], "label": value["definition"]["title"]},
            "sources": [{**service.source_input(value), "document_id": value["source"]["document_id"],
                         "page_geometry_digest": digest(value["page_geometry"]), "head_policy": service.HEAD_POLICY}],
            "effect": {"action": ACTION, "calibration_id": value["id"], "calibration_digest": digest(value),
                       "author_person": value["author_person"], "verification": "independent-human-source-bound-v1"},
            "summary": {"definition": value["definition"], "page_geometry": value["page_geometry"],
                        "unit_manifest_digest": digest(value["unit_manifest"]), "calibration_status": "unverified"}}


def apply_verification(*, actor, company, project, manifest, packet_id, decision_id, operation_id):
    from cipher_aec.governance.approvals import require_approval_effect
    subject_id = manifest["effect"]["calibration_id"]
    require_approval_effect(action=ACTION, subject_id=subject_id, packet_id=packet_id)
    value = authorize_subject(actor=actor, company=company, project=project, subject_id=subject_id, phase="execute", lock=True, manifest=manifest)
    expected = approval_manifest(actor=actor, company=company, project=project, subject_id=subject_id, expected_version=digest(value), lock=True)
    if manifest != expected:
        raise DomainError("stale_calibration", "The approved calibration/source manifest changed.", 412)
    decision = frappe.get_doc("Cipher Approval Decision", decision_id, for_update=True)
    if decision.packet != packet_id or decision.decision != "Grant" or decision.actor_person == value["author_person"]:
        raise DomainError("independent_calibration_required", "The calibration author cannot verify their own calibration through another identity.", 403)
    verified = service._new(company, project, actor, record_id=str(uuid4()), status="verified", calibration_id=value["id"],
                            calibration_digest=digest(value), packet_id=packet_id, decision_id=decision_id,
                            verified_by_person=decision.actor_person, source=value["source"], page_geometry_digest=digest(value["page_geometry"]))
    repository.insert("verification", verified, calibration=subject_id, packet_id=packet_id, decision_id=decision_id,
                      verified_by_person=decision.actor_person)
    return {"verification": verified}
