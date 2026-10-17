"""Supported additive indexes; field duties are explicit, never seeded by default."""
import frappe
from .contracts import KINDS,HEADERS

def after_migrate():
    for kind,doctype in KINDS.items():
        if not frappe.db.exists('DocType',doctype):continue
        frappe.db.add_index(doctype,['company','project','creation'])
        if kind in HEADERS:frappe.db.add_unique(doctype,['company','project','number'])
        elif kind.endswith('_revision'):frappe.db.add_unique(doctype,['parent_id','revision_number'])
        elif kind=='quantity':
            frappe.db.add_index(doctype,['company','project','original_event_id'])
            frappe.db.add_unique(doctype,['source_revision','original_event_id'])
        elif kind=='decision':frappe.db.add_unique(doctype,['source_revision','action'])

def query_denied(user=None):return '1=0'
def permission_denied(doc,ptype='read',user=None,**kwargs):return False
