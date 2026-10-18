import { test, expect, type Page } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { document, drawingInput, engineeringPath, mockEngineering, people, scope, rfiFixture, hash, noEffects } from './engineering-fixture';
async function select(page: Page, name: string, option: string) { await page.getByRole('combobox', { name, exact: true }).click(); await page.getByRole('option', { name: option, exact: true }).click(); }
async function question(page: Page) {
  await page.getByRole('button', { name: 'New RFI', exact: true }).click();
  await page.getByRole('textbox', { name: 'RFI subject', exact: true }).fill('Clarify landing connection');
  await page.getByRole('textbox', { name: 'Question', exact: true }).fill('Confirm the connection detail at the east stair landing.');
  await select(page, 'Engineering project source', `${document.title} · Rev. 1`);
  await page.getByRole('textbox', { name: 'Drawing location or detail', exact: true }).fill(drawingInput.locator);
  await page.getByRole('button', { name: 'Attach drawing reference', exact: true }).click();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the engineering inputs and exact sources', exact: true }));
}
async function saveQuestion(page: Page) { await question(page); await page.getByRole('button', { name: 'Save question', exact: true }).click(); await expect(page.getByRole('heading', { name: 'Clarify landing connection', exact: true }).first()).toBeVisible(); }
async function closeApproval(page: Page) { const close = page.getByRole('button', { name: 'Close authorization', exact: true }); if (await close.isVisible()) await close.click(); }
async function authorize(page: Page, f: Awaited<ReturnType<typeof mockEngineering>>, reviewer: number, executor: number) {
  const id = [...f.packets.keys()].at(-1)!;
  f.setActor(reviewer); await page.goto(`${engineeringPath}/approvals/${id}`);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this exact technical decision and its sources', exact: true }));
  await page.getByRole('button', { name: 'Grant independent authorization', exact: true }).click();
  await expect.poll(() => f.packets.get(id).state).toBe('Granted');
  await expect(page.getByRole('button', { name: 'Close authorization', exact: true })).toBeEnabled();
  f.setActor(executor); await page.reload();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this exact technical decision and its sources', exact: true }));
  await page.getByRole('button', { name: /Make technical decision official|Record internal distribution/, exact: true }).click();
  await expect.poll(() => f.packets.get(id).state).toBe('Consumed');
  await expect(page.getByRole('button', { name: 'Close authorization', exact: true })).toBeEnabled();
}
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));
test('RFI uses stored raw PDF, saves exact basis, authorizes independently and records internal distribution', async ({ page }) => {
  const f = await mockEngineering(page); await page.goto(`${engineeringPath}/rfis`); await question(page);
  await page.getByRole('button', { name: 'View stored drawing', exact: true }).click(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible();
  await page.getByRole('button', { name: 'Save question', exact: true }).click(); await expect(page.getByRole('button', { name: 'Write response', exact: true })).toBeVisible();
  const rfiId = [...f.records.get('rfi')!.keys()][0];
  expect(f.writes[0].body.drawing_references).toEqual([drawingInput]); expect(f.writes[0].body.source_citations).toEqual([]); expect(f.reads).not.toContain('preview_revision');
  await page.getByRole('button', { name: 'Write response', exact: true }).click(); await page.getByRole('textbox', { name: 'Technical answer', exact: true }).fill('Use detail 3/S-201 for the east landing connection.'); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the engineering inputs and exact sources', exact: true })); await page.getByRole('button', { name: 'Save working response', exact: true }).click();
  await page.getByRole('button', { name: 'Request independent authorization', exact: true }).click(); await expect(page.getByRole('button', { name: 'Grant independent authorization', exact: true })).toHaveCount(0);
  await authorize(page, f, 1, 0); await page.goto(`${engineeringPath}/rfis/${rfiId}`); await page.getByRole('button', { name: 'Prepare internal transmittal', exact: true }).click();
  await page.getByRole('textbox', { name: 'Transmittal purpose', exact: true }).fill('Coordinate the authorized landing response.'); await select(page, 'Internal recipients', people[1].display_name); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the engineering inputs and exact sources', exact: true })); await page.getByRole('button', { name: 'Save internal package', exact: true }).click();
  await page.getByRole('button', { name: 'Request internal distribution authorization', exact: true }).click(); await authorize(page, f, 2, 0);
  const tx = [...f.records.get('transmittal')!.values()][0], distribution = [...f.records.get('distribution')!.values()][0];
  expect(distribution.subject_id).toBe(tx.id); expect(distribution.package_digest).toBe(tx.package_digest); expect(distribution.external_delivery).toBe(false); expect(distribution.recipients).toEqual([{ user: people[1].user, person: people[1].person }]);
  await page.goto(`${engineeringPath}/transmittals/${tx.id}`); await expect(page.getByText('Internal distribution recorded', { exact: false }).first()).toBeVisible();
  expect(f.writes.every(row => row.key === row.body.operation_id)).toBe(true);
});
for (const loss of ['loseFirstReply', 'wrongFirstReply'] as const) test(`uncertain ${loss} stays recoverable inside modal and locks global navigation`, async ({ page }) => {
  const f = await mockEngineering(page, { [loss]: true }); await page.goto(`${engineeringPath}/rfis`); await question(page); await page.getByRole('button', { name: 'Save question', exact: true }).click();
  const dialog = page.locator('ui5-dialog[header-text="New RFI"]'); const recover = dialog.getByRole('button', { name: 'Recover original engineering request', exact: true }); await expect(recover).toBeEnabled();
  await expect(dialog.getByRole('textbox', { name: 'RFI subject', exact: true })).toBeDisabled(); await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled(); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  const before = page.url(); await page.evaluate(() => window.dispatchEvent(new PopStateEvent('popstate'))); await expect(page).toHaveURL(before);
  await recover.click(); await expect(dialog).not.toBeVisible(); await expect(page.getByRole('button', { name: 'Open saved engineering record', exact: true })).toBeEnabled();
  expect(f.writes).toHaveLength(2); expect(f.writes[1].body).toEqual(f.writes[0].body); expect(f.records.get('rfi')?.size).toBe(1);
});
test('submittal selects exact package and designated reviewer; blank review comments remain valid', async ({ page }) => {
  const f = await mockEngineering(page); await page.goto(`${engineeringPath}/submittals`); await page.getByRole('button', { name: 'New submittal', exact: true }).click();
  await page.getByRole('textbox', { name: 'Submittal title', exact: true }).fill('Pump P-101 shop drawings'); await page.getByRole('textbox', { name: 'Specification section', exact: true }).fill('43 21 13'); await page.getByRole('textbox', { name: 'Submitting contractor', exact: true }).fill('Synthetic Mechanical Contractor'); await select(page, 'Designated reviewer', people[1].display_name); await select(page, 'Engineering project source', `${document.title} · Rev. 1`); await page.getByRole('button', { name: 'Attach submission document', exact: true }).click(); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the engineering inputs and exact sources', exact: true })); await page.getByRole('button', { name: 'Save submission', exact: true }).click();
  const id = [...f.records.get('submittal')!.keys()][0]; await expect(page.getByRole('button', { name: 'Write disposition', exact: true })).toHaveCount(0);
  f.setActor(1); await page.reload(); await page.getByRole('button', { name: 'Write disposition', exact: true }).click(); await select(page, 'Proposed disposition', 'Approved'); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the engineering inputs and exact sources', exact: true })); await page.getByRole('button', { name: 'Save working disposition', exact: true }).click();
  await page.getByRole('button', { name: 'Request independent authorization', exact: true }).click(); await authorize(page, f, 2, 1);
  await page.goto(`${engineeringPath}/submittals/${id}`); await expect(page.getByRole('button', { name: 'Prepare internal transmittal', exact: true })).toBeVisible(); expect([...f.records.get('disposition')!.values()][0].definition.comments).toBe('');
});
test('known source download denial removes all reviewed source/form content before a save', async ({ page }) => {
  const f = await mockEngineering(page); await page.goto(`${engineeringPath}/rfis`); await question(page); await page.route('**/api/method/cipher_aec.documents.api.download_revision*', route => route.fulfill({ status: 403 })); await page.getByRole('button', { name: 'View stored drawing', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Recheck engineering access', exact: true })).toBeVisible(); await expect(page.locator('ui5-dialog[header-text="New RFI"]')).toHaveCount(0); expect(f.writes).toEqual([]);
});
for (const width of [1440, 900, 390]) test(`engineering authoring remains usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockEngineering(page); await page.goto(`${engineeringPath}/rfis`); await question(page);
  const dialog = page.locator('ui5-dialog[header-text="New RFI"]'), save = dialog.getByRole('button', { name: 'Save question', exact: true }); await expect(save).toBeInViewport(); const box = await save.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width); await save.click(); await expect(page.getByRole('button', { name: 'Write response', exact: true })).toBeVisible();
});

test('a new working response retains the previous official answer without inheriting its authorization', async ({ page }) => {
  const f = await mockEngineering(page), fixture = rfiFixture(), rfi = fixture.response.rfi, original = fixture.response.revision;
  const base = { ...scope, scope_type: 'Project', author_person: people[0].person, author_user: people[0].user, created_at: '2026-10-17T05:00:00Z', status: 'working', parent_id: rfi.id, source_revision: original.id, source_digest: hash(original), source_citations: [], artifacts: [], drawing_references: [], no_effects: noEffects };
  const first = { ...base, id: crypto.randomUUID(), revision_number: 1, predecessor: null, definition: { answer: 'Original official technical answer.', potential_cost_impact: '', potential_schedule_impact: '' } };
  const second = { ...base, id: crypto.randomUUID(), revision_number: 2, predecessor: first.id, definition: { ...first.definition, answer: 'New working technical proposal.' } };
  const official = { ...scope, scope_type: 'Project', author_person: people[0].person, author_user: people[0].user, created_at: '2026-10-17T05:00:00Z', id: crypto.randomUUID(), status: 'official', subject_id: first.id, subject_digest: hash(first), packet_id: crypto.randomUUID(), decision_id: crypto.randomUUID(), checked_by_person: people[1].person, no_effects: noEffects, authority: 'internal-technical-only', parent_id: rfi.id, source_revision: original.id, source_digest: hash(original) };
  f.seed('rfi_revision', original); f.seed('response', first); f.seed('response', second); f.seed('official_response', official); f.seed('rfi', { ...rfi, response_head: second.id, official_response: official.id });
  await page.goto(`${engineeringPath}/rfis/${rfi.id}`); await expect(page.getByRole('heading', { name: 'Previously authorized technical revision', exact: true })).toBeVisible(); await expect(page.getByRole('button', { name: 'Request independent authorization', exact: true })).toBeVisible(); await expect(page.getByRole('button', { name: 'Prepare internal transmittal', exact: true })).toHaveCount(0); expect(f.writes).toEqual([]);
});
