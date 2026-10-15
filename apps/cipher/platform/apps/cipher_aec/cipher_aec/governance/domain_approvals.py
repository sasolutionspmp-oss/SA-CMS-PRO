"""Static adapters into the single canonical packet/decision/consumption engine.

Only the literal actions below are registered. Domain builders and effects are
server imports, never caller-selected dotted paths. No financial posting action
or Company approval action is registered here.
"""
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


ACTIONS = {
    "calibration.verify.v1": Action("calibration.verify.v1", "Cipher Calibration", "Synthetic independent calibration verification", "estimate.read", "estimate.write", "CIPHER-CALIBRATION-VERIFY-POLICY-V1"),
    "contract.baseline.activate.v1": Action("contract.baseline.activate.v1", "Cipher Construction Contract", "Synthetic independent construction baseline acceptance", "contract.read", "contract.write", "CIPHER-CONTRACT-BASELINE-POLICY-V1"),
}


def definition(action):
    spec = ACTIONS.get(action)
    if not spec:
        raise DomainError("approval_action_unqualified", "This approval action is not registered.", 403)
    return {"action": action, "action_version": 1, "request_ability": "approval.request", "review_ability": "approval.decide",
        "execute_ability": "approval.execute", "subject_type": spec.subject_type, "read_ability": spec.read_ability,
        "write_ability": spec.write_ability, "independent_person": True, "executor_must_be_requester": True,
        "human_review": True, "synthetic": True}


def callbacks(action):
    definition(action)
    if action == "calibration.verify.v1":
        from cipher_aec.takeoff.governance import approval_manifest, authorize_subject, apply_verification
        return approval_manifest, authorize_subject, apply_verification
    if action == "contract.baseline.activate.v1":
        from cipher_aec.construction_finance.governance import approval_manifest, authorize_subject, apply_activation
        return approval_manifest, authorize_subject, apply_activation
    raise DomainError("approval_action_unqualified", "This approval action is not registered.", 403)


def authorize(packet, actor, phase="read", lock=False):
    outer = json.loads(packet.manifest_json)
    _, authorize_subject, _ = callbacks(packet.action)
    return authorize_subject(actor=actor, company=packet.company, project=packet.project,
        subject_id=packet.subject_id, phase=phase, lock=lock, manifest=outer["domain"])


def current_manifest(packet, actor, lock=False):
    outer = json.loads(packet.manifest_json)
    builder, _, _ = callbacks(packet.action)
    return builder(actor=actor, company=packet.company, project=packet.project,
        subject_id=packet.subject_id, expected_version=outer["source_version"], lock=lock)


def request_action(company, project, action, subject_id, expected_version, operation_id):
    from .approvals import request_action as request
    return request(company, project, action, subject_id, expected_version, operation_id)
