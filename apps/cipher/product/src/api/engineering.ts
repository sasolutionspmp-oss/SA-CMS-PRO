import engineeringSchema from '../../../platform/apps/cipher_aec/cipher_aec/engineering/schemas/api-v1.schema.json' with { type: 'json' };
import coreSchema from '../../../platform/apps/cipher_aec/cipher_aec/api/schema.json' with { type: 'json' };
import { api, ApiError, rpc } from './client';
import { sameValue, schemaShape } from './schema-validation';
import type * as E from './engineering.generated';
import type { EngineeringApprovalPacket, EngineeringApprovalExecutionResponse, ApprovalCommandResponse } from './contracts.generated';
export type Scope = { company: string; project: string };
export type Actor = { user: string; personId: string };
export type Kind = E.EgGetRecordRequest['kind'];
export type EngineeringAction = EngineeringApprovalPacket['action'];
export const actionFor = { response: 'engineering.rfi.authorize.v1', disposition: 'engineering.submittal.authorize.v1', transmittal: 'engineering.distribute.v1' } as const;
const definitions: Record<Kind, string> = { rfi: 'EgRfi', rfi_revision: 'EgRfiRevision', response: 'EgResponse', official_response: 'EgOfficialResponse', submittal: 'EgSubmittal', submission: 'EgSubmission', disposition: 'EgDisposition', official_disposition: 'EgOfficialDisposition', transmittal: 'EgTransmittal', distribution: 'EgDistribution' };
const prefix = 'cipher_aec.engineering.api.';
export const invalidEngineering = () => new ApiError('The engineering response could not be matched to the selected project, revision and original request.', 'INVALID_CONTRACT', 200);
export const engineeringShape = (name: string, value: unknown) => schemaShape(engineeringSchema, name, value);
export const inScope = (record: E.EgRecord, scope: Scope) => record.company === scope.company && record.project === scope.project && record.scope_type === 'Project';
const canonical = (value: unknown): string => Array.isArray(value) ? '[' + value.map(canonical).join(',') + ']' : value && typeof value === 'object' ? '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical((value as Record<string, unknown>)[key])).join(',') + '}' : JSON.stringify(value);
export async function engineeringDigest(value: unknown): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(value))))].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
export async function validateEngineeringRecord(value: E.EgGetResponse, scope: Scope, kind: Kind, id?: string, parent?: string | null) {
  if (!engineeringShape('EgGetResponse', value) || !engineeringShape(definitions[kind], value.record) || !inScope(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || await engineeringDigest(value.record) !== value.record_digest) throw invalidEngineering();
  return value;
}
export async function validateEngineeringPage(value: E.EgListResponse, input: E.EgListRecordsRequest) {
  if (!engineeringShape('EgListResponse', value) || value.limit !== 25 || value.items.length > 25 || value.total !== null || value.count_mode !== 'none' || input.cursor && input.cursor === value.next_cursor || new Set(value.items.map(item => item.record.id)).size !== value.items.length) throw invalidEngineering();
  await Promise.all(value.items.map(item => validateEngineeringRecord(item, input, input.kind, undefined, input.parent_id).then(row => { if (input.subject_id && (!('subject_id' in row.record) || row.record.subject_id !== input.subject_id)) throw invalidEngineering(); return row; })));
  return value;
}
type Requests = { create_rfi: E.EgCreateRfiRequest; revise_rfi: E.EgReviseRfiRequest; create_response: E.EgCreateResponseRequest; create_submittal: E.EgCreateSubmittalRequest; revise_submission: E.EgReviseSubmissionRequest; create_disposition: E.EgCreateDispositionRequest; create_transmittal: E.EgCreateTransmittalRequest; close_rfi: E.EgCloseRfiRequest };
type Replies = { create_rfi: E.EgCreateRfiResponse; revise_rfi: E.EgReviseRfiResponse; create_response: E.EgCreateResponseResponse; create_submittal: E.EgCreateSubmittalResponse; revise_submission: E.EgReviseSubmissionResponse; create_disposition: E.EgCreateDispositionResponse; create_transmittal: E.EgCreateTransmittalResponse; close_rfi: E.EgCloseRfiResponse };
const commandDefs: { [K in keyof Requests]: [string, string] } = { create_rfi: ['EgCreateRfiRequest', 'EgCreateRfiResponse'], revise_rfi: ['EgReviseRfiRequest', 'EgReviseRfiResponse'], create_response: ['EgCreateResponseRequest', 'EgCreateResponseResponse'], create_submittal: ['EgCreateSubmittalRequest', 'EgCreateSubmittalResponse'], revise_submission: ['EgReviseSubmissionRequest', 'EgReviseSubmissionResponse'], create_disposition: ['EgCreateDispositionRequest', 'EgCreateDispositionResponse'], create_transmittal: ['EgCreateTransmittalRequest', 'EgCreateTransmittalResponse'], close_rfi: ['EgCloseRfiRequest', 'EgCloseRfiResponse'] };
export type EngineeringBasis = { header?: E.EgRfi | E.EgSubmittal; header_digest?: string; source?: { id: string; record_digest: string }; proposed?: { id: string; revision_number: number }; subject?: E.EgGetResponse };
export type AuthorCommand = ({ [K in keyof Requests]: { kind: K; payload: Omit<Requests[K], 'operation_id'> } }[keyof Requests]) & { basis?: EngineeringBasis };
export type RequestApprovalCommand = { kind: 'request_approval'; payload: Scope & { action: EngineeringAction; subject_id: string; expected_version: string }; basis: EngineeringBasis };
export type DecideCommand = { kind: 'approval_action'; payload: Scope & { action: 'Grant' | 'Reject' | 'execute' | 'withdraw'; packet: EngineeringApprovalPacket; reason: string } };
export type EngineeringCommand = AuthorCommand | RequestApprovalCommand | DecideCommand;
export type EngineeringReply = Replies[keyof Replies] | ApprovalCommandResponse | EngineeringApprovalExecutionResponse;
const sameProjected = (actual: object[], expected: object[]) => actual.length === expected.length && actual.every((row, index) => Object.entries(expected[index]).every(([key, value]) => sameValue((row as Record<string, unknown>)[key], value)));
export function validateAuthoredReply(kind: keyof Requests, input: Requests[keyof Requests], value: Replies[keyof Replies], actor: Actor, basis?: EngineeringBasis) {
  if (!engineeringShape(commandDefs[kind][1], value) || value.operation.id !== input.operation_id || value.operation.status !== 'succeeded') throw invalidEngineering();
  const body = value as unknown as Record<string, E.EgRecord>;
  for (const [key, record] of Object.entries(body)) if (!['operation', 'history_id'].includes(key) && !inScope(record, input)) throw invalidEngineering();
  const a = input as unknown as Record<string, unknown>;
  const r = (body.revision || body.response || body.submission || body.disposition || body.transmittal) as E.EgRfiRevision | E.EgResponse | E.EgSubmission | E.EgDisposition | E.EgTransmittal | undefined;
  if (r && (r.author_user !== actor.user || r.author_person !== actor.personId)) throw invalidEngineering();
  if (r && 'definition' in r && !sameValue(r.definition, a.definition)) throw invalidEngineering();
  if (r && 'source_citations' in a && !sameProjected(r.source_citations, a.source_citations as object[])) throw invalidEngineering();
  if (r && 'drawing_references' in a && !sameProjected(r.drawing_references, a.drawing_references as object[])) throw invalidEngineering();
  if (r && 'artifacts' in a && !sameProjected(r.artifacts, a.artifacts as object[])) throw invalidEngineering();
  if (body.rfi) {
    const header = body.rfi as E.EgRfi;
    if (a.rfi_id && header.id !== a.rfi_id || r && 'parent_id' in r && r.parent_id !== header.id || body.revision && header.current_revision !== body.revision.id || body.response && header.response_head !== body.response.id) throw invalidEngineering();
    if (kind === 'close_rfi' && (header.status !== 'closed' || header.official_response !== a.official_response || header.closure?.reason !== a.reason || header.closure?.person !== actor.personId)) throw invalidEngineering();
  }
  if (body.submittal) {
    const header = body.submittal as E.EgSubmittal;
    if (a.submittal_id && header.id !== a.submittal_id || r && 'parent_id' in r && r.parent_id !== header.id || body.submission && header.current_submission !== body.submission.id || body.disposition && header.disposition_head !== body.disposition.id) throw invalidEngineering();
  }
  if (r && 'source_revision' in r && r.source_revision !== a.source_revision || r && 'predecessor' in r && ['create_response', 'create_disposition'].includes(kind) && r.predecessor !== (a.predecessor ?? null)) throw invalidEngineering();
  if (['create_rfi', 'create_submittal'].includes(kind)) {
    const header = (body.rfi || body.submittal) as E.EgRfi | E.EgSubmittal;
    if (header.author_person !== actor.personId || header.author_user !== actor.user || !r || !('predecessor' in r) || r.predecessor !== null || r.revision_number !== 1) throw invalidEngineering();
  }
  if (['revise_rfi', 'revise_submission', 'create_response', 'create_disposition', 'close_rfi'].includes(kind)) {
    const original = basis?.header, header = (body.rfi || body.submittal) as E.EgRfi | E.EgSubmittal;
    if (!original || basis?.header_digest !== a.expected_version || original.id !== header.id || original.author_person !== header.author_person || original.author_user !== header.author_user || original.created_at !== header.created_at || original.number !== header.number) throw invalidEngineering();
    if (kind === 'revise_rfi' || kind === 'revise_submission') {
      const previous = 'current_revision' in original ? original.current_revision : original.current_submission;
      if (!r || !('predecessor' in r) || r.predecessor !== previous || r.revision_number !== original.revision_number + 1) throw invalidEngineering();
    } else if (kind === 'create_response' || kind === 'create_disposition') {
      if (!r || !('source_revision' in r) || !basis?.source || r.source_revision !== basis.source.id || r.source_digest !== basis.source.record_digest || r.revision_number !== (basis.proposed?.revision_number || 0) + 1 || r.predecessor !== (basis.proposed?.id || null) || header.revision_number !== original.revision_number) throw invalidEngineering();
      if ('current_revision' in original && (!('current_revision' in header) || header.current_revision !== original.current_revision || header.official_response !== original.official_response) || 'current_submission' in original && (!('current_submission' in header) || header.current_submission !== original.current_submission || header.official_disposition !== original.official_disposition)) throw invalidEngineering();
    } else {
      const { closure: _closure, status: _status, ...actual } = header as E.EgRfi;
      const { closure: _oldClosure, status: _oldStatus, ...prior } = original as E.EgRfi;
      if (!sameValue(actual, prior)) throw invalidEngineering();
    }
  }
  if (body.transmittal) {
    const t = body.transmittal as E.EgTransmittal;
    if (!basis?.subject || basis.subject.record.id !== a.subject_id || basis.subject.record_digest !== a.subject_digest || t.subject.kind !== a.subject_kind || t.subject.id !== a.subject_id || t.subject_digest !== a.subject_digest || t.purpose !== a.purpose || t.required_response !== a.required_response || !sameValue(t.recipients.map(person => person.user), a.recipients)) throw invalidEngineering();
  }
  return value;
}
export function validateEngineeringPacket(packet: EngineeringApprovalPacket, scope: Scope, id?: string) {
  if (!schemaShape(coreSchema, 'EngineeringApprovalPacket', packet) || packet.company !== scope.company || packet.project !== scope.project || id && packet.id !== id || packet.review_manifest.subject.name !== packet.subject.id || packet.review_manifest.subject.doctype !== packet.subject.type || packet.review_manifest.effect.action !== packet.action || packet.review_manifest.effect.subject_id !== packet.subject.id || packet.review_manifest.effect.subject_digest !== packet.source_version) throw invalidEngineering();
  return packet;
}
export const engineering = {
  async people(scope: Scope, cursor?: string, signal?: AbortSignal) {
    const result = await rpc<E.EgPeopleResponse>(prefix + 'list_people', { ...scope, limit: 25, count_mode: 'none', cursor }, false, signal);
    if (!engineeringShape('EgPeopleResponse', result) || result.limit !== 25 || cursor && result.next_cursor === cursor || new Set(result.items.map(item => item.user)).size !== result.items.length) throw invalidEngineering();
    return result;
  },
  async get(scope: Scope, kind: Kind, id: string, signal?: AbortSignal) { return validateEngineeringRecord(await rpc<E.EgGetResponse>(prefix + 'get_record', { ...scope, kind, record_id: id }, false, signal), scope, kind, id); },
  async list(scope: Scope, kind: Kind, parent_id?: string, cursor?: string, signal?: AbortSignal, subject_id?: string) { const input = { ...scope, kind, parent_id, subject_id, cursor, limit: 25, count_mode: 'none' as const }; return validateEngineeringPage(await rpc<E.EgListResponse>(prefix + 'list_records', input, false, signal), input); },
  async packet(scope: Scope, id: string, signal?: AbortSignal) { return validateEngineeringPacket(await api.approval(scope.company, scope.project, id, signal) as EngineeringApprovalPacket, scope, id); },
  async send(command: EngineeringCommand & { operation_id: string }, actor: Actor): Promise<EngineeringReply> {
    const p = command.payload;
    if (command.kind === 'request_approval') {
      const result = await rpc<ApprovalCommandResponse>('cipher_aec.api.approvals.request_action', { ...p, operation_id: command.operation_id }, true);
      if (!schemaShape(coreSchema, 'ApprovalCommandResponse', result)) throw invalidEngineering();
      const packet = validateEngineeringPacket(result.packet as EngineeringApprovalPacket, p);
      const expected = command.payload;
      if (packet.action !== expected.action || packet.subject.id !== expected.subject_id || packet.source_version !== expected.expected_version || packet.requester.id !== actor.personId) throw invalidEngineering();
      const subject = command.basis.subject?.record;
      if (!subject || command.basis.subject?.record_digest !== expected.expected_version || subject.id !== expected.subject_id) throw invalidEngineering();
      if ('definition' in subject && !sameValue(subject.definition, packet.review_manifest.summary.definition) || 'purpose' in subject && subject.purpose !== packet.review_manifest.summary.purpose) throw invalidEngineering();
      if ('source_revision' in subject && (!('source_revision' in packet.review_manifest.effect) || packet.review_manifest.effect.source_revision !== subject.source_revision || packet.review_manifest.effect.source_digest !== subject.source_digest || packet.review_manifest.effect.parent_id !== subject.parent_id)) throw invalidEngineering();
      if ('package_digest' in subject && (!('package_digest' in packet.review_manifest.effect) || subject.package_digest !== packet.review_manifest.effect.package_digest || !sameValue(subject.recipients, packet.review_manifest.effect.recipients) || subject.channel !== packet.review_manifest.effect.channel)) throw invalidEngineering();
      return result;
    }
    if (command.kind === 'approval_action') {
      const { packet, action, reason, ...scope } = command.payload;
      const result = await api.approvalAction(action, { ...scope, packet_id: packet.id, manifest_hash: packet.manifest_hash, reason, operation_id: command.operation_id });
      if (!schemaShape(coreSchema, action === 'execute' ? 'EngineeringApprovalExecutionResponse' : 'ApprovalCommandResponse', result)) throw invalidEngineering();
      const current = validateEngineeringPacket(result.packet as EngineeringApprovalPacket, scope, packet.id);
      if (current.manifest_hash !== packet.manifest_hash || current.action !== packet.action || current.source_version !== packet.source_version || !sameValue(current.review_manifest, packet.review_manifest)) throw invalidEngineering();
      if (action === 'execute') {
        const effect = (result as EngineeringApprovalExecutionResponse).effect;
        const fact = Object.values(effect)[0];
        if (!inScope(fact, scope) || fact.packet_id !== packet.id || fact.subject_id !== packet.subject.id || fact.subject_digest !== packet.source_version || fact.author_person !== actor.personId || fact.author_user !== actor.user || !packet.decisions.some(decision => decision.id === fact.decision_id && decision.actor.id === fact.checked_by_person && decision.decision === 'Grant')) throw invalidEngineering();
        const expected = packet.review_manifest.effect;
        if ('package_digest' in expected) {
          if (!('package_digest' in fact) || fact.package_digest !== expected.package_digest || !sameValue(fact.recipients, expected.recipients) || fact.channel !== expected.channel || fact.external_delivery !== false) throw invalidEngineering();
        } else if (!('parent_id' in fact) || fact.parent_id !== expected.parent_id || fact.source_revision !== expected.source_revision || fact.source_digest !== expected.source_digest) throw invalidEngineering();
        if (current.state !== 'Consumed') throw invalidEngineering();
      } else if (action !== 'withdraw' && !current.decisions.some(decision => decision.actor.id === actor.personId && decision.decision === action && decision.reason === reason)) throw invalidEngineering();
      return result as EngineeringReply;
    }
    const input = { ...command.payload, operation_id: command.operation_id } as Requests[keyof Requests];
    if (!engineeringShape(commandDefs[command.kind][0], input)) throw new ApiError('Complete the required engineering fields and source selections before saving.', 'engineering_input', 422);
    const result = await rpc<Replies[keyof Replies]>(prefix + command.kind, input as unknown as Record<string, unknown>, true);
    return validateAuthoredReply(command.kind, input, result, actor, command.basis);
  },
};
