import { expect, type Page, type Route } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mockEstimating, estimateId } from './estimating-fixture';
import { company } from './fixture';
import type { CompanyEstEstimateRecord, CompanyEstRevisionRecord, CompanyEstSnapshotRecord } from '../src/api/company-estimating.generated';

// Explicit test-only adapter of the existing synthetic arithmetic fixture into
// Company DTOs. The production client never imports or normalizes fixture data.
function companyDto<T>(value: unknown): T {
  if (Array.isArray(value)) return value.map(item => companyDto(item)) as T;
  if (!value || typeof value !== 'object') return value as T;
  const record = Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, companyDto(entry)]));
  if ('project' in record) { record.project = null; record.scope_type = 'Company'; }
  if (record.schema === 'cipher.canonical.v1') record.schema = 'cipher.canonical.v2';
  if ('document_id' in record && 'excerpt_sha256' in record) { record.company = company; record.project = null; record.scope_type = 'Company'; }
  if ('current_revision' in record && 'title' in record) record.pursuit_id = null;
  if (record.subject_type === 'Cipher Estimate Revision') record.estimate = estimateId;
  return record as T;
}
export async function mockCompany(page: Page, options: { loseCalculation?: boolean; denyRetry412?: boolean; wrongSubject?: boolean; loseUpload?: boolean } = {}) {
  const fixture = await mockEstimating(page); const revisions = new Map<string, CompanyEstRevisionRecord>(); const snapshots = new Map<string, CompanyEstSnapshotRecord>();
  for (const [id, value] of fixture.revisions) revisions.set(id, companyDto(value)); for (const [id, value] of fixture.snapshots) snapshots.set(id, companyDto(value));
  let estimate = companyDto<CompanyEstEstimateRecord>(fixture.getEstimate()); let first = true; let effects = 0;
  const writes: Record<string, unknown>[] = []; const uploads: Record<string, unknown>[] = []; const receipts = new Map<string, unknown>();
  const text = 'Explicit synthetic Company source. <script>window.companyInjected=true</script>';
  const hash = createHash('sha256').update(text).digest('hex'); const citation = { id: 'a'.repeat(64), document_id: 'TEST-COMPANY-DOC', revision_id: 'TEST-COMPANY-REV', document_title: 'Synthetic Company source', revision_number: 1, page: 1, page_label: 'Page 1', excerpt: text, excerpt_sha256: hash, source_sha256: hash, scope_type: 'Company', company, project: null };
  let document = { id: 'TEST-COMPANY-DOC', title: 'Synthetic Company source', company, project: null, scope_type: 'Company', current_revision: 'TEST-COMPANY-REV', revision_number: 1, filename: 'company-source.txt', mime_type: 'text/plain', byte_length: Buffer.byteLength(text), sha256: hash, scan_status: 'not_scanned', retrieval_status: 'permitted', extraction_status: 'ready', extractor_version: 'test-text-v1', page_count: 1, extraction_warning: null as string | null };
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => envelope(route, { authenticated: true, user: 'test.pm@example.invalid', person: { id: 'TEST-PERSON-001', display_name: 'Alex Morgan' }, companies: [{ id: company, name: 'Synthetic Company-only workspace' }], company_scopes: [{ company, capabilities: ['company.read', 'document.read', 'document.write', 'estimate.read', 'estimate.write', 'approval.request'] }], capabilities: ['company.read'], csrf_token: 'test-csrf', site_mode: 'synthetic' }));
  const assertWrite = (route: Route) => { const body = route.request().postDataJSON() as Record<string, unknown>; expect(body).not.toHaveProperty('project'); expect(body).not.toHaveProperty('scope_type'); expect(route.request().headers()['idempotency-key']).toBe(body.operation_id); return body; };
  await page.route('**/api/method/cipher_aec.estimating.company_api.*', async route => {
    const url = new URL(route.request().url()); const method = url.pathname.split('.').pop(); const kind = url.searchParams.get('kind');
    if (method === 'calculate_revision') {
      const body = assertWrite(route); writes.push(body);
      const old = receipts.get(String(body.operation_id)); if (old) { if (options.denyRetry412 && writes.length === 2) return route.fulfill({ status: 412, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'source_changed', message: 'Current source changed after the unknown result.' } } }) }); return envelope(route, old); }
      const oldSnapshot = snapshots.values().next().value!; const oldRevision = revisions.values().next().value!;
      const snapshot = structuredClone(oldSnapshot); snapshot.id = '30000000-0000-4000-8000-000000000002'; snapshot.subject_id = '20000000-0000-4000-8000-000000000002'; snapshot.inputs.lines = body.lines as typeof snapshot.inputs.lines; snapshot.result.total.amount = '139.06'; snapshot.result.direct.amount = '139.06';
      const revision = { ...structuredClone(oldRevision), id: snapshot.subject_id, revision_number: 2, predecessor: oldRevision.id, calculation_snapshot: snapshot.id }; estimate = { ...estimate, current_revision: revision.id, revision_number: 2 };
      snapshots.set(snapshot.id, snapshot); revisions.set(revision.id, revision); effects++;
      const result = { estimate, revision, calculation: snapshot, history_id: 'TEST-COMPANY-HISTORY', operation: { id: body.operation_id, status: 'succeeded', replayed: false } }; receipts.set(String(body.operation_id), { ...result, operation: { ...result.operation, replayed: true } });
      if (first && options.loseCalculation) { first = false; return route.abort('failed'); }
      if (first && options.wrongSubject) { first = false; return envelope(route, { ...result, estimate: { ...estimate, id: 'wrong-subject' } }); }
      return envelope(route, result);
    }
    if (method === 'list_units') return envelope(route, { items: [companyDto(fixture.snapshots.values().next().value!.inputs.unit_manifest.records[0])] });
    if (method === 'list_acceptances') return envelope(route, { items: [] });
    if (method === 'acceptance_subject') return envelope(route, { revision_id: estimate.current_revision, record_digest: 'e'.repeat(64), estimate_id: estimate.id, is_current: true, current_revision: estimate.current_revision, accepted_baseline_id: null });
    if (method === 'list_records') return envelope(route, { items: kind === 'estimate' ? [estimate] : kind === 'rate' ? [companyDto((await import('./estimating-fixture')).rate)] : [], next_cursor: null, total: kind === 'estimate' || kind === 'rate' ? 1 : 0, limit: 50, count_mode: 'exact' });
    if (method === 'get_record') { const id = url.searchParams.get('record_id')!; return envelope(route, kind === 'estimate' ? estimate : kind === 'revision' ? revisions.get(id) : kind === 'snapshot' ? snapshots.get(id) : companyDto((await import('./estimating-fixture')).rate)); }
    return route.fulfill({ status: 404 });
  });
  await page.route('**/api/method/cipher_aec.documents.company_api.*', async route => {
    const method = new URL(route.request().url()).pathname.split('.').pop();
    if (method === 'list_documents') return envelope(route, { items: [document] });
    if (method === 'get_document') return envelope(route, { document, revisions: [{ ...document, id: document.current_revision }] });
    if (method === 'preview_revision') return envelope(route, { document_id: document.id, revision_id: document.current_revision, page: 1, page_count: 1, text, content_type: 'text/plain', citation });
    if (method === 'upload_document') {
      const body = assertWrite(route); uploads.push(body); const old = receipts.get(String(body.operation_id)); if (old) return envelope(route, old);
      document = { ...document, id: 'TEST-COMPANY-UPLOADED', current_revision: 'TEST-COMPANY-UPLOADED-REV', title: String(body.title), filename: String(body.filename), byte_length: Number(body.byte_length), sha256: String(body.sha256) };
      const result = { document, revision: { ...document, id: document.current_revision }, operation: { id: body.operation_id, status: 'succeeded', replayed: false } }; receipts.set(String(body.operation_id), { ...result, operation: { ...result.operation, replayed: true } });
      if (options.loseUpload) return route.abort('failed'); return envelope(route, result);
    }
    return route.fulfill({ status: 404 });
  });
  return { writes, uploads, getEffects: () => effects };
}
