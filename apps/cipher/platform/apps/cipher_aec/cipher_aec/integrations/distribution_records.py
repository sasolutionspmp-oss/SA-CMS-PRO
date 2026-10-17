"""Exact server effect guards for immutable distribution records and intents."""
from contextlib import contextmanager
from contextvars import ContextVar
import json

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.controllers import ScopedImmutableDocument
from . import distribution as service, distribution_contracts as rules

_operation = ContextVar("cipher_distribution_operation_write", default=None)


@contextmanager
def operation_write(identifier, fence):
    token = _operation.set((identifier, fence))
    try:
        yield
    finally:
        _operation.reset(token)


class DistributionRecord(ScopedImmutableDocument):
    def validate(self):
        super().validate()
        kind = next(k for k, name in service.TYPES.items() if name == self.doctype)
        value = json.loads(self.data_json)
        if self.scope_type != "Company" or self.project or self.name != value["id"] or self.company != value["company"] or self.record_digest != digest(value) or service._writing.get() != (kind, value["id"], digest(value)):
            raise DomainError("distribution_effect_required", "Use the exact registered distribution command.", 403)
        if kind == "dispatch":
            from cipher_aec.governance.approvals import require_approval_effect
            require_approval_effect(action=rules.ACTION, subject_id=value["instruction_id"], packet_id=value["packet_id"], scope_type="Company")


def validate_operation(doc):
    """Company delivery writes require a grant or the exact claimed fence."""
    if doc.scope_type != "Company" or doc.project:
        raise DomainError("invalid_scope", "Proposal distribution is Company scoped.", 422)
    payload = json.loads(doc.payload_json)
    if digest(payload) != doc.payload_hash:
        raise DomainError("distribution_integrity", "The delivery payload cannot be verified.", 409)
    if doc.distribution_dispatch != payload["dispatch_id"] or doc.recipient_id != payload["recipient"]["id"]:
        raise DomainError("distribution_integrity", "The recipient index differs from its original payload.", 409)
    dispatch = service.raw("dispatch", payload["dispatch_id"], doc.company)
    instruction = service.raw("instruction", dispatch["instruction_id"], doc.company)
    if payload["instruction_digest"] != digest(instruction) or doc.logical_id != rules.logical_key(dispatch["id"], payload["recipient"]["id"]):
        raise DomainError("distribution_integrity", "The delivery identity differs from its exact dispatch.", 409)
    if doc.is_new():
        from cipher_aec.governance.approvals import require_approval_effect
        require_approval_effect(action=rules.ACTION, subject_id=instruction["id"], packet_id=dispatch["packet_id"], scope_type="Company")
        expected = {"schema": "cipher.distribution.payload.v1", "company": doc.company, "dispatch_id": dispatch["id"],
            "instruction_id": instruction["id"], "instruction_digest": digest(instruction), "issue_id": instruction["issue_id"],
            "recipient": payload["recipient"], "attachment": instruction["attachment"], "message": instruction["message"],
            "profile": instruction["profile"], "mode": "fixture"}
        if payload != expected or payload["recipient"] not in instruction["recipients"] or doc.actor_person != dispatch["requester_person"] or doc.actor_user != dispatch["requester_user"]:
            raise DomainError("distribution_integrity", "The recipient intent differs from its exact approved payload.", 409)
    elif _operation.get() != (doc.name, doc.fencing_token):
        raise DomainError("distribution_effect_required", "Only the exact fenced delivery worker may update this intent.", 403)
