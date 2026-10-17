import { expect, test } from '@playwright/test';
import { exactDraftDecimal, matchesDraftSaveResponse, matchesDraftSaveSubject, publishedDraftSaveShape } from '../src/api/company-draft-saves-validation';
import { matchesSavedSuggestion } from '../src/api/company-ricky-proposals-validation';
import { actor, draftData } from './company-draft-save-fixture';
import { citation, digest, id, ids } from './company-ricky-proposals-fixture';

for (const action of ['aec.scope.draft', 'aec.estimate.draft'] as const) {
  test(`${action} preview binds full canonical original and outer receipt`, async () => {
    const value = draftData(action);
    expect(await matchesSavedSuggestion(value.proposal, value.original.run, [citation], ids.snapshot)).toBe(true);
    expect(publishedDraftSaveShape('CompanyDraftSaveSubject', value.subject)).toBe(true);
    expect(await matchesDraftSaveSubject(value.subject, value.proposal, value.base, actor.user, actor.person)).toBe(true);
    const response = value.response(id(80));
    expect(publishedDraftSaveShape('CompanyDraftSaveResponse', response)).toBe(true);
    const request = { company: value.proposal.company, proposal_id: value.proposal.id, expected_version: 1 as const, expected_content_digest: value.proposal.content_digest, mapping_version: '1' as const, expected_payload_digest: value.subject.payload_digest, operation_id: id(80) };
    const binding = { proposal: value.proposal, subject: value.subject, ...actor };
    expect(await matchesDraftSaveResponse(response, request, binding)).toBe(true);
    expect(await matchesDraftSaveResponse(value.response(id(81)), request, binding)).toBe(false);
    expect(await matchesDraftSaveResponse(response, request, { ...binding, user: 'same.person.alias@example.invalid' })).toBe(false);
    for (const field of ['target_id','saved_revision_id','payload_digest','manifest_digest','receipt_id','invocation_id'] as const) {
      const altered = structuredClone(response); altered.application[field] = field.endsWith('_id') ? id(99) : 'f'.repeat(64);
      altered.application.core_digest = digest(Object.fromEntries(Object.entries(altered.application).filter(([key]) => key !== 'core_digest')));
      expect(await matchesDraftSaveResponse(altered, request, binding), field).toBe(false);
    }
  });

  test(`${action} preview rejects changed original, expiry, payload and extra fields`, async () => {
    const value = draftData(action);
    const changedBase = structuredClone(value.base); changedBase.revision.company = 'FOREIGN';
    expect(await matchesDraftSaveSubject(value.subject, value.proposal, changedBase, actor.user, actor.person)).toBe(false);
    expect(await matchesDraftSaveSubject({ ...value.subject, expires_at: '2099-01-01T00:00:00Z' }, value.proposal, value.base, actor.user, actor.person)).toBe(false);
    expect(await matchesDraftSaveSubject({ ...value.subject, eligible: false }, value.proposal, value.base, actor.user, actor.person)).toBe(false);
    expect(publishedDraftSaveShape('CompanyDraftSaveSubject', { ...value.subject, trusted: true })).toBe(false);
    const bad = structuredClone(value.subject);
    if ('composition' in bad.payload) bad.payload.composition.terms = 'Replaced payment terms';
    else bad.payload.lines[0].quantity.amount = '1000';
    bad.payload_digest = digest(bad.payload);
    expect(await matchesDraftSaveSubject(bad, value.proposal, value.base, actor.user, actor.person)).toBe(false);
  });

  test(`${action} historical saved link remains readable after expiry, with no new save eligibility`, async () => {
    const value = draftData(action), response = value.response(id(80));
    value.proposal.expires_at = '2020-01-01T00:00:00Z';
    const subject = { ...value.subject, expires_at: value.proposal.expires_at, eligible: false, reason: { code: 'draft_already_saved', message: 'Already saved.' }, application: response.application, saved: response.saved };
    expect(await matchesDraftSaveSubject(subject, value.proposal, value.base, actor.user, actor.person)).toBe(true);
    expect(await matchesDraftSaveSubject({ ...subject, saved: null }, value.proposal, value.base, actor.user, actor.person)).toBe(false);
  });
}

test('exact estimate quantities retain all twelve places and refuse rounding', () => {
  expect(exactDraftDecimal('1000000000001', '1000000000000', 12)).toBe('1.000000000001');
  expect(exactDraftDecimal('1', '3', 12)).toBeUndefined();
  expect(exactDraftDecimal('1', '8', 2)).toBeUndefined();
  expect(exactDraftDecimal('1', '8', 3)).toBe('0.125');
  expect(exactDraftDecimal('0', '2', 12)).toBe('0');
  expect(exactDraftDecimal('9007199254740993', '1', 0)).toBe('9007199254740993');
});

test('Company estimate contracts refuse Project envelopes and full citation records as command inputs', () => {
  const value = draftData('aec.estimate.draft'), response = value.response(id(80));
  expect(publishedDraftSaveShape('CompanyDraftSaveResponse', { ...response, saved: { ...response.saved, revision: { ...response.saved.revision, project: 'PROJECT-1', scope_type: 'Project' } } })).toBe(false);
  if ('basis_citations' in value.subject.payload) value.subject.payload.basis_citations = [citation];
  expect(publishedDraftSaveShape('CompanyDraftSaveSubject', value.subject)).toBe(false);
});

test('saved snapshot pins conversion definitions even without separate Stage B manifest rows', async () => {
  const value = draftData('aec.estimate.draft');
  expect(value.proposal.source_manifest.records.filter(row => row.kind === 'conversion')).toEqual([]);
  expect(await matchesDraftSaveSubject(value.subject, value.proposal, value.base, actor.user, actor.person)).toBe(true);
  if (value.base.kind !== 'estimate') throw new Error('Fixture action');
  value.base.conversions[0].definition.numerator = '999';
  expect(await matchesDraftSaveSubject(value.subject, value.proposal, value.base, actor.user, actor.person)).toBe(false);
});
