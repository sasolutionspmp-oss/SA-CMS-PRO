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
const port = Number(process.env.CIPHER_AP_PORT ?? 18767);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535, 'Choose an unused local practice test port.');
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/ap-practice/v1';
const artifacts = process.env.CIPHER_AP_ARTIFACTS ?? '/tmp/cipher-completion/ap-browser';
await mkdir(artifacts, { recursive: true });
const report = {
  source: 'actual-isolated-api', widths: [], views: [], journeys: [], violations: [], requests: [],
  expectedHttpRefusals: [], errors: [], contractChecks: [],
  axeExclusions: ['[data-tabster-dummy]: hidden Fluent/Tabster focus sentinels; keyboard traversal is checked'],
};
let browser;
let server;
async function startServer() {
  // Every viewport receives a genuine fresh in-memory engine and people registry.
  server = spawn(process.env.CIPHER_PYTHON ?? 'python', ['-m', 'apps.cipher', 'ap-practice-web', '--port', String(port)], { cwd: repository, stdio: ['ignore', 'ignore', 'pipe'] });
  let diagnostics = '';
  server.stderr.on('data', chunk => { diagnostics += chunk.toString(); });
  for (let attempt = 0; attempt < 120; attempt++) {
    if (server.exitCode !== null) throw new Error(`The isolated AP practice server exited (${server.exitCode}).`);
    try { if ((await fetch(base)).ok) return () => diagnostics; } catch { /* Wait for the loopback listener. */ }
    await delay(100);
  }
  throw new Error('The isolated AP practice server did not become ready.');
}
async function stopServer() {
  if (!server || server.exitCode !== null) { server = undefined; return; }
  const closed = once(server, 'exit'); server.kill('SIGTERM'); await closed; server = undefined;
}
async function json(context, route) {
  const response = await context.request.get(base + prefix + route);
  assert.equal(response.status(), 200, `The scoped ${route} read failed.`);
  const value = await response.json();
  assert.equal(value.contractVersion, 'cipher.ap-practice.v1'); assert.equal(value.mode, 'practice');
  assert.equal(value.synthetic, true); assert.equal(value.currency, 'USD');
  return value;
}
async function post(context, route, body, extra = {}) {
  const session = await json(context, '/session');
  return context.request.post(base + prefix + route, {
    headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken, ...extra }, data: body,
  });
}
async function snapshot(page, name, width) {
  await page.locator('main[aria-busy="false"]').waitFor();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.getByRole('heading', { level: 1 }).waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1, `${name} needs one page heading.`);
  assert.equal(await page.getByText('Practice data. Nothing here is real money and nothing is sent.', { exact: true }).count(), 1);
  const size = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
  assert.ok(size.document <= size.width, `${name} overflows at ${width}px.`);
  const accessibility = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  report.violations.push(...accessibility.violations.map(item => ({ page: name, width, id: item.id, nodes: item.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content');
  assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true });
  report.views.push({ name, width });
}
async function changePerson(page, kind) {
  await page.getByRole('button', { name: 'Change practice person', exact: true }).click();
  await page.getByRole('heading', { name: 'Start a practice session', exact: true }).waitFor();
  await page.getByRole('button', { name: kind === 'pm' ? /Start as.*project manager/i : /Start as.*accountant/i }).click();
  await page.locator('main[aria-busy="false"]').waitFor();
}
async function actionResponse(page, route, click) {
  const waiting = page.waitForResponse(response => new URL(response.url()).pathname === prefix + route && response.request().method() === 'POST');
  await click(); const response = await waiting;
  assert.equal(response.status(), 200, `The actual ${route} action failed.`);
  return { value: await response.json(), key: response.request().headers()['repeatability-request-id'], body: response.request().postData() };
}
function assertRetry(first, retry) {
  assert.ok(first.key); assert.equal(retry.key, first.key); assert.equal(retry.body, first.body);
  assert.equal(retry.value.receiptId, first.value.receiptId); assert.equal(retry.value.replayed, true);
  assert.equal(retry.value.effectApplied, false); assert.deepEqual(retry.value.result, first.value.result);
}
async function contractChecks(context, approvedExample, postedBillId) {
  for (const [name, collection, mutate, expected] of [
    ['missing bill amount', 'bills', envelope => { delete envelope.value[0].amountDueCents; }, 'incomplete'],
    ['unsafe integer cents', 'bills', envelope => { envelope.value[0].amountDueCents = Number.MAX_SAFE_INTEGER + 1; }, 'accurately'],
    ['object project name', 'projects', envelope => { envelope.value[0].name = { unsupported: true }; }, 'incomplete'],
    ['live envelope', 'projects', envelope => { envelope.mode = 'live'; }, 'supported synthetic'],
    ['unsafe aggregate', 'commitments', envelope => {
      const row = envelope.value[0]; envelope.value = [Number.MAX_SAFE_INTEGER, 1].map((amount, index) => ({ ...row, id: `precision-${index}`, executedAmountCents: amount })); envelope.count = 2;
    }, 'supported monetary range'],
  ]) {
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push({ width: 1440, check: name, message: error.message }));
    await page.route(`**${prefix}/${collection}?*`, async route => {
      const response = await route.fetch(); const envelope = await response.json(); mutate(envelope);
      await route.fulfill({ response, json: envelope });
    });
    await page.goto(base + '/projects'); await page.getByRole('alert').waitFor();
    assert.ok((await page.getByRole('alert').innerText()).includes(expected));
    assert.equal(await page.getByRole('table').count(), 0);
    assert.equal(await page.getByText('Sample fixture', { exact: true }).count(), 0);
    report.contractChecks.push(name); await page.close();
  }
  const precision = await context.newPage();
  precision.on('pageerror', error => report.errors.push({ width: 1440, check: 'exact maximum cents', message: error.message }));
  await precision.route(`**${prefix}/bills?*`, async route => {
    const response = await route.fetch(); const envelope = await response.json();
    envelope.value.find(row => row.id === postedBillId).amountDueCents = Number.MAX_SAFE_INTEGER;
    await route.fulfill({ response, json: envelope });
  });
  await precision.goto(base + `/bills/${postedBillId}`);
  await precision.getByText('$90,071,992,547,409.91', { exact: true }).waitFor();
  report.contractChecks.push('maximum safe integer cents remains exact'); await precision.close();
  for (const [name, mutate, expected] of [
    ['null reviewed debit', review => { review.safeEffects.journalPreview[0].lines[0].debitCents = null; }, 'accurately'],
    ['unsupported external accounting acknowledgement', review => { review.safeEffects.externalAccounting = 'accepted'; }, 'incomplete'],
  ]) {
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push({ width: 1440, check: name, message: error.message }));
    await page.route(`**${prefix}/bills/${approvedExample.id}/post:preflight`, async route => {
      const response = await route.fetch(); const review = await response.json(); mutate(review);
      await route.fulfill({ response, json: review });
    });
    await page.goto(base + `/bills/${approvedExample.id}`);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click();
    await page.getByRole('alert').waitFor(); assert.ok((await page.getByRole('alert').innerText()).includes(expected));
    assert.equal(await page.getByRole('table', { name: 'Reviewed entry 1', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).count(), 0);
    report.contractChecks.push(name); await page.close();
  }
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of [1440, 1024, 390]) {
    const diagnostics = await startServer();
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const expectedHTTP = new Map();
    const requestExpectations = new WeakMap();
    const verifiedHTTPFailures = new Set();
    const httpConsoleMessages = [];
    const expectHTTP = (method, pathname, status) => expectedHTTP.set(`${method}:${pathname}`, new Set([status]));
    page.on('request', request => {
      const address = new URL(request.url());
      requestExpectations.set(request, new Set(expectedHTTP.get(`${request.method()}:${address.pathname}`) ?? []));
    });
    page.on('response', response => {
      if (response.status() < 400) return;
      const request = response.request(); const pathname = new URL(response.url()).pathname;
      if (requestExpectations.get(request)?.has(response.status())) verifiedHTTPFailures.add(`${response.status()}:${response.url()}`);
      else report.errors.push({ width, message: 'Unexpected HTTP refusal', method: request.method(), pathname, status: response.status() });
    });
    page.on('pageerror', error => report.errors.push({ width, message: error.message }));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      const text = message.text(); const matched = text.match(/^Failed to load resource: the server responded with a status of (\d+) /);
      if (matched) { httpConsoleMessages.push({ width, message: text, status: Number(matched[1]), url: message.location().url }); return; }
      report.errors.push({ width, message: text, pathname: message.location().url ? new URL(message.location().url).pathname : null });
    });
    await page.route('**/*', route => {
      const request = route.request(); const address = new URL(request.url());
      assert.equal(address.origin, base, 'The AP practice browser must use its local origin only.');
      assert.ok(['GET', 'HEAD', 'POST'].includes(request.method()));
      if (request.method() === 'POST') assert.ok(address.pathname.startsWith(prefix + '/'), 'Only the explicit AP practice API accepts writes.');
      if (address.pathname.startsWith('/api/')) report.requests.push({ width, method: request.method(), pathname: address.pathname });
      return route.continue();
    });
    await page.goto(base); await snapshot(page, 'session-picker', width);
    await page.getByRole('button', { name: /Start as.*accountant/i }).click();
    await page.getByRole('heading', { name: 'Books', level: 1, exact: true }).waitFor();
    await snapshot(page, 'accountant-home', width);
    const initial = await json(context, '/bills');
    assert.equal(initial.value.length, 2, 'Hidden project bills must not be disclosed.');
    const draft = initial.value.find(bill => bill.status === 'draft');
    const approvedExample = initial.value.find(bill => bill.status === 'approved');
    assert.ok(draft && approvedExample); assert.equal(draft.amountDueCents, 1111110);
    assert.equal(draft.displayNumber, null);
    await page.goto(base + '/projects'); await snapshot(page, 'projects', width);
    await page.keyboard.press('Control+k');
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Search projects');
    await page.getByRole('textbox', { name: 'Search projects', exact: true }).fill('No matching practice project');
    await page.getByText('No projects match this search.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await page.getByRole('table', { name: 'Projects', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Help', exact: true }).click(); await page.getByRole('dialog').waitFor();
    await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: 'Help', exact: true }).evaluate(element => element === document.activeElement), true);
    await page.goto(base + `/projects/${encodeURIComponent(draft.projectId)}`); await snapshot(page, 'project', width);
    await page.goto(base + `/commitments/${encodeURIComponent(draft.commitmentId)}`); await snapshot(page, 'subcontract', width);
    await page.goto(base + `/bills/${encodeURIComponent(draft.id)}`); await snapshot(page, 'certified-draft', width);
    await page.getByRole('button', { name: 'Review request', exact: true }).click();
    await page.getByRole('button', { name: 'Request business approval', exact: true }).waitFor();
    await snapshot(page, 'request-review', width);
    const requested = await actionResponse(page, `/bills/${draft.id}/request-approval`, () => page.getByRole('button', { name: 'Request business approval', exact: true }).click());
    assert.equal(requested.value.result.status, 'pending');
    await page.getByText('Business approval requested.', { exact: true }).waitFor();
    await snapshot(page, 'request-pending', width);
    const requestRetry = await actionResponse(page, `/bills/${draft.id}/request-approval`, () => page.getByRole('button', { name: 'Retry same action', exact: true }).click());
    assertRetry(requested, requestRetry);
    const pending = await json(context, `/bills/${draft.id}`);
    assert.equal(pending.businessApproval.id, null); assert.equal(pending.businessApproval.status, 'pending');
    assert.equal(pending.posting, null); assert.equal(pending.currentDueCents, 0);
    const approvalId = pending.businessApproval.approvalId;
    await changePerson(page, 'pm');
    assert.equal(await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).count(), 0);
    await page.goto(base + `/approvals/${encodeURIComponent(approvalId)}`);
    await page.getByRole('button', { name: 'Review approval', exact: true }).waitFor();
    await snapshot(page, 'pm-business-packet', width);
    await page.getByRole('button', { name: 'Review approval', exact: true }).click();
    await page.getByRole('button', { name: 'Approve bill', exact: true }).waitFor();
    const granted = await actionResponse(page, `/approvals/${approvalId}/approve`, () => page.getByRole('button', { name: 'Approve bill', exact: true }).click());
    assert.equal(granted.value.result.status, 'approved'); assert.equal(granted.value.result.journalDelta, 0); assert.equal(granted.value.result.apDeltaCents, 0);
    await page.getByText('Bill approved for business purposes.', { exact: true }).waitFor();
    await snapshot(page, 'pm-approved-without-posting', width);
    const grantRetry = await actionResponse(page, `/approvals/${approvalId}/approve`, () => page.getByRole('button', { name: 'Retry same action', exact: true }).click());
    assertRetry(granted, grantRetry);
    const businessApproved = await json(context, `/bills/${draft.id}`);
    assert.equal(businessApproved.status, 'approved'); assert.equal(businessApproved.posting, null); assert.equal(businessApproved.currentDueCents, 0);
    assert.notEqual(businessApproved.businessApproval.approvedBy.id, pending.businessApproval.requestedBy.id);
    await changePerson(page, 'accountant');
    await page.goto(base + '/posting-queue'); await snapshot(page, 'posting-queue', width);
    await page.goto(base + `/bills/${encodeURIComponent(draft.id)}`);
    await page.getByRole('button', { name: 'Review posting', exact: true }).waitFor();
    const choices = businessApproved.postingPeriods.filter(period => period.id !== businessApproved.certificationPeriod.id);
    assert.ok(choices.length, 'The fixture needs a genuine later open posting period.');
    await page.getByRole('combobox', { name: 'Posting period', exact: true }).selectOption(choices[0].id);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click();
    await page.getByText('This step is blocked. Read the checks and refresh after the cause is resolved.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).count(), 0);
    await snapshot(page, 'posting-reason-required', width);
    await page.getByRole('textbox', { name: 'Posting reason', exact: true }).fill('Reviewed later-period practice posting');
    assert.equal(await page.getByText('Current facts reviewed. Read the checks and consequence before continuing.', { exact: true }).count(), 0);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click();
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).waitFor();
    await page.getByRole('table', { name: 'Reviewed entry 1', exact: true }).waitFor();
    await snapshot(page, 'posting-entry-review', width);
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    assert.equal(await page.getByRole('button', { name: 'Don’t post', exact: true }).evaluate(element => element === document.activeElement), true, 'Posting confirmation starts on the safe option.');
    await page.getByRole('button', { name: 'Don’t post', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
    const posted = await actionResponse(page, `/bills/${draft.id}/post`, () => page.getByRole('dialog').getByRole('button', { name: `Post to ${choices[0].name}`, exact: true }).click());
    assert.equal(posted.value.result.status, 'posted'); assert.equal(posted.value.result.postingPeriodId, choices[0].id); assert.equal(posted.value.result.journalIds.length, 1);
    await page.getByText('Bill posted to the practice working ledger.', { exact: true }).waitFor();
    await snapshot(page, 'posted-working-ledger', width);
    const postRetry = await actionResponse(page, `/bills/${draft.id}/post`, () => page.getByRole('button', { name: 'Retry same action', exact: true }).click());
    assertRetry(posted, postRetry);
    await page.getByText('Original outcome retrieved. Bill posted to the practice working ledger. No additional effect was applied.', { exact: true }).waitFor();
    await snapshot(page, 'posted-exact-retry', width);
    await page.getByRole('combobox', { name: 'Choose a project', exact: true }).selectOption(draft.projectId);
    await page.getByRole('tab', { name: 'Bills', exact: true }).click();
    await page.getByRole('link', { name: /Bill 1/ }).click();
    await page.getByRole('button', { name: 'Retry same action', exact: true }).waitFor();
    const navigationRetry = await actionResponse(page, `/bills/${draft.id}/post`, () => page.getByRole('button', { name: 'Retry same action', exact: true }).click());
    assertRetry(posted, navigationRetry);
    const postedBill = await json(context, `/bills/${draft.id}`);
    assert.equal(postedBill.currentDueCents, draft.amountDueCents); assert.equal(postedBill.posting.journalIds.length, 1);
    assert.equal(postedBill.posting.postedBy.id, pending.businessApproval.requestedBy.id);
    assert.equal(postedBill.posting.period.id, choices[0].id);
    assert.equal(postedBill.certificationPeriod.id, draft.certificationPeriod.id);
    if (width === 1440) await contractChecks(context, approvedExample, draft.id);
    // A real competing accountant post makes the browser's reviewed facts stale.
    await page.goto(base + `/bills/${encodeURIComponent(approvedExample.id)}`);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click();
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).waitFor();
    // The backend, rather than a simulated error, rejects a changed reviewed input.
    expectHTTP('POST', prefix + `/bills/${approvedExample.id}/post`, 412);
    const actionURL = base + prefix + `/bills/${approvedExample.id}/post`;
    const changeReviewedReason = route => {
      const body = route.request().postDataJSON();
      return route.continue({ postData: JSON.stringify({ ...body, reason: 'Changed after the browser reviewed the entry' }) });
    };
    await page.route(actionURL, changeReviewedReason);
    const changedResponse = page.waitForResponse(response => response.url() === actionURL);
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: `Post to ${approvedExample.certificationPeriod.name}`, exact: true }).click();
    const changed = await changedResponse; assert.equal(changed.status(), 412); const changedBody = await changed.json();
    assert.equal(changedBody.error.code, 'preflight_changed');
    await page.getByRole('alert').filter({ hasText: changedBody.error.message }).waitFor();
    await snapshot(page, 'changed-fingerprint-refused', width);
    report.expectedHttpRefusals.push({ width, status: 412, code: changedBody.error.code, actualBackendFingerprintCheck: true });
    await page.unroute(actionURL, changeReviewedReason);
    assert.equal((await json(context, `/bills/${approvedExample.id}`)).posting, null);
    await page.getByRole('button', { name: 'Review posting', exact: true }).click();
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).waitFor();
    const competingReviewResponse = await post(context, `/bills/${approvedExample.id}/post:preflight`, { periodId: approvedExample.certificationPeriod.id, reason: '' });
    assert.equal(competingReviewResponse.status(), 200); const competingReview = await competingReviewResponse.json();
    const competingPost = await post(context, `/bills/${approvedExample.id}/post`, { periodId: approvedExample.certificationPeriod.id, reason: '', fingerprint: competingReview.fingerprint }, {
      'If-Match': `"${competingReview.resourceVersion}"`, 'Repeatability-Request-ID': crypto.randomUUID(),
    });
    assert.equal(competingPost.status(), 200);
    expectHTTP('POST', prefix + `/bills/${approvedExample.id}/post`, 423);
    const staleResponse = page.waitForResponse(response => new URL(response.url()).pathname === prefix + `/bills/${approvedExample.id}/post`);
    await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: `Post to ${approvedExample.certificationPeriod.name}`, exact: true }).click();
    const stale = await staleResponse; assert.equal(stale.status(), 423); const staleBody = await stale.json();
    assert.equal(staleBody.error.code, 'bill_not_ready');
    await page.getByRole('alert').filter({ hasText: staleBody.error.message }).waitFor();
    await snapshot(page, 'competing-post-refused', width);
    report.expectedHttpRefusals.push({ width, status: 423, code: staleBody.error.code, genuineCompetingPost: true });
    if (width === 390) {
      await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
      await page.getByRole('dialog').getByRole('link', { name: 'Home', exact: true }).click();
      await page.getByRole('heading', { name: 'Books', level: 1, exact: true }).waitFor();
    }
    for (const collection of ['projects', 'commitments', 'bills', 'approvals', 'posting-queue']) expectHTTP('GET', prefix + '/' + collection, 401);
    await context.clearCookies();
    await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click();
    await page.getByRole('heading', { name: 'Start a practice session', level: 1, exact: true }).waitFor();
    await page.getByRole('button', { name: /Start as.*accountant/i }).waitFor();
    assert.equal(await page.getByRole('table').count(), 0, 'Financial records must disappear when the session is lost.');
    assert.equal(await page.getByRole('button', { name: 'Retry same action', exact: true }).count(), 0);
    await snapshot(page, 'session-lost', width);
    report.expectedHttpRefusals.push({ width, status: 401, code: 'session_required', cookieCleared: true });
    report.journeys.push({ width, request: 'pending', grant: 'approved', approvalJournals: 0, approvalPayableCents: 0,
      post: 'posted', journalCount: 1, payableCents: postedBill.currentDueCents, independentPeople: true,
      requestingAccountantAlsoPosted: true, exactRetries: 4, actualLaterPeriod: true, retrySurvivesNavigation: true });
    report.widths.push(width);
    await context.close();
    for (const message of httpConsoleMessages) if (!verifiedHTTPFailures.has(`${message.status}:${message.url}`)) {
      report.errors.push({ width, message: message.message, pathname: message.url ? new URL(message.url).pathname : null });
    }
    assert.equal(diagnostics(), '', 'The AP server reported an unexpected exception.');
    await stopServer();
  }
  await writeFile(path.join(artifacts, 'ap-smoke.json'), JSON.stringify(report, null, 2));
  assert.deepEqual(report.violations, [], 'The AP views have automated accessibility findings.');
  assert.deepEqual(report.errors, [], 'The AP browser reported unexpected application or CSP errors.');
  console.log(JSON.stringify({ source: report.source, widths: report.widths, views: report.views.length, journeys: report.journeys.length,
    exactRetries: report.journeys.reduce((sum, row) => sum + row.exactRetries, 0), contractChecks: report.contractChecks.length, accessibilityViolations: report.violations.length, browserErrors: report.errors.length }));
} catch (error) {
  await writeFile(path.join(artifacts, 'ap-smoke-failed.json'), JSON.stringify(report, null, 2));
  throw error;
} finally {
  await browser?.close(); await stopServer();
}
