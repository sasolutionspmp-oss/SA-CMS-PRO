"""Literal, scope-qualified domain adapters into the single approval engine."""
from dataclasses import dataclass
import json
from cipher_aec.api.errors import DomainError

@dataclass(frozen=True)
class Action:
    name: str
    subject_type: str
    label: str
    read_ability: str
    write_ability: str
    policy_id: str
    scopes: tuple = ("Project",)
    scoped_callback: bool = False
    enabled: bool = True

ACTIONS = {
    **{name: Action(name,doctype,label,"document.control.read",ability,policy) for name,doctype,label,ability,policy in (
      ("document.lifecycle.v1","Cipher Document Lifecycle Request","Independent issued-document lifecycle","document.issue","CIPHER-DOCUMENT-LIFECYCLE-POLICY-V1"),
      ("document.clause.apply.v1","Cipher Redline Revision","Independent exact documentary clause relationship","document.adopt","CIPHER-DOCUMENT-CLAUSE-APPLY-POLICY-V1"),
      ("document.issue.v1","Cipher Document Issue Set","Independent exact documentary issue","document.issue","CIPHER-DOCUMENT-ISSUE-POLICY-V1"),
      ("document.library.adopt.v1","Cipher Adoption Request","Independent exact library adoption","document.adopt","CIPHER-LIBRARY-ADOPTION-POLICY-V1"),
      ("document.transmit.v1","Cipher Transmittal","Independent exact internal documentary distribution","document.distribute","CIPHER-DOCUMENT-TRANSMIT-POLICY-V1"))},
    'engineering.basis.check.v1': Action('engineering.basis.check.v1', 'Cipher Design Basis Revision', 'Independent exact basis checking', "engineering.package.read", "engineering.package.write", 'CIPHER-ENGINEERING-BASIS-CHECK-POLICY-V1'),
    'engineering.calculation.check.v1': Action('engineering.calculation.check.v1', 'Cipher Calculation Revision', 'Independent exact calculation checking', "engineering.package.read", "engineering.package.write", 'CIPHER-ENGINEERING-CALCULATION-CHECK-POLICY-V1'),
    'engineering.deliverable.check.v1': Action('engineering.deliverable.check.v1', 'Cipher Deliverable Revision', 'Independent exact deliverable checking', "engineering.package.read", "engineering.package.write", 'CIPHER-ENGINEERING-DELIVERABLE-CHECK-POLICY-V1'),

    "engineering.rfi.authorize.v1": Action("engineering.rfi.authorize.v1", "Cipher RFI Response Revision", "Independent official RFI response", "engineering.read", "engineering.write", "CIPHER-ENGINEERING-RFI-POLICY-V1"),
    "engineering.submittal.authorize.v1": Action("engineering.submittal.authorize.v1", "Cipher Submittal Disposition Revision", "Independent official submittal disposition", "engineering.read", "engineering.write", "CIPHER-ENGINEERING-SUBMITTAL-POLICY-V1"),
    "engineering.distribute.v1": Action("engineering.distribute.v1", "Cipher Engineering Transmittal", "Independent internal engineering distribution", "engineering.read", "engineering.distribute", "CIPHER-ENGINEERING-DISTRIBUTION-POLICY-V1"),
    "award.project.create.v1": Action("award.project.create.v1", "Cipher Award Handoff Revision", "Independent full pursuit award and initial Project team", "commercial.read", "commercial.award", "CIPHER-AWARD-PROJECT-CREATE-POLICY-V1", ("Company",), True, False),
    "calibration.verify.v1": Action("calibration.verify.v1", "Cipher Calibration", "Synthetic independent calibration verification", "estimate.read", "estimate.write", "CIPHER-CALIBRATION-VERIFY-POLICY-V1", ("Project", "Company"), True),
    "contract.baseline.activate.v1": Action("contract.baseline.activate.v1", "Cipher Construction Contract", "Synthetic independent construction baseline acceptance", "contract.read", "contract.write", "CIPHER-CONTRACT-BASELINE-POLICY-V1"),
    "estimate.accept.v1": Action("estimate.accept.v1", "Cipher Estimate Revision", "Independent estimate baseline acceptance", "estimate.read", "estimate.write", "CIPHER-ESTIMATE-ACCEPT-POLICY-V1", ("Project", "Company"), True),
    "proposal.issue.v1": Action("proposal.issue.v1", "Cipher Proposal Revision", "Independent proposal issue approval", "commercial.read", "commercial.write", "CIPHER-PROPOSAL-ISSUE-POLICY-V1", ("Company",), True),
    "proposal.distribute.v1": Action("proposal.distribute.v1", "Cipher Distribution Instruction", "Independent synthetic proposal distribution", "commercial.read", "commercial.distribute", "CIPHER-PROPOSAL-DISTRIBUTE-POLICY-V1", ("Company",), True),
}

def spec_for(action, scope_type="Project"):
    spec = ACTIONS.get(action)
    if not spec or not spec.enabled or scope_type not in spec.scopes:
        raise DomainError("approval_action_unqualified", "This approval action is not registered in this scope.", 403)
    return spec

def definition(action, scope_type="Project"):
    spec = spec_for(action, scope_type)
    value = {"action": action, "action_version": 1, "request_ability": "approval.request", "review_ability": "approval.decide",
        "execute_ability": "approval.execute", "subject_type": spec.subject_type, "read_ability": spec.read_ability,
        "write_ability": spec.write_ability, "independent_person": True, "executor_must_be_requester": True,
        "human_review": True, "synthetic": True}
    if scope_type == "Company":
        value["scope_type"] = "Company"
    return value

def callbacks(action, scope_type="Project"):
    spec_for(action, scope_type)
    if action in {"document.issue.v1","document.library.adopt.v1","document.transmit.v1","document.clause.apply.v1","document.lifecycle.v1"}:
        from cipher_aec.document_control.governance import CALLBACKS
        return CALLBACKS[action]
    if action in {"engineering.basis.check.v1", "engineering.calculation.check.v1", "engineering.deliverable.check.v1"}:
        from cipher_aec.engineering_packages.governance import CALLBACKS
        return CALLBACKS[action]
    if action in {"engineering.rfi.authorize.v1", "engineering.submittal.authorize.v1", "engineering.distribute.v1"}:
        from cipher_aec.engineering.governance import CALLBACKS
        return CALLBACKS[action]
    if action == "award.project.create.v1":
        from cipher_aec.awards.governance import approval_manifest, authorize_subject, apply_award
        return approval_manifest, authorize_subject, apply_award
    if action == "calibration.verify.v1":
        from cipher_aec.takeoff.governance import approval_manifest, authorize_subject, apply_verification
        return approval_manifest, authorize_subject, apply_verification
    if action == "contract.baseline.activate.v1":
        from cipher_aec.construction_finance.governance import approval_manifest, authorize_subject, apply_activation
        return approval_manifest, authorize_subject, apply_activation
    if action == "estimate.accept.v1":
        from cipher_aec.estimating.governance import approval_manifest, authorize_subject, apply_acceptance
        return approval_manifest, authorize_subject, apply_acceptance
    if action == "proposal.issue.v1":
        from cipher_aec.commercial.governance import approval_manifest, authorize_subject, apply_issue
        return approval_manifest, authorize_subject, apply_issue
    if action == "proposal.distribute.v1":
        from cipher_aec.integrations.distribution_governance import approval_manifest, authorize_subject, apply_dispatch
        return approval_manifest, authorize_subject, apply_dispatch
    raise DomainError("approval_action_unqualified", "This approval action is not registered.", 403)

def scope_kwargs(action, scope_type):
    return {"scope_type": scope_type} if spec_for(action, scope_type).scoped_callback else {}

def authorize(packet, actor, phase="read", lock=False):
    scope_type = packet.scope_type or "Project"
    outer = json.loads(packet.manifest_json)
    _, authorize_subject, _ = callbacks(packet.action, scope_type)
    return authorize_subject(actor=actor, company=packet.company, project=packet.project or None,
        subject_id=packet.subject_id, phase=phase, lock=lock, manifest=outer["domain"], **scope_kwargs(packet.action, scope_type))

def current_manifest(packet, actor, lock=False):
    scope_type = packet.scope_type or "Project"
    outer = json.loads(packet.manifest_json)
    builder, _, _ = callbacks(packet.action, scope_type)
    return builder(actor=actor, company=packet.company, project=packet.project or None,
        subject_id=packet.subject_id, expected_version=outer["source_version"], lock=lock, **scope_kwargs(packet.action, scope_type))

def new_presentation(*, action, actor, company, project, subject_id, scope_type, lock=False):
    """Server facts for a NEW packet only; domain/grant equality stays unchanged."""
    spec = spec_for(action, scope_type)
    if action != "estimate.accept.v1":
        return None
    from cipher_aec.estimating.governance import approval_presentation
    facts = approval_presentation(actor=actor, company=company, project=project,
        subject_id=subject_id, scope_type=scope_type, lock=lock)
    if not isinstance(facts.get("estimate_title"), str) or not facts["estimate_title"].strip() or type(facts.get("revision_number")) is not int or facts["revision_number"] < 1:
        raise RuntimeError("Registered estimate presentation returned invalid facts")
    return {"schema": "cipher.approval.presentation.v1",
        "subject": {"doctype": spec.subject_type, "name": subject_id},
        "subject_label": f"{facts['estimate_title']} · Revision {facts['revision_number']}"}

def subject_label(manifest):
    """Old packets retain their original domain label without a backfill."""
    subject = manifest["domain"]["subject"]
    presentation = manifest.get("presentation")
    if presentation is None:
        return subject["label"]
    if (manifest["action"] != "estimate.accept.v1" or
        presentation.get("schema") != "cipher.approval.presentation.v1" or
        presentation.get("subject") != {"doctype": subject["doctype"], "name": subject["name"]} or
        not isinstance(presentation.get("subject_label"), str) or not presentation["subject_label"].strip()):
        raise RuntimeError("Stored approval presentation does not match its exact subject")
    return presentation["subject_label"]

def request_action(company, project, action, subject_id, expected_version, operation_id, *, scope_type="Project"):
    from .approvals import request_action as request
    return request(company, project, action, subject_id, expected_version, operation_id, scope_type=scope_type)


def participant_people(action, company, subject_id, *, scope_type="Project", lock=False):
    """Literal immutable metadata discovery, never source/delegation authority."""
    if action == "document.transmit.v1":
        spec_for(action,scope_type)
        from cipher_aec.document_control.governance import participants
        return participants(action,company,subject_id,lock=lock)
    if action == "engineering.distribute.v1":
        spec_for(action,scope_type)
        from cipher_aec.engineering.governance import participants
        return participants(action,company,subject_id,lock=lock)
    if action != "award.project.create.v1":return ()
    spec_for(action, scope_type)
    from cipher_aec.awards.service import participant_people as discover
    return discover(company,subject_id,lock=lock)


def require_participants(action,company,subject_id,known,*,scope_type="Project"):
    if action == "document.transmit.v1" and tuple(sorted(set(known))) != participant_people(action,company,subject_id,scope_type=scope_type,lock=True):
        raise DomainError("document_participants_changed","The original internal documentary recipient plan changed.",409)
    if action == "engineering.distribute.v1" and tuple(sorted(set(known))) != participant_people(action,company,subject_id,scope_type=scope_type,lock=True):
        raise DomainError("engineering_participants_changed", "The exact internal recipient plan changed.", 409)
    if action == "award.project.create.v1" and tuple(sorted(set(known))) != participant_people(action,company,subject_id,scope_type=scope_type,lock=True):
        raise DomainError("award_participants_changed", "The exact canonical participant plan changed. Retry after reviewing it.", 409)
