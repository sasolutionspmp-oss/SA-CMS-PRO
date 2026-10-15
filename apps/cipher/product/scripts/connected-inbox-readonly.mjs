import { readFile, mkdir, writeFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { chromium, expect as baseExpect } from '@playwright/test';
const expect = baseExpect.configure({ timeout: 30000 });
const secret = JSON.parse(await readFile('/tmp/cipher-r0-runtime/company-chain-20b85fd4edd2.secret.json', 'utf8'));
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const output = process.env.CIPHER_CAPTURE_DIR || '/workspace/cipher-live-r2/company-inbox-responsive';
await mkdir(output, { recursive: true });
const reads = [], errors = [], network = [], expectedAuth = [], consoles = [], sources = {}, assets = new Set();
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const inventory = async path => { for (const entry of await readdir(new URL(path, import.meta.url), { withFileTypes: true })) { const child = `${path}/${entry.name}`; if (entry.isDirectory()) await inventory(child); else sources[child] = hash(await readFile(new URL(child, import.meta.url))); } };
await inventory('../src'); await inventory('../scripts');
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !message.text().includes('401')) consoles.push(message.text()); });
  page.on('request', request => { const path = new URL(request.url()).pathname; if (path.startsWith('/assets/') || path.startsWith('/pdfjs/')) assets.add(path); });
  page.on('response', async response => {
    const url = new URL(response.url());
    if (response.status() >= 400) { const item = { path: url.pathname, status: response.status() }; if (response.status() === 401 && url.pathname.endsWith('cipher_aec.api.v1.session')) expectedAuth.push(item); else network.push(item); }
    if (url.pathname.endsWith('cipher_aec.api.company_approvals.list_packets') && response.ok()) { const data = (await response.json()).message.data; reads.push({ url: response.url(), status: response.status(), count: data.items.length, count_mode: data.count_mode, total: data.total }); }
  });
  await page.route('**/api/method/cipher_aec.**', route => { if (route.request().method() === 'POST') throw new Error('Read-only qualification refuses every Cipher business mutation.'); return route.continue(); });
  await page.goto(base + '/company/work');
  await page.getByLabel('Email or username', { exact: true }).fill(secret.users.author.user);
  await page.getByLabel('Password', { exact: true }).fill(secret.users.author.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const company = page.locator('ui5-select[accessible-name="Company"]'); await expect(company).toBeVisible(); await company.click();
  await page.getByRole('option', { name: secret.company, exact: true }).click();
  const table = page.locator('ui5-table[accessible-name="Company approval inbox"]');
  await expect(table.locator('ui5-table-row')).toHaveCount(10);
  const geometry = [];
  for (const [width, label] of [[1440, 'desktop'], [900, 'tablet'], [390, 'phone']]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator('.loading-state')).toHaveCount(0);
    await expect.poll(() => page.locator('.workspace-main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    const title = page.getByRole('heading', { name: 'Company approvals', exact: true });
    const row = table.locator('ui5-table-row').first();
    const subject = row.locator('ui5-table-cell').first();
    const state = row.getByRole('group');
    const review = row.getByRole('button', { name: 'Review company packet', exact: true });
    const link = row.getByRole('link', { name: 'Open exact review', exact: true });
    const bounds = [];
    for (const locator of [title, subject, state, review, link]) {
      await expect(locator).toBeVisible();
      await expect.poll(async () => { const box = (await locator.boundingBox()); return box.x >= 0 && box.x + box.width <= width; }).toBe(true);
      bounds.push(await locator.boundingBox());
    }
    await review.focus(); await review.press('Tab'); await expect(link).toBeFocused();
    await expect.poll(() => page.locator('.workspace-main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    geometry.push({ width, content_bounds: bounds, workspace: await page.locator('.workspace-main').evaluate(element => ({ scroll_width: element.scrollWidth, client_width: element.clientWidth, scroll_left: element.scrollLeft })) });
    await page.screenshot({ path: `${output}/actual-inbox-responsive-${label}.png`, fullPage: true });
  }
  expect(reads.length).toBeGreaterThan(0); expect(reads.every(row => row.status === 200 && row.count_mode === 'none' && row.total === null && new URL(row.url).searchParams.get('limit') === '10')).toBe(true);
  if (errors.length || network.length || consoles.length) throw new Error('Unexpected browser or HTTP error.');
  const served = []; for (const path of assets) { const response = await page.request.get(base + path); expect(response.ok()).toBe(true); served.push({ path, sha256: hash(await response.body()) }); }
  await writeFile(`${output}/verification.json`, JSON.stringify({ mode: 'actual-frappe-company-inbox-responsive-readonly', captured_at: new Date().toISOString(), company: secret.company, reads, geometry, viewports: [1440, 900, 390], keyboard_review_to_exact_link: true, no_loading_at_capture: true, business_writes: 0, browser_errors: errors, unexpected_http_errors: network, unexpected_console_errors: consoles, expected_initial_401: expectedAuth, source_hashes: sources, served_assets: served, limits: 'Ordinary first-page visual qualification; cursor/auth scope separately qualified by backend QA. Previous clipped phone images are retained as failed historical evidence.' }, null, 2));
  console.log(`Actual responsive inbox read-only proof passed: ${output}`);
} finally { await browser.close(); }
