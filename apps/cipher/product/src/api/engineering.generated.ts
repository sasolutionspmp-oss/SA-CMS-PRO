/* Generated from cipher_aec/engineering/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 7e4c3698034b7114f489a917fa08909d39a9d353fb6a855a1330d6757cf8cd95
 * Regenerate: npm run generate:api
 */

export type CipherEngineeringContract =
  | EgCreateRfiRequest
  | EgReviseRfiRequest
  | EgCreateResponseRequest
  | EgCreateSubmittalRequest
  | EgReviseSubmissionRequest
  | EgCreateDispositionRequest
  | EgCreateTransmittalRequest
  | EgCloseRfiRequest
  | EgGetRecordRequest
  | EgListPeopleRequest
  | EgListRecordsRequest
  | EgCreateRfiResponse
  | EgReviseRfiResponse
  | EgCreateResponseResponse
  | EgCreateSubmittalResponse
  | EgReviseSubmissionResponse
  | EgCreateDispositionResponse
  | EgCreateTransmittalResponse
  | EgCloseRfiResponse
  | EgGetResponse
  | EgListResponse
  | EgPeopleResponse;
export type EgRecord =
  | EgRfi
  | EgRfiRevision
  | EgResponse
  | EgOfficialResponse
  | EgSubmittal
  | EgSubmission
  | EgDisposition
  | EgOfficialDisposition
  | EgTransmittal
  | EgDistribution;

export interface EgCreateRfiRequest {
  company: string;
  project: string;
  operation_id: string;
  definition: EgRfiDefinition;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitationInput]
    | [EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references:
    | []
    | [EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput
      ];
}
export interface EgRfiDefinition {
  subject: string;
  question: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  responsible_users:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  due_date: string | null;
  location: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  contract_citation_ids:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
}
export interface EgCitationInput {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256: string;
}
export interface EgDrawingInput {
  revision_id: string;
  source_sha256: string;
  page: number;
  locator: string;
}
export interface EgReviseRfiRequest {
  company: string;
  project: string;
  operation_id: string;
  rfi_id: string;
  expected_version: string;
  definition: EgRfiDefinition;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitationInput]
    | [EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references:
    | []
    | [EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput, EgDrawingInput]
    | [
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput,
        EgDrawingInput
      ];
}
export interface EgCreateResponseRequest {
  company: string;
  project: string;
  operation_id: string;
  rfi_id: string;
  source_revision: string;
  expected_version: string;
  definition: EgResponseDefinition;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitationInput]
    | [EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ];
  predecessor: string | null;
}
export interface EgResponseDefinition {
  answer: string;
  potential_cost_impact: string;
  potential_schedule_impact: string;
}
export interface EgCreateSubmittalRequest {
  company: string;
  project: string;
  operation_id: string;
  definition: EgSubmissionDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput
      ]
    | [
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput
      ];
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitationInput]
    | [EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ];
}
export interface EgSubmissionDefinition {
  title: string;
  specification_section: string;
  equipment_tag: string;
  required_date: string | null;
  contractor: string;
  reviewer_user: string;
  submission_standing: "submitted" | "resubmitted";
}
export interface EgArtifactInput {
  revision_id: string;
  source_sha256: string;
}
export interface EgReviseSubmissionRequest {
  company: string;
  project: string;
  operation_id: string;
  submittal_id: string;
  expected_version: string;
  definition: EgSubmissionDefinition;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput, EgArtifactInput]
    | [
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput
      ]
    | [
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput,
        EgArtifactInput
      ];
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitationInput]
    | [EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ];
}
export interface EgCreateDispositionRequest {
  company: string;
  project: string;
  operation_id: string;
  submittal_id: string;
  source_revision: string;
  expected_version: string;
  definition: EgDispositionDefinition;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitationInput]
    | [EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput, EgCitationInput]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ]
    | [
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput,
        EgCitationInput
      ];
  predecessor: string | null;
}
export interface EgDispositionDefinition {
  disposition: "approved" | "approved_as_noted" | "revise_resubmit" | "rejected";
  comments: string;
}
export interface EgCreateTransmittalRequest {
  company: string;
  project: string;
  operation_id: string;
  subject_kind: "official_response" | "official_disposition";
  subject_id: string;
  subject_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [string, ...string[]];
  purpose: string;
  required_response: string;
}
export interface EgCloseRfiRequest {
  company: string;
  project: string;
  operation_id: string;
  rfi_id: string;
  expected_version: string;
  official_response: string;
  reason: string;
}
export interface EgGetRecordRequest {
  company: string;
  project: string;
  kind:
    | "rfi"
    | "rfi_revision"
    | "response"
    | "official_response"
    | "submittal"
    | "submission"
    | "disposition"
    | "official_disposition"
    | "transmittal"
    | "distribution";
  record_id: string;
}
export interface EgListPeopleRequest {
  company: string;
  project: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface EgListRecordsRequest {
  company: string;
  project: string;
  kind:
    | "rfi"
    | "rfi_revision"
    | "response"
    | "official_response"
    | "submittal"
    | "submission"
    | "disposition"
    | "official_disposition"
    | "transmittal"
    | "distribution";
  parent_id?: string | null;
  subject_id?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface EgCreateRfiResponse {
  rfi: EgRfi;
  revision: EgRfiRevision;
  history_id: string;
  operation: EgOperation;
}
export interface EgRfi {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "open" | "closed";
  number: string;
  revision_number: number;
  current_revision: string;
  response_head: string | null;
  official_response: string | null;
  closure?: {
    official_response: string;
    reason: string;
    person: string;
    at: string;
  };
}
export interface EgRfiRevision {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  parent_id: string;
  revision_number: number;
  predecessor: string | null;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitation]
    | [EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts:
    | []
    | [EgArtifact]
    | [EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references:
    | []
    | [EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ];
  no_effects: EgNoEffects;
  definition: EgRfiDefinition;
  /**
   * @minItems 0
   * @maxItems 8
   */
  responsible_people:
    | []
    | [EgPerson]
    | [EgPerson, EgPerson]
    | [EgPerson, EgPerson, EgPerson]
    | [EgPerson, EgPerson, EgPerson, EgPerson]
    | [EgPerson, EgPerson, EgPerson, EgPerson, EgPerson]
    | [EgPerson, EgPerson, EgPerson, EgPerson, EgPerson, EgPerson]
    | [EgPerson, EgPerson, EgPerson, EgPerson, EgPerson, EgPerson, EgPerson]
    | [EgPerson, EgPerson, EgPerson, EgPerson, EgPerson, EgPerson, EgPerson, EgPerson];
}
export interface EgCitation {
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
export interface EgArtifact {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
export interface EgDrawingReference {
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
export interface EgNoEffects {
  commercial_change: false;
  contract_change: false;
  budget_change: false;
  schedule_change: false;
  quality_acceptance: false;
  professional_certification: false;
  external_transmission: false;
}
export interface EgPerson {
  user: string;
  person: string;
}
export interface EgOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
export interface EgReviseRfiResponse {
  rfi: EgRfi;
  revision: EgRfiRevision;
  history_id: string;
  operation: EgOperation;
}
export interface EgCreateResponseResponse {
  rfi: EgRfi;
  response: EgResponse;
  history_id: string;
  operation: EgOperation;
}
export interface EgResponse {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  parent_id: string;
  revision_number: number;
  predecessor: string | null;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitation]
    | [EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts:
    | []
    | [EgArtifact]
    | [EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references:
    | []
    | [EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ];
  no_effects: EgNoEffects;
  definition: EgResponseDefinition;
  source_revision: string;
  source_digest: string;
}
export interface EgCreateSubmittalResponse {
  submittal: EgSubmittal;
  submission: EgSubmission;
  history_id: string;
  operation: EgOperation;
}
export interface EgSubmittal {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "open";
  number: string;
  revision_number: number;
  current_submission: string;
  disposition_head: string | null;
  official_disposition: string | null;
}
export interface EgSubmission {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  parent_id: string;
  revision_number: number;
  predecessor: string | null;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitation]
    | [EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts:
    | []
    | [EgArtifact]
    | [EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references:
    | []
    | [EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ];
  no_effects: EgNoEffects;
  definition: EgSubmissionDefinition;
  reviewer: EgPerson;
}
export interface EgReviseSubmissionResponse {
  submittal: EgSubmittal;
  submission: EgSubmission;
  history_id: string;
  operation: EgOperation;
}
export interface EgCreateDispositionResponse {
  submittal: EgSubmittal;
  disposition: EgDisposition;
  history_id: string;
  operation: EgOperation;
}
export interface EgDisposition {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "working";
  parent_id: string;
  revision_number: number;
  predecessor: string | null;
  /**
   * @minItems 0
   * @maxItems 8
   */
  source_citations:
    | []
    | [EgCitation]
    | [EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation]
    | [EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation, EgCitation];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts:
    | []
    | [EgArtifact]
    | [EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
  /**
   * @minItems 0
   * @maxItems 8
   */
  drawing_references:
    | []
    | [EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ];
  no_effects: EgNoEffects;
  definition: EgDispositionDefinition;
  source_revision: string;
  source_digest: string;
}
export interface EgCreateTransmittalResponse {
  transmittal: EgTransmittal;
  history_id: string;
  operation: EgOperation;
}
export interface EgTransmittal {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "awaiting_independent_authorization";
  subject: {
    kind: "official_response" | "official_disposition";
    id: string;
  };
  subject_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [EgPerson, ...EgPerson[]];
  purpose: string;
  required_response: string;
  channel: "internal";
  /**
   * @minItems 0
   * @maxItems 64
   */
  source_citations: EgCitation[];
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [EgArtifact]
    | [EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
    | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
  /**
   * @minItems 0
   * @maxItems 16
   */
  drawing_references:
    | []
    | [EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ]
    | [
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference,
        EgDrawingReference
      ];
  package_digest: string;
  no_effects: EgNoEffects;
}
export interface EgCloseRfiResponse {
  rfi: EgRfi;
  history_id: string;
  operation: EgOperation;
}
export interface EgGetResponse {
  record: EgRecord;
  record_digest: string;
}
export interface EgOfficialResponse {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "official";
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  no_effects: EgNoEffects;
  authority: "internal-technical-only";
  parent_id: string;
  source_revision: string;
  source_digest: string;
}
export interface EgOfficialDisposition {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "official";
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  no_effects: EgNoEffects;
  authority: "internal-technical-only";
  parent_id: string;
  source_revision: string;
  source_digest: string;
}
export interface EgDistribution {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded_internally";
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  no_effects: EgNoEffects;
  authority: "internal-technical-only";
  package_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [EgPerson, ...EgPerson[]];
  channel: "internal";
  external_delivery: false;
}
export interface EgListResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: EgGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
export interface EgPeopleResponse {
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
