from cipher_aec.api.errors import DomainError
from cipher_aec.governance.controllers import GovernedDocument, ImmutableDocument


class IntegrationOperation(GovernedDocument):
    def validate(self):
        super().validate()
        old = self.get_doc_before_save()
        if old:
            for field in ("company", "project", "actor_user", "actor_person", "logical_id", "effect_operation_id", "kind", "payload_json", "payload_hash"):
                if self.get(field) != old.get(field):
                    raise DomainError("immutable_operation", "An integration operation retains its original source and identity.", 409)


class DeliveryAttempt(ImmutableDocument):
    pass
