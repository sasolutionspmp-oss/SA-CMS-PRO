"""Frappe persistence; immutable field facts require an exact writer plan."""
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write,require_trusted_write
from . import contracts as rules

_plan=ContextVar('cipher_field_write_plan',default=None)
_capture=ContextVar('cipher_field_capture_plan',default=None)
INDEX_KEYS=('number','parent_id','revision_number','predecessor','source_revision','original_event_id','supersedes_event_id','action')

def raw(kind,record_id,*,lock=False):
    if kind not in rules.KINDS:rules.fail('Choose a registered field kind.','kind')
    rules.identifier(record_id)
    try:doc=frappe.get_doc(rules.KINDS[kind],record_id,for_update=lock)
    except frappe.DoesNotExistError:raise DomainError('not_found','This field record is not available.',404) from None
    try:value=json.loads(doc.data_json)
    except (TypeError,ValueError):raise DomainError('field_integrity','The canonical field record cannot be decoded.',409) from None
    capture=_capture.get()
    initial=bool(kind in rules.HEADERS and capture and capture['revision']['parent_id']==value['id'] and value['revision_number']==0)
    rules.record(kind,value,initial=initial)
    if doc.name!=value['id'] or doc.record_digest!=digest(value):raise DomainError('field_integrity','The canonical field identity or digest differs.',409)
    for key in ('company','project','scope_type','author_person','status',*INDEX_KEYS):
        actual,expected=doc.get(key),value.get(key)
        if actual!=expected and not(actual in (None,'') and expected is None):raise DomainError('field_integrity','The native field indexes differ from their exact fact.',409)
    return value

def write(kind,value,*,old=None):
    rules.record(kind,value,initial=old is None and kind in rules.HEADERS)
    plan={'kind':kind,'id':value['id'],'digest':digest(value),'previous':digest(old) if old else None};token=_plan.set(plan)
    try:
        with trusted_write():
            fields={k:value.get(k) for k in INDEX_KEYS}
            fields.update(scope_type='Project',company=value['company'],project=value['project'],author_person=value['author_person'],status=value['status'],record_digest=plan['digest'],data_json=canonical_json(value))
            if old is None:frappe.get_doc({'doctype':rules.KINDS[kind],'name':value['id'],**fields}).insert(ignore_permissions=True,set_name=value['id'])
            else:
                doc=frappe.get_doc(rules.KINDS[kind],value['id'],for_update=True);doc.update(fields);doc.save(ignore_permissions=True)
    finally:_plan.reset(token)
    return value

def require_write(doc,kind,value):
    require_trusted_write()
    previous=None if doc.is_new() else json.loads(doc.get_doc_before_save().data_json)
    if _plan.get()!={'kind':kind,'id':doc.name,'digest':digest(value),'previous':digest(previous) if previous else None}:
        raise DomainError('field_command_required','Use the exact canonical field command.',403)
    if previous:
        if kind not in rules.HEADERS:raise DomainError('immutable_field_record','Create an explicit successor; original field facts remain unchanged.',409)
        if any(value[k]!=previous[k] for k in rules.IMMUTABLE_FIELDS|{'number'}):raise DomainError('immutable_field_record','A field header retains its original identity and authorship.',409)

def candidate_rows(kind,company,project,*,parent_id=None,last=None,limit=25):
    where=['company=%s','project=%s'];args=[company,project]
    if parent_id is not None:where.append('parent_id=%s');args.append(parent_id)
    if last:where.append('(creation<%s OR (creation=%s AND name<%s))');args.extend([last[0],last[0],last[1]])
    return frappe.db.sql('SELECT name,creation FROM `tab'+rules.KINDS[kind]+'` WHERE '+' AND '.join(where)+' ORDER BY creation DESC,name DESC LIMIT %s',(*args,limit),as_dict=True)

def captured_events(company,project,original_event_id,*,lock=False):
    return frappe.db.sql('SELECT name FROM `tabCipher Field Quantity Event` WHERE company=%s AND project=%s AND original_event_id=%s'+(' FOR UPDATE' if lock else ''),(company,project,original_event_id),as_dict=True)

def number(kind,company,project):
    from frappe.model.naming import make_autoname
    return make_autoname('FLD-'+('DAY' if kind=='daily' else 'TM')+'-'+digest({'company':company,'project':project})[:8]+'-.#####')
