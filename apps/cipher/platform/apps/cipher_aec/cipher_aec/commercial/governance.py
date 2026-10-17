"""Exact reviewed prepared-PDF consumption; native Quotation remains a draft."""
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company
from . import service, native, sources
from .outputs import read_output

ACTION = "proposal.issue.v1"


def _scope(scope_type, project):
    if scope_type != "Company" or project is not None:
        raise DomainError("not_found", "This proposal issue is not available.", 404)


def authorize_subject(*, actor, company, project, subject_id, phase, lock=False, manifest=None, scope_type):
    _scope(scope_type, project)
    service._actor(company, actor, lock=lock)
    if phase in ("request", "execute"):
        require_company(company, ability="commercial.write", actor=actor, lock=lock)
    revision = service._read("revision", subject_id, company, actor, lock=lock)[1]
    prepared = read_output(company, subject_id, actor, lock=lock)
    if manifest is not None:
        effect = manifest.get("effect", {})
        if effect.get("action") != ACTION or effect.get("revision_id") != subject_id or effect.get("prepared_output") != prepared or effect.get("proposal_revision_digest") != digest(revision):
            raise DomainError("approval_integrity", "The original reviewed proposal output cannot be verified.", 409)
    if phase == "review" and revision["author_person"] == actor.person_id:
        raise DomainError("independent_proposal_required", "The proposal author cannot independently approve issue through another identity.", 403)
    return revision


def approval_manifest(*, actor, company, project, subject_id, expected_version, lock=False, scope_type):
    _scope(scope_type, project)
    revision = authorize_subject(actor=actor, company=company, project=None, subject_id=subject_id, phase="read", lock=lock, scope_type=scope_type)
    proposal = service._read("proposal", revision["proposal"], company, actor, lock=lock)[1]
    prepared = read_output(company, subject_id, actor, lock=lock)
    if expected_version != prepared["review_version"] or proposal["current_revision"] != subject_id:
        raise DomainError("stale_proposal_issue", "Request issue for the exact prepared current proposal revision.", 412)
    actual = native.persisted(proposal["quotation"],lock=lock)
    if actual["docstatus"] != 0 or digest(actual) != revision["native_fingerprint"]:
        raise DomainError("stale_native_source", "The current native quotation differs from the prepared draft snapshot.", 412)
    if frappe.db.sql("SELECT name FROM `tabCipher Proposal Issue` WHERE proposal_revision=%s LIMIT 1" + (" FOR UPDATE" if lock else ""), (subject_id,)):
        raise DomainError("proposal_already_issued", "This exact proposal revision already has an immutable issue.", 409)
    return {"subject":{"doctype":"Cipher Proposal Revision","name":subject_id,"label":"Proposal revision " + str(revision["revision_number"])},
        "sources":[row["citation"] for row in revision.get("source_citations", [])],
        "effect":{"action":ACTION,"revision_id":subject_id,"proposal_revision_digest":digest(revision),
            "native_fingerprint":revision["native_fingerprint"],"accepted_estimate":revision["accepted_estimate"],"prepared_output":prepared},
        "summary":{"currency":revision["composition"]["currency"],"total":revision["pricing"]["total"],
            "recipient_count":len(prepared["binding"]["recipients"]),"native_lifecycle":"draft-snapshot",
            "distribution":"not-sent","independent_issue_required":True}}


def apply_issue(*, actor, company, project, manifest, packet_id, decision_id, operation_id, scope_type):
    _scope(scope_type, project)
    from cipher_aec.governance.approvals import require_approval_effect
    subject_id = manifest["effect"]["revision_id"]
    require_approval_effect(action=ACTION,subject_id=subject_id,packet_id=packet_id,scope_type="Company")
    revision = authorize_subject(actor=actor,company=company,project=None,subject_id=subject_id,phase="execute",lock=True,manifest=manifest,scope_type=scope_type)
    prepared = manifest["effect"]["prepared_output"]
    current = approval_manifest(actor=actor,company=company,project=None,subject_id=subject_id,expected_version=prepared["review_version"],lock=True,scope_type=scope_type)
    if current != manifest:
        raise DomainError("stale_proposal_issue", "The approved proposal inputs changed. Request fresh independent review.", 412)
    decision = frappe.get_doc("Cipher Approval Decision",decision_id,for_update=True)
    if decision.packet != packet_id or decision.decision != "Grant" or decision.actor_person == revision["author_person"]:
        raise DomainError("independent_proposal_required", "Issue requires an independent canonical person's exact grant.", 403)
    previous = frappe.db.sql("SELECT name,revision_number FROM `tabCipher Proposal Issue` WHERE proposal=%s ORDER BY revision_number DESC LIMIT 1 FOR UPDATE",(revision["proposal"],),as_dict=True)
    from .issue_records import facts
    value = {"id":str(uuid4()),"company":company,"author_person":actor.person_id,
        "revision_number":previous[0].revision_number + 1 if previous else 1,
        "predecessor":previous[0].name if previous else None,"packet_id":packet_id,"decision_id":decision_id,
        "approved_by_person":decision.actor_person,"manifest":manifest,"manifest_digest":digest(manifest),**facts(revision,prepared)}
    service._write("issue",value)
    service._event(actor,company,operation_id,"commercial.proposal.issued","issue",value)
    return {"issue":value}
