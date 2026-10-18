import { expect, test } from '@playwright/test';
import { company, measurement, mockCompanyTakeoff, pageOf, record, set, setId } from './company-takeoff-fixture';
for (const denied of [false, true]) test(`selected measurement clears immediately on page transition${denied ? ' and stays hidden on listing403' : ' to another authorized membership'}`, async ({ page }) => {
  await mockCompanyTakeoff(page); let release!: () => void; let entered!: () => void; const wait = new Promise<void>(resolve => { release = resolve; }); const arrived = new Promise<void>(resolve => { entered = resolve; });
  await page.route('**/api/method/cipher_aec.takeoff.company_api.list_records*', async route => {
    const url = new URL(route.request().url()); if (url.searchParams.get('kind') !== 'measurement') return route.fallback();
    const later = url.searchParams.has('cursor'); if (later) { entered(); await wait; }
    return route.fulfill({ status: later && denied ? 403 : 200, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', ...(later && denied ? { error: { code: 'source_unavailable', message: 'Current measurement list denied.' } } : { data: pageOf([record(later ? { ...measurement, id: '71000000-0000-4000-8000-000000000099', definition: { ...measurement.definition, locator: 'Second measurement page' } } : measurement)], later ? null : 'signed-measurement-next') }) } }) });
  });
  await page.goto(`/company/takeoff/${setId}?company=${company}`); await page.getByRole('button', { name: measurement.definition.locator, exact: true }).click(); await expect(page.getByRole('region', { name: 'Saved Company measurement', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next takeoff page', exact: true }).click(); await arrived;
  await expect(page.getByRole('region', { name: 'Saved Company measurement', exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'Open exact measurement source', exact: true })).toHaveCount(0);
  release(); if (denied) await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible(); else await expect(page.getByRole('button', { name: 'Second measurement page', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Saved Company measurement', exact: true })).toHaveCount(0);
});
test('three-page ancestor cursor cycle is a resource refusal before old rows or unsafe controls appear', async ({ page }) => {
  await mockCompanyTakeoff(page); const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/method/cipher_aec.takeoff.company_api.list_records*', route => {
    const url = new URL(route.request().url()); const cursor = url.searchParams.get('cursor'); const title = cursor === 'b' ? 'Untrusted third page' : cursor === 'a' ? 'Second page' : 'First page';
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data: pageOf([{ record: { ...set, title }, record_digest: 'd'.repeat(64) }], cursor === 'a' ? 'b' : 'a') } }) });
  });
  await page.goto(`/company/takeoff?company=${company}`); await expect(page.getByRole('button', { name: 'First page', exact: true })).toBeVisible(); await page.getByRole('button', { name: 'Next takeoff page', exact: true }).click(); await expect(page.getByRole('button', { name: 'Second page', exact: true })).toBeVisible(); await page.getByRole('button', { name: 'Next takeoff page', exact: true }).click();
  await expect(page.getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible(); await page.locator('.support-details').filter({ hasText: /could not be verified/ }).locator('summary').click(); await expect(page.locator('.support-details[open] > p').filter({ hasText: /could not be verified/ })).toBeVisible(); await expect(page.getByRole('button', { name: 'Untrusted third page', exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'Next takeoff page', exact: true })).toHaveCount(0); expect(errors).toEqual([]);
});
