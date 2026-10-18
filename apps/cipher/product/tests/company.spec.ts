import { expect, test } from '@playwright/test';
import { mockCompany } from './company-fixture';
import { estimateId } from './estimating-fixture';
const path = `/company/estimates/${estimateId}`;
test.beforeEach(({ page }) => { page.on('pageerror', error => { throw error; }); });

for (const width of [1440, 900, 390]) test(`Company estimate title and actions remain usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const fixture = await mockCompany(page); await page.goto(path);
  const title = page.locator('.record-title').filter({ hasText: /^Synthetic source-linked estimate$/ });
  await expect(title).toBeInViewport();
  await expect.poll(async () => (await title.boundingBox())?.width || 0).toBeGreaterThan(120);
  expect((await title.boundingBox())!.height).toBeLessThan(150);
  const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true });
  await expect(quantity).toHaveValue('10.125');
  await quantity.fill('11.125');
  const calculate = page.getByRole('button', { name: 'Save', exact: true });
  if (!await calculate.isVisible()) await page.getByRole('button', { name: 'Estimate actions', exact: true }).click();
  await expect(calculate).toBeInViewport();
  const box = (await calculate.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width);
  await calculate.click();
  await expect(page.getByRole('note', { name: /Version 2 saved/ })).toBeVisible();
  expect(fixture.writes).toHaveLength(1);
});

test('Company estimate loads and calculates exact lines without Project authority parameters', async ({ page }) => {
  const requests: string[] = []; page.on('request', request => { if (/cipher_aec\.api\.v1\.projects?\b/.test(request.url())) requests.push(request.url()); });
  const fixture = await mockCompany(page); await page.goto(path); const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true }); await expect(quantity).toHaveValue('10.125'); await quantity.fill('11.125');
  await page.getByRole('button', { name: 'Save', exact: true }).click(); await expect(page.getByRole('note', { name: /Version 2 saved/ })).toBeVisible();
  expect(requests).toEqual([]); expect(fixture.writes).toHaveLength(1); expect(fixture.writes[0]).not.toHaveProperty('project'); expect(fixture.writes[0]).not.toHaveProperty('scope_type');
});

test('Company unknown calculation keeps exact recovery reachable through later412 without exposing rebase', async ({ page }) => {
  const fixture = await mockCompany(page, { loseCalculation: true, denyRetry412: true }); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true }); await quantity.fill('11.125'); await page.getByRole('button', { name: 'Save', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover', exact: true }); await expect(recover).toBeEnabled(); await recover.click();
  await expect(page.getByRole('note', { name: /Current source changed after the unknown result/ })).toBeVisible(); await expect(recover).toBeEnabled(); await expect(quantity).toBeDisabled(); await expect(page.getByRole('button', { name: 'Use latest version', exact: true })).toHaveCount(0);
  await recover.click(); await expect(page.getByRole('note', { name: /Version 2 saved.*Original request recovered/ })).toBeVisible();
  expect(fixture.writes).toHaveLength(3); for (const body of fixture.writes) expect(body).toEqual(fixture.writes[0]); expect(fixture.getEffects()).toBe(1);
});

test('a successful operation UUID with wrong estimate subject remains unknown until matching replay', async ({ page }) => {
  const fixture = await mockCompany(page, { wrongSubject: true }); await page.goto(path); const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true }); await quantity.fill('11.125'); await page.getByRole('button', { name: 'Save', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover', exact: true }); await expect(recover).toBeEnabled(); await expect(quantity).toBeDisabled(); await recover.click(); await expect(page.getByRole('note', { name: /Original request recovered/ })).toBeVisible(); expect(fixture.getEffects()).toBe(1); expect(fixture.writes[1]).toEqual(fixture.writes[0]);
});

test('Company upload recovery uses retained bytes after the local File becomes unreadable', async ({ page }) => {
  const fixture = await mockCompany(page, { loseUpload: true }); await page.goto('/company/documents'); await page.getByRole('button', { name: 'Add company document', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Add source document"]'); await dialog.getByRole('textbox', { name: 'Document title', exact: true }).fill('Retained Company upload'); await dialog.getByLabel('Source file', { exact: true }).setInputFiles({ name: 'retained.txt', mimeType: 'text/plain', buffer: Buffer.from('Explicit Company upload bytes.') }); await dialog.getByRole('button', { name: 'Add document', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover source upload', exact: true }); await expect(recover).toBeEnabled(); await expect(dialog.getByLabel('Source file', { exact: true })).toBeDisabled(); await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.evaluate(() => { File.prototype.arrayBuffer = async () => { throw new Error('Local File unavailable after original send.'); }; }); await recover.click(); await expect(page.getByRole('heading', { name: 'Retained Company upload', exact: true })).toBeVisible();
  expect(fixture.uploads).toHaveLength(2); expect(fixture.uploads[1]).toEqual(fixture.uploads[0]);
});

test('Company source text remains literal and source preview uses Company endpoint', async ({ page }) => {
  await mockCompany(page); await page.goto('/company/documents/TEST-COMPANY-DOC'); await expect(page.locator('.company-source-text')).toContainText('<script>window.companyInjected=true</script>'); expect(await page.evaluate(() => 'companyInjected' in window)).toBe(false); await expect(page.locator('ui5-select[accessible-name="Project context"]')).toHaveCount(0);
});


test('Company source revision links open the exact owned stored revision', async ({ page }) => {
  const previews: string[] = []; page.on('request', request => { if (request.url().includes('company_api.preview_revision')) previews.push(request.url()); });
  await mockCompany(page); await page.goto('/company/documents/TEST-COMPANY-DOC/revisions/TEST-COMPANY-REV?page=1'); await expect(page.locator('.company-source-text')).toContainText('Explicit synthetic Company source'); expect(previews).toHaveLength(1); expect(new URL(previews[0]).searchParams.get('revision_id')).toBe('TEST-COMPANY-REV');
});

test('a foreign Company revision link never reads bytes or preview under the wrong document title', async ({ page }) => {
  const sourceReads: string[] = []; page.on('request', request => { if (/company_api\.(preview_revision|download_revision)/.test(request.url())) sourceReads.push(request.url()); }); await mockCompany(page); await page.goto('/company/documents/TEST-COMPANY-DOC/revisions/FOREIGN-REVISION?page=1'); await expect(page.getByRole('note', { name: /This item isn’t available/ })).toBeVisible(); expect(sourceReads).toEqual([]); await expect(page.locator('.company-source-text')).toHaveCount(0);
});
