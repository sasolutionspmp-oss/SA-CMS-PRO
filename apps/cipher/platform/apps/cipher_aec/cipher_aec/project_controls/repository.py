"""Exact persistent controls records; all mutable heads use the same row mutex."""
import json
import frappe
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write
from .core import identifier

DOCTYPES = {'code': 'Cipher Cost Code', 'type': 'Cipher Cost Type',
 'code_revision': 'Cipher Cost Code Revision', 'type_revision': 'Cipher Cost Type Revision',
 'wbs': 'Cipher WBS Node', 'budget': 'Cipher Budget Version', 'budget_line': 'Cipher Budget Line'}

def read(kind, record_id, *, lock=False):
    identifier(record_id)
    rows=frappe.db.sql(f'SELECT data_json,record_digest FROM `tab{DOCTYPES[kind]}` WHERE name=%s'+(' FOR UPDATE' if lock else ''),(record_id,))
    if not rows: raise DomainError('not_found','This project controls record is not available.',404)
    value=json.loads(rows[0][0])
    if digest(value)!=rows[0][1] or value.get('id')!=record_id:
        raise DomainError('controls_integrity','The project controls record cannot be verified.',409)
    return value

def write(kind,value,*,update=False):
    from .records import exact_write
    from cipher_aec.awards.runtime import quiet_award_write
    fields=projection(kind,value)
    with exact_write(kind,value), trusted_write():
        if update:
            doc=frappe.get_doc(DOCTYPES[kind],value['id'],for_update=True);doc.update(fields)
            quiet_award_write(doc)
            doc.save(ignore_permissions=True)
        else:
            doc=frappe.get_doc({'doctype':DOCTYPES[kind],'name':value['id'],**fields})
            quiet_award_write(doc)
            doc.insert(ignore_permissions=True,set_name=value['id'])
    return doc

def projection(kind,value):
    result={key:value.get(key) for key in ('company','project','author_person')}
    result.update(record_digest=digest(value),data_json=canonical_json(value))
    if kind in {'code','type'}: result.update(code=value['code'],code_key=value['code'].casefold(),current_revision=value['current_revision'],revision_number=value['revision_number'])
    elif kind.endswith('_revision'): result.update(master=value['master_id'],revision_number=value['revision_number'],effective_from=value['definition']['effective_from'])
    elif kind=='wbs': result.update(code=value['node']['code'],code_key=value['node']['code'].casefold(),budget_version=value['budget_version'],parent_node=value['node']['parent_id'])
    elif kind=='budget':result.update(award=value['award_id'],acceptance=value['plan']['acceptance']['id'],initial_key=value['project'])
    else:result.update(budget_version=value['budget_version'],source_key=digest(value['line']['source']),amount=value['line']['amount']['amount'],currency=value['line']['amount']['currency'])
    return result
