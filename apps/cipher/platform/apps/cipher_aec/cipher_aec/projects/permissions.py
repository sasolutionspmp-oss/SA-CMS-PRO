import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, duty_rows, project_ids


def _ids(user=None):
    try:
        return project_ids(current_actor(user))
    except DomainError:
        return []


def project_query(user=None):
    ids = _ids(user)
    if not ids:
        return "1=0"
    return "`tabProject`.`name` IN (" + ",".join(frappe.db.escape(name) for name in ids) + ")"


def task_query(user=None):
    ids = _ids(user)
    if not ids:
        return "1=0"
    return "`tabTask`.`project` IN (" + ",".join(frappe.db.escape(name) for name in ids) + ")"


def project_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    permission_type = permission_type or ptype or "read"
    if permission_type not in {"read", "select", "report", "print", "email", "export"}:
        return False
    try:
        actor = current_actor(user)
        return doc.name in project_ids(actor, doc.company)
    except DomainError:
        return False


def task_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    permission_type = permission_type or ptype or "read"
    if permission_type not in {"read", "select", "report", "print", "email", "export"}:
        return False
    return doc.project in _ids(user)
