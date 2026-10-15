app_name = "cipher_aec"
app_title = "Cipher AEC/CMS Pro"
app_publisher = "S&A Solutions"
app_description = "Unified AEC project operations, evidence, and governed automation"
app_email = "support@example.invalid"
app_license = "GPL-3.0-or-later"
required_apps = ["erpnext"]

after_install = "cipher_aec.install.after_install"
after_migrate = "cipher_aec.install.after_migrate"
before_migrate = "cipher_aec.install.before_migrate"
before_request = ["cipher_aec.api.boundary.before_request"]
after_request = ["cipher_aec.api.boundary.after_request"]

doc_events = {
    "ToDo": {
        "validate": "cipher_aec.projects.guards.validate_assignment",
        "on_trash": "cipher_aec.projects.guards.validate_assignment",
    },
    "Project": {
        "validate": "cipher_aec.projects.guards.validate_project",
        "on_trash": "cipher_aec.projects.guards.prevent_delete",
    },
    "Task": {
        "validate": "cipher_aec.projects.guards.validate_task",
        "on_trash": "cipher_aec.projects.guards.prevent_delete",
    },
    "File": {
        "validate": "cipher_aec.documents.guards.validate_file",
        "on_trash": "cipher_aec.documents.guards.before_delete_file",
    },
}

permission_query_conditions = {
    "File": "cipher_aec.documents.permissions.file_query",
    "Project": "cipher_aec.projects.permissions.project_query",
    "Task": "cipher_aec.projects.permissions.task_query",
    "Cipher Document": "cipher_aec.documents.permissions.document_query",
    "Cipher Document Revision": "cipher_aec.documents.permissions.revision_query",
}

has_permission = {
    "File": "cipher_aec.documents.permissions.file_permission",
    "Project": "cipher_aec.projects.permissions.project_permission",
    "Task": "cipher_aec.projects.permissions.task_permission",
    "Cipher Document": "cipher_aec.documents.permissions.document_permission",
    "Cipher Document Revision": "cipher_aec.documents.permissions.revision_permission",
}

scheduler_events = {
    "all": ["cipher_aec.integrations.outbox.dispatch_pending", "cipher_aec.ricky.worker.recover_pending"],
}

extend_doctype_class = {"File": ["cipher_aec.documents.guards.CipherFileGuard"]}
override_whitelisted_methods = {"frappe.core.api.file.zip_files": "cipher_aec.documents.guards.zip_files"}

# Closed writer catalog shares FIN's conservative initial-admission boundary.
# There is currently no supported writer/bypass, including for reversible drafts.
# Company bootstrap and COM Opportunity/Quotation composition are excluded.
UNQUALIFIED_FINANCIAL_WRITERS = (
    "Sales Order", "Sales Invoice", "Delivery Note", "Purchase Order", "Purchase Invoice",
    "Purchase Receipt", "Payment Entry", "Journal Entry", "Stock Entry", "Expense Claim",
    "Timesheet", "Material Request",
)
for _financial_doctype in UNQUALIFIED_FINANCIAL_WRITERS:
    doc_events[_financial_doctype] = {event: "cipher_aec.governance.approvals.prevent_unsupported_financial_transition"
        for event in ("before_insert", "before_validate", "validate", "before_save", "before_submit", "before_cancel", "before_update_after_submit", "on_trash")}

doc_events["UOM"] = {"validate": "cipher_aec.estimating.guards.validate_uom", "on_trash": "cipher_aec.estimating.guards.prevent_qualified_uom_delete", "before_rename": "cipher_aec.estimating.guards.prevent_qualified_uom_rename"}

permission_query_conditions["Company"] = "cipher_aec.governance.permissions.company_query"
has_permission["Company"] = "cipher_aec.governance.permissions.company_permission"

for _commercial_native in ("Opportunity", "Quotation"):
    doc_events[_commercial_native] = {"validate": "cipher_aec.commercial.guards.native_validate", "on_trash": "cipher_aec.commercial.guards.native_trash"}
for _kind, _doctype in (("pursuit", "Cipher Pursuit"), ("proposal", "Cipher Proposal"), ("revision", "Cipher Proposal Revision")):
    permission_query_conditions[_doctype] = "cipher_aec.commercial.permissions." + _kind + "_query"
    has_permission[_doctype] = "cipher_aec.commercial.permissions." + _kind + "_permission"
for _finance_type in ("Cipher Construction Contract", "Cipher Contract Revision", "Cipher Retainage Policy Revision", "Cipher SOV Version", "Cipher SOV Line"):
    permission_query_conditions[_finance_type] = "cipher_aec.construction_finance.permissions.finance_query"
    has_permission[_finance_type] = "cipher_aec.construction_finance.permissions.finance_permission"
