"""Additive documentary indexes without any native role or duty grants."""
import frappe
from .contracts import KINDS

def after_migrate():
    for kind,doctype in KINDS.items():
        if not frappe.db.exists('DocType',doctype):continue
        frappe.db.add_index(doctype,['company','project','creation'])
        frappe.db.add_index(doctype,['parent_id','creation'])
        if kind in ('rights','library_revision','redline','lifecycle'):frappe.db.add_unique(doctype,['parent_id','revision_number'])
        if kind in ('issue','adoption','distribution','clause_application','lifecycle'):
            frappe.db.add_unique(doctype,['subject_id']);frappe.db.add_unique(doctype,['packet_id'])
def query_denied(user=None):return '1=0'
def permission_denied(doc,ptype='read',user=None,**kwargs):return False
