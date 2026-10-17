"""Namespaced native child identity; no duplicate party or pricing master."""

def after_migrate():
    import frappe
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({"Quotation Item": [
        {"fieldname": "cipher_line_id", "label": "Cipher Line UUID", "fieldtype": "Data", "read_only": 1, "hidden": 1, "no_copy": 1},
        {"fieldname": "cipher_alternate_group", "label": "Cipher Alternate Group UUID", "fieldtype": "Data", "read_only": 1, "hidden": 1, "no_copy": 1},
    ]}, update=True)
    frappe.db.add_unique("Cipher Proposal Revision", ["proposal", "revision_number"], constraint_name="cipher_proposal_revision_sequence")
    frappe.db.add_unique("Cipher Proposal Issue", ["proposal_revision"], constraint_name="cipher_issue_exact_revision_unique")
    frappe.db.add_unique("Cipher Proposal Issue", ["proposal", "revision_number"], constraint_name="cipher_issue_sequence_unique")
