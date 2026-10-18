import { expect, test } from '@playwright/test';
import { createAppProfile, failProfileDeletion, mockOfflineApp, offlinePath, sealAppCapture, signOutApp, storedProfileCount, unlockAppProfile } from './field-offline-app-fixture';
import { checkUi5Checkbox } from './ui5-controls';

test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));
test('normal App mounts offline Field and preserves a default profile while visiting another route in the same context', async ({ page }) => {
  await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page);
  await page.getByRole('treeitem', { name: 'Connections', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Connections', exact: true })).toBeVisible();
  expect(await storedProfileCount(page)).toBe(1);
  await page.getByRole('treeitem', { name: 'Offline field', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toBeVisible();
});
for (const target of ['project', 'company'] as const) test(`controlled ${target} replacement awaits default encrypted profile removal`, async ({ page }) => {
  await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page);
  await page.getByRole('combobox', { name: target === 'project' ? 'Project context' : 'Company', exact: true }).click();
  await page.getByRole('option', { name: target === 'project' ? 'Second Field project' : 'Second Company', exact: true }).click();
  await expect(page).toHaveURL(target === 'project' ? /\/projects\/SECOND-FIELD-PROJECT$/ : /\/projects$/);
  expect(await storedProfileCount(page)).toBe(0);
  await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toHaveCount(0);
});
for (const target of ['project', 'company', 'logout'] as const) test(`failed cleanup holds ${target} and reports truthful local storage failure`, async ({ page }) => {
  const fixture = await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page); await failProfileDeletion(page);
  if (target === 'logout') await signOutApp(page);
  else { await page.getByRole('combobox', { name: target === 'project' ? 'Project context' : 'Company', exact: true }).click(); await page.getByRole('option', { name: target === 'project' ? 'Second Field project' : 'Second Company', exact: true }).click(); }
  const failure = (target === 'logout' ? page.locator('ui5-dialog[header-text="Your workspace session"]') : page.locator('.workspace-main')).locator('.failure-state').filter({ hasText: /Local Field cleanup could not be verified/ }); await expect(failure.getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible(); await failure.locator('.support-details > summary').click(); await expect(failure.locator('.support-details > p', { hasText: /Local Field cleanup could not be verified/ })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(offlinePath + '$'));
  expect(fixture.logoutCount()).toBe(0); expect(await storedProfileCount(page)).toBe(1);
  await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toHaveCount(0);
  await page.evaluate(() => (window as any).restoreAppDelete());
  if (target === 'logout') { await page.getByRole('button', { name: 'Sign out', exact: true }).click(); await expect.poll(fixture.logoutCount).toBe(1); await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible(); }
  else { await page.getByRole('combobox', { name: target === 'project' ? 'Project context' : 'Company', exact: true }).click(); await page.getByRole('option', { name: target === 'project' ? 'Second Field project' : 'Second Company', exact: true }).click(); await expect(page).not.toHaveURL(new RegExp(offlinePath + '$')); }
  expect(await storedProfileCount(page)).toBe(0);
});
for (const retain of [false, true]) test(`controlled App logout clears the key and honors explicit encrypted retention ${retain}`, async ({ page }) => {
  const fixture = await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page, retain); await signOutApp(page);
  await expect.poll(fixture.logoutCount).toBe(1); await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toHaveCount(0);
  expect(await storedProfileCount(page)).toBe(retain ? 1 : 0);
});
for (const actor of [3, 1]) test(`normal App reload requires exact person ownership for alias or reassigned identity ${actor}`, async ({ page }) => {
  const fixture = await mockOfflineApp(page); await page.goto(offlinePath); const device = await createAppProfile(page, true);
  fixture.setActor(actor); await page.reload(); await unlockAppProfile(page, device);
  if (actor === 3) await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toBeVisible();
  else { await expect(page.getByRole('note', { name: /No encrypted profile exists/ })).toBeVisible(); await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toHaveCount(0); }
});
test('expired App identity hides plaintext and force removes a retained profile', async ({ page }) => {
  await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page, true);
  await page.evaluate(() => window.dispatchEvent(new Event('cipher:session-expired')));
  await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toHaveCount(0);
  await expect.poll(() => storedProfileCount(page)).toBe(0);
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
});
for (const status of [403, 404]) test(`normal App hides and purges a retained capture after current server denial ${status}`, async ({ page }) => {
  await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page, true); await sealAppCapture(page);
  await expect(page.getByText('App offline plaintext observation', { exact: true })).toBeVisible();
  await page.route('**/api/method/cipher_aec.field_offline.api.inspect_capture*', route => route.fulfill({ status, json: { message: { schema: 'cipher.api.v1', error: { code: 'source_unavailable', message: 'Source unavailable' } } } }));
  await page.getByRole('button', { name: 'Inspect original capture', exact: true }).click();
  await expect(page.getByText('App offline plaintext observation', { exact: true })).toHaveCount(0);
  await expect.poll(() => storedProfileCount(page)).toBe(0);
  await expect(page.getByRole('note', { name: /Current access was denied/ })).toBeVisible();
});
test('uncertain offline Apply keeps App context and logout locked until the exact original receipt is recovered', async ({ page }) => {
  const fixture = await mockOfflineApp(page, { loseApply: true }); await page.goto(offlinePath); await createAppProfile(page, true); await sealAppCapture(page);
  await page.getByRole('button', { name: 'Inspect original capture', exact: true }).click();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this sealed offline capture', exact: true }));
  await page.getByRole('button', { name: 'Apply selected capture', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Recover original offline request', exact: true })).toBeEnabled();
  const original = fixture.calls.find(row => row.method === 'apply_capture')!;
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeDisabled();
  await page.getByRole('treeitem', { name: 'Connections', exact: true }).click(); await expect(page).toHaveURL(new RegExp(offlinePath + '$'));
  await page.getByRole('button', { name: 'Offline app fixture author', exact: true }).click(); await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Recover original offline request', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Recover original offline request', exact: true })).toHaveCount(0);
  const attempts = fixture.calls.filter(row => row.method === 'apply_capture'); expect(attempts).toHaveLength(2); expect(attempts[1]).toEqual(original); expect(fixture.business.size).toBe(1);
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeEnabled();
});
for (const status of [403,404]) test(`a later ${status} cannot release an uncertain original offline Apply after local purge`, async ({ page }) => {
  const fixture = await mockOfflineApp(page, { loseApply: true }); await page.goto(offlinePath); await createAppProfile(page, true); await sealAppCapture(page);
  await page.getByRole('button', { name: 'Inspect original capture', exact: true }).click(); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this sealed offline capture', exact: true })); await page.getByRole('button', { name: 'Apply selected capture', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original offline request', exact: true }); await expect(recover).toBeEnabled();
  const original = fixture.calls.find(row => row.method === 'apply_capture')!; let deny = true;
  await page.route('**/api/method/cipher_aec.field_offline.api.apply_capture', route => deny ? route.fulfill({ status, json: { message: { schema: 'cipher.api.v1', error: { code: 'permission_denied', message: 'Current access denied' } } } }) : route.fallback());
  await recover.click(); await expect(recover).toBeEnabled(); await expect.poll(() => storedProfileCount(page)).toBe(0);
  await expect(page.getByText('App offline plaintext observation', { exact: true })).toHaveCount(0); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeDisabled();
  deny = false; await recover.click(); await expect(recover).toHaveCount(0); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeEnabled();
  const attempts = fixture.calls.filter(row => row.method === 'apply_capture'); expect(attempts).toHaveLength(2); expect(attempts[1]).toEqual(original); expect(fixture.business.size).toBe(1); expect(await storedProfileCount(page)).toBe(0);
});
test('revocation hides plaintext even when encrypted removal fails and reports the remaining local copy truthfully', async ({ page }) => {
  await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page, true); await sealAppCapture(page); await failProfileDeletion(page);
  await page.route('**/api/method/cipher_aec.field_offline.api.inspect_capture*', route => route.fulfill({ status: 403, json: { message: { schema: 'cipher.api.v1', error: { code: 'permission_denied', message: 'Current access denied' } } } }));
  await page.getByRole('button', { name: 'Inspect original capture', exact: true }).click(); await expect(page.getByText('App offline plaintext observation', { exact: true })).toHaveCount(0); await expect(page.getByRole('note', { name: /encrypted profile removal could not be verified/ })).toBeVisible(); expect(await storedProfileCount(page)).toBe(1);
});
for (const target of ['project','company','logout'] as const) test(`controlled ${target} waits for the actual IndexedDB cleanup transaction to commit`, async ({ page }) => {
  const fixture = await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page);
  await page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open('cipher-field-offline-v1', 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    const transaction = db.transaction('encrypted_profiles', 'readwrite'), store = transaction.objectStore('encrypted_profiles'); let hold = true;
    (window as any).releaseStorageHold = () => { hold = false; };
    const keepOpen = () => { const request = store.getAllKeys(); request.onsuccess = () => { if (hold) keepOpen(); }; }; keepOpen(); transaction.oncomplete = () => db.close();
  });
  if (target === 'logout') await signOutApp(page);
  else { await page.getByRole('combobox', { name: target === 'project' ? 'Project context' : 'Company', exact: true }).click(); await page.getByRole('option', { name: target === 'project' ? 'Second Field project' : 'Second Company', exact: true }).click(); }
  await expect(page).toHaveURL(new RegExp(offlinePath + '$')); expect(fixture.logoutCount()).toBe(0); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled(); await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toHaveCount(0);
  await page.evaluate(() => (window as any).releaseStorageHold());
  if (target === 'logout') { await expect.poll(fixture.logoutCount).toBe(1); await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible(); }
  else await expect(page).not.toHaveURL(new RegExp(offlinePath + '$'));
  expect(await storedProfileCount(page)).toBe(0);
});
test('browser history project replacement holds the current route on cleanup failure and retries after storage recovers', async ({ page }) => {
  await mockOfflineApp(page); await page.goto(offlinePath); await createAppProfile(page); await failProfileDeletion(page);
  const move = () => page.evaluate(() => { history.pushState({}, '', '/projects/SECOND-FIELD-PROJECT'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await move(); const failure = page.locator('.workspace-main').locator('.failure-state').filter({ hasText: /Local Field cleanup could not be verified/ }); await expect(failure.getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible(); await failure.locator('.support-details > summary').click(); await expect(failure.locator('.support-details > p', { hasText: /Local Field cleanup could not be verified/ })).toBeVisible(); await expect(page).toHaveURL(new RegExp(offlinePath + '$')); expect(await storedProfileCount(page)).toBe(1);
  await page.evaluate(() => (window as any).restoreAppDelete()); await move(); await expect(page).toHaveURL(/\/projects\/SECOND-FIELD-PROJECT$/); expect(await storedProfileCount(page)).toBe(0);
});
