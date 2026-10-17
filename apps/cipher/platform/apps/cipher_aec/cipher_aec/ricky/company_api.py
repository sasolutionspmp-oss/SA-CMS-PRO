"""Explicit Company deterministic reads and prospective command history."""
from cipher_aec.api.transport import endpoint
from cipher_aec.governance.commands import run_company_command
from cipher_aec.governance.history import append_company_event

from .company_backend import START_COMMAND, CANCEL_COMMAND
from .company_contracts import DeterministicReadRequest
from .company_service import build_service, domain_errors


@endpoint(methods=["POST"])
@domain_errors
def start_read(company, request, operation_id):
    request = DeterministicReadRequest.from_value(request)
    service = build_service()
    def effect(actor, record):
        result = service.start_read(company, request.binding(), operation_id)
        append_company_event(actor=actor, company=company, event="ricky.company.read.start.accepted",
            subject_type="Cipher Ricky Run", subject_id=result["id"], operation_id=operation_id,
            details={"action": result["action"], "status": result["status"]})
        return result
    result = run_company_command(company=company, operation_id=operation_id, command=START_COMMAND,
        payload={"request": request.binding()}, ability="ricky.run", effect=effect)
    if not result["operation"]["replayed"]:
        from .api import _dispatch
        _dispatch(result["id"])
    return result


@endpoint()
@domain_errors
def get_run(company, run_id):
    return build_service().get_run(company, run_id)


@endpoint()
@domain_errors
def run_events(company, run_id):
    return {"items": build_service().events(company, run_id)}


@endpoint(methods=["POST"])
@domain_errors
def cancel_run(company, run_id, operation_id):
    service = build_service()
    def effect(actor, record):
        result = service.cancel(company, run_id)
        # An accepted Stop on an already terminal Run does not claim a new
        # cancellation or confer access to its sources/result.
        append_company_event(actor=actor, company=company, event="ricky.company.read.stop.accepted",
            subject_type="Cipher Ricky Run", subject_id=result["id"], operation_id=operation_id,
            details={"status": result["status"], "cancel_requested": result["cancel_requested"]})
        return result
    return run_company_command(company=company, operation_id=operation_id, command=CANCEL_COMMAND,
        payload={"run_id": run_id}, ability="ricky.run", effect=effect)
