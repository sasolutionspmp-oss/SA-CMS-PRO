/** Draft of actual Python DTOs. Authored text is UTF-8 source, rendered as text. */
export type Kind = 'specification_template' | 'contract_clause';
export type Action = 'library.create' | 'library.revise' | 'library.prepareReference' |
  'library.requestAdoption' | 'library.approveAdoption' | 'library.applyAdoption';
export type SourceKind = 'practice-authored-editor-text/1';
export type EffectKind = 'project-reference-only/1';
export type NativeApprovalStatus = 'pending' | 'granted' | 'consumed' | 'expired' | 'invalidated';
export type AuthorizationStatus = NativeApprovalStatus | 'stale';
export interface Provenance { contractVersion: 'cipher.library-practice.v1'; mode: 'practice'; synthetic: true }
export interface Person { id: string; displayName: string }
export interface Project { id: string; name: string }
export interface Revision {
  id: string; entryId: string; documentRevisionId: string; number: number; text: string;
  contentHash: string; byteCount: number; encoding: 'UTF-8'; sourceLocator: string;
  changeReason: string; previousRevisionId: string | null; isCurrent: boolean;
  currentRevisionId: string; author: Person; sourceKind: SourceKind; kind: Kind; title: string;
}
export interface Entry extends Provenance {
  id: string; project: Project; kind: Kind; title: string; documentId: string;
  sourceKind: SourceKind; currentRevision: Revision; revisionCount: number; version: string;
}
export interface EntryDetail extends Entry { revisions: Revision[] }
export interface RevisionDetail extends Revision, Provenance { project: Project; version: string }
export interface Preparation extends Provenance {
  project: Project; kinds: Kind[]; maxTextBytes: 65536; encoding: 'UTF-8';
  sourceKind: SourceKind; effectKind: EffectKind; version: string;
}
export interface ReferencePlan extends Provenance {
  id: string; project: Project; entryId: string; revisionId: string; currentRevisionId: string;
  title: string; kind: Kind; targetLocator: string; purpose: string; author: Person;
  creationStatus: 'prepared'; status: 'prepared' | NativeApprovalStatus | 'adopted_reference';
  effectiveStatus: 'prepared' | AuthorizationStatus | 'adopted_reference'; effectKind: EffectKind;
  approvalId: string | null; referenceId: string | null; sourceRevision: Revision; version: string;
}
export interface Approval extends Provenance {
  id: string; project: Project; planId: string; entryId: string; revisionId: string;
  title: string; kind: Kind; status: NativeApprovalStatus; authorizationStatus: AuthorizationStatus;
  requester: Person; reviewer: Person | null; appliedBy: Person | null; expiresAt: string;
  requestedAt: string; grantedAt: string | null; appliedAt: string | null; effectKind: EffectKind; version: string;
}
export interface ApprovalPacket extends Approval { plan: ReferencePlan }
export interface ProjectReference extends Provenance {
  id: string; project: Project; entryId: string; title: string; kind: Kind; planId: string;
  approvalId: string; revisionId: string; currentRevisionId: string; sourceCurrent: boolean;
  text: string; contentHash: string; targetLocator: string; purpose: string;
  status: 'adopted_reference'; effectKind: EffectKind; requester: Person; reviewer: Person;
  appliedBy: Person; sourceKind: SourceKind; version: string;
}
export interface Page<T> extends Provenance {
  items: T[]; count: number; nextCursor: string | null;
  facets: { statuses: string[]; kinds: Kind[] };
}
export interface CreateBody { kind: Kind; title: string; text: string; sourceLocator: string }
export interface ReviseBody { previousRevisionId: string; text: string; sourceLocator: string; changeReason: string }
export interface ReferenceBody { targetLocator: string; purpose: string }
export interface SafeEffects {
  entriesDelta: number; revisionsDelta: number; headsDelta: number; documentsDelta: number;
  documentRevisionsDelta: number; referencePlansDelta: number; approvalsDelta: number;
  projectReferencesDelta: number; approvalStatus: 'pending' | 'granted' | 'consumed' | null;
  journalDelta: 0; mailSinkDelta: 0; externalDistribution: false; contractExecution: false;
  engineeringCertification: false; projectReferenceOnly: true;
}
export interface Preview {
  kind: Kind; title: string; text: string; encoding: 'UTF-8'; byteCount: number; sourceLocator: string;
  entryId: string | null; revisionId: string | null; revisionNumber: number;
  previousRevisionId: string | null; sourceKind: SourceKind; targetLocator: string | null; purpose: string | null;
}
export interface Preflight extends Provenance {
  action: Action; resourceId: string; resourceVersion: string; version: string; allowed: boolean;
  fingerprint: string | null; checks: { code: string; status: 'passed' | 'blocked'; target: string | null; message: string; fix: string | null }[];
  changes: unknown[]; safeEffects: SafeEffects; preview?: Preview;
}
interface ResultLabels { action: Action; entryId: string; revisionId: string; effectKind: EffectKind;
  journalCountDelta: 0; apBalanceDeltaCents: 0; arBalanceDeltaCents: 0; providerCallsDelta: 0 }
export type Result = ResultLabels & (
  { action: 'library.create' | 'library.revise'; status: 'draft'; revision: number; contentHash: string } |
  { action: 'library.prepareReference'; status: 'prepared'; planId: string } |
  { action: 'library.requestAdoption'; status: 'pending'; planId: string; approvalId: string } |
  { action: 'library.approveAdoption'; status: 'granted'; planId: string; approvalId: string } |
  { action: 'library.applyAdoption'; status: 'adopted_reference'; planId: string; approvalId: string;
    referenceId: string; contentHash: string; targetLocator: string; purpose: string }
);
export interface ActionResponse extends Provenance { receiptId: string; replayed: boolean; effectApplied: boolean; result: Result }

export type PersonaId = 'author' | 'reviewer';
export interface Persona { personaId: PersonaId; displayName: string; synthetic: true }
export interface Session extends Provenance { currency: 'USD'; authenticated: boolean; sessionExpiresAt: string; csrfToken: string;
 person: (Person & {personaId: PersonaId}) | null; duties: string[]; projectIds: string[];
 capabilities: { sessionIdentity: 'registered_synthetic_person'; scopedReads: true; microsoftSignIn: false; liveAdmission: false;
 authoredTextStored: true; projectReferenceOnly: true; licensedContentIngestion: false; externalDistribution: false;
 contractExecution: false; engineeringCertification: false; financialEffects: false; commands: Action[] }; }
export type Receipt = ActionResponse;
export type Check = Preflight['checks'][number];
export interface ReviewBodies { 'library.create': CreateBody; 'library.revise': ReviseBody; 'library.prepareReference': ReferenceBody;
 'library.requestAdoption': Record<string, never>; 'library.approveAdoption': Record<string, never>; 'library.applyAdoption': Record<string, never> }
export interface PreparedAction<A extends Action = Action> { readonly action: A; readonly id: string; readonly version: string;
 readonly repeatabilityId: string; readonly body: Readonly<ReviewBodies[A] & {fingerprint:string}>; readonly bodyJson: string; }
export interface ReviewContext { source: Revision; targetLocator?: string; purpose?: string; planId?: string; approvalId?: string }
export interface Filters { projectId?: string; search?: string; kind?: Kind; status?: string }
