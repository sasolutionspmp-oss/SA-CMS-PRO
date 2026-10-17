import takeoffSchema from '../../../platform/apps/cipher_aec/cipher_aec/takeoff/schemas/api-company-v2.schema.json' with { type: 'json' };
import documentSchema from '../../../platform/apps/cipher_aec/cipher_aec/documents/schemas/company-api-v1.schema.json' with { type: 'json' };
import { ApiError } from './client';
import type { CompanyTakeoffCreateMeasurementRequest, CompanyTakeoffCreateMeasurementResponse, CompanyTakeoffCreateSetRequest, CompanyTakeoffCreateSetResponse, CompanyTakeoffGetResponse, CompanyTakeoffListRequest, CompanyTakeoffListResponse, CompanyTakeoffSourceInput } from './company-takeoff.generated';
import type { CompanyDocumentDetail, CompanyDocumentList, CompanyDocumentPreview, CompanyDocumentRevision } from './company-documents.generated';

type Shape = Record<string, unknown>;
const object = (v: unknown): v is Shape => Boolean(v && typeof v === 'object' && !Array.isArray(v));
export function sameTakeoffValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameTakeoffValue(v, b[i]));
  return object(a) && object(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && sameTakeoffValue(a[k], b[k]));
}
const keywords = new Set(['$ref', '$comment', 'description', 'title', 'type', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'format', 'pattern', 'enum', 'const', 'oneOf', 'anyOf']);
const type = (v: unknown, t: string) => t === 'null' ? v === null : t === 'object' ? object(v) : t === 'array' ? Array.isArray(v) : t === 'integer' ? Number.isSafeInteger(v) : t === 'number' ? typeof v === 'number' && Number.isFinite(v) : ['string', 'boolean'].includes(t) && typeof v === t;
// Finite evaluator over the unchanged published contracts; unknown constraints
// fail closed. It checks wire shape, never current source eligibility/authority.
function shape(v: unknown, s: Shape, defs: Record<string, Shape>, depth = 0): boolean {
  if (depth > 64 || Object.keys(s).some(k => !keywords.has(k))) return false;
  if (s.$ref) { const name = String(s.$ref).replace(/^#\/\$defs\//, ''); if (!defs[name] || !shape(v, defs[name], defs, depth + 1)) return false; }
  if (s.type && !(Array.isArray(s.type) ? s.type : [s.type]).some(t => type(v, String(t)))) return false;
  if (s.oneOf && (s.oneOf as Shape[]).filter(b => shape(v, b, defs, depth + 1)).length !== 1 || s.anyOf && !(s.anyOf as Shape[]).some(b => shape(v, b, defs, depth + 1))) return false;
  if (Object.hasOwn(s, 'const') && !sameTakeoffValue(v, s.const) || s.enum && !(s.enum as unknown[]).some(e => sameTakeoffValue(v, e))) return false;
  if (object(v)) {
    const props = (s.properties || {}) as Record<string, Shape>;
    if ((s.required as string[] || []).some(k => !Object.hasOwn(v, k))) return false;
    for (const [k, item] of Object.entries(v)) {
      if (Object.hasOwn(props, k)) { if (!shape(item, props[k], defs, depth + 1)) return false; }
      else if (s.additionalProperties === false || object(s.additionalProperties) && !shape(item, s.additionalProperties, defs, depth + 1)) return false;
    }
  }
  if (Array.isArray(v) && (typeof s.minItems === 'number' && v.length < s.minItems || typeof s.maxItems === 'number' && v.length > s.maxItems || object(s.items) && !v.every(item => shape(item, s.items as Shape, defs, depth + 1)))) return false;
  if (typeof v === 'string') {
    if (typeof s.minLength === 'number' && [...v].length < s.minLength || typeof s.maxLength === 'number' && [...v].length > s.maxLength || s.pattern && !new RegExp(String(s.pattern)).test(v)) return false;
    if (s.format === 'uuid' && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v)) return false;
    if (s.format === 'date-time' && (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) || !Number.isFinite(Date.parse(v)))) return false;
    if (s.format && !['uuid', 'date-time'].includes(String(s.format))) return false;
  }
  return !(typeof v === 'number' && (typeof s.minimum === 'number' && v < s.minimum || typeof s.maximum === 'number' && v > s.maximum));
}
export function takeoffShape(name: string, value: unknown): boolean {
  const defs = takeoffSchema.$defs as unknown as Record<string, Shape>;
  return Boolean(defs[name] && shape(value, defs[name], defs));
}
function documentsShape(name: string, value: unknown): boolean {
  const defs = documentSchema.$defs as unknown as Record<string, Shape>;
  return Boolean(defs[name] && shape(value, defs[name], defs));
}
export const invalidTakeoff = () => new ApiError('This Company takeoff response could not be verified against the selected record and source. Refresh with current access.', 'INVALID_CONTRACT', 200);
const scoped = (v: { company: string; scope_type: string; project: unknown }, company: string) => v.company === company && v.scope_type === 'Company' && v.project === null;
export function validateTakeoffRecord(v: CompanyTakeoffGetResponse, input: CompanyTakeoffListRequest, id?: string): CompanyTakeoffGetResponse {
  if (!takeoffShape('CompanyTakeoffGetResponse', v) || !scoped(v.record, input.company) || id && v.record.id !== id) throw invalidTakeoff();
  const r = v.record;
  if (!takeoffShape({ set: 'CompanyTakeoffSetRecord', measurement: 'CompanyTakeoffMeasurementRecord', calibration: 'CompanyTakeoffCalibrationRecord', binding: 'CompanyTakeoffBindingRecord' }[input.kind], r) || input.takeoff_set && (!('takeoff_set' in r) || r.takeoff_set !== input.takeoff_set)) throw invalidTakeoff();
  if ('source' in r && !scoped(r.source, input.company)) throw invalidTakeoff();
  if ('unit_manifest' in r && !scoped(r.unit_manifest.scope, input.company)) throw invalidTakeoff();
  if (['measurement', 'calibration'].includes(input.kind) && !v.current_use) throw invalidTakeoff();
  return v;
}
export function validateTakeoffPage(v: CompanyTakeoffListResponse, input: CompanyTakeoffListRequest): CompanyTakeoffListResponse {
  if (!takeoffShape('CompanyTakeoffListResponse', v) || v.limit !== 25 || v.count_mode !== 'none' || v.total !== null || v.items.length > 25 || input.cursor && v.next_cursor === input.cursor || new Set(v.items.map(row => row.record.id)).size !== v.items.length) throw invalidTakeoff();
  v.items.forEach(row => validateTakeoffRecord(row, input)); return v;
}
export function validateSourceList(v: CompanyDocumentList, company: string): CompanyDocumentList {
  if (!documentsShape('CompanyDocumentList', v) || v.items.some(row => !scoped(row, company)) || new Set(v.items.map(row => row.id)).size !== v.items.length) throw invalidTakeoff();
  return v;
}
export function validTakeoffPdfMetadata(v: CompanyDocumentRevision): boolean {
  return v.mime_type === 'application/pdf' && v.retrieval_status === 'available' && /^[a-f0-9]{64}$/.test(v.sha256) &&
    Number.isSafeInteger(v.page_count) && v.page_count >= 1 && v.page_count <= 200 &&
    Number.isSafeInteger(v.byte_length) && v.byte_length >= 1 && v.byte_length <= 10 * 1024 * 1024 &&
    Number.isSafeInteger(v.revision_number) && v.revision_number >= 1;
}
export function validateSourceDetail(v: CompanyDocumentDetail, company: string, id: string): CompanyDocumentDetail {
  if (!documentsShape('CompanyDocumentDetail', v) || !scoped(v.document, company) || v.document.id !== id || !v.revisions.length || v.revisions.some(row => !scoped(row, company)) || new Set(v.revisions.map(row => row.id)).size !== v.revisions.length) throw invalidTakeoff();
  const head = v.revisions.find(row => row.id === v.document.current_revision);
  if (!head || ['sha256', 'revision_number', 'mime_type', 'page_count', 'byte_length'].some(k => head[k as keyof typeof head] !== v.document[k as keyof typeof v.document])) throw invalidTakeoff();
  if (v.revisions.some(row => row.mime_type === 'application/pdf' && row.retrieval_status === 'available' && !validTakeoffPdfMetadata(row))) throw invalidTakeoff();
  return v;
}
export function validateSourcePage(v: CompanyDocumentPreview, company: string, documentId: string, revision: CompanyDocumentRevision, page: number): CompanyDocumentPreview {
  if (!documentsShape('CompanyDocumentPreview', v) || !scoped(v, company) || !scoped(v.citation, company) || v.document_id !== documentId || v.revision_id !== revision.id || v.page !== page || v.page_count !== revision.page_count || page > v.page_count || v.content_type !== 'text/plain' || v.citation.document_id !== documentId || v.citation.revision_id !== revision.id || v.citation.page !== page || v.citation.revision_number !== revision.revision_number || v.citation.source_sha256 !== revision.sha256) throw invalidTakeoff();
  return v;
}
export type CommandActor = { user: string; personId: string };
export function matchesCreatedSet(v: CompanyTakeoffCreateSetResponse, input: CompanyTakeoffCreateSetRequest, actor: CommandActor): boolean {
  return takeoffShape('CompanyTakeoffCreateSetResponse', v) && scoped(v.takeoff_set, input.company) && v.takeoff_set.author_user === actor.user && v.takeoff_set.author_person === actor.personId && ['title', 'discipline', 'drawing_package', 'basis'].every(k => v.takeoff_set[k as keyof typeof v.takeoff_set] === input[k as keyof typeof input]);
}
export function matchesCreatedMeasurement(v: CompanyTakeoffCreateMeasurementResponse, input: CompanyTakeoffCreateMeasurementRequest, actor: CommandActor, documentId: string): boolean {
  if (!takeoffShape('CompanyTakeoffCreateMeasurementResponse', v)) return false;
  const r = v.measurement, s = r.source;
  if (input.definition.method !== 'manual' || input.definition.waste_fraction !== '0') return false;
  const unit = r.unit_manifest.records.filter(row => row.id === input.definition.result_unit_id);
  if (unit.length !== 1 || unit[0].kind !== 'uom' || unit[0].fields.precision !== input.definition.result_precision || unit[0].fields.dimension !== input.definition.kind || input.definition.manual_quantity.unit_id !== input.definition.result_unit_id || input.definition.manual_quantity.precision !== input.definition.result_precision || r.page_geometry !== null || r.calibration_digest !== null) return false;
  const normalized = (amount: string) => amount.includes('.') ? amount.replace(/0+$/, '').replace(/\.$/, '') : amount;
  if (normalized(r.result.quantity.amount) !== normalized(input.definition.manual_quantity.amount) || !scoped(r.unit_manifest.scope, input.company) || r.unit_manifest.dataset_id !== r.id || r.result.tolerance !== input.definition.tolerance || r.result.waste_fraction !== input.definition.waste_fraction) return false;
  return scoped(r, input.company) && scoped(s, input.company) && r.author_user === actor.user && r.author_person === actor.personId && r.takeoff_set === input.takeoff_set && s.document_id === documentId && ['revision_id', 'source_sha256', 'page'].every(k => s[k as keyof typeof s] === input.source[k as keyof CompanyTakeoffSourceInput]) && sameTakeoffValue(r.definition, input.definition) && sameTakeoffValue([...r.conversion_ids].sort(), [...input.conversion_ids].sort()) && r.predecessor === (input.predecessor ?? null) && r.result.method === 'manual' && r.result.calibration_claim === 'none-manual' && r.result.geometry_kind === 'manual' && r.result.quantity.unit_id === input.definition.result_unit_id && r.result.quantity.precision === input.definition.result_precision && r.calibration_id === null && r.verification_id === null;
}
