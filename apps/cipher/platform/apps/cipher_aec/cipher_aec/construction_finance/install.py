"""FIN-01 database-enforced scope, revision, and stable-line uniqueness."""

def after_migrate():
    import frappe
    for table, columns, name in (
        ('Cipher Construction Contract', ['company', 'project', 'contract_number'], 'cipher_contract_number_scope'),
        ('Cipher Contract Revision', ['contract', 'revision_number'], 'cipher_contract_revision'),
        ('Cipher Retainage Policy Revision', ['contract', 'revision_number'], 'cipher_retainage_policy_revision'),
        ('Cipher SOV Version', ['contract', 'revision_number'], 'cipher_sov_version'),
        ('Cipher SOV Line', ['sov_version', 'line_id'], 'cipher_sov_stable_line'),
        ('Cipher SOV Line', ['sov_version', 'item_code'], 'cipher_sov_item_code'),
    ):
        if frappe.db.exists('DocType', table):
            frappe.db.add_unique(table, columns, constraint_name=name)
    for table in ('Cipher Construction Contract', 'Cipher Contract Revision', 'Cipher Retainage Policy Revision', 'Cipher SOV Version', 'Cipher SOV Line'):
        if frappe.db.exists('DocType', table):
            frappe.db.add_index(table, ['company', 'project', 'creation'], 'cipher_finance_scope')
