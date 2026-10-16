"""Supported metadata/index installation; no policy, duties or writer activation."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_migrate():
    create_custom_fields({'Sales Order':[{'fieldname':name,'label':name.replace('_',' ').title(),'fieldtype':'Data','read_only':1,'no_copy':1}
        for name in ('cipher_award_handoff','cipher_issue','cipher_issue_digest','cipher_proposal_revision','cipher_accepted_baseline','cipher_award_native_digest')],
        'Sales Order Item':[{'fieldname':name,'label':name.replace('_',' ').title(),'fieldtype':'Data','read_only':1,'no_copy':1}
        for name in ('cipher_award_line_id','cipher_proposal_line_id')]},update=True)
    for table,columns,name in (
        ('Cipher Award Handoff',['company','pursuit'],'cipher_award_pursuit_once'),
        ('Cipher Award Handoff',['company','opportunity'],'cipher_award_opportunity_once'),
        ('Cipher Award Handoff Revision',['handoff','revision_number'],'cipher_award_plan_ordinal'),
        ('Cipher Award Adoption',['handoff'],'cipher_award_full_once'),
        ('Cipher Award Adoption',['company','pursuit'],'cipher_award_adopt_pursuit'),
        ('Cipher Award Adoption',['company','opportunity'],'cipher_award_adopt_opportunity'),
        ('Cipher Award Adoption',['issue'],'cipher_award_issue_once'),
        ('Cipher Award Adoption',['sales_order'],'cipher_award_order_once'),
        ('Cipher Award Adoption',['contract'],'cipher_award_contract_once'),
        ('Cipher Award Adoption',['target_project'],'cipher_award_project_once'),
        ('Cipher Award Line Adoption',['company','pursuit','proposal_line_id'],'cipher_award_source_line_once'),
        ('Cipher Award Line Adoption',['issue','proposal_line_id'],'cipher_award_issue_line_once'),
        ('Cipher Award Line Adoption',['sales_order_item'],'cipher_award_native_line_once'),
        ('Cipher Project Profile',['project'],'cipher_award_profile_project'),
        ('Cipher Project Profile',['handoff'],'cipher_award_profile_handoff'),
        ('Cipher Project Delegation Policy Revision',['company','version'],'cipher_team_policy_version'),
    ):frappe.db.add_unique(table,columns,constraint_name=name)


def query_denied(user=None):return '1=0'
def permission_denied(doc,user=None,permission_type=None,ptype=None):return False
