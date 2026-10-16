import { expect, test, type Page, type Route } from '@playwright/test';
import { company, mockWorkspace } from './fixture';
const second = 'TEST-SECOND-COMPANY';
async function contextFixture(page: Page) {
  await mockWorkspace(page); let authenticated = false; const reads: URL[] = [];
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  await page.route('**/api/method/login', route => { authenticated = true; return route.fulfill({ contentType: 'application/json', body: '{"message":"Logged In"}' }); });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => authenticated ? envelope(route, { authenticated: true, user: 'source.reader@example.invalid', person: { id: 'TEST-SOURCE-READER', display_name: 'Source reader' }, companies: [company, second].map(id => ({ id, name: id })), company_scopes: [company, second].map(name => ({ company: name, capabilities: ['company.read', 'document.read'] })), capabilities: [], csrf_token: 'test-csrf', site_mode: 'synthetic' }) : route.fulfill({ status: 401, contentType: 'application/json', body: '{"message":{"schema":"cipher.api.v1","error":{"code":"unauthenticated","message":"Sign in to continue."}}}' }));
  const document = { id: 'TEST-SECOND-DOC', title: 'Second Company award evidence', company: second, scope_type: 'Company', project: null, current_revision: 'TEST-SECOND-REV', revision_number: 1, filename: 'award.txt', mime_type: 'text/plain', byte_length: 22, sha256: 'a'.repeat(64), scan_status: 'not_scanned', extraction_status: 'ready', page_count: 1 };
  await page.route('**/api/method/cipher_aec.documents.company_api.*', route => {
    const url = new URL(route.request().url()); reads.push(url); if (url.searchParams.get('company') !== second) return route.fulfill({ status: 404, contentType: 'application/json', body: '{"message":{"schema":"cipher.api.v1","error":{"code":"not_found","message":"This source is unavailable."}}}' });
    if (url.pathname.endsWith('get_document')) return envelope(route, { document, revisions: [{ ...document, id: document.current_revision }] });
    return envelope(route, { document_id: document.id, revision_id: document.current_revision, page: 1, page_count: 1, text: 'Exact second Company award evidence.', content_type: 'text/plain', citation: { document_id: document.id, revision_id: document.current_revision, page: 1 } });
  });
  return reads;
}
async function signIn(page: Page) { await page.getByLabel('Email or username', { exact: true }).fill('source.reader@example.invalid'); await page.getByLabel('Password', { exact: true }).fill('explicit-test-only'); await page.getByRole('button', { name: 'Sign in', exact: true }).click(); }
test('copied second-Company award evidence link preserves exact Company and revision through sign-in', async ({ page }) => {
  const attempted: URL[] = []; const responses: { url: URL; status: number }[] = []; const failures: { url: URL; error: string }[] = [];
  const isSource = (url: string) => url.includes('/api/method/cipher_aec.documents.company_api.');
  page.on('request', request => { if (isSource(request.url())) attempted.push(new URL(request.url())); });
  page.on('response', response => { if (isSource(response.url())) responses.push({ url: new URL(response.url()), status: response.status() }); });
  page.on('requestfailed', request => { if (isSource(request.url())) failures.push({ url: new URL(request.url()), error: request.failure()?.errorText || 'unclassified' }); });
  await contextFixture(page); await page.goto(`/company/documents/TEST-SECOND-DOC/revisions/TEST-SECOND-REV?page=1&company=${second}`); await signIn(page);
  await expect(page.getByRole('heading', { name: 'Second Company award evidence', exact: true })).toBeVisible(); await expect(page.locator('.company-source-text')).toHaveText('Exact second Company award evidence.');
  const identity = (url: URL) => {
    expect(url.searchParams.get('company')).toBe(second); expect(url.searchParams.has('project')).toBe(false);
    const method = url.pathname.split('.').at(-1); expect(['get_document', 'preview_revision']).toContain(method);
    if (method === 'get_document') { expect(url.searchParams.get('document_id')).toBe('TEST-SECOND-DOC'); return 'exact document'; }
    expect(url.searchParams.get('revision_id')).toBe('TEST-SECOND-REV'); expect(url.searchParams.get('page')).toBe('1'); return 'exact revision page';
  };
  // StrictMode may abort its initial detail effect before the replacement mount.
  // Every attempt still has to name the exact authorized Company/source. Only
  // successful response identities count as the two completed business reads.
  attempted.forEach(identity); expect(responses.map(row => ({ identity: identity(row.url), status: row.status }))).toEqual([{ identity: 'exact document', status: 200 }, { identity: 'exact revision page', status: 200 }]);
  failures.forEach(row => { expect(identity(row.url)).toBe('exact document'); expect(row.error).toBe('net::ERR_ABORTED'); }); expect(failures.length).toBeLessThanOrEqual(1); expect(attempted.length).toBe(responses.length + failures.length);
  await expect(page).toHaveURL(new RegExp(`company=${second}$`));
});
test('unavailable Company in a copied document link fails before source detail, preview or byte requests', async ({ page }) => {
  const reads = await contextFixture(page); await page.goto('/company/documents/TEST-SECOND-DOC/revisions/TEST-SECOND-REV?page=1&company=FOREIGN-COMPANY'); await signIn(page);
  await expect(page.getByRole('heading', { name: 'Company context unavailable', exact: true })).toBeVisible(); expect(reads).toEqual([]); await expect(page.locator('.company-source-text')).toHaveCount(0);
});
