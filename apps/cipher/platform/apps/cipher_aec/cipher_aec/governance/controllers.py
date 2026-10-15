import frappe
from frappe.model.document import Document

from cipher_aec.api.errors import DomainError
from .context import ABILITIES, require_trusted_write


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
        if self.ability not in ABILITIES:
            raise DomainError("invalid_duty", "Select a supported project ability.")
        if frappe.db.get_value("Project", self.project, "company") != self.company:
            raise DomainError("invalid_project_company", "Project and duty company must agree.")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise DomainError("invalid_duty_dates", "The duty end date precedes its start date.")
