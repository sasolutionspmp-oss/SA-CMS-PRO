import { randomUUID } from 'node:crypto';
import { expect, test, type Page, type Route } from '@playwright/test';
import { closeoutPath, mockCloseout } from './closeout-fixture';
import { document, hash, noEffects, people, scope, unitManifest } from './engineering-packages-fixture';
import { artifact } from './engineering-fixture';
import { documentBase, libraryDefinition } from './document-control-fixture';
import { expand, source } from './field-fixture';
import { noEffects as qualityNoEffects } from './quality-safety-fixture';
import { checkUi5Checkbox } from './ui5-controls';

// Read-only browser projections reuse the existing synthetic fixture sources.
// These checks establish desktop picker behavior, not native persistence.
function supportingRecords() {
  const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[0].person, author_user: people[0].user, created_at: '2026-10-17T05:00:00Z', status: 'working', no_effects: noEffects });
  const basis: any = { ...base(), parent_id: randomUUID(), family_id: randomUUID(), revision_number: 1, predecessor: null, package_revision: randomUUID(), package_digest: hash('assignment'), checker: { person: people[1].person, user: people[1].user }, source_citations: [], drawing_references: [], artifacts: [], definition: { title: 'Pump design basis', criteria: 'Exact authored design basis', assumptions: '', design_codes: [], change_reason: 'Initial revision' }, quantities: [], unit_manifest: null };
  basis.unit_manifest = unitManifest(basis.id, false);
  const check: any = { ...base(), status: 'checked', parent_id: basis.parent_id, subject_kind: 'basis', subject_id: basis.id, subject_digest: hash(basis), package_revision: basis.package_revision, package_digest: basis.package_digest, checker: basis.checker, preparer_person: basis.author_person, packet_id: randomUUID(), decision_id: randomUUID(), comments: 'Independent check', outcome: 'checked', issue_authorized: false, sealed: false };
  const library: any = { ...documentBase(), parent_id: randomUUID(), predecessor: null, revision_number: 2, definition: structuredClone(libraryDefinition), artifacts: [structuredClone(artifact)] };
  const request: any = { ...documentBase(), parent_id: library.parent_id, library_revision: library.id, library_digest: hash(library), definition: { purpose: 'Use exact specification', target_locator: 'Section 03 30 00', change_reason: 'Initial adoption' }, artifacts: library.artifacts };
  const adoption: any = { ...documentBase(0, 'adopted'), parent_id: request.id, subject_id: request.id, subject_digest: hash(request), packet_id: randomUUID(), decision_id: randomUUID(), checked_by_person: people[1].person, effect_digest: hash('accepted adoption'), artifacts: library.artifacts, electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false };
  const item = randomUUID(), captured = expand(source);
  const qbase = () => ({ ...base(), status: 'recorded', no_effects: qualityNoEffects });
  const revision: any = { ...qbase(), category: 'deficiency', parent_id: randomUUID(), revision_number: 1, predecessor: null, prior_decision: null, amendment_of: null, amendment_reason: '', definition: { title: 'Pump alignment inspection', local_date: '2026-10-17', location: 'Pump P-101', description: 'Documented alignment review', required_closure_items: [{ item_id: item, description: 'Retain alignment result' }] }, evidence: [captured] };
  const closure: any = { ...qbase(), category: revision.category, parent_id: revision.parent_id, source_revision: revision.id, source_digest: hash(revision), predecessor: randomUUID(), action: 'close', from_status: 'checked', to_status: 'closed', comment: 'Recorded independent closure', evidence: [], closure: [{ item_id: item, evidence: [captured] }], checked_by_person: people[1].person };
  const submitted: any = { ...closure, id: randomUUID(), predecessor: null, action: 'submit', from_status: 'draft', to_status: 'submitted', closure: [], checked_by_person: null };
  return { check, basis, adoption, request, library, revision, closure, submitted };
}

const labels = { engineering: 'Pump design basis · Rev. 1 · Checked', document: `${libraryDefinition.title} · Rev. 2 · Adopted`, quality: 'Pump alignment inspection · Pump P-101 · Closed' };
const recordSelect = (page: Page) => page.getByRole('combobox', { name: 'Closeout supporting record', exact: true });
const attach = (page: Page) => page.getByRole('button', { name: 'Attach record', exact: true });
async function choose(page: Page, name: string, option: string) {
  await page.getByRole('combobox', { name, exact: true }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
const chooseType = (page: Page, option: string) => choose(page, 'Closeout supporting record type', option);
const chooseRecord = (page: Page, option: string) => choose(page, 'Closeout supporting record', option);
const envelope = (route: Route, data: unknown) => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data } } });

async function setup(page: Page) {
  const closeout = await mockCloseout(page, { seed: true }), rows = supportingRecords(), reads: URL[] = [];
  const state: { lookup?: 'wrong-project' | 'denied'; verify?: 'changed' | 'denied'; filtered?: boolean; waitForAdoption?: Promise<void> } = {};
  const records: Record<string, Record<string, any>> = { engineering_packages: { check: rows.check, basis: rows.basis }, document_control: { adoption: rows.adoption, adoption_request: rows.request, library_revision: rows.library }, quality_safety: { decision: rows.closure, revision: rows.revision } };
  const wrap = (api: string, kind: string, record: any) => ({ record, record_digest: hash(record), ...(api === 'engineering_packages' ? { review: kind === 'check' ? null : { state: 'checked', check_id: rows.check.id, packet_id: rows.check.packet_id, issue_authorized: false } } : api === 'document_control' ? { library_current: true } : {}) });
  await page.route(/\/api\/method\/cipher_aec\.(engineering_packages|document_control|quality_safety)\.api\.(list_records|get_record)\?/, async route => {
    const req = route.request(), url = new URL(req.url()), api = url.pathname.split('.')[1], kind = url.searchParams.get('kind')!, list = url.pathname.endsWith('list_records');
    reads.push(url);
    expect(req.method()).toBe('GET');
    expect(url.searchParams.get('company')).toBe(scope.company);
    expect(url.searchParams.get('project')).toBe(scope.project);
    if (list && api === 'document_control' && state.waitForAdoption) await state.waitForAdoption;
    if (list && state.lookup === 'denied' || !list && api === 'engineering_packages' && kind === 'check' && state.verify === 'denied') return route.fulfill({ status: 403, json: { message: { schema: 'cipher.api.v1', error: { code: 'fixture_denied', message: 'Current source access is unavailable.' } } } });
    let record = records[api]?.[kind];
    expect(record).toBeDefined();
    if (list) {
      expect(url.searchParams.get('limit')).toBe('25');
      expect(url.searchParams.get('count_mode')).toBe('none');
      expect(url.searchParams.has('parent_id')).toBe(false);
      if (state.lookup === 'wrong-project') record = { ...record, project: 'ANOTHER-PROJECT' };
      if (state.filtered && api === 'quality_safety' && !url.searchParams.get('cursor')) return envelope(route, { items: [wrap(api, kind, rows.submitted)], next_cursor: 'quality-page-two', limit: 25, count_mode: 'none', total: null });
      return envelope(route, { items: [wrap(api, kind, record)], next_cursor: null, limit: 25, count_mode: 'none', total: null });
    }
    expect(url.searchParams.get('record_id')).toBe(record.id);
    if (api === 'engineering_packages' && kind === 'check' && state.verify === 'changed') record = { ...record, comments: 'A later exact check revision' };
    return envelope(route, wrap(api, kind, record));
  });
  return { closeout, rows, state, reads };
}

async function openResult(page: Page, id: string) {
  await page.goto(`${closeoutPath}/${id}`);
  await page.getByRole('button', { name: 'Update result', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Record result — Operator training', exact: true })).toBeVisible();
}

test.use({ viewport: { width: 1440, height: 1000 } });
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));

test('desktop supporting choices show names and save the exact original IDs and digests', async ({ page }) => {
  const f = await setup(page);
  await openResult(page, f.closeout.seedId!);
  const chosen = [
    { type: 'Engineering check', label: labels.engineering, kind: 'engineering_check', row: f.rows.check },
    { type: 'Document adoption', label: labels.document, kind: 'document_adoption', row: f.rows.adoption },
    { type: 'Quality closure', label: labels.quality, kind: 'quality_closure', row: f.rows.closure },
  ];
  for (const [index, choice] of chosen.entries()) {
    if (index) await chooseType(page, choice.type);
    await chooseRecord(page, choice.label);
    await attach(page).click();
    const attached = page.locator('.closeout-evidence-row').filter({ has: page.getByRole('button', { name: `Remove supporting record ${index + 1}`, exact: true }) });
    await expect(attached.getByText(choice.label, { exact: true })).toBeVisible();
    await attached.locator('summary').click();
    await expect(attached.locator('code').nth(0)).toHaveText(choice.row.id);
    await expect(attached.locator('code').nth(1)).toHaveText(hash(choice.row));
    await expect(attach(page)).toBeDisabled();
  }
  await page.getByRole('textbox', { name: 'Result notes', exact: true }).fill('Training completed with the exact retained supporting records.');
  await page.getByRole('textbox', { name: 'Performed on', exact: true }).fill('2026-10-18');
  await page.getByRole('textbox', { name: 'Performed by', exact: true }).fill('Plant trainer, as recorded');
  await page.getByRole('textbox', { name: 'Attendees', exact: true }).fill('Operations crew, as recorded');
  await choose(page, 'Closeout evidence document', `${document.title} · Rev. 1`);
  await page.getByRole('textbox', { name: 'Closeout evidence location', exact: true }).fill('Training attendance sheet');
  await page.getByRole('button', { name: 'Attach evidence', exact: true }).click();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the result, evidence and related records', exact: true }));
  await page.screenshot({ path: test.info().outputPath('closeout-picker-1440.png'), fullPage: true });
  await page.getByRole('button', { name: 'Save result', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open saved closeout package', exact: true })).toBeEnabled();
  expect(f.closeout.writes).toHaveLength(1);
  expect(f.closeout.writes[0].method).toBe('record_result');
  expect(f.closeout.writes[0].body.links).toEqual(chosen.map(choice => ({ kind: choice.kind, id: choice.row.id, record_digest: hash(choice.row) })));
  expect(f.reads.filter(url => url.pathname.endsWith('get_record') && ['check', 'adoption', 'decision'].includes(url.searchParams.get('kind')!))).toHaveLength(3);
});

test('changing record type clears selection and a delayed old lookup cannot replace the current choices', async ({ page }) => {
  const f = await setup(page);
  await openResult(page, f.closeout.seedId!);
  await chooseRecord(page, labels.engineering);
  await expect(attach(page)).toBeEnabled();
  let release!: () => void;
  f.state.waitForAdoption = new Promise<void>(resolve => { release = resolve; });
  await chooseType(page, 'Document adoption');
  await expect.poll(() => f.reads.some(url => url.pathname.includes('document_control') && url.pathname.endsWith('list_records'))).toBe(true);
  await expect(recordSelect(page)).toHaveCount(0);
  await expect(attach(page)).toBeDisabled();
  await chooseType(page, 'Quality closure');
  await expect(recordSelect(page)).toBeEnabled();
  await expect(attach(page)).toBeDisabled();
  release();
  await chooseRecord(page, labels.quality);
  await attach(page).click();
  const attached = page.locator('.closeout-evidence-row').filter({ has: page.getByRole('button', { name: 'Remove supporting record 1', exact: true }) });
  await expect(attached.getByText(labels.quality, { exact: true })).toBeVisible();
  await attached.locator('summary').click();
  await expect(attached.locator('code').nth(0)).toHaveText(f.rows.closure.id);
  expect(f.reads.some(url => url.searchParams.get('kind') === 'check' && url.pathname.endsWith('get_record'))).toBe(false);
  expect(f.closeout.writes).toEqual([]);
});

test('wrong-project and denied refresh hide choices and stale names while preserving the exact attached reference', async ({ page }) => {
  const f = await setup(page);
  await openResult(page, f.closeout.seedId!);
  await chooseRecord(page, labels.engineering);
  await attach(page).click();
  const attached = page.locator('.closeout-evidence-row').filter({ has: page.getByRole('button', { name: 'Remove supporting record 1', exact: true }) });
  await expect(attached.getByText(labels.engineering, { exact: true })).toBeVisible();
  f.state.lookup = 'wrong-project';
  await page.getByRole('button', { name: 'Refresh records', exact: true }).click();
  await expect(recordSelect(page)).toHaveCount(0);
  await expect(page.locator('#main-content').getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible();
  await expect(attach(page)).toBeDisabled();
  await expect(attached.getByText(labels.engineering, { exact: true })).toHaveCount(0);
  await expect(attached.getByText('Engineering check', { exact: true })).toBeVisible();
  await attached.locator('summary').click();
  await expect(attached.locator('code').nth(0)).toHaveText(f.rows.check.id);
  await expect(attached.locator('code').nth(1)).toHaveText(hash(f.rows.check));
  f.state.lookup = 'denied';
  await page.getByRole('button', { name: 'Refresh records', exact: true }).click();
  await expect(page.locator('#main-content').getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible();
  await expect(recordSelect(page)).toHaveCount(0);
  await expect(attach(page)).toBeDisabled();
  await expect(attached.getByText(labels.engineering, { exact: true })).toHaveCount(0);
  await expect(attached.locator('code').nth(0)).toHaveText(f.rows.check.id);
  await expect(page.getByRole('heading', { name: 'Record result — Operator training', exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Closeout supporting record type', exact: true })).toBeEnabled();
  expect(f.closeout.writes).toEqual([]);
});

test('a changed verification digest cannot attach the previously selected record', async ({ page }) => {
  const f = await setup(page);
  await openResult(page, f.closeout.seedId!);
  await chooseRecord(page, labels.engineering);
  f.state.verify = 'changed';
  await attach(page).click();
  await expect(page.locator('#main-content').getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Remove supporting record 1', exact: true })).toHaveCount(0);
  expect(f.closeout.writes).toEqual([]);
});

test('current access denial during verification prevents attachment and hides loaded result content', async ({ page }) => {
  const f = await setup(page);
  await openResult(page, f.closeout.seedId!);
  await chooseRecord(page, labels.engineering);
  f.state.verify = 'denied';
  await attach(page).click();
  await expect(page.locator('#main-content').getByRole('note', { name: /Access changed\. Previously loaded closeout content is hidden\./ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Remove supporting record 1', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save result', exact: true })).toHaveCount(0);
  expect(f.closeout.writes).toEqual([]);
});

test('a filtered-empty Quality page keeps Next usable and the next page offers the permitted closure', async ({ page }) => {
  const f = await setup(page);
  f.state.filtered = true;
  await openResult(page, f.closeout.seedId!);
  await chooseType(page, 'Quality closure');
  await expect(page.getByText('No records available.', { exact: true })).toBeVisible();
  await expect(recordSelect(page)).toBeDisabled();
  await expect(attach(page)).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  await chooseRecord(page, labels.quality);
  await attach(page).click();
  await expect(page.getByRole('button', { name: 'Remove supporting record 1', exact: true })).toBeEnabled();
  expect(f.reads.filter(url => url.pathname.endsWith('list_records') && url.pathname.includes('quality_safety')).map(url => url.searchParams.get('cursor'))).toEqual([null, 'quality-page-two']);
  expect(f.reads.some(url => url.searchParams.get('record_id') === f.rows.submitted.id)).toBe(false);
  expect(f.closeout.writes).toEqual([]);
});
