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

const web = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const repository = path.resolve(web, '../../..');
const port = Number(process.env.CIPHER_COMMERCIAL_PORT ?? 18771);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/commercial-practice/v1';
const artifacts = process.env.CIPHER_COMMERCIAL_ARTIFACTS ?? '/tmp/cipher-completion/commercial-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', widths: [], views: [], journeys: [], exactRetries: [], recoveryChecks: [], contractChecks: [], counters: [], errors: [], violations: [],
  axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard traversal remains checked'] };
// The browser receives only the fixed API. Bounded stdin controls operate on
// this disposable test process, using actual audited engine transitions.
const fixtureControl = `
import json, sys
from threading import Thread
from apps.cipher.commercial_practice_server import make_commercial_practice_server
from apps.cipher.commercial_practice_fixture import ESTIMATOR_LOGIN, PM_LOGIN, BOOTSTRAP_LOGIN
server = make_commercial_practice_server(port=int(sys.argv[1]))
def controls():
    for command in sys.stdin:
        with server.cipher_lock, server.cipher.db._lock:
            c = server.cipher
            if command == "counts\\n":
                tables = ("estimates", "estimate_lines", "commercial_estimate_sources", "commercial_line_sources", "approvals", "commercial_handoffs", "commercial_commitment_sources", "commitments", "sov_lines", "commercial_action_receipts", "audit_log", "journals", "prime_bills", "bills", "outbox", "payment_intents")
                result = {table: c.db.scalar("SELECT COUNT(*) FROM " + table) for table in tables}
                result.update(nativeSubmissions=len(c.provider.submissions), nativeTransfers=len(c.provider.transfers))
            elif command == "advance_drawing\\n":
                revision = c.evidence.add_revision(document_id=c.commercial_practice_records["drawing_id"], content="Synthetic next manual source revision from owned test transition", note="Genuine later drawing revision; no calibrated geometry", actor=ESTIMATOR_LOGIN)
                result = {"drawingAdvanced": True}
            elif command == "register_additional_drawing\\n":
                document = c.evidence.register_document(project_id=c.commercial_practice_records["project_id"], kind="drawing", title="Synthetic additional owned drawing A-102", actor=ESTIMATOR_LOGIN)
                revision = c.evidence.add_revision(document_id=document["id"], content="Synthetic alternate manual drawing source; no calibrated geometry", actor=ESTIMATOR_LOGIN)
                result = {"documentRevisionId": revision["id"]}
            elif command == "execute_latest_commitment\\n":
                row = c.db.one("SELECT commitment_id FROM commercial_commitment_sources ORDER BY rowid DESC LIMIT 1")
                requested = c.request_approval("commitment.execute", row["commitment_id"], actor_role="pm", requested_by=ESTIMATOR_LOGIN)
                c.approve(requested["id"], approver=PM_LOGIN, approver_role="pm")
                c.execute(requested["id"], actor=PM_LOGIN)
                result = {"executed": True}
            elif command == "expire_sessions\\n":
                from apps.cipher.commercial_sessions import IDLE_SECONDS
                original_clock = server.sessions.clock
                server.sessions.clock = lambda: original_clock() + IDLE_SECONDS + 1
                result = {"sessionsExpired": True}
            elif command == "end_preparer_membership\\n":
                c.plugin("people").end_membership(ESTIMATOR_LOGIN, c.commercial_practice_records["project_id"], reason="Synthetic commercial browser duty-loss control", actor=BOOTSTRAP_LOGIN)
                result = {"membershipEnded": True}
            else:
                raise ValueError("Unsupported bounded commercial test control")
            print(json.dumps(result), flush=True)
Thread(target=controls, daemon=True).start()
try: server.serve_forever()
finally: server.server_close()
`;
let server, serverLines, browser;
const expectedTransport = new WeakMap();
const pendingReads = new WeakMap();
async function startServer() {
  server = spawn(process.env.CIPHER_PYTHON ?? 'python', ['-u', '-c', fixtureControl, String(port)], { cwd: repository, stdio: ['pipe', 'pipe', 'pipe'] });
  serverLines = createInterface({ input: server.stdout }); let diagnostics = '';
  server.stderr.on('data', chunk => { diagnostics += chunk.toString(); });
  for (let attempt = 0; attempt < 150; attempt++) {
    if (server.exitCode !== null) throw new Error(`The commercial server exited (${server.exitCode}): ${diagnostics}`);
    try { if ((await fetch(base)).ok) return; } catch { /* Wait for the local owned server. */ }
    await delay(100);
  }
  throw new Error(`The commercial server did not become ready: ${diagnostics}`);
}
async function control(command) {
  const result = once(serverLines, 'line', { signal: AbortSignal.timeout(10000) }); server.stdin.write(command + '\n'); return JSON.parse((await result)[0]);
}
async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const result = once(server, 'exit'); server.kill('SIGTERM'); await result; serverLines.close(); server = undefined;
}
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json(); assert.equal(value.contractVersion, 'cipher.commercial-practice.v1'); assert.equal(value.mode, 'practice'); assert.equal(value.synthetic, true); return value;
}
async function settled(page) {
  const idle = () => {
    const main = document.querySelector('main');
    return !!main && main.getAttribute('aria-busy') !== 'true' && !main.querySelector('[role="progressbar"], [data-action][aria-busy="true"]');
  };
  await page.waitForFunction(idle);
  for (let attempt = 0; attempt < 400 && pendingReads.get(page)?.size; attempt++) await delay(25);
  assert.equal(pendingReads.get(page)?.size ?? 0, 0, `The commercial view still has a pending scoped read: ${[...(pendingReads.get(page) ?? [])].map(request => request.method() + ' ' + new URL(request.url()).pathname).join(', ')}`);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.waitForFunction(idle);
  assert.equal(await page.locator('main [role="progressbar"], main [data-action][aria-busy="true"]').count(), 0, 'A capture must contain settled records, alerts or empty states.');
}
async function snapshot(page, name, width) {
  await settled(page); await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.getByRole('heading', { level: 1 }).waitFor(); assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1);
  await page.evaluate(() => window.scrollTo(0, 0)); await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  const size = await page.evaluate(() => [innerWidth, document.documentElement.scrollWidth]); if (size[1] > size[0]) { await page.screenshot({ path: path.join(artifacts, `overflow-${name}-${width}.png`), fullPage: true }); console.error(JSON.stringify(await page.locator('main *').evaluateAll(nodes => nodes.filter(node => node.getBoundingClientRect().right > innerWidth).map(node => ({ tag: node.tagName, className: node.className, text: node.textContent.slice(0, 80), width: node.getBoundingClientRect().width })).slice(0, 30)))); } assert.ok(size[1] <= size[0], `${name} overflows ${width}px.`);
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  report.violations.push(...axe.violations.map(value => ({ name, width, id: value.id, nodes: value.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content'); assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width });
}
async function choose(page, persona) {
  if (await page.getByRole('button', { name: 'Change practice person', exact: true }).count()) await page.getByRole('button', { name: 'Change practice person', exact: true }).click();
  await page.getByRole('heading', { name: 'Start a commercial practice session', exact: true }).waitFor();
  const names = { preparer: 'Estimate preparer (synthetic)', reviewer: 'Independent estimate reviewer (synthetic)', pm: 'Subcontract project manager (synthetic)' };
  await page.getByRole('button', { name: `Start as ${names[persona]}`, exact: true }).click();
  await page.getByRole('table', { name: 'Commercial estimates', exact: true }).waitFor();
}
const steps = {
  'estimate.create': ['Review manual estimate', 'Create draft estimate', 'projects', 'create-estimate'],
  'estimate.revise': ['Review estimate revision', 'Create successor revision', 'estimates', 'revise'],
  'estimate.request': ['Review acceptance request', 'Request independent acceptance', 'estimates', 'request-acceptance'],
  'estimate.accept': ['Review independent acceptance', 'Authorize estimate acceptance', 'estimate-approvals', 'accept'],
  'estimate.apply': ['Review acceptance application', 'Apply authorized acceptance', 'estimate-approvals', 'apply'],
  'estimate.prepareHandoff': ['Review accepted-source handoff', 'Prepare source handoff', 'estimates', 'prepare-handoff'],
  'estimate.createCommitment': ['Review subcontract draft', 'Create source-bound subcontract draft', 'estimate-handoffs', 'create-commitment'],
};
async function actionResponse(page, route, click, status = 200) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === prefix + route && response.request().method() === 'POST');
  await click(); const response = await pending; assert.equal(response.status(), status, `${route}: ${await response.text()}`);
  return { value: await response.json(), key: response.request().headers()['repeatability-request-id'], version: response.request().headers()['if-match'], body: response.request().postData(), route };
}
function noFinance(before, after) { for (const key of ['journals', 'prime_bills', 'bills', 'outbox', 'payment_intents', 'nativeSubmissions', 'nativeTransfers']) assert.equal(after[key], before[key], key); }
async function act(page, action, resource, keyboard = false) {
  const [review, apply, collection, command] = steps[action]; const panel = page.locator(`[data-action="${action}"]`);
  const before = await control('counts');
  if (keyboard) { await panel.getByRole('button', { name: review, exact: true }).focus(); await page.keyboard.press('Enter'); }
  else await panel.getByRole('button', { name: review, exact: true }).click();
  await panel.getByRole('button', { name: apply, exact: true }).waitFor(); assert.deepEqual(await control('counts'), before, `${action} review must be pure.`);
  const first = await actionResponse(page, `/${collection}/${resource}/${command}`, () => panel.getByRole('button', { name: apply, exact: true }).click());
  assert.equal(first.value.result.action, action); assert.equal(first.value.effectApplied, true); assert.equal(first.value.replayed, false);
  assert.equal(first.value.result.journalCountDelta, 0); assert.equal(first.value.result.apBalanceDeltaCents, 0); assert.equal(first.value.result.providerCallsDelta, 0);
  assert.match(first.key, /^[0-9a-f-]{36}$/); assert.match(first.version, /^"[^\"]+"$/); noFinance(before, await control('counts')); return first;
}
async function editedInflightReview(page, resource, width) {
  const panel = page.locator('[data-action="estimate.create"]'); const routePath = `**${prefix}/projects/${resource}/create-estimate:preflight`;
  const before = await control('counts'); let release; let ready;
  const gate = new Promise(resolve => { release = resolve; }); const received = new Promise(resolve => { ready = resolve; });
  const intercept = async route => { const actual = await route.fetch(); ready(); await gate; await route.fulfill({ response: actual }); };
  await page.route(routePath, intercept); await panel.getByRole('button', { name: 'Review manual estimate', exact: true }).click(); await received;
  await page.getByRole('textbox', { name: 'Quantity for manual line 1', exact: true }).fill('14'); release();
  await page.getByText('The entered facts changed while this review was loading. Review the current source again.', { exact: true }).waitFor();
  assert.equal(await panel.getByRole('button', { name: 'Create draft estimate', exact: true }).count(), 0);
  assert.equal(await panel.getByRole('table', { name: 'Reviewed manual estimate lines', exact: true }).count(), 0);
  assert.deepEqual(await control('counts'), before); await snapshot(page, 'edited-inflight-review-discarded', width);
  await page.unroute(routePath, intercept); await page.getByRole('textbox', { name: 'Quantity for manual line 1', exact: true }).fill('13.125');
  report.recoveryChecks.push({ name: 'input edit discards a genuinely delayed old-body review', width });
}
async function lostCreationResponse(page, resource, width) {
  const panel = page.locator('[data-action="estimate.create"]'); const routePath = `/projects/${resource}/create-estimate`;
  const before = await control('counts');
  await panel.getByRole('button', { name: 'Review manual estimate', exact: true }).click();
  await panel.getByRole('button', { name: 'Create draft estimate', exact: true }).waitFor(); assert.deepEqual(await control('counts'), before);
  let original; let dropped = false; expectedTransport.get(page).add(prefix + routePath);
  const intercept = async route => {
    if (dropped) { await route.continue(); return; }
    dropped = true; const response = await route.fetch(); assert.equal(response.status(), 200);
    original = { value: await response.json(), key: route.request().headers()['repeatability-request-id'], version: route.request().headers()['if-match'], body: route.request().postData(), route: routePath };
    await route.abort('failed');
  };
  await page.route(`**${prefix}${routePath}`, intercept);
  await panel.getByRole('button', { name: 'Create draft estimate', exact: true }).click();
  await panel.getByRole('alert').waitFor(); assert.ok(original); assert.equal(original.value.effectApplied, true);
  assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
  assert.equal((await control('counts')).estimates - before.estimates, 1);
  const quantity = page.getByRole('textbox', { name: 'Quantity for manual line 1', exact: true });
  await quantity.fill('13.1250'); await quantity.fill('13.125'); assert.equal(await panel.getByRole('button', { name: 'Retry same action', exact: true }).count(), 1);
  await quantity.fill('14'); assert.equal(await panel.getByRole('button', { name: 'Review manual estimate', exact: true }).count(), 0);
  await snapshot(page, 'lost-creation-response', width); await retryUI(page, 'estimate.create', original, width);
  assert.equal(await panel.getByRole('button', { name: 'Review edited manual source', exact: true }).count(), 1);
  await page.unroute(`**${prefix}${routePath}`, intercept); expectedTransport.get(page).delete(prefix + routePath);
  report.recoveryChecks.push({ name: 'lost response after genuine commit recovered by same UUID', width }); return original;
}
async function retryUI(page, action, original, width) {
  const before = await control('counts'); const panel = page.locator(`[data-action="${action}"]`);
  const replay = await actionResponse(page, original.route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click());
  assert.equal(replay.key, original.key); assert.equal(replay.body, original.body); assert.equal(replay.version, original.version);
  assert.equal(replay.value.receiptId, original.value.receiptId); assert.equal(replay.value.replayed, true); assert.equal(replay.value.effectApplied, false); assert.deepEqual(replay.value.result, original.value.result);
  assert.deepEqual(await control('counts'), before); report.exactRetries.push({ action, width, receiptId: replay.value.receiptId });
}
async function retryHTTP(context, original, width) {
  const session = await json(context, '/session'); const before = await control('counts');
  const response = await context.request.post(base + prefix + original.route, { headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken,
    'Repeatability-Request-ID': original.key, 'If-Match': original.version }, data: original.body });
  assert.equal(response.status(), 200, await response.text()); const replay = await response.json(); assert.equal(replay.receiptId, original.value.receiptId); assert.deepEqual(replay.result, original.value.result); assert.equal(replay.replayed, true); assert.equal(replay.effectApplied, false);
  assert.deepEqual(await control('counts'), before); report.exactRetries.push({ action: original.value.result.action, width, receiptId: replay.receiptId, afterLaterTransitions: true });
}
async function fillLine(page, n, line) {
  for (const [label, key] of [['Description', 'description'], ['Quantity', 'quantity'], ['Unit price', 'price'], ['Source locator', 'sourceLocator'], ['Cost code', 'costCode']]) await page.getByRole('textbox', { name: `${label} for manual line ${n}`, exact: true }).fill(line[key]);
  await page.getByRole('combobox', { name: `Unit for manual line ${n}`, exact: true }).selectOption(line.unit);
}
async function fillCreate(page, projectId, lines, contingency = '0') {
  await page.goto(base + `/projects/${projectId}/estimate-preparation`); await page.getByRole('combobox', { name: 'Owned drawing revision', exact: true }).waitFor();
  const preparation = await json(page.context(), `/projects/${projectId}/estimate-preparation`);
  await page.getByRole('combobox', { name: 'Owned drawing revision', exact: true }).selectOption(preparation.drawingRevisions[0].documentRevisionId);
  await page.getByRole('textbox', { name: 'Manual measurement basis', exact: true }).fill('Manual synthetic plan trace at A-101; geometry and scale unverified');
  await page.getByRole('textbox', { name: 'Estimate inclusions', exact: true }).fill('Manual piping installation\nManual sleeves');
  await page.getByRole('textbox', { name: 'Estimate exclusions', exact: true }).fill('Excavation');
  await page.getByRole('textbox', { name: 'Price source reference', exact: true }).fill('Synthetic rates, complete manual reference v1');
  await page.getByRole('textbox', { name: 'Contingency percentage', exact: true }).fill(contingency);
  for (let i = 0; i < lines.length; i++) { if (i) await page.getByRole('button', { name: 'Add manual line', exact: true }).click(); await fillLine(page, i + 1, lines[i]); }
}
async function malformedReviews(context, projectId, line, width) {
  for (const [name, mutate] of [
    ['wrong prospective creation flag', value => { value.safeEffects.createsCommitment = true; }],
    ['wrong prospective estimate state', value => { value.safeEffects.estimateStatus = 'approved'; }],
    ['changed reviewed quantity', value => { value.preview.lines[0].quantity = '14'; }],
    ['changed reviewed locator', value => { value.preview.lines[0].sourceLocator = 'Unrelated locator'; }],
    ['nonzero provider effect', value => { value.safeEffects.providerCallBound = 1; }],
    ['missing reviewed preview', value => { delete value.preview; }],
  ]) {
    const page = await context.newPage(); await fillCreate(page, projectId, [line]);
    await page.route(`**${prefix}/projects/${projectId}/create-estimate:preflight`, async route => { const actual = await route.fetch(); const value = await actual.json(); assert.equal(value.allowed, true); mutate(value); await route.fulfill({ response: actual, json: value }); });
    await page.locator('[data-action="estimate.create"]').getByRole('button', { name: 'Review manual estimate', exact: true }).click();
    await page.getByRole('alert').waitFor(); assert.equal(await page.getByRole('button', { name: 'Create draft estimate', exact: true }).count(), 0);
    assert.equal(await page.getByRole('table', { name: 'Reviewed manual estimate lines', exact: true }).count(), 0); report.contractChecks.push({ name, width }); await page.close();
  }
}
async function malformedChecks(context, estimateId, commitmentId, width) {
  const cases = [
    ['numeric manual quantity', `/estimates/${estimateId}`, `/estimates/${estimateId}`, value => { value.lines[0].quantity = 1.25; }],
    ['unsafe integer rate', `/estimates/${estimateId}`, `/estimates/${estimateId}`, value => { value.lines[0].unitPriceCents = Number.MAX_SAFE_INTEGER + 1; }],
    ['verified geometry claim', `/estimates/${estimateId}`, `/estimates/${estimateId}`, value => { value.lines[0].verifiedGeometry = true; }],
    ['private proof disclosure', `/estimates/${estimateId}`, `/estimates/${estimateId}`, value => { value.proofBody = {}; }],
    ['false original commitment status', `/commercial-commitments/${commitmentId}`, `/commercial-commitments/${commitmentId}`, value => { value.creationStatus = 'executed'; }],
    ['foreign related route', `/commercial-commitments/${commitmentId}`, `/commercial-commitments/${commitmentId}`, value => { value.relatedRecords[0].apiRoute = '/api/ap-practice/v1/estimates/foreign'; }],
  ];
  const before = await control('counts');
  for (const [name, route, entry, mutate] of cases) for (const fresh of [true, false]) {
    const page = await context.newPage(); page.on('pageerror', error => report.errors.push({ name, width, message: error.message }));
    if (!fresh) { await page.goto(base + entry); await page.getByRole('table').first().waitFor(); }
    await page.route(`**${prefix}${route}`, async request => { const actual = await request.fetch(); const value = await actual.json(); mutate(value); await request.fulfill({ response: actual, json: value }); });
    if (fresh) await page.goto(base + entry); else await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click();
    await page.getByRole('alert').waitFor(); assert.equal(await page.getByRole('table').count(), 0); assert.equal(await page.locator('[data-action]').count(), 0);
    report.contractChecks.push({ name, width, refreshAfterValidRecord: !fresh }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function nonRetiringFailures(context, projectId, line, width) {
  const before = await control('counts');
  for (const [name, status, code, extra] of [
    ['server500 keeps original reviewed request', 500, 'action_unavailable', {}],
    ['unknown412 integrity hold keeps original request', 412, 'commercial_source_unavailable', {}],
    ['incomplete negative receipt metadata is rejected', 412, 'record_changed', { receiptId: 'refusal_metadata' }],
    ['positive effect in negative receipt is rejected', 412, 'record_changed', { receiptId: 'refusal_metadata', replayed: false, effectApplied: true }],
  ]) {
    const page = await context.newPage(); page.on('pageerror', error => report.errors.push({ name, width, message: error.message }));
    await fillCreate(page, projectId, [line]); const panel = page.locator('[data-action="estimate.create"]');
    await panel.getByRole('button', { name: 'Review manual estimate', exact: true }).click(); await panel.getByRole('button', { name: 'Create draft estimate', exact: true }).waitFor();
    await page.route(`**${prefix}/projects/${projectId}/create-estimate`, route => route.fulfill({ status, contentType: 'application/json', json: { contractVersion: 'cipher.commercial-practice.v1', mode: 'practice', synthetic: true, currency: 'USD', error: { code, message: 'Synthetic altered response only; original request remains unresolved.', target: 'record', fix: null, details: null }, ...extra } }));
    await panel.getByRole('button', { name: 'Create draft estimate', exact: true }).click(); await panel.getByRole('alert').waitFor();
    assert.equal(await panel.getByRole('button', { name: 'Retry same action', exact: true }).count(), 1); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
    assert.deepEqual(await control('counts'), before); report.contractChecks.push({ name, width, responseOnly: true }); await page.close();
  }
}
async function definitiveRefusalRecovery(page, projectId, line, width, expectedFailures) {
  await fillCreate(page, projectId, [line]); const panel = page.locator('[data-action="estimate.create"]'); const route = `/projects/${projectId}/create-estimate`;
  const beforeReview = await control('counts'); await panel.getByRole('button', { name: 'Review manual estimate', exact: true }).click(); await panel.getByRole('button', { name: 'Create draft estimate', exact: true }).waitFor(); assert.deepEqual(await control('counts'), beforeReview);
  const additional = await control('register_additional_drawing'); const afterSource = await control('counts'); expectedFailures.add(prefix + route);
  const refused = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Create draft estimate', exact: true }).click(), 412); assert.equal(refused.value.error.code, 'record_changed');
  await panel.getByRole('alert').waitFor(); assert.deepEqual(await control('counts'), afterSource);
  const repeated = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click(), 412); assert.equal(repeated.key, refused.key); assert.equal(repeated.body, refused.body); assert.equal(repeated.version, refused.version); assert.deepEqual(await control('counts'), afterSource);
  await settled(page); await page.getByRole('combobox', { name: 'Owned drawing revision', exact: true }).selectOption(additional.documentRevisionId);
  const restart = panel.getByRole('button', { name: 'Start a new current review', exact: true }); assert.equal(await restart.count(), 1, 'A definitive412 must permit explicit new current review after retaining the refused request.');
  await restart.click(); const beforeFresh = await control('counts'); const reviewed = await actionResponse(page, route + ':preflight', () => panel.getByRole('button', { name: 'Review manual estimate', exact: true }).click()); assert.equal(reviewed.value.allowed, true); assert.deepEqual(await control('counts'), beforeFresh);
  const next = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Create draft estimate', exact: true }).click()); assert.notEqual(next.key, refused.key); assert.equal(JSON.parse(next.body).documentRevisionId, additional.documentRevisionId); assert.equal(next.value.result.totalCents, 32826);
  const afterFresh = await control('counts'); noFinance(beforeFresh, afterFresh); assert.equal(afterFresh.estimates-beforeFresh.estimates, 1); assert.equal(afterFresh.commercial_action_receipts-beforeFresh.commercial_action_receipts, 1); assert.equal(afterFresh.commitments, beforeFresh.commitments); await retryUI(page, 'estimate.create', next, width);
  const details = panel.locator('details').filter({ hasText: 'Original refusal' }); if (await details.getAttribute('open') === null) await details.locator('summary').click(); assert.ok((await details.innerText()).includes('record_changed'));
  const beforeHistory = await control('counts'); const historical = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry refused request', exact: true }).click(), 412); assert.equal(historical.key, refused.key); assert.equal(historical.body, refused.body); assert.equal(historical.version, refused.version); assert.equal(historical.value.error.code, refused.value.error.code); assert.equal(historical.value.receiptId, refused.value.receiptId); assert.deepEqual(await control('counts'), beforeHistory);
  report.exactRetries.push({ action: 'estimate.create', width, refusedHistoricalRequest: true, key: historical.key }); report.recoveryChecks.push({ name: 'definitive412 explicitly retires into preserved refusal history and a new current-source draft UUID', width }); await snapshot(page, 'definitive-refusal-new-current-review', width);
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of (process.env.CIPHER_COMMERCIAL_WIDTHS ? process.env.CIPHER_COMMERCIAL_WIDTHS.split(',').map(Number) : [1440, 1024, 390])) {
    await startServer(); const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' });
    const page = await context.newPage(); const expectedFailures = new Set();
    page.on('pageerror', error => report.errors.push({ width, message: error.message }));
    expectedTransport.set(page, new Set()); pendingReads.set(page, new Set());
    let documentNavigation = false;
    page.on('framenavigated', frame => { if (frame === page.mainFrame()) { if (documentNavigation) pendingReads.get(page).clear(); documentNavigation = false; } });
    page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) { documentNavigation = true; pendingReads.get(page).clear(); } const url = new URL(request.url()); if (url.origin === base && url.pathname.startsWith(prefix + '/') && (request.method() === 'GET' || url.pathname.endsWith(':preflight'))) pendingReads.get(page).add(request); });
    page.on('requestfinished', request => pendingReads.get(page).delete(request));
    page.on('requestfailed', request => pendingReads.get(page).delete(request));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      const pathname = message.location().url ? new URL(message.location().url).pathname : '';
      if (message.text().startsWith('Failed to load resource: net::ERR_FAILED') && expectedTransport.get(page).has(pathname)) return;
      if (/^Failed to load resource: the server responded with a status of/.test(message.text()) && expectedFailures.has(pathname)) return;
      report.errors.push({ width, message: message.text(), pathname });
    });
    page.on('requestfailed', request => { const pathname = new URL(request.url()).pathname; if (!expectedTransport.get(page).has(pathname) && request.failure()?.errorText !== 'net::ERR_ABORTED') report.errors.push({ width, pathname, message: request.failure()?.errorText }); });
    page.on('response', response => { if (response.status() >= 400 && !expectedFailures.has(new URL(response.url()).pathname)) report.errors.push({ width, status: response.status(), pathname: new URL(response.url()).pathname }); });
    await page.route('**/*', request => { const url = new URL(request.request().url()); assert.equal(url.origin, base); if (request.request().method() === 'POST') assert.ok(url.pathname.startsWith(prefix + '/')); return request.continue(); });
    await page.goto(base); await snapshot(page, 'session-picker', width); await choose(page, 'preparer'); await snapshot(page, 'estimate-list', width);
    const baseline = await control('counts'); const projects = await json(context, '/projects'); assert.equal(projects.count, 1); const projectId = projects.items[0].id;
    await page.goto(base + '/projects'); await snapshot(page, 'scoped-projects', width);
    await page.getByRole('button', { name: 'Help', exact: true }).click(); await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' }); assert.equal(await page.getByRole('button', { name: 'Help', exact: true }).evaluate(element => element === document.activeElement), true);
    if (width === 390) { await page.getByRole('button', { name: 'Open navigation', exact: true }).click(); await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' }); assert.equal(await page.getByRole('button', { name: 'Open navigation', exact: true }).evaluate(element => element === document.activeElement), true); }
    const line1 = { description: 'Manual piping installation', quantity: '13.125', unit: 'LF', price: '25.01', sourceLocator: 'A-101, pipe run 4', costCode: '33-110' };
    const line2 = { description: 'Manual pipe sleeves', quantity: '4', unit: 'EA', price: '50.00', sourceLocator: 'A-101, sleeve schedule', costCode: '33-120' };
    const zero = { description: 'Recorded zero quantity allowance', quantity: '0', unit: 'EA', price: '12.34', sourceLocator: 'A-101, zero allowance note', costCode: '33-130' };
    if (width === 1440) await nonRetiringFailures(context, projectId, line1, width);
    await fillCreate(page, projectId, [line1, line2, zero]); await snapshot(page, 'manual-entry', width);
    await editedInflightReview(page, projectId, width);
    const created = await lostCreationResponse(page, projectId, width); await retryUI(page, 'estimate.create', created, width);
    await page.getByRole('link', { name: 'Open recorded estimate', exact: true }).click(); await page.goBack(); await retryUI(page, 'estimate.create', created, width); await page.getByRole('link', { name: 'Open recorded estimate', exact: true }).click(); const firstId = created.value.result.estimateId;
    let estimate = await json(context, `/estimates/${firstId}`); assert.equal(estimate.lines[0].quantity, '13.125'); assert.equal(estimate.lines[0].unitPriceCents, 2501); assert.equal(estimate.totalCents, 52826); assert.equal(estimate.lines[2].amountCents, 0);
    await snapshot(page, 'original-manual-source', width); await page.getByRole('link', { name: 'Create a successor revision', exact: true }).click();
    await page.getByRole('textbox', { name: 'Quantity for manual line 1', exact: true }).fill('14.375'); await page.getByRole('textbox', { name: 'Source locator for manual line 1', exact: true }).fill('A-101, corrected manual pipe run 4');
    await page.getByRole('button', { name: 'Remove manual line 2', exact: true }).click(); await page.getByRole('button', { name: 'Add manual line', exact: true }).click();
    await fillLine(page, 3, { description: 'Manual coupling assembly', quantity: '2.5', unit: 'EA', price: '12.34', sourceLocator: 'A-101, coupling detail', costCode: '33-140' });
    await page.getByRole('textbox', { name: 'Estimate exclusions', exact: true }).fill(''); await page.getByRole('checkbox', { name: 'Remove exclusion: Excavation', exact: true }).check();
    await page.getByRole('textbox', { name: 'Price source reference', exact: true }).fill('Synthetic complete rates v2');
    await snapshot(page, 'successor-entry', width); const revised = await act(page, 'estimate.revise', firstId); await retryUI(page, 'estimate.revise', revised, width);
    const estimateId = revised.value.result.estimateId; await page.getByRole('link', { name: 'Open recorded estimate', exact: true }).click();
    estimate = await json(context, `/estimates/${estimateId}`); const comparison = await json(context, `/estimates/${estimateId}/comparison`);
    assert.deepEqual(comparison.lines.map(line => line.kind).sort(), ['added', 'changed', 'removed', 'unchanged']); assert.equal(estimate.totalCents, 39037); assert.equal(estimate.lines.length, 3); await snapshot(page, 'revision-comparison', width);
    const requested = await act(page, 'estimate.request', estimateId); await retryUI(page, 'estimate.request', requested, width); const approvalId = requested.value.result.approvalId;
    await page.locator('[data-action="estimate.request"]').getByRole('link', { name: 'Open acceptance review', exact: true }).click(); await page.getByText(/cannot approve their own request|different.*estimator|different.*person/i).first().waitFor(); assert.equal(await page.locator('[data-action="estimate.accept"]').count(), 0); await snapshot(page, 'requester-separation', width);
    await choose(page, 'reviewer'); await page.goto(base + `/estimate-approvals/${approvalId}`); await snapshot(page, 'independent-review', width);
    const granted = await act(page, 'estimate.accept', approvalId); await retryUI(page, 'estimate.accept', granted, width); assert.equal((await json(context, `/estimates/${estimateId}`)).status, 'draft'); await snapshot(page, 'grant-remains-draft', width);
    await choose(page, 'preparer'); await page.goto(base + `/estimate-approvals/${approvalId}`); const applied = await act(page, 'estimate.apply', approvalId); await retryUI(page, 'estimate.apply', applied, width);
    assert.equal((await json(context, `/estimates/${estimateId}`)).status, 'approved'); await snapshot(page, 'accepted-baseline', width);
    await page.goto(base + `/estimates/${estimateId}/handoff-preparation`); await snapshot(page, 'full-source-handoff-review', width);
    const handed = await act(page, 'estimate.prepareHandoff', estimateId); await retryUI(page, 'estimate.prepareHandoff', handed, width); const handoffId = handed.value.result.handoffId;
    await page.getByRole('link', { name: 'Open source handoff', exact: true }).click(); await snapshot(page, 'estimator-handoff', width);
    await choose(page, 'pm'); await page.goto(base + `/estimate-handoffs/${handoffId}`); await snapshot(page, 'pm-draft-review', width);
    let originalCommitmentReceipt; const creationRoute = `**${prefix}/estimate-handoffs/${handoffId}/create-commitment`;
    if (width === 1440) await page.route(creationRoute, async route => {
      if (originalCommitmentReceipt) { await route.continue(); return; }
      const actual = await route.fetch(); const value = await actual.json(); originalCommitmentReceipt = structuredClone(value);
      value.result.status = 'executed'; delete value.result.commitmentId; await route.fulfill({ response: actual, json: value });
    });
    let committed = await act(page, 'estimate.createCommitment', handoffId);
    if (originalCommitmentReceipt) {
      await page.locator('[data-action="estimate.createCommitment"]').getByRole('alert').waitFor(); assert.equal(await page.getByRole('link', { name: 'Open subcontract draft', exact: true }).count(), 0);
      committed = { ...committed, value: originalCommitmentReceipt }; await page.unroute(creationRoute);
      report.contractChecks.push({ name: 'malformed mutation result withheld and original receipt recovered', width });
    }
    await retryUI(page, 'estimate.createCommitment', committed, width); const commitmentId = committed.value.result.commitmentId;
    await page.getByRole('link', { name: 'Open subcontract draft', exact: true }).click(); const commitment = await json(context, `/commercial-commitments/${commitmentId}`);
    assert.equal(commitment.status, 'draft'); assert.equal(commitment.creationStatus, 'draft'); assert.equal(commitment.executionAvailableHere, false); assert.equal(commitment.lines.length, 3); assert.equal(commitment.lines[1].quantity, '0');
    for (const line of commitment.lines) { const original = estimate.lines.find(item => item.id === line.estimateLineId); assert.ok(original); for (const key of ['stableLineId', 'description', 'quantity', 'unit', 'unitPriceCents', 'amountCents', 'sourceLocator', 'costCode']) assert.equal(line[key], original[key]); assert.ok(line.sovLineId); }
    await snapshot(page, 'source-bound-draft', width);
    if (width === 390) {
      const region = page.getByRole('region', { name: 'Subcontract source-to-SOV correspondence, scrollable table', exact: true });
      assert.equal(await region.evaluate(element => element.scrollWidth > element.clientWidth), true); const left = await region.locator('thead th').first().evaluate(element => element.getBoundingClientRect().left);
      await region.focus(); await page.keyboard.press('ArrowRight'); await page.waitForFunction(() => [...document.querySelectorAll('.cipher-table-region')].some(element => element.scrollLeft > 0));
      const after = await region.locator('thead th').first().evaluate(element => element.getBoundingClientRect().left); assert.ok(Math.abs(after - left) < 1);
      report.contractChecks.push({ name: 'phone source table scrolls by keyboard with first column frozen', width });
    }
    await control('execute_latest_commitment'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await page.getByText('Executed', { exact: true }).first().waitFor();
    assert.equal((await json(context, `/commercial-commitments/${commitmentId}`)).creationStatus, 'draft'); await snapshot(page, 'later-executed-original-draft', width);
    await retryHTTP(context, committed, width); await choose(page, 'reviewer'); await retryHTTP(context, granted, width); await choose(page, 'preparer'); for (const original of [created, revised, requested, applied, handed]) await retryHTTP(context, original, width);
    if (width === 1440) { await malformedChecks(context, estimateId, commitmentId, width); await malformedReviews(context, projectId, line1, width); }
    const final = await control('counts'); noFinance(baseline, final); assert.equal(final.commercial_action_receipts - baseline.commercial_action_receipts, 7); assert.equal(final.commercial_handoffs - baseline.commercial_handoffs, 1); assert.equal(final.commercial_commitment_sources - baseline.commercial_commitment_sources, 1); assert.equal(final.sov_lines - baseline.sov_lines, 3);
    report.widths.push(width); report.journeys.push({ width, sevenActions: true, exactSourceLines: 3, zeroAmountLinePreserved: true, laterVerifiedCommitmentState: 'executed', originalCreationOutcome: 'draft' }); report.counters.push({ width, baseline, final });
    // Exact contingent value remains readable, while current handoff is blocked.
    await fillCreate(page, projectId, [line1], '5'); const contingent = await act(page, 'estimate.create', projectId); const contingentId = contingent.value.result.estimateId;
    await page.getByRole('link', { name: 'Open recorded estimate', exact: true }).click(); const contingentRequest = await act(page, 'estimate.request', contingentId); const contingentApproval = contingentRequest.value.result.approvalId;
    await choose(page, 'reviewer'); await page.goto(base + `/estimate-approvals/${contingentApproval}`); await act(page, 'estimate.accept', contingentApproval);
    await choose(page, 'preparer'); await page.goto(base + `/estimate-approvals/${contingentApproval}`); await act(page, 'estimate.apply', contingentApproval);
    await page.goto(base + `/estimates/${contingentId}/handoff-preparation`); await page.getByRole('heading', { name: 'Fixed audited subcontract package', exact: true }).waitFor();
    const contingentSource = await json(context, `/estimates/${contingentId}`); assert.equal(contingentSource.contingencyCents, 1641);
    assert.equal(await page.getByRole('button', { name: 'Review accepted-source handoff', exact: true }).count(), 0); await page.getByText(/contingency.*allocation|allocation.*contingency/i).first().waitFor();
    await snapshot(page, 'visible-nonzero-contingency-hold', width); report.recoveryChecks.push({ name: 'nonzero contingency remains visible and blocks unqualified handoff', width });
    await definitiveRefusalRecovery(page, projectId, line1, width, expectedFailures);
    // A genuine drawing revision invalidates a previously pure reviewed creation.
    await fillCreate(page, projectId, [line1]); const stalePanel = page.locator('[data-action="estimate.create"]');
    await page.getByRole('combobox', { name: 'Owned drawing revision', exact: true }).selectOption(JSON.parse(created.body).documentRevisionId);
    await stalePanel.getByRole('button', { name: 'Review manual estimate', exact: true }).click(); await stalePanel.getByRole('button', { name: 'Create draft estimate', exact: true }).waitFor();
    await control('advance_drawing'); const afterDrawing = await control('counts'); const stalePath = `/projects/${projectId}/create-estimate`; expectedFailures.add(prefix + stalePath);
    const refused = await actionResponse(page, stalePath, () => stalePanel.getByRole('button', { name: 'Create draft estimate', exact: true }).click(), 423);
    await stalePanel.getByRole('alert').waitFor(); assert.deepEqual(await control('counts'), afterDrawing); assert.ok(refused.value.error.message);
    assert.equal(await stalePanel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
    const refusedRetry = await actionResponse(page, stalePath, () => stalePanel.getByRole('button', { name: 'Retry same action', exact: true }).click(), 423);
    assert.equal(refusedRetry.key, refused.key); assert.equal(refusedRetry.version, refused.version); assert.equal(refusedRetry.body, refused.body); assert.deepEqual(await control('counts'), afterDrawing);
    await snapshot(page, 'stale-reviewed-source-refused', width); report.recoveryChecks.push({ name: 'genuine later drawing refuses initial effect and exact retry', width });
    await page.goto(base + `/estimates/${estimateId}`); await page.getByText('A newer drawing revision exists', { exact: true }).waitFor(); await snapshot(page, 'historical-source-after-new-drawing', width);
    await retryHTTP(context, created, width); await retryHTTP(context, handed, width); report.recoveryChecks.push({ name: 'completed source receipts preserve original outcome after newer drawing', width });
    expectedFailures.add(prefix + '/projects'); expectedFailures.add(prefix + '/session'); expectedFailures.add(prefix + `/estimates/${estimateId}`); expectedFailures.add(prefix + `/estimates/${estimateId}/comparison`);
    await control('expire_sessions'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click();
    await page.getByRole('button', { name: 'Start as Estimate preparer (synthetic)', exact: true }).waitFor(); assert.equal(await page.getByRole('table').count(), 0); assert.equal(await page.locator('[data-action]').count(), 0);
    await snapshot(page, 'expired-session-facts-cleared', width); report.recoveryChecks.push({ name: 'expired actual session clears records and actions', width });
    await choose(page, 'preparer'); await page.goto(base + `/estimates/${estimateId}`); await page.getByRole('table', { name: 'Manual estimate lines', exact: true }).waitFor();
    await control('end_preparer_membership'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await page.getByRole('alert').first().waitFor();
    await page.waitForFunction(() => document.querySelectorAll('main table, main [data-action]').length === 0); await snapshot(page, 'current-duty-loss-facts-cleared', width);
    report.recoveryChecks.push({ name: 'actual project membership loss clears facts and action memory', width });
    await context.close(); await stopServer();
  }
  assert.deepEqual(report.errors, []); assert.deepEqual(report.violations, []);
} catch (error) { report.errors.push({ message: error.stack ?? String(error) }); throw error; }
finally { await browser?.close(); await stopServer(); await writeFile(path.join(artifacts, 'commercial-smoke.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ views: report.views.length, journeys: report.journeys.length, exactRetries: report.exactRetries.length, recoveryChecks: report.recoveryChecks.length, contractChecks: report.contractChecks.length, violations: report.violations.length, errors: report.errors.length }));
