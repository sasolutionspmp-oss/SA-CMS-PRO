import { expect, test } from '@playwright/test';
import { company } from './fixture';
import { mockCostMasters } from './cost-masters-fixture';
test('cost navigation renders bundled Horizon icons and SAP 72 fonts without external assets', async ({ page, baseURL }) => {
  const expectedOrigin = new URL(baseURL!).origin;
  const loaderErrors: string[] = []; const external: string[] = [];
  page.on('console', event => { if (event.type() === 'error' && /No loader registered.*icons collection/.test(event.text())) loaderErrors.push(event.text()); });
  page.on('request', request => { if (new URL(request.url()).origin !== expectedOrigin) external.push(request.url()); });
  await mockCostMasters(page); await page.goto(`/company/costs/codes?company=${company}`); await expect(page.locator('ui5-table[accessible-name="Company dated cost masters"]')).toBeVisible();
  await expect(page.locator('ui5-side-navigation-item[text="Cost setup"] ui5-icon[name="settings"] svg path').first()).toHaveAttribute('d', /.+/);
  await page.evaluate(() => document.fonts.ready); expect(await page.evaluate(() => [...document.fonts].some(face => face.family === '72' && face.weight === '400' && face.status === 'loaded'))).toBe(true); expect(loaderErrors).toEqual([]); expect(external).toEqual([]);
});
for (const width of [1440, 900, 390]) test(`cost accounting target and status have separate spacing and plain version wording at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockCostMasters(page); await page.goto(`/company/costs/codes?company=${company}`);
  const table = page.locator('ui5-table[accessible-name="Company dated cost masters"]'); await expect(table).toBeVisible(); await expect(table).toContainText('Displayed rev. 1 · Latest saved rev. 2');
  const facts = table.locator('.cost-accounting-facts').first(); const target = facts.locator('.cost-accounting-target'); const status = facts.locator('.cost-accounting-status');
  await expect(target).toBeVisible(); await expect(status).toBeVisible(); const a = await target.boundingBox(); const b = await status.boundingBox(); expect(b!.y - a!.y - a!.height).toBeGreaterThanOrEqual(7);
  expect(await page.locator('.workspace-main').innerText()).not.toMatch(/canonical|authoring head|new-use eligibility/i);
  await expect.poll(() => page.locator('.workspace-main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
});
