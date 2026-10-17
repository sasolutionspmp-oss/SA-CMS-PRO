import type { CompanyRickyRunResponse, CompanyRickyStopResponse, CompanyRickyRunEventsResponse, CompanyRickySelectedRead } from './company-ricky.generated';

export const companyReadActions = ['aec.pursuit.lookup', 'aec.estimate.recompute', 'aec.estimate.compare', 'aec.quantity.convert'] as const;
export const terminalCompanyRead = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status);
export const companyRunPointerKey = (user: string, person: string, company: string) => JSON.stringify(['cipher.company.ricky.v1', user, person, company]);
export function matchesCompanyRun(run: CompanyRickyRunResponse, company: string, id?: string): boolean {
  return Boolean(run && typeof run.id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(run.id) && (!id || run.id === id) && run.company === company && run.scope_type === 'Company' && run.project === null && run.request_kind === 'deterministic-read-v1' && companyReadActions.includes(run.action) && ['queued', 'retrieving', 'executing', 'succeeded', 'failed', 'cancelled'].includes(run.status) && run.standing?.mode === 'deterministic-read-v1' && run.standing.model_invoked === false && run.standing.live_model_qualified === false && typeof run.cancel_requested === 'boolean' && run.cancel_requested === (run.status === 'cancelled') && run.result_basis === 'original-tool-observation-v1' && matchesCompanySelection(run.selection) && run.selection.action === run.action && /^[a-f0-9]{64}$/.test(run.selection_digest));
}
export function matchesCompanyStop(stop: CompanyRickyStopResponse, company: string, id: string): boolean {
  return Boolean(stop && stop.id === id && stop.company === company && stop.scope_type === 'Company' && stop.project === null && stop.request_kind === 'deterministic-read-v1' && terminalCompanyRead(stop.status) && stop.cancel_requested === (stop.status === 'cancelled') && Object.keys(stop).length === 8 && ['id','company','scope_type','project','request_kind','status','cancel_requested','operation'].every(key => Object.hasOwn(stop, key)));
}
export function matchesCompanyEvents(events: CompanyRickyRunEventsResponse, id: string, action: CompanyRickyRunResponse['action']): boolean {
  return Boolean(events && Array.isArray(events.items) && events.items.length <= 8 && events.items.every(row => row && typeof row.id === 'string') && new Set(events.items.map(row => row.id)).size === events.items.length && events.items.every(row => row && row.run_id === id && row.tool_name === action && ['claimed', 'succeeded', 'failed'].includes(row.status)));
}

// Order-independent exact JSON equality preserves array order and primitive types.
// This compares a returned selection; it never mints a server digest.
export function sameSelectedValue(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object') return false;
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((value, index) => sameSelectedValue(value, right[index]));
  const a = left as Record<string, unknown>; const b = right as Record<string, unknown>; const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && sameSelectedValue(a[key], b[key]));
}
export function matchesSelectedResult(run: CompanyRickyRunResponse, selection: CompanyRickySelectedRead): boolean {
  if (run.action !== selection.action) return false;
  const result = run.result;
  if (run.status !== 'succeeded') return result === null && run.result_digest === null && (terminalCompanyRead(run.status) ? typeof run.completed_at === 'string' : run.completed_at === null);
  if (result === null || run.error !== null || typeof run.completed_at !== 'string') return false;
  const sha = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  if (!sha(run.result_digest)) return false;
  if (selection.action === 'aec.pursuit.lookup') return 'pursuit_id' in result && 'record_digest' in result && result.company === run.company && result.scope_type === 'Company' && result.pursuit_id === selection.pursuit_id && sha(result.record_digest);
  if (selection.action === 'aec.estimate.recompute') return 'revision_id' in result && result.company === run.company && result.scope_type === 'Company' && result.pursuit_id === selection.pursuit_id && result.revision_id === selection.arguments.revision_id && sha(result.revision_digest) && sha(result.input_digest) && sha(result.output_digest);
  if (selection.action === 'aec.estimate.compare') return 'left_revision_id' in result && result.company === run.company && result.scope_type === 'Company' && result.pursuit_id === selection.pursuit_id && result.left_revision_id === selection.arguments.left_revision_id && result.right_revision_id === selection.arguments.right_revision_id && sha(result.left_digest) && sha(result.right_digest);
  return 'source_kind' in result && result.source_kind === selection.arguments.source_kind && result.source_id === selection.arguments.source_id && result.target_unit_id === selection.arguments.target_unit_id && sha(result.source_digest) && result.model_supplied_quantity === false;
}

export function matchesCompanySelection(value: CompanyRickySelectedRead): boolean {
  if (!value || value.schema !== 'cipher.ricky.company.read-request.v1' || !companyReadActions.includes(value.action) || Object.keys(value).length !== 6 || !value.arguments || typeof value.arguments !== 'object' || Array.isArray(value.arguments) || !Array.isArray(value.sources) || value.sources.length > 8 || !Array.isArray(value.measurement_ids) || value.measurement_ids.length > 8) return false;
  const uuid = (input: unknown) => typeof input === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(input);
  const sha = (input: unknown) => typeof input === 'string' && /^[0-9a-f]{64}$/.test(input);
  const fields = value.action === 'aec.pursuit.lookup' ? [] : value.action === 'aec.estimate.recompute' ? ['revision_id'] : value.action === 'aec.estimate.compare' ? ['left_revision_id','right_revision_id'] : ['source_kind','source_id','target_unit_id'];
  if (!uuid(value.pursuit_id) || Object.keys(value.arguments).length !== fields.length || !fields.every(key => Object.hasOwn(value.arguments,key) && (key === 'source_kind' ? ['estimate-line','measurement'].includes(value.arguments[key] as string) : uuid(value.arguments[key])))) return false;
  if (!value.measurement_ids.every(uuid) || new Set(value.measurement_ids).size !== value.measurement_ids.length || !value.sources.every(row => row && Object.keys(row).length === 5 && sha(row.citation_id) && typeof row.revision_id === 'string' && row.revision_id.length > 0 && row.revision_id.length <= 160 && Number.isInteger(row.page) && row.page >= 1 && row.page <= 100000 && sha(row.excerpt_sha256) && sha(row.source_sha256)) || new Set(value.sources.map(row => row.citation_id)).size !== value.sources.length) return false;
  return value.action !== 'aec.quantity.convert' || value.arguments.source_kind !== 'measurement' || value.measurement_ids.some(id => id === value.arguments.source_id);
}

// Command admission is immutable queued state, not a shortcut to source-bearing
// worker results. A replay still acknowledges the original queued admission.
export function matchesCompanyAdmission(run: CompanyRickyRunResponse, company: string): boolean {
  return matchesCompanyRun(run, company) && run.status === 'queued' && run.result === null && run.result_digest === null && run.completed_at === null && run.error === null && run.cancel_requested === false;
}
export type CompanyTerminalObservation = Pick<CompanyRickyRunResponse, 'status' | 'completed_at' | 'result_digest' | 'result' | 'error' | 'cancel_requested'>;
// Called only after full source-bearing Run validation. A narrow Stop cannot
// supply this shape or initialize the original full observation.
export function companyTerminalObservation(run: CompanyRickyRunResponse): CompanyTerminalObservation | undefined {
  return terminalCompanyRead(run.status) ? structuredClone({ status:run.status, completed_at:run.completed_at, result_digest:run.result_digest, result:run.result, error:run.error, cancel_requested:run.cancel_requested }) : undefined;
}
