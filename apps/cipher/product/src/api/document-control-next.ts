import schema from '../../../platform/apps/cipher_aec/cipher_aec/document_control/schemas/api-v1.schema.json' with { type: 'json' };
import coreSchema from '../../../platform/apps/cipher_aec/cipher_aec/api/schema.json' with { type: 'json' };
import { api, ApiError, rpc } from './client';
import { engineeringDigest, type Actor, type Scope } from './engineering';
import { sameValue, schemaShape } from './schema-validation';
import type * as D from './document-control.generated';
import type { ApprovalCommandResponse, DocumentAdoptionRequestApprovalPacket, DocumentSharedAdoptionRequestApprovalPacket, DocumentRedlineApprovalPacket, DocumentLifecycleRequestApprovalPacket, DocumentApprovalExecutionResponse } from './contracts.generated';

export type NextDocumentKind = 'clause_use' | 'redline' | 'clause_application' | 'lifecycle_request' | 'lifecycle' | 'adoption' | 'adoption_request' | 'issue';
export type CompanyDocumentKind = 'rights' | 'library' | 'library_revision';
export type NextDocumentSubjectKind = 'adoption_request' | 'redline' | 'lifecycle_request';
export type NextDocumentPacket = DocumentAdoptionRequestApprovalPacket | DocumentSharedAdoptionRequestApprovalPacket | DocumentRedlineApprovalPacket | DocumentLifecycleRequestApprovalPacket;
export const nextDocumentAction = { adoption_request: 'document.library.adopt.v1', redline: 'document.clause.apply.v1', lifecycle_request: 'document.lifecycle.v1' } as const;
const subjectTypes = { adoption_request: 'Cipher Adoption Request', redline: 'Cipher Redline Revision', lifecycle_request: 'Cipher Document Lifecycle Request' } as const;
const defs: Record<NextDocumentKind, string> = { clause_use: 'DcClauseUse', redline: 'DcRedline', clause_application: 'DcClauseApplication', lifecycle_request: 'DcLifecycleRequest', lifecycle: 'DcLifecycle', adoption: 'DcAdoption', adoption_request: 'DcAdoptionRequest', issue: 'DcIssue' };
const companyDefs: Record<CompanyDocumentKind, string> = { rights: 'DcCompanyRights', library: 'DcCompanyLibrary', library_revision: 'DcCompanyLibraryRevision' };
const projectPrefix = 'cipher_aec.document_control.api.', companyPrefix = 'cipher_aec.document_control.company_api.';
const shape = (name: string, value: unknown) => schemaShape(schema, name, value);
const invalid = () => new ApiError('This reply could not be matched to the exact Company, Project, original sources and reviewed documentary request.', 'INVALID_CONTRACT', 200);
const inputError = () => new ApiError('Complete the fields and exact original document selections before saving.', 'document_control_input', 422);
const scoped = (record: { company: string; project: string | null; scope_type: string }, scope: Scope) => record.company === scope.company && record.project === scope.project && record.scope_type === 'Project';
const companyScoped = (record: { company: string; project: string | null; scope_type: string }, company: string) => record.company === company && record.project === null && record.scope_type === 'Company';
const authored = (record: { author_person: string; author_user: string }, actor: Actor) => record.author_person === actor.personId && record.author_user === actor.user;
const exactArtifacts = (actual: D.DcArtifact[], expected: D.DcArtifactInput[]) => actual.length === expected.length && actual.every((row, i) => row.revision_id === expected[i].revision_id && row.source_sha256 === expected[i].source_sha256);
const textDigest = async (text: string) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(byte => byte.toString(16).padStart(2, '0')).join('');
const standingBody = ({ version: _version, ...body }: D.DcIssuedStanding) => body;
const mergeArtifacts = (...groups: D.DcArtifact[][]) => [...new Map(groups.flat().map(row => [row.revision_id, row])).entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([, row]) => row);

function targetMatches(target: D.DcClauseTargetSnapshot, scope: Scope, kind?: D.DcClauseTargetKind, id?: string) {
  return shape('DcClauseTargetSnapshot', target) && target.company === scope.company && (target.kind === 'proposal_revision' ? companyScoped(target, scope.company) : scoped(target, scope)) && (!kind || target.kind === kind) && (!id || target.id === id);
}
async function validateTextRecord(record: D.DcRecord) {
  if ('predecessor' in record && (record.predecessor === null ? record.revision_number !== 1 : record.revision_number < 2)) throw invalid();
  if ('source_clause' in record && (record.source_clause.text_sha256 !== await textDigest(record.source_clause.text) || [...record.source_clause.text].length !== record.source_clause.reference.end - record.source_clause.reference.start || !record.artifacts.some(row => row.revision_id === record.source_clause.reference.revision_id && row.source_sha256 === record.source_clause.reference.source_sha256))) throw invalid();
  if ('adoption_id' in record && record.parent_id !== record.adoption_id || 'clause_use_id' in record && record.parent_id !== record.clause_use_id) throw invalid();
  if ('proposed_text' in record && (record.proposed_sha256 !== await textDigest(record.proposed_text) || record.proposed_text === record.original_text)) throw invalid();
  if ('target' in record && (!targetMatches(record.target_snapshot, { company: record.company, project: record.project }, record.target.kind, record.target.id) || record.target_snapshot.record_digest !== record.target.record_digest)) throw invalid();
  if ('before' in record && (!scoped(record.before, { company: record.company, project: record.project }) || record.before.document_id !== record.parent_id || record.before.status !== 'issued' || !record.before.current_issued || !record.before.original_issued)) throw invalid();
  if ('expected_version' in record) {
    const current = record.before.current_issued, definition = record.definition, replacement = record.replacement;
    if (record.expected_version !== await engineeringDigest(record.before) || !current || current.issue_id !== definition.issue_id || current.issue_digest !== definition.issue_digest || !record.artifacts.some(row => row.document_id === record.parent_id && row.revision_id === current.revision_id && row.source_sha256 === current.source_sha256) || (definition.action === 'withdraw' ? replacement !== null : !replacement || replacement.issue_id !== definition.replacement_issue_id || replacement.issue_digest !== definition.replacement_issue_digest || replacement.issue_id === current.issue_id || replacement.revision_id === current.revision_id || !record.artifacts.some(row => row.document_id === record.parent_id && row.revision_id === replacement.revision_id && row.source_sha256 === replacement.source_sha256))) throw invalid();
  }
  if ('document_id' in record && 'before' in record && (record.document_id !== record.parent_id || record.predecessor !== (record.before.last_event?.id || null) || (record.action === 'withdraw' ? record.replacement !== null || record.status !== 'withdrawn' : !record.replacement || record.status !== 'superseded' || record.replacement.revision_id === record.before.current_issued?.revision_id))) throw invalid();
}
export async function validateNextDocumentRecord(value: D.DcGetResponse, scope: Scope, kind: NextDocumentKind, id?: string, parent?: string) {
  const recordShape = kind === 'adoption_request' && value && 'library_scope' in (value.record || {}) ? 'DcSharedAdoptionRequest' : defs[kind];
  if (!shape('DcGetResponse', value) || !shape(recordShape, value.record) || !scoped(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || value.record_digest !== await engineeringDigest(value.record) || (kind === 'adoption_request' || kind === 'adoption' ? typeof value.library_current !== 'boolean' : value.library_current !== null)) throw invalid();
  await validateTextRecord(value.record); return value;
}
export async function validateCompanyDocumentRecord(value: D.DcCompanyGetResponse, company: string, kind: CompanyDocumentKind, id?: string, parent?: string) {
  if (!shape('DcCompanyGetResponse', value) || !shape(companyDefs[kind], value.record) || !companyScoped(value.record, company) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || value.record_digest !== await engineeringDigest(value.record) || (kind === 'library_revision' ? typeof value.library_current !== 'boolean' : value.library_current !== null)) throw invalid();
  if ('predecessor' in value.record && (value.record.predecessor === null ? value.record.revision_number !== 1 : value.record.revision_number < 2)) throw invalid();
  return value;
}
export async function validateIssuedStanding(value: D.DcIssuedStandingResponse, scope: Scope, documentId?: string) {
  if (!shape('DcIssuedStandingResponse', value) || !scoped(value.standing, scope) || documentId && value.standing.document_id !== documentId) throw invalid();
  const s = value.standing;
  if (s.version !== await engineeringDigest(standingBody(s)) || (s.status === 'not_issued' ? s.original_issued !== null || s.current_issued !== null || s.last_event !== null : !s.original_issued || (s.status === 'issued' ? !s.current_issued : s.current_issued !== null || !s.last_event)) || !s.last_event && s.status === 'issued' && !sameValue(s.original_issued, s.current_issued)) throw invalid();
  return value;
}
export function validateNextDocumentPacket(packet: NextDocumentPacket, scope: Scope, id?: string) {
  const definition = packet?.action === 'document.library.adopt.v1' ? (packet.review_manifest?.effect && 'library_scope' in packet.review_manifest.effect ? 'DocumentSharedAdoptionRequestApprovalPacket' : 'DocumentAdoptionRequestApprovalPacket') : packet?.action === 'document.clause.apply.v1' ? 'DocumentRedlineApprovalPacket' : packet?.action === 'document.lifecycle.v1' ? 'DocumentLifecycleRequestApprovalPacket' : '';
  if (!definition || !schemaShape(coreSchema, definition, packet) || packet.company !== scope.company || packet.project !== scope.project || id && packet.id !== id || packet.subject.id !== packet.review_manifest.subject.name || packet.subject.type !== packet.review_manifest.subject.doctype || packet.subject.label !== packet.review_manifest.subject.label || packet.review_manifest.effect.subject_id !== packet.subject.id || packet.review_manifest.effect.subject_digest !== packet.source_version || packet.review_manifest.effect.action !== packet.action) throw invalid();
  return packet;
}
export async function validateNextDocumentManifestSubject(packet: NextDocumentPacket, subject: D.DcGetResponse, kind: NextDocumentSubjectKind) {
  const scope = { company: subject.record.company, project: subject.record.project };
  await validateNextDocumentRecord(subject, scope, kind); validateNextDocumentPacket(packet, scope);
  const record = subject.record as D.DcSharedAdoptionRequest | D.DcAdoptionRequest | D.DcRedline | D.DcLifecycleRequest;
  const effect = { schema: 'cipher.document.authorization.v1', action: nextDocumentAction[kind], subject_kind: kind, subject_id: record.id, subject_digest: subject.record_digest, artifacts: record.artifacts, no_effects: record.no_effects, electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false,
    ...(kind === 'adoption_request' ? { library_revision: (record as D.DcAdoptionRequest).library_revision, library_digest: (record as D.DcAdoptionRequest).library_digest, target_locator: (record as D.DcAdoptionRequest).definition.target_locator, ...('library_scope' in record ? { library_scope: record.library_scope } : {}) } : kind === 'redline' ? Object.fromEntries(['target', 'target_snapshot', 'original_text', 'proposed_text', 'proposed_sha256', 'target_changed'].map(key => [key, record[key as keyof typeof record]])) : { document_id: record.parent_id, before: (record as D.DcLifecycleRequest).before, definition: (record as D.DcLifecycleRequest).definition, replacement: (record as D.DcLifecycleRequest).replacement, expected_version: (record as D.DcLifecycleRequest).expected_version }) };
  const summary = { definition: 'definition' in record ? record.definition : null, purpose: null, required_response: null, no_effects: record.no_effects, rights_basis: 'authored-declaration', external_delivery: false, commercial_execution: false };
  const source = packet.review_manifest.sources[0], documents = [...new Set(record.artifacts.map(row => row.document_id))].sort();
  const label = kind === 'redline' ? (record as D.DcRedline).reason : kind === 'lifecycle_request' ? (record as D.DcLifecycleRequest).definition.reason : (record as D.DcAdoptionRequest).definition.purpose;
  if (packet.action !== nextDocumentAction[kind] || packet.subject.type !== subjectTypes[kind] || packet.subject.id !== record.id || packet.subject.label !== label || packet.source_version !== subject.record_digest || packet.requester.id !== record.author_person || !sameValue(packet.review_manifest.effect, effect) || !sameValue(packet.review_manifest.summary, summary) || !sameValue(source.artifacts, record.artifacts) || source.rights.length !== documents.length || source.rights.some((policy, i) => policy.company !== scope.company || policy.parent_id !== documents[i] || (policy.scope_type === 'Company' ? policy.project !== null : !policy.project) || (kind === 'adoption_request' ? 'library_scope' in record ? policy.scope_type !== record.library_scope.scope_type || policy.project !== record.library_scope.project : !scoped(policy, scope) : false))) throw invalid();
  return packet;
}

type CompanyBasis = { original?: D.DcCompanyGetResponse; artifacts: D.DcArtifact[] };
export type NextDocumentCommand =
  | { kind: 'company_set_rights'; payload: Omit<D.DcCompanySetRightsRequest, 'operation_id'>; basis: CompanyBasis }
  | { kind: 'company_create_library'; payload: Omit<D.DcCompanyCreateLibraryRequest, 'operation_id'>; basis: CompanyBasis }
  | { kind: 'company_revise_library'; payload: Omit<D.DcCompanyReviseLibraryRequest, 'operation_id'>; basis: CompanyBasis }
  | { kind: 'create_shared_adoption'; payload: Omit<D.DcCreateSharedAdoptionRequest, 'operation_id'>; basis: { original: D.DcCompanyGetResponse | D.DcGetResponse } }
  | { kind: 'create_clause_use'; payload: Omit<D.DcCreateClauseUseRequest, 'operation_id'>; basis: { adoption: D.DcGetResponse; target: D.DcClauseTargetSnapshot; quotedText: string } }
  | { kind: 'create_redline'; payload: Omit<D.DcCreateRedlineRequest, 'operation_id'>; basis: { original: D.DcGetResponse; previous?: D.DcGetResponse } }
  | { kind: 'request_lifecycle'; payload: Omit<D.DcRequestLifecycleRequest, 'operation_id'>; basis: { standing: D.DcIssuedStanding; original: D.DcGetResponse; replacement?: D.DcGetResponse } }
  | { kind: 'request_authorization'; payload: Scope; subject: D.DcGetResponse; subjectKind: NextDocumentSubjectKind }
  | { kind: 'authorization_action'; payload: Scope; packet: NextDocumentPacket; action: 'Grant' | 'Reject' | 'execute' | 'withdraw'; reason: string };
type AuthorCommand = Exclude<NextDocumentCommand, { kind: 'request_authorization' | 'authorization_action' }>;
export type NextDocumentReply = D.DcCompanySetRightsResponse | D.DcCompanyCreateLibraryResponse | D.DcCompanyReviseLibraryResponse | D.DcCreateSharedAdoptionResponse | D.DcCreateClauseUseResponse | D.DcCreateRedlineResponse | D.DcRequestLifecycleResponse | ApprovalCommandResponse | DocumentApprovalExecutionResponse;
const commands: Record<AuthorCommand['kind'], [string, string, string]> = {
  company_set_rights: ['DcCompanySetRightsRequest', 'DcCompanySetRightsResponse', 'rights'], company_create_library: ['DcCompanyCreateLibraryRequest', 'DcCompanyCreateLibraryResponse', 'library_revision'], company_revise_library: ['DcCompanyReviseLibraryRequest', 'DcCompanyReviseLibraryResponse', 'library_revision'], create_shared_adoption: ['DcCreateSharedAdoptionRequest', 'DcCreateSharedAdoptionResponse', 'adoption_request'], create_clause_use: ['DcCreateClauseUseRequest', 'DcCreateClauseUseResponse', 'clause_use'], create_redline: ['DcCreateRedlineRequest', 'DcCreateRedlineResponse', 'redline'], request_lifecycle: ['DcRequestLifecycleRequest', 'DcRequestLifecycleResponse', 'lifecycle_request'],
};
function issueReference(value: D.DcGetResponse, documentId: string): D.DcIssueReference {
  const issue = value.record as D.DcIssue, artifacts = issue.artifacts.filter(row => row.document_id === documentId);
  if (artifacts.length !== 1) throw invalid();
  return { issue_id: issue.id, issue_digest: value.record_digest, revision_id: artifacts[0].revision_id, source_sha256: artifacts[0].source_sha256 };
}
async function preflight(command: AuthorCommand) {
  if (command.kind.startsWith('company_')) {
    const c = command as Extract<AuthorCommand, { kind: `company_${string}` }>;
    if (c.basis.original) await validateCompanyDocumentRecord(c.basis.original, c.payload.company, c.kind === 'company_set_rights' ? 'rights' : 'library');
    if (c.kind === 'company_set_rights' ? c.payload.expected_version !== (c.basis.original?.record_digest || null) || c.basis.original && (!('parent_id' in c.basis.original.record) || c.basis.original.record.parent_id !== c.payload.document_id) || !exactArtifacts(c.basis.artifacts, [c.payload.definition.evidence_artifact]) || c.basis.artifacts[0]?.document_id === c.payload.document_id : !exactArtifacts(c.basis.artifacts, [c.payload.artifact]) || c.kind === 'company_revise_library' && (!c.basis.original || c.payload.library_id !== c.basis.original.record.id || c.payload.expected_version !== c.basis.original.record_digest)) throw inputError();
  } else if (command.kind === 'create_shared_adoption') {
    const p = command.payload, original = command.basis.original;
    if (p.library_scope.scope_type === 'Company') await validateCompanyDocumentRecord(original as D.DcCompanyGetResponse, p.company, 'library_revision', p.library_revision);
    else {
      const value = original as D.DcGetResponse;
      if (!shape('DcGetResponse', value) || !shape('DcLibraryRevision', value.record) || !scoped(value.record, { company: p.company, project: p.library_scope.project }) || value.record.id !== p.library_revision || await engineeringDigest(value.record) !== value.record_digest || typeof value.library_current !== 'boolean') throw invalid();
    }
    if (original.record_digest !== p.library_digest) throw inputError();
  } else if (command.kind === 'create_clause_use') {
    const p = command.payload, b = command.basis; await validateNextDocumentRecord(b.adoption, p, 'adoption', p.adoption_id);
    if (b.adoption.record_digest !== p.adoption_digest || !targetMatches(b.target, p, p.target.kind, p.target.id) || b.target.record_digest !== p.target.record_digest || !(b.adoption.record as D.DcAdoption).artifacts.some(row => row.revision_id === p.source_clause.revision_id && row.source_sha256 === p.source_clause.source_sha256) || p.source_clause.end <= p.source_clause.start || [...b.quotedText].length !== p.source_clause.end - p.source_clause.start || !b.quotedText.trim()) throw inputError();
  } else if (command.kind === 'create_redline') {
    const p = command.payload, b = command.basis; await validateNextDocumentRecord(b.original, p, 'clause_use', p.clause_use_id);
    if (b.previous) await validateNextDocumentRecord(b.previous, p, 'redline', undefined, p.clause_use_id);
    if (b.original.record_digest !== p.clause_use_digest || p.expected_version !== (b.previous?.record_digest || null) || p.proposed_text === (b.original.record as D.DcClauseUse).source_clause.text) throw inputError();
  } else if (command.kind === 'request_lifecycle') {
    const p = command.payload, b = command.basis; await validateIssuedStanding({ standing: b.standing }, p, p.document_id); await validateNextDocumentRecord(b.original, p, 'issue', p.definition.issue_id);
    if (p.expected_version !== b.standing.version || b.standing.status !== 'issued' || !sameValue(b.standing.current_issued, issueReference(b.original, p.document_id)) || p.definition.issue_digest !== b.original.record_digest) throw inputError();
    if (p.definition.action === 'supersede') {
      if (!b.replacement) throw inputError(); await validateNextDocumentRecord(b.replacement, p, 'issue', p.definition.replacement_issue_id || undefined);
      if (p.definition.replacement_issue_digest !== b.replacement.record_digest || p.definition.replacement_issue_id === p.definition.issue_id || issueReference(b.replacement, p.document_id).revision_id === b.standing.current_issued?.revision_id) throw inputError();
    } else if (b.replacement) throw inputError();
  }
}
async function validateAuthored(command: AuthorCommand & { operation_id: string }, result: NextDocumentReply, actor: Actor) {
  const [, responseDefinition, key] = commands[command.kind];
  if (!shape(responseDefinition, result) || result.operation.id !== command.operation_id) throw invalid();
  const records = result as unknown as Record<string, D.DcRecord | D.DcCompanyRecord>, record = records[key];
  if (!record || !authored(record, actor) || (command.kind.startsWith('company_') ? !companyScoped(record, command.payload.company) : !scoped(record, command.payload as Scope))) throw invalid();
  if (command.kind === 'company_set_rights') {
    const r = record as D.DcCompanyRights, p = command.payload, previous = command.basis.original?.record as D.DcCompanyRights | undefined, { evidence_artifact, ...fields } = p.definition;
    if (!Object.entries(fields).every(([key, value]) => sameValue(r[key as keyof D.DcCompanyRights], value)) || !sameValue([r.evidence_artifact], command.basis.artifacts) || !exactArtifacts([r.evidence_artifact], [evidence_artifact]) || r.parent_id !== p.document_id || r.predecessor !== (previous?.id || null) || r.revision_number !== (previous?.revision_number || 0) + 1) throw invalid();
  } else if (command.kind === 'company_create_library' || command.kind === 'company_revise_library') {
    const r = record as D.DcCompanyLibraryRevision, h = records.library as D.DcCompanyLibrary, p = command.payload;
    if (!companyScoped(h, p.company) || r.parent_id !== h.id || h.current_revision !== r.id || h.revision_number !== r.revision_number || !sameValue(r.definition, p.definition) || !sameValue(r.artifacts, command.basis.artifacts)) throw invalid();
    if (command.kind === 'company_create_library') { if (!authored(h, actor) || h.revision_number !== 1 || r.predecessor !== null) throw invalid(); }
    else { const old = command.basis.original!.record as D.DcCompanyLibrary; if (!sameValue(h, { ...old, current_revision: r.id, revision_number: old.revision_number + 1 }) || r.predecessor !== old.current_revision) throw invalid(); }
  } else if (command.kind === 'create_shared_adoption') {
    const r = record as D.DcSharedAdoptionRequest, p = command.payload, original = command.basis.original.record as D.DcLibraryRevision | D.DcCompanyLibraryRevision;
    if (r.parent_id !== original.parent_id || r.library_revision !== original.id || r.library_digest !== command.basis.original.record_digest || !sameValue(r.library_scope, p.library_scope) || !sameValue(r.artifacts, original.artifacts) || !sameValue(r.definition, p.definition)) throw invalid();
  } else if (command.kind === 'create_clause_use') {
    const r = record as D.DcClauseUse, p = command.payload, b = command.basis;
    if (r.parent_id !== p.adoption_id || r.adoption_id !== p.adoption_id || r.adoption_digest !== p.adoption_digest || !sameValue(r.source_clause.reference, p.source_clause) || r.source_clause.text !== b.quotedText || r.source_clause.text_sha256 !== await textDigest(b.quotedText) || !sameValue(r.target, p.target) || !sameValue(r.target_snapshot, b.target) || r.purpose !== p.purpose || !sameValue(r.artifacts, (b.adoption.record as D.DcAdoption).artifacts)) throw invalid();
  } else if (command.kind === 'create_redline') {
    const r = record as D.DcRedline, p = command.payload, original = command.basis.original.record as D.DcClauseUse, previous = command.basis.previous?.record as D.DcRedline | undefined;
    if (r.parent_id !== p.clause_use_id || r.clause_use_id !== p.clause_use_id || r.clause_use_digest !== p.clause_use_digest || r.predecessor !== (previous?.id || null) || r.revision_number !== (previous?.revision_number || 0) + 1 || r.original_text !== original.source_clause.text || r.proposed_text !== p.proposed_text || r.proposed_sha256 !== await textDigest(p.proposed_text) || r.reason !== p.reason || !sameValue(r.target, original.target) || !sameValue(r.target_snapshot, original.target_snapshot) || !sameValue(r.artifacts, original.artifacts)) throw invalid();
  } else {
    const r = record as D.DcLifecycleRequest, p = command.payload, b = command.basis;
    if (r.parent_id !== p.document_id || r.expected_version !== p.expected_version || !sameValue(r.before, standingBody(b.standing)) || !sameValue(r.definition, p.definition) || !sameValue(r.replacement, b.replacement ? issueReference(b.replacement, p.document_id) : null) || !sameValue(r.artifacts, b.replacement ? mergeArtifacts((b.original.record as D.DcIssue).artifacts, (b.replacement.record as D.DcIssue).artifacts) : (b.original.record as D.DcIssue).artifacts)) throw invalid();
  }
  return result;
}

async function sendApproval(command: Extract<NextDocumentCommand, { kind: 'request_authorization' | 'authorization_action' }> & { operation_id: string }, actor: Actor): Promise<NextDocumentReply> {
  if (command.kind === 'request_authorization') {
    await validateNextDocumentRecord(command.subject, command.payload, command.subjectKind);
    if (command.subject.record.author_person !== actor.personId) throw inputError();
    const result = await rpc<ApprovalCommandResponse>('cipher_aec.api.approvals.request_action', { ...command.payload, action: nextDocumentAction[command.subjectKind], subject_id: command.subject.record.id, expected_version: command.subject.record_digest, operation_id: command.operation_id }, true);
    if (!schemaShape(coreSchema, 'ApprovalCommandResponse', result) || result.operation.id !== command.operation_id) throw invalid();
    await validateNextDocumentManifestSubject(result.packet as NextDocumentPacket, command.subject, command.subjectKind); return result;
  }
  const { packet, action } = command, reason = command.reason.trim(); validateNextDocumentPacket(packet, command.payload);
  let previousLifecycle: D.DcLifecycle | undefined;
  if (action === 'execute' && packet.action === 'document.lifecycle.v1' && packet.review_manifest.effect.before.last_event) {
    const reference = packet.review_manifest.effect.before.last_event;
    const previous = await validateNextDocumentRecord(await rpc<D.DcGetResponse>(projectPrefix + 'get_record', { ...command.payload, kind: 'lifecycle', record_id: reference.id }), command.payload, 'lifecycle', reference.id, packet.review_manifest.effect.document_id);
    if (previous.record_digest !== reference.record_digest) throw invalid();
    previousLifecycle = previous.record as D.DcLifecycle;
  }
  const result = await api.approvalAction(action, { ...command.payload, packet_id: packet.id, manifest_hash: packet.manifest_hash, reason, operation_id: command.operation_id });
  if (!schemaShape(coreSchema, action === 'execute' ? 'DocumentApprovalExecutionResponse' : 'ApprovalCommandResponse', result) || result.operation.id !== command.operation_id) throw invalid();
  const current = validateNextDocumentPacket(result.packet as NextDocumentPacket, command.payload, packet.id);
  const decisionIdentity = (decision: NextDocumentPacket['decisions'][number]) => ({ id: decision.id, actor_person: decision.actor.id, decision: decision.decision, at: decision.at, reason: decision.reason });
  if (current.action !== packet.action || !sameValue(current.subject, packet.subject) || current.source_version !== packet.source_version || current.manifest_hash !== packet.manifest_hash || current.requester.id !== packet.requester.id || current.created_at !== packet.created_at || current.expires_at !== packet.expires_at || current.policy.id !== packet.policy.id || !sameValue(current.review_manifest, packet.review_manifest) || !sameValue(current.decisions.slice(0, packet.decisions.length).map(decisionIdentity), packet.decisions.map(decisionIdentity)) || current.decisions.length !== packet.decisions.length + (action === 'execute' ? 0 : 1)) throw invalid();
  if (action === 'execute') {
    const effect = packet.review_manifest.effect, factKind = packet.action === 'document.clause.apply.v1' ? 'clause_application' : packet.action === 'document.lifecycle.v1' ? 'lifecycle' : 'adoption';
    const fact = (result as unknown as { effect: Record<string, D.DcAdoption | D.DcClauseApplication | D.DcLifecycle> }).effect[factKind];
    if (!fact || !scoped(fact, command.payload) || !authored(fact, actor) || actor.personId !== packet.requester.id || fact.subject_id !== packet.subject.id || fact.subject_digest !== packet.source_version || fact.packet_id !== packet.id || fact.effect_digest !== await engineeringDigest(effect) || !sameValue(fact.artifacts, effect.artifacts) || !packet.decisions.some(decision => decision.id === fact.decision_id && decision.actor.id === fact.checked_by_person && decision.actor.id !== packet.requester.id && decision.decision === 'Grant') || current.state !== 'Consumed') throw invalid();
    if (packet.action === 'document.lifecycle.v1') {
      const f = fact as D.DcLifecycle, e = packet.review_manifest.effect, previous = e.before.last_event;
      if (f.parent_id !== e.document_id || f.document_id !== e.document_id || f.predecessor !== (previous?.id || null) || f.revision_number !== (previousLifecycle?.revision_number || 0) + 1 || f.action !== e.definition.action || f.reason !== e.definition.reason || f.status !== (e.definition.action === 'withdraw' ? 'withdrawn' : 'superseded') || !sameValue(f.before, e.before) || !sameValue(f.replacement, e.replacement)) throw invalid();
    } else if (fact.parent_id !== packet.subject.id) throw invalid();
    if (packet.action === 'document.clause.apply.v1') {
      const f = fact as D.DcClauseApplication, e = packet.review_manifest.effect;
      if (!['target', 'target_snapshot', 'original_text', 'proposed_text', 'proposed_sha256', 'target_changed'].every(key => sameValue(f[key as keyof D.DcClauseApplication], e[key as keyof typeof e]))) throw invalid();
    }
  } else if (current.state !== (action === 'withdraw' ? 'Withdrawn' : action === 'Grant' ? 'Granted' : 'Rejected') || current.decisions.at(-1)?.actor.id !== actor.personId || current.decisions.at(-1)?.decision !== (action === 'withdraw' ? 'Withdraw' : action) || current.decisions.at(-1)?.reason !== reason || (action === 'withdraw' ? actor.personId !== packet.requester.id : actor.personId === packet.requester.id)) throw invalid();
  return result as NextDocumentReply;
}

export const documentControlNext = {
  async get(scope: Scope, kind: NextDocumentKind, id: string, signal?: AbortSignal) { return validateNextDocumentRecord(await rpc<D.DcGetResponse>(projectPrefix + 'get_record', { ...scope, kind, record_id: id }, false, signal), scope, kind, id); },
  async list(scope: Scope, kind: NextDocumentKind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const result = await rpc<D.DcListResponse>(projectPrefix + 'list_records', { ...scope, kind, parent_id, cursor, limit: 25, count_mode: 'none' }, false, signal);
    if (!shape('DcListResponse', result) || result.limit !== 25 || result.items.length > 25 || result.count_mode !== 'none' || result.total !== null || cursor && result.next_cursor === cursor || new Set(result.items.map(row => row.record.id)).size !== result.items.length) throw invalid();
    await Promise.all(result.items.map(row => validateNextDocumentRecord(row, scope, kind, undefined, parent_id))); return result;
  },
  async companyGet(company: string, kind: CompanyDocumentKind, id: string, signal?: AbortSignal) { return validateCompanyDocumentRecord(await rpc<D.DcCompanyGetResponse>(companyPrefix + 'get_record', { company, kind, record_id: id }, false, signal), company, kind, id); },
  async companyList(company: string, kind: CompanyDocumentKind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const result = await rpc<D.DcCompanyListResponse>(companyPrefix + 'list_records', { company, kind, parent_id, cursor, limit: 25, count_mode: 'none' }, false, signal);
    if (!shape('DcCompanyListResponse', result) || result.limit !== 25 || result.items.length > 25 || result.count_mode !== 'none' || result.total !== null || cursor && result.next_cursor === cursor || new Set(result.items.map(row => row.record.id)).size !== result.items.length) throw invalid();
    await Promise.all(result.items.map(row => validateCompanyDocumentRecord(row, company, kind, undefined, parent_id))); return result;
  },
  async standing(scope: Scope, documentId: string, signal?: AbortSignal) { return validateIssuedStanding(await rpc<D.DcIssuedStandingResponse>(projectPrefix + 'issued_standing', { ...scope, document_id: documentId }, false, signal), scope, documentId); },
  async readClauseTarget(scope: Scope, kind: D.DcClauseTargetKind, id: string, signal?: AbortSignal) {
    const result = await rpc<D.DcClauseTargetResponse>(projectPrefix + 'read_clause_target', { ...scope, kind, record_id: id }, false, signal);
    if (!shape('DcClauseTargetResponse', result) || !targetMatches(result.target, scope, kind, id)) throw invalid(); return result;
  },
  async packet(scope: Scope, id: string, signal?: AbortSignal) { return validateNextDocumentPacket(await api.approval(scope.company, scope.project, id, signal) as NextDocumentPacket, scope, id); },
  async send(command: NextDocumentCommand & { operation_id: string }, actor: Actor): Promise<NextDocumentReply> {
    if (command.kind === 'request_authorization' || command.kind === 'authorization_action') return sendApproval(command, actor);
    const [requestDefinition] = commands[command.kind], input = { ...command.payload, operation_id: command.operation_id };
    if (!shape(requestDefinition, input)) throw inputError();
    await preflight(command);
    const method = command.kind.startsWith('company_') ? companyPrefix + command.kind.slice(8) : projectPrefix + command.kind;
    return validateAuthored(command, await rpc<NextDocumentReply>(method, input, true), actor);
  },
};
