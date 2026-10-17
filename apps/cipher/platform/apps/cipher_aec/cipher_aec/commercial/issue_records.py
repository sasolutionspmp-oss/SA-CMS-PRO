"""Issued-record invariants enforce the exact independent approval effect."""
import json
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.approvals import require_approval_effect
from . import contracts


def facts(revision, prepared):
    native_rows = {row["cipher_line_id"]:row for row in revision["native"]["items"]}
    selected = [{"line":line,"unit":revision["units"][line["unit_id"]],"native_item":native_rows[line["id"]]} for line in revision["pricing"]["lines"] if line["selected"]]
    return {"proposal":revision["proposal"],"proposal_revision":revision["id"],"proposal_revision_digest":digest(revision),
        "output_revision":prepared["revision_id"],"prepared_output":prepared,"accepted_estimate":revision["accepted_estimate"],
        "selected_lines":selected,"composition":revision["composition"],"pricing":revision["pricing"],"units":revision["units"],
        "native_snapshot":revision["native"],"native_fingerprint":revision["native_fingerprint"],
        "native_lifecycle":"draft-snapshot","status":"issued","distribution":"not-sent"}


def validate_issue(doc, value, actor):
    from . import governance, service
    from .outputs import read_output
    expected_keys = {"id","company","author_person","proposal","proposal_revision","proposal_revision_digest","revision_number",
        "predecessor","packet_id","decision_id","approved_by_person","output_revision","prepared_output","accepted_estimate",
        "selected_lines","composition","pricing","units","native_snapshot","native_fingerprint","native_lifecycle","status",
        "distribution","manifest","manifest_digest"}
    contracts.keys(value, expected_keys, expected_keys)
    require_approval_effect(action=governance.ACTION,subject_id=value["proposal_revision"],packet_id=value["packet_id"],scope_type="Company")
    if not doc.is_new():
        raise DomainError("immutable_proposal_issue","Issued evidence cannot be rewritten.",409)
    # This controller runs inside the registered effect, after its complete
    # source UOM/currency/native union. Every nested current check reacquires it.
    revision = service._read("revision",value["proposal_revision"],doc.company,actor,lock=True)[1]
    prepared = read_output(doc.company,revision["id"],actor,lock=True)
    expected = governance.approval_manifest(actor=actor,company=doc.company,project=None,subject_id=revision["id"],
        expected_version=prepared["review_version"],lock=True,scope_type="Company")
    if value["manifest"] != expected or value["manifest_digest"] != digest(expected) or any(value[key]!=item for key,item in facts(revision,prepared).items()):
        raise DomainError("issue_integrity","An issue must preserve its exact independently reviewed native draft, source baseline and canonical PDF.",409)
    packet = frappe.get_doc("Cipher Approval Packet",value["packet_id"],for_update=True)
    decision = frappe.get_doc("Cipher Approval Decision",value["decision_id"],for_update=True)
    outer = json.loads(packet.manifest_json)
    if (packet.scope_type != "Company" or packet.project or packet.company != doc.company or packet.action != governance.ACTION
            or packet.subject_type != "Cipher Proposal Revision" or packet.subject_id != revision["id"]
            or packet.requester_person != actor.person_id or outer.get("domain") != expected or digest(outer)!=packet.manifest_hash
            or decision.packet != packet.name or decision.manifest_hash != packet.manifest_hash or decision.decision != "Grant"
            or decision.actor_person != value["approved_by_person"] or decision.actor_person == revision["author_person"]):
        raise DomainError("independent_proposal_required","This issue requires its exact Company packet and independent canonical human's grant.",403)
    previous = frappe.db.sql("SELECT name,revision_number FROM `tabCipher Proposal Issue` WHERE proposal=%s ORDER BY revision_number DESC LIMIT 1 FOR UPDATE",(revision["proposal"],),as_dict=True)
    if value["predecessor"] != (previous[0].name if previous else None) or value["revision_number"] != (previous[0].revision_number+1 if previous else 1):
        raise DomainError("issue_integrity","Issue history must advance its immutable predecessor exactly once.",409)
