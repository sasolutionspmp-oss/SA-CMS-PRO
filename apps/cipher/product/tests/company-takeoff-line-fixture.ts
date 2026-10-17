// Synthetic interception fixtures; no native effect or PDF geometry qualification.
import { createHash } from 'node:crypto';
import { expect, type Page, type Route } from '@playwright/test';
import { canonicalBindingJSON } from '../src/api/company-takeoff-binding';
import type { CompanyEstEstimateRecord, CompanyEstLineRecord, CompanyEstRevisionRecord, CompanyEstSnapshotRecord, CompanyTakeoffBindLineResponse } from '../src/api/company-takeoff.generated';
import { mockCompanyTakeoff, measurement as original, company, user, personId, unit, setId, currentUse, pageOf } from './company-takeoff-fixture';
export { company, setId };
export const digest = (v: unknown) => createHash('sha256').update(canonicalBindingJSON(v)).digest('hex');
const id = (n: number) => `81000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const base = { company, project: null, scope_type: 'Company' as const, author_user: user, author_person: personId, created_at: '2026-10-17T02:00:00Z', status: 'draft' };
export function makeLineFixture(count = 1) {
  const measurement = structuredClone(original); const { result_digest: _discard, ...measurementOutput } = measurement.result; measurement.result.result_digest = digest(measurementOutput);
  const estimate: CompanyEstEstimateRecord = { ...base, id: id(1), title: 'Synthetic tender estimate', currency: 'USD', pricing_date: '2026-10-17', revision_number: 1, current_revision: id(2), pursuit_id: null };
  const money = { amount: '0.00', currency: 'USD' };
  const authored = Array.from({ length: count }, (_, n) => ({ line_id: id(100 + n), description: `Saved tender quantity ${n + 1}`, quantity: structuredClone(measurement.result.quantity), cost_code: 'TEST-AREA', notes: '', alternate: '', included: true, rate_source_id: id(8), material_factor: '1', waste_fraction: '0' }));
  const calculated = authored.map(a => ({ line_id: a.line_id, description: a.description, quantity: structuredClone(a.quantity), quantity_method: 'authored' as const, included: true, alternate: '', cost_code: a.cost_code, components: [], unrounded_extension: { numerator: '0', denominator: '1' }, extension: money }));
  const policy = { version: 'cipher.estimate.line-half-up.v1', rounding_mode: 'ROUND_HALF_UP', currency_exponent: 2, intermediate: 'exact-rational', line_rounding: 'sum-exact-components-then-round', component_allocation: 'nonnegative-largest-remainder-tie-by-stable-component-id', header_rounding: 'sum-rounded-lines' } as const;
  const snapshot: CompanyEstSnapshotRecord = { ...base, id: id(3), estimate: estimate.id, subject_type: 'Cipher Estimate Revision', subject_id: id(2), inputs: { schema: 'cipher.estimate.inputs.v2', unit_manifest: { ...structuredClone(measurement.unit_manifest), dataset_id: id(3), label: 'Synthetic saved estimate fixture' }, currency: 'USD', currency_exponent: 2, pricing_date: estimate.pricing_date, policy_version: policy.version, basis_description: 'Human authored fixture quantity', basis_citations: [], rates: {}, assemblies: {}, lines: authored, adjustments: [] }, result: { schema: 'cipher.estimate.result.v1', policy, lines: calculated, adjustments: [], direct: money, indirect: money, contingency: money, total: money, conversion_references: [], input_digest: '', output_digest: '' }, currency_policy: { currency: 'USD', currency_exponent: 2, fraction_units: 100, native_currency_version: 'fixture' }, input_digest: '', output_digest: '', source_citations: [] };
  snapshot.input_digest = snapshot.result.input_digest = digest(snapshot.inputs); const { input_digest: _i, output_digest: _o, ...out } = snapshot.result; snapshot.output_digest = snapshot.result.output_digest = digest(out);
  const lines: CompanyEstLineRecord[] = authored.map((a, n) => ({ ...base, id: id(200 + n), estimate: estimate.id, estimate_revision: id(2), line_id: a.line_id, authored: a, calculated: calculated[n] }));
  const revision: CompanyEstRevisionRecord = { ...base, id: id(2), estimate: estimate.id, revision_number: 1, predecessor: null, calculation_snapshot: snapshot.id, currency: 'USD', pricing_date: estimate.pricing_date, policy_version: policy.version, line_record_ids: lines.map(l => l.id), source_citations: [], basis_description: snapshot.inputs.basis_description, direct: money, indirect: money, contingency: money, total: money };
  const selected = { record: measurement, record_digest: digest(measurement), current_use: structuredClone(currentUse) };
  return { estimate, revision, snapshot, lines, measurement, selected };
}
export async function mockLineBinding(page: Page, options: { fault?: 'lost' | '503' | 'malformed' | 'wrong-result'; denyRecovery?: boolean; denied?: boolean; count?: number; wrong?: 'company' | 'snapshot' | 'source' | 'quantity'; rejectOnce?: boolean; revokeAfterBind?: boolean } = {}) {
  const previous = await mockCompanyTakeoff(page); const f = makeLineFixture(options.count); previous.saved.push(f.measurement);
  if (options.wrong === 'company') f.estimate.company = 'FOREIGN';
  if (options.wrong === 'snapshot') f.snapshot.input_digest = 'a'.repeat(64);
  if (options.wrong === 'source') f.selected.record_digest = 'a'.repeat(64);
  if (options.wrong === 'quantity') { f.lines[0].authored.quantity.amount = '99.00'; f.lines[0].calculated.quantity.amount = '99.00'; const { input_digest: _i, output_digest: _o, ...out } = f.snapshot.result; f.snapshot.input_digest = f.snapshot.result.input_digest = digest(f.snapshot.inputs); f.snapshot.output_digest = f.snapshot.result.output_digest = digest(out); }
  const reads: URL[] = [], writes: Record<string, unknown>[] = [], effects = new Map<string, CompanyTakeoffBindLineResponse>(); let changedHead = false, sourceEligible = true, readDenied = false;
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const deny = (route: Route, status = 403) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Current Company evidence access denied.' } } }) });
  await page.route('**/api/method/cipher_aec.estimating.company_api.*', route => {
    const u = new URL(route.request().url()); if (u.pathname.endsWith('list_units')) return route.fallback(); reads.push(u); expect(u.searchParams.has('project')).toBe(false);
    if (options.denied || readDenied) return deny(route);
    if (u.pathname.endsWith('list_records')) return envelope(route, pageOf([f.estimate]));
    const kind = u.searchParams.get('kind'); return envelope(route, kind === 'estimate' ? { ...f.estimate, ...(changedHead ? { current_revision: id(99), revision_number: 2 } : {}) } : kind === 'revision' ? f.revision : kind === 'snapshot' ? f.snapshot : f.lines.find(l => l.id === u.searchParams.get('record_id')));
  });
  await page.route('**/api/method/cipher_aec.takeoff.company_api.get_record*', route => {
    const u = new URL(route.request().url()); const kind = u.searchParams.get('kind'); if (kind === 'set') return route.fallback(); reads.push(u);
    if (readDenied) return deny(route);
    if (kind === 'measurement') return envelope(route, { ...f.selected, current_use: { ...currentUse, eligible: sourceEligible, reasons: sourceEligible ? [] : ['source_revision_changed'] } });
    const b = [...effects.values()].find(v => v.binding.id === u.searchParams.get('record_id'))?.binding; return envelope(route, { record: b, record_digest: digest(b) });
  });
  await page.route('**/api/method/cipher_aec.takeoff.company_api.bind_line', async route => {
    const body = route.request().postDataJSON(); writes.push(body); expect(Object.keys(body).sort()).toEqual(['company', 'operation_id', 'measurement_id', 'estimate_line_record', 'quantity_basis', 'reason'].sort()); expect(route.request().headers()['idempotency-key']).toBe(body.operation_id); expect(route.request().headers()['x-frappe-csrf-token']).toBe('test-csrf');
    if (options.rejectOnce && writes.length === 1) return deny(route, 412);
    const old = effects.get(body.operation_id); if (old) { if (options.denyRecovery && writes.length === 2) return deny(route); return envelope(route, { ...old, operation: { ...old.operation, replayed: true } }); }
    const line = f.lines.find(l => l.id === body.estimate_line_record)!;
    const response: CompanyTakeoffBindLineResponse = { binding: { ...base, id: id(5), measurement_id: f.measurement.id, measurement_digest: f.selected.record_digest, estimate_line_record: line.id, estimate: f.estimate.id, estimate_revision: f.revision.id, line_id: line.line_id, estimate_line_digest: digest(line), quantity: f.measurement.result.quantity, reason: body.reason, quantity_basis: 'net-quantity-v1', waste_policy: 'net-takeoff-estimate-component-waste-v1', provenance: 'subsequently-attached-takeoff-evidence-v1', original_snapshot_claim: 'authored-quantity-not-recomputed' }, history_id: 'TEST-LINE-HISTORY', operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
    effects.set(body.operation_id, structuredClone(response)); if (options.revokeAfterBind) readDenied = true;
    if (options.fault === 'lost') return route.abort('failed'); if (options.fault === '503') return deny(route, 503); if (options.fault === 'malformed') return route.fulfill({ contentType: 'application/json', body: '{broken' }); if (options.fault === 'wrong-result') response.binding.estimate_line_digest = 'a'.repeat(64);
    return envelope(route, response);
  });
  return { ...f, reads, writes, effects, headChanged: () => { changedHead = true; }, revokeSource: () => { sourceEligible = false; }, denyRead: () => { readDenied = true; } };
}
export async function reviewLine(page: Page, harness = false) {
  await page.goto(harness ? '/tests/company-takeoff.html' : `/company/takeoff/${setId}?company=${company}`);
  await page.getByRole('button', { name: 'A101, room 12', exact: true }).click(); await page.getByRole('button', { name: 'Attach to saved estimate line', exact: true }).click();
  await page.getByRole('combobox', { name: 'Evidence Company estimate', exact: true }).click(); await page.getByRole('option', { name: 'Synthetic tender estimate', exact: true }).click();
  await page.getByRole('combobox', { name: 'Evidence saved line', exact: true }).click(); await page.getByRole('option', { name: /Saved tender quantity 1 ·/ }).click();
}
export async function confirmLine(page: Page) { await page.getByRole('textbox', { name: 'Evidence attachment reason', exact: true }).fill('Measured tender basis reviewed against A101.'); await page.getByRole('checkbox', { name: 'I reviewed the exact saved line, quantity and drawing reference', exact: true }).click(); }
