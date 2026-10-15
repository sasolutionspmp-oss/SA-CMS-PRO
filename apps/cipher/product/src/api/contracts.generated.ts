/* Generated from cipher_aec/api/schema.json. Do not edit.
 * Source SHA-256: efa57ff2851909c5696fd202556bd42caca7c8590691f26801bb056aaae8c2f4
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
export type ApprovalPacket = ProjectStatusApprovalPacket | DomainApprovalPacket;
/**
 * This interface was referenced by `undefined`'s JSON-Schema
 * via the `definition` "ApprovalExecutionResponse".
 */
export type ApprovalExecutionResponse = ProjectStatusApprovalExecutionResponse | DomainApprovalExecutionResponse;

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
  action: "calibration.verify.v1" | "contract.baseline.activate.v1";
  subject: {
    id: string;
    type: "Cipher Calibration" | "Cipher Construction Contract";
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
