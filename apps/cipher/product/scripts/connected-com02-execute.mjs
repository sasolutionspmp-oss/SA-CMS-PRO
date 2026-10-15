import { appendFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { chromium, expect as baseExpect } from '@playwright/test';
const expect = baseExpect.configure({ timeout: 30000 });
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const secret = JSON.parse(await readFile('/tmp/cipher-r0-runtime/company-chain-20b85fd4edd2.secret.json', 'utf8'));
const original = JSON.parse(await readFile(process.env.CIPHER_COM02_GRANTED_CONTEXT || '/tmp/cipher-r0-runtime/com02-original-granted-context.json', 'utf8'));
if (original.state !== 'Granted' || original.action !== 'proposal.issue.v1' || original.company !== secret.company) throw new Error('Exact known Granted Issue context required.');
const company = secret.company; const attempt = randomUUID();
const output = new URL(process.env.CIPHER_CAPTURE_DIR || `/workspace/cipher-live-r2/com02-execute-${attempt}/`, import.meta.url);
await mkdir(output, { recursive: true });
const journal = `/tmp/cipher-r0-runtime/com02-execute-${attempt}.private.jsonl`;
await writeFile(journal, '', { mode: 0o600 });
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const mutations = [], errors = [], consoles = [], network = [], expectedAuth = [], reads = []; const sources = {}; const assets = new Set();
const ids = { packet: original.packet_id, revision: original.subject_id, prepared_revision: original.prepared_revision_id };
const inventory = async path => { for (const entry of await readdir(new URL(path, import.meta.url), { withFileTypes: true })) { const child = `${path}/${entry.name}`; if (entry.isDirectory()) await inventory(child); else sources[child] = hash(await readFile(new URL(child, import.meta.url))); } };
await inventory('../src'); await inventory('../scripts');
let stage = 'sign in to exact Granted task'; let page;
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !message.text().includes('401')) consoles.push(message.text()); });
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/pdfjs/')) assets.add(url.pathname); });
  page.on('response', response => { if (response.status() < 400) return; const item = { path: new URL(response.url()).pathname, status: response.status() }; if (item.status === 401 && item.path.endsWith('cipher_aec.api.v1.session')) expectedAuth.push(item); else network.push(item); });
  await page.route('**/api/method/cipher_aec.**', async route => {
    const request = route.request(); const url = new URL(request.url());
    if (request.method() !== 'POST') { reads.push(url.pathname); return route.continue(); }
    if (!url.pathname.endsWith('cipher_aec.api.company_approvals.execute_packet') || mutations.length) throw new Error('Only the one unattempted exact Issue execution is permitted. Reconcile before any retry.');
    const raw = request.postData() || ''; const body = JSON.parse(raw);
    if (body.packet_id !== original.packet_id || body.company !== company || body.manifest_hash !== original.manifest_hash || request.headers()['idempotency-key'] !== body.operation_id) throw new Error('Execution does not match preserved packet identity.');
    await appendFile(journal, JSON.stringify({ at: new Date().toISOString(), stage, path: url.pathname, idempotency_key: request.headers()['idempotency-key'], raw_payload: raw }) + '\n', { mode: 0o600 });
    mutations.push({ path: url.pathname, operation_id: body.operation_id, raw_payload_sha256: hash(raw) });
    await writeFile(new URL('mutation-journal-summary.json', output), JSON.stringify({ attempt, private_journal: journal, mutations }, null, 2));
    await route.continue();
  });
  await page.goto(`${base}/company/work/${encodeURIComponent(original.packet_id)}?company=${encodeURIComponent(company)}`);
  await page.getByLabel('Email or username', { exact: true }).fill(secret.users.author.user);
  await page.getByLabel('Password', { exact: true }).fill(secret.users.author.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const review = page.locator('ui5-dialog[header-text="Review company approval packet"]');
  await expect(review.getByRole('button', { name: 'Execute approved company action', exact: true })).toBeVisible();
  const response = await page.request.get(`${base}/api/method/cipher_aec.api.company_approvals.read_packet`, { params: { company, packet_id: original.packet_id } });
  expect(response.ok()).toBe(true); const packet = (await response.json()).message.data;
  expect(packet.state).toBe('Granted'); expect(packet.manifest_hash).toBe(original.manifest_hash); expect(packet.subject.id).toBe(original.subject_id);
  expect(packet.action).toBe('proposal.issue.v1'); expect(packet.review_manifest.effect.prepared_output.revision_id).toBe(original.prepared_revision_id);
  expect(reads.some(path => path.endsWith('list_packets'))).toBe(false);
  await review.getByRole('button', { name: 'Review exact prepared PDF', exact: true }).click();
  const canvas = review.locator('canvas[aria-label="Authorized stored PDF page"]'); await expect(canvas).toBeVisible();
  const prepared = packet.review_manifest.effect.prepared_output;
  const bytes = await page.request.get(`${base}/api/method/cipher_aec.documents.company_api.download_revision`, { params: { company, revision_id: prepared.revision_id } });
  expect(bytes.ok()).toBe(true); expect(hash(await bytes.body())).toBe(prepared.source_sha256);
  for (const [width, name] of [[1440, 'desktop'], [900, 'tablet'], [390, 'phone']]) {
    await page.setViewportSize({ width, height: 1000 }); const zoom = review.getByRole('combobox', { name: 'Drawing zoom', exact: true }); await zoom.click();
    await page.getByRole('option', { name: width < 600 ? '50%' : width < 1000 ? '75%' : '100%', exact: true }).press('Enter');
    await expect(canvas).toBeVisible(); await review.locator('.issue-prepared-review').scrollIntoViewIfNeeded();
    expect(await review.locator('.dialog-form').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: new URL(`actual-granted-exact-issue-${name}.png`, output).pathname, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  stage = 'execute original independently Granted exact Issue once';
  await review.getByRole('checkbox', { name: 'I reviewed this exact company action and its sources', exact: true }).click();
  const pending = page.waitForResponse(response => response.url().endsWith('cipher_aec.api.company_approvals.execute_packet') && response.request().method() === 'POST', { timeout: 60000 });
  await review.getByRole('button', { name: 'Execute approved company action', exact: true }).click();
  const executedResponse = await pending; if (!executedResponse.ok()) throw new Error(`Execution returned${executedResponse.status()}; preserve exact journal before recovery.`);
  const executed = (await executedResponse.json()).message.data; expect(executed.packet.state).toBe('Consumed'); ids.issue = executed.effect.issue.id;
  const issuedResponse = await page.request.get(`${base}/api/method/cipher_aec.commercial.api.issue`, { params: { company, issue_id: ids.issue } });
  expect(issuedResponse.ok()).toBe(true); const issue = (await issuedResponse.json()).message.data;
  expect(issue.proposal_revision).toBe(original.subject_id); expect(issue.output_revision).toBe(original.prepared_revision_id);
  expect(issue.prepared_output.source_sha256).toBe(prepared.source_sha256); expect(issue.native_lifecycle).toBe('draft-snapshot'); expect(issue.native_snapshot.docstatus).toBe(0); expect(issue.distribution).toBe('not-sent');
  await expect(review.getByRole('note', { name: /independently approved action was executed/ })).toBeVisible();
  await page.screenshot({ path: new URL('actual-original-issue-executed.png', output).pathname, fullPage: true });
  if (errors.length || consoles.length || network.length) throw new Error('Unexpected browser or HTTP error.');
  const served = []; for (const path of assets) { const resource = await page.request.get(base + path); expect(resource.ok()).toBe(true); served.push({ path, sha256: hash(await resource.body()) }); }
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: 'actual-frappe-exact-granted-issue-ui', attempt, completed_at: new Date().toISOString(), continuation_of: original.evidence, ids, company, original_preparation_repeated: false, request_or_grant_repeated: false, mutations, private_journal: journal, exact_packet: packet, prepared_output: prepared, issue, actual_pdf_bytes_verified: true, inbox_requests: reads.filter(path => path.endsWith('list_packets')), viewports: [1440, 900, 390], browser_errors: errors, unexpected_console_errors: consoles, unexpected_http_errors: network, expected_initial_401: expectedAuth, source_hashes: sources, served_assets: served }, null, 2));
  console.log(`Exact original Granted Issue execution passed: ${output.pathname}`);
} catch (error) {
  await writeFile(new URL('incomplete-journey.json', output), JSON.stringify({ attempt, stage, at: new Date().toISOString(), ids, mutations, private_journal: journal, source_hashes: sources, browser_errors: errors, unexpected_http_errors: network, unexpected_console_errors: consoles }, null, 2));
  await page?.screenshot({ path: new URL('incomplete-screen.png', output).pathname, fullPage: true }).catch(() => {});
  console.error(`Exact Issue execution stopped at${stage}: ${String(error?.message || '').split('\n')[0]}`); console.error(`Evidence: ${output.pathname}`); process.exitCode = 1;
} finally { await browser.close(); }
