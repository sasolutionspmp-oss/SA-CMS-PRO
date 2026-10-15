/** Exact DTOs for the fixed isolated synthetic owner-billing API. */
export type Provenance = { contractVersion: 'cipher.ar-practice.v1'; mode: 'practice'; synthetic: true; currency: 'USD' };
export type Person = { id: string; displayName: string };
export type Project = { id: string; name: string };
export type BillStatus = 'draft' | 'posted' | 'sent' | 'collected' | 'void' | 'reversed';
export type BillState = 'draft' | 'under_review' | 'approved_not_posted' | 'posted_awaiting_send' | 'sent_open' | 'settled' | 'void' | 'reversed' | 'stale';
export type ApprovalStatus = 'pending' | 'granted' | 'consumed' | 'expired' | 'invalidated';
export type Period = { id: string; name: string; startDate: string; endDate: string; status: 'open' | 'closed' };
export type Source = { documentId: string; revisionId: string; title: string; kind: string; revision: number; current: boolean };
export type Action = 'ownerBill.prepare' | 'ownerBill.requestApproval' | 'ownerBill.approve' | 'ownerBill.post' |
  'ownerBill.requestSend' | 'ownerBill.approveSend' | 'ownerBill.send';
export type Check = { code: string; status: string; target: string | null; message: string; fix: string | null };
export type Related = { type: string; id: string; title: string; apiRoute: string };
export type OwnerSOVLine = { lineId: string; description: string; basis: 'unitPrice' | 'lumpSum'; scheduledAmountCents: number;
  unit: string | null; contractQuantity: string | null; unitPriceCents: number | null };
export type OwnerLine = OwnerSOVLine & { previousQuantity: string | null; claimedQuantity: string | null;
  reviewedQuantity: string | null; previousAmountCents: number; claimedAmountCents: number; reviewedAmountCents: number;
  thisPeriodCents: number; differenceAmountCents: number; differenceReason: string;
  claimSourceLocator: string; reviewSourceLocator: string };
export type Basis = Provenance & { id: string; version: string; project: Project; customer: Project;
  contractValueCents: number; retainageRate: string; termsDays: number; agreementSource: Source; sov: OwnerSOVLine[];
  sourceStatus: 'current' | 'stale'; declaration: string; availableActions: Action[] };
export type Preparation = Provenance & { version: string; basis: Basis; claimSources: Source[]; reviewSources: Source[];
  periods: Period[]; previous: { billId: string | null; certifiedCents: number; retainedCents: number;
    lines: { lineId: string; reviewedQuantity: string | null; reviewedAmountCents: number }[] }; availableActions: Action[] };
export type Approval = Provenance & { id: string; version: string; type: 'business' | 'send'; billId: string;
  project: Project; sequence: number; status: ApprovalStatus; effectiveStatus: ApprovalStatus | 'stale'; requestedBy: Person; approvedBy: Person | null;
  requestedAt: string; approvedAt: string | null; expiresAt: string; availableActions: Action[]; blockedReasons: Check[] };
export type JournalLine = { accountCode: string; debitCents: number; creditCents: number; memo: string };
export type BusinessGrant = { id: string; approvalId: string; status: 'granted'; authorizationStatus: string;
  requestedBy: Person; reviewedBy: Person; reviewedAt: string };
export type Posting = { receiptId: string; journalId: string; period: Period; postedBy: Person; postedAt: string;
  journalPreview: JournalLine[] };
export type SyntheticSend = { id: string; status: 'sent_to_synthetic_sink'; channel: 'mail-sink'; sentAt: string;
  sentBy: Person; recipients: string[]; externalDelivery: false };
export type OwnerBill = Provenance & { id: string; version: string; project: Project; customer: Project; sequence: number;
  status: BillStatus; effectiveStatus: BillState; certificationPeriod: Period; invoiceDate: string; dueDate: string | null;
  termsDays: number | null; basis: { id: string; agreementSource: Source }; claimSource: Source; reviewSource: Source;
  lines: OwnerLine[]; totals: { priorCertifiedCents: number; claimedCertifiedCents: number; reviewedCertifiedCents: number;
    revenueThisPeriodCents: number; retainageThisPeriodCents: number; retainedCumulativeCents: number; amountDueCents: number;
    currentOpenCents: number; currentReceivedCents: number; currentCreditedCents: number; currentWrittenOffCents: number;
    currentDepositsAppliedCents: number }; businessApproval: BusinessGrant | null; posting: Posting | null;
  send: SyntheticSend | null; availableActions: Action[]; blockedReasons: Check[]; relatedRecords: Related[];
  officialBooks: 'unavailable'; externalSettlement: false };
export type ApprovalPacket = Provenance & { id: string; version: string; approval: Approval; bill: OwnerBill;
  availableActions: Action[]; blockedReasons: Check[] };
export type SendPreparation = Provenance & { id: string; version: string; bill: OwnerBill;
  delivery: { channel: 'mail-sink'; recipients: string[]; amountDueCents: number; balanceDueCents: number;
    externalDelivery: false }; availableActions: Action[]; blockedReasons: Check[] };
export type Collection<T> = Provenance & { items: T[]; count: number; nextCursor: string | null;
  facets: { statuses: { value: string; count: number }[] }; totals: Record<string, number> };
export type AgingItem = { billId: string; project: Project; customer: Project; sequence: number; invoiceDate: string;
  dueDate: string | null; daysPastDue: number | null; currentOpenCents: number; agingBucket: string };
export type Aging = Collection<AgingItem> & { agingAsOf: string; balanceBasis: 'current_standing_balance';
  historicalSnapshot: false; workingLedger: true; watermark: 'Working ledger, not for issue';
  scope: 'owner_billing'; reconciliation: { subledgerCents: number; controlCents: number; reconciled: boolean; scope: 'authorized_projects' } };

export type Cents = number;
export type DecimalText = string;
export interface PrepareLine { lineId: string; claimedCumulative: DecimalText; reviewedCumulative: DecimalText; differenceReason: string; claimSourceLocator: string; reviewSourceLocator: string }
export interface PrepareInput { claimRevisionId: string; reviewRevisionId: string; periodId: string; lines: PrepareLine[] }
export type ReviewBodies = { [A in Action]: A extends 'ownerBill.prepare' ? PrepareInput : Record<string, never> };
export type MutationBody<A extends Action> = ReviewBodies[A] & { fingerprint: string };
export interface Change { code: string; message: string; target: string | null; affectedRecordIds: string[] }
export interface Calculation { calculationVersion: 'cipher.owner-billing-calculation.v1'; lines: Omit<OwnerLine, 'claimSourceLocator' | 'reviewSourceLocator'>[];
  primeContractValueCents: Cents; priorCertifiedCents: Cents; claimedCertifiedCents: Cents; reviewedCertifiedCents: Cents;
  priorRetainedCents: Cents; retainageReleasedCents: Cents; retainageRate: DecimalText; retainedCumulativeCents: Cents;
  retainageThisPeriodCents: Cents; revenueThisPeriodCents: Cents; amountDueCents: Cents; journalPreview: JournalLine[] }
export interface SafeEffects { createsDraft: boolean; createsApproval: boolean; grantsApproval: boolean; approvalStatus: ApprovalStatus | null;
  billStatus: BillStatus | null; workingLedgerJournalDelta: 0 | 1; arReceivableDeltaCents: Cents; retainedARDeltaCents: Cents; revenueDeltaCents: Cents;
  journalPreview: JournalLine[]; syntheticSendDelta: 0 | 1; mailSinkOnly: true; externalAccounting: 'unavailable'; quickBooksAccepted: false;
  externalDelivery: false; externalSettlement: false }
export interface Preview { calculation: Calculation; period: Omit<Period,'status'>; invoiceDate: string; dueDate: string | null; datePolicy: string;
  delivery: null | { channel: 'mail-sink'; recipients: string[]; amountDueCents: Cents; balanceDueCents: Cents } }
export interface Preflight extends Provenance { action: Action; resourceId: string; resourceVersion: string; version: string; allowed: boolean;
  fingerprint: string | null; checks: Check[]; changes: Change[]; safeEffects: SafeEffects; preview?: Preview }
export type PersonaId = 'preparer' | 'reviewer' | 'poster' | 'controller';
export interface Persona { personaId: PersonaId; displayName: string; synthetic: true }
export type Duty = 'pm' | 'accountant' | 'controller';
export interface Session extends Provenance { authenticated: boolean; sessionExpiresAt: string; csrfToken: string;
  person: (Person & { personaId: PersonaId }) | null; duties: Duty[]; projectIds: string[];
  capabilities: { sessionIdentity: 'registered_synthetic_person'; scopedReads: true; microsoftSignIn: false; liveAdmission: false;
    externalAccounting: 'unavailable'; manualCertification: true; ownerContractBasis: 'declared_synthetic'; externalSettlement: false;
    syntheticDelivery: 'mail-sink'; commands: Action[] } }
export type DeepReadonly<T> = T extends readonly unknown[] ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T extends object ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T;
export interface PreparedAction<A extends Action = Action> { readonly action: A; readonly id: string; readonly version: string; readonly repeatabilityId: string;
  readonly body: DeepReadonly<MutationBody<A>>; readonly bodyJson: string }
interface Effects { journalCountDelta: 0 | 1; arBalanceDeltaCents: Cents; retainedArDeltaCents: Cents; providerCallsDelta: 0 }
export type ReceiptResult = Effects & { billId: string } & (
  { action: 'ownerBill.prepare'; status: 'draft'; basisId: string; amountDueCents: Cents; reviewedCertifiedCents: Cents } |
  { action: 'ownerBill.requestApproval' | 'ownerBill.requestSend'; status: 'pending'; approvalId: string } |
  { action: 'ownerBill.approve'; status: 'granted'; approvalId: string; billStatus: 'draft'; businessApprovalRecordId: string } |
  { action: 'ownerBill.approveSend'; status: 'granted'; approvalId: string } |
  { action: 'ownerBill.post'; status: 'posted'; approvalId: string; postingReceiptId: string; journalId: string; postingPeriodId: string; amountDueCents: Cents } |
  { action: 'ownerBill.send'; status: 'sent'; approvalId: string; sendId: string; syntheticMailSink: true; externalDelivery: 'not_attempted' }
);
export interface Receipt extends Provenance { receiptId: string; replayed: boolean; effectApplied: boolean; result: ReceiptResult }
export interface Filters { projectId?: string; status?: string; search?: string; asOf?: string }
export interface RetainageAgingItem { project: Project; customer: Project; throughSequence: number | null; retainedCents: Cents; releasedCents: Cents; currentOpenCents: Cents; billIds: string[]; agingBucket: 'unreleased'; dueDate: null; daysPastDue: null }
export type RetainageAging = Omit<Aging,'items'> & { items: RetainageAgingItem[] };
