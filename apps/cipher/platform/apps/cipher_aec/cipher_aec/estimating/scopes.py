"""Explicit Company execution context shared by canonical EST and takeoff.

A null Project never selects Company scope. Only a literal Company entrypoint or
an explicitly scoped immutable record can activate that path. Project execution
keeps its original payloads and command/hash namespace.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from cipher_aec.api.errors import DomainError

_active = ContextVar("cipher_estimating_explicit_scope", default=None)


@dataclass(frozen=True)
class Scope:
    scope_type: str
    company: str
    project: str | None

    def require(self, ability, actor=None, *, lock=False):
        from cipher_aec.governance.context import require_company, require_project
        if self.scope_type == "Company":
            return require_company(self.company, ability="company.read" if ability == "project.read" else ability, actor=actor, lock=lock)
        return require_project(self.company, self.project, ability=ability, actor=actor, lock=lock)

    def matches(self, record):
        return record.get("scope_type", "Project") == self.scope_type and record.get("company") == self.company and record.get("project") == self.project

    def fields(self):
        return {"scope_type": "Company"} if self.scope_type == "Company" else {}

    def manifest_scope(self):
        value = {"company": self.company, "project": self.project}
        return {"scope_type": "Company", **value} if self.scope_type == "Company" else value

    def where(self):
        if self.scope_type == "Company":
            return "scope_type='Company' AND company=%s AND (project IS NULL OR project='')", [self.company]
        return "company=%s AND project=%s", [self.company, self.project]

    def authority(self, actor):
        from cipher_aec.governance.context import authority_fingerprint, company_authority_fingerprint
        return company_authority_fingerprint(actor, self.company) if self.scope_type == "Company" else authority_fingerprint(actor, self.company, self.project)


def active():
    return _active.get()


def current(company, project):
    active = _active.get()
    if active is None:
        if project is None:
            raise DomainError("invalid_scope", "A null Project does not select Company scope. Use the explicit Company interface.", 422)
        return Scope("Project", company, project)
    if active.company != company or active.project != project:
        raise DomainError("invalid_scope", "The explicit estimation scope does not match this operation.", 422)
    return active


@contextmanager
def activate(scope_type, company, project):
    from cipher_aec.api.contracts import text
    company = text(company, "Company")
    if scope_type == "Company" and project is None:
        scope = Scope("Company", company, None)
    elif scope_type == "Project" and project is not None:
        scope = Scope("Project", company, text(project, "Project"))
    else:
        raise DomainError("invalid_scope", "Declare literal Project or Company scope with its exact aggregate.", 422)
    previous = _active.get()
    if previous is not None and previous != scope:
        raise DomainError("invalid_scope", "An operation cannot change its active estimation scope.", 422)
    token = _active.set(scope)
    try:
        yield scope
    finally:
        _active.reset(token)


@contextmanager
def recorded(value):
    with activate(value.get("scope_type", "Project"), value["company"], value["project"]) as scope:
        yield scope


def require(company, project, ability="project.read", actor=None, lock=False):
    return current(company, project).require(ability, actor, lock=lock)


def command(*, company, project, **kwargs):
    from cipher_aec.governance.commands import run_command, run_company_command
    scope = current(company, project)
    if scope.scope_type == "Company":
        # Shared command owns person/Company locks and completed-receipt replay.
        # Plan only a new effect, before any source may acquire native masters.
        effect = kwargs["effect"]
        if kwargs["command"] != "estimate.unit.register.v1":
            def prepared_effect(actor, aggregate):
                from .lockplan import command_plan, prepared
                plan = command_plan(company, actor, kwargs["command"], kwargs["payload"])
                with prepared(plan, actor, company):
                    return effect(actor, aggregate)
            kwargs = {**kwargs, "effect": prepared_effect}
        return run_company_command(company=company, **kwargs)
    return run_command(company=company, project=project, **kwargs)


def event(*, company, project, **kwargs):
    from cipher_aec.governance.history import append_event, append_company_event
    if current(company, project).scope_type == "Company":
        return append_company_event(company=company, **kwargs)
    return append_event(company=company, project=project, **kwargs)


def approval_effect(*, action, subject_id, packet_id):
    from cipher_aec.governance.approvals import require_approval_effect
    active = _active.get()
    values = {"scope_type": "Company"} if active and active.scope_type == "Company" else {}
    return require_approval_effect(action=action, subject_id=subject_id, packet_id=packet_id, **values)


def record_scope(function):
    """Controllers authorize the literal immutable scope before any scoped read."""
    from functools import wraps
    import json
    @wraps(function)
    def wrapped(doc, *args, **kwargs):
        from cipher_aec.governance.context import require_trusted_write
        require_trusted_write()
        try:
            value = json.loads(doc.data_json)
            if type(value) is not dict or value.get("scope_type", "Project") != (doc.get("scope_type") or "Project"):
                raise ValueError
        except (TypeError, ValueError):
            raise DomainError("invalid_scope", "Canonical JSON and metadata must declare the same exact scope.", 422) from None
        with recorded(value):
            return function(doc, *args, **kwargs)
    return wrapped


def company_request():
    """Frappe filters unknown kwargs; reject namespace override attempts first."""
    import frappe
    if getattr(frappe.local, "request", None) and {"project", "scope_type"}.intersection(frappe.form_dict or {}):
        raise DomainError("invalid_scope", "Company estimating routes do not accept Project or scope overrides.", 422)
