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
const port = Number(process.env.CIPHER_RFI_PORT ?? 18776);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/rfi-practice/v1';
const artifacts = process.env.CIPHER_RFI_ARTIFACTS ?? '/tmp/cipher-completion/rfi-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', widths: [], views: [], journeys: [], laterLists: [], recoveryDrafts: [], exactRetries: [], recoveryChecks: [], contractChecks: [], keyboardChecks: [], headerContextChecks: [], counters: [], errors: [], violations: [], axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard controls remain checked'] };
// Genuine bounded controls live only on the disposable test process stdin.
const fixtureControl = `
import json, sys
from threading import Thread
from apps.cipher.rfi_practice_server import make_rfi_practice_server
from apps.cipher.rfi_practice_fixture import PM_LOGIN, STAFF_LOGIN, BOOTSTRAP_LOGIN
server = make_rfi_practice_server(port=int(sys.argv[1]))
def controls():
    for command in sys.stdin:
        with server.cipher_lock, server.cipher.db._lock:
            c=server.cipher
            if command == "counts\\n":
                tables=("field_rfis","field_rfi_links","drawing_references","rfi_sources","rfi_response_revisions","rfi_distribution_revisions","rfi_approval_sources","rfi_action_receipts","field_rfi_distributions","approvals","audit_log","idempotency","journals","changes","commitments","schedule_baselines","outbox","bills","prime_bills","prime_bill_sends","payment_intents","collections","documents","document_revisions")
                result={name:c.db.scalar("SELECT COUNT(*) FROM "+name) for name in tables}
                result.update(projectBudgets=c.db.query("SELECT id,budget FROM projects ORDER BY id"),nativeSubmissions=len(c.provider.submissions),nativeTransfers=len(c.provider.transfers))
            elif command == "advance_support\\n":
                revision=c.evidence.add_revision(document_id=c.rfi_practice_records["document_id"],content="Synthetic genuinely later supporting specification head for browser recovery.",note="Owned current-source browser control",actor=PM_LOGIN)
                result={"revisionId":revision["id"],"revisionNumber":revision["revision"]}
            elif command == "hold_distribution_rights\\n":
                rights=c.plugin("rights")
                license=rights.register_license("Synthetic browser control licensor","Synthetic project-use-only note","Practice1","Synthetic internal team",["project_use"],actor=BOOTSTRAP_LOGIN)
                rights.tag_document(c.rfi_practice_records["document_id"],license["id"],actor=BOOTSTRAP_LOGIN)
                result={"distributionHeld":True}
            elif command == "expire_sessions\\n":
                from apps.cipher.rfi_sessions import IDLE_SECONDS
                original_clock=server.sessions.clock
                server.sessions.clock=lambda:original_clock()+IDLE_SECONDS+1
                result={"sessionsExpired":True}
            elif command == "end_staff_membership\\n":
                c.plugin("people").end_membership(STAFF_LOGIN,c.rfi_practice_records["project_id"],reason="Synthetic RFI browser current membership control",actor=BOOTSTRAP_LOGIN)
                result={"membershipEnded":True}
            elif command == "hidden_id\\n":
                result={"projectId":c.rfi_practice_records["hidden_project_id"]}
            else: raise ValueError("Unsupported bounded RFI browser control")
            print(json.dumps(result),flush=True)
Thread(target=controls,daemon=True).start()
try: server.serve_forever()
finally: server.server_close()
`;
let server, serverLines, browser;
const expectedTransport = new WeakMap();
const pendingReads = new WeakMap();
const readEvents = new WeakMap();
const readIds = new WeakMap();
const expectedFailures = new WeakMap();
async function startServer() {
  server = spawn(process.env.CIPHER_PYTHON ?? 'python', ['-u', '-c', fixtureControl, String(port)], { cwd: repository, stdio: ['pipe', 'pipe', 'pipe'] });
  serverLines = createInterface({ input: server.stdout }); let diagnostics = '';
  server.stderr.on('data', chunk => { diagnostics += chunk.toString(); });
  for (let attempt = 0; attempt < 150; attempt++) {
    if (server.exitCode !== null) throw new Error(`The RFI server exited (${server.exitCode}): ${diagnostics}`);
    try { if ((await fetch(base)).ok) return; } catch { /* Wait for the owned local server. */ }
    await delay(100);
  }
  throw new Error(`The RFI server did not become ready: ${diagnostics}`);
}
async function control(command) { const result = once(serverLines, 'line', { signal: AbortSignal.timeout(10000) }); server.stdin.write(command + '\n'); return JSON.parse((await result)[0]); }
async function stopServer() { if (!server || server.exitCode !== null) return; const result = once(server, 'exit'); server.kill('SIGTERM'); await result; serverLines.close(); server = undefined; }
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json(); assert.equal(value.contractVersion, 'cipher.rfi-practice.v1'); assert.equal(value.mode, 'practice'); assert.equal(value.synthetic, true); return value;
}
async function settled(page) {
  const idle = () => {
    const main = document.querySelector('main');
    return !!main && main.getAttribute('aria-busy') !== 'true' && !main.querySelector('[role="progressbar"], [data-action][aria-busy="true"]');
  };
  await page.waitForFunction(idle);
  for (let attempt = 0; attempt < 400 && pendingReads.get(page)?.size; attempt++) await delay(25);
  if (pendingReads.get(page)?.size) await writeFile(path.join(artifacts, 'pending-scoped-reads.json'), JSON.stringify({ page: page.url(), pending: [...pendingReads.get(page)].map(request => ({ id: readIds.get(page).get(request), method: request.method(), url: request.url() })), events: readEvents.get(page) }, null, 2) + '\n');
  assert.equal(pendingReads.get(page)?.size ?? 0, 0, 'The RFI view still has a pending scoped read; see pending-scoped-reads.json.');
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.waitForFunction(idle);
  assert.equal(await page.locator('main [role="progressbar"], main [data-action][aria-busy="true"]').count(), 0, 'A capture must contain settled records, alerts or empty states.');
}
async function gotoRecord(page, route) { await page.goto(base + route); await settled(page); }
async function snapshot(page, name, width) {
  await settled(page); await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.getByRole('heading', { level: 1 }).waitFor(); assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1);
  await page.evaluate(() => window.scrollTo(0, 0)); await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  const size = await page.evaluate(() => [innerWidth, document.documentElement.scrollWidth]);
  if (size[1] > size[0]) await page.screenshot({ path: path.join(artifacts, `overflow-${name}-${width}.png`), fullPage: true });
  assert.ok(size[1] <= size[0], `${name} overflows ${width}px.`);
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').analyze();
  report.violations.push(...axe.violations.map(value => ({ name, width, id: value.id, nodes: value.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content'); assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width });
}
async function modalSnapshot(page, name, width) {
  const dialog = page.getByRole('dialog'); await dialog.waitFor(); assert.ok(await dialog.getAttribute('aria-labelledby'));
  const size = await page.evaluate(() => [innerWidth, document.documentElement.scrollWidth]); assert.ok(size[1] <= size[0], `${name} overflows ${width}px.`);
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').analyze();
  report.violations.push(...axe.violations.map(value => ({ name, width, id: value.id, nodes: value.nodes.map(node => node.target) })));
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width, modal: true });
}
function monitor(page) {
  expectedTransport.set(page, new Set()); expectedFailures.set(page, new Set()); pendingReads.set(page, new Set()); readEvents.set(page, []); readIds.set(page, new Map());
  let documentNavigation = false;
  const event = (kind, request) => { if (readIds.get(page).has(request)) readEvents.get(page).push({ event: kind, id: readIds.get(page).get(request), method: request.method(), url: request.url(), failure: request.failure()?.errorText ?? null }); };
  page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) { documentNavigation = true; readEvents.get(page).push({ event: 'new-main-document-request', url: request.url(), abandonedReadIds: [...pendingReads.get(page)].map(prior => readIds.get(page).get(prior)) }); pendingReads.get(page).clear(); } const url = new URL(request.url()); if (url.origin === base && url.pathname.startsWith(prefix + '/') && (request.method() === 'GET' || url.pathname.endsWith(':preflight'))) { readIds.get(page).set(request, readIds.get(page).size + 1); pendingReads.get(page).add(request); event('started', request); } });
  page.on('requestfinished', request => { event('finished', request); pendingReads.get(page).delete(request); });
  page.on('requestfailed', request => { event('failed', request); pendingReads.get(page).delete(request); });
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) { readEvents.get(page).push({ event: 'main-frame-url', url: frame.url(), documentCommit: documentNavigation, abandonedReadIds: documentNavigation ? [...pendingReads.get(page)].map(request => readIds.get(page).get(request)) : [] }); if (documentNavigation) pendingReads.get(page).clear(); documentNavigation = false; } });
  page.on('pageerror', error => report.errors.push({ message: error.message }));
  page.on('console', message => { if (message.type() !== 'error') return; const pathname = message.location().url ? new URL(message.location().url).pathname : '';
    if (message.text().startsWith('Failed to load resource: net::ERR_FAILED') && expectedTransport.get(page).has(pathname)) return;
    if (/^Failed to load resource: the server responded with a status of/.test(message.text()) && expectedFailures.get(page).has(pathname)) return;
    report.errors.push({ message: message.text(), pathname });
  });
  page.on('requestfailed', request => { const pathname = new URL(request.url()).pathname; if (!expectedTransport.get(page).has(pathname) && request.failure()?.errorText !== 'net::ERR_ABORTED') report.errors.push({ pathname, message: request.failure()?.errorText }); });
  page.on('response', response => { if (response.status() >= 400 && !expectedFailures.get(page).has(new URL(response.url()).pathname)) report.errors.push({ status: response.status(), pathname: new URL(response.url()).pathname }); });
  return page.route('**/*', request => { const url = new URL(request.request().url()); assert.equal(url.origin, base); if (request.request().method() === 'POST') assert.ok(url.pathname.startsWith(prefix + '/')); return request.continue(); });
}
async function choose(page, persona) {
  if (await page.getByRole('button', { name: 'Change practice person', exact: true }).count()) await page.getByRole('button', { name: 'Change practice person', exact: true }).click();
  await page.getByRole('heading', { name: 'Start an RFI practice session', exact: true }).waitFor();
  const options = await json(page.context(), '/personas'); const person = options.value.find(item => item.id === persona); assert.ok(person);
  await page.getByRole('button', { name: `Start as ${person.name}`, exact: true }).click(); await settled(page);
}
const steps = {
  'rfi.create': ['Review RFI question', 'Create RFI question', 'projects', 'rfis'],
  'rfi.draftResponse': ['Review proposed response', 'Record proposed response', 'rfis', 'draft-response'],
  'rfi.requestResponse': ['Review official response request', 'Request independent response review', 'rfis', 'request-response'],
  'rfi.approveResponse': ['Review independent response authorization', 'Authorize official response', 'rfi-response-approvals', 'approve'],
  'rfi.applyResponse': ['Review authorized official response', 'Apply official response', 'rfi-response-approvals', 'apply'],
  'rfi.setDistribution': ['Review synthetic recipient list', 'Record synthetic recipient list', 'rfis', 'distribution-list'],
  'rfi.requestDistribution': ['Review distribution request', 'Request independent distribution review', 'rfis', 'request-distribution'],
  'rfi.approveDistribution': ['Review independent distribution authorization', 'Authorize local distribution', 'rfi-distribution-approvals', 'approve'],
  'rfi.distribute': ['Review authorized local distribution', 'Record local practice distribution', 'rfi-distribution-approvals', 'distribute'],
};
const question = 'Which drainage alignment should the crew use at grid C4?\nRésumé … 🏗️\n<script>globalThis.rfiInjected=true</script>';
const proposed = 'Use the east alignment for internal coordination, pending normal project design controls.\nReported impacts are potential only.\n<script>globalThis.rfiInjected=true</script>';
const recipientChoices = ['engineer@synthetic-rfi.invalid', 'owner@synthetic-rfi.invalid', 'project-team@synthetic-rfi.invalid'];
const zeroEffects = ['journalDelta', 'changeDraftDelta', 'changeExecutionDelta', 'commitmentDelta', 'contractValueDeltaCents', 'budgetDeltaCents', 'scheduleBaselineDeltaDays'];
async function actionResponse(page, route, click, status = 200) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === prefix + route && response.request().method() === 'POST'); await click();
  const response = await pending; assert.equal(response.status(), status, `${route}: ${await response.text()}`);
  return { value: await response.json(), key: response.request().headers()['repeatability-request-id'], version: response.request().headers()['if-match'], body: response.request().postData(), route };
}
function fixedBoundary(before, after) {
  for (const key of ['journals', 'changes', 'commitments', 'schedule_baselines', 'outbox', 'bills', 'prime_bills', 'prime_bill_sends', 'payment_intents', 'collections', 'nativeSubmissions', 'nativeTransfers']) assert.equal(after[key], before[key], key);
  assert.deepEqual(after.projectBudgets, before.projectBudgets);
}
function expectedDelta(before, after, action) {
  fixedBoundary(before, after);
  const expected = {
    'rfi.create': { field_rfis: 1, field_rfi_links: 2, drawing_references: 1, rfi_sources: 1 },
    'rfi.draftResponse': { rfi_response_revisions: 1 }, 'rfi.setDistribution': { rfi_distribution_revisions: 1 },
    'rfi.requestResponse': { approvals: 1, rfi_approval_sources: 1 }, 'rfi.requestDistribution': { approvals: 1, rfi_approval_sources: 1 },
    'rfi.approveResponse': {}, 'rfi.approveDistribution': {}, 'rfi.applyResponse': {}, 'rfi.distribute': { field_rfi_distributions: 1 },
  }[action];
  for (const key of ['field_rfis', 'field_rfi_links', 'drawing_references', 'rfi_sources', 'rfi_response_revisions', 'rfi_distribution_revisions', 'rfi_approval_sources', 'approvals', 'field_rfi_distributions']) assert.equal(after[key] - before[key], expected[key] ?? 0, `${action}/${key}`);
  assert.equal(after.rfi_action_receipts - before.rfi_action_receipts, 1, `${action}/one original API receipt`);
}
async function exactText(scope, label, text) {
  const region = scope.locator(`pre[aria-label="${label}"]`); await region.waitFor(); assert.equal(await region.textContent(), text);
  assert.equal(await region.evaluate(() => globalThis.rfiInjected), undefined); assert.equal(await region.locator('script,img,iframe').count(), 0);
}
async function approvalHeaderContext(page, kind, rfi, width) {
  const title = `Independent ${kind} review`;
  const header = page.locator('main header').filter({ has: page.getByRole('heading', { level: 1, name: title, exact: true }) });
  assert.equal(await header.count(), 1);
  const expected = `${rfi.project.name} · ${rfi.number} · ${rfi.subject}`;
  const context = header.getByText(expected, { exact: true }); await context.waitFor();
  assert.equal(await context.textContent(), expected, `${kind} approval header must identify its actual project and RFI.`);
  report.headerContextChecks.push({ kind, width, projectId: rfi.project.id, rfiId: rfi.id });
}
async function keyboardTextRegion(page, label, width) {
  const region = page.getByRole('region', { name: label, exact: true });
  assert.equal(await region.getAttribute('tabindex'), '0');
  await region.focus(); assert.equal(await region.evaluate(element => document.activeElement === element), true);
  await page.keyboard.press('Tab'); assert.equal(await region.evaluate(element => document.activeElement === element), false, 'Tab must leave the authored text region.');
  report.keyboardChecks.push({ name: 'literal authored question region accepts focus and Tab leaves; review buttons activate with Enter', width });
}
function sourceFacts(source, input) {
  assert.equal(source.sourceContentAvailable, false); assert.deepEqual(source.drawings.map(item => item.revisionId), input.drawingRevisionIds); assert.deepEqual(source.documents.map(item => item.revisionId), input.documentRevisionIds);
  const drawing = source.drawings[0]; assert.equal(drawing.revisionLabel, 'A'); assert.equal(drawing.current.status, 'issued'); assert.equal(drawing.current.issuedRevisionId, drawing.revisionId);
  assert.ok(drawing.current.workingRevisionId); assert.notEqual(drawing.current.workingRevisionId, drawing.revisionId); assert.notEqual(drawing.current.evidenceHeadRevisionId, drawing.documentRevisionId); assert.equal(drawing.sourceContentAvailable, false);
  for (const row of [...source.drawings, ...source.documents]) { assert.equal(row.sourceContentAvailable, false); assert.equal(row.rights.length, 2); for (const right of row.rights) assert.equal(right.sourceContentAvailable, false); }
}
async function review(page, action, resource, keyboard = false) {
  const panel = page.locator(`[data-action="${action}"]`); const [label, apply, collection, command] = steps[action]; const before = await control('counts');
  const checked = await actionResponse(page, `/${collection}/${resource}/${command}:preflight`, async () => { if (keyboard) { await panel.getByRole('button', { name: label, exact: true }).focus(); await page.keyboard.press('Enter'); } else await panel.getByRole('button', { name: label, exact: true }).click(); });
  assert.equal(checked.value.allowed, true); await panel.getByRole('button', { name: apply, exact: true }).waitFor(); assert.deepEqual(await control('counts'), before, `${action} review is pure`);
  for (const key of zeroEffects) assert.equal(checked.value.safeEffects[key], 0); for (const key of ['externalDistribution', 'engineeringCertification', 'adoptsPotentialImpacts']) assert.equal(checked.value.safeEffects[key], false); assert.equal(checked.value.safeEffects.mailSinkOnly, true);
  await exactText(panel, 'Exact reviewed RFI question', checked.value.preview.question); if (checked.value.preview.responseText !== null) await exactText(panel, 'Exact reviewed response text', checked.value.preview.responseText);
  for (const recipient of checked.value.preview.recipients) assert.ok((await panel.innerText()).includes(recipient)); return checked;
}
async function act(page, action, resource, width, keyboard = false) {
  const before = await control('counts'); await review(page, action, resource, keyboard); const panel = page.locator(`[data-action="${action}"]`); const [, apply, collection, command] = steps[action];
  const first = await actionResponse(page, `/${collection}/${resource}/${command}`, () => panel.getByRole('button', { name: apply, exact: true }).click());
  assert.equal(first.value.result.action, action); assert.equal(first.value.effectApplied, true); assert.equal(first.value.replayed, false); assert.match(first.key, /^[0-9a-f-]{36}$/); assert.match(first.version, /^"[^\"]+"$/);
  for (const key of zeroEffects) assert.equal(first.value.result[key], 0); expectedDelta(before, await control('counts'), action); return first;
}
async function retryUI(page, action, original, width) {
  const before = await control('counts'); const panel = page.locator(`[data-action="${action}"]`); const replay = await actionResponse(page, original.route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click());
  for (const key of ['key', 'body', 'version']) assert.equal(replay[key], original[key]); assert.equal(replay.value.receiptId, original.value.receiptId); assert.deepEqual(replay.value.result, original.value.result); assert.equal(replay.value.replayed, true); assert.equal(replay.value.effectApplied, false);
  assert.deepEqual(await control('counts'), before); report.exactRetries.push({ action, width, receiptId: replay.value.receiptId });
}
async function retryHTTP(context, original, width) {
  const session = await json(context, '/session'); const before = await control('counts'); const response = await context.request.post(base + prefix + original.route, { headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken, 'Repeatability-Request-ID': original.key, 'If-Match': original.version }, data: original.body });
  assert.equal(response.status(), 200, await response.text()); const replay = await response.json(); assert.equal(replay.receiptId, original.value.receiptId); assert.deepEqual(replay.result, original.value.result); assert.equal(replay.replayed, true); assert.equal(replay.effectApplied, false); assert.deepEqual(await control('counts'), before); report.exactRetries.push({ action: original.value.result.action, width, receiptId: replay.receiptId, afterLaterState: true });
}
async function fillCreate(page, projectId, text = question, subject = 'Synthetic drain alignment at grid C4') {
  await gotoRecord(page, `/projects/${projectId}/rfi-preparation`); await page.getByRole('textbox', { name: 'RFI subject', exact: true }).fill(subject); await page.getByRole('textbox', { name: 'RFI question', exact: true }).fill(text);
  const preparation = await json(page.context(), `/projects/${projectId}/preparation`); const drawing = preparation.sources.drawings.find(item => item.citable); const document = preparation.sources.documents.find(item => item.citable); assert.ok(drawing && document);
  await page.getByRole('checkbox', { name: `${drawing.drawingNumber} · issued revision ${drawing.revisionLabel}`, exact: true }).check(); await page.getByRole('checkbox', { name: `${document.title} · supporting revision ${document.revisionNumber}`, exact: true }).check();
  const blocked = preparation.sources.documents.find(item => item.kind === 'drawing'); assert.ok(blocked); assert.equal(blocked.citable, false); assert.equal(blocked.citationHold.code, 'issued_drawing_required'); assert.equal(await page.getByRole('checkbox', { name: `${blocked.title} · supporting revision ${blocked.revisionNumber}`, exact: true }).isDisabled(), true); return preparation;
}
async function fillResponse(page, rfiId) { await gotoRecord(page, `/rfis/${rfiId}/draft-response`); await page.getByRole('textbox', { name: 'Proposed response text', exact: true }).fill(proposed); await page.getByRole('textbox', { name: 'Reported potential cost (USD)', exact: true }).fill('12345.67'); await page.getByRole('textbox', { name: 'Reported potential schedule days', exact: true }).fill('7'); }
async function fillRecipients(page, rfiId, selected) { await gotoRecord(page, `/rfis/${rfiId}/distribution-list`); for (const recipient of recipientChoices) await page.getByRole('checkbox', { name: recipient, exact: true }).setChecked(selected.includes(recipient)); }
async function unicodeAndLateReview(page, projectId, width) {
  const panel = page.locator('[data-action="rfi.create"]'); const input = page.getByRole('textbox', { name: 'RFI question', exact: true }); const before = await control('counts');
  await input.fill('😀'.repeat(12001)); assert.equal(await panel.getByRole('button', { name: steps['rfi.create'][0], exact: true }).count(), 0); await input.fill('😀'.repeat(12000));
  const checked = await review(page, 'rfi.create', projectId); assert.equal(Array.from(checked.value.preview.question).length, 12000); assert.equal(checked.value.preview.question.length, 24000); assert.deepEqual(await control('counts'), before); await input.fill(question);
  let release, ready; const gate = new Promise(resolve => { release = resolve; }); const received = new Promise(resolve => { ready = resolve; }); const match = `**${prefix}/projects/${projectId}/rfis:preflight`;
  const intercept = async route => { const actual = await route.fetch(); ready(); await gate; await route.fulfill({ response: actual }); };
  await page.route(match, intercept); await panel.getByRole('button', { name: steps['rfi.create'][0], exact: true }).click(); await received; await input.fill('Different authored question while review is delayed.'); release();
  await page.getByText(/facts changed while.*review.*loading/i).waitFor(); assert.equal(await panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).count(), 0); assert.deepEqual(await control('counts'), before); await page.unroute(match, intercept); await input.fill(question);
  report.contractChecks.push({ name: '12000 Unicode codepoints accepted and12001 blocked without effect', width }); report.recoveryChecks.push({ name: 'late different-question review discarded', width }); await snapshot(page, 'late-question-review-discarded', width);
}
async function lostCreateAcrossCurrentHead(page, projectId, width) {
  const panel = page.locator('[data-action="rfi.create"]'); const routePath = `/projects/${projectId}/rfis`; const before = await control('counts'); await review(page, 'rfi.create', projectId);
  let original, dropped = false; expectedTransport.get(page).add(prefix + routePath);
  const intercept = async route => { if (dropped) return route.continue(); dropped = true; const actual = await route.fetch(); assert.equal(actual.status(), 200); original = { value: await actual.json(), key: route.request().headers()['repeatability-request-id'], version: route.request().headers()['if-match'], body: route.request().postData(), route: routePath }; await route.abort('failed'); };
  await page.route(`**${prefix}${routePath}`, intercept); await panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).click(); await panel.getByRole('alert').waitFor(); assert.ok(original); expectedDelta(before, await control('counts'), 'rfi.create');
  await page.unroute(`**${prefix}${routePath}`, intercept); expectedTransport.get(page).delete(prefix + routePath); const advanced = await control('advance_support'); const afterSource = await control('counts');
  const input = page.getByRole('textbox', { name: 'RFI question', exact: true }); await input.fill('Edited question before retrieving the original outcome.'); await input.fill(question); await input.fill('Edited question before retrieving the original outcome.');
  assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0); assert.equal(await panel.getByRole('button', { name: steps['rfi.create'][0], exact: true }).count(), 0);
  // These real AppLinks keep action memory alive across SPA unmount/remount.
  await page.locator('main a[href="/rfis"]').click(); await settled(page); await page.getByRole('link', { name: 'Choose a project to create an RFI', exact: true }).click(); await settled(page); await page.getByRole('link', { name: 'Create an RFI question', exact: true }).click(); await settled(page);
  assert.equal(await input.inputValue(), question); assert.equal(await panel.getByRole('button', { name: 'Retry same action', exact: true }).count(), 1, 'A current-head refresh that invalidates selected choices must preserve original exact retry on remount'); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0); assert.equal(await panel.getByRole('button', { name: steps['rfi.create'][0], exact: true }).count(), 0);
  await retryUI(page, 'rfi.create', original, width); assert.deepEqual(await control('counts'), afterSource);
  await page.getByRole('button', { name: 'Clear unavailable citation selections', exact: true }).click(); const current = await json(page.context(), `/projects/${projectId}/preparation`); const support = current.sources.documents.find(item => item.revisionId === advanced.revisionId); assert.ok(support?.citable);
  await page.getByRole('checkbox', { name: `${support.title} · supporting revision ${support.revisionNumber}`, exact: true }).check(); await input.fill('Explicitly edited new question only after original outcome was retrieved.'); const fresh = await review(page, 'rfi.create', projectId); assert.equal(fresh.value.preview.source.documents[0].revisionId, advanced.revisionId); await retryHTTP(page.context(), original, width); assert.deepEqual(await control('counts'), afterSource);
  await snapshot(page, 'lost-original-create-survives-current-head-and-SPA-remount', width); report.recoveryChecks.push({ name: 'lost committed create preserves rawbody/quotedversion/UUID across edit/revert/current-source-loss/SPAremount and recovers once before explicit citation changes', width }); return original;
}
async function potentialImpactPreviews(page, rfiId, width) {
  const before = await control('counts'); const cost = page.getByRole('textbox', { name: 'Reported potential cost (USD)', exact: true }); const days = page.getByRole('textbox', { name: 'Reported potential schedule days', exact: true });
  for (const [money, dayText, cents, expectedDays] of [['', '', null, null], ['0.00', '0', 0, 0], ['999999999999.99', '9007199254740991', 99999999999999, 9007199254740991]]) {
    await cost.fill(money); await days.fill(dayText); const preview = await review(page, 'rfi.draftResponse', rfiId); assert.equal(preview.value.preview.costImpactCents, cents); assert.equal(preview.value.preview.scheduleImpactDays, expectedDays); assert.equal(preview.value.preview.informationalOnly, true); assert.equal(preview.value.preview.adopted, false); assert.deepEqual(await control('counts'), before);
  }
  await cost.fill('12345.67'); await days.fill('0.5'); assert.equal(await page.getByRole('button', { name: steps['rfi.draftResponse'][0], exact: true }).count(), 0); await days.fill('7');
  report.contractChecks.push({ name: 'optionalnull explicitzero and largest exactcost/safewholedays remain informational in pure previews', width });
}
async function actWithAlteredReplies(page, action, resource, width, mutations) {
  const before = await control('counts'); await review(page, action, resource); const panel = page.locator(`[data-action="${action}"]`); const [, apply, collection, command] = steps[action]; const routePath = `/${collection}/${resource}/${command}`;
  let original; let observed = 0;
  const intercept = async route => { const actual = await route.fetch(); assert.equal(actual.status(), 200); const value = await actual.json(); const request = { value, key: route.request().headers()['repeatability-request-id'], version: route.request().headers()['if-match'], body: route.request().postData(), route: routePath };
    if (!original) { original = request; assert.equal(value.effectApplied, true); assert.equal(value.replayed, false); } else { for (const key of ['key', 'body', 'version']) assert.equal(request[key], original[key]); assert.equal(value.receiptId, original.value.receiptId); assert.deepEqual(value.result, original.value.result); assert.equal(value.replayed, true); assert.equal(value.effectApplied, false); report.exactRetries.push({ action, width, receiptId: value.receiptId, alteredReplyToGenuineReplay: true }); }
    const altered = structuredClone(value); mutations[observed++][1](altered); await route.fulfill({ response: actual, json: altered }); };
  await page.route(`**${prefix}${routePath}`, intercept);
  for (let index = 0; index < mutations.length; index++) {
    await actionResponse(page, routePath, () => panel.getByRole('button', { name: index === 0 ? apply : 'Retry same action', exact: true }).click()); await panel.getByRole('alert').waitFor(); await settled(page); assert.match(await panel.getByRole('alert').innerText(), /incomplete or unsupported record/); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
    expectedDelta(before, await control('counts'), action); report.contractChecks.push({ name: mutations[index][0], width, genuineReceipt: original.value.receiptId, responseOnly: true });
  }
  assert.equal(observed, mutations.length); await page.unroute(`**${prefix}${routePath}`, intercept); await retryUI(page, action, original, width); expectedDelta(before, await control('counts'), action); report.recoveryChecks.push({ name: `${action} rejects altered original reply/replays then recovers sameUUID once`, width }); return original;
}
async function malformedReviews(context, projectId, width) {
  const before = await control('counts'); const cases = [
    ['wrong prospective RFI count', value => { value.safeEffects.rfisDelta = 0; }],
    ['unqualified schedule adoption', value => { value.safeEffects.scheduleBaselineDeltaDays = 1; }],
    ['unqualified contract adoption', value => { value.safeEffects.contractValueDeltaCents = 1; }],
    ['different reviewed question', value => { value.preview.question = 'Unreviewed question'; }],
    ['source bytes falsely available', value => { value.preview.source.sourceContentAvailable = true; }],
    ['current source missing distribution decision', value => { value.preview.source.documents[0].rights = value.preview.source.documents[0].rights.filter(right => right.use === 'project_use'); }],
    ['missing exact source preview', value => { delete value.preview; }],
  ];
  for (const [name, mutate] of cases) {
    const page = await context.newPage(); await monitor(page); await fillCreate(page, projectId); const panel = page.locator('[data-action="rfi.create"]');
    await page.route(`**${prefix}/projects/${projectId}/rfis:preflight`, async route => { const actual = await route.fetch(); const value = await actual.json(); assert.equal(value.allowed, true); mutate(value); await route.fulfill({ response: actual, json: value }); });
    await panel.getByRole('button', { name: steps['rfi.create'][0], exact: true }).click(); await Promise.race([panel.getByRole('alert').waitFor(), panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).waitFor().then(() => { throw new Error('Malformed preflight admitted: ' + name); })]);
    assert.equal(await panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).count(), 0); assert.equal(await panel.locator('pre').count(), 0); assert.deepEqual(await control('counts'), before); report.contractChecks.push({ name, width, responseOnly: true }); await page.close();
  }
}
async function nonRetirableResponses(context, projectId, width) {
  const before = await control('counts'); const cases = [
    ['server unavailable retains original request', 500, 'action_unavailable', {}],
    ['unknown412 integrity hold retains original request', 412, 'rfi_integrity_hold', {}],
    ['incomplete negative receipt metadata refused', 412, 'record_changed', { receiptId: 'rfiapi_incomplete' }],
    ['negative receipt cannot claim positive effect', 412, 'rfi_source_changed', { receiptId: 'rfiapi_impossible', replayed: false, effectApplied: true }],
  ];
  for (const [name, status, code, metadata] of cases) {
    const page = await context.newPage(); await monitor(page); await fillCreate(page, projectId); await review(page, 'rfi.create', projectId); const panel = page.locator('[data-action="rfi.create"]'); const routePath = `/projects/${projectId}/rfis`; expectedFailures.get(page).add(prefix + routePath);
    // Negative shape validation only; this effect is never forwarded.
    await page.route(`**${prefix}${routePath}`, route => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ contractVersion: 'cipher.rfi-practice.v1', mode: 'practice', synthetic: true, currency: 'USD', ...metadata, error: { code, target: 'project', message: 'Synthetic bounded response-only fault', fix: null, details: null } }) }));
    await panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).click(); await panel.getByRole('alert').waitFor(); await settled(page); assert.equal(await panel.getByRole('button', { name: 'Retry same action', exact: true }).count(), 1); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0); if (Object.keys(metadata).length) assert.match(await panel.getByRole('alert').innerText(), /incomplete or unsupported record/);
    assert.deepEqual(await control('counts'), before); report.contractChecks.push({ name, width, responseOnly: true }); await page.close();
  }
}
async function malformedRecords(context, rfiId, responseApprovalId, distributionApprovalId, width) {
  const before = await control('counts'); const recordRoute = `/rfis/${rfiId}`; const responseRoute = `/rfi-response-approvals/${responseApprovalId}/packet`; const distributionRoute = `/rfi-distribution-approvals/${distributionApprovalId}/packet`;
  const cases = [
    ['open status beside official answered response', recordRoute, value => { value.status = 'open'; }],
    ['answered RFI retains pending response authorization', recordRoute, value => { Object.assign(value.responseApproval, { status: 'pending', authorizationStatus: 'pending', originalGrantStatus: null, reviewer: null, appliedBy: null, grantedAt: null, appliedAt: null }); }],
    ['official response cites unrelated approval', recordRoute, value => { value.officialResponse.approvalId = 'apr_unrelated'; }],
    ['official reviewer differs from original grant', recordRoute, value => { value.officialResponse.reviewer = { id: 'psn_unrelated', displayName: 'Unrelated reviewer' }; }],
    ['current rights omit distribution decision', recordRoute, value => { value.citations.documents[0].rights = value.citations.documents[0].rights.filter(right => right.use === 'project_use'); }],
    ['reported cents are boolean', recordRoute, value => { value.officialResponse.costImpactCents = false; }],
    ['reported schedule days are fractional', recordRoute, value => { value.officialResponse.scheduleImpactDays = 0.5; }],
    ['potential impacts falsely adopted', recordRoute, value => { value.officialResponse.adopted = true; }],
    ['source files falsely available', recordRoute, value => { value.citations.drawings[0].sourceContentAvailable = true; }],
    ['unregistered external recipient', recordRoute, value => { value.distributions[0].recipients = ['external@example.com']; }],
    ['external distribution falsely claimed', recordRoute, value => { value.distributions[0].externalDistribution = true; }],
    ['private proof field exposed', recordRoute, value => { value.sourceProof = {}; }],
    ['sealed response rights have wrong requested use', responseRoute, value => { value.reviewedCitations.documents[0].rights[0].use = 'distribution'; }],
    ['current packet head contradicts same packet record', responseRoute, value => { value.currentCitations.documents[0].currentRevisionId = 'rev_unrelated'; }],
    ['consumed reviewed response text differs from official original', responseRoute, value => { value.reviewedResponse.text = 'Unreviewed original response'; }],
    ['consumed reviewed response ID differs from official original', responseRoute, value => { value.reviewedResponse.id = 'rfiresponse_unrelated'; }],
    ['consumed reviewed distribution recipients differ from original delivery', distributionRoute, value => { value.reviewedDistributionList.recipients = ['project-team@synthetic-rfi.invalid']; }],
  ];
  for (const [name, apiRoute, mutate] of cases) for (const refresh of [false, true]) {
    const page = await context.newPage(); await monitor(page); const uiRoute = apiRoute.replace(/\/packet$/, ''); if (refresh) { await gotoRecord(page, uiRoute); await page.locator('main pre').first().waitFor(); }
    await page.route(`**${prefix}${apiRoute}`, async route => { const actual = await route.fetch(); assert.equal(actual.status(), 200); const value = await actual.json(); mutate(value); await route.fulfill({ response: actual, json: value }); });
    if (refresh) await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); else await gotoRecord(page, uiRoute); await page.getByRole('alert').waitFor(); assert.equal(await page.locator('main pre,main [data-action]').count(), 0); report.contractChecks.push({ name, width, refreshAfterVerifiedRead: refresh, responseOnly: true }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function malformedPreparations(context, projectId, width) {
  const before = await control('counts'); const cases = [
    ['working drawing is falsely citable', value => { value.sources.drawings[0].current.status = 'working'; }],
    ['noncurrent support is falsely citable', value => { const source = value.sources.documents.find(item => item.citable); source.currentRevisionId = 'rev_unrelated'; source.currentRevisionNumber += 1; }],
  ];
  for (const [name, mutate] of cases) for (const refresh of [false, true]) {
    const page = await context.newPage(); await monitor(page); if (refresh) await gotoRecord(page, `/projects/${projectId}/rfi-preparation`);
    await page.route(`**${prefix}/projects/${projectId}/preparation`, async route => { const actual = await route.fetch(); const value = await actual.json(); mutate(value); await route.fulfill({ response: actual, json: value }); });
    if (refresh) await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); else await gotoRecord(page, `/projects/${projectId}/rfi-preparation`);
    await page.getByRole('alert').waitFor(); assert.equal(await page.locator('main [data-action]').count(), 0); assert.equal(await page.getByRole('checkbox').count(), 0); report.contractChecks.push({ name, width, refreshAfterVerifiedRead: refresh, responseOnly: true }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function laterRecipientDraftAndRights(page, rfiId, width) {
  await control('hold_distribution_rights'); const before = await control('counts'); await fillRecipients(page, rfiId, [recipientChoices[2]]);
  assert.ok((await page.locator('main').innerText()).includes('Distribution: Held.')); const later = await act(page, 'rfi.setDistribution', rfiId, width); assert.equal(later.value.result.rfiVersion, 5); await retryUI(page, 'rfi.setDistribution', later, width);
  await gotoRecord(page, `/rfis/${rfiId}`); const record = await json(page.context(), `/rfis/${rfiId}`); assert.equal(record.nativeVersion, 5); assert.deepEqual(record.distributionList.recipients, [recipientChoices[2]]); assert.deepEqual(record.distributions[0].recipients, recipientChoices.slice(0, 2)); assert.equal(record.distributions.length, 1);
  const panel = page.locator('[data-action="rfi.requestDistribution"]'); const beforeBlocked = await control('counts'); const blocked = await actionResponse(page, `/rfis/${rfiId}/request-distribution:preflight`, () => panel.getByRole('button', { name: steps['rfi.requestDistribution'][0], exact: true }).click()); assert.equal(blocked.value.allowed, false); assert.equal(blocked.value.fingerprint, null); assert.equal(await panel.getByRole('button', { name: steps['rfi.requestDistribution'][1], exact: true }).count(), 0); assert.deepEqual(await control('counts'), beforeBlocked);
  expectedDelta(before, await control('counts'), 'rfi.setDistribution'); report.laterLists.push({ width, rfiId, originalDistributionRecipients: record.distributions[0].recipients, currentDraftRecipients: record.distributionList.recipients, currentNativeVersion: 5, distributions: 1 }); report.recoveryChecks.push({ name: 'project-use-only rights allow recipient draft but block distribution request; new current list preserves original one local distribution', width }); await snapshot(page, 'later-recipient-draft-and-distribution-rights-hold', width); return later;
}
async function staleCreationRecovery(page, projectId, original, width) {
  await fillCreate(page, projectId, 'A different synthetic coordination question requiring current supporting citation.', 'Synthetic current-source recovery question'); const panel = page.locator('[data-action="rfi.create"]'); const route = `/projects/${projectId}/rfis`; await review(page, 'rfi.create', projectId);
  const advanced = await control('advance_support'); const afterSource = await control('counts'); expectedFailures.get(page).add(prefix + route);
  const refused = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).click(), 412); assert.equal(refused.value.error.code, 'record_changed'); await panel.getByRole('alert').waitFor(); await settled(page); assert.deepEqual(await control('counts'), afterSource);
  const repeated = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click(), 412); for (const key of ['key', 'body', 'version']) assert.equal(repeated[key], refused[key]); assert.equal(repeated.value.error.code, refused.value.error.code); assert.deepEqual(await control('counts'), afterSource);
  await page.getByRole('button', { name: 'Clear unavailable citation selections', exact: true }).click(); const current = await json(page.context(), `/projects/${projectId}/preparation`); const support = current.sources.documents.find(item => item.revisionId === advanced.revisionId); assert.ok(support?.citable); await page.getByRole('checkbox', { name: `${support.title} · supporting revision ${support.revisionNumber}`, exact: true }).check();
  assert.equal(await panel.getByRole('button', { name: steps['rfi.create'][0], exact: true }).count(), 0); await snapshot(page, 'genuine-stale-source-keeps-original-request-before-explicit-retirement', width);
  await panel.getByRole('button', { name: 'Start a new current review', exact: true }).click(); const beforeFresh = await control('counts'); const reviewed = await review(page, 'rfi.create', projectId); assert.equal(reviewed.value.preview.source.documents[0].revisionId, advanced.revisionId); assert.deepEqual(await control('counts'), beforeFresh);
  const next = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['rfi.create'][1], exact: true }).click()); assert.notEqual(next.key, refused.key); assert.notEqual(next.value.result.rfiId, original.value.result.rfiId); assert.deepEqual(JSON.parse(next.body).documentRevisionIds, [advanced.revisionId]); expectedDelta(beforeFresh, await control('counts'), 'rfi.create'); await retryUI(page, 'rfi.create', next, width);
  const beforeHistory = await control('counts'); const details = panel.locator('details').filter({ hasText: 'Original refusal' }); if (await details.getAttribute('open') === null) await details.locator('summary').click(); assert.ok((await details.innerText()).includes('record_changed'));
  const old = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry refused request', exact: true }).click(), 412); for (const key of ['key', 'body', 'version']) assert.equal(old[key], refused[key]); assert.equal(old.value.error.code, refused.value.error.code); assert.equal(old.value.receiptId, refused.value.receiptId); assert.deepEqual(await control('counts'), beforeHistory);
  report.exactRetries.push({ action: 'rfi.create', width, refusedHistoricalRequest: true, key: old.key }); report.recoveryDrafts.push({ width, rfiId: next.value.result.rfiId, newRepeatabilityId: next.key, refusedRepeatabilityId: refused.key, before: beforeFresh, after: await control('counts') }); report.recoveryChecks.push({ name: 'genuine supporting-head412 explicitretirement/currentcitationchoice creates one newRFI/newUUID and preserves original refusal history', width }); await snapshot(page, 'explicit-current-citation-review-preserves-original-refusal-history', width); await retryHTTP(page.context(), original, width);
}
async function scopeAndIdentity(page, rfiId, width) {
  const before = await control('counts'); const hidden = await control('hidden_id'); expectedFailures.get(page).add(prefix + `/projects/${hidden.projectId}/preparation`); await gotoRecord(page, `/projects/${hidden.projectId}/rfi-preparation`); await page.getByRole('alert').waitFor(); assert.equal(await page.locator('main pre,main [data-action]').count(), 0); const hiddenSearch = await json(page.context(), '/projects?search=Hidden'); assert.equal(hiddenSearch.count, 0); assert.deepEqual(await control('counts'), before); await snapshot(page, 'hidden-project-refused-before-source-disclosure', width);
  await gotoRecord(page, `/rfis/${rfiId}`); await exactText(page, 'Original RFI question', question); for (const route of ['/session', '/projects', `/rfis/${rfiId}`]) expectedFailures.get(page).add(prefix + route);
  await control('expire_sessions'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await page.getByRole('heading', { name: 'Start an RFI practice session', exact: true }).waitFor(); assert.equal(await page.locator('main pre,main [data-action]').count(), 0); await snapshot(page, 'expired-RFI-session-clears-facts', width);
  await choose(page, 'staff'); await gotoRecord(page, `/rfis/${rfiId}`); await exactText(page, 'Original RFI question', question); await control('end_staff_membership'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await page.waitForFunction(() => document.querySelectorAll('main pre,main [data-action]').length === 0); await snapshot(page, 'actual-staff-membership-loss-clears-facts', width); report.recoveryChecks.push({ name: 'hidden project scopes and genuine session/membership loss clear source facts and actions', width });
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of (process.env.CIPHER_RFI_WIDTHS ? process.env.CIPHER_RFI_WIDTHS.split(',').map(Number) : [1440, 1024, 390])) {
    await startServer(); const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' }); const page = await context.newPage(); await monitor(page); await page.goto(base); await snapshot(page, 'RFI-session-picker', width); await choose(page, 'staff');
    const baseline = await control('counts'); const projects = await json(context, '/projects'); assert.equal(projects.count, 1); const projectId = projects.items[0].id; await snapshot(page, 'staff-scoped-empty-RFI-log', width);
    if (width === 1440 && !process.env.CIPHER_RFI_SKIP_NEGATIVES) { await malformedPreparations(context, projectId, width); await malformedReviews(context, projectId, width); await nonRetirableResponses(context, projectId, width); }
    const preparation = await fillCreate(page, projectId); const drawing = preparation.sources.drawings.find(item => item.citable); assert.equal(drawing.revisionLabel, 'A'); assert.equal(drawing.current.issuedRevisionId, drawing.revisionId); assert.notEqual(drawing.current.workingRevisionId, drawing.revisionId); assert.notEqual(drawing.current.evidenceHeadRevisionId, drawing.documentRevisionId); await snapshot(page, 'issued-A-separate-working-and-disabled-drawing-evidence', width);
    await unicodeAndLateReview(page, projectId, width); const created = await lostCreateAcrossCurrentHead(page, projectId, width); const rfiId = created.value.result.rfiId; assert.equal(created.value.result.rfiVersion, 1);
    await gotoRecord(page, `/rfis/${rfiId}`); await exactText(page, 'Original RFI question', question); await keyboardTextRegion(page, 'Original RFI question', width); const initial = await json(context, `/rfis/${rfiId}`); assert.equal(initial.status, 'open'); assert.equal(initial.officialResponse, null); sourceFacts(initial.citations, JSON.parse(created.body)); assert.equal(initial.citations.documents[0].revisionNumber, 1); assert.equal(initial.citations.documents[0].currentRevisionNumber, 2); await snapshot(page, 'immutable-question-citation-original-versus-current-support', width);
    await fillResponse(page, rfiId); await potentialImpactPreviews(page, rfiId, width); const drafted = await act(page, 'rfi.draftResponse', rfiId, width, true); await retryUI(page, 'rfi.draftResponse', drafted, width); assert.equal(drafted.value.result.rfiVersion, 2);
    const draftedRecord = await json(context, `/rfis/${rfiId}`); assert.equal(draftedRecord.status, 'open'); assert.equal(draftedRecord.officialResponse, null); assert.equal(draftedRecord.draftResponse.text, proposed); assert.equal(draftedRecord.draftResponse.costImpactCents, 1234567); assert.equal(draftedRecord.draftResponse.scheduleImpactDays, 7); assert.equal(draftedRecord.draftResponse.informationalOnly, true); assert.equal(draftedRecord.draftResponse.adopted, false); assert.equal(draftedRecord.responseHistory.length, 1); await snapshot(page, 'staff-proposed-response-informational-impacts-only', width);
    await gotoRecord(page, `/rfis/${rfiId}`); assert.equal(await page.getByRole('button', { name: steps['rfi.requestResponse'][0], exact: true }).count(), 0); const staffSession = await json(context, '/session'); const beforeDutyRefusal = await control('counts'); const staffRequest = await context.request.post(base + prefix + `/rfis/${rfiId}/request-response:preflight`, { headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': staffSession.csrfToken }, data: {} }); assert.equal(staffRequest.status(), 403, await staffRequest.text()); assert.deepEqual(await control('counts'), beforeDutyRefusal); report.recoveryChecks.push({ name: 'actual staff author cannot perform PM request despite current project membership', width });
    const pmContext = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' }); const pmPage = await pmContext.newPage(); await monitor(pmPage); await pmPage.goto(base); await choose(pmPage, 'pm'); await gotoRecord(pmPage, `/rfis/${rfiId}`);
    const responseRequested = await act(pmPage, 'rfi.requestResponse', rfiId, width); await retryUI(pmPage, 'rfi.requestResponse', responseRequested, width); const responseApprovalId = responseRequested.value.result.approvalId; await gotoRecord(pmPage, `/rfi-response-approvals/${responseApprovalId}`); assert.equal(await pmPage.getByRole('button', { name: steps['rfi.approveResponse'][0], exact: true }).count(), 0); await approvalHeaderContext(pmPage, 'response', initial, width); await snapshot(pmPage, 'response-requester-cannot-self-authorize', width);
    const reviewerContext = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' }); const reviewerPage = await reviewerContext.newPage(); await monitor(reviewerPage); await reviewerPage.goto(base); await choose(reviewerPage, 'reviewer'); await gotoRecord(reviewerPage, `/rfi-response-approvals/${responseApprovalId}`);
    const responseGranted = await act(reviewerPage, 'rfi.approveResponse', responseApprovalId, width, true); await retryUI(reviewerPage, 'rfi.approveResponse', responseGranted, width); const grant = await json(reviewerContext, `/rfi-response-approvals/${responseApprovalId}/packet`); assert.equal(grant.status, 'granted'); assert.equal(grant.originalGrantStatus, 'granted'); assert.equal(grant.rfi.status, 'open'); assert.equal(grant.rfi.officialResponse, null); assert.notEqual(grant.reviewer.id, grant.requester.id); assert.notEqual(grant.reviewer.id, grant.reviewedResponse.author.id); await snapshot(reviewerPage, 'independent-PM-grant-leaves-RFI-open', width);
    await gotoRecord(pmPage, `/rfi-response-approvals/${responseApprovalId}`); const responseApplied = width === 1440 ? await actWithAlteredReplies(pmPage, 'rfi.applyResponse', responseApprovalId, width, [
      ['original official response receipt changes original native version', value => { value.result.rfiVersion = 999; }], ['original official response replay changes approval ID', value => { value.result.approvalId = 'apr_unrelated'; }], ['original official response replay changes reviewed response ID', value => { value.result.responseRevisionId = 'rfiresponse_unrelated'; }],
    ]) : await act(pmPage, 'rfi.applyResponse', responseApprovalId, width); await retryUI(pmPage, 'rfi.applyResponse', responseApplied, width); assert.equal(responseApplied.value.result.rfiVersion, 3);
    await gotoRecord(pmPage, `/rfis/${rfiId}`); await exactText(pmPage, 'Exact official response', proposed); const answered = await json(pmContext, `/rfis/${rfiId}`); assert.equal(answered.status, 'answered'); assert.equal(answered.nativeVersion, 3); assert.equal(answered.officialResponse.approvalId, responseApprovalId); assert.equal(answered.responseApproval.status, 'consumed'); assert.equal(answered.responseApproval.originalGrantStatus, 'granted'); assert.equal(answered.officialResponse.author.id, staffSession.person.id); assert.equal(answered.officialResponse.requester.id, grant.requester.id); assert.equal(answered.officialResponse.reviewer.id, grant.reviewer.id); assert.equal(answered.officialResponse.appliedBy.id, grant.requester.id); assert.equal(answered.officialResponse.costImpactCents, 1234567); assert.equal(answered.officialResponse.scheduleImpactDays, 7); assert.equal(answered.officialResponse.adopted, false); await snapshot(pmPage, 'same-independent-grant-separately-applied-official-answer', width);
    await fillRecipients(pmPage, rfiId, recipientChoices.slice(0, 2)); const listed = await act(pmPage, 'rfi.setDistribution', rfiId, width); await retryUI(pmPage, 'rfi.setDistribution', listed, width); assert.equal(listed.value.result.rfiVersion, 4); await snapshot(pmPage, 'fixed-synthetic-recipient-draft-no-distribution', width);
    await gotoRecord(pmPage, `/rfis/${rfiId}`); const distributionRequested = await act(pmPage, 'rfi.requestDistribution', rfiId, width); await retryUI(pmPage, 'rfi.requestDistribution', distributionRequested, width); const distributionApprovalId = distributionRequested.value.result.approvalId; assert.notEqual(distributionApprovalId, responseApprovalId); await gotoRecord(pmPage, `/rfi-distribution-approvals/${distributionApprovalId}`); assert.equal(await pmPage.getByRole('button', { name: steps['rfi.approveDistribution'][0], exact: true }).count(), 0); await approvalHeaderContext(pmPage, 'distribution', initial, width); await snapshot(pmPage, 'distribution-requester-cannot-self-authorize', width);
    await gotoRecord(reviewerPage, `/rfi-distribution-approvals/${distributionApprovalId}`); const distributionGranted = await act(reviewerPage, 'rfi.approveDistribution', distributionApprovalId, width); await retryUI(reviewerPage, 'rfi.approveDistribution', distributionGranted, width); const distributionGrant = await json(reviewerContext, `/rfi-distribution-approvals/${distributionApprovalId}/packet`); assert.equal(distributionGrant.status, 'granted'); assert.equal(distributionGrant.rfi.distributions.length, 0); assert.equal((await control('counts')).field_rfi_distributions, baseline.field_rfi_distributions); await snapshot(reviewerPage, 'independent-distribution-grant-does-not-distribute', width);
    await gotoRecord(pmPage, `/rfi-distribution-approvals/${distributionApprovalId}`); const distributed = width === 1440 ? await actWithAlteredReplies(pmPage, 'rfi.distribute', distributionApprovalId, width, [['original local distribution reply changes approved recipients', value => { value.result.recipients = [recipientChoices[2]]; }]]) : await act(pmPage, 'rfi.distribute', distributionApprovalId, width); await retryUI(pmPage, 'rfi.distribute', distributed, width); assert.equal(distributed.value.result.rfiVersion, 4); assert.equal(distributed.value.result.syntheticMailSink, true); assert.equal(distributed.value.result.externalDelivery, 'not_attempted'); assert.deepEqual(distributed.value.result.recipients, recipientChoices.slice(0, 2));
    await gotoRecord(pmPage, `/rfis/${rfiId}`); const finalRecord = await json(pmContext, `/rfis/${rfiId}`); assert.equal(finalRecord.status, 'answered'); assert.equal(finalRecord.nativeVersion, 4); assert.equal(finalRecord.distributions.length, 1); assert.equal(finalRecord.distributions[0].approvalId, distributionApprovalId); assert.equal(finalRecord.distributions[0].channel, 'mail-sink'); assert.equal(finalRecord.distributions[0].externalDistribution, false); assert.deepEqual(finalRecord.distributions[0].recipients, recipientChoices.slice(0, 2)); await snapshot(pmPage, 'one-local-synthetic-distribution-no-external-delivery', width);
    const primaryFinal = await control('counts'); fixedBoundary(baseline, primaryFinal); for (const [key, delta] of Object.entries({ field_rfis: 1, field_rfi_links: 2, drawing_references: 1, rfi_sources: 1, rfi_response_revisions: 1, rfi_distribution_revisions: 1, rfi_approval_sources: 2, approvals: 2, field_rfi_distributions: 1, rfi_action_receipts: 9 })) assert.equal(primaryFinal[key] - baseline[key], delta, `primary nine actions/${key}`);
    report.journeys.push({ width, nineActions: true, originalDrawing: 'A', separateWorkingHead: true, responseGrantLeavesOpen: true, sameResponseGrantApplied: true, separateDistributionGrant: true, syntheticDistributions: 1, adoptedPotentialImpacts: false }); report.counters.push({ width, baseline, primaryFinal });
    for (const route of ['/projects', '/rfis', '/rfi-response-approvals', '/rfi-distribution-approvals']) { const list = await json(context, route); assert.equal(list.count, 1); await gotoRecord(page, route); await page.getByRole('table').first().waitFor(); assert.equal((await page.locator('main').innerText()).includes('Hidden synthetic drainage project'), false); await snapshot(page, 'scoped-nonempty' + route.replaceAll('/', '-'), width); }
    const laterList = await laterRecipientDraftAndRights(pmPage, rfiId, width); await staleCreationRecovery(page, projectId, created, width);
    await gotoRecord(page, `/rfis/${rfiId}`); const current = await json(context, `/rfis/${rfiId}`); sourceFacts(current.citations, JSON.parse(created.body)); assert.equal(current.citations.documents[0].revisionNumber, 1); assert.equal(current.citations.documents[0].currentRevisionNumber, 3); await snapshot(page, 'original-issued-citations-beside-newer-support-and-rights', width);
    await gotoRecord(pmPage, `/rfi-response-approvals/${responseApprovalId}`); const historical = await json(pmContext, `/rfi-response-approvals/${responseApprovalId}/packet`); assert.equal(historical.status, 'consumed'); assert.equal(historical.originalGrantStatus, 'granted'); assert.equal(historical.reviewedCitations.documents[0].currentRevisionNumber, 2); assert.equal(historical.currentCitations.documents[0].currentRevisionNumber, 3); assert.equal(historical.currentCitations.documents[0].sourceChangedSinceReview, true); assert.equal(historical.reviewedCitations.documents[0].rights.length, 1); assert.equal(historical.currentCitations.documents[0].rights.length, 2); await snapshot(pmPage, 'original-sealed-response-review-versus-current-heads-rights', width);
    await reviewerPage.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await settled(reviewerPage); await retryUI(reviewerPage, 'rfi.approveDistribution', distributionGranted, width); await snapshot(reviewerPage, 'original-granted-distribution-receipt-beside-current-consumed', width);
    for (const original of [created, drafted]) await retryHTTP(context, original, width); for (const original of [responseRequested, responseApplied, listed, distributionRequested, distributed, laterList]) await retryHTTP(pmContext, original, width); for (const original of [responseGranted, distributionGranted]) await retryHTTP(reviewerContext, original, width);
    if (width === 1440 && !process.env.CIPHER_RFI_SKIP_NEGATIVES) await malformedRecords(context, rfiId, responseApprovalId, distributionApprovalId, width);
    await pmContext.close(); await reviewerContext.close(); await scopeAndIdentity(page, rfiId, width); const final = await control('counts'); fixedBoundary(baseline, final); for (const [key, delta] of Object.entries({ field_rfis: 2, field_rfi_links: 4, drawing_references: 2, rfi_sources: 2, rfi_response_revisions: 1, rfi_distribution_revisions: 2, rfi_approval_sources: 2, approvals: 2, field_rfi_distributions: 1, rfi_action_receipts: 11, document_revisions: 2 })) assert.equal(final[key] - baseline[key], delta, `after separately qualified later list/recovery/${key}`); report.counters[report.counters.length - 1].finalAfterRecovery = final;
    report.widths.push(width); await context.close(); await stopServer();
  }
  assert.deepEqual(report.errors, []); assert.deepEqual(report.violations, []);
} catch (error) { report.errors.push({ message: error.stack ?? String(error) }); throw error; }
finally { await browser?.close(); await stopServer(); await writeFile(path.join(artifacts, 'rfi-smoke.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ views: report.views.length, journeys: report.journeys.length, laterLists: report.laterLists.length, recoveryDrafts: report.recoveryDrafts.length, exactRetries: report.exactRetries.length, recoveryChecks: report.recoveryChecks.length, contractChecks: report.contractChecks.length, violations: report.violations.length, errors: report.errors.length }));
