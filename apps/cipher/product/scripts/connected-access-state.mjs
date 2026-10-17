import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

// Read-only verification of a real independently scoped reviewer. Auth writes
// establish a session; this script performs no business commands or mocked calls.
const manifest = JSON.parse(await readFile(process.env.CIPHER_RUNTIME_MANIFEST || '/tmp/cipher-r0-runtime/fixture.secret.json', 'utf8'));
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const output = new URL(process.env.CIPHER_CAPTURE_DIR || '../test-results/connected-access-state/', import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
let stage = 'reviewer sign in';
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; const documentStatuses = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (new URL(response.url()).pathname.endsWith('cipher_aec.documents.api.list_documents')) documentStatuses.push(response.status()); });
  await page.goto(`${base}/projects/${encodeURIComponent(manifest.project)}`);
  await page.getByLabel('Email or username', { exact: true }).fill(manifest.users.reviewer.user);
  await page.getByLabel('Password', { exact: true }).fill(manifest.users.reviewer.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  stage = 'permanent document access state';
  const sources = page.getByRole('region').filter({ has: page.getByRole('heading', { name: 'Source documents', exact: true }) });
  await expect(sources.getByRole('note', { name: /Your current permissions/ })).toBeVisible();
  await expect(sources.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0);
  stage = 'independent approval inbox remains usable';
  await page.getByRole('tab', { name: 'Approvals', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Review packet', exact: true }).first()).toBeEnabled();
  await expect(page.getByRole('button', { name: 'New task', exact: true })).toHaveCount(0);
  await page.screenshot({ path: new URL('connected-reviewer-access-state.png', output).pathname, fullPage: true });
  if (!documentStatuses.includes(403) || errors.length) throw new Error('Connected access checks failed.');
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: 'actual-frappe-read-only-reviewer', captured_at: new Date().toISOString(), mocked_requests: false, business_writes: false, browser_errors: errors.length, document_http_statuses: documentStatuses, checks: ['permanent permission state has plain current-access message', 'no retry for HTTP403', 'approval inbox remains usable', 'no task-create authority'] }, null, 2));
  console.log('Actual reviewer access-state verification passed; no business writes or credential output.');
} catch {
  console.error(`Actual reviewer access-state verification failed at ${stage}. Credentials and authentication errors were not logged.`); process.exitCode = 1;
} finally { await browser.close(); }
