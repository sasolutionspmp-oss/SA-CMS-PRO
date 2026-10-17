"""Native draft masters linked to Cipher can only change through its revision service."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_trusted_write


def _linked(doc):
    target, field = ("Cipher Pursuit", "opportunity") if doc.doctype == "Opportunity" else ("Cipher Proposal", "quotation")
    return frappe.db.exists(target, {field: doc.name})


def native_validate(doc, method=None):
    if _linked(doc):
        require_trusted_write()
        if doc.docstatus != 0:
            raise DomainError("commercial_transition_unavailable", "COM-01 supports draft composition; issue and award are not qualified.", 409)


def native_trash(doc, method=None):
    if _linked(doc):
        raise DomainError("immutable_commercial_history", "Linked native commercial masters retain their proposal evidence.", 403)
