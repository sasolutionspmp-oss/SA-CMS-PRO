import { expect, test, type Page } from '@playwright/test';
import { estimateId, mockEstimating, rateId, unitId } from './estimating-fixture';
import { projects } from './fixture';
const browserErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => { const errors: string[] = []; browserErrors.set(page, errors); page.on('pageerror', error => errors.push(error.stack || error.message)); });
test.afterEach(async ({ page }, info) => { const errors = browserErrors.get(page) || []; if (errors.length) await info.attach('browser-errors', { body: errors.join('\n\n'), contentType: 'text/plain' }); expect(errors).toEqual([]); });
const path = `/projects/${projects[0].id}/estimates/${estimateId}`;
const save = (page: import('@playwright/test').Page) => page.getByRole('button', { name: 'Calculate & save revision', exact: true }).last();

test('estimate editing sends exact text and recovers one original saved revision', async ({ page }, testInfo) => {
  const fixture = await mockEstimating(page, { loseFirst: true });
  await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true });
  await expect(quantity).toHaveValue('10.125');
  await quantity.fill('11.125');
  await page.getByRole('textbox', { name: 'Line 1 description', exact: true }).press('Tab');
  await expect(quantity).toBeFocused();
  await save(page).click();
  const recover = page.getByRole('button', { name: 'Recover calculation', exact: true }).last();
  await expect(recover).toBeEnabled();
  await expect(quantity).toBeDisabled();
  await recover.click();
  await expect(page.getByRole('note', { name: /Revision 2 saved.*Original operation recovered/ })).toBeVisible();
  expect(fixture.writes).toHaveLength(2);
  expect(fixture.writes[1]).toEqual(fixture.writes[0]);
  expect(fixture.writes[0].lines[0].quantity).toEqual({ amount: '11.125', unit_id: unitId, precision: 3 });
  expect(fixture.revisions.size).toBe(2);
  await page.getByRole('button', { name: 'Compare with predecessor', exact: true }).click();
  await expect(page.locator('ui5-table[accessible-name="Estimate revision comparison"]')).toContainText('139.06');
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-estimate-comparison.png'), fullPage: true });
});

test('stale estimate preserves authored edits through explicit review and rebase', async ({ page }) => {
  const fixture = await mockEstimating(page, { staleFirst: true });
  await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true });
  await quantity.fill('11.125'); await save(page).click();
  await expect(page.getByRole('note', { name: /Your local inputs are preserved/ })).toBeVisible();
  await expect(quantity).toHaveValue('11.125');
  await page.getByRole('button', { name: 'Load latest for comparison', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'I reviewed the latest saved revision changes', exact: true })).toBeVisible();
  await expect(quantity).toHaveValue('11.125');
  await page.getByRole('checkbox', { name: 'I reviewed the latest saved revision changes', exact: true }).check();
  await page.getByRole('button', { name: 'Rebase preserved inputs', exact: true }).click();
  await expect(quantity).toHaveValue('11.125'); await save(page).click();
  await expect(page.getByRole('note', { name: /Revision 3 saved/ })).toBeVisible();
  expect(fixture.writes[1].expected_revision).not.toBe(fixture.writes[0].expected_revision);
  expect(fixture.writes[1].lines[0].line_id).toBe(fixture.writes[0].lines[0].line_id);
});

test('paste is atomic and invalid decimals never reach calculation', async ({ page }) => {
  const fixture = await mockEstimating(page);
  await page.goto(path);
  await page.getByRole('button', { name: 'Paste rows', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Paste estimate rows"]');
  await dialog.getByRole('textbox', { name: 'Tab-separated estimate rows', exact: true }).fill(`Pasted exact row\t1.234\tm\t${rateId}\tTEST-PASTE\t0.05`);
  await dialog.getByRole('button', { name: 'Add pasted rows', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Line 2 quantity', exact: true })).toHaveValue('1.234');
  await page.getByRole('textbox', { name: 'Line 1 quantity', exact: true }).fill('1e2');
  await save(page).click();
  await expect(page.getByRole('list', { name: 'Estimate line validation', exact: true })).toContainText('exact nonnegative decimal');
  expect(fixture.writes).toHaveLength(0);
});

test('source inspection opens the exact cited text', async ({ page }) => {
  await mockEstimating(page);
  await page.goto(path);
  await page.getByRole('button', { name: 'Inspect line 1 source', exact: true }).click();
  const source = page.locator('ui5-dialog[header-text="Rate source"]');
  await expect(source).toContainText('TEST-QUOTE-001');
  await source.getByRole('link', { name: 'Site coordination requirements', exact: true }).click();
  await expect(page.locator('ui5-dialog[header-text="Estimate source text"] .source-text')).toContainText('Coordinate the temporary bypass plan');
});

for (const width of [1440, 900, 390]) test(`estimate numeric columns align at ${width}px without page overflow`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockEstimating(page); await page.goto(path);
  const table = page.locator('ui5-table[accessible-name="Editable estimate lines"]');
  await expect(table.getByRole('textbox', { name: 'Line 1 quantity', exact: true })).toHaveValue('10.125');
  const headers = table.getByRole('columnheader'); const cells = table.getByRole('row').nth(1).getByRole('gridcell');
  await expect(headers).toHaveCount(7); await expect(cells).toHaveCount(7);
  await expect.poll(async () => Math.max(...await Promise.all((await headers.all()).map(async (header, index) => { const a = await header.boundingBox(); const b = await cells.nth(index).boundingBox(); return !a || !b ? 999 : Math.max(Math.abs(a.x - b.x), Math.abs(a.width - b.width)); })))).toBeLessThanOrEqual(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  for (const name of ['Add line', 'Paste rows']) { const button = page.getByRole('button', { name, exact: true }); await expect(button).toBeVisible(); const box = await button.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width); }
  if (width === 390) await expect(page.locator('.estimate-editor-surface > ui5-toolbar > ui5-title')).toBeHidden();
  await page.getByRole('textbox', { name: 'Line 1 description', exact: true }).press('Tab');
  await expect(page.getByRole('textbox', { name: 'Line 1 quantity', exact: true })).toBeFocused();
});


test('estimate denial exposes no source rows or calculated totals', async ({ page }) => {
  await mockEstimating(page, { denied: true }); await page.goto(path);
  await expect(page.getByRole('note', { name: /Your current permissions/ })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Line 1 quantity', exact: true })).toHaveCount(0);
  await expect(page.getByText('126.56', { exact: true })).toHaveCount(0);
});

test('new estimate requires explicit currency and opens its persisted draft', async ({ page }) => {
  await mockEstimating(page, { empty: true });
  await page.goto(`/projects/${projects[0].id}/estimates`);
  await page.getByRole('button', { name: 'New estimate', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Create estimate draft"]');
  await expect(dialog.getByRole('textbox', { name: 'Estimate currency', exact: true })).toHaveValue('');
  await dialog.getByRole('textbox', { name: 'Estimate title', exact: true }).fill('Created contract estimate');
  await dialog.getByRole('textbox', { name: 'Estimate currency', exact: true }).fill('USD');
  await dialog.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Created contract estimate', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add line', exact: true })).toBeEnabled();
});

for (const mode of ['lost', 'malformed-json', 'malformed-contract', 'malformed-receipt', 'server-error'] as const) test(`create recovery retains exact request after ${mode} following one effect`, async ({ page }) => {
  const fixture = await mockEstimating(page, { empty: true, createFault: mode });
  await page.goto(`/projects/${projects[0].id}/estimates`);
  await page.getByRole('button', { name: 'New estimate', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Create estimate draft"]');
  const title = dialog.getByRole('textbox', { name: 'Estimate title', exact: true });
  const currency = dialog.getByRole('textbox', { name: 'Estimate currency', exact: true });
  await title.fill('Recover original draft'); await currency.fill('USD');
  await dialog.getByRole('button', { name: 'Create draft', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover draft', exact: true });
  await expect(recover).toBeEnabled();
  for (const input of [title, currency, dialog.getByRole('textbox', { name: 'Estimate pricing date', exact: true })]) await expect(input).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape'); await expect(dialog).toBeVisible();
  await page.keyboard.type('attempted edit'); await expect(title).toHaveValue('Recover original draft');
  await recover.click();
  await expect(page.getByRole('heading', { name: 'Recover original draft', exact: true })).toBeVisible();
  expect(fixture.createWrites).toHaveLength(2); expect(fixture.createWrites[1]).toEqual(fixture.createWrites[0]);
  expect(fixture.getCreateEffects()).toBe(1);
});

for (const mode of ['malformed-json', 'malformed-contract', 'malformed-receipt', 'server-error'] as const) test(`calculation recovery retains exact request after ${mode} following one effect`, async ({ page }) => {
  const fixture = await mockEstimating(page, { calculateFault: mode }); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true });
  await quantity.fill('11.125'); await save(page).click();
  const recover = page.getByRole('button', { name: 'Recover calculation', exact: true }).last();
  await expect(recover).toBeEnabled(); await expect(quantity).toBeDisabled();
  await page.keyboard.type('9'); await expect(quantity).toHaveValue('11.125');
  await recover.click();
  await expect(page.getByRole('note', { name: /Revision 2 saved.*Original operation recovered/ })).toBeVisible();
  expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1]).toEqual(fixture.writes[0]); expect(fixture.revisions.size).toBe(2);
});

test('definitive create rejection unlocks correction with a new operation', async ({ page }) => {
  const fixture = await mockEstimating(page, { empty: true, rejectCreateFirst: true });
  await page.goto(`/projects/${projects[0].id}/estimates`); await page.getByRole('button', { name: 'New estimate', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Create estimate draft"]');
  await dialog.getByRole('textbox', { name: 'Estimate title', exact: true }).fill('Corrected currency draft');
  const currency = dialog.getByRole('textbox', { name: 'Estimate currency', exact: true }); await currency.fill('EUR');
  await dialog.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(dialog).toContainText('Currency is not enabled.'); await expect(currency).toBeEnabled();
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeEnabled();
  await currency.fill('USD'); await dialog.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Corrected currency draft', exact: true })).toBeVisible();
  expect(fixture.createWrites[1].operation_id).not.toBe(fixture.createWrites[0].operation_id); expect(fixture.getCreateEffects()).toBe(1);
});

test('create remains unknown after a recovery permission denial until original receipt resolves', async ({ page }) => {
  const fixture = await mockEstimating(page, { empty: true, createFault: 'lost', denyRecoveryOnce: true });
  await page.goto(`/projects/${projects[0].id}/estimates`); await page.getByRole('button', { name: 'New estimate', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Create estimate draft"]');
  const title = dialog.getByRole('textbox', { name: 'Estimate title', exact: true });
  await title.fill('Original draft across permission changes'); await dialog.getByRole('textbox', { name: 'Estimate currency', exact: true }).fill('USD');
  await dialog.getByRole('button', { name: 'Create draft', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover draft', exact: true });
  await recover.click(); await expect(dialog.getByRole('note', { name: /Your current permissions/ })).toBeVisible();
  await expect(recover).toBeEnabled(); await expect(title).toBeDisabled(); await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape'); await expect(dialog).toBeVisible(); await recover.click();
  await expect(page.getByRole('heading', { name: 'Original draft across permission changes', exact: true })).toBeVisible();
  expect(fixture.createWrites).toHaveLength(3); for (const write of fixture.createWrites) expect(write).toEqual(fixture.createWrites[0]); expect(fixture.getCreateEffects()).toBe(1);
});

test('calculation remains unknown after a recovery permission denial until original receipt resolves', async ({ page }) => {
  const fixture = await mockEstimating(page, { loseFirst: true, denyRecoveryOnce: true }); await page.goto(path);
  const quantity = page.getByRole('textbox', { name: 'Line 1 quantity', exact: true });
  await quantity.fill('11.125'); await save(page).click();
  const recover = page.getByRole('button', { name: 'Recover calculation', exact: true }).last();
  await recover.click(); await expect(page.getByRole('note', { name: /Your current permissions/ })).toBeVisible();
  await expect(recover).toBeEnabled(); await expect(quantity).toBeDisabled(); await recover.click();
  await expect(page.getByRole('note', { name: /Revision 2 saved.*Original operation recovered/ })).toBeVisible();
  expect(fixture.writes).toHaveLength(3); for (const write of fixture.writes) expect(write).toEqual(fixture.writes[0]); expect(fixture.revisions.size).toBe(2);
});
