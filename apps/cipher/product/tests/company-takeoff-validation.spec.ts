import { expect, test } from '@playwright/test';
import { matchesCreatedMeasurement, takeoffShape, validateSourceDetail, validateSourcePage, validateTakeoffPage, validateTakeoffRecord } from '../src/api/company-takeoff-validation';
import { company, document, measurement, pageOf, personId, preview, record, revision, set, setId, user } from './company-takeoff-fixture';
test('published Company manual/source fixtures match closed contracts and PDF preview is canonical text/plain', () => {
  expect(takeoffShape('CompanyTakeoffMeasurementRecord', measurement)).toBe(true);
  expect(validateSourceDetail({ document, revisions: [revision] }, company, document.id)).toBeTruthy();
  expect(validateSourcePage(preview, company, document.id, revision, 1)).toEqual(preview);
});
test('selected raw PDF metadata rejects invalid SHA, page count and byte bounds before retrieval', () => {
  for (const edit of [{ sha256: 'malformed' }, { page_count: 0 }, { page_count: 201 }, { byte_length: 0 }, { byte_length: 10485761 }, { revision_number: 0 }]) {
    expect.soft(() => validateSourceDetail({ document: { ...document, ...edit }, revisions: [{ ...revision, ...edit }] }, company, document.id)).toThrow();
  }
});
test('manual success binds exact quantity as well as source, definition, Company, set and actor', () => {
  const input = { company, operation_id: '71000000-0000-4000-8000-000000000004', takeoff_set: setId, source: { revision_id: revision.id, source_sha256: revision.sha256, page: 1 }, definition: measurement.definition, conversion_ids: [] };
  const response = { measurement, history_id: 'TEST-HISTORY', operation: { id: input.operation_id, status: 'succeeded' as const, replayed: false } };
  expect(matchesCreatedMeasurement(response, input, { user, personId }, document.id)).toBe(true);
  const changed = structuredClone(response); changed.measurement.result.quantity.amount = '999.00';
  expect(matchesCreatedMeasurement(changed, input, { user, personId }, document.id)).toBe(false);
});
test('saved/manual response refuses foreign manifest scope, mismatched unit precision and geometric facts', () => {
  const input = { company, takeoff_set: setId, source: { revision_id: revision.id, source_sha256: revision.sha256, page: 1 }, definition: measurement.definition, conversion_ids: [] };
  const response = { measurement, history_id: 'TEST-HISTORY', operation: { id: '71000000-0000-4000-8000-000000000004', status: 'succeeded' as const, replayed: false } };
  const changed = structuredClone(record()); changed.record.unit_manifest.scope.company = 'FOREIGN'; expect.soft(() => validateTakeoffRecord(changed, { company, kind: 'measurement', takeoff_set: setId })).toThrow();
  for (const edit of [(v: any) => { v.measurement.unit_manifest.records[0].fields.precision = 3; }, (v: any) => { v.measurement.calibration_digest = 'e'.repeat(64); }]) {
    const changed = structuredClone(response); edit(changed); expect.soft(matchesCreatedMeasurement(changed, input, { user, personId }, document.id)).toBe(false);
  }
});
test('pages reject exact totals, wrong scope and cursor loops before exposing rows', () => {
  const page = pageOf([{ record: set, record_digest: 'd'.repeat(64) }]);
  expect(validateTakeoffPage(page as never, { company, kind: 'set' })).toEqual(page);
  for (const edit of [(v: any) => { v.total = 1; }, (v: any) => { v.count_mode = 'exact'; }, (v: any) => { v.items[0].record.company = 'FOREIGN'; }, (v: any) => { v.items[0].record.project = 'FAKE'; }]) {
    const changed: any = structuredClone(page); edit(changed); expect(() => validateTakeoffPage(changed, { company, kind: 'set' })).toThrow();
  }
  expect(() => validateTakeoffPage(pageOf([], 'old') as never, { company, kind: 'set', cursor: 'old' })).toThrow();
  expect(() => validateTakeoffRecord(record(), { company, kind: 'measurement', takeoff_set: 'other' })).toThrow();
});
