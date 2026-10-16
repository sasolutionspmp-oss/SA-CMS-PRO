import { expect, test } from '@playwright/test';
import type { CompanyRickyProposalResponse as Proposal, CompanyRickyProposalRunResponse as Run } from '../src/api/company-ricky-proposals.generated';
import { matchesSavedSuggestion, matchesSuggestionAdmission, matchesSuggestionRun, matchesSuggestionStop, publishedSuggestionShape, suggestionPointerKey, validSuggestionRunDigests, validSuggestionSelection } from '../src/api/company-ricky-proposals-validation';
import { citation, digest, id, ids, saved, selection } from './company-ricky-proposals-fixture';
import { company } from './fixture';

const rehash = (value: ReturnType<typeof saved>) => {
  const output = value.proposal.preparation; output.draft_digest = digest(Object.fromEntries(Object.entries(output).filter(([key]) => key !== 'draft_digest')));
  value.proposal.preparation_digest = digest(output); value.proposal.prepared_manifest_digest = digest(value.proposal.source_manifest);
  value.run.result!.preparation_digest = value.proposal.preparation_digest; value.run.result_digest = digest(value.run.result);
};

for (const action of ['aec.scope.draft', 'aec.estimate.draft'] as const) test(`closed generated ${action} contract retains all common metadata and original linkage`, async () => {
  const value = saved(action);
  // Compile-time common properties must survive action-specific oneOf generation.
  const common: Pick<Proposal, 'id' | 'company' | 'source_manifest' | 'expires_at' | 'content_digest'> = value.proposal;
  expect(common.company).toBe(company); expect(publishedSuggestionShape('CompanyRickyProposalResponse', value.proposal)).toBe(true);
  expect(matchesSuggestionRun(value.run, company, value.run.id)).toBe(true); expect(await validSuggestionRunDigests(value.run)).toBe(true);
  expect(await matchesSavedSuggestion(value.proposal, value.run, [citation], ids.snapshot)).toBe(true);
  for (const key of ['id','company','source_manifest','expires_at','content_digest']) {
    const bad = structuredClone(value.proposal) as unknown as Record<string, unknown>; delete bad[key];
    expect(publishedSuggestionShape('CompanyRickyProposalResponse', bad)).toBe(false);
  }
});

test('proposal selection rejects missing evidence, duplicate sources, unsupported fields and quantity IDs', () => {
  const original = selection(); expect(validSuggestionSelection(original)).toBe(true);
  expect(validSuggestionSelection({ ...original, sources: [] })).toBe(false);
  expect(validSuggestionSelection({ ...original, sources: [...original.sources, ...original.sources] })).toBe(false);
  expect(validSuggestionSelection({ ...original, arguments: { ...original.arguments, unsupported: true } } as never)).toBe(false);
  const estimate = selection('aec.estimate.draft');
  expect(validSuggestionSelection({ ...estimate, arguments: { ...estimate.arguments, selections: [{ line_record_id: ids.line, source_kind: 'measurement', source_id: id(99), target_unit_id: ids.unit }] } } as never)).toBe(false);
});

test('only the immutable queued Start and exact matching operation shape can admit a request', () => {
  const value = saved(); const operation = { id: id(90), status: 'succeeded' as const, replayed: false };
  expect(matchesSuggestionAdmission({ ...value.run, operation }, company, value.run.selection, value.run.selection_digest)).toBe(false);
  const admitted = { ...value.run, status: 'queued' as const, result: null, result_digest: null, completed_at: null, operation };
  expect(matchesSuggestionAdmission(admitted, company, value.run.selection, value.run.selection_digest)).toBe(true);
  expect(matchesSuggestionAdmission({ ...admitted, selection_digest: 'f'.repeat(64) }, company, value.run.selection, value.run.selection_digest)).toBe(false);
  expect(matchesSuggestionAdmission({ ...admitted, selection: selection('aec.estimate.draft') }, company, value.run.selection, value.run.selection_digest)).toBe(false);
});

test('source-free Stop stays narrow and cannot supply a full source-bearing observation', () => {
  const value = saved(); const stop = { id: value.run.id, company, project: null, scope_type: 'Company' as const, request_kind: 'deterministic-proposal-v1' as const, status: 'waiting-for-review' as const, cancel_requested: false, operation: { id:id(90),status:'succeeded' as const,replayed:false } };
  expect(matchesSuggestionStop(stop, company, value.run.id)).toBe(true);
  expect(matchesSuggestionRun(stop as unknown as Run, company)).toBe(false);
  expect(matchesSuggestionStop({ ...stop, result: value.run.result } as never, company, value.run.id)).toBe(false);
});

for (const field of ['sections','dependencies','references','document'] as const) test(`rehashed scope wrapper cannot replace original ${field}`, async () => {
  const value = saved(); const output = value.proposal.preparation;
  if (output.kind !== 'scope-draft.v1') throw new Error('scope fixture');
  if (field === 'sections') output.proposed_fields.sections[0].text = 'Caller replaced the author-selected scope.';
  if (field === 'dependencies') output.record_dependencies = [];
  if (field === 'references') output.verified_source_references = [];
  if (field === 'document') output.verified_source_references[0].document_id = 'DOC-foreign';
  rehash(value); expect(await matchesSavedSuggestion(value.proposal, value.run, [citation])).toBe(false);
});

test('estimate preparation retains exact source IDs, target units and authored notes', async () => {
  for (const field of ['source_id','target_unit_id','notes']) {
    const value = saved('aec.estimate.draft'); const output = value.proposal.preparation;
    if (output.kind !== 'estimate-draft.v1') throw new Error('estimate fixture');
    if (field === 'notes') output.proposed_fields.notes = 'Substituted notes';
    else output.proposed_fields.quantity_selections[0].quantity[field as 'source_id' | 'target_unit_id'] = id(99);
    rehash(value); expect(await matchesSavedSuggestion(value.proposal, value.run, [citation], ids.snapshot)).toBe(false);
  }
});

test('full original citation identity, not only citation hash fields, governs review', async () => {
  const value = saved();
  expect(await matchesSavedSuggestion(value.proposal, value.run, [{ ...citation, document_id:'DOC-foreign' }])).toBe(false);
  expect(await matchesSavedSuggestion(value.proposal, value.run, [{ ...citation, company:'FOREIGN' }])).toBe(false);
  expect(await matchesSavedSuggestion(value.proposal, value.run, [])).toBe(false);
});

test('terminal status/result pairing and exact result digest fail closed', async () => {
  const value = saved();
  expect(matchesSuggestionRun({ ...value.run, status:'queued' }, company)).toBe(false);
  expect(matchesSuggestionRun({ ...value.run, company:'FOREIGN' }, company)).toBe(false);
  expect(matchesSuggestionRun({ ...value.run, completed_at:'not-a-date' }, company)).toBe(false);
  expect(await validSuggestionRunDigests({ ...value.run, result_digest:'f'.repeat(64) })).toBe(false);
});

test('historical expiry does not erase valid original review or invent head eligibility', async () => {
  const value = saved(); expect(Date.parse(value.proposal.expires_at)).toBeLessThan(Date.now());
  expect(await matchesSavedSuggestion(value.proposal, value.run, [citation])).toBe(true);
  const bad = structuredClone(value); bad.proposal.source_manifest.preparation_heads[0].revision_id = ids.successor; rehash(bad);
  expect(await matchesSavedSuggestion(bad.proposal, bad.run, [citation])).toBe(false);
});

test('same-Person alias and Company pointers cannot reuse each other or old read pointers', () => {
  const original = suggestionPointerKey('original','same-person',company);
  expect(original).not.toBe(suggestionPointerKey('alias','same-person',company));
  expect(original).not.toBe(suggestionPointerKey('original','same-person','OTHER'));
  expect(original).not.toContain('cipher.company.ricky.v1');
});
