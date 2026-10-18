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
    "Cipher Document Lifecycle Request": "cipher_aec.document_control.install.query_denied",
    "Cipher Document Lifecycle Event": "cipher_aec.document_control.install.query_denied",
    "Cipher Clause Use": "cipher_aec.document_control.install.query_denied",
    "Cipher Redline Revision": "cipher_aec.document_control.install.query_denied",
    "Cipher Clause Application": "cipher_aec.document_control.install.query_denied",
    "File": "cipher_aec.documents.permissions.file_query",
    "Project": "cipher_aec.projects.permissions.project_query",
    "Task": "cipher_aec.projects.permissions.task_query",
    "Cipher Document": "cipher_aec.documents.permissions.document_query",
    "Cipher Document Revision": "cipher_aec.documents.permissions.revision_query",
}

has_permission = {
    "Cipher Document Lifecycle Request": "cipher_aec.document_control.install.permission_denied",
    "Cipher Document Lifecycle Event": "cipher_aec.document_control.install.permission_denied",
    "Cipher Clause Use": "cipher_aec.document_control.install.permission_denied",
    "Cipher Redline Revision": "cipher_aec.document_control.install.permission_denied",
    "Cipher Clause Application": "cipher_aec.document_control.install.permission_denied",
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
for _kind, _doctype in (("pursuit", "Cipher Pursuit"), ("proposal", "Cipher Proposal"), ("revision", "Cipher Proposal Revision"), ("issue", "Cipher Proposal Issue")):
    permission_query_conditions[_doctype] = "cipher_aec.commercial.permissions." + _kind + "_query"
    has_permission[_doctype] = "cipher_aec.commercial.permissions." + _kind + "_permission"
for _finance_type in ("Cipher Construction Contract", "Cipher Contract Revision", "Cipher Retainage Policy Revision", "Cipher SOV Version", "Cipher SOV Line"):
    permission_query_conditions[_finance_type] = "cipher_aec.construction_finance.permissions.finance_query"
    has_permission[_finance_type] = "cipher_aec.construction_finance.permissions.finance_permission"
for _distribution_type in ("Cipher Distribution Instruction", "Cipher Distribution Dispatch", "Cipher Distribution Cancellation"):
    permission_query_conditions[_distribution_type] = "cipher_aec.integrations.distribution.query_denied"
    has_permission[_distribution_type] = "cipher_aec.integrations.distribution.permission_denied"
for _integration_type in ("Cipher Integration Operation", "Cipher Delivery Attempt"):
    permission_query_conditions[_integration_type] = "cipher_aec.integrations.distribution_install.legacy_query"
    has_permission[_integration_type] = "cipher_aec.integrations.distribution_install.legacy_permission"

# Exact scoped APIs authorize every source; raw native JSON projections remain closed.
for _control_type in ("Cipher Cost Code", "Cipher Cost Type", "Cipher Cost Code Revision", "Cipher Cost Type Revision", "Cipher WBS Node", "Cipher Budget Version", "Cipher Budget Line"):
    permission_query_conditions[_control_type] = "cipher_aec.project_controls.permissions.query_conditions"
    has_permission[_control_type] = "cipher_aec.project_controls.permissions.has_permission"
for _award_type in ("Cipher Award Handoff", "Cipher Award Handoff Revision", "Cipher Award Adoption", "Cipher Award Line Adoption", "Cipher Project Profile", "Cipher Project Delegation Policy Revision"):
    permission_query_conditions[_award_type] = "cipher_aec.awards.install.query_denied"
    has_permission[_award_type] = "cipher_aec.awards.install.permission_denied"

# Company orchestration data has no generic native query/count projection.
# Existing Project rows retain the native role/permission path.
for _ricky_type, _ricky_query in (
    ("Cipher Ricky Run", "run_query"), ("Cipher Ricky Step", "step_query"),
    ("Cipher Tool Invocation", "invocation_query"), ("Cipher Delegation", "delegation_query"),
    ("Cipher Run Artifact", "artifact_query"), ("Cipher Proposed Change", "proposal_query"),
):
    permission_query_conditions[_ricky_type] = "cipher_aec.ricky.permissions." + _ricky_query
    has_permission[_ricky_type] = "cipher_aec.ricky.permissions.has_permission"

# Human draft-save linkage is visible only through its exact scoped reader.
permission_query_conditions["Cipher Ricky Draft Save"] = "cipher_aec.ricky.company_draft_save.query"
has_permission["Cipher Ricky Draft Save"] = "cipher_aec.ricky.company_draft_save.has_permission"

# Engineering JSON is exposed only by the exact source-authorized Project APIs.
from cipher_aec.engineering.contracts import KINDS as _ENGINEERING_KINDS
for _engineering_type in _ENGINEERING_KINDS.values():
    permission_query_conditions[_engineering_type] = "cipher_aec.engineering.install.query_denied"
    has_permission[_engineering_type] = "cipher_aec.engineering.install.permission_denied"

from cipher_aec.engineering_packages.contracts import KINDS as _PACKAGE_KINDS
for _package_type in _PACKAGE_KINDS.values():
    permission_query_conditions[_package_type] = "cipher_aec.engineering_packages.install.query_denied"
    has_permission[_package_type] = "cipher_aec.engineering_packages.install.permission_denied"

from cipher_aec.document_control.contracts import KINDS as _DOCUMENTARY_KINDS
for _documentary_type in _DOCUMENTARY_KINDS.values():
    permission_query_conditions[_documentary_type] = "cipher_aec.document_control.install.query_denied"
    has_permission[_documentary_type] = "cipher_aec.document_control.install.permission_denied"

from cipher_aec.field.contracts import KINDS as _FIELD_KINDS
for _field_type in _FIELD_KINDS.values():
    permission_query_conditions[_field_type] = "cipher_aec.field.install.query_denied"
    has_permission[_field_type] = "cipher_aec.field.install.permission_denied"

# Semantic checkpoint plaintext is available only through current-source services.
permission_query_conditions["Cipher Semantic Corpus"] = "cipher_aec.semantic_index.store.no_native_rows"
has_permission["Cipher Semantic Corpus"] = "cipher_aec.semantic_index.store.deny_native_access"

# Offline envelopes are private; expose only exact current owned API reads.
for _offline_type in ('Cipher Field Offline Device', 'Cipher Field Offline Capture', 'Cipher Field Offline Event'):
    permission_query_conditions[_offline_type] = 'cipher_aec.field_offline.install.query_denied'
    has_permission[_offline_type] = 'cipher_aec.field_offline.install.permission_denied'

# FLD-03 JSON is readable only through current exact scoped services.
from cipher_aec.quality_safety.contracts import KINDS as _QUALITY_SAFETY_KINDS
for _quality_safety_type in (*_QUALITY_SAFETY_KINDS.values(), 'Cipher Incident Evidence Registration'):
    permission_query_conditions[_quality_safety_type] = 'cipher_aec.quality_safety.install.query_denied'
    has_permission[_quality_safety_type] = 'cipher_aec.quality_safety.install.permission_denied'
