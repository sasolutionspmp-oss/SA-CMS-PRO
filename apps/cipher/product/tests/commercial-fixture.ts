import { expect, type Page, type Route } from '@playwright/test';
import { company, mockWorkspace } from './fixture';
import type { ComComposition, ComProposal, ComProposalDetail, ComPursuit, ComRevision } from '../src/api/commercial.generated';
export const pursuitId = '50000000-0000-4000-8000-000000000001';
export const proposalId = '50000000-0000-4000-8000-000000000002';
export const comUnitId = '50000000-0000-4000-8000-000000000003';
export const comLineId = '50000000-0000-4000-8000-000000000004';
export async function mockCommercial(page: Page, options: { loseFirst?: boolean; malformedFirst?: boolean; denyRecoveryOnce?: boolean; denyRecoveryStatus?: number; staleFirst?: boolean; denied?: boolean } = {}) {
  await mockWorkspace(page);
  const requests: { method: string; body: Record<string, unknown> }[] = []; let effects = 0; let first = true;
  const receipts = new Map<string, unknown>(); const revisions = new Map<string, ComRevision>();
  let pursuit: ComPursuit = { id: pursuitId, company, author_person: 'TEST-PERSON-001', revision_number: 1, opportunity: 'TEST-OPPORTUNITY', native_version: 'native1', party_type: 'Customer', party_id: 'TEST-CUSTOMER', title: 'Synthetic commercial pursuit', fields: { title: 'Synthetic commercial pursuit', sector: 'Civil infrastructure' }, stage: 'identified' };
  const composition: ComComposition = { currency: 'USD', price_list: 'TEST-SELLING-LIST', valid_till: '2026-12-31', terms: 'Synthetic authored terms', sections: [{ id: '50000000-0000-4000-8000-000000000005', kind: 'scope', title: 'Construction scope', text: 'Synthetic pipe work' }], price_lines: [{ id: comLineId, description: 'Synthetic authored pipe', quantity: '10', unit_id: comUnitId, unit_revision: 1, rate: '12.50', selected: true, item_code: null, alternate_group: null }], source_references: [], estimate_revision: null };
  let proposal: ComProposal;
  const make = (number: number, authored: ComComposition): ComRevision => {
    const id = `60000000-0000-4000-8000-${String(number).padStart(12, '0')}`; const fingerprint = (number === 1 ? 'a' : number === 2 ? 'b' : 'c').repeat(64); const total = authored.price_lines[0].quantity === '11' ? '137.50' : '125.00';
    const revision: ComRevision = { id, company, author_person: 'TEST-PERSON-001', revision_number: number, proposal: proposalId, predecessor: number > 1 ? proposal.current_revision : null, status: 'draft', composition: structuredClone(authored), pricing: { policy: 'native-no-tax-no-discount-half-up-v1', currency_exponent: 2, lines: authored.price_lines.map(line => ({ ...line, item_code: line.item_code || null, alternate_group: line.alternate_group || null, amount: total })), total }, currency_policy: { currency: 'USD', currency_exponent: 2, fraction_units: 100, native_currency_version: 'currency1', price_list: { name: 'TEST-SELLING-LIST', version: 'list1', currency: 'USD' } }, units: { [comUnitId]: { target: { doctype: 'UOM', name: 'Meter' } } }, native: { id: 'TEST-QUOTATION', version: `native${number}`, company, quotation_to: 'Customer', party_name: 'TEST-CUSTOMER', opportunity: 'TEST-OPPORTUNITY', currency: 'USD', valid_till: authored.valid_till, terms: authored.terms, docstatus: 0, totals: { total }, items: [], taxes: [], selling_price_list: authored.price_list, price_list_currency: 'USD' }, native_fingerprint: fingerprint, company_policy: { base_currency: 'USD', native_company_version: 'company1' } };
    revisions.set(id, revision); proposal = { id: proposalId, company, author_person: 'TEST-PERSON-001', revision_number: number, pursuit: pursuitId, quotation: 'TEST-QUOTATION', party_type: 'Customer', party_id: 'TEST-CUSTOMER', title: pursuit.title, current_revision: id, native_fingerprint: fingerprint, native_version: `native${number}` }; return revision;
  };
  make(1, composition);
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const failure = (route: Route, status: number) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: status === 412 ? 'stale_proposal' : 'capability_denied', message: status === 412 ? 'Proposal source changed.' : 'Commercial access denied.' } } }) });
  await page.route('**/api/method/cipher_aec.api.v1.session', route => envelope(route, { authenticated: true, user: 'test.pm@example.invalid', person: { id: 'TEST-PERSON-001', display_name: 'Alex Morgan' }, companies: [{ id: company, name: 'Synthetic AEC Company' }], company_scopes: [{ company, capabilities: options.denied ? ['company.read'] : ['company.read', 'commercial.read', 'commercial.write'] }], capabilities: ['company.read'], csrf_token: 'test-csrf', site_mode: 'synthetic' }));
  await page.route('**/api/method/cipher_aec.api.masters.*', route => {
    const url = new URL(route.request().url()); const method = url.pathname.split('.').pop();
    const items = method === 'parties' ? [{ id: 'TEST-CUSTOMER', label: 'Existing native customer', kind: 'Customer', version: 'customer1' }] : method === 'currencies' ? [{ id: 'USD', label: 'USD', kind: 'Currency', version: 'currency1', exponent: 2 }, { id: 'EUR', label: 'EUR', kind: 'Currency', version: 'currency2', exponent: 2 }] : method === 'price_lists' ? [{ id: 'TEST-SELLING-LIST', label: 'Native USD selling list', kind: 'Price List', version: 'list1', currency: 'USD' }] : [{ id: 'Meter', label: 'Meter', kind: 'UOM', version: 'unit1', unit_id: comUnitId, revision: 1, dimension: 'length', precision: 3 }];
    return envelope(route, { items, next_cursor: null, total: items.length, limit: 50, count_mode: 'exact', company_currency: 'USD' });
  });
  await page.route('**/api/method/cipher_aec.commercial.api.*', async route => {
    const request = route.request(); const url = new URL(request.url()); const method = url.pathname.split('.').pop()!;
    if (options.denied) return failure(route, 403);
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>; requests.push({ method, body }); expect(request.headers()['idempotency-key']).toBe(body.operation_id); expect(request.headers()['x-frappe-csrf-token']).toBe('test-csrf'); expect(body).not.toHaveProperty('project');
      const old = receipts.get(String(body.operation_id));
      if (old) return options.denyRecoveryOnce && requests.length === 2 ? failure(route, options.denyRecoveryStatus || 403) : envelope(route, old);
      if (method === 'save_proposal_revision' && options.staleFirst && first) { first = false; make(2, { ...composition, terms: 'Concurrent native source change' }); return failure(route, 412); }
      if (method === 'save_proposal_revision') { expect(body.expected_revision).toBe(proposal.revision_number); expect(body.expected_native_fingerprint).toBe(proposal.native_fingerprint); }
      const operation = { id: String(body.operation_id), status: 'succeeded', replayed: false }; let result;
      if (method === 'create_pursuit' || method === 'update_pursuit') { pursuit = { ...pursuit, fields: body.fields as ComPursuit['fields'], title: String((body.fields as { title: string }).title), revision_number: method === 'create_pursuit' ? 1 : pursuit.revision_number + 1 }; result = { pursuit, operation }; }
      else { const revision = make(method === 'create_proposal' ? 1 : proposal.revision_number + 1, body.composition as ComComposition); result = { proposal, revision, operation }; }
      effects++; receipts.set(operation.id, { ...result, operation: { ...operation, replayed: true } });
      if (first && options.loseFirst) { first = false; return route.abort('failed'); }
      if (first && options.malformedFirst) { first = false; return envelope(route, { operation }); }
      return envelope(route, result);
    }
    if (method === 'pursuits' || method === 'proposals') return envelope(route, { items: method === 'pursuits' ? [pursuit] : [proposal], next_cursor: null, total: 1, limit: 30, count_mode: 'exact' });
    if (method === 'pursuit') return envelope(route, pursuit);
    if (method === 'proposal') return envelope(route, { ...proposal, revision: revisions.get(proposal.current_revision)! } satisfies ComProposalDetail);
    if (method === 'proposal_revision') return envelope(route, revisions.get(url.searchParams.get('revision_id')!));
    if (method === 'compare_revisions') { const before = revisions.get(url.searchParams.get('left_revision')!)!; const after = revisions.get(url.searchParams.get('right_revision')!)!; return envelope(route, { proposal_id: proposalId, left_revision: before.id, right_revision: after.id, changes: { sections: { added: [], removed: [], changed: [], order_changed: false }, price_lines: { added: [], removed: [], changed: [{ id: comLineId, before: before.composition.price_lines[0], after: after.composition.price_lines[0] }], order_changed: false }, terms: { before: before.composition.terms, after: after.composition.terms, changed: before.composition.terms !== after.composition.terms }, validity: { before: before.composition.valid_till, after: after.composition.valid_till, changed: false } } }); }
    return route.fulfill({ status: 404 });
  });
  return { requests, revisions, getEffects: () => effects, getProposal: () => proposal };
}
