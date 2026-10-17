"""Protect Frappe File paths from bypassing canonical revision immutability."""
import frappe
from cipher_aec.governance.context import require_trusted_write


def validate_file(doc, method=None):
    previous = doc.get_doc_before_save() if not doc.is_new() else None
    linked = doc.attached_to_doctype == "Cipher Document Revision" or previous and previous.attached_to_doctype == "Cipher Document Revision"
    if not linked:
        return
    require_trusted_write()
    if previous:
        frappe.throw("Source File records are immutable; upload a new document revision.")
    if not doc.is_private or not doc.attached_to_name:
        frappe.throw("Document source Files must be private and bound to a revision.")


def before_delete_file(doc, method=None):
    if doc.attached_to_doctype == "Cipher Document Revision":
        frappe.throw("Document source Files cannot be deleted through ordinary operations.")


class CipherFileGuard:
    """Frappe v16's native private route otherwise grants the File owner access.

    Original sources are served only by our authorized attachment RPC, which checks
    current identity, source availability and SHA-256 immediately before delivery.
    """
    def is_downloadable(self):
        if self.attached_to_doctype == "Cipher Document Revision":
            return False
        return super().is_downloadable()


@frappe.whitelist()
def zip_files(files):
    """Close the native zip path, which calls File's owner-bypassing helper."""
    from frappe.core.doctype.file.file import File
    files = frappe.parse_json(files)
    if not isinstance(files, list) or len(files) > 100:
        frappe.throw("Choose up to 100 files.", frappe.ValidationError)
    for item in files:
        if not isinstance(item, str):
            frappe.throw("File identifiers must be text.", frappe.ValidationError)
        if frappe.db.get_value("File", item, "attached_to_doctype") == "Cipher Document Revision":
            frappe.throw("Download source revisions through Cipher Documents.", frappe.PermissionError)
    frappe.response.update(filename="files.zip", filecontent=File.zip_files(files), type="download")
