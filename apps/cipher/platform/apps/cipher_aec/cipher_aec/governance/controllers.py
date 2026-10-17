import frappe
from frappe.model.document import Document

from cipher_aec.api.errors import DomainError
from .context import ABILITIES, PROJECT_ABILITIES, COMPANY_ABILITIES, require_trusted_write
from cipher_aec.api.contracts import digest


class GovernedDocument(Document):
    def validate(self):
        require_trusted_write()

    def on_trash(self):
        raise DomainError("history_preserved", "Cipher governance records cannot be deleted.", 403)


class ImmutableDocument(GovernedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            raise DomainError("immutable_record", "This original Cipher receipt cannot be changed.", 403)


class PersonDocument(GovernedDocument):
    pass


class IdentityDocument(GovernedDocument):
    def validate(self):
        super().validate()
        if not frappe.db.exists("Cipher Person", self.person):
            raise DomainError("invalid_person", "Select a registered person.")


class DutyDocument(GovernedDocument):
    def validate(self):
        super().validate()
        validate_scope(self)
        supported = COMPANY_ABILITIES if self.scope_type == "Company" else PROJECT_ABILITIES
        if self.ability not in supported:
            raise DomainError("invalid_duty", "This ability is not available in the declared scope.")
        self.scope_key = digest({"person": self.person, "company": self.company, "scope_type": self.scope_type, "project": self.project or None, "ability": self.ability})
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise DomainError("invalid_duty_dates", "The duty end date precedes its start date.")


def validate_scope(doc):
    if doc.scope_type not in {"Project", "Company"} or not doc.company:
        raise DomainError("invalid_scope", "Declare an exact Company or Project scope.")
    if doc.scope_type == "Company":
        if doc.project:
            raise DomainError("invalid_scope", "Company scope cannot contain a Project.", 422)
        doc.project = None
    elif not doc.project or frappe.db.get_value("Project", doc.project, "company") != doc.company:
        raise DomainError("invalid_project_company", "A Project scope requires a Project in this exact Company.", 422)


class ScopedImmutableDocument(ImmutableDocument):
    def validate(self):
        super().validate()
        validate_scope(self)
