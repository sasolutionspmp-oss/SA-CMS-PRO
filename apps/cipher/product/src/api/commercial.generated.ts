/* Generated from cipher_aec/commercial/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 789422807b503709968618e1675a1c404473c49187862e7e228093799ea67fa8
 * Regenerate: npm run generate:api
 */

export interface CipherCOM01CompanyScopedAuthoredDraftContracts {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPursuitFields".
 */
export interface ComPursuitFields {
  title: string;
  sector?: string;
  delivery_method?: string;
  geography?: string;
  bid_due_at?: string;
  bid_timezone?: string;
  procurement_reference?: string;
  probability_basis?: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComSection".
 */
export interface ComSection {
  id: string;
  kind: "scope" | "assumption" | "exclusion" | "schedule" | "other";
  title: string;
  text: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPriceLine".
 */
export interface ComPriceLine {
  id: string;
  description: string;
  quantity: string;
  unit_id: string;
  unit_revision: number;
  rate: string;
  item_code?: string | null;
  alternate_group?: string | null;
  selected: boolean;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPricedLine".
 */
export interface ComPricedLine {
  id: string;
  description: string;
  quantity: string;
  unit_id: string;
  unit_revision: number;
  rate: string;
  item_code: string | null;
  alternate_group: string | null;
  selected: boolean;
  amount: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComComposition".
 */
export interface ComComposition {
  currency: string;
  valid_till: string;
  terms: string;
  /**
   * @maxItems 80
   */
  sections: ComSection[];
  /**
   * @minItems 1
   * @maxItems 150
   */
  price_lines: [ComPriceLine, ...ComPriceLine[]];
  /**
   * @maxItems 30
   */
  source_references?: ComSourceReference[];
  estimate_revision?: null;
  price_list: string;
  estimate_reference?: ComEstimateReference | null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComSourceReference".
 */
export interface ComSourceReference {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256: string;
  purpose: string;
  permission_basis: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComEstimateReference".
 */
export interface ComEstimateReference {
  acceptance_id: string;
  acceptance_digest: string;
  revision_id: string;
  revision_digest: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPursuit".
 */
export interface ComPursuit {
  id: string;
  company: string;
  author_person: string;
  revision_number: number;
  opportunity: string;
  native_version: string;
  party_type: "Customer" | "Lead";
  party_id: string;
  title: string;
  fields: ComPursuitFields;
  stage: "identified";
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComProposal".
 */
export interface ComProposal {
  id: string;
  company: string;
  author_person: string;
  revision_number: number;
  pursuit: string;
  quotation: string;
  party_type: "Customer" | "Lead";
  party_id: string;
  title: string;
  current_revision: string;
  native_fingerprint: string;
  native_version: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPricing".
 */
export interface ComPricing {
  policy: "native-no-tax-no-discount-half-up-v1";
  currency_exponent: number;
  lines: ComPricedLine[];
  total: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComNativeSnapshot".
 */
export interface ComNativeSnapshot {
  id: string;
  version: string;
  company: string;
  quotation_to: string;
  party_name: string;
  opportunity: string;
  currency: string;
  valid_till: string;
  terms: string;
  docstatus: 0;
  totals: {
    [k: string]: string;
  };
  items: {
    [k: string]: unknown;
  }[];
  /**
   * @maxItems 0
   */
  taxes: [];
  selling_price_list: string;
  price_list_currency: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComRevision".
 */
export interface ComRevision {
  id: string;
  company: string;
  author_person: string;
  revision_number: number;
  proposal: string;
  predecessor: string | null;
  status: "draft";
  composition: ComComposition;
  pricing: ComPricing;
  currency_policy: {
    currency: string;
    currency_exponent: number;
    fraction_units: number;
    native_currency_version: string;
    price_list: {
      name: string;
      version: string;
      currency: string;
    };
  };
  units: {
    [k: string]: {
      [k: string]: unknown;
    };
  };
  native: ComNativeSnapshot;
  native_fingerprint: string;
  company_policy: {
    base_currency: string;
    native_company_version: string;
  };
  /**
   * @maxItems 30
   */
  source_citations?: ComSourceCitation[];
  accepted_estimate?: ComAcceptedEstimate | null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComSourceCitation".
 */
export interface ComSourceCitation {
  citation: ComCompanyCitation;
  purpose: string;
  permission_basis: string;
  policy: "pinned-revision-page-v1";
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComCompanyCitation".
 */
export interface ComCompanyCitation {
  id: string;
  document_id: string;
  revision_id: string;
  document_title: string;
  page_label: string;
  excerpt: string;
  excerpt_sha256: string;
  source_sha256: string;
  company: string;
  revision_number: number;
  page: number;
  scope_type: "Company";
  project: null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComAcceptedEstimate".
 */
export interface ComAcceptedEstimate {
  acceptance_id: string;
  acceptance_digest: string;
  estimate_id: string;
  revision_id: string;
  revision_digest: string;
  snapshot_id: string;
  snapshot_digest: string;
  manifest_digest: string;
  pursuit_id: string;
  currency: string;
  total: {
    amount: string;
    currency: string;
  };
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComProposalDetail".
 */
export interface ComProposalDetail {
  id: string;
  company: string;
  author_person: string;
  revision_number: number;
  pursuit: string;
  quotation: string;
  party_type: "Customer" | "Lead";
  party_id: string;
  title: string;
  current_revision: string;
  native_fingerprint: string;
  native_version: string;
  revision: ComRevision;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPursuitList".
 */
export interface ComPursuitList {
  items: ComPursuit[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComProposalList".
 */
export interface ComProposalList {
  items: ComProposal[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComOperation".
 */
export interface ComOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPursuitCommand".
 */
export interface ComPursuitCommand {
  pursuit: ComPursuit;
  operation: ComOperation;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComProposalCommand".
 */
export interface ComProposalCommand {
  proposal: ComProposal;
  revision: ComRevision;
  operation: ComOperation;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComComparison".
 */
export interface ComComparison {
  proposal_id: string;
  left_revision: string;
  right_revision: string;
  changes: {
    sections: {
      added: ComSection[];
      removed: ComSection[];
      changed: {
        id: string;
        before: ComSection;
        after: ComSection;
      }[];
      order_changed: boolean;
    };
    price_lines: {
      added: ComPriceLine[];
      removed: ComPriceLine[];
      changed: {
        id: string;
        before: ComPriceLine;
        after: ComPriceLine;
      }[];
      order_changed: boolean;
    };
    terms: {
      before: string;
      after: string;
      changed: boolean;
    };
    validity: {
      before: string;
      after: string;
      changed: boolean;
    };
    basis: {
      before: {
        currency: string;
        price_list: string;
        /**
         * @maxItems 30
         */
        source_references: ComSourceReference[];
        estimate_reference: ComEstimateReference | null;
      };
      after: {
        currency: string;
        price_list: string;
        /**
         * @maxItems 30
         */
        source_references: ComSourceReference[];
        estimate_reference: ComEstimateReference | null;
      };
      changed: boolean;
    };
  };
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPursuitsRequest".
 */
export interface ComPursuitsRequest {
  company: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComProposalsRequest".
 */
export interface ComProposalsRequest {
  company: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPursuitRequest".
 */
export interface ComPursuitRequest {
  company: string;
  pursuit_id: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComProposalRequest".
 */
export interface ComProposalRequest {
  company: string;
  proposal_id: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComRevisionRequest".
 */
export interface ComRevisionRequest {
  company: string;
  revision_id: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComCompareRequest".
 */
export interface ComCompareRequest {
  company: string;
  proposal_id: string;
  left_revision: string;
  right_revision: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComCreatePursuitRequest".
 */
export interface ComCreatePursuitRequest {
  company: string;
  party_type: "Customer" | "Lead";
  party_id: string;
  fields: ComPursuitFields;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComUpdatePursuitRequest".
 */
export interface ComUpdatePursuitRequest {
  company: string;
  pursuit_id: string;
  expected_revision: number;
  fields: ComPursuitFields;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComCreateProposalRequest".
 */
export interface ComCreateProposalRequest {
  company: string;
  pursuit_id: string;
  composition: ComComposition;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComSaveRevisionRequest".
 */
export interface ComSaveRevisionRequest {
  company: string;
  proposal_id: string;
  expected_revision: number;
  expected_native_fingerprint: string;
  composition: ComComposition;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComRecipient".
 */
export interface ComRecipient {
  name: string;
  email: string;
  organization: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComRendererPolicy".
 */
export interface ComRendererPolicy {
  renderer: "weasyprint";
  versions: {
    weasyprint: "68.0";
    pydyf: "0.12.1";
    fonttools: "4.67.0";
  };
  fonts: {
    [k: string]: {
      path: string;
      sha256: string;
    };
  };
  parameters: {
    [k: string]: unknown;
  };
  fingerprint: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComOutputBinding".
 */
export interface ComOutputBinding {
  schema: "cipher.proposal.output.input.v1";
  company: string;
  proposal_id: string;
  proposal_revision_id: string;
  proposal_revision_digest: string;
  native_fingerprint: string;
  accepted_estimate: ComAcceptedEstimate;
  source_citations: ComSourceCitation[];
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [ComRecipient, ...ComRecipient[]];
  cover: string;
  renderer: ComRendererPolicy;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComRenderingProvenance".
 */
export interface ComRenderingProvenance {
  renderer: "weasyprint";
  versions: {
    weasyprint: "68.0";
    pydyf: "0.12.1";
    fonttools: "4.67.0";
  };
  fonts: {
    [k: string]: {
      path: string;
      sha256: string;
    };
  };
  parameters: {
    [k: string]: unknown;
  };
  fingerprint: string;
  proposal_revision_digest: string;
  baseline: ComAcceptedEstimate;
  cover_digest: string;
  recipients_digest: string;
  output_sha256: string;
  output_byte_length: number;
  input_digest: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPreparedOutput".
 */
export interface ComPreparedOutput {
  company: string;
  proposal_id: string;
  proposal_revision_id: string;
  proposal_revision_digest: string;
  document_id: string;
  revision_id: string;
  source_sha256: string;
  byte_length: number;
  page_count: number;
  input_digest: string;
  binding: ComOutputBinding;
  rendering: ComRenderingProvenance;
  review_version: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPreparedOutputCommand".
 */
export interface ComPreparedOutputCommand {
  prepared_output: ComPreparedOutput;
  operation: ComOperation;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComIssue".
 */
export interface ComIssue {
  id: string;
  company: string;
  author_person: string;
  proposal: string;
  proposal_revision: string;
  proposal_revision_digest: string;
  revision_number: number;
  predecessor: string | null;
  packet_id: string;
  decision_id: string;
  approved_by_person: string;
  output_revision: string;
  prepared_output: ComPreparedOutput;
  accepted_estimate: ComAcceptedEstimate;
  /**
   * @minItems 1
   */
  selected_lines: [
    {
      line: ComPricedLine;
      unit: {
        [k: string]: unknown;
      };
      native_item: {
        [k: string]: unknown;
      };
    },
    ...{
      line: ComPricedLine;
      unit: {
        [k: string]: unknown;
      };
      native_item: {
        [k: string]: unknown;
      };
    }[]
  ];
  composition: ComComposition;
  pricing: ComPricing;
  units: {
    [k: string]: {
      [k: string]: unknown;
    };
  };
  native_snapshot: ComNativeSnapshot;
  native_fingerprint: string;
  native_lifecycle: "draft-snapshot";
  status: "issued";
  distribution: "not-sent";
  manifest: {
    [k: string]: unknown;
  };
  manifest_digest: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComIssueList".
 */
export interface ComIssueList {
  items: ComIssue[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPrepareOutputRequest".
 */
export interface ComPrepareOutputRequest {
  company: string;
  proposal_id: string;
  revision_id: string;
  expected_revision_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [ComRecipient, ...ComRecipient[]];
  cover: string;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComPreparedOutputRequest".
 */
export interface ComPreparedOutputRequest {
  company: string;
  revision_id: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComIssueRequest".
 */
export interface ComIssueRequest {
  company: string;
  issue_id: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComIssuesRequest".
 */
export interface ComIssuesRequest {
  company: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
  proposal_id: string;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComOutputSubject".
 */
export interface ComOutputSubject {
  company: string;
  proposal_id: string;
  revision_id: string;
  revision_digest: string;
  native_fingerprint: string;
  is_current: true;
  prepared_output: ComPreparedOutput | null;
}
/**
 * This interface was referenced by `CipherCOM01CompanyScopedAuthoredDraftContracts`'s JSON-Schema
 * via the `definition` "ComOutputSubjectRequest".
 */
export interface ComOutputSubjectRequest {
  company: string;
  proposal_id: string;
}
