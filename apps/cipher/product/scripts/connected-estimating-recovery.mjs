import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

// One real synthetic-site create. Only delivery of its first committed response
// is fault-injected. A subsequent receipt-access denial is injected separately;
// the original and successful replay writes/readback reach actual Frappe.
const manifest = JSON.parse(await readFile(process.env.CIPHER_RUNTIME_MANIFEST || '/tmp/cipher-r0-runtime/fixture.secret.json', 'utf8'));
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const output = new URL(process.env.CIPHER_CAPTURE_DIR || '/workspace/cipher-live-r1/estimating-create-recovery-final/', import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
let stage = 'sign in';
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = []; const consoleErrors = []; const unexpectedHttp = []; const expectedAuth = []; const expectedFaults = [];
  const rpcPath = '/api/method/cipher_aec.estimating.api.create_estimate';
  let authenticated = false; let injected = false; let denialInjected = false;
  page.on('pageerror', error => browserErrors.push(error.message));
  page.on('console', message => {
    if (!authenticated || message.type() !== 'error') return;
    const value = { message: message.text(), path: new URL(message.location().url || base).pathname };
    if (injected && value.path === rpcPath && (/ERR_FAILED/.test(value.message) || (denialInjected && /403/.test(value.message)))) expectedFaults.push(value); else consoleErrors.push(value);
  });
  page.on('requestfailed', request => {
    const value = { path: new URL(request.url()).pathname, error: request.failure()?.errorText };
    if (injected && value.path === rpcPath) expectedFaults.push(value); else unexpectedHttp.push(value);
  });
  page.on('response', response => {
    if (response.status() < 400) return;
    const value = { path: new URL(response.url()).pathname, status: response.status() };
    if (!authenticated && value.path.endsWith('cipher_aec.api.v1.session') && value.status === 401) expectedAuth.push(value);
    else if (denialInjected && value.path === rpcPath && value.status === 403) expectedFaults.push(value);
    else unexpectedHttp.push(value);
  });
  await page.goto(`${base}/projects/${encodeURIComponent(manifest.project)}/estimates`);
  await page.getByLabel('Email or username', { exact: true }).fill(manifest.users.primary.user);
  await page.getByLabel('Password', { exact: true }).fill(manifest.users.primary.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Estimates', exact: true })).toBeVisible(); authenticated = true;
  const requests = []; const receipts = [];
  await page.route(`**${rpcPath}`, async route => {
    const request = route.request(); const body = request.postDataJSON();
    expect(request.headers()['idempotency-key']).toBe(body.operation_id);
    requests.push(request.postData());
    if (injected && !denialInjected) {
      denialInjected = true;
      return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Injected current receipt-access denial.' } } }) });
    }
    const response = await route.fetch(); expect(response.status()).toBe(200);
    const receipt = (await response.json()).message.data; expect(receipt.operation.status).toBe('succeeded'); receipts.push(receipt);
    if (!injected) { injected = true; return route.abort('failed'); }
    return route.fulfill({ response });
  });
  stage = 'committed create with injected lost delivery';
  await page.getByRole('button', { name: 'New estimate', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Create estimate draft"]');
  const title = `Synthetic response recovery ${crypto.randomUUID().slice(0, 8)}`;
  const titleInput = dialog.getByRole('textbox', { name: 'Estimate title', exact: true });
  await titleInput.fill(title);
  await dialog.getByRole('textbox', { name: 'Estimate currency', exact: true }).fill('USD');
  await dialog.getByRole('button', { name: 'Create draft', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover draft', exact: true });
  await expect(recover).toBeEnabled();
  for (const name of ['Estimate title', 'Estimate currency', 'Estimate pricing date']) await expect(dialog.getByRole('textbox', { name, exact: true })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape'); await expect(dialog).toBeVisible();
  await page.keyboard.type('attempted edit'); await expect(titleInput).toHaveValue(title);
  await page.screenshot({ path: new URL('actual-create-result-unknown.png', output).pathname, fullPage: true });
  stage = 'injected receipt denial preserves original uncertainty';
  await recover.click(); await expect(dialog.getByRole('note', { name: /Your current permissions/ })).toBeVisible();
  await expect(recover).toBeEnabled(); await expect(titleInput).toBeDisabled(); await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape'); await expect(dialog).toBeVisible();
  await page.screenshot({ path: new URL('actual-create-still-unknown-after-injected-denial.png', output).pathname, fullPage: true });
  stage = 'exact operation replay and independent scoped readback';
  await recover.click(); await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  expect(requests).toHaveLength(3); for (const request of requests) expect(request).toBe(requests[0]);
  expect(receipts[0].operation.replayed).toBe(false); expect(receipts[1].operation.replayed).toBe(true);
  expect(receipts[1].estimate.id).toBe(receipts[0].estimate.id);
  const estimateId = receipts[0].estimate.id;
  const params = new URLSearchParams({ company: manifest.company, project: manifest.project, kind: 'estimate', record_id: estimateId });
  const read = await page.request.get(`${base}/api/method/cipher_aec.estimating.api.get_record?${params}`); expect(read.status()).toBe(200);
  const saved = (await read.json()).message.data; expect(saved.title).toBe(title); expect(saved.current_revision).toBeNull();
  let cursor; const matches = [];
  do {
    const query = new URLSearchParams({ company: manifest.company, project: manifest.project, kind: 'estimate', limit: '200', count_mode: 'exact', ...(cursor ? { cursor } : {}) });
    const response = await page.request.get(`${base}/api/method/cipher_aec.estimating.api.list_records?${query}`); expect(response.status()).toBe(200);
    const data = (await response.json()).message.data; matches.push(...data.items.filter(item => item.title === title)); cursor = data.next_cursor;
  } while (cursor);
  expect(matches).toHaveLength(1); expect(matches[0].id).toBe(estimateId);
  await page.screenshot({ path: new URL('actual-create-original-operation-recovered.png', output).pathname, fullPage: true });
  if (browserErrors.length || consoleErrors.length || unexpectedHttp.length) throw new Error('Unexpected browser errors.');
  const digest = bytes => createHash('sha256').update(bytes).digest('hex');
  const html = await (await page.request.get(base)).body();
  const assets = [...html.toString().matchAll(/(?:src|href)="(\/assets\/[^\"]+\.(?:js|css))"/g)].map(match => match[1]);
  const served = [];
  for (const asset of assets) { const bytes = await (await page.request.get(`${base}${asset}`)).body(); served.push({ path: asset, sha256: digest(bytes), bytes: bytes.length }); }
  const sources = {};
  for (const file of ['src/Estimates.tsx', 'src/api/client.ts', 'src/api/estimating.ts', 'tests/estimating.spec.ts', 'tests/estimating-fixture.ts', 'README.md', 'scripts/connected-estimating-recovery.mjs']) sources[file] = digest(await readFile(new URL(`../${file}`, import.meta.url)));
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: 'actual-frappe-create-with-injected-response-loss-and-receipt-denial', captured_at: new Date().toISOString(), real_backend_effect: true, response_delivery_fault_injected: true, receipt_denial_injected: true, actual_permissions_modified: false, synthetic_contract_fixture: false, estimate: estimateId, operation_id: JSON.parse(requests[0]).operation_id, request_count: requests.length, real_backend_write_requests: receipts.length, exact_payload_and_uuid_replayed: true, replay_receipt: receipts[1].operation, independent_title_match_count: matches.length, inputs_cancel_escape_locked: true, unknown_retained_after_injected_denial: true, mounted_recovery_only: true, browser_errors: browserErrors, unexpected_console_errors: consoleErrors, unexpected_http_errors: unexpectedHttp, expected_injected_faults: expectedFaults, expected_initial_authentication_responses: expectedAuth, served_html_sha256: digest(html), served_assets: served, source_sha256: sources }, null, 2));
  console.log('Actual create recovery passed: real effect, injected lost delivery and receipt denial, exact replay, one independently read-back draft. Credentials not logged.');
} catch {
  console.error(`Actual create recovery failed at ${stage}. No credentials or authentication details logged.`); process.exitCode = 1;
} finally { await browser.close(); }
