import type {
  Action, Acceptance, ActionAvailability, Change, Check, Collection, CollectionFilters, Comparison,
  ApprovalPacket, DraftCommitment, DrawingRevisionRow, DrawingSource, EntryLine, EstimateApprovalRow,
  EstimatePreparation, EstimateRecord, EstimateRow, Handoff, HandoffLine, HandoffPreparation,
  Persona, PersonaId, Person, PreparedAction, Preflight, Project, ProjectRow, ReadLine, Receipt,
  ReviewBodies, SafeEffects, Session,
} from './types';
export type { PreparedAction } from './types';

const prefix = '/api/commercial-practice/v1';
const actions: readonly Action[] = ['estimate.create', 'estimate.revise', 'estimate.request', 'estimate.accept',
  'estimate.apply', 'estimate.prepareHandoff', 'estimate.createCommitment'];
const units = new Set(['LS', 'EA', 'LF', 'SF', 'SY', 'CY', 'TON', 'HR', 'DAY', 'GAL', 'LB', 'MO']);
const maxCents = 999_999_999_999_999;
const provenanceKeys = ['contractVersion', 'mode', 'synthetic', 'currency'];
const pendingReads = new Set<AbortController>();
const reviewedBodies = new WeakMap<Preflight, string>();
const preparedRequests = new WeakSet<object>();
type ObjectValue = Record<string, unknown>;
const unreadable = () => new Error('The commercial practice server returned an incomplete or unsupported record.');
export class CommercialError extends Error {
  constructor(readonly status: number, readonly problem: { code: string; message: string; target: string | null; fix?: string | null },
    readonly replayed = false, readonly receiptId: string | null = null) { super(problem.message); this.name = 'CommercialError'; }
}
export function isDefinitiveRefusal(error: unknown): error is CommercialError {
  return error instanceof CommercialError && error.status === 412 && ['commercial_source_changed', 'record_changed', 'preflight_changed'].includes(error.problem.code);
}
export function abortScopedReads() { for (const controller of pendingReads) controller.abort(); pendingReads.clear(); }
function object(raw: unknown): ObjectValue {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw unreadable();
  return raw as ObjectValue;
}
function fields(raw: ObjectValue, required: readonly string[], optional: readonly string[] = []) {
  if (required.some(key => !Object.hasOwn(raw, key)) || Object.keys(raw).some(key => !required.includes(key) && !optional.includes(key))) throw unreadable();
}
function text(raw: unknown, limit = 400, empty = false): asserts raw is string {
  if (typeof raw !== 'string' || raw.length > limit || !empty && !raw.trim() || /[\u0000-\u001f\u007f]/.test(raw)) throw unreadable();
}
function id(raw: unknown): asserts raw is string {
  if (typeof raw !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(raw)) throw unreadable();
}
function nullableId(raw: unknown) { if (raw !== null) id(raw); }
function version(raw: unknown): asserts raw is string {
  if (typeof raw !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(raw) || /["\\]/.test(raw)) throw unreadable();
}
function integer(raw: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): asserts raw is number {
  if (!Number.isSafeInteger(raw) || (raw as number) < minimum || (raw as number) > maximum) throw unreadable();
}
function cents(raw: unknown, signed = false): asserts raw is number { integer(raw, signed ? -maxCents : 0, maxCents); }
function decimal(raw: unknown, rate = false): asserts raw is string {
  const pattern = rate ? /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$/ : /^(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,15})?$/;
  if (typeof raw !== 'string' || rate && raw.length > 10 || !pattern.test(raw)) throw unreadable();
}
function timestamp(raw: unknown) {
  if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || Number.isNaN(new Date(raw).valueOf())) throw unreadable();
  const calendar = new Date(raw.slice(0, 10) + 'T00:00:00Z');
  if (calendar.toISOString().slice(0, 10) !== raw.slice(0, 10)) throw unreadable();
}
function bool(raw: unknown): asserts raw is boolean { if (typeof raw !== 'boolean') throw unreadable(); }
function list(raw: unknown, maximum = 5000): unknown[] { if (!Array.isArray(raw) || raw.length > maximum) throw unreadable(); return raw; }
function texts(raw: unknown) { for (const value of list(raw, 32)) text(value, 240); }
function ids(raw: unknown) { const seen = new Set<string>(); for (const value of list(raw)) { id(value); if (seen.has(value)) throw unreadable(); seen.add(value); } }
function member(raw: unknown, values: readonly string[]) { if (typeof raw !== 'string' || !values.includes(raw)) throw unreadable(); }
function publicTree(raw: unknown, allowSessionCsrf = false, depth = 0) {
  if (depth > 20) throw unreadable();
  if (Array.isArray(raw)) { for (const value of raw) publicTree(value, false, depth + 1); return; }
  if (raw && typeof raw === 'object') for (const [key, value] of Object.entries(raw)) {
    if (key === 'csrfToken' && allowSessionCsrf && depth === 0) continue;
    if (/^(?:lease.*|.*token|.*secret|credentials?|.*password|.*hash|proof.*|manifest.*|.*binding|.*capability|providerUrl|realmId|.*policyInventory|cookie.*)$/i.test(key)) throw unreadable();
    if (key.endsWith('Cents')) cents(value, key === 'deltaCents');
    publicTree(value, false, depth + 1);
  }
}
function provenance(raw: unknown, allowSessionCsrf = false): ObjectValue {
  const value = object(raw);
  if (value.contractVersion !== 'cipher.commercial-practice.v1' || value.mode !== 'practice' || value.synthetic !== true || value.currency !== 'USD') {
    throw new Error('This view requires the supported synthetic commercial practice workspace.');
  }
  publicTree(value, allowSessionCsrf); return value;
}
function person(raw: unknown): Person { const value = object(raw); fields(value, ['id', 'displayName']); id(value.id); text(value.displayName, 240); return value as unknown as Person; }
function project(raw: unknown): Project { const value = object(raw); fields(value, ['id', 'name']); id(value.id); text(value.name, 240); return value as unknown as Project; }
function drawing(raw: unknown): DrawingSource {
  const value = object(raw); fields(value, ['documentId', 'documentRevisionId', 'title', 'revision', 'current']);
  id(value.documentId); id(value.documentRevisionId); text(value.title, 240); integer(value.revision, 1); bool(value.current);
  return value as unknown as DrawingSource;
}
function availability(raw: unknown) {
  const seen = new Set<string>();
  for (const item of list(raw, actions.length)) {
    const value = object(item); fields(value, ['action', 'allowed', 'reason', 'target']); member(value.action, actions); bool(value.allowed);
    if (seen.has(value.action as string)) throw unreadable(); seen.add(value.action as string);
    if (value.reason !== null) text(value.reason, 1000); if (value.target !== null) text(value.target, 240);
  }
  return raw as ActionAvailability[];
}
function entry(raw: unknown, read = false): EntryLine {
  const value = object(raw); text(value.description, 240); decimal(value.quantity); text(value.unit, 4);
  if (!units.has((value.unit as string).toUpperCase())) throw unreadable();
  if (read && value.unit !== (value.unit as string).toUpperCase()) throw unreadable();
  cents(value.unitPriceCents); text(value.sourceLocator, 120); text(value.costCode, 240); return value as unknown as EntryLine;
}
function readLine(raw: unknown): ReadLine {
  const value = object(raw); fields(value, ['id', 'lineNo', 'amountCents', 'stableLineId', 'previousLineId', 'measurementMethod', 'verifiedGeometry', 'description', 'quantity', 'unit', 'unitPriceCents', 'sourceLocator', 'costCode']);
  entry(value, true); id(value.id); integer(value.lineNo, 1, 50); cents(value.amountCents); id(value.stableLineId); nullableId(value.previousLineId);
  if (value.measurementMethod !== 'manual_entry' || value.verifiedGeometry !== false) throw unreadable(); return value as unknown as ReadLine;
}
function uniqueLines(raw: unknown, validate: (value: unknown) => { id?: string; stableLineId: string; lineNo?: number; sovLineId?: string | null }) {
  const seen = new Set<string>(); const stable = new Set<string>(); const positions = new Set<number>(); const sov = new Set<string>();
  const sources = new Set<string>(); const sovPositions = new Set<number>();
  const values = list(raw, 50); if (!values.length) throw unreadable();
  for (const item of values) { const value = validate(item);
    if (value.id) { if (seen.has(value.id)) throw unreadable(); seen.add(value.id); }
    if (stable.has(value.stableLineId)) throw unreadable(); stable.add(value.stableLineId);
    if (value.lineNo !== undefined) { if (positions.has(value.lineNo)) throw unreadable(); positions.add(value.lineNo); }
    if (value.sovLineId) { if (sov.has(value.sovLineId)) throw unreadable(); sov.add(value.sovLineId); }
    const source = object(item).estimateLineId; if (source !== undefined) { id(source); if (sources.has(source)) throw unreadable(); sources.add(source); }
    const position = object(item).sovLineNo; if (position !== undefined) { integer(position, 1, 50); if (sovPositions.has(position)) throw unreadable(); sovPositions.add(position); }
  }
}
function acceptance(raw: unknown): Acceptance {
  const value = object(raw); fields(value, ['approvalId', 'requestedBy', 'acceptedBy', 'appliedBy', 'requestedAt', 'acceptedAt', 'appliedAt', 'expiresAt', 'status', 'effectiveStatus']);
  id(value.approvalId); person(value.requestedBy); if (value.acceptedBy !== null) person(value.acceptedBy); if (value.appliedBy !== null) person(value.appliedBy);
  for (const key of ['requestedAt', 'expiresAt']) timestamp(value[key]); for (const key of ['acceptedAt', 'appliedAt']) if (value[key] !== null) timestamp(value[key]);
  member(value.status, ['pending', 'granted', 'consumed', 'expired', 'invalidated']);
  member(value.effectiveStatus, ['pending', 'granted', 'consumed', 'expired', 'invalidated', 'stale']);
  return value as unknown as Acceptance;
}
function estimateRow(raw: unknown): EstimateRow {
  const value = object(raw); id(value.id); version(value.version); project(value.project); integer(value.revision, 1);
  member(value.status, ['draft', 'approved', 'superseded']); member(value.effectiveStatus, ['draft', 'under_review', 'accepted', 'superseded', 'stale']);
  drawing(value.source); for (const key of ['subtotalCents', 'contingencyCents', 'totalCents']) cents(value[key]);
  return value as unknown as EstimateRow;
}
function estimate(raw: unknown, expectedId: string): EstimateRecord {
  const value = provenance(raw); estimateRow(value); if (value.id !== expectedId) throw unreadable();
  fields(value, [...provenanceKeys, 'id', 'version', 'project', 'revision', 'status', 'effectiveStatus', 'source', 'subtotalCents', 'contingencyCents', 'totalCents',
    'lines', 'priceBookRef', 'inclusions', 'exclusions', 'contingencyRate', 'measurementBasis', 'predecessor', 'successor', 'acceptance', 'availableActions', 'markers']);
  uniqueLines(value.lines, readLine); if (value.priceBookRef !== null) text(value.priceBookRef, 240); texts(value.inclusions); texts(value.exclusions);
  decimal(value.contingencyRate, true); text(value.measurementBasis, 400);
  for (const key of ['predecessor', 'successor']) if (value[key] !== null) { const relation = object(value[key]); fields(relation, ['id', 'revision']); id(relation.id); integer(relation.revision, 1); if (relation.id === expectedId) throw unreadable(); }
  if (value.acceptance !== null) acceptance(value.acceptance); availability(value.availableActions);
  for (const item of list(value.markers, 50)) { const marker = object(item); fields(marker, ['code', 'message']); text(marker.code, 128); text(marker.message, 1000); }
  return value as unknown as EstimateRecord;
}
function handoffLine(raw: unknown, sovRequired = false): HandoffLine {
  const value = object(raw); fields(value, ['estimateLineId', 'stableLineId', 'description', 'quantity', 'unit', 'unitPriceCents', 'amountCents', 'costCode', 'sourceLocator', 'measurementBasis', 'measurementMethod', 'verifiedGeometry', 'sovLineId'], sovRequired ? ['sovLineNo'] : []);
  entry(value, true); id(value.estimateLineId); id(value.stableLineId); cents(value.amountCents); text(value.measurementBasis, 400);
  if (value.measurementMethod !== 'manual_entry' || value.verifiedGeometry !== false) throw unreadable();
  if (sovRequired) { id(value.sovLineId); integer(value.sovLineNo, 1, 50); } else nullableId(value.sovLineId);
  return value as unknown as HandoffLine;
}
function supplier(raw: unknown) { const value = object(raw); fields(value, ['id', 'name']); id(value.id); text(value.name, 240); }
function handoff(raw: unknown, expectedId?: string): Handoff {
  const value = provenance(raw); fields(value, [...provenanceKeys, 'id', 'version', 'project', 'estimateId', 'estimateRevision', 'acceptanceApprovalId', 'source', 'status', 'effectiveStatus',
    'supplier', 'commitmentTitle', 'retainageRate', 'subtotalCents', 'contingencyCents', 'totalCents', 'lines', 'commitmentId', 'availableActions', 'consequence']);
  id(value.id); if (expectedId !== undefined && value.id !== expectedId) throw unreadable(); version(value.version); project(value.project); id(value.estimateId); integer(value.estimateRevision, 1);
  id(value.acceptanceApprovalId); drawing(value.source); member(value.status, ['prepared', 'draft_created']); member(value.effectiveStatus, ['prepared', 'draft_created', 'stale']);
  supplier(value.supplier); text(value.commitmentTitle, 240); decimal(value.retainageRate, true); cents(value.subtotalCents); cents(value.totalCents);
  if (value.contingencyCents !== 0) throw unreadable(); nullableId(value.commitmentId); uniqueLines(value.lines, handoffLine);
  if (value.status === 'prepared' && (value.commitmentId !== null || list(value.lines).some(line => object(line).sovLineId !== null)) ||
      value.status === 'draft_created' && (value.commitmentId === null || list(value.lines).some(line => object(line).sovLineId === null))) throw unreadable();
  availability(value.availableActions); text(value.consequence, 1000); return value as unknown as Handoff;
}
function draftCommitment(raw: unknown, expectedId: string): DraftCommitment {
  const value = provenance(raw); fields(value, [...provenanceKeys, 'id', 'version', 'project', 'title', 'status', 'creationStatus', 'effectiveSourceStatus', 'supplier', 'retainageRate', 'originalAmountCents',
    'handoffId', 'estimate', 'source', 'lines', 'executionAvailableHere', 'availableActions', 'consequence', 'relatedRecords']);
  id(value.id); if (value.id !== expectedId || value.creationStatus !== 'draft' || value.executionAvailableHere !== false || list(value.availableActions, 0).length) throw unreadable();
  version(value.version); project(value.project); text(value.title, 240); member(value.status, ['draft', 'executed', 'closed']); member(value.effectiveSourceStatus, ['current', 'stale']); supplier(value.supplier); decimal(value.retainageRate, true); cents(value.originalAmountCents);
  id(value.handoffId); const baseline = object(value.estimate); fields(baseline, ['id', 'revision', 'acceptanceApprovalId']); id(baseline.id); integer(baseline.revision, 1); id(baseline.acceptanceApprovalId); drawing(value.source);
  uniqueLines(value.lines, line => handoffLine(line, true)); text(value.consequence, 1000);
  const linked = new Set<string>(); for (const item of list(value.relatedRecords, 2)) {
    const link = object(item); fields(link, ['type', 'id', 'title', 'apiRoute']); member(link.type, ['estimate', 'handoff']); id(link.id); text(link.title, 240);
    if (linked.has(link.type as string)) throw unreadable(); linked.add(link.type as string);
    const expected = link.type === 'estimate' ? baseline.id : value.handoffId;
    if (link.id !== expected || link.apiRoute !== `${prefix}/${link.type === 'estimate' ? 'estimates' : 'estimate-handoffs'}/${encodeURIComponent(link.id as string)}`) throw unreadable();
  }
  if (linked.size !== 2) throw unreadable(); return value as unknown as DraftCommitment;
}
function comparison(raw: unknown, expectedId: string): Comparison {
  const value = provenance(raw); fields(value, [...provenanceKeys, 'version', 'estimateId', 'predecessorId', 'lines', 'totals', 'scope', 'sourceChanged', 'priceBookChanged']);
  version(value.version); id(value.estimateId); if (value.estimateId !== expectedId) throw unreadable(); nullableId(value.predecessorId); bool(value.sourceChanged); bool(value.priceBookChanged);
  const seen = new Set<string>(); for (const item of list(value.lines, 100)) {
    const line = object(item); fields(line, ['stableLineId', 'kind', 'before', 'after', 'changedFields']); id(line.stableLineId); if (seen.has(line.stableLineId as string)) throw unreadable(); seen.add(line.stableLineId as string);
    member(line.kind, ['added', 'removed', 'changed', 'unchanged']);
    if (line.before !== null && readLine(line.before).stableLineId !== line.stableLineId || line.after !== null && readLine(line.after).stableLineId !== line.stableLineId) throw unreadable();
    if (line.kind === 'added' && (line.before !== null || line.after === null) || line.kind === 'removed' && (line.before === null || line.after !== null) ||
      ['changed', 'unchanged'].includes(line.kind as string) && (line.before === null || line.after === null)) throw unreadable();
    const changed = list(line.changedFields, 7); if (new Set(changed).size !== changed.length) throw unreadable();
    for (const field of changed) member(field, ['description', 'quantity', 'unit', 'unitPriceCents', 'amountCents', 'sourceLocator', 'costCode']);
    if (line.kind === 'unchanged' && changed.length) throw unreadable();
  }
  const totals = object(value.totals); fields(totals, ['afterCents'], ['beforeCents', 'deltaCents']); cents(totals.afterCents);
  if (totals.beforeCents !== undefined) cents(totals.beforeCents); if (totals.deltaCents !== undefined) cents(totals.deltaCents, true);
  if (value.predecessorId === null && (totals.beforeCents !== undefined || totals.deltaCents !== undefined) || (totals.beforeCents === undefined) !== (totals.deltaCents === undefined)) throw unreadable();
  const scope = object(value.scope); fields(scope, ['addedInclusions', 'removedInclusions', 'addedExclusions', 'removedExclusions']); for (const entries of Object.values(scope)) texts(entries);
  return value as unknown as Comparison;
}
function check(raw: unknown): Check {
  const value = object(raw); fields(value, ['code', 'status', 'message', 'target', 'fix']); text(value.code, 128); text(value.message, 1000); member(value.status, ['passed', 'warning', 'blocked']);
  if (value.target !== null) text(value.target, 240); if (value.fix !== undefined && value.fix !== null) text(value.fix, 1000); return value as unknown as Check;
}
function change(raw: unknown): Change {
  const value = object(raw); fields(value, ['code', 'message', 'target', 'affectedRecordIds']); text(value.code, 128); text(value.message, 1000);
  if (value.target !== null) text(value.target, 240); ids(value.affectedRecordIds); return value as unknown as Change;
}
function safeEffects(raw: unknown, action: Action, allowed: boolean): SafeEffects {
  const value = object(raw); fields(value, ['createsEstimateRevision', 'approvalStatus', 'estimateStatus', 'createsAcceptedBaseline', 'createsHandoff', 'createsCommitment',
    'workingLedgerJournalDelta', 'apPayableDeltaCents', 'journalPreview', 'externalAccounting', 'payment', 'providerCallBound', 'customerIssue', 'customerAward', 'budgetAdoption']);
  for (const key of ['createsEstimateRevision', 'createsAcceptedBaseline', 'createsHandoff', 'createsCommitment']) bool(value[key]);
  if (value.approvalStatus !== null) member(value.approvalStatus, ['pending', 'granted', 'consumed']); if (value.estimateStatus !== null) member(value.estimateStatus, ['draft', 'approved', 'superseded']);
  if (value.workingLedgerJournalDelta !== 0 || value.apPayableDeltaCents !== 0 || value.providerCallBound !== 0 || list(value.journalPreview, 0).length || value.externalAccounting !== 'unavailable' ||
    value.payment !== 'not_started' || value.customerIssue !== 'not_started' || value.customerAward !== 'not_started' || value.budgetAdoption !== 'not_started') throw unreadable();
  const expected: Record<string, unknown> = { createsEstimateRevision: false, approvalStatus: null, estimateStatus: null, createsAcceptedBaseline: false, createsHandoff: false, createsCommitment: false };
  const changes: Record<Action, Partial<SafeEffects>> = {
    'estimate.create': { createsEstimateRevision: true, estimateStatus: 'draft' },
    'estimate.revise': { createsEstimateRevision: true, estimateStatus: 'draft' },
    'estimate.request': { approvalStatus: 'pending', estimateStatus: 'draft' },
    'estimate.accept': { approvalStatus: 'granted', estimateStatus: 'draft' },
    'estimate.apply': { approvalStatus: 'consumed', estimateStatus: 'approved', createsAcceptedBaseline: true },
    'estimate.prepareHandoff': { createsHandoff: true, estimateStatus: 'approved' },
    'estimate.createCommitment': { createsCommitment: true, estimateStatus: 'approved' },
  };
  if (allowed) Object.assign(expected, changes[action]);
  if (Object.entries(expected).some(([key, expectedValue]) => value[key] !== expectedValue)) throw unreadable();
  return value as unknown as SafeEffects;
}
function preview(raw: unknown, action: Action, bodyJson: string) {
  const value = object(raw); fields(value, ['lines', 'subtotalCents', 'contingencyCents', 'totalCents', 'revision']); integer(value.revision, 1);
  for (const key of ['subtotalCents', 'contingencyCents', 'totalCents']) cents(value[key]);
  const source = object(JSON.parse(bodyJson)); const input = list(source.lines, 50); const rows = list(value.lines, 50); if (!rows.length || rows.length !== input.length) throw unreadable();
  const positions = new Set<number>(); for (const item of rows) {
    const line = object(item); fields(line, ['lineNo', 'description', 'quantity', 'unit', 'unitPriceCents', 'amountCents', 'sourceLocator', 'costCode', ...(action === 'estimate.revise' ? ['previousLineId'] : [])]);
    entry(line, true); integer(line.lineNo, 1, 50); cents(line.amountCents); if (positions.has(line.lineNo as number)) throw unreadable(); positions.add(line.lineNo as number);
    const original = object(input[(line.lineNo as number) - 1]);
    // Compare source facts without repricing or using floating point. The
    // server still owns all line amounts, contingency and total arithmetic.
    const plainQuantity = (raw: string) => { const [whole, fraction = ''] = raw.split('.'); const tail = fraction.replace(/0+$/, ''); return whole + (tail ? '.' + tail : ''); };
    if (line.unitPriceCents !== original.unitPriceCents || plainQuantity(line.quantity as string) !== plainQuantity(original.quantity as string) ||
      line.description !== (original.description as string).trim() || line.unit !== (original.unit as string).trim().toUpperCase() ||
      line.sourceLocator !== (original.sourceLocator as string).trim() || line.costCode !== (original.costCode as string).trim().split(/\s+/u).join(' ').toUpperCase()) throw unreadable();
    if (action === 'estimate.revise') { nullableId(line.previousLineId); if (line.previousLineId !== original.previousLineId) throw unreadable(); }
  }
}
function validateBody<A extends Action>(action: A, raw: ReviewBodies[A]): string {
  const value = object(raw); const estimateInput = ['documentRevisionId', 'lines', 'priceBookRef', 'inclusions', 'exclusions', 'contingencyRate', 'measurementBasis'];
  fields(value, action === 'estimate.create' ? estimateInput : action === 'estimate.revise' ? [...estimateInput, 'removedExclusions'] : []);
  if (action === 'estimate.create' || action === 'estimate.revise') {
    id(value.documentRevisionId); if (value.priceBookRef !== null) text(value.priceBookRef, 240); texts(value.inclusions); texts(value.exclusions); decimal(value.contingencyRate, true); text(value.measurementBasis, 400);
    if (action === 'estimate.revise') texts(value.removedExclusions);
    const lines = list(value.lines, 50); if (!lines.length) throw unreadable(); const previous = new Set<string>();
    for (const item of lines) { const line = object(item); fields(line, ['description', 'quantity', 'unit', 'unitPriceCents', 'sourceLocator', 'costCode', ...(action === 'estimate.revise' ? ['previousLineId'] : [])]); entry(line);
      if (action === 'estimate.revise') { nullableId(line.previousLineId); if (line.previousLineId !== null) { if (previous.has(line.previousLineId as string)) throw unreadable(); previous.add(line.previousLineId as string); } }
    }
  }
  publicTree(value); const json = JSON.stringify(value); if (new TextEncoder().encode(json).length > 16384) throw unreadable(); return json;
}
function freeze<T>(value: T): T { if (value && typeof value === 'object') { for (const child of Object.values(value)) freeze(child); Object.freeze(value); } return value; }

async function request(path: string, options: { method?: 'POST'; csrf?: string; bodyJson?: string; version?: string; repeatabilityId?: string; signal?: AbortSignal; session?: boolean } = {}) {
  const headers: Record<string, string> = { Accept: 'application/json' }; const isRead = !options.method || path.endsWith(':preflight');
  if (options.method) { text(options.csrf, 256); headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = options.csrf as string;
    if (options.version) { version(options.version); headers['If-Match'] = `"${options.version}"`; }
    if (options.repeatabilityId) { if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(options.repeatabilityId)) throw unreadable(); headers['Repeatability-Request-ID'] = options.repeatabilityId; }
  }
  const controller = isRead ? new AbortController() : null; if (controller) pendingReads.add(controller);
  try {
    const response = await fetch(prefix + path, { method: options.method ?? 'GET', headers, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      ...(options.method ? { body: options.bodyJson ?? '{}' } : {}), signal: controller ? options.signal ? AbortSignal.any([controller.signal, options.signal]) : controller.signal : options.signal });
    let raw: unknown; try { raw = await response.json(); } catch (error) { if (error instanceof Error && error.name === 'AbortError') throw error; throw unreadable(); }
    const value = provenance(raw, options.session === true);
    if (!response.ok) {
      fields(value, [...provenanceKeys, 'error'], ['receiptId', 'replayed', 'effectApplied']);
      const problem = object(value.error); fields(problem, ['code', 'message', 'target', 'fix', 'details']); text(problem.code, 128); text(problem.message, 1000); if (problem.target !== null) text(problem.target, 240);
      if (problem.fix !== null) text(problem.fix, 1000); if (problem.details !== null) throw unreadable();
      const receiptFields = ['receiptId', 'replayed', 'effectApplied']; const hasReceipt = receiptFields.some(key => Object.hasOwn(value, key));
      if (hasReceipt) { if (!receiptFields.every(key => Object.hasOwn(value, key))) throw unreadable(); id(value.receiptId); bool(value.replayed); if (value.effectApplied !== false) throw unreadable(); }
      throw new CommercialError(response.status, problem as unknown as CommercialError['problem'], hasReceipt && value.replayed === true, hasReceipt ? value.receiptId as string : null);
    }
    if (response.status !== 200) throw unreadable();
    if (!options.method && typeof value.version === 'string' && response.headers.get('ETag') !== `"${value.version}"`) throw unreadable();
    return value;
  } finally { if (controller) pendingReads.delete(controller); }
}

export function actionPath(action: Action, resourceId: string) {
  id(resourceId); member(action, actions); const encoded = encodeURIComponent(resourceId);
  const paths: Record<Action, string> = { 'estimate.create': `/projects/${encoded}/create-estimate`, 'estimate.revise': `/estimates/${encoded}/revise`,
    'estimate.request': `/estimates/${encoded}/request-acceptance`, 'estimate.accept': `/estimate-approvals/${encoded}/accept`, 'estimate.apply': `/estimate-approvals/${encoded}/apply`,
    'estimate.prepareHandoff': `/estimates/${encoded}/prepare-handoff`, 'estimate.createCommitment': `/estimate-handoffs/${encoded}/create-commitment` };
  return paths[action];
}
export async function preflight<A extends Action>(action: A, resourceId: string, body: ReviewBodies[A], csrf: string, signal?: AbortSignal): Promise<Preflight> {
  const bodyJson = validateBody(action, body); const value = await request(actionPath(action, resourceId) + ':preflight', { method: 'POST', csrf, bodyJson, signal });
  fields(value, [...provenanceKeys, 'action', 'resourceId', 'resourceVersion', 'version', 'allowed', 'checks', 'changes', 'safeEffects', 'fingerprint'], ['preview']);
  if (value.action !== action || value.resourceId !== resourceId) throw unreadable(); version(value.resourceVersion); if (value.version !== value.resourceVersion) throw unreadable(); bool(value.allowed);
  const checks = list(value.checks, 100).map(check); list(value.changes, 100).forEach(change); safeEffects(value.safeEffects, action, value.allowed);
  if (value.allowed ? typeof value.fingerprint !== 'string' || !value.fingerprint || checks.some(item => item.status === 'blocked') : value.fingerprint !== null || !checks.some(item => item.status === 'blocked')) throw unreadable();
  if (value.fingerprint !== null) text(value.fingerprint, 256);
  const priced = action === 'estimate.create' || action === 'estimate.revise';
  if (priced && value.allowed ? value.preview === undefined : value.preview !== undefined) throw unreadable();
  if (value.preview !== undefined) preview(value.preview, action, bodyJson);
  const review = freeze(value as unknown as Preflight); reviewedBodies.set(review, bodyJson); return review;
}
export function prepareAction<A extends Action>(review: Preflight, body: ReviewBodies[A]): PreparedAction<A> {
  const original = reviewedBodies.get(review); if (!review.allowed || !review.fingerprint || original === undefined || validateBody(review.action as A, body) !== original) throw new Error('Review these exact current commercial facts before applying the action.');
  const mutation = freeze({ ...JSON.parse(original), fingerprint: review.fingerprint }) as PreparedAction<A>['body'];
  const prepared: PreparedAction<A> = Object.freeze({ action: review.action as A, id: review.resourceId, version: review.resourceVersion,
    repeatabilityId: crypto.randomUUID(), body: mutation, bodyJson: JSON.stringify(mutation) }); preparedRequests.add(prepared); return prepared;
}
export async function applyPreparedAction<A extends Action>(prepared: PreparedAction<A>, csrf: string): Promise<Receipt<A>> {
  if (!preparedRequests.has(prepared) || !Object.isFrozen(prepared) || prepared.bodyJson !== JSON.stringify(prepared.body)) throw new Error('Use the original immutable reviewed commercial request.');
  const value = await request(actionPath(prepared.action, prepared.id), { method: 'POST', csrf, bodyJson: prepared.bodyJson, version: prepared.version, repeatabilityId: prepared.repeatabilityId });
  fields(value, [...provenanceKeys, 'receiptId', 'replayed', 'effectApplied', 'result']); id(value.receiptId); bool(value.replayed); bool(value.effectApplied);
  if (value.effectApplied !== !value.replayed) throw unreadable();
  const result = object(value.result); const base = ['action', 'status', 'journalCountDelta', 'apBalanceDeltaCents', 'providerCallsDelta', 'estimateId'];
  const extra: Record<Action, string[]> = { 'estimate.create': ['revision', 'totalCents'], 'estimate.revise': ['predecessorId', 'revision', 'totalCents'],
    'estimate.request': ['approvalId'], 'estimate.accept': ['approvalId'], 'estimate.apply': ['approvalId', 'revision', 'totalCents'],
    'estimate.prepareHandoff': ['handoffId', 'totalCents'], 'estimate.createCommitment': ['commitmentId', 'handoffId', 'totalCents'] };
  const statuses: Record<Action, string> = { 'estimate.create': 'draft', 'estimate.revise': 'draft', 'estimate.request': 'pending', 'estimate.accept': 'granted',
    'estimate.apply': 'approved', 'estimate.prepareHandoff': 'prepared', 'estimate.createCommitment': 'draft' };
  fields(result, [...base, ...extra[prepared.action]]); if (result.action !== prepared.action || result.status !== statuses[prepared.action] ||
    result.journalCountDelta !== 0 || result.apBalanceDeltaCents !== 0 || result.providerCallsDelta !== 0) throw unreadable();
  for (const key of ['estimateId', 'predecessorId', 'approvalId', 'handoffId', 'commitmentId']) if (result[key] !== undefined) id(result[key]);
  if (result.revision !== undefined) integer(result.revision, 1); if (result.totalCents !== undefined) cents(result.totalCents);
  const source = prepared.action === 'estimate.revise' ? result.predecessorId : ['estimate.request', 'estimate.prepareHandoff'].includes(prepared.action) ? result.estimateId
    : ['estimate.accept', 'estimate.apply'].includes(prepared.action) ? result.approvalId : prepared.action === 'estimate.createCommitment' ? result.handoffId : prepared.id;
  if (source !== prepared.id) throw unreadable(); return freeze(value as unknown as Receipt<A>);
}
export const applyAction = applyPreparedAction;
export async function readEstimate(estimateId: string, signal?: AbortSignal) { id(estimateId); return freeze(estimate(await request(`/estimates/${encodeURIComponent(estimateId)}`, { signal }), estimateId)); }
export async function readComparison(estimateId: string, signal?: AbortSignal) { id(estimateId); return freeze(comparison(await request(`/estimates/${encodeURIComponent(estimateId)}/comparison`, { signal }), estimateId)); }
export async function readHandoff(handoffId: string, signal?: AbortSignal) { id(handoffId); return freeze(handoff(await request(`/estimate-handoffs/${encodeURIComponent(handoffId)}`, { signal }), handoffId)); }
export async function readDraftCommitment(commitmentId: string, signal?: AbortSignal) { id(commitmentId); return freeze(draftCommitment(await request(`/commercial-commitments/${encodeURIComponent(commitmentId)}`, { signal }), commitmentId)); }

async function readCollection<T>(collection: string, validate: (value: unknown) => T, signal?: AbortSignal, filters: CollectionFilters = {}): Promise<Collection<T>> {
  const normalized = object(filters); fields(normalized, [], collection === 'projects' ? ['search'] : ['projectId', 'status', 'search']);
  if (filters.projectId !== undefined) id(filters.projectId); if (filters.status !== undefined) text(filters.status, 32); if (filters.search !== undefined) text(filters.search, 200, true);
  const rows: T[] = []; const cursors = new Set<string>(); const identifiers = new Set<string>(); let cursor: string | null = null; let count: number | null = null;
  let first: Collection<T> | null = null;
  do {
    const query = new URLSearchParams({ top: '50', ...filters }); if (cursor) query.set('cursor', cursor);
    const value = await request(`/${collection}?${query}`, { signal }); fields(value, [...provenanceKeys, 'items', 'count', 'nextCursor', 'facets', 'totals']); integer(value.count, 0, 5000);
    if (count !== null && value.count !== count) throw unreadable(); count = value.count as number;
    if (value.nextCursor !== null) text(value.nextCursor, 2000); const facets = object(value.facets); fields(facets, ['statuses']);
    for (const item of list(facets.statuses, 50)) { const facet = object(item); fields(facet, ['value', 'count']); text(facet.value, 32); integer(facet.count); }
    const totals = object(value.totals); fields(totals, [], ['subtotalCents', 'contingencyCents', 'totalCents']); for (const amount of Object.values(totals)) cents(amount);
    if (!first) first = value as unknown as Collection<T>;
    else if (JSON.stringify(first.facets) !== JSON.stringify(value.facets) || JSON.stringify(first.totals) !== JSON.stringify(value.totals)) throw unreadable();
    for (const item of list(value.items, 50)) { const record = validate(item); const identity = object(record).id ?? object(record).approvalId ?? object(record).documentRevisionId; id(identity);
      if (identifiers.has(identity)) throw unreadable(); identifiers.add(identity); rows.push(freeze(record)); }
    cursor = value.nextCursor as string | null; if (cursor && (cursors.has(cursor) || cursors.size >= 100)) throw unreadable(); if (cursor) cursors.add(cursor);
  } while (cursor);
  if (rows.length !== count || !first) throw unreadable(); return freeze({ ...first, items: rows, nextCursor: null });
}
export function readProjects(signal?: AbortSignal, filters?: Pick<CollectionFilters, 'search'>) { return readCollection('projects', projectRow, signal, filters); }
export function readEstimates(signal?: AbortSignal, filters?: CollectionFilters) { return readCollection('estimates', raw => {
  const value = object(raw); fields(value, ['id', 'version', 'project', 'revision', 'status', 'effectiveStatus', 'source', 'subtotalCents', 'contingencyCents', 'totalCents']); return estimateRow(value);
}, signal, filters); }

function projectRow(raw: unknown): ProjectRow {
  const value = object(raw); fields(value, ['id', 'name', 'entity', 'currency', 'estimateCount', 'handoffCount']);
  project({ id: value.id, name: value.name }); text(value.entity, 240); if (value.currency !== 'USD') throw unreadable(); integer(value.estimateCount); integer(value.handoffCount);
  return value as unknown as ProjectRow;
}
function drawingRow(raw: unknown): DrawingRevisionRow {
  const value = object(raw); fields(value, ['documentId', 'documentRevisionId', 'title', 'revision', 'current', 'id', 'version', 'projectId', 'projectName']);
  drawing({ documentId: value.documentId, documentRevisionId: value.documentRevisionId, title: value.title, revision: value.revision, current: value.current });
  id(value.id); if (value.id !== value.documentRevisionId) throw unreadable(); version(value.version); id(value.projectId); text(value.projectName, 240);
  return value as unknown as DrawingRevisionRow;
}
function approvalRow(raw: unknown): EstimateApprovalRow {
  const value = object(raw); fields(value, ['id', 'version', 'project', 'estimateId', 'estimateRevision', 'status', 'effectiveStatus', 'totalCents', 'requestedBy', 'approvedBy',
    'requestedAt', 'grantedAt', 'expiresAt', 'availableActions']); id(value.id); version(value.version); project(value.project); id(value.estimateId); integer(value.estimateRevision, 1); cents(value.totalCents);
  member(value.status, ['pending', 'granted', 'consumed', 'expired', 'invalidated']); member(value.effectiveStatus, ['pending', 'granted', 'consumed', 'expired', 'invalidated', 'stale']);
  person(value.requestedBy); if (value.approvedBy !== null) person(value.approvedBy); timestamp(value.requestedAt); timestamp(value.expiresAt); if (value.grantedAt !== null) timestamp(value.grantedAt);
  if (['granted', 'consumed'].includes(value.status as string) && (value.approvedBy === null || value.grantedAt === null)) throw unreadable();
  availability(value.availableActions); return value as unknown as EstimateApprovalRow;
}
function session(raw: unknown): Session {
  const value = provenance(raw, true); fields(value, [...provenanceKeys, 'authenticated', 'sessionExpiresAt', 'csrfToken', 'person', 'duties', 'projectIds', 'capabilities']);
  bool(value.authenticated); timestamp(value.sessionExpiresAt); text(value.csrfToken, 128);
  if (value.person !== null) { const identity = object(value.person); fields(identity, ['id', 'displayName', 'personaId']); id(identity.id); text(identity.displayName, 240); member(identity.personaId, ['preparer', 'reviewer', 'pm']); }
  if (value.authenticated !== (value.person !== null)) throw unreadable();
  const duties = list(value.duties, 2); if (new Set(duties).size !== duties.length) throw unreadable(); for (const duty of duties) member(duty, ['estimator', 'pm']); ids(value.projectIds);
  if (!value.authenticated && (duties.length || list(value.projectIds).length)) throw unreadable();
  const capability = object(value.capabilities); fields(capability, ['sessionIdentity', 'scopedReads', 'microsoftSignIn', 'liveAdmission', 'externalAccounting', 'manualQuantities', 'verifiedGeometry',
    'customerProposals', 'commitmentExecution', 'commands']);
  if (capability.sessionIdentity !== 'registered_synthetic_person' || capability.scopedReads !== true || capability.microsoftSignIn !== false || capability.liveAdmission !== false ||
    capability.externalAccounting !== 'unavailable' || capability.manualQuantities !== true || capability.verifiedGeometry !== false || capability.customerProposals !== false || capability.commitmentExecution !== false) throw unreadable();
  const commands = list(capability.commands, actions.length); if (commands.length !== actions.length || new Set(commands).size !== actions.length) throw unreadable(); for (const action of commands) member(action, actions);
  return value as unknown as Session;
}
export async function readSession(signal?: AbortSignal) { return freeze(session(await request('/session', { signal, session: true }))); }
export async function readPersonas(signal?: AbortSignal): Promise<Persona[]> {
  const value = await request('/personas', { signal }); fields(value, [...provenanceKeys, 'value']); const seen = new Set<string>();
  for (const item of list(value.value, 3)) { const persona = object(item); fields(persona, ['personaId', 'displayName', 'synthetic']); member(persona.personaId, ['preparer', 'reviewer', 'pm']); text(persona.displayName, 240);
    if (persona.synthetic !== true || seen.has(persona.personaId as string)) throw unreadable(); seen.add(persona.personaId as string); }
  if (seen.size !== 3) throw unreadable(); return freeze(value.value as Persona[]);
}
export async function bindSession(personaId: PersonaId, csrf: string): Promise<Session> {
  member(personaId, ['preparer', 'reviewer', 'pm']); abortScopedReads();
  return freeze(session(await request('/session', { method: 'POST', csrf, bodyJson: JSON.stringify({ personaId }), session: true })));
}
export async function endSession(csrf: string): Promise<Session> {
  abortScopedReads(); return freeze(session(await request('/session/logout', { method: 'POST', csrf, session: true })));
}
export function readDrawingRevisions(signal?: AbortSignal, filters?: CollectionFilters) { return readCollection('drawing-revisions', drawingRow, signal, filters); }
export function readApprovals(signal?: AbortSignal, filters?: CollectionFilters) { return readCollection('estimate-approvals', approvalRow, signal, filters); }
export function readHandoffs(signal?: AbortSignal, filters?: CollectionFilters) { return readCollection('estimate-handoffs', handoff, signal, filters); }
export async function readEstimatePreparation(projectId: string, signal?: AbortSignal): Promise<EstimatePreparation> {
  id(projectId); const value = await request(`/projects/${encodeURIComponent(projectId)}/estimate-preparation`, { signal });
  fields(value, [...provenanceKeys, 'version', 'project', 'drawingRevisions', 'units', 'inputMode', 'verifiedGeometry', 'availableActions']); version(value.version); const context = project(value.project);
  if (context.id !== projectId || value.inputMode !== 'manual_entry' || value.verifiedGeometry !== false) throw unreadable();
  const revisions = new Set<string>(); for (const raw of list(value.drawingRevisions, 100)) { const row = drawingRow(raw);
    if (row.projectId !== projectId || row.projectName !== context.name || !row.current || revisions.has(row.id)) throw unreadable(); revisions.add(row.id); }
  const registry = new Set<string>(); for (const raw of list(value.units, 50)) { const unit = object(raw); fields(unit, ['unit', 'name', 'measured']); text(unit.unit, 4); text(unit.name, 240); bool(unit.measured);
    if (!units.has(unit.unit as string) || registry.has(unit.unit as string)) throw unreadable(); registry.add(unit.unit as string); }
  if (!registry.size) throw unreadable(); availability(value.availableActions); return freeze(value as unknown as EstimatePreparation);
}
export async function readAcceptancePacket(approvalId: string, signal?: AbortSignal): Promise<ApprovalPacket> {
  id(approvalId); const value = await request(`/estimate-approvals/${encodeURIComponent(approvalId)}/packet`, { signal });
  fields(value, [...provenanceKeys, 'version', 'approval', 'estimate', 'comparison', 'summary', 'consequence', 'checks', 'availableActions']); version(value.version);
  const approval = approvalRow(value.approval); if (approval.id !== approvalId || approval.version !== value.version) throw unreadable(); const source = estimate(value.estimate, approval.estimateId);
  if (approval.project.id !== source.project.id || approval.estimateRevision !== source.revision || approval.totalCents !== source.totalCents) throw unreadable();
  comparison(value.comparison, source.id); text(value.summary, 1000); text(value.consequence, 1000); list(value.checks, 100).forEach(check); availability(value.availableActions);
  return freeze(value as unknown as ApprovalPacket);
}
export async function readHandoffPreparation(estimateId: string, signal?: AbortSignal): Promise<HandoffPreparation> {
  id(estimateId); const value = await request(`/estimates/${encodeURIComponent(estimateId)}/handoff-preparation`, { signal });
  fields(value, [...provenanceKeys, 'version', 'project', 'estimate', 'package', 'lines', 'subtotalCents', 'contingencyCents', 'totalCents', 'existingHandoffId', 'checks', 'availableActions', 'consequence']);
  version(value.version); const context = project(value.project); const source = estimate(value.estimate, estimateId); if (context.id !== source.project.id) throw unreadable();
  const packageValue = object(value.package); fields(packageValue, ['id', 'title', 'supplier', 'retainageRate']); id(packageValue.id); text(packageValue.title, 240); supplier(packageValue.supplier); decimal(packageValue.retainageRate, true);
  uniqueLines(value.lines, handoffLine); cents(value.subtotalCents); cents(value.contingencyCents); cents(value.totalCents); if (value.contingencyCents !== source.contingencyCents || value.subtotalCents !== source.subtotalCents || value.totalCents !== source.totalCents) throw unreadable();
  const inputLines = source.lines; const mapped = list(value.lines); if (mapped.length !== inputLines.length) throw unreadable();
  for (const raw of mapped) { const line = handoffLine(raw); const original = inputLines.find(item => item.id === line.estimateLineId);
    if (!original || line.stableLineId !== original.stableLineId || line.description !== original.description || line.quantity !== original.quantity || line.unit !== original.unit ||
      line.unitPriceCents !== original.unitPriceCents || line.amountCents !== original.amountCents || line.costCode !== original.costCode || line.sourceLocator !== original.sourceLocator ||
      line.measurementBasis !== source.measurementBasis || line.sovLineId !== null) throw unreadable(); }
  nullableId(value.existingHandoffId); list(value.checks, 100).forEach(check); availability(value.availableActions); text(value.consequence, 1000);
  return freeze(value as unknown as HandoffPreparation);
}
