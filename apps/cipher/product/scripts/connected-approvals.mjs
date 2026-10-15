import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

// Explicit synthetic-site acceptance. All effects use the normal UI and real
// same-origin services. Run only in the mutation slot assigned by the runtime owner.
const manifest = JSON.parse(await readFile(process.env.CIPHER_RUNTIME_MANIFEST || '/tmp/cipher-r0-runtime/fixture.secret.json', 'utf8'));
const base = process.env.CIPHER_RUNTIME_URL || 'http://127.0.0.1:18880';
const output = new URL('../test-results/connected-approvals/', import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
let stage = 'private fixture configuration';
const results = [];
try {
  const reviewer = manifest.users[process.env.CIPHER_REVIEWER_KEY || 'reviewer'];
  if (!reviewer?.user || !reviewer?.password) throw new Error('Reviewer is not configured.');
  const primaryContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const reviewerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const primary = await primaryContext.newPage();
  const review = await reviewerContext.newPage();
  const errors = [];
  primary.on('pageerror', error => errors.push(error.message));
  review.on('pageerror', error => errors.push(error.message));
  const projectPath = `${base}/projects/${encodeURIComponent(manifest.project)}`;
  const signIn = async (page, credentials) => {
    await page.goto(projectPath);
    await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toBeVisible();
    await page.getByLabel('Email or username', { exact: true }).fill(credentials.user);
    await page.getByLabel('Password', { exact: true }).fill(credentials.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.locator('ui5-table[accessible-name="Project tasks"]')).toBeVisible();
  };
  stage = 'primary sign in'; await signIn(primary, manifest.users.primary);
  stage = 'independent reviewer sign in'; await signIn(review, reviewer);
  const read = async (page, method) => {
    const parameters = new URLSearchParams({ company: manifest.company, project: manifest.project, ...(method === 'tasks' ? { count_mode: 'exact', limit: '200' } : {}) });
    const response = await page.request.get(`${base}/api/method/cipher_aec.api.v1.${method}?${parameters}`);
    if (!response.ok()) throw new Error('Read verification failed.');
    return (await response.json()).message.data;
  };
  const before = await read(primary, 'project');
  if (before.status !== 'Open') throw new Error('Approval acceptance requires the isolated project initially Open.');
  const tasksBefore = await read(primary, 'tasks');
  const taskSnapshot = tasks => JSON.stringify(tasks.items.map(task => [task.id, task.status, task.version]).sort());
  const flow = async (target, label) => {
    stage = `${label}: request exact change`;
    await primary.goto(projectPath);
    await primary.getByRole('button', { name: 'Request status change', exact: true }).click();
    const requested = primary.waitForResponse(response => response.url().endsWith('cipher_aec.api.approvals.request_project_status') && response.request().method() === 'POST');
    await primary.getByRole('button', { name: 'Submit approval request', exact: true }).click();
    const requestedResponse = await requested;
    if (!requestedResponse.ok()) throw new Error('Approval request failed.');
    const packet = (await requestedResponse.json()).message.data.packet;
    if (packet.changes.status.to !== target) throw new Error('Requested target does not match.');
    const primaryDialog = primary.locator('ui5-dialog[header-text="Review approval packet"]');
    await expect(primaryDialog).toContainText(packet.id);
    await expect(primaryDialog.getByRole('button', { name: 'Grant approval', exact: true })).toHaveCount(0);
    await expect(primaryDialog.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
    if (label === 'hold') await primary.screenshot({ path: new URL('connected-approval-requested.png', output).pathname, fullPage: true });
    await primaryDialog.getByRole('button', { name: 'Close review', exact: true }).click();
    const afterRequest = await read(primary, 'project');
    if (afterRequest.status !== packet.changes.status.from) throw new Error('Request changed the project before execution.');

    stage = `${label}: independent human review`;
    await review.goto(projectPath);
    await review.getByRole('button', { name: 'Review packet', exact: true }).first().click();
    const reviewDialog = review.locator('ui5-dialog[header-text="Review approval packet"]');
    await expect(reviewDialog).toContainText(packet.id);
    const grant = reviewDialog.getByRole('button', { name: 'Grant approval', exact: true });
    await expect(grant).toBeDisabled();
    await reviewDialog.getByRole('checkbox', { name: 'I reviewed this exact change and its source', exact: true }).check();
    await reviewDialog.getByRole('textbox', { name: 'Approval decision note', exact: true }).fill('Synthetic browser acceptance: independently reviewed exact project-only change.');
    if (label === 'hold') await review.screenshot({ path: new URL('connected-approval-independent-review.png', output).pathname, fullPage: true });
    await grant.click();
    await expect(reviewDialog.getByRole('note', { name: /Approval granted/ })).toBeVisible();
    await expect(reviewDialog.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
    await reviewDialog.getByRole('button', { name: 'Close review', exact: true }).click();
    const afterGrant = await read(primary, 'project');
    if (afterGrant.status !== packet.changes.status.from) throw new Error('Grant changed the project before execution.');

    stage = `${label}: separate authorized execution`;
    await primary.goto(projectPath);
    await primary.getByRole('button', { name: 'Review packet', exact: true }).first().click();
    await expect(primaryDialog).toContainText(packet.id);
    const execute = primaryDialog.getByRole('button', { name: 'Execute approved change', exact: true });
    await expect(execute).toBeDisabled();
    await primaryDialog.getByRole('checkbox', { name: 'I reviewed this exact change and its source', exact: true }).check();
    await execute.click();
    await expect(primaryDialog.getByRole('note', { name: /The approved status change was executed/ })).toBeVisible();
    await expect(primaryDialog.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
    if (label === 'hold') await primary.screenshot({ path: new URL('connected-approval-executed.png', output).pathname, fullPage: true });
    await primaryDialog.getByRole('button', { name: 'Close review', exact: true }).click();
    const after = await read(primary, 'project');
    const tasksAfter = await read(primary, 'tasks');
    if (after.status !== target || taskSnapshot(tasksAfter) !== taskSnapshot(tasksBefore)) throw new Error('Exact Project/Task effect verification failed.');
    results.push({ packet_id: packet.id, manifest_hash: packet.manifest_hash, from: packet.changes.status.from, to: target, unchanged_tasks: tasksAfter.items.length, independent_review: true, separate_execution: true });
  };
  await flow('On hold', 'hold');
  await flow('Open', 'restore');
  if (errors.length) throw new Error('Browser reported uncaught errors.');
  await writeFile(new URL('verification.json', output), JSON.stringify({ mode: 'actual-frappe-synthetic-ui-effects', captured_at: new Date().toISOString(), mocked_requests: false, business_writes: true, initial_and_final_status: 'Open', browser_errors: errors.length, results }, null, 2));
  console.log('Actual approval UI journey passed: independent review, separate execution, unchanged Tasks, independently approved restoration to Open. No credentials were logged.');
} catch {
  console.error(`Actual approval UI verification failed at ${stage}. Credentials and authentication errors were not logged. Project restoration must be assessed from persisted packets.`);
  process.exitCode = 1;
} finally { await browser.close(); }
