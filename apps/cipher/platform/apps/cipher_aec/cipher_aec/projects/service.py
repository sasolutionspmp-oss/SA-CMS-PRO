import frappe
from frappe.utils import now_datetime

from cipher_aec.api.contracts import digest, expected_version as parse_version, text, version_of
from cipher_aec.api.paging import decode_cursor, page_options, page_result, signing_secret
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.context import current_actor, duty_rows, project_ids, require_project
from cipher_aec.governance.history import append_event, present_event


def present_project(doc, actor=None):
    result = {"id": doc.name, "name": doc.project_name, "company": doc.company, "status": doc.status,
        "version": version_of(doc), "expected_start_date": str(doc.expected_start_date) if doc.expected_start_date else None,
        "expected_end_date": str(doc.expected_end_date) if doc.expected_end_date else None}
    if actor:
        result["capabilities"] = sorted({row.ability for row in duty_rows(actor, doc.company, doc.name)})
    return result


def present_task(doc):
    from html import unescape
    from frappe.utils import strip_html
    return {"id": doc.name, "subject": doc.subject, "status": doc.status, "project": doc.project,
        "version": version_of(doc), "description": unescape(strip_html((doc.description or "").replace("<br>", "\n")))}


def _page_scope(actor, company, project, collection):
    rows = duty_rows(actor, company, project)
    duties = [{key: str(value) for key, value in row.items()} for row in rows]
    return {"user": actor.user, "person": actor.person_id, "company": company,
        "project": project, "collection": collection, "duties": digest(duties)}


def _query_page(doctype, *, filters, order_field, ascending, limit, last, native_permissions=True):
    table = frappe.qb.DocType(doctype)
    query = frappe.qb.get_query(doctype, fields=["name", order_field], filters=filters,
        order_by=f"{order_field} {'asc' if ascending else 'desc'}, name {'asc' if ascending else 'desc'}",
        limit=limit + 1, ignore_permissions=not native_permissions)
    if last:
        key = table[order_field]
        seek = ((key > last[0]) | ((key == last[0]) & (table.name > last[1]))) if ascending else ((key < last[0]) | ((key == last[0]) & (table.name < last[1])))
        query = query.where(seek)
    return query.run(as_dict=True)


def _exact_count(doctype, filters, native_permissions=True):
    query = frappe.qb.get_query(doctype, fields=[{"COUNT": "name", "as": "total"}], filters=filters, ignore_permissions=not native_permissions)
    return int(query.run(as_dict=True)[0].total)


def list_projects(company, limit=50, cursor=None, count_mode="none"):
    actor = current_actor()
    company = text(company, "Company")
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = _page_scope(actor, company, None, "projects")
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    ids = project_ids(actor, company)
    if not ids:
        return page_result([], has_more=False, last=None, scope=scope, limit=limit, count_mode=count_mode, total=0 if count_mode == "exact" else None)
    filters = {"company": company, "name": ["in", ids]}
    rows = _query_page("Project", filters=filters, order_field="project_name", ascending=True, limit=limit, last=last)
    page = rows[:limit]
    items = [present_project(require_project(company, row.name, actor=actor)) for row in page]
    last_key = [page[-1].project_name, page[-1].name] if page else None
    return page_result(items, has_more=len(rows) > limit, last=last_key, scope=scope, limit=limit,
        count_mode=count_mode, total=_exact_count("Project", filters) if count_mode == "exact" else None)


def read_project(company, project):
    actor = current_actor()
    return present_project(require_project(company, project, actor=actor), actor)


def list_tasks(company, project, limit=50, cursor=None, count_mode="none"):
    actor = current_actor()
    require_project(company, project, actor=actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = _page_scope(actor, company, project, "tasks")
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    filters = {"project": project}
    rows = _query_page("Task", filters=filters, order_field="creation", ascending=False, limit=limit, last=last)
    page = rows[:limit]
    last_key = [str(page[-1].creation), page[-1].name] if page else None
    return page_result([present_task(frappe.get_doc("Task", row.name)) for row in page], has_more=len(rows) > limit,
        last=last_key, scope=scope, limit=limit, count_mode=count_mode,
        total=_exact_count("Task", filters) if count_mode == "exact" else None)


def create_task(company, project, operation_id, expected_version, subject, description="", *, guard=None):
    subject = text(subject, "Task subject", 140)
    description = text(description, "Task description", 12000, required=False)
    # Task description is plain authored text for R0; no caller-supplied executable HTML.
    from html import escape
    rendered_description = escape(description).replace("\n", "<br>")
    expected_version = parse_version(expected_version)
    payload = {"expected_version": expected_version, "subject": subject, "description": description}

    def effect(actor, record):
        if version_of(record) != expected_version:
            raise DomainError("stale_version", "This project changed. Refresh it before saving the task.", 412)
        task = frappe.get_doc({"doctype": "Task", "project": project, "subject": subject,
            "description": rendered_description, "status": "Open"})
        task.insert(ignore_permissions=True)
        record.db_set("modified", now_datetime(), update_modified=False)
        append_event(actor=actor, company=company, project=project, event="task.created",
            subject_type="Task", subject_id=task.name, operation_id=operation_id,
            details={"subject": subject, "status": "Open"})
        return {"task": present_task(task), "project_version": version_of(record)}

    return run_command(company=company, project=project, operation_id=operation_id, command="task.create",
        payload=payload, ability="task.create", effect=effect, guard=guard)


def history(company, project, limit=50, cursor=None, count_mode="none"):
    actor = current_actor()
    require_project(company, project, actor=actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = _page_scope(actor, company, project, "history")
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    filters = {"company": company, "project": project}
    rows = _query_page("Cipher History Event", filters=filters, order_field="creation", ascending=False, limit=limit, last=last, native_permissions=False)
    page = rows[:limit]
    last_key = [str(page[-1].creation), page[-1].name] if page else None
    return page_result([present_event(frappe.get_doc("Cipher History Event", row.name)) for row in page], has_more=len(rows) > limit,
        last=last_key, scope=scope, limit=limit, count_mode=count_mode,
        total=_exact_count("Cipher History Event", filters, native_permissions=False) if count_mode == "exact" else None)
