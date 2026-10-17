"""Governed native ERPNext Task assignment and ordinary status commands.

The canonical Person is server owned. One native ToDo backs each assignment;
aliases never become multiple assignees. Unexplained native facts fail closed.
"""

from html import escape

import frappe
from frappe.utils import now_datetime, nowdate

from cipher_aec.api.contracts import expected_version as parse_version, text, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.context import Actor, current_actor, duty_rows, require_project
from cipher_aec.governance.history import append_event
from .task_rules import ASSIGNMENT_FIELDS, TASK_STATUSES, assignment_state, check_task, status_value


def _require_metadata():
    meta = frappe.get_meta("Task")
    targets = dict(zip(ASSIGNMENT_FIELDS, ("Cipher Person", "User", "ToDo")))
    for fieldname, target in targets.items():
        field = meta.get_field(fieldname)
        if not field or field.fieldtype != "Link" or field.options != target or not field.read_only or not field.no_copy:
            raise DomainError("task_metadata_unavailable", "Task controls are unavailable until this site's application upgrade is complete.", 503)
    status = meta.get_field("status")
    if not status or not set(TASK_STATUSES) <= set((status.options or "").splitlines()):
        raise DomainError("task_metadata_unavailable", "This site's native Task statuses require qualification before these controls can be used.", 503)


def require_task(company, project, task, *, actor=None, lock=False):
    actor = actor or current_actor()
    require_project(company, project, actor=actor, lock=lock)
    try:
        doc = frappe.get_doc("Task", text(task, "Task"), for_update=lock)
    except frappe.DoesNotExistError:
        raise DomainError("not_found", "This task is not available.", 404) from None
    if doc.project != project or not frappe.has_permission("Task", ptype="read", doc=doc, user=actor.user):
        raise DomainError("not_found", "This task is not available.", 404)
    return doc


def read_task(company, project, task):
    from .service import present_task
    return present_task(require_task(company, project, task))


def _candidate_rows(company, project, person=None, *, lock=False):
    conditions = " AND p.name=%s" if person else ""
    values = [company, project, nowdate(), nowdate()]
    if person:
        values.append(person)
    return frappe.db.sql(
        "SELECT p.name AS person,p.display_name,b.user,b.name AS binding "
        "FROM `tabCipher Person` p JOIN `tabCipher Identity Binding` b ON b.person=p.name "
        "JOIN `tabUser` u ON u.name=b.user WHERE p.active=1 AND b.active=1 AND u.enabled=1 "
        "AND u.user_type='System User' AND EXISTS (SELECT 1 FROM `tabCipher Project Duty` d "
        "WHERE d.person=p.name AND d.scope_type='Project' AND d.company=%s AND d.project=%s "
        "AND d.ability='project.read' AND d.active=1 AND (d.valid_from IS NULL OR d.valid_from<=%s) "
        "AND (d.valid_until IS NULL OR d.valid_until>=%s))" + conditions +
        " ORDER BY p.name,b.user,b.name" + (" FOR UPDATE" if lock else ""), values, as_dict=True)


def _eligible(company, project, *, person=None, task=None, lock=False):
    people = {}
    for row in _candidate_rows(company, project, person, lock=lock):
        if row.person in people:
            continue
        try:
            candidate = Actor(row.user, row.person, row.display_name)
            require_project(company, project, actor=candidate, lock=lock)
            if not frappe.has_permission("Task", ptype="read", doc=task, user=row.user):
                continue
        except DomainError as error:
            if error.status not in {403, 404}:
                raise
            continue
        people[row.person] = {"id": row.person, "display_name": row.display_name, "user": row.user}
    return people


def task_choices(company, project):
    actor = current_actor()
    require_project(company, project, actor=actor)
    capabilities = sorted({row.ability for row in duty_rows(actor, company, project)} & {"task.assign", "task.update"})
    if not capabilities:
        raise DomainError("capability_denied", "Your current project duties do not allow changing tasks.", 403)
    _require_metadata()
    people = _eligible(company, project) if "task.assign" in capabilities else {}
    return {"people": [{"id": row["id"], "display_name": row["display_name"]} for row in people.values()],
        "statuses": list(TASK_STATUSES), "capabilities": capabilities}


def active_assignments(doc, *, lock=False):
    return frappe.db.sql("SELECT name,allocated_to FROM `tabToDo` WHERE reference_type='Task' "
        "AND reference_name=%s AND status NOT IN ('Cancelled','Closed') ORDER BY name" +
        (" FOR UPDATE" if lock else ""), (doc.name,), as_dict=True)


def present_assignees(doc, active=None):
    # The stored canonical Person survives account revocation/rebinding. Return
    # only the assignment that is still active in the native assignment ledger.
    person = doc.get("cipher_assignee_person")
    if not person or not doc.get("cipher_assignment_todo"):
        return []
    active = active_assignments(doc) if active is None else active
    if not any(row.name == doc.get("cipher_assignment_todo") and row.allocated_to == doc.get("cipher_assignee_user") for row in active):
        return []
    display_name = frappe.db.get_value("Cipher Person", person, "display_name")
    return [{"id": person, "display_name": display_name or "Unavailable person"}]


def _save(doc, project):
    # Native Task updates normally derive Project status without its governed
    # approval and may reschedule other Tasks. These supported controller flags
    # keep this command bounded to the reviewed Task and its native ToDo.
    doc.flags.from_project = True
    doc.flags.ignore_reschedule = True
    doc.set("_assign", frappe.db.get_value("Task", doc.name, "_assign"))
    doc.save(ignore_permissions=True)
    # ToDo.on_update writes Task._assign directly; refresh after native saves.
    doc.reload()
    project.db_set("modified", now_datetime(), update_modified=False)


def _result(doc, project):
    from .service import present_task
    return {"task": present_task(doc), "project_version": version_of(project)}


def assign_task(company, project, task, person, operation_id, expected_version):
    task, expected_version = text(task, "Task"), parse_version(expected_version)
    if person is not None:
        person = text(person, "Assigned person")
    # Scope admission precedes participant lookup. Only an existing canonical
    # Person enters the command's ordered participant lock set.
    require_task(company, project, task)
    require_project(company, project, ability="task.assign")
    participants = ()
    if person is not None:
        if not frappe.db.exists("Cipher Person", person):
            raise DomainError("assignee_unavailable", "Choose a person with current access to this project.", 409)
        participants = (person,)

    def effect(actor, record):
        _require_metadata()
        doc = require_task(company, project, task, actor=actor, lock=True)
        check_task(doc, expected_version)
        if doc.status == "Completed":
            raise DomainError("task_closed", "Reopen this completed task before changing its assignment.", 409)
        previous_status = doc.status
        current = assignment_state(doc, active_assignments(doc, lock=True))
        candidate = None
        if person is not None:
            candidate = _eligible(company, project, person=person, task=doc, lock=True).get(person)
            if candidate is None:
                raise DomainError("assignee_unavailable", "Choose a person with current access to this project.", 409)
        if (current["person"] if current else None) == person:
            raise DomainError("task_unchanged", "This task already has the selected assignment.", 409)
        if current:
            todo = frappe.get_doc("ToDo", current["todo"], for_update=True)
            todo.status = "Cancelled"
            todo.save(ignore_permissions=True)
        for field in ASSIGNMENT_FIELDS:
            doc.set(field, None)
        if candidate:
            # Supported native Document API, as in Frappe assign_to._add. ToDo
            # owns _assign and native comments. No implicit sharing, follow, or
            # helper notification is needed to grant already-verified access.
            todo = frappe.get_doc({"doctype": "ToDo", "reference_type": "Task", "reference_name": doc.name,
                "allocated_to": candidate["user"], "assigned_by": actor.user, "status": "Open", "priority": "Medium",
                "description": escape(doc.subject), "date": nowdate()}).insert(ignore_permissions=True)
            doc.cipher_assignee_person, doc.cipher_assignee_user, doc.cipher_assignment_todo = person, candidate["user"], todo.name
        _save(doc, record)
        if doc.status != previous_status:
            raise DomainError("task_status_changed", "Native task rules would change this task's status. Refresh it and select its status explicitly before assigning it.", 409)
        append_event(actor=actor, company=company, project=project,
            event="task.assigned" if candidate else "task.unassigned", subject_type="Task", subject_id=doc.name,
            operation_id=operation_id, details={"subject": doc.subject, "previous_person": current["person"] if current else None,
                "person": person, "status": doc.status})
        return _result(doc, record)

    return run_command(company=company, project=project, operation_id=operation_id, command="task.assign",
        payload={"task": task, "person": person, "expected_version": expected_version}, ability="task.assign",
        effect=effect, participant_people=participants)


def update_task_status(company, project, task, status, operation_id, expected_version):
    task, status, expected_version = text(task, "Task"), status_value(status), parse_version(expected_version)

    def effect(actor, record):
        _require_metadata()
        doc = require_task(company, project, task, actor=actor, lock=True)
        check_task(doc, expected_version)
        previous = doc.status
        if previous == "Completed" and status != "Open":
            raise DomainError("task_reopen_required", "Reopen this completed task to Open before selecting another status.", 409)
        if previous == status:
            raise DomainError("task_unchanged", "This task already has the selected status.", 409)
        current = assignment_state(doc, active_assignments(doc, lock=True))
        if status == "Completed":
            # Same-Project command serialization protects dependency reads. The
            # native controller repeats its own completion validation on save.
            for dependency in sorted({row.task for row in doc.get("depends_on") or []}):
                linked = require_task(company, project, dependency, actor=actor, lock=True)
                if linked.status not in {"Completed", "Cancelled"}:
                    raise DomainError("task_dependency_open", "Complete or cancel this task's dependencies before completing it.", 409)
            doc.completed_by = actor.user
            # Close the exact owned native ToDo before Task.db_update so its
            # _assign cache cannot overwrite ToDo's native update. The native
            # controller repeats close_all_assignments and finds none left.
            if current:
                todo = frappe.get_doc("ToDo", current["todo"], for_update=True)
                todo.status = "Closed"
                todo.save(ignore_permissions=True)
            for field in ASSIGNMENT_FIELDS:
                doc.set(field, None)
        doc.status = status
        _save(doc, record)
        if doc.status != status:
            raise DomainError("task_status_changed", "Native task rules changed this status. Refresh the task before continuing.", 409)
        event = "task.completed" if status == "Completed" else "task.reopened" if previous == "Completed" else "task.status_changed"
        append_event(actor=actor, company=company, project=project, event=event,
            subject_type="Task", subject_id=doc.name, operation_id=operation_id,
            details={"subject": doc.subject, "previous_status": previous, "status": doc.status})
        return _result(doc, record)

    return run_command(company=company, project=project, operation_id=operation_id, command="task.update_status",
        payload={"task": task, "status": status, "expected_version": expected_version}, ability="task.update", effect=effect)
