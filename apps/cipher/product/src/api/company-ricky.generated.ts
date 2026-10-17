/* Generated from cipher_aec/ricky/schemas/company-api-v1.schema.json. Do not edit.
 * Source SHA-256: 8c101c7669901ff7df24c137a919a30e666cfa79964c5bf1f4f6a256cbbde93f
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickySelectedRead".
 */
export type CompanyRickySelectedRead = {
  schema: "cipher.ricky.company.read-request.v1";
  pursuit_id: string;
  action: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
  arguments: {
    [k: string]: unknown;
  };
  /**
   * @maxItems 8
   */
  sources:
    | []
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ]
    | [
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        },
        {
          citation_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
        }
      ];
  /**
   * @maxItems 8
   */
  measurement_ids:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
} & CompanyRickySelectedRead1;
export type CompanyRickySelectedRead1 =
  | {
      action: "aec.pursuit.lookup";
      arguments: {};
      [k: string]: unknown;
    }
  | {
      action: "aec.estimate.recompute";
      arguments: {
        revision_id: string;
      };
      [k: string]: unknown;
    }
  | {
      action: "aec.estimate.compare";
      arguments: {
        left_revision_id: string;
        right_revision_id: string;
      };
      [k: string]: unknown;
    }
  | {
      action: "aec.quantity.convert";
      arguments: {
        source_kind: "estimate-line" | "measurement";
        source_id: string;
        target_unit_id: string;
      };
      [k: string]: unknown;
    };

export interface CipherRickyCompanyApiV1 {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyStartReadRequest".
 */
export interface CompanyRickyStartReadRequest {
  company: string;
  request: CompanyRickySelectedRead;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyGetRunRequest".
 */
export interface CompanyRickyGetRunRequest {
  company: string;
  run_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyRunEventsRequest".
 */
export interface CompanyRickyRunEventsRequest {
  company: string;
  run_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyCancelRunRequest".
 */
export interface CompanyRickyCancelRunRequest {
  company: string;
  run_id: string;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyRunResponse".
 */
export interface CompanyRickyRunResponse {
  id: string;
  company: string;
  scope_type: "Company";
  project: null;
  request_kind: "deterministic-read-v1";
  status: "queued" | "retrieving" | "executing" | "succeeded" | "failed" | "cancelled";
  cancel_requested: boolean;
  created_at: string;
  completed_at: string | null;
  action: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
  result:
    | {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        record_digest: string;
        revision_number: number;
        title: string;
      }
    | {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        revision_id: string;
        revision_digest: string;
        snapshot_id: string;
        input_digest: string;
        output_digest: string;
        policy_version: string;
        total: {
          amount: string;
          currency: string;
        };
        quantity_basis: "authored-original-snapshot";
        current_working_revision: boolean;
      }
    | {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        left_revision_id: string;
        right_revision_id: string;
        left_digest: string;
        right_digest: string;
        currency: string;
        total_delta: string;
        /**
         * @maxItems 200
         */
        changed_line_ids: string[];
      }
    | {
        source_kind: "estimate-line" | "measurement";
        source_id: string;
        source_digest: string;
        source_unit_id: string;
        target_unit_id: string;
        numerator: string;
        denominator: string;
        provenance: "authored-estimate-line" | "manual-measurement" | "calibrated-measurement";
        quantity_basis: "authored-line-v1" | "net-quantity-v1" | "after-takeoff-waste-v1";
        independently_verified: boolean;
        eligible_for_new_use: boolean;
        model_supplied_quantity: false;
      }
    | null;
  result_digest: string | null;
  error: {
    code: string;
    message: string;
    retryable: boolean;
  } | null;
  standing: {
    mode: "deterministic-read-v1";
    model_invoked: false;
    live_model_qualified: false;
  };
  result_basis: "original-tool-observation-v1";
  selection: CompanyRickySelectedRead;
  selection_digest: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyStartReadResponse".
 */
export interface CompanyRickyStartReadResponse {
  id: string;
  company: string;
  scope_type: "Company";
  project: null;
  request_kind: "deterministic-read-v1";
  status: "queued" | "retrieving" | "executing" | "succeeded" | "failed" | "cancelled";
  cancel_requested: boolean;
  created_at: string;
  completed_at: string | null;
  action: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
  result:
    | {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        record_digest: string;
        revision_number: number;
        title: string;
      }
    | {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        revision_id: string;
        revision_digest: string;
        snapshot_id: string;
        input_digest: string;
        output_digest: string;
        policy_version: string;
        total: {
          amount: string;
          currency: string;
        };
        quantity_basis: "authored-original-snapshot";
        current_working_revision: boolean;
      }
    | {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        left_revision_id: string;
        right_revision_id: string;
        left_digest: string;
        right_digest: string;
        currency: string;
        total_delta: string;
        /**
         * @maxItems 200
         */
        changed_line_ids: string[];
      }
    | {
        source_kind: "estimate-line" | "measurement";
        source_id: string;
        source_digest: string;
        source_unit_id: string;
        target_unit_id: string;
        numerator: string;
        denominator: string;
        provenance: "authored-estimate-line" | "manual-measurement" | "calibrated-measurement";
        quantity_basis: "authored-line-v1" | "net-quantity-v1" | "after-takeoff-waste-v1";
        independently_verified: boolean;
        eligible_for_new_use: boolean;
        model_supplied_quantity: false;
      }
    | null;
  result_digest: string | null;
  error: {
    code: string;
    message: string;
    retryable: boolean;
  } | null;
  standing: {
    mode: "deterministic-read-v1";
    model_invoked: false;
    live_model_qualified: false;
  };
  result_basis: "original-tool-observation-v1";
  operation: {
    id: string;
    status: "succeeded";
    replayed: boolean;
  };
  selection: CompanyRickySelectedRead;
  selection_digest: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyStopResponse".
 */
export interface CompanyRickyStopResponse {
  id: string;
  company: string;
  scope_type: "Company";
  project: null;
  request_kind: "deterministic-read-v1";
  status: "succeeded" | "failed" | "cancelled";
  cancel_requested: boolean;
  operation: {
    id: string;
    status: "succeeded";
    replayed: boolean;
  };
}
/**
 * This interface was referenced by `CipherRickyCompanyApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyRunEventsResponse".
 */
export interface CompanyRickyRunEventsResponse {
  /**
   * @maxItems 8
   */
  items:
    | []
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ]
    | [
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        },
        {
          id: string;
          run_id: string;
          status: "claimed" | "succeeded" | "failed";
          tool_name: "aec.pursuit.lookup" | "aec.estimate.recompute" | "aec.estimate.compare" | "aec.quantity.convert";
          created_at: string;
          completed_at: string | null;
          error: {
            code: string;
            message: string;
          } | null;
        }
      ];
}
