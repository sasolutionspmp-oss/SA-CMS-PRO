"""Desk, REST and private File reads share the current project boundary."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, project_ids, require_project


def _query(doctype, user=None):
    try:
        actor = current_actor(user)
        projects = project_ids(actor, ability="document.read")
        # Include standard Project permissions and current project/company state.
        allowed = []
        for project in projects:
            company = frappe.db.get_value("Project", project, "company")
            try:
                require_project(company, project, ability="document.read", actor=actor)
                allowed.append(project)
            except DomainError:
                continue
        if not allowed:
            return "1=0"
        return "`tab" + doctype + "`.`project` IN (" + ",".join(frappe.db.escape(p) for p in allowed) + ")"
    except DomainError:
        return "1=0"


def document_query(user=None):
    return _query("Cipher Document", user)


def _scan_clause():
    unscanned_allowed = frappe.conf.get("cipher_site_mode") == "synthetic" and frappe.conf.get("cipher_allow_unscanned_documents") in (1, True, "1")
    states = "'clean','not_scanned'" if unscanned_allowed else "'clean'"
    return "`tabCipher Document Revision`.`retrieval_status`='available' AND `tabCipher Document Revision`.`scan_status` IN (" + states + ")"


def revision_query(user=None):
    # Native get_list can select Long Text without per-row permission callbacks.
    return "(" + _query("Cipher Document Revision", user) + ") AND (" + _scan_clause() + ")"


def _permission(doc, user=None, permission_type=None):
    if permission_type not in (None, "read", "select"):
        return False
    try:
        require_project(doc.company, doc.project, ability="document.read", actor=current_actor(user))
        return True
    except DomainError:
        return False


def document_permission(doc, user=None, permission_type=None, ptype=None, debug=False):
    return _permission(doc, user, ptype or permission_type)


def revision_permission(doc, user=None, permission_type=None, ptype=None, debug=False):
    # This also guards the attached File's Frappe private download path.
    unscanned_allowed = frappe.conf.get("cipher_site_mode") == "synthetic" and frappe.conf.get("cipher_allow_unscanned_documents") in (1, True, "1")
    scan_allowed = doc.scan_status == "clean" or unscanned_allowed and doc.scan_status == "not_scanned"
    if doc.retrieval_status != "available" or not scan_allowed:
        return False
    return _permission(doc, user, ptype or permission_type)


def file_permission(doc, user=None, permission_type=None, ptype=None, debug=False):
    permission_type = ptype or permission_type
    if doc.attached_to_doctype != "Cipher Document Revision":
        return True
    if permission_type not in (None, "read", "select"):
        return False
    try:
        revision = frappe.get_doc("Cipher Document Revision", doc.attached_to_name)
        if revision.storage_reference != doc.name or not doc.is_private:
            return False
        if not revision_permission(revision, user, permission_type):
            return False
        from .storage import FrappeFileStorage
        FrappeFileStorage().read(doc.name, revision.sha256, revision.byte_length)
        return True
    except Exception:
        # Frappe's download route must never turn missing bytes/records into access.
        return False


def file_query(user=None):
    revision_clause = revision_query(user)
    return "(`tabFile`.`attached_to_doctype` != 'Cipher Document Revision' OR `tabFile`.`attached_to_doctype` IS NULL OR `tabFile`.`attached_to_name` IN (SELECT `name` FROM `tabCipher Document Revision` WHERE " + revision_clause + "))"
