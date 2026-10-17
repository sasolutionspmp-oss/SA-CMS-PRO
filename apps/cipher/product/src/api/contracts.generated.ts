/* Generated from cipher_aec/api/schema.json. Do not edit.
 * Source SHA-256: 3122fc1e7a4fd299cafd34a280b1d56322a1d9e1a58f2c0df47d0558933ca873
 * Regenerate: npm run generate:api
 */

/**
 * Frappe message contains schema/data/meta; errors contain schema/error/meta. POST Idempotency-Key must equal operation_id and X-Frappe-CSRF-Token is required for authenticated session commands.
 */
export type CipherAPIV1 = {
  schema: "cipher.api.v1";
  request_id: string;
  meta: Meta;
  data?: unknown;
  error?: Error;
  [k: string]: unknown;
} & {
  [k: string]: unknown;
};
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ApprovalPacket".
 */
export type ApprovalPacket =
  | ProjectStatusApprovalPacket
  | DomainApprovalPacket
  | EngineeringApprovalPacket
  | EngineeringPackageApprovalPacket
  | DocumentApprovalPacket;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringApprovalPacket".
 */
export type EngineeringApprovalPacket =
  EngineeringResponseApprovalPacket | EngineeringDispositionApprovalPacket | EngineeringTransmittalApprovalPacket;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringPackageApprovalPacket".
 */
export type EngineeringPackageApprovalPacket =
  | EngineeringPackageBasisApprovalPacket
  | EngineeringPackageCalculationApprovalPacket
  | EngineeringPackageDeliverableApprovalPacket;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCanonicaluuid".
 */
export type EpCanonicaluuid = string;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentApprovalPacket".
 */
export type DocumentApprovalPacket =
  | DocumentIssueSetApprovalPacket
  | DocumentAdoptionRequestApprovalPacket
  | DocumentTransmittalApprovalPacket
  | DocumentRedlineApprovalPacket
  | DocumentSharedAdoptionRequestApprovalPacket
  | DocumentLifecycleRequestApprovalPacket;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseTarget".
 */
export type DcClauseTarget =
  | {
      id: string;
      kind: "proposal_revision";
      locator: string;
      record_digest: string;
    }
  | {
      id: string;
      kind: "contract_revision";
      locator: string;
      record_digest: string;
    }
  | {
      id: string;
      kind: "document_revision";
      locator: string;
      record_digest: string;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseTargetSnapshot".
 */
export type DcClauseTargetSnapshot =
  | {
      company: string;
      id: string;
      kind: "proposal_revision";
      parent_id: string;
      project: null;
      record_digest: string;
      scope_type: "Company";
    }
  | {
      company: string;
      id: string;
      kind: "contract_revision";
      parent_id: string;
      project: string;
      record_digest: string;
      scope_type: "Project";
    }
  | {
      company: string;
      id: string;
      kind: "document_revision";
      parent_id: string;
      project: string;
      record_digest: string;
      scope_type: "Project";
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLibraryScope".
 */
export type DcLibraryScope =
  | {
      project: null;
      scope_type: "Company";
    }
  | {
      project: string;
      scope_type: "Project";
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLifecycleDefinition".
 */
export type DcLifecycleDefinition = {
  action: "withdraw" | "supersede";
  issue_digest: string;
  issue_id: string;
  reason: string;
  replacement_issue_digest: string | null;
  replacement_issue_id: string | null;
} & DcLifecycleDefinition1;
export type DcLifecycleDefinition1 =
  | {
      action?: "withdraw";
      replacement_issue_digest?: null;
      replacement_issue_id?: null;
      [k: string]: unknown;
    }
  | {
      action?: "supersede";
      replacement_issue_digest?: string;
      replacement_issue_id?: string;
      [k: string]: unknown;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ApprovalExecutionResponse".
 */
export type ApprovalExecutionResponse =
  | ProjectStatusApprovalExecutionResponse
  | DomainApprovalExecutionResponse
  | EngineeringApprovalExecutionResponse
  | EngineeringPackageApprovalExecutionResponse
  | DocumentApprovalExecutionResponse;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringApprovalExecutionResponse".
 */
export type EngineeringApprovalExecutionResponse =
  | {
      packet: EngineeringResponseApprovalPacket;
      effect: {
        official_response: EgOfficialResponse;
      };
      operation: Operation;
    }
  | {
      packet: EngineeringDispositionApprovalPacket;
      effect: {
        official_disposition: EgOfficialDisposition;
      };
      operation: Operation;
    }
  | {
      packet: EngineeringTransmittalApprovalPacket;
      effect: {
        distribution: EgDistribution;
      };
      operation: Operation;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringPackageApprovalExecutionResponse".
 */
export type EngineeringPackageApprovalExecutionResponse =
  | {
      packet: EngineeringPackageBasisApprovalPacket;
      effect: {
        check: EpCheck;
      };
      operation: Operation;
    }
  | {
      packet: EngineeringPackageCalculationApprovalPacket;
      effect: {
        check: EpCheck;
      };
      operation: Operation;
    }
  | {
      packet: EngineeringPackageDeliverableApprovalPacket;
      effect: {
        check: EpCheck;
      };
      operation: Operation;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentApprovalExecutionResponse".
 */
export type DocumentApprovalExecutionResponse =
  | {
      effect: {
        issue: DcIssue;
      };
      operation: Operation;
      packet: DocumentIssueSetApprovalPacket;
    }
  | {
      effect: {
        adoption: DcAdoption;
      };
      operation: Operation;
      packet: DocumentAdoptionRequestApprovalPacket;
    }
  | {
      effect: {
        distribution: DcDistribution;
      };
      operation: Operation;
      packet: DocumentTransmittalApprovalPacket;
    }
  | {
      effect: {
        clause_application: DcClauseApplication;
      };
      operation: Operation;
      packet: DocumentRedlineApprovalPacket;
    }
  | {
      effect: {
        adoption: DcAdoption;
      };
      operation: Operation;
      packet: DocumentSharedAdoptionRequestApprovalPacket;
    }
  | {
      effect: {
        lifecycle: DcLifecycle;
      };
      operation: Operation;
      packet: DocumentLifecycleRequestApprovalPacket;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseTargetKind".
 */
export type DcClauseTargetKind = "proposal_revision" | "contract_revision" | "document_revision";
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyRecord".
 */
export type DcCompanyRecord = DcCompanyRights | DcCompanyLibrary | DcCompanyLibraryRevision;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRecord".
 */
export type DcRecord =
  | DcRights
  | DcLibrary
  | DcLibraryRevision
  | DcAdoptionRequest
  | DcAdoption
  | DcIssueSet
  | DcIssue
  | DcTransmittal
  | DcDistribution
  | DcEvidence
  | DcClauseUse
  | DcRedline
  | DcClauseApplication
  | DcSharedAdoptionRequest
  | DcLifecycleRequest
  | DcLifecycle;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcReadClauseTargetRequest".
 */
export type DcReadClauseTargetRequest =
  | {
      company: string;
      kind: "proposal_revision";
      project: string;
      record_id: string;
    }
  | {
      company: string;
      kind: "contract_revision";
      project: string;
      record_id: string;
    }
  | {
      company: string;
      kind: "document_revision";
      project: string;
      record_id: string;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticScope".
 */
export type SemanticScope =
  | {
      company: string;
      scope_type: "Company";
      project: null;
    }
  | {
      company: string;
      scope_type: "Project";
      project: string;
    };
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticSource".
 */
export type SemanticSource =
  | {
      document_id: string;
      revision_id: string;
      source_sha256: string;
      selection: "working" | "issued";
      adoption_id: null;
      adoption_digest: null;
    }
  | {
      document_id: string;
      revision_id: string;
      source_sha256: string;
      selection: "adopted";
      adoption_id: string;
      adoption_digest: string;
    };

/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Meta".
 */
export interface Meta {
  request_id: string;
  api_version: "v1";
  server_time: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Error".
 */
export interface Error {
  code: string;
  message: string;
  details: {
    [k: string]: unknown;
  };
  retryable: boolean;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Person".
 */
export interface Person {
  id: string;
  display_name: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Company".
 */
export interface Company {
  id: string;
  name: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Session".
 */
export interface Session {
  authenticated: true;
  user: string;
  person: Person;
  companies: Company[];
  capabilities: string[];
  site_mode: "synthetic";
  csrf_token: string;
  company_scopes: {
    company: string;
    capabilities: string[];
  }[];
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Project".
 */
export interface Project {
  id: string;
  name: string;
  company: string;
  status: string;
  version: string;
  expected_start_date: string | null;
  expected_end_date: string | null;
  capabilities?: string[];
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Task".
 */
export interface Task {
  id: string;
  subject: string;
  status: string;
  project: string;
  version: string;
  description: string;
  /**
   * Current reads and new commands supply canonical active assignees. Historical immutable receipts may omit this additive field.
   */
  assignees?: Person[];
  /**
   * Current native assignment reconciliation state; historical immutable receipts may omit this additive field.
   */
  assignment_conflict?: boolean;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "HistoryItem".
 */
export interface HistoryItem {
  id: string;
  event: string;
  actor: string;
  at: string;
  subject_type: string;
  subject_id: string;
  details: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Operation".
 */
export interface Operation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CreateTaskRequest".
 */
export interface CreateTaskRequest {
  company: string;
  project: string;
  operation_id: string;
  expected_version: string;
  subject: string;
  description?: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CreateTaskResponse".
 */
export interface CreateTaskResponse {
  task: Task;
  operation: Operation;
  project_version: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "Money".
 */
export interface Money {
  amount: string;
  currency: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ProjectList".
 */
export interface ProjectList {
  items: Project[];
  total: number | null;
  limit: number;
  next_cursor: string | null;
  count_mode: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "TaskList".
 */
export interface TaskList {
  items: Task[];
  total: number | null;
  limit: number;
  next_cursor: string | null;
  count_mode: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "HistoryList".
 */
export interface HistoryList {
  items: HistoryItem[];
  total: number | null;
  limit: number;
  next_cursor: string | null;
  count_mode: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ApprovalDecision".
 */
export interface ApprovalDecision {
  id: string;
  decision: "Grant" | "Reject" | "Withdraw";
  actor: Person;
  at: string;
  reason: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ProjectStatusApprovalPacket".
 */
export interface ProjectStatusApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "project.status.change.v1";
  subject: {
    id: string;
    type: "Project";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  changes: {
    status: {
      from: string;
      to: string;
    };
  };
  native_completion: {
    percent_complete_method: string | null;
    percent_complete: string;
  };
  task_effects: {
    count: number;
    /**
     * @maxItems 0
     */
    changes: [];
  };
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DomainApprovalPacket".
 */
export interface DomainApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "calibration.verify.v1" | "contract.baseline.activate.v1" | "estimate.accept.v1";
  subject: {
    id: string;
    type: "Cipher Calibration" | "Cipher Construction Contract" | "Cipher Estimate Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: string;
      name: string;
      label: string;
    };
    sources: {
      [k: string]: unknown;
    }[];
    effect: {
      [k: string]: unknown;
    };
    summary: {
      [k: string]: unknown;
    };
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringResponseApprovalPacket".
 */
export interface EngineeringResponseApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "engineering.rfi.authorize.v1";
  subject: {
    id: string;
    type: "Cipher RFI Response Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: "Cipher RFI Response Revision";
      name: string;
      label: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 0
         * @maxItems 64
         */
        source_citations: EgCitation[];
        /**
         * @minItems 0
         * @maxItems 8
         */
        artifacts:
          | []
          | [EgArtifact]
          | [EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
        /**
         * @minItems 0
         * @maxItems 16
         */
        drawing_references:
          | []
          | [EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ];
      }
    ];
    effect: {
      schema: "cipher.engineering.authorization.v1";
      action: "engineering.rfi.authorize.v1";
      subject_kind: "response";
      subject_id: string;
      subject_digest: string;
      parent_id: string;
      source_revision: string;
      source_digest: string;
      /**
       * @minItems 1
       * @maxItems 2
       */
      author_people: [string] | [string, string];
    };
    summary: {
      schema: "cipher.engineering.review.v1";
      definition: EgResponseDefinition;
      purpose: null;
      no_effects: EgNoEffects;
      professional_seal: false;
      external_delivery: false;
    };
  };
  schema: "cipher.engineering.approval.v1";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgCitation".
 */
export interface EgCitation {
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
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgArtifact".
 */
export interface EgArtifact {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgDrawingReference".
 */
export interface EgDrawingReference {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: "application/pdf";
  page_count: number;
  page: number;
  locator: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgResponseDefinition".
 */
export interface EgResponseDefinition {
  answer: string;
  potential_cost_impact: string;
  potential_schedule_impact: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgNoEffects".
 */
export interface EgNoEffects {
  commercial_change: false;
  contract_change: false;
  budget_change: false;
  schedule_change: false;
  quality_acceptance: false;
  professional_certification: false;
  external_transmission: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringDispositionApprovalPacket".
 */
export interface EngineeringDispositionApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "engineering.submittal.authorize.v1";
  subject: {
    id: string;
    type: "Cipher Submittal Disposition Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: "Cipher Submittal Disposition Revision";
      name: string;
      label: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 0
         * @maxItems 64
         */
        source_citations: EgCitation[];
        /**
         * @minItems 0
         * @maxItems 8
         */
        artifacts:
          | []
          | [EgArtifact]
          | [EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
        /**
         * @minItems 0
         * @maxItems 16
         */
        drawing_references:
          | []
          | [EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ];
      }
    ];
    effect: {
      schema: "cipher.engineering.authorization.v1";
      action: "engineering.submittal.authorize.v1";
      subject_kind: "disposition";
      subject_id: string;
      subject_digest: string;
      parent_id: string;
      source_revision: string;
      source_digest: string;
      /**
       * @minItems 1
       * @maxItems 2
       */
      author_people: [string] | [string, string];
    };
    summary: {
      schema: "cipher.engineering.review.v1";
      definition: EgDispositionDefinition;
      purpose: null;
      no_effects: EgNoEffects;
      professional_seal: false;
      external_delivery: false;
    };
  };
  schema: "cipher.engineering.approval.v1";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgDispositionDefinition".
 */
export interface EgDispositionDefinition {
  disposition: "approved" | "approved_as_noted" | "revise_resubmit" | "rejected";
  comments: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringTransmittalApprovalPacket".
 */
export interface EngineeringTransmittalApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "engineering.distribute.v1";
  subject: {
    id: string;
    type: "Cipher Engineering Transmittal";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: "Cipher Engineering Transmittal";
      name: string;
      label: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 0
         * @maxItems 64
         */
        source_citations: EgCitation[];
        /**
         * @minItems 0
         * @maxItems 8
         */
        artifacts:
          | []
          | [EgArtifact]
          | [EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact]
          | [EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact, EgArtifact];
        /**
         * @minItems 0
         * @maxItems 16
         */
        drawing_references:
          | []
          | [EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference, EgDrawingReference]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ]
          | [
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference,
              EgDrawingReference
            ];
      }
    ];
    effect: {
      schema: "cipher.engineering.authorization.v1";
      action: "engineering.distribute.v1";
      subject_kind: "transmittal";
      subject_id: string;
      subject_digest: string;
      package_digest: string;
      /**
       * @minItems 1
       * @maxItems 30
       */
      recipients: [EgPerson, ...EgPerson[]];
      channel: "internal";
    };
    summary: {
      schema: "cipher.engineering.review.v1";
      definition: null;
      purpose: string;
      no_effects: EgNoEffects;
      professional_seal: false;
      external_delivery: false;
    };
  };
  schema: "cipher.engineering.approval.v1";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgPerson".
 */
export interface EgPerson {
  user: string;
  person: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringPackageBasisApprovalPacket".
 */
export interface EngineeringPackageBasisApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "engineering.basis.check.v1";
  subject: {
    id: string;
    type: "Cipher Design Basis Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: "Cipher Design Basis Revision";
      name: string;
      label: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 0
         * @maxItems 64
         */
        source_citations: EpCitation[];
        /**
         * @minItems 0
         * @maxItems 16
         */
        drawing_references:
          | []
          | [EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ];
        /**
         * @minItems 0
         * @maxItems 8
         */
        artifacts:
          | []
          | [EpArtifact]
          | [EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact];
        unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1 | null;
      }
    ];
    effect: {
      schema: "cipher.engineering.package-check.v1";
      action: "engineering.basis.check.v1";
      subject_kind: "basis";
      subject_id: string;
      subject_digest: string;
      parent_id: string;
      package_revision: string;
      package_digest: string;
      preparer_person: string;
      checker: EpPerson;
      outcome: "checked";
      issue_authorized: false;
      sealed: false;
    };
    summary: {
      definition: EpBasisDefinition;
      /**
       * @minItems 0
       * @maxItems 32
       */
      inputs: EpQuantityRow[];
      /**
       * @minItems 0
       * @maxItems 32
       */
      outputs: EpQuantityRow[];
      /**
       * @minItems 0
       * @maxItems 8
       */
      calculations:
        | []
        | [EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference, EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference, EpCalculationReference, EpCalculationReference]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ];
      no_effects: EpNoEffects;
      solver_executed: false;
      issue_authorized: false;
      sealed: false;
    };
  };
  schema: "cipher.engineering.package-approval.v1";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCitation".
 */
export interface EpCitation {
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
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpDrawingReference".
 */
export interface EpDrawingReference {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: "application/pdf";
  page_count: number;
  page: number;
  locator: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpArtifact".
 */
export interface EpArtifact {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpUnitManifest".
 */
export interface CipherIndependentCanonicalMasterDimensionManifestV1 {
  schema: "cipher.canonical.v1";
  dataset_id: EpCanonicaluuid;
  scope: {
    company: string;
    project: string;
  };
  label?: string;
  /**
   * @minItems 1
   * @maxItems 65
   */
  records: [
    (
      | {
          id: EpCanonicaluuid;
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
          id: EpCanonicaluuid;
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
    ),
    ...(
      | {
          id: EpCanonicaluuid;
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
          id: EpCanonicaluuid;
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
    )[]
  ];
  /**
   * @maxItems 0
   */
  unit_conversions: [];
  /**
   * @maxItems 500
   */
  quantities?: EpCanonicalquantity[];
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCanonicalquantity".
 */
export interface EpCanonicalquantity {
  id: EpCanonicaluuid;
  amount: string;
  unit_id: EpCanonicaluuid;
  convert_to_unit_id?: EpCanonicaluuid;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpPerson".
 */
export interface EpPerson {
  user: string;
  person: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpBasisDefinition".
 */
export interface EpBasisDefinition {
  title: string;
  criteria: string;
  assumptions: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  design_codes:
    | []
    | [EpCode]
    | [EpCode, EpCode]
    | [EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode, EpCode, EpCode, EpCode];
  change_reason: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCode".
 */
export interface EpCode {
  code: string;
  edition: string;
  clause: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpQuantityRow".
 */
export interface EpQuantityRow {
  key: string;
  label: string;
  quantity: EpQuantity;
  source: EpDrawingInput;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpQuantity".
 */
export interface EpQuantity {
  amount: string;
  unit_id: string;
  precision: number;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpDrawingInput".
 */
export interface EpDrawingInput {
  revision_id: string;
  source_sha256: string;
  page: number;
  locator: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCalculationReference".
 */
export interface EpCalculationReference {
  id: string;
  record_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpNoEffects".
 */
export interface EpNoEffects {
  commercial_change: false;
  contract_change: false;
  budget_change: false;
  schedule_change: false;
  quality_acceptance: false;
  professional_certification: false;
  external_transmission: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringPackageCalculationApprovalPacket".
 */
export interface EngineeringPackageCalculationApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "engineering.calculation.check.v1";
  subject: {
    id: string;
    type: "Cipher Calculation Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: "Cipher Calculation Revision";
      name: string;
      label: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 0
         * @maxItems 64
         */
        source_citations: EpCitation[];
        /**
         * @minItems 0
         * @maxItems 16
         */
        drawing_references:
          | []
          | [EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ];
        /**
         * @minItems 0
         * @maxItems 8
         */
        artifacts:
          | []
          | [EpArtifact]
          | [EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact];
        unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1 | null;
      }
    ];
    effect: {
      schema: "cipher.engineering.package-check.v1";
      action: "engineering.calculation.check.v1";
      subject_kind: "calculation";
      subject_id: string;
      subject_digest: string;
      parent_id: string;
      package_revision: string;
      package_digest: string;
      preparer_person: string;
      checker: EpPerson;
      outcome: "checked";
      issue_authorized: false;
      sealed: false;
    };
    summary: {
      definition: EpCalculationDefinition;
      /**
       * @minItems 0
       * @maxItems 32
       */
      inputs: EpQuantityRow[];
      /**
       * @minItems 0
       * @maxItems 32
       */
      outputs: EpQuantityRow[];
      /**
       * @minItems 0
       * @maxItems 8
       */
      calculations:
        | []
        | [EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference, EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference, EpCalculationReference, EpCalculationReference]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ];
      no_effects: EpNoEffects;
      solver_executed: false;
      issue_authorized: false;
      sealed: false;
    };
  };
  schema: "cipher.engineering.package-approval.v1";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCalculationDefinition".
 */
export interface EpCalculationDefinition {
  title: string;
  method: "human-authored-results-v1";
  algorithm_reference: string;
  tool_name: string;
  tool_version: string;
  model_version: string;
  /**
   * @minItems 0
   * @maxItems 8
   */
  design_codes:
    | []
    | [EpCode]
    | [EpCode, EpCode]
    | [EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode, EpCode, EpCode]
    | [EpCode, EpCode, EpCode, EpCode, EpCode, EpCode, EpCode, EpCode];
  explanation: string;
  change_reason: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EngineeringPackageDeliverableApprovalPacket".
 */
export interface EngineeringPackageDeliverableApprovalPacket {
  id: string;
  company: string;
  project: string;
  action: "engineering.deliverable.check.v1";
  subject: {
    id: string;
    type: "Cipher Deliverable Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: "Cipher Deliverable Revision";
      name: string;
      label: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 0
         * @maxItems 64
         */
        source_citations: EpCitation[];
        /**
         * @minItems 0
         * @maxItems 16
         */
        drawing_references:
          | []
          | [EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference, EpDrawingReference]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ]
          | [
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference,
              EpDrawingReference
            ];
        /**
         * @minItems 0
         * @maxItems 8
         */
        artifacts:
          | []
          | [EpArtifact]
          | [EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact]
          | [EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact, EpArtifact];
        unit_manifest: CipherIndependentCanonicalMasterDimensionManifestV1 | null;
      }
    ];
    effect: {
      schema: "cipher.engineering.package-check.v1";
      action: "engineering.deliverable.check.v1";
      subject_kind: "deliverable";
      subject_id: string;
      subject_digest: string;
      parent_id: string;
      package_revision: string;
      package_digest: string;
      preparer_person: string;
      checker: EpPerson;
      outcome: "checked";
      issue_authorized: false;
      sealed: false;
    };
    summary: {
      definition: EpDeliverableDefinition;
      /**
       * @minItems 0
       * @maxItems 32
       */
      inputs: EpQuantityRow[];
      /**
       * @minItems 0
       * @maxItems 32
       */
      outputs: EpQuantityRow[];
      /**
       * @minItems 0
       * @maxItems 8
       */
      calculations:
        | []
        | [EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference, EpCalculationReference]
        | [EpCalculationReference, EpCalculationReference, EpCalculationReference, EpCalculationReference]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ]
        | [
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference,
            EpCalculationReference
          ];
      no_effects: EpNoEffects;
      solver_executed: false;
      issue_authorized: false;
      sealed: false;
    };
  };
  schema: "cipher.engineering.package-approval.v1";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpDeliverableDefinition".
 */
export interface EpDeliverableDefinition {
  title: string;
  deliverable_type: string;
  description: string;
  checking_notes: string;
  change_reason: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentIssueSetApprovalPacket".
 */
export interface DocumentIssueSetApprovalPacket {
  action: "document.issue.v1";
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  company: string;
  created_at: string;
  decisions: ApprovalDecision[];
  expires_at: string;
  id: string;
  manifest_hash: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  project: string;
  requester: Person;
  review_manifest: {
    effect: {
      action: "document.issue.v1";
      /**
       * @minItems 0
       * @maxItems 8
       */
      adoptions:
        | []
        | [DcExactReference]
        | [DcExactReference, DcExactReference]
        | [DcExactReference, DcExactReference, DcExactReference]
        | [DcExactReference, DcExactReference, DcExactReference, DcExactReference]
        | [DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference]
        | [DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference]
        | [
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference
          ]
        | [
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference,
            DcExactReference
          ];
      /**
       * @minItems 1
       * @maxItems 8
       */
      artifacts:
        | [DcArtifact]
        | [DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
      commercial_execution: false;
      electronic_signature: false;
      external_delivery: false;
      no_effects: DcNoEffects;
      package_digest: string;
      professional_seal: false;
      schema: "cipher.document.authorization.v1";
      subject_digest: string;
      subject_id: string;
      subject_kind: "issue_set";
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 1
         * @maxItems 8
         */
        artifacts:
          | [DcArtifact]
          | [DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
        /**
         * @minItems 1
         * @maxItems 8
         */
        rights:
          | [DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ];
      }
    ];
    subject: {
      doctype: "Cipher Document Issue Set";
      label: string;
      name: string;
    };
    summary: {
      commercial_execution: false;
      definition: DcIssueDefinition;
      external_delivery: false;
      no_effects: DcNoEffects;
      purpose: null;
      required_response: null;
      rights_basis: "authored-declaration";
    };
  };
  schema: "cipher.document.approval.v1";
  source_version: string;
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  subject: {
    id: string;
    label: string;
    type: "Cipher Document Issue Set";
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcExactReference".
 */
export interface DcExactReference {
  id: string;
  record_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcArtifact".
 */
export interface DcArtifact {
  document_id: string;
  revision_id: string;
  revision_number: number;
  source_sha256: string;
  byte_length: number;
  mime_type: string;
  page_count: number;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcNoEffects".
 */
export interface DcNoEffects {
  commercial_change: false;
  contract_change: false;
  budget_change: false;
  schedule_change: false;
  quality_acceptance: false;
  professional_certification: false;
  external_transmission: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRights".
 */
export interface DcRights {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "authored_rights_basis";
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  revision_number: number;
  ingest_allowed: boolean;
  read_allowed: boolean;
  distribute_allowed: boolean;
  rights_basis: string;
  rights_holder: string;
  allowed_purpose: string;
  restriction: string;
  valid_from: string | null;
  valid_until: string | null;
  evidence_artifact: DcArtifact;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyRights".
 */
export interface DcCompanyRights {
  allowed_purpose: string;
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  distribute_allowed: boolean;
  evidence_artifact: DcArtifact;
  id: string;
  ingest_allowed: boolean;
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  project: null;
  read_allowed: boolean;
  restriction: string;
  revision_number: number;
  rights_basis: string;
  rights_holder: string;
  scope_type: "Company";
  status: "authored_rights_basis";
  valid_from: string | null;
  valid_until: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssueDefinition".
 */
export interface DcIssueDefinition {
  title: string;
  purpose: string;
  issue_purpose: "coordination" | "information" | "review" | "contract_reference";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentAdoptionRequestApprovalPacket".
 */
export interface DocumentAdoptionRequestApprovalPacket {
  action: "document.library.adopt.v1";
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  company: string;
  created_at: string;
  decisions: ApprovalDecision[];
  expires_at: string;
  id: string;
  manifest_hash: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  project: string;
  requester: Person;
  review_manifest: {
    effect: {
      action: "document.library.adopt.v1";
      /**
       * @minItems 1
       * @maxItems 8
       */
      artifacts:
        | [DcArtifact]
        | [DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
      commercial_execution: false;
      electronic_signature: false;
      external_delivery: false;
      library_digest: string;
      library_revision: string;
      no_effects: DcNoEffects;
      professional_seal: false;
      schema: "cipher.document.authorization.v1";
      subject_digest: string;
      subject_id: string;
      subject_kind: "adoption_request";
      target_locator: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 1
         * @maxItems 8
         */
        artifacts:
          | [DcArtifact]
          | [DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
        /**
         * @minItems 1
         * @maxItems 8
         */
        rights:
          | [DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ];
      }
    ];
    subject: {
      doctype: "Cipher Adoption Request";
      label: string;
      name: string;
    };
    summary: {
      commercial_execution: false;
      definition: DcAdoptionDefinition;
      external_delivery: false;
      no_effects: DcNoEffects;
      purpose: null;
      required_response: null;
      rights_basis: "authored-declaration";
    };
  };
  schema: "cipher.document.approval.v1";
  source_version: string;
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  subject: {
    id: string;
    label: string;
    type: "Cipher Adoption Request";
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcAdoptionDefinition".
 */
export interface DcAdoptionDefinition {
  purpose: string;
  target_locator: string;
  change_reason: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentTransmittalApprovalPacket".
 */
export interface DocumentTransmittalApprovalPacket {
  action: "document.transmit.v1";
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  company: string;
  created_at: string;
  decisions: ApprovalDecision[];
  expires_at: string;
  id: string;
  manifest_hash: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  project: string;
  requester: Person;
  review_manifest: {
    effect: {
      action: "document.transmit.v1";
      /**
       * @minItems 1
       * @maxItems 8
       */
      artifacts:
        | [DcArtifact]
        | [DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
      channel: "internal";
      commercial_execution: false;
      electronic_signature: false;
      external_delivery: false;
      no_effects: DcNoEffects;
      package_digest: string;
      professional_seal: false;
      /**
       * @minItems 1
       * @maxItems 30
       */
      recipients: [DcPerson, ...DcPerson[]];
      schema: "cipher.document.authorization.v1";
      subject_digest: string;
      subject_id: string;
      subject_kind: "transmittal";
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 1
         * @maxItems 8
         */
        artifacts:
          | [DcArtifact]
          | [DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
        /**
         * @minItems 1
         * @maxItems 8
         */
        rights:
          | [DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ];
      }
    ];
    subject: {
      doctype: "Cipher Transmittal";
      label: string;
      name: string;
    };
    summary: {
      commercial_execution: false;
      definition: null;
      external_delivery: false;
      no_effects: DcNoEffects;
      purpose: string;
      required_response: string;
      rights_basis: "authored-declaration";
    };
  };
  schema: "cipher.document.approval.v1";
  source_version: string;
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  subject: {
    id: string;
    label: string;
    type: "Cipher Transmittal";
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcPerson".
 */
export interface DcPerson {
  user: string;
  person: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentRedlineApprovalPacket".
 */
export interface DocumentRedlineApprovalPacket {
  action: "document.clause.apply.v1";
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  company: string;
  created_at: string;
  decisions: ApprovalDecision[];
  expires_at: string;
  id: string;
  manifest_hash: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  project: string;
  requester: Person;
  review_manifest: {
    effect: {
      action: "document.clause.apply.v1";
      /**
       * @minItems 1
       * @maxItems 8
       */
      artifacts:
        | [DcArtifact]
        | [DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
      commercial_execution: false;
      electronic_signature: false;
      external_delivery: false;
      no_effects: DcNoEffects;
      original_text: string;
      professional_seal: false;
      proposed_sha256: string;
      proposed_text: string;
      schema: "cipher.document.authorization.v1";
      subject_digest: string;
      subject_id: string;
      subject_kind: "redline";
      target: DcClauseTarget;
      target_changed: false;
      target_snapshot: DcClauseTargetSnapshot;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 1
         * @maxItems 8
         */
        artifacts:
          | [DcArtifact]
          | [DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
        /**
         * @minItems 1
         * @maxItems 8
         */
        rights:
          | [DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ];
      }
    ];
    subject: {
      doctype: "Cipher Redline Revision";
      label: string;
      name: string;
    };
    summary: {
      commercial_execution: false;
      definition: null;
      external_delivery: false;
      no_effects: DcNoEffects;
      purpose: null;
      required_response: null;
      rights_basis: "authored-declaration";
    };
  };
  schema: "cipher.document.approval.v1";
  source_version: string;
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  subject: {
    id: string;
    label: string;
    type: "Cipher Redline Revision";
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentSharedAdoptionRequestApprovalPacket".
 */
export interface DocumentSharedAdoptionRequestApprovalPacket {
  action: "document.library.adopt.v1";
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  company: string;
  created_at: string;
  decisions: ApprovalDecision[];
  expires_at: string;
  id: string;
  manifest_hash: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  project: string;
  requester: Person;
  review_manifest: {
    effect: {
      action: "document.library.adopt.v1";
      /**
       * @minItems 1
       * @maxItems 8
       */
      artifacts:
        | [DcArtifact]
        | [DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
      commercial_execution: false;
      electronic_signature: false;
      external_delivery: false;
      library_digest: string;
      library_revision: string;
      library_scope: DcLibraryScope;
      no_effects: DcNoEffects;
      professional_seal: false;
      schema: "cipher.document.authorization.v1";
      subject_digest: string;
      subject_id: string;
      subject_kind: "adoption_request";
      target_locator: string;
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 1
         * @maxItems 8
         */
        artifacts:
          | [DcArtifact]
          | [DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
        /**
         * @minItems 1
         * @maxItems 8
         */
        rights:
          | [DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ];
      }
    ];
    subject: {
      doctype: "Cipher Adoption Request";
      label: string;
      name: string;
    };
    summary: {
      commercial_execution: false;
      definition: DcAdoptionDefinition;
      external_delivery: false;
      no_effects: DcNoEffects;
      purpose: null;
      required_response: null;
      rights_basis: "authored-declaration";
    };
  };
  schema: "cipher.document.approval.v1";
  source_version: string;
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  subject: {
    id: string;
    label: string;
    type: "Cipher Adoption Request";
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DocumentLifecycleRequestApprovalPacket".
 */
export interface DocumentLifecycleRequestApprovalPacket {
  action: "document.lifecycle.v1";
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  company: string;
  created_at: string;
  decisions: ApprovalDecision[];
  expires_at: string;
  id: string;
  manifest_hash: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  project: string;
  requester: Person;
  review_manifest: {
    effect: {
      action: "document.lifecycle.v1";
      /**
       * @minItems 1
       * @maxItems 16
       */
      artifacts:
        | [DcArtifact]
        | [DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ]
        | [
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact,
            DcArtifact
          ];
      before: DcIssuedStandingBody;
      commercial_execution: false;
      definition: DcLifecycleDefinition;
      document_id: string;
      electronic_signature: false;
      expected_version: string;
      external_delivery: false;
      no_effects: DcNoEffects;
      professional_seal: false;
      replacement: DcIssueReference | null;
      schema: "cipher.document.authorization.v1";
      subject_digest: string;
      subject_id: string;
      subject_kind: "lifecycle_request";
    };
    /**
     * @minItems 1
     * @maxItems 1
     */
    sources: [
      {
        /**
         * @minItems 1
         * @maxItems 16
         */
        artifacts:
          | [DcArtifact]
          | [DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ]
          | [
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact,
              DcArtifact
            ];
        /**
         * @minItems 1
         * @maxItems 16
         */
        rights:
          | [DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [DcRights | DcCompanyRights, DcRights | DcCompanyRights, DcRights | DcCompanyRights]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ]
          | [
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights,
              DcRights | DcCompanyRights
            ];
      }
    ];
    subject: {
      doctype: "Cipher Document Lifecycle Request";
      label: string;
      name: string;
    };
    summary: {
      commercial_execution: false;
      definition: DcLifecycleDefinition;
      external_delivery: false;
      no_effects: DcNoEffects;
      purpose: null;
      required_response: null;
      rights_basis: "authored-declaration";
    };
  };
  schema: "cipher.document.approval.v1";
  source_version: string;
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  subject: {
    id: string;
    label: string;
    type: "Cipher Document Lifecycle Request";
  };
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssuedStandingBody".
 */
export interface DcIssuedStandingBody {
  company: string;
  current_issued: DcIssueReference | null;
  document_id: string;
  last_event: DcLifecycleEventReference | null;
  original_issued: DcIssueReference | null;
  project: string;
  scope_type: "Project";
  status: "not_issued" | "issued" | "withdrawn";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssueReference".
 */
export interface DcIssueReference {
  issue_digest: string;
  issue_id: string;
  revision_id: string;
  source_sha256: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLifecycleEventReference".
 */
export interface DcLifecycleEventReference {
  id: string;
  record_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ApprovalList".
 */
export interface ApprovalList {
  items: ApprovalPacket[];
  total: number | null;
  limit: number;
  next_cursor: string | null;
  count_mode: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ApprovalCommandResponse".
 */
export interface ApprovalCommandResponse {
  packet: ApprovalPacket;
  operation: Operation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ProjectStatusApprovalExecutionResponse".
 */
export interface ProjectStatusApprovalExecutionResponse {
  packet: ProjectStatusApprovalPacket;
  effect: {
    project: Project;
  };
  operation: Operation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DomainApprovalExecutionResponse".
 */
export interface DomainApprovalExecutionResponse {
  packet: DomainApprovalPacket;
  effect: {
    [k: string]: unknown;
  };
  operation: Operation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgOfficialResponse".
 */
export interface EgOfficialResponse {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "official";
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  no_effects: EgNoEffects;
  authority: "internal-technical-only";
  parent_id: string;
  source_revision: string;
  source_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgOfficialDisposition".
 */
export interface EgOfficialDisposition {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "official";
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  no_effects: EgNoEffects;
  authority: "internal-technical-only";
  parent_id: string;
  source_revision: string;
  source_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EgDistribution".
 */
export interface EgDistribution {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded_internally";
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  no_effects: EgNoEffects;
  authority: "internal-technical-only";
  package_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [EgPerson, ...EgPerson[]];
  channel: "internal";
  external_delivery: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCheck".
 */
export interface EpCheck {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "checked";
  no_effects: EpNoEffects;
  parent_id: string;
  subject_kind: "basis" | "calculation" | "deliverable";
  subject_id: string;
  subject_digest: string;
  package_revision: string;
  package_digest: string;
  checker: EpPerson;
  preparer_person: string;
  packet_id: string;
  decision_id: string;
  comments: string;
  outcome: "checked";
  issue_authorized: false;
  sealed: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssue".
 */
export interface DcIssue {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "issued";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
  package_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcAdoption".
 */
export interface DcAdoption {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "adopted";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcDistribution".
 */
export interface DcDistribution {
  id: string;
  company: string;
  project: string;
  scope_type: "Project";
  author_person: string;
  author_user: string;
  created_at: string;
  status: "recorded_internally";
  no_effects: DcNoEffects;
  parent_id: string;
  subject_id: string;
  subject_digest: string;
  packet_id: string;
  decision_id: string;
  checked_by_person: string;
  effect_digest: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
  electronic_signature: false;
  professional_seal: false;
  external_delivery: false;
  commercial_execution: false;
  package_digest: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [DcPerson, ...DcPerson[]];
  channel: "internal";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseApplication".
 */
export interface DcClauseApplication {
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  checked_by_person: string;
  commercial_execution: false;
  company: string;
  created_at: string;
  decision_id: string;
  effect_digest: string;
  electronic_signature: false;
  external_delivery: false;
  id: string;
  no_effects: DcNoEffects;
  original_text: string;
  packet_id: string;
  parent_id: string;
  professional_seal: false;
  project: string;
  proposed_sha256: string;
  proposed_text: string;
  scope_type: "Project";
  status: "approved_relationship";
  subject_digest: string;
  subject_id: string;
  target: DcClauseTarget;
  target_changed: false;
  target_snapshot: DcClauseTargetSnapshot;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLifecycle".
 */
export interface DcLifecycle {
  action: "withdraw" | "supersede";
  /**
   * @minItems 1
   * @maxItems 16
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ];
  author_person: string;
  author_user: string;
  before: DcIssuedStandingBody;
  checked_by_person: string;
  commercial_execution: false;
  company: string;
  created_at: string;
  decision_id: string;
  document_id: string;
  effect_digest: string;
  electronic_signature: false;
  external_delivery: false;
  id: string;
  no_effects: DcNoEffects;
  packet_id: string;
  parent_id: string;
  predecessor: string | null;
  professional_seal: false;
  project: string;
  reason: string;
  replacement: DcIssueReference | null;
  revision_number: number;
  scope_type: "Project";
  status: "withdrawn" | "superseded";
  subject_digest: string;
  subject_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CompanyApprovalPacket".
 */
export interface CompanyApprovalPacket {
  id: string;
  company: string;
  project: null;
  action:
    | "calibration.verify.v1"
    | "estimate.accept.v1"
    | "proposal.issue.v1"
    | "proposal.distribute.v1"
    | "award.project.create.v1";
  subject: {
    id: string;
    type:
      | "Cipher Calibration"
      | "Cipher Estimate Revision"
      | "Cipher Proposal Revision"
      | "Cipher Distribution Instruction"
      | "Cipher Award Handoff Revision";
    label: string;
  };
  requester: Person;
  created_at: string;
  expires_at: string;
  manifest_hash: string;
  source_version: string;
  policy: {
    id: string;
    label: string;
    synthetic: true;
  };
  state: "Pending" | "Granted" | "Rejected" | "Withdrawn" | "Expired" | "Stale" | "Consumed";
  decisions: ApprovalDecision[];
  actions: {
    can_decide: boolean;
    can_execute: boolean;
    can_withdraw: boolean;
    disabled_reason: string | null;
  };
  review_manifest: {
    subject: {
      doctype: string;
      name: string;
      label: string;
    };
    sources: {
      [k: string]: unknown;
    }[];
    effect: {
      [k: string]: unknown;
    };
    summary: {
      [k: string]: unknown;
    };
  };
  scope_type: "Company";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CompanyApprovalList".
 */
export interface CompanyApprovalList {
  items: CompanyApprovalPacket[];
  total: number | null;
  limit: number;
  next_cursor: string | null;
  count_mode: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CompanyApprovalCommandResponse".
 */
export interface CompanyApprovalCommandResponse {
  packet: CompanyApprovalPacket;
  operation: Operation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CompanyApprovalExecutionResponse".
 */
export interface CompanyApprovalExecutionResponse {
  packet: CompanyApprovalPacket;
  effect: {
    [k: string]: unknown;
  };
  operation: Operation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeMasterChoice".
 */
export interface NativeMasterChoice {
  id: string;
  label: string;
  kind: "Customer" | "Lead" | "Price List" | "UOM" | "Currency" | "Item" | "Cost Center" | "Account";
  version: string;
  unit_id?: string;
  revision?: number;
  dimension?: string;
  precision?: number;
  exponent?: number;
  currency?: string;
  stock_uom?: string;
  company?: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeMasterList".
 */
export interface NativeMasterList {
  items: NativeMasterChoice[];
  total: number | null;
  limit: number;
  next_cursor: string | null;
  count_mode: "none" | "exact";
  company_currency: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativePartiesRequest".
 */
export interface NativePartiesRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
  party_type: "Customer" | "Lead";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativePriceListsRequest".
 */
export interface NativePriceListsRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
  currency?: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeUnitsRequest".
 */
export interface NativeUnitsRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
  dimension?: null | "length" | "area" | "volume" | "mass" | "count" | "time" | "labor_time" | "equipment_time";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeCurrenciesRequest".
 */
export interface NativeCurrenciesRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeItemsRequest".
 */
export interface NativeItemsRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
  unit_id?: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeCostCentersRequest".
 */
export interface NativeCostCentersRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeAccountsRequest".
 */
export interface NativeAccountsRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "NativeAwardItemsRequest".
 */
export interface NativeAwardItemsRequest {
  company: string;
  query?: string;
  limit?: number;
  cursor?: string | null;
  count_mode?: "none" | "exact";
  unit_id?: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "EpCanonicalconversion".
 */
export interface EpCanonicalconversion {
  id: EpCanonicaluuid;
  revision: number;
  from_unit_id: EpCanonicaluuid;
  to_unit_id: EpCanonicaluuid;
  dimension: "area" | "count" | "equipment_time" | "labor_time" | "length" | "mass" | "time" | "volume";
  numerator: string;
  denominator: string;
  source: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "TaskChoices".
 */
export interface TaskChoices {
  people: Person[];
  statuses: ("Open" | "Working" | "Pending Review" | "Completed")[];
  capabilities: ("task.assign" | "task.update")[];
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "AssignTaskRequest".
 */
export interface AssignTaskRequest {
  company: string;
  project: string;
  task: string;
  expected_version: string;
  operation_id: string;
  assignee_person: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "UpdateTaskStatusRequest".
 */
export interface UpdateTaskStatusRequest {
  company: string;
  project: string;
  task: string;
  expected_version: string;
  operation_id: string;
  status: "Open" | "Working" | "Pending Review" | "Completed";
}
/**
 * Current Task mutation result. Unlike historical Task receipts, active canonical assignment projection and reconciliation state are always present.
 *
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "CurrentTask".
 */
export interface CurrentTask {
  id: string;
  subject: string;
  status: string;
  project: string;
  version: string;
  description: string;
  /**
   * Current reads and new commands supply canonical active assignees. Historical immutable receipts may omit this additive field.
   */
  assignees: Person[];
  /**
   * Current native assignment reconciliation state; historical immutable receipts may omit this additive field.
   */
  assignment_conflict: boolean;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "TaskControlResponse".
 */
export interface TaskControlResponse {
  task: CurrentTask;
  operation: Operation;
  project_version: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcAdoptionRequest".
 */
export interface DcAdoptionRequest {
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  definition: DcAdoptionDefinition;
  id: string;
  library_digest: string;
  library_revision: string;
  no_effects: DcNoEffects;
  parent_id: string;
  project: string;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcArtifactInput".
 */
export interface DcArtifactInput {
  revision_id: string;
  source_sha256: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseSourceReference".
 */
export interface DcClauseSourceReference {
  end: number;
  excerpt_sha256: string;
  page: number;
  revision_id: string;
  source_sha256: string;
  start: number;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseTargetResponse".
 */
export interface DcClauseTargetResponse {
  target: DcClauseTargetSnapshot;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcClauseUse".
 */
export interface DcClauseUse {
  adoption_digest: string;
  adoption_id: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  id: string;
  no_effects: DcNoEffects;
  parent_id: string;
  project: string;
  purpose: string;
  scope_type: "Project";
  source_clause: DcQuotedClause;
  status: "referenced";
  target: DcClauseTarget;
  target_changed: false;
  target_snapshot: DcClauseTargetSnapshot;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcQuotedClause".
 */
export interface DcQuotedClause {
  reference: DcClauseSourceReference;
  text: string;
  text_sha256: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyCreateLibraryRequest".
 */
export interface DcCompanyCreateLibraryRequest {
  artifact: DcArtifactInput;
  company: string;
  definition: DcLibraryDefinition;
  operation_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLibraryDefinition".
 */
export interface DcLibraryDefinition {
  category: "specification" | "contract_clause" | "reference";
  change_reason: string;
  discipline: string;
  ownership: string;
  /**
   * @minItems 0
   * @maxItems 20
   */
  tags:
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
  title: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyCreateLibraryResponse".
 */
export interface DcCompanyCreateLibraryResponse {
  history_id: string;
  library: DcCompanyLibrary;
  library_revision: DcCompanyLibraryRevision;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyLibrary".
 */
export interface DcCompanyLibrary {
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  current_revision: string;
  id: string;
  no_effects: DcNoEffects;
  project: null;
  revision_number: number;
  scope_type: "Company";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyLibraryRevision".
 */
export interface DcCompanyLibraryRevision {
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  definition: DcLibraryDefinition;
  id: string;
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  project: null;
  revision_number: number;
  scope_type: "Company";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcOperation".
 */
export interface DcOperation {
  id: string;
  replayed: boolean;
  status: "succeeded";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyGetRecordRequest".
 */
export interface DcCompanyGetRecordRequest {
  company: string;
  kind: "rights" | "library" | "library_revision";
  record_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyGetResponse".
 */
export interface DcCompanyGetResponse {
  library_current: boolean | null;
  record: DcCompanyRecord;
  record_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyListRecordsRequest".
 */
export interface DcCompanyListRecordsRequest {
  company: string;
  count_mode?: "none";
  cursor?: string | null;
  kind: "rights" | "library" | "library_revision";
  limit?: number;
  parent_id?: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyListResponse".
 */
export interface DcCompanyListResponse {
  count_mode: "none";
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: DcCompanyGetResponse[];
  limit: number;
  next_cursor: string | null;
  total: null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyReviseLibraryRequest".
 */
export interface DcCompanyReviseLibraryRequest {
  artifact: DcArtifactInput;
  company: string;
  definition: DcLibraryDefinition;
  expected_version: string;
  library_id: string;
  operation_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanyReviseLibraryResponse".
 */
export interface DcCompanyReviseLibraryResponse {
  history_id: string;
  library: DcCompanyLibrary;
  library_revision: DcCompanyLibraryRevision;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanySetRightsRequest".
 */
export interface DcCompanySetRightsRequest {
  company: string;
  definition: DcRightsDefinition;
  document_id: string;
  expected_version: string | null;
  operation_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRightsDefinition".
 */
export interface DcRightsDefinition {
  allowed_purpose: string;
  distribute_allowed: boolean;
  evidence_artifact: DcArtifactInput;
  ingest_allowed: boolean;
  read_allowed: boolean;
  restriction: string;
  rights_basis: string;
  rights_holder: string;
  valid_from: string | null;
  valid_until: string | null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCompanySetRightsResponse".
 */
export interface DcCompanySetRightsResponse {
  history_id: string;
  operation: DcOperation;
  rights: DcCompanyRights;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateAdoptionRequest".
 */
export interface DcCreateAdoptionRequest {
  company: string;
  definition: DcAdoptionDefinition;
  library_digest: string;
  library_revision: string;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateAdoptionResponse".
 */
export interface DcCreateAdoptionResponse {
  adoption_request: DcAdoptionRequest;
  history_id: string;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateClauseUseRequest".
 */
export interface DcCreateClauseUseRequest {
  adoption_digest: string;
  adoption_id: string;
  company: string;
  operation_id: string;
  project: string;
  purpose: string;
  source_clause: DcClauseSourceReference;
  target: DcClauseTarget;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateClauseUseResponse".
 */
export interface DcCreateClauseUseResponse {
  clause_use: DcClauseUse;
  history_id: string;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateIssueSetRequest".
 */
export interface DcCreateIssueSetRequest {
  /**
   * @minItems 0
   * @maxItems 8
   */
  adoptions:
    | []
    | [DcExactReference]
    | [DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference]
    | [
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference
      ]
    | [
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference
      ];
  /**
   * @minItems 0
   * @maxItems 8
   */
  artifacts:
    | []
    | [DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput
      ]
    | [
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput
      ];
  company: string;
  definition: DcIssueDefinition;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateIssueSetResponse".
 */
export interface DcCreateIssueSetResponse {
  history_id: string;
  issue_set: DcIssueSet;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssueSet".
 */
export interface DcIssueSet {
  /**
   * @minItems 0
   * @maxItems 8
   */
  adoptions:
    | []
    | [DcExactReference]
    | [DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference]
    | [DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference, DcExactReference]
    | [
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference
      ]
    | [
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference,
        DcExactReference
      ];
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  definition: DcIssueDefinition;
  id: string;
  no_effects: DcNoEffects;
  package_digest: string;
  project: string;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateLibraryRequest".
 */
export interface DcCreateLibraryRequest {
  artifact: DcArtifactInput;
  company: string;
  definition: DcLibraryDefinition;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateLibraryResponse".
 */
export interface DcCreateLibraryResponse {
  history_id: string;
  library: DcLibrary;
  library_revision: DcLibraryRevision;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLibrary".
 */
export interface DcLibrary {
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  current_revision: string;
  id: string;
  no_effects: DcNoEffects;
  project: string;
  revision_number: number;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLibraryRevision".
 */
export interface DcLibraryRevision {
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  definition: DcLibraryDefinition;
  id: string;
  no_effects: DcNoEffects;
  parent_id: string;
  predecessor: string | null;
  project: string;
  revision_number: number;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateRedlineRequest".
 */
export interface DcCreateRedlineRequest {
  clause_use_digest: string;
  clause_use_id: string;
  company: string;
  expected_version: string | null;
  operation_id: string;
  project: string;
  proposed_text: string;
  reason: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateRedlineResponse".
 */
export interface DcCreateRedlineResponse {
  history_id: string;
  operation: DcOperation;
  redline: DcRedline;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRedline".
 */
export interface DcRedline {
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  clause_use_digest: string;
  clause_use_id: string;
  company: string;
  created_at: string;
  id: string;
  no_effects: DcNoEffects;
  original_text: string;
  parent_id: string;
  predecessor: string | null;
  project: string;
  proposed_sha256: string;
  proposed_text: string;
  reason: string;
  revision_number: number;
  scope_type: "Project";
  status: "proposed";
  target: DcClauseTarget;
  target_changed: false;
  target_snapshot: DcClauseTargetSnapshot;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateSharedAdoptionRequest".
 */
export interface DcCreateSharedAdoptionRequest {
  company: string;
  definition: DcAdoptionDefinition;
  library_digest: string;
  library_revision: string;
  library_scope: DcLibraryScope;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateSharedAdoptionResponse".
 */
export interface DcCreateSharedAdoptionResponse {
  adoption_request: DcSharedAdoptionRequest;
  history_id: string;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcSharedAdoptionRequest".
 */
export interface DcSharedAdoptionRequest {
  /**
   * @minItems 1
   * @maxItems 1
   */
  artifacts: [DcArtifact];
  author_person: string;
  author_user: string;
  company: string;
  created_at: string;
  definition: DcAdoptionDefinition;
  id: string;
  library_digest: string;
  library_revision: string;
  library_scope: DcLibraryScope;
  no_effects: DcNoEffects;
  parent_id: string;
  project: string;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateTransmittalRequest".
 */
export interface DcCreateTransmittalRequest {
  company: string;
  issue_digest: string;
  issue_id: string;
  operation_id: string;
  project: string;
  purpose: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [string, ...string[]];
  required_response: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcCreateTransmittalResponse".
 */
export interface DcCreateTransmittalResponse {
  history_id: string;
  operation: DcOperation;
  transmittal: DcTransmittal;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcTransmittal".
 */
export interface DcTransmittal {
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
  author_person: string;
  author_user: string;
  channel: "internal";
  company: string;
  created_at: string;
  id: string;
  issue_digest: string;
  issue_id: string;
  no_effects: DcNoEffects;
  package_digest: string;
  parent_id: string;
  project: string;
  purpose: string;
  /**
   * @minItems 1
   * @maxItems 30
   */
  recipients: [DcPerson, ...DcPerson[]];
  required_response: string;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcEvidence".
 */
export interface DcEvidence {
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact];
  author_person: string;
  author_user: string;
  commercial_execution: false;
  company: string;
  created_at: string;
  electronic_signature: false;
  id: string;
  no_effects: DcNoEffects;
  parent_id: string;
  project: string;
  scope_type: "Project";
  statement: string;
  status: "reported_received" | "reported_execution";
  subject_digest: string;
  subject_id: string;
  subject_kind: "distribution" | "adoption";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcGetRecordRequest".
 */
export interface DcGetRecordRequest {
  company: string;
  kind:
    | "rights"
    | "library"
    | "library_revision"
    | "adoption_request"
    | "adoption"
    | "issue_set"
    | "issue"
    | "transmittal"
    | "distribution"
    | "evidence"
    | "clause_use"
    | "redline"
    | "clause_application"
    | "lifecycle_request"
    | "lifecycle";
  project: string;
  record_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcGetResponse".
 */
export interface DcGetResponse {
  library_current: boolean | null;
  record: DcRecord;
  record_digest: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcLifecycleRequest".
 */
export interface DcLifecycleRequest {
  /**
   * @minItems 1
   * @maxItems 16
   */
  artifacts:
    | [DcArtifact]
    | [DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact, DcArtifact]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ]
    | [
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact,
        DcArtifact
      ];
  author_person: string;
  author_user: string;
  before: DcIssuedStandingBody;
  company: string;
  created_at: string;
  definition: DcLifecycleDefinition;
  expected_version: string;
  id: string;
  no_effects: DcNoEffects;
  parent_id: string;
  project: string;
  replacement: DcIssueReference | null;
  scope_type: "Project";
  status: "working";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssuedStanding".
 */
export interface DcIssuedStanding {
  company: string;
  current_issued: DcIssueReference | null;
  document_id: string;
  last_event: DcLifecycleEventReference | null;
  original_issued: DcIssueReference | null;
  project: string;
  scope_type: "Project";
  status: "not_issued" | "issued" | "withdrawn";
  version: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssuedStandingRequest".
 */
export interface DcIssuedStandingRequest {
  company: string;
  document_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcIssuedStandingResponse".
 */
export interface DcIssuedStandingResponse {
  standing: DcIssuedStanding;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcListPeopleRequest".
 */
export interface DcListPeopleRequest {
  company: string;
  count_mode?: "none";
  cursor?: string | null;
  limit?: number;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcListRecordsRequest".
 */
export interface DcListRecordsRequest {
  company: string;
  count_mode?: "none";
  cursor?: string | null;
  kind:
    | "rights"
    | "library"
    | "library_revision"
    | "adoption_request"
    | "adoption"
    | "issue_set"
    | "issue"
    | "transmittal"
    | "distribution"
    | "evidence"
    | "clause_use"
    | "redline"
    | "clause_application"
    | "lifecycle_request"
    | "lifecycle";
  limit?: number;
  parent_id?: string | null;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcListResponse".
 */
export interface DcListResponse {
  count_mode: "none";
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: DcGetResponse[];
  limit: number;
  next_cursor: string | null;
  total: null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcPeopleResponse".
 */
export interface DcPeopleResponse {
  count_mode: "none";
  /**
   * @minItems 0
   * @maxItems 100
   */
  items: {
    display_name: string;
    person: string;
    user: string;
  }[];
  limit: number;
  next_cursor: string | null;
  total: null;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRecordEvidenceRequest".
 */
export interface DcRecordEvidenceRequest {
  /**
   * @minItems 1
   * @maxItems 8
   */
  artifacts:
    | [DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput, DcArtifactInput]
    | [
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput
      ]
    | [
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput,
        DcArtifactInput
      ];
  company: string;
  operation_id: string;
  project: string;
  statement: string;
  subject_digest: string;
  subject_id: string;
  subject_kind: "distribution" | "adoption";
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRecordEvidenceResponse".
 */
export interface DcRecordEvidenceResponse {
  evidence: DcEvidence;
  history_id: string;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRequestLifecycleRequest".
 */
export interface DcRequestLifecycleRequest {
  company: string;
  definition: DcLifecycleDefinition;
  document_id: string;
  expected_version: string;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcRequestLifecycleResponse".
 */
export interface DcRequestLifecycleResponse {
  history_id: string;
  lifecycle_request: DcLifecycleRequest;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcReviseLibraryRequest".
 */
export interface DcReviseLibraryRequest {
  artifact: DcArtifactInput;
  company: string;
  definition: DcLibraryDefinition;
  expected_version: string;
  library_id: string;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcReviseLibraryResponse".
 */
export interface DcReviseLibraryResponse {
  history_id: string;
  library: DcLibrary;
  library_revision: DcLibraryRevision;
  operation: DcOperation;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcSetRightsRequest".
 */
export interface DcSetRightsRequest {
  company: string;
  definition: DcRightsDefinition;
  document_id: string;
  expected_version: string | null;
  operation_id: string;
  project: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "DcSetRightsResponse".
 */
export interface DcSetRightsResponse {
  history_id: string;
  operation: DcOperation;
  rights: DcRights;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticJobResponse".
 */
export interface SemanticJobResponse {
  operation_id: string;
  generation: string;
  status: "pending" | "running" | "retryable" | "rejected" | "active" | "retired" | "cancelled" | "deleted";
  chunks: number;
  indexed_chunks: number;
  error_code: string | null;
  replayed: boolean;
  connected_qualification: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticPrepareRequest".
 */
export interface SemanticPrepareRequest {
  scope: SemanticScope;
  /**
   * @minItems 1
   * @maxItems 16
   */
  sources:
    | [SemanticSource]
    | [SemanticSource, SemanticSource]
    | [SemanticSource, SemanticSource, SemanticSource]
    | [SemanticSource, SemanticSource, SemanticSource, SemanticSource]
    | [SemanticSource, SemanticSource, SemanticSource, SemanticSource, SemanticSource]
    | [SemanticSource, SemanticSource, SemanticSource, SemanticSource, SemanticSource, SemanticSource]
    | [SemanticSource, SemanticSource, SemanticSource, SemanticSource, SemanticSource, SemanticSource, SemanticSource]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ]
    | [
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource,
        SemanticSource
      ];
  operation_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticJobRequest".
 */
export interface SemanticJobRequest {
  scope: SemanticScope;
  operation_id: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticQueryRequest".
 */
export interface SemanticQueryRequest {
  scope: SemanticScope;
  question: string;
  limit: number;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticQueryResponse".
 */
export interface SemanticQueryResponse {
  status: "ready";
  generation: string;
  profile_id: string;
  /**
   * @maxItems 16
   */
  results:
    | []
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ]
    | [
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        },
        {
          id: string;
          score: number;
          excerpt: string;
          chunk_sha256: string;
          start: number;
          end: number;
          citation: {
            id: string;
            document_id: string;
            revision_id: string;
            document_title: string;
            revision_number: number;
            page: number;
            page_label: string;
            excerpt_sha256: string;
            source_sha256: string;
            company?: string;
            scope_type?: "Company" | "Project";
            project?: string | null;
          };
          source: SemanticSource;
        }
      ];
  connected_qualification: false;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "SemanticStatusRequest".
 */
export interface SemanticStatusRequest {
  scope: SemanticScope;
  /**
   * Reference to the existing rebuild operation; this read does not create a command.
   */
  job_operation_id: string;
}
