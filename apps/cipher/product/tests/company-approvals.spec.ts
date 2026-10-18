import { expect, test, type Page, type Route } from '@playwright/test';
import { mockWorkspace, company } from './fixture';

const secondCompany = 'TEST-SECOND-COMPANY';
const packetId = 'TEST-EXACT-REVIEW';
async function fixture(page: Page, options: { login?: boolean; lost?: boolean; company?: string } = {}) {
  await mockWorkspace(page);
  let authenticated = !options.login; let denied = 0; let state = 'Pending';
  const reads: URL[] = []; const writes: string[] = []; let effectCount = 0;
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const packet = (id = packetId) => ({ id, company: options.company || company, scope_type: 'Company', project: null, action: 'calibration.verify.v1', subject: { id: 'TEST-CALIBRATION', type: 'Cipher Calibration', label: 'Utility drawing scale review' }, requester: { id: 'OTHER-PERSON', display_name: 'Other requester' }, created_at: '2026-10-15T12:00:00Z', expires_at: '2030-10-15T12:00:00Z', manifest_hash: 'a'.repeat(64), source_version: 'b'.repeat(64), policy: { id: 'TEST-POLICY', label: 'Independent review', synthetic: true }, state, decisions: [], actions: { can_decide: state === 'Pending', can_execute: false, can_withdraw: false, disabled_reason: null }, review_manifest: { subject: { doctype: 'Cipher Calibration', name: 'TEST-CALIBRATION', label: 'Utility drawing scale review' }, sources: [], effect: { verification: 'Independent scale review' }, summary: { known_length: '200.00', unit: 'Foot' } } });
  await page.route('**/api/method/login', route => { authenticated = true; return route.fulfill({ contentType: 'application/json', body: '{"message":"Logged In"}' }); });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => authenticated ? envelope(route, { authenticated: true, user: 'reviewer@example.invalid', person: { id: 'TEST-REVIEWER', display_name: 'Casey Reviewer' }, companies: [{ id: company, name: 'First Company' }, { id: secondCompany, name: 'Second Company' }], company_scopes: [company, secondCompany].map(name => ({ company: name, capabilities: ['company.read', 'approval.decide'] })), capabilities: ['company.read', 'approval.decide'], csrf_token: 'test-csrf', site_mode: 'synthetic' }) : route.fulfill({ status: 401, contentType: 'application/json', body: '{"message":{"schema":"cipher.api.v1","error":{"code":"unauthenticated","message":"Sign in to continue."}}}' }));
  await page.route('**/api/method/cipher_aec.api.company_approvals.*', route => {
    const request = route.request(); const url = new URL(request.url()); reads.push(url);
    const method = url.pathname.split('.').pop();
    if (method === 'list_packets') {
      expect(url.searchParams.get('limit')).toBe('10'); expect(url.searchParams.get('count_mode')).toBe('none');
      const later = Boolean(url.searchParams.get('cursor'));
      return envelope(route, { items: later ? [packet('TEST-LATER-PACKET')] : Array.from({ length: 10 }, (_, index) => packet(index ? `TEST-PACKET-${index}` : packetId)), limit: 10, next_cursor: later ? null : 'signed-test-next', count_mode: 'none', total: null });
    }
    if (method === 'read_packet') {
      if (denied) return route.fulfill({ status: denied, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'capability_denied', message: 'Current review access is unavailable.' } } }) });
      expect(url.searchParams.get('company')).toBe(options.company || company);
      expect(url.searchParams.get('packet_id')).toBe(packetId);
      return envelope(route, packet());
    }
    const raw = request.postData()!; const body = JSON.parse(raw); writes.push(raw);
    expect(request.headers()['idempotency-key']).toBe(body.operation_id); expect(body).not.toHaveProperty('expected_packet');
    if (!effectCount) { effectCount++; state = 'Granted'; if (options.lost) return route.abort('failed'); }
    if (options.lost && writes.length === 2) return route.fulfill({ status: 403, contentType: 'application/json', body: '{"message":{"schema":"cipher.api.v1","error":{"code":"capability_denied","message":"Current review access is unavailable."}}}' });
    return envelope(route, { packet: packet(), operation: { id: body.operation_id, status: 'succeeded', replayed: writes.length > 1 } });
  });
  return { reads, writes, deny: (status: number) => { denied = status; }, effects: () => effectCount };
}
test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));
test('copied exact review preserves authorized second Company through sign-in and never fetches inbox', async ({ page }) => {
  const mock = await fixture(page, { login: true, company: secondCompany });
  const path = `/company/work/${packetId}?company=${encodeURIComponent(secondCompany)}`;
  await page.goto(path); await page.getByLabel('Email or username', { exact: true }).fill('reviewer@example.invalid'); await page.getByLabel('Password', { exact: true }).fill('explicit-test-password'); await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Utility drawing scale review', exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp('company=TEST-SECOND-COMPANY$'));
  await expect(page.locator('ui5-select[accessible-name="Company"]')).toContainText('Second Company');
  expect(mock.reads.length).toBeGreaterThan(0); expect(mock.reads.every(url => url.pathname.endsWith('read_packet') && url.searchParams.get('company') === secondCompany)).toBe(true);
  const link = page.getByRole('link', { name: 'Open exact review', exact: true }); await expect(link).toHaveAttribute('href', path);
});
for (const status of [403, 404]) test(`exact review refresh respects current${status} and removes action controls without inbox reads`, async ({ page }) => {
  const mock = await fixture(page); await page.goto(`/company/work/${packetId}?company=${company}`);
  await expect(page.getByRole('button', { name: 'Grant company approval', exact: true })).toBeVisible(); mock.deny(status); await page.reload();
  await expect(page.getByRole('note', { name: status === 403 ? /You don’t have access to this item\./ : /This item isn’t available\./ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Grant company approval', exact: true })).toHaveCount(0);
  expect(mock.reads.every(url => url.pathname.endsWith('read_packet'))).toBe(true); expect(mock.writes).toEqual([]);
});
test('unavailable Company in copied review link does not fall back to the first Company or read packet', async ({ page }) => {
  const mock = await fixture(page); await page.goto(`/company/work/${packetId}?company=FOREIGN-COMPANY`);
  await expect(page.getByRole('heading', { name: 'Company unavailable', exact: true })).toBeVisible();
  expect(mock.reads).toEqual([]); await expect(page.getByRole('button', { name: 'Grant company approval', exact: true })).toHaveCount(0);
});
test('ordinary Company inbox uses ten-row cursor pages without implying an exact total and exposes copyable links', async ({ page }) => {
  const mock = await fixture(page); await page.goto('/company/work');
  const table = page.locator('ui5-table[accessible-name="Company approval inbox"]'); await expect(table.locator('ui5-table-row')).toHaveCount(10);
  await expect(table.getByRole('link', { name: 'Open exact review', exact: true }).first()).toHaveAttribute('href', `/company/work/${packetId}?company=${company}`);
  await expect(page.getByText(/total records|\d+ records total/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Next page', exact: true }).click(); await expect(table.locator('ui5-table-row')).toHaveCount(1);
  expect(mock.reads.at(-1)!.searchParams.get('cursor')).toBe('signed-test-next');
});
test('exact review lost grant stays mounted and recovers original payload through later denial', async ({ page }) => {
  const mock = await fixture(page, { lost: true }); await page.goto(`/company/work/${packetId}?company=${company}`);
  const dialog = page.locator('ui5-dialog[header-text="Review company approval packet"]');
  await dialog.getByRole('checkbox', { name: 'I reviewed this exact company action and its sources', exact: true }).click(); await dialog.getByRole('button', { name: 'Grant company approval', exact: true }).click();
  const recover = dialog.getByRole('button', { name: 'Recover company approval action', exact: true }); await expect(recover).toBeEnabled(); await expect(dialog.getByRole('button', { name: 'Close company review', exact: true })).toBeDisabled();
  await expect(dialog.locator('ui5-link').filter({ hasText: 'Open exact review' })).toHaveAttribute('disabled', '');
  await recover.click(); await expect(recover).toBeEnabled(); await recover.click(); await expect(dialog.getByRole('note', { name: /Approval granted/ })).toBeVisible();
  expect(mock.writes).toHaveLength(3); expect(new Set(mock.writes).size).toBe(1); expect(mock.effects()).toBe(1); expect(mock.reads.every(url => !url.pathname.endsWith('list_packets'))).toBe(true);
});
test('Company inbox keeps subject state and exact review controls inside nested workspace bounds at three widths', async ({ page }) => {
  await fixture(page); await page.goto('/company/work');
  const table = page.locator('ui5-table[accessible-name="Company approval inbox"]');
  await expect(table.locator('ui5-table-row')).toHaveCount(10);
  for (const width of [1440, 900, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => page.locator('.workspace-main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    const title = page.getByRole('heading', { name: 'Company approvals', exact: true });
    await expect.poll(async () => (await title.boundingBox())!.x).toBeGreaterThanOrEqual(0);
    const row = table.locator('ui5-table-row').first();
    const subject = row.locator('ui5-table-cell').first(); const state = row.getByText('Pending', { exact: true });
    const review = row.getByRole('button', { name: 'Review company packet', exact: true });
    const link = row.getByRole('link', { name: 'Open exact review', exact: true });
    for (const content of [subject, state, review, link]) {
      await expect(content).toBeVisible();
      await expect.poll(async () => { const box = (await content.boundingBox())!; return box.x >= 0 && box.x + box.width <= width; }).toBe(true);
    }
    await review.focus(); await review.press('Tab'); await expect(link).toBeFocused();
  }
});
