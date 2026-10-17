/* Generated from cipher_aec/ricky/schemas/company-draft-save-api-v1.schema.json. Do not edit.
 * Source SHA-256: 5012dcb273a48e82d55776aeb7def3976efa7ab52289da5ba5ef70abd7287dd2
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSavePayload".
 */
export type CompanyDraftSavePayload =
  | {
      proposal_id: string;
      expected_revision: number;
      expected_native_fingerprint: string;
      composition: ComComposition;
    }
  | {
      estimate_id: string;
      expected_revision: string | null;
      /**
       * @maxItems 100
       */
      lines: EstLineInput[];
      /**
       * @maxItems 30
       */
      adjustments: EstAdjustment[];
      /**
       * @maxItems 64
       */
      conversion_ids: string[];
      basis_description: string;
      /**
       * @maxItems 8
       */
      basis_citations: EstCitationReference[];
    };
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "EstLineInput".
 */
export type EstLineInput = EstDirectLine | EstAssemblyLine;
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveCanonicalResult".
 */
export type CompanyDraftSaveCanonicalResult =
  | {
      proposal: ComProposal;
      revision: ComRevision;
    }
  | {
      estimate: CompanyEstEstimateRecord;
      revision: CompanyEstRevisionRecord;
      calculation: CompanyEstSnapshotRecord;
      history_id: string;
    };
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstCanonicaluuid".
 */
export type CompanyEstCanonicaluuid = string;
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstLineInput".
 */
export type CompanyEstLineInput = CompanyEstDirectLine | CompanyEstAssemblyLine;

export interface CipherCompanyDraftSaveContract {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveCore".
 */
export interface CompanyDraftSaveCore {
  id: string;
  proposal_id: string;
  run_id: string;
  step_id: string;
  invocation_id: string;
  target_id: string;
  base_revision_id: string;
  saved_revision_id: string;
  operation_id: string;
  proposal_digest: string;
  preparation_digest: string;
  manifest_digest: string;
  payload_digest: string;
  saved_revision_digest: string;
  receipt_id: string;
  core_digest: string;
  schema: "cipher.ricky.company.draft-save.v1";
  scope_type: "Company";
  project: null;
  company: string;
  user: string;
  person: string;
  proposal_version: 1;
  action: "aec.scope.draft" | "aec.estimate.draft";
  classification: "unverified-author-suggestion";
  mapping_version: "1";
  command: "ricky.company.proposal.save-scope.v1" | "ricky.company.proposal.save-estimate.v1";
  canonical_command: "commercial.proposal.revise" | "estimate.calculate.v1";
  target_doctype: "Cipher Proposal" | "Cipher Estimate";
  saved_doctype: "Cipher Proposal Revision" | "Cipher Estimate Revision";
  created_at: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
  price_lines: ComPriceLine[];
  /**
   * @maxItems 30
   */
  source_references?: ComSourceReference[];
  estimate_revision?: null;
  price_list: string;
  estimate_reference?: ComEstimateReference | null;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "ComSection".
 */
export interface ComSection {
  id: string;
  kind: "scope" | "assumption" | "exclusion" | "schedule" | "other";
  title: string;
  text: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "ComEstimateReference".
 */
export interface ComEstimateReference {
  acceptance_id: string;
  acceptance_digest: string;
  revision_id: string;
  revision_digest: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "EstDirectLine".
 */
export interface EstDirectLine {
  line_id: string;
  description: string;
  quantity: EstQuantity;
  cost_code: string;
  notes: string;
  alternate: string;
  included: boolean;
  rate_source_id: string;
  material_factor: string;
  waste_fraction: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "EstQuantity".
 */
export interface EstQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "EstAssemblyLine".
 */
export interface EstAssemblyLine {
  line_id: string;
  description: string;
  quantity: EstQuantity;
  cost_code: string;
  notes: string;
  alternate: string;
  included: boolean;
  assembly_revision_id: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "EstAdjustment".
 */
export interface EstAdjustment {
  line_id: string;
  kind: "indirect" | "contingency";
  label: string;
  method: "fixed" | "fraction_of_direct";
  value: string;
  basis_description: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "EstCitationReference".
 */
export interface EstCitationReference {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256?: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "ComPricing".
 */
export interface ComPricing {
  policy: "native-no-tax-no-discount-half-up-v1";
  currency_exponent: number;
  lines: ComPricedLine[];
  total: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
  taxes: unknown[];
  selling_price_list: string;
  price_list_currency: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "ComSourceCitation".
 */
export interface ComSourceCitation {
  citation: ComCompanyCitation;
  purpose: string;
  permission_basis: string;
  policy: "pinned-revision-page-v1";
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstEstimateRecord".
 */
export interface CompanyEstEstimateRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  title: string;
  currency: string;
  pricing_date: string;
  revision_number: number;
  current_revision: string | null;
  scope_type: "Company";
  pursuit_id: string | null;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstRevisionRecord".
 */
export interface CompanyEstRevisionRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  estimate: string;
  revision_number: number;
  predecessor: string | null;
  calculation_snapshot: string;
  currency: string;
  pricing_date: string;
  policy_version: "cipher.estimate.line-half-up.v1";
  /**
   * @maxItems 100
   */
  line_record_ids: string[];
  /**
   * @maxItems 64
   */
  source_citations: CompanyEstCitation[];
  basis_description: string;
  direct: CompanyEstMoney;
  indirect: CompanyEstMoney;
  contingency: CompanyEstMoney;
  total: CompanyEstMoney;
  scope_type: "Company";
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstMoney".
 */
export interface CompanyEstMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstSnapshotRecord".
 */
export interface CompanyEstSnapshotRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  subject_type: "Cipher Estimate Revision";
  subject_id: string;
  inputs: CompanyEstCalculationInputs;
  result: CompanyEstCalculationResult;
  currency_policy: {
    currency: string;
    currency_exponent: number;
    fraction_units: number;
    native_currency_version: string;
  };
  input_digest: string;
  output_digest: string;
  /**
   * @maxItems 64
   */
  source_citations: CompanyEstCitation[];
  scope_type: "Company";
  estimate: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstCalculationInputs".
 */
export interface CompanyEstCalculationInputs {
  schema: "cipher.estimate.inputs.v2";
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  currency: string;
  currency_exponent: number;
  pricing_date: string;
  policy_version: "cipher.estimate.line-half-up.v1";
  basis_description: string;
  /**
   * @maxItems 8
   */
  basis_citations: CompanyEstCitation[];
  rates: {
    [k: string]: CompanyEstRateDefinition;
  };
  assemblies: {
    [k: string]: CompanyEstAssemblyDefinition;
  };
  /**
   * @maxItems 100
   */
  lines: CompanyEstLineInput[];
  /**
   * @maxItems 30
   */
  adjustments: CompanyEstAdjustment[];
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstUnitManifest".
 */
export interface CipherIndependentCanonicalMasterDimensionManifestV1 {
  schema: "cipher.canonical.v2";
  dataset_id: CompanyEstCanonicaluuid;
  scope: {
    company: string;
    project: null;
    scope_type: "Company";
  };
  label?: string;
  /**
   * @minItems 1
   * @maxItems 500
   */
  records: (
    | {
        id: CompanyEstCanonicaluuid;
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
        id: CompanyEstCanonicaluuid;
        kind: "project";
        revision: number;
        fields: {
          title: string;
          company_id: CompanyEstCanonicaluuid;
          status: "Open" | "On hold" | "Completed" | "Cancelled";
          customer_id?: CompanyEstCanonicaluuid;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "Project";
          name: string;
          version?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
        kind: "customer";
        revision: number;
        fields: {
          name: string;
          company_id: CompanyEstCanonicaluuid;
          active: boolean;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "Customer";
          name: string;
          version?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
        kind: "supplier";
        revision: number;
        fields: {
          name: string;
          company_id: CompanyEstCanonicaluuid;
          active: boolean;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "Supplier";
          name: string;
          version?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
        kind: "item";
        revision: number;
        fields: {
          code: string;
          name: string;
          company_id: CompanyEstCanonicaluuid;
          stock_uom_id: CompanyEstCanonicaluuid;
          is_stock_item: boolean;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "Item";
          name: string;
          version?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
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
    | {
        id: CompanyEstCanonicaluuid;
        kind: "cost_center";
        revision: number;
        fields: {
          code: string;
          name: string;
          company_id: CompanyEstCanonicaluuid;
          is_group: boolean;
          parent_id?: CompanyEstCanonicaluuid;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
        target?: {
          doctype: "Cost Center";
          name: string;
          version?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
        kind: "cost_code";
        revision: number;
        fields: {
          code: string;
          title: string;
          company_id: CompanyEstCanonicaluuid;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
        kind: "cost_type";
        revision: number;
        fields: {
          code: string;
          title: string;
          company_id: CompanyEstCanonicaluuid;
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
      }
    | {
        id: CompanyEstCanonicaluuid;
        kind: "accounting_dimension";
        revision: number;
        fields: {
          code: string;
          title: string;
          company_id: CompanyEstCanonicaluuid;
          value_kind: "project" | "cost_center" | "cost_code" | "cost_type";
        };
        source?: {
          system: string;
          record_id: string;
          revision?: string;
        };
      }
  )[];
  /**
   * @maxItems 1000
   */
  unit_conversions: CompanyEstCanonicalconversion[];
  /**
   * @maxItems 500
   */
  quantities?: CompanyEstCanonicalquantity[];
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstCanonicalconversion".
 */
export interface CompanyEstCanonicalconversion {
  id: CompanyEstCanonicaluuid;
  revision: number;
  from_unit_id: CompanyEstCanonicaluuid;
  to_unit_id: CompanyEstCanonicaluuid;
  dimension: "area" | "count" | "equipment_time" | "labor_time" | "length" | "mass" | "time" | "volume";
  numerator: string;
  denominator: string;
  source: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstCanonicalquantity".
 */
export interface CompanyEstCanonicalquantity {
  id: CompanyEstCanonicaluuid;
  amount: string;
  unit_id: CompanyEstCanonicaluuid;
  convert_to_unit_id?: CompanyEstCanonicaluuid;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstRateDefinition".
 */
export interface CompanyEstRateDefinition {
  title: string;
  cost_type: "material" | "labor" | "equipment" | "subcontract" | "other";
  unit_id: string;
  rate_amount: string;
  rate_precision: number;
  currency: string;
  quote_reference: string;
  quote_date: string;
  expiry_date: string | null;
  geography: string;
  inclusions: string;
  exclusions: string;
  freight_tax_assumptions: string;
  permission_basis: string;
  /**
   * @maxItems 8
   */
  source_citations: CompanyEstCitation[];
  item: string | null;
  party_type: null | "Supplier" | "Customer";
  party: string | null;
  id: string;
  source_id: string;
  revision: number;
  predecessor: string | null;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstAssemblyDefinition".
 */
export interface CompanyEstAssemblyDefinition {
  id: string;
  assembly_id: string;
  revision: number;
  predecessor: string | null;
  title: string;
  basis_unit_id: string;
  /**
   * @maxItems 50
   */
  components: CompanyEstAssemblyComponent[];
  author_basis: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstAssemblyComponent".
 */
export interface CompanyEstAssemblyComponent {
  line_id: string;
  rate_source_id: string;
  kind: "material" | "labor" | "equipment" | "subcontract" | "other";
  work_quantity: CompanyEstQuantity;
  resource_quantity: CompanyEstQuantity;
  material_factor: string;
  waste_fraction: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstQuantity".
 */
export interface CompanyEstQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstDirectLine".
 */
export interface CompanyEstDirectLine {
  line_id: string;
  description: string;
  quantity: CompanyEstQuantity;
  cost_code: string;
  notes: string;
  alternate: string;
  included: boolean;
  rate_source_id: string;
  material_factor: string;
  waste_fraction: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstAssemblyLine".
 */
export interface CompanyEstAssemblyLine {
  line_id: string;
  description: string;
  quantity: CompanyEstQuantity;
  cost_code: string;
  notes: string;
  alternate: string;
  included: boolean;
  assembly_revision_id: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstAdjustment".
 */
export interface CompanyEstAdjustment {
  line_id: string;
  kind: "indirect" | "contingency";
  label: string;
  method: "fixed" | "fraction_of_direct";
  value: string;
  basis_description: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyEstRational".
 */
export interface CompanyEstRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
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
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveReason".
 */
export interface CompanyDraftSaveReason {
  code: string;
  message: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveSubjectRequest".
 */
export interface CompanyDraftSaveSubjectRequest {
  company: string;
  proposal_id: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveRequest".
 */
export interface CompanyDraftSaveRequest {
  company: string;
  proposal_id: string;
  expected_version: 1;
  expected_content_digest: string;
  mapping_version: "1";
  expected_payload_digest: string;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveSubject".
 */
export interface CompanyDraftSaveSubject {
  proposal_id: string;
  proposal_version: 1;
  proposal_digest: string;
  action: "aec.scope.draft" | "aec.estimate.draft";
  mapping_version: "1";
  payload: CompanyDraftSavePayload;
  payload_digest: string;
  expires_at: string;
  eligible: boolean;
  reason: null | CompanyDraftSaveReason;
  application: null | CompanyDraftSaveCore;
  saved: null | CompanyDraftSaveCanonicalResult;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "CompanyDraftSaveResponse".
 */
export interface CompanyDraftSaveResponse {
  application: CompanyDraftSaveCore;
  saved: CompanyDraftSaveCanonicalResult;
  operation: ComOperation;
}
/**
 * This interface was referenced by `CipherCompanyDraftSaveContract`'s JSON-Schema
 * via the `definition` "ComOperation".
 */
export interface ComOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}

// Exact published definitions and their transitive canonical dependencies.
export const companyDraftSaveSchema = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$defs": {
    "CompanyDraftSaveCore": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "proposal_id": {
          "type": "string",
          "format": "uuid"
        },
        "run_id": {
          "type": "string",
          "format": "uuid"
        },
        "step_id": {
          "type": "string",
          "format": "uuid"
        },
        "invocation_id": {
          "type": "string",
          "format": "uuid"
        },
        "target_id": {
          "type": "string",
          "format": "uuid"
        },
        "base_revision_id": {
          "type": "string",
          "format": "uuid"
        },
        "saved_revision_id": {
          "type": "string",
          "format": "uuid"
        },
        "operation_id": {
          "type": "string",
          "format": "uuid"
        },
        "proposal_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "preparation_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "manifest_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "payload_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "saved_revision_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "receipt_id": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "core_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "schema": {
          "const": "cipher.ricky.company.draft-save.v1"
        },
        "scope_type": {
          "const": "Company"
        },
        "project": {
          "type": "null"
        },
        "company": {
          "type": "string",
          "minLength": 1
        },
        "user": {
          "type": "string",
          "minLength": 1
        },
        "person": {
          "type": "string",
          "minLength": 1
        },
        "proposal_version": {
          "const": 1
        },
        "action": {
          "enum": [
            "aec.scope.draft",
            "aec.estimate.draft"
          ]
        },
        "classification": {
          "const": "unverified-author-suggestion"
        },
        "mapping_version": {
          "const": "1"
        },
        "command": {
          "enum": [
            "ricky.company.proposal.save-scope.v1",
            "ricky.company.proposal.save-estimate.v1"
          ]
        },
        "canonical_command": {
          "enum": [
            "commercial.proposal.revise",
            "estimate.calculate.v1"
          ]
        },
        "target_doctype": {
          "enum": [
            "Cipher Proposal",
            "Cipher Estimate"
          ]
        },
        "saved_doctype": {
          "enum": [
            "Cipher Proposal Revision",
            "Cipher Estimate Revision"
          ]
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        }
      },
      "required": [
        "id",
        "proposal_id",
        "run_id",
        "step_id",
        "invocation_id",
        "target_id",
        "base_revision_id",
        "saved_revision_id",
        "operation_id",
        "proposal_digest",
        "preparation_digest",
        "manifest_digest",
        "payload_digest",
        "saved_revision_digest",
        "receipt_id",
        "core_digest",
        "schema",
        "scope_type",
        "project",
        "company",
        "user",
        "person",
        "proposal_version",
        "action",
        "classification",
        "mapping_version",
        "command",
        "canonical_command",
        "target_doctype",
        "saved_doctype",
        "created_at"
      ],
      "additionalProperties": false
    },
    "CompanyDraftSavePayload": {
      "oneOf": [
        {
          "type": "object",
          "properties": {
            "proposal_id": {
              "type": "string",
              "format": "uuid"
            },
            "expected_revision": {
              "type": "integer",
              "minimum": 1
            },
            "expected_native_fingerprint": {
              "type": "string",
              "pattern": "^[a-f0-9]{64}$"
            },
            "composition": {
              "$ref": "#/$defs/ComComposition"
            }
          },
          "required": [
            "proposal_id",
            "expected_revision",
            "expected_native_fingerprint",
            "composition"
          ],
          "additionalProperties": false
        },
        {
          "type": "object",
          "properties": {
            "estimate_id": {
              "type": "string",
              "format": "uuid"
            },
            "expected_revision": {
              "anyOf": [
                {
                  "type": "string",
                  "format": "uuid"
                },
                {
                  "type": "null"
                }
              ]
            },
            "lines": {
              "type": "array",
              "items": {
                "$ref": "#/$defs/EstLineInput"
              },
              "maxItems": 100
            },
            "adjustments": {
              "type": "array",
              "items": {
                "$ref": "#/$defs/EstAdjustment"
              },
              "maxItems": 30
            },
            "conversion_ids": {
              "type": "array",
              "items": {
                "type": "string",
                "format": "uuid"
              },
              "maxItems": 64
            },
            "basis_description": {
              "type": "string",
              "maxLength": 2000
            },
            "basis_citations": {
              "type": "array",
              "items": {
                "$ref": "#/$defs/EstCitationReference"
              },
              "maxItems": 8
            }
          },
          "required": [
            "estimate_id",
            "expected_revision",
            "lines",
            "adjustments",
            "conversion_ids",
            "basis_description",
            "basis_citations"
          ],
          "additionalProperties": false
        }
      ]
    },
    "CompanyDraftSaveCanonicalResult": {
      "oneOf": [
        {
          "type": "object",
          "properties": {
            "proposal": {
              "$ref": "#/$defs/ComProposal"
            },
            "revision": {
              "$ref": "#/$defs/ComRevision"
            }
          },
          "required": [
            "proposal",
            "revision"
          ],
          "additionalProperties": false
        },
        {
          "type": "object",
          "properties": {
            "estimate": {
              "$ref": "#/$defs/CompanyEstEstimateRecord"
            },
            "revision": {
              "$ref": "#/$defs/CompanyEstRevisionRecord"
            },
            "calculation": {
              "$ref": "#/$defs/CompanyEstSnapshotRecord"
            },
            "history_id": {
              "type": "string"
            }
          },
          "required": [
            "estimate",
            "revision",
            "calculation",
            "history_id"
          ],
          "additionalProperties": false
        }
      ]
    },
    "CompanyDraftSaveReason": {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "minLength": 1
        },
        "message": {
          "type": "string",
          "minLength": 1
        }
      },
      "required": [
        "code",
        "message"
      ],
      "additionalProperties": false
    },
    "CompanyDraftSaveSubjectRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1
        },
        "proposal_id": {
          "type": "string",
          "format": "uuid"
        }
      },
      "required": [
        "company",
        "proposal_id"
      ],
      "additionalProperties": false
    },
    "CompanyDraftSaveRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1
        },
        "proposal_id": {
          "type": "string",
          "format": "uuid"
        },
        "expected_version": {
          "const": 1
        },
        "expected_content_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "mapping_version": {
          "const": "1"
        },
        "expected_payload_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "operation_id": {
          "type": "string",
          "format": "uuid"
        }
      },
      "required": [
        "company",
        "proposal_id",
        "expected_version",
        "expected_content_digest",
        "mapping_version",
        "expected_payload_digest",
        "operation_id"
      ],
      "additionalProperties": false
    },
    "CompanyDraftSaveSubject": {
      "type": "object",
      "properties": {
        "proposal_id": {
          "type": "string",
          "format": "uuid"
        },
        "proposal_version": {
          "const": 1
        },
        "proposal_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "action": {
          "enum": [
            "aec.scope.draft",
            "aec.estimate.draft"
          ]
        },
        "mapping_version": {
          "const": "1"
        },
        "payload": {
          "$ref": "#/$defs/CompanyDraftSavePayload"
        },
        "payload_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "expires_at": {
          "type": "string",
          "format": "date-time"
        },
        "eligible": {
          "type": "boolean"
        },
        "reason": {
          "oneOf": [
            {
              "type": "null"
            },
            {
              "$ref": "#/$defs/CompanyDraftSaveReason"
            }
          ]
        },
        "application": {
          "oneOf": [
            {
              "type": "null"
            },
            {
              "$ref": "#/$defs/CompanyDraftSaveCore"
            }
          ]
        },
        "saved": {
          "oneOf": [
            {
              "type": "null"
            },
            {
              "$ref": "#/$defs/CompanyDraftSaveCanonicalResult"
            }
          ]
        }
      },
      "required": [
        "proposal_id",
        "proposal_version",
        "proposal_digest",
        "action",
        "mapping_version",
        "payload",
        "payload_digest",
        "expires_at",
        "eligible",
        "reason",
        "application",
        "saved"
      ],
      "additionalProperties": false
    },
    "CompanyDraftSaveResponse": {
      "type": "object",
      "properties": {
        "application": {
          "$ref": "#/$defs/CompanyDraftSaveCore"
        },
        "saved": {
          "$ref": "#/$defs/CompanyDraftSaveCanonicalResult"
        },
        "operation": {
          "$ref": "#/$defs/ComOperation"
        }
      },
      "required": [
        "application",
        "saved",
        "operation"
      ],
      "additionalProperties": false
    },
    "ComComposition": {
      "type": "object",
      "properties": {
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "valid_till": {
          "type": "string",
          "format": "date"
        },
        "terms": {
          "type": "string",
          "maxLength": 24000
        },
        "sections": {
          "type": "array",
          "maxItems": 80,
          "items": {
            "$ref": "#/$defs/ComSection"
          }
        },
        "price_lines": {
          "type": "array",
          "minItems": 1,
          "maxItems": 150,
          "items": {
            "$ref": "#/$defs/ComPriceLine"
          }
        },
        "source_references": {
          "type": "array",
          "maxItems": 30,
          "items": {
            "$ref": "#/$defs/ComSourceReference"
          }
        },
        "estimate_revision": {
          "type": "null"
        },
        "price_list": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "estimate_reference": {
          "anyOf": [
            {
              "$ref": "#/$defs/ComEstimateReference"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "currency",
        "valid_till",
        "terms",
        "sections",
        "price_lines",
        "price_list"
      ],
      "additionalProperties": false
    },
    "ComSection": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "kind": {
          "enum": [
            "scope",
            "assumption",
            "exclusion",
            "schedule",
            "other"
          ]
        },
        "title": {
          "type": "string",
          "maxLength": 140
        },
        "text": {
          "type": "string",
          "maxLength": 12000
        }
      },
      "required": [
        "id",
        "kind",
        "title",
        "text"
      ],
      "additionalProperties": false
    },
    "ComPriceLine": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 2000
        },
        "quantity": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,11})(\\.[0-9]{1,9})?$"
        },
        "unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "unit_revision": {
          "type": "integer",
          "minimum": 1
        },
        "rate": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,11})(\\.[0-9]{1,9})?$"
        },
        "item_code": {
          "type": [
            "string",
            "null"
          ]
        },
        "alternate_group": {
          "type": [
            "string",
            "null"
          ]
        },
        "selected": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "description",
        "quantity",
        "unit_id",
        "unit_revision",
        "rate",
        "selected"
      ],
      "additionalProperties": false
    },
    "ComSourceReference": {
      "type": "object",
      "properties": {
        "revision_id": {
          "type": "string",
          "pattern": "^REV-[a-f0-9]{32}$"
        },
        "page": {
          "type": "integer",
          "minimum": 1,
          "maximum": 100
        },
        "excerpt_sha256": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "source_sha256": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "purpose": {
          "type": "string",
          "minLength": 1,
          "maxLength": 1000
        },
        "permission_basis": {
          "type": "string",
          "minLength": 1,
          "maxLength": 2000
        }
      },
      "required": [
        "revision_id",
        "page",
        "excerpt_sha256",
        "source_sha256",
        "purpose",
        "permission_basis"
      ],
      "additionalProperties": false
    },
    "ComEstimateReference": {
      "type": "object",
      "properties": {
        "acceptance_id": {
          "type": "string",
          "format": "uuid"
        },
        "acceptance_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "revision_id": {
          "type": "string",
          "format": "uuid"
        },
        "revision_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        }
      },
      "required": [
        "acceptance_id",
        "acceptance_digest",
        "revision_id",
        "revision_digest"
      ],
      "additionalProperties": false
    },
    "EstLineInput": {
      "oneOf": [
        {
          "$ref": "#/$defs/EstDirectLine"
        },
        {
          "$ref": "#/$defs/EstAssemblyLine"
        }
      ]
    },
    "EstDirectLine": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 200
        },
        "quantity": {
          "$ref": "#/$defs/EstQuantity"
        },
        "cost_code": {
          "type": "string",
          "maxLength": 200
        },
        "notes": {
          "type": "string",
          "maxLength": 2000
        },
        "alternate": {
          "type": "string",
          "maxLength": 200
        },
        "included": {
          "type": "boolean"
        },
        "rate_source_id": {
          "type": "string",
          "format": "uuid"
        },
        "material_factor": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "waste_fraction": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        }
      },
      "required": [
        "line_id",
        "description",
        "quantity",
        "cost_code",
        "notes",
        "alternate",
        "included",
        "rate_source_id",
        "material_factor",
        "waste_fraction"
      ],
      "additionalProperties": false
    },
    "EstQuantity": {
      "type": "object",
      "properties": {
        "amount": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "precision": {
          "type": "integer",
          "minimum": 0,
          "maximum": 12
        }
      },
      "required": [
        "amount",
        "unit_id",
        "precision"
      ],
      "additionalProperties": false
    },
    "EstAssemblyLine": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 200
        },
        "quantity": {
          "$ref": "#/$defs/EstQuantity"
        },
        "cost_code": {
          "type": "string",
          "maxLength": 200
        },
        "notes": {
          "type": "string",
          "maxLength": 2000
        },
        "alternate": {
          "type": "string",
          "maxLength": 200
        },
        "included": {
          "type": "boolean"
        },
        "assembly_revision_id": {
          "type": "string",
          "format": "uuid"
        }
      },
      "required": [
        "line_id",
        "description",
        "quantity",
        "cost_code",
        "notes",
        "alternate",
        "included",
        "assembly_revision_id"
      ],
      "additionalProperties": false
    },
    "EstAdjustment": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "kind": {
          "enum": [
            "indirect",
            "contingency"
          ]
        },
        "label": {
          "type": "string",
          "maxLength": 200
        },
        "method": {
          "enum": [
            "fixed",
            "fraction_of_direct"
          ]
        },
        "value": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "basis_description": {
          "type": "string",
          "maxLength": 2000
        }
      },
      "required": [
        "line_id",
        "kind",
        "label",
        "method",
        "value",
        "basis_description"
      ],
      "additionalProperties": false
    },
    "EstCitationReference": {
      "type": "object",
      "properties": {
        "revision_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "page": {
          "type": "integer",
          "minimum": 1
        },
        "excerpt_sha256": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "source_sha256": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        }
      },
      "required": [
        "revision_id",
        "page",
        "excerpt_sha256"
      ],
      "additionalProperties": false
    },
    "ComProposal": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "company": {
          "type": "string"
        },
        "author_person": {
          "type": "string"
        },
        "revision_number": {
          "type": "integer",
          "minimum": 1
        },
        "pursuit": {
          "type": "string",
          "format": "uuid"
        },
        "quotation": {
          "type": "string"
        },
        "party_type": {
          "enum": [
            "Customer",
            "Lead"
          ]
        },
        "party_id": {
          "type": "string"
        },
        "title": {
          "type": "string"
        },
        "current_revision": {
          "type": "string",
          "format": "uuid"
        },
        "native_fingerprint": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "native_version": {
          "type": "string"
        }
      },
      "required": [
        "id",
        "company",
        "author_person",
        "revision_number",
        "pursuit",
        "quotation",
        "party_type",
        "party_id",
        "title",
        "current_revision",
        "native_fingerprint",
        "native_version"
      ],
      "additionalProperties": false
    },
    "ComRevision": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "company": {
          "type": "string"
        },
        "author_person": {
          "type": "string"
        },
        "revision_number": {
          "type": "integer",
          "minimum": 1
        },
        "proposal": {
          "type": "string",
          "format": "uuid"
        },
        "predecessor": {
          "type": [
            "string",
            "null"
          ]
        },
        "status": {
          "const": "draft"
        },
        "composition": {
          "$ref": "#/$defs/ComComposition"
        },
        "pricing": {
          "$ref": "#/$defs/ComPricing"
        },
        "currency_policy": {
          "type": "object",
          "properties": {
            "currency": {
              "type": "string"
            },
            "currency_exponent": {
              "type": "integer"
            },
            "fraction_units": {
              "type": "integer",
              "minimum": 1
            },
            "native_currency_version": {
              "type": "string"
            },
            "price_list": {
              "type": "object",
              "properties": {
                "name": {
                  "type": "string"
                },
                "version": {
                  "type": "string"
                },
                "currency": {
                  "type": "string"
                }
              },
              "required": [
                "name",
                "version",
                "currency"
              ],
              "additionalProperties": false
            }
          },
          "required": [
            "currency",
            "currency_exponent",
            "fraction_units",
            "native_currency_version",
            "price_list"
          ],
          "additionalProperties": false
        },
        "units": {
          "type": "object",
          "additionalProperties": {
            "type": "object"
          }
        },
        "native": {
          "$ref": "#/$defs/ComNativeSnapshot"
        },
        "native_fingerprint": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "company_policy": {
          "type": "object",
          "properties": {
            "base_currency": {
              "type": "string"
            },
            "native_company_version": {
              "type": "string"
            }
          },
          "required": [
            "base_currency",
            "native_company_version"
          ],
          "additionalProperties": false
        },
        "source_citations": {
          "type": "array",
          "maxItems": 30,
          "items": {
            "$ref": "#/$defs/ComSourceCitation"
          }
        },
        "accepted_estimate": {
          "anyOf": [
            {
              "$ref": "#/$defs/ComAcceptedEstimate"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "id",
        "company",
        "author_person",
        "revision_number",
        "proposal",
        "predecessor",
        "status",
        "composition",
        "pricing",
        "currency_policy",
        "units",
        "native",
        "native_fingerprint",
        "company_policy"
      ],
      "additionalProperties": false
    },
    "ComPricing": {
      "type": "object",
      "properties": {
        "policy": {
          "const": "native-no-tax-no-discount-half-up-v1"
        },
        "currency_exponent": {
          "type": "integer",
          "minimum": 0,
          "maximum": 6
        },
        "lines": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/ComPricedLine"
          }
        },
        "total": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,11})(\\.[0-9]{1,9})?$"
        }
      },
      "required": [
        "policy",
        "currency_exponent",
        "lines",
        "total"
      ],
      "additionalProperties": false
    },
    "ComPricedLine": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 2000
        },
        "quantity": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,11})(\\.[0-9]{1,9})?$"
        },
        "unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "unit_revision": {
          "type": "integer",
          "minimum": 1
        },
        "rate": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,11})(\\.[0-9]{1,9})?$"
        },
        "item_code": {
          "type": [
            "string",
            "null"
          ]
        },
        "alternate_group": {
          "type": [
            "string",
            "null"
          ]
        },
        "selected": {
          "type": "boolean"
        },
        "amount": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,11})(\\.[0-9]{1,9})?$"
        }
      },
      "required": [
        "id",
        "description",
        "quantity",
        "unit_id",
        "unit_revision",
        "rate",
        "item_code",
        "alternate_group",
        "selected",
        "amount"
      ],
      "additionalProperties": false
    },
    "ComNativeSnapshot": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        },
        "version": {
          "type": "string"
        },
        "company": {
          "type": "string"
        },
        "quotation_to": {
          "type": "string"
        },
        "party_name": {
          "type": "string"
        },
        "opportunity": {
          "type": "string"
        },
        "currency": {
          "type": "string"
        },
        "valid_till": {
          "type": "string"
        },
        "terms": {
          "type": "string"
        },
        "docstatus": {
          "const": 0
        },
        "totals": {
          "type": "object",
          "additionalProperties": {
            "type": "string"
          }
        },
        "items": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "taxes": {
          "type": "array",
          "maxItems": 0
        },
        "selling_price_list": {
          "type": "string"
        },
        "price_list_currency": {
          "type": "string"
        }
      },
      "required": [
        "id",
        "version",
        "company",
        "quotation_to",
        "party_name",
        "opportunity",
        "currency",
        "valid_till",
        "terms",
        "docstatus",
        "totals",
        "items",
        "taxes",
        "selling_price_list",
        "price_list_currency"
      ],
      "additionalProperties": false
    },
    "ComSourceCitation": {
      "type": "object",
      "properties": {
        "citation": {
          "$ref": "#/$defs/ComCompanyCitation"
        },
        "purpose": {
          "type": "string"
        },
        "permission_basis": {
          "type": "string"
        },
        "policy": {
          "const": "pinned-revision-page-v1"
        }
      },
      "required": [
        "citation",
        "purpose",
        "permission_basis",
        "policy"
      ],
      "additionalProperties": false
    },
    "ComCompanyCitation": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        },
        "document_id": {
          "type": "string"
        },
        "revision_id": {
          "type": "string"
        },
        "document_title": {
          "type": "string"
        },
        "page_label": {
          "type": "string"
        },
        "excerpt": {
          "type": "string"
        },
        "excerpt_sha256": {
          "type": "string"
        },
        "source_sha256": {
          "type": "string"
        },
        "company": {
          "type": "string"
        },
        "revision_number": {
          "type": "integer",
          "minimum": 1
        },
        "page": {
          "type": "integer",
          "minimum": 1
        },
        "scope_type": {
          "const": "Company"
        },
        "project": {
          "type": "null"
        }
      },
      "additionalProperties": false,
      "required": [
        "id",
        "document_id",
        "revision_id",
        "document_title",
        "page_label",
        "excerpt",
        "excerpt_sha256",
        "source_sha256",
        "company",
        "revision_number",
        "page",
        "scope_type",
        "project"
      ]
    },
    "ComAcceptedEstimate": {
      "type": "object",
      "properties": {
        "acceptance_id": {
          "type": "string",
          "format": "uuid"
        },
        "acceptance_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "estimate_id": {
          "type": "string",
          "format": "uuid"
        },
        "revision_id": {
          "type": "string",
          "format": "uuid"
        },
        "revision_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "snapshot_id": {
          "type": "string",
          "format": "uuid"
        },
        "snapshot_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "manifest_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "pursuit_id": {
          "type": "string",
          "format": "uuid"
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "total": {
          "type": "object",
          "properties": {
            "amount": {
              "type": "string",
              "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]+)?$"
            },
            "currency": {
              "type": "string"
            }
          },
          "required": [
            "amount",
            "currency"
          ],
          "additionalProperties": false
        }
      },
      "required": [
        "acceptance_id",
        "acceptance_digest",
        "estimate_id",
        "revision_id",
        "revision_digest",
        "snapshot_id",
        "snapshot_digest",
        "manifest_digest",
        "pursuit_id",
        "currency",
        "total"
      ],
      "additionalProperties": false
    },
    "CompanyEstEstimateRecord": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "project": {
          "type": "null"
        },
        "author_person": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "author_user": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "status": {
          "type": "string"
        },
        "title": {
          "type": "string",
          "maxLength": 200
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "pricing_date": {
          "type": "string",
          "format": "date"
        },
        "revision_number": {
          "type": "integer",
          "minimum": 0
        },
        "current_revision": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ]
        },
        "scope_type": {
          "const": "Company"
        },
        "pursuit_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "id",
        "company",
        "project",
        "author_person",
        "author_user",
        "created_at",
        "status",
        "title",
        "currency",
        "pricing_date",
        "revision_number",
        "current_revision",
        "scope_type",
        "pursuit_id"
      ],
      "additionalProperties": false
    },
    "CompanyEstRevisionRecord": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "project": {
          "type": "null"
        },
        "author_person": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "author_user": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "status": {
          "type": "string"
        },
        "estimate": {
          "type": "string",
          "format": "uuid"
        },
        "revision_number": {
          "type": "integer",
          "minimum": 1
        },
        "predecessor": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ]
        },
        "calculation_snapshot": {
          "type": "string",
          "format": "uuid"
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "pricing_date": {
          "type": "string",
          "format": "date"
        },
        "policy_version": {
          "const": "cipher.estimate.line-half-up.v1"
        },
        "line_record_ids": {
          "type": "array",
          "items": {
            "type": "string",
            "format": "uuid"
          },
          "maxItems": 100
        },
        "source_citations": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstCitation"
          },
          "maxItems": 64
        },
        "basis_description": {
          "type": "string",
          "maxLength": 2000
        },
        "direct": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "indirect": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "contingency": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "total": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "scope_type": {
          "const": "Company"
        }
      },
      "required": [
        "id",
        "company",
        "project",
        "author_person",
        "author_user",
        "created_at",
        "status",
        "estimate",
        "revision_number",
        "predecessor",
        "calculation_snapshot",
        "currency",
        "pricing_date",
        "policy_version",
        "line_record_ids",
        "source_citations",
        "basis_description",
        "direct",
        "indirect",
        "contingency",
        "total",
        "scope_type"
      ],
      "additionalProperties": false
    },
    "CompanyEstCitation": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "document_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "revision_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "document_title": {
          "type": "string",
          "maxLength": 200
        },
        "revision_number": {
          "type": "integer",
          "minimum": 1
        },
        "page": {
          "type": "integer",
          "minimum": 1
        },
        "page_label": {
          "type": "string",
          "maxLength": 200
        },
        "excerpt": {
          "type": "string",
          "maxLength": 20000
        },
        "excerpt_sha256": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "source_sha256": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "scope_type": {
          "const": "Company"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "project": {
          "type": "null"
        }
      },
      "required": [
        "id",
        "document_id",
        "revision_id",
        "document_title",
        "revision_number",
        "page",
        "page_label",
        "excerpt",
        "excerpt_sha256",
        "source_sha256",
        "scope_type",
        "company",
        "project"
      ],
      "additionalProperties": false
    },
    "CompanyEstMoney": {
      "type": "object",
      "properties": {
        "amount": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,6})?$"
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        }
      },
      "required": [
        "amount",
        "currency"
      ],
      "additionalProperties": false
    },
    "CompanyEstSnapshotRecord": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "project": {
          "type": "null"
        },
        "author_person": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "author_user": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "status": {
          "type": "string"
        },
        "subject_type": {
          "const": "Cipher Estimate Revision"
        },
        "subject_id": {
          "type": "string",
          "format": "uuid"
        },
        "inputs": {
          "$ref": "#/$defs/CompanyEstCalculationInputs"
        },
        "result": {
          "$ref": "#/$defs/CompanyEstCalculationResult"
        },
        "currency_policy": {
          "type": "object",
          "properties": {
            "currency": {
              "type": "string",
              "pattern": "^[A-Z]{3}$"
            },
            "currency_exponent": {
              "type": "integer",
              "minimum": 0,
              "maximum": 6
            },
            "fraction_units": {
              "type": "integer",
              "minimum": 1
            },
            "native_currency_version": {
              "type": "string"
            }
          },
          "required": [
            "currency",
            "currency_exponent",
            "fraction_units",
            "native_currency_version"
          ],
          "additionalProperties": false
        },
        "input_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "output_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "source_citations": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstCitation"
          },
          "maxItems": 64
        },
        "scope_type": {
          "const": "Company"
        },
        "estimate": {
          "type": "string",
          "format": "uuid"
        }
      },
      "required": [
        "id",
        "company",
        "project",
        "author_person",
        "author_user",
        "created_at",
        "status",
        "subject_type",
        "subject_id",
        "inputs",
        "result",
        "currency_policy",
        "input_digest",
        "output_digest",
        "source_citations",
        "scope_type",
        "estimate"
      ],
      "additionalProperties": false
    },
    "CompanyEstCalculationInputs": {
      "type": "object",
      "properties": {
        "schema": {
          "const": "cipher.estimate.inputs.v2"
        },
        "unit_manifest": {
          "$ref": "#/$defs/CompanyEstUnitManifest"
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "currency_exponent": {
          "type": "integer",
          "minimum": 0,
          "maximum": 6
        },
        "pricing_date": {
          "type": "string",
          "format": "date"
        },
        "policy_version": {
          "const": "cipher.estimate.line-half-up.v1"
        },
        "basis_description": {
          "type": "string",
          "maxLength": 2000
        },
        "basis_citations": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstCitation"
          },
          "maxItems": 8
        },
        "rates": {
          "type": "object",
          "additionalProperties": {
            "$ref": "#/$defs/CompanyEstRateDefinition"
          },
          "maxProperties": 500
        },
        "assemblies": {
          "type": "object",
          "additionalProperties": {
            "$ref": "#/$defs/CompanyEstAssemblyDefinition"
          },
          "maxProperties": 100
        },
        "lines": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstLineInput"
          },
          "maxItems": 100
        },
        "adjustments": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstAdjustment"
          },
          "maxItems": 30
        }
      },
      "required": [
        "schema",
        "unit_manifest",
        "currency",
        "currency_exponent",
        "pricing_date",
        "policy_version",
        "basis_description",
        "basis_citations",
        "rates",
        "assemblies",
        "lines",
        "adjustments"
      ],
      "additionalProperties": false
    },
    "CompanyEstUnitManifest": {
      "type": "object",
      "properties": {
        "schema": {
          "const": "cipher.canonical.v2"
        },
        "dataset_id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        },
        "scope": {
          "type": "object",
          "properties": {
            "company": {
              "type": "string",
              "minLength": 1,
              "maxLength": 140
            },
            "project": {
              "type": "null"
            },
            "scope_type": {
              "const": "Company"
            }
          },
          "required": [
            "company",
            "project",
            "scope_type"
          ],
          "additionalProperties": false
        },
        "label": {
          "type": "string",
          "minLength": 1,
          "maxLength": 200
        },
        "records": {
          "type": "array",
          "minItems": 1,
          "maxItems": 500,
          "items": {
            "oneOf": [
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "company"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "currency": {
                        "type": "string",
                        "pattern": "^[A-Z]{3}$"
                      },
                      "timezone": {
                        "type": [
                          "string",
                          "null"
                        ],
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "name",
                      "currency",
                      "timezone"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "Company"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "project"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "status": {
                        "enum": [
                          "Open",
                          "On hold",
                          "Completed",
                          "Cancelled"
                        ]
                      },
                      "customer_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      }
                    },
                    "required": [
                      "title",
                      "company_id",
                      "status"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "Project"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "customer"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "active": {
                        "type": "boolean"
                      }
                    },
                    "required": [
                      "name",
                      "company_id",
                      "active"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "Customer"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "supplier"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "active": {
                        "type": "boolean"
                      }
                    },
                    "required": [
                      "name",
                      "company_id",
                      "active"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "Supplier"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "item"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "stock_uom_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "is_stock_item": {
                        "type": "boolean"
                      }
                    },
                    "required": [
                      "code",
                      "name",
                      "company_id",
                      "stock_uom_id",
                      "is_stock_item"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "Item"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "uom"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "symbol": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "dimension": {
                        "enum": [
                          "area",
                          "count",
                          "equipment_time",
                          "labor_time",
                          "length",
                          "mass",
                          "time",
                          "volume"
                        ]
                      },
                      "precision": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 12
                      }
                    },
                    "required": [
                      "symbol",
                      "dimension",
                      "precision"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "UOM"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "cost_center"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "is_group": {
                        "type": "boolean"
                      },
                      "parent_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      }
                    },
                    "required": [
                      "code",
                      "name",
                      "company_id",
                      "is_group"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  },
                  "target": {
                    "type": "object",
                    "properties": {
                      "doctype": {
                        "const": "Cost Center"
                      },
                      "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      }
                    },
                    "required": [
                      "doctype",
                      "name"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "cost_code"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      },
                      "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      }
                    },
                    "required": [
                      "code",
                      "title",
                      "company_id"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "cost_type"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      },
                      "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      }
                    },
                    "required": [
                      "code",
                      "title",
                      "company_id"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "id": {
                    "$ref": "#/$defs/CompanyEstCanonicaluuid"
                  },
                  "kind": {
                    "const": "accounting_dimension"
                  },
                  "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483647
                  },
                  "fields": {
                    "type": "object",
                    "properties": {
                      "code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80
                      },
                      "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "company_id": {
                        "$ref": "#/$defs/CompanyEstCanonicaluuid"
                      },
                      "value_kind": {
                        "enum": [
                          "project",
                          "cost_center",
                          "cost_code",
                          "cost_type"
                        ]
                      }
                    },
                    "required": [
                      "code",
                      "title",
                      "company_id",
                      "value_kind"
                    ],
                    "additionalProperties": false
                  },
                  "source": {
                    "type": "object",
                    "properties": {
                      "system": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "revision": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      }
                    },
                    "required": [
                      "system",
                      "record_id"
                    ],
                    "additionalProperties": false
                  }
                },
                "required": [
                  "id",
                  "kind",
                  "revision",
                  "fields"
                ],
                "additionalProperties": false
              }
            ]
          }
        },
        "unit_conversions": {
          "type": "array",
          "maxItems": 1000,
          "items": {
            "$ref": "#/$defs/CompanyEstCanonicalconversion"
          }
        },
        "quantities": {
          "type": "array",
          "maxItems": 500,
          "items": {
            "$ref": "#/$defs/CompanyEstCanonicalquantity"
          }
        }
      },
      "required": [
        "schema",
        "dataset_id",
        "scope",
        "records",
        "unit_conversions"
      ],
      "additionalProperties": false,
      "title": "Cipher independent canonical master/dimension manifest v1",
      "$comment": "Structural interchange schema. Server validator additionally enforces exact references, scoped company, reduced rational factors, conversion consistency, precision and current authorization."
    },
    "CompanyEstCanonicaluuid": {
      "type": "string",
      "format": "uuid",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "CompanyEstCanonicalconversion": {
      "type": "object",
      "properties": {
        "id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        },
        "revision": {
          "type": "integer",
          "minimum": 1,
          "maximum": 2147483647
        },
        "from_unit_id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        },
        "to_unit_id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        },
        "dimension": {
          "enum": [
            "area",
            "count",
            "equipment_time",
            "labor_time",
            "length",
            "mass",
            "time",
            "volume"
          ]
        },
        "numerator": {
          "type": "string",
          "pattern": "^[1-9][0-9]{0,24}$"
        },
        "denominator": {
          "type": "string",
          "pattern": "^[1-9][0-9]{0,24}$"
        },
        "source": {
          "type": "string",
          "minLength": 1,
          "maxLength": 200
        }
      },
      "required": [
        "id",
        "revision",
        "from_unit_id",
        "to_unit_id",
        "dimension",
        "numerator",
        "denominator",
        "source"
      ],
      "additionalProperties": false
    },
    "CompanyEstCanonicalquantity": {
      "type": "object",
      "properties": {
        "id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        },
        "amount": {
          "type": "string",
          "pattern": "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
          "maxLength": 50
        },
        "unit_id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        },
        "convert_to_unit_id": {
          "$ref": "#/$defs/CompanyEstCanonicaluuid"
        }
      },
      "required": [
        "id",
        "amount",
        "unit_id"
      ],
      "additionalProperties": false
    },
    "CompanyEstRateDefinition": {
      "type": "object",
      "properties": {
        "title": {
          "type": "string",
          "maxLength": 200
        },
        "cost_type": {
          "enum": [
            "material",
            "labor",
            "equipment",
            "subcontract",
            "other"
          ]
        },
        "unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "rate_amount": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "rate_precision": {
          "type": "integer",
          "minimum": 0,
          "maximum": 12
        },
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "quote_reference": {
          "type": "string",
          "maxLength": 200
        },
        "quote_date": {
          "type": "string",
          "format": "date"
        },
        "expiry_date": {
          "anyOf": [
            {
              "type": "string",
              "format": "date"
            },
            {
              "type": "null"
            }
          ]
        },
        "geography": {
          "type": "string",
          "maxLength": 200
        },
        "inclusions": {
          "type": "string",
          "maxLength": 2000
        },
        "exclusions": {
          "type": "string",
          "maxLength": 2000
        },
        "freight_tax_assumptions": {
          "type": "string",
          "maxLength": 2000
        },
        "permission_basis": {
          "type": "string",
          "maxLength": 2000
        },
        "source_citations": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstCitation"
          },
          "maxItems": 8
        },
        "item": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 140
            },
            {
              "type": "null"
            }
          ]
        },
        "party_type": {
          "enum": [
            null,
            "Supplier",
            "Customer"
          ]
        },
        "party": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 140
            },
            {
              "type": "null"
            }
          ]
        },
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "source_id": {
          "type": "string",
          "format": "uuid"
        },
        "revision": {
          "type": "integer",
          "minimum": 1
        },
        "predecessor": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "title",
        "cost_type",
        "unit_id",
        "rate_amount",
        "rate_precision",
        "currency",
        "quote_reference",
        "quote_date",
        "expiry_date",
        "geography",
        "inclusions",
        "exclusions",
        "freight_tax_assumptions",
        "permission_basis",
        "source_citations",
        "item",
        "party_type",
        "party",
        "id",
        "source_id",
        "revision",
        "predecessor"
      ],
      "additionalProperties": false
    },
    "CompanyEstAssemblyDefinition": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "assembly_id": {
          "type": "string",
          "format": "uuid"
        },
        "revision": {
          "type": "integer",
          "minimum": 1
        },
        "predecessor": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ]
        },
        "title": {
          "type": "string",
          "maxLength": 200
        },
        "basis_unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "components": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstAssemblyComponent"
          },
          "maxItems": 50
        },
        "author_basis": {
          "type": "string",
          "maxLength": 2000
        }
      },
      "required": [
        "id",
        "assembly_id",
        "revision",
        "predecessor",
        "title",
        "basis_unit_id",
        "components",
        "author_basis"
      ],
      "additionalProperties": false
    },
    "CompanyEstAssemblyComponent": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "rate_source_id": {
          "type": "string",
          "format": "uuid"
        },
        "kind": {
          "enum": [
            "material",
            "labor",
            "equipment",
            "subcontract",
            "other"
          ]
        },
        "work_quantity": {
          "$ref": "#/$defs/CompanyEstQuantity"
        },
        "resource_quantity": {
          "$ref": "#/$defs/CompanyEstQuantity"
        },
        "material_factor": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "waste_fraction": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        }
      },
      "required": [
        "line_id",
        "rate_source_id",
        "kind",
        "work_quantity",
        "resource_quantity",
        "material_factor",
        "waste_fraction"
      ],
      "additionalProperties": false
    },
    "CompanyEstQuantity": {
      "type": "object",
      "properties": {
        "amount": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "precision": {
          "type": "integer",
          "minimum": 0,
          "maximum": 12
        }
      },
      "required": [
        "amount",
        "unit_id",
        "precision"
      ],
      "additionalProperties": false
    },
    "CompanyEstLineInput": {
      "oneOf": [
        {
          "$ref": "#/$defs/CompanyEstDirectLine"
        },
        {
          "$ref": "#/$defs/CompanyEstAssemblyLine"
        }
      ]
    },
    "CompanyEstDirectLine": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 200
        },
        "quantity": {
          "$ref": "#/$defs/CompanyEstQuantity"
        },
        "cost_code": {
          "type": "string",
          "maxLength": 200
        },
        "notes": {
          "type": "string",
          "maxLength": 2000
        },
        "alternate": {
          "type": "string",
          "maxLength": 200
        },
        "included": {
          "type": "boolean"
        },
        "rate_source_id": {
          "type": "string",
          "format": "uuid"
        },
        "material_factor": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "waste_fraction": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        }
      },
      "required": [
        "line_id",
        "description",
        "quantity",
        "cost_code",
        "notes",
        "alternate",
        "included",
        "rate_source_id",
        "material_factor",
        "waste_fraction"
      ],
      "additionalProperties": false
    },
    "CompanyEstAssemblyLine": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 200
        },
        "quantity": {
          "$ref": "#/$defs/CompanyEstQuantity"
        },
        "cost_code": {
          "type": "string",
          "maxLength": 200
        },
        "notes": {
          "type": "string",
          "maxLength": 2000
        },
        "alternate": {
          "type": "string",
          "maxLength": 200
        },
        "included": {
          "type": "boolean"
        },
        "assembly_revision_id": {
          "type": "string",
          "format": "uuid"
        }
      },
      "required": [
        "line_id",
        "description",
        "quantity",
        "cost_code",
        "notes",
        "alternate",
        "included",
        "assembly_revision_id"
      ],
      "additionalProperties": false
    },
    "CompanyEstAdjustment": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "kind": {
          "enum": [
            "indirect",
            "contingency"
          ]
        },
        "label": {
          "type": "string",
          "maxLength": 200
        },
        "method": {
          "enum": [
            "fixed",
            "fraction_of_direct"
          ]
        },
        "value": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "basis_description": {
          "type": "string",
          "maxLength": 2000
        }
      },
      "required": [
        "line_id",
        "kind",
        "label",
        "method",
        "value",
        "basis_description"
      ],
      "additionalProperties": false
    },
    "CompanyEstCalculationResult": {
      "type": "object",
      "properties": {
        "schema": {
          "const": "cipher.estimate.result.v1"
        },
        "policy": {
          "$ref": "#/$defs/CompanyEstCalculationPolicy"
        },
        "lines": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstCalculatedLine"
          },
          "maxItems": 100
        },
        "adjustments": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstCalculatedAdjustment"
          },
          "maxItems": 30
        },
        "direct": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "indirect": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "contingency": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "total": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "conversion_references": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string",
                "format": "uuid"
              },
              "revision": {
                "type": "integer",
                "minimum": 1
              },
              "source": {
                "type": "string",
                "maxLength": 200
              },
              "numerator": {
                "type": "string"
              },
              "denominator": {
                "type": "string"
              }
            },
            "required": [
              "id",
              "revision",
              "source",
              "numerator",
              "denominator"
            ],
            "additionalProperties": false
          },
          "maxItems": 64
        },
        "input_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "output_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        }
      },
      "required": [
        "schema",
        "policy",
        "lines",
        "adjustments",
        "direct",
        "indirect",
        "contingency",
        "total",
        "conversion_references",
        "input_digest",
        "output_digest"
      ],
      "additionalProperties": false
    },
    "CompanyEstCalculationPolicy": {
      "type": "object",
      "properties": {
        "version": {
          "const": "cipher.estimate.line-half-up.v1"
        },
        "rounding_mode": {
          "const": "ROUND_HALF_UP"
        },
        "currency_exponent": {
          "type": "integer",
          "minimum": 0,
          "maximum": 6
        },
        "intermediate": {
          "const": "exact-rational"
        },
        "line_rounding": {
          "const": "sum-exact-components-then-round"
        },
        "component_allocation": {
          "const": "nonnegative-largest-remainder-tie-by-stable-component-id"
        },
        "header_rounding": {
          "const": "sum-rounded-lines"
        }
      },
      "required": [
        "version",
        "rounding_mode",
        "currency_exponent",
        "intermediate",
        "line_rounding",
        "component_allocation",
        "header_rounding"
      ],
      "additionalProperties": false
    },
    "CompanyEstCalculatedLine": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "description": {
          "type": "string",
          "maxLength": 200
        },
        "quantity": {
          "$ref": "#/$defs/CompanyEstQuantity"
        },
        "quantity_method": {
          "const": "authored"
        },
        "included": {
          "type": "boolean"
        },
        "alternate": {
          "type": "string",
          "maxLength": 200
        },
        "cost_code": {
          "type": "string",
          "maxLength": 200
        },
        "components": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/CompanyEstPricedComponent"
          },
          "maxItems": 50
        },
        "unrounded_extension": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "extension": {
          "$ref": "#/$defs/CompanyEstMoney"
        }
      },
      "required": [
        "line_id",
        "description",
        "quantity",
        "quantity_method",
        "included",
        "alternate",
        "cost_code",
        "components",
        "unrounded_extension",
        "extension"
      ],
      "additionalProperties": false
    },
    "CompanyEstPricedComponent": {
      "type": "object",
      "properties": {
        "component_id": {
          "type": "string",
          "format": "uuid"
        },
        "rate_source_id": {
          "type": "string",
          "format": "uuid"
        },
        "rate_revision": {
          "type": "integer",
          "minimum": 1
        },
        "cost_type": {
          "enum": [
            "material",
            "labor",
            "equipment",
            "subcontract",
            "other"
          ]
        },
        "source_unit_id": {
          "type": "string",
          "format": "uuid"
        },
        "resource_quantity_exact": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "priced_quantity_exact": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "material_factor": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "waste_fraction": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "unrounded_cost": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "allocated_amount": {
          "$ref": "#/$defs/CompanyEstMoney"
        },
        "rounding_increment": {
          "$ref": "#/$defs/CompanyEstMoney"
        }
      },
      "required": [
        "component_id",
        "rate_source_id",
        "rate_revision",
        "cost_type",
        "source_unit_id",
        "resource_quantity_exact",
        "priced_quantity_exact",
        "material_factor",
        "waste_fraction",
        "unrounded_cost",
        "allocated_amount",
        "rounding_increment"
      ],
      "additionalProperties": false
    },
    "CompanyEstRational": {
      "type": "object",
      "properties": {
        "numerator": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)$"
        },
        "denominator": {
          "type": "string",
          "pattern": "^[1-9][0-9]*$"
        }
      },
      "required": [
        "numerator",
        "denominator"
      ],
      "additionalProperties": false
    },
    "CompanyEstCalculatedAdjustment": {
      "type": "object",
      "properties": {
        "line_id": {
          "type": "string",
          "format": "uuid"
        },
        "kind": {
          "enum": [
            "indirect",
            "contingency"
          ]
        },
        "label": {
          "type": "string",
          "maxLength": 200
        },
        "method": {
          "enum": [
            "fixed",
            "fraction_of_direct"
          ]
        },
        "value": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]*)(\\.[0-9]{1,12})?$",
          "maxLength": 43
        },
        "basis_description": {
          "type": "string",
          "maxLength": 2000
        },
        "unrounded_amount": {
          "$ref": "#/$defs/CompanyEstRational"
        },
        "amount": {
          "$ref": "#/$defs/CompanyEstMoney"
        }
      },
      "required": [
        "line_id",
        "kind",
        "label",
        "method",
        "value",
        "basis_description",
        "unrounded_amount",
        "amount"
      ],
      "additionalProperties": false
    },
    "ComOperation": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "format": "uuid"
        },
        "status": {
          "const": "succeeded"
        },
        "replayed": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "status",
        "replayed"
      ],
      "additionalProperties": false
    }
  }
} as const;
