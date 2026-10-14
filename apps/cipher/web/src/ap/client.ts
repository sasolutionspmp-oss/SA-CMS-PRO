import { sumCents } from '../copy/format';
import type {
  ActionOutcome, APAction, Bill, Collection, Envelope, Packet, Persona, Preflight, Problem,
  Records, Session, Workspace,
} from './types';

const prefix = '/api/ap-practice/v1';
const supportedActions: APAction[] = ['bill.requestApproval', 'bill.approve', 'bill.post'];
const pendingReads = new Set<AbortController>();
export function abortScopedReads() {
  for (const controller of pendingReads) controller.abort();
  pendingReads.clear();
}
type ObjectValue = Record<string, unknown>;
const unreadable = () => new Error('The AP practice server returned an incomplete or unsupported record.');
function object(raw: unknown): ObjectValue {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw unreadable();
  return raw as ObjectValue;
}
function strings(raw: ObjectValue, fields: string[]) {
  if (fields.some(field => typeof raw[field] !== 'string')) throw unreadable();
}
function integers(raw: ObjectValue, fields: string[]) {
  if (fields.some(field => !Number.isSafeInteger(raw[field]))) throw unreadable();
}
function nullableStrings(raw: ObjectValue, fields: string[]) {
  if (fields.some(field => raw[field] !== null && typeof raw[field] !== 'string')) throw unreadable();
}
function array(raw: ObjectValue, key: string): unknown[] {
  if (!Array.isArray(raw[key])) throw unreadable();
  return raw[key];
}
function provenance(raw: unknown): ObjectValue {
  const value = object(raw);
  if (value.contractVersion !== 'cipher.ap-practice.v1' || value.mode !== 'practice' || value.synthetic !== true || value.currency !== 'USD') {
    throw new Error('This view requires the supported synthetic AP practice workspace.');
  }
  safeMoneyTree(value);
  return value;
}
// Every server money field, including nested previews and results, is exact integer cents.
function safeMoneyTree(raw: unknown, depth = 0) {
  if (depth > 20) throw unreadable();
  if (Array.isArray(raw)) { for (const value of raw) safeMoneyTree(value, depth + 1); return; }
  if (raw && typeof raw === 'object') for (const [key, value] of Object.entries(raw)) {
    if ((key.endsWith('Cents') || key.endsWith('Micros')) && !Number.isSafeInteger(value)) {
      throw new Error('An AP practice amount could not be read accurately.');
    }
    safeMoneyTree(value, depth + 1);
  }
}
function person(raw: unknown) { strings(object(raw), ['id', 'displayName']); }
function period(raw: unknown) { strings(object(raw), ['id', 'name', 'startDate', 'endDate', 'status']); }
function problems(raw: unknown) {
  if (!Array.isArray(raw)) throw unreadable();
  for (const item of raw) { const value = object(item); strings(value, ['code', 'message']); nullableStrings(value, ['target', 'fix']); }
}
function checks(raw: unknown) {
  problems(raw);
  for (const item of raw as unknown[]) {
    const check = object(item);
    if (check.status !== 'passed' && check.status !== 'blocked') throw unreadable();
  }
}
function effects(raw: unknown, allowed: boolean) {
  const value = object(raw);
  strings(value, ['billStatus']); integers(value, ['workingLedgerJournalDelta', 'apPayableDeltaCents']);
  if (allowed) integers(value, ['amountDueCents', 'retainageCents']);
  else for (const field of ['amountDueCents', 'retainageCents']) if (value[field] !== undefined && !Number.isSafeInteger(value[field])) throw unreadable();
  if (value.externalAccounting !== 'unavailable' || value.payment !== 'not_started') throw unreadable();
  for (const item of array(value, 'journalPreview')) {
    const journal = object(item); strings(journal, ['periodId', 'description']);
    for (const item of array(journal, 'lines')) {
      const line = object(item); strings(line, ['account', 'memo']); integers(line, ['debitCents', 'creditCents']);
      if (line.accountName !== undefined && typeof line.accountName !== 'string') throw unreadable();
    }
  }
}
function changes(raw: unknown) {
  if (!Array.isArray(raw)) throw unreadable();
  for (const item of raw) {
    const change = object(item); strings(change, ['field']);
    if (!Object.hasOwn(change, 'before') || !Object.hasOwn(change, 'after')) throw unreadable();
  }
}
function bill(raw: unknown) {
  const value = object(raw);
  strings(value, ['id', 'version', 'projectId', 'commitmentId', 'supplierId', 'projectName', 'commitmentTitle', 'supplierName', 'status', 'effectiveStatus']);
  integers(value, ['sequence', 'amountDueCents', 'currentDueCents', 'retainageCents', 'thisPeriodCents']);
  if (value.displayNumber !== null) throw unreadable();
  period(value.certificationPeriod);
  for (const item of array(value, 'postingPeriods')) period(item);
  for (const item of array(value, 'lines')) {
    const line = object(item); strings(line, ['id', 'sovLineId', 'description', 'costCode']);
    integers(line, ['cumulativeInstalledCents', 'priorInstalledCents', 'thisPeriodInstalledCents']);
  }
  if (value.businessApproval !== null) {
    const approval = object(value.businessApproval);
    strings(approval, ['approvalId', 'status', 'effectiveStatus', 'requestedAt', 'expiresAt']);
    nullableStrings(approval, ['id', 'approvedAt']); person(approval.requestedBy);
    if (approval.approvedBy !== null) person(approval.approvedBy);
  }
  if (value.posting !== null) {
    const posting = object(value.posting); strings(posting, ['receiptId', 'postedAt', 'reason']);
    if (array(posting, 'journalIds').some(id => typeof id !== 'string')) throw unreadable();
    period(posting.period); person(posting.postedBy);
  }
  if (array(value, 'availableActions').some(action => !supportedActions.includes(action as APAction))) throw unreadable();
  problems(value.blockedReasons);
}
function record(raw: unknown, collection: Collection) {
  const value = object(raw);
  if (collection === 'projects') {
    strings(value, ['id', 'name', 'entity', 'currency']); integers(value, ['budgetCents']);
    if (value.currency !== 'USD') throw unreadable();
    if (value.customerName !== undefined && value.customerName !== null && typeof value.customerName !== 'string') throw unreadable();
  } else if (collection === 'commitments') {
    strings(value, ['id', 'projectId', 'supplierId', 'title', 'status', 'supplierName', 'projectName']);
    integers(value, ['originalAmountCents', 'executedAmountCents', 'retainageRateMicros']);
    if (!(typeof value.version === 'string' || Number.isSafeInteger(value.version))) throw unreadable();
  } else if (collection === 'bills') bill(value);
  else if (collection === 'approvals') {
    strings(value, ['id', 'version', 'billId', 'projectId', 'projectName', 'subjectLabel', 'status', 'effectiveStatus', 'requestedAt', 'expiresAt']);
    integers(value, ['amountDueCents']); nullableStrings(value, ['approvedAt']); person(value.requestedBy);
    if (value.approvedBy !== null) person(value.approvedBy);
  } else {
    strings(value, ['billId', 'version', 'projectId', 'supplierName', 'commitmentTitle', 'businessApprovalId', 'approvedAt', 'expiresAt']);
    integers(value, ['sequence', 'amountDueCents']); period(value.certificationPeriod); person(value.approvedBy);
    if (typeof value.ready !== 'boolean') throw unreadable(); problems(value.blockedReasons);
  }
}
export class APError extends Error {
  readonly status: number; readonly problem: Problem; readonly replayed: boolean; readonly receiptId: string | null;
  constructor(status: number, problem: Problem, replayed = false, receiptId: string | null = null) {
    super(problem.message); this.name = 'APError'; this.status = status; this.problem = problem;
    this.replayed = replayed; this.receiptId = receiptId;
  }
}
export async function request(path: string, options: {
  method?: 'GET' | 'POST'; csrf?: string; body?: ObjectValue; signal?: AbortSignal; version?: string; repeatabilityId?: string;
} = {}): Promise<unknown> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.method === 'POST') {
    headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = options.csrf ?? '';
    if (options.version) headers['If-Match'] = `"${options.version}"`;
    if (options.repeatabilityId) headers['Repeatability-Request-ID'] = options.repeatabilityId;
  }
  const scopedRead = (options.method !== 'POST' && !['/session', '/personas'].includes(path)) || path.endsWith(':preflight');
  const controller = scopedRead ? new AbortController() : null;
  if (controller) pendingReads.add(controller);
  try {
    const response = await fetch(prefix + path, {
      method: options.method ?? 'GET', headers, credentials: 'same-origin', cache: 'no-store',
      ...(options.method === 'POST' ? { body: JSON.stringify(options.body ?? {}) } : {}),
      signal: controller ? options.signal ? AbortSignal.any([controller.signal, options.signal]) : controller.signal : options.signal,
    });
    let raw: unknown;
    try { raw = await response.json(); } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw new Error('The AP practice server did not return a readable response. Refresh the practice session.');
    }
    const envelope = provenance(raw);
    if (!response.ok) {
      const error = object(envelope.error); strings(error, ['code', 'message']); nullableStrings(error, ['target']);
      if (error.fix !== undefined && error.fix !== null && typeof error.fix !== 'string') throw unreadable();
      const problem: Problem = { code: error.code as string, message: error.message as string, target: error.target as string | null, fix: typeof error.fix === 'string' ? error.fix : null };
      throw new APError(response.status, problem, envelope.replayed === true, typeof envelope.receiptId === 'string' ? envelope.receiptId : null);
    }
    return envelope;
  } finally { if (controller) pendingReads.delete(controller); }
}
export async function readSession(signal?: AbortSignal): Promise<Session> {
  return session(await request('/session', { signal }));
}
function session(raw: unknown): Session {
  const value = provenance(raw); strings(value, ['csrfToken']); nullableStrings(value, ['sessionExpiresAt']);
  if (typeof value.authenticated !== 'boolean') throw unreadable();
  if (value.person !== null) { person(value.person); strings(object(value.person), ['personaId']); }
  if (value.authenticated !== (value.person !== null)) throw unreadable();
  if (array(value, 'duties').some(duty => duty !== 'pm' && duty !== 'accountant') || array(value, 'projectIds').some(id => typeof id !== 'string')) throw unreadable();
  const capabilities = object(value.capabilities);
  if (capabilities.sessionIdentity !== 'registered_synthetic_person' || capabilities.scopedReads !== true ||
      capabilities.microsoftSignIn !== false || capabilities.liveAdmission !== false || capabilities.externalAccounting !== 'unavailable' ||
      array(capabilities, 'commands').some(action => !supportedActions.includes(action as APAction))) throw unreadable();
  return value as unknown as Session;
}
export async function readPersonas(signal?: AbortSignal): Promise<Persona[]> {
  const value = provenance(await request('/personas', { signal }));
  for (const item of array(value, 'value')) {
    const option = object(item); strings(option, ['personaId', 'displayName']); if (option.synthetic !== true) throw unreadable();
  }
  return value.value as Persona[];
}
export async function bindSession(personaId: string, csrf: string): Promise<Session> {
  return session(await request('/session', { method: 'POST', csrf, body: { personaId } }));
}
export async function endSession(csrf: string): Promise<Session> {
  return session(await request('/session/logout', { method: 'POST', csrf, body: {} }));
}
export async function readCollection<K extends Collection>(collection: K, signal?: AbortSignal): Promise<Records[K][]> {
  const rows: Records[K][] = []; const seen = new Set<string>(); let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ top: '50' }); if (cursor) query.set('cursor', cursor);
    const value = provenance(await request(`/${collection}?${query}`, { signal }));
    if (value.collection !== collection || !Number.isSafeInteger(value.count) || (value.count as number) < 0) throw unreadable();
    nullableStrings(value, ['nextCursor', 'projectId']); object(value.facets);
    const totals = object(value.totals); if (Object.values(totals).some(amount => !Number.isSafeInteger(amount))) throw unreadable();
    const page = array(value, 'value'); for (const item of page) record(item, collection);
    const envelope = value as unknown as Envelope<Records[K]>;
    rows.push(...envelope.value); cursor = envelope.nextCursor;
    if (cursor && (seen.has(cursor) || seen.size >= 100)) throw new Error('The scoped practice list could not finish loading.');
    if (cursor) seen.add(cursor);
  } while (cursor);
  return rows;
}
export async function loadWorkspace(signal?: AbortSignal): Promise<Workspace> {
  const [projects, commitments, bills, approvals, postingQueue] = await Promise.all([
    readCollection('projects', signal), readCollection('commitments', signal), readCollection('bills', signal),
    readCollection('approvals', signal), readCollection('posting-queue', signal),
  ]);
  for (const project of projects) {
    sumCents(commitments.filter(row => row.projectId === project.id).map(row => row.executedAmountCents));
    sumCents(bills.filter(row => row.projectId === project.id).map(row => row.currentDueCents));
  }
  return { projects, commitments, bills, approvals, postingQueue, loadedAt: new Date() };
}
export async function readBill(id: string, signal?: AbortSignal): Promise<Bill> {
  const value = provenance(await request(`/bills/${encodeURIComponent(id)}`, { signal })); bill(value);
  return value as unknown as Bill;
}
export async function readPacket(id: string, signal?: AbortSignal): Promise<Packet> {
  const value = provenance(await request(`/approvals/${encodeURIComponent(id)}/packet`, { signal }));
  strings(value, ['approvalId', 'billId', 'version', 'status', 'requestedAt', 'expiresAt']);
  integers(value, ['amountDueCents', 'retainedCents']); person(value.requestedBy); if (value.approvedBy !== null) person(value.approvedBy);
  object(value.boundFacts); object(value.currentFacts); object(value.sourceSummary); checks(value.checks); changes(value.changes); bill(value.bill);
  const effect = object(value.effect);
  if (effect.billStatus !== 'approved' || effect.workingLedgerJournalDelta !== 0 || effect.apPayableDeltaCents !== 0) throw unreadable();
  return value as unknown as Packet;
}
export function actionPath(action: APAction, id: string) {
  const encoded = encodeURIComponent(id);
  return action === 'bill.requestApproval' ? `/bills/${encoded}/request-approval`
    : action === 'bill.approve' ? `/approvals/${encoded}/approve` : `/bills/${encoded}/post`;
}
export async function preflight(action: APAction, id: string, body: ObjectValue, csrf: string): Promise<Preflight> {
  const value = provenance(await request(actionPath(action, id) + ':preflight', { method: 'POST', csrf, body }));
  strings(value, ['action', 'resourceId', 'resourceVersion']); checks(value.checks); changes(value.changes);
  if (value.action !== action || value.resourceId !== id || typeof value.allowed !== 'boolean' ||
      (value.allowed ? typeof value.fingerprint !== 'string' || !value.fingerprint : value.fingerprint !== null)) throw unreadable();
  effects(value.safeEffects, value.allowed);
  return value as unknown as Preflight;
}
export async function applyAction(action: APAction, id: string, body: ObjectValue, csrf: string, version: string, repeatabilityId: string): Promise<ActionOutcome> {
  const value = provenance(await request(actionPath(action, id), { method: 'POST', csrf, body, version, repeatabilityId }));
  strings(value, ['receiptId']); object(value.result);
  if (typeof value.replayed !== 'boolean' || typeof value.effectApplied !== 'boolean') throw unreadable();
  return value as unknown as ActionOutcome;
}
