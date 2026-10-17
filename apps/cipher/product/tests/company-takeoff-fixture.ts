import { expect, type Page, type Route } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mockWorkspace, company } from './fixture';
import { vectorPdf } from './pdf-fixture';
import type { CompanyTakeoffMeasurementRecord, CompanyTakeoffSetRecord, CompanyTakeoffSource } from '../src/api/company-takeoff.generated';
export { company };
export const user = 'test.pm@example.invalid', personId = 'TEST-PERSON-001';
export const setId = '71000000-0000-4000-8000-000000000001', measurementId = '71000000-0000-4000-8000-000000000002', unitId = '71000000-0000-4000-8000-000000000003';
export const bytes = vectorPdf(); export const sha = createHash('sha256').update(bytes).digest('hex');
export const caps = ['company.read', 'estimate.read', 'estimate.write', 'document.read'];
export const revision = { id: 'TEST-COMPANY-DRAWING-REV', revision_number: 1, filename: 'company-vector.pdf', mime_type: 'application/pdf', byte_length: bytes.length, sha256: sha, scan_status: 'not_scanned', retrieval_status: 'available', extraction_status: 'ready', extractor_version: 'test-vector', page_count: 1, extraction_warning: null, scope_type: 'Company' as const, company, project: null };
export const document = { ...revision, id: 'TEST-COMPANY-DRAWING', current_revision: revision.id, title: 'Synthetic Company drawing' };
export const citation = { id: 'a'.repeat(64), document_id: document.id, revision_id: revision.id, document_title: document.title, page_label: 'Page 1', excerpt: 'Synthetic Company rectangle', excerpt_sha256: 'b'.repeat(64), source_sha256: sha, company, revision_number: 1, page: 1, scope_type: 'Company' as const, project: null };
export const preview = { document_id: document.id, revision_id: revision.id, page: 1, page_count: 1, text: citation.excerpt, content_type: 'text/plain', citation, scope_type: 'Company' as const, company, project: null };
export const unit = { id: unitId, kind: 'uom' as const, revision: 1, fields: { symbol: 'sf', dimension: 'area' as const, precision: 2 }, target: { doctype: 'UOM' as const, name: 'Square Foot' } };
export const set: CompanyTakeoffSetRecord = { id: setId, company, project: null, scope_type: 'Company', author_person: personId, author_user: user, created_at: '2026-10-17T02:00:00Z', status: 'draft', title: 'Pre-award Company quantities', discipline: 'Architectural', drawing_package: 'Tender drawings', basis: 'Explicit authored fixture basis', supported_method: 'authored-manual-and-verified-pdf-planar-v1' };
export const source: CompanyTakeoffSource = { document_id: document.id, revision_id: revision.id, revision_number: 1, current_revision: revision.id, current_revision_number: 1, is_current: true, page: 1, page_count: 1, mime_type: 'application/pdf', source_sha256: sha, byte_length: bytes.length, extraction_status: 'ready', scope_type: 'Company', company, project: null };
export const measurement: CompanyTakeoffMeasurementRecord = { id: measurementId, company, project: null, scope_type: 'Company', author_person: personId, author_user: user, created_at: '2026-10-17T02:01:00Z', status: 'draft', takeoff_set: setId, family_id: measurementId, revision_number: 1, predecessor: null, source, source_head_policy: 'current-working-revision-v1', definition: { method: 'manual', kind: 'area', locator: 'A101, room 12', reason: 'Authored tender allowance', result_unit_id: unitId, result_precision: 2, tolerance: '0.000001', waste_fraction: '0', formula_version: 'cipher.takeoff.planar.v1', manual_quantity: { amount: '12.50', unit_id: unitId, precision: 2 } }, calibration_id: null, calibration_digest: null, verification_id: null, page_geometry: null, unit_manifest: { schema: 'cipher.canonical.v2', dataset_id: measurementId, scope: { company, project: null, scope_type: 'Company' }, label: 'Synthetic source unit manifest', records: [unit], unit_conversions: [] }, conversion_ids: [], result: { formula_version: 'cipher.takeoff.planar.v1', method: 'manual', geometry_kind: 'manual', quantity: { amount: '12.50', unit_id: unitId, precision: 2 }, raw_interval: { lower: { numerator: '25', denominator: '2' }, upper: { numerator: '25', denominator: '2' } }, result_interval: { lower: { numerator: '25', denominator: '2' }, upper: { numerator: '25', denominator: '2' } }, tolerance: '0.000001', rounding: 'half_up_unique_interval', waste_fraction: '0', calibration_claim: 'none-manual', result_digest: 'c'.repeat(64) } };
export const currentUse = { eligible: true, reasons: [] as [], current_working_revision: revision.id, head_policy: 'current-working-revision-v1' as const, original_record_preserved: true as const };
export const record = (value = measurement) => ({ record: value, record_digest: 'd'.repeat(64), current_use: currentUse });
export const pageOf = (items: unknown[], next_cursor: string | null = null) => ({ items, limit: 25, count_mode: 'none', total: null, next_cursor });
export const sourceCaps = { antivirus: false, ocr: false, formats: ['application/pdf', 'text/plain'], semantic_search: false, storage: 'frappe-private-file' };
export type Fault = 'lost' | '503' | 'malformed' | 'wrong-source';
export async function mockCompanyTakeoff(page: Page, options: { fault?: Fault; denyRecovery?: boolean; rejectOnce?: boolean; wrongDetail?: boolean; deniedSource?: boolean; wrongHash?: boolean; wrongPageCount?: boolean; noEmbeddedText?: boolean; paged?: boolean } = {}) {
  await mockWorkspace(page); const reads: URL[] = [], writes: Record<string, unknown>[] = []; const effects = new Map<string, unknown>(); const saved: CompanyTakeoffMeasurementRecord[] = [];
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const deny = (route: Route, status = 403) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Current Company source access denied.' } } }) });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => envelope(route, { authenticated: true, user, person: { id: personId, display_name: 'Alex Morgan' }, companies: [{ id: company, name: 'Synthetic Company' }, { id: 'SECOND', name: 'Second Company' }], company_scopes: [company, 'SECOND'].map(company => ({ company, capabilities: caps })), capabilities: [], csrf_token: 'test-csrf', site_mode: 'synthetic' }));
  await page.route('**/api/method/cipher_aec.documents.company_api.*', route => {
    const url = new URL(route.request().url()); reads.push(url);
    const extraction = options.noEmbeddedText ? { extraction_status: 'ocr_unavailable', extraction_warning: 'No embedded text; OCR is not configured.' } : {};
    expect(url.searchParams.has('project')).toBe(false);
    if (url.pathname.endsWith('list_documents')) return envelope(route, { items: [{ ...document, ...extraction }], capabilities: sourceCaps });
    if (options.deniedSource) return deny(route);
    if (url.pathname.endsWith('get_document')) return envelope(route, { document: { ...document, ...extraction, ...(options.wrongDetail ? { company: 'FOREIGN' } : {}), ...(options.wrongPageCount ? { page_count: 2 } : {}) }, revisions: [{ ...revision, ...extraction, ...(options.wrongPageCount ? { page_count: 2 } : {}) }, { ...revision, id: 'TEST-HISTORICAL', revision_number: 2 }] });
    if (url.pathname.endsWith('download_revision')) return route.fulfill({ contentType: 'application/pdf', body: options.wrongHash ? Buffer.from('Wrong bytes') : bytes });
    if (options.noEmbeddedText) return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'invalid_artifact', message: 'Source has no available embedded text; OCR is not configured.' } } }) });
    return envelope(route, options.wrongPageCount ? { ...preview, page_count: 2 } : preview);
  });
  await page.route('**/api/method/cipher_aec.estimating.company_api.list_units*', route => envelope(route, { items: [unit] }));
  await page.route('**/api/method/cipher_aec.takeoff.company_api.*', async route => {
    const request = route.request(), url = new URL(request.url()); reads.push(url); const method = url.pathname.split('.').at(-1);
    if (request.method() === 'GET') {
      expect(url.searchParams.has('project')).toBe(false);
      if (method === 'get_record') return envelope(route, url.searchParams.get('kind') === 'set' ? { record: set, record_digest: 'd'.repeat(64) } : record(saved.find(r => r.id === url.searchParams.get('record_id')) || measurement));
      const kind = url.searchParams.get('kind'); const cursor = url.searchParams.get('cursor');
      if (kind === 'set') return envelope(route, pageOf([{ record: { ...set, title: cursor ? 'Second bounded set page' : set.title }, record_digest: 'd'.repeat(64) }], options.paged && !cursor ? 'signed-company-set-cursor' : null));
      return envelope(route, pageOf(saved.map(r => record(r))));
    }
    const body = request.postDataJSON(); writes.push(body); expect(request.headers()['idempotency-key']).toBe(body.operation_id); expect(request.headers()['x-frappe-csrf-token']).toBe('test-csrf');
    for (const k of ['project', 'scope_type', 'user', 'person', 'actor', 'session', 'pursuit_id']) expect(body).not.toHaveProperty(k);
    if (options.rejectOnce && writes.length === 1) return deny(route, 422);
    const old = effects.get(body.operation_id);
    if (old) { if (options.denyRecovery && writes.filter(row => row.operation_id === body.operation_id).length === 2) return deny(route); return envelope(route, { ...(old as object), operation: { id: body.operation_id, status: 'succeeded', replayed: true } }); }
    const result = method === 'create_set' ? { takeoff_set: { ...set, ...body, operation_id: undefined }, history_id: 'TEST-CREATE-HISTORY', operation: { id: body.operation_id, status: 'succeeded', replayed: false } } : { measurement: { ...structuredClone(measurement), definition: body.definition, source: { ...source, ...body.source, ...(options.noEmbeddedText ? { extraction_status: 'ocr_unavailable' } : {}) } }, history_id: 'TEST-MEASURE-HISTORY', operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
    effects.set(body.operation_id, result); if ('measurement' in result) saved.push(result.measurement as CompanyTakeoffMeasurementRecord);
    if (options.fault === 'lost') return route.abort('failed');
    if (options.fault === '503') return deny(route, 503);
    if (options.fault === 'malformed') return route.fulfill({ contentType: 'application/json', body: '{broken' });
    if (options.fault === 'wrong-source' && 'measurement' in result) return envelope(route, { ...result, measurement: { ...result.measurement, source: { ...source, page: 2 } } });
    return envelope(route, result);
  });
  return { reads, writes, effects, saved };
}
export async function chooseSource(page: Page) {
  await page.getByRole('combobox', { name: 'Company takeoff source', exact: true }).click(); await page.getByRole('option', { name: document.title, exact: true }).click();
  await page.getByRole('combobox', { name: 'Company takeoff revision', exact: true }).click(); await page.getByRole('option', { name: 'Rev. 1 · Current working', exact: true }).click();
}
export async function fillManual(page: Page, sourceAlreadySelected = false) {
  if (!sourceAlreadySelected) await chooseSource(page); await page.getByRole('combobox', { name: 'Manual quantity unit', exact: true }).click(); await page.getByRole('option', { name: 'sf · area · 2 decimal places', exact: true }).click();
  await page.getByRole('textbox', { name: 'Manual quantity', exact: true }).fill('12.50'); await page.getByRole('textbox', { name: 'Drawing locator', exact: true }).fill('A101, room 12'); await page.getByRole('textbox', { name: 'Manual quantity reason', exact: true }).fill('Authored tender allowance');
}
