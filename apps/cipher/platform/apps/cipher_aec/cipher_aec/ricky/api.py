"""Same-origin session endpoints for the embedded Ricky panel."""

from functools import wraps

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.api.transport import endpoint
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.context import current_actor

from .adapter import ConnectionProfile, resolve_adapter
from .backend import FrappeBackend
from .contracts import RickyError
from .engine import RickyService
from .storage import FrappeStore


def build_service(*, worker=False):
    # The browser cannot choose a model, endpoint, adapter, secret or resource limit.
    raw = frappe.conf.get("cipher_ricky_connection") or {}
    allowed = set(ConnectionProfile.__dataclass_fields__)
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise DomainError("invalid_configuration", "The local Ricky connection profile is invalid.", 503)
    profile = ConnectionProfile(**raw)
    return RickyService(FrappeStore(worker=worker), FrappeBackend(), resolve_adapter(profile), profile=profile)


def build_run_service(run_id, *, worker=False):
    # Current native metadata and immutable JSON must agree BEFORE any model
    # profile/adapter/default registry construction, including malformed rows.
    run = FrappeStore(worker=worker).get_scoped("run", run_id)
    if run.get("scope_type", "Project") == "Company":
        if run.get("request_kind") == "deterministic-proposal-v1":
            from .company_proposal_service import build_service as build_proposal_service
            return build_proposal_service(worker=worker)
        if run.get("request_kind") != "deterministic-read-v1":
            raise RickyError("not_found", "This Company Ricky request kind is unavailable.")
        from .company_service import build_service as build_company_service
        return build_company_service(worker=worker)
    return build_service(worker=worker)


def _project_run_service(run_id):
    service = build_run_service(run_id)
    if not isinstance(service, RickyService) or type(service) is not RickyService:
        raise RickyError("not_found", "Use the explicit Company read endpoint for this record.")
    return service


def _project_proposal_service(proposal_id):
    proposal = FrappeStore().get_scoped("proposal", proposal_id)
    if proposal.get("scope_type", "Project") != "Project":
        raise RickyError("not_found", "Company deterministic reads have no Proposed Changes.")
    return _project_run_service(proposal["run_id"])


def _errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except RickyError as error:
            status = {"not_found": 404, "forbidden": 403, "forbidden_tool": 403, "operation_conflict": 409,
                      "stale_source": 412, "stale_authority": 412, "stale_proposal": 412,
                      "expired_proposal": 409, "rate_limit": 429, "upstream_unavailable": 503, "invalid_configuration": 503}.get(error.code, 422)
            raise DomainError(error.code, error.message, status) from None
    return wrapped


@endpoint()
@_errors
def connection_status():
    current_actor()
    return build_service().adapter.status()


def _dispatch(identifier):
    from cipher_aec.governance.context import require_effects_enabled
    require_effects_enabled()
    def enqueue_hint():
        try:
            require_effects_enabled()
            # Catch the actual Redis call after commit, not merely registration
            # of Frappe's deferred callback. A queue outage cannot undo the run.
            frappe.enqueue("cipher_aec.ricky.worker.process_run", run_id=identifier, enqueue_after_commit=False,
                           job_id="cipher-ricky-" + identifier, queue="short", timeout=360)
        except Exception:
            frappe.logger("cipher_ricky").warning("Ricky queue hint failed; durable run remains queued")
    frappe.db.after_commit.add(enqueue_hint)


@endpoint(methods=["POST"])
@_errors
def start_run(company, project, question, operation_id):
    service = build_service()
    result = run_command(company=company, project=project, operation_id=operation_id, command="ricky.start.v1",
                         payload={"question": question, "version": 1}, ability="ricky.run",
                         effect=lambda actor, record: service.start(company, project, question, operation_id))
    if not result["operation"]["replayed"]:
        _dispatch(result["id"])
    return result


@endpoint()
@_errors
def get_run(run_id):
    return _project_run_service(run_id).get_run(run_id)


@endpoint()
@_errors
def run_events(run_id):
    return {"items": _project_run_service(run_id).events(run_id)}


@endpoint(methods=["POST"])
@_errors
def cancel_run(run_id, operation_id):
    service = _project_run_service(run_id)
    run = service.store.get("run", run_id)
    service._check(run, revision=False)
    result = run_command(company=run["company"], project=run["project"], operation_id=operation_id,
                         command="ricky.cancel.v1", payload={"run_id": run_id}, ability="ricky.run",
                         effect=lambda actor, record: service.cancel(run_id))
    if not result["operation"]["replayed"]:
        def cancel_adapter():
            try:
                service.adapter.cancel(run_id)
            except Exception:
                frappe.logger("cipher_ricky").warning("Ricky adapter cancellation unavailable; durable cancellation remains recorded")
        frappe.db.after_commit.add(cancel_adapter)
    return result


@endpoint()
@_errors
def get_proposal(proposal_id):
    return _project_proposal_service(proposal_id).get_proposal(proposal_id)


@endpoint(methods=["POST"])
@_errors
def commit_proposal(proposal_id, proposal_version, operation_id):
    if isinstance(proposal_version, str) and proposal_version.isdecimal():
        proposal_version = int(proposal_version)
    return _project_proposal_service(proposal_id).commit_proposal(proposal_id, proposal_version, operation_id)
