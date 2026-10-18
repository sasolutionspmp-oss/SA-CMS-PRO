"""Supported Frappe persistence with exact private native write plans."""
from contextvars import ContextVar
import json
import frappe
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write, require_trusted_write
from . import contracts as rules

_plan = ContextVar('cipher_closeout_repository_plan', default=None)
INDEX_KEYS = ('number', 'parent_id', 'package_revision', 'revision_number', 'predecessor',
              'item_id', 'category', 'requirement_id', 'subject_id', 'action')


def check_indexes(doc, value):
    if doc.name != value['id'] or doc.record_digest != digest(value):
        raise DomainError('closeout_integrity', 'The retained native identity or digest differs.', 409)
    for key in ('company', 'project', 'scope_type', 'author_person', 'status', *INDEX_KEYS):
        expected, actual = value.get(key), doc.get(key)
        if actual != expected and not (actual in (None, '') and expected is None):
            raise DomainError('closeout_integrity', 'Native closeout indexes differ from their retained fact.', 409)


def raw(kind, record_id, *, lock=False):
    rules.kind(kind); rules.identifier(record_id)
    try: doc = frappe.get_doc(rules.KINDS[kind], record_id, for_update=lock)
    except frappe.DoesNotExistError:
        raise DomainError('not_found', 'This closeout record is not available.', 404) from None
    try: value = json.loads(doc.data_json)
    except (TypeError, ValueError):
        raise DomainError('closeout_integrity', 'The retained closeout fact cannot be decoded.', 409) from None
    from .service import _effect
    plan = _effect.get()
    initial = bool(plan and plan['action'] == 'create_package' and kind == 'package' and value['revision_number'] == 0)
    rules.record(kind, value, initial=initial); check_indexes(doc, value)
    return value


def write(kind, value, *, old=None):
    rules.record(kind, value, initial=old is None and kind == 'package')
    token = _plan.set({'kind': kind, 'id': value['id'], 'digest': digest(value), 'previous': digest(old) if old else None})
    try:
        with trusted_write():
            fields = {key: value.get(key) for key in INDEX_KEYS}
            fields.update({key: value[key] for key in ('company', 'project', 'scope_type', 'author_person', 'status')})
            fields.update(record_digest=digest(value), data_json=canonical_json(value))
            if old is None:
                frappe.get_doc({'doctype': rules.KINDS[kind], 'name': value['id'], **fields}).insert(ignore_permissions=True, set_name=value['id'])
            else:
                doc = frappe.get_doc(rules.KINDS[kind], value['id'], for_update=True)
                doc.update(fields); doc.save(ignore_permissions=True)
    finally: _plan.reset(token)
    return value


def require_write(doc, kind, value):
    require_trusted_write()
    old = None if doc.is_new() else json.loads(doc.get_doc_before_save().data_json)
    if _plan.get() != {'kind': kind, 'id': value['id'], 'digest': digest(value), 'previous': digest(old) if old else None}:
        raise DomainError('closeout_command_required', 'Use the exact admitted closeout command.', 403)
    if old and (kind != 'package' or any(old[k] != value[k] for k in rules.BASE | {'number'})):
        # Package standing is the sole mutable projection field in BASE.
        if kind != 'package' or any(old[k] != value[k] for k in (rules.BASE - {'status'}) | {'number'}):
            raise DomainError('immutable_closeout', 'Original closeout facts and identity cannot be rewritten.', 409)


def number(company, project):
    from frappe.model.naming import make_autoname
    return make_autoname('CO-' + digest({'company': company, 'project': project})[:8] + '-.#####')


def candidates(kind, company, project, *, parent_id=None, last=None, limit=25):
    rules.kind(kind)
    where, args = ['company=%s', 'project=%s'], [company, project]
    if parent_id is not None: where.append('parent_id=%s'); args.append(parent_id)
    if last: where.append('(creation<%s OR (creation=%s AND name<%s))'); args.extend((last[0], last[0], last[1]))
    return frappe.db.sql('SELECT name,creation FROM `tab' + rules.KINDS[kind] + '` WHERE ' + ' AND '.join(where) + ' ORDER BY creation DESC,name DESC LIMIT %s', (*args, limit), as_dict=True)


def accepted(subject_kind, subject_id, *, lock=False):
    if subject_kind not in rules.RESULTS | {'turnover'}: rules.fail('Use an exact acceptance subject.')
    action = 'accept_turnover' if subject_kind == 'turnover' else 'accept_result'
    rows = frappe.db.sql('SELECT name FROM `tabCipher Closeout Decision` WHERE subject_id=%s AND action=%s' + (' FOR UPDATE' if lock else ''), (subject_id, action), as_dict=True)
    if len(rows) > 1:
        raise DomainError('closeout_integrity', 'An exact original has multiple independent decisions.', 409)
    if not rows: return None
    value = raw('decision', rows[0].name, lock=lock)
    if value['subject_kind'] != subject_kind:
        raise DomainError('closeout_integrity', 'The acceptance subject native kind differs.', 409)
    return value
