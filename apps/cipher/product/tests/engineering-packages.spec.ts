import { test, expect, type Page } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { document, hash, mockEngineeringPackages, packagePath, people, scope, unit } from './engineering-packages-fixture';
type Fixture = Awaited<ReturnType<typeof mockEngineeringPackages>>;
const title = 'East stair structural design';
async function choose(page: Page, name: string, option: string) { await page.getByRole('combobox', { name, exact: true }).click(); await page.getByRole('option', { name: option, exact: true }).click(); }
const reviewed = (page: Page) => checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the package revision and sources', exact: true }));
async function assignment(page: Page) {
  await page.getByRole('button', { name: 'New work package', exact: true }).click();
  await page.getByRole('textbox', { name: 'Package title', exact: true }).fill(title);
  await page.getByRole('textbox', { name: 'Engineering discipline', exact: true }).fill('Structural');
  await page.getByRole('textbox', { name: 'Engineering scope', exact: true }).fill('Design the east stair landing and retain the exact engineering basis.');
  await choose(page, 'Responsible engineer', people[0].display_name);
  await choose(page, 'Required independent checker', people[1].display_name);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the package assignments', exact: true }));
}
async function createPackage(page: Page, fixture: Fixture) {
  await assignment(page); await page.getByRole('button', { name: 'Save work package', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open saved work package', exact: true })).toBeEnabled();
  const id = [...fixture.records.get('package')!.keys()][0]; await page.getByRole('button', { name: 'Open saved work package', exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible(); return id;
}
async function revisionTitle(page: Page, name: string) { await page.getByRole('textbox', { name: 'Revision title', exact: true }).fill(name); await page.getByRole('textbox', { name: 'Change reason', exact: true }).fill('Initial exact engineering record.'); }
async function attach(page: Page, drawing: boolean) {
  await choose(page, 'Engineering project source', `${document.title} · Rev. 1`);
  if (drawing) { await page.getByRole('textbox', { name: 'Drawing location or detail', exact: true }).fill('Grid B/4, detail 3'); await page.getByRole('button', { name: 'Attach drawing reference', exact: true }).click(); }
  else await page.getByRole('button', { name: 'Attach submission document', exact: true }).click();
}
async function quantity(page: Page, key: string, label: string, amount: string, retained = false) {
  await page.getByRole('button', { name: 'Add quantity', exact: true }).click();
  await page.getByRole('textbox', { name: 'Quantity key 1', exact: true }).fill(key); await page.getByRole('textbox', { name: 'Quantity label 1', exact: true }).fill(label); await page.getByRole('textbox', { name: 'Exact quantity 1', exact: true }).fill(amount);
  await choose(page, 'Quantity unit 1', 'm · length · 6 decimals');
  await choose(page, 'Quantity source 1', `${retained ? 'Drawing' : document.title} · Rev. 1 · Page 1 · Grid B/4, detail 3`);
}
async function basis(page: Page, rawPdf = false) {
  await page.getByRole('button', { name: 'Create design basis', exact: true }).click(); await revisionTitle(page, 'Landing design basis');
  await page.getByRole('textbox', { name: 'Design criteria', exact: true }).fill('Use the exact landing span from the retained drawing.');
  await page.getByRole('button', { name: 'Add design code', exact: true }).click();
  await page.getByRole('textbox', { name: 'Design code 1', exact: true }).fill('ASCE 7'); await page.getByRole('textbox', { name: 'Code edition 1', exact: true }).fill('2022'); await page.getByRole('textbox', { name: 'Code clause 1', exact: true }).fill('4');
  await attach(page, true);
  if (rawPdf) { await page.getByRole('button', { name: 'View stored drawing', exact: true }).click(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible(); }
  await quantity(page, 'span', 'Landing span', '4.250000'); await reviewed(page); await page.getByRole('button', { name: 'Save basis revision', exact: true }).click(); await expect(page.getByRole('button', { name: 'Record calculation', exact: true })).toBeEnabled();
}
async function check(page: Page, fixture: Fixture) {
  const packetId = [...fixture.packets.keys()].at(-1)!;
  await expect(page.getByRole('button', { name: 'Grant independent check', exact: true })).toHaveCount(0);
  fixture.setActor(1); await page.goto(`${packagePath}/approvals/${packetId}`);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the exact engineering check', exact: true })); await page.getByRole('button', { name: 'Grant independent check', exact: true }).click();
  await expect.poll(() => fixture.packets.get(packetId).state).toBe('Granted'); await expect(page.getByRole('button', { name: 'Close package check', exact: true })).toBeEnabled();
  fixture.setActor(0); await page.reload(); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the exact engineering check', exact: true })); await page.getByRole('button', { name: 'Record independent check', exact: true }).click();
  await expect.poll(() => fixture.packets.get(packetId).state).toBe('Consumed'); await expect(page.getByRole('button', { name: 'Close package check', exact: true })).toBeEnabled();
}
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));
test('package-only engineer authors exact basis, manual calculation and deliverable with independent checks', async ({ page }) => {
  test.setTimeout(90000);
  const fixture = await mockEngineeringPackages(page); await page.goto(packagePath); const id = await createPackage(page, fixture); await basis(page, true);
  await page.getByRole('button', { name: 'Request independent check', exact: true }).click(); await check(page, fixture);
  await page.goto(`${packagePath}/${id}`); await page.getByRole('button', { name: 'Record calculation', exact: true }).click(); await revisionTitle(page, 'Landing span calculation');
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'Use design input span', exact: true }));
  for (const [name, value] of [['Equation or algorithm reference', 'Span verification note 1'], ['Calculation tool name', 'Engineer worksheet'], ['Calculation tool version', '1.0'], ['Calculation explanation', 'Human calculation recorded against the exact basis.']]) await page.getByRole('textbox', { name, exact: true }).fill(value);
  await attach(page, false); await quantity(page, 'verified_span', 'Verified span', '4.250000', true); await reviewed(page); await page.getByRole('button', { name: 'Save calculation revision', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Landing span calculation', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Request independent check', exact: true }).click(); await check(page, fixture);
  await page.goto(`${packagePath}/${id}`); await page.getByRole('button', { name: 'Prepare deliverable', exact: true }).click(); await revisionTitle(page, 'East stair design package');
  await page.getByRole('textbox', { name: 'Deliverable type', exact: true }).fill('Engineering calculation package'); await page.getByRole('textbox', { name: 'Deliverable description', exact: true }).fill('Exact landing calculation and retained drawing.');
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'Include calculation Landing span calculation', exact: true })); await attach(page, true); await reviewed(page); await page.getByRole('button', { name: 'Save deliverable revision', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'East stair design package', exact: true })).toBeVisible(); await page.getByRole('button', { name: 'Request independent check', exact: true }).click(); await check(page, fixture);
  const b = [...fixture.records.get('basis')!.values()][0], c = [...fixture.records.get('calculation')!.values()][0], d = [...fixture.records.get('deliverable')!.values()][0];
  expect(c.inputs).toEqual(b.quantities); expect(c.inputs[0].quantity).toEqual({ amount: '4.250000', unit_id: unit.id, precision: 6 }); expect(c.execution).toEqual({ kind: 'manual-record', executed_by_cipher: false, solver_qualified: false }); expect(d.calculations).toEqual([{ id: c.id, record_digest: hash(c) }]); expect(d.issue_readiness).toBe('not_authorized_for_issue');
  expect(fixture.records.get('check')!.size).toBe(3); expect([...fixture.records.get('check')!.values()].every(row => row.comments === '' && !row.issue_authorized && !row.sealed)).toBe(true); expect(fixture.writes.every(row => row.key === row.body.operation_id)).toBe(true);
});
for (const loss of ['loseFirst', 'wrongFirst'] as const) test(`original package UUID remains recoverable after ${loss}`, async ({ page }) => {
  const fixture = await mockEngineeringPackages(page, { [loss]: true }); await page.goto(packagePath); await assignment(page); await page.getByRole('button', { name: 'Save work package', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="New engineering work package"]'); await expect(dialog.getByRole('button', { name: 'Recover original package request', exact: true })).toBeEnabled(); await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Recover original package request', exact: true }).click(); await expect(dialog).not.toBeVisible(); expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1].body).toEqual(fixture.writes[0].body); expect(fixture.records.get('package')!.size).toBe(1);
});
test('assignment revisions retain history and require a current basis for new calculation or checking', async ({ page }) => {
  const fixture = await mockEngineeringPackages(page); await page.goto(packagePath); const id = await createPackage(page, fixture); await basis(page);
  const original = [...fixture.records.get('basis')!.values()][0]; await page.getByRole('button', { name: 'Revise scope and assignments', exact: true }).click(); await page.getByRole('textbox', { name: 'Engineering scope', exact: true }).fill('Revised landing scope requiring a new exact basis.'); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the package assignments', exact: true })); await page.getByRole('button', { name: 'Save work package', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Record calculation', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Prepare deliverable', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: 'Request independent check', exact: true })).toHaveCount(0); await expect(page.getByRole('heading', { name: 'Landing design basis', exact: true })).toBeVisible();
  await page.goto(`${packagePath}/record/basis/${original.id}`); await expect(page.getByRole('heading', { name: 'Landing design basis', exact: true })).toBeVisible(); expect(fixture.records.get('basis')!.get(original.id)).toEqual(original); expect(fixture.records.get('package')!.get(id).basis_head).toBe(original.id);
});
test('designated checker can return a revision with blank comments', async ({ page }) => {
  const fixture = await mockEngineeringPackages(page); await page.goto(packagePath); await createPackage(page, fixture); await basis(page); await page.getByRole('button', { name: 'Request independent check', exact: true }).click();
  const packetId = [...fixture.packets.keys()][0]; fixture.setActor(2); await page.goto(`${packagePath}/approvals/${packetId}`); await expect(page.getByRole('button', { name: 'Grant independent check', exact: true })).toHaveCount(0);
  fixture.setActor(1); await page.reload(); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the exact engineering check', exact: true })); await page.getByRole('button', { name: 'Return for revision', exact: true }).click(); await expect(page.getByRole('button', { name: 'Close package check', exact: true })).toBeEnabled(); await expect.poll(() => fixture.packets.get(packetId).state).toBe('Rejected'); expect(fixture.packets.get(packetId).decisions[0].reason).toBe(''); expect(fixture.records.get('check')?.size || 0).toBe(0);
});
for (const source of ['people', 'units', 'drawing'] as const) test(`${source} access denial removes package authoring authority`, async ({ page }) => {
  const fixture = await mockEngineeringPackages(page); await page.goto(packagePath);
  if (source === 'people') { await page.route('**/api/method/cipher_aec.engineering_packages.api.list_people*', route => route.fulfill({ status: 403 })); await page.getByRole('button', { name: 'New work package', exact: true }).click(); }
  else { await createPackage(page, fixture); if (source === 'units') await page.route('**/api/method/cipher_aec.engineering_packages.api.list_units*', route => route.fulfill({ status: 403 })); await page.getByRole('button', { name: 'Create design basis', exact: true }).click(); if (source === 'drawing') { await attach(page, true); await page.route('**/api/method/cipher_aec.documents.api.download_revision*', route => route.fulfill({ status: 403 })); await page.getByRole('button', { name: 'View stored drawing', exact: true }).click(); } }
  await expect(page.getByRole('button', { name: 'Recheck work package access', exact: true })).toBeVisible(); await expect(page.locator('ui5-dialog[header-text="New engineering work package"], ui5-dialog[header-text="New design basis version"]')).toHaveCount(0); expect(fixture.records.get('basis')?.size || 0).toBe(0);
});
for (const width of [1440, 900, 390]) test(`work-package assignment remains usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); const fixture = await mockEngineeringPackages(page); await page.goto(packagePath); await assignment(page); const save = page.getByRole('button', { name: 'Save work package', exact: true }); await expect(save).toBeInViewport(); const box = await save.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width); await save.click(); await expect(page.getByRole('button', { name: 'Open saved work package', exact: true })).toBeEnabled(); expect(fixture.records.get('package')!.size).toBe(1);
});
