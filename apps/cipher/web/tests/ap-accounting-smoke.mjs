import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { mkdir, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const directory = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const repository = path.resolve(directory, '../../..');
const port = Number(process.env.CIPHER_ACCOUNTING_PORT ?? 18770);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/ap-practice/v1';
const artifacts = process.env.CIPHER_ACCOUNTING_ARTIFACTS ?? '/tmp/cipher-completion/ap-accounting-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', datePresentationZone: 'America/New_York', widths: [], views: [], journeys: [], exactRetries: [], contractChecks: [],
  violations: [], errors: [], requests: [], counters: [], recoverySteps: [],
  axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard traversal remains checked'] };
let server;
let serverLines;
let browser;
// Owned, disposable factory only. Fixed stdin commands inject bounded supported
// simulator faults. This creates no HTTP endpoint or caller-selected runtime.
const fixtureControl = `
import json
import sys
from threading import Thread
from apps.cipher.ap_practice_server import make_ap_practice_server
from apps.cipher.accounting_simulator import Fault
server = make_ap_practice_server(port=int(sys.argv[1]))
def controls():
    for command in sys.stdin:
        if command == "timeout_after_acceptance\\n":
            server.accounting_adapter.queue_fault("submit", Fault.TIMEOUT_AFTER_ACCEPTANCE)
            print(json.dumps({"faultQueued": True}), flush=True)
        elif command == "timeout_before_acceptance\\n":
            server.accounting_adapter.queue_fault("submit", Fault.TIMEOUT_BEFORE_ACCEPTANCE)
            print(json.dumps({"faultQueued": True}), flush=True)
        elif command == "readback_unavailable\\n":
            server.accounting_adapter.queue_fault("read_record", Fault.LOOKUP_TIMEOUT)
            print(json.dumps({"faultQueued": True}), flush=True)
        elif command == "readback_malformed\\n":
            server.accounting_adapter.queue_fault("read_record", Fault.READBACK_MISMATCH)
            print(json.dumps({"faultQueued": True}), flush=True)
        elif command == "counts\\n":
            with server.cipher_lock, server.cipher.db._lock:
                print(json.dumps({"effects": server.accounting_store.effect_count,
                    "calls": dict(server.accounting_adapter.calls),
                    "journals": server.cipher.db.scalar("SELECT COUNT(*) FROM journals"),
                    "nativeSubmissions": len(server.cipher.provider.submissions),
                    "nativeTransfers": len(server.cipher.provider.transfers)}), flush=True)
        else:
            raise ValueError("Unsupported bounded fixture control")
Thread(target=controls, daemon=True).start()
try:
    server.serve_forever()
finally:
    server.server_close()
`;
async function startServer() {
  server = spawn(process.env.CIPHER_PYTHON ?? 'python', ['-u', '-c', fixtureControl, String(port)], { cwd: repository, stdio: ['pipe', 'pipe', 'pipe'] });
  serverLines = createInterface({ input: server.stdout });
  let diagnostics = ''; server.stderr.on('data', chunk => { diagnostics += chunk.toString(); });
  for (let attempt = 0; attempt < 120; attempt++) {
    if (server.exitCode !== null) throw new Error(`The isolated accounting server exited (${server.exitCode}): ${diagnostics}`);
    try { if ((await fetch(base)).ok) return () => diagnostics; } catch { /* Waiting for the local listener. */ }
    await delay(100);
  }
  throw new Error('The isolated accounting server did not become ready.');
}
async function control(command) {
  const acknowledgment = once(serverLines, 'line', { signal: AbortSignal.timeout(10_000) });
  server.stdin.write(command + '\n'); const [line] = await acknowledgment; return JSON.parse(line);
}
async function stopServer() {
  if (!server || server.exitCode !== null) { server = undefined; return; }
  const closed = once(server, 'exit'); server.kill('SIGTERM'); await closed; serverLines?.close(); server = undefined;
}
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json(); assert.equal(value.mode, 'practice'); assert.equal(value.synthetic, true); assert.equal(value.contractVersion, 'cipher.ap-practice.v1'); return value;
}
async function selectPerson(page, persona) {
  if (await page.getByRole('button', { name: 'Change practice person', exact: true }).count()) await page.getByRole('button', { name: 'Change practice person', exact: true }).click();
  await page.getByRole('heading', { name: 'Start a practice session', exact: true }).waitFor();
  await page.getByRole('button', { name: ({ accountant: /Start as Alex Rivera/, reviewer: /Start as Jordan Chen/, pm: /Start as Morgan Lee/ })[persona] }).click();
  await page.getByRole('heading', { name: persona === 'pm' ? 'My projects' : 'Books', level: 1, exact: true }).waitFor();
}
async function snapshot(page, name, width) {
  await page.locator('main[aria-busy="false"]').waitFor(); await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.getByRole('heading', { level: 1 }).waitFor(); assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1);
  await page.evaluate(() => window.scrollTo(0, 0)); await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth })); assert.ok(size.document <= size.viewport, `${name} overflows at ${width}px.`);
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  report.violations.push(...axe.violations.map(item => ({ name, width, id: item.id, nodes: item.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content'); assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width });
}
async function response(page, route, click, expectedStatus = 200) {
  const waiting = page.waitForResponse(value => new URL(value.url()).pathname === prefix + route && value.request().method() === 'POST');
  await click(); const result = await waiting; assert.equal(result.status(), expectedStatus, `${route}: ${await result.text()}`);
  return { value: await result.json(), key: result.request().headers()['repeatability-request-id'], version: result.request().headers()['if-match'], body: result.request().postData() };
}
const steps = {
  'accounting.prepare': ['Review handoff preparation', 'Prepare practice handoff', 'bills', 'prepare-accounting', 'accounting-preparation'],
  'accounting.request': ['Review handoff request', 'Request handoff approval', 'accounting-plans', 'request-approval', 'review'],
  'accounting.approve': ['Review handoff approval', 'Approve practice handoff', 'accounting-approvals', 'approve', 'packet'],
  'accounting.queue': ['Review approved handoff', 'Queue approved practice handoff', 'accounting-approvals', 'queue', 'packet'],
  'accounting.deliver': ['Review practice delivery', 'Run practice delivery', 'accounting-intents', 'deliver', 'review'],
  'accounting.lookup': ['Review original outcome lookup', 'Look up original outcome', 'accounting-intents', 'lookup', 'review'],
  'accounting.reconcile': ['Review simulation readback', 'Reconcile simulation', 'accounting-intents', 'reconcile', 'review'],
};
function assertAccountingResult(result) {
  assert.equal(result.simulation, true); assert.equal(result.quickBooksAccepted, false);
  assert.equal(result.journalCountDelta, 0); assert.equal(result.apBalanceDeltaCents, 0);
  assert.equal(/"(?:lease[^" ]*|credentials|accessToken|refreshToken|realmId)"/i.test(JSON.stringify(result)), false);
}
async function act(page, action, id, keyboard = false, expectedStatus = 200, nextStep = false) {
  const [reviewLabel, applyLabel, collection, command, detail] = steps[action]; const resource = `/${collection}/${id}`;
  const current = await json(page.context(), `${resource}/${detail}`);
  await page.waitForFunction(({ action, version }) => document.querySelector(`[data-action="${action}"]`)?.getAttribute('data-resource-version') === version, { action, version: current.version });
  const panel = page.locator(`[data-action="${action}"]`);
  const reviewButton = nextStep ? 'Review next practice step' : reviewLabel;
  if (keyboard) { await panel.getByRole('button', { name: reviewButton, exact: true }).focus(); await page.keyboard.press('Enter'); }
  else await panel.getByRole('button', { name: reviewButton, exact: true }).click();
  const preflight = await panel.getByRole('button', { name: applyLabel, exact: true }).waitFor(); void preflight;
  const first = await response(page, `${resource}/${command}`, () => panel.getByRole('button', { name: applyLabel, exact: true }).click(), expectedStatus);
  if (expectedStatus === 200) assertAccountingResult(first.value.result);
  else { assert.equal(first.value.retrySameRequest, true); assert.equal(first.value.effectApplied, false); assert.equal(first.value.result, undefined); }
  assert.ok(first.key); assert.deepEqual(Object.keys(JSON.parse(first.body)), ['fingerprint']); return first;
}
async function retry(page, action, id, first, width) {
  const [, , collection, command] = steps[action];
  const again = await response(page, `/${collection}/${id}/${command}`, () => page.locator(`[data-action="${action}"]`).getByRole('button', { name: 'Retry same action', exact: true }).click());
  assert.equal(again.key, first.key); assert.equal(again.body, first.body); assert.equal(again.value.receiptId, first.value.receiptId);
  assert.equal(again.value.replayed, true); assert.equal(again.value.effectApplied, false); assert.deepEqual(again.value.result, first.value.result);
  report.exactRetries.push({ width, action, originalStatus: first.value.result.status });
}
async function originalReceipt(context, route, original, width) {
  const session = await json(context, '/session');
  const actual = await context.request.post(base + prefix + route, { headers: {
    Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken,
    'If-Match': original.version, 'Repeatability-Request-ID': original.key,
  }, data: original.body });
  assert.equal(actual.status(), 200, await actual.text()); const value = await actual.json();
  assert.equal(value.receiptId, original.value.receiptId); assert.equal(value.replayed, true); assert.equal(value.effectApplied, false); assert.deepEqual(value.result, original.value.result);
  report.exactRetries.push({ width, action: 'accounting.deliver', originalStatus: original.value.result.status, afterExplicitNewStep: true });
}
function nativeUnchanged(before, after) {
  assert.equal(after.journals, before.journals); assert.equal(after.nativeSubmissions, before.nativeSubmissions); assert.equal(after.nativeTransfers, before.nativeTransfers);
}
function countsEqual(before, after) { nativeUnchanged(before, after); assert.equal(after.effects, before.effects); assert.deepEqual(after.calls, before.calls); }
async function approveAndPostSources(page, context, draft, approved) {
  await page.goto(base + `/bills/${draft.id}`); await page.getByRole('button', { name: 'Review request', exact: true }).click();
  await response(page, `/bills/${draft.id}/request-approval`, () => page.getByRole('button', { name: 'Request business approval', exact: true }).click());
  const pending = await json(context, `/bills/${draft.id}`); const id = pending.businessApproval.approvalId;
  await selectPerson(page, 'pm'); await page.goto(base + `/approvals/${id}`); await page.getByRole('button', { name: 'Review approval', exact: true }).click();
  await response(page, `/approvals/${id}/approve`, () => page.getByRole('button', { name: 'Approve bill', exact: true }).click());
  await selectPerson(page, 'accountant');
  const grant = await json(context, `/bills/${draft.id}`); const later = grant.postingPeriods.find(period => period.endDate === '2026-11-30'); assert.ok(later);
  assert.equal(grant.certificationPeriod.endDate, '2026-10-31');
  for (const [bill, period, reason] of [[grant, later, 'Synthetic later-period handoff qualification'], [approved, approved.certificationPeriod, '']]) {
    await page.goto(base + `/bills/${bill.id}`); await page.getByRole('combobox', { name: 'Posting period', exact: true }).selectOption(period.id);
    if (reason) await page.getByRole('textbox', { name: 'Posting reason', exact: true }).fill(reason);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click(); await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
    await response(page, `/bills/${bill.id}/post`, () => page.getByRole('dialog').getByRole('button', { name: `Post to ${period.name}`, exact: true }).click());
  }
}
async function assertSource(page, plan, expected, expectedDate) {
  assert.deepEqual([plan.original.originalCostCents, plan.original.originalApCents, plan.original.originalRetainageCents], expected);
  assert.equal(plan.original.sourcePeriod.endDate, expectedDate); assert.equal(plan.date.transactionDate, expectedDate);
  assert.equal(plan.date.policy, 'synthetic.period-end.v1'); assert.equal(plan.date.qualification, 'synthetic_only');
  assert.equal(plan.capability.quickBooksAccepted, false); assert.equal(plan.capability.liveDatePolicy, 'unqualified');
  assert.equal(BigInt(expected[0]), BigInt(expected[1]) + BigInt(expected[2]));
  const formatted = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value / 100);
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Original posted obligation', exact: true }) });
  for (const [label, cents] of [['Original certified cost', expected[0]], ['Original AP liability', expected[1]], ['Original retained liability', expected[2]]]) {
    const fact = section.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) });
    await fact.waitFor(); assert.equal(await fact.locator('dd').innerText(), formatted(cents));
  }
  const calendar = section.locator('dl > div').filter({ has: page.getByText('Practice transaction date', { exact: true }) }).locator('dd');
  await calendar.waitFor();
  assert.equal(await calendar.evaluate(element => Array.from(element.childNodes).filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent).join('').trim()), expectedDate === '2026-11-30' ? 'Nov 30, 2026' : 'Oct 31, 2026');
  const entry = page.getByRole('table', { name: 'Practice handoff entry', exact: true });
  for (const code of ['5000', '2000', '2050']) await entry.getByText(new RegExp(`^${code} ·`)).waitFor();
  await page.getByText(/QuickBooks official books and payments are unavailable/).waitFor();
}
async function prepareQueue(page, context, bill, expected, expectedDate, width) {
  const before = await control('counts');
  await page.goto(base + `/bills/${bill.id}/accounting-preparation`); await page.getByRole('heading', { name: 'Prepare practice accounting handoff', exact: true }).waitFor();
  await snapshot(page, `preparation-${expectedDate}`, width);
  let originalPreparation;
  if (width === 1440 && expectedDate === '2026-11-30') {
    let changed = false;
    await page.route(`**${prefix}/bills/${bill.id}/prepare-accounting`, async route => {
      const actual = await route.fetch(); const value = await actual.json();
      if (!changed) {
        assert.equal(actual.status(), 200); changed = true; originalPreparation = structuredClone(value);
        value.result.status = 'reconciled'; delete value.result.planId; delete value.result.billId;
      }
      await route.fulfill({ response: actual, json: value });
    });
  }
  let prepared = await act(page, 'accounting.prepare', bill.id, width === 1440);
  if (originalPreparation) {
    await page.locator('[data-action="accounting.prepare"]').getByRole('alert').waitFor();
    assert.equal(await page.getByRole('link', { name: 'Open practice handoff plan', exact: true }).count(), 0);
    prepared = { ...prepared, value: originalPreparation }; report.contractChecks.push('wrong human result status and missing identifiers refused');
  }
  await retry(page, 'accounting.prepare', bill.id, prepared, width);
  const planId = prepared.value.result.planId; await page.getByRole('link', { name: 'Open practice handoff plan', exact: true }).click();
  const plan = (await json(context, `/accounting-plans/${planId}/review`)).plan;
  await assertSource(page, plan, expected, expectedDate); await snapshot(page, `plan-${expectedDate}`, width);
  const requested = await act(page, 'accounting.request', planId); await retry(page, 'accounting.request', planId, requested, width);
  const approvalId = requested.value.result.approvalId;
  await selectPerson(page, 'reviewer'); await page.goto(base + `/accounting-approvals/${approvalId}`);
  await assertSource(page, plan, expected, expectedDate); await snapshot(page, `independent-packet-${expectedDate}`, width);
  const packet = await json(context, `/accounting-approvals/${approvalId}/packet`); const reviewer = (await json(context, '/session')).person;
  assert.notEqual(packet.approval.requestedBy.id, reviewer.id);
  const approved = await act(page, 'accounting.approve', approvalId); await retry(page, 'accounting.approve', approvalId, approved, width);
  const grant = await json(context, `/accounting-approvals/${approvalId}/packet`); assert.equal(grant.approval.approvedBy.id, reviewer.id);
  await selectPerson(page, 'accountant'); await page.goto(base + `/accounting-approvals/${approvalId}`);
  const queued = await act(page, 'accounting.queue', approvalId); await retry(page, 'accounting.queue', approvalId, queued, width);
  const intentId = queued.value.result.intentId; countsEqual(before, await control('counts'));
  const originalBill = await json(context, `/bills/${bill.id}`); assert.equal(originalBill.currentDueCents, expected[1]); assert.equal(originalBill.status, 'posted');
  await page.getByRole('link', { name: 'Open practice delivery record', exact: true }).click();
  await snapshot(page, `queued-${expectedDate}`, width); return { plan, planId, approvalId, intentId };
}
async function contractChecks(context, { planId, billId, approvalId, intentId }) {
  for (const [name, mutate] of [
    ['unsafe original cents', value => { value.plan.original.originalCostCents = Number.MAX_SAFE_INTEGER + 1; }],
    ['null original retainage', value => { value.plan.original.originalRetainageCents = null; }],
    ['wrong date policy', value => { value.plan.date.policy = 'live.today'; }],
    ['certification date substituted for posting date', value => { value.plan.date.transactionDate = '2026-10-31'; value.plan.transactionDate = '2026-10-31'; }],
    ['non-calendar date', value => { value.plan.date.transactionDate = '2026-11-31'; value.plan.transactionDate = '2026-11-31'; }],
    ['unsupported capability route', value => { value.plan.capability.route = 'quickbooks.live'; }],
    ['official acknowledgement claim', value => { value.plan.capability.quickBooksAccepted = true; }],
    ['live provenance', value => { value.mode = 'live'; }],
    ['private lease field', value => { value.plan.leaseToken = 'unsupported-private-field'; }],
    ['unbalanced mapped preview', value => { value.plan.preview.lines[0].debitCents += 1; }],
    ['invalid source posting timestamp', value => { value.plan.original.sourcePostedAt = 'invalid timestamp'; }],
    ['wrong plan route identity', value => { value.plan.id = 'unrelated-plan'; }],
  ]) {
    const page = await context.newPage(); page.on('pageerror', error => report.errors.push({ width: 1440, check: name, message: error.message }));
    await page.route(`**${prefix}/accounting-plans/${planId}/review`, async route => {
      const response = await route.fetch(); const value = await response.json(); mutate(value); await route.fulfill({ response, json: value });
    });
    await page.goto(base + `/accounting-plans/${planId}`); await page.getByRole('alert').waitFor();
    assert.equal(await page.getByRole('table', { name: 'Practice handoff entry', exact: true }).count(), 0);
    assert.equal(await page.locator('[data-action^="accounting."]').count(), 0); report.contractChecks.push(name); await page.close();
  }
  for (const [name, read, location, mutate] of [
    ['wrong source bill route identity', `/bills/${billId}/accounting-preparation`, `/bills/${billId}/accounting-preparation`, value => { value.bill.id = 'unrelated-bill'; }],
    ['wrong approval route identity', `/accounting-approvals/${approvalId}/packet`, `/accounting-approvals/${approvalId}`, value => { value.approval.id = 'unrelated-approval'; }],
    ['invalid approval expiry timestamp', `/accounting-approvals/${approvalId}/packet`, `/accounting-approvals/${approvalId}`, value => { value.approval.expiresAt = 'invalid timestamp'; }],
    ['wrong intent route identity', `/accounting-intents/${intentId}/review`, `/accounting-intents/${intentId}`, value => { value.intent.id = 'unrelated-intent'; }],
    ['invalid intent update timestamp', `/accounting-intents/${intentId}/review`, `/accounting-intents/${intentId}`, value => { value.intent.updatedAt = 'invalid timestamp'; }],
  ]) {
    const page = await context.newPage(); page.on('pageerror', error => report.errors.push({ width: 1440, check: name, message: error.message }));
    await page.route(`**${prefix}${read}`, async route => { const response = await route.fetch(); const value = await response.json(); mutate(value); await route.fulfill({ response, json: value }); });
    await page.goto(base + location); await page.getByRole('alert').waitFor(); assert.equal(await page.locator('[data-action^="accounting."]').count(), 0);
    report.contractChecks.push(name); await page.close();
  }
  const refresh = await context.newPage(); let malformed = false;
  refresh.on('pageerror', error => report.errors.push({ width: 1440, check: 'malformed refreshed packet', message: error.message }));
  await refresh.route(`**${prefix}/accounting-plans/${planId}/review`, async route => { const response = await route.fetch(); const value = await response.json(); if (malformed) value.plan.original.originalCostCents = null; await route.fulfill({ response, json: value }); });
  await refresh.goto(base + `/accounting-plans/${planId}`); await refresh.getByRole('table', { name: 'Practice handoff entry', exact: true }).waitFor();
  malformed = true; await refresh.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await refresh.getByRole('alert').waitFor();
  assert.equal(await refresh.locator('[data-action^="accounting."]').count(), 0); assert.equal(await refresh.getByRole('table', { name: 'Practice handoff entry', exact: true }).count(), 0);
  report.contractChecks.push('malformed refresh removes stale facts and actions'); await refresh.close();
  const stale = await context.newPage();
  await stale.route(`**${prefix}/accounting-approvals/${approvalId}/packet`, async route => { const response = await route.fetch(); const value = await response.json(); value.approval.effectiveStatus = 'stale'; await route.fulfill({ response, json: value }); });
  await stale.goto(base + `/accounting-approvals/${approvalId}`); await stale.getByText('Facts changed', { exact: true }).waitFor(); await stale.getByRole('table', { name: 'Practice handoff entry', exact: true }).waitFor();
  assert.equal(await stale.getByRole('alert').count(), 0); report.contractChecks.push('historical stale review remains readable'); await stale.close();
}
async function preflightChecks(context, intentId) {
  for (const [name, mutate] of [
    ['readback cannot become submission', value => { value.safeEffects.intendedWorkerPhase = 'submit'; value.safeEffects.accountingSimulatorCallBound = 3; }],
    ['readback call bound is exact', value => { value.safeEffects.accountingSimulatorCallBound = 3; }],
    ['accounting review cannot promise AP change', value => { value.safeEffects.apPayableDeltaCents = 1; }],
  ]) {
    const page = await context.newPage(); page.on('pageerror', error => report.errors.push({ width: 1440, check: name, message: error.message }));
    await page.route(`**${prefix}/accounting-intents/${intentId}/reconcile:preflight`, async route => { const response = await route.fetch(); const value = await response.json(); assert.equal(value.allowed, true); mutate(value); await route.fulfill({ response, json: value }); });
    await page.goto(base + `/accounting-intents/${intentId}`); await page.getByRole('button', { name: 'Review simulation readback', exact: true }).click();
    await page.getByRole('alert').waitFor(); assert.equal(await page.getByRole('button', { name: 'Reconcile simulation', exact: true }).count(), 0);
    report.contractChecks.push(name); await page.close();
  }
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of [1440, 1024, 390]) {
    const diagnostics = await startServer(); const context = await browser.newContext({ viewport: { width, height: 1000 }, timezoneId: 'America/New_York', reducedMotion: 'reduce', hasTouch: width < 1024 });
    context.setDefaultTimeout(15_000); context.setDefaultNavigationTimeout(15_000);
    const page = await context.newPage(); page.on('pageerror', error => report.errors.push({ width, message: error.message }));
    page.on('console', message => { if (message.type() === 'error') report.errors.push({ width, message: message.text() }); });
    page.on('response', value => { if (value.status() >= 400) report.errors.push({ width, status: value.status(), route: new URL(value.url()).pathname }); });
    await page.route('**/*', route => {
      const request = route.request(); const url = new URL(request.url()); assert.equal(url.origin, base); assert.ok(['GET', 'HEAD', 'POST'].includes(request.method()));
      if (request.method() === 'POST') assert.ok(url.pathname.startsWith(prefix + '/'));
      if (url.pathname.startsWith('/api/')) report.requests.push({ width, method: request.method(), route: url.pathname }); return route.continue();
    });
    await page.goto(base); await selectPerson(page, 'accountant');
    const initial = (await json(context, '/bills')).value; const draft = initial.find(row => row.status === 'draft'); const approved = initial.find(row => row.status === 'approved'); assert.ok(draft && approved);
    assert.deepEqual([draft.thisPeriodCents, draft.amountDueCents, draft.retainageCents], [1234567, 1111110, 123457]);
    assert.deepEqual([approved.thisPeriodCents, approved.amountDueCents, approved.retainageCents], [2345678, 2111110, 234568]);
    await approveAndPostSources(page, context, draft, approved); const baseline = await control('counts');
    assert.equal(baseline.effects, 0); assert.deepEqual(baseline.calls, { submit: 0, lookup: 0, read_record: 0 });
    const happy = await prepareQueue(page, context, draft, [1234567, 1111110, 123457], '2026-11-30', width);
    let originalDelivery;
    if (width === 1440) {
      let unfinished = true;
      await page.route(`**${prefix}/accounting-intents/${happy.intentId}/deliver`, async route => {
        const actual = await route.fetch(); const value = await actual.json();
        if (unfinished) {
          assert.equal(actual.status(), 200); unfinished = false; originalDelivery = value;
          const { contractVersion, mode, synthetic, currency } = value;
          // Only the transport response is bounded here. The genuine owned
          // backend has recorded its original invocation and simulator effect.
          await route.fulfill({ response: actual, status: 202, json: { contractVersion, mode, synthetic, currency,
            invocationId: value.result.invocationId, state: 'observed', retrySameRequest: true, replayed: false, effectApplied: false } });
        } else await route.fulfill({ response: actual, json: value });
      });
    }
    let delivered = await act(page, 'accounting.deliver', happy.intentId, false, width === 1440 ? 202 : 200);
    if (originalDelivery) {
      await page.getByText(/This original practice step is unfinished/).waitFor(); await snapshot(page, 'unfinished-original-response', width);
      assert.equal(await page.locator('[data-action="accounting.deliver"]').getByRole('button', { name: 'Review next practice step', exact: true }).count(), 0);
      const pendingRequest = delivered; delivered = { ...delivered, value: originalDelivery };
      await retry(page, 'accounting.deliver', happy.intentId, delivered, width);
      assert.equal(pendingRequest.value.receiptId, undefined); report.contractChecks.push('unfinished response exact retry retrieves genuine original receipt');
    }
    assert.equal(delivered.value.result.status, 'simulated_accepted');
    await retry(page, 'accounting.deliver', happy.intentId, delivered, width); await snapshot(page, 'simulator-acknowledged', width);
    const accepted = await json(context, `/accounting-intents/${happy.intentId}/review`); assert.equal(accepted.intent.status, 'simulated_accepted'); assert.equal(accepted.intent.hasAcceptance, true);
    const afterDelivery = await control('counts'); nativeUnchanged(baseline, afterDelivery); assert.equal(afterDelivery.effects, 1); assert.deepEqual(afterDelivery.calls, { submit: 1, lookup: 0, read_record: 0 });
    if (width === 1440) { await preflightChecks(context, happy.intentId); countsEqual(afterDelivery, await control('counts')); }
    const reconciled = await act(page, 'accounting.reconcile', happy.intentId); assert.equal(reconciled.value.result.status, 'reconciled');
    await retry(page, 'accounting.reconcile', happy.intentId, reconciled, width); await snapshot(page, 'happy-reconciled', width);
    const afterHappy = await control('counts'); nativeUnchanged(baseline, afterHappy); assert.equal(afterHappy.effects, 1); assert.deepEqual(afterHappy.calls, { submit: 1, lookup: 0, read_record: 1 });
    const uncertain = await prepareQueue(page, context, approved, [2345678, 2111110, 234568], '2026-10-31', width);
    assert.deepEqual(await control('timeout_before_acceptance'), { faultQueued: true });
    const beforeAcceptance = await act(page, 'accounting.deliver', uncertain.intentId); assert.equal(beforeAcceptance.value.result.status, 'outcome_unknown');
    await retry(page, 'accounting.deliver', uncertain.intentId, beforeAcceptance, width); await snapshot(page, 'unknown-before-acceptance', width);
    const missing = await act(page, 'accounting.lookup', uncertain.intentId); assert.equal(missing.value.result.status, 'confirmed_missing');
    assert.equal(missing.value.result.logicalOperationId, beforeAcceptance.value.result.logicalOperationId);
    await retry(page, 'accounting.lookup', uncertain.intentId, missing, width);
    const queuedAgain = await json(context, `/accounting-intents/${uncertain.intentId}/review`); assert.equal(queuedAgain.intent.status, 'queued'); assert.equal(queuedAgain.intent.hasAcceptance, false);
    const afterMissing = await control('counts'); nativeUnchanged(baseline, afterMissing); assert.equal(afterMissing.effects, 1); assert.deepEqual(afterMissing.calls, { submit: 2, lookup: 1, read_record: 1 });
    // Until the person explicitly chooses a new review, the old outcome and
    // exact retry remain available; Missing itself never submits an entry.
    await retry(page, 'accounting.deliver', uncertain.intentId, beforeAcceptance, width); countsEqual(afterMissing, await control('counts'));
    await snapshot(page, 'confirmed-missing-awaits-explicit-review', width);
    assert.deepEqual(await control('timeout_after_acceptance'), { faultQueued: true });
    const unknown = await act(page, 'accounting.deliver', uncertain.intentId, false, 200, true); assert.equal(unknown.value.result.status, 'outcome_unknown');
    assert.notEqual(unknown.key, beforeAcceptance.key); assert.equal(unknown.value.result.logicalOperationId, beforeAcceptance.value.result.logicalOperationId);
    report.recoverySteps.push({ width, case: 'confirmed Missing → explicit new delivery review', originalLogicalOperationPreserved: true });
    await retry(page, 'accounting.deliver', uncertain.intentId, unknown, width); await snapshot(page, 'unknown-after-acceptance', width);
    const unknownRead = await json(context, `/accounting-intents/${uncertain.intentId}/review`); assert.equal(unknownRead.intent.status, 'outcome_unknown'); assert.equal(unknownRead.intent.lookupRequired, true); assert.equal(unknownRead.intent.hasAcceptance, false);
    assert.equal(await page.locator('[data-action="accounting.deliver"]').getByRole('button', { name: 'Run practice delivery', exact: true }).count(), 0);
    const afterUnknown = await control('counts'); nativeUnchanged(baseline, afterUnknown); assert.equal(afterUnknown.effects, 2); assert.deepEqual(afterUnknown.calls, { submit: 3, lookup: 1, read_record: 1 });
    const recovered = await act(page, 'accounting.lookup', uncertain.intentId, false, 200, true); assert.equal(recovered.value.result.status, 'simulated_accepted'); assert.notEqual(recovered.key, missing.key);
    assert.equal(recovered.value.result.logicalOperationId, unknown.value.result.logicalOperationId);
    await retry(page, 'accounting.lookup', uncertain.intentId, recovered, width); await snapshot(page, 'original-outcome-recovered', width);
    assert.deepEqual(await control('readback_unavailable'), { faultQueued: true });
    const unavailable = await act(page, 'accounting.reconcile', uncertain.intentId); assert.equal(unavailable.value.result.status, 'reconciliation_unavailable');
    await retry(page, 'accounting.reconcile', uncertain.intentId, unavailable, width); await snapshot(page, 'readback-unavailable-acknowledgment-retained', width);
    const acknowledgmentRetained = await json(context, `/accounting-intents/${uncertain.intentId}/review`); assert.equal(acknowledgmentRetained.intent.status, 'simulated_accepted'); assert.equal(acknowledgmentRetained.intent.hasAcceptance, true);
    assert.equal(unavailable.value.result.recordId, recovered.value.result.recordId); assert.equal(unavailable.value.result.recordVersion, recovered.value.result.recordVersion);
    assert.deepEqual(await control('readback_malformed'), { faultQueued: true });
    const malformedReadback = await act(page, 'accounting.reconcile', uncertain.intentId, false, 200, true);
    // The fixed fault makes the payload unbalanced; qualification fails before
    // a valid authoritative comparison, so unavailable is the observed outcome.
    assert.equal(malformedReadback.value.result.status, 'reconciliation_unavailable'); assert.notEqual(malformedReadback.key, unavailable.key);
    assert.equal(malformedReadback.value.result.recordId, recovered.value.result.recordId); assert.equal(malformedReadback.value.result.recordVersion, recovered.value.result.recordVersion);
    await retry(page, 'accounting.reconcile', uncertain.intentId, malformedReadback, width); await snapshot(page, 'malformed-readback-acknowledgment-retained', width);
    const stillAcknowledged = await json(context, `/accounting-intents/${uncertain.intentId}/review`); assert.equal(stillAcknowledged.intent.status, 'simulated_accepted'); assert.equal(stillAcknowledged.intent.hasAcceptance, true);
    const readback = await act(page, 'accounting.reconcile', uncertain.intentId, false, 200, true); assert.equal(readback.value.result.status, 'reconciled'); assert.notEqual(readback.key, malformedReadback.key);
    assert.equal(readback.value.result.logicalOperationId, unknown.value.result.logicalOperationId);
    report.recoverySteps.push({ width, case: 'unavailable/malformed readback → explicit new review → reconciled', originalAcknowledgmentRetained: true });
    await retry(page, 'accounting.reconcile', uncertain.intentId, readback, width); await snapshot(page, 'unknown-reconciled', width);
    const beforeLateRetry = await control('counts'); nativeUnchanged(baseline, beforeLateRetry); assert.equal(beforeLateRetry.effects, 2); assert.deepEqual(beforeLateRetry.calls, { submit: 3, lookup: 2, read_record: 4 });
    await originalReceipt(context, `/accounting-intents/${uncertain.intentId}/deliver`, beforeAcceptance, width); countsEqual(beforeLateRetry, await control('counts'));
    // SPA navigation keeps the exact original body and UUID. Original Unknown
    // must remain Unknown even after lookup and separate readback complete.
    await page.getByRole('link', { name: 'Open accounting handoffs', exact: true }).click(); await page.getByRole('table', { name: 'Accounting practice deliveries', exact: true }).waitFor();
    await snapshot(page, 'handoff-register', width); await page.locator(`a[href="/accounting-intents/${uncertain.intentId}"]`).click();
    await retry(page, 'accounting.deliver', uncertain.intentId, unknown, width);
    await page.getByText(/Original outcome retrieved\. The original simulation outcome is unknown/).waitFor();
    const final = await json(context, `/accounting-intents/${uncertain.intentId}/review`); assert.equal(final.intent.status, 'reconciled'); assert.equal(final.intent.hasAcceptance, true);
    await page.waitForFunction(version => document.querySelector('[data-action="accounting.deliver"]')?.getAttribute('data-resource-version') === version, final.version);
    await page.locator('[data-action="accounting.deliver"]').getByText(/The original simulation outcome is unknown/).waitFor();
    countsEqual(beforeLateRetry, await control('counts')); await snapshot(page, 'original-unknown-retry-after-reconciliation', width);
    if (width < 1024) { await page.getByRole('button', { name: 'Open navigation', exact: true }).click(); await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' }); assert.equal(await page.getByRole('button', { name: 'Open navigation', exact: true }).evaluate(element => element === document.activeElement), true); }
    if (width === 1440) await contractChecks(context, { ...happy, billId: draft.id });
    const finalBills = (await json(context, '/bills')).value;
    assert.equal(finalBills.find(row => row.id === draft.id).currentDueCents, 1111110); assert.equal(finalBills.find(row => row.id === approved.id).currentDueCents, 2111110);
    await selectPerson(page, 'reviewer'); await page.goto(base + `/accounting-intents/${uncertain.intentId}`); await page.getByRole('heading', { name: /Practice delivery for Bill/, exact: false }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Retry same action', exact: true }).count(), 0);
    await selectPerson(page, 'accountant'); await page.goto(base + `/accounting-intents/${uncertain.intentId}`); await page.getByRole('heading', { name: /Practice delivery for Bill/, exact: false }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Retry same action', exact: true }).count(), 0); countsEqual(beforeLateRetry, await control('counts'));
    report.counters.push({ width, ...beforeLateRetry }); report.widths.push(width); report.journeys.push({ width, happy: 'prepared → requested → independently granted → queued → simulator acknowledged → separately reconciled', recovery: 'timeout before acceptance → Unknown → confirmed Missing → explicit fresh review → timeout after acceptance → original UUID lookup → unavailable/malformed readback → explicit fresh reviews → reconciled → original Unknown replay' });
    assert.equal(diagnostics().includes('Traceback'), false, diagnostics()); await context.close(); await stopServer();
  }
  assert.deepEqual(report.widths, [1440, 1024, 390]); assert.equal(report.violations.length, 0, JSON.stringify(report.violations)); assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
  console.log(JSON.stringify({ widths: report.widths, views: report.views.length, journeys: report.journeys.length, exactRetries: report.exactRetries.length, contractChecks: report.contractChecks.length, violations: report.violations.length, errors: report.errors.length, artifacts }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ lastView: report.views.at(-1), recentRequests: report.requests.slice(-12), errors: report.errors }, null, 2));
  throw error;
} finally {
  await writeFile(path.join(artifacts, 'ap-accounting-smoke.json'), JSON.stringify(report, null, 2) + '\n'); await browser?.close(); await stopServer();
}
