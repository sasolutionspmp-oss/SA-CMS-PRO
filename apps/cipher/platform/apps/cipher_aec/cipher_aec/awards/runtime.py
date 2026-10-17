"""Selected native profile and receipt-safe literal award callback isolation."""
from contextlib import contextmanager
from contextvars import ContextVar
from types import CodeType
import frappe
from cipher_aec.api.errors import DomainError

from .runtime_profile import PROFILE, require_native_profile as _require_native_profile

_boundary=ContextVar('cipher_award_command_callback_boundary',default=None)
MANAGERS=('before_commit','after_commit','before_rollback','after_rollback')
LOCAL_QUEUES=('_webhook_queue','_realtime_log')


class AwardCallbackBoundaryError(DomainError):
    """Raised only after an actual full rollback; no savepoint may remain."""


def require_native_profile():
    from .runtime_catalog import require_catalog
    require_catalog()
    return _require_native_profile()


def quiet_award_write(doc):
    """Suppress only native deferred UI notices for this exact award stage.

    Every write still runs normal validation/hooks and the strict callback-tail
    check. Ordinary commands and reads do not acquire a suppression scope.
    """
    state=_boundary.get()
    if state is None or state['stage'] is None:return doc
    from .runtime_profile import TARGETS
    stage=state['stage']
    current_db=frappe.db._get_current_object() if hasattr(frappe.db,'_get_current_object') else frappe.db
    if current_db is not stage['db']:
        raise AwardCallbackBoundaryError('award_callback_boundary_changed','The award transaction changed before its native write.',503)
    if doc.doctype not in TARGETS or doc.get('company')!=state['company']:
        raise DomainError('award_write_unqualified','Only the exact Company award write catalog may suppress native UI notices.',503)
    if not any(doc is existing for existing in stage['write_documents']):stage['write_documents'].append(doc)
    doc.flags.notify_update=False
    return doc


def _contents(manager):
    values=manager.cut(0)
    for callback in values:manager.add(callback)
    return tuple(values)


def _managers():return {name:getattr(frappe.db,name) for name in MANAGERS}


def _local_queue(name):return getattr(frappe.local,name,None)


def begin_callback_stage(*,company,operation_id,packet_id,award_revision_id,plan_digest):
    state=_boundary.get()
    if not state or state['company']!=company or state['operation_id']!=operation_id or state['stage'] is not None:
        raise DomainError('award_callback_boundary_required','Award allocation requires its single receipt-safe Company command boundary.',403)
    managers=_managers()
    state['stage']={'packet_id':packet_id,'award_revision_id':award_revision_id,'plan_digest':plan_digest,
        'db':frappe.db._get_current_object() if hasattr(frappe.db,'_get_current_object') else frappe.db,
        'managers':managers,'lengths':{name:len(manager) for name,manager in managers.items()},
        'prefixes':{name:_contents(manager) for name,manager in managers.items()},
        'queues':{name:_local_queue(name) for name in LOCAL_QUEUES},
        'queue_lengths':{name:len(_local_queue(name)) if _local_queue(name) is not None else 0 for name in LOCAL_QUEUES},
        'queue_prefixes':{name:tuple(id(item) for item in _local_queue(name)) if type(_local_queue(name)) is list else () for name in LOCAL_QUEUES},
        'write_documents':[]}


def _native_cache_invalidator(callback,stage):
    from frappe.model.document import clear_document_cache
    allowed={code for code in clear_document_cache.__code__.co_consts if isinstance(code,CodeType) and code.co_name=='clear_in_redis'}
    if (not any(getattr(callback,'__code__',None) is code for code in allowed)
            or getattr(callback,'__globals__',None) is not clear_document_cache.__globals__):return False
    names=callback.__code__.co_freevars;cells=getattr(callback,'__closure__',None) or ()
    if names!=('doctype','name') or len(cells)!=2:return False
    doctype,name=(cell.cell_contents for cell in cells)
    if type(doctype) is not str or type(name) is not str or not name:return False
    # Name may be assigned by native autoname after the exact write object was
    # registered. Never qualify a doctype-wide or arbitrary-name invalidator.
    return any(doc.doctype==doctype and doc.name==name for doc in stage['write_documents'])


def _known_invalidator(callback,stage):
    # Public CallbackManager tail APIs are used; only this inspected nested code
    # identity may survive success. No module-name/caller boolean allowlist.
    from cipher_aec.documents import provenance
    allowed={code for code in provenance._watch_transaction.__code__.co_consts if isinstance(code,CodeType) and code.co_name=='invalidate'}
    if (not any(getattr(callback,'__code__',None) is code for code in allowed)
            or getattr(callback,'__globals__',None) is not provenance._watch_transaction.__globals__):return _native_cache_invalidator(callback,stage)
    cells=getattr(callback,'__closure__',None) or ()
    return len(cells)==1 and type(cells[0].cell_contents) is dict and cells[0].cell_contents.get('valid') is False and not cells[0].cell_contents.get('authorized')


def _tails(stage,*,discard=False):
    current_db=frappe.db._get_current_object() if hasattr(frappe.db,'_get_current_object') else frappe.db
    snapshots={name:_contents(manager) for name,manager in stage['managers'].items()}
    if current_db is not stage['db'] or any(getattr(frappe.db,n) is not m or len(snapshots[n])<stage['lengths'][n]
            or any(actual is not expected for actual,expected in zip(snapshots[n],stage['prefixes'][n])) for n,m in stage['managers'].items()):
        raise AwardCallbackBoundaryError('award_callback_boundary_changed','The award transaction callback boundary changed. Nothing was committed.',503)
    tails={name:snapshots[name][stage['lengths'][name]:] for name in MANAGERS}
    cache_callbacks={id(callback):callback for tail in tails.values() for callback in tail if _native_cache_invalidator(callback,stage)}
    for callback in cache_callbacks.values():
        if (any(callback is value for manager in ('before_commit','before_rollback') for value in tails[manager])
                or not all(any(callback is value for value in tails[manager]) for manager in ('after_commit','after_rollback'))):
            raise AwardCallbackBoundaryError('award_cache_callback_unqualified','A native cache callback must retain its exact commit/rollback pair.',503)
    # A rollback callback can own an actual filesystem cleanup. Never discard
    # an unfamiliar one as though it were a provenance no-op: the supported
    # full rollback must run it and suppress every pending commit intent.
    if any(not _known_invalidator(callback,stage) for name in ('before_rollback','after_rollback') for callback in tails[name]):
        raise AwardCallbackBoundaryError('award_rollback_callback_unqualified','An unexpected native cleanup requires full transaction rollback.',503)
    unknown=any(not _known_invalidator(callback,stage) for tail in tails.values() for callback in tail)
    # Validate the whole boundary before cutting any callback or local tail.
    for name in LOCAL_QUEUES:
        old=stage['queues'][name];current=_local_queue(name);count=stage['queue_lengths'][name]
        if old is not None and (current is not old or type(current) is not list or len(current)<count or tuple(id(item) for item in current[:count])!=stage['queue_prefixes'][name]):
            raise AwardCallbackBoundaryError('award_callback_boundary_changed','The award local callback queue changed. Nothing was committed.',503)
        if current is not None and type(current) is not list:
            raise AwardCallbackBoundaryError('award_callback_boundary_changed','The native local callback queue is unsupported. Nothing was committed.',503)
        if current is not None and len(current)>count:unknown=True
    if discard:
        # Native deletion ran before possible cache repopulation. Re-invalidate
        # only these exact derived keys before the caller's SQL savepoint
        # rollback; perform no own cache reads afterward. Keep earlier tails.
        try:
            for callback in cache_callbacks.values():callback()
        except Exception as error:
            raise AwardCallbackBoundaryError('award_cache_cleanup_failed','Native cache cleanup requires full transaction rollback.',503) from error
        for name,manager in stage['managers'].items():manager.truncate(stage['lengths'][name])
        for name in LOCAL_QUEUES:
            current=_local_queue(name)
            if current is not None:del current[stage['queue_lengths'][name]:]
    return unknown


def _full_rollback(stage):
    """Close both transactions and deferred local intents on this fatal branch.

    CallbackManager.run pops each callback before invoking it. If one cleanup
    throws, the next supported rollback continues remaining cleanup and reaches
    the SQL rollback. A bounded pathological callback chain closes the DB.
    """
    current=frappe.db._get_current_object() if hasattr(frappe.db,'_get_current_object') else frappe.db
    errors=[]
    databases=[stage['db']]+([current] if current is not stage['db'] else [])
    try:
        for db in databases:
            # No unbounded retry of a callback that appends more callbacks.
            budget=sum(len(getattr(db,name)) for name in ('before_rollback','after_rollback'))+2
            for attempt in range(budget):
                try:db.rollback();break
                except Exception as error:
                    errors.append(error)
                    if attempt==budget-1:
                        try:db.close()
                        except Exception as close_error:errors.append(close_error)
    finally:
        # Whole-transaction rollback invalidates prior local intents too. This
        # differs deliberately from ordinary savepoint-tail preservation.
        for name in LOCAL_QUEUES:
            queue=_local_queue(name)
            if type(queue) is list:queue.clear()
            elif queue is not None:setattr(frappe.local,name,[])
    if errors:
        raise AwardCallbackBoundaryError('award_rollback_cleanup_failed','The award transaction was aborted during native cleanup. No savepoint may be reused.',503) from errors[0]


@contextmanager
def command_boundary(*,company,operation_id):
    """NEW Company approval.execute only; lazily active for the literal award.

    Outer owner encloses logical-operation finally AND command receipt insertion.
    No-op for other actions; it neither creates an intent nor chooses a callback.
    """
    if _boundary.get() is not None:raise DomainError('nested_award_boundary','Award command callback scopes cannot nest.',409)
    state={'company':company,'operation_id':operation_id,'stage':None};token=_boundary.set(state)
    try:
        try:
            yield
            if state['stage'] is not None and _tails(state['stage']):
                raise DomainError('award_callback_unqualified','A native callback or local business intent is outside the qualified award profile.',503)
        except BaseException:
            if state['stage'] is not None:
                try:_tails(state['stage'],discard=True)
                except AwardCallbackBoundaryError:
                    _full_rollback(state['stage'])
                    raise
            raise
    finally:_boundary.reset(token)
