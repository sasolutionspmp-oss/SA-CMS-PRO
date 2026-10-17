/* Generated from cipher_aec/takeoff/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: a1a3dd44be6dde4ede9919d1a30c94c1956e20b717a82a1eab6d303c3ed7fa57
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstLineInput".
 */
export type EstLineInput = EstDirectLine | EstAssemblyLine;
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstCanonicaluuid".
 */
export type EstCanonicaluuid = string;
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstRecordResponse".
 */
export type EstRecordResponse =
  | EstConversionRecord
  | EstRateRecord
  | EstAssemblyRecord
  | EstEstimateRecord
  | EstRevisionRecord
  | EstLineRecord
  | EstSnapshotRecord
  | EstAcceptanceRecord;
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffMeasurementDefinition".
 */
export type TakeoffMeasurementDefinition =
  | {
      method: "manual";
      kind: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
      locator: string;
      reason: string;
      result_unit_id: string;
      result_precision: number;
      /**
       * Absolute arithmetic interval tolerance in the selected output unit.
       */
      tolerance: string;
      waste_fraction: string;
      formula_version: "cipher.takeoff.planar.v1";
      manual_quantity: EstQuantity;
    }
  | {
      method: "calibrated";
      kind: "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
      locator: string;
      reason: string;
      result_unit_id: string;
      result_precision: number;
      /**
       * Absolute arithmetic interval tolerance in the selected output unit.
       */
      tolerance: string;
      waste_fraction: string;
      formula_version: "cipher.takeoff.planar.v1";
      calibration_id: string;
      geometry: {
        type: "segment" | "polyline" | "rectangle" | "polygon";
        /**
         * @minItems 2
         * @maxItems 128
         */
        points: [[string, string], [string, string], ...[string, string][]];
      };
      depth: EstQuantity | null;
    };

export interface CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstQuantity".
 */
export interface EstQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstCitationReference".
 */
export interface EstCitationReference {
  revision_id: string;
  page: number;
  excerpt_sha256: string;
  source_sha256?: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstMoney".
 */
export interface EstMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstRational".
 */
export interface EstRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstCanonicalquantity".
 */
export interface EstCanonicalquantity {
  id: EstCanonicaluuid;
  amount: string;
  unit_id: EstCanonicaluuid;
  convert_to_unit_id?: EstCanonicaluuid;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstAcceptanceRecord".
 */
export interface EstAcceptanceRecord {
  id: string;
  company: string;
  project: string;
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
  manifest: EstAcceptanceManifest;
  manifest_digest: string;
  accepted_result: EstCalculationResult;
  currency: string;
  total: EstMoney;
  /**
   * @maxItems 64
   */
  source_citations: EstCitation[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstAcceptanceManifest".
 */
export interface EstAcceptanceManifest {
  subject: {
    doctype: "Cipher Estimate Revision";
    name: string;
    label: string;
  };
  /**
   * @maxItems 64
   */
  sources: EstCitation[];
  effect: {
    action: "estimate.accept.v1";
    revision_id: string;
    facts: EstAcceptanceFacts;
  };
  summary: {
    total: EstMoney;
    currency: string;
    rounding_policy: "cipher.estimate.line-half-up.v1";
    binding_count: number;
    independent_acceptance_required: true;
  };
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstAcceptanceFacts".
 */
export interface EstAcceptanceFacts {
  policy: "cipher.estimate.acceptance-facts.v1";
  scope: EstAcceptanceScope;
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
  pinned_records: EstPinnedRecord[];
  /**
   * @maxItems 200
   */
  qualified_units: EstUnitRecord[];
  currency_policy: {
    currency: string;
    currency_exponent: number;
    fraction_units: number;
    native_currency_version: string;
  };
  /**
   * @maxItems 700
   */
  native_references: EstNativeReference[];
  pursuit: EstPursuitPlan | null;
  /**
   * @maxItems 200
   */
  bindings: EstAcceptanceBinding[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstAcceptanceScope".
 */
export interface EstAcceptanceScope {
  company: string;
  project: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstPinnedRecord".
 */
export interface EstPinnedRecord {
  kind: "rate" | "assembly" | "conversion";
  id: string;
  digest: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstNativeReference".
 */
export interface EstNativeReference {
  doctype: "Item" | "Supplier" | "Customer" | "Lead" | "Opportunity";
  name: string;
  version: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstPursuitPlan".
 */
export interface EstPursuitPlan {
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstAcceptanceBinding".
 */
export interface EstAcceptanceBinding {
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstOperation".
 */
export interface EstOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "GetEstimateRecordRequest".
 */
export interface GetEstimateRecordRequest {
  company: string;
  project: string;
  kind: "conversion" | "rate" | "assembly" | "estimate" | "revision" | "line" | "snapshot" | "acceptance";
  record_id: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "ListEstimateUnitsRequest".
 */
export interface ListEstimateUnitsRequest {
  company: string;
  project: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "RegisterUnitResponse".
 */
export interface RegisterUnitResponse {
  unit: EstUnitRecord;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "CreateConversionResponse".
 */
export interface CreateConversionResponse {
  conversion: EstConversionRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "CreateRateResponse".
 */
export interface CreateRateResponse {
  rate_source: EstRateRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "CreateAssemblyResponse".
 */
export interface CreateAssemblyResponse {
  assembly_revision: EstAssemblyRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "CreateEstimateResponse".
 */
export interface CreateEstimateResponse {
  estimate: EstEstimateRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "ListEstimateUnitsResponse".
 */
export interface ListEstimateUnitsResponse {
  /**
   * @maxItems 200
   */
  items: EstUnitRecord[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffSourceInput".
 */
export interface TakeoffSourceInput {
  revision_id: string;
  source_sha256: string;
  page: number;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffSource".
 */
export interface TakeoffSource {
  document_id: string;
  revision_id: string;
  revision_number: number;
  current_revision: string;
  current_revision_number: number;
  is_current: boolean;
  page: number;
  page_count: number;
  mime_type: "application/pdf" | "text/plain";
  source_sha256: string;
  byte_length: number;
  extraction_status: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffPageGeometry".
 */
export interface TakeoffPageGeometry {
  coordinate_system: "pdf-user-space-v1";
  /**
   * @minItems 4
   * @maxItems 4
   */
  media_box: [string, string, string, string];
  /**
   * @minItems 4
   * @maxItems 4
   */
  crop_box: [string, string, string, string];
  rotate: 0 | 90 | 180 | 270;
  user_unit: "1";
  parser: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffDerivedUnitInput".
 */
export interface TakeoffDerivedUnitInput {
  output_unit_id: string;
  power: 2 | 3;
  numerator: string;
  denominator: string;
  basis: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  source_citations:
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
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCalibrationDefinitionInput".
 */
export interface TakeoffCalibrationDefinitionInput {
  title: string;
  coordinate_system: "pdf-user-space-v1";
  /**
   * @minItems 2
   * @maxItems 2
   */
  anchors: [[string, string], [string, string]];
  known_distance: EstQuantity;
  /**
   * Dimensionless maximum arithmetic interval width divided by the upper quantity bound; not survey uncertainty.
   */
  relative_numeric_tolerance: string;
  /**
   * @maxItems 16
   */
  derived_units:
    | []
    | [TakeoffDerivedUnitInput]
    | [TakeoffDerivedUnitInput, TakeoffDerivedUnitInput]
    | [TakeoffDerivedUnitInput, TakeoffDerivedUnitInput, TakeoffDerivedUnitInput]
    | [TakeoffDerivedUnitInput, TakeoffDerivedUnitInput, TakeoffDerivedUnitInput, TakeoffDerivedUnitInput]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ]
    | [
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput,
        TakeoffDerivedUnitInput
      ];
  basis: string;
  formula_version: "cipher.takeoff.planar.v1";
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffDerivedUnit".
 */
export interface TakeoffDerivedUnit {
  output_unit_id: string;
  power: 2 | 3;
  numerator: string;
  denominator: string;
  basis: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  source_citations:
    | [EstCitation]
    | [EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation]
    | [EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation, EstCitation];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCalibrationDefinition".
 */
export interface TakeoffCalibrationDefinition {
  title: string;
  coordinate_system: "pdf-user-space-v1";
  /**
   * @minItems 2
   * @maxItems 2
   */
  anchors: [[string, string], [string, string]];
  known_distance: EstQuantity;
  /**
   * Dimensionless maximum arithmetic interval width divided by the upper quantity bound; not survey uncertainty.
   */
  relative_numeric_tolerance: string;
  /**
   * @maxItems 16
   */
  derived_units:
    | []
    | [TakeoffDerivedUnit]
    | [TakeoffDerivedUnit, TakeoffDerivedUnit]
    | [TakeoffDerivedUnit, TakeoffDerivedUnit, TakeoffDerivedUnit]
    | [TakeoffDerivedUnit, TakeoffDerivedUnit, TakeoffDerivedUnit, TakeoffDerivedUnit]
    | [TakeoffDerivedUnit, TakeoffDerivedUnit, TakeoffDerivedUnit, TakeoffDerivedUnit, TakeoffDerivedUnit]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ]
    | [
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit,
        TakeoffDerivedUnit
      ];
  basis: string;
  formula_version: "cipher.takeoff.planar.v1";
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffInterval".
 */
export interface TakeoffInterval {
  lower: EstRational;
  upper: EstRational;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffMeasurementResult".
 */
export interface TakeoffMeasurementResult {
  formula_version: "cipher.takeoff.planar.v1";
  method: "manual" | "calibrated";
  geometry_kind: "manual" | "segment" | "polyline" | "rectangle" | "polygon";
  quantity: EstQuantity;
  raw_interval: TakeoffInterval;
  result_interval: TakeoffInterval;
  tolerance: string;
  rounding: "half_up_unique_interval";
  waste_fraction: string;
  calibration_claim: "none-manual" | "independently-verified-source-bound-planar";
  result_digest: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffSetRecord".
 */
export interface TakeoffSetRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  title: string;
  discipline: string;
  drawing_package: string;
  basis: string;
  supported_method: "authored-manual-and-verified-pdf-planar-v1";
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCalibrationRecord".
 */
export interface TakeoffCalibrationRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  takeoff_set: string;
  family_id: string;
  revision_number: number;
  predecessor: string | null;
  source: TakeoffSource;
  source_head_policy: "current-working-revision-v1";
  definition: TakeoffCalibrationDefinition;
  page_geometry: TakeoffPageGeometry;
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  /**
   * @maxItems 64
   */
  source_citations: EstCitation[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffVerificationRecord".
 */
export interface TakeoffVerificationRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  calibration_id: string;
  calibration_digest: string;
  packet_id: string;
  decision_id: string;
  verified_by_person: string;
  source: TakeoffSource;
  page_geometry_digest: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffMeasurementRecord".
 */
export interface TakeoffMeasurementRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  takeoff_set: string;
  family_id: string;
  revision_number: number;
  predecessor: string | null;
  source: TakeoffSource;
  source_head_policy: "current-working-revision-v1";
  definition: TakeoffMeasurementDefinition;
  calibration_id: string | null;
  calibration_digest: string | null;
  verification_id: string | null;
  page_geometry: TakeoffPageGeometry | null;
  unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1;
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  result: TakeoffMeasurementResult;
  /**
   * @maxItems 64
   */
  source_citations?: EstCitation[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffBindingRecord".
 */
export interface TakeoffBindingRecord {
  id: string;
  company: string;
  project: string;
  author_person: string;
  author_user: string;
  created_at: string;
  status: string;
  measurement_id: string;
  measurement_digest: string;
  estimate_line_record: string;
  estimate: string;
  estimate_revision: string;
  line_id: string;
  estimate_line_digest: string;
  quantity: EstQuantity;
  reason: string;
  quantity_basis: "net-quantity-v1" | "after-takeoff-waste-v1";
  waste_policy: "takeoff-waste-only-v1" | "net-takeoff-estimate-component-waste-v1";
  provenance: "subsequently-attached-takeoff-evidence-v1";
  original_snapshot_claim: "authored-quantity-not-recomputed";
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCurrentUse".
 */
export interface TakeoffCurrentUse {
  eligible: boolean;
  /**
   * @maxItems 8
   */
  reasons:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  current_working_revision: string;
  head_policy: "current-working-revision-v1";
  original_record_preserved: true;
  verification?: {
    id: string;
    verified_by_person: string;
  } | null;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffGetResponse".
 */
export interface TakeoffGetResponse {
  record:
    | TakeoffSetRecord
    | TakeoffCalibrationRecord
    | TakeoffVerificationRecord
    | TakeoffMeasurementRecord
    | TakeoffBindingRecord;
  record_digest: string;
  current_use?: TakeoffCurrentUse;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCreateSetRequest".
 */
export interface TakeoffCreateSetRequest {
  company: string;
  project: string;
  operation_id?: string;
  title: string;
  discipline: string;
  drawing_package: string;
  basis: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCreateCalibrationRequest".
 */
export interface TakeoffCreateCalibrationRequest {
  company: string;
  project: string;
  operation_id?: string;
  takeoff_set: string;
  source: TakeoffSourceInput;
  definition: TakeoffCalibrationDefinitionInput;
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  predecessor?: string | null;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCreateMeasurementRequest".
 */
export interface TakeoffCreateMeasurementRequest {
  company: string;
  project: string;
  operation_id?: string;
  takeoff_set: string;
  source: TakeoffSourceInput;
  definition: TakeoffMeasurementDefinition;
  /**
   * @maxItems 64
   */
  conversion_ids: string[];
  predecessor?: string | null;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffBindLineRequest".
 */
export interface TakeoffBindLineRequest {
  company: string;
  project: string;
  operation_id?: string;
  measurement_id: string;
  estimate_line_record: string;
  quantity_basis: "net-quantity-v1" | "after-takeoff-waste-v1";
  reason: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffGetRequest".
 */
export interface TakeoffGetRequest {
  company: string;
  project: string;
  kind: "set" | "calibration" | "verification" | "measurement" | "binding";
  record_id: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffListRequest".
 */
export interface TakeoffListRequest {
  company: string;
  project: string;
  kind: "set" | "calibration" | "measurement" | "binding";
  takeoff_set?: string | null;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffImpactRequest".
 */
export interface TakeoffImpactRequest {
  company: string;
  project: string;
  revision_id: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCompareRequest".
 */
export interface TakeoffCompareRequest {
  company: string;
  project: string;
  before_id: string;
  after_id: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCreateSetResponse".
 */
export interface TakeoffCreateSetResponse {
  takeoff_set: TakeoffSetRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCreateCalibrationResponse".
 */
export interface TakeoffCreateCalibrationResponse {
  calibration: TakeoffCalibrationRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCreateMeasurementResponse".
 */
export interface TakeoffCreateMeasurementResponse {
  measurement: TakeoffMeasurementRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffBindLineResponse".
 */
export interface TakeoffBindLineResponse {
  binding: TakeoffBindingRecord;
  history_id: string;
  operation: EstOperation;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffListResponse".
 */
export interface TakeoffListResponse {
  /**
   * @maxItems 100
   */
  items: TakeoffGetResponse[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffBoundLine".
 */
export interface TakeoffBoundLine {
  id: string;
  estimate: string;
  estimate_revision: string;
  line_id: string;
  estimate_line_record: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffImpactMeasurement".
 */
export interface TakeoffImpactMeasurement {
  measurement_id: string;
  measurement_digest: string;
  current_use: TakeoffCurrentUse;
  /**
   * @maxItems 200
   */
  bound_lines: TakeoffBoundLine[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffImpactResponse".
 */
export interface TakeoffImpactResponse {
  source: TakeoffSource;
  /**
   * @maxItems 200
   */
  measurements: TakeoffImpactMeasurement[];
  new_use_requires_explicit_successor: boolean;
  historical_results_changed: false;
  head_policy: "current-working-revision-v1";
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "TakeoffCompareResponse".
 */
export interface TakeoffCompareResponse {
  family_id: string;
  before: {
    id: string;
    digest: string;
    quantity: EstQuantity;
    source: TakeoffSource;
  };
  after: {
    id: string;
    digest: string;
    quantity: EstQuantity;
    source: TakeoffSource;
  };
  changed: {
    source: boolean;
    quantity: boolean;
    geometry_or_manual_inputs: boolean;
    calibration: boolean;
  };
  original_records_preserved: true;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "ListEstimateAcceptancesRequest".
 */
export interface ListEstimateAcceptancesRequest {
  company: string;
  project: string;
  estimate_id: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "ListEstimateAcceptancesResponse".
 */
export interface ListEstimateAcceptancesResponse {
  /**
   * @maxItems 200
   */
  items: EstAcceptanceRecord[];
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstimateAcceptanceSubjectRequest".
 */
export interface EstimateAcceptanceSubjectRequest {
  company: string;
  project: string;
  revision_id: string;
}
/**
 * This interface was referenced by `CipherEST02AuthoredManualAndIndependentlyVerifiedPDFPlanarTakeoff`'s JSON-Schema
 * via the `definition` "EstimateAcceptanceSubjectResponse".
 */
export interface EstimateAcceptanceSubjectResponse {
  revision_id: string;
  record_digest: string;
  estimate_id: string;
  is_current: boolean;
  current_revision: string | null;
  accepted_baseline_id: string | null;
}
