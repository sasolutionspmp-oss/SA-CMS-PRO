"""Canonical Company award records with immutable plan/adoption projections."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json,digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write
from .contracts import identifier

TYPES={'handoff':'Cipher Award Handoff','revision':'Cipher Award Handoff Revision','adoption':'Cipher Award Adoption','line':'Cipher Award Line Adoption','profile':'Cipher Project Profile'}
_writing=ContextVar('cipher_award_exact_record_write',default=None)


def read(kind,record_id,company,*,lock=False):
    identifier(record_id)
    rows=frappe.db.sql('SELECT data_json,record_digest FROM `tab'+TYPES[kind]+'` WHERE name=%s AND company=%s'+(' FOR UPDATE' if lock else ''),(record_id,company))
    if not rows:raise DomainError('not_found','This award record is not available.',404)
    try:value=json.loads(rows[0][0])
    except (TypeError,ValueError):raise DomainError('award_integrity','Award facts cannot be verified.',409) from None
    if type(value) is not dict or value.get('id')!=record_id or value.get('company')!=company or digest(value)!=rows[0][1]:
        raise DomainError('award_integrity','Award facts cannot be verified.',409)
    if kind!='profile' and (value.get('scope_type')!='Company' or value.get('project') is not None):
        raise DomainError('award_integrity','Company award evidence cannot be retargeted into a Project.',409)
    return value


def write(kind,value,*,update=False):
    fields={k:value[k] for k in ('company','project','author_person','status','handoff','revision_number','current_revision','adoption','pursuit','opportunity','issue','proposal_line_id','sales_order_item','sales_order','contract','award_revision','target_project') if k in value}
    fields.update(data_json=canonical_json(value),record_digest=digest(value))
    token=_writing.set((kind,value['id'],digest(value)))
    try:
        with trusted_write():
            from .runtime import quiet_award_write
            if update:
                doc=frappe.get_doc(TYPES[kind],value['id'],for_update=True);doc.update(fields);quiet_award_write(doc);doc.save(ignore_permissions=True)
            else:
                doc=frappe.get_doc({'doctype':TYPES[kind],**fields});quiet_award_write(doc);doc.insert(ignore_permissions=True,set_name=value['id'])
        return doc
    finally:_writing.reset(token)


def require_record_write(kind,value):
    if _writing.get()!=(kind,value['id'],digest(value)):
        raise DomainError('governed_write_required','Use the exact award service for this record.',403)
