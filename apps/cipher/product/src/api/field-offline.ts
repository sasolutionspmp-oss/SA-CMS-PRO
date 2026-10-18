import schema from '../../../platform/apps/cipher_aec/cipher_aec/field_offline/schemas/api-v1.schema.json' with { type: 'json' };
import { ApiError, rpc } from './client';
import { engineeringDigest, type Actor, type Scope } from './engineering';
import { fieldInputProjection } from './field';
import { sameValue } from './schema-validation';
import type * as O from './field-offline.generated';

export type OfflineEnvelope = O.FoEnvelope;
export type OfflineReceipt = O.FoCreateRecordResponse;
export type OfflineActorContext = Scope & { actor: Actor; receiptActor?: Actor };
type Shape = Record<string, unknown>;
const object = (value: unknown): value is Shape => Boolean(value && typeof value === 'object' && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value)));
const keywords = new Set(['$ref', 'description', 'title', 'type', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'format', 'pattern', 'enum', 'const', 'oneOf', 'anyOf', 'allOf', 'not', 'if', 'then', 'else', 'uniqueItems', 'x-max-json-bytes']);
const typed = (value: unknown, type: string) => type === 'null' ? value === null : type === 'object' ? object(value) : type === 'array' ? Array.isArray(value) : type === 'integer' ? Number.isSafeInteger(value) : type === 'number' ? typeof value === 'number' && Number.isFinite(value) : ['string', 'boolean'].includes(type) && typeof value === type;
const canonical = (value: unknown): string => Array.isArray(value) ? '[' + value.map(canonical).join(',') + ']' : object(value) ? '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}' : JSON.stringify(value);
function timestamp(value: string): boolean {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!parts || Number(parts[1]) < 1 || Number(parts[4]) > 23 || Number(parts[5]) > 59 || Number(parts[6]) > 59 || parts[7] && (Number(parts[8]) > 23 || Number(parts[9]) > 59)) return false;
  const day = value.slice(0, 10), date = new Date(day + 'T00:00:00Z');
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === day && Number.isFinite(Date.parse(value));
}

// This evaluator owns only the unchanged FLD-02 schema. Unknown constraints fail
// closed; local validation never grants device, source, Person or write authority.
function shape(value: unknown, rule: Shape, defs: Record<string, Shape>, depth = 0): boolean {
  const match = (child: Shape) => shape(value, child, defs, depth + 1);
  if (depth > 64 || Object.keys(rule).some(key => !keywords.has(key))) return false;
  if (rule.$ref && (!String(rule.$ref).startsWith('#/$defs/') || !defs[String(rule.$ref).slice(8)] || !match(defs[String(rule.$ref).slice(8)]))) return false;
  if (rule.type && !(Array.isArray(rule.type) ? rule.type : [rule.type]).some(type => typed(value, String(type)))) return false;
  if (rule.allOf && !(rule.allOf as Shape[]).every(match) || rule.anyOf && !(rule.anyOf as Shape[]).some(match) || rule.oneOf && (rule.oneOf as Shape[]).filter(match).length !== 1 || rule.not && match(rule.not as Shape)) return false;
  if (rule.if && !match((match(rule.if as Shape) ? rule.then : rule.else) as Shape || {})) return false;
  if (Object.hasOwn(rule, 'const') && !sameValue(value, rule.const) || rule.enum && !(rule.enum as unknown[]).some(item => sameValue(value, item))) return false;
  if (object(value)) {
    const properties = (rule.properties || {}) as Record<string, Shape>;
    if ((rule.required as string[] || []).some(key => !Object.hasOwn(value, key))) return false;
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(properties, key)) { if (!shape(item, properties[key], defs, depth + 1)) return false; }
      else if (rule.additionalProperties === false || object(rule.additionalProperties) && !shape(item, rule.additionalProperties, defs, depth + 1)) return false;
    }
  }
  if (Array.isArray(value)) {
    if (typeof rule.minItems === 'number' && value.length < rule.minItems || typeof rule.maxItems === 'number' && value.length > rule.maxItems || object(rule.items) && !value.every(item => shape(item, rule.items as Shape, defs, depth + 1))) return false;
    if (rule.uniqueItems && value.some((item, index) => value.slice(0, index).some(prior => sameValue(item, prior)))) return false;
  }
  if (typeof value === 'string') {
    if (typeof rule.minLength === 'number' && [...value].length < rule.minLength || typeof rule.maxLength === 'number' && [...value].length > rule.maxLength || rule.pattern && !new RegExp(String(rule.pattern)).test(value)) return false;
    if (rule.format === 'date-time' && !timestamp(value)) return false;
    if (rule.format === 'date' && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0, 4)) < 1 || !Number.isFinite(Date.parse(value + 'T00:00:00Z')) || new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) !== value)) return false;
    if (rule.format === 'uuid' && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value)) return false;
    if (rule.format && !['uuid', 'date-time', 'date'].includes(String(rule.format))) return false;
  }
  return !(typeof value === 'number' && (typeof rule.minimum === 'number' && value < rule.minimum || typeof rule.maximum === 'number' && value > rule.maximum));
}

// Match the server's finite JSON admission before hashing or sending. No JSON
// coercion, sparse arrays, custom toJSON, cycles, invalid Unicode or credentials.
function boundedJson(value: unknown, maximumBytes?: number): boolean {
  const ancestors = new Set<object>(); let nodes = 0;
  const validText = (text: string) => !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(text);
  const visit = (item: unknown, depth: number): boolean => {
    if (++nodes > 20000 || depth > 32) return false;
    if (typeof item === 'string') return validText(item);
    if (item === null || typeof item === 'boolean') return true;
    if (typeof item === 'number') return Number.isFinite(item);
    if (!Array.isArray(item) && !object(item) || ancestors.has(item as object)) return false;
    const row = item as Shape | unknown[];
    if (Reflect.ownKeys(row).some(key => typeof key !== 'string' || key !== 'length' && !Object.getOwnPropertyDescriptor(row, key)?.enumerable || key !== 'length' && !('value' in Object.getOwnPropertyDescriptor(row, key)!))) return false;
    ancestors.add(row);
    let result: boolean;
    if (Array.isArray(row)) {
      const keys = Object.keys(row);
      result = row.length <= 20000 && keys.length === row.length && keys.every((key, index) => key === String(index));
      if (result) for (let index = 0; index < row.length; index++) if (!Object.hasOwn(row, index) || !visit(row[index], depth + 1)) { result = false; break; }
    } else result = Object.entries(row).every(([key, child]) => visit(key, depth + 1) && visit(child, depth + 1));
    ancestors.delete(row); return result;
  };
  try { return visit(value, 0) && (maximumBytes === undefined || new TextEncoder().encode(canonical(value)).byteLength <= maximumBytes); } catch { return false; }
}
export function offlineShape(name: string, value: unknown): boolean {
  const defs = schema.$defs as unknown as Record<string, Shape>;
  try { return Boolean(defs[name] && boundedJson(value, name === 'FoEnvelope' ? 262144 : undefined) && shape(value, defs[name], defs)); } catch { return false; }
}
export const invalidOffline = () => new ApiError('The offline response could not be matched to this Person, project and original capture. Inspect the original capture before another command.', 'INVALID_CONTRACT', 200);
const invalidInput = () => new ApiError('Keep the exact sealed capture, current Person and selected project. Complete the documentary fields before synchronizing.', 'invalid_field_offline', 422);
const scoped = (value: Scope, context: Scope) => value.company === context.company && value.project === context.project;
function contextValid(context: OfflineActorContext) {
  return [context.company, context.project, context.actor.personId, context.actor.user].every(value => typeof value === 'string' && Boolean(value.trim()) && !value.includes('\0')) && (!context.receiptActor || context.receiptActor.personId === context.actor.personId);
}
export function actorScopePerson(context: OfflineActorContext): string {
  if (!contextValid(context)) throw invalidInput();
  return JSON.stringify([context.company, context.project, context.actor.personId]);
}
export function validateOfflineEnvelope(envelope: unknown, context: OfflineActorContext): O.FoEnvelope {
  if (!contextValid(context) || !offlineShape('FoEnvelope', envelope)) throw invalidInput();
  const value = envelope as O.FoEnvelope;
  if (!scoped(value, context) || value.actor_person !== context.actor.personId || new Set(value.command.quantities.map(row => row.original_event_id)).size !== value.command.quantities.length) throw invalidInput();
  return value;
}
const inFieldScope = (value: O.FoDailyHeader | O.FoTicketHeader | O.FoDailyRevision | O.FoTicketRevision | O.FoQuantity, scope: Scope) => scoped(value, scope) && value.scope_type === 'Project';

export async function validateOfflineReceipt(envelope: O.FoEnvelope, value: O.FoCreateRecordResponse, context: OfflineActorContext, fresh = false) {
  validateOfflineEnvelope(envelope, context);
  if (!offlineShape('FoCreateRecordResponse', value)) throw invalidOffline();
  const command = envelope.command, header = value.header, revision = value.revision, author = revision.author_user;
  if (value.operation.id !== envelope.capture_id || value.operation.status !== 'succeeded' || value.family !== command.family || !inFieldScope(header, context) || !inFieldScope(revision, context) || revision.author_person !== context.actor.personId || context.receiptActor && author !== context.receiptActor.user || fresh && author !== context.actor.user || revision.parent_id !== header.id || header.current_revision !== revision.id || header.revision_number !== revision.revision_number || header.status !== 'draft' || header.last_decision !== null || !sameValue(fieldInputProjection(revision.definition), command.definition) || !sameValue(fieldInputProjection(revision.photos), command.photos)) throw invalidOffline();
  if (command.family === 'daily') {
    if (!('superintendent' in revision) || !('superintendent_user' in command.definition) || revision.superintendent.user !== command.definition.superintendent_user || !sameValue(revision.quantity_ids, value.quantities.map(row => row.id)) || value.quantities.length !== command.quantities.length) throw invalidOffline();
    if ((revision.superintendent.user === envelope.actor_user || revision.superintendent.user === author) && revision.superintendent.person !== envelope.actor_person) throw invalidOffline();
    for (const [index, quantity] of value.quantities.entries()) if (!inFieldScope(quantity, context) || quantity.author_person !== context.actor.personId || quantity.author_user !== author || quantity.parent_id !== header.id || quantity.source_revision !== revision.id || quantity.revision_number !== revision.revision_number || !sameValue(fieldInputProjection(quantity.definition), command.quantities[index]) || quantity.original_event_id !== quantity.definition.original_event_id || quantity.supersedes_event_id !== quantity.definition.supersedes_event_id) throw invalidOffline();
  } else if (value.quantities.length) throw invalidOffline();
  if (command.action === 'create') {
    if (header.author_person !== context.actor.personId || header.author_user !== author || header.revision_number !== 1 || header.accepted_revision !== null || revision.predecessor !== null || revision.prior_decision !== null || revision.amendment_of !== null || revision.amendment_reason !== '') throw invalidOffline();
  } else {
    if (header.id !== command.record_id || revision.predecessor !== command.base_revision_id || revision.revision_number < 2 || revision.amendment_reason !== command.amendment_reason || revision.amendment_of !== header.accepted_revision) throw invalidOffline();
    // FLD-01 changes these four header values on revision. Reconstruct the exact
    // prior header and bind every retained field to the sealed expected digest.
    const statuses = command.family === 'daily' ? ['draft', 'returned', 'accepted'] : ['draft', 'returned', 'accepted', 'acknowledged'];
    const candidates = await Promise.all(statuses.map(status => engineeringDigest({ ...header, current_revision: command.base_revision_id, revision_number: revision.revision_number - 1, last_decision: revision.prior_decision, status })));
    if (!candidates.includes(command.expected_version)) throw invalidOffline();
  }
  return value;
}
async function validateCapture(value: O.FoCaptureSummary, context: OfflineActorContext, id: string, envelope?: O.FoEnvelope) {
  if (!offlineShape('FoCaptureSummary', value) || !scoped(value, context) || value.actor_person !== context.actor.personId || value.capture_id !== id || value.replacement_capture_id === value.capture_id || value.replaces_capture_id === value.capture_id || value.replacement_capture_id && value.status !== 'superseded' || value.status === 'discarded' && value.payload_retained) throw invalidOffline();
  if (envelope && (envelope.capture_id !== id || value.device_id !== envelope.device_id || value.actor_user !== envelope.actor_user || value.envelope_digest !== await engineeringDigest(envelope))) throw invalidOffline();
}
type ReadResult = O.FoGetCaptureResponse | O.FoInspectCaptureResponse | O.FoApplyCaptureResponse;
export async function validateOfflineRead(kind: 'get' | 'inspect' | 'apply', value: ReadResult, context: OfflineActorContext, captureId: string, originalEnvelope?: O.FoEnvelope) {
  if (!contextValid(context) || !offlineShape({ get: 'FoGetCaptureResponse', inspect: 'FoInspectCaptureResponse', apply: 'FoApplyCaptureResponse' }[kind], value)) throw invalidOffline();
  const envelope = 'envelope' in value && value.envelope !== null ? value.envelope : originalEnvelope;
  if (envelope) { validateOfflineEnvelope(envelope, context); if (originalEnvelope && !sameValue(envelope, originalEnvelope)) throw invalidOffline(); }
  await validateCapture(value.capture, context, captureId, envelope);
  if ('envelope' in value && value.capture.payload_retained !== (value.envelope !== null)) throw invalidOffline();
  if ('disposition' in value) {
    if (value.original_receipt ? value.disposition !== 'committed' : value.disposition === 'committed' || !['ready', 'conflict'].includes(value.disposition) && value.disposition !== value.capture.status) throw invalidOffline();
    if (['ready', 'conflict'].includes(value.disposition) && value.capture.status !== 'staged') throw invalidOffline();
  }
  if (value.original_receipt) {
    if (!envelope) throw invalidOffline(); // A redacted remote copy needs the retained original envelope to prove its payload.
    const fresh = kind === 'apply' && 'replayed' in value && !value.replayed;
    if (fresh && value.capture.status !== 'committed') throw invalidOffline();
    if (kind !== 'apply' && !value.original_receipt.operation.replayed || 'replayed' in value && value.replayed !== value.original_receipt.operation.replayed) throw invalidOffline();
    await validateOfflineReceipt(envelope, value.original_receipt, context, fresh);
  } else if (value.capture.status === 'committed') throw invalidOffline();
  return value;
}

const prefix = 'cipher_aec.field_offline.api.';
function request<T extends Scope>(name: string, input: T, context: OfflineActorContext): T {
  if (!contextValid(context) || !scoped(input, context) || !offlineShape(name, input)) throw invalidInput();
  // Snapshot before the first await so edits to a caller's draft cannot alter an in-flight request.
  return structuredClone(input);
}
const operation = (value: O.FoCaptureMutationResponse | O.FoDeviceMutationResponse, id: string) => { if (value.operation.id !== id || value.operation.status !== 'succeeded') throw invalidOffline(); };
export const fieldOffline = {
  async registerDevice(input: O.FoRegisterDeviceRequest, context: OfflineActorContext) {
    const body = request('FoRegisterDeviceRequest', input, context), value = await rpc<O.FoDeviceMutationResponse>(prefix + 'register_device', { ...body }, true);
    if (!offlineShape('FoDeviceMutationResponse', value)) throw invalidOffline(); operation(value, body.operation_id);
    if (!scoped(value.device, context) || value.device.device_id !== body.device_id || value.device.owner_person !== context.actor.personId || value.device.label !== body.label || value.device.status !== 'active' || !value.operation.replayed && value.device.registered_user !== context.actor.user) throw invalidOffline();
    return value;
  },
  async revokeDevice(input: O.FoRevokeDeviceRequest, context: OfflineActorContext) {
    const body = request('FoRevokeDeviceRequest', input, context), value = await rpc<O.FoDeviceMutationResponse>(prefix + 'revoke_device', { ...body }, true);
    if (!offlineShape('FoDeviceMutationResponse', value)) throw invalidOffline(); operation(value, body.operation_id);
    if (!scoped(value.device, context) || value.device.device_id !== body.device_id || value.device.owner_person !== context.actor.personId || value.device.status !== 'revoked') throw invalidOffline();
    return value;
  },
  async stage(input: O.FoStageCaptureRequest, context: OfflineActorContext) {
    const body = request('FoStageCaptureRequest', input, context); validateOfflineEnvelope(body.envelope, context);
    if (body.operation_id === body.envelope.capture_id) throw invalidInput();
    const value = await rpc<O.FoCaptureMutationResponse>(prefix + 'stage_capture', { ...body }, true);
    if (!offlineShape('FoCaptureMutationResponse', value)) throw invalidOffline(); operation(value, body.operation_id); await validateCapture(value.capture, context, body.envelope.capture_id, body.envelope);
    if (value.capture.status !== 'staged' || !value.capture.payload_retained || value.capture.replaces_capture_id !== null) throw invalidOffline();
    return value;
  },
  async get(scope: Scope, captureId: string, context: OfflineActorContext, envelope?: O.FoEnvelope, signal?: AbortSignal) {
    const body = request('FoGetCaptureRequest', { ...scope, capture_id: captureId }, context);
    return await validateOfflineRead('get', await rpc<O.FoGetCaptureResponse>(prefix + 'get_capture', body, false, signal), context, captureId, envelope) as O.FoGetCaptureResponse;
  },
  async inspect(scope: Scope, captureId: string, context: OfflineActorContext, envelope?: O.FoEnvelope, signal?: AbortSignal) {
    const body = request('FoInspectCaptureRequest', { ...scope, capture_id: captureId }, context);
    return await validateOfflineRead('inspect', await rpc<O.FoInspectCaptureResponse>(prefix + 'inspect_capture', body, false, signal), context, captureId, envelope) as O.FoInspectCaptureResponse;
  },
  async apply(input: O.FoApplyCaptureRequest, context: OfflineActorContext, envelope: O.FoEnvelope) {
    const body = request('FoApplyCaptureRequest', input, context), original = structuredClone(validateOfflineEnvelope(envelope, context));
    if (body.operation_id !== body.capture_id || body.capture_id !== original.capture_id) throw invalidInput();
    return await validateOfflineRead('apply', await rpc<O.FoApplyCaptureResponse>(prefix + 'apply_capture', { ...body }, true), context, body.capture_id, original) as O.FoApplyCaptureResponse;
  },
  async discard(input: O.FoDiscardCaptureRequest, context: OfflineActorContext, envelope?: O.FoEnvelope) {
    const body = request('FoDiscardCaptureRequest', input, context), original = envelope && structuredClone(validateOfflineEnvelope(envelope, context));
    if (body.operation_id === body.capture_id) throw invalidInput();
    const value = await rpc<O.FoCaptureMutationResponse>(prefix + 'discard_capture', { ...body }, true);
    if (!offlineShape('FoCaptureMutationResponse', value)) throw invalidOffline(); operation(value, body.operation_id); await validateCapture(value.capture, context, body.capture_id, original);
    if (value.capture.payload_retained || !['discarded', 'committed', 'superseded'].includes(value.capture.status)) throw invalidOffline();
    return value;
  },
  async resolve(input: O.FoResolveCaptureRequest, context: OfflineActorContext, originalEnvelope: O.FoEnvelope) {
    const body = request('FoResolveCaptureRequest', input, context), original = structuredClone(validateOfflineEnvelope(originalEnvelope, context)), replacement = validateOfflineEnvelope(body.replacement_envelope, context), old = original.command, next = replacement.command;
    if (body.operation_id === body.capture_id || body.operation_id === replacement.capture_id || body.capture_id !== original.capture_id || replacement.capture_id === original.capture_id || old.action !== next.action || old.family !== next.family || ('record_id' in old ? old.record_id : null) !== ('record_id' in next ? next.record_id : null)) throw invalidInput();
    const value = await rpc<O.FoCaptureMutationResponse>(prefix + 'resolve_capture', { ...body }, true);
    if (!offlineShape('FoCaptureMutationResponse', value)) throw invalidOffline(); operation(value, body.operation_id); await validateCapture(value.capture, context, replacement.capture_id, replacement);
    if (value.capture.status !== 'staged' || !value.capture.payload_retained || value.capture.replaces_capture_id !== body.capture_id) throw invalidOffline();
    return value;
  },
};
