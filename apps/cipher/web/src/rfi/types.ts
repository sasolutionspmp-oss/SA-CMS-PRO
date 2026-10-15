/** Fixed local RFI contract. Source files/bytes and external delivery are unavailable. */
export type Action = 'rfi.create' | 'rfi.draftResponse' | 'rfi.requestResponse' | 'rfi.approveResponse' | 'rfi.applyResponse' | 'rfi.setDistribution' | 'rfi.requestDistribution' | 'rfi.approveDistribution' | 'rfi.distribute';
export type ResourceType = 'project' | 'rfi' | 'responseApproval' | 'distributionApproval';
export type Duty = 'staff' | 'pm';
export type RFIStatus = 'open' | 'answered';
export type ApprovalStatus = 'pending' | 'granted' | 'consumed' | 'expired' | 'invalidated';
export type AuthorizationStatus = ApprovalStatus | 'stale';
export type Recipient = 'engineer@synthetic-rfi.invalid' | 'owner@synthetic-rfi.invalid' | 'project-team@synthetic-rfi.invalid';
export interface Provenance { contractVersion: 'cipher.rfi-practice.v1'; mode: 'practice'; synthetic: true; currency: 'USD' }
export interface Person { id: string; displayName: string }
export interface Project { id: string; name: string }
export interface Right { use: 'project_use' | 'distribution'; allowed: boolean; status: 'permitted' | 'held'; reason: string; onDate: string; sourceContentAvailable: false }
export interface DrawingCitation {
  drawingId: string; drawingNumber: string; title: string; revisionId: string; revisionLabel: string; documentRevisionId: string;
  issuedAtCitation: { issuedAt: string; issuedBy: string };
  current: { status: 'working' | 'issued' | 'superseded' | 'withdrawn'; issuedRevisionId: string | null; issuedRevisionLabel: string | null; workingRevisionId: string | null; evidenceHeadRevisionId: string };
  sourceChangedSinceReview: boolean | null; rights: Right[]; sourceContentAvailable: false;
}
export interface DocumentCitation { documentId: string; kind: string; title: string; revisionId: string; revisionNumber: number; currentRevisionId: string; currentRevisionNumber: number; sourceChangedSinceReview: boolean | null; rights: Right[]; sourceContentAvailable: false }
export interface CitationHold { code: 'issued_drawing_required' | 'project_use_required'; message: string }
export type DrawingChoice = DrawingCitation & { citable: boolean; citationHold: CitationHold | null };
export type DocumentChoice = DocumentCitation & { citable: boolean; citationHold: CitationHold | null };
export interface Citations { drawings: DrawingCitation[]; documents: DocumentCitation[]; sourceContentAvailable: false }
export interface Preparation extends Provenance { project: Project; sources: { drawings: DrawingChoice[]; documents: DocumentChoice[]; sourceContentAvailable: false }; maxTextCharacters: 12000; maxCitationsPerKind: 12; version: string }
export interface Impact { costImpactCents: number | null; scheduleImpactDays: number | null; informationalOnly: true; adopted: false }
export interface ResponseRevision extends Impact { id: string; nativeVersion: number; text: string; author: Person; createdAt: string }
export interface OfficialResponse extends ResponseRevision { status: 'answered'; approvalId: string; requester: Person; reviewer: Person; appliedBy: Person; answeredAt: string; engineeringCertification: false }
export interface DistributionList { id: string; nativeVersion: number; recipients: Recipient[]; preparedBy: Person; createdAt: string; channel: 'mail-sink'; externalDistribution: false }
export interface Distribution { id: string; approvalId: string; status: 'distributed'; recipients: Recipient[]; channel: 'mail-sink'; externalDistribution: false; distributedAt: string; distributedBy: Person; requester: Person; reviewer: Person }
export interface Approval extends Provenance { id: string; projectId: string; rfiId: string; operation: 'field.respond_rfi' | 'field.distribute_rfi'; status: ApprovalStatus; authorizationStatus: AuthorizationStatus; originalGrantStatus: 'granted' | null; requester: Person; reviewer: Person | null; appliedBy: Person | null; requestedAt: string; grantedAt: string | null; appliedAt: string | null; expiresAt: string; version: string }
export interface RFI extends Provenance { id: string; projectId: string; project: Project; number: string; subject: string; question: string; status: RFIStatus; nativeVersion: number; version: string; createdBy: Person; createdAt: string; citations: Citations; draftResponse: ResponseRevision | null; officialResponse: OfficialResponse | null; responseApproval: Approval | null; distributionList: DistributionList | null; distributionApproval: Approval | null; distributions: Distribution[]; actions: { action: Action; resourceType: 'rfi'; requiredDuty: Duty; authorityAllowed: boolean; requiresReview: true }[] }
export interface RFIDetail extends RFI { responseHistory: ResponseRevision[]; distributionHistory: DistributionList[] }
export interface ApprovalPacket extends Approval { rfi: RFI; reviewedCitations: Citations; currentCitations: Citations; reviewedResponse: ResponseRevision | null; reviewedDistributionList: DistributionList | null }
export interface DistributionPreparation extends Provenance { rfi: RFI; recipientChoices: Recipient[]; channel: 'mail-sink'; externalDistribution: false; version: string }
export interface Page<T> extends Provenance { items: T[]; count: number; nextCursor: string | null; facets: { statuses: string[] } }
export interface SafeEffects {
  rfisDelta: number; rfiLinksDelta: number; drawingReferencesDelta: number; rfiSourcesDelta: number;
  responseRevisionsDelta: number; distributionRevisionsDelta: number; approvalSourcesDelta: number; approvalsDelta: number; syntheticDistributionsDelta: number; invalidatedApprovalsDelta: number;
  approvalStatus: 'pending' | 'granted' | 'consumed' | null; rfiStatus: RFIStatus | null;
  journalDelta: 0; changeDraftDelta: 0; changeExecutionDelta: 0; commitmentDelta: 0; contractValueDeltaCents: 0; budgetDeltaCents: 0; scheduleBaselineDeltaDays: 0;
  externalDistribution: false; engineeringCertification: false; adoptsPotentialImpacts: false; mailSinkOnly: true;
}
export interface Preview extends Impact { source: Citations; subject: string; question: string; responseText: string | null; recipients: Recipient[]; approvalId: string | null }
export interface Preflight extends Provenance { action: Action; resourceId: string; resourceVersion: string; version: string; allowed: boolean; checks: { code: string; status: 'passed' | 'blocked'; message: string; target: string; fix: string | null }[]; changes: never[]; safeEffects: SafeEffects; fingerprint: string | null; preview?: Preview }
export interface CreateBody { subject: string; question: string; drawingRevisionIds: string[]; documentRevisionIds: string[] }
export interface ResponseBody { responseText: string; costImpact: string | null; scheduleImpactDays: number | null }
export interface DistributionBody { recipients: Recipient[] }
export type Body = CreateBody | ResponseBody | DistributionBody | Record<string, never>;
export interface Session extends Provenance { authenticated: boolean; sessionExpiresAt: string; csrfToken: string; person: (Person & { personaId: 'staff' | 'pm' | 'reviewer' }) | null; duties: Duty[]; projectIds: string[]; capabilities: { sessionIdentity: 'registered_synthetic_person'; scopedReads: true; microsoftSignIn: false; liveAdmission: false; issuedDrawingCitations: true; syntheticDistribution: true; externalDistribution: false; contractChange: false; engineeringCertification: false; financialEffects: false; commands: Action[] } }
export interface ErrorResponse extends Provenance { error: { code: string; target: string | null; message: string; fix: null; details: null }; receiptId?: string; replayed?: boolean; effectApplied?: false }

export type PersonaId = 'staff' | 'pm' | 'reviewer';
export interface Persona { personaId: PersonaId; displayName: string; synthetic: true }
export interface Filters { projectId?: string; search?: string; status?: string }
export interface ReviewBodies { 'rfi.create': CreateBody; 'rfi.draftResponse': ResponseBody; 'rfi.setDistribution': DistributionBody;
 'rfi.requestResponse': Record<string, never>; 'rfi.approveResponse': Record<string, never>; 'rfi.applyResponse': Record<string, never>;
 'rfi.requestDistribution': Record<string, never>; 'rfi.approveDistribution': Record<string, never>; 'rfi.distribute': Record<string, never> }
export interface PreparedAction<A extends Action = Action> { readonly action: A; readonly id: string; readonly version: string;
 readonly repeatabilityId: string; readonly body: Readonly<ReviewBodies[A] & {fingerprint:string}>; readonly bodyJson: string }
export interface ReviewContext { preparation?: Preparation; rfi?: RFI; packet?: ApprovalPacket }
export interface Result { action: Action; rfiId: string; rfiVersion: number; status: 'open'|'draft'|'recorded'|'pending'|'granted'|'answered'|'distributed';
 rfiStatus?: RFIStatus; responseRevisionId?: string; distributionRevisionId?: string; approvalId?: string; distributionId?: string;
 recipients?: Recipient[]; syntheticMailSink?: true; externalDelivery?: 'not_attempted';
 journalDelta: 0; changeDraftDelta: 0; changeExecutionDelta: 0; commitmentDelta: 0; contractValueDeltaCents: 0;
 budgetDeltaCents: 0; scheduleBaselineDeltaDays: 0; externalDistribution: false; engineeringCertification: false;
 adoptsPotentialImpacts: false; mailSinkOnly: true }
export interface Receipt extends Provenance { receiptId: string; replayed: boolean; effectApplied: boolean; result: Result }
