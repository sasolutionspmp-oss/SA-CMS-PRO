import { expect, test } from '@playwright/test';
import { company, mockWorkspace, projects } from './fixture';

// Browser-only transport fixtures. Real image decoding/byte readback lives in the
// backend photo contracts; these cases establish no native HTTP or storage claim.
for (const mime of ['image/jpeg', 'image/png']) {
  test(`photo revision shows its actual ${mime} format without requesting text or a citation`, async ({ page }, testInfo) => {
    await mockWorkspace(page);
    const extension = mime === 'image/png' ? 'png' : 'jpeg';
    const label = mime === 'image/png' ? 'PNG image' : 'JPEG image';
    const photo = { id: 'TEST-PHOTO', title: 'Concrete placement photo', company, project: projects[0].id,
      current_revision: 'TEST-PHOTO-REV', revision_number: 1, filename: `placement.${extension}`, mime_type: mime,
      byte_length: 4321, sha256: 'b'.repeat(64), scan_status: 'not_scanned', retrieval_status: 'available',
      extraction_status: 'image_text_unavailable', page_count: 1 };
    let textRequests = 0;
    page.on('request', request => { if (/documents\.api\.(preview_revision|get_citation)/.test(request.url())) textRequests += 1; });
    await page.route('**/api/method/cipher_aec.documents.api.get_document*', route => route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ message: { schema: 'cipher.api.v1', data: { document: photo, revisions: [{ ...photo, id: photo.current_revision }] } } }) }));
    await page.goto(`/documents/${photo.id}`);
    await expect(page.getByRole('heading', { name: photo.title, exact: true })).toBeVisible();
    await expect(page.getByText(label, { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Source image', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Original image only', exact: true })).toBeVisible();
    await expect(page.getByText('Image text unavailable', { exact: true })).toBeVisible();
    await expect(page.getByText(/OCR and image interpretation are not configured; no source text or excerpt citation is available/)).toBeVisible();
    await expect(page.locator('.source-text')).toHaveCount(0);
    expect(textRequests).toBe(0);
    await page.screenshot({ path: testInfo.outputPath(`synthetic-contract-${extension}-original-only.png`), fullPage: true });
  });
}

test('historical photo uses selected revision facts and requests its authorized original after metadata access', async ({ page }) => {
  await mockWorkspace(page);
  const document = { id: 'TEST-PHOTO', title: 'Placement evidence', company, project: projects[0].id,
    current_revision: 'TEST-CURRENT-PDF', revision_number: 2, filename: 'placement-report.pdf', mime_type: 'application/pdf',
    byte_length: 98765, sha256: 'c'.repeat(64), scan_status: 'not_scanned', extraction_status: 'ready', page_count: 2 };
  const historical = { id: 'TEST-OLD-PHOTO', revision_number: 1, filename: 'placement-original.png', mime_type: 'image/png',
    byte_length: 123, sha256: 'b'.repeat(64), scan_status: 'not_scanned', extraction_status: 'image_text_unavailable' };
  const originalRequests: string[] = [];
  await page.route('**/api/method/cipher_aec.documents.api.get_document*', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ message: { schema: 'cipher.api.v1', data: { document, revisions: [historical, { ...document, id: document.current_revision }] } } }) }));
  await page.context().route('**/api/method/cipher_aec.documents.api.download_revision*', route => {
    originalRequests.push(route.request().url());
    return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1',
      error: { code: 'capability_denied', message: 'Current source access was revoked.' } } }) });
  });
  await page.goto(`/documents/${document.id}/revisions/${historical.id}`);
  await expect(page.getByRole('heading', { name: 'Original image only', exact: true })).toBeVisible();
  await expect(page.getByText('PNG image', { exact: true })).toBeVisible();
  await expect(page.getByText('123 bytes', { exact: true })).toBeVisible();
  await expect(page.getByText('97 KB', { exact: true })).toHaveCount(0);
  expect(originalRequests).toEqual([]);
  const popup = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Open original', exact: true }).click();
  const originalPage = await popup;
  await expect.poll(() => originalRequests.length).toBe(1);
  const request = new URL(originalRequests[0]);
  expect(request.searchParams.get('company')).toBe(company);
  expect(request.searchParams.get('revision_id')).toBe(historical.id);
  expect(request.pathname).toBe('/api/method/cipher_aec.documents.api.download_revision');
  await expect(originalPage.getByText(/Current source access was revoked/)).toBeVisible();
  await originalPage.close();
});

test('source upload chooser names the bounded photo formats and leaves acceptance to the server', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/projects/${projects[0].id}/documents`);
  await page.getByRole('button', { name: 'Add document', exact: true }).click();
  await expect(page.getByLabel('Source file', { exact: true })).toHaveAttribute('accept', /\.jpg,\.jpeg,\.png/);
  await expect(page.getByText(/Images have no OCR or image interpretation/)).toBeVisible();
});
