"""Supported additive indexes only; no permissions, grants or fixture mutation."""
import frappe
from .contracts import KINDS

def after_migrate():
    for kind,doctype in KINDS.items():
        if not frappe.db.exists('DocType',doctype):continue
        frappe.db.add_index(doctype,['company','project','creation'])
        if kind in ('rfi','submittal'):frappe.db.add_unique(doctype,['company','project','number'])
        elif kind in ('rfi_revision','submission'):frappe.db.add_unique(doctype,['parent_id','revision_number'])
        elif kind in ('response','disposition'):frappe.db.add_unique(doctype,['source_revision','revision_number'])
        elif kind in ('official_response','official_disposition','distribution'):
            frappe.db.add_unique(doctype,['subject_id']);frappe.db.add_unique(doctype,['packet_id'])

def query_denied(user=None):return '1=0'
def permission_denied(doc,ptype='read',user=None,**kwargs):return False
