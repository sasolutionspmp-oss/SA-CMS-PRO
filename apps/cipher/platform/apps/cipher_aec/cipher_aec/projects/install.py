"""Supported additive Task metadata; never grants duties or rewrites assignments."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
import frappe

FIELDS = {"cipher_assignee_person": "Cipher Person", "cipher_assignee_user": "User", "cipher_assignment_todo": "ToDo"}


def after_migrate():
    create_custom_fields({"Task": [
        {"fieldname": "cipher_assignee_person", "label": "Cipher Assigned Person", "fieldtype": "Link", "options": "Cipher Person", "read_only": 1, "no_copy": 1, "hidden": 1},
        {"fieldname": "cipher_assignee_user", "label": "Cipher Native Assignment User", "fieldtype": "Link", "options": "User", "read_only": 1, "no_copy": 1, "hidden": 1},
        {"fieldname": "cipher_assignment_todo", "label": "Cipher Native Assignment ToDo", "fieldtype": "Link", "options": "ToDo", "read_only": 1, "no_copy": 1, "hidden": 1},
    ]}, update=True)


def metadata_status():
    """Read-only post-migration evidence, without fixture or permission writes."""
    rows = []
    for fieldname, target in FIELDS.items():
        row = frappe.db.get_value("Custom Field", {"dt": "Task", "fieldname": fieldname},
            ["fieldtype", "options", "read_only", "no_copy", "hidden"], as_dict=True)
        column = frappe.db.has_column("Task", fieldname)
        rows.append({"fieldname": fieldname, "column": bool(column), "definition": dict(row) if row else None,
            "valid": bool(column and row and row.fieldtype == "Link" and row.options == target and row.read_only and row.no_copy and row.hidden)})
    return {"schema": "cipher.task-controls.metadata.v1", "ready": all(row["valid"] for row in rows), "fields": rows}
