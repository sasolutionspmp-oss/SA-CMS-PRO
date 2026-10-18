/* Generated from cipher_aec/quality_safety/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 8e744f7623040beb7455b795d2005b657864eee76a3af1082a39c3afd740eced
 * Regenerate: npm run generate:api
 */

export type UrnCipherQualitySafetyApiV1 =
  | QsUploadEvidenceRequest
  | QsCreateRecordRequest
  | QsReviseRecordRequest
  | QsTransitionRequest
  | QsGetRecordRequest
  | QsListRecordsRequest
  | QsUploadEvidenceResponse
  | QsCreateRecordResponse
  | QsReviseRecordResponse
  | QsTransitionResponse
  | QsGetResponse
  | QsListResponse;
export type QsUuid = string;
export type QsDigest = string;
export type QsCreateRecordRequest =
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: "record";
      category: "inspection" | "deficiency" | "safety_observation";
      definition: QsOrdinaryDefinition;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsSourceInput[];
    }
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: "record";
      category: "permit_record";
      definition: QsPermitDefinition;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsSourceInput[];
    }
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: "incident";
      category: "incident";
      definition: QsIncidentDefinition;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsSourceInput[];
    };
export type QsDate = string;
export type QsTimestamp = string;
export type QsReviseRecordRequest =
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: "record";
      record_id: QsUuid;
      expected_version: QsDigest;
      definition: QsOrdinaryDefinition | QsPermitDefinition;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsSourceInput[];
      amendment_reason?: string;
    }
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: "incident";
      record_id: QsUuid;
      expected_version: QsDigest;
      definition: QsIncidentDefinition;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsSourceInput[];
      amendment_reason?: string;
    };
export type QsTransitionRequest =
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: QsFamily;
      record_id: QsUuid;
      expected_version: QsDigest;
      action: "submit";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsSourceInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosureInput[];
    }
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: QsFamily;
      record_id: QsUuid;
      expected_version: QsDigest;
      action: "check";
      comment: string;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsSourceInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosureInput[];
    }
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: QsFamily;
      record_id: QsUuid;
      expected_version: QsDigest;
      action: "return";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsSourceInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosureInput[];
    }
  | {
      company: string;
      project: string;
      operation_id: QsUuid;
      family: QsFamily;
      record_id: QsUuid;
      expected_version: QsDigest;
      action: "close";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsSourceInput[];
      /**
       * @minItems 1
       * @maxItems 12
       */
      closure: QsClosureInput[];
    };
export type QsFamily = "record" | "incident";
export type QsKind = "record" | "revision" | "decision" | "incident" | "incident_revision" | "incident_decision";
export type QsCreateRecordResponse =
  | {
      family: "record";
      header: QsOrdinaryHeader;
      revision: QsOrdinaryRevision;
      history_id: string | null;
      operation: QsOperation;
    }
  | {
      family: "incident";
      header: QsIncidentHeader;
      revision: QsIncidentRevision;
      history_id: (string | null) & null;
      operation: QsOperation;
    };
export type QsReviseRecordResponse =
  | {
      family: "record";
      header: QsOrdinaryHeader;
      revision: QsOrdinaryRevision;
      history_id: string | null;
      operation: QsOperation;
    }
  | {
      family: "incident";
      header: QsIncidentHeader;
      revision: QsIncidentRevision;
      history_id: (string | null) & null;
      operation: QsOperation;
    };
export type QsTransitionResponse =
  | {
      family: "record";
      header: QsOrdinaryHeader;
      revision: QsOrdinaryRevision;
      history_id: string | null;
      operation: QsOperation;
      decision: QsOrdinaryDecision;
    }
  | {
      family: "incident";
      header: QsIncidentHeader;
      revision: QsIncidentRevision;
      history_id: (string | null) & null;
      operation: QsOperation;
      decision: QsIncidentDecision;
    };
export type QsOrdinaryDecision =
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "inspection" | "deficiency" | "safety_observation" | "permit_record";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "submit";
      from_status: "draft";
      to_status: "submitted";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosure[];
      checked_by_person: (string | null) & null;
      no_effects: QsNoEffects;
    }
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "inspection" | "deficiency" | "safety_observation" | "permit_record";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "check";
      from_status: "submitted";
      to_status: "checked";
      comment: string;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosure[];
      checked_by_person: (string | null) & null;
      no_effects: QsNoEffects;
    }
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "inspection" | "deficiency" | "safety_observation" | "permit_record";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "return";
      from_status: "submitted" | "checked";
      to_status: "returned";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosure[];
      checked_by_person: (string | null) & null;
      no_effects: QsNoEffects;
    }
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "inspection" | "deficiency" | "safety_observation" | "permit_record";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "close";
      from_status: "checked";
      to_status: "closed";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 1
       * @maxItems 12
       */
      closure: QsClosure[];
      checked_by_person: string;
      no_effects: QsNoEffects;
    };
export type QsIncidentDecision =
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "incident";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "submit";
      from_status: "draft";
      to_status: "submitted";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosure[];
      checked_by_person: (string | null) & null;
      no_effects: QsNoEffects;
    }
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "incident";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "check";
      from_status: "submitted";
      to_status: "checked";
      comment: string;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosure[];
      checked_by_person: (string | null) & null;
      no_effects: QsNoEffects;
    }
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "incident";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "return";
      from_status: "submitted" | "checked";
      to_status: "returned";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      closure: QsClosure[];
      checked_by_person: (string | null) & null;
      no_effects: QsNoEffects;
    }
  | {
      id: QsUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: QsTimestamp;
      status: "recorded";
      category: "incident";
      parent_id: QsUuid;
      source_revision: QsUuid;
      source_digest: QsDigest;
      predecessor: QsUuid | null;
      action: "close";
      from_status: "checked";
      to_status: "closed";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: QsCapturedSource[];
      /**
       * @minItems 1
       * @maxItems 12
       */
      closure: QsClosure[];
      checked_by_person: string;
      no_effects: QsNoEffects;
    };
export type QsRecord =
  | QsOrdinaryHeader
  | QsOrdinaryRevision
  | QsOrdinaryDecision
  | QsIncidentHeader
  | QsIncidentRevision
  | QsIncidentDecision;

export interface QsUploadEvidenceRequest {
  company: string;
  project: string;
  operation_id: QsUuid;
  title: string;
  filename: string;
  content_base64: string;
  byte_length: number;
  sha256: QsDigest;
  rights_basis: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  permission_evidence: QsSourceInput[];
}
export interface QsSourceInput {
  revision_id: string;
  source_sha256: QsDigest;
  page: number;
  locator: string;
}
export interface QsOrdinaryDefinition {
  title: string;
  local_date: QsDate;
  location: string;
  description: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  required_closure_items: QsClosureRequirement[];
}
export interface QsClosureRequirement {
  item_id: QsUuid;
  description: string;
}
export interface QsPermitDefinition {
  title: string;
  local_date: QsDate;
  location: string;
  description: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  required_closure_items: QsClosureRequirement[];
  issuer_as_recorded: string;
  permit_identifier: string;
  valid_from: QsTimestamp;
  valid_until: QsTimestamp;
  conditions_as_recorded: string;
}
export interface QsIncidentDefinition {
  title: string;
  local_date: QsDate;
  location: string;
  description: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  required_closure_items: QsClosureRequirement[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  involved_people: string[];
  restricted_account: string;
  immediate_response: string;
  /**
   * @minItems 0
   * @maxItems 32
   */
  shared_evidence_revisions: string[];
  shared_evidence_statement: string;
}
export interface QsClosureInput {
  item_id: QsUuid;
  /**
   * @minItems 1
   * @maxItems 8
   */
  evidence: QsSourceInput[];
}
export interface QsGetRecordRequest {
  company: string;
  project: string;
  kind: QsKind;
  record_id: QsUuid;
}
export interface QsListRecordsRequest {
  company: string;
  project: string;
  kind: QsKind;
  parent_id?: QsUuid | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface QsUploadEvidenceResponse {
  family: "incident";
  evidence_upload: true;
  document: QsUploadedDocument;
  revision: QsUploadedRevision;
  registration: QsEvidenceRegistration;
  history_id: null;
  operation: QsOperation;
}
export interface QsUploadedDocument {
  id: string;
  revision_number: number;
  filename: string;
  mime_type: "text/plain" | "application/pdf" | "image/jpeg" | "image/png";
  byte_length: number;
  sha256: QsDigest;
  scan_status: "clean" | "infected" | "not_scanned" | "unavailable";
  retrieval_status: "available" | "quarantined";
  extraction_status: string;
  extractor_version: string;
  page_count: number;
  extraction_warning: string | null;
  title: string;
  current_revision: string;
  company: string;
  project: string;
}
export interface QsUploadedRevision {
  id: string;
  revision_number: number;
  filename: string;
  mime_type: "text/plain" | "application/pdf" | "image/jpeg" | "image/png";
  byte_length: number;
  sha256: QsDigest;
  scan_status: "clean" | "infected" | "not_scanned" | "unavailable";
  retrieval_status: "available" | "quarantined";
  extraction_status: string;
  extractor_version: string;
  page_count: number;
  extraction_warning: string | null;
}
export interface QsEvidenceRegistration {
  id: QsUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: QsTimestamp;
  document_id: string;
  rights_basis: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  permission_evidence: QsCapturedSource[];
  classification: "restricted_from_creation";
}
export interface QsCapturedSource {
  revision_id: string;
  source_sha256: QsDigest;
  page: number;
  locator: string;
  document_id: string;
  revision_number: number;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
export interface QsOperation {
  id: QsUuid;
  status: "succeeded";
  replayed: boolean;
}
export interface QsOrdinaryHeader {
  id: QsUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: QsTimestamp;
  status: "draft" | "submitted" | "checked" | "returned" | "closed";
  category: "inspection" | "deficiency" | "safety_observation" | "permit_record";
  number: string;
  revision_number: number;
  current_revision: QsUuid;
  last_decision: QsUuid | null;
  closed_revision: QsUuid | null;
}
export interface QsOrdinaryRevision {
  id: QsUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: QsTimestamp;
  status: "recorded";
  category: "inspection" | "deficiency" | "safety_observation" | "permit_record";
  parent_id: QsUuid;
  revision_number: number;
  predecessor: QsUuid | null;
  prior_decision: QsUuid | null;
  amendment_of: QsUuid | null;
  amendment_reason: string;
  definition: QsOrdinaryDefinition | QsPermitDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  evidence: QsCapturedSource[];
  no_effects: QsNoEffects;
}
export interface QsNoEffects {
  contract_change: false;
  budget_change: false;
  procurement_change: false;
  invoice_change: false;
  financial_posting: false;
  payroll_release: false;
  award_execution: false;
  engineering_approval: false;
  regulatory_approval: false;
  hazardous_work_authority: false;
  medical_advice: false;
  compliance_certification: false;
  external_transmission: false;
}
export interface QsIncidentHeader {
  id: QsUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: QsTimestamp;
  status: "draft" | "submitted" | "checked" | "returned" | "closed";
  category: "incident";
  number: string;
  revision_number: number;
  current_revision: QsUuid;
  last_decision: QsUuid | null;
  closed_revision: QsUuid | null;
}
export interface QsIncidentRevision {
  id: QsUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: QsTimestamp;
  status: "recorded";
  category: "incident";
  parent_id: QsUuid;
  revision_number: number;
  predecessor: QsUuid | null;
  prior_decision: QsUuid | null;
  amendment_of: QsUuid | null;
  amendment_reason: string;
  definition: QsIncidentDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  evidence: QsCapturedSource[];
  no_effects: QsNoEffects;
}
export interface QsClosure {
  item_id: QsUuid;
  /**
   * @minItems 1
   * @maxItems 8
   */
  evidence: QsCapturedSource[];
}
export interface QsGetResponse {
  record: QsRecord;
  record_digest: QsDigest;
}
export interface QsListResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: QsGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
