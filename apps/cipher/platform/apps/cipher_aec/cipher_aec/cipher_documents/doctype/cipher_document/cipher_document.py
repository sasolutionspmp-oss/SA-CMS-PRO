"""Metadata head; bytes and issued revision metadata cannot be edited in place."""
import frappe
from frappe.model.document import Document
from cipher_aec.governance.context import require_trusted_write


class CipherDocument(Document):
    def validate(self):
        require_trusted_write()
        if not self.is_new():
            previous = self.get_doc_before_save()
            for field in ("company", "project", "title"):
                if previous.get(field) != self.get(field):
                    frappe.throw("Document scope and title are immutable; create a new document.")
            if self.revision_number != previous.revision_number + 1:
                frappe.throw("Document head must advance exactly one revision.")
            row = frappe.db.get_value("Cipher Document Revision", self.current_revision,
                                      ["document", "revision_number", "company", "project"], as_dict=True)
            if not row or row.document != self.name or row.revision_number != self.revision_number or row.company != self.company or row.project != self.project:
                frappe.throw("Document head must identify its next stored revision.")
        elif self.revision_number != 0 or self.current_revision:
            frappe.throw("A new document starts without a revision.")

    def on_trash(self):
        frappe.throw("Document history cannot be deleted through ordinary operations.")
