import type { Page, Route } from '@playwright/test';
import { expect } from '@playwright/test';
import { company, mockWorkspace, projects } from './fixture';
import type { CalculateRevisionRequest, CreateEstimateRequest, EstEstimateRecord, EstSnapshotRecord, EstRevisionRecord, EstRateRecord, EstUnitRecord } from '../src/api/estimating.generated';

export const estimateId = '10000000-0000-4000-8000-000000000010';
export const unitId = '10000000-0000-4000-8000-000000000001';
export const rateId = '10000000-0000-4000-8000-000000000002';
export const lineId = '10000000-0000-4000-8000-000000000003';
const citation = { id: 'a'.repeat(64), document_id: 'TEST-DOC-001', revision_id: 'TEST-REV-001', document_title: 'Site coordination requirements', revision_number: 1, page: 1, page_label: 'Page 1', excerpt: 'Coordinate the temporary bypass plan before mobilization.', excerpt_sha256: 'a'.repeat(64), source_sha256: 'b'.repeat(64) };
const base = { company, project: projects[0].id, author_person: 'TEST-PERSON-001', author_user: 'test.pm@example.invalid', created_at: '2026-10-15T12:00:00Z', status: 'draft' };
export const unit: EstUnitRecord = { id: unitId, kind: 'uom', revision: 1, fields: { symbol: 'm', dimension: 'length', precision: 3 }, target: { doctype: 'UOM', name: 'Meter' } };
export const rate: EstRateRecord = { ...base, id: rateId, rate: { id: rateId, source_id: rateId, revision: 1, predecessor: null, title: 'Synthetic pipe rate', cost_type: 'material', unit_id: unitId, rate_amount: '12.50', rate_precision: 2, currency: 'USD', quote_reference: 'TEST-QUOTE-001', quote_date: '2026-10-01', expiry_date: null, geography: 'Synthetic site', inclusions: 'Pipe material', exclusions: 'Installation', freight_tax_assumptions: 'Authored fixture assumptions', permission_basis: 'Explicit synthetic contract data', source_citations: [citation], item: null, party_type: null, party: null }, unit_manifest: { schema: 'cipher.canonical.v1', dataset_id: '10000000-0000-4000-8000-000000000004', scope: { company, project: projects[0].id }, records: [unit], unit_conversions: [] }, source_citations: [citation] };

type ResponseFault = 'lost' | 'malformed-json' | 'malformed-contract' | 'malformed-receipt' | 'server-error';
export async function mockEstimating(page: Page, options: { loseFirst?: boolean; staleFirst?: boolean; empty?: boolean; denied?: boolean; createFault?: ResponseFault; calculateFault?: ResponseFault; rejectCreateFirst?: boolean; denyRecoveryOnce?: boolean } = {}) {
  await mockWorkspace(page, { estimating: true });
  let sequence = options.empty ? 0 : 1; let first = true;
  const revisions = new Map<string, EstRevisionRecord>(); const snapshots = new Map<string, EstSnapshotRecord>();
  const writes: CalculateRevisionRequest[] = []; const receipts = new Map<string, unknown>();
  const createWrites: CreateEstimateRequest[] = []; const createReceipts = new Map<string, unknown>(); let createEffects = 0; let firstCreate = true;
  let estimate: EstEstimateRecord = { ...base, id: estimateId, title: 'Synthetic source-linked estimate', currency: 'USD', pricing_date: '2026-10-15', revision_number: 0, current_revision: null };
  const make = (number: number, lines: CalculateRevisionRequest['lines'], predecessor: string | null) => {
    const revisionId = `20000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
    const snapshotId = `30000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
    // Contract fixture totals are deliberately server-owned constants, not a UI calculator.
    const total = lines[0]?.quantity.amount === '10.125' ? '126.56' : lines[0]?.quantity.amount === '11.125' ? '139.06' : '77.77';
    const money = (amount: string) => ({ amount, currency: 'USD' });
    const policy = { version: 'cipher.estimate.line-half-up.v1', rounding_mode: 'ROUND_HALF_UP', currency_exponent: 2, intermediate: 'exact-rational', line_rounding: 'sum-exact-components-then-round', component_allocation: 'nonnegative-largest-remainder-tie-by-stable-component-id', header_rounding: 'sum-rounded-lines' } as const;
    const snapshot: EstSnapshotRecord = { ...base, id: snapshotId, status: 'calculated', subject_type: 'Cipher Estimate Revision', subject_id: revisionId, inputs: { schema: 'cipher.estimate.inputs.v1', unit_manifest: rate.unit_manifest, currency: 'USD', currency_exponent: 2, pricing_date: estimate.pricing_date, policy_version: policy.version, basis_description: 'Synthetic authored basis', basis_citations: [citation], rates: { [rateId]: rate.rate }, assemblies: {}, lines, adjustments: [] }, result: { schema: 'cipher.estimate.result.v1', policy, lines: lines.map(line => ({ line_id: line.line_id, description: line.description, quantity: line.quantity, quantity_method: 'authored', included: line.included, alternate: line.alternate, cost_code: line.cost_code, components: [], unrounded_extension: { numerator: '12656', denominator: '100' }, extension: money(total) })), adjustments: [], direct: money(total), indirect: money('0.00'), contingency: money('0.00'), total: money(total), conversion_references: [], input_digest: 'c'.repeat(64), output_digest: 'd'.repeat(64) }, currency_policy: { currency: 'USD', currency_exponent: 2, fraction_units: 100, native_currency_version: 'test-native-currency' }, input_digest: 'c'.repeat(64), output_digest: 'd'.repeat(64), source_citations: [citation] };
    const revision: EstRevisionRecord = { ...base, id: revisionId, status: 'draft-calculated', estimate: estimateId, revision_number: number, predecessor, calculation_snapshot: snapshotId, currency: 'USD', pricing_date: estimate.pricing_date, policy_version: policy.version, line_record_ids: [], source_citations: [citation], basis_description: snapshot.inputs.basis_description, direct: money(total), indirect: money('0.00'), contingency: money('0.00'), total: money(total) };
    revisions.set(revisionId, revision); snapshots.set(snapshotId, snapshot); estimate = { ...estimate, current_revision: revisionId, revision_number: number };
    return { estimate, revision, calculation: snapshot, history_id: `TEST-HISTORY-${number}`, operation: { id: 'test-operation', status: 'succeeded', replayed: false } };
  };
  if (!options.empty) make(1, [{ line_id: lineId, description: 'Synthetic pipe quantity', quantity: { amount: '10.125', unit_id: unitId, precision: 3 }, rate_source_id: rateId, material_factor: '1', waste_fraction: '0', cost_code: 'TEST-PIPE', notes: '', alternate: '', included: true }], null);
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data, request_id: 'test-estimate-request' } }) });
  const denyReceipt = (route: Route) => route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Current rights prevent receipt recovery.' } } }) });
  const fault = (route: Route, mode: ResponseFault) => mode === 'lost' ? route.abort('failed') : mode === 'malformed-json' ? route.fulfill({ contentType: 'application/json', body: '{invalid' }) : mode === 'malformed-contract' ? route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'unexpected' } }) }) : mode === 'malformed-receipt' ? envelope(route, {}) : route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'service_unavailable' } } }) });
  await page.route('**/api/method/cipher_aec.estimating.api.*', async route => {
    const request = route.request(); const url = new URL(request.url()); const method = url.pathname.split('.').pop();
    const body = request.method() === 'POST' ? request.postDataJSON() as Record<string, unknown> : {};
    if (options.denied) return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Estimate access denied.' } } }) });
    if (request.method() === 'POST') { expect(request.headers()['idempotency-key']).toBe(body.operation_id); expect(request.headers()['x-frappe-csrf-token']).toBe('test-csrf'); }
    if (method === 'list_units') return envelope(route, { items: [unit] });
    if (method === 'list_records') { const kind = url.searchParams.get('kind'); return envelope(route, { items: kind === 'estimate' ? [estimate] : kind === 'rate' ? [rate] : [], total: kind === 'estimate' || kind === 'rate' ? 1 : 0, next_cursor: null, limit: 50, count_mode: 'exact' }); }
    if (method === 'get_record') { const kind = url.searchParams.get('kind'); const id = url.searchParams.get('record_id')!; return envelope(route, kind === 'estimate' ? estimate : kind === 'revision' ? revisions.get(id) : kind === 'snapshot' ? snapshots.get(id) : kind === 'rate' ? rate : null); }
    if (method === 'create_estimate') {
      createWrites.push(body as unknown as CreateEstimateRequest);
      const old = createReceipts.get(String(body.operation_id)); if (old) return options.denyRecoveryOnce && createWrites.length === 2 ? denyReceipt(route) : envelope(route, old);
      if (firstCreate && options.rejectCreateFirst) { firstCreate = false; return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'invalid_currency', message: 'Currency is not enabled.' } } }) }); }
      estimate = { ...estimate, title: String(body.title), currency: String(body.currency), pricing_date: String(body.pricing_date) }; createEffects++;
      const result = { estimate, history_id: 'TEST-ESTIMATE-CREATED', operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
      createReceipts.set(String(body.operation_id), { ...result, operation: { ...result.operation, replayed: true } });
      if (firstCreate && options.createFault) { firstCreate = false; return fault(route, options.createFault); }
      return envelope(route, result);
    }
    if (method === 'calculate_revision') {
      writes.push(body as unknown as CalculateRevisionRequest);
      const old = receipts.get(String(body.operation_id)); if (old) return options.denyRecoveryOnce && writes.length === 2 ? denyReceipt(route) : envelope(route, old);
      if (options.staleFirst && first) { first = false; make(++sequence, snapshots.values().next().value!.inputs.lines.map(line => ({ ...line, description: 'Concurrent server change' })), estimate.current_revision); return route.fulfill({ status: 412, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'stale_estimate', message: 'The estimate changed. Calculate against its current revision.' } } }) }); }
      expect(body.expected_revision).toBe(estimate.current_revision);
      const result = make(++sequence, body.lines as CalculateRevisionRequest['lines'], estimate.current_revision); result.operation.id = String(body.operation_id); receipts.set(String(body.operation_id), { ...result, operation: { ...result.operation, replayed: true } });
      if (first && (options.loseFirst || options.calculateFault)) { first = false; return fault(route, options.calculateFault || 'lost'); }
      return envelope(route, result);
    }
    return route.fulfill({ status: 404 });
  });
  return { writes, createWrites, revisions, snapshots, getEstimate: () => estimate, getCreateEffects: () => createEffects };
}
