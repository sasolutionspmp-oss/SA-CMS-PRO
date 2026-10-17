"""Opt-in DOC-04 boundary; global catalog/schema registration is a fragment.

These functions are not whitelisted. The local integration writer composes
them with the established v1 transport, auth, CSRF and exception envelope.
"""
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,assert_synthetic_site,require_effects_enabled
from .configuration import service
from .contracts import closed,scope as exact_scope

def call(name,body):
    if name not in CONTRACTS:
        raise DomainError('not_found','This semantic operation is not available.',404)
    closed(body,CONTRACTS[name]['fields']); exact_scope(body['scope'])
    assert_synthetic_site(); actor=current_actor()
    if name in ('prepare','cancel'): require_effects_enabled()
    backend=service()
    if name=='prepare':
        result=backend.prepare(body['scope'],body['sources'],body['operation_id'],actor)
        # Publication only after the request transaction commits. Disabled
        # unless the local integration explicitly registers this API entry.
        import frappe
        frappe.enqueue('cipher_aec.semantic_index.worker.rebuild',queue='long',enqueue_after_commit=True,
                       scope=body['scope'],operation_id=body['operation_id'],requested_user=actor.user)
        return result
    if name=='cancel': return backend.cancel(body['scope'],body['operation_id'],actor)
    if name=='status': return backend.status(body['scope'],body['operation_id'],actor)
    return backend.query(body['scope'],body['question'],actor,limit=body['limit'])

CONTRACTS={
    'prepare':{'method':'POST','ability':'document.semantic.manage','fields':{'scope','sources','operation_id'}},
    'cancel':{'method':'POST','ability':'document.semantic.manage','fields':{'scope','operation_id'}},
    'status':{'method':'POST','ability':'document.read','fields':{'scope','operation_id'}},
    'query':{'method':'POST','ability':'document.read','fields':{'scope','question','limit'}},
}
