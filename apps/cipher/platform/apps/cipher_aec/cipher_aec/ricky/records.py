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
        scope = value.get("scope_type", "Project")
        if scope != (self.get("scope_type") or "Project") or scope not in {"Project", "Company"}:
            raise DomainError("invalid_scope", "The native Ricky scope differs from its original payload.")
        for field, key in (("company", "company"), ("project", "project"), ("requested_by", "user"), ("person_id", "person"), ("status", "status")):
            if self.get(field) != value.get(key):
                raise DomainError("invalid_input", "The Ricky record scope does not match its payload.")
        before = self.get_doc_before_save()
        if scope == "Company":
            from .storage import DOCTYPES, CompanyStore
            from .company_records import initial_run_admission, validate_company_record
            from .company_service import domain_errors
            kind = next(key for key, doctype in DOCTYPES.items() if doctype == self.doctype)
            if self.get("run_id") != value.get("run_id") and not (
                    kind == "run" and before is None and self.get("run_id") in (None, "")
                    and domain_errors(initial_run_admission)(value)):
                raise DomainError("source_integrity", "The native Company run Link differs from its original payload.", 409)
            domain_errors(validate_company_record)(kind, value, CompanyStore(),
                before=json.loads(before.data_json) if before else None)
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
