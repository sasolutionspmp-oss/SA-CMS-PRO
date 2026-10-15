import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const directory = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const external = process.env.CIPHER_WEB_BASE_URL;
const base = external ?? 'http://127.0.0.1:5179';
const address = new URL(base);
assert.equal(address.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(address.hostname), 'Smoke checks are restricted to local practice servers.');
const artifacts = process.env.CIPHER_WEB_ARTIFACTS ?? '/tmp/cipher-web-review';
await mkdir(artifacts, { recursive: true });
let server;
let browser;
const errors = [];
try {
  if (!external) {
    server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5179', '--strictPort', '--mode', 'fixture'], { cwd: directory, stdio: 'ignore' });
  }
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    try { if ((await fetch(base)).ok) { ready = true; break; } } catch { /* Wait for the local listener. */ }
    await delay(250);
  }
  assert.ok(ready, 'The local practice web server did not become ready.');
  const fixture = JSON.parse(await readFile(path.join(directory, 'src/api/fixture.json'), 'utf8'));
  const records = {};
  for (const collection of ['projects', 'commitments', 'bills', 'approvals']) {
    const envelope = external ? await (await fetch(`${base}/api/practice/v1/${collection}?top=100`)).json() : fixture[collection];
    assert.equal(envelope.contractVersion, 'cipher.practice-read.v1');
    assert.equal(envelope.mode, 'practice');
    assert.equal(envelope.synthetic, true);
    records[collection] = envelope.value;
  }
  browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME ?? '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const pages = [
    ['home', '/'], ['projects', '/projects'],
    ...records.projects.slice(0, 1).map(row => ['project', `/projects/${encodeURIComponent(row.id)}`]),
    ...records.commitments.slice(0, 1).map(row => ['subcontract', `/commitments/${encodeURIComponent(row.id)}`]),
    ...records.bills.slice(0, 1).map(row => ['pay-app', `/bills/${encodeURIComponent(row.id)}`]),
    ...records.approvals.slice(0, 1).map(row => ['approval', `/approvals/${encodeURIComponent(row.id)}`]),
  ];
  const report = { source: external ? 'api' : 'fixture', widths: [], pages: pages.map(([name]) => name), violations: [], requests: [], axeExclusions: ['[data-tabster-dummy]: hidden library focus sentinels, keyboard traversal checked'] };
  for (const width of [1440, 1024, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1024 });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.route('**/*', route => {
      const request = route.request();
      const url = new URL(request.url());
      assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname), `Unexpected offsite request: ${url.hostname}`);
      assert.ok(['GET', 'HEAD'].includes(request.method()), `Unexpected write request: ${request.method()}`);
      if (url.pathname.startsWith('/api/')) report.requests.push({ method: request.method(), pathname: url.pathname });
      return route.continue();
    });
    for (const [name, route] of pages) {
      await page.goto(base + route);
      await page.locator('main[aria-busy="false"]').waitFor();
      assert.equal(await page.getByText('Practice data. Nothing here is real money and nothing is sent.', { exact: true }).count(), 1);
      assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1);
      assert.equal(await page.getByRole('button', { name: /^(Approve|Post|Pay|Release|Send|Execute)(\s|$)/ }).count(), 0);
      const layout = await page.evaluate(() => ({ width: window.innerWidth, documentWidth: document.documentElement.scrollWidth }));
      assert.ok(layout.documentWidth <= layout.width, `${name} overflows the page at ${width}px: ${JSON.stringify(layout)}`);
      const accessibility = await new AxeBuilder({ page }).exclude('[data-tabster-dummy]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      report.violations.push(...accessibility.violations.map(violation => ({ width, page: name, id: violation.id, nodes: violation.nodes.map(node => node.target) })));
      await page.screenshot({ path: path.join(artifacts, `${report.source}-${name}-${width}.png`), fullPage: true });
    }
    await page.goto(base + '/projects');
    await page.locator('main[aria-busy="false"]').waitFor();
    await page.keyboard.press('Control+k');
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Search projects');
    const search = page.getByRole('textbox', { name: 'Search projects' });
    await search.fill('No matching practice project');
    await page.getByText('No projects match this search.', { exact: false }).waitFor();
    await page.getByRole('button', { name: 'Clear filters' }).click();
    assert.ok(await page.getByRole('table', { name: 'Projects', exact: true }).count());
    await page.getByRole('button', { name: 'Help', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: 'Help', exact: true }).evaluate(element => element === document.activeElement), true);
    if (width === 390) {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('dialog').getByRole('link', { name: 'Home', exact: true }).click();
      await page.getByRole('heading', { name: 'My projects', level: 1, exact: true }).waitFor();
    }
    if (external) {
      const nonce = await page.locator('meta[name="cipher-style-nonce"]').getAttribute('content');
      assert.ok(nonce && nonce !== '__CIPHER_STYLE_NONCE__');
      const missingNonce = await page.locator('style').evaluateAll(styles => styles.some(style => style.nonce !== document.querySelector('meta[name="cipher-style-nonce"]').content));
      assert.equal(missingNonce, false, 'A Fluent/Griffel style element is missing the response nonce.');
    }
    await page.goto(base + '/bills');
    await page.locator('main[aria-busy="false"]').waitFor();
    const billSearch = page.getByRole('textbox', { name: 'Search sub pay apps' });
    await billSearch.fill('No matching practice pay app');
    const selectedStatus = records.bills[0]?.status;
    assert.ok(selectedStatus, 'The synthetic fixture needs a recorded bill status for combined filter checks.');
    await page.getByRole('combobox', { name: 'Filter by status' }).selectOption(selectedStatus);
    assert.equal(await billSearch.inputValue(), 'No matching practice pay app');
    assert.ok(new URL(page.url()).searchParams.has('search'));
    assert.equal(new URL(page.url()).searchParams.get('status'), selectedStatus);
    report.widths.push(width);
    await context.close();
  }
  if (external) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    report.contractChecks = [];
    for (const [name, collection, mutate, expected] of [
      ['missing required amount', 'projects', page => { delete page.value[0].budgetCents; }, 'incomplete'],
      ['object in a name', 'projects', page => { page.value[0].name = { bad: 'typed-contract' }; }, 'incomplete'],
      ['null period amount', 'bills', page => { page.value[0].thisPeriodCents = null; }, 'incomplete'],
      ['live envelope', 'projects', page => { page.mode = 'live'; }, 'supported synthetic'],
      ['out-of-range project aggregate', 'commitments', page => {
        const first = page.value[0];
        page.value = [Number.MAX_SAFE_INTEGER, 1].map((amount, index) => ({ ...first, id: `aggregate-${index}`, status: 'executed', executedAmountCents: amount }));
        page.count = 2;
      }, 'supported monetary range'],
    ]) {
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.route(`**/api/practice/v1/${collection}?*`, async route => {
        const response = await route.fetch();
        const envelope = await response.json();
        mutate(envelope);
        await route.fulfill({ response, json: envelope });
      });
      await page.goto(base + '/projects');
      await page.getByRole('alert').waitFor();
      assert.ok((await page.getByRole('alert').innerText()).includes(expected));
      assert.equal(await page.getByRole('table').count(), 0);
      assert.equal(await page.getByText('Sample fixture', { exact: true }).count(), 0);
      report.contractChecks.push(name);
      await page.close();
    }
    if (records.bills.length) {
      const page = await context.newPage();
      await page.route('**/api/practice/v1/bills?*', async route => {
        const response = await route.fetch();
        const envelope = await response.json();
        envelope.value[0].amountDueCents = Number.MAX_SAFE_INTEGER;
        await route.fulfill({ response, json: envelope });
      });
      await page.goto(base + `/bills/${encodeURIComponent(records.bills[0].id)}`);
      await page.getByText('$90,071,992,547,409.91', { exact: true }).waitFor();
      report.contractChecks.push('maximum safe integer cents remains exact');
      await page.close();
    }
    if (records.commitments.length) {
      const page = await context.newPage();
      await page.route('**/api/practice/v1/commitments?*', async route => {
        const response = await route.fetch();
        const envelope = await response.json();
        const first = envelope.value[0];
        envelope.value = [Number.MAX_SAFE_INTEGER, 2, -143].map((amount, index) => ({ ...first, id: `aggregate-${index}`, status: 'executed', executedAmountCents: amount }));
        envelope.count = 3;
        await route.fulfill({ response, json: envelope });
      });
      await page.goto(base + `/projects/${encodeURIComponent(records.commitments[0].projectId)}`);
      await page.locator('dd').filter({ hasText: '$90,071,992,547,409' }).waitFor();
      report.contractChecks.push('aggregate arithmetic stays exact across the safe-integer boundary');
      await page.close();
    }
    await context.close();
  }
  report.errors = errors;
  await writeFile(path.join(artifacts, `${report.source}-smoke.json`), JSON.stringify(report, null, 2));
  assert.deepEqual(report.violations, [], 'Automated accessibility checks found violations.');
  assert.deepEqual(errors, [], 'The browser reported errors, including possible CSP failures.');
  console.log(JSON.stringify({ source: report.source, widths: report.widths, pages: report.pages, accessibilityViolations: report.violations.length, browserErrors: errors.length }));
} finally {
  await browser?.close();
  server?.kill('SIGTERM');
}
