import { expect, test, type Page } from '@playwright/test';
import { draftFixture } from './company-draft-save-fixture';
import { openSuggestions } from './company-ricky-proposals-fixture';

async function preview(page: Page) {
  await openSuggestions(page);
  await page.getByRole('button', { name: 'Review draft save', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Review the draft to save', exact: true })).toBeVisible();
}
async function confirm(page: Page, kind: 'scope' | 'estimate') {
  const save = page.getByRole('button', { name: `Save reviewed ${kind} draft`, exact: true });
  await expect(save).toBeDisabled();
  await page.getByRole('checkbox', { name: 'I reviewed the proposed draft and its original sources', exact: true }).click();
  await save.click();
}

for (const kind of ['scope','estimate'] as const) test(`human-reviewed ${kind} saves one linked canonical draft`, async ({ page }) => {
  const fixture = await draftFixture(page, { action: kind === 'scope' ? 'aec.scope.draft' : 'aec.estimate.draft' });
  await preview(page);
  if (kind === 'scope') await expect(page.getByText('Unverified author suggestion: Suggested scope', { exact: true })).toBeVisible();
  else await expect(page.getByText('1.000000000001 m', { exact: true })).toBeVisible();
  await confirm(page, kind);
  await expect(page.getByText(new RegExp(`Reviewed ${kind === 'scope' ? 'proposal' : 'estimate'} draft saved as revision 2`))).toBeVisible();
  expect(fixture.writes).toHaveLength(1); expect(fixture.effects()).toBe(1);
  await page.getByRole('button', { name: 'Close Ricky', exact: true }).click();
  await page.getByRole('button', { name: 'Toggle Ricky assistant' }).click();
  if (await page.getByRole('button', { name: 'Saved suggestions', exact: true }).isVisible()) await page.getByRole('button', { name: 'Saved suggestions', exact: true }).click();
  await page.getByRole('button', { name: 'Review draft save', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Saved draft', exact: true })).toBeVisible();
  expect(fixture.writes).toHaveLength(1);
});

for (const fault of ['lost','wrongReceipt'] as const) test(`${fault} save retains original operation across denial and locks panel/navigation`, async ({ page }) => {
  const fixture = await draftFixture(page, { [fault]: true });
  await preview(page); await confirm(page, 'scope');
  const recover = page.getByRole('button', { name: 'Recover original draft save', exact: true });
  await expect(recover).toBeVisible();
  await expect(page.getByRole('button', { name: 'Close Ricky', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Company reads', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Refresh suggestion access', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Stop this request', exact: true })).toBeDisabled();
  const path = page.url(); await page.getByRole('treeitem', { name: 'Projects', exact: true }).click(); expect(page.url()).toBe(path);
  fixture.deny(true); await recover.click(); await expect(recover).toBeEnabled();
  await expect(page.getByRole('region', { name: 'Saved suggestion review' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Review the draft to save', exact: true })).toHaveCount(0);
  fixture.deny(false); await recover.click();
  await expect(page.getByRole('heading', { name: 'Saved draft', exact: true })).toBeVisible();
  expect(fixture.writes).toHaveLength(3); expect(fixture.writes[1]).toEqual(fixture.writes[0]); expect(fixture.writes[2]).toEqual(fixture.writes[0]); expect(fixture.effects()).toBe(1);
});

for (const constraint of ['expired','denyWrite'] as const) test(`${constraint} suggestion remains reviewable with save disabled`, async ({ page }) => {
  const fixture = await draftFixture(page, { [constraint]: true });
  await preview(page);
  await expect(page.getByRole('button', { name: 'Save reviewed scope draft', exact: true })).toBeDisabled();
  await expect(page.getByRole('checkbox', { name: 'I reviewed the proposed draft and its original sources', exact: true })).toBeDisabled();
  expect(fixture.writes).toHaveLength(0);
});

test('stale original head is rejected without a recovery lock or an invented saved draft', async ({ page }) => {
  const fixture = await draftFixture(page, { stale: true });
  await preview(page); await confirm(page, 'scope');
  await expect(page.getByRole('note', { name: 'Error Message Strip The working revision changed.', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Recover original draft save', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Close Ricky', exact: true })).toBeEnabled();
  expect(fixture.effects()).toBe(0);
});

for (const width of [390,900]) test(`draft review and explicit save remain usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const fixture = await draftFixture(page, { action: 'aec.estimate.draft' });
  await preview(page);
  await expect(page.getByText('1.000000000001 m', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await confirm(page, 'estimate');
  await expect(page.getByRole('heading', { name: 'Saved draft', exact: true })).toBeVisible();
  expect(fixture.effects()).toBe(1);
});
