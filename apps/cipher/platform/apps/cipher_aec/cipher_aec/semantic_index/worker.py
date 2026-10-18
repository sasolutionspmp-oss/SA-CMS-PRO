"""Dedicated worker entrypoints; never turn caller admission errors into success."""
from cipher_aec.api.errors import DomainError
from . import contracts as c


def _run(entry, requested_user, effect):
    from cipher_aec.governance.context import require_effects_enabled
    from .store import dedicated_worker
    from .transactions import worker_user
    # Admission is outside the DomainError handler: no caller transaction/user
    # mutation, rollback, or ordinary returned value on an unsafe invocation.
    with dedicated_worker(entry=entry) as transaction:
        try:
            with worker_user(requested_user):
                require_effects_enabled()
                return effect()
        except DomainError as error:
            # Frappe.execute_job commits ordinary returned values. Roll back our
            # complete owned transaction (including pending callbacks) first.
            transaction.abort(error)
            return {'status': 'blocked', 'error_code': error.code,
                    'connected_qualification': False}


def rebuild(scope, operation_id, requested_user):
    from cipher_aec.governance.context import current_actor
    from .configuration import service
    c.scope(scope)
    c.uid(operation_id)
    c.identifier(requested_user)
    return _run('rebuild', requested_user,
                lambda: service(durable=True).run(scope, operation_id, current_actor()))


def reconcile(scope, requested_user, offset=None):
    from cipher_aec.governance.context import current_actor
    from .configuration import service
    c.scope(scope)
    c.identifier(requested_user)
    if offset is not None:
        c.uid(offset)
    return _run('reconcile', requested_user,
                lambda: service(durable=True).reconcile(scope, current_actor(), offset=offset))
