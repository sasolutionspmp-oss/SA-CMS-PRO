import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

// Read-only responsive verification of the previously persisted UI estimate.
const manifest = JSON.parse(await readFile(process.env.CIPHER_RUNTIME_MANIFEST || '/tmp/cipher-r0-runtime/fixture.secret.json', 'utf8'));
const prior = JSON.parse(await readFile(process.env.CIPHER_ESTIMATE_EVIDENCE || '/workspace/cipher-live-r1/estimating-draft-workspace/verification.json', 'utf8'));
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const output = new URL(process.env.CIPHER_CAPTURE_DIR || '/workspace/cipher-live-r1/estimating-responsive-correction/', import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
let stage = 'sign in';
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; const consoleErrors = []; const unexpectedHttp = []; const expectedAuth = [];
  let authenticated = false;
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (authenticated && message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('response', response => { if (response.status() >= 400) { const value = { path: new URL(response.url()).pathname, status: response.status() }; if (!authenticated && value.path.endsWith('cipher_aec.api.v1.session') && value.status === 401) expectedAuth.push(value); else unexpectedHttp.push(value); } });
  const url = `${base}/projects/${encodeURIComponent(manifest.project)}/estimates/${prior.created_estimate}`;
  await page.goto(url);
  await page.getByLabel('Email or username', { exact: true }).fill(manifest.users.primary.user);
  await page.getByLabel('Password', { exact: true }).fill(manifest.users.primary.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Line 1 quantity', exact: true })).toHaveValue('11'); authenticated = true;
  const measured = [];
  for (const [width, label] of [[1440, 'desktop'], [900, 'tablet'], [390, 'phone']]) {
    stage = `${label} responsive controls and numeric columns`;
    await page.setViewportSize({ width, height: 1000 }); await page.goto(url);
    await expect(page.getByRole('textbox', { name: 'Line 1 quantity', exact: true })).toHaveValue('11');
    const table = page.locator('ui5-table[accessible-name="Editable estimate lines"]');
    const headers = table.getByRole('columnheader'); const cells = table.getByRole('row').nth(1).getByRole('gridcell');
    await expect(headers).toHaveCount(7); await expect(cells).toHaveCount(7);
    await expect.poll(async () => Math.max(...await Promise.all((await headers.all()).map(async (header, index) => { const a = await header.boundingBox(); const b = await cells.nth(index).boundingBox(); return !a || !b ? 999 : Math.max(Math.abs(a.x - b.x), Math.abs(a.width - b.width)); })))).toBeLessThanOrEqual(2);
    const actionBoxes = [];
    for (const name of ['Add line', 'Paste rows']) {
      const button = page.getByRole('button', { name, exact: true }); await expect(button).toBeVisible(); const box = await button.boundingBox();
      if (!box || box.x < 0 || box.x + box.width > width) throw new Error('Editor action outside viewport.'); actionBoxes.push(box);
    }
    if (actionBoxes[0].x + actionBoxes[0].width > actionBoxes[1].x) throw new Error('Editor actions overlap.');
    if (width === 390) await expect(page.locator('.estimate-editor-surface > ui5-toolbar > ui5-title')).toBeHidden();
    if (!(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))) throw new Error('Page overflow.');
    await page.screenshot({ path: new URL(`connected-estimate-editor-${label}.png`, output).pathname, fullPage: true });
    await page.getByRole('textbox', { name: 'Line 1 description', exact: true }).press('Tab');
    await expect(page.getByRole('textbox', { name: 'Line 1 quantity', exact: true })).toBeFocused();
    await page.screenshot({ path: new URL(`connected-estimate-numeric-focus-${label}.png`, output).pathname, fullPage: true });
    measured.push({ width, numeric_columns: 7, header_body_tolerance_px: 2, action_boxes: actionBoxes, keyboard_description_to_quantity: true, no_page_overflow: true });
  }
  if (errors.length || consoleErrors.length || unexpectedHttp.length) throw new Error('Unexpected browser errors.');
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: 'actual-frappe-estimating-responsive-read-only', captured_at: new Date().toISOString(), estimate: prior.created_estimate, mocked_requests: false, business_writes: false, measured, browser_errors: errors, console_errors: consoleErrors, unexpected_http_errors: unexpectedHttp, expected_initial_authentication_responses: expectedAuth, historical_full_journey: '/workspace/cipher-live-r1/estimating-draft-workspace' }, null, 2));
  console.log('Actual estimate responsive controls, keyboard and geometry passed at1440/900/390. No business writes or credential output.');
} catch { console.error(`Responsive estimating verification failed at ${stage}. No credentials or authentication details logged.`); process.exitCode = 1; }
finally { await browser.close(); }
