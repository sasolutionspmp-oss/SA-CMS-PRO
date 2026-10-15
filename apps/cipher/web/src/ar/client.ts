import type { Action, Aging, Approval, ApprovalPacket, Basis, Calculation, Check, Collection, Filters, JournalLine, OwnerBill, OwnerLine, OwnerSOVLine, Period, Persona, PersonaId, Person, Preparation, PreparedAction, Preflight, Preview, Project, Receipt, ReviewBodies, SafeEffects, SendPreparation, Session, Source } from './types';
export type { PreparedAction } from './types';
const prefix = '/api/ar-practice/v1';
const actions: readonly Action[] = ['ownerBill.prepare', 'ownerBill.requestApproval', 'ownerBill.approve', 'ownerBill.post', 'ownerBill.requestSend', 'ownerBill.approveSend', 'ownerBill.send'];
const provenanceKeys = 'contractVersion mode synthetic currency';
const maxCents = 9_000_000_000_000;
const approvalStatuses = ['pending', 'granted', 'consumed', 'expired', 'invalidated'];
const billStatuses = ['draft', 'posted', 'sent', 'collected', 'void', 'reversed'];
const billStates = ['draft', 'under_review', 'approved_not_posted', 'posted_awaiting_send', 'sent_open', 'settled', 'void', 'reversed', 'stale'];
const pendingReads = new Set<AbortController>();
const reviewedBodies = new WeakMap<Preflight, string>();
const preparedRequests = new WeakSet<object>();
type Obj = Record<string, unknown>;
const unreadable = () => new Error('The AR practice server returned an incomplete or unsupported record.');
export class ARError extends Error {
  constructor(readonly status: number, readonly problem: { code: string; message: string; target: string | null; fix?: string | null }, readonly replayed = false, readonly receiptId: string | null = null) { super(problem.message); this.name = 'ARError'; }
}
export function isDefinitiveRefusal(error: unknown): error is ARError {
  return error instanceof ARError && error.status === 412 && ['owner_source_changed', 'record_changed', 'preflight_changed'].includes(error.problem.code);
}
export function abortScopedReads() { for (const controller of pendingReads) controller.abort(); pendingReads.clear(); }
function object(raw: unknown): Obj { if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw unreadable(); return raw as Obj; }
function shape(raw: unknown, required: string, optional = ''): Obj {
  const value = object(raw); const keys = required.split(' ').filter(Boolean); const allowed = [...keys, ...optional.split(' ').filter(Boolean)];
  if (keys.some(key => !Object.hasOwn(value, key)) || Object.keys(value).some(key => !allowed.includes(key))) throw unreadable(); return value;
}
function text(raw: unknown, maximum = 400, empty = false): asserts raw is string { if (typeof raw !== 'string' || raw.length > maximum || !empty && !raw.trim() || /[\u0000-\u001f\u007f]/.test(raw)) throw unreadable(); }
function id(raw: unknown): asserts raw is string { if (typeof raw !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(raw)) throw unreadable(); }
function version(raw: unknown): asserts raw is string { if (typeof raw !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(raw) || /["\\]/.test(raw)) throw unreadable(); }
function integer(raw: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): asserts raw is number { if (!Number.isSafeInteger(raw) || (raw as number) < minimum || (raw as number) > maximum) throw unreadable(); }
function cents(raw: unknown, signed = false): asserts raw is number { integer(raw, signed ? -maxCents : 0, maxCents); }
function bool(raw: unknown): asserts raw is boolean { if (typeof raw !== 'boolean') throw unreadable(); }
function member(raw: unknown, values: readonly string[]) { if (typeof raw !== 'string' || !values.includes(raw)) throw unreadable(); }
function list(raw: unknown, maximum = 5000): unknown[] { if (!Array.isArray(raw) || raw.length > maximum) throw unreadable(); return raw; }
function calendar(raw: unknown): asserts raw is string { if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) throw unreadable(); const parsed = new Date(raw + 'T12:00:00Z'); if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== raw) throw unreadable(); }
function timestamp(raw: unknown) { if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || Number.isNaN(new Date(raw).valueOf())) throw unreadable(); calendar(raw.slice(0, 10)); }
function decimal(raw: unknown, dollars = false): asserts raw is string { if (typeof raw !== 'string' || !(dollars ? /^(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$/ : /^(?:0|[1-9]\d{0,11})(?:\.\d{1,6})?$/).test(raw)) throw unreadable(); }
function rate(raw: unknown) { if (typeof raw !== 'string' || !/^(?:0|1)(?:\.\d{1,6})?$/.test(raw) || raw.startsWith('1.') && /[1-9]/.test(raw.slice(2))) throw unreadable(); }
export const canonicalMeasure = (raw: string) => { const [whole, fraction = ''] = raw.split('.'); const tail = fraction.replace(/0+$/, ''); return whole + (tail ? '.' + tail : ''); };
function publicTree(raw: unknown, csrf = false, depth = 0) {
  if (depth > 24) throw unreadable(); if (Array.isArray(raw)) { raw.forEach(value => publicTree(value, false, depth + 1)); return; }
  if (raw && typeof raw === 'object') for (const [key, value] of Object.entries(raw)) {
    if (key === 'csrfToken' && csrf && depth === 0) continue;
    if (/^(?:lease.*|.*token|.*secret|credentials?|.*password|.*hash|proof.*|manifest.*|.*binding|.*capability|realmId|providerUrl|cookie.*)$/i.test(key)) throw unreadable();
    if (key.endsWith('Cents') && !(key === 'unitPriceCents' && value === null)) cents(value, true); publicTree(value, false, depth + 1);
  }
}
function provenance(raw: unknown, csrf = false): Obj {
  const value = object(raw); if (value.contractVersion !== 'cipher.ar-practice.v1' || value.mode !== 'practice' || value.synthetic !== true || value.currency !== 'USD') throw new Error('This view requires the supported synthetic AR practice workspace.');
  publicTree(value, csrf); return value;
}
function freeze<T>(value: T): T { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; }
function person(raw: unknown): Person { const value = shape(raw, 'id displayName'); id(value.id); text(value.displayName, 240); return value as unknown as Person; }
function project(raw: unknown): Project { const value = shape(raw, 'id name'); id(value.id); text(value.name, 240); return value as unknown as Project; }
function period(raw: unknown, status = true): Period { const value = shape(raw, 'id name startDate endDate' + (status ? ' status' : '')); id(value.id); text(value.name, 120); calendar(value.startDate); calendar(value.endDate); if (value.startDate > value.endDate) throw unreadable(); if (status) member(value.status, ['open', 'closed']); return value as unknown as Period; }
function source(raw: unknown, kind?: string): Source { const value = shape(raw, 'documentId revisionId title kind revision current'); id(value.documentId); id(value.revisionId); text(value.title, 240); member(value.kind, ['owner_agreement', 'owner_claim', 'owner_certification']); if (kind && value.kind !== kind) throw unreadable(); integer(value.revision, 1); bool(value.current); return value as unknown as Source; }
function availability(raw: unknown): Action[] { const rows = list(raw, actions.length); const seen = new Set(); for (const item of rows) { member(item, actions); if (seen.has(item)) throw unreadable(); seen.add(item); } return raw as Action[]; }
function check(raw: unknown): Check { const value = shape(raw, 'code status target message fix'); text(value.code, 128); member(value.status, ['passed', 'warning', 'blocked']); if (value.target !== null) text(value.target, 240); text(value.message, 1000); if (value.fix !== null) text(value.fix, 1000); return value as unknown as Check; }
const sovKeys = 'lineId description basis scheduledAmountCents unit contractQuantity unitPriceCents';
const progressKeys = 'previousQuantity claimedQuantity reviewedQuantity previousAmountCents claimedAmountCents reviewedAmountCents thisPeriodCents differenceAmountCents differenceReason';
function sov(raw: unknown, exact = true): OwnerSOVLine {
  const value = exact ? shape(raw, sovKeys) : object(raw); id(value.lineId); if ((value.lineId as string).length > 64) throw unreadable(); text(value.description, 240); member(value.basis, ['unitPrice', 'lumpSum']); cents(value.scheduledAmountCents);
  if (value.basis === 'unitPrice') { text(value.unit, 32); decimal(value.contractQuantity); cents(value.unitPriceCents); }
  else if (value.unit !== null || value.contractQuantity !== null || value.unitPriceCents !== null) throw unreadable();
  return value as unknown as OwnerSOVLine;
}
function ownerLine(raw: unknown, locators = true): OwnerLine {
  const value = shape(raw, sovKeys + ' ' + progressKeys + (locators ? ' claimSourceLocator reviewSourceLocator' : '')); sov(value, false);
  for (const key of ['previousAmountCents', 'claimedAmountCents', 'reviewedAmountCents', 'thisPeriodCents']) cents(value[key]); cents(value.differenceAmountCents, true); text(value.differenceReason, 500, true);
  for (const key of ['previousQuantity', 'claimedQuantity', 'reviewedQuantity']) if (value.basis === 'unitPrice') decimal(value[key]); else if (value[key] !== null) throw unreadable();
  if ((value.differenceAmountCents !== 0 || value.basis === 'unitPrice' && canonicalMeasure(value.claimedQuantity as string) !== canonicalMeasure(value.reviewedQuantity as string)) && !(value.differenceReason as string).trim()) throw unreadable();
  if (locators) { text(value.claimSourceLocator, 240); text(value.reviewSourceLocator, 240); } return value as unknown as OwnerLine;
}
function unique<T>(raw: unknown, validate: (item: unknown) => T, key: (item: T) => string, maximum = 100, nonempty = true): T[] {
  const rows = list(raw, maximum).map(validate); if (nonempty && !rows.length) throw unreadable(); const ids = rows.map(key); if (new Set(ids).size !== ids.length) throw unreadable(); return rows;
}
function journal(raw: unknown): JournalLine[] {
  const rows = list(raw, 10).map(item => { const value = shape(item, 'accountCode debitCents creditCents memo'); member(value.accountCode, ['1100', '1150', '4000']); cents(value.debitCents); cents(value.creditCents); text(value.memo, 500); if ((value.debitCents === 0) === (value.creditCents === 0)) throw unreadable(); return value as unknown as JournalLine; });
  if (rows.reduce((sum, line) => sum + BigInt(line.debitCents) - BigInt(line.creditCents), 0n) !== 0n) throw unreadable(); return rows;
}
function sourceEntry(raw: unknown, amountDue: unknown, retained: unknown, revenue: unknown) {
  cents(amountDue); cents(retained, true); cents(revenue); const lines = journal(raw);
  if (!lines.length || new Set(lines.map(line => line.accountCode)).size !== lines.length) throw unreadable();
  const expected: Record<string, bigint> = { '1100': BigInt(amountDue), '1150': BigInt(retained), '4000': -BigInt(revenue) };
  for (const [account, amount] of Object.entries(expected)) {
    const actual = lines.filter(line => line.accountCode === account).reduce((net, line) => net + BigInt(line.debitCents) - BigInt(line.creditCents), 0n);
    if (actual !== amount) throw unreadable();
  }
}
function calculation(raw: unknown): Calculation {
  const value = shape(raw, 'calculationVersion lines primeContractValueCents priorCertifiedCents claimedCertifiedCents reviewedCertifiedCents priorRetainedCents retainageReleasedCents retainageRate retainedCumulativeCents retainageThisPeriodCents revenueThisPeriodCents amountDueCents journalPreview');
  if (value.calculationVersion !== 'cipher.owner-billing-calculation.v1') throw unreadable(); unique(value.lines, item => ownerLine(item, false), item => item.lineId);
  for (const key of Object.keys(value).filter(key => key.endsWith('Cents'))) cents(value[key], key === 'retainageThisPeriodCents'); rate(value.retainageRate); sourceEntry(value.journalPreview, value.amountDueCents, value.retainageThisPeriodCents, value.revenueThisPeriodCents); return value as unknown as Calculation;
}
function basis(raw: unknown, expected?: string): Basis {
  const value = provenance(raw); shape(value, provenanceKeys + ' id version project customer contractValueCents retainageRate termsDays agreementSource sov sourceStatus declaration availableActions'); id(value.id); if (expected && value.id !== expected) throw unreadable(); version(value.version); project(value.project); project(value.customer); cents(value.contractValueCents); rate(value.retainageRate); integer(value.termsDays, 0, 365); source(value.agreementSource, 'owner_agreement'); unique(value.sov, item => sov(item), item => item.lineId); member(value.sourceStatus, ['current', 'stale']); text(value.declaration, 1000); availability(value.availableActions); return value as unknown as Basis;
}
function approval(raw: unknown, expected?: string): Approval {
  const value = provenance(raw); shape(value, provenanceKeys + ' id version type billId project sequence status effectiveStatus requestedBy approvedBy requestedAt approvedAt expiresAt availableActions blockedReasons'); id(value.id); if (expected && value.id !== expected) throw unreadable(); version(value.version); member(value.type, ['business', 'send']); id(value.billId); project(value.project); integer(value.sequence, 1); member(value.status, approvalStatuses); member(value.effectiveStatus, [...approvalStatuses, 'stale']); person(value.requestedBy); if (value.approvedBy !== null) person(value.approvedBy); timestamp(value.requestedAt); timestamp(value.expiresAt); if (value.approvedAt !== null) timestamp(value.approvedAt); if (['granted', 'consumed'].includes(value.status as string) && (value.approvedBy === null || value.approvedAt === null)) throw unreadable(); availability(value.availableActions); list(value.blockedReasons, 100).forEach(check); return value as unknown as Approval;
}
function bill(raw: unknown, expected?: string): OwnerBill {
  const value = provenance(raw); shape(value, provenanceKeys + ' id version project customer sequence status effectiveStatus certificationPeriod invoiceDate dueDate termsDays basis claimSource reviewSource lines totals businessApproval posting send availableActions blockedReasons relatedRecords officialBooks externalSettlement'); id(value.id); if (expected && value.id !== expected) throw unreadable(); version(value.version); project(value.project); project(value.customer); integer(value.sequence, 1); member(value.status, billStatuses); member(value.effectiveStatus, billStates); period(value.certificationPeriod); calendar(value.invoiceDate); if (value.dueDate !== null) calendar(value.dueDate); if (value.termsDays !== null) integer(value.termsDays, 0, 365);
  const declared = shape(value.basis, 'id agreementSource'); id(declared.id); source(declared.agreementSource, 'owner_agreement'); const claim = source(value.claimSource, 'owner_claim'); const review = source(value.reviewSource, 'owner_certification'); if (claim.documentId === review.documentId || claim.revisionId === review.revisionId) throw unreadable();
  unique(value.lines, item => ownerLine(item), item => item.lineId); const totals = shape(value.totals, 'priorCertifiedCents claimedCertifiedCents reviewedCertifiedCents revenueThisPeriodCents retainageThisPeriodCents retainedCumulativeCents amountDueCents currentOpenCents currentReceivedCents currentCreditedCents currentWrittenOffCents currentDepositsAppliedCents'); for (const [key, amount] of Object.entries(totals)) cents(amount, key === 'retainageThisPeriodCents');
  let reviewer: Person | null = null;
  if (value.businessApproval !== null) { const grant = shape(value.businessApproval, 'id approvalId status authorizationStatus requestedBy reviewedBy reviewedAt'); id(grant.id); id(grant.approvalId); if (grant.status !== 'granted') throw unreadable(); member(grant.authorizationStatus, approvalStatuses); const requester = person(grant.requestedBy); reviewer = person(grant.reviewedBy); if (requester.id === reviewer.id) throw unreadable(); timestamp(grant.reviewedAt); }
  if (value.posting !== null) { const posting = shape(value.posting, 'receiptId journalId period postedBy postedAt journalPreview'); id(posting.receiptId); id(posting.journalId); const postedPeriod = period(posting.period); const poster = person(posting.postedBy); if (!reviewer || reviewer.id === poster.id || postedPeriod.id !== object(value.certificationPeriod).id) throw unreadable(); timestamp(posting.postedAt); sourceEntry(posting.journalPreview, totals.amountDueCents, totals.retainageThisPeriodCents, totals.revenueThisPeriodCents); }
  if (value.send !== null) { const send = shape(value.send, 'id status channel sentAt sentBy recipients externalDelivery'); id(send.id); if (send.status !== 'sent_to_synthetic_sink' || send.channel !== 'mail-sink' || send.externalDelivery !== false || value.posting === null) throw unreadable(); timestamp(send.sentAt); person(send.sentBy); recipients(send.recipients); }
  if (value.posting !== null) {
    if (!['posted', 'sent', 'collected', 'reversed'].includes(value.status as string) || value.businessApproval === null || object(value.businessApproval).authorizationStatus !== 'consumed') throw unreadable();
    if (value.status === 'reversed' ? value.effectiveStatus !== 'reversed' : value.effectiveStatus !== (totals.currentOpenCents === 0 ? 'settled' : value.send !== null ? 'sent_open' : 'posted_awaiting_send')) throw unreadable();
    if (value.status === 'sent' && value.send === null) throw unreadable();
  } else {
    if (!['draft', 'void'].includes(value.status as string) || value.businessApproval !== null && object(value.businessApproval).authorizationStatus === 'consumed') throw unreadable();
    if (['currentOpenCents', 'currentReceivedCents', 'currentCreditedCents', 'currentWrittenOffCents', 'currentDepositsAppliedCents'].some(key => totals[key] !== 0)) throw unreadable();
    if (value.status === 'void' ? value.effectiveStatus !== 'void' : !['draft', 'under_review', 'approved_not_posted', 'stale'].includes(value.effectiveStatus as string)) throw unreadable();
    if (value.effectiveStatus === 'approved_not_posted' && (value.businessApproval === null || object(value.businessApproval).authorizationStatus !== 'granted')) throw unreadable();
  }
  availability(value.availableActions); list(value.blockedReasons, 100).forEach(check);
  for (const raw of list(value.relatedRecords, 20)) { const link = shape(raw, 'type id title apiRoute'); text(link.type, 64); id(link.id); text(link.title, 240); const permitted = [`${prefix}/owner-bases/${link.id}/preparation`, `${prefix}/owner-bills/${link.id}`, `${prefix}/owner-bill-approvals/${link.id}/packet`, `${prefix}/owner-send-approvals/${link.id}/packet`]; if (!permitted.includes(link.apiRoute as string)) throw unreadable(); }
  if (value.officialBooks !== 'unavailable' || value.externalSettlement !== false) throw unreadable(); return value as unknown as OwnerBill;
}
function recipients(raw: unknown) { const values = list(raw, 10); if (!values.length || new Set(values).size !== values.length) throw unreadable(); for (const item of values) if (item !== 'owner-billing@synthetic-owner.invalid') throw unreadable(); }
function preview(raw: unknown, action: Action, bodyJson: string): Preview {
  const value = shape(raw, 'calculation period invoiceDate dueDate datePolicy delivery'); const calculated = calculation(value.calculation); period(value.period, false); calendar(value.invoiceDate); if (value.dueDate !== null) calendar(value.dueDate); if (value.datePolicy !== 'practice.invoice-date.period-start.v1' || value.invoiceDate !== object(value.period).startDate) throw unreadable();
  if (value.delivery !== null) { const delivery = shape(value.delivery, 'channel recipients amountDueCents balanceDueCents'); if (delivery.channel !== 'mail-sink') throw unreadable(); recipients(delivery.recipients); cents(delivery.amountDueCents); cents(delivery.balanceDueCents); if (delivery.amountDueCents !== calculated.amountDueCents) throw unreadable(); }
  if (action === 'ownerBill.prepare') {
    const original = object(JSON.parse(bodyJson)); if (original.periodId !== object(value.period).id) throw unreadable(); const submitted = list(original.lines, 100).map(object); if (submitted.length !== calculated.lines.length) throw unreadable();
    for (const line of calculated.lines) { const input = submitted.find(item => item.lineId === line.lineId); if (!input || line.differenceReason !== (input.differenceReason as string).trim()) throw unreadable(); if (line.basis === 'unitPrice') { if (canonicalMeasure(line.claimedQuantity!) !== canonicalMeasure(input.claimedCumulative as string) || canonicalMeasure(line.reviewedQuantity!) !== canonicalMeasure(input.reviewedCumulative as string)) throw unreadable(); }
      else { const centsOf = (raw: string) => { const [whole, fraction = ''] = raw.split('.'); return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0')); }; if (BigInt(line.claimedAmountCents) !== centsOf(input.claimedCumulative as string) || BigInt(line.reviewedAmountCents) !== centsOf(input.reviewedCumulative as string)) throw unreadable(); }
    }
  }
  return value as unknown as Preview;
}
function effects(raw: unknown, action: Action, allowed: boolean, priced?: Preview): SafeEffects {
  const value = shape(raw, 'createsDraft createsApproval grantsApproval approvalStatus billStatus workingLedgerJournalDelta arReceivableDeltaCents retainedARDeltaCents revenueDeltaCents journalPreview syntheticSendDelta mailSinkOnly externalAccounting quickBooksAccepted externalDelivery externalSettlement');
  for (const key of ['createsDraft', 'createsApproval', 'grantsApproval']) bool(value[key]); if (value.approvalStatus !== null) member(value.approvalStatus, approvalStatuses); if (value.billStatus !== null) member(value.billStatus, billStatuses);
  integer(value.workingLedgerJournalDelta, 0, 1); integer(value.syntheticSendDelta, 0, 1); cents(value.arReceivableDeltaCents); cents(value.retainedARDeltaCents, true); cents(value.revenueDeltaCents); journal(value.journalPreview);
  if (value.mailSinkOnly !== true || value.externalAccounting !== 'unavailable' || value.quickBooksAccepted !== false || value.externalDelivery !== false || value.externalSettlement !== false) throw unreadable();
  if (value.createsDraft !== (allowed && action === 'ownerBill.prepare') || value.createsApproval !== (allowed && ['ownerBill.requestApproval', 'ownerBill.requestSend'].includes(action)) || value.grantsApproval !== (allowed && ['ownerBill.approve', 'ownerBill.approveSend'].includes(action))) throw unreadable();
  const states: Record<Action, readonly [string | null, string | null]> = { 'ownerBill.prepare': [null, 'draft'], 'ownerBill.requestApproval': ['pending', 'draft'], 'ownerBill.approve': ['granted', 'draft'], 'ownerBill.post': ['consumed', 'posted'], 'ownerBill.requestSend': ['pending', 'posted'], 'ownerBill.approveSend': ['granted', 'posted'], 'ownerBill.send': ['consumed', 'sent'] };
  const expectedState = allowed ? states[action] : [null, null]; if (value.approvalStatus !== expectedState[0] || value.billStatus !== expectedState[1]) throw unreadable();
  if (value.workingLedgerJournalDelta !== (allowed && action === 'ownerBill.post' ? 1 : 0) || value.syntheticSendDelta !== (allowed && action === 'ownerBill.send' ? 1 : 0)) throw unreadable();
  if (allowed && action === 'ownerBill.post') { if (!priced || value.arReceivableDeltaCents !== priced.calculation.amountDueCents || value.retainedARDeltaCents !== priced.calculation.retainageThisPeriodCents || value.revenueDeltaCents !== priced.calculation.revenueThisPeriodCents || JSON.stringify(value.journalPreview) !== JSON.stringify(priced.calculation.journalPreview)) throw unreadable(); }
  else if (value.arReceivableDeltaCents !== 0 || value.retainedARDeltaCents !== 0 || value.revenueDeltaCents !== 0 || list(value.journalPreview).length) throw unreadable();
  return value as unknown as SafeEffects;
}
function validateBody<A extends Action>(action: A, raw: ReviewBodies[A]): string {
  member(action, actions); const value = shape(raw, action === 'ownerBill.prepare' ? 'claimRevisionId reviewRevisionId periodId lines' : '');
  if (action === 'ownerBill.prepare') { id(value.claimRevisionId); id(value.reviewRevisionId); id(value.periodId); if (value.claimRevisionId === value.reviewRevisionId) throw unreadable(); unique(value.lines, item => { const line = shape(item, 'lineId claimedCumulative reviewedCumulative differenceReason claimSourceLocator reviewSourceLocator'); id(line.lineId); if ((line.lineId as string).length > 64) throw unreadable(); decimal(line.claimedCumulative); decimal(line.reviewedCumulative); text(line.differenceReason, 500, true); text(line.claimSourceLocator, 240); text(line.reviewSourceLocator, 240); return line; }, line => line.lineId as string); }
  publicTree(value); const json = JSON.stringify(value); if (new TextEncoder().encode(json).length > 16384) throw unreadable(); return json;
}
async function request(path: string, options: { method?: 'POST'; csrf?: string; bodyJson?: string; version?: string; repeatabilityId?: string; signal?: AbortSignal; session?: boolean } = {}) {
  const headers: Record<string, string> = { Accept: 'application/json' }; const isRead = !options.method || path.endsWith(':preflight');
  if (options.method) { text(options.csrf, 256); headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = options.csrf as string; if (options.version) { version(options.version); headers['If-Match'] = `"${options.version}"`; } if (options.repeatabilityId) { if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(options.repeatabilityId)) throw unreadable(); headers['Repeatability-Request-ID'] = options.repeatabilityId; } }
  const controller = isRead ? new AbortController() : null; if (controller) pendingReads.add(controller);
  try { const response = await fetch(prefix + path, { method: options.method ?? 'GET', headers, credentials: 'same-origin', cache: 'no-store', redirect: 'error', ...(options.method ? { body: options.bodyJson ?? '{}' } : {}), signal: controller ? options.signal ? AbortSignal.any([controller.signal, options.signal]) : controller.signal : options.signal });
    let raw: unknown; try { raw = await response.json(); } catch (error) { if (error instanceof Error && error.name === 'AbortError') throw error; throw unreadable(); }
    const value = provenance(raw, options.session);
    if (!response.ok) {
      shape(value, provenanceKeys + ' error', 'receiptId replayed effectApplied');
      const error = shape(value.error, 'code message target fix details'); text(error.code, 128); text(error.message, 1000); if (error.target !== null) text(error.target, 240); if (error.fix !== null) text(error.fix, 1000); if (error.details !== null) throw unreadable();
      const receiptFields = ['receiptId', 'replayed', 'effectApplied']; const hasReceipt = receiptFields.some(key => Object.hasOwn(value, key));
      if (hasReceipt) { if (!receiptFields.every(key => Object.hasOwn(value, key))) throw unreadable(); id(value.receiptId); bool(value.replayed); if (value.effectApplied !== false) throw unreadable(); }
      throw new ARError(response.status, error as unknown as ARError['problem'], hasReceipt && value.replayed === true, hasReceipt ? value.receiptId as string : null);
    }
    if (response.status !== 200 || !options.method && typeof value.version === 'string' && response.headers.get('ETag') !== `"${value.version}"`) throw unreadable(); return value;
  } finally { if (controller) pendingReads.delete(controller); }
}
export function actionPath(action: Action, resourceId: string) {
  id(resourceId); member(action, actions); const encoded = encodeURIComponent(resourceId); const routes: Record<Action, string> = {
    'ownerBill.prepare': `/owner-bases/${encoded}/prepare-bill`, 'ownerBill.requestApproval': `/owner-bills/${encoded}/request-approval`, 'ownerBill.approve': `/owner-bill-approvals/${encoded}/approve`, 'ownerBill.post': `/owner-bills/${encoded}/post`, 'ownerBill.requestSend': `/owner-bills/${encoded}/request-send`, 'ownerBill.approveSend': `/owner-send-approvals/${encoded}/approve`, 'ownerBill.send': `/owner-send-approvals/${encoded}/send`,
  }; return routes[action];
}
export async function preflight<A extends Action>(action: A, resourceId: string, body: ReviewBodies[A], csrf: string, signal?: AbortSignal): Promise<Preflight> {
  const bodyJson = validateBody(action, body); const value = await request(actionPath(action, resourceId) + ':preflight', { method: 'POST', csrf, bodyJson, signal }); shape(value, provenanceKeys + ' action resourceId resourceVersion version allowed fingerprint checks changes safeEffects', 'preview');
  if (value.action !== action || value.resourceId !== resourceId) throw unreadable(); version(value.resourceVersion); if (value.version !== value.resourceVersion) throw unreadable(); bool(value.allowed); const checks = list(value.checks, 100).map(check);
  if (value.allowed ? typeof value.fingerprint !== 'string' || !value.fingerprint || checks.some(item => item.status === 'blocked') : value.fingerprint !== null || !checks.some(item => item.status === 'blocked')) throw unreadable(); if (value.fingerprint !== null) text(value.fingerprint, 256);
  for (const item of list(value.changes, 100)) { const change = shape(item, 'code message target affectedRecordIds'); text(change.code, 128); text(change.message, 1000); if (change.target !== null) text(change.target, 240); unique(change.affectedRecordIds, value => { id(value); return value; }, value => value, 100, false); }
  if (value.allowed ? value.preview === undefined : value.preview !== undefined) throw unreadable(); const priced = value.preview === undefined ? undefined : preview(value.preview, action, bodyJson); effects(value.safeEffects, action, value.allowed, priced);
  const reviewed = freeze(value as unknown as Preflight); reviewedBodies.set(reviewed, bodyJson); return reviewed;
}
export function prepareAction<A extends Action>(review: Preflight, body: ReviewBodies[A]): PreparedAction<A> {
  const original = reviewedBodies.get(review); if (!review.allowed || !review.fingerprint || original === undefined || validateBody(review.action as A, body) !== original) throw new Error('Review these exact current owner-billing facts before applying the action.');
  const mutation = freeze({ ...JSON.parse(original), fingerprint: review.fingerprint }) as PreparedAction<A>['body']; const prepared: PreparedAction<A> = Object.freeze({ action: review.action as A, id: review.resourceId, version: review.resourceVersion, repeatabilityId: crypto.randomUUID(), body: mutation, bodyJson: JSON.stringify(mutation) }); preparedRequests.add(prepared); return prepared;
}
export async function applyPreparedAction(prepared: PreparedAction, csrf: string): Promise<Receipt> {
  if (!preparedRequests.has(prepared) || !Object.isFrozen(prepared) || prepared.bodyJson !== JSON.stringify(prepared.body)) throw new Error('Use the original immutable reviewed owner-billing request.');
  const value = await request(actionPath(prepared.action, prepared.id), { method: 'POST', csrf, bodyJson: prepared.bodyJson, version: prepared.version, repeatabilityId: prepared.repeatabilityId }); shape(value, provenanceKeys + ' receiptId replayed effectApplied result'); id(value.receiptId); bool(value.replayed); bool(value.effectApplied); if (value.effectApplied !== !value.replayed) throw unreadable();
  const extra: Record<Action, string> = { 'ownerBill.prepare': 'basisId amountDueCents reviewedCertifiedCents', 'ownerBill.requestApproval': 'approvalId', 'ownerBill.approve': 'approvalId billStatus businessApprovalRecordId', 'ownerBill.post': 'approvalId postingReceiptId journalId postingPeriodId amountDueCents', 'ownerBill.requestSend': 'approvalId', 'ownerBill.approveSend': 'approvalId', 'ownerBill.send': 'approvalId sendId syntheticMailSink externalDelivery' };
  const statuses: Record<Action, string> = { 'ownerBill.prepare': 'draft', 'ownerBill.requestApproval': 'pending', 'ownerBill.approve': 'granted', 'ownerBill.post': 'posted', 'ownerBill.requestSend': 'pending', 'ownerBill.approveSend': 'granted', 'ownerBill.send': 'sent' };
  const result = shape(value.result, 'action status billId journalCountDelta arBalanceDeltaCents retainedArDeltaCents providerCallsDelta ' + extra[prepared.action]); if (result.action !== prepared.action || result.status !== statuses[prepared.action]) throw unreadable();
  // Status is included separately to keep the exact original action outcome.
  for (const key of ['billId', 'basisId', 'approvalId', 'businessApprovalRecordId', 'postingReceiptId', 'journalId', 'postingPeriodId', 'sendId']) if (result[key] !== undefined) id(result[key]);
  cents(result.arBalanceDeltaCents); cents(result.retainedArDeltaCents, true); if (result.providerCallsDelta !== 0) throw unreadable();
  if (prepared.action === 'ownerBill.post') { cents(result.amountDueCents); if (result.journalCountDelta !== 1 || result.arBalanceDeltaCents !== result.amountDueCents) throw unreadable(); }
  else if (result.journalCountDelta !== 0 || result.arBalanceDeltaCents !== 0 || result.retainedArDeltaCents !== 0) throw unreadable();
  if (prepared.action === 'ownerBill.approve' && result.billStatus !== 'draft' || prepared.action === 'ownerBill.send' && (result.syntheticMailSink !== true || result.externalDelivery !== 'not_attempted')) throw unreadable();
  for (const key of ['amountDueCents', 'reviewedCertifiedCents']) if (result[key] !== undefined) cents(result[key]);
  const binding = prepared.action === 'ownerBill.prepare' ? result.basisId : ['ownerBill.approve', 'ownerBill.approveSend', 'ownerBill.send'].includes(prepared.action) ? result.approvalId : result.billId; if (binding !== prepared.id) throw unreadable();
  return freeze(value as unknown as Receipt);
}
function session(raw: unknown): Session {
  const value = provenance(raw, true); shape(value, provenanceKeys + ' authenticated sessionExpiresAt csrfToken person duties projectIds capabilities'); bool(value.authenticated); timestamp(value.sessionExpiresAt); text(value.csrfToken, 128);
  if (value.person !== null) { const identity = shape(value.person, 'id displayName personaId'); id(identity.id); text(identity.displayName, 240); member(identity.personaId, ['preparer', 'reviewer', 'poster', 'controller']); }
  if (value.authenticated !== (value.person !== null)) throw unreadable(); unique(value.duties, item => { member(item, ['pm', 'accountant', 'controller']); return item as string; }, item => item, 3, false); unique(value.projectIds, item => { id(item); return item; }, item => item, 500, false); if (!value.authenticated && (list(value.duties).length || list(value.projectIds).length)) throw unreadable();
  const capability = shape(value.capabilities, 'sessionIdentity scopedReads microsoftSignIn liveAdmission externalAccounting manualCertification ownerContractBasis externalSettlement syntheticDelivery commands');
  if (capability.sessionIdentity !== 'registered_synthetic_person' || capability.scopedReads !== true || capability.microsoftSignIn !== false || capability.liveAdmission !== false || capability.externalAccounting !== 'unavailable' || capability.manualCertification !== true || capability.ownerContractBasis !== 'declared_synthetic' || capability.externalSettlement !== false || capability.syntheticDelivery !== 'mail-sink') throw unreadable();
  if (availability(capability.commands).length !== actions.length) throw unreadable(); return value as unknown as Session;
}
export async function readSession(signal?: AbortSignal): Promise<Session> { return freeze(session(await request('/session', { signal, session: true }))); }
export async function readPersonas(signal?: AbortSignal): Promise<Persona[]> {
  const value = await request('/personas', { signal }); shape(value, provenanceKeys + ' value'); const options = unique(value.value, item => { const option = shape(item, 'personaId displayName synthetic'); member(option.personaId, ['preparer', 'reviewer', 'poster', 'controller']); text(option.displayName, 240); if (option.synthetic !== true) throw unreadable(); return option as unknown as Persona; }, item => item.personaId, 4); if (options.length !== 4) throw unreadable(); return freeze(options);
}
export async function bindSession(personaId: PersonaId, csrf: string) { member(personaId, ['preparer', 'reviewer', 'poster', 'controller']); abortScopedReads(); return freeze(session(await request('/session', { method: 'POST', csrf, bodyJson: JSON.stringify({ personaId }), session: true }))); }
export async function endSession(csrf: string) { abortScopedReads(); return freeze(session(await request('/session/logout', { method: 'POST', csrf, session: true }))); }
export async function readPreparation(basisId: string, signal?: AbortSignal): Promise<Preparation> {
  id(basisId); const value = await request(`/owner-bases/${encodeURIComponent(basisId)}/preparation`, { signal }); shape(value, provenanceKeys + ' version basis claimSources reviewSources periods previous availableActions'); version(value.version); const declared = basis(value.basis, basisId); if (declared.version !== value.version) throw unreadable();
  const claim = unique(value.claimSources, item => source(item, 'owner_claim'), item => item.revisionId, 100, false); const review = unique(value.reviewSources, item => source(item, 'owner_certification'), item => item.revisionId, 100, false); if ([...claim, ...review].some(item => !item.current)) throw unreadable(); if (claim.some(left => review.some(right => left.documentId === right.documentId))) throw unreadable();
  unique(value.periods, item => period(item), item => item.id, 100, false); const previous = shape(value.previous, 'billId certifiedCents retainedCents lines'); if (previous.billId !== null) id(previous.billId); cents(previous.certifiedCents); cents(previous.retainedCents);
  const lines = unique(previous.lines, item => { const line = shape(item, 'lineId reviewedQuantity reviewedAmountCents'); id(line.lineId); cents(line.reviewedAmountCents); const owner = declared.sov.find(item => item.lineId === line.lineId); if (!owner) throw unreadable(); if (owner.basis === 'unitPrice') decimal(line.reviewedQuantity); else if (line.reviewedQuantity !== null) throw unreadable(); return line; }, item => item.lineId as string); if (lines.length !== declared.sov.length) throw unreadable(); availability(value.availableActions); return freeze(value as unknown as Preparation);
}
export async function readBill(billId: string, signal?: AbortSignal) { id(billId); return freeze(bill(await request(`/owner-bills/${encodeURIComponent(billId)}`, { signal }), billId)); }
export async function readPacket(approvalId: string, signal?: AbortSignal, send = false): Promise<ApprovalPacket> {
  id(approvalId); const value = await request(`/${send ? 'owner-send-approvals' : 'owner-bill-approvals'}/${encodeURIComponent(approvalId)}/packet`, { signal }); shape(value, provenanceKeys + ' id version approval bill availableActions blockedReasons'); if (value.id !== approvalId) throw unreadable(); version(value.version); const authorization = approval(value.approval, approvalId); const original = bill(value.bill, authorization.billId); if (authorization.type !== (send ? 'send' : 'business') || authorization.version !== value.version || authorization.project.id !== original.project.id || authorization.sequence !== original.sequence) throw unreadable(); availability(value.availableActions); list(value.blockedReasons, 100).forEach(check); return freeze(value as unknown as ApprovalPacket);
}
export function readBusinessPacket(approvalId: string, signal?: AbortSignal) { return readPacket(approvalId, signal); }
export function readSendPacket(approvalId: string, signal?: AbortSignal) { return readPacket(approvalId, signal, true); }
export async function readSendPreparation(billId: string, signal?: AbortSignal): Promise<SendPreparation> {
  id(billId); const value = await request(`/owner-bills/${encodeURIComponent(billId)}/send-preparation`, { signal }); shape(value, provenanceKeys + ' id version bill delivery availableActions blockedReasons'); if (value.id !== billId) throw unreadable(); version(value.version); const original = bill(value.bill, billId); const delivery = shape(value.delivery, 'channel recipients amountDueCents balanceDueCents externalDelivery'); if (delivery.channel !== 'mail-sink' || delivery.externalDelivery !== false) throw unreadable(); recipients(delivery.recipients); cents(delivery.amountDueCents); cents(delivery.balanceDueCents); if (delivery.amountDueCents !== original.totals.amountDueCents || delivery.balanceDueCents !== original.totals.currentOpenCents) throw unreadable(); availability(value.availableActions); list(value.blockedReasons, 100).forEach(check); return freeze(value as unknown as SendPreparation);
}
async function collection<T>(name: string, validate: (raw: unknown) => T, identity: (row: T) => string, signal?: AbortSignal, filters: Filters = {}, aging = false): Promise<Collection<T>> {
  shape(filters, '', name === 'projects' ? 'search' : aging ? 'projectId search asOf' : 'projectId search status'); if (filters.projectId !== undefined) id(filters.projectId); if (filters.search !== undefined) text(filters.search, 200, true); if (filters.status !== undefined) text(filters.status, 40); if (filters.asOf !== undefined) calendar(filters.asOf);
  const rows: T[] = []; const cursors = new Set(); const identifiers = new Set(); let cursor: string | null = null; let first: Obj | null = null;
  do { const query = new URLSearchParams({ top: '50', ...filters }); if (cursor) query.set('cursor', cursor); const value = await request(`/${name}?${query}`, { signal }); shape(value, provenanceKeys + ' items count nextCursor facets totals' + (aging ? ' agingAsOf balanceBasis historicalSnapshot workingLedger watermark scope reconciliation' : '')); integer(value.count, 0, 5000); if (first && value.count !== first.count) throw unreadable();
    if (value.nextCursor !== null) text(value.nextCursor, 2048); const facets = shape(value.facets, 'statuses'); unique(facets.statuses, raw => { const facet = shape(raw, 'value count'); text(facet.value, 40); integer(facet.count); return facet; }, row => row.value as string, 30, false); const totals = object(value.totals); for (const [key, amount] of Object.entries(totals)) { if (!key.endsWith('Cents')) throw unreadable(); cents(amount, key === 'retainageThisPeriodCents'); }
    if (aging) { calendar(value.agingAsOf); if (filters.asOf && value.agingAsOf !== filters.asOf || value.balanceBasis !== 'current_standing_balance' || value.historicalSnapshot !== false || value.workingLedger !== true || value.watermark !== 'Working ledger, not for issue' || value.scope !== 'owner_billing') throw unreadable(); const reconciliation = shape(value.reconciliation, 'subledgerCents controlCents reconciled scope'); cents(reconciliation.subledgerCents); cents(reconciliation.controlCents); bool(reconciliation.reconciled); if (reconciliation.scope !== 'authorized_projects' || reconciliation.reconciled !== (reconciliation.subledgerCents === reconciliation.controlCents)) throw unreadable(); }
    if (first && ['facets', 'totals', ...(aging ? ['agingAsOf', 'reconciliation'] : [])].some(key => JSON.stringify(first![key]) !== JSON.stringify(value[key]))) throw unreadable(); if (!first) first = value;
    for (const raw of list(value.items, 50)) { const row = validate(raw); const key = identity(row); id(key); if (identifiers.has(key)) throw unreadable(); identifiers.add(key); rows.push(freeze(row)); }
    cursor = value.nextCursor as string | null; if (cursor && (cursors.has(cursor) || cursors.size >= 100)) throw unreadable(); if (cursor) cursors.add(cursor);
  } while (cursor);
  if (!first || rows.length !== first.count) throw unreadable(); return freeze({ ...first, items: rows, nextCursor: null } as unknown as Collection<T>);
}
export function readProjects(signal?: AbortSignal) { return collection('projects', raw => { const value = provenance(raw); shape(value, provenanceKeys + ' id name'); project({ id: value.id, name: value.name }); return value as unknown as Project; }, row => row.id, signal); }
export function readBases(signal?: AbortSignal, filters?: Filters) { return collection('owner-bases', raw => basis(raw), row => row.id, signal, filters); }
export function readBills(signal?: AbortSignal, filters?: Filters) { return collection('owner-bills', raw => bill(raw), row => row.id, signal, filters); }
export function readApprovals(signal?: AbortSignal, filters?: Filters, send = false) { return collection(send ? 'owner-send-approvals' : 'owner-bill-approvals', raw => approval(raw), row => row.id, signal, filters); }
export async function readAging(signal?: AbortSignal, filters?: Filters): Promise<Aging> {
  return await collection('ar-aging', raw => { const value = shape(raw, 'billId project customer sequence invoiceDate dueDate daysPastDue currentOpenCents agingBucket'); id(value.billId); project(value.project); project(value.customer); integer(value.sequence, 1); calendar(value.invoiceDate); if (value.dueDate !== null) calendar(value.dueDate); if (value.daysPastDue !== null) integer(value.daysPastDue); cents(value.currentOpenCents); member(value.agingBucket, ['current', '1_30', '31_60', '61_90', 'over_90', 'undated']); return value; }, row => row.billId as string, signal, filters, true) as unknown as Aging;
}
export async function readRetainageAging(signal?: AbortSignal, filters?: Filters): Promise<import('./types').RetainageAging> {
  return await collection('retainage-aging', raw => { const value = shape(raw, 'project customer throughSequence retainedCents releasedCents currentOpenCents billIds agingBucket dueDate daysPastDue'); project(value.project); project(value.customer); if (value.throughSequence !== null) integer(value.throughSequence, 1); cents(value.retainedCents); cents(value.releasedCents); cents(value.currentOpenCents); unique(value.billIds, value => { id(value); return value; }, value => value, 500, false); if (value.agingBucket !== 'unreleased' || value.dueDate !== null || value.daysPastDue !== null) throw unreadable(); return value; }, row => (row.project as Project).id, signal, filters, true) as unknown as import('./types').RetainageAging;
}
