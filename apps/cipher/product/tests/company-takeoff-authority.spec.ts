import { expect, test, type Page } from '@playwright/test';
import { caps, chooseSource, fillManual, mockCompanyTakeoff } from './company-takeoff-fixture';
const harness = '/tests/company-takeoff.html';
const context = (page: Page, detail: object) => page.evaluate(detail => window.dispatchEvent(new CustomEvent('test:takeoff-context', { detail })), detail);
test('a denied original recovery clears still-mounted source content without losing its UUID', async ({ page }) => {
  const f = await mockCompanyTakeoff(page, { fault: 'lost', denyRecovery: true }); await page.goto(harness); await fillManual(page); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original takeoff request', exact: true }); await expect(recover).toBeEnabled(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible(); await recover.click(); await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible();
  await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0); await expect(recover).toBeEnabled(); expect(f.writes[1]).toEqual(f.writes[0]);
});
for (const capability of ['document.read', 'estimate.read']) test(`known ${capability} loss clears source and preserves unknown original command across denied replay`, async ({ page }) => {
  const f = await mockCompanyTakeoff(page, { fault: 'lost', denyRecovery: true }); await page.goto(harness); await fillManual(page); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original takeoff request', exact: true }); await expect(recover).toBeEnabled();
  await context(page, { capabilities: caps.filter(c => c !== capability) }); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(page.getByRole('textbox', { name: 'Manual quantity', exact: true })).toHaveCount(0); await expect(recover).toBeEnabled();
  await recover.click(); await expect(recover).toBeEnabled(); await context(page, { capabilities: caps }); await recover.click(); await expect(page.getByRole('note', { name: /Manual measurement saved/ })).toBeVisible(); expect(f.writes).toHaveLength(3); expect(f.writes[1]).toEqual(f.writes[0]); expect(f.writes[2]).toEqual(f.writes[0]); expect(f.effects.size).toBe(1);
});
test('an existing global uncertain command locks all new takeoff source/manual controls', async ({ page }) => {
  await mockCompanyTakeoff(page); await page.goto(harness); await fillManual(page); await context(page, { navigationLocked: true }); await expect(page.getByRole('button', { name: 'Save manual measurement', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Company takeoff source', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Company takeoff sets', exact: true })).toBeDisabled();
});
for (const detail of [{ company: 'SECOND' }, { user: 'same-person-alias' }, { personId: 'OTHER-PERSON' }, { capabilities: [...caps, 'commercial.read'] }]) test(`authority change ${Object.keys(detail)[0]} clears selected source, form and original pixels`, async ({ page }) => {
  await mockCompanyTakeoff(page); await page.goto(harness); await fillManual(page); await context(page, detail); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(page.getByRole('textbox', { name: 'Manual quantity', exact: true })).toHaveCount(0);
});
test('late raw source bytes after authority change are aborted and never expose old pixels or form', async ({ page }) => {
  await mockCompanyTakeoff(page); let release!: () => void; let arrived!: () => void; const started = new Promise<void>(resolve => { arrived = resolve; }); const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/method/cipher_aec.documents.company_api.download_revision*', async route => { arrived(); await held; await route.fallback(); });
  await page.goto(harness); await chooseSource(page); await started; await context(page, { user: 'same-person-alias' }); release(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(page.getByRole('textbox', { name: 'Manual quantity', exact: true })).toHaveCount(0);
});
