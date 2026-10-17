/* Generated from cipher_aec/field/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 23506187c3802fdec51803723572c3ba883c2ceaa484976bda300cf73e097db6
 * Regenerate: npm run generate:api
 */

export type UrnCipherFieldApiV1 =
  | FdCreateRecordRequest
  | FdReviseRecordRequest
  | FdTransitionRequest
  | FdGetRecordRequest
  | FdListRecordsRequest
  | FdCreateRecordResponse
  | FdReviseRecordResponse
  | FdTransitionResponse
  | FdGetResponse
  | FdListResponse;
export type FdCreateRecordRequest =
  | {
      company: string;
      project: string;
      operation_id: FdUuid;
      family: "daily";
      definition: FdDailyDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FdPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FdQuantityDefinitionInput[];
    }
  | {
      company: string;
      project: string;
      operation_id: FdUuid;
      family: "ticket";
      definition: FdTicketDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FdPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FdQuantityDefinitionInput[];
    };
export type FdUuid = string;
export type FdDate = string;
export type FdDigest = string;
export type FdTimestamp = string;
export type FdQuantityValue = string;
export type FdReviseRecordRequest =
  | {
      company: string;
      project: string;
      operation_id: FdUuid;
      family: "daily";
      definition: FdDailyDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FdPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FdQuantityDefinitionInput[];
      record_id: FdUuid;
      expected_version: FdDigest;
      amendment_reason?: string;
    }
  | {
      company: string;
      project: string;
      operation_id: FdUuid;
      family: "ticket";
      definition: FdTicketDefinitionInput;
      /**
       * @minItems 0
       * @maxItems 12
       */
      photos: FdPhotoInput[];
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FdQuantityDefinitionInput[];
      record_id: FdUuid;
      expected_version: FdDigest;
      amendment_reason?: string;
    };
export type FdTransitionRequest =
  | {
      company: string;
      project: string;
      operation_id: FdUuid;
      family: "daily";
      record_id: FdUuid;
      expected_version: FdDigest;
      action: "submit" | "review" | "return" | "accept";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: FdSourceInput[];
      acknowledged_by?: string;
    }
  | {
      company: string;
      project: string;
      operation_id: FdUuid;
      family: "ticket";
      record_id: FdUuid;
      expected_version: FdDigest;
      action: "submit" | "review" | "return" | "accept" | "acknowledge";
      comment: string;
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: FdSourceInput[];
      acknowledged_by?: string;
    };
export type FdKind = "daily" | "daily_revision" | "quantity" | "ticket" | "ticket_revision" | "decision";
export type FdCreateRecordResponse =
  | {
      family: "daily";
      header: FdDailyHeader & {
        status?: "draft";
        last_decision?: null;
        [k: string]: unknown;
      };
      revision: FdDailyRevision;
      history_id: string;
      operation: FdOperation;
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FdQuantity[];
    }
  | {
      family: "ticket";
      header: FdTicketHeader & {
        status?: "draft";
        last_decision?: null;
        [k: string]: unknown;
      };
      revision: FdTicketRevision;
      history_id: string;
      operation: FdOperation;
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FdQuantity[];
    };
export type FdReviseRecordResponse =
  | {
      family: "daily";
      header: FdDailyHeader & {
        status?: "draft";
        last_decision?: null;
        [k: string]: unknown;
      };
      revision: FdDailyRevision;
      history_id: string;
      operation: FdOperation;
      /**
       * @minItems 0
       * @maxItems 40
       */
      quantities: FdQuantity[];
    }
  | {
      family: "ticket";
      header: FdTicketHeader & {
        status?: "draft";
        last_decision?: null;
        [k: string]: unknown;
      };
      revision: FdTicketRevision;
      history_id: string;
      operation: FdOperation;
      /**
       * @minItems 0
       * @maxItems 0
       */
      quantities: FdQuantity[];
    };
export type FdTransitionResponse =
  | {
      family: "daily";
      header: FdDailyHeader;
      revision: FdDailyRevision;
      history_id: string;
      operation: FdOperation;
      decision: FdDecision;
    }
  | {
      family: "ticket";
      header: FdTicketHeader;
      revision: FdTicketRevision;
      history_id: string;
      operation: FdOperation;
      decision: FdDecision;
    };
export type FdDecision =
  | {
      id: FdUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: FdTimestamp;
      status: "recorded";
      parent_id: FdUuid;
      source_revision: FdUuid;
      source_digest: FdDigest;
      predecessor: FdUuid | null;
      action: "submit";
      from_status: "draft";
      to_status: "submitted";
      comment: string;
      acknowledged_by: "";
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: FdCapturedSource[];
      no_effects: FdNoEffects;
    }
  | {
      id: FdUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: FdTimestamp;
      status: "recorded";
      parent_id: FdUuid;
      source_revision: FdUuid;
      source_digest: FdDigest;
      predecessor: FdUuid | null;
      action: "review";
      from_status: "submitted";
      to_status: "reviewed";
      comment: string;
      acknowledged_by: "";
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: FdCapturedSource[];
      no_effects: FdNoEffects;
    }
  | {
      id: FdUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: FdTimestamp;
      status: "recorded";
      parent_id: FdUuid;
      source_revision: FdUuid;
      source_digest: FdDigest;
      predecessor: FdUuid | null;
      action: "return";
      from_status: "submitted" | "reviewed";
      to_status: "returned";
      comment: string;
      acknowledged_by: "";
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: FdCapturedSource[];
      no_effects: FdNoEffects;
    }
  | {
      id: FdUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: FdTimestamp;
      status: "recorded";
      parent_id: FdUuid;
      source_revision: FdUuid;
      source_digest: FdDigest;
      predecessor: FdUuid | null;
      action: "accept";
      from_status: "reviewed";
      to_status: "accepted";
      comment: string;
      acknowledged_by: "";
      /**
       * @minItems 0
       * @maxItems 8
       */
      evidence: FdCapturedSource[];
      no_effects: FdNoEffects;
    }
  | {
      id: FdUuid;
      company: string;
      project: string;
      scope_type: "Project";
      author_person: string;
      author_user: string;
      created_at: FdTimestamp;
      status: "recorded";
      parent_id: FdUuid;
      source_revision: FdUuid;
      source_digest: FdDigest;
      predecessor: FdUuid | null;
      action: "acknowledge";
      from_status: "accepted";
      to_status: "acknowledged";
      comment: string;
      acknowledged_by: string;
      /**
       * @minItems 1
       * @maxItems 8
       */
      evidence: FdCapturedSource[];
      no_effects: FdNoEffects;
    };
export type FdRecord = FdHeader | FdDailyRevision | FdTicketRevision | FdQuantity | FdDecision;

export interface FdDailyDefinitionInput {
  local_date: FdDate;
  superintendent_user: string;
  weather: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  weather_sources: FdSourceInput[];
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
export interface FdSourceInput {
  revision_id: string;
  source_sha256: FdDigest;
  page: number;
  locator: string;
}
export interface FdPhotoInput {
  source: FdSourceInput;
  caption: string;
  captured_at: FdTimestamp;
  representation: "source_image" | "photo_on_pdf_page";
}
export interface FdQuantityDefinitionInput {
  original_event_id: FdUuid;
  supersedes_event_id: FdUuid | null;
  kind: "installed" | "delivered";
  description: string;
  wbs_code: string;
  cost_code: string;
  quantity: FdQuantityValue;
  unit: string;
  location: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FdSourceInput[];
}
export interface FdTicketDefinitionInput {
  local_date: FdDate;
  title: string;
  customer_name: string;
  location: string;
  work_description: string;
  potential_change_reference: string;
  /**
   * @minItems 1
   * @maxItems 40
   */
  lines: FdTicketLineInput[];
}
export interface FdTicketLineInput {
  kind: "labor" | "equipment" | "material";
  description: string;
  quantity: FdQuantityValue;
  unit: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FdSourceInput[];
}
export interface FdGetRecordRequest {
  company: string;
  project: string;
  kind: FdKind;
  record_id: FdUuid;
}
export interface FdListRecordsRequest {
  company: string;
  project: string;
  kind: FdKind;
  parent_id?: FdUuid | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none";
}
export interface FdDailyHeader {
  id: FdUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FdTimestamp;
  status: "draft" | "submitted" | "reviewed" | "returned" | "accepted";
  number: string;
  revision_number: number;
  current_revision: FdUuid;
  last_decision: FdUuid | null;
  accepted_revision: FdUuid | null;
}
export interface FdDailyRevision {
  id: FdUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FdTimestamp;
  status: "recorded";
  parent_id: FdUuid;
  revision_number: number;
  predecessor: FdUuid | null;
  prior_decision: FdUuid | null;
  amendment_of: FdUuid | null;
  amendment_reason: string;
  /**
   * @minItems 0
   * @maxItems 12
   */
  photos: FdPhoto[];
  no_effects: FdNoEffects;
  definition: FdDailyDefinition;
  superintendent: FdPerson;
  /**
   * @minItems 0
   * @maxItems 40
   */
  quantity_ids: FdUuid[];
}
export interface FdPhoto {
  source: FdCapturedSource;
  caption: string;
  captured_at: FdTimestamp;
  representation: "source_image" | "photo_on_pdf_page";
}
export interface FdCapturedSource {
  revision_id: string;
  source_sha256: FdDigest;
  page: number;
  locator: string;
  document_id: string;
  revision_number: number;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
export interface FdNoEffects {
  contract_change: false;
  budget_change: false;
  procurement_change: false;
  invoice_change: false;
  financial_posting: false;
  payroll_release: false;
  quality_certification: false;
  external_transmission: false;
}
export interface FdDailyDefinition {
  local_date: FdDate;
  superintendent_user: string;
  weather: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  weather_sources: FdCapturedSource[];
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
export interface FdPerson {
  user: string;
  person: string;
}
export interface FdOperation {
  id: FdUuid;
  status: "succeeded";
  replayed: boolean;
}
export interface FdQuantity {
  id: FdUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FdTimestamp;
  status: "recorded";
  parent_id: FdUuid;
  source_revision: FdUuid;
  revision_number: number;
  original_event_id: FdUuid;
  supersedes_event_id: FdUuid | null;
  definition: FdQuantityDefinition;
  no_effects: FdNoEffects;
}
export interface FdQuantityDefinition {
  original_event_id: FdUuid;
  supersedes_event_id: FdUuid | null;
  kind: "installed" | "delivered";
  description: string;
  wbs_code: string;
  cost_code: string;
  quantity: FdQuantityValue;
  unit: string;
  location: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FdCapturedSource[];
}
export interface FdTicketHeader {
  id: FdUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FdTimestamp;
  status: "draft" | "submitted" | "reviewed" | "returned" | "accepted" | "acknowledged";
  number: string;
  revision_number: number;
  current_revision: FdUuid;
  last_decision: FdUuid | null;
  accepted_revision: FdUuid | null;
}
export interface FdTicketRevision {
  id: FdUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FdTimestamp;
  status: "recorded";
  parent_id: FdUuid;
  revision_number: number;
  predecessor: FdUuid | null;
  prior_decision: FdUuid | null;
  amendment_of: FdUuid | null;
  amendment_reason: string;
  /**
   * @minItems 0
   * @maxItems 12
   */
  photos: FdPhoto[];
  no_effects: FdNoEffects;
  definition: FdTicketDefinition;
}
export interface FdTicketDefinition {
  local_date: FdDate;
  title: string;
  customer_name: string;
  location: string;
  work_description: string;
  potential_change_reference: string;
  /**
   * @minItems 1
   * @maxItems 40
   */
  lines: FdTicketLine[];
}
export interface FdTicketLine {
  kind: "labor" | "equipment" | "material";
  description: string;
  quantity: FdQuantityValue;
  unit: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sources: FdCapturedSource[];
}
export interface FdGetResponse {
  record: FdRecord;
  record_digest: FdDigest;
}
export interface FdHeader {
  id: FdUuid;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: FdTimestamp;
  status: "draft" | "submitted" | "reviewed" | "returned" | "accepted" | "acknowledged";
  number: string;
  revision_number: number;
  current_revision: FdUuid;
  last_decision: FdUuid | null;
  accepted_revision: FdUuid | null;
}
export interface FdListResponse {
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: FdGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none";
  total: null;
}
