"""Database uniqueness supplements sequential row locking in upload commands."""

def after_migrate():
    import frappe
    frappe.db.add_unique("Cipher Document Revision", ["document", "revision_number"], constraint_name="cipher_document_revision_sequence")
