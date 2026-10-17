"""Database uniqueness supplements sequential row locking in upload commands."""

def after_migrate():
    import frappe
    frappe.db.add_unique("Cipher Document Revision", ["document", "revision_number"], constraint_name="cipher_document_revision_sequence")

    # Missing ownership never becomes Company authority. Pre-extension rows are
    # Project records, retaining their IDs, revision hashes and command receipts.
    for doctype in ("Cipher Document", "Cipher Document Revision"):
        frappe.db.sql("UPDATE `tab" + doctype + "` SET scope_type='Project' WHERE scope_type IS NULL OR scope_type='' ")
        frappe.db.add_index(doctype, ["company", "scope_type", "project"], "cipher_source_exact_scope")

    frappe.db.sql("UPDATE `tabCipher Document` SET producer_kind=NULL,producer_input_digest=NULL WHERE producer_kind IS NULL OR producer_kind=''")
    # NULL raw-producer fields permit many raw documents; generated input is unique.
    frappe.db.add_unique("Cipher Document", ["company", "producer_kind", "producer_input_digest"], constraint_name="cipher_generated_input_unique")
    frappe.db.add_unique("Cipher Document", ["company", "producer_kind", "producer_reference"], constraint_name="cipher_prepared_revision_unique")
