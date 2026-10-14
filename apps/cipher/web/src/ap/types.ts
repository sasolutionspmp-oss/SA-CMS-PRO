export interface Provenance {
  contractVersion: 'cipher.ap-practice.v1'; mode: 'practice'; synthetic: true; currency: 'USD';
}
export type APAction = 'bill.requestApproval' | 'bill.approve' | 'bill.post' | 'bill.prepare'
  | 'invoice.receive' | 'invoice.computeMatch' | 'invoice.requestMatchApproval'
  | 'invoice.approveMatch' | 'invoice.executeMatch' | 'invoice.revise' | 'invoice.reject'
  | 'invoice.reviewDuplicate' | 'bill.cancel' | 'bill.prepareCorrection' | 'bill.requestCorrection'
  | 'bill.approveCorrection' | 'bill.executeCorrection';
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
export interface Records {
  projects: Project; commitments: Commitment; bills: Bill; approvals: Approval; 'posting-queue': PostingQueueRow;
  invoices: Invoice; 'invoice-evidence': InvoiceEvidence; 'match-approvals': MatchApproval; 'correction-approvals': CorrectionApproval;
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
