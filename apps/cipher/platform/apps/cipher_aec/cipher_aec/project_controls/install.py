"""Supported uniqueness constraints for canonical controls identities."""
import frappe

def install():
    for name in ('Cipher Cost Code','Cipher Cost Type'):
        frappe.db.add_unique(name,['company','code_key'],constraint_name=name.lower().replace(' ','_')+'_scope')
    for name in ('Cipher Cost Code Revision','Cipher Cost Type Revision'):
        frappe.db.add_unique(name,['master','revision_number'],constraint_name=name.lower().replace(' ','_')+'_ordinal')
    frappe.db.add_unique('Cipher WBS Node',['project','code_key'],constraint_name='cipher_wbs_project_code')
    for field in ('initial_key','award','acceptance'):
        frappe.db.add_unique('Cipher Budget Version',[field],constraint_name='cipher_budget_'+field)
    frappe.db.add_unique('Cipher Budget Line',['budget_version','source_key'],constraint_name='cipher_budget_source_once')
