"""Defend persisted orchestration records from generic-resource write bypasses."""

import json

from frappe.model.document import Document

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_trusted_write


class RickyRecord(Document):
    def validate(self):
        require_trusted_write()
        try:
            value = json.loads(self.data_json)
        except (TypeError, ValueError):
            raise DomainError("invalid_input", "A durable Ricky record requires valid JSON.") from None
        if not isinstance(value, dict) or value.get("id") != self.name:
            raise DomainError("invalid_input", "The Ricky record identifier does not match its payload.")
        for field, key in (("company", "company"), ("project", "project"), ("requested_by", "user"), ("person_id", "person"), ("status", "status")):
            if self.get(field) != value.get(key):
                raise DomainError("invalid_input", "The Ricky record scope does not match its payload.")
        before = self.get_doc_before_save()
        if before:
            old = json.loads(before.data_json)
            if any(old.get(key) != value.get(key) for key in ("id", "company", "project", "user", "person", "run_id", "authority")):
                raise DomainError("immutable_scope", "A durable Ricky record cannot change its scope or actor.")
            if self.doctype in {"Cipher Tool Invocation", "Cipher Run Artifact"} and old != value:
                raise DomainError("immutable_record", "Completed tool receipts and source references are immutable.")

    def on_trash(self):
        raise DomainError("immutable_record", "Durable Ricky history cannot be deleted through a document action.", 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError("immutable_record", "Durable Ricky identifiers cannot be renamed.", 403)
