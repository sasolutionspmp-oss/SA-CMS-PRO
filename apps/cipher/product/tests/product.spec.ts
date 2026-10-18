import { checkUi5Checkbox } from './ui5-controls';
import { expect, test, type Locator } from '@playwright/test';
import { mockWorkspace, projects } from './fixture';

test('users sign in and sign out within Cipher using the real auth contract', async ({ page }) => {
  await mockWorkspace(page, { login: true });
  await page.goto('/projects');
  await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toBeVisible();
  await page.getByLabel('Email or username', { exact: true }).fill('test.pm@example.invalid');
  await page.getByLabel('Password', { exact: true }).fill('fixture-password-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Alex Morgan', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toBeVisible();
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  await expect(page.getByRole('link', { name: projects[0].name, exact: true })).toHaveCount(0);
});

test('server cursors page the register without exposing a previous page as current', async ({ page }) => {
  await mockWorkspace(page, { pagination: true });
  await page.goto('/projects');
  await expect(page.getByRole('link', { name: projects[0].name, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(page.getByRole('link', { name: projects[2].name, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: projects[0].name, exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Previous page', exact: true }).click();
  await expect(page.getByRole('link', { name: projects[0].name, exact: true })).toBeVisible();
});

test('disconnected workspace never substitutes fixture records', async ({ page }) => {
  await page.route('**/api/method/**', route => route.fulfill({ status: 503, body: 'Unavailable', contentType: 'text/plain' }));
  await page.goto('/projects');
  await expect(page.getByRole('heading', { name: 'Your workspace is unavailable' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
  await expect(page.getByText(projects[0].name, { exact: true })).toHaveCount(0);
});

test('project register filters and opens the actual ObjectPage', async ({ page }, testInfo) => {
  await mockWorkspace(page);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/projects');
  await expect(page.getByRole('link', { name: projects[0].name, exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-project-register.png'), fullPage: true });
  await page.getByRole('textbox', { name: 'Find a project', exact: true }).fill('North River');
  await expect(page.getByRole('link', { name: projects[1].name, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: projects[0].name, exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByRole('link', { name: projects[0].name, exact: true }).click();
  await expect(page.getByRole('heading', { name: projects[0].name, exact: true })).toBeVisible();
  await expect(page.getByText('Review temporary works requirements', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-project-object-page.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('task creation recovers a lost response using the original operation', async ({ page }) => {
  const fixture = await mockWorkspace(page, { loseFirstTaskResponse: true });
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  await page.getByRole('textbox', { name: 'Task name', exact: true }).fill('Prepare site access review');
  await page.getByRole('button', { name: 'Create task', exact: true }).click();
  const connectionFailure = page.getByRole('alert').filter({ hasText: 'The workspace could not be reached.' });
  await connectionFailure.locator('.support-details > summary').click();
  await expect(connectionFailure.getByText('The workspace could not be reached.', { exact: false })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Task name', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Recover task', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Recover task', exact: true }).click();
  await expect(page.getByRole('note', { name: /Task “Prepare site access review” was created/ })).toBeVisible();
  expect(fixture.tasks.filter(task => task.subject === 'Prepare site access review')).toHaveLength(1);
  expect(fixture.writes).toHaveLength(2);
  expect(fixture.writes[0].body).toEqual(fixture.writes[1].body);
});

test('stale task source reports a conflict without success', async ({ page }) => {
  await mockWorkspace(page, { staleTask: true });
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  await page.getByRole('textbox', { name: 'Task name', exact: true }).fill('Stale task');
  await page.getByRole('button', { name: 'Create task', exact: true }).click();
  await expect(page.getByRole('note', { name: /The project changed. Refresh and review/ })).toBeVisible();
  await expect(page.getByText('Task “Stale task” was created.', { exact: true })).toHaveCount(0);
});

test('a transient project refresh keeps the stale task draft mounted', async ({ page }) => {
  await mockWorkspace(page, { staleTask: true });
  let unavailable = false;
  await page.route('**/api/method/cipher_aec.api.v1.project?**', route => unavailable ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'unavailable', message: 'The project refresh is temporarily unavailable.' } } }) }) : route.fallback());
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Create project task"]');
  await dialog.getByRole('textbox', { name: 'Task name', exact: true }).fill('Preserved access review');
  await dialog.getByRole('textbox', { name: 'Task description', exact: true }).fill('Keep this authored description.');
  await dialog.getByRole('button', { name: 'Create task', exact: true }).click();
  unavailable = true;
  await dialog.getByRole('button', { name: 'Refresh project', exact: true }).click();
  const refreshFailure = page.locator('.failure-state').filter({ hasText: /The project refresh is temporarily unavailable/ });
  await expect(refreshFailure.locator('ui5-message-strip')).toBeVisible();
  await expect(refreshFailure.locator('ui5-message-strip')).toContainText('We couldn’t confirm the result.');
  const refreshDiagnostic = refreshFailure.locator('.support-details > p');
  await expect(refreshDiagnostic).toBeAttached();
  await expect(refreshDiagnostic).toHaveText('The project refresh is temporarily unavailable.');
  await expect(dialog.getByRole('textbox', { name: 'Task name', exact: true })).toHaveValue('Preserved access review');
  await expect(dialog.getByRole('textbox', { name: 'Task description', exact: true })).toHaveValue('Keep this authored description.');
  unavailable = false;
  await dialog.getByRole('button', { name: 'Refresh project', exact: true }).click();
  await expect(dialog.getByRole('textbox', { name: 'Task name', exact: true })).toHaveValue('Preserved access review');
});

test('upload sends exact bytes and preview renders source as text', async ({ page }, testInfo) => {
  const fixture = await mockWorkspace(page);
  await page.goto(`/projects/${projects[0].id}/documents`);
  await page.getByRole('button', { name: 'Add document', exact: true }).click();
  await page.getByRole('textbox', { name: 'Document title', exact: true }).fill('Upload contract fixture');
  await page.getByLabel('Source file', { exact: true }).setInputFiles({ name: 'fixture.txt', mimeType: 'text/plain', buffer: Buffer.from('Fixture upload source.') });
  await page.getByRole('button', { name: 'Add document', exact: true }).last().click();
  await expect(page.getByRole('link', { name: 'Upload contract fixture', exact: true })).toBeVisible();
  expect(fixture.documents).toHaveLength(2);
  await page.getByRole('link', { name: 'Site coordination requirements', exact: true }).click();
  await expect(page.locator('.source-text')).toContainText('Coordinate the temporary bypass plan');
  await expect(page.locator('.source-text')).toContainText('<script>window.fixtureInjection=true</script>');
  expect(await page.evaluate(() => 'fixtureInjection' in window)).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-document-preview.png'), fullPage: true });
});

test('Ricky unavailable state leaves manual project work usable', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'Toggle Ricky assistant', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ricky is not connected' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send question to Ricky', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'New task', exact: true })).toBeEnabled();
});

test('cited Ricky proposal requires review then updates project tasks', async ({ page }, testInfo) => {
  const fixture = await mockWorkspace(page, { model: true });
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'Toggle Ricky assistant', exact: true }).click();
  await page.getByRole('textbox', { name: 'Ask Ricky about this project', exact: true }).fill('Propose a task from the source requirements.');
  await page.getByRole('button', { name: 'Send question to Ricky', exact: true }).click();
  const commit = page.getByRole('button', { name: 'Create proposed task', exact: true });
  await expect(commit).toBeDisabled();
  await expect(page.getByRole('link', { name: 'Site coordination requirements', exact: true }).last()).toBeVisible();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this task and its sources', exact: true }));
  await expect(commit).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-ricky-proposal.png'), fullPage: true });
  await commit.click();
  await expect(page.getByRole('note', { name: /Task “Prepare temporary bypass plan” was created/ })).toBeVisible();
  expect(fixture.tasks.filter(task => task.subject === 'Prepare temporary bypass plan')).toHaveLength(1);
});

test('phone layout keeps navigation and project controls usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockWorkspace(page);
  await page.goto('/projects');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
  await expect(page.getByText('Tasks', { exact: true })).toBeVisible();
});

// Compare rendered geometry, not configured widths: this catches the former
// AnalyticalTable grow-mode mismatch after an ObjectPage/container resize.
async function expectAlignedColumns(grid: Locator) {
  await expect(grid).toBeVisible();
  const headers = grid.getByRole('columnheader');
  const cells = grid.getByRole('row').nth(1).getByRole('gridcell');
  await expect(headers.first()).toBeVisible();
  await expect(cells).toHaveCount(await headers.count());
  await expect.poll(async () => {
    const deltas = await Promise.all((await headers.all()).map(async (header, index) => {
      const a = await header.boundingBox(); const b = await cells.nth(index).boundingBox();
      return !a || !b ? 999 : Math.max(Math.abs(a.x - b.x), Math.abs(a.width - b.width));
    }));
    return Math.max(...deltas);
  }, { message: 'Table headers and body cells must share column boundaries' }).toBeLessThanOrEqual(2);
}

test('table columns remain aligned across project, document and assistant layouts', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto('/projects');
  await expectAlignedColumns(page.getByRole('grid', { name: 'Projects', exact: true }));
  await page.getByRole('link', { name: projects[0].name, exact: true }).click();
  const tasks = page.locator('ui5-table[accessible-name="Project tasks"]');
  await expectAlignedColumns(tasks);
  await page.getByRole('button', { name: 'Toggle Ricky assistant', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ricky is not connected', exact: true })).toBeVisible();
  await expectAlignedColumns(tasks);
  await page.getByRole('button', { name: 'Close Ricky', exact: true }).click();
  await expectAlignedColumns(tasks);
  await page.getByRole('button', { name: 'Manage documents', exact: true }).click();
  await expectAlignedColumns(page.locator('ui5-table[accessible-name="Project documents"]'));
});

test('project status requires independent review and recovers execution with the original key', async ({ page }, testInfo) => {
  const fixture = await mockWorkspace(page, { approvals: true, loseFirstApprovalResponse: true });
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'Request status change', exact: true }).click();
  await page.getByRole('button', { name: 'Submit approval request', exact: true }).click();
  let review = page.locator('ui5-dialog[header-text="Review approval packet"]');
  await expect(review.getByRole('note', { name: /A different person must review this request/ })).toBeVisible();
  await expect(review.getByRole('button', { name: 'Grant approval', exact: true })).toHaveCount(0);
  await expect(review.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
  expect(fixture.packets[0].state).toBe('Pending');
  expect(fixture.tasks[0].status).toBe('Open');

  fixture.setReviewer(true);
  await page.reload();
  await page.getByRole('button', { name: 'Review packet', exact: true }).click();
  review = page.locator('ui5-dialog[header-text="Review approval packet"]');
  const grant = review.getByRole('button', { name: 'Grant approval', exact: true });
  await expect(grant).toBeDisabled();
  await checkUi5Checkbox(review.getByRole('checkbox', { name: 'I reviewed this exact change and its source', exact: true }));
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-approval-independent-review.png'), fullPage: true });
  await grant.click();
  await expect(review.getByRole('note', { name: /A different person must execute this grant/ })).toBeVisible();
  await expect(review.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
  expect(fixture.packets[0].state).toBe('Granted');

  fixture.setReviewer(false);
  await page.reload();
  await page.getByRole('button', { name: 'Review packet', exact: true }).click();
  review = page.locator('ui5-dialog[header-text="Review approval packet"]');
  const execute = review.getByRole('button', { name: 'Execute approved change', exact: true });
  await expect(execute).toBeDisabled();
  await checkUi5Checkbox(review.getByRole('checkbox', { name: 'I reviewed this exact change and its source', exact: true }));
  await execute.click();
  const executionFailure = review.getByRole('alert').filter({ hasText: /The workspace could not be reached/ });
  await executionFailure.locator('.support-details > summary').click();
  await expect(executionFailure.getByText(/The workspace could not be reached/)).toBeVisible();
  await execute.click();
  await expect(review.getByRole('note', { name: /The approved status change was executed/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('synthetic-contract-approval-executed.png'), fullPage: true });
  expect(fixture.packets[0].state).toBe('Consumed');
  expect(fixture.tasks).toHaveLength(1);
  expect(fixture.tasks[0].status).toBe('Open');
  const executions = fixture.writes.filter(write => write.method === 'execute_packet');
  expect(executions).toHaveLength(2);
  expect(executions[0].body.operation_id).toBe(executions[1].body.operation_id);
  await review.getByRole('button', { name: 'Close review', exact: true }).click();
  await expect(page.locator('.project-object-page').getByText('On hold', { exact: true }).first()).toBeVisible();
});


test('expired sessions remove project context and return to in-app authentication', async ({ page }) => {
  const fixture = await mockWorkspace(page);
  await page.goto(`/projects/${projects[0].id}`);
  await expect(page.getByText('Review temporary works requirements', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Toggle Ricky assistant', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ricky is not connected', exact: true })).toBeVisible();
  fixture.expireSession();
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in to your workspace', exact: true })).toBeVisible();
  await expect(page.getByText('Review temporary works requirements', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Ricky is not connected', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Alex Morgan', exact: true })).toHaveCount(0);
});


test('stale approval sources remove decision actions without reporting a grant', async ({ page }) => {
  const fixture = await mockWorkspace(page, { approvals: true, staleApproval: true });
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('button', { name: 'Request status change', exact: true }).click();
  await page.getByRole('button', { name: 'Submit approval request', exact: true }).click();
  await expect(page.locator('ui5-dialog[header-text="Review approval packet"]')).toBeVisible();
  fixture.setReviewer(true);
  await page.reload();
  await page.getByRole('button', { name: 'Review packet', exact: true }).click();
  const review = page.locator('ui5-dialog[header-text="Review approval packet"]');
  await checkUi5Checkbox(review.getByRole('checkbox', { name: 'I reviewed this exact change and its source', exact: true }));
  await review.getByRole('button', { name: 'Grant approval', exact: true }).click();
  await expect(review.getByRole('note', { name: /The approval source changed/ })).toBeVisible();
  await expect(review.getByRole('button', { name: 'Grant approval', exact: true })).toHaveCount(0);
  await expect(review.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
  expect(fixture.packets[0].state).toBe('Stale');
  expect(fixture.packets[0].decisions).toHaveLength(0);
});


for (const status of [403, 404, 503] as const) {
  test(`document HTTP ${status} keeps approvals usable and offers only recoverable retries`, async ({ page }) => {
    const fixture = await mockWorkspace(page, { approvals: true, documentFailure: status });
    await page.goto(`/projects/${projects[0].id}`);
    const sources = page.getByRole('region').filter({ has: page.getByRole('heading', { name: 'Source documents', exact: true }) });
    await expect(sources.getByRole('alert')).toBeVisible();
    await expect(page.getByRole('button', { name: 'New task', exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Request status change', exact: true })).toBeEnabled();
    const retry = sources.getByRole('button', { name: 'Try again', exact: true });
    if (status === 503) {
      await expect(retry).toBeVisible();
      fixture.recoverDocuments();
      await retry.click();
      await expect(sources.getByRole('link', { name: 'Site coordination requirements', exact: true })).toBeVisible();
    } else {
      await expect(retry).toHaveCount(0);
      await expect(sources.getByRole('note', { name: status === 403 ? /You don’t have access to this item/ : /This item isn’t available/ })).toBeVisible();
    }
  });
}


test('shared approval inbox renders domain manifests without invented project status effects', async ({ page }) => {
  await mockWorkspace(page, { domainApproval: true }); await page.goto(`/projects/${projects[0].id}`);
  await expect(page.locator('ui5-table[accessible-name="Project approvals"]')).toContainText('Source page calibration');
  await page.getByRole('button', { name: 'Review packet', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Review approval packet"]');
  await expect(dialog).toContainText('Verify calibration');
  await expect(dialog).toContainText('Scale verification');
  await expect(dialog).toContainText('200.00');
  await expect(dialog.getByText('Status at request', { exact: true })).toHaveCount(0);
  await expect(dialog.getByText('Resulting completion', { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Execute approved change', exact: true })).toHaveCount(0);
});

test('desktop-to-phone resize closes the navigation overlay and phone selections return focusable content', async ({ page }) => {
  await mockWorkspace(page); await page.goto('/projects'); await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 1000 }); const layout = page.locator('ui5-navigation-layout'); await expect(layout).toHaveAttribute('side-collapsed', '');
  const heading = page.getByRole('heading', { name: 'Projects', exact: true }); const box = await heading.boundingBox(); expect(box).not.toBeNull();
  await expect.poll(() => page.evaluate(({ x, y }) => !document.elementFromPoint(x, y)?.closest('ui5-side-navigation'), { x: box!.x + Math.min(50, box!.width / 2), y: box!.y + box!.height / 2 })).toBe(true);
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click(); await expect(layout).not.toHaveAttribute('side-collapsed', '');
  await page.locator('ui5-side-navigation').getByText('Documents', { exact: true }).click(); await expect(page.getByRole('heading', { name: 'Documents', exact: true })).toBeVisible(); await expect(layout).toHaveAttribute('side-collapsed', '');
  await page.getByRole('button', { name: 'Open projects', exact: true }).focus(); await expect(page.getByRole('button', { name: 'Open projects', exact: true })).toBeFocused();
});

// Authored public assets must survive the source snapshot AND actual Vite build.
// A same-origin200 SPA fallback is not an image or a dependency notice.
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const builtProduct = process.env.CIPHER_BUILT_PRODUCT_DIST || fileURLToPath(new URL('../dist/', import.meta.url));
test('packaged static assets preserve exact SVG and dependency notice bytes', async ({ page, request }) => {
  for (const [name,mime] of [['cipher-mark.svg',/^image\/svg\+xml(?:;|$)/i],['THIRD_PARTY_NOTICES.txt',/^text\/plain(?:;|$)/i]] as const) {
    const expected = await readFile(new URL(`../public/${name}`,import.meta.url));
    expect(await readFile(path.join(builtProduct,name))).toEqual(expected);
    const response = await request.get(`/${name}`);expect(response.status()).toBe(200);expect(response.headers()['content-type']).toMatch(mime);
    const bytes = await response.body();expect(bytes).toEqual(expected);expect(bytes.toString().trimStart()).not.toMatch(/^(?:<!doctype\s+html|<html)/i);
  }
  await mockWorkspace(page,{login:true});await page.goto('/projects');const signInLogo=page.locator('.sign-in-brand img');await expect(signInLogo).toBeVisible();await expect.poll(()=>signInLogo.evaluate(async image=>{await (image as HTMLImageElement).decode();return (image as HTMLImageElement).naturalWidth;})).toBeGreaterThan(0);
  await page.getByLabel('Email or username',{exact:true}).fill('test.pm@example.invalid');await page.getByLabel('Password',{exact:true}).fill('fixture-password-only');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByRole('heading',{name:'Projects',exact:true})).toBeVisible();const shellLogo=page.locator('ui5-shellbar-branding img');await expect(shellLogo).toBeVisible();await expect.poll(()=>shellLogo.evaluate(async image=>{await (image as HTMLImageElement).decode();return (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth>0;})).toBe(true);
});
