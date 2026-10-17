"""Supported Frappe persistence with an exact, record-specific writer context."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write, require_trusted_write
from .contracts import KINDS, identifier, record

_plan=ContextVar('cipher_engineering_write_plan',default=None)
HEADERS={'rfi','submittal'}
INDEX_KEYS=('parent_id','revision_number','predecessor','subject_id','packet_id','decision_id','number','source_revision')

def raw(kind,record_id,*,lock=False):
    identifier(record_id)
    doc=frappe.get_doc(KINDS[kind],record_id,for_update=lock)
    value=json.loads(doc.data_json)
    record(kind,value)
    if doc.name!=value.get('id') or doc.record_digest!=digest(value) or any(doc.get(k)!=value.get(k) for k in ('company','project','scope_type','author_person','status')):
        raise DomainError('engineering_integrity','The immutable engineering payload cannot be verified.',409)
    for k in INDEX_KEYS:
        actual=doc.get(k);expected=value.get(k)
        if actual!=expected and not(actual in (None,'') and expected is None):
            raise DomainError('engineering_integrity','Engineering index metadata differs from its canonical fact.',409)
    return value

def write(kind,value,*,old=None):
    plan={'kind':kind,'id':value['id'],'digest':digest(value),'previous':digest(old) if old else None}
    token=_plan.set(plan)
    try:
        with trusted_write():
            fields={k:value.get(k) for k in INDEX_KEYS}
            fields.update(scope_type='Project',company=value['company'],project=value['project'],author_person=value['author_person'],status=value['status'],data_json=canonical_json(value),record_digest=plan['digest'])
            if old is None:
                doc=frappe.get_doc({'doctype':KINDS[kind],'name':value['id'],**fields});doc.insert(ignore_permissions=True,set_name=value['id'])
            else:
                doc=frappe.get_doc(KINDS[kind],value['id'],for_update=True);doc.update(fields);doc.save(ignore_permissions=True)
    finally:_plan.reset(token)
    return value

def require_write(doc,kind,value):
    require_trusted_write();plan=_plan.get()
    if not plan or plan!={'kind':kind,'id':doc.name,'digest':digest(value),'previous':None if doc.is_new() else digest(json.loads(doc.get_doc_before_save().data_json))}:
        raise DomainError('engineering_command_required','Use the exact canonical engineering command.',403)
    if not doc.is_new() and kind not in HEADERS:
        raise DomainError('immutable_engineering','Create an explicit successor; original engineering facts remain unchanged.',409)

def candidate_rows(kind,company,project,*,parent_id=None,subject_id=None,last=None,limit=50):
    where=['company=%s','project=%s'];args=[company,project]
    if parent_id is not None:where.append('parent_id=%s');args.append(parent_id)
    if subject_id is not None:where.append('subject_id=%s');args.append(subject_id)
    if last:where.append('(creation<%s OR (creation=%s AND name<%s))');args.extend([last[0],last[0],last[1]])
    return frappe.db.sql('SELECT name,creation FROM `tab'+KINDS[kind]+'` WHERE '+' AND '.join(where)+' ORDER BY creation DESC,name DESC LIMIT %s',(*args,limit),as_dict=True)

def official_for(kind,subject_id,*,lock=False):
    rows=frappe.db.sql('SELECT name FROM `tab'+KINDS[kind]+'` WHERE subject_id=%s'+(' FOR UPDATE' if lock else ''),(subject_id,))
    return raw(kind,rows[0][0],lock=lock) if rows else None

def number(kind,company,project):
    from frappe.model.naming import make_autoname
    return make_autoname('ENG-'+('RFI' if kind=='rfi' else 'SUB')+'-'+digest({'company':company,'project':project})[:8]+'-.#####')
