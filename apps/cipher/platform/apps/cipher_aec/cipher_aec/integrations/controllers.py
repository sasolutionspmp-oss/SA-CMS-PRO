from cipher_aec.api.errors import DomainError
from cipher_aec.governance.controllers import GovernedDocument, ImmutableDocument, validate_scope


class IntegrationOperation(GovernedDocument):
    def validate(self):
        super().validate()
        if self.get("scope_type") == "Company" and self.kind != "company.proposal.fixture.v1":
            raise DomainError("integration_unavailable", "This Company effect is not registered.", 403)
        if self.kind == "company.proposal.fixture.v1":
            from .distribution_records import validate_operation
            validate_scope(self)
            validate_operation(self)
        old = self.get_doc_before_save()
        if old:
            for field in ("scope_type", "company", "project", "actor_user", "actor_person", "logical_id", "effect_operation_id", "kind", "payload_json", "payload_hash"):
                if self.get(field) != old.get(field):
                    raise DomainError("immutable_operation", "An integration operation retains its original source and identity.", 409)
            if self.kind == "company.proposal.fixture.v1" and any(self.get(field) != old.get(field) for field in ("distribution_dispatch", "recipient_id")):
                raise DomainError("immutable_operation", "The original recipient and dispatch remain immutable.", 409)


class DeliveryAttempt(ImmutableDocument):
    def validate(self):
        super().validate()
        if self.get("scope_type") == "Company":
            import frappe
            from .distribution_records import _operation
            validate_scope(self)
            operation = frappe.get_doc("Cipher Integration Operation", self.operation)
            if operation.scope_type != "Company" or operation.company != self.company or _operation.get() != (self.operation, self.fencing_token):
                raise DomainError("distribution_effect_required", "Delivery evidence requires its exact operation fence.", 403)
