import { expect, type Page } from '@playwright/test';
import { mockPdfTakeoff } from './pdf-fixture';
import { company, projects } from './fixture';
import { estimateId, lineId, unitId, unit } from './estimating-fixture';
const revision1 = '20000000-0000-4000-8000-000000000001';
const revision2 = '20000000-0000-4000-8000-000000000002';
export const measurementId = '40000000-0000-4000-8000-000000000020';
export const savedLineId = '40000000-0000-4000-8000-000000000021';
export async function mockTakeoffBinding(page: Page, loseFirst = false, shape: 'segment' | 'rectangle' = 'segment', eligible = false) {
  await mockPdfTakeoff(page); const writes: Record<string, unknown>[] = [];
  const envelope = (data: unknown) => ({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const areaUnit = { ...unit, id: '10000000-0000-4000-8000-000000000099', fields: { symbol: 'm²', dimension: 'area', precision: 6 }, target: { doctype: 'UOM', name: 'Square Meter' } };
  const quantity = { amount: '200.000000', unit_id: shape === 'rectangle' ? areaUnit.id : unitId, precision: 6 };
  await page.route('**/api/method/cipher_aec.estimating.api.list_units*', route => route.fulfill(envelope({ items: [unit, areaUnit] })));
  const interval = { lower: { numerator: '200', denominator: '1' }, upper: { numerator: '200', denominator: '1' } };
  const source = { document_id: 'TEST-PDF-DOC', revision_id: 'TEST-PDF-REV-A', source_sha256: 'a'.repeat(64), page: 1, revision_number: 1, is_current: false };
  const measurement = { id: measurementId, company, project: projects[0].id, takeoff_set: '40000000-0000-4000-8000-000000000001', revision_number: 1, predecessor: null, source, definition: { method: 'calibrated', kind: shape === 'rectangle' ? 'area' : 'length', locator: 'North utility reference segment', reason: 'Explicit contract fixture', geometry: { type: shape, points: [['100', '100'], ['300', shape === 'rectangle' ? '200' : '100']] }, result_unit_id: quantity.unit_id, waste_fraction: '0', tolerance: '0.000001' }, result: { quantity, method: 'calibrated', calibration_claim: 'independently-verified-source-bound-planar', result_interval: interval } };
  const currentUse = { eligible, reasons: eligible ? [] : ['source_revision_not_current'], verification: { id: 'TEST-SCALE-REVIEW' } };
  const line = (revision: string) => ({ id: revision === revision2 ? savedLineId : '40000000-0000-4000-8000-000000000022', company, project: projects[0].id, estimate: estimateId, estimate_revision: revision, line_id: lineId, authored: { line_id: lineId, description: 'Utility allowance', quantity } });
  await page.route('**/api/method/cipher_aec.estimating.api.get_record*', route => { const url = new URL(route.request().url()); const kind = url.searchParams.get('kind'); const id = url.searchParams.get('record_id');
    if (kind === 'estimate') return route.fulfill(envelope({ id: estimateId, title: 'Saved utility estimate', current_revision: revision2, revision_number: 2 }));
    if (kind === 'revision') return route.fulfill(envelope({ id, estimate: estimateId, revision_number: id === revision2 ? 2 : 1, predecessor: id === revision2 ? revision1 : null, line_record_ids: [line(id!).id] }));
    if (kind === 'line') return route.fulfill(envelope(line(id === savedLineId ? revision2 : revision1)));
    return route.fallback();
  });
  await page.route('**/api/method/cipher_aec.takeoff.api.*', route => { const request = route.request(); const url = new URL(request.url()); const method = url.pathname.split('.').pop();
    if (method === 'list_records') return route.fulfill(envelope({ items: url.searchParams.get('kind') === 'measurement' ? [{ record: measurement, current_use: currentUse }] : [], next_cursor: null, total: 1 }));
    if (method === 'get_record' && url.searchParams.get('kind') === 'measurement') return route.fulfill(envelope({ record: measurement, current_use: currentUse }));
    if (method === 'drawing_impact') return route.fulfill(envelope({ source, measurements: [{ measurement_id: measurementId, current_use: currentUse, bound_lines: [{ id: 'TEST-BINDING', estimate: estimateId, estimate_revision: revision2, line_id: lineId, estimate_line_record: savedLineId }] }], historical_results_changed: false, new_use_requires_explicit_successor: true }));
    if (method === 'bind_line') { const body = request.postDataJSON() as Record<string, unknown>; writes.push(body); expect(request.headers()['idempotency-key']).toBe(body.operation_id); if (loseFirst && writes.length === 1) return route.abort('failed'); return route.fulfill(envelope({ binding: { id: 'TEST-NEW-BINDING', ...body }, operation: { id: body.operation_id, status: 'succeeded', replayed: writes.length > 1 } })); }
    return route.fallback();
  });
  return { writes, revokeCurrentUse: () => { currentUse.eligible = false; currentUse.reasons = ['source_revision_not_current']; } };
}
