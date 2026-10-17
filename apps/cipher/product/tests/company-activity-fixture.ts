import { expect, type Page, type Route } from '@playwright/test';
import type { HistoryItem, HistoryList } from '../src/api/contracts.generated';
import { mockWorkspace, company } from './fixture';

export { company };
export const otherCompany = 'TEST-AEC-OTHER';
export const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
export const event = (n: number, overrides: Partial<HistoryItem> = {}): HistoryItem => ({
  id: `HISTORY-FIXTURE-${n}`, event: n === 1 ? 'ricky.company.proposal.draft-saved' : n === 2 ? 'estimate.created' : 'commercial.proposal.revision.created',
  actor: n === 1 ? 'Casey Registered' : 'Alex Registered', at: `2026-10-17T12:${String(59 - n % 60).padStart(2, '0')}:00.123456Z`,
  subject_type: n === 2 ? 'Cipher Estimate' : 'Cipher Proposal Revision', subject_id: id(n),
  details: { revision_number: 2 }, ...overrides,
});
export const historyPage = (items: HistoryItem[], next: string | null = null): HistoryList => ({ items, total: null, limit: 25, count_mode: 'none', next_cursor: next });

export async function activityFixture(page: Page, options: { firstPage?: HistoryList; morePage?: HistoryList; secondCompany?: boolean } = {}) {
  const core = await mockWorkspace(page); let identity = { user: 'test.pm@example.invalid', person: 'TEST-PERSON-001' };
  const first = options.firstPage ?? historyPage([event(1), event(2)], 'signed-company-history-page-2');
  const more = options.morePage ?? historyPage([event(3)]);
  let error: { status: number; code: string } | undefined; let substitute: unknown;
  let holdNext = false; const waiting: { route: Route; release: () => void }[] = [];
  const requests: { company: string | null; cursor: string | null; query: Record<string, string> }[] = [];
  const answer = (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: {
    schema: 'cipher.api.v1', request_id: id(800), meta: { api_version: 'v1', request_id: id(800), server_time: '2026-10-17T12:00:00Z' }, ...data as object,
  } }) });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => answer(route, { data: {
    authenticated: true, user: identity.user, person: { id: identity.person, display_name: 'Registered fixture person' },
    companies: [{ id: company, name: 'Synthetic Company One' }, ...(options.secondCompany ? [{ id: otherCompany, name: 'Synthetic Company Two' }] : [])],
    company_scopes: [company, ...(options.secondCompany ? [otherCompany] : [])].map(company => ({ company, capabilities: ['company.read', 'estimate.read', 'document.read'] })),
    capabilities: ['company.read'], csrf_token: 'test-csrf', site_mode: 'synthetic',
  } }));
  await page.route('**/api/method/cipher_aec.api.company.history*', async route => {
    const url = new URL(route.request().url()); const query = Object.fromEntries(url.searchParams.entries());
    expect(route.request().method()).toBe('GET'); expect(query.limit).toBe('25'); expect(query.count_mode).toBe('none');
    expect(Object.keys(query).sort()).toEqual(query.cursor ? ['company', 'count_mode', 'cursor', 'limit'] : ['company', 'count_mode', 'limit']);
    requests.push({ company: url.searchParams.get('company'), cursor: url.searchParams.get('cursor'), query });
    const observedError = error; const observedSubstitute = substitute;
    const observed = query.company === otherCompany ? historyPage([event(90, { actor: 'Other registered person', event: 'document.revision.uploaded' })]) : query.cursor ? more : first;
    if (holdNext) { holdNext = false; await new Promise<void>(release => waiting.push({ route, release })); }
    if (observedError) return answer(route, { error: { code: observedError.code, message: 'This activity page is unavailable with current access.', details: {}, retryable: false } }, observedError.status);
    return answer(route, { data: observedSubstitute === undefined ? observed : observedSubstitute });
  });
  return { ...core, requests, first, more,
    deny: (status: number, code: string) => { error = { status, code }; }, restore: () => { error = undefined; substitute = undefined; },
    substitute: (value: unknown) => { substitute = value; }, holdNext: () => { holdNext = true; },
    waiting: () => waiting.length, release: () => { waiting.splice(0).forEach(row => row.release()); },
    identity: (user: string, person: string) => { identity = { user, person }; },
  };
}
