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
    "task": ("GET", "Task"), "task_choices": ("GET", "TaskChoices"),
    "assign_task": ("POST", "TaskControlResponse", True),
    "update_task_status": ("POST", "TaskControlResponse", True),
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
_module("cipher_aec.ricky.company_api", {
    "start_read": ("POST", "CompanyRickyStartReadResponse", True),
    "get_run": ("GET", "CompanyRickyRunResponse"),
    "run_events": ("GET", "CompanyRickyRunEventsResponse"),
    "cancel_run": ("POST", "CompanyRickyStopResponse", True),
})
_module("cipher_aec.ricky.company_proposal_api", {
    "start_proposal": ("POST", "CompanyRickyProposalStartResponse", True),
    "get_run": ("GET", "CompanyRickyProposalRunResponse"),
    "run_events": ("GET", "CompanyRickyProposalEventsResponse"),
    "get_proposal": ("GET", "CompanyRickyProposalResponse"),
    "cancel_run": ("POST", "CompanyRickyProposalStopResponse", True),
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

_module("cipher_aec.api.company_approvals", {
    "list_packets": ("GET", "CompanyApprovalList"), "read_packet": ("GET", "CompanyApprovalPacket"),
    "request_action": ("POST", "CompanyApprovalCommandResponse", True),
    "decide_packet": ("POST", "CompanyApprovalCommandResponse", True),
    "withdraw_packet": ("POST", "CompanyApprovalCommandResponse", True),
    "execute_packet": ("POST", "CompanyApprovalExecutionResponse", True),
})
_module("cipher_aec.api.masters", {name:("GET", "NativeMasterList") for name in ("parties", "price_lists", "units", "currencies", "items")})


_module("cipher_aec.documents.company_api", {
    "upload_document": ("POST", "CompanyDocumentUploadResponse", True),
    "list_documents": ("GET", "CompanyDocumentList"), "get_document": ("GET", "CompanyDocumentDetail"),
    "preview_revision": ("GET", "CompanyDocumentPreview"), "search_documents": ("GET", "CompanyCitationList"),
    "get_citation": ("GET", "CompanyCitation"), "download_revision": ("GET", "SourceBytes", False, True),
})

_module("cipher_aec.estimating.api", {"list_acceptances": ("GET", "ListEstimateAcceptancesResponse"), "acceptance_subject": ("GET", "EstimateAcceptanceSubjectResponse")})
_module("cipher_aec.estimating.company_api", {
    "register_unit": ("POST", "CompanyRegisterUnitResponse", True),
    "create_conversion": ("POST", "CompanyCreateConversionResponse", True),
    "create_rate": ("POST", "CompanyCreateRateResponse", True),
    "create_assembly": ("POST", "CompanyCreateAssemblyResponse", True),
    "create_estimate": ("POST", "CompanyCreateEstimateResponse", True),
    "calculate_revision": ("POST", "CompanyCalculateRevisionResponse", True),
    "get_record": ("GET", "CompanyEstRecordResponse"),
    "list_records": ("GET", "CompanyEstListResponse"),
    "list_units": ("GET", "CompanyListEstimateUnitsResponse"),
    "list_acceptances": ("GET", "CompanyListEstimateAcceptancesResponse"),
    "acceptance_subject": ("GET", "CompanyEstimateAcceptanceSubjectResponse"),
    "accepted_baseline_reference": ("GET", "CompanyAcceptedBaselineReferenceResponse"),
})
_module("cipher_aec.takeoff.company_api", {
    "create_set": ("POST", "CompanyTakeoffCreateSetResponse", True),
    "create_calibration": ("POST", "CompanyTakeoffCreateCalibrationResponse", True),
    "create_measurement": ("POST", "CompanyTakeoffCreateMeasurementResponse", True),
    "bind_line": ("POST", "CompanyTakeoffBindLineResponse", True),
    "get_record": ("GET", "CompanyTakeoffGetResponse"),
    "list_records": ("GET", "CompanyTakeoffListResponse"),
    "drawing_impact": ("GET", "CompanyTakeoffImpactResponse"),
    "compare_measurements": ("GET", "CompanyTakeoffCompareResponse"),
})

_module("cipher_aec.commercial.api", {
    "prepare_proposal_output": ("POST", "ComPreparedOutputCommand", True),
    "prepared_output": ("GET", "ComPreparedOutput"),
    "proposal_output_subject": ("GET", "ComOutputSubject"),
    "issue": ("GET", "ComIssue"), "issues": ("GET", "ComIssueList"),
})

_module("cipher_aec.integrations.distribution_api", {
    "create_instruction": ("POST", "DistCreateInstructionResponse", True),
    "get_instruction": ("GET", "DistInstructionResponse"),
    "get_dispatch": ("GET", "DistDispatchDetail"),
    "get_recipient_delivery": ("GET", "DistRecipientDelivery"),
    "list_dispatches": ("GET", "DistDispatchList"),
    "cancel_dispatch": ("POST", "DistCancelResponse", True),
    "profiles": ("GET", "DistProfiles"),
    "recipient_choices": ("GET", "DistRecipientChoices"),
    "list_instructions": ("GET", "DistInstructionList"),
})

_module("cipher_aec.api.masters", {name:("GET", "NativeMasterList") for name in ("cost_centers", "accounts", "award_items")})
_module("cipher_aec.project_controls.company_api", {
    "create_master": ("POST", "PcMasterCommand", True), "revise_master": ("POST", "PcMasterCommand", True),
    "get_revision": ("GET", "PcResolvedRevision"), "list_masters": ("GET", "PcMasterPage"),
})
_module("cipher_aec.project_controls.api", {"get_record": ("GET", "PcProjectRecord"), "list_records": ("GET", "PcProjectPage")})
_module("cipher_aec.awards.api", {
    "list_handoffs": ("GET", "AwHandoffList"), "get_handoff": ("GET", "AwHandoffResponse"),
    "get_plan": ("GET", "AwPlanResponse"), "approval_subject": ("GET", "AwApprovalSubject"),
    "delegation_policy": ("GET", "AwDelegationPolicyResponse"), "team_choices": ("GET", "AwTeamChoices"),
    "source_preview": ("GET", "AwSourcePreview"), "preview_plan": ("POST", "AwPlanPreview"),
    "create_handoff": ("POST", "AwHandoffCommand", True), "plan_handoff": ("POST", "AwPlanCommand", True),
})

_module("cipher_aec.ricky.company_draft_save_api", {
    "draft_save_subject": ("GET", "CompanyDraftSaveSubject"),
    "save_draft": ("POST", "CompanyDraftSaveResponse", True),
})

_module("cipher_aec.engineering.api", {
    'create_rfi': ('POST', 'EgCreateRfiResponse', True),
    'revise_rfi': ('POST', 'EgReviseRfiResponse', True),
    'create_response': ('POST', 'EgCreateResponseResponse', True),
    'create_submittal': ('POST', 'EgCreateSubmittalResponse', True),
    'revise_submission': ('POST', 'EgReviseSubmissionResponse', True),
    'create_disposition': ('POST', 'EgCreateDispositionResponse', True),
    'create_transmittal': ('POST', 'EgCreateTransmittalResponse', True),
    'close_rfi': ('POST', 'EgCloseRfiResponse', True),
    'list_people': ('GET', 'EgPeopleResponse'),
    'get_record': ('GET', 'EgGetResponse'),
    'list_records': ('GET', 'EgListResponse'),
})

_module("cipher_aec.engineering_packages.api", {
    'create_package': ('POST', 'EpCreatePackageResponse', True),
    'revise_package': ('POST', 'EpRevisePackageResponse', True),
    'create_basis': ('POST', 'EpCreateBasisResponse', True),
    'create_calculation': ('POST', 'EpCreateCalculationResponse', True),
    'create_deliverable': ('POST', 'EpCreateDeliverableResponse', True),
    'get_record': ('GET', 'EpGetResponse'),
    'list_records': ('GET', 'EpListResponse'),
    'list_people': ('GET', 'EpPeopleResponse'),
    'list_units': ('GET', 'EpUnitsResponse'),
})


_module("cipher_aec.document_control.api", {
    'issued_standing': ('GET', 'DcIssuedStandingResponse'),
    'request_lifecycle': ('POST', 'DcRequestLifecycleResponse', True),
    "create_shared_adoption": ("POST", "DcCreateSharedAdoptionResponse", True),
    "create_clause_use": ("POST", "DcCreateClauseUseResponse", True),
    "create_redline": ("POST", "DcCreateRedlineResponse", True),
    "read_clause_target": ("GET", "DcClauseTargetResponse"),'set_rights': ('POST', 'DcSetRightsResponse', True), 'create_library': ('POST', 'DcCreateLibraryResponse', True), 'revise_library': ('POST', 'DcReviseLibraryResponse', True), 'create_adoption': ('POST', 'DcCreateAdoptionResponse', True), 'create_issue_set': ('POST', 'DcCreateIssueSetResponse', True), 'create_transmittal': ('POST', 'DcCreateTransmittalResponse', True), 'record_evidence': ('POST', 'DcRecordEvidenceResponse', True), 'get_record': ('GET', 'DcGetResponse'), 'list_records': ('GET', 'DcListResponse'), 'list_people': ('GET', 'DcPeopleResponse')})

_module("cipher_aec.document_control.company_api", {
    'set_rights': ('POST', 'DcCompanySetRightsResponse', True),
    'create_library': ('POST', 'DcCompanyCreateLibraryResponse', True),
    'revise_library': ('POST', 'DcCompanyReviseLibraryResponse', True),
    'get_record': ('GET', 'DcCompanyGetResponse'),
    'list_records': ('GET', 'DcCompanyListResponse'),
})

_module("cipher_aec.field.api", {
    'create_record': ('POST', 'FdCreateRecordResponse', True),
    'revise_record': ('POST', 'FdReviseRecordResponse', True),
    'transition': ('POST', 'FdTransitionResponse', True),
    'get_record': ('GET', 'FdGetResponse'),
    'list_records': ('GET', 'FdListResponse'),
})

_module("cipher_aec.api.semantic", {
    'prepare': ('POST', 'SemanticJobResponse', True),
    'cancel': ('POST', 'SemanticJobResponse', True),
    'status': ('POST', 'SemanticJobResponse'),
    'query': ('POST', 'SemanticQueryResponse'),
})

_module('cipher_aec.field_offline.api', {
    'register_device': ('POST', 'FoDeviceMutationResponse', True),
    'revoke_device': ('POST', 'FoDeviceMutationResponse', True),
    'stage_capture': ('POST', 'FoCaptureMutationResponse', True),
    'get_capture': ('GET', 'FoGetCaptureResponse'),
    'inspect_capture': ('GET', 'FoInspectCaptureResponse'),
    'apply_capture': ('POST', 'FoApplyCaptureResponse', True),
    'discard_capture': ('POST', 'FoCaptureMutationResponse', True),
    'resolve_capture': ('POST', 'FoCaptureMutationResponse', True),
})

_module('cipher_aec.quality_safety.api', {
    'upload_evidence': ('POST', 'QsUploadEvidenceResponse', True),
    'create_record': ('POST', 'QsCreateRecordResponse', True),
    'revise_record': ('POST', 'QsReviseRecordResponse', True),
    'transition': ('POST', 'QsTransitionResponse', True),
    'get_record': ('GET', 'QsGetResponse'),
    'list_records': ('GET', 'QsListResponse'),
})

AUTH_RPC = frozenset({"login", "logout", "frappe.auth.login", "frappe.auth.logout", "frappe.auth.get_logged_user"})
RPC = frozenset(ROUTES) | AUTH_RPC

