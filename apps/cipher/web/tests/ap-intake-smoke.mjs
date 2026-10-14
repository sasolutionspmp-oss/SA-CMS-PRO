import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const directory = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const repository = path.resolve(directory, '../../..');
const port = Number(process.env.CIPHER_INTAKE_PORT ?? 18768);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/ap-practice/v1';
const artifacts = process.env.CIPHER_INTAKE_ARTIFACTS ?? '/tmp/cipher-completion/ap-intake-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', widths: [], views: [], journeys: [], exactRetries: [],
  refusals: [], contractChecks: [], violations: [], errors: [], requests: [],
  axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard traversal remains checked'] };
const decimal = cents => `${BigInt(cents) / 100n}.${(BigInt(cents) % 100n).toString().padStart(2, '0')}`;
let server;
let browser;
// This test-only control pipe advances one fixture document through the normal
// owned Evidence API. No HTTP route, actor selector or SQL is added to the app.
const fixtureControl = `
import sys
from threading import Thread
from apps.cipher.ap_practice_server import make_ap_practice_server
from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN
server = make_ap_practice_server(port=int(sys.argv[1]))
def controls():
    for command in sys.stdin:
        if command != "advance_invoice_evidence\\n":
            raise ValueError("Unsupported bounded fixture control")
        with server.cipher_lock, server.cipher.db._lock:
            document = server.cipher.ap_practice_records["visible_invoice_evidence_ids"][2]
            server.cipher.evidence.add_revision(document_id=document,
                content="Synthetic source revision during browser review",
                note="Synthetic browser stale-source check", actor=ACCOUNTANT_LOGIN)
        print("evidence_advanced", flush=True)
Thread(target=controls, daemon=True).start()
try:
    server.serve_forever()
finally:
    server.server_close()
`;
async function startServer() {
  server = spawn(process.env.CIPHER_PYTHON ?? 'python', ['-u', '-c', fixtureControl, String(port)], { cwd: repository, stdio: ['pipe', 'pipe', 'pipe'] });
  let diagnostics = ''; server.stderr.on('data', chunk => { diagnostics += chunk.toString(); });
  for (let attempt = 0; attempt < 120; attempt++) {
    if (server.exitCode !== null) throw new Error(`The isolated intake server exited (${server.exitCode}): ${diagnostics}`);
    try { if ((await fetch(base)).ok) return () => diagnostics; } catch { /* The loopback listener is starting. */ }
    await delay(100);
  }
  throw new Error('The isolated intake server did not become ready.');
}
async function advanceEvidence() {
  const acknowledgment = once(server.stdout, 'data', { signal: AbortSignal.timeout(10_000) });
  server.stdin.write('advance_invoice_evidence\n');
  const [data] = await acknowledgment; assert.equal(data.toString().trim(), 'evidence_advanced');
}
async function stopServer() {
  if (!server || server.exitCode !== null) { server = undefined; return; }
  const closed = once(server, 'exit'); server.kill('SIGTERM'); await closed; server = undefined;
}
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, route);
  const value = await response.json();
  assert.equal(value.mode, 'practice'); assert.equal(value.synthetic, true); assert.equal(value.contractVersion, 'cipher.ap-practice.v1');
  return value;
}
async function post(context, route, body, headers = {}) {
  const session = await json(context, '/session');
  return context.request.post(base + prefix + route, { headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken, ...headers }, data: body });
}
async function snapshot(page, name, width) {
  await page.locator('main[aria-busy="false"]').waitFor();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.getByRole('heading', { level: 1 }).waitFor();
  assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  assert.ok(size.document <= size.viewport, `${name} overflows at ${width}px.`);
  assert.equal(await page.getByText('Practice data. Nothing here is real money and nothing is sent.', { exact: true }).count(), 1);
  const accessibility = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  report.violations.push(...accessibility.violations.map(item => ({ name, width, id: item.id, nodes: item.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content');
  assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width });
}
async function choosePerson(page, persona) {
  if (await page.getByRole('button', { name: 'Change practice person', exact: true }).count()) {
    await page.getByRole('button', { name: 'Change practice person', exact: true }).click();
  }
  await page.getByRole('heading', { name: 'Start a practice session', exact: true }).waitFor();
  await page.getByRole('button', { name: ({ accountant: /Start as Alex Rivera/, reviewer: /Start as Jordan Chen/, pm: /Start as Morgan Lee/ })[persona] }).click();
  await page.getByRole('heading', { name: persona === 'pm' ? 'My projects' : 'Books', level: 1, exact: true }).waitFor();
  await page.locator('main[aria-busy="false"]').waitFor();
}
async function actionResponse(page, route, click) {
  const waiting = page.waitForResponse(response => new URL(response.url()).pathname === prefix + route && response.request().method() === 'POST');
  await click(); const response = await waiting; assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return { value: await response.json(), key: response.request().headers()['repeatability-request-id'], body: response.request().postData() };
}
async function reviewedAction(page, route, action, reviewLabel, applyLabel) {
  const panel = page.locator(`[data-action="${action}"]`);
  await panel.getByRole('button', { name: reviewLabel, exact: true }).click();
  await panel.getByRole('button', { name: applyLabel, exact: true }).waitFor();
  return actionResponse(page, route, () => panel.getByRole('button', { name: applyLabel, exact: true }).click());
}
async function exactRetry(page, route, action, first, width) {
  const retry = await actionResponse(page, route, () => page.locator(`[data-action="${action}"]`).getByRole('button', { name: 'Retry same action', exact: true }).click());
  assert.ok(first.key); assert.equal(retry.key, first.key); assert.equal(retry.body, first.body);
  assert.equal(retry.value.receiptId, first.value.receiptId); assert.equal(retry.value.replayed, true);
  assert.equal(retry.value.effectApplied, false); assert.deepEqual(retry.value.result, first.value.result);
  report.exactRetries.push({ width, action });
}
async function receive(page, context, commitment, invoiceNumber, amountCents, evidence) {
  await page.goto(base + `/commitments/${commitment.id}/receive-invoice`);
  await page.getByRole('textbox', { name: 'Supplier invoice number', exact: true }).fill(invoiceNumber);
  await page.getByLabel('Invoice date', { exact: true }).fill('2026-10-14');
  await page.getByRole('textbox', { name: 'Invoice amount (USD)', exact: true }).fill(decimal(amountCents));
  await page.getByRole('combobox', { name: 'Source invoice evidence', exact: true }).selectOption(evidence.revisionId);
  assert.equal((await json(context, '/invoice-evidence')).value.find(row => row.revisionId === evidence.revisionId).projectId, commitment.projectId);
}
async function contractChecks(context, invoiceId) {
  for (const [name, collection, mutate, expected] of [
    ['missing invoice source', 'invoices', value => { delete value.value[0].evidence.revisionId; }, 'incomplete'],
    ['unsafe invoice cents', 'invoices', value => { value.value[0].amountCents = Number.MAX_SAFE_INTEGER + 1; }, 'accurately'],
    ['malformed evidence availability', 'invoice-evidence', value => { value.value[0].available = 'yes'; }, 'incomplete'],
    ['unsafe invoice aggregate', 'invoices', value => {
      const invoice = value.value[0]; value.value = [Number.MAX_SAFE_INTEGER, 1].map((amountCents, i) => ({ ...invoice, id: `precision-${i}`, status: 'received', amountCents })); value.count = 2;
    }, 'supported monetary range'],
  ]) {
    const page = await context.newPage();
    await page.route(`**${prefix}/${collection}?*`, async route => { const response = await route.fetch(); const value = await response.json(); mutate(value); await route.fulfill({ response, json: value }); });
    await page.goto(base + '/invoices'); await page.getByRole('alert').waitFor();
    assert.ok((await page.getByRole('alert').innerText()).includes(expected)); assert.equal(await page.getByRole('table').count(), 0);
    report.contractChecks.push(name); await page.close();
  }
  const page = await context.newPage();
  await page.route(`**${prefix}/invoices/${invoiceId}`, async route => { const response = await route.fetch(); const value = await response.json(); value.amountCents = Number.MAX_SAFE_INTEGER; await route.fulfill({ response, json: value }); });
  await page.goto(base + `/invoices/${invoiceId}`); await page.getByText('$90,071,992,547,409.91', { exact: true }).waitFor();
  report.contractChecks.push('maximum invoice cents displayed exactly'); await page.close();
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of [1440, 1024, 390]) {
    const diagnostics = await startServer();
    const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce', hasTouch: width < 1024 });
    const page = await context.newPage();
    const expectedHTTP = new Map(); const requestExpectations = new WeakMap(); const verifiedHTTP = new Set(); const consoleHTTP = [];
    function expectHTTP(method, route, status) { expectedHTTP.set(`${method}:${prefix + route}`, new Set([status])); }
    page.on('request', request => requestExpectations.set(request, new Set(expectedHTTP.get(`${request.method()}:${new URL(request.url()).pathname}`) ?? [])));
    page.on('response', response => { if (response.status() < 400) return; const request = response.request(); if (requestExpectations.get(request)?.has(response.status())) verifiedHTTP.add(`${response.status()}:${response.url()}`); else report.errors.push({ width, kind: 'unexpected HTTP refusal', status: response.status(), route: new URL(response.url()).pathname }); });
    page.on('pageerror', error => report.errors.push({ width, kind: 'application', message: error.message }));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      const text = message.text(); const match = text.match(/^Failed to load resource: the server responded with a status of (\d+) /);
      if (match) consoleHTTP.push({ status: Number(match[1]), url: message.location().url, message: text });
      else report.errors.push({ width, kind: 'console or CSP', message: text });
    });
    await page.route('**/*', route => {
      const request = route.request(); const address = new URL(request.url()); assert.equal(address.origin, base);
      assert.ok(['GET', 'HEAD', 'POST'].includes(request.method()));
      if (request.method() === 'POST') assert.ok(address.pathname.startsWith(prefix + '/'));
      if (address.pathname.startsWith('/api/')) report.requests.push({ width, method: request.method(), route: address.pathname });
      return route.continue();
    });
    await page.goto(base); await snapshot(page, 'three-person-picker', width); await choosePerson(page, 'accountant');
    const commitments = (await json(context, '/commitments')).value;
    const commitment = commitments.find(row => row.title === 'Civil works subcontract'); assert.ok(commitment);
    const preparation = await json(context, `/commitments/${commitment.id}/preparation`); assert.equal(preparation.lines.length, 2);
    const sources = (await json(context, '/invoice-evidence')).value.filter(row => row.projectId === commitment.projectId && row.available && row.isCurrent);
    assert.equal(sources.length, 3); assert.equal((await json(context, '/invoices')).value.length, 0);
    await page.goto(base + '/invoices'); await snapshot(page, 'invoices-empty', width);
    await page.goto(base + `/commitments/${commitment.id}`);
    await page.getByRole('link', { name: 'Prepare a bill', exact: true }).click();
    await page.getByRole('table', { name: 'Bill preparation schedule of values', exact: true }).waitFor();
    await snapshot(page, 'bill-preparation', width);
    const amounts = ['12345.67', '23456.78'];
    for (let i = 0; i < preparation.lines.length; i++) await page.getByRole('textbox', { name: `Installed to date for ${preparation.lines[i].description}`, exact: true }).fill(amounts[i]);
    await page.getByRole('textbox', { name: `Installed to date for ${preparation.lines[0].description}`, exact: true }).fill('0.001');
    assert.equal(await page.getByRole('button', { name: 'Review preparation', exact: true }).count(), 0, 'Fractional cents must block review.');
    await page.getByRole('textbox', { name: `Installed to date for ${preparation.lines[0].description}`, exact: true }).fill('90071992547409.92');
    assert.equal(await page.getByRole('button', { name: 'Review preparation', exact: true }).count(), 0, 'Unsafe integer cents must block review.');
    await page.getByRole('textbox', { name: `Installed to date for ${preparation.lines[0].description}`, exact: true }).fill(amounts[0]);
    await page.getByRole('button', { name: 'Review preparation', exact: true }).click();
    await page.getByRole('button', { name: 'Prepare draft bill', exact: true }).waitFor(); await snapshot(page, 'bill-preparation-review', width);
    const prepared = await actionResponse(page, `/commitments/${commitment.id}/prepare-bill`, () => page.getByRole('button', { name: 'Prepare draft bill', exact: true }).click());
    assert.equal(prepared.value.result.status, 'draft'); assert.equal(prepared.value.result.journalDelta, 0); assert.equal(prepared.value.result.apDeltaCents, 0);
    await page.getByText('Certified draft bill prepared.', { exact: true }).waitFor(); await exactRetry(page, `/commitments/${commitment.id}/prepare-bill`, 'bill.prepare', prepared, width);
    await page.getByRole('link', { name: commitment.commitmentTitle ?? commitment.title, exact: true }).first().click();
    await page.getByRole('link', { name: 'Prepare a bill', exact: true }).click();
    await exactRetry(page, `/commitments/${commitment.id}/prepare-bill`, 'bill.prepare', prepared, width);
    const billId = prepared.value.result.billId; const bill = await json(context, `/bills/${billId}`);
    assert.equal(bill.status, 'draft'); assert.equal(bill.currentDueCents, 0); assert.equal(bill.posting, null);
    await receive(page, context, commitment, 'SYN-INTAKE-2026-100', bill.amountDueCents, sources[0]);
    await snapshot(page, 'invoice-receipt-form', width);
    await page.getByRole('button', { name: 'Review invoice receipt', exact: true }).click();
    await page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).waitFor(); await snapshot(page, 'invoice-receipt-review', width);
    const received = await actionResponse(page, `/commitments/${commitment.id}/receive-invoice`, () => page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).click());
    assert.equal(received.value.result.status, 'received'); assert.equal(received.value.result.amountCents, bill.amountDueCents);
    await page.getByText('Supplier invoice received.', { exact: true }).waitFor(); await exactRetry(page, `/commitments/${commitment.id}/receive-invoice`, 'invoice.receive', received, width);
    const invoiceId = received.value.result.invoiceId;
    await page.getByRole('link', { name: 'Open received invoice', exact: true }).click();
    await page.getByRole('button', { name: 'Review matching', exact: true }).waitFor(); await snapshot(page, 'invoice-source-record', width);
    const matched = await reviewedAction(page, `/invoices/${invoiceId}/compute-match`, 'invoice.computeMatch', 'Review matching', 'Compute invoice match');
    assert.equal(matched.value.result.status, 'matched'); assert.equal(matched.value.result.billId, billId); assert.deepEqual(matched.value.result.exceptions, []);
    await page.getByText('Invoice match computed.', { exact: true }).waitFor(); await exactRetry(page, `/invoices/${invoiceId}/compute-match`, 'invoice.computeMatch', matched, width);
    const matchRequested = await reviewedAction(page, `/invoices/${invoiceId}/request-match-approval`, 'invoice.requestMatchApproval', 'Review match request', 'Request match approval');
    assert.equal(matchRequested.value.result.status, 'pending');
    await page.getByText('Invoice match approval requested.', { exact: true }).waitFor(); await exactRetry(page, `/invoices/${invoiceId}/request-match-approval`, 'invoice.requestMatchApproval', matchRequested, width);
    const matchId = matchRequested.value.result.approvalId;
    await choosePerson(page, 'reviewer'); await page.goto(base + '/match-approvals'); await snapshot(page, 'match-review-queue', width);
    await page.getByRole('link', { name: /SYN-INTAKE-2026-100/ }).click();
    await page.getByRole('button', { name: 'Review match approval', exact: true }).waitFor(); await snapshot(page, 'independent-match-packet', width);
    const packet = await json(context, `/match-approvals/${matchId}/packet`); const reviewer = await json(context, '/session');
    assert.notEqual(packet.requestedBy.id, reviewer.person.id);
    const granted = await reviewedAction(page, `/match-approvals/${matchId}/approve`, 'invoice.approveMatch', 'Review match approval', 'Approve invoice match');
    assert.equal(granted.value.result.status, 'granted'); assert.equal(granted.value.result.journalDelta, 0); assert.equal(granted.value.result.apDeltaCents, 0);
    await page.getByText('Invoice match approved.', { exact: true }).waitFor(); await exactRetry(page, `/match-approvals/${matchId}/approve`, 'invoice.approveMatch', granted, width);
    assert.equal((await json(context, `/bills/${billId}`)).currentDueCents, 0);
    await choosePerson(page, 'accountant'); await page.goto(base + `/match-approvals/${matchId}`);
    await page.getByRole('button', { name: 'Review approved match', exact: true }).waitFor(); await snapshot(page, 'approved-match-to-apply', width);
    const applied = await reviewedAction(page, `/match-approvals/${matchId}/execute`, 'invoice.executeMatch', 'Review approved match', 'Apply approved match');
    assert.equal(applied.value.result.status, 'matched'); assert.equal(applied.value.result.billId, billId); assert.equal(applied.value.result.journalDelta, 0);
    await page.getByText('Approved invoice match applied to the bill.', { exact: true }).waitFor(); await exactRetry(page, `/match-approvals/${matchId}/execute`, 'invoice.executeMatch', applied, width);
    await page.getByRole('link', { name: 'Open linked bill', exact: true }).click();
    const requested = await reviewedAction(page, `/bills/${billId}/request-approval`, 'bill.requestApproval', 'Review request', 'Request business approval');
    await choosePerson(page, 'pm'); await page.goto(base + `/approvals/${requested.value.result.approvalId}`);
    const business = await reviewedAction(page, `/approvals/${requested.value.result.approvalId}/approve`, 'bill.approve', 'Review approval', 'Approve bill');
    assert.equal(business.value.result.journalDelta, 0); assert.equal(business.value.result.apDeltaCents, 0);
    await choosePerson(page, 'accountant'); await page.goto(base + `/bills/${billId}`);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click(); await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
    const posted = await actionResponse(page, `/bills/${billId}/post`, () => page.getByRole('dialog').getByRole('button', { name: `Post to ${bill.certificationPeriod.name}`, exact: true }).click());
    assert.equal(posted.value.result.status, 'posted'); await page.getByText('Bill posted to the practice working ledger.', { exact: true }).waitFor(); await snapshot(page, 'intake-bill-posted', width);
    const postedBill = await json(context, `/bills/${billId}`); assert.equal(postedBill.currentDueCents, bill.amountDueCents); assert.equal(postedBill.posting.journalIds.length, 1);
    await page.goto(base + '/invoices'); await page.getByRole('table', { name: 'Supplier invoices', exact: true }).waitFor(); await snapshot(page, 'invoices-after-match', width);
    await page.getByRole('textbox', { name: 'Search invoices', exact: true }).fill('No such supplier invoice');
    await page.getByText('No supplier invoices match this view. Open a subcontract to receive an invoice.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await receive(page, context, commitment, 'SYN-INTAKE-2026-100', bill.amountDueCents, sources[1]);
    const duplicateWait = page.waitForResponse(response => new URL(response.url()).pathname === prefix + `/commitments/${commitment.id}/receive-invoice:preflight`);
    await page.getByRole('button', { name: 'Review invoice receipt', exact: true }).click(); const duplicate = await duplicateWait;
    assert.equal(duplicate.status(), 200); const duplicateReview = await duplicate.json();
    assert.equal(duplicateReview.allowed, false); assert.equal(duplicateReview.fingerprint, null);
    assert.ok(duplicateReview.checks.some(check => check.code === 'duplicate_invoice' && check.status === 'blocked'));
    await page.getByText('This step is blocked. Read the checks and refresh after the cause is resolved.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).count(), 0); await snapshot(page, 'duplicate-invoice-refused', width);
    report.refusals.push({ width, code: 'duplicate_invoice', actualBackend: true, blockedPureReview: true });
    const mismatchCommitment = commitments.find(row => row.id !== commitment.id && row.projectId === commitment.projectId);
    assert.ok(mismatchCommitment, 'The mismatch branch needs a genuine eligible unlinked bill.');
    await receive(page, context, mismatchCommitment, 'SYN-INTAKE-2026-101', 100, sources[1]);
    const mismatch = await reviewedAction(page, `/commitments/${mismatchCommitment.id}/receive-invoice`, 'invoice.receive', 'Review invoice receipt', 'Receive supplier invoice');
    await page.getByRole('link', { name: 'Open received invoice', exact: true }).click();
    const mismatched = await reviewedAction(page, `/invoices/${mismatch.value.result.invoiceId}/compute-match`, 'invoice.computeMatch', 'Review matching', 'Compute invoice match');
    assert.equal(mismatched.value.result.status, 'exception'); assert.ok(mismatched.value.result.exceptions.includes('amount_mismatch'));
    await page.getByText('The invoice amount does not equal the eligible certified bill.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Request match approval', exact: true }).count(), 0); await snapshot(page, 'amount-mismatch-held', width);
    report.refusals.push({ width, code: 'amount_mismatch', actualBackend: true, approvalUnavailable: true });
    await receive(page, context, commitment, 'SYN-INTAKE-2026-102', 12300, sources[2]);
    await page.getByRole('button', { name: 'Review invoice receipt', exact: true }).click();
    await page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).waitFor();
    const beforeStale = (await json(context, '/invoices')).count;
    await advanceEvidence();
    expectHTTP('POST', `/commitments/${commitment.id}/receive-invoice`, 423);
    const staleWait = page.waitForResponse(response => new URL(response.url()).pathname === prefix + `/commitments/${commitment.id}/receive-invoice`);
    await page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).click();
    const stale = await staleWait; assert.equal(stale.status(), 423); assert.equal((await stale.json()).error.code, 'evidence_stale');
    await page.getByRole('alert').waitFor(); await snapshot(page, 'stale-source-evidence-refused', width);
    assert.equal((await json(context, '/invoices')).count, beforeStale, 'Stale source receipt must not create an invoice.');
    report.refusals.push({ width, code: 'evidence_stale', actualBackend: true, genuineOwnedSourceRevision: true, invoiceNotCreated: true });
    if (width === 1440) {
      const currentSource = (await json(context, '/invoice-evidence')).value.find(row => row.documentId === sources[2].documentId);
      assert.equal(currentSource.revision, sources[2].revision + 1);
      await receive(page, context, commitment, 'SYN-INTAKE-2026-103', bill.amountDueCents, currentSource);
      const warningWait = page.waitForResponse(response => new URL(response.url()).pathname === prefix + `/commitments/${commitment.id}/receive-invoice:preflight`);
      await page.getByRole('button', { name: 'Review invoice receipt', exact: true }).click();
      const warning = await (await warningWait).json(); assert.equal(warning.allowed, true); assert.equal(warning.safeEffects.possibleDuplicate, true);
      assert.ok(warning.checks.some(check => check.code === 'possible_duplicate' && check.status === 'warning'));
      await page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).waitFor();
      const possibleDuplicate = await actionResponse(page, `/commitments/${commitment.id}/receive-invoice`, () => page.getByRole('button', { name: 'Receive supplier invoice', exact: true }).click());
      assert.equal(possibleDuplicate.value.result.possibleDuplicate, true);
      await page.getByRole('link', { name: 'Open received invoice', exact: true }).click();
      await page.getByText('Required before match approval', { exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Review match request', exact: true }).count(), 0);
      await snapshot(page, 'possible-duplicate-held', width);
      report.refusals.push({ width, code: 'possible_duplicate', actualBackend: true, receiptWarningDisplayed: true, matchApprovalUnavailable: true });
      await contractChecks(context, invoiceId);
    }
    await page.getByRole('button', { name: 'Help', exact: true }).click(); await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' }); assert.equal(await page.getByRole('button', { name: 'Help', exact: true }).evaluate(element => element === document.activeElement), true);
    if (width === 390) { await page.getByRole('button', { name: 'Open navigation', exact: true }).click(); await page.getByRole('dialog').getByRole('link', { name: 'Invoices', exact: true }).click(); await page.getByRole('heading', { name: 'Invoices', exact: true }).waitFor(); }
    for (const message of consoleHTTP) if (!verifiedHTTP.has(`${message.status}:${message.url}`)) report.errors.push({ width, kind: 'unverified HTTP console error', ...message });
    assert.equal(diagnostics(), '', 'The intake server reported an unexpected exception.');
    report.journeys.push({ width, preparedDraft: true, ownedEvidence: true, invoiceReceived: true, matchComputed: true,
      distinctMatchReviewer: true, requesterAppliedMatch: true, pmBusinessApproved: true, independentlyPosted: true,
      amountDueCents: bill.amountDueCents, journalCount: 1, journalFreeIntake: true, retrySurvivesNavigation: true });
    report.widths.push(width); await context.close(); await stopServer();
  }
  await writeFile(path.join(artifacts, 'ap-intake-smoke.json'), JSON.stringify(report, null, 2));
  assert.deepEqual(report.violations, [], 'The intake views have automated accessibility findings.');
  assert.deepEqual(report.errors, [], 'The intake browser reported application, CSP or unexpected HTTP errors.');
  console.log(JSON.stringify({ source: report.source, widths: report.widths, views: report.views.length, journeys: report.journeys.length,
    exactRetries: report.exactRetries.length, actualRefusals: report.refusals.length, contractChecks: report.contractChecks.length,
    accessibilityViolations: report.violations.length, browserErrors: report.errors.length }));
} catch (error) {
  await writeFile(path.join(artifacts, 'ap-intake-smoke-failed.json'), JSON.stringify(report, null, 2)); throw error;
} finally { await browser?.close(); await stopServer(); }
