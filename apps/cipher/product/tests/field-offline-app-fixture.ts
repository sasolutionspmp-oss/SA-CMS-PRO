import { expect, type Page } from '@playwright/test';
import { mockOffline, passphrase, people, scope } from './field-offline-fixture';
import { checkUi5Checkbox } from './ui5-controls';

export const offlinePath = `/projects/${scope.project}/field/offline`;
export async function mockOfflineApp(page: Page, options: Parameters<typeof mockOffline>[1] = {}) {
  const fixture = await mockOffline(page, options);
  let actor = 0, signedIn = true, logoutCount = 0;
  const projects = [scope.project, 'SECOND-FIELD-PROJECT'].map(id => ({ id, company: scope.company, name: id === scope.project ? 'Field project' : 'Second Field project', status: 'Open', version: 'v1', expected_start_date: null, expected_end_date: null, capabilities: ['field.read', 'field.write'] }));
  await page.route('**/api/method/cipher_aec.api.v1.*', async route => {
    const url = new URL(route.request().url()), method = url.pathname.split('.').at(-1);
    const envelope = (data: unknown) => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data } } });
    if (method === 'session') return envelope({ authenticated: signedIn, user: people[actor].user, person: { id: people[actor].person, display_name: 'Offline app fixture author' }, companies: [{ id: scope.company, name: 'Fixture Company' }, { id: 'SECOND-COMPANY', name: 'Second Company' }], company_scopes: [{ company: scope.company, capabilities: [] }, { company: 'SECOND-COMPANY', capabilities: [] }], capabilities: [], csrf_token: 'fixture-csrf', site_mode: 'synthetic' });
    if (method === 'projects') return envelope({ items: url.searchParams.get('company') === scope.company ? projects : [], next_cursor: null, total: 2, count_mode: 'exact', limit: 50 });
    if (method === 'project') return envelope(projects.find(row => row.id === url.searchParams.get('project')));
    if (method === 'tasks' || method === 'history') return envelope({ items: [], next_cursor: null, total: 0, count_mode: 'exact', limit: 50 });
    throw new Error(`Unhandled App fixture core read: ${method}`);
  });
  await page.route('**/api/method/cipher_aec.ricky.api.connection_status', route => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data: { available: false, message: 'Synthetic fixture: model unavailable.' } } } }));
  await page.route('**/api/method/cipher_aec.api.approvals.list_packets*', route => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data: { items: [], next_cursor: null, total: 0, count_mode: 'exact', limit: 50 } } } }));
  await page.route('**/api/method/logout', route => { logoutCount++; signedIn = false; return route.fulfill({ json: { message: 'Logged out' } }); });
  return { ...fixture, projects, logoutCount: () => logoutCount, setActor: (index: number) => { actor = index; fixture.setActor(index); } };
}
export async function createAppProfile(page: Page, retain = false) {
  await page.getByRole('button', { name: 'Choose new registration UUID', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Offline device UUID', exact: true })).toHaveValue(/^[a-f0-9]{8}-/);
  const device = await page.getByRole('textbox', { name: 'Offline device UUID', exact: true }).inputValue();
  await page.getByRole('textbox', { name: 'Local vault passphrase', exact: true }).fill(passphrase);
  await page.getByText('Create a local profile', { exact: true }).click();
  await page.getByRole('textbox', { name: 'Offline profile label', exact: true }).fill('App encrypted Field profile');
  await page.getByRole('textbox', { name: 'Confirm local vault passphrase', exact: true }).fill(passphrase);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'Opt in to encrypted local storage', exact: true }));
  if (retain) await checkUi5Checkbox(page.getByRole('checkbox', { name: 'Retain encrypted profile on logout', exact: true }));
  await page.getByRole('button', { name: 'Create encrypted profile', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'App encrypted Field profile', exact: true })).toBeVisible();
  return device;
}
export async function unlockAppProfile(page: Page, device: string) {
  await page.getByRole('textbox', { name: 'Offline device UUID', exact: true }).fill(device);
  await page.getByRole('textbox', { name: 'Local vault passphrase', exact: true }).fill(passphrase);
  await page.getByRole('button', { name: 'Unlock profile', exact: true }).click();
}
export async function storedProfileCount(page: Page) {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open('cipher-field-offline-v1', 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    try { return await new Promise<number>((resolve, reject) => { const transaction = db.transaction('encrypted_profiles', 'readonly'), request = transaction.objectStore('encrypted_profiles').count(); let count = 0; request.onsuccess = () => { count = request.result; }; transaction.oncomplete = () => resolve(count); transaction.onabort = () => reject(transaction.error); }); } finally { db.close(); }
  });
}
export async function failProfileDeletion(page: Page) {
  await page.evaluate(() => { const original = IDBObjectStore.prototype.delete; (window as any).restoreAppDelete = () => { IDBObjectStore.prototype.delete = original; }; IDBObjectStore.prototype.delete = function() { throw new DOMException('Synthetic cleanup failure', 'UnknownError'); }; });
}
export async function signOutApp(page: Page) {
  await page.getByRole('button', { name: 'Offline app fixture author', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
}

export async function sealAppCapture(page: Page) {
  await page.getByRole('button', { name: 'Register device online', exact: true }).click();
  await page.getByRole('button', { name: 'New offline capture', exact: true }).click();
  await page.getByRole('textbox', { name: 'Report date (YYYY-MM-DD)', exact: true }).fill('2026-10-17');
  await page.getByRole('textbox', { name: 'Activities, one per line', exact: true }).fill('App offline plaintext observation');
  await page.getByRole('textbox', { name: 'Capture time with UTC offset', exact: true }).fill('2026-10-17T11:00:00-04:00');
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this offline capture', exact: true }));
  await page.getByRole('button', { name: 'Seal encrypted capture', exact: true }).click();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this sealed offline capture', exact: true }));
  await page.getByRole('button', { name: 'Stage selected capture', exact: true }).click();
}
