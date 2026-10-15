"""Desk, REST and private File reads share the current project boundary."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, project_ids, require_project, company_ids, require_company
from .scope import scope_of
from .extraction import ArtifactError


def _query(doctype, user=None):
    try:
        actor = current_actor(user)
        projects = project_ids(actor, ability="document.read")
        allowed_projects, allowed_companies = [], []
        for project in projects:
            company = frappe.db.get_value("Project", project, "company")
            try:
                require_project(company, project, ability="document.read", actor=actor)
                allowed_projects.append(project)
            except DomainError:
                continue
        for company in company_ids(actor, ability="document.read"):
            try:
                require_company(company, ability="document.read", actor=actor)
                allowed_companies.append(company)
            except DomainError:
                continue
        table = "`tab" + doctype + "`"
        clauses = []
        if allowed_projects:
            clauses.append("(" + table + ".scope_type='Project' AND " + table + ".project IN (" + ",".join(frappe.db.escape(p) for p in allowed_projects) + "))")
        if allowed_companies:
            clauses.append("(" + table + ".scope_type='Company' AND " + table + ".project IS NULL AND " + table + ".company IN (" + ",".join(frappe.db.escape(c) for c in allowed_companies) + "))")
        return "(" + " OR ".join(clauses) + ")" if clauses else "1=0"
    except DomainError:
        return "1=0"


def _producer_query(doctype, user=None):
    """Source authorization before native list/count/Long Text projection."""
    from .provenance import authorize, QUERY_SCAN_CAP
    table = "`tab" + doctype + "`"
    if not frappe.db.has_column("Cipher Document", "producer_kind"):
        # No generated record can exist in the pre-extension schema. Raw routes
        # stay usable during the coordinated source-before-metadata rollout.
        return "1=1"
    raw_clause = ("COALESCE(" + table + ".producer_kind,'')=''" if doctype == "Cipher Document" else
        table + ".document IN (SELECT name FROM `tabCipher Document` WHERE COALESCE(producer_kind,'')='')")
    required = ("producer_reference", "producer_input_digest", "producer_binding_json")
    if any(not frappe.db.has_column("Cipher Document", field) for field in required):
        return raw_clause
    try:
        actor = current_actor(user)
        # Raw records never require a producer-source scan. The bounded generated
        # set is discovered internally and independently reauthorized before SQL.
        rows = frappe.get_all("Cipher Document", filters={"producer_kind": ["is", "set"]},
            fields=["name", "company", "project", "scope_type"],
            order_by="name", limit_page_length=QUERY_SCAN_CAP + 1)
        if len(rows) > QUERY_SCAN_CAP:
            return raw_clause
        allowed = []
        for row in rows:
            try:
                if not _permission(row, user, "read"):
                    continue
                allowed.append(row.name)
            except DomainError:
                continue
        identity = "name" if doctype == "Cipher Document" else "document"
        clause = raw_clause
        if allowed:
            clause += " OR " + table + ".`" + identity + "` IN (" + ",".join(frappe.db.escape(name) for name in allowed) + ")"
        return "(" + clause + ")"
    except DomainError:
        return "1=0"


def document_query(user=None):
    return "(" + _query("Cipher Document", user) + ") AND (" + _producer_query("Cipher Document", user) + ")"


def _scan_clause():
    unscanned_allowed = frappe.conf.get("cipher_site_mode") == "synthetic" and frappe.conf.get("cipher_allow_unscanned_documents") in (1, True, "1")
    states = "'clean','not_scanned'" if unscanned_allowed else "'clean'"
    return "`tabCipher Document Revision`.`retrieval_status`='available' AND `tabCipher Document Revision`.`scan_status` IN (" + states + ")"


def revision_query(user=None):
    # Native get_list can select Long Text without per-row permission callbacks.
    return "(" + _query("Cipher Document Revision", user) + ") AND (" + _scan_clause() + ") AND (" + _producer_query("Cipher Document Revision", user) + ")"


def _permission(doc, user=None, permission_type=None):
    if permission_type not in (None, "read", "select"):
        return False
    try:
        actor = current_actor(user)
        if scope_of(doc.as_dict() if callable(getattr(doc, "as_dict", None)) else doc) == "Company":
            require_company(doc.company, ability="document.read", actor=actor)
        else:
            require_project(doc.company, doc.project, ability="document.read", actor=actor)
        from .provenance import authorize
        authorize(doc.as_dict() if callable(getattr(doc, "as_dict", None)) else doc, actor)
        return True
    except (DomainError, ArtifactError):
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
