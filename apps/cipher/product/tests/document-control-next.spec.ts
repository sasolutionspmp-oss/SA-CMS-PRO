import { expect, test, type Page } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { companyDocument, document, mockNextDocuments, nextPath, scope } from './document-control-next-fixture';

type Fixture = Awaited<ReturnType<typeof mockNextDocuments>>;
// UI5 exposes the named role inside its shadow wrapper; authored content is slotted under the host.
function namedDialog(page: Page, name: string) { return page.locator('ui5-dialog').filter({ has: page.getByRole('dialog', { name, exact: true }) }); }
async function choose(page: Page, name: string, option: string) { await page.getByRole('combobox', { name, exact: true }).click(); await page.getByRole('option', { name: option, exact: true }).click(); }
async function openSaved(page: Page) { const open = page.getByRole('button', { name: 'Open saved record', exact: true }); await expect(open).toBeEnabled(); await open.click(); }
async function recordAction(page: Page, name: string) { const button = page.getByRole('button', { name, exact: true }); const more = page.locator('.engineering-object-page').getByRole('button', { name: 'Additional Options', exact: true }); if (!await button.isVisible() && await more.isVisible()) await more.click(); await button.click(); }
async function authorize(page: Page, fixture: Fixture, requestName = 'Request independent review') {
  await recordAction(page, requestName);
  const review = namedDialog(page, 'Review document change'); await expect(review).toBeVisible();
  const id = [...fixture.packets.keys()].at(-1)!; fixture.setActor(1);
  await page.goto(`${nextPath}/review/${id}`);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this exact document change', exact: true }));
  await page.getByRole('button', { name: 'Grant review', exact: true }).click(); await expect.poll(() => fixture.packets.get(id).state).toBe('Granted');
  fixture.setActor(0); await page.reload();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this exact document change', exact: true }));
  await page.getByRole('button', { name: 'Record authorized change', exact: true }).click(); await expect.poll(() => fixture.packets.get(id).state).toBe('Consumed');
}
async function issuedDocument(page: Page) { await page.goto(`${nextPath}/issued`); await choose(page, 'Issued document', document.title); await expect(page.getByRole('button', { name: 'Supersede issued revision', exact: true })).toBeEnabled(); }
async function lifecycleRequest(page: Page, action: 'supersede' | 'withdraw', fixture: Fixture, reason: string) {
  await page.getByRole('button', { name: action === 'supersede' ? 'Supersede issued revision' : 'Withdraw issued revision', exact: true }).click();
  const dialog = namedDialog(page, action === 'supersede' ? 'Supersede issued revision' : 'Withdraw issued revision');
  if (action === 'supersede') await choose(page, 'Replacement issue', `Revision 2 · Oct 17, 2026 · ${fixture.replacementIssue.id.slice(0, 8)}`);
  await dialog.getByRole('textbox', { name: 'Reason for change', exact: true }).fill(reason);
  const reviewed = dialog.getByRole('checkbox', { name: 'I reviewed the issued change', exact: true }); await expect(reviewed).toBeEnabled(); await checkUi5Checkbox(reviewed);
  await dialog.getByRole('button', { name: 'Save change request', exact: true }).click(); return dialog;
}

test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));

test('Company library authoring saves exact Company scope and remains discoverable after reload', async ({ page }) => {
  const fixture = await mockNextDocuments(page); await page.goto(`/company/library?company=${encodeURIComponent(scope.company)}`);
  await page.getByRole('button', { name: 'New library entry', exact: true }).click();
  const dialog = namedDialog(page, 'New Company library entry');
  for (const [name, value] of [['Library title', 'Reusable concrete requirements'], ['Discipline', 'Civil'], ['Ownership', 'Company authored'], ['Change reason', 'Register exact approved source']]) await dialog.getByRole('textbox', { name, exact: true }).fill(value);
  await choose(page, 'Company library source', `${companyDocument.title} · Rev. 1`); await dialog.getByRole('button', { name: 'Select company library source', exact: true }).click();
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: 'I reviewed this library record', exact: true }));
  await dialog.getByRole('button', { name: 'Save', exact: true }).click(); await openSaved(page);
  await expect(page.getByRole('heading', { name: 'Reusable concrete requirements', exact: true })).toBeVisible(); await page.reload();
  await expect(page.getByRole('heading', { name: 'Reusable concrete requirements', exact: true })).toBeVisible();
  expect(fixture.writes[0].body.company).toBe(scope.company); expect(fixture.writes[0].body.project).toBeUndefined();
});

test('cancelling a stale Company revision does not block a separate new library entry', async ({ page }) => {
  const fixture = await mockNextDocuments(page, { staleCompany: true }); await page.goto(`/company/library/record/library/${fixture.library.id}?company=${encodeURIComponent(scope.company)}`);
  await page.getByRole('button', { name: 'Create revision', exact: true }).click(); const revision = namedDialog(page, 'Create Company revision'); await expect(revision.getByRole('textbox', { name: 'Library title', exact: true })).toHaveValue('Company standard clauses');
  await revision.getByRole('textbox', { name: 'Change reason', exact: true }).fill('Attempt this separate revision'); await checkUi5Checkbox(revision.getByRole('checkbox', { name: 'I reviewed this library record', exact: true })); await revision.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(revision.getByRole('button', { name: 'Load current record', exact: true })).toBeVisible(); await revision.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Library', exact: true }).click(); await page.getByRole('button', { name: 'New library entry', exact: true }).click(); const fresh = namedDialog(page, 'New Company library entry');
  await expect(fresh.getByRole('button', { name: 'Load current record', exact: true })).toHaveCount(0);
  for (const [name, value] of [['Library title', 'Independent new library entry'], ['Discipline', 'Civil'], ['Ownership', 'Company authored'], ['Change reason', 'Separate new authoring request']]) await fresh.getByRole('textbox', { name, exact: true }).fill(value);
  await choose(page, 'Company library source', `${companyDocument.title} · Rev. 1`); await fresh.getByRole('button', { name: 'Select company library source', exact: true }).click(); await checkUi5Checkbox(fresh.getByRole('checkbox', { name: 'I reviewed this library record', exact: true })); await fresh.getByRole('button', { name: 'Save', exact: true }).click(); await openSaved(page);
  await expect(page.getByRole('heading', { name: 'Independent new library entry', exact: true })).toBeVisible(); expect(fixture.writes[0].method).toBe('company_revise_library'); expect(fixture.writes[1].method).toBe('company_create_library'); expect(fixture.writes[1].body.operation_id).not.toBe(fixture.writes[0].body.operation_id);
});

for (const area of ['Company', 'Clause'] as const) test(`${area} register switches start with a fresh filter-bound page`, async ({ page }) => {
  await mockNextDocuments(page); const reads: URL[] = [], companyArea = area === 'Company', first = companyArea ? 'library' : 'clause_use', second = companyArea ? 'rights' : 'redline';
  await page.route(companyArea ? '**/api/method/cipher_aec.document_control.company_api.list_records*' : '**/api/method/cipher_aec.document_control.api.list_records*', route => {
    const url = new URL(route.request().url()); reads.push(url); const next = url.searchParams.get('kind') === first && !url.searchParams.get('cursor') ? 'fixture-filter-bound-page-two' : null;
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data: { items: [], limit: 25, count_mode: 'none', total: null, next_cursor: next } } }) });
  });
  await page.goto(companyArea ? `/company/library?company=${encodeURIComponent(scope.company)}` : `${nextPath}/clauses`); await page.getByRole('button', { name: 'Next page', exact: true }).click(); await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: companyArea ? 'Content permissions' : 'Proposed revisions', exact: true }).click(); await expect.poll(() => reads.at(-1)?.searchParams.get('kind')).toBe(second);
  expect(reads.filter(url => url.searchParams.get('kind') === second).every(url => !url.searchParams.has('cursor'))).toBe(true); await expect(page.getByRole('button', { name: 'Previous page', exact: true })).toHaveCount(0);
});

test('same Company library reuse requires separate Project review and preserves its original scope', async ({ page }) => {
  const fixture = await mockNextDocuments(page); await page.goto(`${nextPath}/shared/library_revision/${fixture.libraryRevision.id}`);
  await page.getByRole('button', { name: 'Use in this project', exact: true }).click();
  const dialog = namedDialog(page, 'Use Company revision in project');
  for (const [name, value] of [['Adoption purpose', 'Use original Company clauses'], ['Project location', 'Concrete work section'], ['Change reason', 'Independent Project selection']]) await dialog.getByRole('textbox', { name, exact: true }).fill(value);
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: 'I reviewed this exact library revision', exact: true }));
  await dialog.getByRole('button', { name: 'Save adoption request', exact: true }).click(); await openSaved(page); await authorize(page, fixture);
  expect(fixture.records.get('adoption')!.size).toBe(2);
  const fact = [...fixture.records.get('adoption')!.values()].at(-1)!;
  await page.goto(`${nextPath}/shared/record/adoption/${fact.id}`);
  await expect(page.getByText(`Company · ${scope.company}`, { exact: true })).toBeVisible();
  expect(fact.artifacts).toEqual(fixture.libraryRevision.artifacts);
});

test('stale Company adoption preserves authored fields and reloads only the original revision', async ({ page }) => {
  const fixture = await mockNextDocuments(page, { staleAdoption: true }); await page.goto(`${nextPath}/shared/library_revision/${fixture.libraryRevision.id}`);
  await page.getByRole('button', { name: 'Use in this project', exact: true }).click(); const dialog = namedDialog(page, 'Use Company revision in project');
  for (const [name, value] of [['Adoption purpose', 'Preserve exact Company selection'], ['Project location', 'Original concrete section'], ['Change reason', 'Keep authored adoption reason']]) await dialog.getByRole('textbox', { name, exact: true }).fill(value);
  const reviewed = dialog.getByRole('checkbox', { name: 'I reviewed this exact library revision', exact: true }), save = dialog.getByRole('button', { name: 'Save adoption request', exact: true });
  await checkUi5Checkbox(reviewed); await save.click(); await expect(save).toBeDisabled(); await expect(reviewed).toBeDisabled();
  await dialog.getByRole('button', { name: 'Reload exact Company revision', exact: true }).click(); await dialog.getByRole('button', { name: 'Use reloaded original revision', exact: true }).click();
  await expect(dialog.getByRole('textbox', { name: 'Adoption purpose', exact: true })).toHaveValue('Preserve exact Company selection'); await expect(dialog.getByRole('textbox', { name: 'Project location', exact: true })).toHaveValue('Original concrete section'); await expect(dialog.getByRole('textbox', { name: 'Change reason', exact: true })).toHaveValue('Keep authored adoption reason');
  await expect(reviewed).not.toBeChecked(); await expect(save).toBeDisabled(); await checkUi5Checkbox(reviewed); await save.click(); await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeEnabled();
  expect(fixture.writes[0].body.library_revision).toBe(fixture.libraryRevision.id); expect(fixture.writes[1].body.library_revision).toBe(fixture.libraryRevision.id); expect(fixture.writes[1].body.operation_id).not.toBe(fixture.writes[0].body.operation_id);
});

test('review acknowledgement cannot carry to a different original packet during navigation', async ({ page }) => {
  const fixture = await mockNextDocuments(page), first = fixture.addPacket('adoption_request', fixture.adoptionRequest.id);
  const other = { ...structuredClone(fixture.adoptionRequest), id: crypto.randomUUID(), definition: { ...fixture.adoptionRequest.definition, purpose: 'Second independent adoption request' } }; fixture.put('adoption_request', other); const second = fixture.addPacket('adoption_request', other.id); fixture.setActor(1);
  await page.goto(`${nextPath}/review/${first.id}`); const reviewed = page.getByRole('checkbox', { name: 'I reviewed this exact document change', exact: true }); await checkUi5Checkbox(reviewed); await expect(page.getByRole('button', { name: 'Grant review', exact: true })).toBeEnabled();
  await page.evaluate(path => { window.history.pushState({}, '', path); window.dispatchEvent(new PopStateEvent('popstate')); }, `${nextPath}/review/${second.id}`);
  await expect(page.getByRole('heading', { name: 'Second independent adoption request', exact: true })).toBeVisible(); await expect(reviewed).not.toBeChecked(); await expect(page.getByRole('button', { name: 'Grant review', exact: true })).toBeDisabled(); expect(fixture.writes).toEqual([]);
});

test('adopted exact wording, a proposed redline and its independent relationship leave the target unchanged', async ({ page }) => {
  const fixture = await mockNextDocuments(page); await page.goto(`${nextPath}/clauses`);
  await page.getByRole('button', { name: 'Reference an adopted clause', exact: true }).click();
  const dialog = namedDialog(page, 'Reference an adopted clause');
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: `Independently adopted source ${fixture.adoption.id}`, exact: true }));
  await dialog.getByRole('button', { name: 'Use entire source passage', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Target revision ID', exact: true }).fill(document.current_revision); await dialog.getByRole('button', { name: 'Look up exact target revision', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Target location', exact: true }).fill('Specification section 03'); await dialog.getByRole('textbox', { name: 'Clause reference purpose', exact: true }).fill('Review the exact adopted wording');
  const reviewed = dialog.getByRole('checkbox', { name: 'I reviewed the exact source wording and target revision', exact: true }); await expect(reviewed).toBeEnabled(); await checkUi5Checkbox(reviewed);
  await dialog.getByRole('button', { name: 'Save clause reference', exact: true }).click(); await openSaved(page);
  await recordAction(page, 'Propose clause revision'); const redline = namedDialog(page, 'Propose clause revision');
  await redline.getByRole('textbox', { name: 'Proposed clause wording', exact: true }).fill('The contractor shall retain the exact independently reviewed specification.');
  await redline.getByRole('textbox', { name: 'Reason for proposed change', exact: true }).fill('Clarify independent review'); await checkUi5Checkbox(redline.getByRole('checkbox', { name: 'I reviewed the original clause and this proposed revision', exact: true }));
  await redline.getByRole('button', { name: 'Save proposed revision', exact: true }).click(); await openSaved(page); await authorize(page, fixture, 'Request independent relationship approval');
  const fact = [...fixture.records.get('clause_application')!.values()][0]; expect(fact.target_changed).toBe(false); expect(fact.target.id).toBe(document.current_revision); expect(fact.original_text).not.toBe(fact.proposed_text);
});

test('separate supersession and withdrawal preserve issued history and do not follow working uploads', async ({ page }) => {
  const fixture = await mockNextDocuments(page); const original = structuredClone(fixture.issue);
  await issuedDocument(page); await lifecycleRequest(page, 'supersede', fixture, 'Use the separately authorized replacement'); await openSaved(page); await authorize(page, fixture);
  expect(fixture.standing().status).toBe('issued'); expect(fixture.standing().current_issued.revision_id).toBe(fixture.replacementIssue.artifacts[0].revision_id);
  await issuedDocument(page); await lifecycleRequest(page, 'withdraw', fixture, 'Withdraw the current issued revision'); await openSaved(page); await authorize(page, fixture);
  expect(fixture.standing().status).toBe('withdrawn'); expect(fixture.standing().current_issued).toBeNull(); expect(fixture.records.get('lifecycle')!.size).toBe(2); expect(fixture.get('issue', original.id)).toEqual(original);
});

test('a lost lifecycle save remains locked after denial and recovers only its original request', async ({ page }) => {
  const fixture = await mockNextDocuments(page, { lose: 'request_lifecycle' }), requests: unknown[] = [];
  page.on('request', request => { if (request.url().endsWith('request_lifecycle')) requests.push(request.postDataJSON()); });
  await issuedDocument(page); const dialog = await lifecycleRequest(page, 'withdraw', fixture, 'Recover exact withdrawal request');
  await expect(dialog.getByRole('button', { name: 'Recover document save', exact: true })).toBeEnabled(); await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled(); await page.keyboard.press('Escape'); await expect(dialog).toBeVisible();
  fixture.setDenied(true); await dialog.getByRole('button', { name: 'Recover document save', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Recheck document access', exact: true })).toBeVisible(); await expect(dialog).not.toBeVisible();
  const recovery = page.locator('.engineering-command-state').getByRole('button', { name: 'Recover document save', exact: true });
  await expect(recovery).toBeEnabled(); await expect(page.getByRole('combobox', { name: 'Project context', exact: true, includeHidden: true })).toBeDisabled();
  fixture.setDenied(false); await recovery.click();
  await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeEnabled(); expect(requests).toHaveLength(3); expect(requests[1]).toEqual(requests[0]); expect(requests[2]).toEqual(requests[0]); expect(fixture.records.get('lifecycle_request')!.size).toBe(1); expect(fixture.records.get('lifecycle')?.size || 0).toBe(0);
});

test('stale issued standing retains its reason until explicit current standing review', async ({ page }) => {
  const fixture = await mockNextDocuments(page, { staleLifecycle: true }); await issuedDocument(page); const dialog = await lifecycleRequest(page, 'withdraw', fixture, 'Preserve this authored withdrawal reason');
  await dialog.getByRole('button', { name: 'Load current standing', exact: true }).click(); await dialog.getByRole('button', { name: 'Use current standing', exact: true }).click();
  await expect(dialog.getByRole('textbox', { name: 'Reason for change', exact: true })).toHaveValue('Preserve this authored withdrawal reason');
  await checkUi5Checkbox(dialog.getByRole('checkbox', { name: 'I reviewed the issued change', exact: true })); await dialog.getByRole('button', { name: 'Save change request', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeEnabled(); expect(fixture.writes[0].body.operation_id).not.toBe(fixture.writes[1].body.operation_id);
});

test('read-only rights expose records while hiding Company and Project writers', async ({ page }) => {
  const fixture = await mockNextDocuments(page, { readOnly: true }); await page.goto(`/company/library?company=${encodeURIComponent(scope.company)}`); await expect(page.getByRole('link', { name: 'Company standard clauses', exact: true })).toBeVisible(); await expect(page.getByRole('button', { name: 'New library entry', exact: true })).toHaveCount(0);
  await page.goto(`${nextPath}/shared/library_revision/${fixture.libraryRevision.id}`); await expect(page.getByRole('button', { name: 'Use in this project', exact: true })).toHaveCount(0);
});

test('Company source denial removes cached library records and authoring controls', async ({ page }) => {
  const fixture = await mockNextDocuments(page); await page.goto(`/company/library?company=${encodeURIComponent(scope.company)}`);
  await expect(page.getByRole('link', { name: 'Company standard clauses', exact: true })).toBeVisible(); fixture.setDenied(true);
  await page.getByRole('button', { name: 'Refresh library', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Recheck library access', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Company standard clauses', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'New library entry', exact: true })).toHaveCount(0);
});

test('author review is cleared when the proposed issued change is edited', async ({ page }) => {
  const fixture = await mockNextDocuments(page); await issuedDocument(page);
  await page.getByRole('button', { name: 'Withdraw issued revision', exact: true }).click();
  const dialog = namedDialog(page, 'Withdraw issued revision'), reviewed = dialog.getByRole('checkbox', { name: 'I reviewed the issued change', exact: true });
  await expect(reviewed).toBeDisabled(); await dialog.getByRole('textbox', { name: 'Reason for change', exact: true }).fill('First reviewed reason'); await expect(reviewed).toBeEnabled(); await checkUi5Checkbox(reviewed);
  await dialog.getByRole('textbox', { name: 'Reason for change', exact: true }).fill('Changed reason needs another review');
  await expect(reviewed).not.toBeChecked(); await expect(dialog.getByRole('button', { name: 'Save change request', exact: true })).toBeDisabled(); expect(fixture.writes).toEqual([]);
});

test('issued change authoring and confirmation are usable by keyboard', async ({ page }) => {
  const fixture = await mockNextDocuments(page); await issuedDocument(page); await page.getByRole('button', { name: 'Withdraw issued revision', exact: true }).press('Enter');
  const dialog = namedDialog(page, 'Withdraw issued revision'), reason = dialog.getByRole('textbox', { name: 'Reason for change', exact: true }), reviewed = dialog.getByRole('checkbox', { name: 'I reviewed the issued change', exact: true });
  await reason.focus(); await page.keyboard.type('Keyboard authored withdrawal request'); await page.keyboard.press('Tab'); await expect(reviewed).toBeFocused(); await page.keyboard.press('Space'); await expect(reviewed).toBeChecked();
  const save = dialog.getByRole('button', { name: 'Save change request', exact: true }); await save.focus(); await page.keyboard.press('Enter'); await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeEnabled();
  expect(fixture.writes[0].body.definition.reason).toBe('Keyboard authored withdrawal request'); expect(fixture.writes[0].body.definition.issue_id).toBe(fixture.issue.id);
});

for (const width of [1440, 900, 390]) test(`issued change form keeps its footer usable at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 }); const fixture = await mockNextDocuments(page); await issuedDocument(page);
  await page.getByRole('button', { name: 'Withdraw issued revision', exact: true }).click(); const dialog = namedDialog(page, 'Withdraw issued revision');
  await expect(dialog.getByRole('button', { name: 'Save change request', exact: true })).toBeInViewport(); expect(await page.evaluate(() => globalThis.document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`synthetic-contract-issued-change-${width}.png`), fullPage: true }); expect(fixture.writes).toEqual([]);
});
