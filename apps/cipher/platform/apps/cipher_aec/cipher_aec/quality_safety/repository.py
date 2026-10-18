"""Exact native writer plans; generic native JSON projections remain closed."""
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write,require_trusted_write
from . import contracts as rules

_plan=ContextVar('cipher_quality_safety_write_plan',default=None)
INDEX_KEYS=('number','category','parent_id','revision_number','predecessor','source_revision','action')

def raw(kind,record_id,*,lock=False):
    rules.family_for(kind);rules.identifier(record_id)
    try:doc=frappe.get_doc(rules.KINDS[kind],record_id,for_update=lock)
    except frappe.DoesNotExistError:raise DomainError('not_found','This record is not available.',404) from None
    try:value=json.loads(doc.data_json)
    except (TypeError,ValueError):raise DomainError('quality_safety_integrity','The retained fact cannot be decoded.',409) from None
    # An initial empty header is readable only by its exact active creation plan.
    from .service import _effect
    plan=_effect.get();initial=bool(plan and plan['action']=='create' and kind in rules.HEADERS and value['revision_number']==0)
    rules.record(kind,value,initial=initial);check_indexes(doc,value)
    return value

def check_indexes(doc,value):
    if doc.name!=value['id'] or doc.record_digest!=digest(value):raise DomainError('quality_safety_integrity','The retained identity or digest differs.',409)
    for key in ('company','project','scope_type','author_person','status',*INDEX_KEYS):
        actual,expected=doc.get(key),value.get(key)
        if actual!=expected and not(actual in (None,'') and expected is None):raise DomainError('quality_safety_integrity','Native indexes differ from the retained fact.',409)

def write(kind,value,*,old=None):
    rules.record(kind,value,initial=old is None and kind in rules.HEADERS)
    token=_plan.set({'kind':kind,'id':value['id'],'digest':digest(value),'previous':digest(old) if old else None})
    try:
        with trusted_write():
            fields={k:value.get(k) for k in INDEX_KEYS}
            fields.update(scope_type='Project',company=value['company'],project=value['project'],author_person=value['author_person'],status=value['status'],record_digest=digest(value),data_json=canonical_json(value))
            if old is None:frappe.get_doc({'doctype':rules.KINDS[kind],'name':value['id'],**fields}).insert(ignore_permissions=True,set_name=value['id'])
            else:
                doc=frappe.get_doc(rules.KINDS[kind],value['id'],for_update=True);doc.update(fields);doc.save(ignore_permissions=True)
    finally:_plan.reset(token)
    return value

def require_write(doc,kind,value):
    require_trusted_write();previous=None if doc.is_new() else json.loads(doc.get_doc_before_save().data_json)
    if _plan.get()!={'kind':kind,'id':doc.name,'digest':digest(value),'previous':digest(previous) if previous else None}:
        raise DomainError('quality_safety_command_required','Use the exact documentary command.',403)
    if previous and (kind not in rules.HEADERS or any(value[k]!=previous[k] for k in (rules.BASE-{'status'})|{'number','category'})):
        raise DomainError('immutable_quality_safety','Original facts and identity cannot be rewritten.',409)

def candidate_rows(kind,company,project,*,parent_id=None,last=None,limit=25):
    rules.family_for(kind);where=['company=%s','project=%s'];args=[company,project]
    if parent_id is not None:where.append('parent_id=%s');args.append(parent_id)
    if last:where.append('(creation<%s OR (creation=%s AND name<%s))');args.extend([last[0],last[0],last[1]])
    return frappe.db.sql('SELECT name,creation FROM `tab'+rules.KINDS[kind]+'` WHERE '+' AND '.join(where)+' ORDER BY creation DESC,name DESC LIMIT %s',(*args,limit),as_dict=True)

def number(family,company,project):
    from frappe.model.naming import make_autoname
    return make_autoname(('INC-' if family=='incident' else 'QS-')+digest({'company':company,'project':project})[:8]+'-.#####')
