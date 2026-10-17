/* Generated from cipher_aec/awards/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: b8c01de5e57edcb5f6375ccf1e803a2c0bcb43e2e639d5d62e30ab142dd2120b
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcAllocationSource".
 */
export type PcAllocationSource =
  | {
      kind: "component";
      line_id: string;
      component_id: string;
    }
  | {
      kind: "adjustment";
      adjustment_id: string;
    };
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcDefinition".
 */
export type PcDefinition = PcCodeDefinition | PcTypeDefinition;

export interface CipherAwardContract {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "ComSourceCitation".
 */
export interface ComSourceCitation {
  citation: ComCompanyCitation;
  purpose: string;
  permission_basis: string;
  policy: "pinned-revision-page-v1";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "ComRecipient".
 */
export interface ComRecipient {
  name: string;
  email: string;
  organization: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "ComSection".
 */
export interface ComSection {
  id: string;
  kind: "scope" | "assumption" | "exclusion" | "schedule" | "other";
  title: string;
  text: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "ComEstimateReference".
 */
export interface ComEstimateReference {
  acceptance_id: string;
  acceptance_digest: string;
  revision_id: string;
  revision_digest: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "ComPricing".
 */
export interface ComPricing {
  policy: "native-no-tax-no-discount-half-up-v1";
  currency_exponent: number;
  lines: ComPricedLine[];
  total: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
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
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstAcceptanceRecord".
 */
export interface CompanyEstAcceptanceRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: "accepted";
  estimate: string;
  estimate_revision: string;
  calculation_snapshot: string;
  baseline_number: number;
  predecessor: string | null;
  packet_id: string;
  decision_id: string;
  accepted_by_person: string;
  manifest: CompanyEstAcceptanceManifest;
  manifest_digest: string;
  accepted_result: CompanyEstCalculationResult;
  currency: string;
  total: CompanyEstMoney;
  /**
   * @maxItems 64
   */
  source_citations: CompanyEstCitation[];
  scope_type: "Company";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstAcceptanceManifest".
 */
export interface CompanyEstAcceptanceManifest {
  subject: {
    doctype: "Cipher Estimate Revision";
    name: string;
    label: string;
  };
  /**
   * @maxItems 64
   */
  sources: CompanyEstCitation[];
  effect: {
    action: "estimate.accept.v1";
    revision_id: string;
    facts: CompanyEstAcceptanceFacts;
  };
  summary: {
    total: CompanyEstMoney;
    currency: string;
    rounding_policy: "cipher.estimate.line-half-up.v1";
    binding_count: number;
    independent_acceptance_required: true;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstCitation".
 */
export interface CompanyEstCitation {
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
  scope_type: "Company";
  company: string;
  project: null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstAcceptanceFacts".
 */
export interface CompanyEstAcceptanceFacts {
  policy: "cipher.estimate.acceptance-facts.v1";
  scope: CompanyEstAcceptanceScope;
  pricing_sources_policy: "pinned-revision-at-pricing-date";
  drawing_calibration_policy: "current-working-head-v1";
  estimate: {
    id: string;
    digest: string;
    current_revision: string;
  };
  revision: {
    id: string;
    digest: string;
  };
  snapshot: {
    id: string;
    digest: string;
    input_digest: string;
    output_digest: string;
  };
  rounding_policy: "cipher.estimate.line-half-up.v1";
  /**
   * @maxItems 700
   */
  pinned_records: CompanyEstPinnedRecord[];
  /**
   * @maxItems 200
   */
  qualified_units: CompanyEstUnitRecord[];
  currency_policy: {
    currency: string;
    currency_exponent: number;
    fraction_units: number;
    native_currency_version: string;
  };
  /**
   * @maxItems 700
   */
  native_references: CompanyEstNativeReference[];
  pursuit: CompanyEstPursuitPlan | null;
  /**
   * @maxItems 200
   */
  bindings: CompanyEstAcceptanceBinding[];
  /**
   * @minItems 1
   * @maxItems 128
   */
  generated_sources?: [CompanyEstGeneratedSourceNode, ...CompanyEstGeneratedSourceNode[]];
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstAcceptanceScope".
 */
export interface CompanyEstAcceptanceScope {
  company: string;
  project: null;
  scope_type: "Company";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstPinnedRecord".
 */
export interface CompanyEstPinnedRecord {
  kind: "rate" | "assembly" | "conversion";
  id: string;
  digest: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstUnitRecord".
 */
export interface CompanyEstUnitRecord {
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
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstNativeReference".
 */
export interface CompanyEstNativeReference {
  doctype: "Item" | "Supplier" | "Customer" | "Lead" | "Opportunity";
  name: string;
  version: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstPursuitPlan".
 */
export interface CompanyEstPursuitPlan {
  company: string;
  pursuit_id: string;
  record_digest: string;
  revision_number: number;
  party_type: "Customer" | "Lead";
  party_id: string;
  /**
   * @maxItems 3
   */
  native_refs:
    | []
    | [
        {
          doctype: "Customer" | "Lead" | "Opportunity";
          name: string;
        }
      ]
    | [
        {
          doctype: "Customer" | "Lead" | "Opportunity";
          name: string;
        },
        {
          doctype: "Customer" | "Lead" | "Opportunity";
          name: string;
        }
      ]
    | [
        {
          doctype: "Customer" | "Lead" | "Opportunity";
          name: string;
        },
        {
          doctype: "Customer" | "Lead" | "Opportunity";
          name: string;
        },
        {
          doctype: "Customer" | "Lead" | "Opportunity";
          name: string;
        }
      ];
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstAcceptanceBinding".
 */
export interface CompanyEstAcceptanceBinding {
  id: string;
  digest: string;
  measurement_id: string;
  measurement_digest: string;
  current_use: {
    eligible: true;
    /**
     * @maxItems 0
     */
    reasons: [];
    current_working_revision: string;
    head_policy: "current-working-revision-v1";
    original_record_preserved: true;
    verification: {
      id: string;
      verified_by_person: string;
    } | null;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstGeneratedSourceNode".
 */
export interface CompanyEstGeneratedSourceNode {
  document_id: string;
  revision_id: string;
  source_sha256: string;
  byte_length: number;
  page_count: number;
  input_digest: string;
  producer_kind: "commercial.proposal.output.v1";
  proposal_revision_id: string;
  proposal_revision_digest: string;
  native_fingerprint: string;
  accepted_baseline_id: string;
  accepted_baseline_digest: string;
  accepted_revision_digest: string;
  accepted_manifest_digest: string;
  citation_manifest_digest: string;
  renderer_fingerprint: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstMoney".
 */
export interface CompanyEstMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstCalculationResult".
 */
export interface CompanyEstCalculationResult {
  schema: "cipher.estimate.result.v1";
  policy: CompanyEstCalculationPolicy;
  /**
   * @maxItems 100
   */
  lines: CompanyEstCalculatedLine[];
  /**
   * @maxItems 30
   */
  adjustments: CompanyEstCalculatedAdjustment[];
  direct: CompanyEstMoney;
  indirect: CompanyEstMoney;
  contingency: CompanyEstMoney;
  total: CompanyEstMoney;
  /**
   * @maxItems 64
   */
  conversion_references: {
    id: string;
    revision: number;
    source: string;
    numerator: string;
    denominator: string;
  }[];
  input_digest: string;
  output_digest: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstCalculationPolicy".
 */
export interface CompanyEstCalculationPolicy {
  version: "cipher.estimate.line-half-up.v1";
  rounding_mode: "ROUND_HALF_UP";
  currency_exponent: number;
  intermediate: "exact-rational";
  line_rounding: "sum-exact-components-then-round";
  component_allocation: "nonnegative-largest-remainder-tie-by-stable-component-id";
  header_rounding: "sum-rounded-lines";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstCalculatedLine".
 */
export interface CompanyEstCalculatedLine {
  line_id: string;
  description: string;
  quantity: CompanyEstQuantity;
  quantity_method: "authored";
  included: boolean;
  alternate: string;
  cost_code: string;
  /**
   * @maxItems 50
   */
  components: CompanyEstPricedComponent[];
  unrounded_extension: CompanyEstRational;
  extension: CompanyEstMoney;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstQuantity".
 */
export interface CompanyEstQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstPricedComponent".
 */
export interface CompanyEstPricedComponent {
  component_id: string;
  rate_source_id: string;
  rate_revision: number;
  cost_type: "material" | "labor" | "equipment" | "subcontract" | "other";
  source_unit_id: string;
  resource_quantity_exact: CompanyEstRational;
  priced_quantity_exact: CompanyEstRational;
  material_factor: CompanyEstRational;
  waste_fraction: CompanyEstRational;
  unrounded_cost: CompanyEstRational;
  allocated_amount: CompanyEstMoney;
  rounding_increment: CompanyEstMoney;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstRational".
 */
export interface CompanyEstRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "CompanyEstCalculatedAdjustment".
 */
export interface CompanyEstCalculatedAdjustment {
  line_id: string;
  kind: "indirect" | "contingency";
  label: string;
  method: "fixed" | "fraction_of_direct";
  value: string;
  basis_description: string;
  unrounded_amount: CompanyEstRational;
  amount: CompanyEstMoney;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcInitialPlan".
 */
export interface PcInitialPlan {
  schema: "cipher.project-controls.initial-plan.v1";
  company: string;
  basis_date: string;
  acceptance: {
    id: string;
    digest: string;
    estimate_id: string;
    revision_id: string;
    snapshot_id: string;
    manifest_digest: string;
  };
  /**
   * @maxItems 500
   */
  wbs_nodes: PcWbsNode[];
  /**
   * @maxItems 5030
   */
  allocations: PcAllocation[];
  /**
   * @maxItems 500
   */
  resolved_codes: PcResolvedRevision[];
  /**
   * @maxItems 500
   */
  resolved_types: PcResolvedRevision[];
  /**
   * @maxItems 5030
   */
  budget_lines: PcBudgetLine[];
  /**
   * @maxItems 100
   */
  excluded_source_lines: {
    line_id: string;
    digest: string;
  }[];
  /**
   * @maxItems 500
   */
  source_units: PcQualifiedUnit[];
  currency: string;
  currency_exponent: number;
  totals: {
    direct: PcMoney;
    indirect: PcMoney;
    contingency: PcMoney;
    total: PcMoney;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcWbsNode".
 */
export interface PcWbsNode {
  id: string;
  code: string;
  parent_id: string | null;
  title: string;
  is_leaf: boolean;
  accountable_person: string | null;
  phase: string;
  active_from: string | null;
  active_until: string | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcAllocation".
 */
export interface PcAllocation {
  id: string;
  source: PcAllocationSource;
  wbs_id: string;
  code_revision_id: string;
  type_revision_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcResolvedRevision".
 */
export interface PcResolvedRevision {
  kind: "code" | "type";
  company: string;
  basis_date: string;
  purpose: "award.initial-budget.v1" | "cost.author.v1" | "historical_read";
  revision: PcRevision;
  revision_digest: string;
  native: PcNativeTarget;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcRevision".
 */
export interface PcRevision {
  schema: "cipher.cost-revision.v1";
  id: string;
  company: string;
  project: null;
  kind: "code" | "type";
  code: string;
  author_person: string;
  master_id: string;
  revision_number: number;
  predecessor: string | null;
  definition: PcDefinition;
  authored_native: PcNativeTarget;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcCodeDefinition".
 */
export interface PcCodeDefinition {
  title: string;
  effective_from: string;
  effective_until: string | null;
  enabled: boolean;
  native_target: {
    doctype: "Cost Center";
    name: string;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcTypeDefinition".
 */
export interface PcTypeDefinition {
  title: string;
  effective_from: string;
  effective_until: string | null;
  enabled: boolean;
  native_target: {
    doctype: "Account";
    name: string;
  };
  cost_category: ("material" | "labor" | "equipment" | "subcontract" | "other") | null;
  allocation_class: "component" | "indirect" | "contingency";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcNativeTarget".
 */
export interface PcNativeTarget {
  doctype: "Cost Center" | "Account";
  name: string;
  company: string;
  version: string;
  is_group: boolean;
  disabled: boolean;
  root_type: string | null;
  account_currency: string | null;
  currency_policy: null | {
    currency: string;
    currency_exponent: number;
    fraction_units: number;
    native_currency_version: string;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcBudgetLine".
 */
export interface PcBudgetLine {
  id: string;
  source: PcAllocationSource;
  wbs_id: string;
  code_revision_id: string;
  type_revision_id: string;
  amount: PcMoney;
  cost_category: ("material" | "labor" | "equipment" | "subcontract" | "other") | null;
  allocation_class: "component" | "indirect" | "contingency";
  source_quantity: {
    source_unit_id: string;
    resource_quantity_exact: PcRational;
    priced_quantity_exact: PcRational;
  } | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcMoney".
 */
export interface PcMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcRational".
 */
export interface PcRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "PcQualifiedUnit".
 */
export interface PcQualifiedUnit {
  id: string;
  kind: "uom";
  revision: number;
  fields: {
    symbol: string;
    dimension: string;
    precision: number;
  };
  target: {
    doctype: "UOM";
    name: string;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "FinDefinition".
 */
export interface FinDefinition {
  number: string;
  kind: "prime" | "subcontract" | "consultant" | "service";
  direction: "receivable" | "payable";
  party_type: "Customer" | "Supplier";
  party: string;
  currency: string;
  original_value: FinMoney;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "FinMoney".
 */
export interface FinMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "FinCurrencyPolicy".
 */
export interface FinCurrencyPolicy {
  currency: string;
  currency_exponent: number;
  fraction_units: number;
  native_currency_version: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwAvailability".
 */
export interface AwAvailability {
  action: "award.project.create.v1";
  action_available: boolean;
  disabled_reason: string | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwTeamMember".
 */
export interface AwTeamMember {
  person_id: string;
  /**
   * @minItems 1
   * @maxItems 15
   */
  abilities:
    | [
        | "project.read"
        | "project.write"
        | "task.create"
        | "document.read"
        | "document.write"
        | "ricky.run"
        | "approval.request"
        | "approval.decide"
        | "approval.execute"
        | "estimate.read"
        | "estimate.write"
        | "contract.read"
        | "contract.write"
        | "wbs.read"
        | "budget.read"
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ];
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwTeam".
 */
export interface AwTeam {
  delegator_person: string;
  policy_id: string;
  policy_digest: string;
  /**
   * @minItems 1
   * @maxItems 25
   */
  members: [AwTeamMember, ...AwTeamMember[]];
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwDelegationDefinition".
 */
export interface AwDelegationDefinition {
  schema: "cipher.project-team.delegation-policy.v1";
  version: 1;
  max_members: 25;
  /**
   * @minItems 1
   * @maxItems 15
   */
  allowed_project_abilities:
    | [
        | "project.read"
        | "project.write"
        | "task.create"
        | "document.read"
        | "document.write"
        | "ricky.run"
        | "approval.request"
        | "approval.decide"
        | "approval.execute"
        | "estimate.read"
        | "estimate.write"
        | "contract.read"
        | "contract.write"
        | "wbs.read"
        | "budget.read"
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ]
    | [
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        ),
        (
          | "project.read"
          | "project.write"
          | "task.create"
          | "document.read"
          | "document.write"
          | "ricky.run"
          | "approval.request"
          | "approval.decide"
          | "approval.execute"
          | "estimate.read"
          | "estimate.write"
          | "contract.read"
          | "contract.write"
          | "wbs.read"
          | "budget.read"
        )
      ];
  delegator_must_be_requester: true;
  team_identity_kind: "Human";
  eligibility_ability: "company.read";
  implicit_creator_access: false;
  role_copy: false;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwDelegationPolicy".
 */
export interface AwDelegationPolicy {
  id: string;
  company: string;
  version: number;
  digest: string;
  definition: AwDelegationDefinition;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwProjectDefinition".
 */
export interface AwProjectDefinition {
  project_name: string;
  expected_start_date: string;
  expected_end_date: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwNativeOrderDefinition".
 */
export interface AwNativeOrderDefinition {
  customer: string;
  transaction_date: string;
  delivery_date: string;
  selling_price_list: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwLineMapping".
 */
export interface AwLineMapping {
  proposal_line_id: string;
  item_code: string;
  delivery_date: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwEvidenceInput".
 */
export interface AwEvidenceInput {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256: string;
  purpose: string;
  permission_basis: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwEvidence".
 */
export interface AwEvidence {
  citation: ComCompanyCitation;
  purpose: string;
  permission_basis: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwDefinition".
 */
export interface AwDefinition {
  issue_id: string;
  project_definition: AwProjectDefinition;
  native_order_definition: AwNativeOrderDefinition;
  contract_definition: FinDefinition;
  /**
   * @minItems 1
   * @maxItems 150
   */
  line_mappings: [AwLineMapping, ...AwLineMapping[]];
  /**
   * @minItems 1
   * @maxItems 8
   */
  award_evidence:
    | [AwEvidenceInput]
    | [AwEvidenceInput, AwEvidenceInput]
    | [AwEvidenceInput, AwEvidenceInput, AwEvidenceInput]
    | [AwEvidenceInput, AwEvidenceInput, AwEvidenceInput, AwEvidenceInput]
    | [AwEvidenceInput, AwEvidenceInput, AwEvidenceInput, AwEvidenceInput, AwEvidenceInput]
    | [AwEvidenceInput, AwEvidenceInput, AwEvidenceInput, AwEvidenceInput, AwEvidenceInput, AwEvidenceInput]
    | [
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput
      ]
    | [
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput,
        AwEvidenceInput
      ];
  party_correspondence: {
    lead: string;
    customer: string;
    explanation: string;
  } | null;
  team: AwTeam;
  /**
   * @minItems 1
   * @maxItems 500
   */
  wbs_nodes: [PcWbsNode, ...PcWbsNode[]];
  /**
   * @minItems 1
   * @maxItems 5030
   */
  budget_allocations: [PcAllocation, ...PcAllocation[]];
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwSelectedLine".
 */
export interface AwSelectedLine {
  proposal_line_id: string;
  award_line_id: string;
  description: string;
  item_code: string;
  quantity: string;
  rate: string;
  amount: string;
  unit: PcQualifiedUnit;
  currency: string;
  conversion_factor: {
    numerator: "1";
    denominator: "1";
  };
  delivery_date: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwNativeReference".
 */
export interface AwNativeReference {
  doctype: string;
  name: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwSourcePlan".
 */
export interface AwSourcePlan {
  /**
   * @minItems 0
   * @maxItems 128
   */
  generated_sources: {
    document_id: string;
    input_digest: string;
  }[];
  /**
   * @minItems 0
   * @maxItems 500
   */
  unit_ids: string[];
  /**
   * @minItems 0
   * @maxItems 20
   */
  currencies:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ];
  /**
   * @minItems 0
   * @maxItems 1000
   */
  native_refs: AwNativeReference[];
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwNativeSources".
 */
export interface AwNativeSources {
  company_version: string;
  base_currency: string;
  currency_policy: FinCurrencyPolicy;
  /**
   * @minItems 0
   * @maxItems 500
   */
  qualified_units: PcQualifiedUnit[];
  /**
   * @minItems 0
   * @maxItems 1000
   */
  native_references: {
    doctype: string;
    name: string;
    version: string;
  }[];
  native_create_policy: ["Project", "Sales Order"];
  payment_schedule_policy: "native-default-100-percent-transaction-date-v1";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwIssuedOutput".
 */
export interface AwIssuedOutput {
  document_id: string;
  revision_id: string;
  source_sha256: string;
  byte_length: number;
  input_digest: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwSourceFacts".
 */
export interface AwSourceFacts {
  issue_digest: string;
  pursuit: string;
  opportunity: string;
  accepted_estimate: ComAcceptedEstimate;
  native_sources: AwNativeSources;
  /**
   * @minItems 1
   * @maxItems 8
   */
  award_evidence:
    | [AwEvidence]
    | [AwEvidence, AwEvidence]
    | [AwEvidence, AwEvidence, AwEvidence]
    | [AwEvidence, AwEvidence, AwEvidence, AwEvidence]
    | [AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence]
    | [AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence]
    | [AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence]
    | [AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence, AwEvidence];
  issued_output: AwIssuedOutput;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwHandoff".
 */
export interface AwHandoff {
  id: string;
  schema: "cipher.award.handoff.v1";
  scope_type: "Company";
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: "draft" | "adopted";
  pursuit: string;
  opportunity: string;
  issue: string;
  revision_number: number;
  current_revision: string | null;
  adoption: string | null;
  original_issue: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwServerIdentities".
 */
export interface AwServerIdentities {
  id: string;
  profile_id: string;
  contract_id: string;
  adoption_id: string;
  line_ids: {
    [k: string]: string;
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwPlan".
 */
export interface AwPlan {
  id: string;
  schema: "cipher.award.plan.v1";
  scope_type: "Company";
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: "planned";
  handoff: string;
  revision_number: number;
  predecessor: string | null;
  ids: AwServerIdentities;
  resource_plan: AwSourcePlan;
  definition: AwDefinition;
  issue: string;
  issue_digest: string;
  source_facts: AwSourceFacts;
  controls_plan: PcInitialPlan;
  /**
   * @minItems 1
   * @maxItems 150
   */
  lines: [AwSelectedLine, ...AwSelectedLine[]];
  /**
   * @minItems 1
   * @maxItems 26
   */
  participants: [string, ...string[]];
  delegation_policy: AwDelegationPolicy;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwProjectAccess".
 */
export interface AwProjectAccess {
  standing: "not_created" | "available" | "not_available";
  project_id: string | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwHandoffResponse".
 */
export interface AwHandoffResponse {
  handoff: AwHandoff;
  version: string;
  project_access: AwProjectAccess;
  availability: AwAvailability;
  adoption: AwAdoption | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwAdoption".
 */
export interface AwAdoption {
  id: string;
  scope_type: "Company";
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  schema: "cipher.award.adoption.v1";
  status: "adopted";
  target_project: string;
  handoff: string;
  award_revision: string;
  pursuit: string;
  opportunity: string;
  issue: string;
  issue_digest: string;
  sales_order: string;
  contract: string;
  effect_binding: AwEffectBinding;
  plan_digest: string;
  accepted_estimate: ComAcceptedEstimate;
  native_digest: string;
  native_version: string;
  native_snapshot: AwNativeSnapshot;
  profile: string;
  budget: string;
  controls_plan_digest: string;
  /**
   * @maxItems 25
   */
  team: AwTeamMember[];
  /**
   * @maxItems 150
   */
  line_adoptions: string[];
  packet_id: string;
  decision_id: string;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwEffectBinding".
 */
export interface AwEffectBinding {
  company: string;
  project: string;
  award_id: string;
  award_revision_id: string;
  plan_digest: string;
  packet_id: string;
  decision_id: string;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwNativeSnapshot".
 */
export interface AwNativeSnapshot {
  projection: {
    schema: "cipher.award.sales_order.reconciliation.v1";
    header: {
      name: string;
      company: string;
      project: string;
      customer: string;
      transaction_date: string;
      delivery_date: string;
      currency: string;
      selling_price_list: string;
      price_list_currency: string;
      apply_discount_on: string;
      cipher_award_handoff: string;
      cipher_issue: string;
      cipher_issue_digest: string;
      cipher_proposal_revision: string;
      cipher_accepted_baseline: string;
      conversion_rate: string;
      plc_conversion_rate: string;
      total: string;
      net_total: string;
      grand_total: string;
      rounded_total: string;
      base_total: string;
      base_net_total: string;
      base_grand_total: string;
      base_rounded_total: string;
      total_taxes_and_charges: string;
      discount_amount: string;
      additional_discount_percentage: string;
      docstatus: 0;
      payment_terms_template: "";
    };
    /**
     * @maxItems 150
     */
    rows: {
      name: string;
      cipher_award_line_id: string;
      cipher_proposal_line_id: string;
      item_code: string;
      description: string;
      uom: string;
      stock_uom: string;
      delivery_date: string;
      prevdoc_docname: string;
      quotation_item: string;
      qty: string;
      conversion_factor: string;
      rate: string;
      amount: string;
      base_rate: string;
      base_amount: string;
      discount_percentage: string;
      discount_amount: string;
    }[];
    /**
     * @minItems 1
     * @maxItems 1
     */
    payment_schedule: [
      {
        name: string;
        payment_term: "";
        description: "";
        due_date: string;
        mode_of_payment: "";
        discount_date: "";
        discount_type: "Percentage";
        due_date_based_on: "";
        discount_validity_based_on: "";
        invoice_portion: string;
        payment_amount: string;
        base_payment_amount: string;
        paid_amount: string;
        base_paid_amount: string;
        discounted_amount: string;
        outstanding: string;
        base_outstanding: string;
        discount: string;
        credit_days: string;
        credit_months: string;
        discount_validity: string;
      }
    ];
  };
  digest: string;
  version: string;
  derived_digest: string;
  support: {
    tax_rows: 0;
    packed_item_count: 0;
    skip_delivery_note: 0;
    taxes_and_charges: "";
    shipping_rule: "";
    tax_category: "";
    terms: string;
    order_type: "Sales";
    status: "Draft";
    disable_rounded_total: 1;
    ignore_pricing_rule: 1;
    unsupported_item_behavior: false;
    tc_name: "";
  };
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwPlanResponse".
 */
export interface AwPlanResponse {
  plan: AwPlan;
  version: string;
  availability: AwAvailability;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwInputQualification".
 */
export interface AwInputQualification {
  policy: "qualified-original-estimate-inputs-v1";
  eligible: boolean;
  generated_input_count: number;
  disabled_reason: string | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwSourcePreview".
 */
export interface AwSourcePreview {
  company: string;
  issue: ComIssue;
  issue_digest: string;
  pursuit: ComPursuit;
  handoff: AwHandoffResponse | null;
  input_qualification: AwInputQualification;
  accepted_baseline: CompanyEstAcceptanceRecord;
  accepted_baseline_digest: string;
  availability: AwAvailability;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwPlanPreview".
 */
export interface AwPlanPreview {
  definition: AwDefinition;
  issue: string;
  issue_digest: string;
  source_facts: AwSourceFacts;
  controls_plan: PcInitialPlan;
  /**
   * @minItems 1
   * @maxItems 150
   */
  lines: [AwSelectedLine, ...AwSelectedLine[]];
  /**
   * @minItems 1
   * @maxItems 26
   */
  participants: [string, ...string[]];
  delegation_policy: AwDelegationPolicy;
  availability: AwAvailability;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwApprovalSubject".
 */
export interface AwApprovalSubject {
  revision_id: string;
  record_digest: string;
  handoff_id: string;
  is_current: boolean;
  current_revision: string | null;
  adoption_id: string | null;
  action: "award.project.create.v1";
  action_available: boolean;
  disabled_reason: string | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwDelegationPolicyResponse".
 */
export interface AwDelegationPolicyResponse {
  policy: AwDelegationPolicy;
  requester_person: string;
  availability: AwAvailability;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwTeamChoice".
 */
export interface AwTeamChoice {
  person_id: string;
  display_name: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwHandoffList".
 */
export interface AwHandoffList {
  /**
   * @minItems 0
   * @maxItems 200
   */
  items: AwHandoffResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwTeamChoices".
 */
export interface AwTeamChoices {
  /**
   * @minItems 0
   * @maxItems 200
   */
  items: AwTeamChoice[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwOperation".
 */
export interface AwOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwHandoffCommand".
 */
export interface AwHandoffCommand {
  handoff: AwHandoff;
  version: string;
  project_access: AwProjectAccess;
  availability: AwAvailability;
  operation: AwOperation;
  adoption: AwAdoption | null;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwPlanCommand".
 */
export interface AwPlanCommand {
  plan: AwPlan;
  version: string;
  handoff: AwHandoff;
  handoff_version: string;
  operation: AwOperation;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwListHandoffsRequest".
 */
export interface AwListHandoffsRequest {
  company: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwGetHandoffRequest".
 */
export interface AwGetHandoffRequest {
  company: string;
  handoff_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwGetPlanRequest".
 */
export interface AwGetPlanRequest {
  company: string;
  revision_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwApprovalSubjectRequest".
 */
export interface AwApprovalSubjectRequest {
  company: string;
  revision_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwDelegationPolicyRequest".
 */
export interface AwDelegationPolicyRequest {
  company: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwTeamChoicesRequest".
 */
export interface AwTeamChoicesRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwSourcePreviewRequest".
 */
export interface AwSourcePreviewRequest {
  company: string;
  issue_id: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwPreviewPlanRequest".
 */
export interface AwPreviewPlanRequest {
  company: string;
  handoff_id: string;
  expected_version: string;
  definition: AwDefinition;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwCreateHandoffRequest".
 */
export interface AwCreateHandoffRequest {
  company: string;
  issue_id: string;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwPlanHandoffRequest".
 */
export interface AwPlanHandoffRequest {
  company: string;
  handoff_id: string;
  expected_version: string;
  definition: AwDefinition;
  operation_id?: string;
}
/**
 * This interface was referenced by `CipherAwardContract`'s JSON-Schema
 * via the `definition` "AwAwardEffect".
 */
export interface AwAwardEffect {
  adoption: AwAdoption;
  version: string;
}
