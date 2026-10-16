/* Generated from cipher_aec/project_controls/schemas/api-v1.schema.json. Do not edit.
 * Source SHA-256: 5a40062cb083e03956abb173a8e7d6baa53bdb17012d38319a390a6ec26fa146
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcDefinition".
 */
export type PcDefinition = PcCodeDefinition | PcTypeDefinition;
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcProjectRecord".
 */
export type PcProjectRecord = PcBudgetRecord | PcWbsRecord | PcBudgetLineRecord;

export interface UrnCipherProjectControlsApiV1 {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcMaster".
 */
export interface PcMaster {
  schema: "cipher.cost-master.v1";
  id: string;
  company: string;
  project: null;
  kind: "code" | "type";
  code: string;
  author_person: string;
  current_revision: string | null;
  revision_number: number;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcOperation".
 */
export interface PcOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcMasterCommand".
 */
export interface PcMasterCommand {
  master: PcMaster;
  revision: PcRevision;
  version: string;
  operation: PcOperation;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcMasterItem".
 */
export interface PcMasterItem {
  master: PcMaster;
  revision: PcResolvedRevision;
  version: string;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcMasterPage".
 */
export interface PcMasterPage {
  /**
   * @maxItems 200
   */
  items: PcMasterItem[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcMoney".
 */
export interface PcMoney {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcRational".
 */
export interface PcRational {
  numerator: string;
  denominator: string;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcAwardContext".
 */
export interface PcAwardContext {
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
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcBudgetRecord".
 */
export interface PcBudgetRecord {
  schema: "cipher.project-budget.v1";
  id: string;
  company: string;
  project: string;
  author_person: string;
  award_context: PcAwardContext;
  controls_plan_digest: string;
  award_id: string;
  award_revision_id: string;
  status: "adopted";
  version_number: 1;
  predecessor: null;
  plan: PcInitialPlan;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcWbsRecord".
 */
export interface PcWbsRecord {
  schema: "cipher.project-wbs.v1";
  id: string;
  company: string;
  project: string;
  author_person: string;
  award_context: PcAwardContext;
  controls_plan_digest: string;
  budget_version: string;
  node: PcWbsNode;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcBudgetLineRecord".
 */
export interface PcBudgetLineRecord {
  schema: "cipher.project-budget-line.v1";
  id: string;
  company: string;
  project: string;
  author_person: string;
  award_context: PcAwardContext;
  controls_plan_digest: string;
  budget_version: string;
  line: PcBudgetLine;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcProjectPage".
 */
export interface PcProjectPage {
  /**
   * @maxItems 200
   */
  items: PcProjectRecord[];
  next_cursor: string | null;
  limit: number;
  count_mode: "none" | "exact";
  total: number | null;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcCreateMasterRequest".
 */
export interface PcCreateMasterRequest {
  company: string;
  operation_id?: string;
  kind: "code" | "type";
  code: string;
  definition: PcDefinition;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcReviseMasterRequest".
 */
export interface PcReviseMasterRequest {
  company: string;
  operation_id?: string;
  kind: "code" | "type";
  master_id: string;
  expected_version: string;
  definition: PcDefinition;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcGetRevisionRequest".
 */
export interface PcGetRevisionRequest {
  company: string;
  kind: "code" | "type";
  revision_id: string;
  basis_date: string;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcListMastersRequest".
 */
export interface PcListMastersRequest {
  company: string;
  kind: "code" | "type";
  basis_date: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcGetProjectRecordRequest".
 */
export interface PcGetProjectRecordRequest {
  company: string;
  project: string;
  kind: "wbs" | "budget" | "budget_line";
  record_id: string;
}
/**
 * This interface was referenced by `UrnCipherProjectControlsApiV1`'s JSON-Schema
 * via the `definition` "PcListProjectRecordsRequest".
 */
export interface PcListProjectRecordsRequest {
  company: string;
  project: string;
  kind: "wbs" | "budget" | "budget_line";
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
