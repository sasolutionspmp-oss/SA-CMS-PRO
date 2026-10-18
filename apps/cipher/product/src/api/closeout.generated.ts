/* Generated from cipher_aec/closeout/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 8e6ed8ec2ee88dacaa1ed37001df34a8816979d84343460b93d6fb3afb124639
 * Regenerate: npm run generate:api
 */

/**
 * ENG-04 exact documentary commissioning and closeout. No external delivery, professional seal, operating authority, accounting, or automated test execution.
 */
export type CipherCloseoutContract =
  | CloseoutPackageDefinition
  | CloseoutRequirementInput
  | CloseoutLink
  | CloseoutSourceInput
  | CloseoutSource
  | CloseoutCommissioningResultDefinition
  | CloseoutPunchResultDefinition
  | CloseoutOMResultDefinition
  | CloseoutWarrantyResultDefinition
  | CloseoutTrainingResultDefinition
  | CloseoutAssetHandoverResultDefinition
  | CloseoutResultDefinition
  | CloseoutNoEffects
  | CloseoutAcceptedResult
  | CloseoutResultHead
  | CloseoutRequirementReference
  | CloseoutHeader
  | CloseoutPackageRevision
  | CloseoutRequirement
  | CloseoutResult
  | CloseoutDecision
  | CloseoutTurnover
  | CloseoutRecord
  | CloseoutOperation
  | CloseoutCommandResult
  | CloseoutRecordResult
  | CloseoutListResult
  | CreatePackageRequest
  | RevisePackageRequest
  | RecordResultRequest
  | AcceptResultRequest
  | AssembleTurnoverRequest
  | AcceptTurnoverRequest
  | GetRecordRequest
  | ListRecordsRequest;
export type CloseoutResultDefinition =
  | CloseoutCommissioningResultDefinition
  | CloseoutPunchResultDefinition
  | CloseoutOMResultDefinition
  | CloseoutWarrantyResultDefinition
  | CloseoutTrainingResultDefinition
  | CloseoutAssetHandoverResultDefinition;
export type CloseoutRecord =
  CloseoutHeader | CloseoutPackageRevision | CloseoutRequirement | CloseoutResult | CloseoutDecision | CloseoutTurnover;

export interface CloseoutPackageDefinition {
  title: string;
  description: string;
  asset_tag: string;
  location: string;
}
export interface CloseoutRequirementInput {
  item_id: string;
  title: string;
  category: "commissioning" | "punch" | "om" | "warranty" | "training" | "asset_handover";
  required: boolean;
  criteria: string;
}
export interface CloseoutLink {
  kind: "engineering_check" | "document_adoption" | "quality_closure";
  id: string;
  record_digest: string;
}
export interface CloseoutSourceInput {
  revision_id: string;
  source_sha256: string;
  page: number;
  locator: string;
}
export interface CloseoutSource {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
  page: number;
  locator: string;
}
export interface CloseoutCommissioningResultDefinition {
  outcome: "pass" | "fail";
  notes: string;
  performed_on: string;
  performed_by: string;
  test_method: string;
  observed_result: string;
  acceptance_criteria_as_recorded: string;
}
export interface CloseoutPunchResultDefinition {
  outcome: "pass" | "fail";
  notes: string;
  performed_on: string;
  performed_by: string;
}
export interface CloseoutOMResultDefinition {
  outcome: "pass" | "fail";
  notes: string;
  performed_on: string;
  performed_by: string;
  manual_title: string;
  manual_revision_as_recorded: string;
}
export interface CloseoutWarrantyResultDefinition {
  outcome: "pass" | "fail";
  notes: string;
  performed_on: string;
  performed_by: string;
  manufacturer: string;
  warranty_identifier: string;
  starts_on: string;
  expires_on: string;
}
export interface CloseoutTrainingResultDefinition {
  outcome: "pass" | "fail";
  notes: string;
  performed_on: string;
  performed_by: string;
  attendees_as_recorded: string;
}
export interface CloseoutAssetHandoverResultDefinition {
  outcome: "pass" | "fail";
  notes: string;
  performed_on: string;
  performed_by: string;
  asset_tag: string;
  serial_number: string;
  recipient_as_recorded: string;
}
export interface CloseoutNoEffects {
  engineering_approval: false;
  professional_seal: false;
  regulatory_approval: false;
  operating_authority: false;
  contract_change: false;
  budget_change: false;
  procurement_change: false;
  invoice_change: false;
  financial_posting: false;
  award_execution: false;
  external_transmission: false;
  owner_acceptance: false;
  asset_capitalization: false;
  automated_test_execution: false;
}
export interface CloseoutAcceptedResult {
  requirement_id: string;
  result_kind: "test_result" | "asset_handover";
  result_id: string;
  result_digest: string;
  decision_id: string;
  decision_digest: string;
}
export interface CloseoutResultHead {
  requirement_id: string;
  result_kind: "test_result" | "asset_handover";
  result_id: string;
}
export interface CloseoutRequirementReference {
  kind: "commissioning_requirement" | "requirement";
  id: string;
  record_digest: string;
}
export interface CloseoutHeader {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "draft" | "assembled" | "accepted";
  number: string;
  revision_number: number;
  current_revision: string;
  /**
   * @minItems 0
   * @maxItems 32
   */
  result_heads: CloseoutResultHead[];
  /**
   * @minItems 0
   * @maxItems 32
   */
  accepted_results: CloseoutAcceptedResult[];
  turnover_head: string | null;
  accepted_turnover: string | null;
}
export interface CloseoutPackageRevision {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded";
  parent_id: string;
  revision_number: number;
  predecessor: string | null;
  definition: CloseoutPackageDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  requirements: CloseoutRequirementReference[];
  amendment_of: string | null;
  amendment_reason: string;
  no_effects: CloseoutNoEffects;
}
export interface CloseoutRequirement {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded";
  parent_id: string;
  package_revision: string;
  revision_number: number;
  predecessor: string | null;
  item_id: string;
  title: string;
  category: "commissioning" | "punch" | "om" | "warranty" | "training" | "asset_handover";
  required: boolean;
  criteria: string;
  no_effects: CloseoutNoEffects;
}
export interface CloseoutResult {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded";
  parent_id: string;
  package_revision: string;
  requirement_id: string;
  requirement_digest: string;
  predecessor: string | null;
  definition: CloseoutResultDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  evidence: CloseoutSource[];
  /**
   * @minItems 0
   * @maxItems 12
   */
  links: CloseoutLink[];
  no_effects: CloseoutNoEffects;
}
export interface CloseoutDecision {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded";
  parent_id: string;
  package_revision: string;
  action: "accept_result" | "accept_turnover";
  subject_kind: "test_result" | "asset_handover" | "turnover";
  subject_id: string;
  subject_digest: string;
  comment: string;
  no_effects: CloseoutNoEffects;
}
export interface CloseoutTurnover {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded";
  parent_id: string;
  package_revision: string;
  package_digest: string;
  /**
   * @minItems 1
   * @maxItems 32
   */
  items: CloseoutAcceptedResult[];
  comment: string;
  no_effects: CloseoutNoEffects;
}
export interface CloseoutOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
export interface CloseoutCommandResult {
  package: CloseoutHeader;
  package_revision?: CloseoutPackageRevision;
  /**
   * @minItems 1
   * @maxItems 32
   */
  requirements?: CloseoutRequirement[];
  result?: CloseoutResult;
  decision?: CloseoutDecision;
  turnover?: CloseoutTurnover;
  history_id: string;
  operation: CloseoutOperation;
}
export interface CloseoutRecordResult {
  record: CloseoutRecord;
  record_digest: string;
}
export interface CloseoutListResult {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: CloseoutRecordResult[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
export interface CreatePackageRequest {
  company: string;
  project: string;
  operation_id: string;
  definition: CloseoutPackageDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  requirements: CloseoutRequirementInput[];
}
export interface RevisePackageRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  definition: CloseoutPackageDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  requirements: CloseoutRequirementInput[];
  amendment_reason?: string;
}
export interface RecordResultRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  requirement_id: string;
  definition: CloseoutResultDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  evidence: CloseoutSourceInput[];
  /**
   * @minItems 0
   * @maxItems 12
   */
  links: CloseoutLink[];
}
export interface AcceptResultRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  result_id: string;
  result_digest: string;
  comment: string;
}
export interface AssembleTurnoverRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  comment: string;
}
export interface AcceptTurnoverRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  turnover_id: string;
  turnover_digest: string;
  comment: string;
}
export interface GetRecordRequest {
  company: string;
  project: string;
  kind:
    | "package"
    | "package_revision"
    | "commissioning_requirement"
    | "requirement"
    | "test_result"
    | "asset_handover"
    | "decision"
    | "turnover";
  record_id: string;
}
export interface ListRecordsRequest {
  company: string;
  project: string;
  kind:
    | "package"
    | "package_revision"
    | "commissioning_requirement"
    | "requirement"
    | "test_result"
    | "asset_handover"
    | "decision"
    | "turnover";
  parent_id?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
