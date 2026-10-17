import { rpc } from './client';
import { companyTakeoff } from './company-takeoff';
import { bindingDigest } from './company-takeoff-binding';
import { invalidTakeoff, sameTakeoffValue as same, takeoffShape } from './company-takeoff-validation';
import type { CompanyTakeoffGetResponse, CompanyTakeoffMeasurementRecord as Measurement, CompanyTakeoffCompareResponse, CompanyTakeoffCreateMeasurementResponse } from './company-takeoff.generated';
export async function savedManual(v: CompanyTakeoffGetResponse, requireCurrentUse = true) {
  if (!takeoffShape('CompanyTakeoffGetResponse', v) || !takeoffShape('CompanyTakeoffMeasurementRecord', v.record)) throw invalidTakeoff();
  const r = v.record as Measurement; const { result_digest, ...output } = r.result;
  const u = r.unit_manifest.records.filter(row => row.id === r.result.quantity.unit_id && row.kind === 'uom');
  const decimal = (n: string) => n.includes('.') ? n.replace(/0+$/, '').replace(/\.$/, '') : n;
  if (r.scope_type !== 'Company' || r.project !== null || r.source.scope_type !== 'Company' || r.source.project !== null || r.source.company !== r.company || r.unit_manifest.scope.scope_type !== 'Company' || r.unit_manifest.scope.project !== null || r.unit_manifest.scope.company !== r.company || r.unit_manifest.dataset_id !== r.id || r.source.page > r.source.page_count || r.definition.method !== 'manual' || r.result.method !== 'manual' || r.result.geometry_kind !== 'manual' || r.result.calibration_claim !== 'none-manual' || r.calibration_id !== null || r.calibration_digest !== null || r.verification_id !== null || r.page_geometry !== null || decimal(r.definition.waste_fraction) !== '0' || decimal(r.result.waste_fraction) !== '0' || r.definition.result_unit_id !== r.result.quantity.unit_id || r.definition.result_precision !== r.result.quantity.precision || r.definition.manual_quantity.unit_id !== r.result.quantity.unit_id || r.definition.manual_quantity.precision !== r.result.quantity.precision || decimal(r.definition.manual_quantity.amount) !== decimal(r.result.quantity.amount) || u.length !== 1 || u[0].kind !== 'uom' || u[0].fields.precision !== r.result.quantity.precision || u[0].fields.dimension !== r.definition.kind || await bindingDigest(output) !== result_digest || await bindingDigest(r) !== v.record_digest || requireCurrentUse && !v.current_use) throw invalidTakeoff();
  return v as CompanyTakeoffGetResponse & { record: Measurement };
}
export function successorLineage(before: Measurement, after: Measurement) { return after.id !== before.id && after.company === before.company && after.project === null && after.scope_type === 'Company' && after.takeoff_set === before.takeoff_set && after.family_id === before.family_id && after.predecessor === before.id && after.revision_number === before.revision_number + 1; }
const sourceInput = (r: Measurement) => ({ revision_id: r.source.revision_id, source_sha256: r.source.source_sha256, page: r.source.page });
export function verifiedComparison(v: CompanyTakeoffCompareResponse, before: Awaited<ReturnType<typeof savedManual>>, after: Awaited<ReturnType<typeof savedManual>>) {
  if (!takeoffShape('CompanyTakeoffCompareResponse', v) || !successorLineage(before.record, after.record) || v.family_id !== before.record.family_id || !same(v.before, { id: before.record.id, digest: before.record_digest, quantity: before.record.result.quantity, source: before.record.source }) || !same(v.after, { id: after.record.id, digest: after.record_digest, quantity: after.record.result.quantity, source: after.record.source }) || !same(v.changed, { source: !same(sourceInput(before.record), sourceInput(after.record)), quantity: !same(before.record.result.quantity, after.record.result.quantity), geometry_or_manual_inputs: !same(before.record.definition, after.record.definition), calibration: before.record.calibration_id !== after.record.calibration_id }) || v.original_records_preserved !== true) throw invalidTakeoff();
  return v;
}
export type SavedSuccessor = { before: Awaited<ReturnType<typeof savedManual>>; response: CompanyTakeoffCreateMeasurementResponse; authority: string };
export async function readSuccessor(v: SavedSuccessor, signal?: AbortSignal) {
  const company = v.before.record.company;
  const before = await savedManual(await companyTakeoff.get(company, 'measurement', v.before.record.id, signal, v.before.record.takeoff_set));
  const after = await savedManual(await companyTakeoff.get(company, 'measurement', v.response.measurement.id, signal, v.before.record.takeoff_set));
  if (!same(before.record, v.before.record) || !same(after.record, v.response.measurement)) throw invalidTakeoff();
  const compared = verifiedComparison(await rpc<CompanyTakeoffCompareResponse>('cipher_aec.takeoff.company_api.compare_measurements', { company, before_id: before.record.id, after_id: after.record.id }, false, signal), before, after);
  return { before, after, compared };
}

export async function readStoredSuccessor(company: string, selected: CompanyTakeoffGetResponse, signal?: AbortSignal) {
  const after = await savedManual(await companyTakeoff.get(company, 'measurement', selected.record.id, signal));
  if (!same(after.record, selected.record) || after.record_digest !== selected.record_digest || !after.record.predecessor) throw invalidTakeoff();
  const before = await savedManual(await companyTakeoff.get(company, 'measurement', after.record.predecessor, signal, after.record.takeoff_set));
  const compared = verifiedComparison(await rpc<CompanyTakeoffCompareResponse>('cipher_aec.takeoff.company_api.compare_measurements', { company, before_id: before.record.id, after_id: after.record.id }, false, signal), before, after);
  return { before, after, compared };
}
