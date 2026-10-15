"""Fixed supported product route catalog, shared by boundary and OpenAPI.

No incoming command string selects a Python import outside this catalog.
Authentication methods are upstream Frappe contracts, separate from Cipher v1.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    method: str
    response: str
    command: bool = False
    binary: bool = False


ROUTES = {}

def _module(module, routes):
    for name, definition in routes.items():
        ROUTES[module + "." + name] = Route(*definition)


_module("cipher_aec.api.v1", {
    "session": ("GET", "Session"), "projects": ("GET", "ProjectList"),
    "project": ("GET", "Project"), "tasks": ("GET", "TaskList"),
    "history": ("GET", "HistoryList"), "operation": ("GET", "CommandResult"),
    "create_task": ("POST", "CreateTaskResponse", True),
})
_module("cipher_aec.api.company", {"history": ("GET", "HistoryList"), "operation": ("GET", "CommandResult")})
_module("cipher_aec.api.approvals", {
    "list_packets": ("GET", "ApprovalList"), "read_packet": ("GET", "ApprovalPacket"),
    "request_project_status": ("POST", "ApprovalCommandResponse", True),
    "request_action": ("POST", "ApprovalCommandResponse", True),
    "decide_packet": ("POST", "ApprovalCommandResponse", True),
    "withdraw_packet": ("POST", "ApprovalCommandResponse", True),
    "execute_packet": ("POST", "ApprovalExecutionResponse", True),
})
_module("cipher_aec.documents.api", {
    "upload_document": ("POST", "DocumentUploadResponse", True),
    "list_documents": ("GET", "DocumentList"), "get_document": ("GET", "DocumentDetail"),
    "preview_revision": ("GET", "DocumentPreview"), "search_documents": ("GET", "CitationList"),
    "get_citation": ("GET", "Citation"), "download_revision": ("GET", "SourceBytes", False, True),
})
_module("cipher_aec.ricky.api", {
    "connection_status": ("GET", "ModelStatus"), "start_run": ("POST", "RickyRun", True),
    "get_run": ("GET", "RickyRun"), "run_events": ("GET", "RickyEvents"),
    "cancel_run": ("POST", "RickyRun", True), "get_proposal": ("GET", "RickyProposal"),
    "commit_proposal": ("POST", "ProposalCommitResponse", True),
})
_module("cipher_aec.migrations.api", {
    "validate_manifest": ("POST", "CanonicalValidation"),
    "preview_manifest": ("POST", "CanonicalPreview"),
    "export_records": ("POST", "CanonicalExport"),
})
_module("cipher_aec.estimating.api", {
    "register_unit": ("POST", "RegisterUnitResponse", True),
    "create_conversion": ("POST", "CreateConversionResponse", True),
    "create_rate": ("POST", "CreateRateResponse", True),
    "create_assembly": ("POST", "CreateAssemblyResponse", True),
    "create_estimate": ("POST", "CreateEstimateResponse", True),
    "calculate_revision": ("POST", "CalculateRevisionResponse", True),
    "get_record": ("GET", "EstRecordResponse"),
    "list_records": ("GET", "EstListResponse"),
    "list_units": ("GET", "ListEstimateUnitsResponse"),
})

_module("cipher_aec.takeoff.api", {
    "create_set": ("POST", "TakeoffCreateSetResponse", True),
    "create_calibration": ("POST", "TakeoffCreateCalibrationResponse", True),
    "create_measurement": ("POST", "TakeoffCreateMeasurementResponse", True),
    "bind_line": ("POST", "TakeoffBindLineResponse", True),
    "get_record": ("GET", "TakeoffGetResponse"),
    "list_records": ("GET", "TakeoffListResponse"),
    "drawing_impact": ("GET", "TakeoffImpactResponse"),
    "compare_measurements": ("GET", "TakeoffCompareResponse"),
})
_module("cipher_aec.commercial.api", {
    "pursuits": ("GET", "ComPursuitList"), "pursuit": ("GET", "ComPursuit"),
    "proposals": ("GET", "ComProposalList"), "proposal": ("GET", "ComProposalDetail"),
    "proposal_revision": ("GET", "ComRevision"), "compare_revisions": ("GET", "ComComparison"),
    "create_pursuit": ("POST", "ComPursuitCommand", True), "update_pursuit": ("POST", "ComPursuitCommand", True),
    "create_proposal": ("POST", "ComProposalCommand", True), "save_proposal_revision": ("POST", "ComProposalCommand", True),
})

_module("cipher_aec.construction_finance.api", {
    "create_contract": ("POST", "CreateContractResponse", True),
    "author_revision": ("POST", "AuthorContractRevisionResponse", True),
    "get_record": ("GET", "GetContractRecordResponse"),
    "list_contracts": ("GET", "ListContractsResponse"),
})

AUTH_RPC = frozenset({"login", "logout", "frappe.auth.login", "frappe.auth.logout", "frappe.auth.get_logged_user"})
RPC = frozenset(ROUTES) | AUTH_RPC
