import schema from '../../../platform/apps/cipher_aec/cipher_aec/document_control/schemas/api-v1.schema.json' with { type: 'json' };
import coreSchema from '../../../platform/apps/cipher_aec/cipher_aec/api/schema.json' with { type: 'json' };
import { api, ApiError, rpc } from './client';
import { engineeringDigest, type Actor, type Scope } from './engineering';
import { sameValue, schemaShape } from './schema-validation';
import type * as D from './document-control.generated';
import type { ApprovalCommandResponse, DocumentIssueSetApprovalPacket, DocumentAdoptionRequestApprovalPacket, DocumentTransmittalApprovalPacket, DocumentApprovalExecutionResponse } from './contracts.generated';

export type DocumentKind = D.DcGetRecordRequest['kind'];
export type DocumentPacket = DocumentIssueSetApprovalPacket | DocumentAdoptionRequestApprovalPacket | DocumentTransmittalApprovalPacket;
export type DocumentSubjectKind = 'issue_set' | 'adoption_request' | 'transmittal';
export const documentAction = { issue_set: 'document.issue.v1', adoption_request: 'document.library.adopt.v1', transmittal: 'document.transmit.v1' } as const;
const subjectTypes = { issue_set: 'Cipher Document Issue Set', adoption_request: 'Cipher Adoption Request', transmittal: 'Cipher Transmittal' } as const;
const defs: Record<DocumentKind, string> = { rights: 'DcRights', library: 'DcLibrary', library_revision: 'DcLibraryRevision', adoption_request: 'DcAdoptionRequest', adoption: 'DcAdoption', issue_set: 'DcIssueSet', issue: 'DcIssue', transmittal: 'DcTransmittal', distribution: 'DcDistribution', evidence: 'DcEvidence' };
const prefix = 'cipher_aec.document_control.api.';
export const documentShape = (name: string, value: unknown) => schemaShape(schema, name, value);
export const invalidDocumentControl = () => new ApiError('This reply could not be matched to the exact Project, original document revisions and reviewed request.', 'INVALID_CONTRACT', 200);
const scoped = (value: D.DcRecord, scope: Scope) => value.scope_type === 'Project' && value.company === scope.company && value.project === scope.project;
const exactArtifacts = (actual: D.DcArtifact[], expected: D.DcArtifactInput[]) => actual.length === expected.length && actual.every((row, i) => row.revision_id === expected[i].revision_id && row.source_sha256 === expected[i].source_sha256);
const artifactInputs = (rows: D.DcArtifact[]) => rows.map(({ revision_id, source_sha256 }) => ({ revision_id, source_sha256 }));
export async function validateDocumentRecord(value: D.DcGetResponse, scope: Scope, kind: DocumentKind, id?: string, parent?: string) {
  if (!documentShape('DcGetResponse', value) || !documentShape(defs[kind], value.record) || !scoped(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || await engineeringDigest(value.record) !== value.record_digest) throw invalidDocumentControl();
  if (['library_revision', 'adoption_request', 'adoption'].includes(kind) ? typeof value.library_current !== 'boolean' : value.library_current !== null) throw invalidDocumentControl();
  if (kind === 'issue_set') { const record = value.record as D.DcIssueSet; if (record.package_digest !== await engineeringDigest({ definition: record.definition, artifacts: record.artifacts, adoptions: record.adoptions })) throw invalidDocumentControl(); }
  return value;
}
export function validateDocumentPacket(packet: DocumentPacket, scope: Scope, id?: string) {
  const definition = { 'document.issue.v1': 'DocumentIssueSetApprovalPacket', 'document.library.adopt.v1': 'DocumentAdoptionRequestApprovalPacket', 'document.transmit.v1': 'DocumentTransmittalApprovalPacket' }[packet?.action];
  if (!definition || !schemaShape(coreSchema, definition, packet) || packet.company !== scope.company || packet.project !== scope.project || id && packet.id !== id || packet.subject.id !== packet.review_manifest.subject.name || packet.subject.type !== packet.review_manifest.subject.doctype || packet.subject.label !== packet.review_manifest.subject.label || packet.review_manifest.effect.subject_id !== packet.subject.id || packet.review_manifest.effect.subject_digest !== packet.source_version || packet.review_manifest.effect.action !== packet.action) throw invalidDocumentControl();
  return packet;
}
export async function validateDocumentManifestSubject(packet: DocumentPacket, subject: D.DcGetResponse, kind: DocumentSubjectKind) {
  const scope = { company: subject.record.company, project: subject.record.project };
  await validateDocumentRecord(subject, scope, kind); validateDocumentPacket(packet, scope);
  const value = subject.record as D.DcIssueSet | D.DcAdoptionRequest | D.DcTransmittal;
  const effect = { schema: 'cipher.document.authorization.v1', action: documentAction[kind], subject_kind: kind, subject_id: value.id, subject_digest: subject.record_digest, artifacts: value.artifacts, no_effects: value.no_effects, electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false,
    ...(kind === 'transmittal' ? { package_digest: (value as D.DcTransmittal).package_digest, recipients: (value as D.DcTransmittal).recipients, channel: 'internal' } : kind === 'issue_set' ? { package_digest: (value as D.DcIssueSet).package_digest, adoptions: (value as D.DcIssueSet).adoptions } : { library_revision: (value as D.DcAdoptionRequest).library_revision, library_digest: (value as D.DcAdoptionRequest).library_digest, target_locator: (value as D.DcAdoptionRequest).definition.target_locator }) };
  const summary = { definition: 'definition' in value ? value.definition : null, purpose: 'purpose' in value ? value.purpose : null, required_response: 'required_response' in value ? value.required_response : null, no_effects: value.no_effects, rights_basis: 'authored-declaration', external_delivery: false, commercial_execution: false };
  const source = packet.review_manifest.sources[0], documentIds = [...new Set(value.artifacts.map(row => row.document_id))].sort();
  // The full authority-envelope hash remains opaque; only the domain is exposed for review.
  if (packet.action !== documentAction[kind] || packet.subject.type !== subjectTypes[kind] || packet.subject.id !== value.id || packet.source_version !== subject.record_digest || packet.requester.id !== value.author_person || !sameValue(packet.review_manifest.effect, effect) || !sameValue(packet.review_manifest.summary, summary) || !sameValue(source.artifacts, value.artifacts) || source.rights.length !== documentIds.length || source.rights.some((policy, i) => !scoped(policy, scope) || policy.parent_id !== documentIds[i])) throw invalidDocumentControl();
  return packet;
}
type Inputs = { set_rights: D.DcSetRightsRequest; create_library: D.DcCreateLibraryRequest; revise_library: D.DcReviseLibraryRequest; create_adoption: D.DcCreateAdoptionRequest; create_issue_set: D.DcCreateIssueSetRequest; create_transmittal: D.DcCreateTransmittalRequest; record_evidence: D.DcRecordEvidenceRequest };
type Outputs = { set_rights: D.DcSetRightsResponse; create_library: D.DcCreateLibraryResponse; revise_library: D.DcReviseLibraryResponse; create_adoption: D.DcCreateAdoptionResponse; create_issue_set: D.DcCreateIssueSetResponse; create_transmittal: D.DcCreateTransmittalResponse; record_evidence: D.DcRecordEvidenceResponse };
const commandDefs: { [K in keyof Inputs]: [string, string, DocumentKind] } = { set_rights: ['DcSetRightsRequest', 'DcSetRightsResponse', 'rights'], create_library: ['DcCreateLibraryRequest', 'DcCreateLibraryResponse', 'library_revision'], revise_library: ['DcReviseLibraryRequest', 'DcReviseLibraryResponse', 'library_revision'], create_adoption: ['DcCreateAdoptionRequest', 'DcCreateAdoptionResponse', 'adoption_request'], create_issue_set: ['DcCreateIssueSetRequest', 'DcCreateIssueSetResponse', 'issue_set'], create_transmittal: ['DcCreateTransmittalRequest', 'DcCreateTransmittalResponse', 'transmittal'], record_evidence: ['DcRecordEvidenceRequest', 'DcRecordEvidenceResponse', 'evidence'] };
export type DocumentBasis = { original?: D.DcGetResponse; artifacts?: D.DcArtifact[]; recipients?: D.DcPerson[] };
export type DocumentCommand = { [K in keyof Inputs]: { kind: K; payload: Omit<Inputs[K], 'operation_id'>; basis?: DocumentBasis } }[keyof Inputs] | { kind: 'request_authorization'; payload: Scope; subject: D.DcGetResponse; subjectKind: DocumentSubjectKind } | { kind: 'authorization_action'; payload: Scope; packet: DocumentPacket; action: 'Grant' | 'Reject' | 'execute' | 'withdraw'; reason: string };
export type DocumentReply = Outputs[keyof Outputs] | ApprovalCommandResponse | DocumentApprovalExecutionResponse;
export const documentControl = {
  async get(scope: Scope, kind: DocumentKind, id: string, signal?: AbortSignal) { return validateDocumentRecord(await rpc<D.DcGetResponse>(prefix + 'get_record', { ...scope, kind, record_id: id }, false, signal), scope, kind, id); },
  async list(scope: Scope, kind: DocumentKind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const value = await rpc<D.DcListResponse>(prefix + 'list_records', { ...scope, kind, parent_id, cursor, limit: 25, count_mode: 'none' }, false, signal);
    if (!documentShape('DcListResponse', value) || value.limit !== 25 || value.items.length > 25 || cursor && value.next_cursor === cursor || new Set(value.items.map(row => row.record.id)).size !== value.items.length) throw invalidDocumentControl();
    await Promise.all(value.items.map(row => validateDocumentRecord(row, scope, kind, undefined, parent_id))); return value;
  },
  async people(scope: Scope, cursor?: string, signal?: AbortSignal) { const value = await rpc<D.DcPeopleResponse>(prefix + 'list_people', { ...scope, cursor, limit: 25, count_mode: 'none' }, false, signal); if (!documentShape('DcPeopleResponse', value) || value.limit !== 25 || value.items.length > 25 || cursor && value.next_cursor === cursor || new Set(value.items.map(row => row.user)).size !== value.items.length) throw invalidDocumentControl(); return value; },
  async packet(scope: Scope, id: string, signal?: AbortSignal) { return validateDocumentPacket(await api.approval(scope.company, scope.project, id, signal) as DocumentPacket, scope, id); },
  async send(command: DocumentCommand & { operation_id: string }, actor: Actor): Promise<DocumentReply> {
    if (command.kind === 'request_authorization') {
      const result = await rpc<ApprovalCommandResponse>('cipher_aec.api.approvals.request_action', { ...command.payload, action: documentAction[command.subjectKind], subject_id: command.subject.record.id, expected_version: command.subject.record_digest, operation_id: command.operation_id }, true);
      if (!schemaShape(coreSchema, 'ApprovalCommandResponse', result)) throw invalidDocumentControl();
      await validateDocumentManifestSubject(result.packet as DocumentPacket, command.subject, command.subjectKind);
      if (result.packet.requester.id !== actor.personId) throw invalidDocumentControl(); return result;
    }
    if (command.kind === 'authorization_action') {
      const { packet, action } = command; validateDocumentPacket(packet, command.payload);
      const result = await api.approvalAction(action, { ...command.payload, packet_id: packet.id, manifest_hash: packet.manifest_hash, reason: command.reason, operation_id: command.operation_id });
      if (!schemaShape(coreSchema, action === 'execute' ? 'DocumentApprovalExecutionResponse' : 'ApprovalCommandResponse', result)) throw invalidDocumentControl();
      const current = validateDocumentPacket(result.packet as DocumentPacket, command.payload, packet.id);
      const decisionIdentity = (row: DocumentPacket['decisions'][number]) => ({ id: row.id, actor_person: row.actor.id, decision: row.decision, at: row.at, reason: row.reason });
      // Display names are current labels; original canonical people and recorded decisions cannot change.
      if (current.manifest_hash !== packet.manifest_hash || current.requester.id !== packet.requester.id || current.created_at !== packet.created_at || current.expires_at !== packet.expires_at || current.policy.id !== packet.policy.id || !sameValue(current.review_manifest, packet.review_manifest) || !sameValue(current.decisions.slice(0, packet.decisions.length).map(decisionIdentity), packet.decisions.map(decisionIdentity)) || current.decisions.length !== packet.decisions.length + (action === 'Grant' || action === 'Reject' ? 1 : 0)) throw invalidDocumentControl();
      if (action === 'execute') {
        const factKind = { 'document.issue.v1': 'issue', 'document.library.adopt.v1': 'adoption', 'document.transmit.v1': 'distribution' }[packet.action] as 'issue' | 'adoption' | 'distribution';
        const effect = packet.review_manifest.effect, fact = (result as unknown as { effect: Record<string, D.DcIssue | D.DcAdoption | D.DcDistribution> }).effect[factKind];
        if (!fact || !scoped(fact, command.payload) || fact.author_person !== actor.personId || fact.author_user !== actor.user || fact.parent_id !== packet.subject.id || fact.subject_id !== packet.subject.id || fact.subject_digest !== packet.source_version || fact.packet_id !== packet.id || fact.effect_digest !== await engineeringDigest(effect) || !sameValue(fact.artifacts, effect.artifacts) || !packet.decisions.some(row => row.id === fact.decision_id && row.actor.id === fact.checked_by_person && row.actor.id !== packet.requester.id && row.decision === 'Grant') || 'package_digest' in effect && (!('package_digest' in fact) || fact.package_digest !== effect.package_digest) || 'recipients' in effect && (!('recipients' in fact) || !sameValue(fact.recipients, effect.recipients) || fact.channel !== 'internal') || current.state !== 'Consumed') throw invalidDocumentControl();
      } else if (action === 'withdraw' ? current.state !== 'Withdrawn' : !current.decisions.some(row => row.actor.id === actor.personId && row.decision === action && row.reason === command.reason)) throw invalidDocumentControl();
      return result as DocumentReply;
    }
    const input = { ...command.payload, operation_id: command.operation_id } as Inputs[keyof Inputs], definition = commandDefs[command.kind];
    if (!documentShape(definition[0], input)) throw new ApiError('Complete the fields and exact original document selections before saving.', 'document_control_input', 422);
    const result = await rpc<Outputs[keyof Outputs]>(prefix + command.kind, input as unknown as Record<string, unknown>, true);
    if (!documentShape(definition[1], result) || result.operation.id !== command.operation_id) throw invalidDocumentControl();
    const records = result as unknown as Record<string, D.DcRecord>, value = records[definition[2]];
    if (!value || !scoped(value, input) || value.author_person !== actor.personId || value.author_user !== actor.user) throw invalidDocumentControl();
    const original = command.basis?.original;
    if (command.kind === 'set_rights') {
      const r = value as D.DcRights, p = command.payload;
      const { evidence_artifact, ...fields } = p.definition;
      if (!Object.entries(fields).every(([k, field]) => sameValue(r[k as keyof D.DcRights], field)) || !exactArtifacts([r.evidence_artifact], [evidence_artifact]) || !sameValue([r.evidence_artifact], command.basis?.artifacts) || r.evidence_artifact.document_id === p.document_id || r.parent_id !== p.document_id || r.predecessor !== (original?.record.id || null) || r.revision_number !== (original && 'revision_number' in original.record ? original.record.revision_number + 1 : 1) || p.expected_version !== (original?.record_digest || null)) throw invalidDocumentControl();
    } else if (command.kind === 'create_library' || command.kind === 'revise_library') {
      const r = value as D.DcLibraryRevision, h = records.library as D.DcLibrary, p = command.payload;
      if (!scoped(h, input) || r.parent_id !== h.id || h.current_revision !== r.id || h.revision_number !== r.revision_number || !sameValue(r.definition, p.definition) || !exactArtifacts(r.artifacts, [p.artifact]) || !sameValue(r.artifacts, command.basis?.artifacts)) throw invalidDocumentControl();
      if (command.kind === 'create_library') { if (h.author_person !== actor.personId || h.author_user !== actor.user || h.revision_number !== 1 || r.predecessor !== null) throw invalidDocumentControl(); }
      else { const old = original?.record as D.DcLibrary | undefined; if (!old || command.payload.library_id !== old.id || command.payload.expected_version !== original!.record_digest || !sameValue(h, { ...old, current_revision: r.id, revision_number: old.revision_number + 1 }) || r.predecessor !== old.current_revision) throw invalidDocumentControl(); }
    } else if (command.kind === 'create_adoption') {
      const r = value as D.DcAdoptionRequest, p = command.payload, old = original?.record as D.DcLibraryRevision | undefined;
      if (!old || old.id !== p.library_revision || original!.record_digest !== p.library_digest || r.parent_id !== old.parent_id || r.library_revision !== p.library_revision || r.library_digest !== p.library_digest || !sameValue(r.artifacts, old.artifacts) || !sameValue(r.definition, p.definition)) throw invalidDocumentControl();
    } else if (command.kind === 'create_issue_set') {
      const r = value as D.DcIssueSet, p = command.payload;
      if (!command.basis?.artifacts || !sameValue(r.definition, p.definition) || !sameValue(r.adoptions, p.adoptions) || !sameValue(r.artifacts, command.basis.artifacts) || r.package_digest !== await engineeringDigest({ definition: r.definition, artifacts: r.artifacts, adoptions: r.adoptions })) throw invalidDocumentControl();
    } else if (command.kind === 'create_transmittal') {
      const r = value as D.DcTransmittal, p = command.payload, old = original?.record as D.DcIssue | undefined;
      if (!old || old.id !== p.issue_id || original!.record_digest !== p.issue_digest || r.parent_id !== old.id || r.issue_id !== old.id || r.issue_digest !== p.issue_digest || r.package_digest !== old.package_digest || !sameValue(r.artifacts, old.artifacts) || !command.basis?.recipients || !sameValue(r.recipients, command.basis.recipients) || !sameValue(r.recipients.map(row => row.user), p.recipients) || r.purpose !== p.purpose || r.required_response !== p.required_response) throw invalidDocumentControl();
    } else {
      const r = value as D.DcEvidence, p = command.payload;
      if (!original || original.record.id !== p.subject_id || original.record_digest !== p.subject_digest || r.parent_id !== p.subject_id || r.subject_kind !== p.subject_kind || r.subject_id !== p.subject_id || r.subject_digest !== p.subject_digest || r.statement !== p.statement || r.status !== (p.subject_kind === 'distribution' ? 'reported_received' : 'reported_execution') || !exactArtifacts(r.artifacts, p.artifacts) || !sameValue(r.artifacts, command.basis?.artifacts)) throw invalidDocumentControl();
    }
    return result;
  }
};
export { artifactInputs };
