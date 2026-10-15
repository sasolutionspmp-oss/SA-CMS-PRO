import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_trusted_write


def _installing():
    return bool(frappe.flags.in_install or frappe.flags.in_migrate)


def validate_project(doc, method=None):
    if _installing():
        return
    require_trusted_write()
    if not doc.company:
        raise DomainError("company_required", "A Cipher project requires a company.")
    old = doc.get_doc_before_save()
    if old and old.status != doc.status:
        from cipher_aec.governance.approvals import require_project_status_grant
        require_project_status_grant(doc, old)
    if old and old.company != doc.company:
        raise DomainError("immutable_company", "Project company cannot change.", 409)


def validate_task(doc, method=None):
    if _installing():
        return
    require_trusted_write()
    if not doc.project:
        raise DomainError("project_required", "A Cipher task requires a project.")
    old = doc.get_doc_before_save()
    if old and old.project != doc.project:
        raise DomainError("immutable_project", "Task project cannot change.", 409)


def prevent_delete(doc, method=None):
    if not _installing():
        raise DomainError("history_preserved", "Project work history must be retained.", 403)


def validate_assignment(doc, method=None):
    # Frappe's assign_to endpoint checks target read, then writes ToDo with
    # ignore_permissions and updates target._assign directly. Catch that path.
    if not _installing() and (doc.reference_type in {"Project", "Task"} or (doc.reference_type or "").startswith("Cipher ")):
        require_trusted_write()
