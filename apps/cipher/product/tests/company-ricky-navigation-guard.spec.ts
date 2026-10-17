import { expect, test } from '@playwright/test';
import { openSuggestions, scopeInputs, suggestionFixture } from './company-ricky-proposals-fixture';

test('uncertain Company command keeps its original identity and mounted recovery through workspace controls', async ({ page }) => {
  const state = await suggestionFixture(page, { lostStart: true, twoCompanies: true });
  await openSuggestions(page);
  await scopeInputs(page);
  await page.getByRole('button', { name: 'Prepare scope suggestion', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original suggestion request', exact: true });
  await expect(recover).toBeEnabled();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  const originalUrl = page.url();
  await page.getByRole('treeitem', { name: 'Projects', exact: true }).click();
  await expect(page).toHaveURL(originalUrl);
  await expect(recover).toBeEnabled();
  await recover.click();
  await expect(page.getByRole('region', { name: 'Saved suggestion review', exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeEnabled();
  expect(state.requests).toHaveLength(2);
  expect(state.requests[1]).toEqual(state.requests[0]);
  expect(state.effects()).toBe(1);
  await page.getByRole('button', { name: 'Close Ricky', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Company saved suggestions', exact: true })).toHaveCount(0);
  await page.getByRole('treeitem', { name: 'Projects', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
});
