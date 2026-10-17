"""Supported Frappe persistence with private exact command write plans."""
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write,require_trusted_write
from .contracts import KINDS,identifier
_plan=ContextVar('document_control_write_plan',default=None)
INDEXES=('parent_id','revision_number','predecessor','subject_id','packet_id','decision_id','read_allowed')

def raw(kind,name,*,lock=False):
    identifier(name);doc=frappe.get_doc(KINDS[kind],name,for_update=lock);value=json.loads(doc.data_json)
    if value.get('id')!=doc.name or digest(value)!=doc.record_digest:raise DomainError('document_control_integrity','The exact documentary record cannot be verified.',409)
    for key in ('company','project','scope_type','author_person','status',*INDEXES):
        a,b=doc.get(key),value.get(key)
        if key=='read_allowed' and b is None:a=None if a in (None,'',0) else a
        if a!=b and not(a in (None,'') and b is None):raise DomainError('document_control_integrity','Native documentary indexes differ from the exact record.',409)
    return value

def write(kind,value,*,old=None):
    token=_plan.set({'kind':kind,'id':value['id'],'digest':digest(value),'previous':digest(old) if old else None})
    try:
        with trusted_write():
            fields={k:value.get(k) for k in INDEXES};fields.update(scope_type=value['scope_type'],company=value['company'],project=value['project'],author_person=value['author_person'],status=value['status'],record_digest=digest(value),data_json=canonical_json(value))
            if old is None:frappe.get_doc({'doctype':KINDS[kind],'name':value['id'],**fields}).insert(ignore_permissions=True,set_name=value['id'])
            else:
                doc=frappe.get_doc(KINDS[kind],value['id'],for_update=True);doc.update(fields);doc.save(ignore_permissions=True)
    finally:_plan.reset(token)
    return value

def require_write(doc,kind,value):
    require_trusted_write();previous=None if doc.is_new() else digest(json.loads(doc.get_doc_before_save().data_json))
    if _plan.get()!={'kind':kind,'id':doc.name,'digest':digest(value),'previous':previous}:raise DomainError('document_control_command_required','Use the exact canonical document-control command.',403)
    if not doc.is_new() and kind!='library':raise DomainError('immutable_document_control','Original documentary evidence is immutable.',409)

def latest(kind,parent_id,*,lock=False):
    rows=frappe.db.sql('SELECT name FROM `tab'+KINDS[kind]+'` WHERE parent_id=%s ORDER BY revision_number DESC,name DESC LIMIT 1'+(' FOR UPDATE' if lock else ''),(parent_id,))
    return raw(kind,rows[0][0],lock=lock) if rows else None

def official(kind,subject_id,*,lock=False):
    rows=frappe.db.sql('SELECT name FROM `tab'+KINDS[kind]+'` WHERE subject_id=%s'+(' FOR UPDATE' if lock else ''),(subject_id,))
    return raw(kind,rows[0][0],lock=lock) if rows else None

def candidates(kind,company,project,*,parent_id=None,last=None,limit=25,scope_type='Project'):
    where=['company=%s',"scope_type=%s"];args=[company,scope_type]
    if scope_type=='Company' and project is None:where.append('project IS NULL')
    elif scope_type=='Project' and project:where.append('project=%s');args.append(project)
    else:raise DomainError('invalid_document_scope','Choose an exact documentary scope.',422)
    if parent_id is not None:where.append('parent_id=%s');args.append(parent_id)
    if last:where.append('(creation<%s OR (creation=%s AND name<%s))');args.extend([last[0],last[0],last[1]])
    return frappe.db.sql('SELECT name,creation FROM `tab'+KINDS[kind]+'` WHERE '+' AND '.join(where)+' ORDER BY creation DESC,name DESC LIMIT %s',(*args,limit),as_dict=True)


def issue_candidates(company,project,document_id,*,lock=False):
    # Hard admission cap, not pagination, a total or a performance qualification.
    rows=frappe.db.sql("SELECT name FROM `tabCipher Document Issue` WHERE company=%s AND project=%s AND scope_type='Project' AND JSON_CONTAINS(data_json,JSON_OBJECT('document_id',%s),'$.artifacts') ORDER BY creation,name LIMIT 201"+(' FOR UPDATE' if lock else ''),(company,project,document_id))
    if len(rows)>200:raise DomainError('document_issue_limit','The issued-document projection exceeds its bounded admission limit.',409)
    return [row[0] for row in rows]

def lifecycle_chain(document_id,*,lock=False):
    rows=frappe.db.sql('SELECT name FROM `tabCipher Document Lifecycle Event` WHERE parent_id=%s ORDER BY revision_number,name LIMIT 65'+(' FOR UPDATE' if lock else ''),(document_id,))
    if len(rows)>64:raise DomainError('document_lifecycle_limit','The append-only document lifecycle exceeds its bounded admission limit.',409)
    return [raw('lifecycle',row[0],lock=lock) for row in rows]
