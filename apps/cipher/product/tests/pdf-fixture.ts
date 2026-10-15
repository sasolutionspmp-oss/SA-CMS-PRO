import { createHash } from 'node:crypto';
import type { Page } from '@playwright/test';
import { mockEstimating } from './estimating-fixture';
import { company, projects } from './fixture';

// Explicit synthetic vector PDF bytes; no screenshot stands in for a PDF.
export function vectorPdf(rotation = 0) {
  const content = '2 w 0 0 0 RG 100 100 m 300 100 l 300 200 l 100 200 l h S\n';
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /CropBox [40 30 560 370] /Rotate ${rotation} /Resources << >> /Contents 4 0 R >>`, `<< /Length ${content.length} >>\nstream\n${content}endstream`];
  let text = '%PDF-1.7\n'; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(text)); text += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(text); text += `xref\n0 5\n0000000000 65535 f \n${offsets.slice(1).map(value => `${String(value).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(text);
}
export const takeoffPath = `/projects/${projects[0].id}/takeoff/40000000-0000-4000-8000-000000000001`;
export async function mockPdfTakeoff(page: Page, options: { rotation?: number; denySecond?: boolean; wrongHash?: boolean } = {}) {
  await mockEstimating(page);
  const bytes = vectorPdf(options.rotation); const sha = createHash('sha256').update(bytes).digest('hex');
  const envelope = (data: unknown) => ({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const document = { id: 'TEST-PDF-DOC', title: 'Synthetic rectangle drawing', company, project: projects[0].id, current_revision: 'TEST-PDF-REV-A', revision_number: 1, filename: 'synthetic-vector.pdf', mime_type: 'application/pdf', byte_length: bytes.length, sha256: options.wrongHash ? '0'.repeat(64) : sha, scan_status: 'not_scanned', extraction_status: 'ready', page_count: 1 };
  await page.route('**/api/method/cipher_aec.documents.api.list_documents*', route => route.fulfill(envelope({ items: [document] })));
  await page.route('**/api/method/cipher_aec.documents.api.get_document*', route => route.fulfill(envelope({ document, revisions: [{ id: 'TEST-PDF-REV-A', revision_number: 1, sha256: document.sha256 }, { id: 'TEST-PDF-REV-B', revision_number: 2, sha256: sha }] })));
  await page.route('**/api/method/cipher_aec.documents.api.download_revision*', route => options.denySecond && new URL(route.request().url()).searchParams.get('revision_id') === 'TEST-PDF-REV-B' ? route.fulfill({ status: 403 }) : route.fulfill({ contentType: 'application/pdf', body: bytes }));
  await page.route('**/api/method/cipher_aec.takeoff.api.*', route => {
    const method = new URL(route.request().url()).pathname.split('.').pop();
    if (method === 'get_record') return route.fulfill(envelope({ record: { id: '40000000-0000-4000-8000-000000000001', title: 'Synthetic PDF takeoff', discipline: 'Civil', drawing_package: 'TEST-PDF-PACKAGE', basis: 'Explicit synthetic contract fixture', company, project: projects[0].id } }));
    if (method === 'drawing_impact') return route.fulfill(envelope({ measurements: [], historical_results_changed: false, new_use_requires_explicit_successor: false }));
    return route.fulfill(envelope({ items: [], total: 0, next_cursor: null, limit: 30, count_mode: 'exact' }));
  });
  return { sha, bytes };
}
