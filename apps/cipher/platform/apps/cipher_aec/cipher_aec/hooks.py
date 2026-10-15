app_name = "cipher_aec"
app_title = "Cipher AEC/CMS Pro"
app_publisher = "S&A Solutions"
app_description = "Unified AEC project operations, evidence, and governed automation"
app_email = "support@example.invalid"
app_license = "GPL-3.0-or-later"
required_apps = ["erpnext"]

after_install = "cipher_aec.install.after_install"
after_migrate = "cipher_aec.install.after_migrate"
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

# Submitting/cancelling native financial documents is explicitly unqualified in R0.
for _financial_doctype in ("Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Purchase Order", "Sales Order", "Purchase Receipt", "Delivery Note", "Stock Entry", "Expense Claim"):
    doc_events[_financial_doctype] = {event: "cipher_aec.governance.approvals.prevent_unsupported_financial_transition" for event in ("validate", "before_submit", "before_cancel")}

doc_events["UOM"] = {"validate": "cipher_aec.estimating.guards.validate_uom", "on_trash": "cipher_aec.estimating.guards.prevent_qualified_uom_delete", "before_rename": "cipher_aec.estimating.guards.prevent_qualified_uom_rename"}
