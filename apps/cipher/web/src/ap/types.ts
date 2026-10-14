export interface Provenance {
  contractVersion: 'cipher.ap-practice.v1'; mode: 'practice'; synthetic: true; currency: 'USD';
}
export type APAction = 'bill.requestApproval' | 'bill.approve' | 'bill.post' | 'bill.prepare'
  | 'invoice.receive' | 'invoice.computeMatch' | 'invoice.requestMatchApproval'
  | 'invoice.approveMatch' | 'invoice.executeMatch' | 'invoice.revise' | 'invoice.reject'
  | 'invoice.reviewDuplicate' | 'bill.cancel' | 'bill.prepareCorrection' | 'bill.requestCorrection'
  | 'bill.approveCorrection' | 'bill.executeCorrection' | AccountingAction;
export type AccountingAction = 'accounting.prepare' | 'accounting.request' | 'accounting.approve' | 'accounting.queue'
  | 'accounting.deliver' | 'accounting.lookup' | 'accounting.reconcile';
export type Duty = 'pm' | 'accountant';
export interface Person { id: string; displayName: string }
export interface Capabilities {
  sessionIdentity: 'registered_synthetic_person'; scopedReads: true; microsoftSignIn: false;
  liveAdmission: false; externalAccounting: 'unavailable'; commands: APAction[];
}
export interface Session extends Provenance {
  authenticated: boolean; sessionExpiresAt: string | null; csrfToken: string;
  person: (Person & { personaId: string }) | null; duties: Duty[]; projectIds: string[]; capabilities: Capabilities;
}
export interface Persona { personaId: string; displayName: string; synthetic: true }
export interface Problem { code: string; target: string | null; message: string; fix?: string | null }
export interface Check extends Problem { status: string }
export interface Period { id: string; name: string; startDate: string; endDate: string; status: string }
export interface Project { id: string; name: string; entity: string; currency: 'USD'; budgetCents: number; customerName?: string | null }
export interface Commitment {
  id: string; projectId: string; supplierId: string; title: string; status: string;
  supplierName: string; projectName: string; originalAmountCents: number; executedAmountCents: number;
  retainageRateMicros: number; version: number | string;
}
export interface BillLine {
  id: string; sovLineId: string; description: string; costCode: string;
  cumulativeInstalledCents: number; priorInstalledCents: number; thisPeriodInstalledCents: number;
}
export interface BusinessApproval {
  id: string | null; approvalId: string; status: string; effectiveStatus: string; requestedBy: Person;
  approvedBy: Person | null; requestedAt: string; approvedAt: string | null; expiresAt: string;
}
export interface Posting {
  receiptId: string; journalIds: string[]; period: Period; postedBy: Person; postedAt: string; reason: string;
}
export interface Bill {
  id: string; version: string; projectId: string; commitmentId: string; supplierId: string;
  projectName: string; commitmentTitle: string; supplierName: string; sequence: number; displayNumber: null;
  status: string; effectiveStatus: string; certificationPeriod: Period; postingPeriods: Period[];
  amountDueCents: number; currentDueCents: number; retainageCents: number; thisPeriodCents: number;
  lines: BillLine[]; businessApproval: BusinessApproval | null; posting: Posting | null;
  availableActions: APAction[]; blockedReasons: Problem[];
}
export interface Approval {
  id: string; version: string; billId: string; projectId: string; projectName: string; subjectLabel: string;
  status: string; effectiveStatus: string; requestedBy: Person; approvedBy: Person | null;
  requestedAt: string; approvedAt: string | null; expiresAt: string; amountDueCents: number;
}
export interface PostingQueueRow {
  billId: string; version: string; projectId: string; supplierName: string; commitmentTitle: string;
  sequence: number; amountDueCents: number; certificationPeriod: Period; businessApprovalId: string;
  approvedBy: Person; approvedAt: string; expiresAt: string; ready: boolean; blockedReasons: Problem[];
}
export type SafeValue = string | number | boolean | null | SafeValue[] | { [key: string]: SafeValue };
export interface Change { field: string; before: SafeValue; after: SafeValue }
export interface Packet extends Provenance {
  approvalId: string; billId: string; version: string; status: string; requestedBy: Person;
  approvedBy: Person | null; requestedAt: string; expiresAt: string; boundFacts: Record<string, SafeValue>;
  currentFacts: Record<string, SafeValue>; changes: Change[]; checks: Check[]; amountDueCents: number;
  retainedCents: number; sourceSummary: Record<string, SafeValue>; bill: Bill;
  effect: { billStatus: 'approved'; workingLedgerJournalDelta: 0; apPayableDeltaCents: 0 };
}
export interface Preflight extends Provenance {
  action: APAction; resourceId: string; resourceVersion: string; allowed: boolean;
  checks: Check[]; changes: Change[]; safeEffects: Record<string, SafeValue>; fingerprint: string | null;
}
export interface ActionOutcome extends Provenance {
  receiptId: string; replayed: boolean; effectApplied: boolean; result: Record<string, SafeValue>;
}
export interface WorkerPendingOutcome extends Provenance {
  invocationId: string; state: string; retrySameRequest: true; replayed: boolean; effectApplied: false;
}
export interface Preparation extends Provenance {
  id: string; version: string; projectId: string; projectName: string; commitmentTitle: string;
  supplierId: string; supplierName: string; status: string; retainageRateMicros: number;
  lines: { sovLineId: string; lineNo: number; description: string; costCode: string; scheduledCents: number; priorInstalledCents: number }[];
  periods: Period[]; priorBill: { id: string; sequence: number; status: string } | null;
  availableActions: APAction[]; blockedReasons: Problem[];
}
export interface InvoiceEvidence {
  id: string; documentId: string; revisionId: string; projectId: string; title: string;
  revision: number; isCurrent: boolean; available: boolean; status: string;
}
export interface Invoice extends Provenance {
  id: string; version: string; projectId: string; projectName: string; commitmentId: string | null;
  commitmentTitle: string | null; supplierId: string; supplierName: string; invoiceNumber: string;
  invoiceDate: string; dueDate: string; amountCents: number; status: string; invoiceVersion: number;
  evidence: { documentId: string; revisionId: string; title: string; revision: number; isCurrent: boolean };
  possibleDuplicate: boolean; duplicateBlocking: boolean;
  match: { status: string; basis: string; exceptions: { code: string; message: string }[]; billId: string | null; attemptId: string } | null;
  matchApprovalId: string | null; availableActions: APAction[]; blockedReasons: Problem[];
}
export interface MatchApproval {
  id: string; approvalId: string; version: string; projectId: string; projectName: string;
  invoiceId: string; invoiceNumber: string; supplierName: string; status: string; effectiveStatus: string;
  requestedBy: Person; approvedBy: Person | null; requestedAt: string; approvedAt: string | null;
  expiresAt: string; amountCents: number;
}
export interface MatchPacket extends Provenance, MatchApproval {
  invoice: Invoice; boundFacts: Record<string, SafeValue>; currentFacts: Record<string, SafeValue>;
  changes: Change[]; effect: { invoiceStatus: 'matched'; billLinked: boolean; workingLedgerJournalDelta: 0; apPayableDeltaCents: 0 };
  availableActions: APAction[]; blockedReasons: Problem[];
}
export interface InvoiceException extends Provenance {
  version: string; invoice: Invoice; availableActions: APAction[]; blockedReasons: Problem[];
}
export interface BillException extends Provenance {
  version: string; bill: Bill; correction: { id: string; status: string; reason: string; requestedBy: Person; requestedAt: string } | null;
  correctionPeriods: Period[]; availableActions: APAction[]; blockedReasons: Problem[];
}
export interface CorrectionApproval {
  id: string; approvalId: string; version: string; projectId: string; projectName: string; billId: string;
  sequence: number; supplierName: string; status: string; effectiveStatus: string; requestedBy: Person;
  approvedBy: Person | null; requestedAt: string; approvedAt: string | null; expiresAt: string;
  amountDueCents: number; correctionId: string; reason: string;
}
export interface CorrectionPacket extends Provenance, CorrectionApproval {
  bill: Bill; boundFacts: Record<string, SafeValue>; currentFacts: Record<string, SafeValue>; changes: Change[];
  effect: Record<string, SafeValue>; availableActions: APAction[]; blockedReasons: Problem[]; correctionPeriods: Period[];
}
export interface AccountingSource {
  billId: string; sequence: number; projectId: string; projectName: string; supplierId: string;
  supplierName: string; commitmentId: string; commitmentTitle: string; currentBillStatus: string;
  postingReceiptId: string; originalJournalId: string;
}
export interface AccountingCapability {
  source: 'original_installed_work_posting_receipt'; route: 'practice.simulated-journal-entry.v1';
  simulation: true; externalAccounting: 'unavailable'; quickBooksAccepted: false;
  datePolicy: 'synthetic.period-end.v1'; liveDatePolicy: 'unqualified'; transactionKind: 'aggregate_practice_journal';
  dimensions: ['project', 'supplier']; costTypeQualification: 'unavailable'; taxQualification: 'unavailable'; payment: 'not_started';
}
export interface AccountingPlan {
  id: string; status: 'prepared'; version?: string; projectId: string; billId: string; source: AccountingSource;
  original: { originalCostCents: number; originalApCents: number; originalRetainageCents: number;
    sourcePeriod: Period; sourcePostedBy: Person; sourcePostedAt: string };
  date: { policy: 'synthetic.period-end.v1'; transactionDate: string; sourcePeriodId: string;
    sourcePeriodEndDate: string; qualification: 'synthetic_only' };
  preview: { lines: { id: string; sourceAccountCode: '5000' | '2000' | '2050'; sourceAccountName: string;
    practiceAccountName: string; debitCents: number; creditCents: number; projectName: string; supplierName: string; memo: string }[];
    debitTotalCents: number; creditTotalCents: number };
  capability: AccountingCapability; mapping: { id: string; version: number; hash: string };
  logicalOperationId: string; payloadHash: string; route: 'practice.simulated-journal-entry.v1';
  datePolicy: 'synthetic.period-end.v1'; transactionDate: string; currency: 'USD';
  grossCostCents: number; netApCents: number; retainageCents: number; preparedBy: Person; preparedAt: string;
}
export interface AccountingApproval {
  id: string; planId: string; version?: string; status: string; effectiveStatus: string;
  requestedBy: Person; requestedAt: string; approvedBy: Person | null; approvedAt: string | null; expiresAt: string;
}
export interface AccountingIntent {
  id: string; planId: string; approvalId: string; version?: string;
  status: 'queued' | 'submitting' | 'outcome_unknown' | 'simulated_accepted' | 'reconciled' | 'refused';
  revision: number; logicalOperationId: string; payloadHash: string; queuedBy: Person; queuedAt: string;
  updatedBy: Person; updatedAt: string; lookupRequired: boolean; hasAcceptance: boolean;
  simulation: true; externalAccounting: 'unavailable'; liveAccounting: 'unavailable';
}
export interface AccountingPreparation extends Provenance {
  version: string; bill: Bill; mapping: { id: string; version: number; hash: string; route: string; datePolicy: string } | null;
  availableActions: APAction[]; blockedReasons: Problem[]; simulation: true; externalAccounting: 'unavailable'; liveAccounting: 'unavailable';
}
export interface AccountingPlanReview extends Provenance {
  version: string; plan: AccountingPlan; availableActions: APAction[]; blockedReasons: Problem[];
}
export interface AccountingPacket extends AccountingPlanReview { approval: AccountingApproval }
export interface AccountingIntentReview extends AccountingPlanReview {
  intent: AccountingIntent; deliveryAdmission: 'disposable-memory-practice-only';
}
export interface Records {
  projects: Project; commitments: Commitment; bills: Bill; approvals: Approval; 'posting-queue': PostingQueueRow;
  invoices: Invoice; 'invoice-evidence': InvoiceEvidence; 'match-approvals': MatchApproval; 'correction-approvals': CorrectionApproval;
  'accounting-plans': AccountingPlan; 'accounting-approvals': AccountingApproval; 'accounting-intents': AccountingIntent;
}
export type Collection = keyof Records;
export interface Envelope<T> extends Provenance {
  collection: Collection; projectId: string | null; value: T[]; count: number; nextCursor: string | null;
  facets: { statuses?: { value: string; count: number }[]; [key: string]: unknown }; totals: Record<string, number>;
}
export interface Workspace {
  projects: Project[]; commitments: Commitment[]; bills: Bill[]; approvals: Approval[];
  postingQueue: PostingQueueRow[]; invoices: Invoice[]; invoiceEvidence: InvoiceEvidence[]; matchApprovals: MatchApproval[]; loadedAt: Date;
}
