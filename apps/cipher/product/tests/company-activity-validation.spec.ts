import { expect, test } from '@playwright/test';
import { activityDestination, activityLabel, validateCompanyHistory } from '../src/api/company-history';
import { event, historyPage, company } from './company-activity-fixture';

test('published HistoryList keeps count_mode none and null total without invented Company fields', () => {
  const original = historyPage([event(1)]); expect(validateCompanyHistory(original)).toEqual(original);
  expect(Object.keys(original.items[0]).sort()).toEqual(['actor','at','details','event','id','subject_id','subject_type']);
  for (const mutate of [(v: typeof original) => { v.total = 1; }, (v: typeof original) => { v.count_mode = 'exact'; },
      (v: typeof original) => { v.limit = 200; }, (v: typeof original) => { v.items = Array.from({ length: 26 }, (_, n) => event(n)); }]) {
    const invalid = structuredClone(original); mutate(invalid); expect(() => validateCompanyHistory(invalid)).toThrow();
  }
});
test('malformed, duplicated, extra-scope and non-timestamp event rows fail closed', () => {
  for (const item of [{ ...event(1), company: 'OTHER' }, { ...event(1), actor: null }, { ...event(1), details: [] },
      { ...event(1), at: '2026-10-17' }, { ...event(1), subject_id: null }]) expect(() => validateCompanyHistory(historyPage([item as never]))).toThrow();
  expect(() => validateCompanyHistory(historyPage([event(1), event(1)]))).toThrow();
  expect(() => validateCompanyHistory(historyPage([event(1)], 'same-cursor'), 'same-cursor')).toThrow();
});
test('only implemented scoped record routes can open; raw revision/native/Run references stay details', () => {
  expect(activityDestination(event(2), company)?.path).toBe(`/company/estimates/${event(2).subject_id}?company=${company}`);
  for (const subject_type of ['Cipher Proposal Revision','Cipher Ricky Run','Cipher Ricky Draft Save','Sales Order','Quotation']) expect(activityDestination(event(1, { subject_type }), company)).toBeUndefined();
  expect(activityDestination(event(1, { subject_type: 'Cipher Document', subject_id: '../other' }), company)).toBeUndefined();
  expect(activityLabel('ricky.company.proposal.draft-saved')).toBe('Suggestion saved as draft');
  expect(activityLabel('future.record.created')).toBe('Future record created');
});
