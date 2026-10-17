"""Additive package indexes and closed native projection, without grants."""
import frappe
from .contracts import KINDS

def after_migrate():
    for kind,doctype in KINDS.items():
        if not frappe.db.exists('DocType',doctype):continue
        frappe.db.add_index(doctype,['company','project','creation'])
        if kind=='package':frappe.db.add_unique(doctype,['company','project','number'])
        elif kind=='package_revision':frappe.db.add_unique(doctype,['parent_id','revision_number'])
        elif kind=='check':
            frappe.db.add_unique(doctype,['subject_id']);frappe.db.add_unique(doctype,['packet_id'])
        else:frappe.db.add_unique(doctype,['family_id','revision_number'])
def query_denied(user=None):return '1=0'
def permission_denied(doc,ptype='read',user=None,**kwargs):return False
