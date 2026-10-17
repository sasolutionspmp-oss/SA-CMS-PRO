import { expect, test } from '@playwright/test';
import { activityFixture, company, otherCompany, event, historyPage } from './company-activity-fixture';
import { draftFixture } from './company-draft-save-fixture';
import { openSuggestions } from './company-ricky-proposals-fixture';

test('bounded Company activity preserves actual event order, actor and timestamp without totals or eager next reads', async ({ page }) => {
  const fixture = await activityFixture(page); await page.goto('/company/activity');
  await expect(page.getByRole('heading', { name: 'Company activity', exact: true })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Company activity events' }).getByRole('listitem')).toHaveCount(2);
  await expect(page.locator('.company-activity-list strong')).toHaveText(['Suggestion saved as draft', 'Estimate created']);
  await expect(page.getByText('Casey Registered', { exact: false })).toBeVisible();
  await expect(page.locator('time').first()).toHaveAttribute('datetime', event(1).at);
  await expect(page.locator('time').first()).toHaveText('Oct 17, 2026, 12:58:00 PM UTC');
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous page', exact: true })).toBeDisabled();
  // Development StrictMode can abort its initial effect after the GET reaches
  // the fixture. Neither initial request may prefetch another cursor/page.
  const initialReads = fixture.requests.length; expect(initialReads).toBeGreaterThanOrEqual(1); expect(initialReads).toBeLessThanOrEqual(2);
  expect(fixture.requests.every(row => row.cursor === null && JSON.stringify(row.query) === JSON.stringify({ company, limit: '25', count_mode: 'none' }))).toBe(true);
  expect(fixture.writes).toHaveLength(0);
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  await expect(page.locator('.company-activity-list strong')).toHaveText(['Proposal draft saved']);
  await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
  expect(fixture.requests).toHaveLength(initialReads + 1); expect(fixture.requests.at(-1)?.cursor).toBe('signed-company-history-page-2');
  await page.getByRole('button', { name: 'Previous page', exact: true }).click();
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  await expect(page.locator('.company-activity-list strong')).toHaveText(['Suggestion saved as draft', 'Estimate created']);
  expect(fixture.requests).toHaveLength(initialReads + 2); expect(fixture.requests.at(-1)?.cursor).toBeNull();
});

for (const refusal of [{ status: 403, code: 'source_unavailable' }, { status: 404, code: 'source_unavailable' }, { status: 409, code: 'cursor_invalid' }]) test(`${refusal.status} source or cursor refusal hides prior rows and requires explicit fresh paging`, async ({ page }) => {
  const fixture = await activityFixture(page); await page.goto('/company/activity');
  await expect(page.getByText('Suggestion saved as draft', { exact: true })).toBeVisible();
  fixture.deny(refusal.status, refusal.code);
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Recorded activity' }).getByRole('alert')).toBeVisible();
  await expect(page.getByRole('list', { name: 'Company activity events' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Previous page', exact: true })).toHaveCount(0);
  fixture.restore(); await page.getByRole('button', { name: 'Refresh activity', exact: true }).click();
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible(); expect(fixture.requests.at(-1)?.cursor).toBeNull();
});

test('an unauthorized Company query never falls back to another Company activity', async ({ page }) => {
  const fixture = await activityFixture(page); await page.goto('/company/activity?company=UNAUTHORIZED');
  await expect(page.getByRole('heading', { name: 'Company context unavailable', exact: true })).toBeVisible();
  expect(fixture.requests).toHaveLength(0);
});

test('changing Company drops an older in-flight page and restarts cursor state', async ({ page }) => {
  const fixture = await activityFixture(page, { secondCompany: true }); await page.goto('/company/activity');
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible(); fixture.holdNext();
  await page.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect.poll(fixture.waiting).toBe(1);
  await page.getByRole('combobox', { name: 'Company', exact: true }).click();
  await page.getByRole('option', { name: 'Synthetic Company Two', exact: true }).click();
  await expect(page.getByText('Document revision uploaded', { exact: true })).toBeVisible(); fixture.release();
  await expect(page.getByText('Proposal draft saved', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  expect(fixture.requests.at(-1)?.company).toBe(otherCompany); expect(fixture.requests.at(-1)?.cursor).toBeNull();
});

for (const identity of [{ user: 'same-person-alias' }, { personId: 'different-person' }]) test(`changing ${Object.keys(identity)[0]} clears paging and drops the old in-flight result`, async ({ page }) => {
  const fixture = await activityFixture(page); await page.goto('/tests/company-activity.html');
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible(); fixture.holdNext();
  await page.getByRole('button', { name: 'Next page', exact: true }).click(); await expect.poll(fixture.waiting).toBe(1);
  fixture.substitute(historyPage([event(88, { event: 'identity.current.observation' })]));
  await page.evaluate(detail => window.dispatchEvent(new CustomEvent('test:activity-context', { detail })), identity);
  await expect(page.getByText('Identity current observation', { exact: true })).toBeVisible(); fixture.release();
  await expect(page.getByText('Proposal draft saved', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible(); expect(fixture.requests.at(-1)?.cursor).toBeNull();
});

test('permission removal clears cached rows and does not read with absent Company capability', async ({ page }) => {
  const fixture = await activityFixture(page); await page.goto('/tests/company-activity.html');
  await expect(page.getByText('Suggestion saved as draft', { exact: true })).toBeVisible(); const count = fixture.requests.length;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('test:activity-context', { detail: { capabilities: [] } })));
  await expect(page.getByRole('heading', { name: 'Company activity unavailable', exact: true })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Company activity events' })).toHaveCount(0); expect(fixture.requests).toHaveLength(count);
});

for (const domain of [
  { capability: 'commercial.read', event: 'commercial.proposal.revision.created', subject_type: 'Cipher Proposal Revision' },
  { capability: 'estimate.read', event: 'estimate.revision.calculated', subject_type: 'Cipher Estimate Revision' },
  { capability: 'document.read', event: 'document.revision.uploaded', subject_type: 'Cipher Document Revision' },
]) test(`known ${domain.capability} loss with Company read retained clears source rows and reauthorizes page one`, async ({ page }) => {
  const fixture = await activityFixture(page, { morePage: historyPage([event(3, { event: domain.event, subject_type: domain.subject_type })]) });
  try {
    await page.goto('/tests/company-activity.html'); await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Next page', exact: true }).click(); await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
    await expect(page.getByRole('list', { name: 'Company activity events' })).toBeVisible();
    fixture.substitute(historyPage([])); fixture.holdNext();
    await page.evaluate(capability => window.dispatchEvent(new CustomEvent('test:activity-context', { detail: {
      capabilities: ['company.read', 'commercial.read', 'estimate.read', 'document.read'].filter(value => value !== capability),
    } })), domain.capability);
    await expect(page.getByRole('list', { name: 'Company activity events' })).toHaveCount(0);
    await expect(page.getByRole('status').filter({ hasText: 'Loading Company activity' })).toBeVisible();
    await expect.poll(fixture.waiting).toBe(1); expect(fixture.requests.at(-1)?.cursor).toBeNull();
    fixture.release(); await expect(page.getByRole('heading', { name: 'No visible Company activity', exact: true })).toBeVisible();
    await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  } finally { fixture.release(); }
});

test('known domain capability loss aborts the old cursor request and drops its late source-bearing page', async ({ page }) => {
  const fixture = await activityFixture(page);
  try {
    await page.goto('/tests/company-activity.html'); await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
    fixture.holdNext(); await page.getByRole('button', { name: 'Next page', exact: true }).click(); await expect.poll(fixture.waiting).toBe(1);
    fixture.substitute(historyPage([]));
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('test:activity-context', { detail: { capabilities: ['company.read', 'commercial.read', 'estimate.read'] } })));
    await expect(page.getByRole('heading', { name: 'No visible Company activity', exact: true })).toBeVisible();
    expect(fixture.requests.at(-1)?.cursor).toBeNull(); fixture.release();
    await expect(page.getByText('Proposal draft saved', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  } finally { fixture.release(); }
});

test('reordering unchanged Company capabilities preserves the current authorized page', async ({ page }) => {
  const fixture = await activityFixture(page); await page.goto('/tests/company-activity.html');
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next page', exact: true }).click(); await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  const count = fixture.requests.length;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('test:activity-context', { detail: { capabilities: ['document.read', 'estimate.read', 'commercial.read', 'company.read'] } })));
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  await expect(page.getByText('Proposal draft saved', { exact: true })).toBeVisible(); expect(fixture.requests).toHaveLength(count);
});

test('a mounted global mutation lock disables every activity navigation control', async ({ page }) => {
  await activityFixture(page); await page.goto('/tests/company-activity.html');
  await expect(page.getByRole('button', { name: 'Open estimate', exact: true })).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('test:activity-context', { detail: { navigationLocked: true } })));
  for (const name of ['Open estimate', 'Next page', 'Previous page', 'Refresh activity']) await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
  await expect(page.getByText('Suggestion saved as draft', { exact: true })).toBeVisible();
});

test('malformed response clears old rows; details are collapsed and authored text stays escaped', async ({ page }) => {
  const fixture = await activityFixture(page, { firstPage: historyPage([event(1, { details: { note: '<script>window.historyInjected=true</script>' } })]) });
  await page.goto('/company/activity'); await expect(page.getByText('Suggestion saved as draft', { exact: true })).toBeVisible();
  await expect(page.locator('.company-activity-event details')).not.toHaveAttribute('open');
  await page.getByText('Record details', { exact: true }).click(); await expect(page.locator('.company-activity-event pre')).toContainText('<script>');
  expect(await page.evaluate(() => 'historyInjected' in window)).toBe(false);
  fixture.substitute({ ...fixture.first, total: 10234 }); await page.getByRole('button', { name: 'Refresh activity', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Recorded activity' }).getByRole('alert')).toBeVisible(); await expect(page.getByRole('list', { name: 'Company activity events' })).toHaveCount(0);
});

test('implemented record navigation preserves Company context and unsupported revision IDs do not become links', async ({ page }) => {
  await activityFixture(page); await page.goto('/company/activity');
  await expect(page.getByRole('button', { name: 'Open estimate', exact: true })).toBeVisible();
  expect(await page.locator('.company-activity-list').getByRole('button').count()).toBe(1);
  await page.getByRole('button', { name: 'Open estimate', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/company/estimates/${event(2).subject_id}\\?company=${company}$`));
});

test('the new activity navigation cannot escape an uncertain original draft save', async ({ page }) => {
  await draftFixture(page, { lost: true }); await openSuggestions(page);
  await page.getByRole('button', { name: 'Review draft save', exact: true }).click();
  await page.getByRole('checkbox', { name: 'I reviewed the proposed draft and its original sources', exact: true }).click();
  await page.getByRole('button', { name: 'Save reviewed scope draft', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original draft save', exact: true }); await expect(recover).toBeVisible();
  const original = page.url(); await page.getByRole('treeitem', { name: 'Company activity', exact: true }).click();
  await expect(page).toHaveURL(original); await expect(recover).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Company activity', exact: true })).toHaveCount(0);
});

for (const width of [390,900]) test(`activity paging and record details work by keyboard at ${width}px without overflow`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); await activityFixture(page);
  await page.goto('/company/activity'); await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  const next = page.getByRole('button', { name: 'Next page', exact: true }); await next.focus(); await page.keyboard.press('Enter');
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  const summary = page.getByText('Record details', { exact: true }); await summary.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('.company-activity-event details')).toHaveAttribute('open');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  expect(await page.locator('.company-activity-surface').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  const refresh = page.getByRole('button', { name: 'Refresh activity', exact: true }); await refresh.focus(); await page.keyboard.press('Enter');
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
});
