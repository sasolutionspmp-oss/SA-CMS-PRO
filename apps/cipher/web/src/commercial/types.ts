/* Fixed synthetic commercial API. Quantities stay exact source strings. */
export type DecimalText = string; // Exact plain decimal, checked by the server.
export type Cents = number; // Bounded safe integer; no browser pricing arithmetic.
export type ResourceVersion = string; // Opaque quoted ETag in mutation headers.

export interface Provenance {
  contractVersion: 'cipher.commercial-practice.v1';
  mode: 'practice';
  synthetic: true;
  currency: 'USD';
}
export interface Person { id: string; displayName: string }
export interface Project { id: string; name: string }
export interface DrawingSource {
  documentId: string;
  documentRevisionId: string;
  title: string;
  revision: number;
  current: boolean;
  // Synthetic metadata and immutable revision hash, not uploaded drawing bytes.
}
export interface EntryLine {
  description: string;
  quantity: DecimalText;
  unit: string;
  unitPriceCents: Cents;
  sourceLocator: string;
  costCode: string;
}
export interface RevisedLine extends EntryLine { previousLineId: string | null }
export interface EstimateInput {
  documentRevisionId: string;
  lines: EntryLine[];
  priceBookRef: string | null;
  inclusions: string[];
  exclusions: string[];
  contingencyRate: DecimalText;
  measurementBasis: string;
}
export interface RevisionInput extends Omit<EstimateInput, 'lines'> {
  lines: RevisedLine[];
  removedExclusions: string[];
}
export type Action =
  | 'estimate.create' | 'estimate.revise' | 'estimate.request'
  | 'estimate.accept' | 'estimate.apply'
  | 'estimate.prepareHandoff' | 'estimate.createCommitment';
export interface ReviewBodies {
  'estimate.create': EstimateInput;
  'estimate.revise': RevisionInput;
  'estimate.request': Record<string, never>;
  'estimate.accept': Record<string, never>;
  'estimate.apply': Record<string, never>;
  'estimate.prepareHandoff': Record<string, never>;
  'estimate.createCommitment': Record<string, never>;
}
export type MutationBody<A extends Action> = A extends 'estimate.create' | 'estimate.revise'
  ? ReviewBodies[A] & { fingerprint: string }
  : { fingerprint: string };
export interface ActionAvailability {
  action: Action;
  allowed: boolean;
  reason: string | null;
  target: string | null;
}
export interface ReadLine extends EntryLine {
  id: string;
  lineNo: number;
  amountCents: Cents;
  stableLineId: string;
  previousLineId: string | null;
  measurementMethod: 'manual_entry';
  verifiedGeometry: false;
}
export interface EstimateRow {
  id: string;
  version: ResourceVersion;
  project: Project;
  revision: number;
  status: 'draft' | 'approved' | 'superseded'; // Preserve engine stored codes.
  effectiveStatus: 'draft' | 'under_review' | 'accepted' | 'superseded' | 'stale';
  source: DrawingSource;
  subtotalCents: Cents;
  contingencyCents: Cents;
  totalCents: Cents;
}
export interface Acceptance {
  approvalId: string;
  requestedBy: Person;
  acceptedBy: Person | null;
  appliedBy: Person | null;
  requestedAt: string;
  acceptedAt: string | null;
  appliedAt: string | null;
  expiresAt: string;
  status: 'pending' | 'granted' | 'consumed' | 'expired' | 'invalidated';
  effectiveStatus: string;
}
export interface EstimateRecord extends Provenance, EstimateRow {
  lines: ReadLine[];
  priceBookRef: string | null;
  inclusions: string[];
  exclusions: string[];
  contingencyRate: DecimalText;
  measurementBasis: string;
  predecessor: { id: string; revision: number } | null;
  successor: { id: string; revision: number } | null;
  acceptance: Acceptance | null;
  availableActions: ActionAvailability[];
  markers: { code: string; message: string }[];
}
export interface LineDifference {
  stableLineId: string;
  kind: 'added' | 'removed' | 'changed' | 'unchanged';
  before: ReadLine | null;
  after: ReadLine | null;
  changedFields: ('description' | 'quantity' | 'unit' | 'unitPriceCents' | 'amountCents' | 'sourceLocator' | 'costCode')[];
}
export interface Comparison extends Provenance {
  version: ResourceVersion;
  estimateId: string;
  predecessorId: string | null;
  lines: LineDifference[];
  totals: { beforeCents?: Cents; afterCents: Cents; deltaCents?: Cents };
  scope: { addedInclusions: string[]; removedInclusions: string[]; addedExclusions: string[]; removedExclusions: string[] };
  sourceChanged: boolean;
  priceBookChanged: boolean;
}
export interface HandoffLine {
  estimateLineId: string;
  stableLineId: string;
  description: string;
  quantity: DecimalText;
  unit: string;
  unitPriceCents: Cents;
  amountCents: Cents;
  costCode: string;
  sourceLocator: string;
  measurementBasis: string;
  measurementMethod: 'manual_entry';
  verifiedGeometry: false;
  sovLineId: string | null;
}
export interface Handoff extends Provenance {
  id: string;
  version: ResourceVersion;
  project: Project;
  estimateId: string;
  estimateRevision: number;
  acceptanceApprovalId: string;
  source: DrawingSource;
  status: 'prepared' | 'draft_created';
  effectiveStatus: 'prepared' | 'draft_created' | 'stale';
  supplier: { id: string; name: string };
  commitmentTitle: string;
  retainageRate: DecimalText;
  subtotalCents: Cents;
  contingencyCents: 0;
  totalCents: Cents;
  lines: HandoffLine[];
  commitmentId: string | null;
  availableActions: ActionAvailability[];
  consequence: string; // Creates a draft. Supplier contract execution is separate.
}
export interface DraftCommitment extends Provenance {
  id: string;
  version: ResourceVersion;
  project: Project;
  title: string;
  status: 'draft' | 'executed' | 'closed';
  creationStatus: 'draft';
  effectiveSourceStatus: 'current' | 'stale';
  supplier: { id: string; name: string };
  retainageRate: DecimalText;
  originalAmountCents: Cents;
  handoffId: string;
  estimate: { id: string; revision: number; acceptanceApprovalId: string };
  source: DrawingSource;
  lines: (HandoffLine & { sovLineId: string; sovLineNo: number })[];
  executionAvailableHere: false;
  availableActions: [];
  consequence: string;
  relatedRecords: {
    type: 'estimate' | 'handoff';
    id: string;
    title: string;
    // All paths resolve against this commercial API. Never AP's fresh fixture.
    apiRoute: string;
  }[];
}
export interface Collection<T> extends Provenance {
  items: T[];
  count: number;
  nextCursor: string | null;
  facets: { statuses: { value: string; count: number }[] };
  totals: { subtotalCents?: Cents; contingencyCents?: Cents; totalCents?: Cents };
}
export type Duty = 'estimator' | 'pm';
export type PersonaId = 'preparer' | 'reviewer' | 'pm';
export interface Persona { personaId: PersonaId; displayName: string; synthetic: true }
export interface Capabilities {
  sessionIdentity: 'registered_synthetic_person'; scopedReads: true; microsoftSignIn: false;
  liveAdmission: false; externalAccounting: 'unavailable'; manualQuantities: true;
  verifiedGeometry: false; customerProposals: false; commitmentExecution: false; commands: Action[];
}
export interface Session extends Provenance {
  authenticated: boolean; sessionExpiresAt: string; csrfToken: string;
  person: (Person & { personaId: PersonaId }) | null; duties: Duty[]; projectIds: string[]; capabilities: Capabilities;
}
export interface Problem { code: string; message: string; target: string | null; fix?: string | null }
export interface Check extends Problem { status: 'passed' | 'warning' | 'blocked'; fix: string | null }
export type SafeValue = string | number | boolean | null | SafeValue[] | { [key: string]: SafeValue };
export interface Change { code: string; message: string; target: string | null; affectedRecordIds: string[] }
export interface SafeEffects {
  createsEstimateRevision: boolean; approvalStatus: string | null; estimateStatus: string | null;
  createsAcceptedBaseline: boolean; createsHandoff: boolean; createsCommitment: boolean;
  workingLedgerJournalDelta: 0; apPayableDeltaCents: 0; journalPreview: [];
  externalAccounting: 'unavailable'; payment: 'not_started'; providerCallBound: 0;
  customerIssue: 'not_started'; customerAward: 'not_started'; budgetAdoption: 'not_started';
}
export interface Preflight extends Provenance {
  action: Action; resourceId: string; resourceVersion: ResourceVersion; version: ResourceVersion;
  allowed: boolean; fingerprint: string | null; checks: Check[]; changes: Change[]; safeEffects: SafeEffects;
  preview?: EstimatePreview;
}
export interface EstimatePreview {
  lines: (EntryLine & { lineNo: number; amountCents: Cents; previousLineId?: string | null })[];
  subtotalCents: Cents; contingencyCents: Cents; totalCents: Cents; revision: number;
}
interface ZeroFinancialEffects { journalCountDelta: 0; apBalanceDeltaCents: 0; providerCallsDelta: 0 }
export type ReceiptResult = ZeroFinancialEffects & (
  | { action: 'estimate.create'; status: 'draft'; estimateId: string; revision: number; totalCents: Cents }
  | { action: 'estimate.revise'; status: 'draft'; estimateId: string; predecessorId: string; revision: number; totalCents: Cents }
  | { action: 'estimate.request'; status: 'pending'; approvalId: string; estimateId: string }
  | { action: 'estimate.accept'; status: 'granted'; approvalId: string; estimateId: string }
  | { action: 'estimate.apply'; status: 'approved'; approvalId: string; estimateId: string; revision: number; totalCents: Cents }
  | { action: 'estimate.prepareHandoff'; status: 'prepared'; handoffId: string; estimateId: string; totalCents: Cents }
  | { action: 'estimate.createCommitment'; status: 'draft'; commitmentId: string; handoffId: string; estimateId: string; totalCents: Cents }
);
export interface Receipt<A extends Action = Action> extends Provenance {
  receiptId: string; replayed: boolean; effectApplied: boolean;
  result: Extract<ReceiptResult, { action: A }>;
}
export type DeepReadonly<T> = T extends readonly unknown[] ? { readonly [K in keyof T]: DeepReadonly<T[K]> }
  : T extends object ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T;
export interface PreparedAction<A extends Action = Action> {
  readonly action: A; readonly id: string; readonly version: ResourceVersion; readonly repeatabilityId: string;
  readonly body: DeepReadonly<MutationBody<A>>;
  readonly bodyJson: string; // The original reviewed wire body plus fingerprint, serialized once.
}
export interface CollectionFilters { projectId?: string; status?: string; search?: string }

export interface Personas extends Provenance { value: Persona[] }
export interface ProjectRow extends Project {
  entity: string;
  currency: 'USD';
  estimateCount: number;
  handoffCount: number;
}
export type Projects = Collection<ProjectRow>;
export interface DrawingRevisionRow extends DrawingSource {
  id: string; // Same ID as documentRevisionId; suitable for RecordGrid identity.
  version: ResourceVersion;
  projectId: string;
  projectName: string;
}
export type DrawingRevisions = Collection<DrawingRevisionRow>;
export interface Unit {
  unit: string;
  name: string;
  measured: boolean;
}
export interface EstimatePreparation extends Provenance {
  version: ResourceVersion;
  project: Project;
  drawingRevisions: DrawingRevisionRow[]; // Owned current revisions only.
  units: Unit[];
  inputMode: 'manual_entry';
  verifiedGeometry: false;
  availableActions: ActionAvailability[];
}
export interface EstimateApprovalRow {
  id: string;
  version: ResourceVersion;
  project: Project;
  estimateId: string;
  estimateRevision: number;
  status: 'pending' | 'granted' | 'consumed' | 'expired' | 'invalidated';
  effectiveStatus: string;
  totalCents: number;
  requestedBy: Person;
  approvedBy: Person | null;
  requestedAt: string;
  grantedAt: string | null;
  expiresAt: string;
  availableActions: ActionAvailability[];
}
export type EstimateApprovals = Collection<EstimateApprovalRow>;
export interface ApprovalPacket extends Provenance {
  version: ResourceVersion;
  approval: EstimateApprovalRow;
  estimate: EstimateRecord;
  comparison: Comparison;
  summary: string;
  consequence: string;
  checks: Preflight['checks'];
  availableActions: ActionAvailability[];
}
export interface HandoffPackage {
  id: string;
  title: string;
  supplier: { id: string; name: string };
  retainageRate: string;
}
export interface HandoffPreparation extends Provenance {
  version: ResourceVersion;
  project: Project;
  estimate: EstimateRecord;
  package: HandoffPackage;
  lines: HandoffLine[];
  subtotalCents: Cents;
  contingencyCents: Cents;
  totalCents: Cents;
  existingHandoffId: string | null;
  checks: Preflight['checks'];
  availableActions: ActionAvailability[];
  consequence: string;
}
export interface ErrorEnvelope {
  error: { code: string; message: string; target: string | null };
}
