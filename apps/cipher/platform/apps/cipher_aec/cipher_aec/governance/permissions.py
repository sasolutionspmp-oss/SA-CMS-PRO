import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import company_ids, current_actor, read_company_authority, _consume_company_native_read


def company_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    kind = permission_type or ptype or "read"
    if kind not in {"read", "select", "report", "print", "email", "export"}:
        return False
    checked = _consume_company_native_read(doc, user, kind)
    if checked is not None:
        return checked
    try:
        _, can_read, _ = read_company_authority(user, doc.name)
        return can_read
    except DomainError:
        return False


def company_query(user=None):
    try:
        identifiers = company_ids(current_actor(user))
    except DomainError:
        identifiers = []
    return "`tabCompany`.`name` IN (" + ",".join(frappe.db.escape(name) for name in identifiers) + ")" if identifiers else "1=0"
