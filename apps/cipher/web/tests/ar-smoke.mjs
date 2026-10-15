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
const port = Number(process.env.CIPHER_AR_PORT ?? 18791);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`;
const prefix = '/api/ar-practice/v1';
const artifacts = process.env.CIPHER_AR_ARTIFACTS ?? '/tmp/cipher-completion/ar-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', widths: [], views: [], journeys: [], recoveryDrafts: [], exactRetries: [], recoveryChecks: [], contractChecks: [], counters: [], errors: [], violations: [],
  axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard traversal remains checked'] };
// These controls exist only on the disposable test process stdin. The browser
// receives the fixed AR API; no testing effects or financial override routes.
const fixtureControl = `
import json, sys
from threading import Thread
from apps.cipher.ar_practice_server import make_ar_practice_server
from apps.cipher.ar_practice_fixture import PM_LOGIN, BOOTSTRAP_LOGIN
server = make_ar_practice_server(port=int(sys.argv[1]))
def controls():
    for command in sys.stdin:
        with server.cipher_lock, server.cipher.db._lock:
            c = server.cipher
            if command == "counts\\n":
                tables = ("owner_billing_bases", "owner_billing_sources", "owner_billing_grants", "owner_billing_postings", "ar_action_receipts", "prime_bills", "prime_bill_sends", "approvals", "audit_log", "journals", "bills", "outbox", "payment_intents", "collections")
                result = {table: c.db.scalar("SELECT COUNT(*) FROM " + table) for table in tables}
                result.update(arBalanceCents=int(c.ledger.balance("1100")*100), retainedArCents=int(c.ledger.balance("1150")*100), nativeSubmissions=len(c.provider.submissions), nativeTransfers=len(c.provider.transfers))
            elif command == "last_bill_state\\n":
                row = c.db.one("SELECT prime_bill_id FROM owner_billing_sources ORDER BY rowid DESC LIMIT 1")
                if row is None:
                    result = None
                else:
                    bill_id = row["prime_bill_id"]
                    bill = c.receivables.get(bill_id)
                    posting = c.plugin("owner_billing").posting_receipt(bill_id)
                    result = {"billId":bill_id, "status":bill["status"], "journalId":bill["journal_id"], "approvalId":bill["approval_id"], "invoiceDate":bill["invoice_date"], "dueDate":bill["due_date"], "posting":None}
                    if posting:
                        result["posting"] = {"approvalId":posting["approval_id"], "reviewerPersonId":c.plugin("owner_billing").grant_proof(bill_id,approval_id=posting["approval_id"])["record"]["reviewerPersonId"], "posterPersonId":posting["posterPersonId"], "period":posting["period"], "journal":posting["journal"]}
                    sends = c.db.query("SELECT id,approval_id,channel,recipients_json FROM prime_bill_sends WHERE prime_bill_id=?",(bill_id,))
                    result["sends"] = [{"id":s["id"],"approvalId":s["approval_id"],"channel":s["channel"],"recipients":json.loads(s["recipients_json"])} for s in sends]
            elif command == "advance_review_revision\\n":
                revision = c.evidence.revision(c.ar_practice_records["review_revision_id"])
                c.evidence.add_revision(document_id=revision["document_id"], content="Synthetic genuinely later reviewed owner progress", note="Owned later certification for stale-source browser control", actor=PM_LOGIN)
                result = {"reviewAdvanced":True}
            elif command == "expire_sessions\\n":
                from apps.cipher.ar_sessions import IDLE_SECONDS
                original_clock = server.sessions.clock
                server.sessions.clock = lambda: original_clock()+IDLE_SECONDS+1
                result = {"sessionsExpired":True}
            elif command == "end_preparer_membership\\n":
                c.plugin("people").end_membership(PM_LOGIN,c.ar_practice_records["project_id"],reason="Synthetic AR browser current-duty control",actor=BOOTSTRAP_LOGIN)
                result = {"membershipEnded":True}
            else:
                raise ValueError("Unsupported bounded AR test control")
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
    if (server.exitCode !== null) throw new Error(`The AR server exited (${server.exitCode}): ${diagnostics}`);
    try { if ((await fetch(base)).ok) return; } catch { /* Wait for the owned local server. */ }
    await delay(100);
  }
  throw new Error(`The AR server did not become ready: ${diagnostics}`);
}
async function control(command) { const result = once(serverLines, 'line', { signal: AbortSignal.timeout(10000) }); server.stdin.write(command + '\n'); return JSON.parse((await result)[0]); }
async function stopServer() { if (!server || server.exitCode !== null) return; const result = once(server, 'exit'); server.kill('SIGTERM'); await result; serverLines.close(); server = undefined; }
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json(); assert.equal(value.contractVersion, 'cipher.ar-practice.v1'); assert.equal(value.mode, 'practice'); assert.equal(value.synthetic, true); return value;
}
async function settled(page) {
  const idle = () => {
    const main = document.querySelector('main');
    return !!main && main.getAttribute('aria-busy') !== 'true' && !main.querySelector('[role="progressbar"], [data-action][aria-busy="true"]');
  };
  await page.waitForFunction(idle);
  for (let attempt = 0; attempt < 400 && pendingReads.get(page)?.size; attempt++) await delay(25);
  if (pendingReads.get(page)?.size) await writeFile(path.join(artifacts, 'pending-scoped-reads.json'), JSON.stringify({ page: page.url(), pending: [...pendingReads.get(page)].map(request => ({ id: readIds.get(page).get(request), method: request.method(), url: request.url() })), events: readEvents.get(page) }, null, 2) + '\n');
  assert.equal(pendingReads.get(page)?.size ?? 0, 0, 'The AR view still has a pending scoped read; see pending-scoped-reads.json.');
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
async function choose(page, persona) {
  if (await page.getByRole('button', { name: 'Change practice person', exact: true }).count()) await page.getByRole('button', { name: 'Change practice person', exact: true }).click();
  await page.getByRole('heading', { name: 'Start an AR practice session', exact: true }).waitFor();
  const personas = await json(page.context(), '/personas'); const person = personas.value.find(item => item.personaId === persona); assert.ok(person);
  await page.getByRole('button', { name: `Start as ${person.displayName}`, exact: true }).click();
  await page.getByRole('heading', { name: /^Owner bills \(\d+\)$/ }).waitFor(); await settled(page);
}
const steps = {
  'ownerBill.prepare': ['Review owner pay app', 'Prepare owner bill', 'owner-bases', 'prepare-bill'],
  'ownerBill.requestApproval': ['Review owner bill request', 'Request owner bill approval', 'owner-bills', 'request-approval'],
  'ownerBill.approve': ['Review owner bill approval', 'Approve owner bill', 'owner-bill-approvals', 'approve'],
  'ownerBill.post': ['Review owner bill posting', 'Post owner bill', 'owner-bills', 'post'],
  'ownerBill.requestSend': ['Review owner send request', 'Request owner send approval', 'owner-bills', 'request-send'],
  'ownerBill.approveSend': ['Review owner send approval', 'Approve synthetic owner send', 'owner-send-approvals', 'approve'],
  'ownerBill.send': ['Review synthetic send', 'Send to practice mail sink', 'owner-send-approvals', 'send'],
};
async function actionResponse(page, route, click, status = 200) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === prefix + route && response.request().method() === 'POST');
  await click(); const response = await pending; assert.equal(response.status(), status, `${route}: ${await response.text()}`);
  return { value: await response.json(), key: response.request().headers()['repeatability-request-id'], version: response.request().headers()['if-match'], body: response.request().postData(), route };
}
function fixedBoundary(before, after) { for (const key of ['bills', 'outbox', 'payment_intents', 'collections', 'nativeSubmissions', 'nativeTransfers']) assert.equal(after[key], before[key], key); }
function noPosting(before, after) { fixedBoundary(before, after); for (const key of ['journals', 'arBalanceCents', 'retainedArCents', 'owner_billing_postings']) assert.equal(after[key], before[key], key); }
async function applyClick(page, panel, action) {
  await panel.getByRole('button', { name: steps[action][1], exact: true }).click();
  if (action === 'ownerBill.post') await page.getByRole('dialog').getByRole('button', { name: 'Post to October 2026', exact: true }).click();
  if (action === 'ownerBill.send') await page.getByRole('dialog').getByRole('button', { name: 'Send synthetic owner bill', exact: true }).click();
}
async function act(page, action, resource, width, keyboard = false) {
  const [review, apply, collection, command] = steps[action]; const panel = page.locator(`[data-action="${action}"]`); const before = await control('counts');
  if (keyboard) { await panel.getByRole('button', { name: review, exact: true }).focus(); await page.keyboard.press('Enter'); }
  else await panel.getByRole('button', { name: review, exact: true }).click();
  await panel.getByRole('button', { name: apply, exact: true }).waitFor(); assert.deepEqual(await control('counts'), before, `${action} preflight must be pure.`);
  if (action === 'ownerBill.post' || action === 'ownerBill.send') {
    await panel.getByRole('button', { name: apply, exact: true }).click(); const dialog = page.getByRole('dialog');
    const cancel = dialog.getByRole('button', { name: action === 'ownerBill.post' ? "Don't post" : "Don't send", exact: true });
    await cancel.waitFor(); await page.waitForFunction(label => document.activeElement?.textContent === label, action === 'ownerBill.post' ? "Don't post" : "Don't send"); await modalSnapshot(page, `${action}-safe-confirmation`, width); assert.deepEqual(await control('counts'), before); await cancel.click(); await dialog.waitFor({ state: 'hidden' });
    assert.deepEqual(await control('counts'), before); assert.equal(await panel.getByRole('button', { name: apply, exact: true }).evaluate(button => button === document.activeElement), true);
    await panel.getByRole('button', { name: apply, exact: true }).focus(); await page.keyboard.press('Enter'); await dialog.waitFor();
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' }); assert.deepEqual(await control('counts'), before);
    report.recoveryChecks.push({ name: `${action} cancel and Escape leave original financial state unchanged`, width });
  }
  const first = await actionResponse(page, `/${collection}/${resource}/${command}`, () => applyClick(page, panel, action));
  assert.equal(first.value.result.action, action); assert.equal(first.value.effectApplied, true); assert.equal(first.value.replayed, false);
  assert.equal(first.value.result.providerCallsDelta, 0); assert.match(first.key, /^[0-9a-f-]{36}$/); assert.match(first.version, /^"[^\"]+"$/);
  const after = await control('counts'); fixedBoundary(before, after);
  if (action === 'ownerBill.post') { assert.equal(after.journals-before.journals, 1); assert.equal(after.arBalanceCents-before.arBalanceCents, 2025000); assert.equal(after.retainedArCents-before.retainedArCents, 225000); }
  else noPosting(before, after);
  if (action === 'ownerBill.send') assert.equal(after.prime_bill_sends-before.prime_bill_sends, 1); else assert.equal(after.prime_bill_sends, before.prime_bill_sends);
  return first;
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
async function fillPreparation(page, basisId) {
  await page.goto(base + `/owner-bases/${basisId}/preparation`);
  let admitted = false;
  await Promise.race([page.getByRole('combobox', { name: 'Claimed progress document', exact: true }).waitFor(), page.getByRole('alert').waitFor().then(async () => { if (admitted) return; await page.screenshot({ path: path.join(artifacts, 'preparation-refused.png'), fullPage: true }); throw new Error('Preparation refused: ' + await page.locator('main').innerText()); })]); admitted = true;
  // IDs come from owned scoped DTOs, never DOM-hidden fixture identifiers.
  for (const label of ['Claimed progress document', 'Reviewed progress document', 'Owner billing period']) {
    const select = page.getByRole('combobox', { name: label, exact: true });
    const value = await select.locator('option').evaluateAll(options => options.find(option => option.value && !option.disabled)?.value);
    assert.ok(value, `No owned choice for ${label}`); await select.selectOption(value);
  }
  for (const [lineId, claimed, reviewed, reason] of [['U1', '12', '10', 'Two claimed units await independent installation verification'], ['L2', '15000', '12500', 'Reviewed dewatering excludes unverified claimed activity']]) {
    for (const [label, value] of [['Claimed cumulative', claimed], ['Reviewed cumulative', reviewed], ['Difference reason', reason], ['Claim source locator', `Claim cover sheet / ${lineId}`], ['Review source locator', `PM review worksheet / ${lineId}`]]) await page.getByRole('textbox', { name: `${label} for owner line ${lineId}`, exact: true }).fill(value);
  }
}
async function fractionalReview(page, basisId, width) {
  const before = await control('counts'); const panel = page.locator('[data-action="ownerBill.prepare"]');
  await page.getByRole('textbox', { name: 'Claimed cumulative for owner line U1', exact: true }).fill('12.345678');
  await page.getByRole('textbox', { name: 'Reviewed cumulative for owner line U1', exact: true }).fill('10.125001');
  const reviewed = await actionResponse(page, `/owner-bases/${basisId}/prepare-bill:preflight`, () => panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click());
  assert.equal(reviewed.value.allowed, true); const calculation = reviewed.value.preview.calculation; const line = calculation.lines.find(item => item.lineId === 'U1');
  assert.equal(line.claimedQuantity, '12.345678'); assert.equal(line.reviewedQuantity, '10.125001'); assert.equal(line.claimedAmountCents, 1234568); assert.equal(line.reviewedAmountCents, 1012500);
  assert.equal(calculation.reviewedCertifiedCents, 2262500); assert.equal(calculation.retainageThisPeriodCents, 226250); assert.equal(calculation.amountDueCents, 2036250);
  await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).waitFor();
  assert.ok((await panel.innerText()).includes('12.345678')); assert.ok((await panel.innerText()).includes('10.125001')); assert.deepEqual(await control('counts'), before);
  await snapshot(page, 'six-place-exact-source-server-cent-rounding', width);
  await page.getByRole('textbox', { name: 'Claimed cumulative for owner line U1', exact: true }).fill('12');
  await page.getByRole('textbox', { name: 'Reviewed cumulative for owner line U1', exact: true }).fill('10');
  assert.equal(await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).count(), 0);
  report.contractChecks.push({ name: 'six-place claimed and reviewed source remains exact with server-rounded cents', width });
}
async function lateReview(page, basisId, width) {
  const panel = page.locator('[data-action="ownerBill.prepare"]'); const match = `**${prefix}/owner-bases/${basisId}/prepare-bill:preflight`; const before = await control('counts');
  let release, ready; const gate = new Promise(resolve => { release = resolve; }); const received = new Promise(resolve => { ready = resolve; });
  const intercept = async route => { const actual = await route.fetch(); ready(); await gate; await route.fulfill({ response: actual }); };
  await page.route(match, intercept); await panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click(); await received;
  await page.getByRole('textbox', { name: 'Claimed cumulative for owner line U1', exact: true }).fill('13'); release();
  await page.getByText(/facts changed while.*review.*loading/i).waitFor(); assert.equal(await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).count(), 0);
  assert.equal(await panel.getByRole('table').count(), 0); assert.deepEqual(await control('counts'), before);
  await snapshot(page, 'late-original-review-discarded', width); await page.unroute(match, intercept);
  await page.getByRole('textbox', { name: 'Claimed cumulative for owner line U1', exact: true }).fill('12'); report.recoveryChecks.push({ name: 'late old-input review discarded', width });
}
async function lostPreparedResponse(page, basisId, width) {
  const panel = page.locator('[data-action="ownerBill.prepare"]'); const routePath = `/owner-bases/${basisId}/prepare-bill`; const before = await control('counts');
  await panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).waitFor();
  let original, dropped = false; expectedTransport.get(page).add(prefix + routePath);
  const intercept = async route => { if (dropped) return route.continue(); dropped = true; const actual = await route.fetch(); assert.equal(actual.status(), 200); original = { value: await actual.json(), key: route.request().headers()['repeatability-request-id'], version: route.request().headers()['if-match'], body: route.request().postData(), route: routePath }; await route.abort('failed'); };
  await page.route(`**${prefix}${routePath}`, intercept); await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).click(); await panel.getByRole('alert').waitFor();
  assert.ok(original); assert.equal((await control('counts')).prime_bills-before.prime_bills, 1); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
  await page.unroute(`**${prefix}${routePath}`, intercept); expectedTransport.get(page).delete(prefix + routePath);
  const input = page.getByRole('textbox', { name: 'Claimed cumulative for owner line U1', exact: true }); await input.fill('12.000000'); await input.fill('12'); await input.fill('13');
  assert.equal(await panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).count(), 0);
  assert.equal(await panel.getByRole('button', { name: 'Review edited owner source', exact: true }).count(), 0);
  await snapshot(page, 'lost-preparation-retains-original-request', width); await retryUI(page, 'ownerBill.prepare', original, width);
  const currentPreparation = await json(page.context(), `/owner-bases/${basisId}/preparation`);
  if (currentPreparation.availableActions.includes('ownerBill.prepare')) await panel.getByRole('button', { name: 'Review edited owner source', exact: true }).waitFor();
  else { assert.equal(await panel.getByRole('button', { name: 'Review edited owner source', exact: true }).count(), 0); assert.equal((await json(page.context(), `/owner-bills/${original.value.result.billId}`)).status, 'draft'); }
  assert.equal(await input.inputValue(), '13');
  await panel.getByRole('link', { name: 'Open prepared owner bill', exact: true }).click(); await page.getByRole('table', { name: 'Claimed and reviewed owner SOV progress', exact: true }).waitFor(); await page.goBack();
  assert.equal(await input.inputValue(), '12'); await retryUI(page, 'ownerBill.prepare', original, width);
  assert.equal((await control('counts')).prime_bills-before.prime_bills, 1); report.recoveryChecks.push({ name: 'lost preparation outcome and edited-input exact retry recover original receipt once', width }); return original;
}
function sourceFacts(bill, originalBody) {
  assert.equal(bill.claimSource.revisionId, originalBody.claimRevisionId); assert.equal(bill.reviewSource.revisionId, originalBody.reviewRevisionId);
  assert.notEqual(bill.claimSource.documentId, bill.reviewSource.documentId); assert.notEqual(bill.claimSource.revisionId, bill.reviewSource.revisionId);
  assert.equal(bill.certificationPeriod.id, originalBody.periodId); assert.equal(bill.lines.length, 2);
  for (const line of bill.lines) {
    const original = originalBody.lines.find(item => item.lineId === line.lineId); assert.ok(original);
    assert.equal(line.differenceReason, original.differenceReason); assert.equal(line.claimSourceLocator, original.claimSourceLocator); assert.equal(line.reviewSourceLocator, original.reviewSourceLocator);
    assert.notEqual(line.claimSourceLocator, line.reviewSourceLocator);
    if (line.lineId === 'U1') { assert.equal(line.claimedQuantity, '12'); assert.equal(line.reviewedQuantity, '10'); assert.equal(line.claimedAmountCents, 1200000); assert.equal(line.reviewedAmountCents, 1000000); assert.equal(line.differenceAmountCents, -200000); }
    else { assert.equal(line.lineId, 'L2'); assert.equal(line.claimedQuantity, null); assert.equal(line.reviewedQuantity, null); assert.equal(line.claimedAmountCents, 1500000); assert.equal(line.reviewedAmountCents, 1250000); assert.equal(line.differenceAmountCents, -250000); }
  }
  assert.equal(bill.totals.claimedCertifiedCents, 2700000); assert.equal(bill.totals.reviewedCertifiedCents, 2250000); assert.equal(bill.totals.amountDueCents, 2025000); assert.equal(bill.totals.retainageThisPeriodCents, 225000);
}
async function aging(page, billId, width) {
  const before = await control('counts');
  for (const [route, table, amount] of [['ar-aging', 'Current receivables aged at selected date', 2025000], ['retainage-aging', 'Current retained receivables aged at selected date', 225000]]) {
    await gotoRecord(page, '/' + route); await page.getByRole('table', { name: table, exact: true }).waitFor();
    for (const asOf of ['2026-09-30', '2026-12-31']) {
      const refreshed = page.waitForResponse(response => { const url = new URL(response.url()); return response.request().method() === 'GET' && url.pathname === prefix + '/' + route && url.searchParams.get('asOf') === asOf; });
      await page.getByLabel('Age date', { exact: true }).fill(asOf); const renderedResponse = await refreshed; assert.equal(renderedResponse.status(), 200);
      const value = await json(page.context(), `/${route}?asOf=${asOf}`);
      assert.equal(value.balanceBasis, 'current_standing_balance'); assert.equal(value.historicalSnapshot, false); assert.equal(value.agingAsOf, asOf);
      assert.equal(value.workingLedger, true); assert.equal(value.watermark, 'Working ledger, not for issue'); assert.equal(value.scope, 'owner_billing');
      assert.equal(value.items.length, 1); assert.equal(value.items[0].currentOpenCents, amount);
      if (route === 'ar-aging') { assert.equal(value.items[0].billId, billId); assert.equal(value.items[0].invoiceDate, '2026-10-01'); assert.equal(value.items[0].dueDate, '2026-10-31'); assert.equal(value.items[0].daysPastDue, asOf === '2026-09-30' ? 0 : 61); assert.equal(value.items[0].agingBucket, asOf === '2026-09-30' ? 'current' : '61_90'); }
      else { assert.deepEqual(value.items[0].billIds, [billId]); assert.equal(value.items[0].retainedCents, 225000); assert.equal(value.items[0].releasedCents, 0); assert.equal(value.items[0].agingBucket, 'unreleased'); assert.equal(value.items[0].dueDate, null); assert.equal(value.items[0].daysPastDue, null); }
      assert.equal(value.reconciliation.scope, 'authorized_projects');
      assert.equal(value.reconciliation.subledgerCents, amount); assert.equal(value.reconciliation.controlCents, amount); assert.equal(value.reconciliation.reconciled, true);
      await page.getByRole('table', { name: table, exact: true }).waitFor(); await snapshot(page, `${route}-${asOf}`, width);
    }
  }
  assert.deepEqual(await control('counts'), before); report.recoveryChecks.push({ name: 'aging uses current standing balances even when age date precedes original invoice', width });
}
async function malformedReviews(context, basisId, width) {
  const before = await control('counts');
  const cases = [
    ['balanced source journal with wrong server amounts', value => { const lines = value.preview.calculation.journalPreview; value.preview.calculation.journalPreview = [{ ...lines.find(line => line.accountCode === '1100'), debitCents: 1, creditCents: 0 }, { ...lines.find(line => line.accountCode === '4000'), debitCents: 0, creditCents: 1 }]; }],
    ['empty positive source journal preview', value => { value.preview.calculation.journalPreview = []; }],
    ['wrong prospective draft effect', value => { value.safeEffects.createsDraft = false; }],
    ['unexpected prospective journal', value => { value.safeEffects.workingLedgerJournalDelta = 1; }],
    ['external delivery claim', value => { value.safeEffects.externalDelivery = true; }],
    ['changed reviewed quantity', value => { value.preview.calculation.lines[0].reviewedQuantity = '11'; }],
    ['missing exact priced preview', value => { delete value.preview; }],
  ];
  for (const [name, mutate] of cases) {
    const page = await context.newPage(); await monitor(page); await fillPreparation(page, basisId);
    await page.route(`**${prefix}/owner-bases/${basisId}/prepare-bill:preflight`, async route => { const actual = await route.fetch(); const value = await actual.json(); assert.equal(value.allowed, true); mutate(value); await route.fulfill({ response: actual, json: value }); });
    const panel = page.locator('[data-action="ownerBill.prepare"]'); await panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click();
    await Promise.race([panel.getByRole('alert').waitFor(), panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).waitFor().then(() => { throw new Error('Malformed preflight was admitted: ' + name); })]); assert.equal(await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).count(), 0); assert.equal(await panel.getByRole('table').count(), 0);
    report.contractChecks.push({ name, width }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function nonRetirableResponses(context, basisId, width) {
  const before = await control('counts');
  const cases = [
    ['server action unavailable keeps original request', 500, 'action_unavailable', {}],
    ['unknown412 integrity hold keeps original request', 412, 'owner_integrity_hold', {}],
    ['incomplete refusal receipt metadata is rejected', 412, 'owner_source_changed', { receiptId: 'arreceipt_incomplete' }],
    ['positive effect in refusal receipt is rejected', 412, 'record_changed', { receiptId: 'arreceipt_impossible', replayed: false, effectApplied: true }],
  ];
  for (const [name, status, code, receipt] of cases) {
    const page = await context.newPage(); await monitor(page); await fillPreparation(page, basisId); const panel = page.locator('[data-action="ownerBill.prepare"]');
    await panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).waitFor();
    const routePath = `/owner-bases/${basisId}/prepare-bill`; expectedFailures.get(page).add(prefix + routePath);
    // Response-only fault: never forward this effect request to the server.
    await page.route(`**${prefix}${routePath}`, route => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ contractVersion: 'cipher.ar-practice.v1', mode: 'practice', synthetic: true, currency: 'USD', ...receipt, error: { code, message: 'Synthetic bounded response-only fault', target: 'basis', fix: null, details: null } }) }));
    await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).click(); await panel.getByRole('alert').waitFor(); await settled(page);
    assert.equal(await panel.getByRole('button', { name: 'Retry same action', exact: true }).count(), 1); assert.equal(await panel.getByRole('button', { name: 'Start a new current review', exact: true }).count(), 0);
    if (Object.keys(receipt).length) assert.match(await panel.getByRole('alert').innerText(), /incomplete or unsupported record/);
    assert.deepEqual(await control('counts'), before); report.contractChecks.push({ name, width, responseOnly: true }); await page.close();
  }
}
async function malformedRecords(context, billId, width) {
  const before = await control('counts');
  const cases = [
    ['draft state beside standing original posting', value => { value.status = 'draft'; value.effectiveStatus = 'draft'; }],
    ['pending business authorization beside standing posting', value => { value.businessApproval.authorizationStatus = 'pending'; }],
    ['balanced original posting with wrong server amounts', value => { const rows = value.posting.journalPreview; value.posting.journalPreview = [{ ...rows.find(line => line.accountCode === '1100'), debitCents: 1, creditCents: 0 }, { ...rows.find(line => line.accountCode === '4000'), debitCents: 0, creditCents: 1 }]; }],
    ['numeric claimed quantity', value => { value.lines[0].claimedQuantity = 12; }],
    ['unexplained exact quantity difference below cent rounding', value => { const line = value.lines.find(item => item.lineId === 'U1'); line.claimedQuantity = '10.000001'; line.reviewedQuantity = '10'; line.claimedAmountCents = line.reviewedAmountCents; line.differenceAmountCents = 0; line.differenceReason = ''; }],
    ['boolean cent amount', value => { value.totals.currentOpenCents = false; }],
    ['unsafe integer amount', value => { value.lines[0].reviewedAmountCents = Number.MAX_SAFE_INTEGER + 1; }],
    ['private proof disclosure', value => { value.sourceProof = {}; }],
    ['external settlement claim', value => { value.externalSettlement = true; }],
    ['foreign related workspace', value => { value.relatedRecords[0].apiRoute = '/api/ap-practice/v1/owner-bills/foreign'; }],
  ];
  for (const [name, mutate] of cases) for (const refresh of [false, true]) {
    const page = await context.newPage(); await monitor(page);
    if (refresh) { await gotoRecord(page, `/owner-bills/${billId}`); await page.getByRole('table').first().waitFor(); }
    await page.route(`**${prefix}/owner-bills/${billId}`, async route => { const actual = await route.fetch(); const value = await actual.json(); mutate(value); await route.fulfill({ response: actual, json: value }); });
    if (refresh) await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); else await gotoRecord(page, `/owner-bills/${billId}`);
    await page.getByRole('alert').waitFor(); assert.equal(await page.getByRole('table').count(), 0); assert.equal(await page.locator('[data-action]').count(), 0);
    report.contractChecks.push({ name, width, refreshAfterVerifiedRead: refresh }); await page.close();
  }
  assert.deepEqual(await control('counts'), before);
}
async function staleAndIdentity(page, basisId, billId, prepared, width) {
  await fillPreparation(page, basisId);
  await page.getByRole('textbox', { name: 'Reviewed cumulative for owner line U1', exact: true }).fill('11');
  await page.getByRole('textbox', { name: 'Reviewed cumulative for owner line L2', exact: true }).fill('13000');
  const panel = page.locator('[data-action="ownerBill.prepare"]');
  await panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click(); await panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).waitFor();
  await control('advance_review_revision'); const afterSource = await control('counts'); const route = `/owner-bases/${basisId}/prepare-bill`; expectedFailures.get(page).add(prefix + route);
  const refused = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).click(), 412); assert.equal(refused.value.error.code, 'owner_source_changed');
  await panel.getByRole('alert').waitFor(); assert.deepEqual(await control('counts'), afterSource);
  const repeated = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry same action', exact: true }).click(), 412); assert.equal(repeated.value.error.code, 'owner_source_changed');
  assert.equal(repeated.key, refused.key); assert.equal(repeated.body, refused.body); assert.equal(repeated.version, refused.version); assert.deepEqual(await control('counts'), afterSource);
  await snapshot(page, 'genuine-later-review-source-refuses-stale-effect', width);
  const currentPreparation = await json(page.context(), `/owner-bases/${basisId}/preparation`);
  const nextReviewSource = currentPreparation.reviewSources.find(source => source.revisionId !== JSON.parse(refused.body).reviewRevisionId); assert.ok(nextReviewSource);
  await page.getByRole('combobox', { name: 'Reviewed progress document', exact: true }).selectOption(nextReviewSource.revisionId); await settled(page);
  const restart = panel.getByRole('button', { name: 'Start a new current review', exact: true });
  assert.equal(await restart.count(), 1, 'A definitive412 refusal must allow explicit review of the newly selected current source.');
  await restart.click(); const beforeFreshReview = await control('counts');
  const freshReview = await actionResponse(page, route + ':preflight', () => panel.getByRole('button', { name: steps['ownerBill.prepare'][0], exact: true }).click());
  assert.equal(freshReview.value.allowed, true); assert.deepEqual(await control('counts'), beforeFreshReview);
  const nextDraft = await actionResponse(page, route, () => panel.getByRole('button', { name: steps['ownerBill.prepare'][1], exact: true }).click());
  assert.notEqual(nextDraft.key, refused.key); assert.notEqual(nextDraft.value.result.billId, billId); assert.equal(nextDraft.value.result.status, 'draft'); assert.equal(nextDraft.value.result.amountDueCents, 135000);
  const afterFresh = await control('counts'); noPosting(beforeFreshReview, afterFresh); assert.equal(afterFresh.prime_bills-beforeFreshReview.prime_bills, 1); report.recoveryDrafts.push({ width, billId: nextDraft.value.result.billId, repeatabilityId: nextDraft.key, refusedRepeatabilityId: refused.key, amountDueCents: nextDraft.value.result.amountDueCents, journalDelta: afterFresh.journals-beforeFreshReview.journals, sendDelta: afterFresh.prime_bill_sends-beforeFreshReview.prime_bill_sends, before: beforeFreshReview, after: afterFresh });
  await retryUI(page, 'ownerBill.prepare', nextDraft, width);
  const beforeHistoryRetry = await control('counts');
  const historyDetails = panel.locator('details').filter({ hasText: 'Original refusal' }); if (await historyDetails.getAttribute('open') === null) await historyDetails.locator('summary').click(); assert.ok((await historyDetails.innerText()).includes('owner_source_changed'), 'The retired refusal keeps its original bounded code available in technical details.');
  const oldRefusal = await actionResponse(page, route, () => panel.getByRole('button', { name: 'Retry refused request', exact: true }).click(), 412);
  assert.equal(oldRefusal.key, refused.key); assert.equal(oldRefusal.body, refused.body); assert.equal(oldRefusal.version, refused.version); assert.equal(oldRefusal.value.error.code, refused.value.error.code); assert.equal(oldRefusal.value.receiptId, refused.value.receiptId); assert.deepEqual(await control('counts'), beforeHistoryRetry);
  report.exactRetries.push({ action: 'ownerBill.prepare', width, refusedHistoricalRequest: true, key: oldRefusal.key });
  await snapshot(page, 'definitive-refusal-retires-only-by-explicit-current-review', width);
  await retryHTTP(page.context(), prepared, width);
  report.recoveryChecks.push({ name: 'definitive412 preserves original refusal and explicitly starts a new current review/new UUID without extra posting', width });
  report.recoveryChecks.push({ name: 'genuine later review source refuses stale preparation while completed original receipt remains historical', width });
  await gotoRecord(page, `/owner-bills/${billId}`); await page.getByRole('table').first().waitFor();
  for (const path of ['/session', '/projects', `/owner-bills/${billId}`]) expectedFailures.get(page).add(prefix + path);
  await control('expire_sessions'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click();
  await page.getByRole('heading', { name: 'Start an AR practice session', exact: true }).waitFor(); assert.equal(await page.getByRole('table').count(), 0); assert.equal(await page.locator('[data-action]').count(), 0); await snapshot(page, 'expired-ar-session-clears-facts', width);
  await choose(page, 'preparer'); await gotoRecord(page, `/owner-bills/${billId}`); await page.getByRole('table').first().waitFor();
  await control('end_preparer_membership'); await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click(); await page.getByRole('alert').first().waitFor();
  await page.waitForFunction(() => document.querySelectorAll('main table, main [data-action]').length === 0); await snapshot(page, 'actual-ar-duty-loss-clears-facts', width);
  report.recoveryChecks.push({ name: 'expired session and genuine project membership loss clear source facts and actions', width });
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

try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of (process.env.CIPHER_AR_WIDTHS ? process.env.CIPHER_AR_WIDTHS.split(',').map(Number) : [1440, 1024, 390])) {
    await startServer(); const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' });
    const page = await context.newPage(); await monitor(page); await page.goto(base); await snapshot(page, 'ar-session-picker', width); await choose(page, 'preparer');
    const baseline = await control('counts'); const bases = await json(context, '/owner-bases'); assert.equal(bases.count, 1); const basisId = bases.items[0].id;
    await snapshot(page, 'ar-scoped-owner-bills', width); if (width === 1440) { await malformedReviews(context, basisId, width); await nonRetirableResponses(context, basisId, width); } await fillPreparation(page, basisId); await snapshot(page, 'claimed-and-reviewed-manual-source', width); await fractionalReview(page, basisId, width); await lateReview(page, basisId, width);
    const prepared = await lostPreparedResponse(page, basisId, width); const billId = prepared.value.result.billId;
    assert.equal(prepared.value.result.reviewedCertifiedCents, 2250000); assert.equal(prepared.value.result.amountDueCents, 2025000);
    await page.getByRole('link', { name: 'Open prepared owner bill', exact: true }).click(); await page.getByRole('table', { name: 'Claimed and reviewed owner SOV progress', exact: true }).waitFor(); await snapshot(page, 'prepared-owner-bill', width); sourceFacts(await json(context, `/owner-bills/${billId}`), JSON.parse(prepared.body));
    const requested = await act(page, 'ownerBill.requestApproval', billId, width); await retryUI(page, 'ownerBill.requestApproval', requested, width); const approvalId = requested.value.result.approvalId;
    await page.getByRole('link', { name: 'Open owner bill approval', exact: true }).click(); await settled(page); await snapshot(page, 'requester-separation', width);
    assert.equal(await page.getByRole('button', { name: 'Approve owner bill', exact: true }).count(), 0);
    await choose(page, 'reviewer'); await gotoRecord(page, `/owner-bill-approvals/${approvalId}`); await snapshot(page, 'independent-owner-bill-review', width);
    const granted = await act(page, 'ownerBill.approve', approvalId, width); await retryUI(page, 'ownerBill.approve', granted, width);
    const grantedState = await control('last_bill_state'); assert.equal(grantedState.status, 'draft'); assert.equal(grantedState.journalId, null); assert.equal((await control('counts')).journals, baseline.journals);
    await gotoRecord(page, `/owner-bills/${billId}`); assert.equal(await page.getByRole('button', { name: 'Post owner bill', exact: true }).count(), 0); await snapshot(page, 'grant-is-journal-free', width);
    await choose(page, 'poster'); await gotoRecord(page, `/owner-bills/${billId}`); const posted = await act(page, 'ownerBill.post', billId, width); await retryUI(page, 'ownerBill.post', posted, width);
    const postedState = await control('last_bill_state'); assert.equal(postedState.posting.approvalId, approvalId); assert.notEqual(postedState.posting.reviewerPersonId, postedState.posting.posterPersonId); assert.equal(postedState.journalId, posted.value.result.journalId);
    assert.equal(postedState.posting.period.id, '2026-10'); assert.equal(postedState.posting.journal.header.period_id, '2026-10');
    assert.deepEqual(postedState.posting.journal.lines.map(line => ({ account: line.account_code, debit: line.debit, credit: line.credit })), [
      { account: '1100', debit: '20250.00', credit: '0.00' }, { account: '1150', debit: '2250.00', credit: '0.00' }, { account: '4000', debit: '0.00', credit: '22500.00' },
    ]);
    assert.equal(postedState.invoiceDate, '2026-10-01'); assert.equal(postedState.dueDate, '2026-10-31'); await snapshot(page, 'separate-accountant-posting', width);
    const sendContext = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024, reducedMotion: 'reduce', timezoneId: 'America/New_York' });
    const sendPage = await sendContext.newPage(); await monitor(sendPage); await sendPage.goto(base);
    await choose(sendPage, 'preparer'); await gotoRecord(sendPage, `/owner-bills/${billId}/send-preparation`); await snapshot(sendPage, 'fixed-owner-mail-sink-review', width);
    const sendRequested = await act(sendPage, 'ownerBill.requestSend', billId, width); await retryUI(sendPage, 'ownerBill.requestSend', sendRequested, width); const sendApprovalId = sendRequested.value.result.approvalId;
    await sendPage.getByRole('link', { name: 'Open owner send approval', exact: true }).click(); await settled(sendPage); assert.equal(await sendPage.getByRole('button', { name: 'Approve synthetic owner send', exact: true }).count(), 0); await snapshot(sendPage, 'send-requester-separation', width);
    await choose(sendPage, 'reviewer'); await gotoRecord(sendPage, `/owner-send-approvals/${sendApprovalId}`); const sendGranted = await act(sendPage, 'ownerBill.approveSend', sendApprovalId, width); await retryUI(sendPage, 'ownerBill.approveSend', sendGranted, width); await snapshot(sendPage, 'send-authorization-is-separate', width);
    await choose(sendPage, 'preparer'); await gotoRecord(sendPage, `/owner-send-approvals/${sendApprovalId}`); const sent = await act(sendPage, 'ownerBill.send', sendApprovalId, width); await retryUI(sendPage, 'ownerBill.send', sent, width);
    const sentState = await control('last_bill_state'); assert.equal(sentState.status, 'sent'); assert.equal(sentState.sends.length, 1); assert.equal(sentState.sends[0].channel, 'mail-sink'); assert.equal(sentState.sends[0].approvalId, sendApprovalId); assert.deepEqual(sentState.sends[0].recipients, ['owner-billing@synthetic-owner.invalid']);
    assert.equal(sent.value.result.syntheticMailSink, true); assert.equal(sent.value.result.externalDelivery, 'not_attempted'); await snapshot(sendPage, 'synthetic-owner-send-recorded-once', width);
    for (const original of [prepared, requested, sendRequested, sent]) await retryHTTP(sendContext, original, width);
    await choose(sendPage, 'reviewer'); for (const original of [granted, sendGranted]) await retryHTTP(sendContext, original, width);
    await page.getByRole('button', { name: 'Refresh scoped records', exact: true }).click();
    assert.equal((await json(context, `/owner-bills/${billId}`)).status, 'sent'); await retryUI(page, 'ownerBill.post', posted, width);
    await snapshot(page, 'original-posted-receipt-beside-current-sent-state', width);
    report.recoveryChecks.push({ name: 'original posting receipt remains posted while current bill is sent', width });
    await retryHTTP(context, posted, width); await aging(page, billId, width);
    if (width === 1440) await malformedRecords(context, billId, width);
    await sendContext.close();
    const final = await control('counts'); fixedBoundary(baseline, final); assert.equal(final.journals-baseline.journals, 1); assert.equal(final.prime_bills-baseline.prime_bills, 1); assert.equal(final.prime_bill_sends-baseline.prime_bill_sends, 1); assert.equal(final.ar_action_receipts-baseline.ar_action_receipts, 7);
    report.widths.push(width); report.journeys.push({ width, sevenActions: true, sourceLines: 2, journalFreeGrant: true, distinctActualPoster: true, sameGrantConsumed: true, syntheticSends: 1 }); report.counters.push({ width, baseline, final });
    await choose(page, 'preparer'); await staleAndIdentity(page, basisId, billId, prepared, width);
    await context.close(); await stopServer();
  }
  assert.deepEqual(report.errors, []); assert.deepEqual(report.violations, []);
} catch (error) { report.errors.push({ message: error.stack ?? String(error) }); throw error; }
finally { await browser?.close(); await stopServer(); await writeFile(path.join(artifacts, 'ar-smoke.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ views: report.views.length, journeys: report.journeys.length, recoveryDrafts: report.recoveryDrafts.length, exactRetries: report.exactRetries.length, recoveryChecks: report.recoveryChecks.length, contractChecks: report.contractChecks.length, violations: report.violations.length, errors: report.errors.length }));
