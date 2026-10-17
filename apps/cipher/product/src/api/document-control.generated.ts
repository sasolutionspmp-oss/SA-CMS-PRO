/* Generated from cipher_aec/document_control/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: a4a573432ee57c08b00d5a71d633877ca88c4ba229d1ee51b13aae05840ea806
 * Regenerate: npm run generate:api
 */

export type UrnCipherDocumentControlApiV1 =
  | DcSetRightsRequest
  | DcCreateLibraryRequest
  | DcReviseLibraryRequest
  | DcCreateAdoptionRequest
  | DcCreateIssueSetRequest
  | DcCreateTransmittalRequest
  | DcRecordEvidenceRequest
  | DcGetRecordRequest
  | DcListRecordsRequest
  | DcListPeopleRequest
  | DcSetRightsResponse
  | DcCreateLibraryResponse
  | DcReviseLibraryResponse
  | DcCreateAdoptionResponse
  | DcCreateIssueSetResponse
  | DcCreateTransmittalResponse
  | DcRecordEvidenceResponse
  | DcGetResponse
  | DcListResponse
  | DcPeopleResponse
  | DcCreateClauseUseRequest
  | DcCreateRedlineRequest
  | DcReadClauseTargetRequest
  | DcCreateSharedAdoptionRequest
  | DcIssuedStandingRequest
  | DcRequestLifecycleRequest
  | DcCreateClauseUseResponse
  | DcCreateRedlineResponse
  | DcClauseTargetResponse
  | DcCreateSharedAdoptionResponse
  | DcIssuedStandingResponse
  | DcRequestLifecycleResponse
  | DcCompanySetRightsRequest
  | DcCompanyCreateLibraryRequest
  | DcCompanyReviseLibraryRequest
  | DcCompanyGetRecordRequest
  | DcCompanyListRecordsRequest
  | DcCompanySetRightsResponse
  | DcCompanyCreateLibraryResponse
  | DcCompanyReviseLibraryResponse
  | DcCompanyGetResponse
  | DcCompanyListResponse;
export type DcRecord =
  | DcRights
  | DcLibrary
  | DcLibraryRevision
  | DcAdoptionRequest
  | DcAdoption
  | DcIssueSet
  | DcIssue
  | DcTransmittal
  | DcDistribution
  | DcEvidence
  | DcClauseUse
  | DcRedline
  | DcClauseApplication
  | DcSharedAdoptionRequest
  | DcLifecycleRequest
  | DcLifecycle;
export type DcClauseTarget =
  | {
      kind: "proposal_revision";
      id: string;
      record_digest: string;
      locator: string;
    }
  | {
      kind: "contract_revision";
      id: string;
      record_digest: string;
      locator: string;
    }
  | {
      kind: "document_revision";
      id: string;
      record_digest: string;
      locator: string;
    };
export type DcClauseTargetSnapshot =
  | {
      kind: "proposal_revision";
      id: string;
      record_digest: string;
      parent_id: string;
      company: string;
      project: null;
      scope_type: "Company";
    }
  | {
      kind: "contract_revision";
      id: string;
      record_digest: string;
      parent_id: string;
      company: string;
      project: string;
      scope_type: "Project";
    }
  | {
      kind: "document_revision";
      id: string;
      record_digest: string;
      parent_id: string;
      company: string;
      project: string;
      scope_type: "Project";
    };
export type DcLibraryScope =
  | {
      scope_type: "Company";
      project: null;
    }
  | {
      scope_type: "Project";
      project: string;
    };
export type DcLifecycleDefinition = {
  action: "withdraw" | "supersede";
  issue_id: string;
  issue_digest: string;
  replacement_issue_id: string | null;
  replacement_issue_digest: string | null;
  reason: string;
} & DcLifecycleDefinition1;
export type DcLifecycleDefinition1 =
  | {
      action?: "withdraw";
      replacement_issue_id?: null;
      replacement_issue_digest?: null;
      [k: string]: unknown;
    }
  | {
      action?: "supersede";
      replacement_issue_id?: string;
      replacement_issue_digest?: string;
      [k: string]: unknown;
    };
export type DcReadClauseTargetRequest = {
  company: string;
  project: string;
  kind: DcClauseTargetKind;
  record_id: string;
} & DcReadClauseTargetRequest1;
export type DcClauseTargetKind = "proposal_revision" | "contract_revision" | "document_revision";
export type DcReadClauseTargetRequest1 =
  | {
      company: string;
      project: string;
      kind: "proposal_revision";
      record_id: string;
    }
  | {
      company: string;
      project: string;
      kind: "contract_revision";
      record_id: string;
    }
  | {
      company: string;
      project: string;
      kind: "document_revision";
      record_id: string;
    };
export type DcCompanyRecord = DcCompanyRights | DcCompanyLibrary | DcCompanyLibraryRevision;

export interface DcSetRightsRequest {
  company: string;
  project: string;
  operation_id: string;
  document_id: string;
  expected_version: string | null;
  definition: DcRightsDefinition;
}
export interface DcRightsDefinition {
  ingest_allowed: boolean;
  read_allowed: boolean;
  distribute_allowed: boolean;
  rights_basis: string;
  rights_holder: string;
  allowed_purpose: string;
  restriction: string;
  valid_from: string | null;
  valid_until: string | null;
  evidence_artifact: DcArtifactInput;
}
export interface DcArtifactInput {
  revision_id: string;
  source_sha256: string;
}
export interface DcCreateLibraryRequest {
  company: string;
  project: string;
  operation_id: string;
  definition: DcLibraryDefinition;
  artifact: DcArtifactInput;
}
export interface DcLibraryDefinition {
  title: string;
  category: "specification" | "contract_clause" | "reference";
  discipline: string;
  ownership: string;
  /**
   * @minItems 0
   * @maxItems 20
   */
  tags: string[];
  change_reason: string;
}
export interface DcReviseLibraryRequest {
  company: string;
  project: string;
  operation_id: string;
  library_id: string;
  expected_version: string;
  definition: DcLibraryDefinition;
  artifact: DcArtifactInput;
}
export interface DcCreateAdoptionRequest {
  company: string;
  project: string;
  operation_id: string;
  library_revision: string;
  library_digest: string;
  definition: DcAdoptionDefinition;
}
export interface DcAdoptionDefinition {
  purpose: string;
  target_locator: string;
  change_reason: string;
}
export interface DcCreateIssueSetRequest {
  company: string;
  project: string;
  operation_id: string;
  definition: DcIssueDefinition;
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts: DcArtifactInput[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  adoptions: DcExactReference[];
}
export interface DcIssueDefinition {
  title: string;
  purpose: string;
  issue_purpose: "coordination" | "information" | "review" | "contract_reference";
}
export interface DcExactReference {
  id: string;
  record_digest: string;
}
export interface DcCreateTransmittalRequest {
  company: string;
  project: string;
  operation_id: string;
  issue_id: string;
  issue_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: string[];
  purpose: string;
  required_response: string;
}
export interface DcRecordEvidenceRequest {
  company: string;
  project: string;
  operation_id: string;
  subject_kind: "distribution" | "adoption";
  subject_id: string;
  subject_digest: string;
  statement: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: DcArtifactInput[];
}
export interface DcGetRecordRequest {
  company: string;
  project: string;
  kind:
    | "rights"
    | "library"
    | "library_revision"
    | "adoption_request"
    | "adoption"
    | "issue_set"
    | "issue"
    | "transmittal"
    | "distribution"
    | "evidence"
    | "clause_use"
    | "redline"
    | "clause_application"
    | "lifecycle_request"
    | "lifecycle";
  record_id: string;
}
export interface DcListRecordsRequest {
  company: string;
  project: string;
  kind:
    | "rights"
    | "library"
    | "library_revision"
    | "adoption_request"
    | "adoption"
    | "issue_set"
    | "issue"
    | "transmittal"
    | "distribution"
    | "evidence"
    | "clause_use"
    | "redline"
    | "clause_application"
    | "lifecycle_request"
    | "lifecycle";
  parent_id?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface DcListPeopleRequest {
  company: string;
  project: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface DcSetRightsResponse {
  rights: DcRights;
  history_id: string;
  operation: DcOperation;
}
export interface DcRights {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "authored_rights_basis";
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  revision_number: number;
  ingest_allowed: boolean;
  read_allowed: boolean;
  distribute_allowed: boolean;
  rights_basis: string;
  rights_holder: string;
  allowed_purpose: string;
  restriction: string;
  valid_from: string | null;
  valid_until: string | null;
  evidence_artifact: DcArtifact;
}
export interface DcNoEffects {
  commercial_change: false;
  contract_change: false;
  budget_change: false;
  schedule_change: false;
  quality_acceptance: false;
  professional_certification: false;
  external_transmission: false;
}
export interface DcArtifact {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
export interface DcOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
export interface DcCreateLibraryResponse {
  library: DcLibrary;
  library_revision: DcLibraryRevision;
  history_id: string;
  operation: DcOperation;
}
export interface DcLibrary {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  current_revision: string;
  revision_number: number;
}
export interface DcLibraryRevision {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  revision_number: number;
  definition: DcLibraryDefinition;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
}
export interface DcReviseLibraryResponse {
  library: DcLibrary;
  library_revision: DcLibraryRevision;
  history_id: string;
  operation: DcOperation;
}
export interface DcCreateAdoptionResponse {
  adoption_request: DcAdoptionRequest;
  history_id: string;
  operation: DcOperation;
}
export interface DcAdoptionRequest {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  parent_id: string;
  library_revision: string;
  library_digest: string;
  definition: DcAdoptionDefinition;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
}
export interface DcCreateIssueSetResponse {
  issue_set: DcIssueSet;
  history_id: string;
  operation: DcOperation;
}
export interface DcIssueSet {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  definition: DcIssueDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: DcArtifact[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  adoptions: DcExactReference[];
  package_digest: string;
}
export interface DcCreateTransmittalResponse {
  transmittal: DcTransmittal;
  history_id: string;
  operation: DcOperation;
}
export interface DcTransmittal {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  parent_id: string;
  issue_id: string;
  issue_digest: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: DcArtifact[];
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: DcPerson[];
  purpose: string;
  required_response: string;
  channel: "internal";
  package_digest: string;
}
export interface DcPerson {
  user: string;
  person: string;
}
export interface DcRecordEvidenceResponse {
  evidence: DcEvidence;
  history_id: string;
  operation: DcOperation;
}
export interface DcEvidence {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "reported_received" | "reported_execution";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_kind: "distribution" | "adoption";
  subject_id: string;
  subject_digest: string;
  statement: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: DcArtifact[];
  commercial_execution: false;
  electronic_signature: false;
}
export interface DcGetResponse {
  record: DcRecord;
  record_digest: string;
  library_current: boolean | null;
}
export interface DcAdoption {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "adopted";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
}
export interface DcIssue {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "issued";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: DcArtifact[];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
  package_digest: string;
}
export interface DcDistribution {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded_internally";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: DcArtifact[];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
  package_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: DcPerson[];
  channel: "internal";
}
export interface DcClauseUse {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "referenced";
  no_effects: DcNoEffects;
  parent_id: string;
  adoption_id: string;
  adoption_digest: string;
  source_clause: DcQuotedClause;
  target: DcClauseTarget;
  target_snapshot: DcClauseTargetSnapshot;
  purpose: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
  target_changed: false;
}
export interface DcQuotedClause {
  reference: DcClauseSourceReference;
  text: string;
  text_sha256: string;
}
export interface DcClauseSourceReference {
  revision_id: string;
  source_sha256: string;
  page: number;
  excerpt_sha256: string;
  start: number;
  end: number;
}
export interface DcRedline {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "proposed";
  no_effects: DcNoEffects;
  parent_id: string;
  clause_use_id: string;
  clause_use_digest: string;
  predecessor: string | null;
  revision_number: number;
  original_text: string;
  proposed_text: string;
  proposed_sha256: string;
  reason: string;
  target: DcClauseTarget;
  target_snapshot: DcClauseTargetSnapshot;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
  target_changed: false;
}
export interface DcClauseApplication {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "approved_relationship";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
  target: DcClauseTarget;
  target_snapshot: DcClauseTargetSnapshot;
  original_text: string;
  proposed_text: string;
  proposed_sha256: string;
  target_changed: false;
}
export interface DcSharedAdoptionRequest {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  parent_id: string;
  library_revision: string;
  library_digest: string;
  definition: DcAdoptionDefinition;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
  library_scope: DcLibraryScope;
}
export interface DcLifecycleRequest {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  parent_id: string;
  expected_version: string;
  before: DcIssuedStandingBody;
  definition: DcLifecycleDefinition;
  replacement: DcIssueReference | null;
  /**
   * @minItems 1
   * @maxItems 16
   */
  artifacts: DcArtifact[];
}
export interface DcIssuedStandingBody {
  company: string;
  project: string;
  scope_type: "Project";
  document_id: string;
  status: "not_issued" | "issued" | "withdrawn";
  original_issued: DcIssueReference | null;
  current_issued: DcIssueReference | null;
  last_event: DcLifecycleEventReference | null;
}
export interface DcIssueReference {
  issue_id: string;
  issue_digest: string;
  revision_id: string;
  source_sha256: string;
}
export interface DcLifecycleEventReference {
  id: string;
  record_digest: string;
}
export interface DcLifecycle {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "withdrawn" | "superseded";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  artifacts: DcArtifact[];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
  document_id: string;
  revision_number: number;
  predecessor: string | null;
  action: "withdraw" | "supersede";
  reason: string;
  replacement: DcIssueReference | null;
  before: DcIssuedStandingBody;
}
export interface DcListResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: DcGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
export interface DcPeopleResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: {
    user: string;
    person: string;
    display_name: string;
  }[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
export interface DcCreateClauseUseRequest {
  company: string;
  project: string;
  operation_id: string;
  adoption_id: string;
  adoption_digest: string;
  source_clause: DcClauseSourceReference;
  target: DcClauseTarget;
  purpose: string;
}
export interface DcCreateRedlineRequest {
  company: string;
  project: string;
  operation_id: string;
  clause_use_id: string;
  clause_use_digest: string;
  expected_version: string | null;
  proposed_text: string;
  reason: string;
}
export interface DcCreateSharedAdoptionRequest {
  company: string;
  project: string;
  operation_id: string;
  library_revision: string;
  library_digest: string;
  definition: DcAdoptionDefinition;
  library_scope: DcLibraryScope;
}
export interface DcIssuedStandingRequest {
  company: string;
  project: string;
  document_id: string;
}
export interface DcRequestLifecycleRequest {
  company: string;
  project: string;
  operation_id: string;
  document_id: string;
  expected_version: string;
  definition: DcLifecycleDefinition;
}
export interface DcCreateClauseUseResponse {
  clause_use: DcClauseUse;
  history_id: string;
  operation: DcOperation;
}
export interface DcCreateRedlineResponse {
  redline: DcRedline;
  history_id: string;
  operation: DcOperation;
}
export interface DcClauseTargetResponse {
  target: DcClauseTargetSnapshot;
}
export interface DcCreateSharedAdoptionResponse {
  adoption_request: DcSharedAdoptionRequest;
  history_id: string;
  operation: DcOperation;
}
export interface DcIssuedStandingResponse {
  standing: DcIssuedStanding;
}
export interface DcIssuedStanding {
  company: string;
  project: string;
  scope_type: "Project";
  document_id: string;
  status: "not_issued" | "issued" | "withdrawn";
  original_issued: DcIssueReference | null;
  current_issued: DcIssueReference | null;
  last_event: DcLifecycleEventReference | null;
  version: string;
}
export interface DcRequestLifecycleResponse {
  lifecycle_request: DcLifecycleRequest;
  history_id: string;
  operation: DcOperation;
}
export interface DcCompanySetRightsRequest {
  company: string;
  operation_id: string;
  document_id: string;
  expected_version: string | null;
  definition: DcRightsDefinition;
}
export interface DcCompanyCreateLibraryRequest {
  company: string;
  operation_id: string;
  definition: DcLibraryDefinition;
  artifact: DcArtifactInput;
}
export interface DcCompanyReviseLibraryRequest {
  company: string;
  operation_id: string;
  library_id: string;
  expected_version: string;
  definition: DcLibraryDefinition;
  artifact: DcArtifactInput;
}
export interface DcCompanyGetRecordRequest {
  company: string;
  kind: "rights" | "library" | "library_revision";
  record_id: string;
}
export interface DcCompanyListRecordsRequest {
  company: string;
  kind: "rights" | "library" | "library_revision";
  parent_id?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface DcCompanySetRightsResponse {
  rights: DcCompanyRights;
  history_id: string;
  operation: DcOperation;
}
export interface DcCompanyRights {
  id: string;
  company: string;
  project: null;
  scope_type: "Company";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "authored_rights_basis";
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  revision_number: number;
  ingest_allowed: boolean;
  read_allowed: boolean;
  distribute_allowed: boolean;
  rights_basis: string;
  rights_holder: string;
  allowed_purpose: string;
  restriction: string;
  valid_from: string | null;
  valid_until: string | null;
  evidence_artifact: DcArtifact;
}
export interface DcCompanyCreateLibraryResponse {
  library: DcCompanyLibrary;
  library_revision: DcCompanyLibraryRevision;
  history_id: string;
  operation: DcOperation;
}
export interface DcCompanyLibrary {
  id: string;
  company: string;
  project: null;
  scope_type: "Company";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  current_revision: string;
  revision_number: number;
}
export interface DcCompanyLibraryRevision {
  id: string;
  company: string;
  project: null;
  scope_type: "Company";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  revision_number: number;
  definition: DcLibraryDefinition;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: DcArtifact[];
}
export interface DcCompanyReviseLibraryResponse {
  library: DcCompanyLibrary;
  library_revision: DcCompanyLibraryRevision;
  history_id: string;
  operation: DcOperation;
}
export interface DcCompanyGetResponse {
  record: DcCompanyRecord;
  record_digest: string;
  library_current: boolean | null;
}
export interface DcCompanyListResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: DcCompanyGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
