"""Fixed Company distribution routes; every delivery is explicitly a fixture."""
from cipher_aec.api.transport import endpoint
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_company
from . import distribution as service


@endpoint(methods=["POST"])
def create_instruction(company, issue_id, recipient_ids, subject, body, profile_id, operation_id):
    return service.create_instruction(company, issue_id, recipient_ids, subject, body, profile_id, operation_id)


@endpoint()
def get_instruction(company, instruction_id):
    from cipher_aec.api.contracts import digest
    value = service.read("instruction", instruction_id, company)
    return {"instruction": value, "version": digest(value)}


@endpoint()
def get_dispatch(company, dispatch_id):
    return service.get_dispatch(company, dispatch_id)


@endpoint()
def get_recipient_delivery(company, dispatch_id, recipient_id):
    value = service.get_dispatch(company, dispatch_id)
    for row in value["deliveries"]:
        if row["recipient_id"] == recipient_id:
            return row
    raise DomainError("not_found", "This recipient delivery is not available.", 404)


@endpoint()
def list_dispatches(company, issue_id, limit=50, cursor=None, count_mode="none"):
    return service.list_dispatches(company, issue_id, limit, cursor, count_mode)


@endpoint(methods=["POST"])
def cancel_dispatch(company, dispatch_id, reason, operation_id):
    return service.cancel_dispatch(company, dispatch_id, reason, operation_id)


@endpoint()
def profiles(company):
    require_company(company, ability="commercial.read", actor=current_actor())
    return {"items": [service.profile(require_enabled=False)], "live_transmission": False}


@endpoint()
def recipient_choices(company, issue_id):
    return service.recipient_choices(company, issue_id)


@endpoint()
def list_instructions(company, issue_id=None, limit=50, cursor=None, count_mode="none"):
    return service.list_instructions(company, issue_id, limit, cursor, count_mode)
