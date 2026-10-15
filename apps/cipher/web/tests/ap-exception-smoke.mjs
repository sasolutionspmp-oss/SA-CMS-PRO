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
const port = Number(process.env.CIPHER_EXCEPTION_PORT ?? 18769);
assert.ok(Number.isInteger(port) && port > 1024 && port <= 65535);
const base = `http://127.0.0.1:${port}`; const prefix = '/api/ap-practice/v1';
const artifacts = process.env.CIPHER_EXCEPTION_ARTIFACTS ?? '/tmp/cipher-completion/ap-exception-browser';
await mkdir(artifacts, { recursive: true });
const report = { source: 'actual-isolated-api', widths: [], views: [], journeys: [], retries: [], refusals: [], contractChecks: [],
  violations: [], errors: [], requests: [], axeExclusions: ['[data-tabster-dummy]: hidden Fluent focus sentinels; keyboard dismissal/focus is checked'] };
let server; let browser;
async function startServer() {
  server = spawn(process.env.CIPHER_PYTHON ?? 'python', ['-m', 'apps.cipher', 'ap-practice-web', '--port', String(port)], { cwd: repository, stdio: ['ignore', 'ignore', 'pipe'] });
  let diagnostics = ''; server.stderr.on('data', chunk => { diagnostics += chunk.toString(); });
  for (let i = 0; i < 120; i++) {
    if (server.exitCode !== null) throw new Error(`Practice startup failed: ${diagnostics}`);
    try { if ((await fetch(base)).ok) return () => diagnostics; } catch { /* Local server startup. */ }
    await delay(100);
  }
  throw new Error('The exception practice server did not become ready.');
}
async function stopServer() {
  if (!server || server.exitCode !== null) { server = undefined; return; }
  const closed = once(server, 'exit'); server.kill('SIGTERM'); await closed; server = undefined;
}
async function json(context, route) {
  const response = await context.request.get(base + prefix + route); assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json(); assert.equal(value.synthetic, true); assert.equal(value.mode, 'practice'); return value;
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
  const size = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth })); assert.ok(size.document <= size.width, `${name} overflows at ${width}px.`);
  const axe = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  report.violations.push(...axe.violations.map(item => ({ name, width, id: item.id, nodes: item.nodes.map(node => node.target) })));
  const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content'); assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
  assert.equal(await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content)), false);
  await page.screenshot({ path: path.join(artifacts, `${name}-${width}.png`), fullPage: true }); report.views.push({ name, width });
}
async function response(page, route, click) {
  const waiting = page.waitForResponse(value => new URL(value.url()).pathname === prefix + route && value.request().method() === 'POST');
  await click(); const result = await waiting; assert.equal(result.status(), 200, `${route}: ${await result.text()}`);
  return { value: await result.json(), key: result.request().headers()['repeatability-request-id'], body: result.request().postData() };
}
async function act(page, action, route, reviewLabel, applyLabel, confirm = false) {
  const resource = route.split('/').slice(0, 3).join('/');
  const detail = ['bill.prepare', 'invoice.receive'].includes(action) ? `${resource}/preparation`
    : ['invoice.revise', 'invoice.reject', 'invoice.reviewDuplicate', 'bill.cancel', 'bill.prepareCorrection', 'bill.requestCorrection'].includes(action) ? `${resource}/exception-review`
      : ['bill.approve', 'invoice.approveMatch', 'invoice.executeMatch', 'bill.approveCorrection', 'bill.executeCorrection'].includes(action) ? `${resource}/packet` : resource;
  const current = await json(page.context(), detail);
  await page.waitForFunction(({ action, version }) => document.querySelector(`[data-action="${action}"]`)?.getAttribute('data-resource-version') === version, { action, version: current.version });
  const panel = page.locator(`[data-action="${action}"]`); await panel.getByRole('button', { name: reviewLabel, exact: true }).click();
  await panel.getByRole('button', { name: applyLabel, exact: true }).waitFor();
  if (!confirm) return response(page, route, () => panel.getByRole('button', { name: applyLabel, exact: true }).click());
  await panel.getByRole('button', { name: applyLabel, exact: true }).click(); await page.getByRole('dialog').waitFor();
  const safeOption = action === 'invoice.reject' ? 'Keep invoice' : action === 'bill.cancel' ? 'Keep bill' : 'Don’t reverse';
  assert.equal(await page.getByRole('dialog').getByRole('button', { name: safeOption, exact: true }).evaluate(element => element === document.activeElement), true);
  await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(await panel.getByRole('button', { name: reviewLabel, exact: true }).evaluate(element => element === document.activeElement), true);
  await panel.getByRole('button', { name: applyLabel, exact: true }).click();
  return response(page, route, () => page.getByRole('dialog').getByRole('button', { name: applyLabel, exact: true }).click());
}
async function retry(page, action, route, first, width) {
  const again = await response(page, route, () => page.locator(`[data-action="${action}"]`).getByRole('button', { name: 'Retry same action', exact: true }).click());
  assert.equal(again.key, first.key); assert.equal(again.body, first.body); assert.equal(again.value.receiptId, first.value.receiptId);
  assert.equal(again.value.replayed, true); assert.equal(again.value.effectApplied, false); assert.deepEqual(again.value.result, first.value.result);
  report.retries.push({ width, action });
}
async function receive(page, commitment, source, number, amount = '100.00') {
  await page.goto(base + `/commitments/${commitment.id}/receive-invoice`);
  await page.getByRole('textbox', { name: 'Supplier invoice number', exact: true }).fill(number); await page.getByLabel('Invoice date', { exact: true }).fill('2026-10-14');
  await page.getByRole('textbox', { name: 'Invoice amount (USD)', exact: true }).fill(amount);
  await page.getByRole('combobox', { name: 'Source invoice evidence', exact: true }).selectOption(source.revisionId);
  return act(page, 'invoice.receive', `/commitments/${commitment.id}/receive-invoice`, 'Review invoice receipt', 'Receive supplier invoice');
}
async function prepare(page, context, commitment, amounts) {
  const dto = await json(context, `/commitments/${commitment.id}/preparation`); await page.goto(base + `/commitments/${commitment.id}/prepare-bill`);
  for (let i = 0; i < dto.lines.length; i++) await page.getByRole('textbox', { name: `Installed to date for ${dto.lines[i].description}`, exact: true }).fill(amounts[i]);
  return act(page, 'bill.prepare', `/commitments/${commitment.id}/prepare-bill`, 'Review preparation', 'Prepare draft bill');
}
async function postBill(page, bill) {
  await page.goto(base + `/bills/${bill.id}`); await page.getByRole('button', { name: 'Review posting', exact: true }).click();
  await page.getByRole('button', { name: 'Post to practice working ledger', exact: true }).click();
  return response(page, `/bills/${bill.id}/post`, () => page.getByRole('dialog').getByRole('button', { name: `Post to ${bill.certificationPeriod.name}`, exact: true }).click());
}
async function matchInvoice(page, invoiceId, billId) {
  await page.goto(base + `/invoices/${invoiceId}`);
  await act(page, 'invoice.computeMatch', `/invoices/${invoiceId}/compute-match`, 'Review matching', 'Compute invoice match');
  const requested = await act(page, 'invoice.requestMatchApproval', `/invoices/${invoiceId}/request-match-approval`, 'Review match request', 'Request match approval');
  const approvalId = requested.value.result.approvalId;
  await selectPerson(page, 'reviewer'); await page.goto(base + `/match-approvals/${approvalId}`);
  await act(page, 'invoice.approveMatch', `/match-approvals/${approvalId}/approve`, 'Review match approval', 'Approve invoice match');
  await selectPerson(page, 'accountant'); await page.goto(base + `/match-approvals/${approvalId}`);
  const applied = await act(page, 'invoice.executeMatch', `/match-approvals/${approvalId}/execute`, 'Review approved match', 'Apply approved match');
  assert.equal(applied.value.result.billId, billId);
}
async function contractChecks(context, approvalId) {
  const malformedPacket = await context.newPage();
  malformedPacket.on('pageerror', error => report.errors.push({ width: 1440, check: 'unsupported correction effect', message: error.message }));
  await malformedPacket.route(`**${prefix}/correction-approvals/${approvalId}/packet`, async route => {
    const response = await route.fetch(); const value = await response.json(); value.effect.externalAccounting = 'accepted'; await route.fulfill({ response, json: value });
  });
  await malformedPacket.goto(base + `/correction-approvals/${approvalId}`); await malformedPacket.getByRole('alert').waitFor();
  assert.equal(await malformedPacket.getByRole('button', { name: 'Execute approved correction', exact: true }).count(), 0);
  report.contractChecks.push('unsupported correction accounting acknowledgement refused'); await malformedPacket.close();
  const malformedPreview = await context.newPage();
  malformedPreview.on('pageerror', error => report.errors.push({ width: 1440, check: 'null reversal debit', message: error.message }));
  await malformedPreview.route(`**${prefix}/correction-approvals/${approvalId}/execute:preflight`, async route => {
    const response = await route.fetch(); const value = await response.json(); value.safeEffects.journalPreview[0].lines[0].debitCents = null; await route.fulfill({ response, json: value });
  });
  await malformedPreview.goto(base + `/correction-approvals/${approvalId}`); await malformedPreview.getByRole('button', { name: 'Review correction reversal', exact: true }).click();
  await malformedPreview.getByRole('alert').waitFor(); assert.ok((await malformedPreview.getByRole('alert').innerText()).includes('accurately'));
  assert.equal(await malformedPreview.getByRole('button', { name: 'Execute approved correction', exact: true }).count(), 0);
  assert.equal(await malformedPreview.getByRole('table', { name: 'Reviewed entry 1', exact: true }).count(), 0);
  report.contractChecks.push('null reversal cents refused'); await malformedPreview.close();
}
try {
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  for (const width of [1440, 1024, 390]) {
    const diagnostics = await startServer(); const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce', hasTouch: width < 1024 });
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push({ width, message: error.message }));
    page.on('console', message => { if (message.type() === 'error') report.errors.push({ width, message: message.text() }); });
    page.on('response', value => { if (value.status() >= 400) report.errors.push({ width, status: value.status(), route: new URL(value.url()).pathname }); });
    await page.route('**/*', route => {
      const request = route.request(); const url = new URL(request.url()); assert.equal(url.origin, base); assert.ok(['GET', 'HEAD', 'POST'].includes(request.method()));
      if (request.method() === 'POST') assert.ok(url.pathname.startsWith(prefix + '/'));
      if (url.pathname.startsWith('/api/')) report.requests.push({ width, method: request.method(), route: url.pathname }); return route.continue();
    });
    await page.goto(base); await selectPerson(page, 'accountant');
    const commitments = (await json(context, '/commitments')).value; const civil = commitments.find(row => row.title === 'Civil works subcontract'); assert.ok(civil);
    const sources = (await json(context, '/invoice-evidence')).value.filter(row => row.projectId === civil.projectId && row.available); assert.equal(sources.length, 3);
    await receive(page, civil, sources[0], 'SYN-EXCEPTION-201');
    const duplicate = await receive(page, civil, sources[1], 'SYN-EXCEPTION-202'); assert.equal(duplicate.value.result.possibleDuplicate, true);
    const invoiceId = duplicate.value.result.invoiceId;
    await page.getByRole('link', { name: 'Open received invoice', exact: true }).click();
    await page.getByRole('link', { name: 'Review invoice revision, duplicate or rejection', exact: true }).click();
    await page.getByRole('textbox', { name: 'Duplicate review reason', exact: true }).fill('Reviewed both synthetic source documents; this is a separate obligation.');
    await snapshot(page, 'duplicate-review-form', width);
    const cleared = await act(page, 'invoice.reviewDuplicate', `/invoices/${invoiceId}/review-duplicate`, 'Review duplicate decision', 'Record duplicate review');
    assert.equal(cleared.value.result.duplicateReviewed, true); await retry(page, 'invoice.reviewDuplicate', `/invoices/${invoiceId}/review-duplicate`, cleared, width);
    assert.equal((await json(context, `/invoices/${invoiceId}`)).duplicateBlocking, false);
    await page.getByRole('textbox', { name: 'Revised supplier invoice number', exact: true }).fill('SYN-EXCEPTION-203');
    await page.getByRole('textbox', { name: 'Revision reason', exact: true }).fill('Supplier corrected the source invoice number; reassess duplicate facts.');
    const revised = await act(page, 'invoice.revise', `/invoices/${invoiceId}/revise`, 'Review invoice revision', 'Revise supplier invoice');
    assert.equal(revised.value.result.invoiceVersion, 2); await retry(page, 'invoice.revise', `/invoices/${invoiceId}/revise`, revised, width);
    assert.equal((await json(context, `/invoices/${invoiceId}`)).duplicateBlocking, true); await snapshot(page, 'revision-requires-duplicate-review', width);
    await page.getByRole('textbox', { name: 'Duplicate review reason', exact: true }).fill('Reviewed reissued synthetic number and reconfirmed distinct source obligation.');
    const reviewedAgain = await act(page, 'invoice.reviewDuplicate', `/invoices/${invoiceId}/review-duplicate`, 'Review duplicate decision', 'Record duplicate review');
    assert.equal(reviewedAgain.value.result.invoiceVersion, 2); assert.equal((await json(context, `/invoices/${invoiceId}`)).duplicateBlocking, false);
    await page.getByRole('textbox', { name: 'Rejection reason', exact: true }).fill('Final synthetic rejection after confirming this invoice is not owed.');
    const rejected = await act(page, 'invoice.reject', `/invoices/${invoiceId}/reject`, 'Review invoice rejection', 'Reject supplier invoice', true);
    assert.equal(rejected.value.result.status, 'rejected'); await retry(page, 'invoice.reject', `/invoices/${invoiceId}/reject`, rejected, width);
    await snapshot(page, 'final-invoice-rejection', width);
    const finalInvoice = await json(context, `/invoices/${invoiceId}`); assert.equal(finalInvoice.status, 'rejected');
    const released = (await json(context, '/invoice-evidence')).value.find(row => row.documentId === sources[1].documentId); assert.equal(released.available, true);
    const reused = await receive(page, civil, released, 'SYN-EXCEPTION-204', '120.00'); assert.equal(reused.value.result.status, 'received');
    const originalBills = (await json(context, '/bills')).value; const draft = originalBills.find(row => row.status === 'draft'); const approved = originalBills.find(row => row.status === 'approved'); assert.ok(draft && approved);
    await page.goto(base + `/bills/${draft.id}`); await page.getByRole('link', { name: 'Review bill cancellation or correction', exact: true }).click();
    await page.getByRole('textbox', { name: 'Cancellation reason', exact: true }).fill('Cancel the unused synthetic certification before replacement.'); await snapshot(page, 'unposted-cancellation-review', width);
    const canceled = await act(page, 'bill.cancel', `/bills/${draft.id}/cancel`, 'Review bill cancellation', 'Cancel unposted bill', true);
    assert.equal(canceled.value.result.status, 'void'); assert.equal(canceled.value.result.journalDelta, 0); await retry(page, 'bill.cancel', `/bills/${draft.id}/cancel`, canceled, width);
    assert.equal((await json(context, `/bills/${draft.id}`)).currentDueCents, 0);
    await selectPerson(page, 'pm'); await page.goto(base + `/bills/${approved.id}/exceptions`);
    await page.getByRole('textbox', { name: 'Cancellation reason', exact: true }).fill('Original project manager withdraws the unposted synthetic approval.');
    const withdrawn = await act(page, 'bill.cancel', `/bills/${approved.id}/cancel`, 'Review approved withdrawal', 'Withdraw approved bill', true);
    assert.equal(withdrawn.value.result.status, 'void'); await retry(page, 'bill.cancel', `/bills/${approved.id}/cancel`, withdrawn, width); await snapshot(page, 'original-pm-approved-withdrawal', width);
    await selectPerson(page, 'accountant'); const prepared = await prepare(page, context, civil, ['1000.00', '2000.00']); const billId = prepared.value.result.billId;
    const invoice = await receive(page, civil, sources[2], 'SYN-CORRECTION-205', '2700.00'); const sourceInvoiceId = invoice.value.result.invoiceId;
    await matchInvoice(page, sourceInvoiceId, billId);
    await page.goto(base + `/bills/${billId}`);
    const requested = await act(page, 'bill.requestApproval', `/bills/${billId}/request-approval`, 'Review request', 'Request business approval');
    await selectPerson(page, 'pm'); await page.goto(base + `/approvals/${requested.value.result.approvalId}`);
    await act(page, 'bill.approve', `/approvals/${requested.value.result.approvalId}/approve`, 'Review approval', 'Approve bill');
    await selectPerson(page, 'accountant'); const bill = await json(context, `/bills/${billId}`); await postBill(page, bill);
    await page.getByRole('link', { name: 'Review bill cancellation or correction', exact: true }).click();
    await page.getByRole('textbox', { name: 'Correction reason', exact: true }).fill('Synthetic source review found a certification error; reverse before replacement.');
    const correctionPrepared = await act(page, 'bill.prepareCorrection', `/bills/${billId}/prepare-correction`, 'Review correction preparation', 'Prepare correction request');
    assert.equal(correctionPrepared.value.result.journalDelta, 0); await retry(page, 'bill.prepareCorrection', `/bills/${billId}/prepare-correction`, correctionPrepared, width);
    const correctionRequested = await act(page, 'bill.requestCorrection', `/bills/${billId}/request-correction`, 'Review correction request', 'Request correction approval');
    await retry(page, 'bill.requestCorrection', `/bills/${billId}/request-correction`, correctionRequested, width); const correctionId = correctionRequested.value.result.approvalId;
    await selectPerson(page, 'reviewer'); await page.goto(base + '/correction-approvals'); await page.getByRole('table', { name: 'Bill correction reviews', exact: true }).waitFor(); await snapshot(page, 'correction-review-queue', width);
    await page.getByRole('link', { name: /Bill 1/ }).click(); await page.getByRole('button', { name: 'Review correction approval', exact: true }).waitFor(); await snapshot(page, 'independent-correction-packet', width);
    const packet = await json(context, `/correction-approvals/${correctionId}/packet`); const reviewer = await json(context, '/session'); assert.notEqual(packet.requestedBy.id, reviewer.person.id);
    assert.equal(packet.bill.thisPeriodCents, 300000); assert.equal(packet.bill.retainageCents, 30000); assert.equal(packet.amountDueCents, 270000);
    const decisionFacts = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Correction decision facts', exact: true }) });
    for (const [label, value] of [['Original certified cost', '$3,000.00'], ['Original retainage', '$300.00'], ['Original amount due', '$2,700.00']]) {
      await decisionFacts.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) }).getByText(value, { exact: true }).waitFor();
    }
    const correctionGranted = await act(page, 'bill.approveCorrection', `/correction-approvals/${correctionId}/approve`, 'Review correction approval', 'Approve bill correction');
    assert.equal(correctionGranted.value.result.journalDelta, 0); await retry(page, 'bill.approveCorrection', `/correction-approvals/${correctionId}/approve`, correctionGranted, width);
    await selectPerson(page, 'accountant'); await page.goto(base + `/correction-approvals/${correctionId}`);
    if (width === 1440) await contractChecks(context, correctionId);
    await page.getByRole('combobox', { name: 'Correction period', exact: true }).selectOption('2026-11');
    const panel = page.locator('[data-action="bill.executeCorrection"]'); await panel.getByRole('button', { name: 'Review correction reversal', exact: true }).click();
    await page.getByRole('table', { name: 'Reviewed entry 1', exact: true }).waitFor(); await snapshot(page, 'reviewed-correction-reversal', width);
    await panel.getByRole('button', { name: 'Execute approved correction', exact: true }).click();
    assert.equal(await page.getByRole('dialog').getByRole('button', { name: 'Don’t reverse', exact: true }).evaluate(element => element === document.activeElement), true);
    const corrected = await response(page, `/correction-approvals/${correctionId}/execute`, () => page.getByRole('dialog').getByRole('button', { name: 'Execute approved correction', exact: true }).click());
    assert.equal(corrected.value.result.status, 'corrected'); assert.equal(corrected.value.result.periodId, '2026-11'); assert.equal(corrected.value.result.apDeltaCents, -bill.amountDueCents);
    assert.equal(corrected.value.result.reversalJournalIds.length, 1); await retry(page, 'bill.executeCorrection', `/correction-approvals/${correctionId}/execute`, corrected, width);
    assert.equal((await json(context, `/bills/${billId}`)).currentDueCents, 0); await snapshot(page, 'corrected-before-replacement', width);
    await page.getByRole('link', { name: 'Prepare replacement bill', exact: true }).click();
    await page.getByRole('combobox', { name: 'Certification period', exact: true }).selectOption('2026-11');
    await page.getByRole('textbox', { name: 'Installed to date for Site excavation', exact: true }).fill('1100.00'); await page.getByRole('textbox', { name: 'Installed to date for Concrete foundations', exact: true }).fill('2200.00');
    const replacement = await act(page, 'bill.prepare', `/commitments/${civil.id}/prepare-bill`, 'Review preparation', 'Prepare draft bill');
    assert.notEqual(replacement.value.result.billId, billId);
    await page.goto(base + `/invoices/${sourceInvoiceId}/exceptions`);
    await page.getByRole('textbox', { name: 'Revised invoice amount (USD)', exact: true }).fill('2970.00');
    await page.getByRole('textbox', { name: 'Revision reason', exact: true }).fill('Supplier reissued the corrected synthetic certification for replacement.');
    await act(page, 'invoice.revise', `/invoices/${sourceInvoiceId}/revise`, 'Review invoice revision', 'Revise supplier invoice');
    await matchInvoice(page, sourceInvoiceId, replacement.value.result.billId);
    await page.goto(base + `/bills/${replacement.value.result.billId}`);
    const replacementRequested = await act(page, 'bill.requestApproval', `/bills/${replacement.value.result.billId}/request-approval`, 'Review request', 'Request business approval');
    await selectPerson(page, 'pm'); await page.goto(base + `/approvals/${replacementRequested.value.result.approvalId}`);
    await act(page, 'bill.approve', `/approvals/${replacementRequested.value.result.approvalId}/approve`, 'Review approval', 'Approve bill');
    await selectPerson(page, 'accountant'); const replacementBill = await json(context, `/bills/${replacement.value.result.billId}`); await postBill(page, replacementBill);
    assert.equal((await json(context, `/bills/${replacementBill.id}`)).currentDueCents, replacementBill.amountDueCents); await snapshot(page, 'replacement-approved-and-posted', width);
    await page.getByRole('button', { name: 'Help', exact: true }).click(); await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: 'Help', exact: true }).evaluate(element => element === document.activeElement), true);
    if (width === 390) { await page.getByRole('button', { name: 'Open navigation', exact: true }).click(); await page.getByRole('dialog').getByRole('link', { name: 'Correction reviews', exact: true }).click(); await page.getByRole('heading', { name: 'Correction reviews', exact: true }).waitFor(); }
    assert.equal(diagnostics(), '', 'The exception server reported an unexpected exception.');
    report.journeys.push({ width, revisedDuplicateReReview: true, finalRejected: true, evidenceReleasedAndReused: true,
      draftCanceledWithoutJournal: true, originalPmWithdrawnWithoutJournal: true, distinctCorrectionApprover: true,
      originalMatchedUnpaidBillReversed: true, actualLaterCorrectionPeriod: true, invoiceRevisedAndFreshlyMatchedToReplacement: true,
      replacementApprovedAndPosted: true });
    report.widths.push(width); await context.close(); await stopServer();
  }
  await writeFile(path.join(artifacts, 'ap-exception-smoke.json'), JSON.stringify(report, null, 2));
  assert.deepEqual(report.violations, []); assert.deepEqual(report.errors, []);
  console.log(JSON.stringify({ source: report.source, widths: report.widths, views: report.views.length, journeys: report.journeys.length,
    exactRetries: report.retries.length, contractChecks: report.contractChecks.length, accessibilityViolations: report.violations.length, browserErrors: report.errors.length }));
} catch (error) { await writeFile(path.join(artifacts, 'ap-exception-smoke-failed.json'), JSON.stringify(report, null, 2)); throw error; }
finally { await browser?.close(); await stopServer(); }
