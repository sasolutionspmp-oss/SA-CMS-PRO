import { checkUi5Checkbox } from './ui5-controls';
import { expect, test } from '@playwright/test';
import { mockAwardEffect } from './award-effect-fixture';
import { awardIssue } from './award-fixture';
import { company } from './fixture';
const path = `/commercial/issues/${awardIssue}/award?company=${company}`;
const reviewPath = (id: string) => `/company/work/${id}?company=${company}`;
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));

test('award review opens the exact fixture PDF before independent Grant and preserves the frozen team and cost plan', async ({ page }) => {
  const fixture = await mockAwardEffect(page); await page.goto(path); await page.getByRole('button', { name: 'Request independent award review', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open exact award review', exact: true })).toHaveAttribute('href', reviewPath(fixture.packetId));
  fixture.setReviewer(true); await page.goto(reviewPath(fixture.packetId)); const dialog = page.locator('ui5-dialog[header-text="Review company approval packet"]'); await expect(dialog.getByRole('region', { name: 'Independent Project award review' })).toBeVisible(); await expect(dialog.getByText('One native schedule row: 100% of the selling value (USD 125.00) due 2026-10-15.', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Review awarded Issue PDF', exact: true }).click(); await expect(dialog.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible();
  await expect(dialog.locator('ui5-table[accessible-name="Reviewed award cost allocations"]')).toContainText('100.123456789');
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: 'I reviewed this exact company action and its sources', exact: true })); await dialog.getByRole('button', { name: 'Grant company approval', exact: true }).click(); await expect(dialog.getByRole('note', { name: /Approval granted/ })).toBeVisible();
  expect(fixture.writes.map(row => row.method)).toEqual(['request_action', 'decide_packet']); expect(fixture.effects()).toBe(0);
});
test('award execution refuses an old independent Grant receipt then recovers the exact original operation through later denial', async ({ page }) => {
  const fixture = await mockAwardEffect(page, { wrongGrant: true, denyRecovery: true }); fixture.grant(); await page.goto(reviewPath(fixture.packetId)); const dialog = page.locator('ui5-dialog[header-text="Review company approval packet"]');
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: 'I reviewed this exact company action and its sources', exact: true })); await dialog.getByRole('button', { name: 'Execute approved company action', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover company approval action', exact: true }); await expect(recover).toBeEnabled(); await expect(dialog.getByRole('button', { name: 'Close company review', exact: true })).toBeDisabled(); await recover.click(); await expect(recover).toBeEnabled(); await recover.click();
  await expect(dialog.getByRole('note', { name: /independently approved action was executed/ })).toBeVisible(); expect(fixture.effects()).toBe(1); expect(fixture.writes).toHaveLength(3); expect(new Set(fixture.writes.map(row => row.raw)).size).toBe(1); expect(new Set(fixture.writes.map(row => row.key)).size).toBe(1);
});
test('same-key refreshed adoption props are revalidated against the original immutable Company review', async ({ page }) => {
  const fixture = await mockAwardEffect(page, { adopted: true }); await page.goto(path); await expect(page.getByRole('region', { name: 'Recorded Company award' })).toBeVisible(); fixture.corruptReadback(); await page.getByRole('button', { name: 'Refresh award sources', exact: true }).click();
  await expect(page.getByRole('note', { name: /recorded award does not match its original reviewed plan/ })).toBeVisible(); await expect(page.getByRole('region', { name: 'Recorded Company award' })).toHaveCount(0);
});
test('adopted author sees Company completion without new draft actions or inferred Project access', async ({ page }) => {
  const projectReads: string[] = []; page.on('request', request => { if (/cipher_aec\.api\.v1\.projects?\b/.test(request.url())) projectReads.push(request.url()); }); const fixture = await mockAwardEffect(page, { adopted: true }); await page.goto(path);
  await expect(page.getByRole('region', { name: 'Recorded Company award' })).toBeVisible(); await expect(page.getByRole('link', { name: /Open.*authorized Project/ })).toHaveCount(0); await expect(page.getByRole('note', { name: /outside your current access/ }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save award plan', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Check award plan', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Request independent award review', exact: true })).toHaveCount(0); expect(fixture.writes).toEqual([]); expect(projectReads).toEqual([]);
});
test('lost award review request keeps the original saved-plan snapshot and same UUID after current access denial', async ({ page }) => {
  const fixture = await mockAwardEffect(page, { loseRequest: true, denyRecovery: true }); await page.goto(path); await page.getByRole('button', { name: 'Request independent award review', exact: true }).click(); const recover = page.getByRole('button', { name: 'Recover award review request', exact: true });
  await expect(recover).toBeEnabled(); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Refresh award sources', exact: true })).toBeDisabled(); await recover.click(); await expect(recover).toBeEnabled(); await recover.click(); await expect(page.locator('ui5-dialog[header-text="Review company approval packet"]')).toBeVisible(); expect(fixture.writes).toHaveLength(3); expect(new Set(fixture.writes.map(row => row.raw)).size).toBe(1); expect(new Set(fixture.writes.map(row => row.key)).size).toBe(1);
});

test('Company completion refuses an adoption linked to a superseded independent Grant', async ({ page }) => {
  const fixture = await mockAwardEffect(page, { adopted: true }); await page.goto(path); await expect(page.getByRole('region', { name: 'Recorded Company award' })).toBeVisible(); fixture.corruptDecision(); await page.getByRole('button', { name: 'Refresh award sources', exact: true }).click(); await expect(page.getByRole('note', { name: /recorded award does not match its original reviewed plan/ })).toBeVisible(); await expect(page.getByRole('region', { name: 'Recorded Company award' })).toHaveCount(0);
});
