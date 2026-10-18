import { checkUi5Checkbox } from './ui5-controls';
import { expect, test } from '@playwright/test';
import { comLineId, comUnitId, mockCommercial, proposalId } from './commercial-fixture';
const path = `/commercial/proposals/${proposalId}`;
test.beforeEach(({ page }) => { page.on('pageerror', error => { throw error; }); });

test('company commercial creates a pursuit using an existing native party without Project requests', async ({ page }) => {
  const projectRequests: string[] = []; page.on('request', request => { if (/cipher_aec\.api\.v1\.projects?\b/.test(request.url())) projectRequests.push(request.url()); });
  const fixture = await mockCommercial(page); await page.goto('/commercial/pursuits');
  await expect(page.getByRole('heading', { name: 'Sales', exact: true })).toBeVisible();
  await expect(page.locator('ui5-select[accessible-name="Project context"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'New opportunity', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="New opportunity"]');
  await dialog.locator('ui5-select[accessible-name="Customer or lead"]').click(); await page.getByRole('option', { name: 'Existing native customer', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Name', exact: true }).fill('Created company-only pursuit');
  await dialog.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByText('Created company-only pursuit', { exact: true })).toBeVisible();
  expect(projectRequests).toEqual([]); expect(fixture.requests[0].body.party_id).toBe('TEST-CUSTOMER'); expect(fixture.requests[0].body).not.toHaveProperty('project');
});

test('proposal exact string editing preserves stable identity and compares saved native revisions', async ({ page }) => {
  const fixture = await mockCommercial(page); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Price line 1 quantity', exact: true }); await expect(quantity).toHaveValue('10'); await quantity.fill('11');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('note', { name: /Proposal revision 2 saved/ })).toBeVisible();
  const body = fixture.requests[0].body.composition as { price_lines: { id: string; quantity: string; unit_id: string }[] };
  expect(body.price_lines[0]).toMatchObject({ id: comLineId, quantity: '11', unit_id: comUnitId });
  await page.getByRole('button', { name: 'Compare changes', exact: true }).click();
  await expect(page.locator('ui5-table[accessible-name="Proposal revision line comparison"]')).toContainText('11'); expect(fixture.revisions.size).toBe(2);
});

for (const malformed of [false, true]) test(`proposal preserves original request through ${malformed ? 'incomplete success' : 'lost response'} and later permission denial`, async ({ page }) => {
  const fixture = await mockCommercial(page, { loseFirst: !malformed, malformedFirst: malformed, denyRecoveryOnce: true }); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Price line 1 quantity', exact: true }); await quantity.fill('11');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover', exact: true }); await expect(recover).toBeEnabled(); await expect(quantity).toBeDisabled();
  await recover.click(); await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible(); await expect(quantity).toBeDisabled();
  await recover.click(); await expect(page.getByRole('note', { name: /Proposal revision 2 saved.*Original operation recovered/ })).toBeVisible();
  expect(fixture.requests).toHaveLength(3); for (const request of fixture.requests) expect(request.body).toEqual(fixture.requests[0].body); expect(fixture.getEffects()).toBe(1); expect(fixture.revisions.size).toBe(2);
});

test('proposal stale rejection preserves authored input for explicit reviewed rebase', async ({ page }) => {
  const fixture = await mockCommercial(page, { staleFirst: true }); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Price line 1 quantity', exact: true }); await quantity.fill('11');
  await page.getByRole('button', { name: 'Save', exact: true }).click(); await expect(page.getByRole('note', { name: /The proposal changed\. Review the latest version before saving your changes\./ })).toBeVisible(); await expect(quantity).toHaveValue('11');
  await page.getByRole('button', { name: 'Review latest version', exact: true }).click();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the latest version', exact: true }));
  await page.getByRole('button', { name: 'Use latest version', exact: true }).click(); await expect(quantity).toHaveValue('11');
  await page.getByRole('button', { name: 'Save', exact: true }).click(); await expect(page.getByRole('note', { name: /Proposal revision 3 saved/ })).toBeVisible(); expect(fixture.requests[1].body.expected_revision).toBe(2);
});

test('an unknown proposal retry412 keeps original recovery and hides local head rebasing', async ({ page }) => {
  const fixture = await mockCommercial(page, { loseFirst: true, denyRecoveryOnce: true, denyRecoveryStatus: 412 }); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Price line 1 quantity', exact: true }); await quantity.fill('11'); await page.getByRole('button', { name: 'Save', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover', exact: true }); await recover.click(); await expect(page.getByRole('note', { name: /Proposal source changed/ })).toBeVisible(); await expect(recover).toBeEnabled(); await expect(quantity).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Review latest version', exact: true })).toHaveCount(0); await recover.click(); await expect(page.getByRole('note', { name: /Original operation recovered/ })).toBeVisible();
  expect(fixture.requests).toHaveLength(3); for (const request of fixture.requests) expect(request.body).toEqual(fixture.requests[0].body); expect(fixture.getEffects()).toBe(1);
});

for (const width of [1440, 900, 390]) test(`commercial price columns align and keyboard input stays usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockCommercial(page); await page.goto(path);
  const table = page.locator('ui5-table[accessible-name="Proposal prices"]'); const headers = table.getByRole('columnheader'); const cells = table.getByRole('row').nth(1).getByRole('gridcell');
  await expect(headers).toHaveCount(6); await expect(cells).toHaveCount(6);
  await expect.poll(async () => Math.max(...await Promise.all((await headers.all()).map(async (header, index) => { const a = await header.boundingBox(); const b = await cells.nth(index).boundingBox(); return !a || !b ? 999 : Math.max(Math.abs(a.x - b.x), Math.abs(a.width - b.width)); })))).toBeLessThanOrEqual(2);
  await page.getByRole('textbox', { name: 'Price line 1 description', exact: true }).press('Tab'); await expect(page.getByRole('textbox', { name: 'Price line 1 quantity', exact: true })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  for (const name of ['Add line', 'Paste rows']) { const box = await page.getByRole('button', { name, exact: true }).boundingBox(); expect(box).not.toBeNull(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width); }
});

test('commercial paste rejects invalid exact numbers without a write', async ({ page }) => {
  const fixture = await mockCommercial(page); await page.goto(path); await page.getByRole('button', { name: 'Paste rows', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Paste rows"]'); await dialog.getByRole('textbox', { name: 'Tab-separated commercial price lines', exact: true }).fill('Invalid exponent\t1e2\tMeter\t12.50'); await dialog.getByRole('button', { name: 'Add rows', exact: true }).click();
  await expect(dialog).toContainText('Row 1: enter a description, positive quantity, available unit, and rate.'); expect(fixture.requests).toHaveLength(0);
});

test('commercial scope denial contains no proposal lines or native totals', async ({ page }) => {
  await mockCommercial(page, { denied: true }); await page.goto(path); await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible(); await expect(page.getByRole('textbox', { name: 'Price line 1 quantity', exact: true })).toHaveCount(0); await expect(page.getByText('TEST-QUOTATION', { exact: true })).toHaveCount(0);
});
