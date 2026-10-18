import { expect, test } from '@playwright/test';
import { mockTakeoffBinding, savedLineId } from './takeoff-binding-fixture';
import { takeoffPath } from './pdf-fixture';
const select = async (page: import('@playwright/test').Page, label: string, option: string) => {
  const host = page.locator(`ui5-select[accessible-name="${label}"]`); await expect(host).toContainText(option);
  const choices = await host.locator('ui5-option').allTextContents(); const index = choices.findIndex(text => text === option); expect(index).toBeGreaterThanOrEqual(0);
  const control = page.getByRole('combobox', { name: label, exact: true }); await expect(control).toBeEnabled(); await control.press('Home'); for (let row = 0; row < index; row++) await control.press('ArrowDown'); await control.press('Enter'); await control.press('Escape');
};

test('saved measurement uses compact exact quantity, authorized revision choices and readable impact labels', async ({ page }) => {
  await mockTakeoffBinding(page); await page.goto(takeoffPath); await page.getByRole('button', { name: 'Inspect measurement', exact: true }).click();
  const summary = page.getByRole('region', { name: 'Saved measurement summary', exact: true }); await expect(summary).toContainText('200 m'); await expect(summary).toContainText('PDF measurement'); await expect(summary).toContainText('Verified scale'); await expect(summary).toContainText('Stale source');
  await page.getByText('Attach to a saved estimate line', { exact: true }).click(); await select(page, 'Binding estimate', 'Synthetic source-linked estimate');
  const revision = page.locator('ui5-select[accessible-name="Binding saved revision"]'); await expect(revision).toContainText('Rev. 2 · Current saved'); await expect(page.getByRole('textbox', { name: 'Binding revision ID', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Load earlier saved revisions', exact: true }).click(); await select(page, 'Binding saved revision', 'Rev. 1 · Previous'); await select(page, 'Binding saved line', 'Utility allowance · 200 m');
  await expect(page.getByRole('region', { name: 'Drawing change impact', exact: true })).toContainText('North utility reference segment'); await expect(page.getByRole('region', { name: 'Drawing change impact', exact: true })).toContainText('Utility allowance · Rev. 2');
  await page.getByRole('textbox', { name: 'Attachment reason', exact: true }).fill('Review saved evidence.'); await expect(page.getByRole('button', { name: 'Attach measurement evidence', exact: true })).toBeDisabled(); await page.getByRole('combobox', { name: 'Binding saved revision', exact: true }).press('Tab'); await expect.poll(() => page.locator('ui5-select[accessible-name="Binding saved line"]').evaluate(element => element.matches(':focus-within'))).toBe(true);
  for (const width of [1440, 900, 390]) { await page.setViewportSize({ width, height: 1000 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); expect(await summary.locator('.measurement-status').first().evaluate(element => parseFloat(getComputedStyle(element).fontSize))).toBeLessThanOrEqual(16); }
});

test('uncertain evidence binding locks saved revision and line choices and replays exact original identity', async ({ page }) => {
  const fixture = await mockTakeoffBinding(page, true, 'segment', true); await page.goto(takeoffPath); await page.getByRole('button', { name: 'Inspect measurement', exact: true }).click(); await page.getByText('Attach to a saved estimate line', { exact: true }).click(); await select(page, 'Binding estimate', 'Synthetic source-linked estimate'); await select(page, 'Binding saved line', 'Utility allowance · 200 m'); await page.getByRole('textbox', { name: 'Attachment reason', exact: true }).fill('Attach reviewed original evidence.'); await page.getByRole('button', { name: 'Attach measurement evidence', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover attachment', exact: true }); await expect(recover).toBeEnabled(); await expect(page.getByRole('combobox', { name: 'Binding saved revision', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Binding saved line', exact: true })).toBeDisabled(); fixture.revokeCurrentUse(); await page.getByRole('button', { name: 'Refresh takeoff', exact: true }).click(); await expect(page.getByRole('note', { name: /New attachment is unavailable/ })).toBeVisible(); await expect(recover).toBeEnabled(); await recover.click(); await expect(page.getByRole('note', { name: /Measurement attached to Utility allowance · Rev. 2/ })).toBeVisible(); expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1]).toEqual(fixture.writes[0]); expect(fixture.writes[0].estimate_line_record).toBe(savedLineId);
});


test('inspecting a saved rectangle restores its stored outline after the tool starts as a segment', async ({ page }) => {
  await mockTakeoffBinding(page, false, 'rectangle'); await page.goto(takeoffPath); await page.getByRole('button', { name: 'Inspect measurement', exact: true }).click();
  const drawing = page.locator('svg[aria-label="Drawing point selection"]'); await expect(drawing.locator('polygon')).toBeVisible(); await expect(drawing.locator('polyline')).toHaveCount(0); expect((await drawing.locator('polygon').getAttribute('points'))!.trim().split(/\s+/)).toHaveLength(4);
});
