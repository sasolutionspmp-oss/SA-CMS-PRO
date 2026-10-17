// Synthetic browser contract data only. Never loaded by the product or runtime.
import { expect, type Page, type Route } from '@playwright/test';
import type { CompanyDraftSaveSubject, CompanyDraftSaveResponse, CompanyDraftSaveCanonicalResult, ComRevision, ComComposition, CompanyEstSnapshotRecord, CompanyEstRevisionRecord } from '../src/api/company-draft-saves.generated';
import type { CompanyEstLineRecord, CompanyEstConversionRecord } from '../src/api/company-estimating.generated';
import type { DraftSaveBase } from '../src/api/company-draft-saves-validation';
import { company } from './fixture';
import { citation, digest, id, ids, saved, suggestionFixture, unitManifest } from './company-ricky-proposals-fixture';

export const actor = { user: 'test.pm@example.invalid', person: 'TEST-PERSON-001' };
export function draftData(action: 'aec.scope.draft' | 'aec.estimate.draft' = 'aec.scope.draft') {
  const original = saved(action), proposal = original.proposal, scope = action === 'aec.scope.draft';
  const stamp = new Date().toISOString();
  proposal.created_at = stamp; proposal.expires_at = new Date(Date.now() + 300000).toISOString();
  original.run.created_at = stamp; original.run.completed_at = stamp;
  let base: DraftSaveBase; let payload: CompanyDraftSaveSubject['payload']; let canonical: CompanyDraftSaveCanonicalResult;
  if (scope) {
    const composition: ComComposition = { currency: 'USD', price_list: 'TEST-SELLING-LIST', valid_till: '2026-12-31', terms: 'Retain net 30 payment terms.', sections: [{ id: id(40), kind: 'scope', title: 'Original scope', text: 'Original drainage work.' }], price_lines: [{ id: id(41), description: 'Drainage design', quantity: '10', unit_id: ids.unit, unit_revision: 1, rate: '12.50', selected: true, item_code: null, alternate_group: null }], source_references: [], estimate_revision: null, estimate_reference: null };
    const revision: ComRevision = { id: ids.commercialRevision, company, author_person: actor.person, revision_number: 1, proposal: ids.commercial, predecessor: null, status: 'draft', composition, pricing: { policy: 'native-no-tax-no-discount-half-up-v1', currency_exponent: 2, lines: [{ ...composition.price_lines[0], item_code: null, alternate_group: null, amount: '125.00' }], total: '125.00' }, currency_policy: { currency: 'USD', currency_exponent: 2, fraction_units: 100, native_currency_version: 'currency1', price_list: { name: 'TEST-SELLING-LIST', version: 'list1', currency: 'USD' } }, units: {}, native: { id: 'Fixture Quotation', version: 'native1', company, quotation_to: 'Customer', party_name: 'Fixture Customer', opportunity: 'Fixture Opportunity', currency: 'USD', valid_till: composition.valid_till, terms: composition.terms, docstatus: 0, totals: { total: '125.00' }, items: [], taxes: [], selling_price_list: composition.price_list, price_list_currency: 'USD' }, native_fingerprint: 'a'.repeat(64), company_policy: { base_currency: 'USD', native_company_version: 'company1' } };
    const next = structuredClone(composition);
    next.sections.push({ id: id(42), kind: 'scope', title: 'Unverified author suggestion: Suggested scope', text: 'Review the drainage work from the original source.' }, { id: id(43), kind: 'assumption', title: 'Unverified author statement', text: 'Verify access conditions.' });
    next.source_references = [{ revision_id: citation.revision_id, page: 1, excerpt_sha256: citation.excerpt_sha256, source_sha256: citation.source_sha256, purpose: 'Human-reviewed unverified author suggestion', permission_basis: 'Current canonical source authorization' }];
    base = { kind: 'scope', revision };
    payload = { proposal_id: ids.commercial, expected_revision: 1, expected_native_fingerprint: revision.native_fingerprint, composition: next };
    canonical = { proposal: { id: ids.commercial, company, author_person: actor.person, revision_number: 2, pursuit: ids.pursuit, quotation: 'Fixture Quotation', party_type: 'Customer', party_id: 'Fixture Customer', title: 'Working commercial draft', current_revision: ids.successor, native_fingerprint: 'b'.repeat(64), native_version: 'native2' }, revision: { ...structuredClone(revision), id: ids.successor, predecessor: revision.id, revision_number: 2, composition: next, native_fingerprint: 'b'.repeat(64), native: { ...revision.native, version: 'native2' } } };
  } else {
    const common = { company, scope_type: 'Company' as const, project: null, author_person: actor.person, author_user: actor.user, created_at: stamp, status: 'draft-calculated' };
    const policy = { version: 'cipher.estimate.line-half-up.v1', rounding_mode: 'ROUND_HALF_UP', currency_exponent: 2, intermediate: 'exact-rational', line_rounding: 'sum-exact-components-then-round', component_allocation: 'nonnegative-largest-remainder-tie-by-stable-component-id', header_rounding: 'sum-rounded-lines' } as const;
    const money = (amount: string) => ({ amount, currency: 'USD' });
    const authored = { line_id: id(21), description: 'Saved drainage length', quantity: { amount: '1.000000000001', unit_id: ids.unit, precision: 12 }, cost_code: 'CIVIL', notes: '', alternate: '', included: true, rate_source_id: id(44), material_factor: '1', waste_fraction: '0' };
    const calculated = { line_id: authored.line_id, description: authored.description, quantity: authored.quantity, quantity_method: 'authored' as const, included: true, alternate: '', cost_code: 'CIVIL', components: [], unrounded_extension: { numerator: '1000000000001', denominator: '100000000000' }, extension: money('10.00') };
    const line: CompanyEstLineRecord = { ...common, id: ids.line, estimate: ids.estimate, estimate_revision: ids.estimateRevision, line_id: authored.line_id, authored, calculated };
    const rate = { id: id(44), source_id: id(44), revision: 1, predecessor: null, title: 'Saved rate', cost_type: 'material' as const, unit_id: ids.unit, rate_amount: '10', rate_precision: 2, currency: 'USD', quote_reference: 'Quote 1', quote_date: '2026-10-01', expiry_date: null, geography: 'Fixture site', inclusions: 'Materials', exclusions: 'Labor', freight_tax_assumptions: 'Excluded', permission_basis: 'Synthetic test', source_citations: [citation], item: null, party_type: null, party: null };
    const snapshot: CompanyEstSnapshotRecord = { ...common, id: ids.snapshot, status: 'calculated', estimate: ids.estimate, subject_type: 'Cipher Estimate Revision', subject_id: ids.estimateRevision, inputs: { schema: 'cipher.estimate.inputs.v2', unit_manifest: unitManifest as CompanyEstSnapshotRecord['inputs']['unit_manifest'], currency: 'USD', currency_exponent: 2, pricing_date: '2026-10-16', policy_version: policy.version, basis_description: 'Retained original basis.', basis_citations: [citation], rates: { [rate.id]: rate }, assemblies: {}, lines: [authored], adjustments: [] }, result: { schema: 'cipher.estimate.result.v1', policy, lines: [calculated], adjustments: [], direct: money('10.00'), indirect: money('0.00'), contingency: money('0.00'), total: money('10.00'), conversion_references: [], input_digest: 'c'.repeat(64), output_digest: 'd'.repeat(64) }, currency_policy: { currency: 'USD', currency_exponent: 2, fraction_units: 100, native_currency_version: 'currency1' }, input_digest: 'c'.repeat(64), output_digest: 'd'.repeat(64), source_citations: [citation] };
    const revision: CompanyEstRevisionRecord = { ...common, id: ids.estimateRevision, estimate: ids.estimate, revision_number: 1, predecessor: null, calculation_snapshot: ids.snapshot, currency: 'USD', pricing_date: '2026-10-16', policy_version: policy.version, line_record_ids: [line.id], source_citations: [citation], basis_description: snapshot.inputs.basis_description, direct: money('10.00'), indirect: money('0.00'), contingency: money('0.00'), total: money('10.00') };
    const definition = { id: id(48), revision: 1, from_unit_id: ids.unit, to_unit_id: id(49), dimension: 'length' as const, numerator: '1000', denominator: '1', source: 'Saved exact metric conversion' };
    snapshot.inputs.unit_manifest = structuredClone(snapshot.inputs.unit_manifest);
    snapshot.inputs.unit_manifest.records.push({ id: id(49), kind: 'uom', revision: 1, fields: { symbol: 'mm', dimension: 'length', precision: 12 }, target: { doctype: 'UOM', name: 'Millimetre' } });
    snapshot.inputs.unit_manifest.unit_conversions.push(definition);
    const conversion = { ...common, id: definition.id, definition, predecessor: null, source_citations: [citation], permission_basis: 'Synthetic original conversion', unit_manifest: snapshot.inputs.unit_manifest as CompanyEstConversionRecord['unit_manifest'] };
    base = { kind: 'estimate', revision, snapshot, lines: [line], conversions: [conversion] };
    payload = { estimate_id: ids.estimate, expected_revision: ids.estimateRevision, lines: [authored], adjustments: [], conversion_ids: [id(48)], basis_description: 'Retained original basis.; Unverified author suggestion: Review this existing canonical quantity.', basis_citations: [{ revision_id: citation.revision_id, page: 1, excerpt_sha256: citation.excerpt_sha256, source_sha256: citation.source_sha256 }] };
    canonical = { estimate: { ...common, id: ids.estimate, status: 'draft', title: 'Working drainage estimate', currency: 'USD', pricing_date: '2026-10-16', revision_number: 2, current_revision: ids.successor, pursuit_id: ids.pursuit }, revision: { ...revision, id: ids.successor, revision_number: 2, predecessor: ids.estimateRevision, calculation_snapshot: id(45), basis_description: payload.basis_description }, calculation: { ...structuredClone(snapshot), id: id(45), subject_id: ids.successor, inputs: { ...structuredClone(snapshot.inputs), basis_description: payload.basis_description } }, history_id: id(46) };
    if (proposal.preparation.kind === 'estimate-draft.v1') proposal.preparation.proposed_fields.quantity_selections[0].quantity.source_digest = digest(line);
  }
  const manifest = proposal.source_manifest, prep = proposal.preparation;
  for (const row of manifest.records) {
    if (row.id === base.revision.id) row.digest = digest(base.revision);
    if (base.kind === 'estimate' && row.id === base.snapshot.id) row.digest = digest(base.snapshot);
    if (base.kind === 'estimate' && row.id === ids.line) row.digest = digest(base.lines[0]);
  }
  manifest.preparation_heads[0].digest = digest(base.revision);
  for (const row of prep.record_dependencies) { const match = manifest.records.find(item => item.id === row.id); if (match) row.digest = match.digest; }
  prep.draft_digest = digest(Object.fromEntries(Object.entries(prep).filter(([key]) => key !== 'draft_digest')));
  proposal.preparation_digest = digest(prep); proposal.prepared_manifest_digest = digest(manifest);
  original.run.result!.preparation_digest = proposal.preparation_digest; original.run.result_digest = digest(original.run.result);
  const subject: CompanyDraftSaveSubject = { proposal_id: proposal.id, proposal_version: 1, proposal_digest: proposal.content_digest, action, mapping_version: '1', payload, payload_digest: digest(payload), expires_at: proposal.expires_at, eligible: true, reason: null, application: null, saved: null };
  function response(operationId: string, replayed = false): CompanyDraftSaveResponse {
    const core: CompanyDraftSaveResponse['application'] = { id: id(47), schema: 'cipher.ricky.company.draft-save.v1', company, scope_type: 'Company', project: null, user: actor.user, person: actor.person, proposal_id: proposal.id, proposal_version: 1, proposal_digest: proposal.content_digest, run_id: proposal.run_id, step_id: proposal.step_id, invocation_id: proposal.invocation_id, preparation_digest: proposal.preparation_digest, manifest_digest: proposal.prepared_manifest_digest, payload_digest: subject.payload_digest, mapping_version: '1', action, classification: 'unverified-author-suggestion', command: scope ? 'ricky.company.proposal.save-scope.v1' : 'ricky.company.proposal.save-estimate.v1', canonical_command: scope ? 'commercial.proposal.revise' : 'estimate.calculate.v1', target_doctype: scope ? 'Cipher Proposal' : 'Cipher Estimate', target_id: scope ? ids.commercial : ids.estimate, base_revision_id: base.revision.id, saved_doctype: scope ? 'Cipher Proposal Revision' : 'Cipher Estimate Revision', saved_revision_id: canonical.revision.id, saved_revision_digest: digest(canonical.revision), operation_id: operationId, receipt_id: digest({ person: actor.person, operation_id: operationId }), created_at: stamp, core_digest: '' };
    core.core_digest = digest(Object.fromEntries(Object.entries(core).filter(([key]) => key !== 'core_digest')));
    return { application: core, saved: structuredClone(canonical), operation: { id: operationId, status: 'succeeded', replayed } };
  }
  return { original, proposal, base, subject, response };
}

export async function draftFixture(page: Page, options: { action?: 'aec.scope.draft' | 'aec.estimate.draft'; lost?: boolean; wrongReceipt?: boolean; expired?: boolean; denyWrite?: boolean; stale?: boolean } = {}) {
  const data = draftData(options.action), inherited = await suggestionFixture(page, { pointer: true, action: options.action, twoCompanies: true });
  if (options.expired) { data.proposal.expires_at = new Date(Date.now() - 1).toISOString(); data.subject.expires_at = data.proposal.expires_at; data.subject.eligible = false; data.subject.reason = { code: 'expired', message: 'The original review window has expired.' }; }
  inherited.mutateRun(data.original.run); inherited.mutateProposal(data.proposal);
  const writes: Record<string, unknown>[] = []; let receipt: CompanyDraftSaveResponse | undefined; let denied = false;
  const send = (route: Route, value: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data: value } }) });
  const refuse = (route: Route, status = 403) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: status === 412 ? 'stale_draft_save' : 'capability_denied', message: status === 412 ? 'The working revision changed.' : 'Current source access denied.' } } }) });
  await page.route('**/api/method/**', async route => {
    const request = route.request(), url = new URL(request.url()), full = url.pathname.split('/').at(-1)!;
    if (full === 'cipher_aec.api.v1.session') return send(route, { authenticated: true, user: actor.user, person: { id: actor.person, display_name: 'Alex Morgan' }, companies: [{ id: company, name: 'Company A' }, { id: 'COMPANY-B', name: 'Company B' }], company_scopes: [{ company, capabilities: ['company.read', 'commercial.read', 'estimate.read', 'document.read', 'ricky.run', ...(options.denyWrite ? [] : ['commercial.write', 'estimate.write'])] }, { company: 'COMPANY-B', capabilities: ['company.read'] }], capabilities: [], csrf_token: 'test-csrf', site_mode: 'synthetic' });
    if (full.startsWith('cipher_aec.ricky.company_draft_save_api.')) {
      if (request.method() === 'GET') return denied ? refuse(route) : send(route, receipt ? { ...data.subject, eligible: false, reason: { code: 'draft_already_saved', message: 'This suggestion already has a saved canonical draft.' }, application: receipt.application, saved: receipt.saved } : data.subject);
      expect(full).toBe('cipher_aec.ricky.company_draft_save_api.save_draft');
      const body = request.postDataJSON(); writes.push(body);
      expect(Object.keys(body).sort()).toEqual(['company','proposal_id','expected_version','expected_content_digest','mapping_version','expected_payload_digest','operation_id'].sort());
      expect(request.headers()['idempotency-key']).toBe(body.operation_id);
      if (denied) return refuse(route);
      if (options.stale && !receipt) return refuse(route, 412);
      const replay = Boolean(receipt); receipt ||= data.response(body.operation_id);
      expect(body.operation_id).toBe(receipt.operation.id);
      if (options.lost && writes.length === 1) return route.abort('failed');
      return send(route, options.wrongReceipt && writes.length === 1 ? { ...receipt, application: { ...receipt.application, target_id: id(99) } } : { ...receipt, operation: { ...receipt.operation, replayed: replay } });
    }
    if (full === 'cipher_aec.commercial.api.proposal_revision') return denied ? refuse(route) : send(route, data.base.revision);
    if (full === 'cipher_aec.estimating.company_api.get_record' && data.base.kind === 'estimate') {
      if (denied) return refuse(route);
      const kind = url.searchParams.get('kind');
      if (kind === 'revision') return send(route, data.base.revision);
      if (kind === 'snapshot') return send(route, data.base.snapshot);
      if (kind === 'line') return send(route, data.base.lines[0]);
      if (kind === 'conversion') return send(route, data.base.conversions.find(row => row.id === url.searchParams.get('record_id')));
    }
    return route.fallback();
  });
  return { ...data, writes, effects: () => receipt ? 1 : 0, deny: (value: boolean) => { denied = value; inherited.setDenied(value); } };
}
