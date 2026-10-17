"""Dedicated worker transactions only; no hooks/scheduler are auto-enabled."""
from cipher_aec.api.errors import DomainError
from . import contracts as c

def rebuild(scope,operation_id,requested_user):
    import frappe
    from cipher_aec.governance.context import current_actor,require_effects_enabled
    from .configuration import service
    from .store import dedicated_worker
    c.scope(scope); c.uid(operation_id); c.identifier(requested_user)
    previous=frappe.session.user
    try:
        frappe.set_user(requested_user)
        require_effects_enabled()
        with dedicated_worker():
            backend=service(durable=True)
            # run binds the job's exact original user/person and refreshes duties.
            return backend.run(scope,operation_id,current_actor())
    except DomainError as error:
        # Frappe can retain this safe code without question/source/provider body.
        return {'status':'blocked','error_code':error.code,'connected_qualification':False}
    finally: frappe.set_user(previous)

def reconcile(scope,requested_user,offset=None):
    import frappe
    from cipher_aec.governance.context import current_actor,require_effects_enabled
    from .configuration import service
    from .store import dedicated_worker
    c.scope(scope); c.identifier(requested_user)
    if offset is not None: c.uid(offset)
    previous=frappe.session.user
    try:
        frappe.set_user(requested_user); require_effects_enabled()
        with dedicated_worker():
            return service(durable=True).reconcile(scope,current_actor(),offset=offset)
    except DomainError as error:
        return {'status':'blocked','error_code':error.code,'connected_qualification':False}
    finally: frappe.set_user(previous)
