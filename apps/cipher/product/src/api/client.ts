import type { ApprovalPacket, ApprovalList, ApprovalCommandResponse, ApprovalExecutionResponse, AssignTaskRequest, Collection, CreateTaskRequest, CreateTaskResponse, DocumentCollection, DocumentPreview, DocumentRecord, DocumentRevision, HistoryItem, Project, Session, Task, TaskChoices, TaskControlResponse, UpdateTaskStatusRequest } from './types';

const base = '/api/method/';
const core = 'cipher_aec.api.v1.';
const docs = 'cipher_aec.documents.api.';
let csrfToken = '';

export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number, public requestId?: string, public details?: Record<string, unknown>) {
    super(message);
    this.name = 'ApiError';
  }
}

// A delivered HTTP response is not necessarily an authoritative mutation result.
export function isUnknownResult(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500 ||
    (error.status >= 200 && error.status < 300 && ['INVALID_RESPONSE', 'INVALID_CONTRACT'].includes(error.code));
}

export async function rpc<T>(method: string, parameters: Record<string, unknown> = {}, write = false, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams();
  if (!write) Object.entries(parameters).forEach(([key, value]) => { if (value !== undefined && value !== null) query.set(key, String(value)); });
  let response: Response;
  try {
    response = await fetch(`${base}${method}${query.size ? `?${query}` : ''}`, {
      method: write ? 'POST' : 'GET', credentials: 'same-origin', signal,
      headers: { Accept: 'application/json', ...(write ? { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': csrfToken, ...(parameters.operation_id ? { 'Idempotency-Key': String(parameters.operation_id) } : {}) } : {}) },
      ...(write ? { body: JSON.stringify(parameters) } : {}),
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ApiError('The workspace could not be reached. Check your connection and try again.', 'CONNECTION_UNAVAILABLE', 0);
  }
  let body: Record<string, unknown>;
  try { body = await response.json(); }
  catch { throw new ApiError('The workspace returned an unexpected response. Try again or contact your administrator.', 'INVALID_RESPONSE', response.status); }
  const envelope = (body.message ?? body) as { schema?: string; data?: T; request_id?: string; error?: { code?: string; message?: string; details?: Record<string, unknown> } };
  if (!response.ok || envelope.error) {
    if (response.status === 401) window.dispatchEvent(new Event('cipher:session-expired'));
    const defaults: Record<number, string> = {
      401: 'Your session has ended. Sign in to continue.', 403: 'You do not have permission for this action.',
      404: 'This record is unavailable or you no longer have access.', 409: 'This action conflicts with a previous request. Refresh the record before continuing.',
      412: 'The source changed. Refresh and review the latest version before saving.',
      429: 'The workspace is busy. Wait a moment and try again.', 503: 'This service is unavailable. Your other work is still available.',
    };
    throw new ApiError(envelope.error?.message || defaults[response.status] || 'The request could not be completed.', envelope.error?.code || `HTTP_${response.status}`, response.status, envelope.request_id, envelope.error?.details);
  }
  if (envelope.schema !== 'cipher.api.v1' || !('data' in envelope)) {
    throw new ApiError('This workspace does not provide the expected Cipher API contract.', 'INVALID_CONTRACT', response.status);
  }
  return envelope.data as T;
}

export const api = {
  async signIn(usr: string, pwd: string) {
    let response: Response;
    try { response = await fetch(`${base}login`, { method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify({ usr, pwd }) }); }
    catch { throw new ApiError('The workspace could not be reached. Try signing in again.', 'CONNECTION_UNAVAILABLE', 0); }
    if (!response.ok) throw new ApiError(response.status === 401 ? 'Check your username and password, then try again.' : response.status === 429 ? 'Too many sign-in attempts. Wait a moment and try again.' : 'Sign-in could not be completed. Try again or contact your administrator.', 'SIGN_IN_FAILED', response.status);
  },
  async signOut() {
    const response = await fetch(`${base}logout`, { method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json', 'X-Frappe-CSRF-Token': csrfToken } });
    if (!response.ok) throw new ApiError('Sign-out could not be completed. Try again.', 'SIGN_OUT_FAILED', response.status);
    csrfToken = '';
    Object.keys(sessionStorage).filter(key => key.startsWith('cipher.run.')).forEach(key => sessionStorage.removeItem(key));
  },
  async session(signal?: AbortSignal) {
    const data = await rpc<Session>(`${core}session`, {}, false, signal);
    csrfToken = data.csrf_token ?? '';
    return data;
  },
  projects: (company: string, signal?: AbortSignal, cursor?: string) => rpc<Collection<Project>>(`${core}projects`, { company, limit: 50, count_mode: 'exact', cursor }, false, signal),
  project: (company: string, project: string, signal?: AbortSignal) => rpc<Project>(`${core}project`, { company, project }, false, signal),
  tasks: (company: string, project: string, signal?: AbortSignal, cursor?: string) => rpc<Collection<Task>>(`${core}tasks`, { company, project, limit: 50, count_mode: 'exact', cursor }, false, signal),
  task: (company: string, project: string, task: string, signal?: AbortSignal) => rpc<Task>(`${core}task`, { company, project, task }, false, signal),
  taskChoices: (company: string, project: string, signal?: AbortSignal) => rpc<TaskChoices>(`${core}task_choices`, { company, project }, false, signal),
  history: (company: string, project: string, signal?: AbortSignal, cursor?: string) => rpc<Collection<HistoryItem>>(`${core}history`, { company, project, limit: 50, count_mode: 'exact', cursor }, false, signal),
  createTask: (input: CreateTaskRequest) => rpc<CreateTaskResponse>(`${core}create_task`, { ...input }, true),
  assignTask: (input: AssignTaskRequest) => rpc<TaskControlResponse>(`${core}assign_task`, { ...input }, true),
  updateTaskStatus: (input: UpdateTaskStatusRequest) => rpc<TaskControlResponse>(`${core}update_task_status`, { ...input }, true),
  documents: (company: string, project: string, signal?: AbortSignal) => rpc<DocumentCollection>(`${docs}list_documents`, { company, project }, false, signal),
  document: (company: string, document_id: string, signal?: AbortSignal) => rpc<{ document: DocumentRecord; revisions: DocumentRevision[] }>(`${docs}get_document`, { company, document_id }, false, signal),
  preview: (company: string, revision_id: string, page: number, signal?: AbortSignal) => rpc<DocumentPreview>(`${docs}preview_revision`, { company, revision_id, page }, false, signal),
  upload: (input: Record<string, unknown>) => rpc<{ document: DocumentRecord; revision: DocumentRevision; operation: { replayed: boolean } }>(`${docs}upload_document`, input, true),
  approvals: (company: string, project: string, signal?: AbortSignal, cursor?: string) => rpc<ApprovalList>('cipher_aec.api.approvals.list_packets', { company, project, cursor, limit: 50, count_mode: 'exact' }, false, signal),
  approval: (company: string, project: string, packet_id: string, signal?: AbortSignal) => rpc<ApprovalPacket>('cipher_aec.api.approvals.read_packet', { company, project, packet_id }, false, signal),
  requestStatus: (input: { company: string; project: string; status: string; expected_version: string; operation_id: string }) => rpc<ApprovalCommandResponse>('cipher_aec.api.approvals.request_project_status', input, true),
  approvalAction: (action: 'Grant' | 'Reject' | 'execute' | 'withdraw', input: { company: string; project: string; packet_id: string; manifest_hash: string; reason: string; operation_id: string }) => rpc<ApprovalCommandResponse | ApprovalExecutionResponse>(`cipher_aec.api.approvals.${action === 'execute' ? 'execute_packet' : action === 'withdraw' ? 'withdraw_packet' : 'decide_packet'}`, { company: input.company, project: input.project, packet_id: input.packet_id, manifest_hash: input.manifest_hash, operation_id: input.operation_id, ...(action !== 'execute' ? { reason: input.reason } : {}), ...(['Grant', 'Reject'].includes(action) ? { decision: action } : {}) }, true),
  downloadUrl: (company: string, revision_id: string) => `${base}${docs}download_revision?${new URLSearchParams({ company, revision_id })}`,
};
