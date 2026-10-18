import { expect, test, type Page, type Route } from '@playwright/test';
import { company, mockWorkspace } from './fixture';
import { companyDocument, mockNextDocuments, people, scope } from './document-control-next-fixture';
import { checkUi5Checkbox } from './ui5-controls';

const secondCompany = 'TEST/SECOND & Company';
const libraryPath = (companyId: string, tail = '') => `/company/library${tail ? `/${tail}` : ''}?company=${encodeURIComponent(companyId)}`;

async function navigationFixture(page: Page) {
  await mockWorkspace(page);
  const reads: URL[] = [], projectReads: URL[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.includes('/api/method/') && (url.searchParams.has('project') || /cipher_aec\.api\.v1\.projects?$/.test(url.pathname) || url.pathname.includes('cipher_aec.document_control.api.'))) projectReads.push(url);
  });
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => envelope(route, {
    authenticated: true, user: 'library.reader@example.invalid', person: { id: 'TEST-LIBRARY-READER', display_name: 'Library reader' },
    companies: [company, secondCompany].map(id => ({ id, name: id })),
    company_scopes: [{ company, capabilities: ['company.read'] }, { company: secondCompany, capabilities: ['company.read', 'document.control.read'] }],
    capabilities: [], csrf_token: 'test-csrf', site_mode: 'synthetic',
  }));
  await page.route('**/api/method/cipher_aec.api.v1.projects*', route => envelope(route, { items: [], next_cursor: null }));
  await page.route('**/api/method/cipher_aec.document_control.company_api.*', route => {
    expect(route.request().method()).toBe('GET');
    const url = new URL(route.request().url()); reads.push(url);
    expect(url.searchParams.get('company')).toBe(secondCompany); expect(url.searchParams.has('project')).toBe(false);
    return envelope(route, { items: [], limit: 25, count_mode: 'none', total: null, next_cursor: null });
  });
  return { reads, projectReads };
}

test('Company library navigation uses only the selected Company capability and an explicit encoded Company', async ({ page }) => {
  const fixture = await navigationFixture(page); await page.goto('/projects');
  await expect(page.getByRole('treeitem', { name: 'Company library', exact: true })).toHaveCount(0);
  await page.getByRole('combobox', { name: 'Company', exact: true }).click();
  await page.getByRole('option', { name: secondCompany, exact: true }).click();
  const library = page.getByRole('treeitem', { name: 'Company library', exact: true }); await expect(library).toBeVisible();
  await library.click(); await expect(page).toHaveURL(libraryPath(secondCompany));
  await expect(page.getByRole('heading', { name: 'Reusable documents', exact: true })).toBeVisible();
  await expect.poll(() => fixture.reads.length).toBeGreaterThan(0);
  expect(fixture.reads.every(url => url.searchParams.get('company') === secondCompany && !url.searchParams.has('project'))).toBe(true);
  await page.getByRole('combobox', { name: 'Company', exact: true }).click(); await page.getByRole('option', { name: company, exact: true }).click();
  await expect(page).toHaveURL(libraryPath(company));
  await expect(page.getByRole('treeitem', { name: 'Company library', exact: true })).toHaveCount(0);
  await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible();
});

test('copied Company library subroute keeps its exact Company and route tail without Project reads', async ({ page }) => {
  const fixture = await navigationFixture(page); await page.goto(libraryPath(secondCompany, 'register/rights'));
  await expect(page.getByRole('heading', { name: 'Content permissions', exact: true }).first()).toBeVisible();
  await expect.poll(() => fixture.reads.length).toBeGreaterThan(0);
  expect(fixture.reads.every(url => url.searchParams.get('kind') === 'rights')).toBe(true);
  expect(fixture.projectReads).toEqual([]);
});

test('unavailable Company in a copied library link fails before library or source reads', async ({ page }) => {
  const fixture = await navigationFixture(page); const sourceReads: string[] = [];
  page.on('request', request => { if (request.url().includes('cipher_aec.documents.company_api.')) sourceReads.push(request.url()); });
  await page.goto(libraryPath('FOREIGN-COMPANY', 'register/rights'));
  await expect(page.getByRole('heading', { name: 'Company unavailable', exact: true })).toBeVisible();
  expect(fixture.reads).toEqual([]); expect(fixture.projectReads).toEqual([]); expect(sourceReads).toEqual([]);
});

test('unknown Company library save keeps its mounted recovery and guards Company and browser history changes', async ({ page }) => {
  const fixture = await mockNextDocuments(page, { lose: 'company_create_library' });
  await page.goto(libraryPath(scope.company)); await page.getByRole('button', { name: 'New library entry', exact: true }).click();
  const namedDialog = page.getByRole('dialog', { name: 'New Company library entry', exact: true }); await expect(namedDialog).toBeVisible();
  const dialog = page.locator('ui5-dialog').filter({ has: namedDialog });
  for (const [name, value] of [['Library title', 'Company navigation recovery'], ['Discipline', 'Civil'], ['Ownership', 'Company authored'], ['Change reason', 'Explicit browser shell fixture']]) await dialog.getByRole('textbox', { name, exact: true }).fill(value);
  await dialog.getByRole('combobox', { name: 'Company library source', exact: true }).click();
  await page.getByRole('option', { name: `${companyDocument.title} · Rev. 1`, exact: true }).click();
  await dialog.getByRole('button', { name: 'Select company library source', exact: true }).click();
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: 'I reviewed this library record', exact: true }));
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover document save', exact: true }); await expect(recover).toBeEnabled();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true, includeHidden: true })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape'); await expect(namedDialog).toBeVisible(); await expect(recover).toBeEnabled();
  await page.locator('ui5-side-navigation-item[text="Ricky"]').evaluate(item => item.dispatchEvent(new MouseEvent('click', { bubbles: true })));
  await expect(page.locator('.workspace-frame')).not.toHaveClass(/with-assistant/);
  const pinned = page.url();
  expect(await page.evaluate(() => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; })).toBe(true);
  await page.evaluate(() => { window.history.pushState({}, '', '/projects'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await expect(page).toHaveURL(pinned); await expect(recover).toBeEnabled();
  await page.route('**/api/method/login', route => route.fulfill({ contentType: 'application/json', body: '{"message":"Logged In"}' }));
  const signInAs = async (actor: number) => {
    fixture.setActor(actor); await page.evaluate(() => window.dispatchEvent(new Event('cipher:session-expired')));
    await expect(page.getByRole('button', { name: 'Recover document save', exact: true })).toBeDisabled();
    await page.getByRole('textbox', { name: 'Email or username', exact: true }).fill(people[actor].user);
    await page.getByLabel('Password', { exact: true }).fill('explicit-browser-fixture-only');
    const session = page.waitForResponse(response => response.url().endsWith('/api/method/cipher_aec.api.v1.session'));
    await page.getByRole('button', { name: 'Sign in', exact: true }).click(); await session;
    await expect(page.getByRole('heading', { name: 'Reusable documents', exact: true })).toBeVisible();
  };
  await signInAs(1); const retainedRecovery = page.getByRole('button', { name: 'Recover document save', exact: true });
  await expect(retainedRecovery).toBeDisabled(); expect(fixture.writes).toHaveLength(1);
  await signInAs(0); await expect(retainedRecovery).toBeEnabled(); await retainedRecovery.click();
  await expect(retainedRecovery).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeEnabled();
  expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1]).toEqual(fixture.writes[0]); expect(fixture.companyRecords.get('library')!.size).toBe(2);
});
