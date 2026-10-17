"""Bounded ordinary Task controls, using the pinned ERPNext status vocabulary."""

import json
from decimal import Decimal

from cipher_aec.api.contracts import digest, expected_version, text, version_of
from cipher_aec.api.errors import DomainError

TASK_STATUSES = ("Open", "Working", "Pending Review", "Completed")
ASSIGNMENT_FIELDS = ("cipher_assignee_person", "cipher_assignee_user", "cipher_assignment_todo")


def task_version(doc):
    # Native overdue and assignment maintenance use update_modified=False.
    # Bind the optimistic token to the actual reviewed Task facts as well as
    # its native timestamp, so these native changes cannot bypass staleness.
    facts = {field: doc.get(field) or None for field in (
        "status", "subject", "description", "parent_task", "completed_by", "_assign", *ASSIGNMENT_FIELDS)}
    facts.update(modified=version_of(doc),
        progress=str(Decimal(str(doc.get("progress") or 0)).normalize()),
        completed_on=str(doc.get("completed_on")) if doc.get("completed_on") else None,
        is_template=bool(doc.get("is_template")), is_group=bool(doc.get("is_group")),
        dependencies=sorted(row.get("task") for row in doc.get("depends_on") or []))
    return digest(facts)


def status_value(value):
    value = text(value, "Task status", 40)
    if value not in TASK_STATUSES:
        raise DomainError("invalid_task_status", "Choose Open, Working, Pending Review, or Completed.", 422)
    return value


def check_task(doc, version):
    if task_version(doc) != expected_version(version):
        raise DomainError("stale_version", "This task changed. Refresh and review it before saving.", 412)
    if doc.get("is_template") or doc.get("is_group") or doc.get("parent_task"):
        raise DomainError("task_structure_unqualified", "This control supports ordinary standalone tasks. Use a separately qualified template or group workflow for this task.", 409)
    if doc.status == "Cancelled":
        raise DomainError("task_closed", "This task was cancelled and cannot be changed by this workflow.", 409)


def assignment_state(doc, active):
    """Never adopt or erase a native assignment created outside this command."""
    values = [doc.get(field) for field in ASSIGNMENT_FIELDS]
    if any(not isinstance(row.get("allocated_to"), str) or not row["allocated_to"] or not isinstance(row.get("name"), str) or not row["name"] for row in active):
        raise DomainError("assignment_conflict", "This task has an incomplete native assignment. Ask an administrator to reconcile it.", 409)
    try:
        native = json.loads(doc.get("_assign") or "[]")
    except (ValueError, TypeError):
        native = None
    if not isinstance(native, list) or not all(isinstance(value, str) for value in native) or sorted(native) != sorted(row["allocated_to"] for row in active):
        raise DomainError("assignment_conflict", "This task's native assignment list needs administrator reconciliation.", 409)
    if not any(values) and not active:
        return None
    if not all(values) or len(active) != 1:
        raise DomainError("assignment_conflict", "This task has assignment information that needs administrator reconciliation before it can be changed.", 409)
    row = active[0]
    if row["name"] != values[2] or row["allocated_to"] != values[1]:
        raise DomainError("assignment_conflict", "This task has a different native assignment. Refresh it and ask an administrator to reconcile its assignment.", 409)
    return {"person": values[0], "user": values[1], "todo": values[2]}
