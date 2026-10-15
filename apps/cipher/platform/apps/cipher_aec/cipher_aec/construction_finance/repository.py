"""Persistent FIN records with full-payload current locking reads."""
import json
import frappe
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write
from .core import identifier

DOCTYPES = {'contract': 'Cipher Construction Contract', 'revision': 'Cipher Contract Revision',
            'policy': 'Cipher Retainage Policy Revision', 'sov': 'Cipher SOV Version', 'line': 'Cipher SOV Line'}


def read(kind, record_id, *, lock=False):
    identifier(record_id)
    rows = frappe.db.sql(f'SELECT data_json,record_digest FROM `tab{DOCTYPES[kind]}` WHERE name=%s' + (' FOR UPDATE' if lock else ''), (record_id,))
    if not rows:
        raise DomainError('not_found', 'This construction contract record is not available.', 404)
    value = json.loads(rows[0][0])
    if digest(value) != rows[0][1]:
        raise DomainError('contract_integrity', 'The exact construction contract record cannot be verified.', 409)
    return value


def insert(record_kind, value, **fields):
    with trusted_write():
        doc = frappe.get_doc({'doctype': DOCTYPES[record_kind], 'name': value['id'], 'company': value['company'], 'project': value['project'],
            'author_person': value['author_person'], 'status': value['status'], 'record_digest': digest(value), 'data_json': canonical_json(value), **fields})
        doc.insert(ignore_permissions=True, set_name=value['id'])
    return doc


def update_contract(value):
    with trusted_write():
        doc = frappe.get_doc(DOCTYPES['contract'], value['id'], for_update=True)
        doc.update({'data_json': canonical_json(value), 'record_digest': digest(value), 'status': value['status'],
                    'revision_number': value['revision_number'], 'draft_revision': value['draft_revision'], 'accepted_revision': value['accepted_revision']})
        doc.save(ignore_permissions=True)
    return doc
