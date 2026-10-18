/* Generated from cipher_aec/field_offline/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 711de866e0800becb68fe5726189b3ffd013cda3351849b707930cd4a5594a45
 * Regenerate: npm run generate:api
 */

/**
 * Input validation grants no device registration, current canonical Person authority, source rights, base revision standing, review, acceptance, financial effect or native qualification. Cross-field equality and replay lineage remain server checks.
 */
export type FLD02BoundedOfflineDocumentaryCaptureTransport =
  | FoApplyCaptureRequest
  | FoApplyCaptureResponse
  | FoCaptureMutationResponse
  | FoDeviceMutationResponse
  | FoDiscardCaptureRequest
  | FoGetCaptureRequest
  | FoGetCaptureResponse
  | FoInspectCaptureRequest
  | FoInspectCaptureResponse
  | FoRegisterDeviceRequest
  | FoResolveCaptureRequest
  | FoRevokeDeviceRequest
  | FoStageCaptureRequest;
export type FoCaptureUuid = string;
export type FoDigest = string;
export type FoCreateRecordResponse =
  | {
      family: "daily";
      header: FoDailyHeader & {
        status?: "draft";
        last_decision?: null;
        [k: string]: unknown;
      };
      revision: FoDailyRevision;
      history_id: string;
      operation: FoOperation;
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FoQuantity[];
    }
  | {
      family: "ticket";
      header: FoTicketHeader & {
        status?: "draft";
        last_decision?: null;
        [k: string]: unknown;
      };
      revision: FoTicketRevision;
      history_id: string;
      operation: FoOperation;
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FoQuantity[];
    };
export type FoUuid = string;
export type FoTimestamp = string;
export type FoDate = string;
export type FoQuantityValue = string;
export type FoCommand = FoCreateCommand | FoReviseCommand;
export type FoCreateCommand =
  | {
      action: "create";
      family: "daily";
      definition: FoDailyDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FoPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FoQuantityDefinitionInput[];
    }
  | {
      action: "create";
      family: "ticket";
      definition: FoTicketDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FoPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FoQuantityDefinitionInput[];
    };
export type FoReviseCommand =
  | {
      action: "revise";
      family: "daily";
      definition: FoDailyDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FoPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FoQuantityDefinitionInput[];
      record_id: FoUuid;
      expected_version: FoDigest;
      base_revision_id: FoUuid;
      base_revision_digest: FoDigest;
      amendment_reason: string;
    }
  | {
      action: "revise";
      family: "ticket";
      definition: FoTicketDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FoPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FoQuantityDefinitionInput[];
      record_id: FoUuid;
      expected_version: FoDigest;
      base_revision_id: FoUuid;
      base_revision_digest: FoDigest;
      amendment_reason: string;
    };

export interface FoApplyCaptureRequest {
  company: string;
  project: string;
  operation_id: FoCaptureUuid;
  capture_id: FoCaptureUuid;
  expected_version: FoDigest;
}
export interface FoApplyCaptureResponse {
  capture: FoCaptureSummary;
  capture_version: FoDigest;
  original_receipt: FoCreateRecordResponse;
  replayed: boolean;
}
export interface FoCaptureSummary {
  capture_id: FoCaptureUuid;
  device_id: FoCaptureUuid;
  company: string;
  project: string;
  actor_person: string;
  actor_user: string;
  envelope_digest: FoDigest;
  status: "staged" | "committed" | "discarded" | "superseded";
  payload_retained: boolean;
  replaces_capture_id: FoCaptureUuid | null;
  replacement_capture_id: FoCaptureUuid | null;
}
export interface FoDailyHeader {
  id: FoUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FoTimestamp;
  status: "draft" | "submitted" | "reviewed" | "returned" | "accepted";
  number: string;
  revision_number: number;
  current_revision: FoUuid;
  last_decision: FoUuid | null;
  accepted_revision: FoUuid | null;
}
export interface FoDailyRevision {
  id: FoUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FoTimestamp;
  status: "recorded";
  parent_id: FoUuid;
  revision_number: number;
  predecessor: FoUuid | null;
  prior_decision: FoUuid | null;
  amendment_of: FoUuid | null;
  amendment_reason: string;
  /**
   * @minItems 0
   * @maxItems 12
   */
  photos: FoPhoto[];
  no_effects: FoNoEffects;
  definition: FoDailyDefinition;
  superintendent: FoPerson;
  /**
   * @minItems 0
   * @maxItems 40
   */
  quantity_ids: FoUuid[];
}
export interface FoPhoto {
  source: FoCapturedSource;
  caption: string;
  captured_at: FoTimestamp;
  representation: "source_image" | "photo_on_pdf_page";
}
export interface FoCapturedSource {
  revision_id: string;
  source_sha256: FoDigest;
  page: number;
  locator: string;
  document_id: string;
  revision_number: number;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
export interface FoNoEffects {
  contract_change: false;
  budget_change: false;
  procurement_change: false;
  invoice_change: false;
  financial_posting: false;
  payroll_release: false;
  quality_certification: false;
  external_transmission: false;
}
export interface FoDailyDefinition {
  local_date: FoDate;
  superintendent_user: string;
  weather: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  weather_sources: FoCapturedSource[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  crews: string[];
  /**
   * @minItems 1
   * @maxItems 20
   */
  activities: string[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  delays: string[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  visitors: string[];
}
export interface FoPerson {
  user: string;
  person: string;
}
export interface FoOperation {
  id: FoUuid;
  status: "succeeded";
  replayed: boolean;
}
export interface FoQuantity {
  id: FoUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FoTimestamp;
  status: "recorded";
  parent_id: FoUuid;
  source_revision: FoUuid;
  revision_number: number;
  original_event_id: FoUuid;
  supersedes_event_id: FoUuid | null;
  definition: FoQuantityDefinition;
  no_effects: FoNoEffects;
}
export interface FoQuantityDefinition {
  original_event_id: FoUuid;
  supersedes_event_id: FoUuid | null;
  kind: "installed" | "delivered";
  description: string;
  wbs_code: string;
  cost_code: string;
  quantity: FoQuantityValue;
  unit: string;
  location: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FoCapturedSource[];
}
export interface FoTicketHeader {
  id: FoUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FoTimestamp;
  status: "draft" | "submitted" | "reviewed" | "returned" | "accepted" | "acknowledged";
  number: string;
  revision_number: number;
  current_revision: FoUuid;
  last_decision: FoUuid | null;
  accepted_revision: FoUuid | null;
}
export interface FoTicketRevision {
  id: FoUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FoTimestamp;
  status: "recorded";
  parent_id: FoUuid;
  revision_number: number;
  predecessor: FoUuid | null;
  prior_decision: FoUuid | null;
  amendment_of: FoUuid | null;
  amendment_reason: string;
  /**
   * @minItems 0
   * @maxItems 12
   */
  photos: FoPhoto[];
  no_effects: FoNoEffects;
  definition: FoTicketDefinition;
}
export interface FoTicketDefinition {
  local_date: FoDate;
  title: string;
  customer_name: string;
  location: string;
  work_description: string;
  potential_change_reference: string;
  /**
   * @minItems 1
   * @maxItems 40
   */
  lines: FoTicketLine[];
}
export interface FoTicketLine {
  kind: "labor" | "equipment" | "material";
  description: string;
  quantity: FoQuantityValue;
  unit: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FoCapturedSource[];
}
export interface FoCaptureMutationResponse {
  capture: FoCaptureSummary;
  capture_version: FoDigest;
  operation: FoSyncOperation;
}
export interface FoSyncOperation {
  id: FoCaptureUuid;
  status: "succeeded";
  replayed: boolean;
}
export interface FoDeviceMutationResponse {
  device: FoDeviceSummary;
  device_version: FoDigest;
  operation: FoSyncOperation;
}
export interface FoDeviceSummary {
  device_id: FoCaptureUuid;
  company: string;
  project: string;
  owner_person: string;
  registered_user: string;
  status: "active" | "revoked";
  label: string;
}
export interface FoDiscardCaptureRequest {
  company: string;
  project: string;
  operation_id: FoCaptureUuid;
  capture_id: FoCaptureUuid;
  expected_version: FoDigest;
  reason: string;
}
export interface FoGetCaptureRequest {
  company: string;
  project: string;
  capture_id: FoCaptureUuid;
}
export interface FoGetCaptureResponse {
  capture: FoCaptureSummary;
  capture_version: FoDigest;
  envelope: FoEnvelope | null;
  original_receipt: FoCreateRecordResponse | null;
}
/**
 * Immutable Project capture attribution; device ownership/current authority and exact source/base revision facts are verified by the server. Canonical UTF-8 JSON is limited to 256 KiB by the service.
 */
export interface FoEnvelope {
  schema: "cipher.field.offline.v1";
  device_id: FoCaptureUuid;
  capture_id: FoCaptureUuid;
  company: string;
  project: string;
  actor_person: string;
  actor_user: string;
  captured_at: FoTimestamp;
  command: FoCommand;
}
export interface FoDailyDefinitionInput {
  local_date: FoDate;
  superintendent_user: string;
  weather: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  weather_sources: FoSourceInput[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  crews: string[];
  /**
   * @minItems 1
   * @maxItems 20
   */
  activities: string[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  delays: string[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  visitors: string[];
}
export interface FoSourceInput {
  revision_id: string;
  source_sha256: FoDigest;
  page: number;
  locator: string;
}
export interface FoPhotoInput {
  source: FoSourceInput;
  caption: string;
  captured_at: FoTimestamp;
  representation: "source_image" | "photo_on_pdf_page";
}
export interface FoQuantityDefinitionInput {
  original_event_id: FoUuid;
  supersedes_event_id: FoUuid | null;
  kind: "installed" | "delivered";
  description: string;
  wbs_code: string;
  cost_code: string;
  quantity: FoQuantityValue;
  unit: string;
  location: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FoSourceInput[];
}
export interface FoTicketDefinitionInput {
  local_date: FoDate;
  title: string;
  customer_name: string;
  location: string;
  work_description: string;
  potential_change_reference: string;
  /**
   * @minItems 1
   * @maxItems 40
   */
  lines: FoTicketLineInput[];
}
export interface FoTicketLineInput {
  kind: "labor" | "equipment" | "material";
  description: string;
  quantity: FoQuantityValue;
  unit: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FoSourceInput[];
}
export interface FoInspectCaptureRequest {
  company: string;
  project: string;
  capture_id: FoCaptureUuid;
}
export interface FoInspectCaptureResponse {
  capture: FoCaptureSummary;
  capture_version: FoDigest;
  disposition: "ready" | "conflict" | "committed" | "discarded" | "superseded";
  conflict: FoConflict | null;
  original_receipt: FoCreateRecordResponse | null;
}
export interface FoConflict {
  code: "base_changed" | "record_state_changed" | "source_changed";
  current_header_version: FoDigest | null;
  current_revision_id: FoUuid | null;
  current_revision_digest: FoDigest | null;
}
export interface FoRegisterDeviceRequest {
  company: string;
  project: string;
  operation_id: FoCaptureUuid;
  device_id: FoCaptureUuid;
  label: string;
}
export interface FoResolveCaptureRequest {
  company: string;
  project: string;
  operation_id: FoCaptureUuid;
  capture_id: FoCaptureUuid;
  expected_version: FoDigest;
  replacement_envelope: FoEnvelope;
  reason: string;
}
export interface FoRevokeDeviceRequest {
  company: string;
  project: string;
  operation_id: FoCaptureUuid;
  device_id: FoCaptureUuid;
  expected_version: FoDigest;
  reason: string;
}
export interface FoStageCaptureRequest {
  company: string;
  project: string;
  operation_id: FoCaptureUuid;
  envelope: FoEnvelope;
}
