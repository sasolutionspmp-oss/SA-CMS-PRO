"""Company duties and native-source permission guard generic commercial reads."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import company_ids, current_actor
from .service import _read, _actor


def _permission(doc, kind, user=None, permission_type=None, ptype=None, debug=False):
    if (ptype or permission_type) not in (None, "read", "select"):
        return False
    try:
        actor = _actor(doc.company, current_actor(user))
        _read(kind, doc.name, doc.company, actor)
        return True
    except DomainError:
        return False


def _query(doctype, kind, user=None):
    try:
        actor = current_actor(user)
        names = []
        for company in company_ids(actor, ability="commercial.read"):
            for row in frappe.get_all(doctype, filters={"company": company}, fields=["name"]):
                try:
                    _read(kind, row.name, company, actor)
                    names.append(row.name)
                except DomainError:
                    continue
        return "`tab" + doctype + "`.`name` IN (" + ",".join(frappe.db.escape(name) for name in names) + ")" if names else "1=0"
    except DomainError:
        return "1=0"


def pursuit_query(user=None):
    return _query("Cipher Pursuit", "pursuit", user)


def proposal_query(user=None):
    return _query("Cipher Proposal", "proposal", user)


def revision_query(user=None):
    return _query("Cipher Proposal Revision", "revision", user)


def pursuit_permission(doc, **kwargs):
    return _permission(doc, "pursuit", **kwargs)


def proposal_permission(doc, **kwargs):
    return _permission(doc, "proposal", **kwargs)


def revision_permission(doc, **kwargs):
    return _permission(doc, "revision", **kwargs)
