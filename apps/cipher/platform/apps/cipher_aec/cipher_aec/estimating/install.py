"""Narrow UOM qualification metadata; the standard UOM remains the master."""

from cipher_aec.migrations.contracts import DIMENSIONS


def after_migrate():
    import frappe
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({"UOM": [
        {"fieldname": "cipher_unit_id", "label": "Cipher Unit Identity", "fieldtype": "Data", "read_only": 1, "unique": 1, "no_copy": 1},
        {"fieldname": "cipher_dimension", "label": "Cipher Quantity Dimension", "fieldtype": "Select", "options": "\n" + "\n".join(sorted(DIMENSIONS)), "read_only": 1, "no_copy": 1},
        {"fieldname": "cipher_quantity_precision", "label": "Cipher Quantity Precision", "fieldtype": "Int", "read_only": 1, "no_copy": 1},
        {"fieldname": "cipher_unit_revision", "label": "Cipher Unit Revision", "fieldtype": "Int", "read_only": 1, "no_copy": 1},
    ]}, update=True)
    for doctype, columns, name in (
        ("Cipher Rate Source", ["source_id", "revision_number"], "cipher_rate_source_revision"),
        ("Cipher Assembly Revision", ["assembly_id", "revision_number"], "cipher_assembly_revision"),
        ("Cipher Estimate Revision", ["estimate", "revision_number"], "cipher_estimate_revision"),
        ("Cipher Estimate Acceptance", ["estimate", "baseline_number"], "cipher_estimate_acceptance_number"),
        ("Cipher Estimate Acceptance", ["estimate_revision"], "cipher_estimate_acceptance_revision"),
        ("Cipher Estimate Line", ["estimate_revision", "line_id"], "cipher_estimate_revision_line"),
        ("Cipher Unit Conversion", ["company", "project", "from_unit_id", "to_unit_id", "revision_number"], "cipher_unit_conversion_revision"),
    ):
        if frappe.db.exists("DocType", doctype):
            frappe.db.add_unique(doctype, columns, constraint_name=name)
    if frappe.db.exists("DocType", "Cipher Rate Source"):
        frappe.db.add_index("Cipher Rate Source", ["company", "project", "source_id"], "cipher_rate_scope")
    if frappe.db.exists("DocType", "Cipher Estimate Line"):
        frappe.db.add_index("Cipher Estimate Line", ["company", "project", "line_id"], "cipher_estimate_line_scope")
