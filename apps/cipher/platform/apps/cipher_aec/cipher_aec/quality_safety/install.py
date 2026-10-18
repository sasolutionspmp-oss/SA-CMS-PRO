"""Additive indexes; all eight duties must be explicitly granted per Project."""
import frappe
from .contracts import KINDS,HEADERS

def after_migrate():
    for kind,doctype in KINDS.items():
        if not frappe.db.exists('DocType',doctype):continue
        frappe.db.add_index(doctype,['company','project','creation'])
        if kind in HEADERS:frappe.db.add_unique(doctype,['company','project','number'])
        elif kind.endswith('revision'):frappe.db.add_unique(doctype,['parent_id','revision_number'])
        else:frappe.db.add_unique(doctype,['source_revision','action'])
    from .privacy import DOCTYPE
    if frappe.db.exists('DocType',DOCTYPE):
        frappe.db.add_unique(DOCTYPE,['document_id'])
        frappe.db.add_index(DOCTYPE,['company','project','document_id'])

def query_denied(user=None):return '1=0'
def permission_denied(doc,ptype='read',user=None,**kwargs):return False
