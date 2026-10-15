/* Generated from cipher_aec/estimating/schemas/api-company-v2.schema.json. Do not edit.
 * Source SHA-256: 458a246db2480b33db9ad21f58c2d6ea2eb44e5d6cab87f27f5347fd66c9933c
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstLineInput".
 */
export type CompanyEstLineInput = CompanyEstDirectLine | CompanyEstAssemblyLine;
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstCanonicaluuid".
 */
export type CompanyEstCanonicaluuid = string;
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstRecordResponse".
 */
export type CompanyEstRecordResponse =
  | CompanyEstConversionRecord
  | CompanyEstRateRecord
  | CompanyEstAssemblyRecord
  | CompanyEstEstimateRecord
  | CompanyEstRevisionRecord
  | CompanyEstLineRecord
  | CompanyEstSnapshotRecord
  | CompanyEstAcceptanceRecord;

/**
 * Company scope is selected only by these explicit interfaces. No placeholder Project. Existing Project v1 contracts remain unchanged.
 */
export interface ExplicitCompanyEstimatingCanonicalAPI {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstQuantity".
 */
export interface CompanyEstQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstCitationReference".
 */
export interface CompanyEstCitationReference {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256?: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstConversionDefinition".
 */
export interface CompanyEstConversionDefinition {
  from_unit_id: string;
  to_unit_id: string;
  dimension: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
  numerator: string;
  denominator: string;
  source: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstRateInput".
 */
export interface CompanyEstRateInput {
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
  source_citations:
    | []
    | [CompanyEstCitationReference]
    | [CompanyEstCitationReference, CompanyEstCitationReference]
    | [CompanyEstCitationReference, CompanyEstCitationReference, CompanyEstCitationReference]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ];
  item?: string | null;
  party_type?: null | "Supplier" | "Customer";
  party?: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
  source_citations:
    | []
    | [CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation, CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation, CompanyEstCitation, CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation, CompanyEstCitation, CompanyEstCitation, CompanyEstCitation]
    | [
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation
      ]
    | [
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation
      ]
    | [
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation
      ];
  item: string | null;
  party_type: null | "Supplier" | "Customer";
  party: string | null;
  id: string;
  source_id: string;
  revision: number;
  predecessor: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstMoney".
 */
export interface CompanyEstMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstRational".
 */
export interface CompanyEstRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstCanonicalquantity".
 */
export interface CompanyEstCanonicalquantity {
  id: CompanyEstCanonicaluuid;
  amount: string;
  unit_id: CompanyEstCanonicaluuid;
  convert_to_unit_id?: CompanyEstCanonicaluuid;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
  records: [
    (
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
    ),
    ...(
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
    )[]
  ];
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
  basis_citations:
    | []
    | [CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation, CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation, CompanyEstCitation, CompanyEstCitation]
    | [CompanyEstCitation, CompanyEstCitation, CompanyEstCitation, CompanyEstCitation, CompanyEstCitation]
    | [
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation
      ]
    | [
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation
      ]
    | [
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation,
        CompanyEstCitation
      ];
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstConversionRecord".
 */
export interface CompanyEstConversionRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  definition: {
    from_unit_id: string;
    to_unit_id: string;
    dimension: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
    numerator: string;
    denominator: string;
    source: string;
    id: string;
    revision: number;
  };
  predecessor: string | null;
  /**
   * @maxItems 64
   */
  source_citations: CompanyEstCitation[];
  permission_basis: string;
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  scope_type: "Company";
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstRateRecord".
 */
export interface CompanyEstRateRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  rate: CompanyEstRateDefinition;
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  /**
   * @maxItems 64
   */
  source_citations: CompanyEstCitation[];
  scope_type: "Company";
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstAssemblyRecord".
 */
export interface CompanyEstAssemblyRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  assembly: CompanyEstAssemblyDefinition;
  rates: {
    [k: string]: CompanyEstRateDefinition;
  };
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  /**
   * @maxItems 64
   */
  source_citations: CompanyEstCitation[];
  scope_type: "Company";
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstLineRecord".
 */
export interface CompanyEstLineRecord {
  id: string;
  company: string;
  project: null;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  estimate: string;
  estimate_revision: string;
  line_id: string;
  authored: CompanyEstLineInput;
  calculated: CompanyEstCalculatedLine;
  scope_type: "Company";
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstAcceptanceScope".
 */
export interface CompanyEstAcceptanceScope {
  company: string;
  project: null;
  scope_type: "Company";
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstPinnedRecord".
 */
export interface CompanyEstPinnedRecord {
  kind: "rate" | "assembly" | "conversion";
  id: string;
  digest: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstNativeReference".
 */
export interface CompanyEstNativeReference {
  doctype: "Item" | "Supplier" | "Customer" | "Lead" | "Opportunity";
  name: string;
  version: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
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
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstListResponse".
 */
export interface CompanyEstListResponse {
  /**
   * @maxItems 200
   */
  items: CompanyEstRecordResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstOperation".
 */
export interface CompanyEstOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyRegisterUnitRequest".
 */
export interface CompanyRegisterUnitRequest {
  company: string;
  operation_id?: string;
  uom: string;
  dimension: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
  quantity_precision: number;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateConversionRequest".
 */
export interface CompanyCreateConversionRequest {
  company: string;
  operation_id?: string;
  definition: CompanyEstConversionDefinition;
  /**
   * @maxItems 8
   */
  source_citations:
    | []
    | [CompanyEstCitationReference]
    | [CompanyEstCitationReference, CompanyEstCitationReference]
    | [CompanyEstCitationReference, CompanyEstCitationReference, CompanyEstCitationReference]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ];
  permission_basis: string;
  predecessor?: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateRateRequest".
 */
export interface CompanyCreateRateRequest {
  company: string;
  operation_id?: string;
  rate: CompanyEstRateInput;
  predecessor?: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateAssemblyRequest".
 */
export interface CompanyCreateAssemblyRequest {
  company: string;
  operation_id?: string;
  title: string;
  basis_unit_id: string;
  /**
   * @maxItems 50
   */
  components: CompanyEstAssemblyComponent[];
  author_basis: string;
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  predecessor?: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateEstimateRequest".
 */
export interface CompanyCreateEstimateRequest {
  company: string;
  operation_id?: string;
  title: string;
  currency: string;
  pricing_date: string;
  pursuit_id?: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCalculateRevisionRequest".
 */
export interface CompanyCalculateRevisionRequest {
  company: string;
  operation_id?: string;
  estimate_id: string;
  expected_revision: string | null;
  /**
   * @maxItems 100
   */
  lines: CompanyEstLineInput[];
  /**
   * @maxItems 30
   */
  adjustments: CompanyEstAdjustment[];
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  basis_description: string;
  /**
   * @maxItems 8
   */
  basis_citations:
    | []
    | [CompanyEstCitationReference]
    | [CompanyEstCitationReference, CompanyEstCitationReference]
    | [CompanyEstCitationReference, CompanyEstCitationReference, CompanyEstCitationReference]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ]
    | [
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference,
        CompanyEstCitationReference
      ];
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyGetEstimateRecordRequest".
 */
export interface CompanyGetEstimateRecordRequest {
  company: string;
  kind: "conversion" | "rate" | "assembly" | "estimate" | "revision" | "line" | "snapshot" | "acceptance";
  record_id: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyListEstimateRecordsRequest".
 */
export interface CompanyListEstimateRecordsRequest {
  company: string;
  kind: "conversion" | "rate" | "assembly" | "estimate";
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyListEstimateUnitsRequest".
 */
export interface CompanyListEstimateUnitsRequest {
  company: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyRegisterUnitResponse".
 */
export interface CompanyRegisterUnitResponse {
  unit: CompanyEstUnitRecord;
  operation: CompanyEstOperation;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateConversionResponse".
 */
export interface CompanyCreateConversionResponse {
  conversion: CompanyEstConversionRecord;
  history_id: string;
  operation: CompanyEstOperation;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateRateResponse".
 */
export interface CompanyCreateRateResponse {
  rate_source: CompanyEstRateRecord;
  history_id: string;
  operation: CompanyEstOperation;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateAssemblyResponse".
 */
export interface CompanyCreateAssemblyResponse {
  assembly_revision: CompanyEstAssemblyRecord;
  history_id: string;
  operation: CompanyEstOperation;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCreateEstimateResponse".
 */
export interface CompanyCreateEstimateResponse {
  estimate: CompanyEstEstimateRecord;
  history_id: string;
  operation: CompanyEstOperation;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyCalculateRevisionResponse".
 */
export interface CompanyCalculateRevisionResponse {
  estimate: CompanyEstEstimateRecord;
  revision: CompanyEstRevisionRecord;
  calculation: CompanyEstSnapshotRecord;
  history_id: string;
  operation: CompanyEstOperation;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyListEstimateUnitsResponse".
 */
export interface CompanyListEstimateUnitsResponse {
  /**
   * @maxItems 200
   */
  items: CompanyEstUnitRecord[];
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyListEstimateAcceptancesRequest".
 */
export interface CompanyListEstimateAcceptancesRequest {
  company: string;
  estimate_id: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyListEstimateAcceptancesResponse".
 */
export interface CompanyListEstimateAcceptancesResponse {
  /**
   * @maxItems 200
   */
  items: CompanyEstAcceptanceRecord[];
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstimateAcceptanceSubjectRequest".
 */
export interface CompanyEstimateAcceptanceSubjectRequest {
  company: string;
  revision_id: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyEstimateAcceptanceSubjectResponse".
 */
export interface CompanyEstimateAcceptanceSubjectResponse {
  revision_id: string;
  record_digest: string;
  estimate_id: string;
  is_current: boolean;
  current_revision: string | null;
  accepted_baseline_id: string | null;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyAcceptedBaselineReferenceRequest".
 */
export interface CompanyAcceptedBaselineReferenceRequest {
  company: string;
  acceptance_id: string;
}
/**
 * This interface was referenced by `ExplicitCompanyEstimatingCanonicalAPI`'s JSON-Schema
 * via the `definition` "CompanyAcceptedBaselineReferenceResponse".
 */
export interface CompanyAcceptedBaselineReferenceResponse {
  acceptance_id: string;
  acceptance_digest: string;
  estimate_id: string;
  revision_id: string;
  revision_digest: string;
  snapshot_id: string;
  snapshot_digest: string;
  manifest_digest: string;
  pursuit_id: string | null;
  currency: string;
  total: CompanyEstMoney;
}
