/* Generated from cipher_aec/engineering_packages/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: ee1fdea90ff83eae25f3a040dbad41f2133c4353cf673d71e72ec318309741cf
 * Regenerate: npm run generate:api
 */

export type UrnCipherEngineeringPackagesApiV1 =
  | EpCreatePackageRequest
  | EpRevisePackageRequest
  | EpCreateBasisRequest
  | EpCreateCalculationRequest
  | EpCreateDeliverableRequest
  | EpGetRecordRequest
  | EpListRecordsRequest
  | EpListPeopleRequest
  | EpListUnitsRequest
  | EpCreatePackageResponse
  | EpRevisePackageResponse
  | EpCreateBasisResponse
  | EpCreateCalculationResponse
  | EpCreateDeliverableResponse
  | EpGetResponse
  | EpListResponse
  | EpPeopleResponse
  | EpUnitsResponse;
export type EpCanonicaluuid = string;
export type EpRecord = EpPackage | EpPackageRevision | EpBasis | EpCalculation | EpDeliverable | EpCheck;

export interface EpCreatePackageRequest {
  company: string;
  project: string;
  operation_id: string;
  definition: EpPackageDefinition;
}
export interface EpPackageDefinition {
  title: string;
  discipline: string;
  scope: string;
  responsible_user: string;
  checker_user: string;
  due_date: string | null;
  /**
   * @minItems 0
   * @maxItems 8
   */
  task_ids: string[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  wbs_ids: string[];
}
export interface EpRevisePackageRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  definition: EpPackageDefinition;
}
export interface EpCreateBasisRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  definition: EpBasisDefinition;
  /**
   * @minItems 0
   * @maxItems 32
   */
  quantities: EpQuantityRow[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations: EpCitationInput[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references: EpDrawingInput[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts: EpArtifactInput[];
}
export interface EpBasisDefinition {
  title: string;
  criteria: string;
  assumptions: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  design_codes: EpCode[];
  change_reason: string;
}
export interface EpCode {
  code: string;
  edition: string;
  clause: string;
}
export interface EpQuantityRow {
  key: string;
  label: string;
  quantity: EpQuantity;
  source: EpDrawingInput;
}
export interface EpQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
export interface EpDrawingInput {
  revision_id: string;
  source_sha256: string;
  page: number;
  locator: string;
}
export interface EpCitationInput {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256: string;
}
export interface EpArtifactInput {
  revision_id: string;
  source_sha256: string;
}
export interface EpCreateCalculationRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  basis_revision: string;
  basis_digest: string;
  definition: EpCalculationDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  input_keys: string[];
  /**
   * @minItems 0
   * @maxItems 32
   */
  outputs: EpQuantityRow[];
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts: EpArtifactInput[];
  predecessor: string | null;
}
export interface EpCalculationDefinition {
  title: string;
  method: "human-authored-results-v1";
  algorithm_reference: string;
  tool_name: string;
  tool_version: string;
  model_version: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  design_codes: EpCode[];
  explanation: string;
  change_reason: string;
}
export interface EpCreateDeliverableRequest {
  company: string;
  project: string;
  operation_id: string;
  package_id: string;
  expected_version: string;
  basis_revision: string;
  basis_digest: string;
  definition: EpDeliverableDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  calculations: EpCalculationReference[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations: EpCitationInput[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references: EpDrawingInput[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts: EpArtifactInput[];
  predecessor: string | null;
}
export interface EpDeliverableDefinition {
  title: string;
  deliverable_type: string;
  description: string;
  checking_notes: string;
  change_reason: string;
}
export interface EpCalculationReference {
  id: string;
  record_digest: string;
}
export interface EpGetRecordRequest {
  company: string;
  project: string;
  kind: "package" | "package_revision" | "basis" | "calculation" | "deliverable" | "check";
  record_id: string;
}
export interface EpListRecordsRequest {
  company: string;
  project: string;
  kind: "package" | "package_revision" | "basis" | "calculation" | "deliverable" | "check";
  parent_id?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface EpListPeopleRequest {
  company: string;
  project: string;
  role: "engineer" | "checker";
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface EpListUnitsRequest {
  company: string;
  project: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface EpCreatePackageResponse {
  package: EpPackage;
  revision: EpPackageRevision;
  history_id: string;
  operation: EpOperation;
}
export interface EpPackage {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: EpNoEffects;
  number: string;
  revision_number: number;
  current_revision: string;
  basis_head: string | null;
  /**
   * @minItems 0
   * @maxItems 20
   */
  calculation_heads: string[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  deliverable_heads: string[];
}
export interface EpNoEffects {
  commercial_change: false;
  contract_change: false;
  budget_change: false;
  schedule_change: false;
  quality_acceptance: false;
  professional_certification: false;
  external_transmission: false;
}
export interface EpPackageRevision {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: EpNoEffects;
  parent_id: string;
  revision_number: number;
  predecessor: string | null;
  definition: EpPackageDefinition;
  responsible: EpPerson;
  checker: EpPerson;
}
export interface EpPerson {
  user: string;
  person: string;
}
export interface EpOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
export interface EpRevisePackageResponse {
  package: EpPackage;
  revision: EpPackageRevision;
  history_id: string;
  operation: EpOperation;
}
export interface EpCreateBasisResponse {
  package: EpPackage;
  basis: EpBasis;
  history_id: string;
  operation: EpOperation;
}
export interface EpBasis {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: EpNoEffects;
  parent_id: string;
  family_id: string;
  revision_number: number;
  predecessor: string | null;
  package_revision: string;
  package_digest: string;
  checker: EpPerson;
  /**
   * @minItems 0
   * @maxItems 64
   */
  source_citations: EpCitation[];
  /**
   * @minItems 0
   * @maxItems 16
   */
  drawing_references: EpDrawingReference[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts: EpArtifact[];
  definition: EpBasisDefinition;
  /**
   * @minItems 0
   * @maxItems 32
   */
  quantities: EpQuantityRow[];
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
}
export interface EpCitation {
  id: string;
  document_id: string;
  revision_id: string;
  document_title: string;
  revision_number: number;
  page: number;
  page_label: string;
  excerpt: string;
  excerpt_sha256: string;
  source_sha256: string;
}
export interface EpDrawingReference {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: "application/pdf";
  page_count: number;
  page: number;
  locator: string;
}
export interface EpArtifact {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
export interface CipherIndependentCanonicalMasterDimensionManifestV1 {
  schema: "cipher.canonical.v1";
  dataset_id: EpCanonicaluuid;
  scope: {
    company: string;
    project: string;
  };
  label?: string;
  /**
   * @minItems 1
   * @maxItems 65
   */
  records: (
    | {
        id: EpCanonicaluuid;
        kind: "company";
        revision: number;
        fields: {
          name: string;
          currency: string;
          timezone: string | null;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "Company";
          name: string;
          version?: string;
        };
      }
    | {
        id: EpCanonicaluuid;
        kind: "uom";
        revision: number;
        fields: {
          symbol: string;
          dimension: "area" | "count" | "equipment_time" | "labor_time" | "length" | "mass" | "time" | "volume";
          precision: number;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "UOM";
          name: string;
          version?: string;
        };
      }
  )[];
  /**
   * @maxItems 0
   */
  unit_conversions: EpCanonicalconversion[];
  /**
   * @maxItems 500
   */
  quantities?: EpCanonicalquantity[];
}
export interface EpCanonicalconversion {
  id: EpCanonicaluuid;
  revision: number;
  from_unit_id: EpCanonicaluuid;
  to_unit_id: EpCanonicaluuid;
  dimension: "area" | "count" | "equipment_time" | "labor_time" | "length" | "mass" | "time" | "volume";
  numerator: string;
  denominator: string;
  source: string;
}
export interface EpCanonicalquantity {
  id: EpCanonicaluuid;
  amount: string;
  unit_id: EpCanonicaluuid;
  convert_to_unit_id?: EpCanonicaluuid;
}
export interface EpCreateCalculationResponse {
  package: EpPackage;
  calculation: EpCalculation;
  history_id: string;
  operation: EpOperation;
}
export interface EpCalculation {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: EpNoEffects;
  parent_id: string;
  family_id: string;
  revision_number: number;
  predecessor: string | null;
  package_revision: string;
  package_digest: string;
  checker: EpPerson;
  /**
   * @minItems 0
   * @maxItems 64
   */
  source_citations: EpCitation[];
  /**
   * @minItems 0
   * @maxItems 16
   */
  drawing_references: EpDrawingReference[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts: EpArtifact[];
  basis_revision: string;
  basis_digest: string;
  definition: EpCalculationDefinition;
  /**
   * @minItems 1
   * @maxItems 32
   */
  input_keys: string[];
  /**
   * @minItems 1
   * @maxItems 32
   */
  inputs: EpQuantityRow[];
  /**
   * @minItems 0
   * @maxItems 32
   */
  outputs: EpQuantityRow[];
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  execution: {
    kind: "manual-record";
    executed_by_cipher: false;
    solver_qualified: false;
  };
  issue_readiness: "not_authorized_for_issue";
}
export interface EpCreateDeliverableResponse {
  package: EpPackage;
  deliverable: EpDeliverable;
  history_id: string;
  operation: EpOperation;
}
export interface EpDeliverable {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  no_effects: EpNoEffects;
  parent_id: string;
  family_id: string;
  revision_number: number;
  predecessor: string | null;
  package_revision: string;
  package_digest: string;
  checker: EpPerson;
  /**
   * @minItems 0
   * @maxItems 64
   */
  source_citations: EpCitation[];
  /**
   * @minItems 0
   * @maxItems 16
   */
  drawing_references: EpDrawingReference[];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts: EpArtifact[];
  basis_revision: string;
  basis_digest: string;
  definition: EpDeliverableDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  calculations: EpCalculationReference[];
  issue_readiness: "not_authorized_for_issue";
}
export interface EpGetResponse {
  record: EpRecord;
  record_digest: string;
  review: EpReview | null;
}
export interface EpCheck {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "checked";
  no_effects: EpNoEffects;
  parent_id: string;
  subject_kind: "basis" | "calculation" | "deliverable";
  subject_id: string;
  subject_digest: string;
  package_revision: string;
  package_digest: string;
  checker: EpPerson;
  preparer_person: string;
  packet_id: string;
  decision_id: string;
  comments: string;
  outcome: "checked";
  issue_authorized: false;
  sealed: false;
}
export interface EpReview {
  state: "working" | "in_check" | "grant_awaiting_record" | "returned" | "checked";
  check_id: string | null;
  packet_id: string | null;
  issue_authorized: false;
}
export interface EpListResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: EpGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
export interface EpPeopleResponse {
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
export interface EpUnitsResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: EpUnitChoice[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
export interface EpUnitChoice {
  id: string;
  kind: "uom";
  revision: number;
  fields: {
    symbol: string;
    dimension: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
    precision: number;
  };
  target: {
    doctype: "UOM";
    name: string;
  };
}
