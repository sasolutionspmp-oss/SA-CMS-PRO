"""Private Frappe persistence and exact canonical receipt lookup."""
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write,require_trusted_write

KINDS={'device':'Cipher Field Offline Device','capture':'Cipher Field Offline Capture','event':'Cipher Field Offline Event'}
INDEXES=('device_id','capture_id','owner_person','revision_number','last_event')
_plan=ContextVar('field_offline_exact_write',default=None)
_operation=ContextVar('field_offline_operation',default=None)

def raw(kind,name,*,lock=False,optional=False):
    try: doc=frappe.get_doc(KINDS[kind],name,for_update=lock)
    except frappe.DoesNotExistError:
        if optional:return None
        raise DomainError('not_found','This offline capture is not available.',404) from None
    try: value=json.loads(doc.data_json)
    except (TypeError,ValueError):raise DomainError('field_offline_integrity','The offline record cannot be decoded.',409) from None
    from .records import validate_record
    validate_record(kind,value)
    if doc.name!=value['id'] or doc.record_digest!=digest(value):raise DomainError('field_offline_integrity','The offline record identity or digest differs.',409)
    for key in ('company','project','scope_type','author_person','status',*INDEXES):
        actual,expected=doc.get(key),value.get(key)
        if key=='revision_number' and key not in value and type(actual) is int and actual==0:actual=None
        if actual!=expected and not(actual in (None,'') and expected is None):raise DomainError('field_offline_integrity','The native offline indexes differ.',409)
    return value

def write(kind,value,*,old=None):
    token=_plan.set((kind,value['id'],digest(value),digest(old) if old else None))
    try:
        with trusted_write():
            fields={k:value.get(k) for k in INDEXES}
            fields.update(company=value['company'],project=value['project'],scope_type='Project',author_person=value['author_person'],status=value['status'],record_digest=digest(value),data_json=canonical_json(value))
            if old is None:frappe.get_doc({'doctype':KINDS[kind],'name':value['id'],**fields}).insert(ignore_permissions=True,set_name=value['id'])
            else:
                doc=frappe.get_doc(KINDS[kind],value['id'],for_update=True);doc.update(fields);doc.save(ignore_permissions=True)
    finally:_plan.reset(token)
    return value

def require_write(doc,kind,value):
    require_trusted_write()
    old=None if doc.is_new() else json.loads(doc.get_doc_before_save().data_json)
    if _plan.get()!=(kind,doc.name,digest(value),digest(old) if old else None):raise DomainError('field_offline_command_required','Use the exact offline capture command.',403)
    return old

def canonical_receipt(person,capture_id,*,lock=False):
    rows=frappe.db.sql('SELECT command,company,project,scope_type,request_hash,result_json,result_hash,state FROM `tabCipher Command Receipt` WHERE name=%s'+(' FOR UPDATE' if lock else ''),(digest({'person':person,'operation_id':capture_id}),),as_dict=True)
    if not rows:return None
    row=dict(rows[0])
    try: result=json.loads(row.pop('result_json'))
    except (TypeError,ValueError):raise DomainError('receipt_integrity','The original field receipt cannot be decoded.',409) from None
    if row.get('state')!='Succeeded' or digest(result)!=row['result_hash']:raise DomainError('receipt_integrity','The original field receipt cannot be verified.',409)
    return {**row,'result':result}
