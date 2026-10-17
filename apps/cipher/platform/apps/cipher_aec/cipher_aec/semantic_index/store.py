"""Frappe-backed compare-and-swap checkpoints, without network inside DB locks.

Durable mode is reserved for a dedicated worker transaction. Request handlers
enqueue after commit; they must not commit another command's transaction.
"""
from contextvars import ContextVar
from contextlib import contextmanager
import json
import frappe
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write, require_trusted_write
from .contracts import corpus_key, checkpoint

DOCTYPE='Cipher Semantic Corpus'
MAX_STATE_BYTES=8*1024*1024
_plan=ContextVar('semantic_checkpoint_plan',default=None)
_worker=ContextVar('semantic_dedicated_worker',default=False)

def require_clean_worker():
    if not _worker.get() or getattr(frappe.db,'transaction_writes',None)!=0:
        raise DomainError('semantic_worker_required','Semantic checkpoints require a clean dedicated worker transaction.',409)

@contextmanager
def dedicated_worker():
    # Private process/queue entry boundary, never exposed as an RPC option.
    if getattr(frappe.db,'transaction_writes',None)!=0:
        raise DomainError('semantic_worker_required','Start semantic work in a clean dedicated worker transaction.',409)
    token=_worker.set(True)
    try: yield
    finally: _worker.reset(token)

def require_fresh_reads():
    # Pinned MariaDB/Frappe backend. Do not change isolation or commit a caller's
    # transaction to simulate freshness. Unsupported/repeatable snapshots refuse
    # work before plaintext leaves Cipher or a candidate is admitted.
    try: rows=frappe.db.sql('SELECT @@session.tx_isolation')
    except Exception:
        raise DomainError('semantic_unavailable','Current database read isolation cannot be verified.',503) from None
    if not isinstance(rows,(list,tuple)) or len(rows)!=1 or not isinstance(rows[0],(list,tuple)) or len(rows[0])!=1 or str(rows[0][0]).upper().replace('_','-').replace(' ','-')!='READ-COMMITTED':
        raise DomainError('semantic_unavailable','Semantic work requires current committed database reads.',503)

def validate_state(value):
    try: checkpoint(value)
    except (DomainError,TypeError,KeyError,ValueError,OverflowError):
        raise DomainError('semantic_integrity','The semantic checkpoint cannot be verified.',409) from None
    if len(canonical_json(value).encode())>MAX_STATE_BYTES:
        raise DomainError('semantic_capacity','The bounded semantic checkpoint is full.',409)
    return value

class FrappeStore:
    def __init__(self, *, durable=False):
        self.durable=durable
        if durable: require_clean_worker()

    def load(self,key):
        require_fresh_reads()
        # Direct bounded exact-name access, never an unscoped DocType list.
        if not frappe.db.exists(DOCTYPE,key): return None
        doc=frappe.get_doc(DOCTYPE,key)
        try: value=validate_state(json.loads(doc.data_json))
        except (TypeError,ValueError):
            raise DomainError('semantic_integrity','The semantic checkpoint cannot be read.',409) from None
        s=value['scope']
        if doc.name!=corpus_key(s,value['profile_id']) or doc.profile_id!=value['profile_id'] or doc.record_digest!=digest(value) or doc.company!=s['company'] or doc.scope_type!=s['scope_type'] or (doc.project or None)!=s['project'] or doc.state_version!=value['version']:
            raise DomainError('semantic_integrity','The native semantic checkpoint differs.',409)
        return value

    def save(self,key,expected,value):
        if self.durable: require_clean_worker()
        require_fresh_reads()
        validate_state(value)
        if key!=corpus_key(value['scope'],value['profile_id']) or value['version']!=expected+1:
            raise DomainError('semantic_integrity','The checkpoint version differs.',409)
        rows=frappe.db.sql('SELECT state_version FROM `tabCipher Semantic Corpus` WHERE name=%s FOR UPDATE',(key,))
        if (rows[0][0] if rows else 0)!=expected:
            raise DomainError('semantic_conflict','The semantic job changed. Refresh its status.',409)
        if rows: self.load(key)  # native digest/profile/scope drift under the row lock
        token=_plan.set((key,expected,digest(value)))
        try:
            with trusted_write():
                fields={'company':value['scope']['company'],'project':value['scope']['project'],
                        'scope_type':value['scope']['scope_type'],'state_version':value['version'],
                        'profile_id':value['profile_id'],'record_digest':digest(value),'data_json':canonical_json(value)}
                if rows:
                    doc=frappe.get_doc(DOCTYPE,key,for_update=True); doc.update(fields); doc.save(ignore_permissions=True)
                else:
                    frappe.get_doc({'doctype':DOCTYPE,'name':key,**fields}).insert(ignore_permissions=True,set_name=key)
            if self.durable: frappe.db.commit()
        finally: _plan.reset(token)

def require_checkpoint_write(doc,value):
    require_trusted_write(); validate_state(value)
    previous=0 if doc.is_new() else doc.get_doc_before_save().state_version
    if _plan.get()!=(doc.name,previous,digest(value)) or value['version']!=previous+1 or doc.name!=corpus_key(value['scope'],value['profile_id']):
        raise DomainError('semantic_command_required','Use the semantic index service.',403)
    for key in ('company','scope_type','project'):
        if (doc.get(key) or None)!=(value['scope'][key] or None):
            raise DomainError('semantic_integrity','The native semantic scope differs.',409)
    if doc.profile_id!=value['profile_id'] or doc.state_version!=value['version'] or doc.record_digest!=digest(value):
        raise DomainError('semantic_integrity','The semantic checkpoint indexes differ.',409)

def deny_native_access(*args,**kwargs): return False

def no_native_rows(*args,**kwargs): return '1=0'
