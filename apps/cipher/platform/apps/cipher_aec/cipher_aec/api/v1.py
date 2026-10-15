import frappe

from cipher_aec.governance.context import current_actor, duty_rows
from cipher_aec.governance.commands import read_operation
from cipher_aec.projects import service
from .transport import endpoint


@endpoint()
def session():
    from frappe.sessions import get_csrf_token
    actor = current_actor()
    rows = duty_rows(actor)
    companies = sorted({row.company for row in rows if row.ability == "project.read"})
    return {"authenticated": True, "user": actor.user, "person": {"id": actor.person_id, "display_name": actor.display_name},
        "companies": [{"id": company, "name": company} for company in companies],
        "capabilities": sorted({row.ability for row in rows}), "site_mode": "synthetic", "csrf_token": get_csrf_token()}


@endpoint()
def projects(company, limit=50, cursor=None, count_mode="none"):
    return service.list_projects(company, limit, cursor, count_mode)


@endpoint()
def project(company, project):
    return service.read_project(company, project)


@endpoint()
def tasks(company, project, limit=50, cursor=None, count_mode="none"):
    return service.list_tasks(company, project, limit, cursor, count_mode)


@endpoint()
def history(company, project, limit=50, cursor=None, count_mode="none"):
    return service.history(company, project, limit, cursor, count_mode)


@endpoint()
def operation(company, project, operation_id):
    return read_operation(company, project, operation_id)


@endpoint(methods=["POST"])
def create_task(company, project, operation_id, expected_version=None, subject=None, description=""):
    return service.create_task(company, project, operation_id, expected_version, subject, description)
