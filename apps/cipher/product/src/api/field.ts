import { ApiError, rpc } from './client';
import { engineeringDigest, type Actor, type Scope } from './engineering';
import { sameValue } from './schema-validation';
import { fieldShape } from './field-validation';
import type * as F from './field.generated';
export { fieldShape } from './field-validation';
export type FieldFamily = F.FdCreateRecordRequest['family'];
export type FieldRevision = F.FdDailyRevision | F.FdTicketRevision;
export type FieldKind = F.FdKind;
export type FieldBasis = { header: F.FdGetResponse; revision: F.FdGetResponse };
export type FieldCommand =
  | { kind: 'create_record'; payload: Omit<F.FdCreateRecordRequest, 'operation_id'> }
  | { kind: 'revise_record'; payload: Omit<F.FdReviseRecordRequest, 'operation_id'>; basis: FieldBasis }
  | { kind: 'transition'; payload: Omit<F.FdTransitionRequest, 'operation_id'>; basis: FieldBasis };
export type FieldReply = F.FdCreateRecordResponse | F.FdReviseRecordResponse | F.FdTransitionResponse;
const prefix = 'cipher_aec.field.api.';
const definitions: Record<FieldKind, string> = { daily: 'FdDailyHeader', ticket: 'FdTicketHeader', daily_revision: 'FdDailyRevision', ticket_revision: 'FdTicketRevision', quantity: 'FdQuantity', decision: 'FdDecision' };
const contracts = { create_record: ['FdCreateRecordRequest', 'FdCreateRecordResponse'], revise_record: ['FdReviseRecordRequest', 'FdReviseRecordResponse'], transition: ['FdTransitionRequest', 'FdTransitionResponse'] } as const;
export const invalidField = () => new ApiError('The field reply could not be matched to the original project, revision and request. Recover the original request.', 'INVALID_CONTRACT', 200);
const scoped = (row: F.FdRecord, scope: Scope) => row.company === scope.company && row.project === scope.project && row.scope_type === 'Project';
export const fieldSourceInput = (source: F.FdSourceInput | F.FdCapturedSource): F.FdSourceInput => ({ revision_id: source.revision_id, source_sha256: source.source_sha256, page: source.page, locator: source.locator });
export function fieldInputProjection(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(fieldInputProjection);
  if (value && typeof value === 'object') {
    if ('revision_id' in value && 'source_sha256' in value && 'page' in value && 'locator' in value) return fieldSourceInput(value as F.FdCapturedSource);
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, fieldInputProjection(item)]));
  }
  return value;
}
export async function validateFieldRecord(value: F.FdGetResponse, scope: Scope, kind: FieldKind, id?: string, parent?: string) {
  if (!fieldShape('FdGetResponse', value) || !fieldShape(definitions[kind], value.record) || !scoped(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || await engineeringDigest(value.record) !== value.record_digest) throw invalidField();
  return value;
}
export async function validateFieldReply(command: FieldCommand & { operation_id: string }, value: FieldReply, actor: Actor) {
  const input = command.payload;
  if (!fieldShape(contracts[command.kind][1], value) || value.operation.id !== command.operation_id || value.operation.status !== 'succeeded' || value.family !== input.family || !scoped(value.header, input) || !scoped(value.revision, input)) throw invalidField();
  const header = value.header, revision = value.revision;
  if (!fieldShape(definitions[input.family], header) || !fieldShape(definitions[input.family === 'daily' ? 'daily_revision' : 'ticket_revision'], revision) || revision.parent_id !== header.id || header.current_revision !== revision.id || header.revision_number !== revision.revision_number) throw invalidField();
  if (command.kind === 'transition') {
    if (!('decision' in value)) throw invalidField();
    const old = command.basis.header.record as F.FdHeader, original = command.basis.revision.record as FieldRevision, decision = value.decision;
    const request = command.payload, target = { submit: 'submitted', review: 'reviewed', return: 'returned', accept: 'accepted', acknowledge: 'acknowledged' }[request.action];
    if (old.id !== request.record_id || command.basis.header.record_digest !== request.expected_version || original.id !== old.current_revision || original.parent_id !== old.id || !sameValue(revision, original) || !scoped(decision, input) || decision.author_person !== actor.personId || decision.author_user !== actor.user || decision.parent_id !== old.id || decision.source_revision !== original.id || decision.source_digest !== command.basis.revision.record_digest || decision.predecessor !== old.last_decision || decision.action !== request.action || decision.from_status !== old.status || decision.to_status !== target || decision.comment !== request.comment || decision.acknowledged_by !== (request.acknowledged_by || '') || !sameValue(fieldInputProjection(decision.evidence), request.evidence)) throw invalidField();
    if (request.action !== 'submit' && (original.author_person === actor.personId || 'superintendent' in original && original.superintendent.person === actor.personId)) throw invalidField();
    if (!sameValue(header, { ...old, status: target, last_decision: decision.id, accepted_revision: request.action === 'accept' ? original.id : old.accepted_revision })) throw invalidField();
    return value;
  }
  const capture = command.payload;
  if (!('quantities' in value) || revision.author_user !== actor.user || revision.author_person !== actor.personId || !sameValue(fieldInputProjection(revision.definition), capture.definition) || !sameValue(fieldInputProjection(revision.photos), capture.photos)) throw invalidField();
  if (capture.family === 'daily') {
    if (!('superintendent' in revision) || !('superintendent_user' in capture.definition) || revision.superintendent.user !== capture.definition.superintendent_user || !sameValue(revision.quantity_ids, value.quantities.map(row => row.id)) || value.quantities.length !== capture.quantities.length) throw invalidField();
    for (const [index, quantity] of value.quantities.entries()) if (!fieldShape('FdQuantity', quantity) || !scoped(quantity, capture) || quantity.author_person !== actor.personId || quantity.author_user !== actor.user || quantity.parent_id !== header.id || quantity.source_revision !== revision.id || quantity.revision_number !== revision.revision_number || !sameValue(fieldInputProjection(quantity.definition), capture.quantities[index]) || quantity.original_event_id !== quantity.definition.original_event_id || quantity.supersedes_event_id !== quantity.definition.supersedes_event_id) throw invalidField();
  } else if (value.quantities.length) throw invalidField();
  if (command.kind === 'create_record') {
    if (header.author_person !== actor.personId || header.author_user !== actor.user || header.revision_number !== 1 || header.status !== 'draft' || header.last_decision !== null || header.accepted_revision !== null || revision.predecessor !== null || revision.prior_decision !== null || revision.amendment_of !== null || revision.amendment_reason !== '') throw invalidField();
  } else {
    const request = command.payload, old = command.basis.header.record as F.FdHeader;
    if (command.basis.header.record_digest !== request.expected_version || old.id !== request.record_id || revision.predecessor !== old.current_revision || revision.prior_decision !== old.last_decision || revision.amendment_of !== old.accepted_revision || revision.amendment_reason !== (request.amendment_reason || '') || revision.revision_number !== old.revision_number + 1 || !sameValue(header, { ...old, current_revision: revision.id, revision_number: revision.revision_number, last_decision: null, status: 'draft' })) throw invalidField();
  }
  return value;
}
export const field = {
  async get(scope: Scope, kind: FieldKind, id: string, signal?: AbortSignal) { return validateFieldRecord(await rpc<F.FdGetResponse>(prefix + 'get_record', { ...scope, kind, record_id: id }, false, signal), scope, kind, id); },
  async list(scope: Scope, kind: FieldKind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const result = await rpc<F.FdListResponse>(prefix + 'list_records', { ...scope, kind, parent_id, cursor, limit: 25, count_mode: 'none' }, false, signal);
    if (!fieldShape('FdListResponse', result) || result.limit !== 25 || result.items.length > 25 || cursor && cursor === result.next_cursor || new Set(result.items.map(row => row.record.id)).size !== result.items.length) throw invalidField();
    await Promise.all(result.items.map(row => validateFieldRecord(row, scope, kind, undefined, parent_id)));
    return result;
  },
  async send(command: FieldCommand & { operation_id: string }, actor: Actor): Promise<FieldReply> {
    const payload = { ...command.payload, operation_id: command.operation_id };
    if (!fieldShape(contracts[command.kind][0], payload)) throw new ApiError('Complete the field record, exact quantities and stored source references before saving.', 'invalid_field_input', 422);
    return validateFieldReply(command, await rpc<FieldReply>(prefix + command.kind, payload, true), actor);
  },
};
