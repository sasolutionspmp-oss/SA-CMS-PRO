/* Generated from cipher_aec/ricky/schemas/company-proposal-api-v1.schema.json. Do not edit.
 * Source SHA-256: 7288a18e38029761e95815bdb1873550c04bde0a8a18b017f6109625d46b7e87
 * Regenerate: npm run generate:api
 */

/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalSelection".
 */
export type CompanyRickyProposalSelection = {
  schema: "cipher.ricky.company.proposal-request.v1";
  pursuit_id: string;
  action: "aec.scope.draft" | "aec.estimate.draft";
  arguments: {
    [k: string]: unknown;
  };
  /**
   * @maxItems 8
   */
  sources: {
    citation_id: string;
    revision_id: string;
    page: number;
    excerpt_sha256: string;
    source_sha256: string;
  }[];
  /**
   * @maxItems 8
   */
  measurement_ids: string[];
} & CompanyRickyProposalSelection1;
export type CompanyRickyProposalSelection1 =
  | {
      action: "aec.scope.draft";
      arguments: {
        proposal_revision_id: string;
        /**
         * @maxItems 8
         */
        sections: {
          heading: string;
          text: string;
          /**
           * @maxItems 8
           */
          citation_ids: string[];
        }[];
        /**
         * @maxItems 8
         */
        unverified_claims: string[];
      };
      [k: string]: unknown;
    }
  | {
      action: "aec.estimate.draft";
      arguments: {
        base_revision_id: string;
        /**
         * @maxItems 8
         */
        selections: {
          line_record_id: string;
          source_kind: "estimate-line" | "measurement";
          source_id: string;
          target_unit_id: string;
        }[];
        notes: string;
        /**
         * @maxItems 8
         */
        citation_ids: string[];
        /**
         * @maxItems 8
         */
        unverified_claims: string[];
      };
      [k: string]: unknown;
    };
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalResponse".
 */
export type CompanyRickyProposalResponse =
  | {
      id: string;
      company: string;
      scope_type: "Company";
      project: null;
      created_at: string;
      schema: "cipher.ricky.company.proposal.v1";
      run_id: string;
      status: "proposed";
      version: 1;
      persistent: true;
      action: "aec.scope.draft";
      action_version: "1";
      kind: "scope-draft.v1";
      step_id: string;
      invocation_id: string;
      expires_at: string;
      content_digest: string;
      preparation_digest: string;
      preparation: {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        persistent: false;
        review_required: true;
        claim_classification: "unverified-author-suggestion";
        /**
         * @maxItems 8
         */
        verified_source_references: {
          citation_id: string;
          document_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
          canonical_digest: string;
        }[];
        /**
         * @maxItems 8
         */
        unverified_claims: string[];
        /**
         * @maxItems 32
         */
        record_dependencies: {
          kind: string;
          id: string;
          digest: string;
        }[];
        draft_digest: string;
        kind: "scope-draft.v1";
        proposed_fields: {
          /**
           * @maxItems 8
           */
          sections: {
            heading: string;
            text: string;
            /**
             * @maxItems 8
             */
            citation_ids: string[];
          }[];
        };
      };
      source_manifest: CompanyRickyProposalManifest;
      prepared_manifest_digest: string;
      review_required: true;
      claim_classification: "unverified-author-suggestion";
    }
  | {
      id: string;
      company: string;
      scope_type: "Company";
      project: null;
      created_at: string;
      schema: "cipher.ricky.company.proposal.v1";
      run_id: string;
      status: "proposed";
      version: 1;
      persistent: true;
      action: "aec.estimate.draft";
      action_version: "1";
      kind: "estimate-draft.v1";
      step_id: string;
      invocation_id: string;
      expires_at: string;
      content_digest: string;
      preparation_digest: string;
      preparation: {
        scope_type: "Company";
        company: string;
        pursuit_id: string;
        persistent: false;
        review_required: true;
        claim_classification: "unverified-author-suggestion";
        /**
         * @maxItems 8
         */
        verified_source_references: {
          citation_id: string;
          document_id: string;
          revision_id: string;
          page: number;
          excerpt_sha256: string;
          source_sha256: string;
          canonical_digest: string;
        }[];
        /**
         * @maxItems 8
         */
        unverified_claims: string[];
        /**
         * @maxItems 32
         */
        record_dependencies: {
          kind: string;
          id: string;
          digest: string;
        }[];
        draft_digest: string;
        kind: "estimate-draft.v1";
        proposed_fields: {
          /**
           * @maxItems 8
           */
          quantity_selections: {
            line_record_id: string;
            quantity: {
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
            };
          }[];
          notes: string;
        };
      };
      source_manifest: CompanyRickyProposalManifest;
      prepared_manifest_digest: string;
      review_required: true;
      claim_classification: "unverified-author-suggestion";
    };

export interface CipherRickyCompanyProposalApiV1 {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalStartRequest".
 */
export interface CompanyRickyProposalStartRequest {
  company: string;
  request: CompanyRickyProposalSelection;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalGetRunRequest".
 */
export interface CompanyRickyProposalGetRunRequest {
  company: string;
  run_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalEventsRequest".
 */
export interface CompanyRickyProposalEventsRequest {
  company: string;
  run_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalStopRequest".
 */
export interface CompanyRickyProposalStopRequest {
  company: string;
  run_id: string;
  operation_id: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalRunResponse".
 */
export interface CompanyRickyProposalRunResponse {
  id: string;
  company: string;
  scope_type: "Company";
  project: null;
  request_kind: "deterministic-proposal-v1";
  status: "queued" | "retrieving" | "executing" | "waiting-for-review" | "failed" | "cancelled";
  cancel_requested: boolean;
  created_at: string;
  completed_at: string | null;
  action: "aec.scope.draft" | "aec.estimate.draft";
  result: {
    proposal_id: string;
    proposal_version: 1;
    proposal_digest: string;
    preparation_digest: string;
  } | null;
  result_digest: string | null;
  error: {
    code: string;
    message: string;
    retryable: boolean;
  } | null;
  standing: {
    mode: "deterministic-proposal-v1";
    model_invoked: false;
    live_model_qualified: false;
  };
  result_basis: "persisted-proposal-reference-v1";
  selection: CompanyRickyProposalSelection;
  selection_digest: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalStartResponse".
 */
export interface CompanyRickyProposalStartResponse {
  id: string;
  company: string;
  scope_type: "Company";
  project: null;
  request_kind: "deterministic-proposal-v1";
  status: "queued" | "retrieving" | "executing" | "waiting-for-review" | "failed" | "cancelled";
  cancel_requested: boolean;
  created_at: string;
  completed_at: string | null;
  action: "aec.scope.draft" | "aec.estimate.draft";
  result: {
    proposal_id: string;
    proposal_version: 1;
    proposal_digest: string;
    preparation_digest: string;
  } | null;
  result_digest: string | null;
  error: {
    code: string;
    message: string;
    retryable: boolean;
  } | null;
  standing: {
    mode: "deterministic-proposal-v1";
    model_invoked: false;
    live_model_qualified: false;
  };
  result_basis: "persisted-proposal-reference-v1";
  operation: {
    id: string;
    status: "succeeded";
    replayed: boolean;
  };
  selection: CompanyRickyProposalSelection;
  selection_digest: string;
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalStopResponse".
 */
export interface CompanyRickyProposalStopResponse {
  id: string;
  company: string;
  scope_type: "Company";
  project: null;
  request_kind: "deterministic-proposal-v1";
  status: "waiting-for-review" | "failed" | "cancelled";
  cancel_requested: boolean;
  operation: {
    id: string;
    status: "succeeded";
    replayed: boolean;
  };
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalEventsResponse".
 */
export interface CompanyRickyProposalEventsResponse {
  /**
   * @maxItems 8
   */
  items: {
    id: string;
    run_id: string;
    status: "claimed" | "succeeded" | "failed";
    tool_name: "aec.scope.draft" | "aec.estimate.draft";
    created_at: string;
    completed_at: string | null;
    error: {
      code: string;
      message: string;
    } | null;
  }[];
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalManifest".
 */
export interface CompanyRickyProposalManifest {
  schema: "cipher.ricky.company.original-proposal.v1";
  selection_digest: string;
  action_complete: boolean;
  pursuit: {
    id: string;
    digest: string;
    party_type: "Customer" | "Lead";
    party_id: string;
    opportunity: string;
    /**
     * @maxItems 2
     */
    native_refs: {
      doctype: "Customer" | "Lead" | "Opportunity";
      name: string;
    }[];
  };
  /**
   * @maxItems 8
   */
  citations: {
    id: string;
    digest: string;
  }[];
  /**
   * @maxItems 128
   */
  records: (
    | {
        domain: "commercial";
        kind: "proposal-revision";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "acceptance";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "assembly";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "conversion";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "line";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "rate";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "revision";
        id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "snapshot";
        id: string;
        digest: string;
      }
    | {
        domain: "takeoff";
        kind: "binding";
        id: string;
        digest: string;
      }
    | {
        domain: "takeoff";
        kind: "calibration";
        id: string;
        digest: string;
      }
    | {
        domain: "takeoff";
        kind: "measurement";
        id: string;
        digest: string;
      }
    | {
        domain: "takeoff";
        kind: "verification";
        id: string;
        digest: string;
      }
  )[];
  /**
   * @maxItems 8
   */
  owners: (
    | {
        domain: "commercial";
        kind: "proposal";
        id: string;
        pursuit_id: string;
        digest: string;
      }
    | {
        domain: "estimate";
        kind: "estimate";
        id: string;
        pursuit_id: string;
        digest: string;
      }
  )[];
  /**
   * @maxItems 8
   */
  preparation_heads: {
    domain: "commercial" | "estimate";
    owner_id: string;
    revision_id: string;
    digest: string;
  }[];
  /**
   * @maxItems 500
   */
  qualified_units: {
    id: string;
    digest: string;
  }[];
  /**
   * @maxItems 8
   */
  quantity_standing: {
    measurement_id: string;
    eligible: boolean;
    verification_id: string | null;
    digest: string;
  }[];
}
/**
 * This interface was referenced by `CipherRickyCompanyProposalApiV1`'s JSON-Schema
 * via the `definition` "CompanyRickyProposalGetRequest".
 */
export interface CompanyRickyProposalGetRequest {
  company: string;
  proposal_id: string;
}

// Published closed runtime shapes, generated from the same source as these types.
export const companyRickyProposalSchema = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "cipher.ricky.company-proposal-api.v1",
  "$defs": {
    "CompanyRickyProposalSelection": {
      "type": "object",
      "properties": {
        "schema": {
          "const": "cipher.ricky.company.proposal-request.v1"
        },
        "pursuit_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        },
        "action": {
          "enum": [
            "aec.scope.draft",
            "aec.estimate.draft"
          ]
        },
        "arguments": {
          "type": "object"
        },
        "sources": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "citation_id": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$"
              },
              "revision_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160
              },
              "page": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100000
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
              "citation_id",
              "revision_id",
              "page",
              "excerpt_sha256",
              "source_sha256"
            ],
            "additionalProperties": false
          },
          "maxItems": 8
        },
        "measurement_ids": {
          "type": "array",
          "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 140,
            "format": "uuid"
          },
          "maxItems": 8
        }
      },
      "required": [
        "schema",
        "pursuit_id",
        "action",
        "arguments",
        "sources",
        "measurement_ids"
      ],
      "additionalProperties": false,
      "oneOf": [
        {
          "properties": {
            "action": {
              "const": "aec.scope.draft"
            },
            "arguments": {
              "type": "object",
              "properties": {
                "proposal_revision_id": {
                  "type": "string",
                  "minLength": 36,
                  "maxLength": 36
                },
                "sections": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "heading": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200
                      },
                      "text": {
                        "type": "string",
                        "maxLength": 2000
                      },
                      "citation_ids": {
                        "type": "array",
                        "items": {
                          "type": "string",
                          "minLength": 64,
                          "maxLength": 64
                        },
                        "maxItems": 8
                      }
                    },
                    "required": [
                      "heading",
                      "text",
                      "citation_ids"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 8
                },
                "unverified_claims": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "maxItems": 8
                }
              },
              "required": [
                "proposal_revision_id",
                "sections",
                "unverified_claims"
              ],
              "additionalProperties": false
            }
          },
          "required": [
            "action",
            "arguments"
          ]
        },
        {
          "properties": {
            "action": {
              "const": "aec.estimate.draft"
            },
            "arguments": {
              "type": "object",
              "properties": {
                "base_revision_id": {
                  "type": "string",
                  "minLength": 36,
                  "maxLength": 36
                },
                "selections": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "line_record_id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      },
                      "source_kind": {
                        "type": "string",
                        "enum": [
                          "estimate-line",
                          "measurement"
                        ]
                      },
                      "source_id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      },
                      "target_unit_id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      }
                    },
                    "required": [
                      "line_record_id",
                      "source_kind",
                      "source_id",
                      "target_unit_id"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 8
                },
                "notes": {
                  "type": "string",
                  "maxLength": 2000
                },
                "citation_ids": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "minLength": 64,
                    "maxLength": 64
                  },
                  "maxItems": 8
                },
                "unverified_claims": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "maxItems": 8
                }
              },
              "required": [
                "base_revision_id",
                "selections",
                "notes",
                "citation_ids",
                "unverified_claims"
              ],
              "additionalProperties": false
            }
          },
          "required": [
            "action",
            "arguments"
          ]
        }
      ]
    },
    "CompanyRickyProposalStartRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "request": {
          "$ref": "#/$defs/CompanyRickyProposalSelection"
        },
        "operation_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        }
      },
      "required": [
        "company",
        "request",
        "operation_id"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalGetRunRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "run_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        }
      },
      "required": [
        "company",
        "run_id"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalEventsRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "run_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        }
      },
      "required": [
        "company",
        "run_id"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalStopRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "run_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        },
        "operation_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        }
      },
      "required": [
        "company",
        "run_id",
        "operation_id"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalRunResponse": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "scope_type": {
          "const": "Company"
        },
        "project": {
          "type": "null"
        },
        "request_kind": {
          "const": "deterministic-proposal-v1"
        },
        "status": {
          "enum": [
            "queued",
            "retrieving",
            "executing",
            "waiting-for-review",
            "failed",
            "cancelled"
          ]
        },
        "cancel_requested": {
          "type": "boolean"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "completed_at": {
          "anyOf": [
            {
              "type": "string",
              "format": "date-time"
            },
            {
              "type": "null"
            }
          ]
        },
        "action": {
          "enum": [
            "aec.scope.draft",
            "aec.estimate.draft"
          ]
        },
        "result": {
          "anyOf": [
            {
              "type": "object",
              "properties": {
                "proposal_id": {
                  "type": "string",
                  "format": "uuid",
                  "minLength": 36,
                  "maxLength": 36
                },
                "proposal_version": {
                  "const": 1
                },
                "proposal_digest": {
                  "type": "string",
                  "pattern": "^[a-f0-9]{64}$"
                },
                "preparation_digest": {
                  "type": "string",
                  "pattern": "^[a-f0-9]{64}$"
                }
              },
              "required": [
                "proposal_id",
                "proposal_version",
                "proposal_digest",
                "preparation_digest"
              ],
              "additionalProperties": false
            },
            {
              "type": "null"
            }
          ]
        },
        "result_digest": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[a-f0-9]{64}$"
            },
            {
              "type": "null"
            }
          ]
        },
        "error": {
          "anyOf": [
            {
              "type": "object",
              "properties": {
                "code": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 140
                },
                "message": {
                  "type": "string",
                  "maxLength": 2000
                },
                "retryable": {
                  "type": "boolean"
                }
              },
              "required": [
                "code",
                "message",
                "retryable"
              ],
              "additionalProperties": false
            },
            {
              "type": "null"
            }
          ]
        },
        "standing": {
          "type": "object",
          "properties": {
            "mode": {
              "const": "deterministic-proposal-v1"
            },
            "model_invoked": {
              "const": false
            },
            "live_model_qualified": {
              "const": false
            }
          },
          "required": [
            "mode",
            "model_invoked",
            "live_model_qualified"
          ],
          "additionalProperties": false
        },
        "result_basis": {
          "const": "persisted-proposal-reference-v1"
        },
        "selection": {
          "$ref": "#/$defs/CompanyRickyProposalSelection"
        },
        "selection_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        }
      },
      "required": [
        "id",
        "company",
        "scope_type",
        "project",
        "request_kind",
        "status",
        "cancel_requested",
        "created_at",
        "completed_at",
        "action",
        "result",
        "result_digest",
        "error",
        "standing",
        "result_basis",
        "selection",
        "selection_digest"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalStartResponse": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "scope_type": {
          "const": "Company"
        },
        "project": {
          "type": "null"
        },
        "request_kind": {
          "const": "deterministic-proposal-v1"
        },
        "status": {
          "enum": [
            "queued",
            "retrieving",
            "executing",
            "waiting-for-review",
            "failed",
            "cancelled"
          ]
        },
        "cancel_requested": {
          "type": "boolean"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "completed_at": {
          "anyOf": [
            {
              "type": "string",
              "format": "date-time"
            },
            {
              "type": "null"
            }
          ]
        },
        "action": {
          "enum": [
            "aec.scope.draft",
            "aec.estimate.draft"
          ]
        },
        "result": {
          "anyOf": [
            {
              "type": "object",
              "properties": {
                "proposal_id": {
                  "type": "string",
                  "format": "uuid",
                  "minLength": 36,
                  "maxLength": 36
                },
                "proposal_version": {
                  "const": 1
                },
                "proposal_digest": {
                  "type": "string",
                  "pattern": "^[a-f0-9]{64}$"
                },
                "preparation_digest": {
                  "type": "string",
                  "pattern": "^[a-f0-9]{64}$"
                }
              },
              "required": [
                "proposal_id",
                "proposal_version",
                "proposal_digest",
                "preparation_digest"
              ],
              "additionalProperties": false
            },
            {
              "type": "null"
            }
          ]
        },
        "result_digest": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[a-f0-9]{64}$"
            },
            {
              "type": "null"
            }
          ]
        },
        "error": {
          "anyOf": [
            {
              "type": "object",
              "properties": {
                "code": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 140
                },
                "message": {
                  "type": "string",
                  "maxLength": 2000
                },
                "retryable": {
                  "type": "boolean"
                }
              },
              "required": [
                "code",
                "message",
                "retryable"
              ],
              "additionalProperties": false
            },
            {
              "type": "null"
            }
          ]
        },
        "standing": {
          "type": "object",
          "properties": {
            "mode": {
              "const": "deterministic-proposal-v1"
            },
            "model_invoked": {
              "const": false
            },
            "live_model_qualified": {
              "const": false
            }
          },
          "required": [
            "mode",
            "model_invoked",
            "live_model_qualified"
          ],
          "additionalProperties": false
        },
        "result_basis": {
          "const": "persisted-proposal-reference-v1"
        },
        "operation": {
          "type": "object",
          "properties": {
            "id": {
              "type": "string",
              "minLength": 1,
              "maxLength": 140,
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
        },
        "selection": {
          "$ref": "#/$defs/CompanyRickyProposalSelection"
        },
        "selection_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        }
      },
      "required": [
        "id",
        "company",
        "scope_type",
        "project",
        "request_kind",
        "status",
        "cancel_requested",
        "created_at",
        "completed_at",
        "action",
        "result",
        "result_digest",
        "error",
        "standing",
        "result_basis",
        "operation",
        "selection",
        "selection_digest"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalStopResponse": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "scope_type": {
          "const": "Company"
        },
        "project": {
          "type": "null"
        },
        "request_kind": {
          "const": "deterministic-proposal-v1"
        },
        "status": {
          "enum": [
            "waiting-for-review",
            "failed",
            "cancelled"
          ]
        },
        "cancel_requested": {
          "type": "boolean"
        },
        "operation": {
          "type": "object",
          "properties": {
            "id": {
              "type": "string",
              "minLength": 1,
              "maxLength": 140,
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
      },
      "required": [
        "id",
        "company",
        "scope_type",
        "project",
        "request_kind",
        "status",
        "cancel_requested",
        "operation"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalEventsResponse": {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 140,
                "format": "uuid"
              },
              "run_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 140,
                "format": "uuid"
              },
              "status": {
                "enum": [
                  "claimed",
                  "succeeded",
                  "failed"
                ]
              },
              "tool_name": {
                "enum": [
                  "aec.scope.draft",
                  "aec.estimate.draft"
                ]
              },
              "created_at": {
                "type": "string",
                "format": "date-time"
              },
              "completed_at": {
                "anyOf": [
                  {
                    "type": "string",
                    "format": "date-time"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "error": {
                "anyOf": [
                  {
                    "type": "object",
                    "properties": {
                      "code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 140
                      },
                      "message": {
                        "type": "string",
                        "maxLength": 2000
                      }
                    },
                    "required": [
                      "code",
                      "message"
                    ],
                    "additionalProperties": false
                  },
                  {
                    "type": "null"
                  }
                ]
              }
            },
            "required": [
              "id",
              "run_id",
              "status",
              "tool_name",
              "created_at",
              "completed_at",
              "error"
            ],
            "additionalProperties": false
          },
          "maxItems": 8
        }
      },
      "required": [
        "items"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalManifest": {
      "type": "object",
      "properties": {
        "schema": {
          "const": "cipher.ricky.company.original-proposal.v1"
        },
        "selection_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "action_complete": {
          "type": "boolean"
        },
        "pursuit": {
          "type": "object",
          "properties": {
            "id": {
              "type": "string",
              "format": "uuid",
              "minLength": 36,
              "maxLength": 36
            },
            "digest": {
              "type": "string",
              "pattern": "^[a-f0-9]{64}$"
            },
            "party_type": {
              "enum": [
                "Customer",
                "Lead"
              ]
            },
            "party_id": {
              "type": "string",
              "minLength": 1,
              "maxLength": 140
            },
            "opportunity": {
              "type": "string",
              "minLength": 1,
              "maxLength": 140
            },
            "native_refs": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "doctype": {
                    "enum": [
                      "Customer",
                      "Lead",
                      "Opportunity"
                    ]
                  },
                  "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 140
                  }
                },
                "required": [
                  "doctype",
                  "name"
                ],
                "additionalProperties": false
              },
              "maxItems": 2
            }
          },
          "required": [
            "id",
            "digest",
            "party_type",
            "party_id",
            "opportunity",
            "native_refs"
          ],
          "additionalProperties": false
        },
        "citations": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$"
              },
              "digest": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$"
              }
            },
            "required": [
              "id",
              "digest"
            ],
            "additionalProperties": false
          },
          "maxItems": 8
        },
        "records": {
          "type": "array",
          "items": {
            "oneOf": [
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "commercial"
                  },
                  "kind": {
                    "const": "proposal-revision"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "acceptance"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "assembly"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "conversion"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "line"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "rate"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "revision"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "snapshot"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "takeoff"
                  },
                  "kind": {
                    "const": "binding"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "takeoff"
                  },
                  "kind": {
                    "const": "calibration"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "takeoff"
                  },
                  "kind": {
                    "const": "measurement"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "takeoff"
                  },
                  "kind": {
                    "const": "verification"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "digest"
                ],
                "additionalProperties": false
              }
            ]
          },
          "maxItems": 128
        },
        "owners": {
          "type": "array",
          "items": {
            "oneOf": [
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "commercial"
                  },
                  "kind": {
                    "const": "proposal"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "pursuit_id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "pursuit_id",
                  "digest"
                ],
                "additionalProperties": false
              },
              {
                "type": "object",
                "properties": {
                  "domain": {
                    "const": "estimate"
                  },
                  "kind": {
                    "const": "estimate"
                  },
                  "id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "pursuit_id": {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  "digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                  }
                },
                "required": [
                  "domain",
                  "kind",
                  "id",
                  "pursuit_id",
                  "digest"
                ],
                "additionalProperties": false
              }
            ]
          },
          "maxItems": 8
        },
        "preparation_heads": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "domain": {
                "enum": [
                  "commercial",
                  "estimate"
                ]
              },
              "owner_id": {
                "type": "string",
                "format": "uuid",
                "minLength": 36,
                "maxLength": 36
              },
              "revision_id": {
                "type": "string",
                "format": "uuid",
                "minLength": 36,
                "maxLength": 36
              },
              "digest": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$"
              }
            },
            "required": [
              "domain",
              "owner_id",
              "revision_id",
              "digest"
            ],
            "additionalProperties": false
          },
          "maxItems": 8
        },
        "qualified_units": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string",
                "format": "uuid",
                "minLength": 36,
                "maxLength": 36
              },
              "digest": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$"
              }
            },
            "required": [
              "id",
              "digest"
            ],
            "additionalProperties": false
          },
          "maxItems": 500
        },
        "quantity_standing": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "measurement_id": {
                "type": "string",
                "format": "uuid",
                "minLength": 36,
                "maxLength": 36
              },
              "eligible": {
                "type": "boolean"
              },
              "verification_id": {
                "anyOf": [
                  {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "digest": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$"
              }
            },
            "required": [
              "measurement_id",
              "eligible",
              "verification_id",
              "digest"
            ],
            "additionalProperties": false
          },
          "maxItems": 8
        }
      },
      "required": [
        "schema",
        "selection_digest",
        "action_complete",
        "pursuit",
        "citations",
        "records",
        "owners",
        "preparation_heads",
        "qualified_units",
        "quantity_standing"
      ],
      "additionalProperties": false
    },
    "CompanyRickyProposalResponse": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140,
          "format": "uuid"
        },
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "scope_type": {
          "const": "Company"
        },
        "project": {
          "type": "null"
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "schema": {
          "const": "cipher.ricky.company.proposal.v1"
        },
        "run_id": {
          "type": "string",
          "format": "uuid",
          "minLength": 36,
          "maxLength": 36
        },
        "status": {
          "const": "proposed"
        },
        "version": {
          "const": 1
        },
        "persistent": {
          "const": true
        },
        "action": {
          "enum": [
            "aec.scope.draft",
            "aec.estimate.draft"
          ]
        },
        "action_version": {
          "const": "1"
        },
        "kind": {
          "enum": [
            "scope-draft.v1",
            "estimate-draft.v1"
          ]
        },
        "step_id": {
          "type": "string",
          "format": "uuid",
          "minLength": 36,
          "maxLength": 36
        },
        "invocation_id": {
          "type": "string",
          "format": "uuid",
          "minLength": 36,
          "maxLength": 36
        },
        "expires_at": {
          "type": "string",
          "format": "date-time"
        },
        "content_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "preparation_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "preparation": {
          "oneOf": [
            {
              "type": "object",
              "properties": {
                "scope_type": {
                  "type": "string",
                  "enum": [
                    "Company"
                  ]
                },
                "company": {
                  "type": "string",
                  "maxLength": 2000
                },
                "pursuit_id": {
                  "type": "string",
                  "minLength": 36,
                  "maxLength": 36
                },
                "persistent": {
                  "type": "boolean",
                  "enum": [
                    false
                  ]
                },
                "review_required": {
                  "type": "boolean",
                  "enum": [
                    true
                  ]
                },
                "claim_classification": {
                  "type": "string",
                  "enum": [
                    "unverified-author-suggestion"
                  ]
                },
                "verified_source_references": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "citation_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "document_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "revision_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100000
                      },
                      "excerpt_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "source_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "canonical_digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "citation_id",
                      "document_id",
                      "revision_id",
                      "page",
                      "excerpt_sha256",
                      "source_sha256",
                      "canonical_digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 8
                },
                "unverified_claims": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "maxItems": 8
                },
                "record_dependencies": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "kind": {
                        "type": "string",
                        "maxLength": 40
                      },
                      "id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      },
                      "digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "kind",
                      "id",
                      "digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 32
                },
                "draft_digest": {
                  "type": "string",
                  "minLength": 64,
                  "maxLength": 64
                },
                "kind": {
                  "type": "string",
                  "enum": [
                    "scope-draft.v1"
                  ]
                },
                "proposed_fields": {
                  "type": "object",
                  "properties": {
                    "sections": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "heading": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200
                          },
                          "text": {
                            "type": "string",
                            "maxLength": 2000
                          },
                          "citation_ids": {
                            "type": "array",
                            "items": {
                              "type": "string",
                              "minLength": 64,
                              "maxLength": 64
                            },
                            "maxItems": 8
                          }
                        },
                        "required": [
                          "heading",
                          "text",
                          "citation_ids"
                        ],
                        "additionalProperties": false
                      },
                      "maxItems": 8
                    }
                  },
                  "required": [
                    "sections"
                  ],
                  "additionalProperties": false
                }
              },
              "required": [
                "scope_type",
                "company",
                "pursuit_id",
                "persistent",
                "review_required",
                "claim_classification",
                "verified_source_references",
                "unverified_claims",
                "record_dependencies",
                "draft_digest",
                "kind",
                "proposed_fields"
              ],
              "additionalProperties": false
            },
            {
              "type": "object",
              "properties": {
                "scope_type": {
                  "type": "string",
                  "enum": [
                    "Company"
                  ]
                },
                "company": {
                  "type": "string",
                  "maxLength": 2000
                },
                "pursuit_id": {
                  "type": "string",
                  "minLength": 36,
                  "maxLength": 36
                },
                "persistent": {
                  "type": "boolean",
                  "enum": [
                    false
                  ]
                },
                "review_required": {
                  "type": "boolean",
                  "enum": [
                    true
                  ]
                },
                "claim_classification": {
                  "type": "string",
                  "enum": [
                    "unverified-author-suggestion"
                  ]
                },
                "verified_source_references": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "citation_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "document_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "revision_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100000
                      },
                      "excerpt_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "source_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "canonical_digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "citation_id",
                      "document_id",
                      "revision_id",
                      "page",
                      "excerpt_sha256",
                      "source_sha256",
                      "canonical_digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 8
                },
                "unverified_claims": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "maxItems": 8
                },
                "record_dependencies": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "kind": {
                        "type": "string",
                        "maxLength": 40
                      },
                      "id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      },
                      "digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "kind",
                      "id",
                      "digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 32
                },
                "draft_digest": {
                  "type": "string",
                  "minLength": 64,
                  "maxLength": 64
                },
                "kind": {
                  "type": "string",
                  "enum": [
                    "estimate-draft.v1"
                  ]
                },
                "proposed_fields": {
                  "type": "object",
                  "properties": {
                    "quantity_selections": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "line_record_id": {
                            "type": "string",
                            "minLength": 36,
                            "maxLength": 36
                          },
                          "quantity": {
                            "type": "object",
                            "properties": {
                              "source_kind": {
                                "type": "string",
                                "enum": [
                                  "estimate-line",
                                  "measurement"
                                ]
                              },
                              "source_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36
                              },
                              "source_digest": {
                                "type": "string",
                                "minLength": 64,
                                "maxLength": 64
                              },
                              "source_unit_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36
                              },
                              "target_unit_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36
                              },
                              "numerator": {
                                "type": "string",
                                "maxLength": 2600
                              },
                              "denominator": {
                                "type": "string",
                                "maxLength": 2600
                              },
                              "provenance": {
                                "type": "string",
                                "enum": [
                                  "authored-estimate-line",
                                  "manual-measurement",
                                  "calibrated-measurement"
                                ]
                              },
                              "quantity_basis": {
                                "type": "string",
                                "enum": [
                                  "authored-line-v1",
                                  "net-quantity-v1",
                                  "after-takeoff-waste-v1"
                                ]
                              },
                              "independently_verified": {
                                "type": "boolean"
                              },
                              "eligible_for_new_use": {
                                "type": "boolean"
                              },
                              "model_supplied_quantity": {
                                "type": "boolean",
                                "enum": [
                                  false
                                ]
                              }
                            },
                            "required": [
                              "source_kind",
                              "source_id",
                              "source_digest",
                              "source_unit_id",
                              "target_unit_id",
                              "numerator",
                              "denominator",
                              "provenance",
                              "quantity_basis",
                              "independently_verified",
                              "eligible_for_new_use",
                              "model_supplied_quantity"
                            ],
                            "additionalProperties": false
                          }
                        },
                        "required": [
                          "line_record_id",
                          "quantity"
                        ],
                        "additionalProperties": false
                      },
                      "maxItems": 8
                    },
                    "notes": {
                      "type": "string",
                      "maxLength": 2000
                    }
                  },
                  "required": [
                    "quantity_selections",
                    "notes"
                  ],
                  "additionalProperties": false
                }
              },
              "required": [
                "scope_type",
                "company",
                "pursuit_id",
                "persistent",
                "review_required",
                "claim_classification",
                "verified_source_references",
                "unverified_claims",
                "record_dependencies",
                "draft_digest",
                "kind",
                "proposed_fields"
              ],
              "additionalProperties": false
            }
          ]
        },
        "source_manifest": {
          "$ref": "#/$defs/CompanyRickyProposalManifest"
        },
        "prepared_manifest_digest": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$"
        },
        "review_required": {
          "const": true
        },
        "claim_classification": {
          "const": "unverified-author-suggestion"
        }
      },
      "required": [
        "id",
        "company",
        "scope_type",
        "project",
        "created_at",
        "schema",
        "run_id",
        "status",
        "version",
        "persistent",
        "action",
        "action_version",
        "kind",
        "step_id",
        "invocation_id",
        "expires_at",
        "content_digest",
        "preparation_digest",
        "preparation",
        "source_manifest",
        "prepared_manifest_digest",
        "review_required",
        "claim_classification"
      ],
      "additionalProperties": false,
      "oneOf": [
        {
          "properties": {
            "action": {
              "const": "aec.scope.draft"
            },
            "kind": {
              "const": "scope-draft.v1"
            },
            "preparation": {
              "type": "object",
              "properties": {
                "scope_type": {
                  "type": "string",
                  "enum": [
                    "Company"
                  ]
                },
                "company": {
                  "type": "string",
                  "maxLength": 2000
                },
                "pursuit_id": {
                  "type": "string",
                  "minLength": 36,
                  "maxLength": 36
                },
                "persistent": {
                  "type": "boolean",
                  "enum": [
                    false
                  ]
                },
                "review_required": {
                  "type": "boolean",
                  "enum": [
                    true
                  ]
                },
                "claim_classification": {
                  "type": "string",
                  "enum": [
                    "unverified-author-suggestion"
                  ]
                },
                "verified_source_references": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "citation_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "document_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "revision_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100000
                      },
                      "excerpt_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "source_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "canonical_digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "citation_id",
                      "document_id",
                      "revision_id",
                      "page",
                      "excerpt_sha256",
                      "source_sha256",
                      "canonical_digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 8
                },
                "unverified_claims": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "maxItems": 8
                },
                "record_dependencies": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "kind": {
                        "type": "string",
                        "maxLength": 40
                      },
                      "id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      },
                      "digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "kind",
                      "id",
                      "digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 32
                },
                "draft_digest": {
                  "type": "string",
                  "minLength": 64,
                  "maxLength": 64
                },
                "kind": {
                  "type": "string",
                  "enum": [
                    "scope-draft.v1"
                  ]
                },
                "proposed_fields": {
                  "type": "object",
                  "properties": {
                    "sections": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "heading": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200
                          },
                          "text": {
                            "type": "string",
                            "maxLength": 2000
                          },
                          "citation_ids": {
                            "type": "array",
                            "items": {
                              "type": "string",
                              "minLength": 64,
                              "maxLength": 64
                            },
                            "maxItems": 8
                          }
                        },
                        "required": [
                          "heading",
                          "text",
                          "citation_ids"
                        ],
                        "additionalProperties": false
                      },
                      "maxItems": 8
                    }
                  },
                  "required": [
                    "sections"
                  ],
                  "additionalProperties": false
                }
              },
              "required": [
                "scope_type",
                "company",
                "pursuit_id",
                "persistent",
                "review_required",
                "claim_classification",
                "verified_source_references",
                "unverified_claims",
                "record_dependencies",
                "draft_digest",
                "kind",
                "proposed_fields"
              ],
              "additionalProperties": false
            }
          },
          "required": [
            "action",
            "kind",
            "preparation"
          ]
        },
        {
          "properties": {
            "action": {
              "const": "aec.estimate.draft"
            },
            "kind": {
              "const": "estimate-draft.v1"
            },
            "preparation": {
              "type": "object",
              "properties": {
                "scope_type": {
                  "type": "string",
                  "enum": [
                    "Company"
                  ]
                },
                "company": {
                  "type": "string",
                  "maxLength": 2000
                },
                "pursuit_id": {
                  "type": "string",
                  "minLength": 36,
                  "maxLength": 36
                },
                "persistent": {
                  "type": "boolean",
                  "enum": [
                    false
                  ]
                },
                "review_required": {
                  "type": "boolean",
                  "enum": [
                    true
                  ]
                },
                "claim_classification": {
                  "type": "string",
                  "enum": [
                    "unverified-author-suggestion"
                  ]
                },
                "verified_source_references": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "citation_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "document_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "revision_id": {
                        "type": "string",
                        "maxLength": 160
                      },
                      "page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100000
                      },
                      "excerpt_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "source_sha256": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      },
                      "canonical_digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "citation_id",
                      "document_id",
                      "revision_id",
                      "page",
                      "excerpt_sha256",
                      "source_sha256",
                      "canonical_digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 8
                },
                "unverified_claims": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "maxLength": 2000
                  },
                  "maxItems": 8
                },
                "record_dependencies": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "kind": {
                        "type": "string",
                        "maxLength": 40
                      },
                      "id": {
                        "type": "string",
                        "minLength": 36,
                        "maxLength": 36
                      },
                      "digest": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64
                      }
                    },
                    "required": [
                      "kind",
                      "id",
                      "digest"
                    ],
                    "additionalProperties": false
                  },
                  "maxItems": 32
                },
                "draft_digest": {
                  "type": "string",
                  "minLength": 64,
                  "maxLength": 64
                },
                "kind": {
                  "type": "string",
                  "enum": [
                    "estimate-draft.v1"
                  ]
                },
                "proposed_fields": {
                  "type": "object",
                  "properties": {
                    "quantity_selections": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "line_record_id": {
                            "type": "string",
                            "minLength": 36,
                            "maxLength": 36
                          },
                          "quantity": {
                            "type": "object",
                            "properties": {
                              "source_kind": {
                                "type": "string",
                                "enum": [
                                  "estimate-line",
                                  "measurement"
                                ]
                              },
                              "source_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36
                              },
                              "source_digest": {
                                "type": "string",
                                "minLength": 64,
                                "maxLength": 64
                              },
                              "source_unit_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36
                              },
                              "target_unit_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36
                              },
                              "numerator": {
                                "type": "string",
                                "maxLength": 2600
                              },
                              "denominator": {
                                "type": "string",
                                "maxLength": 2600
                              },
                              "provenance": {
                                "type": "string",
                                "enum": [
                                  "authored-estimate-line",
                                  "manual-measurement",
                                  "calibrated-measurement"
                                ]
                              },
                              "quantity_basis": {
                                "type": "string",
                                "enum": [
                                  "authored-line-v1",
                                  "net-quantity-v1",
                                  "after-takeoff-waste-v1"
                                ]
                              },
                              "independently_verified": {
                                "type": "boolean"
                              },
                              "eligible_for_new_use": {
                                "type": "boolean"
                              },
                              "model_supplied_quantity": {
                                "type": "boolean",
                                "enum": [
                                  false
                                ]
                              }
                            },
                            "required": [
                              "source_kind",
                              "source_id",
                              "source_digest",
                              "source_unit_id",
                              "target_unit_id",
                              "numerator",
                              "denominator",
                              "provenance",
                              "quantity_basis",
                              "independently_verified",
                              "eligible_for_new_use",
                              "model_supplied_quantity"
                            ],
                            "additionalProperties": false
                          }
                        },
                        "required": [
                          "line_record_id",
                          "quantity"
                        ],
                        "additionalProperties": false
                      },
                      "maxItems": 8
                    },
                    "notes": {
                      "type": "string",
                      "maxLength": 2000
                    }
                  },
                  "required": [
                    "quantity_selections",
                    "notes"
                  ],
                  "additionalProperties": false
                }
              },
              "required": [
                "scope_type",
                "company",
                "pursuit_id",
                "persistent",
                "review_required",
                "claim_classification",
                "verified_source_references",
                "unverified_claims",
                "record_dependencies",
                "draft_digest",
                "kind",
                "proposed_fields"
              ],
              "additionalProperties": false
            }
          },
          "required": [
            "action",
            "kind",
            "preparation"
          ]
        }
      ]
    },
    "CompanyRickyProposalGetRequest": {
      "type": "object",
      "properties": {
        "company": {
          "type": "string",
          "minLength": 1,
          "maxLength": 140
        },
        "proposal_id": {
          "type": "string",
          "format": "uuid",
          "minLength": 36,
          "maxLength": 36
        }
      },
      "required": [
        "company",
        "proposal_id"
      ],
      "additionalProperties": false
    }
  }
} as const;
