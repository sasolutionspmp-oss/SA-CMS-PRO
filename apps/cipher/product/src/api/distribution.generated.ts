/* Generated from cipher_aec/integrations/schemas/distribution-v1.schema.json. Do not edit.
 * Source SHA-256: 694428d6af4a47b7f6cc07bd8dea1f1eba8d162117c54b9690e1dc805f1acc60
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistDeliveryResult".
 */
export type DistDeliveryResult =
  | {
      receipt: DistSinkReceipt;
      mode: "fixture";
    }
  | {
      attempt_not_after: string;
      mode: "fixture";
    };

export interface CipherDistributionContract {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistRecipient".
 */
export interface DistRecipient {
  id: string;
  name: string;
  email: string;
  organization: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistAttachment".
 */
export interface DistAttachment {
  revision_id: string;
  document_id: string;
  sha256: string;
  byte_length: number;
  media_type: "application/pdf";
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistProfile".
 */
export interface DistProfile {
  id: "local-fixture-v1";
  version: 1;
  mode: "fixture";
  enabled: boolean;
  max_recipients: 30;
  mandate_seconds: 86400;
  attempt_seconds: 30;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistMessage".
 */
export interface DistMessage {
  subject: string;
  body: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistInstruction".
 */
export interface DistInstruction {
  id: string;
  scope_type: "Company";
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  session_reference: string;
  created_at: string;
  valid_until: string;
  issue_id: string;
  issue_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [DistRecipient, ...DistRecipient[]];
  attachment: DistAttachment;
  cover_digest: string;
  message: DistMessage;
  message_digest: string;
  profile: DistProfile;
  mode: "fixture";
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistDispatch".
 */
export interface DistDispatch {
  id: string;
  scope_type: "Company";
  company: string;
  project: null;
  instruction_id: string;
  instruction_digest: string;
  issue_id: string;
  packet_id: string;
  decision_id: string;
  packet_manifest_hash: string;
  requester_person: string;
  requester_user: string;
  reviewer_person: string;
  reviewer_user: string;
  request_session_reference: string;
  execute_session_reference: string;
  review_session_reference: string;
  policy_revision: string;
  created_at: string;
  valid_until: string;
  profile: DistProfile;
  mode: "fixture";
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistCancellation".
 */
export interface DistCancellation {
  id: string;
  scope_type: "Company";
  company: string;
  project: null;
  dispatch_id: string;
  instruction_id: string;
  actor_person: string;
  reason: string;
  cancelled_at: string;
  in_flight_may_complete: true;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistSinkReceipt".
 */
export interface DistSinkReceipt {
  mode: "fixture";
  logical_key: string;
  payload_hash: string;
  attachment_sha256: string;
  byte_length: number;
  acknowledgment_id: string;
  accepted_at: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistRecipientDelivery".
 */
export interface DistRecipientDelivery {
  operation_id: string;
  recipient_id: string;
  state: "Queued" | "Claimed" | "Succeeded" | "Failed" | "Unknown" | "Cancelled";
  mode: "fixture";
  receipt: DistDeliveryResult | null;
  error_code: string | null;
  /**
   * Always present on current dispatch/recipient reads; optional only for byte-preserved historical embedded cancellation command receipts. Missing expected identity must remain unverified until current readback.
   */
  logical_key?: string;
  /**
   * Always present on current dispatch/recipient reads; optional only for byte-preserved historical embedded cancellation command receipts. Missing expected identity must remain unverified until current readback.
   */
  payload_hash?: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistDispatchDetail".
 */
export interface DistDispatchDetail {
  dispatch: DistDispatch;
  state: "Unknown" | "SucceededFixture" | "PartiallySucceeded" | "Cancelled" | "Failed" | "Queued";
  mode: "fixture";
  deliveries: DistRecipientDelivery[];
  cancellation: DistCancellation | null;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistOperation".
 */
export interface DistOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistInstructionResponse".
 */
export interface DistInstructionResponse {
  instruction: DistInstruction;
  version: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistCreateInstructionResponse".
 */
export interface DistCreateInstructionResponse {
  instruction: DistInstruction;
  version: string;
  operation: DistOperation;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistCancelResponse".
 */
export interface DistCancelResponse {
  cancellation: DistCancellation;
  dispatch: DistDispatchDetail;
  operation: DistOperation;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistDispatchList".
 */
export interface DistDispatchList {
  items: DistDispatch[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistProfiles".
 */
export interface DistProfiles {
  items: DistProfile[];
  live_transmission: false;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistCreateInstructionRequest".
 */
export interface DistCreateInstructionRequest {
  company: string;
  issue_id: string;
  recipient_ids: [string, ...string[]] | null;
  subject: string;
  body: string;
  profile_id: "local-fixture-v1";
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistGetInstructionRequest".
 */
export interface DistGetInstructionRequest {
  company: string;
  instruction_id: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistGetDispatchRequest".
 */
export interface DistGetDispatchRequest {
  company: string;
  dispatch_id: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistGetRecipientRequest".
 */
export interface DistGetRecipientRequest {
  company: string;
  dispatch_id: string;
  recipient_id: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistListDispatchesRequest".
 */
export interface DistListDispatchesRequest {
  company: string;
  issue_id: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistCancelRequest".
 */
export interface DistCancelRequest {
  company: string;
  dispatch_id: string;
  reason: string;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistProfilesRequest".
 */
export interface DistProfilesRequest {
  company: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistRecipientChoicesRequest".
 */
export interface DistRecipientChoicesRequest {
  company: string;
  issue_id: string;
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistRecipientChoices".
 */
export interface DistRecipientChoices {
  issue_id: string;
  issue_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [DistRecipient, ...DistRecipient[]];
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistListInstructionsRequest".
 */
export interface DistListInstructionsRequest {
  company: string;
  issue_id?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherDistributionContract`'s JSON-Schema
 * via the `definition` "DistInstructionList".
 */
export interface DistInstructionList {
  items: DistInstructionResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
