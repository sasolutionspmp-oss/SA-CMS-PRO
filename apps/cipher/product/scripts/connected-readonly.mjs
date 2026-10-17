import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { chromium, expect } from '@playwright/test';

// Explicit, authenticated runtime verification. No mocked requests or business writes.
// The manifest is private input; never print it or persist its credentials/cookies.
const manifest = JSON.parse(await readFile(process.env.CIPHER_RUNTIME_MANIFEST || '/tmp/cipher-r0-runtime/fixture.secret.json', 'utf8'));
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const output = new URL('../test-results/connected-runtime/', import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
async function alignedColumns(grid) {
  await expect(grid).toBeVisible();
  const headers = grid.getByRole('columnheader');
  const cells = grid.getByRole('row').nth(1).getByRole('gridcell');
  await expect(headers.first()).toBeVisible();
  await expect(cells).toHaveCount(await headers.count());
  await expect.poll(async () => Math.max(...await Promise.all((await headers.all()).map(async (header, index) => {
    const a = await header.boundingBox(); const b = await cells.nth(index).boundingBox();
    return !a || !b ? 999 : Math.max(Math.abs(a.x - b.x), Math.abs(a.width - b.width));
  })))).toBeLessThanOrEqual(2);
}
let stage = 'sign in';
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const credentials = manifest.users.primary;
  await page.goto(`${base}/projects`);
  await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toBeVisible();
  await page.screenshot({ path: new URL('connected-sign-in.png', output).pathname, fullPage: true });
  const username = page.getByLabel('Email or username', { exact: true });
  const password = page.getByLabel('Password', { exact: true });
  stage = 'empty username keyboard focus';
  await username.focus();
  await expect(username).toBeFocused();
  await page.screenshot({ path: new URL('connected-sign-in-keyboard-focus.png', output).pathname, fullPage: true });
  await username.fill(credentials.user);
  await page.keyboard.press('Tab');
  stage = 'password keyboard focus';
  await expect(password).toBeFocused();
  await password.fill(credentials.password);
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
  await page.keyboard.press('Tab');
  stage = 'sign in button keyboard focus';
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  stage = 'project register';
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await alignedColumns(page.getByRole('grid', { name: 'Projects', exact: true }));
  await page.screenshot({ path: new URL('connected-project-register.png', output).pathname, fullPage: true });
  stage = 'project detail';
  await page.goto(`${base}/projects/${encodeURIComponent(manifest.project)}`);
  await alignedColumns(page.locator('ui5-table[accessible-name="Project tasks"]'));
  await page.screenshot({ path: new URL('connected-project-object-page.png', output).pathname, fullPage: true });
  stage = 'local model status';
  await page.getByRole('button', { name: 'Toggle Ricky assistant', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ricky is not connected', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send question to Ricky', exact: true })).toBeDisabled();
  await alignedColumns(page.locator('ui5-table[accessible-name="Project tasks"]'));
  await page.screenshot({ path: new URL('connected-ricky-unavailable.png', output).pathname, fullPage: true });
  await page.getByRole('button', { name: 'Close Ricky', exact: true }).click();
  stage = 'document register navigation';
  await page.getByRole('button', { name: 'Manage documents', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible();
  stage = 'document register records';
  const documentLink = page.locator('ui5-table[accessible-name="Project documents"]').getByRole('link').first();
  await expect(documentLink).toBeVisible();
  stage = 'document table alignment';
  await alignedColumns(page.locator('ui5-table[accessible-name="Project documents"]'));
  await page.screenshot({ path: new URL('connected-document-register.png', output).pathname, fullPage: true });
  await documentLink.click();
  stage = 'document source';
  await expect(page.locator('.source-text')).toBeVisible();
  await page.screenshot({ path: new URL('connected-document-source.png', output).pathname, fullPage: true });
  stage = 'keyboard navigation';
  const navigationToggle = page.getByRole('button', { name: 'Toggle navigation', exact: true });
  await navigationToggle.focus();
  await expect(navigationToggle).toBeFocused();
  await page.keyboard.press('Enter');
  await page.screenshot({ path: new URL('connected-navigation-keyboard-focus.png', output).pathname, fullPage: true });
  await page.keyboard.press('Enter');
  await page.setViewportSize({ width: 900, height: 1000 });
  stage = 'tablet layout';
  await page.goto(`${base}/projects`);
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await expect(page.getByRole('grid', { name: 'Projects', exact: true })).toBeVisible();
  if (!(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))) throw new Error('Tablet layout overflowed the viewport.');
  await page.screenshot({ path: new URL('connected-project-register-tablet.png', output).pathname, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  stage = 'phone layout';
  await page.goto(`${base}/projects`);
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  if (!(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))) throw new Error('Phone layout overflowed the viewport.');
  await page.screenshot({ path: new URL('connected-project-register-mobile.png', output).pathname, fullPage: true });
  if (errors.length) throw new Error(`Browser reported ${errors.length} uncaught errors.`);
  stage = 'served build provenance';
  const html = await (await fetch(`${base}/index.html`)).text();
  const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^" ]+\.(?:js|css))"/g)].map(match => match[1]);
  const digest = value => createHash('sha256').update(value).digest('hex');
  const served = [];
  const sourceSnapshot = [];
  for (const asset of assets) {
    const response = await fetch(`${base}${asset}`); if (!response.ok) throw new Error('Served asset unavailable.');
    const bytes = Buffer.from(await response.arrayBuffer());
    const local = await readFile(new URL(`../dist${asset}`, import.meta.url));
    if (digest(bytes) !== digest(local)) throw new Error('Served and local bundles differ.');
    served.push({ path: asset, sha256: digest(bytes), byte_length: bytes.length });
    if (asset.endsWith('.js')) {
      const mapResponse = await fetch(`${base}${asset}.map`); if (!mapResponse.ok) throw new Error('Source provenance unavailable.');
      const mapBytes = Buffer.from(await mapResponse.arrayBuffer());
      const map = JSON.parse(mapBytes.toString());
      for (let index = 0; index < map.sources.length; index++) if (map.sources[index].includes('/src/') && !map.sources[index].includes('node_modules') && map.sourcesContent[index]) {
        sourceSnapshot.push({ path: map.sources[index], sha256: digest(map.sourcesContent[index]), content: map.sourcesContent[index] });
      }
      served.push({ path: `${asset}.map`, sha256: digest(mapBytes), byte_length: mapBytes.length });
    }
  }
  await writeFile(new URL('served-build-provenance.json', output), JSON.stringify({ captured_at: new Date().toISOString(), served, source_snapshot_from_served_source_map: sourceSnapshot, note: 'Hashes describe the served R0 build. Working approval source may be newer.' }, null, 2));
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: 'actual-frappe-read-only', origin: base, captured_at: new Date().toISOString(), browser_errors: errors.length, checks: ['sign in through the real UI form', 'authenticated same-origin session', 'persistent project register', 'project tasks and document context', 'rendered table header/body alignment within 2 pixels including assistant resize', 'honest unavailable local model', 'document original source text', 'desktop 1440, tablet 900 and phone 390 viewport without page overflow', 'keyboard login with Tab/Enter and focused navigation activation', 'served bundle and source snapshot hashes independent of newer working source'], mocked_requests: false, business_writes: false }, null, 2));
  console.log('Connected Frappe read-only journey passed; captures saved under product/test-results/connected-runtime. No credentials were logged.');
} catch {
  console.error(`Connected verification failed at ${stage}. Credentials and authentication errors were not logged.`);
  process.exitCode = 1;
} finally { await browser.close(); }
