"""Indexes bind immutable revisions and prevent duplicate effective line bases."""
import frappe


def after_migrate():
    for doctype in ("Cipher Calibration", "Cipher Takeoff Measurement"):
        if frappe.db.exists("DocType", doctype):
            frappe.db.add_unique(doctype, ["family_id", "revision_number"])
            frappe.db.add_index(doctype, ["company", "project", "source_revision"])
    if frappe.db.exists("DocType", "Cipher Calibration Verification"):
        frappe.db.add_unique("Cipher Calibration Verification", ["calibration"])
        frappe.db.add_unique("Cipher Calibration Verification", ["packet_id"])
    if frappe.db.exists("DocType", "Cipher Takeoff Line Binding"):
        frappe.db.add_unique("Cipher Takeoff Line Binding", ["estimate_revision", "line_id"])
        frappe.db.add_index("Cipher Takeoff Line Binding", ["measurement"])
