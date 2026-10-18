"""Additive native indexes. New duties require explicit current Project grants."""
import frappe
from .contracts import KINDS, REQUIREMENTS


def after_migrate():
    for kind, doctype in KINDS.items():
        if not frappe.db.exists('DocType', doctype): continue
        frappe.db.add_index(doctype, ['company', 'project', 'creation'])
        if kind == 'package': frappe.db.add_unique(doctype, ['company', 'project', 'number'])
        elif kind == 'package_revision': frappe.db.add_unique(doctype, ['parent_id', 'revision_number'])
        elif kind in REQUIREMENTS: frappe.db.add_unique(doctype, ['package_revision', 'item_id'])
        elif kind == 'decision': frappe.db.add_unique(doctype, ['subject_id', 'action'])
        if kind != 'package': frappe.db.add_index(doctype, ['parent_id', 'creation'])


def query_denied(user=None): return '1=0'


def permission_denied(doc, ptype='read', user=None, **kwargs): return False
