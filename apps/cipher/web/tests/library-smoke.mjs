import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
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
const port = Number(process.env.CIPHER_LIBRARY_PORT ?? 18774);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/library-practice/v1';
const artifacts = process.env.CIPHER_LIBRARY_ARTIFACTS ?? '/tmp/cipher-completion/library-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', widths: [], views: [], journeys: [], recoveryDrafts: [], recoverySuccessors: [], exactRetries: [], recoveryChecks: [], contractChecks: [], counters: [], errors: [], violations: [],
  axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard traversal remains checked'] };
// Bounded native controls exist on the disposable process stdin only. No public test routes.
const fixtureControl = `
import json, sys
from threading import Thread
from apps.cipher.library_practice_server import make_library_practice_server
from apps.cipher.library_practice_fixture import PM_LOGIN, BOOTSTRAP_LOGIN
server = make_library_practice_server(port=int(sys.argv[1]))
def controls():
    for command in sys.stdin:
        with server.cipher_lock, server.cipher.db._lock:
            c = server.cipher
            if command == "counts\\n":
                tables = ("library_entries", "library_revisions", "library_heads", "library_plans", "library_adoptions", "library_action_receipts", "documents", "document_revisions", "approvals", "audit_log", "journals", "bills", "prime_bills", "prime_bill_sends", "outbox", "payment_intents", "collections")
                result = {table: c.db.scalar("SELECT COUNT(*) FROM " + table) for table in tables}
                result.update(nativeSubmissions=len(c.provider.submissions), nativeTransfers=len(c.provider.transfers))
            elif command == "advance_project\\n":
                c.plugin("library").create(c.library_practice_records["project_id"], {"kind":"contract_clause", "title":"Independent genuinely later authored control", "text":"Synthetic actual intervening text, not issued.", "sourceLocator":"Owned editor / independent later creation"}, actor=PM_LOGIN)
                result = {"projectAdvanced":True}
            elif command == "advance_revision\\n":
                row = c.db.one("SELECT id FROM library_entries ORDER BY rowid LIMIT 1")
                original = c.plugin("library").entry_proof(row["id"], current=True)
                changed = c.plugin("library").revise(row["id"], {"previousRevisionId":original["currentRevisionId"], "text":"Synthetic genuine intervening authored revision.", "sourceLocator":"Owned editor / later revision", "changeReason":"Bounded current-source browser recovery"}, actor=PM_LOGIN)
                result = {"entryId":row["id"], "currentRevisionId":changed["currentRevisionId"]}
            elif command == "expire_sessions\\n":
                from apps.cipher.library_sessions import IDLE_SECONDS
                original_clock = server.sessions.clock
                server.sessions.clock = lambda: original_clock()+IDLE_SECONDS+1
                result = {"sessionsExpired":True}
            elif command == "end_author_membership\\n":
                c.plugin("people").end_membership(PM_LOGIN,c.library_practice_records["project_id"],reason="Synthetic library current-duty browser control",actor=BOOTSTRAP_LOGIN)
                result = {"membershipEnded":True}
            elif command == "hidden_id\\n":
                result = {"projectId":c.library_practice_records["hidden_project_id"]}
            else:
                raise ValueError("Unsupported bounded library test control")
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
    if (server.exitCode !== null) throw new Error(`The library server exited (${server.exitCode}): ${diagnostics}`);
    try { if ((await fetch(base)).ok) return; } catch { /* Wait for the owned local server. */ }
    await delay(100);
  }
  throw new Error(`The library server did not become ready: ${diagnostics}`);
}
async function control(command) { const result = once(serverLines, 'line', { signal: AbortSignal.timeout(10000) }); server.stdin.write(command + '\n'); return JSON.parse((await result)[0]); }
async function stopServer() { if (!server || server.exitCode !== null) return; const result = once(server, 'exit'); server.kill('SIGTERM'); await result; serverLines.close(); server = undefined; }
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json(); assert.equal(value.contractVersion, 'cipher.library-practice.v1'); assert.equal(value.mode, 'practice'); assert.equal(value.synthetic, true); return value;
}
async function settled(page) {
  const idle = () => {
    const main = document.querySelector('main');
    return !!main && main.getAttribute('aria-busy') !== 'true' && !main.querySelector('[role="progressbar"], [data-action][aria-busy="true"]');
  };
  await page.waitForFunction(idle);
  for (let attempt = 0; attempt < 400 && pendingReads.get(page)?.size; attempt++) await delay(25);
  if (pendingReads.get(page)?.size) await writeFile(path.join(artifacts, 'pending-scoped-reads.json'), JSON.stringify({ page: page.url(), pending: [...pendingReads.get(page)].map(request => ({ id: readIds.get(page).get(request), method: request.method(), url: request.url() })), events: readEvents.get(page) }, null, 2) + '\n');
  assert.equal(pendingReads.get(page)?.size ?? 0, 0, 'The library view still has a pending scoped read; see pending-scoped-reads.json.');
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
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  report.violations.push(...axe.violations.map(value => ({ name, width, id: value.id, nodes: value.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content'); assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width });
}
async function modalSnapshot(page, name, width) {
  const dialog = page.getByRole('dialog'); await dialog.waitFor(); assert.ok(await dialog.getAttribute('aria-labelledby'));
  const size = await page.evaluate(() => [innerWidth, document.documentElement.scrollWidth]); assert.ok(size[1] <= size[0], `${name} overflows ${width}px.`);
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
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
  await page.getByRole('heading', { name: 'Start a library practice session', exact: true }).waitFor();
  const personas = await json(page.context(), '/personas'); const person = personas.value.find(item => item.personaId === persona); assert.ok(person);
  await page.getByRole('button', { name: `Start as ${person.displayName}`, exact: true }).click(); await settled(page);
}
const steps = {
  'library.create': ['Review authored entry', 'Create authored entry', 'projects', 'create-entry'],
  'library.revise': ['Review authored revision', 'Create next revision', 'library-entries', 'revise'],
  'library.prepareReference': ['Review project reference intent', 'Prepare project reference intent', 'library-revisions', 'prepare-reference'],
  'library.requestAdoption': ['Review reference adoption request', 'Request independent reference review', 'reference-plans', 'request-adoption'],
  'library.approveAdoption': ['Review independent reference authorization', 'Authorize project reference', 'adoption-approvals', 'approve'],
  'library.applyAdoption': ['Review authorized reference application', 'Apply project reference', 'adoption-approvals', 'apply'],
};
const authoredPrefix = '  SYNTHETIC authored practice text.\n<script>globalThis.libraryInjected=true</script>\nRésumé … 🏗️\n';
function boundedText(suffix) { const head = authoredPrefix + suffix + '\n'; const remaining = 65536 - Buffer.byteLength(head); return head + '界'.repeat(Math.floor(remaining / 3)) + 'x'.repeat(remaining % 3); }
const originalText = boundedText('Original library wording / original authored bytes.');
const adoptedText = boundedText('Second library wording / exact independently reviewed bytes.');
const laterText = '  SYNTHETIC later authored wording.\nRésumé … 🏗️\nThis separately stored revision does not rewrite the adopted original copy.\n';
assert.equal(Buffer.byteLength(originalText), 65536); assert.equal(Buffer.byteLength(adoptedText), 65536);
async function actionResponse(page, route, click, status = 200) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === prefix + route && response.request().method() === 'POST');
  await click(); const response = await pending; assert.equal(response.status(), status, `${route}: ${await response.text()}`);
  return { value: await response.json(), key: response.request().headers()['repeatability-request-id'], version: response.request().headers()['if-match'], body: response.request().postData(), route };
}
function fixedBoundary(before, after) { for (const key of ['journals', 'bills', 'prime_bills', 'prime_bill_sends', 'outbox', 'payment_intents', 'collections', 'nativeSubmissions', 'nativeTransfers']) assert.equal(after[key], before[key], key); }
function expectedDelta(before, after, action) {
  fixedBoundary(before, after);
  const changes = {
    'library.create': { library_entries: 1, library_revisions: 1, library_heads: 1, documents: 1, document_revisions: 1 },
    'library.revise': { library_revisions: 1, library_heads: 1, document_revisions: 1 },
    'library.prepareReference': { library_plans: 1 },
    'library.requestAdoption': { approvals: 1 },
    'library.approveAdoption': {}, 'library.applyAdoption': { library_adoptions: 1 },
  }[action];
  for (const key of ['library_entries', 'library_revisions', 'library_heads', 'documents', 'document_revisions', 'library_plans', 'approvals', 'library_adoptions']) assert.equal(after[key] - before[key], changes[key] ?? 0, `${action}/${key}`);
  assert.equal(after.library_action_receipts - before.library_action_receipts, 1, `${action}/one original action receipt`);
}
async function act(page, action, resource, width, keyboard = false) {
  const [review, apply, collection, command] = steps[action]; const panel = page.locator(`[data-action="${action}"]`); const before = await control('counts');
  const preflight = await actionResponse(page, `/${collection}/${resource}/${command}:preflight`, async () => { if (keyboard) { await panel.getByRole('button', { name: review, exact: true }).focus(); await page.keyboard.press('Enter'); } else await panel.getByRole('button', { name: review, exact: true }).click(); });
  assert.equal(preflight.value.allowed, true); await panel.getByRole('button', { name: apply, exact: true }).waitFor(); assert.deepEqual(await control('counts'), before, `${action} preflight is pure`);
  for (const key of ['journalDelta', 'mailSinkDelta']) assert.equal(preflight.value.safeEffects[key], 0);
  for (const key of ['externalDistribution', 'contractExecution', 'engineeringCertification']) assert.equal(preflight.value.safeEffects[key], false);
  assert.equal(preflight.value.safeEffects.projectReferenceOnly, true);
  assert.ok(preflight.value.preview); assert.equal(preflight.value.preview.byteCount, Buffer.byteLength(preflight.value.preview.text)); assert.equal(preflight.value.preview.encoding, 'UTF-8');
  await exactSource(panel, 'Exact authored source text', preflight.value.preview.text);
  for (const field of ['targetLocator', 'purpose']) if (preflight.value.preview[field] !== null) assert.ok((await panel.innerText()).includes(preflight.value.preview[field]), `${action} must show exact reviewed ${field}`);
  const result = await actionResponse(page, `/${collection}/${resource}/${command}`, () => panel.getByRole('button', { name: apply, exact: true }).click());
  assert.equal(result.value.result.action, action); assert.equal(result.value.effectApplied, true); assert.equal(result.value.replayed, false);
  for (const key of ['journalCountDelta', 'apBalanceDeltaCents', 'arBalanceDeltaCents', 'providerCallsDelta']) assert.equal(result.value.result[key], 0);
  assert.equal(result.value.result.effectKind, 'project-reference-only/1'); assert.match(result.key, /^[0-9a-f-]{36}$/); assert.match(result.version, /^"[^\"]+"$/);
  expectedDelta(before, await control('counts'), action); return result;
}
async function applyWithAlteredOriginalReplies(page, approvalId, width) {
  const action = 'library.applyAdoption'; const [review, apply] = steps[action]; const routePath = `/adoption-approvals/${approvalId}/apply`;
  const panel = page.locator(`[data-action="${action}"]`); const before = await control('counts');
  const reviewed = await actionResponse(page, routePath + ':preflight', () => panel.getByRole('button', { name: review, exact: true }).click());
  assert.equal(reviewed.value.allowed, true); await panel.getByRole('button', { name: apply, exact: true }).waitFor(); await exactSource(panel, 'Exact authored source text', adoptedText);
  for (const field of ['targetLocator', 'purpose']) assert.ok((await panel.innerText()).includes(reviewed.value.preview[field])); assert.deepEqual(await control('counts'), before);
  const mutations = [
    ['original apply reply changes reviewed revision', value => { value.result.revisionId = 'librev_unrelated'; }],
    ['original apply replay changes reviewed target', value => { value.result.targetLocator = 'Unreviewed project location'; }],
    ['original apply replay changes reviewed purpose', value => { value.result.purpose = 'Unreviewed purpose'; }],
    ['original apply replay changes original text digest', value => { value.result.contentHash = '0'.repeat(64); }],
  ];
  let original; let observed = 0;
  const intercept = async route => {
    const actual = await route.fetch(); assert.equal(actual.status(), 200); const value = await actual.json();
    const request = { value, key: route.request().headers()['repeatability-request-id'], version: route.request().headers()['if-match'], body: route.request().postData(), route: routePath };
    if (!original) { original = request; assert.equal(value.effectApplied, true); assert.equal(value.replayed, false); }
    else { for (const key of ['key', 'version', 'body']) assert.equal(request[key], original[key]); assert.equal(value.receiptId, original.value.receiptId); assert.deepEqual(value.result, original.value.result); assert.equal(value.replayed, true); assert.equal(value.effectApplied, false); report.exactRetries.push({ action, width, receiptId: value.receiptId, originalReplyAlteredLocally: true }); }
    const altered = structuredClone(value); mutations[observed++][1](altered); await route.fulfill({ response: actual, json: altered });
  };
  await page.route(`**${prefix}${routePath}`, intercept);
  for (let index = 0; index < mutations.length; index++) {
    await actionResponse(page, routePath, () => panel.getByRole('button', { name: index === 0 ? apply : 'Retry same action', exact: true }).click());
    await panel.getByRole('alert').waitFor(); await settled(page); assert.match(await panel.getByRole('alert').innerText(), /incomplete or unsupported record/);
    assert.equal(await panel.getByRole('link', { name: 'Open adopted project reference', exact: true }).count(), 0); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
    expectedDelta(before, await control('counts'), action); report.contractChecks.push({ name: mutations[index][0], width, responseOnly: true, genuineOriginalReceipt: original.value.receiptId });
  }
  assert.equal(observed, 4); await page.unroute(`**${prefix}${routePath}`, intercept); await retryUI(page, action, original, width); expectedDelta(before, await control('counts'), action);
  report.recoveryChecks.push({ name: 'four altered replies refuse receipt mismatch then original sameUUID receipt recovers with one reference effect', width }); return original;
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
  const response = await context.request.post(base + prefix + original.route, { headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken, 'Repeatability-Request-ID': original.key, 'If-Match': original.version }, data: original.body });
  assert.equal(response.status(), 200, await response.text()); const replay = await response.json(); assert.equal(replay.receiptId, original.value.receiptId); assert.deepEqual(replay.result, original.value.result); assert.equal(replay.replayed, true); assert.equal(replay.effectApplied, false);
  assert.deepEqual(await control('counts'), before); report.exactRetries.push({ action: original.value.result.action, width, receiptId: replay.receiptId, afterLaterTransitions: true });
}
async function fillCreate(page, projectId, text = originalText, title = 'Synthetic exact UTF-8 piping specification') {
  await gotoRecord(page, `/projects/${projectId}/library-preparation`);
  await page.getByRole('combobox', { name: 'Library entry kind', exact: true }).selectOption('specification_template');
  await page.getByRole('textbox', { name: 'Library entry title', exact: true }).fill(title);
  await page.getByRole('textbox', { name: 'Authored source text', exact: true }).fill(text);
  await page.getByRole('textbox', { name: 'Author source locator', exact: true }).fill('Author editor / piping specification section 1');
}
async function fillRevision(page, entryId, text, reason) {
  await gotoRecord(page, `/library-entries/${entryId}/revise`);
  await page.getByRole('textbox', { name: 'Authored source text', exact: true }).fill(text);
  await page.getByRole('textbox', { name: 'Revision source locator', exact: true }).fill('Author editor / piping specification / ' + reason);
  await page.getByRole('textbox', { name: 'Revision change reason', exact: true }).fill(reason);
}
async function exactSource(page, label, text) {
  const source = page.locator(`pre[aria-label="${label}"]`); await source.waitFor(); assert.equal(await source.textContent(), text);
  assert.equal(await source.evaluate(() => globalThis.libraryInjected), undefined); assert.equal(await source.locator('script, img, iframe').count(), 0);
}
async function lateReviewAndLimit(page, projectId, width) {
  await fillCreate(page, projectId); const panel = page.locator('[data-action="library.create"]'); const before = await control('counts');
  const input = page.getByRole('textbox', { name: 'Authored source text', exact: true }); await input.fill(originalText + 'x'); await settled(page);
  assert.equal(await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).count(), 0, '65537 actual UTF8 bytes cannot be reviewed'); await input.fill(originalText);
  const match = `**${prefix}/projects/${projectId}/create-entry:preflight`; let release, ready;
  const gate = new Promise(resolve => { release = resolve; }); const received = new Promise(resolve => { ready = resolve; });
  const intercept = async route => { const actual = await route.fetch(); assert.equal(actual.status(), 200); ready(); await gate; await route.fulfill({ response: actual }); };
  await page.route(match, intercept); await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).click(); await received;
  await input.fill(laterText); release(); await page.getByText(/facts changed while.*review.*loading/i).waitFor();
  assert.equal(await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).count(), 0); assert.deepEqual(await control('counts'), before);
  await snapshot(page, 'late-authored-review-discarded', width); await page.unroute(match, intercept); await input.fill(originalText);
  report.recoveryChecks.push({ name: 'exact65536UTF8 allowed/65537blocked and delayed different-input review discarded', width });
}
async function lostCreate(page, projectId, width) {
  const panel = page.locator('[data-action="library.create"]'); const routePath = `/projects/${projectId}/create-entry`; const before = await control('counts');
  await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).waitFor();
  await exactSource(panel, 'Exact authored source text', originalText);
  let original, dropped = false; expectedTransport.get(page).add(prefix + routePath);
  const intercept = async route => { if (dropped) return route.continue(); dropped = true; const actual = await route.fetch(); assert.equal(actual.status(), 200); original = { value: await actual.json(), key: route.request().headers()['repeatability-request-id'], version: route.request().headers()['if-match'], body: route.request().postData(), route: routePath }; await route.abort('failed'); };
  await page.route(`**${prefix}${routePath}`, intercept); await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).click(); await panel.getByRole('alert').waitFor(); assert.ok(original);
  expectedDelta(before, await control('counts'), 'library.create'); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
  await page.unroute(`**${prefix}${routePath}`, intercept); expectedTransport.get(page).delete(prefix + routePath);
  const input = page.getByRole('textbox', { name: 'Authored source text', exact: true }); await input.fill(laterText); await input.fill(originalText); await input.fill(laterText);
  assert.equal(await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).count(), 0);
  assert.equal(await panel.getByRole('button', { name: /Review edited/ }).count(), 0); await retryUI(page, 'library.create', original, width);
  await panel.getByRole('button', { name: /Review edited/ }).waitFor(); await snapshot(page, 'lost-create-original-receipt-recovered', width);
  await page.getByRole('link', { name: 'Open authored entry', exact: true }).click(); await settled(page); await page.goBack(); await settled(page);
  assert.equal(await input.inputValue(), originalText); await retryUI(page, 'library.create', original, width); expectedDelta(before, await control('counts'), 'library.create');
  report.recoveryChecks.push({ name: 'lost committed create preserves original text/body/version/UUID across edits/revert/remount', width }); return original;
}
async function malformedReviews(context, projectId, width) {
  const before = await control('counts');
  const cases = [
    ['wrong prospective entry count', value => { value.safeEffects.entriesDelta = 0; }],
    ['unqualified prospective journal', value => { value.safeEffects.journalDelta = 1; }],
    ['unqualified contract execution claim', value => { value.safeEffects.contractExecution = true; }],
    ['missing exact authored preview', value => { delete value.preview; }],
    ['incorrect UTF8 byte count', value => { value.preview.byteCount -= 1; }],
    ['different authored text than reviewed input', value => { value.preview.text = laterText; value.preview.byteCount = Buffer.byteLength(laterText); }],
    ['different entry title than reviewed input', value => { value.preview.title = 'Different source'; }],
  ];
  for (const [name, mutate] of cases) {
    const page = await context.newPage(); await monitor(page); await fillCreate(page, projectId);
    await page.route(`**${prefix}/projects/${projectId}/create-entry:preflight`, async route => { const actual = await route.fetch(); const value = await actual.json(); assert.equal(value.allowed, true); mutate(value); await route.fulfill({ response: actual, json: value }); });
    const panel = page.locator('[data-action="library.create"]'); await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).click();
    await Promise.race([panel.getByRole('alert').waitFor(), panel.getByRole('button', { name: steps['library.create'][1], exact: true }).waitFor().then(() => { throw new Error('Malformed preflight was admitted: ' + name); })]);
    assert.equal(await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).count(), 0); assert.equal(await panel.locator('pre').count(), 0);
    report.contractChecks.push({ name, width, responseOnly: true }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function nonRetirableResponses(context, projectId, width) {
  const before = await control('counts');
  const cases = [
    ['server action unavailable keeps original request', 500, 'action_unavailable', {}],
    ['unknown412 integrity hold keeps original request', 412, 'library_integrity_hold', {}],
    ['incomplete negative receipt is rejected', 412, 'library_source_changed', { receiptId: 'libapi_incomplete' }],
    ['positive effect negative receipt is rejected', 412, 'record_changed', { receiptId: 'libapi_impossible', replayed: false, effectApplied: true }],
  ];
  for (const [name, status, code, receipt] of cases) {
    const page = await context.newPage(); await monitor(page); await fillCreate(page, projectId); const panel = page.locator('[data-action="library.create"]');
    await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).waitFor();
    const routePath = `/projects/${projectId}/create-entry`; expectedFailures.get(page).add(prefix + routePath);
    // A negative-response shape check only: never forwards this effect request.
    await page.route(`**${prefix}${routePath}`, route => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ contractVersion: 'cipher.library-practice.v1', mode: 'practice', synthetic: true, ...receipt, error: { code, message: 'Synthetic bounded response-only fault', target: 'project', fix: null, details: null } }) }));
    await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).click(); await panel.getByRole('alert').waitFor(); await settled(page);
    assert.equal(await panel.getByRole('button', { name: 'Retry same action', exact: true }).count(), 1); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
    if (Object.keys(receipt).length) assert.match(await panel.getByRole('alert').innerText(), /incomplete or unsupported record/);
    assert.deepEqual(await control('counts'), before); report.contractChecks.push({ name, width, responseOnly: true }); await page.close();
  }
}
async function malformedRecords(context, ids, width) {
  const before = await control('counts');
  const cases = [
    ['entry byte count disagrees with actual UTF8 source', `/library-entries/${ids.entryId}`, value => { value.currentRevision.byteCount -= 1; }],
    ['entry revision count disagrees with full history', `/library-entries/${ids.entryId}`, value => { value.revisionCount += 1; }],
    ['revision encoding is unsupported', `/library-revisions/${ids.revisionId}`, value => { value.encoding = 'UTF-16'; }],
    ['revision current marker disagrees with current ID', `/library-revisions/${ids.revisionId}`, value => { value.isCurrent = true; }],
    ['plan current granted state has no grant', `/reference-plans/${ids.planId}`, value => { value.status = 'granted'; value.effectiveStatus = 'granted'; value.approvalId = null; }],
    ['prepared plan retains unrelated adopted reference', `/reference-plans/${ids.planId}`, value => { value.status = 'prepared'; value.effectiveStatus = 'stale'; value.approvalId = null; }],
    ['granted plan reports pending effective authorization', `/reference-plans/${ids.planId}`, value => { value.status = 'granted'; value.effectiveStatus = 'pending'; value.referenceId = null; }],
    ['consumed approval reports pending authorization', `/adoption-approvals/${ids.approvalId}/packet`, value => { value.authorizationStatus = 'pending'; }],
    ['pending approval retains completed grant and application acts', `/adoption-approvals/${ids.approvalId}/packet`, value => { value.status = 'pending'; value.authorizationStatus = 'pending'; }],
    ['self-granted approval packet', `/adoption-approvals/${ids.approvalId}/packet`, value => { value.reviewer = { ...value.requester }; }],
    ['reference falsely claims current source', `/project-references/${ids.referenceId}`, value => { value.sourceCurrent = true; }],
    ['reference copied text differs from original revision', `/project-references/${ids.referenceId}`, value => { value.text = laterText; }],
    ['private credentials field in public record', `/library-entries/${ids.entryId}`, value => { value.credentials = 'forbidden'; }],
    ['foreign practice provenance', `/library-entries/${ids.entryId}`, value => { value.contractVersion = 'cipher.commercial-practice.v1'; }],
  ];
  for (const [name, apiRoute, mutate] of cases) for (const refresh of [false, true]) {
    const page = await context.newPage(); await monitor(page); const uiRoute = apiRoute.replace(/\/packet$/, '');
    if (refresh) { await gotoRecord(page, uiRoute); await page.locator('main pre').first().waitFor(); }
    await page.route(`**${prefix}${apiRoute}`, async route => { const actual = await route.fetch(); assert.equal(actual.status(), 200); const value = await actual.json(); mutate(value); await route.fulfill({ response: actual, json: value }); });
    if (refresh) await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); else await gotoRecord(page, uiRoute);
    await page.getByRole('alert').waitFor(); assert.equal(await page.locator('main pre, main [data-action]').count(), 0, 'Invalid refreshed source must clear previously verified facts/actions.');
    report.contractChecks.push({ name, width, refreshAfterVerifiedRead: refresh, responseOnly: true }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function staleRecovery(page, projectId, original, width) {
  await fillCreate(page, projectId, 'Synthetic additional authored recovery text.\nNo issued document.', 'Synthetic recovery-only clause');
  const panel = page.locator('[data-action="library.create"]'); const route = `/projects/${projectId}/create-entry`;
  await panel.getByRole('button', { name: steps['library.create'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['library.create'][1], exact: true }).waitFor();
  await control('advance_project'); const afterSource = await control('counts'); expectedFailures.get(page).add(prefix + route);
  const refused = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['library.create'][1], exact: true }).click(), 412); assert.equal(refused.value.error.code, 'record_changed');
  await panel.getByRole('alert').waitFor(); assert.deepEqual(await control('counts'), afterSource);
  const retry = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click(), 412);
  for (const key of ['key', 'version', 'body']) assert.equal(retry[key], refused[key]); assert.equal(retry.value.error.code, refused.value.error.code); assert.deepEqual(await control('counts'), afterSource);
  await snapshot(page, 'genuine-library-version-refusal', width);
  await panel.getByRole('button', { name: 'Start a new current review', exact: true }).click(); const beforeFresh = await control('counts');
  const reviewed = await actionResponse(page, route + ':preflight', () => panel.getByRole('button', { name: steps['library.create'][0], exact: true }).click()); assert.equal(reviewed.value.allowed, true); assert.deepEqual(await control('counts'), beforeFresh);
  const next = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['library.create'][1], exact: true }).click());
  assert.notEqual(next.key, refused.key); assert.notEqual(next.value.result.entryId, original.value.result.entryId); expectedDelta(beforeFresh, await control('counts'), 'library.create');
  await retryUI(page, 'library.create', next, width); const beforeHistory = await control('counts');
  const details = panel.locator('details').filter({ hasText: 'Original refusal' }); if (await details.getAttribute('open') === null) await details.locator('summary').click(); assert.ok((await details.innerText()).includes('record_changed'));
  const old = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry refused request', exact: true }).click(), 412);
  for (const key of ['key', 'version', 'body']) assert.equal(old[key], refused[key]); assert.equal(old.value.error.code, refused.value.error.code); assert.equal(old.value.receiptId, refused.value.receiptId); assert.deepEqual(await control('counts'), beforeHistory);
  report.exactRetries.push({ action: 'library.create', width, refusedHistoricalRequest: true, key: old.key });
  report.recoveryDrafts.push({ width, entryId: next.value.result.entryId, repeatabilityId: next.key, refusedRepeatabilityId: refused.key, before: beforeFresh, after: await control('counts') });
  report.recoveryChecks.push({ name: 'genuine412 explicit retirement preserves refused history and fresh review creates once with a newUUID', width });
  await snapshot(page, 'explicit-current-review-preserves-original-refusal-history', width); await retryHTTP(page.context(), original, width);
}
async function staleRevisionRecovery(page, entryId, width) {
  const recoveryText = 'Synthetic preserved editor text for a freshly reconciled authored successor.\nRésumé … 🏗️';
  await fillRevision(page, entryId, recoveryText, 'Original attempted successor before source advanced'); const panel = page.locator('[data-action="library.revise"]'); const route = `/library-entries/${entryId}/revise`;
  await panel.getByRole('button', { name: steps['library.revise'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['library.revise'][1], exact: true }).waitFor();
  const advanced = await control('advance_revision'); assert.equal(advanced.entryId, entryId); const afterSource = await control('counts'); expectedFailures.get(page).add(prefix + route);
  const refused = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['library.revise'][1], exact: true }).click(), 412); assert.equal(refused.value.error.code, 'library_source_changed'); await panel.getByRole('alert').waitFor(); await settled(page);
  assert.equal(await page.getByRole('button', { name: 'Use current authored predecessor', exact: true }).count(), 0, 'Unresolved original revision request keeps its predecessor fixed');
  const retry = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click(), 412); for (const key of ['key', 'version', 'body']) assert.equal(retry[key], refused[key]); assert.deepEqual(await control('counts'), afterSource);
  await panel.getByRole('button', { name: 'Start a new current review', exact: true }).click(); const current = page.getByRole('button', { name: 'Use current authored predecessor', exact: true }); await current.waitFor();
  const editor = page.getByRole('textbox', { name: 'Authored source text', exact: true }); assert.equal(await editor.inputValue(), recoveryText); await current.click(); assert.equal(await editor.inputValue(), recoveryText);
  const reason = page.getByRole('textbox', { name: 'Revision change reason', exact: true }); assert.equal(await reason.inputValue(), ''); assert.equal(await panel.getByRole('button', { name: steps['library.revise'][0], exact: true }).count(), 0); await reason.fill('Fresh current-predecessor reconciliation reviewed explicitly');
  const beforeFresh = await control('counts'); const review = await actionResponse(page, route + ':preflight', () => panel.getByRole('button', { name: steps['library.revise'][0], exact: true }).click());
  assert.equal(review.value.allowed, true); assert.equal(review.value.preview.previousRevisionId, advanced.currentRevisionId); assert.equal(review.value.preview.text, recoveryText); assert.equal(review.value.preview.revisionNumber, 5); assert.deepEqual(await control('counts'), beforeFresh);
  const next = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['library.revise'][1], exact: true }).click()); assert.notEqual(next.key, refused.key); assert.equal(JSON.parse(next.body).previousRevisionId, advanced.currentRevisionId); assert.equal(next.value.result.revision, 5); assert.equal(next.value.result.entryId, entryId); expectedDelta(beforeFresh, await control('counts'), 'library.revise');
  await retryUI(page, 'library.revise', next, width); const beforeHistory = await control('counts'); const details = panel.locator('details').filter({ hasText: 'Original refusal' }); if (await details.getAttribute('open') === null) await details.locator('summary').click(); assert.ok((await details.innerText()).includes('library_source_changed'));
  const old = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry refused request', exact: true }).click(), 412); for (const key of ['key', 'version', 'body']) assert.equal(old[key], refused[key]); assert.equal(old.value.error.code, refused.value.error.code); assert.equal(old.value.receiptId, refused.value.receiptId); assert.deepEqual(await control('counts'), beforeHistory);
  report.exactRetries.push({ action: 'library.revise', width, refusedHistoricalRequest: true, key: old.key }); report.recoverySuccessors.push({ width, entryId, revision: 5, revisionId: next.value.result.revisionId, repeatabilityId: next.key, refusedRepeatabilityId: refused.key, before: beforeFresh, after: await control('counts') });
  report.recoveryChecks.push({ name: 'stale revision explicit retirement immediately reveals current predecessor and preserves editor text before fresh reason/review/newUUID successor', width }); await snapshot(page, 'stale-revision-explicit-current-predecessor-successor', width);
}
async function scopeAndIdentity(page, projectId, entryId, width) {
  const hidden = await control('hidden_id'); const before = await control('counts');
  expectedFailures.get(page).add(prefix + `/projects/${hidden.projectId}/preparation`);
  await gotoRecord(page, `/projects/${hidden.projectId}/library-preparation`); await page.getByRole('alert').waitFor(); assert.equal(await page.locator('main pre, main [data-action]').count(), 0);
  assert.deepEqual(await control('counts'), before); const projects = await json(page.context(), '/projects?search=Hidden'); assert.equal(projects.count, 0); assert.deepEqual(projects.items, []);
  await snapshot(page, 'hidden-project-refused-before-source-disclosure', width);
  await gotoRecord(page, `/library-entries/${entryId}`); await page.locator('main pre').first().waitFor();
  for (const route of ['/session', '/projects', `/library-entries/${entryId}`]) expectedFailures.get(page).add(prefix + route);
  await control('expire_sessions'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await page.getByRole('heading', { name: 'Start a library practice session', exact: true }).waitFor();
  assert.equal(await page.locator('main pre, main [data-action]').count(), 0); await snapshot(page, 'expired-library-session-clears-facts', width);
  await choose(page, 'author'); await gotoRecord(page, `/library-entries/${entryId}`); await page.locator('main pre').first().waitFor();
  await control('end_author_membership'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('main pre, main [data-action]').length === 0); await snapshot(page, 'actual-library-project-PM-loss-clears-facts', width);
  report.recoveryChecks.push({ name: 'hidden project remains scoped and expired session/actualPMmembership loss clear source facts and actions', width });
}
function revisionFacts(value, text, number) {
  assert.equal(value.text, text); assert.equal(value.byteCount, Buffer.byteLength(text)); assert.equal(value.encoding, 'UTF-8'); assert.equal(value.number, number);
  assert.equal(value.contentHash, createHash('sha256').update(text, 'utf8').digest('hex')); assert.equal(value.sourceKind, 'practice-authored-editor-text/1');
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of (process.env.CIPHER_LIBRARY_WIDTHS ? process.env.CIPHER_LIBRARY_WIDTHS.split(',').map(Number) : [1440, 1024, 390])) {
    await startServer(); const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' });
    const page = await context.newPage(); await monitor(page); await page.goto(base); await snapshot(page, 'library-session-picker', width); await choose(page, 'author');
    const baseline = await control('counts'); const projects = await json(context, '/projects'); assert.equal(projects.count, 1); const projectId = projects.items[0].id;
    await snapshot(page, 'scoped-authored-library', width);
    if (width === 1440) { await malformedReviews(context, projectId, width); await nonRetirableResponses(context, projectId, width); }
    await fillCreate(page, projectId); await snapshot(page, 'exact65536byte-authored-editor', width); await lateReviewAndLimit(page, projectId, width);
    const created = await lostCreate(page, projectId, width); const entryId = created.value.result.entryId; const revision1 = created.value.result.revisionId;
    assert.equal(JSON.parse(created.body).text, originalText); assert.equal(created.value.result.status, 'draft'); assert.equal(created.value.result.revision, 1);
    await gotoRecord(page, `/library-entries/${entryId}`); await exactSource(page, 'Exact authored source text', originalText); const entry1 = await json(context, `/library-entries/${entryId}`);
    revisionFacts(entry1.currentRevision, originalText, 1); assert.equal(entry1.revisionCount, 1);
    const textRegion = page.locator('pre[aria-label="Exact authored source text"]'); await textRegion.focus(); await page.keyboard.press('PageDown'); await page.waitForFunction(() => document.querySelector('pre[aria-label="Exact authored source text"]').scrollTop > 0); await textRegion.evaluate(element => { element.scrollTop = 0; });
    report.recoveryChecks.push({ name: 'keyboard focuses and scrolls the bounded exact-text region without executing authored markup', width }); await snapshot(page, 'stored-original-authored-text', width);
    await fillRevision(page, entryId, adoptedText, 'Exact independently reviewed replacement wording'); const revised = await act(page, 'library.revise', entryId, width, true); await retryUI(page, 'library.revise', revised, width);
    const revisionId = revised.value.result.revisionId; assert.notEqual(revisionId, revision1); assert.equal(revised.value.result.revision, 2);
    const entry2 = await json(context, `/library-entries/${entryId}`); revisionFacts(entry2.currentRevision, adoptedText, 2); assert.equal(entry2.revisionCount, 2);
    revisionFacts(entry2.revisions.find(item => item.id === revision1), originalText, 1); assert.equal(entry2.revisions.find(item => item.id === revision1).isCurrent, false);
    await gotoRecord(page, `/library-revisions/${revisionId}`); await exactSource(page, 'Exact authored source text', adoptedText);
    await page.getByRole('textbox', { name: 'Target project locator', exact: true }).fill('Project reference / piping review / internal section 4');
    await page.getByRole('textbox', { name: 'Reference purpose', exact: true }).fill('Internal synthetic design coordination reference; no issue or execution');
    await snapshot(page, 'explicit-project-reference-intent', width); const planned = await act(page, 'library.prepareReference', revisionId, width); await retryUI(page, 'library.prepareReference', planned, width); const planId = planned.value.result.planId;
    await gotoRecord(page, `/reference-plans/${planId}`); await exactSource(page, 'Exact authored source text', adoptedText); const originalPlan = await json(context, `/reference-plans/${planId}`);
    assert.equal(originalPlan.creationStatus, 'prepared'); assert.equal(originalPlan.status, 'prepared'); assert.equal(originalPlan.referenceId, null); assert.equal(originalPlan.revisionId, revisionId); await snapshot(page, 'prepared-intent-is-reference-only', width);
    const requested = await act(page, 'library.requestAdoption', planId, width); await retryUI(page, 'library.requestAdoption', requested, width); const approvalId = requested.value.result.approvalId;
    await gotoRecord(page, `/adoption-approvals/${approvalId}`); await exactSource(page, 'Exact authored source text', adoptedText); await snapshot(page, 'reference-requester-separation', width);
    assert.equal(await page.getByRole('button', { name: steps['library.approveAdoption'][1], exact: true }).count(), 0); assert.equal(await page.getByRole('button', { name: steps['library.approveAdoption'][0], exact: true }).count(), 0, 'Requester must not self-authorize');
    const beforeSelfReview = await control('counts'); const authorSession = await json(context, '/session');
    const selfReviewResponse = await context.request.post(base + prefix + `/adoption-approvals/${approvalId}/approve:preflight`, { headers: { Origin: base, 'Content-Type': 'application/json', 'X-CSRF-Token': authorSession.csrfToken }, data: {} });
    assert.equal(selfReviewResponse.status(), 200, await selfReviewResponse.text()); const selfReview = await selfReviewResponse.json(); assert.equal(selfReview.allowed, false); assert.equal(selfReview.fingerprint, null); assert.ok(selfReview.checks.some(check => check.status === 'blocked')); assert.deepEqual(await control('counts'), beforeSelfReview);
    report.recoveryChecks.push({ name: 'actual author self-authorization preflight is blocked without any effect', width });
    const reviewerContext = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' });
    const reviewerPage = await reviewerContext.newPage(); await monitor(reviewerPage); await reviewerPage.goto(base); await choose(reviewerPage, 'reviewer'); await gotoRecord(reviewerPage, `/adoption-approvals/${approvalId}`);
    await snapshot(reviewerPage, 'independent-actual-project-PM-review', width); const granted = await act(reviewerPage, 'library.approveAdoption', approvalId, width, true); await retryUI(reviewerPage, 'library.approveAdoption', granted, width);
    const grant = await json(reviewerContext, `/adoption-approvals/${approvalId}/packet`); assert.equal(grant.status, 'granted'); assert.equal(grant.authorizationStatus, 'granted'); assert.notEqual(grant.requester.id, grant.reviewer.id); assert.equal(grant.appliedBy, null);
    assert.equal((await control('counts')).library_adoptions, baseline.library_adoptions); await snapshot(reviewerPage, 'independent-grant-creates-no-reference', width);
    await gotoRecord(page, `/adoption-approvals/${approvalId}`); const applied = width === 1440 ? await applyWithAlteredOriginalReplies(page, approvalId, width) : await act(page, 'library.applyAdoption', approvalId, width); await retryUI(page, 'library.applyAdoption', applied, width); const referenceId = applied.value.result.referenceId;
    const reference = await json(context, `/project-references/${referenceId}`); assert.equal(reference.revisionId, revisionId); assert.equal(reference.currentRevisionId, revisionId); assert.equal(reference.sourceCurrent, true); assert.equal(reference.text, adoptedText); assert.equal(reference.contentHash, entry2.currentRevision.contentHash);
    assert.equal(reference.approvalId, approvalId); assert.equal(reference.planId, planId); assert.equal(reference.status, 'adopted_reference'); assert.equal(reference.effectKind, 'project-reference-only/1'); assert.notEqual(reference.requester.id, reference.reviewer.id); assert.equal(reference.requester.id, reference.appliedBy.id); assert.equal(reference.targetLocator, originalPlan.targetLocator); assert.equal(reference.purpose, originalPlan.purpose);
    const consumed = await json(context, `/adoption-approvals/${approvalId}/packet`); assert.equal(consumed.status, 'consumed'); assert.equal(consumed.authorizationStatus, 'consumed'); assert.equal(consumed.plan.creationStatus, 'prepared'); assert.equal(consumed.plan.status, 'adopted_reference');
    await gotoRecord(page, `/project-references/${referenceId}`); await exactSource(page, 'Exact adopted reference text', adoptedText); await snapshot(page, 'one-adopted-project-reference', width);
    for (const route of ['/projects', '/library-entries', '/reference-plans', '/adoption-approvals', '/project-references']) {
      const scoped = await json(context, route); assert.equal(scoped.count, 1); await gotoRecord(page, route); const visibleName = scoped.items[0].title ?? scoped.items[0].name; assert.ok((await page.locator('main').innerText()).includes(visibleName));
      assert.equal((await page.locator('main').innerText()).includes('Hidden synthetic authored clauses project'), false); await snapshot(page, 'scoped-nonempty' + route.replaceAll('/', '-'), width);
    }
    const primaryFinal = await control('counts'); fixedBoundary(baseline, primaryFinal); assert.equal(primaryFinal.library_action_receipts - baseline.library_action_receipts, 6); assert.equal(primaryFinal.library_entries - baseline.library_entries, 1); assert.equal(primaryFinal.library_revisions - baseline.library_revisions, 2); assert.equal(primaryFinal.library_adoptions - baseline.library_adoptions, 1); assert.equal(primaryFinal.library_plans - baseline.library_plans, 1); assert.equal(primaryFinal.approvals - baseline.approvals, 1);
    report.journeys.push({ width, sixActions: true, actualIndependentPMs: true, sameGrantConsumed: true, originalUTF8Bytes: 65536, adoptedUTF8Bytes: 65536, projectReferences: 1 }); report.counters.push({ width, baseline, primaryFinal });
    await fillRevision(page, entryId, laterText, 'Later separate revision after internal adoption'); const later = await act(page, 'library.revise', entryId, width); await retryUI(page, 'library.revise', later, width); assert.equal(later.value.result.revision, 3);
    const originalRevision = await json(context, `/library-revisions/${revisionId}`); revisionFacts(originalRevision, adoptedText, 2); assert.equal(originalRevision.isCurrent, false); assert.equal(originalRevision.currentRevisionId, later.value.result.revisionId);
    const oldReference = await json(context, `/project-references/${referenceId}`); assert.equal(oldReference.text, adoptedText); assert.equal(oldReference.contentHash, reference.contentHash); assert.equal(oldReference.revisionId, revisionId); assert.equal(oldReference.currentRevisionId, later.value.result.revisionId); assert.equal(oldReference.sourceCurrent, false); assert.equal(oldReference.status, 'adopted_reference');
    await gotoRecord(page, `/project-references/${referenceId}`); await exactSource(page, 'Exact adopted reference text', adoptedText); await snapshot(page, 'original-adopted-copy-beside-later-current-revision', width);
    await gotoRecord(page, `/library-revisions/${revisionId}`); await exactSource(page, 'Exact authored source text', adoptedText); assert.equal(await page.getByRole('button', { name: steps['library.prepareReference'][0], exact: true }).count(), 0, 'Historical source cannot prepare a new current reference'); await snapshot(page, 'historical-authored-revision-is-separate', width);
    for (const original of [created, revised, planned, requested, applied, later]) await retryHTTP(context, original, width); await retryHTTP(reviewerContext, granted, width);
    assert.equal((await control('counts')).library_adoptions, primaryFinal.library_adoptions); report.recoveryChecks.push({ name: 'later revision preserves original adopted text/revision/hash and every original action receipt remains exact', width });
    if (width === 1440) await malformedRecords(context, { entryId, revisionId, planId, approvalId, referenceId }, width);
    await reviewerContext.close(); await staleRevisionRecovery(page, entryId, width); await staleRecovery(page, projectId, created, width); await scopeAndIdentity(page, projectId, entryId, width);
    const final = await control('counts'); fixedBoundary(baseline, final);
    for (const [key, delta] of Object.entries({ library_entries: 3, library_revisions: 7, library_heads: 7, library_plans: 1, library_adoptions: 1, library_action_receipts: 9, documents: 3, document_revisions: 7, approvals: 1 })) assert.equal(final[key] - baseline[key], delta, `all genuine flows/${key}`);
    report.counters[report.counters.length - 1].finalAfterRecovery = final;
    report.widths.push(width); await context.close(); await stopServer();
  }
  assert.deepEqual(report.errors, []); assert.deepEqual(report.violations, []);
} catch (error) { report.errors.push({ message: error.stack ?? String(error) }); throw error; }
finally { await browser?.close(); await stopServer(); await writeFile(path.join(artifacts, 'library-smoke.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ views: report.views.length, journeys: report.journeys.length, recoveryDrafts: report.recoveryDrafts.length, recoverySuccessors: report.recoverySuccessors.length, exactRetries: report.exactRetries.length, recoveryChecks: report.recoveryChecks.length, contractChecks: report.contractChecks.length, violations: report.violations.length, errors: report.errors.length }));
