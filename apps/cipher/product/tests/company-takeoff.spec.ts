import { expect, test, type Page } from '@playwright/test';
import { chooseSource, company, document, fillManual, measurement, mockCompanyTakeoff, setId, type Fault } from './company-takeoff-fixture';
const path = `/company/takeoff/${setId}?company=${company}`;
test.beforeEach(({ page }) => { page.on('pageerror', error => { throw error; }); });
test('an authorized PDF without embedded text renders and saves manual quantity without a text-preview request', async ({ page }) => {
  const f = await mockCompanyTakeoff(page, { noEmbeddedText: true }); await page.goto(path); await chooseSource(page); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible(); await fillManual(page, true); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click(); await expect(page.getByRole('note', { name: /Manual measurement saved/ })).toBeVisible(); expect(f.writes).toHaveLength(1); expect(f.saved[0].source.extraction_status).toBe('ocr_unavailable'); expect(f.reads.filter(u => u.pathname.endsWith('preview_revision'))).toEqual([]); expect(f.reads.some(u => u.pathname.endsWith('download_revision'))).toBe(true);
});
test('revoked Company detail access removes old PDF/form and cannot trigger a new byte download', async ({ page }) => {
  const f = await mockCompanyTakeoff(page); await page.goto(path); await fillManual(page); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible(); const before = f.reads.filter(u => u.pathname.endsWith('download_revision')).length;
  await page.route('**/api/method/cipher_aec.documents.company_api.get_document*', route => route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Source metadata access revoked.' } } }) }));
  await page.getByRole('button', { name: 'Refresh source access', exact: true }).click(); await page.getByRole('combobox', { name: 'Company takeoff source', exact: true }).click(); await page.getByRole('option', { name: document.title, exact: true }).click(); await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0); expect(f.reads.filter(u => u.pathname.endsWith('download_revision'))).toHaveLength(before);
});
test('Company register uses bounded none pages and exact direct Company context without Project reads', async ({ page }) => {
  const fixture = await mockCompanyTakeoff(page, { paged: true }); const projectReads: string[] = []; page.on('request', r => { if (/cipher_aec\.api\.v1\.projects?\b/.test(r.url())) projectReads.push(r.url()); });
  await page.goto(`/company/takeoff?company=${company}`); await expect(page.getByRole('heading', { name: 'Company drawing takeoff', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next takeoff page', exact: true }).click(); await expect(page.getByRole('button', { name: 'Second bounded set page', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Previous takeoff page', exact: true }).click(); await expect(page.getByRole('button', { name: 'Pre-award Company quantities', exact: true })).toBeVisible();
  for (const url of fixture.reads.filter(u => u.pathname.endsWith('list_records'))) { expect(url.searchParams.get('limit')).toBe('25'); expect(url.searchParams.get('count_mode')).toBe('none'); expect(url.searchParams.get('company')).toBe(company); }
  expect(projectReads).toEqual([]); await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toHaveCount(0);
});
async function fillSet(page: Page) {
  await page.getByRole('button', { name: 'New Company takeoff set', exact: true }).click();
  for (const [name, value] of [['Takeoff set title', 'Tender manual quantities'], ['Discipline', 'Civil'], ['Drawing package', 'Tender set A'], ['Takeoff set basis', 'Human-authored preliminary quantities']]) await page.getByRole('textbox', { name, exact: true }).fill(value);
}
test('ordinary Company takeoff set creation binds receipt then opens exact created set', async ({ page }) => {
  const f = await mockCompanyTakeoff(page); await page.goto(`/company/takeoff?company=${company}`); await fillSet(page); await page.getByRole('button', { name: 'Create Company takeoff set', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open created takeoff set', exact: true })).toBeEnabled(); expect(f.writes).toHaveLength(1); await page.getByRole('button', { name: 'Open created takeoff set', exact: true }).click(); await expect(page).toHaveURL(path);
});
test('manual measurement keeps exact decimal/unit/precision and source receipt; saved facts reread independently', async ({ page }) => {
  const f = await mockCompanyTakeoff(page); await page.goto(path); await fillManual(page); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible();
  await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click(); await expect(page.getByRole('note', { name: /Manual measurement saved/ })).toBeVisible();
  expect(f.writes).toHaveLength(1); expect(f.writes[0]).toMatchObject({ company, takeoff_set: setId, conversion_ids: [], definition: { method: 'manual', manual_quantity: { amount: '12.50', precision: 2 }, result_precision: 2, waste_fraction: '0' } });
  await page.getByRole('button', { name: 'A101, room 12', exact: true }).click(); const detail = page.getByRole('region', { name: 'Saved Company measurement', exact: true }); await expect(detail).toContainText('No calibrated geometry claim.');
  expect(f.reads.some(u => u.pathname.endsWith('get_record') && u.searchParams.get('kind') === 'measurement')).toBe(true);
});
test('saved manual quantity displays its exact immutable unit symbol in list and detail', async ({ page }) => {
  const f = await mockCompanyTakeoff(page); f.saved.push(measurement); await page.goto(path); await expect.soft(page.locator('.company-takeoff-list')).toContainText('12.50 sf'); await page.getByRole('button', { name: measurement.definition.locator, exact: true }).click(); await expect.soft(page.getByRole('region', { name: 'Saved Company measurement', exact: true })).toContainText('12.50 sf');
});
for (const fault of ['lost', '503', 'malformed', 'wrong-source'] as Fault[]) test(`manual ${fault} retains original UUID and payload through denied recovery and global navigation`, async ({ page }) => {
  const f = await mockCompanyTakeoff(page, { fault, denyRecovery: true }); await page.goto(`/company/takeoff?company=${company}`); await page.getByRole('button', { name: 'Pre-award Company quantities', exact: true }).click(); await fillManual(page); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original takeoff request', exact: true }); await expect(recover).toBeEnabled(); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  await page.getByRole('treeitem', { name: 'Projects', exact: true }).click(); await expect(page).toHaveURL(path);
  await page.goBack(); await expect(page).toHaveURL(path); await expect(recover).toBeEnabled();
  await page.getByRole('button', { name: 'Alex Morgan', exact: true }).click(); await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeDisabled(); await page.getByRole('button', { name: 'Close', exact: true }).click();
  await recover.click(); await expect(recover).toBeEnabled(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeHidden(); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0);
  await recover.click(); await expect(page.getByRole('note', { name: /Manual measurement saved/ })).toBeVisible(); expect(f.writes).toHaveLength(3); expect(f.writes[1]).toEqual(f.writes[0]); expect(f.writes[2]).toEqual(f.writes[0]); expect(f.effects.size).toBe(1);
});
test('definitive first refusal unlocks correction with a fresh operation UUID', async ({ page }) => {
  const f = await mockCompanyTakeoff(page, { rejectOnce: true }); await page.goto(path); await fillManual(page); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Manual quantity', exact: true })).toBeEnabled(); await page.getByRole('textbox', { name: 'Manual quantity reason', exact: true }).fill('Corrected human reason'); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click(); await expect(page.getByRole('note', { name: /Manual measurement saved/ })).toBeVisible(); expect(f.writes[1].operation_id).not.toBe(f.writes[0].operation_id); expect(f.effects.size).toBe(1);
});
test('excess decimal precision cannot create a manual request', async ({ page }) => {
  const f = await mockCompanyTakeoff(page); await page.goto(path); await fillManual(page); await page.getByRole('textbox', { name: 'Manual quantity', exact: true }).fill('12.501'); await expect(page.getByRole('button', { name: 'Save manual measurement', exact: true })).toBeDisabled(); expect(f.writes).toEqual([]);
});
test('wrong Company source detail cannot request preview/bytes or expose manual form', async ({ page }) => {
  const f = await mockCompanyTakeoff(page, { wrongDetail: true }); await page.goto(path); await page.getByRole('combobox', { name: 'Company takeoff source', exact: true }).click(); await page.getByRole('option', { name: document.title, exact: true }).click(); await expect(page.getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible(); await page.locator('.support-details').filter({ hasText: /could not be verified/ }).locator('summary').click(); await expect(page.locator('.support-details[open] > p').filter({ hasText: /could not be verified/ })).toBeVisible(); expect(f.reads.filter(u => /preview_revision|download_revision/.test(u.pathname))).toEqual([]); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0);
});
test('mismatched stored bytes hide both PDF pixels and new manual entry', async ({ page }) => {
  await mockCompanyTakeoff(page, { wrongHash: true }); await page.goto(path); await chooseSource(page); await expect(page.getByRole('note', { name: /PDF bytes do not match/ })).toBeVisible(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeHidden(); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0);
});
test('PDF page count differing from authorized metadata hides pixels and manual entry', async ({ page }) => {
  await mockCompanyTakeoff(page, { wrongPageCount: true }); await page.goto(path); await chooseSource(page); await expect(page.getByRole('note', { name: /PDF page count/ })).toBeVisible(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0);
});
test('reselecting a previously verified revision rechecks denied bytes before exposing manual entry', async ({ page }) => {
  await mockCompanyTakeoff(page); await page.goto(path); await fillManual(page); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toBeVisible();
  await page.route('**/api/method/cipher_aec.documents.company_api.download_revision*', route => route.fulfill({ status: 403 }));
  await page.getByRole('combobox', { name: 'Company takeoff source', exact: true }).click(); await page.getByRole('option', { name: 'Choose an authorized drawing', exact: true }).click(); await chooseSource(page);
  await expect(page.getByRole('note', { name: /You don’t have access to this item\./ })).toBeVisible(); await expect(page.getByRole('region', { name: 'Author manual quantity', exact: true })).toHaveCount(0);
});
test('an earlier definitive set refusal cannot mask a later manual recovery access refusal', async ({ page }) => {
  await mockCompanyTakeoff(page, { rejectOnce: true, fault: 'lost', denyRecovery: true }); await page.goto(`/company/takeoff?company=${company}`); await fillSet(page); await page.getByRole('button', { name: 'Create Company takeoff set', exact: true }).click(); await expect(page.getByRole('button', { name: 'Cancel new takeoff set', exact: true })).toBeEnabled(); await page.getByRole('button', { name: 'Cancel new takeoff set', exact: true }).click(); await page.getByRole('button', { name: 'Pre-award Company quantities', exact: true }).click(); await fillManual(page); await page.getByRole('button', { name: 'Save manual measurement', exact: true }).click(); const recover = page.getByRole('button', { name: 'Recover original takeoff request', exact: true }); await expect(recover).toBeEnabled(); await recover.click(); await expect(page.locator('canvas[aria-label="Authorized stored PDF page"]')).toHaveCount(0); await expect(recover).toBeEnabled();
});
test('unavailable Company direct URL refuses before Company takeoff/source calls', async ({ page }) => {
  const f = await mockCompanyTakeoff(page); await page.goto(`/company/takeoff/${setId}?company=FOREIGN`); await expect(page.getByRole('heading', { name: 'Company unavailable', exact: true })).toBeVisible(); expect(f.reads).toEqual([]);
});
for (const width of [900, 390]) test(`Company manual workflow keeps keyboard and source controls usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mockCompanyTakeoff(page); await page.goto(path); await fillManual(page);
  const locator = page.getByRole('textbox', { name: 'Drawing locator', exact: true }); await locator.focus(); await page.keyboard.press('Tab'); await expect(page.getByRole('textbox', { name: 'Manual quantity reason', exact: true })).toBeFocused();
  const button = page.getByRole('button', { name: 'Save manual measurement', exact: true }); await button.scrollIntoViewIfNeeded(); await expect(button).toBeInViewport(); const box = (await button.boundingBox())!; expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width); expect(await page.evaluate(() => window.document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('phone takeoff card headings and saved detail fit inside padded surfaces', async ({ page }) => {
  await page.setViewportSize({width:390,height:844}); await mockCompanyTakeoff(page); await page.goto(path); await fillManual(page); await page.getByRole('button',{name:'Save manual measurement',exact:true}).click(); await page.getByRole('button',{name:'A101, room 12',exact:true}).click();
  const detail=page.getByRole('region',{name:'Saved Company measurement',exact:true});await expect(detail).toBeVisible();
  for (const name of ['Drawing source','Saved measurements']) {
    const bounds=await page.getByRole('heading',{name,exact:true}).evaluate(el=>{const box=el.getBoundingClientRect();let node:Element|null=el;while(node&&!node.matches('.surface'))node=node.parentElement??(node.getRootNode() as ShadowRoot).host;const surface=node!.getBoundingClientRect();return {left:box.left,right:box.right,innerLeft:surface.left+16,innerRight:surface.right-16};});
    expect.soft(bounds.left,name+' stays inside left padding').toBeGreaterThanOrEqual(bounds.innerLeft-1);expect.soft(bounds.right,name+' stays inside right padding').toBeLessThanOrEqual(bounds.innerRight+1);
  }
  const bounds=await detail.evaluate(el=>{const box=el.getBoundingClientRect();let node:Element|null=el;while(node&&!node.matches('.surface'))node=node.parentElement??(node.getRootNode() as ShadowRoot).host;const surface=node!.getBoundingClientRect();return {right:box.right,innerRight:surface.right-16};});expect(bounds.right,'saved detail does not extend behind clipped card edge').toBeLessThanOrEqual(bounds.innerRight+1);
});
