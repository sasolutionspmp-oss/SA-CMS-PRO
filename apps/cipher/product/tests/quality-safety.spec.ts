import { expect, test, type Page } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { document, mockQuality, people, qualityPath } from './quality-safety-fixture';

async function choose(page: Page, label: string, option: string) { await page.getByRole('combobox', { name: label, exact: true }).click(); await page.getByRole('option', { name: option, exact: true }).click(); }
async function evidence(page: Page, label: string) { await choose(page, label, `${document.title} · Rev. 1`); await page.getByRole('textbox', { name: label + ' locator', exact: true }).fill('Exact documentary observation'); await page.getByRole('button', { name: 'Attach ' + label.toLowerCase(), exact: true }).click(); }
async function newRecord(page: Page) { await page.getByRole('button', { name: 'New record', exact: true }).click(); await fields(page); await evidence(page, 'Record evidence'); }
async function fields(page: Page) { for (const [label, value] of Object.entries({ 'Record title': 'Reviewed synthetic inspection', 'Record date': '2026-10-17', 'Work location': 'East wall', Description: 'Recorded the exact source observation.', 'Closure item 1': 'Retain exact closure evidence' })) await page.getByRole('textbox', { name: label, exact: true }).fill(value); }
async function save(page: Page) { await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the quality record', exact: true })); await page.getByRole('button', { name: 'Save record', exact: true }).click(); }
async function action(page: Page, comment: string) { await page.getByRole('textbox', { name: 'Quality decision comment', exact: true }).fill(comment); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the exact quality decision', exact: true })); await page.getByRole('button', { name: 'Record action', exact: true }).click(); }
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));

test('normal App Quality record uses independent checker and third closer, then preserves a closed original during amendment', async ({ page }) => {
  test.setTimeout(90000); const fixture = await mockQuality(page); await page.goto(qualityPath()); await newRecord(page); await save(page);
  await page.getByRole('button', { name: 'Open saved record', exact: true }).click();
  const header = [...fixture.records.get('record')!.values()][0], original = fixture.get('revision', header.current_revision);
  await action(page, 'Submit exact immutable revision.'); await expect.poll(() => fixture.get('record', header.id).status).toBe('submitted');
  fixture.setActor(3); await page.reload(); await expect(page.getByRole('note', { name: /canonical person separation/ })).toBeVisible(); await expect(page.getByRole('button', { name: 'Record action', exact: true })).toHaveCount(0);
  fixture.setActor(1); await page.reload(); await evidence(page, 'Decision evidence'); await action(page, 'Independent documentary check.'); await expect.poll(() => fixture.get('record', header.id).status).toBe('checked');
  await expect(page.getByRole('option', { name: 'Close documentary record', exact: true })).toHaveCount(0);
  fixture.setActor(2); await page.reload(); await evidence(page, 'Closure evidence 1'); await action(page, 'Third person documentary closure.'); await expect.poll(() => fixture.get('record', header.id).status).toBe('closed');
  fixture.setActor(0); await page.reload(); await page.getByRole('button', { name: 'Amend closed record', exact: true }).click(); await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Explicit successor corrects the observation.'); await page.getByRole('textbox', { name: 'Amendment reason', exact: true }).fill('Correct the documentary observation with retained sources.'); await save(page);
  const updated = fixture.get('record', header.id), amended = fixture.get('revision', updated.current_revision);
  expect(updated).toMatchObject({ revision_number: 2, status: 'draft', closed_revision: original.id }); expect(amended).toMatchObject({ predecessor: original.id, amendment_of: original.id }); expect(fixture.get('revision', original.id)).toEqual(original); expect(Object.values(amended.no_effects)).toEqual(Array(13).fill(false)); expect(fixture.writes.every(row => row.key === row.body.operation_id)).toBe(true);
  await page.getByRole('button', { name: 'Open saved record', exact: true }).click(); await page.getByRole('button', { name: 'Read revision 1', exact: true }).click(); await expect(page.getByText(original.definition.description, { exact: true })).toBeVisible(); await expect(page.getByRole('note', { name: /immutable historical revision/ })).toBeVisible();
});
for (const loss of ['loseFirst','wrongFirst'] as const) test(`Quality original request recovery retains context locks after ${loss} and later denial`, async ({ page }) => {
  const fixture = await mockQuality(page, { [loss]: true }); await page.goto(qualityPath()); await newRecord(page); await save(page);
  const recover = page.getByRole('button', { name: 'Recover original quality request', exact: true }); await expect(recover).toBeEnabled();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeDisabled();
  await page.getByRole('treeitem', { name: 'Connections', exact: true }).click(); await expect(page).toHaveURL(new RegExp(qualityPath() + '$'));
  fixture.setDenied(403); await recover.click(); await expect(recover).toBeEnabled(); await expect(page.getByText('SENSITIVE SERVER REASON MUST NEVER BE SHOWN', { exact: true })).toHaveCount(0); await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveCount(0);
  fixture.setDenied(0); await recover.click(); await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeVisible(); expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1]).toEqual(fixture.writes[0]); expect(fixture.records.get('record')!.size).toBe(1);
});
for (const status of [403,404]) test(`Quality current ${status} hides cached sensitive account, history, evidence and server reason`, async ({ page }) => {
  const fixture = await mockQuality(page), seed = fixture.seed('incident'); await page.goto(qualityPath('incident', seed.header.id));
  await expect(page.getByText('Sensitive synthetic incident account', { exact: true })).toBeVisible(); fixture.setDenied(status); await page.getByRole('button', { name: 'Refresh record', exact: true }).click();
  await expect(page.getByText('Sensitive synthetic incident account', { exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'View original evidence', exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'Record action', exact: true })).toHaveCount(0); await expect(page.getByText('SENSITIVE SERVER REASON MUST NEVER BE SHOWN', { exact: true })).toHaveCount(0); await expect(page.getByRole('note', { name: /Access unavailable/ })).toBeVisible();
});
for (const invalid of ['unfilteredTotal','crossFamily'] as const) test(`ordinary register refuses ${invalid} without displaying incident content or counts`, async ({ page }) => {
  const fixture = await mockQuality(page, { [invalid]: true }); fixture.seed('incident'); await page.goto(qualityPath());
  await expect(page.getByRole('note', { name: /request could not be verified/ })).toBeVisible(); await expect(page.getByText(/PRIVATE-INCIDENT|Sensitive synthetic|888/)).toHaveCount(0);
  expect(fixture.reads.every(row => row.kind === 'record' && row.count_mode === 'none' && row.limit === '25')).toBe(true);
});
test('restricted incident private upload, source attachment and saved record stay online and outside ordinary history', async ({ page }) => {
  const fixture = await mockQuality(page); await page.goto(qualityPath('incident')); await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await fields(page);
  for (const [label,value] of Object.entries({ 'People as recorded, one per line': 'Synthetic Person', 'Restricted account': 'Private synthetic account', 'Immediate response': 'Synthetic first response' })) await page.getByRole('textbox', { name: label, exact: true }).fill(value);
  await page.getByLabel('Private evidence file', { exact: true }).setInputFiles({ name: 'private-observation.txt', mimeType: 'text/plain', buffer: Buffer.from('Private fixture evidence bytes') });
  for (const [label,value] of Object.entries({ 'Private evidence title': 'Private original', 'Private evidence rights basis': 'Synthetic permission fixture only', 'Private evidence locator': 'Private source paragraph 1' })) await page.getByRole('textbox', { name: label, exact: true }).fill(value);
  await evidence(page, 'Upload permission evidence'); await page.getByRole('button', { name: 'Upload private original', exact: true }).click(); await expect(page.getByRole('note', { name: /Private evidence saved and attached/ })).toBeVisible(); await save(page);
  await page.getByRole('button', { name: 'Open saved record', exact: true }).click(); await expect(page.getByText('Private synthetic account', { exact: true })).toBeVisible(); await page.getByRole('button', { name: 'View original evidence', exact: true }).click(); await expect(page.getByText('Private fixture evidence bytes', { exact: true })).toBeVisible();
  expect(fixture.writes.map(row => row.method)).toEqual(['upload_evidence','create_record']); expect([...fixture.receipts.values()].every(row => row.history_id === null)).toBe(true); expect(fixture.records.has('record')).toBe(false); expect(fixture.uploads.size).toBe(1);
  const browserStorage = await page.evaluate(() => ({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })); expect(JSON.stringify(browserStorage)).not.toMatch(/Private synthetic|Private fixture|restricted_account/);
});
test('stale Quality successor preserves inputs and requires fresh review rather than automatic rebasing', async ({ page }) => {
  const fixture = await mockQuality(page, { staleFirst: true }), seed = fixture.seed(); await page.goto(qualityPath('record', seed.header.id)); await page.getByRole('button', { name: 'Create revision', exact: true }).click(); await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Preserved corrected observation'); await save(page);
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Preserved corrected observation'); await expect(page.getByRole('button', { name: 'Save record', exact: true })).toBeDisabled(); await expect(page.getByText(/Your inputs are retained/)).toBeVisible(); expect(fixture.get('record', seed.header.id)).toEqual(seed.header);
});
for (const width of [1440,900,390]) test(`actual App Quality record remains readable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); const fixture = await mockQuality(page), seed = fixture.seed(); await page.goto(qualityPath('record', seed.header.id)); await expect(page.getByRole('heading', { name: 'East wall inspection', exact: true })).toBeVisible(); expect(await page.evaluate(() => window.document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.screenshot({ path: `test-results/quality-safety/synthetic-quality-${width}.png`, fullPage: true });
});
