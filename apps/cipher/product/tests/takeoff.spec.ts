import { expect, test } from '@playwright/test';
import { mockPdfTakeoff, takeoffPath } from './pdf-fixture';
test.use({ deviceScaleFactor: 2 });

for (const nativeRotation of [0, 90, 180, 270]) test(`PDF selection inverts native rotation ${nativeRotation}, crop, view rotation, zoom, CSS scale and DPR`, async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await mockPdfTakeoff(page, { rotation: nativeRotation }); await page.goto(takeoffPath);
  const drawing = page.locator('svg[aria-label="Drawing point selection"]'); await expect(drawing).toBeVisible();
  await page.locator('ui5-select[accessible-name="Drawing task"]').click(); await page.getByRole('option', { name: 'Calibrate scale', exact: true }).click();
  await page.locator('ui5-select[accessible-name="Drawing zoom"]').click(); await page.getByRole('option', { name: '150%', exact: true }).click();
  await expect(drawing).toBeVisible(); await page.getByRole('button', { name: 'Rotate view', exact: true }).click(); await expect(drawing).toBeVisible();
  await page.locator('.drawing-sheet').evaluate(element => { (element as HTMLElement).style.transform = 'scale(0.8)'; (element as HTMLElement).style.transformOrigin = 'top left'; });
  const totalRotation = (nativeRotation + 90) % 360; const scale = 1.5;
  // Independently known PDF point (300,200) and explicit orthogonal page formulas.
  const [x, y] = totalRotation === 0 ? [(300 - 40) * scale, (370 - 200) * scale] : totalRotation === 90 ? [(200 - 30) * scale, (300 - 40) * scale] : totalRotation === 180 ? [(560 - 300) * scale, (200 - 30) * scale] : [(370 - 200) * scale, (560 - 300) * scale];
  const rect = await drawing.boundingBox(); expect(rect).not.toBeNull(); await page.mouse.click(rect!.x + x * 0.8, rect!.y + y * 0.8);
  await expect(page.getByRole('textbox', { name: 'Point 1 X', exact: true })).toBeVisible();
  // Browser pointer dispatch quantizes fractional CSS positions. This is a
  // sub-pixel mapping bound, not a claim that pointing supplies exact geometry.
  expect(Math.abs(Number(await page.getByRole('textbox', { name: 'Point 1 X', exact: true }).inputValue()) - 300)).toBeLessThan(0.5);
  expect(Math.abs(Number(await page.getByRole('textbox', { name: 'Point 1 Y', exact: true }).inputValue()) - 200)).toBeLessThan(0.5);
  const canvas = page.locator('canvas[aria-label="Authorized stored PDF page"]');
  expect(await canvas.evaluate(element => (element as HTMLCanvasElement).width / parseFloat((element as HTMLCanvasElement).style.width))).toBeCloseTo(2, 2); expect(errors).toEqual([]);
});

test('a denied new drawing source hides every pixel of the previous source', async ({ page }) => {
  await mockPdfTakeoff(page, { denySecond: true }); await page.goto(takeoffPath);
  const canvas = page.locator('canvas[aria-label="Authorized stored PDF page"]'); await expect(canvas).toBeVisible();
  await page.locator('ui5-select[accessible-name="Takeoff drawing revision"]').click(); await page.getByRole('option', { name: 'Rev. 2 · Historical', exact: true }).click();
  await expect(page.getByRole('note', { name: /Your current permissions/ })).toBeVisible();
  await expect(canvas).toBeHidden(); await expect(page.locator('svg[aria-label="Drawing point selection"]')).toBeHidden();
});

test('PDF bytes with a different SHA cannot render or accept drawing points', async ({ page }) => {
  await mockPdfTakeoff(page, { wrongHash: true }); await page.goto(takeoffPath);
  await expect(page.getByRole('note', { name: /PDF bytes do not match this source revision/ })).toBeVisible();
  await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeHidden(); await expect(page.locator('svg[aria-label="Drawing point selection"]')).toHaveCount(0);
});
