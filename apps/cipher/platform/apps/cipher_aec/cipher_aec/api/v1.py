import frappe

from cipher_aec.governance.context import current_actor, duty_rows, company_duty_rows, require_company, require_project
from cipher_aec.governance.commands import read_operation
from cipher_aec.projects import service
from .transport import endpoint


@endpoint()
def session():
    from frappe.sessions import get_csrf_token
    actor = current_actor()
    rows = duty_rows(actor)
    company_rows = company_duty_rows(actor)
    from .errors import DomainError
    project_companies, direct_companies = set(), set()
    for row in rows:
        if row.ability != "project.read":
            continue
        try:
            require_project(row.company, row.project, actor=actor)
            project_companies.add(row.company)
        except DomainError as error:
            if error.status not in {403,404}:
                raise
    for company in sorted({row.company for row in company_rows if row.ability == "company.read"}):
        try:
            require_company(company, actor=actor)
            direct_companies.add(company)
        except DomainError as error:
            if error.status not in {403,404}:
                raise
    companies = sorted(project_companies | direct_companies)
    return {"authenticated": True, "user": actor.user, "person": {"id": actor.person_id, "display_name": actor.display_name},
        "companies": [{"id": company, "name": company} for company in companies],
        "capabilities": sorted({row.ability for row in rows + company_rows}),
        "company_scopes": [{"company": company, "capabilities": sorted({row.ability for row in company_rows if row.company == company})} for company in sorted(direct_companies)], "site_mode": "synthetic", "csrf_token": get_csrf_token()}


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
