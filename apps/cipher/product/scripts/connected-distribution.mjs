import { appendFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { chromium, expect as baseExpect } from '@playwright/test';

// Coordinated synthetic runtime only. This script never starts a worker or
// changes native roles, duties, transport configuration, or source records.
const expect = baseExpect.configure({ timeout: 30000 });
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const secret = JSON.parse(await readFile(process.env.CIPHER_COMPANY_MANIFEST || '/tmp/cipher-r0-runtime/company-chain-20b85fd4edd2.secret.json', 'utf8'));
const resumed = process.env.CIPHER_DISTRIBUTION_READBACK ? JSON.parse(await readFile(process.env.CIPHER_DISTRIBUTION_READBACK, 'utf8')) : undefined;
const issueId = resumed?.ids?.issue || process.env.CIPHER_DISTRIBUTION_ISSUE_ID;
if (!issueId || (resumed && !resumed.ids?.dispatch)) throw new Error('An exact qualified Issue ID, or completed dispatch proof for read-only continuation, is required.');
const company = secret.company;
const attempt = randomUUID();
const directory = process.env.CIPHER_CAPTURE_DIR || `/workspace/cipher-live-r2/com02-distribution-${attempt}/`;
const output = new URL(directory.endsWith('/') ? directory : directory + '/', import.meta.url);
await mkdir(output, { recursive: true });
const journal = `/tmp/cipher-r0-runtime/distribution-ui-${attempt}.private.jsonl`;
await writeFile(journal, '', { mode: 0o600 });
const hash = value => createHash('sha256').update(value).digest('hex');
const errors = [], consoles = [], network = [], expectedAuth = [], mutations = [], projectRequests = [];
const assets = new Set(); const sources = {}; const ids = { issue: issueId, ...resumed?.ids };
let stage = 'sign in'; let failed; let current;
const inventory = async path => {
  for (const entry of await readdir(new URL(path, import.meta.url), { withFileTypes: true })) {
    const child = `${path}/${entry.name}`;
    if (entry.isDirectory()) await inventory(child); else sources[child] = hash(await readFile(new URL(child, import.meta.url)));
  }
};
await inventory('../src'); await inventory('../scripts');
for (const path of ['../package.json', '../package-lock.json']) sources[path] = hash(await readFile(new URL(path, import.meta.url)));
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const author = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage(); failed = author;
  const reviewer = resumed ? undefined : await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  for (const page of [author, reviewer].filter(Boolean)) {
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error' && !message.text().includes('401')) consoles.push(message.text()); });
    page.on('response', response => {
      if (response.status() < 400) return;
      const item = { path: new URL(response.url()).pathname, status: response.status() };
      if (item.status === 401 && item.path.endsWith('cipher_aec.api.v1.session')) expectedAuth.push(item); else network.push(item);
    });
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith('/assets/') || path.startsWith('/pdfjs/')) assets.add(path);
      if (/cipher_aec\.api\.v1\.projects?\b/.test(path)) projectRequests.push(path);
    });
    await page.route('**/api/method/cipher_aec.**', async route => {
      const request = route.request(); if (request.method() !== 'POST') return route.continue();
      if (resumed) throw new Error('Readback phase refuses every business mutation.');
      const raw = request.postData() || ''; const body = JSON.parse(raw);
      const entry = { at: new Date().toISOString(), stage, path: new URL(request.url()).pathname, idempotency_key: request.headers()['idempotency-key'], raw_payload: raw };
      if (entry.idempotency_key !== body.operation_id) throw new Error('Mutation key mismatch before send.');
      await appendFile(journal, JSON.stringify(entry) + '\n', { mode: 0o600 });
      mutations.push({ at: entry.at, stage, path: entry.path, operation_id: body.operation_id, raw_payload_sha256: hash(raw) });
      await writeFile(new URL('mutation-journal-summary.json', output), JSON.stringify({ attempt, private_journal: journal, mutations }, null, 2));
      await route.continue();
    });
  }
  const signIn = async (page, actor, path) => {
    await page.goto(base + path);
    await page.getByLabel('Email or username', { exact: true }).fill(actor.user);
    await page.getByLabel('Password', { exact: true }).fill(actor.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    const choice = page.locator('ui5-select[accessible-name="Company"]');
    await expect(choice).toBeVisible(); await expect(choice).toContainText(company); await choice.click();
    await page.getByRole('option', { name: company, exact: true }).click();
  };
  const read = async (page, method, parameters) => {
    const response = await page.request.get(`${base}/api/method/${method}`, { params: { company, ...parameters } });
    if (!response.ok()) throw new Error(`${method.split('.').pop()} rejected ${response.status()}.`);
    return (await response.json()).message.data;
  };
  const command = async (page, method, action) => {
    const pending = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(method), { timeout: 60000 });
    await action(); const response = await pending;
    if (!response.ok()) throw new Error(`${method.split('.').pop()} rejected ${response.status()}; reconcile the journal before any new-key attempt.`);
    return (await response.json()).message.data;
  };
  const capture = async (page, name) => page.screenshot({ path: new URL(name, output).pathname, fullPage: true });
  const prefix = 'cipher_aec.integrations.distribution_api.';
  const path = `/commercial/issues/${issueId}/distribution`;
  await signIn(author, secret.users.author, path);
  const issue = await read(author, 'cipher_aec.commercial.api.issue', { issue_id: issueId });
  const choices = await read(author, prefix + 'recipient_choices', { issue_id: issueId });
  const pdf = await author.request.get(`${base}/api/method/cipher_aec.documents.company_api.download_revision`, { params: { company, revision_id: issue.prepared_output.revision_id } });
  expect(pdf.ok()).toBe(true); expect(hash(await pdf.body())).toBe(issue.prepared_output.source_sha256);
  let selected = resumed?.selected_recipients;
  if (!resumed) {
    if (choices.recipients.length < 2) throw new Error('Subset qualification requires an issued record with at least two original recipients; no writes attempted.');
    selected = [choices.recipients[0]];
    stage = 'author exact original recipient subset';
    await author.getByRole('button', { name: 'New fixture instruction', exact: true }).click();
    const form = author.locator('ui5-dialog[header-text="New fixture distribution instruction"]');
    await form.getByRole('textbox', { name: 'Fixture message subject', exact: true }).fill(`Utility proposal fixture review ${attempt.slice(0, 8)}`);
    await form.getByRole('textbox', { name: 'Fixture message subject', exact: true }).press('Tab');
    await expect(form.getByRole('textbox', { name: 'Fixture message body', exact: true })).toBeFocused();
    await form.getByRole('textbox', { name: 'Fixture message body', exact: true }).fill('Review the exact issued utility proposal PDF. This approved instruction uses local synthetic fixture transport only.');
    for (const recipient of choices.recipients.slice(1)) await form.getByRole('checkbox', { name: `${recipient.name} · ${recipient.email}`, exact: true }).click();
    for (const [width, label] of [[1440, 'desktop'], [900, 'tablet'], [390, 'phone']]) {
      await author.setViewportSize({ width, height: 1000 });
      expect(await author.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await form.locator('.dialog-form').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
      await capture(author, `actual-fixture-recipient-subset-${label}.png`);
    }
    await author.setViewportSize({ width: 1440, height: 1000 });
    const saved = await command(author, prefix + 'create_instruction', () => form.getByRole('button', { name: 'Save fixture instruction', exact: true }).click());
    ids.instruction = saved.instruction.id;
    expect(saved.instruction.recipients).toEqual(selected);
    expect(saved.instruction.issue_digest).toBe(choices.issue_digest);
    expect(saved.instruction.attachment.sha256).toBe(issue.prepared_output.source_sha256);
    stage = 'discover saved immutable instruction';
    await author.goto(base + path);
    const register = author.locator('ui5-table[accessible-name="Saved distribution instructions"]');
    const row = register.locator('ui5-table-row').filter({ hasText: saved.instruction.message.subject });
    await row.getByRole('button', { name: 'Open instruction', exact: true }).click();
    await expect(author.getByRole('region', { name: 'Selected saved instruction', exact: true })).toContainText(saved.instruction.message.body);
    const requested = await command(author, 'cipher_aec.api.company_approvals.request_action', () => author.getByRole('button', { name: 'Request independent fixture review', exact: true }).click());
    ids.packet = requested.packet.id; expect(requested.packet.source_version).toBe(saved.version);
    await author.getByRole('button', { name: 'Close company review', exact: true }).click();
    const open = async page => {
      await page.goto(`${base}/company/work/${encodeURIComponent(ids.packet)}?company=${encodeURIComponent(company)}`);
      const dialog = page.locator('ui5-dialog[header-text="Review company approval packet"]');
      await expect(dialog).toContainText(saved.instruction.message.body);
      await expect(dialog).toContainText(selected[0].email);
      for (const omitted of choices.recipients.slice(1)) await expect(dialog.locator('.distribution-instruction-facts')).not.toContainText(omitted.email);
      await dialog.getByRole('button', { name: 'Review exact issued PDF', exact: true }).click();
      await expect(dialog.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible();
      return dialog;
    };
    stage = 'independent reviewer exact message recipient and PDF review'; failed = reviewer;
    await signIn(reviewer, secret.users.reviewer, '/company/work');
    let review = await open(reviewer);
    for (const [width, label] of [[1440, 'desktop'], [900, 'tablet'], [390, 'phone']]) {
      await reviewer.setViewportSize({ width, height: 1000 });
      const zoom = review.getByRole('combobox', { name: 'Drawing zoom', exact: true });
      await zoom.click(); await reviewer.getByRole('option', { name: width < 600 ? '50%' : width < 1000 ? '75%' : '100%', exact: true }).press('Enter');
      await expect(review.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible();
      await review.locator('.distribution-instruction-facts').scrollIntoViewIfNeeded();
      expect(await review.locator('.dialog-form').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
      await capture(reviewer, `actual-independent-fixture-review-${label}.png`);
    }
    await reviewer.setViewportSize({ width: 1440, height: 1000 });
    await review.getByRole('checkbox', { name: 'I reviewed this exact company action and its sources', exact: true }).click();
    await review.getByRole('textbox', { name: 'Company approval review note', exact: true }).fill('Reviewed the exact original recipient subset, fixed PDF, authored message and local fixture transport.');
    const granted = await command(reviewer, 'cipher_aec.api.company_approvals.decide_packet', () => review.getByRole('button', { name: 'Grant company approval', exact: true }).click());
    expect(granted.packet.state).toBe('Granted');
    stage = 'original author separately queues approved fixture dispatch'; failed = author;
    review = await open(author);
    await review.getByRole('checkbox', { name: 'I reviewed this exact company action and its sources', exact: true }).click();
    const queued = await command(author, 'cipher_aec.api.company_approvals.execute_packet', () => review.getByRole('button', { name: 'Execute approved company action', exact: true }).click());
    expect(queued.packet.state).toBe('Consumed'); expect(queued.effect.mode).toBe('fixture');
    expect(queued.effect.delivery_status).toBe('Queued'); ids.dispatch = queued.effect.dispatch.id;
  }
  stage = resumed ? 'read current fixture acknowledgments' : 'read actual queued fixture dispatch'; failed = author;
  await author.goto(`${base}${path}/dispatches/${ids.dispatch}`);
  const status = author.getByRole('region', { name: 'Selected fixture dispatch', exact: true });
  current = await read(author, prefix + 'get_dispatch', { dispatch_id: ids.dispatch });
  expect(current.dispatch.issue_id).toBe(issueId); expect(current.dispatch.instruction_id).toBe(ids.instruction);
  expect(current.mode).toBe('fixture'); expect(current.deliveries.map(row => row.recipient_id)).toEqual(selected.map(row => row.id));
  for (const delivery of current.deliveries) {
    expect(delivery.logical_key).toMatch(/^[a-f0-9]{64}$/); expect(delivery.payload_hash).toMatch(/^[a-f0-9]{64}$/);
    if (delivery.state === 'Succeeded') {
      expect(delivery.receipt?.receipt?.logical_key).toBe(delivery.logical_key);
      expect(delivery.receipt?.receipt?.payload_hash).toBe(delivery.payload_hash);
      expect(delivery.receipt?.receipt?.attachment_sha256).toBe(issue.prepared_output.source_sha256);
    }
  }
  const verifiedCount = current.deliveries.filter(row => row.state === 'Succeeded' && row.logical_key && row.payload_hash && row.receipt?.receipt?.logical_key === row.logical_key && row.receipt?.receipt?.payload_hash === row.payload_hash).length;
  await expect(status).toContainText(`${verifiedCount} of ${selected.length} fixture acknowledgments verified.`);
  await expect(status.locator('ui5-table[accessible-name="Fixture recipient delivery readback"]')).toBeVisible();
  await expect(author.locator('ui5-table[accessible-name="Fixture dispatch register"]')).toBeVisible();
  await expect(author.locator('ui5-table[accessible-name="Saved distribution instructions"]')).toBeVisible();
  for (const [width, label] of [[1440, 'desktop'], [900, 'tablet'], [390, 'phone']]) {
    await author.setViewportSize({ width, height: 1000 }); await status.scrollIntoViewIfNeeded();
    await expect(status.getByRole('heading', { name: 'Fixture status and recipient readback', exact: true })).toBeVisible();
    await expect(author.locator('.loading-state')).toHaveCount(0);
    expect(await author.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await capture(author, `actual-fixture-${resumed ? 'readback' : 'queued'}-${label}.png`);
  }
  if (errors.length || consoles.length || network.length || projectRequests.length) throw new Error('Unexpected browser/network/Project-scope error.');
  const served = [];
  for (const path of assets) { const response = await author.request.get(base + path); expect(response.ok()).toBe(true); served.push({ path, sha256: hash(await response.body()) }); }
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: resumed ? 'actual-frappe-distribution-readonly' : 'actual-frappe-distribution-ui', attempt, continuation_of_attempt: resumed?.attempt, captured_at: new Date().toISOString(), company, ids, selected_recipients: selected, issued_recipient_count: choices.recipients.length, canonical_pdf_sha256: issue.prepared_output.source_sha256, actual_pdf_bytes_verified: true, dispatch_readback: current, mutations, private_journal: journal, independent_review_and_separate_execution: !resumed || resumed.independent_review_and_separate_execution, live_transmission: false, worker_administration_performed: false, browser_errors: errors, unexpected_console_errors: consoles, unexpected_http_errors: network, expected_initial_401: expectedAuth, project_authority_requests: projectRequests, viewports: [1440, 900, 390], source_hashes: sources, served_assets: served, recovery_limit: 'Mounted-only application recovery; private tooling journal does not add restart recovery.' }, null, 2));
  console.log(`Actual fixture distribution proof passed: ${output.pathname}`);
} catch (error) {
  await writeFile(new URL('incomplete-journey.json', output), JSON.stringify({ attempt, stage, at: new Date().toISOString(), ids, current, mutations, private_journal: journal, source_hashes: sources, browser_errors: errors, unexpected_console_errors: consoles, unexpected_http_errors: network }, null, 2));
  await failed?.screenshot({ path: new URL('incomplete-screen.png', output).pathname, fullPage: true }).catch(() => {});
  console.error(`Distribution journey stopped at ${stage}: ${String(error?.message || '').split('\n')[0]}`);
  console.error(`Evidence: ${output.pathname}`); process.exitCode = 1;
} finally { await browser.close(); }
