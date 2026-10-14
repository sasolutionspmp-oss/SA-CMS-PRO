import { sumCents } from '../copy/format';
import type {
  ActionOutcome, APAction, Bill, Collection, Envelope, Packet, Persona, Preflight, Problem,
  BillException, CorrectionApproval, CorrectionPacket, Invoice, InvoiceException, MatchPacket, Preparation, Records, Session, Workspace,
} from './types';

const prefix = '/api/ap-practice/v1';
const supportedActions: APAction[] = ['bill.requestApproval', 'bill.approve', 'bill.post', 'bill.prepare',
  'invoice.receive', 'invoice.computeMatch', 'invoice.requestMatchApproval', 'invoice.approveMatch', 'invoice.executeMatch',
  'invoice.revise', 'invoice.reject', 'invoice.reviewDuplicate', 'bill.cancel', 'bill.prepareCorrection',
  'bill.requestCorrection', 'bill.approveCorrection', 'bill.executeCorrection'];
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
  for (const item of raw) {
    const value = object(item); strings(value, ['code', 'message']); nullableStrings(value, ['target']);
    if (value.fix !== undefined && value.fix !== null && typeof value.fix !== 'string') throw unreadable();
  }
}
function checks(raw: unknown) {
  problems(raw);
  for (const item of raw as unknown[]) {
    const check = object(item);
    if (check.status !== 'passed' && check.status !== 'blocked' && check.status !== 'warning') throw unreadable();
  }
}
function effects(raw: unknown, allowed: boolean, action: APAction) {
  const value = object(raw);
  integers(value, ['workingLedgerJournalDelta', 'apPayableDeltaCents']);
  if (['bill.requestApproval', 'bill.approve', 'bill.post'].includes(action)) {
    strings(value, ['billStatus']);
    if (allowed) integers(value, ['amountDueCents', 'retainageCents']);
  } else if (['bill.prepare', 'invoice.receive', 'invoice.computeMatch', 'invoice.requestMatchApproval', 'invoice.approveMatch', 'invoice.executeMatch'].includes(action)) {
    nullableStrings(value, ['billStatus', 'invoiceStatus', 'approvalStatus', 'matchStatus']);
    if (allowed) integers(value, action === 'bill.prepare' ? ['amountDueCents', 'retainageCents', 'thisPeriodCents'] : ['amountCents']);
    if (value.workingLedgerJournalDelta !== 0 || value.apPayableDeltaCents !== 0 || array(value, 'journalPreview').length !== 0) throw unreadable();
    if (array(value, 'matchExceptionCodes').some(code => typeof code !== 'string') || typeof value.possibleDuplicate !== 'boolean' || typeof value.billLinked !== 'boolean') throw unreadable();
  } else {
    if (action !== 'bill.executeCorrection' && (value.workingLedgerJournalDelta !== 0 || value.apPayableDeltaCents !== 0 || array(value, 'journalPreview').length !== 0)) throw unreadable();
    for (const field of ['billStatus', 'invoiceStatus', 'approvalStatus']) if (value[field] !== undefined && value[field] !== null && typeof value[field] !== 'string') throw unreadable();
    if (typeof value.duplicateReviewed !== 'boolean' || typeof value.requiresNewMatch !== 'boolean' || !Number.isSafeInteger(value.invalidatedApprovalCount) || (value.invalidatedApprovalCount as number) < 0) throw unreadable();
    if (allowed) {
      strings(value, action.startsWith('invoice.') ? ['invoiceStatus'] : ['billStatus']);
      integers(value, action.startsWith('invoice.') ? ['amountCents'] : ['amountDueCents']);
    }
  }
  for (const field of ['amountDueCents', 'retainageCents', 'amountCents', 'thisPeriodCents']) if (value[field] !== undefined && !Number.isSafeInteger(value[field])) throw unreadable();
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
function actions(value: ObjectValue) {
  if (array(value, 'availableActions').some(action => !supportedActions.includes(action as APAction))) throw unreadable();
  problems(value.blockedReasons);
}
function evidence(raw: unknown) {
  const value = object(raw); strings(value, ['documentId', 'revisionId', 'title']); integers(value, ['revision']);
  if (typeof value.isCurrent !== 'boolean') throw unreadable();
}
function invoice(raw: unknown) {
  const value = object(raw);
  strings(value, ['id', 'version', 'projectId', 'projectName', 'supplierId', 'supplierName', 'invoiceNumber', 'invoiceDate', 'dueDate', 'status']);
  nullableStrings(value, ['commitmentId', 'commitmentTitle', 'matchApprovalId']); integers(value, ['amountCents', 'invoiceVersion']); evidence(value.evidence);
  if (typeof value.possibleDuplicate !== 'boolean' || typeof value.duplicateBlocking !== 'boolean') throw unreadable();
  if (value.match !== null) {
    const match = object(value.match); strings(match, ['status', 'basis', 'attemptId']); nullableStrings(match, ['billId']);
    for (const item of array(match, 'exceptions')) strings(object(item), ['code', 'message']);
  }
  actions(value);
}
function matchApproval(raw: unknown) {
  const value = object(raw);
  strings(value, ['id', 'approvalId', 'version', 'projectId', 'projectName', 'invoiceId', 'invoiceNumber', 'supplierName', 'status', 'effectiveStatus', 'requestedAt', 'expiresAt']);
  nullableStrings(value, ['approvedAt']); integers(value, ['amountCents']); person(value.requestedBy);
  if (value.approvedBy !== null) person(value.approvedBy);
}
function correctionApproval(raw: unknown) {
  const value = object(raw);
  strings(value, ['id', 'approvalId', 'version', 'projectId', 'projectName', 'billId', 'supplierName', 'status', 'effectiveStatus', 'requestedAt', 'expiresAt', 'correctionId', 'reason']);
  integers(value, ['sequence', 'amountDueCents']); nullableStrings(value, ['approvedAt']); person(value.requestedBy);
  if (value.approvedBy !== null) person(value.approvedBy);
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
  } else if (collection === 'posting-queue') {
    strings(value, ['billId', 'version', 'projectId', 'supplierName', 'commitmentTitle', 'businessApprovalId', 'approvedAt', 'expiresAt']);
    integers(value, ['sequence', 'amountDueCents']); period(value.certificationPeriod); person(value.approvedBy);
    if (typeof value.ready !== 'boolean') throw unreadable(); problems(value.blockedReasons);
  } else if (collection === 'invoices') invoice(value);
  else if (collection === 'match-approvals') matchApproval(value);
  else if (collection === 'correction-approvals') correctionApproval(value);
  else {
    strings(value, ['id', 'projectId', 'status']); evidence(value);
    if (typeof value.available !== 'boolean') throw unreadable();
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
  const [projects, commitments, bills, approvals, postingQueue, invoices, invoiceEvidence, matchApprovals] = await Promise.all([
    readCollection('projects', signal), readCollection('commitments', signal), readCollection('bills', signal),
    readCollection('approvals', signal), readCollection('posting-queue', signal),
    readCollection('invoices', signal), readCollection('invoice-evidence', signal), readCollection('match-approvals', signal),
  ]);
  for (const project of projects) {
    sumCents(commitments.filter(row => row.projectId === project.id).map(row => row.executedAmountCents));
    sumCents(bills.filter(row => row.projectId === project.id).map(row => row.currentDueCents));
    sumCents(invoices.filter(row => row.projectId === project.id && row.status !== 'rejected').map(row => row.amountCents));
  }
  return { projects, commitments, bills, approvals, postingQueue, invoices, invoiceEvidence, matchApprovals, loadedAt: new Date() };
}
export async function readPreparation(id: string, signal?: AbortSignal): Promise<Preparation> {
  const value = provenance(await request(`/commitments/${encodeURIComponent(id)}/preparation`, { signal }));
  strings(value, ['id', 'version', 'projectId', 'projectName', 'commitmentTitle', 'supplierId', 'supplierName', 'status']); integers(value, ['retainageRateMicros']);
  for (const item of array(value, 'lines')) {
    const line = object(item); strings(line, ['sovLineId', 'description', 'costCode']); integers(line, ['lineNo', 'scheduledCents', 'priorInstalledCents']);
  }
  for (const item of array(value, 'periods')) period(item);
  if (value.priorBill !== null) { const prior = object(value.priorBill); strings(prior, ['id', 'status']); integers(prior, ['sequence']); }
  actions(value); return value as unknown as Preparation;
}
export async function readInvoice(id: string, signal?: AbortSignal): Promise<Invoice> {
  const value = provenance(await request(`/invoices/${encodeURIComponent(id)}`, { signal })); invoice(value);
  return value as unknown as Invoice;
}
export async function readMatchPacket(id: string, signal?: AbortSignal): Promise<MatchPacket> {
  const value = provenance(await request(`/match-approvals/${encodeURIComponent(id)}/packet`, { signal }));
  matchApproval(value); invoice(value.invoice); object(value.boundFacts); object(value.currentFacts); changes(value.changes); actions(value);
  const effect = object(value.effect);
  if (effect.invoiceStatus !== 'matched' || typeof effect.billLinked !== 'boolean' || effect.workingLedgerJournalDelta !== 0 || effect.apPayableDeltaCents !== 0) throw unreadable();
  return value as unknown as MatchPacket;
}
export async function readInvoiceException(id: string, signal?: AbortSignal): Promise<InvoiceException> {
  const value = provenance(await request(`/invoices/${encodeURIComponent(id)}/exception-review`, { signal }));
  strings(value, ['version']); invoice(value.invoice); actions(value); return value as unknown as InvoiceException;
}
export async function readBillException(id: string, signal?: AbortSignal): Promise<BillException> {
  const value = provenance(await request(`/bills/${encodeURIComponent(id)}/exception-review`, { signal }));
  strings(value, ['version']); bill(value.bill); actions(value);
  for (const item of array(value, 'correctionPeriods')) period(item);
  if (value.correction !== null) {
    const correction = object(value.correction); strings(correction, ['id', 'status', 'reason', 'requestedAt']); person(correction.requestedBy);
  }
  return value as unknown as BillException;
}
export async function readCorrectionPacket(id: string, signal?: AbortSignal): Promise<CorrectionPacket> {
  const value = provenance(await request(`/correction-approvals/${encodeURIComponent(id)}/packet`, { signal }));
  correctionApproval(value); bill(value.bill); actions(value); changes(value.changes); object(value.boundFacts); object(value.currentFacts);
  const effect = object(value.effect);
  if (effect.billStatus !== 'corrected' || effect.externalAccounting !== 'unavailable' || effect.payment !== 'not_started') throw unreadable();
  for (const item of array(value, 'correctionPeriods')) period(item);
  return value as unknown as CorrectionPacket;
}
export function readCorrectionApprovals(_id: string, signal?: AbortSignal): Promise<CorrectionApproval[]> {
  return readCollection('correction-approvals', signal);
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
  const routes: Record<APAction, string> = {
    'bill.requestApproval': `/bills/${encoded}/request-approval`, 'bill.approve': `/approvals/${encoded}/approve`,
    'bill.post': `/bills/${encoded}/post`, 'bill.prepare': `/commitments/${encoded}/prepare-bill`,
    'invoice.receive': `/commitments/${encoded}/receive-invoice`, 'invoice.computeMatch': `/invoices/${encoded}/compute-match`,
    'invoice.requestMatchApproval': `/invoices/${encoded}/request-match-approval`,
    'invoice.approveMatch': `/match-approvals/${encoded}/approve`, 'invoice.executeMatch': `/match-approvals/${encoded}/execute`,
    'invoice.revise': `/invoices/${encoded}/revise`, 'invoice.reject': `/invoices/${encoded}/reject`,
    'invoice.reviewDuplicate': `/invoices/${encoded}/review-duplicate`, 'bill.cancel': `/bills/${encoded}/cancel`,
    'bill.prepareCorrection': `/bills/${encoded}/prepare-correction`, 'bill.requestCorrection': `/bills/${encoded}/request-correction`,
    'bill.approveCorrection': `/correction-approvals/${encoded}/approve`, 'bill.executeCorrection': `/correction-approvals/${encoded}/execute`,
  };
  return routes[action];
}
export async function preflight(action: APAction, id: string, body: ObjectValue, csrf: string): Promise<Preflight> {
  const value = provenance(await request(actionPath(action, id) + ':preflight', { method: 'POST', csrf, body }));
  strings(value, ['action', 'resourceId', 'resourceVersion']); checks(value.checks); changes(value.changes);
  if (value.action !== action || value.resourceId !== id || typeof value.allowed !== 'boolean' ||
      (value.allowed ? typeof value.fingerprint !== 'string' || !value.fingerprint : value.fingerprint !== null)) throw unreadable();
  effects(value.safeEffects, value.allowed, action);
  return value as unknown as Preflight;
}
export async function applyAction(action: APAction, id: string, body: ObjectValue, csrf: string, version: string, repeatabilityId: string): Promise<ActionOutcome> {
  const value = provenance(await request(actionPath(action, id), { method: 'POST', csrf, body, version, repeatabilityId }));
  strings(value, ['receiptId']); object(value.result);
  if (typeof value.replayed !== 'boolean' || typeof value.effectApplied !== 'boolean') throw unreadable();
  return value as unknown as ActionOutcome;
}
