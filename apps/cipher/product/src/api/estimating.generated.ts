/* Generated from cipher_aec/estimating/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 8c5296687071ef33395322460562f73c78f03277fe64c0037e1dc41d7e4ea119
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstLineInput".
 */
export type EstLineInput = EstDirectLine | EstAssemblyLine;
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCanonicaluuid".
 */
export type EstCanonicaluuid = string;
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstRecordResponse".
 */
export type EstRecordResponse =
  | EstConversionRecord
  | EstRateRecord
  | EstAssemblyRecord
  | EstEstimateRecord
  | EstRevisionRecord
  | EstLineRecord
  | EstSnapshotRecord;

/**
 * Request fields are closed. POST operation_id may be supplied by the required Idempotency-Key header. Inputs are authored quantities, never calibrated geometry. Sources remain subject to current project/document access. Permission basis is an authored assertion, not a derived license entitlement. No estimate acceptance or external provider action is exposed.
 */
export interface CipherEST01AuthoredExactDraftEstimating {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstQuantity".
 */
export interface EstQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCitationReference".
 */
export interface EstCitationReference {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256?: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCitation".
 */
export interface EstCitation {
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
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstConversionDefinition".
 */
export interface EstConversionDefinition {
  from_unit_id: string;
  to_unit_id: string;
  dimension: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
  numerator: string;
  denominator: string;
  source: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstRateInput".
 */
export interface EstRateInput {
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
    | [EstCitationReference]
    | [EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ];
  item?: string | null;
  party_type?: null | "Supplier" | "Customer";
  party?: string | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstRateDefinition".
 */
export interface EstRateDefinition {
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
    | [EstCitation]
    | [EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation];
  item: string | null;
  party_type: null | "Supplier" | "Customer";
  party: string | null;
  id: string;
  source_id: string;
  revision: number;
  predecessor: string | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstAssemblyComponent".
 */
export interface EstAssemblyComponent {
  line_id: string;
  rate_source_id: string;
  kind: "material" | "labor" | "equipment" | "subcontract" | "other";
  work_quantity: EstQuantity;
  resource_quantity: EstQuantity;
  material_factor: string;
  waste_fraction: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstAssemblyDefinition".
 */
export interface EstAssemblyDefinition {
  id: string;
  assembly_id: string;
  revision: number;
  predecessor: string | null;
  title: string;
  basis_unit_id: string;
  /**
   * @maxItems 50
   */
  components: EstAssemblyComponent[];
  author_basis: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
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
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
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
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
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
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstMoney".
 */
export interface EstMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstRational".
 */
export interface EstRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstPricedComponent".
 */
export interface EstPricedComponent {
  component_id: string;
  rate_source_id: string;
  rate_revision: number;
  cost_type: "material" | "labor" | "equipment" | "subcontract" | "other";
  source_unit_id: string;
  resource_quantity_exact: EstRational;
  priced_quantity_exact: EstRational;
  material_factor: EstRational;
  waste_fraction: EstRational;
  unrounded_cost: EstRational;
  allocated_amount: EstMoney;
  rounding_increment: EstMoney;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCalculatedLine".
 */
export interface EstCalculatedLine {
  line_id: string;
  description: string;
  quantity: EstQuantity;
  quantity_method: "authored";
  included: boolean;
  alternate: string;
  cost_code: string;
  /**
   * @maxItems 50
   */
  components: EstPricedComponent[];
  unrounded_extension: EstRational;
  extension: EstMoney;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCalculatedAdjustment".
 */
export interface EstCalculatedAdjustment {
  line_id: string;
  kind: "indirect" | "contingency";
  label: string;
  method: "fixed" | "fraction_of_direct";
  value: string;
  basis_description: string;
  unrounded_amount: EstRational;
  amount: EstMoney;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCalculationPolicy".
 */
export interface EstCalculationPolicy {
  version: "cipher.estimate.line-half-up.v1";
  rounding_mode: "ROUND_HALF_UP";
  currency_exponent: number;
  intermediate: "exact-rational";
  line_rounding: "sum-exact-components-then-round";
  component_allocation: "nonnegative-largest-remainder-tie-by-stable-component-id";
  header_rounding: "sum-rounded-lines";
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCalculationResult".
 */
export interface EstCalculationResult {
  schema: "cipher.estimate.result.v1";
  policy: EstCalculationPolicy;
  /**
   * @maxItems 100
   */
  lines: EstCalculatedLine[];
  /**
   * @maxItems 30
   */
  adjustments: EstCalculatedAdjustment[];
  direct: EstMoney;
  indirect: EstMoney;
  contingency: EstMoney;
  total: EstMoney;
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
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCanonicalconversion".
 */
export interface EstCanonicalconversion {
  id: EstCanonicaluuid;
  revision: number;
  from_unit_id: EstCanonicaluuid;
  to_unit_id: EstCanonicaluuid;
  dimension: "area" | "count" | "equipment_time" | "labor_time" | "length" | "mass" | "time" | "volume";
  numerator: string;
  denominator: string;
  source: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCanonicalquantity".
 */
export interface EstCanonicalquantity {
  id: EstCanonicaluuid;
  amount: string;
  unit_id: EstCanonicaluuid;
  convert_to_unit_id?: EstCanonicaluuid;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstUnitManifest".
 */
export interface CipherIndependentCanonicalMasterDimensionManifestV1 {
  schema: "cipher.canonical.v1";
  dataset_id: EstCanonicaluuid;
  scope: {
    company: string;
    project: string;
  };
  label?: string;
  /**
   * @minItems 1
   * @maxItems 500
   */
  records: [
    (
      | {
          id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "project";
          revision: number;
          fields: {
            title: string;
            company_id: EstCanonicaluuid;
            status: "Open" | "On hold" | "Completed" | "Cancelled";
            customer_id?: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "customer";
          revision: number;
          fields: {
            name: string;
            company_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "supplier";
          revision: number;
          fields: {
            name: string;
            company_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "item";
          revision: number;
          fields: {
            code: string;
            name: string;
            company_id: EstCanonicaluuid;
            stock_uom_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "cost_center";
          revision: number;
          fields: {
            code: string;
            name: string;
            company_id: EstCanonicaluuid;
            is_group: boolean;
            parent_id?: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "cost_code";
          revision: number;
          fields: {
            code: string;
            title: string;
            company_id: EstCanonicaluuid;
          };
          source?: {
            system: string;
            record_id: string;
            revision?: string;
          };
        }
      | {
          id: EstCanonicaluuid;
          kind: "cost_type";
          revision: number;
          fields: {
            code: string;
            title: string;
            company_id: EstCanonicaluuid;
          };
          source?: {
            system: string;
            record_id: string;
            revision?: string;
          };
        }
      | {
          id: EstCanonicaluuid;
          kind: "accounting_dimension";
          revision: number;
          fields: {
            code: string;
            title: string;
            company_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "project";
          revision: number;
          fields: {
            title: string;
            company_id: EstCanonicaluuid;
            status: "Open" | "On hold" | "Completed" | "Cancelled";
            customer_id?: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "customer";
          revision: number;
          fields: {
            name: string;
            company_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "supplier";
          revision: number;
          fields: {
            name: string;
            company_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "item";
          revision: number;
          fields: {
            code: string;
            name: string;
            company_id: EstCanonicaluuid;
            stock_uom_id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "cost_center";
          revision: number;
          fields: {
            code: string;
            name: string;
            company_id: EstCanonicaluuid;
            is_group: boolean;
            parent_id?: EstCanonicaluuid;
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
          id: EstCanonicaluuid;
          kind: "cost_code";
          revision: number;
          fields: {
            code: string;
            title: string;
            company_id: EstCanonicaluuid;
          };
          source?: {
            system: string;
            record_id: string;
            revision?: string;
          };
        }
      | {
          id: EstCanonicaluuid;
          kind: "cost_type";
          revision: number;
          fields: {
            code: string;
            title: string;
            company_id: EstCanonicaluuid;
          };
          source?: {
            system: string;
            record_id: string;
            revision?: string;
          };
        }
      | {
          id: EstCanonicaluuid;
          kind: "accounting_dimension";
          revision: number;
          fields: {
            code: string;
            title: string;
            company_id: EstCanonicaluuid;
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
  unit_conversions: EstCanonicalconversion[];
  /**
   * @maxItems 500
   */
  quantities?: EstCanonicalquantity[];
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstCalculationInputs".
 */
export interface EstCalculationInputs {
  schema: "cipher.estimate.inputs.v1";
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
    | [EstCitation]
    | [EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation];
  rates: {
    [k: string]: EstRateDefinition;
  };
  assemblies: {
    [k: string]: EstAssemblyDefinition;
  };
  /**
   * @maxItems 100
   */
  lines: EstLineInput[];
  /**
   * @maxItems 30
   */
  adjustments: EstAdjustment[];
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstUnitRecord".
 */
export interface EstUnitRecord {
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
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstConversionRecord".
 */
export interface EstConversionRecord {
  id: string;
  company: string;
  project: string;
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
  source_citations: EstCitation[];
  permission_basis: string;
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstRateRecord".
 */
export interface EstRateRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  rate: EstRateDefinition;
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  /**
   * @maxItems 64
   */
  source_citations: EstCitation[];
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstAssemblyRecord".
 */
export interface EstAssemblyRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  assembly: EstAssemblyDefinition;
  rates: {
    [k: string]: EstRateDefinition;
  };
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  /**
   * @maxItems 64
   */
  source_citations: EstCitation[];
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstEstimateRecord".
 */
export interface EstEstimateRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  title: string;
  currency: string;
  pricing_date: string;
  revision_number: number;
  current_revision: string | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstRevisionRecord".
 */
export interface EstRevisionRecord {
  id: string;
  company: string;
  project: string;
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
  source_citations: EstCitation[];
  basis_description: string;
  direct: EstMoney;
  indirect: EstMoney;
  contingency: EstMoney;
  total: EstMoney;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstLineRecord".
 */
export interface EstLineRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  estimate: string;
  estimate_revision: string;
  line_id: string;
  authored: EstLineInput;
  calculated: EstCalculatedLine;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstSnapshotRecord".
 */
export interface EstSnapshotRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  subject_type: "Cipher Estimate Revision";
  subject_id: string;
  inputs: EstCalculationInputs;
  result: EstCalculationResult;
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
  source_citations: EstCitation[];
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstListResponse".
 */
export interface EstListResponse {
  /**
   * @maxItems 200
   */
  items: EstRecordResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "EstOperation".
 */
export interface EstOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "RegisterUnitRequest".
 */
export interface RegisterUnitRequest {
  company: string;
  project: string;
  operation_id?: string;
  uom: string;
  dimension: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
  quantity_precision: number;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateConversionRequest".
 */
export interface CreateConversionRequest {
  company: string;
  project: string;
  operation_id?: string;
  definition: EstConversionDefinition;
  /**
   * @maxItems 8
   */
  source_citations:
    | []
    | [EstCitationReference]
    | [EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ];
  permission_basis: string;
  predecessor?: string | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateRateRequest".
 */
export interface CreateRateRequest {
  company: string;
  project: string;
  operation_id?: string;
  rate: EstRateInput;
  predecessor?: string | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateAssemblyRequest".
 */
export interface CreateAssemblyRequest {
  company: string;
  project: string;
  operation_id?: string;
  title: string;
  basis_unit_id: string;
  /**
   * @maxItems 50
   */
  components: EstAssemblyComponent[];
  author_basis: string;
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  predecessor?: string | null;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateEstimateRequest".
 */
export interface CreateEstimateRequest {
  company: string;
  project: string;
  operation_id?: string;
  title: string;
  currency: string;
  pricing_date: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CalculateRevisionRequest".
 */
export interface CalculateRevisionRequest {
  company: string;
  project: string;
  operation_id?: string;
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
  basis_citations:
    | []
    | [EstCitationReference]
    | [EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference]
    | [EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference, EstCitationReference]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ]
    | [
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference,
        EstCitationReference
      ];
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "GetEstimateRecordRequest".
 */
export interface GetEstimateRecordRequest {
  company: string;
  project: string;
  kind: "conversion" | "rate" | "assembly" | "estimate" | "revision" | "line" | "snapshot";
  record_id: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "ListEstimateRecordsRequest".
 */
export interface ListEstimateRecordsRequest {
  company: string;
  project: string;
  kind: "conversion" | "rate" | "assembly" | "estimate";
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "ListEstimateUnitsRequest".
 */
export interface ListEstimateUnitsRequest {
  company: string;
  project: string;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "RegisterUnitResponse".
 */
export interface RegisterUnitResponse {
  unit: EstUnitRecord;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateConversionResponse".
 */
export interface CreateConversionResponse {
  conversion: EstConversionRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateRateResponse".
 */
export interface CreateRateResponse {
  rate_source: EstRateRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateAssemblyResponse".
 */
export interface CreateAssemblyResponse {
  assembly_revision: EstAssemblyRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CreateEstimateResponse".
 */
export interface CreateEstimateResponse {
  estimate: EstEstimateRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "CalculateRevisionResponse".
 */
export interface CalculateRevisionResponse {
  estimate: EstEstimateRecord;
  revision: EstRevisionRecord;
  calculation: EstSnapshotRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST01AuthoredExactDraftEstimating`'s JSON-Schema
 * via the `definition` "ListEstimateUnitsResponse".
 */
export interface ListEstimateUnitsResponse {
  /**
   * @maxItems 200
   */
  items: EstUnitRecord[];
}
