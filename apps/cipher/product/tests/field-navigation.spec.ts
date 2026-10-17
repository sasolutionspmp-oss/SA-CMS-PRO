import { expect, test, type Page, type Route } from '@playwright/test';
import { capabilities, expand, mockField, people, scope, seedDaily, source } from './field-fixture';
import { checkUi5Checkbox } from './ui5-controls';

const fieldRoot = `/projects/${encodeURIComponent(scope.project)}/field`;
const fieldApi = '/api/method/cipher_aec.field.api.';

async function shellFieldFixture(page: Page, options: { read?: boolean; loseFirst?: boolean; seed?: boolean } = {}) {
  const fixture = await mockField(page, { loseFirst: options.loseFirst, seed: options.seed });
  let actor = 0;
  const projectCaps = ['project.read', ...(options.read === false ? [] : capabilities)];
  const reads: URL[] = [], posts: { url: string; body: Record<string, unknown>; key?: string }[] = [], projectDetailReads: string[] = [], companyLibraryReads: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith(fieldApi)) {
      expect(url.pathname).toMatch(/^\/api\/method\/cipher_aec\.field\.api\.(list_records|get_record|create_record|revise_record|transition)$/);
      if (request.method() === 'POST') {
        const body = request.postDataJSON() as Record<string, unknown>; expect(body.company).toBe(scope.company); expect(body.project).toBe(scope.project);
        posts.push({ url: url.pathname, body, key: request.headers()['idempotency-key'] });
      } else { expect(url.searchParams.get('company')).toBe(scope.company); expect(url.searchParams.get('project')).toBe(scope.project); reads.push(url); }
    }
    if (/cipher_aec\.api\.v1\.(tasks|history)$/.test(url.pathname) || url.pathname.includes('cipher_aec.api.approvals.')) projectDetailReads.push(url.pathname);
    if (url.pathname.includes('cipher_aec.document_control.company_api.')) companyLibraryReads.push(url.pathname);
    if (url.pathname.endsWith('cipher_aec.documents.api.list_documents')) { expect(url.searchParams.get('company')).toBe(scope.company); expect(url.searchParams.get('project')).toBe(scope.project); }
  });
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const project = () => ({ id: scope.project, company: scope.company, name: 'Field project', version: '1', status: 'Open', capabilities: projectCaps });
  // The frozen Field fixture deliberately owns only Field RPCs. This overlay
  // supplies a complete authenticated shell and records excluded Project calls.
  await page.route('**/api/method/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/login')) return route.fulfill({ contentType: 'application/json', body: '{"message":"Logged In"}' });
    if (url.pathname.endsWith('cipher_aec.api.v1.session')) return envelope(route, { authenticated: true, user: people[actor].user, person: { id: people[actor].person, display_name: people[actor].user }, companies: [{ id: scope.company, name: scope.company }], company_scopes: [{ company: scope.company, capabilities: ['document.control.read'] }], capabilities: ['field.read'], csrf_token: 'fixture-csrf', site_mode: 'synthetic' });
    if (url.pathname.endsWith('cipher_aec.api.v1.projects')) return envelope(route, { items: [project()], next_cursor: null });
    if (url.pathname.endsWith('cipher_aec.api.v1.project')) { expect(url.searchParams.get('company')).toBe(scope.company); expect(url.searchParams.get('project')).toBe(scope.project); return envelope(route, project()); }
    if (/cipher_aec\.api\.v1\.(tasks|history)$/.test(url.pathname) || url.pathname.includes('cipher_aec.document_control.company_api.')) return envelope(route, { items: [], limit: 25, count_mode: 'none', total: null, next_cursor: null });
    return route.fallback();
  });
  return { ...fixture, reads, posts, projectDetailReads, companyLibraryReads, setActor: (index: number) => { actor = index; fixture.setActor(index); } };
}

for (const allowed of [true, false]) test(`Field navigation uses the current Project field.read capability (${allowed ? 'allowed' : 'denied'})`, async ({ page }) => {
  const fixture = await shellFieldFixture(page, { read: allowed });
  await page.goto(`/projects/${encodeURIComponent(scope.project)}/documents`);
  const navigation = page.getByRole('treeitem', { name: 'Field', exact: true });
  if (!allowed) {
    await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible(); await expect(navigation).toHaveCount(0);
    await page.goto(`${fieldRoot}/daily`); await expect(page.getByRole('note', { name: /Your current permissions do not allow this access or action/ })).toBeVisible(); expect(fixture.reads).toEqual([]);
  } else {
    await expect(navigation).toBeVisible(); await navigation.click(); await expect(page).toHaveURL(`${fieldRoot}/daily`);
    await expect(page.getByRole('heading', { name: 'Daily reports', exact: true })).toBeVisible(); await expect.poll(() => fixture.reads.length).toBeGreaterThan(0);
    expect(fixture.reads.every(url => url.searchParams.get('kind') === 'daily')).toBe(true);
  }
  expect(fixture.projectDetailReads).toEqual([]);
});

test('copied Field daily and ticket record routes preserve exact family, record, Company and Project', async ({ page }) => {
  const fixture = await shellFieldFixture(page, { seed: true });
  const daily = [...fixture.records.get('daily')!.values()][0];
  const ticketSeed = seedDaily(0, false), { superintendent, quantity_ids, ...common } = ticketSeed.revision;
  const ticket = { ...ticketSeed.header, number: 'TICKET-ROUTE-0001' };
  const revision = { ...common, definition: { local_date: '2026-10-17', title: 'Exact route ticket', customer_name: 'Fixture customer', location: 'East wall', work_description: 'Retained route fixture', potential_change_reference: '', lines: [{ kind: 'labor', description: 'Recorded work', quantity: '1.00', unit: 'hours', sources: [expand(source)] }] } };
  fixture.put('ticket', ticket); fixture.put('ticket_revision', revision);
  for (const [section, kind, record] of [['daily', 'daily', daily], ['tickets', 'ticket', ticket]] as const) {
    fixture.reads.length = 0; await page.goto(`${fieldRoot}/${section}/${encodeURIComponent(record.id)}`);
    await expect(page.getByText(`${record.number} · Revision 1`, { exact: true })).toBeVisible();
    await expect.poll(() => fixture.reads.some(url => url.pathname.endsWith('get_record') && url.searchParams.get('kind') === kind && url.searchParams.get('record_id') === record.id)).toBe(true);
    expect(fixture.reads.some(url => url.searchParams.get('kind') === `${kind}_revision` && url.searchParams.get('record_id') === record.current_revision)).toBe(true);
  }
  expect(fixture.projectDetailReads).toEqual([]); expect(fixture.posts).toEqual([]);
});

test('unknown Field save isolates navigation and recovers only the original person and request', async ({ page }) => {
  const fixture = await shellFieldFixture(page, { loseFirst: true }); await page.goto(`${fieldRoot}/daily`);
  await page.getByRole('button', { name: 'New daily report', exact: true }).click();
  await page.getByRole('textbox', { name: 'Report date (YYYY-MM-DD)', exact: true }).fill('2026-10-17');
  await page.getByRole('textbox', { name: 'Activities, one per line', exact: true }).fill('Exact original field shell observation.');
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this field draft', exact: true }));
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original field request', exact: true }); await expect(recover).toBeEnabled();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  const pinned = page.url(); await page.getByRole('treeitem', { name: 'Company library', exact: true }).click(); await expect(page).toHaveURL(pinned);
  await page.getByRole('treeitem', { name: 'Ricky', exact: true }).click(); await expect(page.locator('.workspace-frame')).not.toHaveClass(/with-assistant/);
  expect(await page.evaluate(() => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; })).toBe(true);
  await page.evaluate(() => { window.history.pushState({}, '', '/projects'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await expect(page).toHaveURL(pinned); await expect(recover).toBeEnabled(); expect(fixture.companyLibraryReads).toEqual([]);
  const signInAs = async (actor: number) => {
    fixture.setActor(actor); await page.evaluate(() => window.dispatchEvent(new Event('cipher:session-expired'))); await expect(recover).toBeDisabled();
    await page.getByRole('textbox', { name: 'Email or username', exact: true }).fill(people[actor].user); await page.getByLabel('Password', { exact: true }).fill('explicit-browser-fixture-only');
    const session = page.waitForResponse(response => response.url().endsWith('/api/method/cipher_aec.api.v1.session')); await page.getByRole('button', { name: 'Sign in', exact: true }).click(); await session;
    await expect(page.getByRole('heading', { name: 'Field', exact: true })).toBeVisible();
  };
  await signInAs(1); await expect(recover).toBeDisabled(); expect(fixture.posts).toHaveLength(1);
  await signInAs(0); await expect(recover).toBeEnabled(); await recover.click();
  await expect(page.getByRole('button', { name: 'Open saved field record', exact: true })).toBeEnabled();
  expect(fixture.posts).toHaveLength(2); expect(fixture.posts[1]).toEqual(fixture.posts[0]); expect(fixture.posts[0].key).toBe(fixture.posts[0].body.operation_id);
  expect(fixture.records.get('daily')!.size).toBe(1); expect(fixture.companyLibraryReads).toEqual([]); expect(fixture.projectDetailReads).toEqual([]);
});
