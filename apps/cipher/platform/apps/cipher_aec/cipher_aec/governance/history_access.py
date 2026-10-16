"""Literal history-subject readers; audit metadata never grants source access."""
import frappe
import json

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company, require_project

EST_SUBJECTS = {"Cipher Unit Conversion":"conversion", "Cipher Rate Source":"rate", "Cipher Assembly Revision":"assembly",
    "Cipher Estimate":"estimate", "Cipher Estimate Revision":"revision", "Cipher Estimate Line":"line", "Cipher Calculation Snapshot":"snapshot", "Cipher Estimate Acceptance":"acceptance"}
TAKEOFF_SUBJECTS = {"Cipher Takeoff Set":"set", "Cipher Calibration":"calibration", "Cipher Calibration Verification":"verification",
    "Cipher Takeoff Measurement":"measurement", "Cipher Takeoff Line Binding":"binding"}
FIN_SUBJECTS = {"Cipher Construction Contract":"contract", "Cipher Contract Revision":"revision", "Cipher Retainage Policy Revision":"policy", "Cipher SOV Version":"sov", "Cipher SOV Line":"line"}
COM_SUBJECTS = {"Cipher Pursuit":"pursuit", "Cipher Proposal":"proposal", "Cipher Proposal Revision":"revision", "Cipher Proposal Issue":"issue"}


def readable(event, actor, company, project):
    """Current exact source/revision rights, before counts or public cursors.

    An integrity failure aborts the whole read; only explicit denied/unavailable
    subjects are omitted. Unknown subjects remain closed until registered here.
    """
    subject, identifier = event.subject_type, event.subject_id
    try:
        if subject == "Company":
            return identifier == company and bool(require_company(company, actor=actor))
        if subject == "Project":
            return bool(project and identifier == project and require_project(company, project, actor=actor))
        if subject == "Task":
            row = frappe.get_doc("Task", identifier)
            if not project or row.project != project:
                return False
            return bool(require_project(company, project, actor=actor) and frappe.has_permission("Task", "read", doc=row, user=actor.user))
        if subject in {"Cipher Document", "Cipher Document Revision"}:
            if project is None:
                from cipher_aec.documents.service import authorize_company_subject
                authorize_company_subject(actor, company, subject, identifier)
                return True
            row = frappe.get_doc(subject, identifier)
            if row.company != company or row.project != project:
                return False
            require_project(company, project, ability="document.read", actor=actor)
            return bool(frappe.has_permission(subject, "read", doc=row, user=actor.user))
        if subject == "Cipher Ricky Run":
            if project is not None:
                return False
            from cipher_aec.ricky.company_service import authorize_history as authorize_company_ricky_history
            authorize_company_ricky_history(actor, company, identifier, lock=False)
            return True
        if subject == "Cipher Approval Packet":
            from .approvals import authorize_history_packet
            authorize_history_packet(company, project, identifier, actor=actor,
                scope_type="Project" if project is not None else "Company")
            return True
        if subject in EST_SUBJECTS:
            from cipher_aec.estimating.service import _scoped
            from cipher_aec.estimating.scopes import activate
            with activate("Project" if project is not None else "Company", company, project):
                _scoped(EST_SUBJECTS[subject], identifier, company, project, actor)
            return True
        if subject in TAKEOFF_SUBJECTS:
            from cipher_aec.takeoff.service import _read
            from cipher_aec.estimating.scopes import activate
            with activate("Project" if project is not None else "Company", company, project):
                _read(TAKEOFF_SUBJECTS[subject], identifier, company, project, actor, new_use=False)
            return True
        if subject in FIN_SUBJECTS:
            if not project:
                return False
            from cipher_aec.construction_finance.service import scoped
            kind = FIN_SUBJECTS[subject]
            if subject == "Cipher Construction Contract":
                details = json.loads(event.details_json)
                if event.event == "contract.revision.authored":
                    revision = scoped("revision", details.get("record_id"), company, project, actor)
                    if revision["contract"] != identifier:
                        raise DomainError("history_integrity", "The exact contract history source is inconsistent.", 409)
                    return True
                if event.event != "contract.created" or details.get("record_id") != identifier:
                    return False
            scoped(kind, identifier, company, project, actor)
            return True
        if subject in {"Cipher Cost Code Revision", "Cipher Cost Type Revision"}:
            if project is not None:return False
            from cipher_aec.project_controls.service import get_revision
            value = get_revision(company, "code" if subject == "Cipher Cost Code Revision" else "type", identifier, str(event.creation)[:10])
            return True
        if subject in {"Cipher WBS Node", "Cipher Budget Version", "Cipher Budget Line"}:
            if project is None:return False
            from cipher_aec.project_controls.service import get_record
            kind = {"Cipher WBS Node":"wbs", "Cipher Budget Version":"budget", "Cipher Budget Line":"budget_line"}[subject]
            get_record(company, project, kind, identifier)
            return True
        if subject in {"Cipher Award Handoff", "Cipher Award Handoff Revision", "Cipher Award Adoption", "Cipher Award Line Adoption"}:
            if project is not None:return False
            from cipher_aec.awards.service import authorize_history
            authorize_history(company, subject, identifier, actor, event_name=event.event, details=json.loads(event.details_json))
            return True
        if subject in COM_SUBJECTS:
            if project is not None:
                return False
            require_company(company, ability="commercial.read", actor=actor)
            from cipher_aec.commercial.service import _read
            _read(COM_SUBJECTS[subject], identifier, company, actor)
            return True
        if subject in {"Cipher Distribution Instruction", "Cipher Distribution Dispatch", "Cipher Distribution Cancellation"}:
            if project is not None:
                return False
            from cipher_aec.integrations.distribution import TYPES, read
            kind = next(kind for kind, name in TYPES.items() if name == subject)
            read(kind, identifier, company, actor)
            return True
        return False
    except frappe.DoesNotExistError:
        return False
    except DomainError as error:
        if error.status in {401, 403, 404}:
            return False
        raise
