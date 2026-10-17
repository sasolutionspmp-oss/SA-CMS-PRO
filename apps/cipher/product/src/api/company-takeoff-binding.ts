import { ApiError, rpc } from './client';
import { companyTakeoff } from './company-takeoff';
import { invalidTakeoff, sameTakeoffValue as same, takeoffShape } from './company-takeoff-validation';
import type { CompanyEstEstimateRecord as Estimate, CompanyEstRevisionRecord as Revision, CompanyEstSnapshotRecord as Snapshot, CompanyEstLineRecord as Line, CompanyEstListResponse, CompanyTakeoffMeasurementRecord as Measurement, CompanyTakeoffBindLineRequest, CompanyTakeoffBindLineResponse, CompanyTakeoffBindingRecord, CompanyTakeoffGetResponse } from './company-takeoff.generated';
export type EstimateReview = { estimate: Estimate; revision: Revision; snapshot: Snapshot };
export type LineReview = EstimateReview & { measurement: Measurement; measurementDigest: string; line: Line; lineDigest: string };
export function canonicalBindingJSON(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalBindingJSON).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonicalBindingJSON((value as Record<string, unknown>)[k])).join(',') + '}';
  if (value === null || typeof value === 'string' || typeof value === 'boolean' || Number.isSafeInteger(value)) return JSON.stringify(value);
  throw invalidTakeoff();
}
export async function bindingDigest(value: unknown) { const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalBindingJSON(value))); return [...new Uint8Array(bytes)].map(n => n.toString(16).padStart(2, '0')).join(''); }
const scoped = (v: { company: string; project: unknown; scope_type: string }, company: string) => v.company === company && v.project === null && v.scope_type === 'Company';
export function estimateRecord<T extends Estimate | Revision | Snapshot | Line>(name: string, value: T, company: string, id: string): T { if (!takeoffShape(name, value) || !scoped(value, company) || value.id !== id) throw invalidTakeoff(); return value; }
const prefix = 'cipher_aec.estimating.company_api.';
async function get<T extends Estimate | Revision | Snapshot | Line>(company: string, kind: string, name: string, id: string, signal?: AbortSignal) { return estimateRecord(name, await rpc<T>(prefix + 'get_record', { company, kind, record_id: id }, false, signal), company, id); }
export async function validateEstimateReview(v: EstimateReview, current = true) {
  const { estimate: e, revision: r, snapshot: s } = v;
  estimateRecord('CompanyEstEstimateRecord', e, e.company, e.id); estimateRecord('CompanyEstRevisionRecord', r, e.company, r.id); estimateRecord('CompanyEstSnapshotRecord', s, e.company, s.id);
  const { input_digest, output_digest, ...output } = s.result;
  if (current && (e.current_revision !== r.id || e.revision_number !== r.revision_number) || r.estimate !== e.id || s.estimate !== e.id || r.calculation_snapshot !== s.id || s.subject_type !== 'Cipher Estimate Revision' || s.subject_id !== r.id || s.inputs.unit_manifest.dataset_id !== s.id || e.currency !== r.currency || e.pricing_date !== r.pricing_date || !scoped(s.inputs.unit_manifest.scope, e.company) || new Set(r.line_record_ids).size !== r.line_record_ids.length || s.inputs.lines.length !== r.line_record_ids.length || new Set(s.inputs.lines.map(l => l.line_id)).size !== s.inputs.lines.length || new Set(s.result.lines.map(l => l.line_id)).size !== s.result.lines.length || s.result.lines.length !== s.inputs.lines.length || input_digest !== s.input_digest || output_digest !== s.output_digest || await bindingDigest(s.inputs) !== input_digest || await bindingDigest(output) !== output_digest) throw invalidTakeoff();
  if (r.currency !== s.inputs.currency || r.pricing_date !== s.inputs.pricing_date || r.policy_version !== s.inputs.policy_version || r.basis_description !== s.inputs.basis_description || s.currency_policy.currency !== r.currency || s.currency_policy.currency_exponent !== s.inputs.currency_exponent || s.result.policy.version !== r.policy_version || s.result.policy.currency_exponent !== s.inputs.currency_exponent || !['direct', 'indirect', 'contingency', 'total'].every(k => same(r[k as keyof Revision], s.result[k as keyof typeof s.result]))) throw invalidTakeoff();
  return v;
}
export async function validateLineReview(v: LineReview) {
  const { measurement: m, line: l, estimate: e, revision: r, snapshot: s } = v;
  const { result_digest, ...measurementOutput } = m.result;
  estimateRecord('CompanyEstLineRecord', l, e.company, l.id);
  if (!takeoffShape('CompanyTakeoffMeasurementRecord', m) || !scoped(m, e.company) || !scoped(m.source, e.company) || !scoped(m.unit_manifest.scope, e.company) || m.unit_manifest.dataset_id !== m.id || m.source.page > m.source.page_count || await bindingDigest(measurementOutput) !== result_digest || !r.line_record_ids.includes(l.id) || l.estimate !== e.id || l.estimate_revision !== r.id || l.line_id !== l.authored.line_id || l.line_id !== l.calculated.line_id || !same(l.authored, s.inputs.lines.find(row => row.line_id === l.line_id)) || !same(l.calculated, s.result.lines.find(row => row.line_id === l.line_id)) || await bindingDigest(m) !== v.measurementDigest || await bindingDigest(l) !== v.lineDigest) throw invalidTakeoff();
  const q = m.result.quantity; const units = (records: typeof m.unit_manifest.records) => records.filter(row => row.id === q.unit_id && row.kind === 'uom');
  const a = units(m.unit_manifest.records), b = units(s.inputs.unit_manifest.records);
  if (a.length !== 1 || b.length !== 1 || !same(a[0], b[0]) || a[0].kind !== 'uom' || a[0].fields.precision !== q.precision || a[0].fields.dimension !== m.definition.kind || !same(l.authored.quantity, l.calculated.quantity)) throw invalidTakeoff();
  return v;
}
const decimal = (v: string) => v.includes('.') ? v.replace(/0+$/, '').replace(/\.$/, '') : v;
export function matchingManualQuantity(v: LineReview) { const m = v.measurement, a = m.result.quantity, b = v.line.authored.quantity; return m.definition.method === 'manual' && m.result.method === 'manual' && m.result.calibration_claim === 'none-manual' && m.result.geometry_kind === 'manual' && m.definition.result_unit_id === a.unit_id && m.definition.result_precision === a.precision && m.calibration_digest === null && m.definition.manual_quantity.unit_id === a.unit_id && m.definition.manual_quantity.precision === a.precision && decimal(m.definition.manual_quantity.amount) === decimal(a.amount) && m.calibration_id === null && m.verification_id === null && m.page_geometry === null && decimal(m.definition.waste_fraction) === '0' && decimal(m.result.waste_fraction) === '0' && a.unit_id === b.unit_id && a.precision === b.precision && decimal(a.amount) === decimal(b.amount); }
export function matchesBinding(b: CompanyTakeoffBindingRecord, input: CompanyTakeoffBindLineRequest, v: LineReview, actor: { user: string; personId: string }) {
  return takeoffShape('CompanyTakeoffBindingRecord', b) && scoped(b, input.company) && b.author_user === actor.user && b.author_person === actor.personId && b.measurement_id === input.measurement_id && b.measurement_id === v.measurement.id && b.measurement_digest === v.measurementDigest && b.estimate_line_record === input.estimate_line_record && b.estimate_line_record === v.line.id && b.estimate_line_digest === v.lineDigest && b.estimate === v.estimate.id && b.estimate_revision === v.revision.id && b.line_id === v.line.line_id && same(b.quantity, v.measurement.result.quantity) && b.reason === input.reason && b.quantity_basis === 'net-quantity-v1' && input.quantity_basis === b.quantity_basis && b.waste_policy === 'net-takeoff-estimate-component-waste-v1' && b.provenance === 'subsequently-attached-takeoff-evidence-v1' && b.original_snapshot_claim === 'authored-quantity-not-recomputed';
}
export const companyTakeoffBinding = {
  async estimates(company: string, cursor?: string, signal?: AbortSignal) {
    const v = await rpc<CompanyEstListResponse>(prefix + 'list_records', { company, kind: 'estimate', limit: 25, count_mode: 'none', cursor }, false, signal);
    if (!takeoffShape('CompanyEstListResponse', v) || v.limit !== 25 || v.count_mode !== 'none' || v.total !== null || v.items.length > 25 || new Set(v.items.map(r => r.id)).size !== v.items.length) throw invalidTakeoff();
    v.items.forEach(r => estimateRecord('CompanyEstEstimateRecord', r as Estimate, company, r.id)); return v as Omit<CompanyEstListResponse, 'items'> & { items: Estimate[] };
  },
  async review(company: string, estimateId: string, signal?: AbortSignal, revisionId?: string) {
    const estimate = await get<Estimate>(company, 'estimate', 'CompanyEstEstimateRecord', estimateId, signal);
    const id = revisionId || estimate.current_revision; if (!id) throw new ApiError('This estimate has no saved revision to review.', 'saved_revision_required', 412);
    const revision = await get<Revision>(company, 'revision', 'CompanyEstRevisionRecord', id, signal);
    const snapshot = await get<Snapshot>(company, 'snapshot', 'CompanyEstSnapshotRecord', revision.calculation_snapshot, signal);
    return validateEstimateReview({ estimate, revision, snapshot }, !revisionId);
  },
  async lines(v: EstimateReview, offset: number, signal?: AbortSignal) {
    if (!Number.isInteger(offset) || offset < 0 || offset % 10) throw invalidTakeoff();
    return Promise.all(v.revision.line_record_ids.slice(offset, offset + 10).map(id => get<Line>(v.estimate.company, 'line', 'CompanyEstLineRecord', id, signal)));
  },
  async lineReview(v: EstimateReview, line: Line, selected: CompanyTakeoffGetResponse) { return validateLineReview({ ...v, line, lineDigest: await bindingDigest(line), measurement: selected.record as Measurement, measurementDigest: selected.record_digest }); },
  async preflight(v: LineReview, signal?: AbortSignal) {
    const fresh = await this.review(v.estimate.company, v.estimate.id, signal);
    const measured = await companyTakeoff.get(v.estimate.company, 'measurement', v.measurement.id, signal, v.measurement.takeoff_set);
    const line = await get<Line>(v.estimate.company, 'line', 'CompanyEstLineRecord', v.line.id, signal);
    const next = await this.lineReview(fresh, line, measured);
    if (!measured.current_use?.eligible || !same(fresh.revision, v.revision) || !same(fresh.snapshot, v.snapshot) || !same(next.measurement, v.measurement) || !same(next.line, v.line) || !matchingManualQuantity(next)) throw new ApiError('The reviewed estimate or source eligibility changed. Refresh and review before attaching evidence.', 'binding_review_changed', 412);
  },
  bind: (input: CompanyTakeoffBindLineRequest) => rpc<CompanyTakeoffBindLineResponse>('cipher_aec.takeoff.company_api.bind_line', { company: input.company, operation_id: input.operation_id, measurement_id: input.measurement_id, estimate_line_record: input.estimate_line_record, quantity_basis: input.quantity_basis, reason: input.reason }, true),
  async readback(response: CompanyTakeoffBindLineResponse, v: LineReview, signal?: AbortSignal) {
    const company = v.estimate.company;
    const saved = await companyTakeoff.get(company, 'binding', response.binding.id, signal);
    const fresh = await this.review(company, v.estimate.id, signal, v.revision.id);
    const measured = await companyTakeoff.get(company, 'measurement', v.measurement.id, signal, v.measurement.takeoff_set);
    const line = await get<Line>(company, 'line', 'CompanyEstLineRecord', v.line.id, signal);
    const checked = await this.lineReview(fresh, line, measured);
    if (!same(saved.record, response.binding) || await bindingDigest(saved.record) !== saved.record_digest || !same(checked.line, v.line) || !same(checked.measurement, v.measurement) || !same(fresh.revision, v.revision) || !same(fresh.snapshot, v.snapshot)) throw invalidTakeoff();
    return { binding: response.binding, review: checked, currentUse: measured.current_use, currentRevision: fresh.estimate.current_revision };
  },
};
