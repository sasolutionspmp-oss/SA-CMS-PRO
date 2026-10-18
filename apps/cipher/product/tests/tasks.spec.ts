import { expect, test, type Page } from '@playwright/test';
import { projects } from './fixture';
import { mockTasks, taskPeople } from './tasks-fixture';

async function openTask(page: Page) {
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('link', { name: 'Review temporary works requirements', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Project task"]');
  await expect(dialog.getByRole('heading', { name: 'Review temporary works requirements', exact: true })).toBeVisible();
  return dialog;
}

test('assign a current project person, save status, complete and reopen the saved task', async ({ page }) => {
  const fixture = await mockTasks(page);
  let dialog = await openTask(page);
  const people = dialog.getByRole('combobox', { name: 'Assigned to', exact: true });
  await people.click(); await page.getByRole('option', { name: taskPeople[1].display_name, exact: true }).click();
  await dialog.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(dialog.getByRole('note', { name: /Task saved\./ })).toBeVisible();
  await expect(dialog.getByRole('paragraph').filter({ hasText: 'Assigned to:' })).toContainText('Jordan Lee');
  await dialog.getByRole('button', { name: 'Close task', exact: true }).click();
  await page.reload();
  await page.getByRole('link', { name: fixture.task.subject, exact: true }).click(); dialog = page.locator('ui5-dialog[header-text="Project task"]');
  await expect(dialog.getByRole('paragraph').filter({ hasText: 'Assigned to:' })).toContainText('Jordan Lee');
  await dialog.getByRole('combobox', { name: 'Task status', exact: true }).click(); await page.getByRole('option', { name: 'Working', exact: true }).click();
  await dialog.getByRole('button', { name: 'Save status', exact: true }).click();
  await expect.poll(() => fixture.task.status).toBe('Working');
  await dialog.getByRole('button', { name: 'Mark complete', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Reopen task', exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Save assignment', exact: true })).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Reopen task', exact: true }).click();
  await expect.poll(() => fixture.task.status).toBe('Open');
  expect(fixture.task.assignees).toEqual([]); expect(fixture.effects()).toBe(4);
});

test('read-only project review shows saved assignment and no task change controls', async ({ page }) => {
  await mockTasks(page, { readOnly: true }); const dialog = await openTask(page);
  await expect(dialog.getByRole('paragraph').filter({ hasText: 'Assigned to:' })).toContainText('Alex Morgan');
  await expect(dialog.getByRole('combobox')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: /Save|Mark complete|Reopen/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'New task', exact: true })).toHaveCount(0);
});

test('update-only duty exposes status without a people selector', async ({ page }) => {
  await mockTasks(page, { updateOnly: true }); const dialog = await openTask(page);
  await expect(dialog.getByRole('combobox', { name: 'Task status', exact: true })).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: 'Assigned to', exact: true })).toHaveCount(0);
});

test('task loading keeps edits unavailable until current options arrive', async ({ page }) => {
  await mockTasks(page, { readDelay: 500 });
  await page.goto(`/projects/${projects[0].id}`);
  await page.getByRole('link', { name: 'Review temporary works requirements', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Project task"]');
  await expect(dialog.getByText('Loading task…', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Mark complete', exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Mark complete', exact: true })).toBeVisible();
});

test('unknown assignment recovers its original person without a second assignment', async ({ page }) => {
  const fixture = await mockTasks(page, { failure: 'lost' }); const dialog = await openTask(page);
  await dialog.getByRole('combobox', { name: 'Assigned to', exact: true }).click();
  await page.getByRole('option', { name: taskPeople[1].display_name, exact: true }).click();
  await dialog.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(dialog.getByRole('combobox', { name: 'Assigned to', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Recover task change', exact: true }).click();
  await expect(dialog.getByRole('note', { name: /The original task change was recovered\./ })).toBeVisible();
  expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1]).toEqual(fixture.writes[0]);
  expect(fixture.task.assignees).toEqual([taskPeople[1]]); expect(fixture.effects()).toBe(1);
});

test('stale task preserves selections until the latest saved task is explicitly reviewed', async ({ page }) => {
  const fixture = await mockTasks(page, { stale: true }); const dialog = await openTask(page);
  await dialog.getByRole('button', { name: 'Mark complete', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Refresh task', exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Mark complete', exact: true })).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Refresh task', exact: true }).click();
  await dialog.getByRole('button', { name: 'Use current task', exact: true }).click();
  await dialog.getByRole('button', { name: 'Mark complete', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Reopen task', exact: true })).toBeVisible();
  expect(fixture.writes).toHaveLength(2); expect(fixture.writes[0].body.expected_version).toBe('1'); expect(fixture.writes[1].body.expected_version).toBe('2');
  expect(fixture.writes[0].body.operation_id).not.toBe(fixture.writes[1].body.operation_id); expect(fixture.effects()).toBe(1);
});

for (const failure of ['lost', 'server', 'malformed', 'wrong-receipt', 'missing-task-fields'] as const) {
  test(`unknown ${failure} result locks the view and recovers the exact original status request`, async ({ page }) => {
    const fixture = await mockTasks(page, { failure }); const dialog = await openTask(page);
    await dialog.getByRole('button', { name: 'Mark complete', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Recover task change', exact: true })).toBeEnabled();
    await expect(dialog.getByRole('button', { name: 'Close task', exact: true })).toBeDisabled();
    await expect(dialog.getByRole('combobox', { name: 'Task status', exact: true })).toBeDisabled();
    await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeDisabled();
    await page.keyboard.press('Escape'); await expect(dialog).toBeVisible();
    fixture.denyRecovery(true);
    await dialog.getByRole('button', { name: 'Recover task change', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Recover task change', exact: true })).toBeEnabled();
    await expect(dialog.getByRole('button', { name: 'Close task', exact: true })).toBeDisabled();
    fixture.denyRecovery(false);
    await dialog.getByRole('button', { name: 'Recover task change', exact: true }).click();
    await expect(dialog.getByRole('note', { name: /The original task change was recovered\./ })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Close task', exact: true })).toBeEnabled();
    expect(fixture.writes).toHaveLength(3); expect(fixture.writes[1]).toEqual(fixture.writes[0]); expect(fixture.writes[2]).toEqual(fixture.writes[0]); expect(fixture.effects()).toBe(1);
  });
}

test('revoked task access removes the cached task body and assignment', async ({ page }) => {
  const fixture = await mockTasks(page); const dialog = await openTask(page); fixture.denyRead();
  await dialog.getByRole('button', { name: 'Close task', exact: true }).click();
  await page.getByRole('link', { name: fixture.task.subject, exact: true }).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByRole('heading', { name: fixture.task.subject, exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('paragraph').filter({ hasText: 'Assigned to:' })).toHaveCount(0);
  await expect(dialog.getByRole('combobox')).toHaveCount(0);
});

test('unreconciled native assignment is explicit and cannot be edited', async ({ page }) => {
  await mockTasks(page, { conflict: true }); const dialog = await openTask(page);
  await expect(dialog.getByRole('paragraph').filter({ hasText: 'Assigned to:' })).toContainText('Assignment needs review');
  await expect(dialog.getByRole('combobox')).toHaveCount(0);
});

for (const width of [1440, 900, 390]) {
  test(`task details remain usable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 }); await mockTasks(page); const dialog = await openTask(page);
    await expect(dialog.getByRole('button', { name: 'Mark complete', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`synthetic-contract-task-details-${width}.png`), fullPage: true });
  });
}
