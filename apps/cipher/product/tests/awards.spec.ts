import { expect, test, type Page } from '@playwright/test';
import { awardIssue, mockAward } from './award-fixture';
import { company } from './fixture';
const path = `/commercial/issues/${awardIssue}/award?company=${company}`;
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));

test('award workspace preserves a copied second Company through sign-in without Project reads or implicit team membership', async ({ page }) => {
  const fixture = await mockAward(page, { secondCompany: 'TEST-SECOND-COMPANY', login: true }); const projects: string[] = []; page.on('request', request => { if (/cipher_aec\.api\.v1\.projects?\b/.test(request.url())) projects.push(request.url()); });
  await page.goto(`/commercial/issues/${awardIssue}/award?company=TEST-SECOND-COMPANY`);
  await page.getByLabel('Email or username', { exact: true }).fill('author@example.invalid'); await page.getByLabel('Password', { exact: true }).fill('explicit-test-only'); await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toHaveValue('Cedar Valley award');
  expect(fixture.reads.every(url => url.searchParams.get('company') === 'TEST-SECOND-COMPANY')).toBe(true); expect(projects).toEqual([]); expect(fixture.definition.team.members.map(member => member.person_id)).not.toContain('TEST-PERSON-001');
  await expect(page.getByRole('button', { name: /Execute.*award|Request.*award/i })).toHaveCount(0);
  await expect(page.getByRole('note', { name: /Award execution awaits runtime qualification/ })).toBeVisible();
});
test('foreign Company award link fails before any award source request', async ({ page }) => {
  const fixture = await mockAward(page); await page.goto(`/commercial/issues/${awardIssue}/award?company=FOREIGN-COMPANY`); await expect(page.getByRole('heading', { name: 'Company context unavailable', exact: true })).toBeVisible(); expect(fixture.reads).toEqual([]); expect(fixture.writes).toEqual([]);
});
test('selecting reviewed cost revisions requires cost read access without cost-master write authority', async ({ page }) => {
  const fixture = await mockAward(page, { costReadOnly: true }); await page.goto(path); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toBeEnabled(); await expect(page.getByRole('button', { name: 'Save award plan', exact: true })).toBeEnabled(); expect(fixture.writes).toEqual([]);
});
test('unqualified original estimate input blocks new award authoring without treating its ordinary Issue PDF as a cause', async ({ page }) => {
  const fixture = await mockAward(page, { unqualified: true }); await page.goto(path);
  await expect(page.getByRole('note', { name: /accepted estimate contains an unqualified generated input/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save award plan', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Check award plan', exact: true })).toBeDisabled();
  await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toBeDisabled(); expect(fixture.writes).toEqual([]);
});
test('explicit award source denial removes retained source/editor content and offers no permission retry', async ({ page }) => {
  const fixture = await mockAward(page); await page.goto(path); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toBeVisible(); fixture.deny(403);
  await page.getByRole('button', { name: 'Refresh award sources', exact: true }).click(); await expect(page.getByRole('note', { name: /Your current permissions/ }).first()).toBeVisible(); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0); expect(fixture.writes).toEqual([]);
});
test('saved historical award facts remain visible when current authoring policy is unavailable', async ({ page }) => {
  const fixture = await mockAward(page, { policyDenied: true }); await page.goto(path);
  await expect(page.getByRole('region', { name: 'Frozen award plan review' })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Cedar Valley award · Plan revision 1', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save award plan', exact: true })).toHaveCount(0); expect(fixture.writes).toEqual([]);
});
test('award save preserves source decimal strings and identities while the server check remains read-only', async ({ page }) => {
  const fixture = await mockAward(page); await page.goto(path); const name = page.getByRole('textbox', { name: 'Project name', exact: true }); await expect(name).toHaveValue('Cedar Valley award'); await name.fill('Cedar Valley construction');
  await page.getByRole('button', { name: 'Check award plan', exact: true }).click(); await expect(page.getByRole('heading', { name: 'Validated plan', exact: true })).toBeVisible(); expect(fixture.writes).toEqual([]);
  await expect(page.locator('ui5-table[accessible-name="Accepted award cost allocations"]')).toContainText('100.123456789');
  await page.getByRole('button', { name: 'Save award plan', exact: true }).click(); await expect(page.getByRole('note', { name: /Award plan revision 2 saved/ })).toBeVisible();
  const definition = fixture.writes[0].body.definition as typeof fixture.definition; expect(definition.contract_definition.original_value.amount).toBe('125.00'); expect(definition.budget_allocations).toEqual(fixture.definition.budget_allocations); expect(definition.budget_allocations[0]).not.toHaveProperty('amount'); expect(definition.project_definition.project_name).toBe('Cedar Valley construction');
});
for (const fault of ['lost', 'wrong-subject', 'wrong-lineage'] as const) test(`award ${fault} result keeps the exact pending save through later412 and recovers one effect`, async ({ page }) => {
  const fixture = await mockAward(page, { lost: fault === 'lost', wrongSubject: fault === 'wrong-subject', wrongLineage: fault === 'wrong-lineage', later412: true }); await page.goto(path);
  const name = page.getByRole('textbox', { name: 'Project name', exact: true }); await expect(name).toHaveValue('Cedar Valley award'); await name.fill('Preserved award intent'); await page.getByRole('button', { name: 'Save award plan', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover award plan', exact: true }); await expect(recover).toBeEnabled(); await expect(name).toBeDisabled(); await expect(page.getByRole('button', { name: 'Refresh award sources', exact: true })).toBeDisabled(); await recover.click();
  await expect(page.getByRole('note', { name: /Award source changed/ })).toBeVisible(); await expect(recover).toBeEnabled(); await expect(name).toBeDisabled(); await expect(page.getByRole('button', { name: 'Load current award handoff', exact: true })).toHaveCount(0);
  await recover.click(); await expect(page.getByRole('note', { name: /Original operation recovered/ })).toBeVisible(); expect(fixture.writes).toHaveLength(3); expect(new Set(fixture.writes.map(write => write.raw)).size).toBe(1); expect(new Set(fixture.writes.map(write => write.key)).size).toBe(1); expect(fixture.effects()).toBe(1);
});
test('dated cost selection uses the effective revision instead of a future authoring head', async ({ page }) => {
  const fixture = await mockAward(page); await page.goto(path); const table = page.locator('ui5-table[accessible-name="Accepted award cost allocations"]'); await table.getByRole('button', { name: 'Saved cost code revision', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="Choose cost code"]'); await expect(dialog.getByText('Site works', { exact: true })).toBeVisible(); await dialog.getByRole('button', { name: 'Select cost code SITE', exact: true }).click();
  await page.getByRole('button', { name: 'Save award plan', exact: true }).click(); await expect(page.getByRole('note', { name: /Award plan revision 2 saved/ })).toBeVisible(); const definition = fixture.writes[0].body.definition as typeof fixture.definition; expect(definition.budget_allocations[0].code_revision_id).toBe(fixture.codeId); expect(definition.budget_allocations[0].code_revision_id).not.toBe(fixture.futureHead); const request = fixture.reads.find(url => url.pathname.endsWith('list_masters'))!; expect(request.searchParams.get('basis_date')).toBe('2026-10-15');
});
test('definitive stale award preserves authored fields for an explicit reviewed version', async ({ page }) => {
  const fixture = await mockAward(page, { stale: true }); await page.goto(path); const name = page.getByRole('textbox', { name: 'Project name', exact: true }); await expect(name).toHaveValue('Cedar Valley award'); await name.fill('Preserved concurrent award'); await page.getByRole('button', { name: 'Save award plan', exact: true }).click();
  await page.getByRole('button', { name: 'Load current award handoff', exact: true }).click(); await expect(page.getByRole('region', { name: 'Frozen award plan review' }).first()).toBeVisible(); await page.getByRole('checkbox', { name: 'I reviewed the current saved award handoff', exact: true }).check(); await page.getByRole('button', { name: 'Use reviewed handoff version', exact: true }).click(); await expect(name).toHaveValue('Preserved concurrent award');
  await page.getByRole('button', { name: 'Save award plan', exact: true }).click(); await expect(page.getByRole('note', { name: /Award plan revision 2 saved/ })).toBeVisible(); expect(fixture.writes[1].body.expected_version).toBe('f'.repeat(64));
});
test('rebase refuses a fetched current plan from another handoff while keeping authored input', async ({ page }) => {
  const fixture = await mockAward(page, { stale: true, wrongRebase: true }); await page.goto(path); const name = page.getByRole('textbox', { name: 'Project name', exact: true }); await expect(name).toHaveValue('Cedar Valley award'); await name.fill('Preserved exact award'); await page.getByRole('button', { name: 'Save award plan', exact: true }).click(); await page.getByRole('button', { name: 'Load current award handoff', exact: true }).click();
  await expect(page.getByRole('note', { name: /current saved plan does not match the reviewed handoff/ })).toBeVisible(); await expect(page.getByRole('button', { name: 'Use reviewed handoff version', exact: true })).toBeDisabled(); await expect(name).toHaveValue('Preserved exact award'); expect(fixture.effects()).toBe(0);
});
test('rebase rejects a wrong root handoff even when its returned plan consistently matches that wrong root', async ({ page }) => {
  const fixture = await mockAward(page, { stale: true, wrongRoot: true }); await page.goto(path); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toHaveValue('Cedar Valley award'); await page.getByRole('button', { name: 'Save award plan', exact: true }).click(); await page.getByRole('button', { name: 'Load current award handoff', exact: true }).click();
  await expect(page.getByRole('note', { name: /current handoff does not match this award workspace/ })).toBeVisible(); await expect(page.getByRole('button', { name: 'Use reviewed handoff version', exact: true })).toHaveCount(0); expect(fixture.effects()).toBe(0);
});
test('a prior preview412 cannot rebase the local version during an in-flight save', async ({ page }) => {
  const fixture = await mockAward(page, { previewStale: true, holdSave: true }); await page.goto(path); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toHaveValue('Cedar Valley award'); await page.getByRole('button', { name: 'Check award plan', exact: true }).click(); await page.getByRole('button', { name: 'Load current award handoff', exact: true }).click(); await page.getByRole('checkbox', { name: 'I reviewed the current saved award handoff', exact: true }).check();
  const rebase = page.getByRole('button', { name: 'Use reviewed handoff version', exact: true }); await expect(rebase).toBeEnabled(); await page.getByRole('button', { name: 'Save award plan', exact: true }).click(); await expect(rebase).toBeDisabled(); await expect(page.getByRole('checkbox', { name: 'I reviewed the current saved award handoff', exact: true })).toBeDisabled(); fixture.releaseSave(); await expect(page.getByRole('note', { name: /Award plan revision 2 saved/ })).toBeVisible(); expect(fixture.effects()).toBe(1);
});
test('unknown handoff creation recovers its same key instead of reserving a second handoff', async ({ page }) => {
  const fixture = await mockAward(page, { noHandoff: true, lost: true, later412: true }); await page.goto(path); await page.getByRole('button', { name: 'Start award handoff', exact: true }).click(); const recover = page.getByRole('button', { name: 'Recover award handoff', exact: true }); await expect(recover).toBeEnabled(); await recover.click(); await expect(recover).toBeEnabled(); await recover.click(); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toBeVisible(); expect(fixture.effects()).toBe(1); expect(new Set(fixture.writes.map(write => write.raw)).size).toBe(1);
});
for (const width of [1440, 900, 390]) test(`award inputs, cost identity and keyboard stay inside workspace at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockAward(page); await page.goto(path); const name = page.getByRole('textbox', { name: 'Project name', exact: true }); await expect(name).toHaveValue('Cedar Valley award');
  await expect.poll(() => page.locator('.workspace-main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
  for (const content of [name, page.getByRole('button', { name: 'Save award plan', exact: true }), page.locator('ui5-table[accessible-name="Accepted award cost allocations"]')]) { await expect(content).toBeVisible(); const box = await content.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1); }
  await name.focus(); await name.press('Tab'); await expect(page.getByRole('textbox', { name: 'Project start date', exact: true })).toBeFocused();
});
async function accessibleAwardReturn(page: Page, width: number) {
  const toolbar = page.getByRole('toolbar', { name: 'Award actions', exact: true }); await expect(toolbar).toBeVisible();
  const returnAction = page.getByRole('button', { name: 'Return to proposal', exact: true }); const more = page.getByRole('button', { name: 'More award actions', exact: true });
  await expect.poll(async () => { if (await returnAction.isVisible()) { const bounds = await returnAction.boundingBox(); return Boolean(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width); } return more.isVisible(); }).toBe(true);
  if (!await returnAction.isVisible()) { await more.focus(); await more.press('Enter'); await expect(returnAction).toBeVisible(); }
  const bounds = await returnAction.boundingBox(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
  return returnAction;
}
for (const width of [1440, 900, 390]) test(`award toolbar exposes first action within bounds with supported keyboard overflow at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockAward(page); await page.goto(path); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toHaveValue('Cedar Valley award');
  const returnAction = await accessibleAwardReturn(page, width); await returnAction.focus(); await returnAction.press('Enter'); await expect(page).toHaveURL(/\/commercial\/proposals\//);
});
test('desktop to phone resize preserves a visible save action and supported return navigation', async ({ page }) => {
  await mockAward(page); await page.goto(path); await expect(page.getByRole('textbox', { name: 'Project name', exact: true })).toHaveValue('Cedar Valley award'); await page.setViewportSize({ width: 390, height: 1000 });
  const save = page.getByRole('button', { name: 'Save award plan', exact: true }); await expect(save).toBeVisible(); const returnAction = await accessibleAwardReturn(page, 390); await returnAction.focus(); await returnAction.press('Enter'); await expect(page).toHaveURL(/\/commercial\/proposals\//);
});
