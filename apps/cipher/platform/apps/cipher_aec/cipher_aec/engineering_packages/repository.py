"""Exact private write plans over supported Frappe DocTypes."""
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write,require_trusted_write
from .contracts import KINDS,identifier
_plan=ContextVar('engineering_package_write_plan',default=None)
INDEXES=('parent_id','family_id','revision_number','predecessor','subject_id','packet_id','decision_id','number')

def raw(kind,identifier_value,*,lock=False):
    identifier(identifier_value);doc=frappe.get_doc(KINDS[kind],identifier_value,for_update=lock);value=json.loads(doc.data_json)
    if value.get('id')!=doc.name or digest(value)!=doc.record_digest or any(doc.get(k)!=value.get(k) for k in ('company','project','scope_type','author_person','status')):raise DomainError('package_integrity','The exact engineering package fact cannot be verified.',409)
    for key in INDEXES:
        if doc.get(key)!=value.get(key) and not(doc.get(key) in (None,'') and value.get(key) is None):raise DomainError('package_integrity','Package index metadata differs from its exact fact.',409)
    return value

def write(kind,value,*,old=None):
    plan={'kind':kind,'id':value['id'],'digest':digest(value),'previous':digest(old) if old else None};token=_plan.set(plan)
    try:
        with trusted_write():
            fields={k:value.get(k) for k in INDEXES};fields.update(scope_type='Project',company=value['company'],project=value['project'],author_person=value['author_person'],status=value['status'],record_digest=digest(value),data_json=canonical_json(value))
            if old is None:frappe.get_doc({'doctype':KINDS[kind],'name':value['id'],**fields}).insert(ignore_permissions=True,set_name=value['id'])
            else:
                doc=frappe.get_doc(KINDS[kind],value['id'],for_update=True);doc.update(fields);doc.save(ignore_permissions=True)
    finally:_plan.reset(token)
    return value

def require_write(doc,kind,value):
    require_trusted_write();previous=None if doc.is_new() else digest(json.loads(doc.get_doc_before_save().data_json))
    if _plan.get()!={'kind':kind,'id':doc.name,'digest':digest(value),'previous':previous}:raise DomainError('package_command_required','Use the exact canonical engineering package command.',403)
    if not doc.is_new() and kind!='package':raise DomainError('immutable_package','Create an explicit successor; original engineering facts remain intact.',409)

def checked(kind,subject_id,*,lock=False):
    rows=frappe.db.sql('SELECT name FROM `tabCipher Engineering Check Revision` WHERE subject_id=%s'+(' FOR UPDATE' if lock else ''),(subject_id,))
    return raw('check',rows[0][0],lock=lock) if rows else None

def candidates(kind,company,project,*,parent_id=None,last=None,limit=25):
    where=['company=%s','project=%s'];args=[company,project]
    if parent_id is not None:where.append('parent_id=%s');args.append(parent_id)
    if last:where.append('(creation<%s OR (creation=%s AND name<%s))');args.extend([last[0],last[0],last[1]])
    return frappe.db.sql('SELECT name,creation FROM `tab'+KINDS[kind]+'` WHERE '+' AND '.join(where)+' ORDER BY creation DESC,name DESC LIMIT %s',(*args,limit),as_dict=True)
