import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import company_ids, current_actor


def company_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    if (permission_type or ptype or "read") not in {"read", "select", "report", "print", "email", "export"}:
        return False
    try:
        return doc.name in company_ids(current_actor(user))
    except DomainError:
        return False


def company_query(user=None):
    try:
        identifiers = company_ids(current_actor(user))
    except DomainError:
        identifiers = []
    return "`tabCompany`.`name` IN (" + ",".join(frappe.db.escape(name) for name in identifiers) + ")" if identifiers else "1=0"
