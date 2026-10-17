import { test, expect } from '@playwright/test';
import { engineering, engineeringDigest, engineeringShape, validateAuthoredReply, validateEngineeringPage, validateEngineeringRecord } from '../src/api/engineering';
import { rfiFixture, people, hash, scope, artifact, noEffects } from './engineering-fixture';
const actor = { user: people[0].user, personId: people[0].person };
test('a raw drawing RFI has no fabricated text citation and canonical digest matches Python encoding', async () => {
  const fixture = rfiFixture();
  expect(engineeringShape('EgCreateRfiRequest', fixture.input)).toBe(true);
  expect(engineeringShape('EgCreateRfiResponse', fixture.response)).toBe(true);
  expect(await engineeringDigest(fixture.response.revision)).toBe(hash(fixture.response.revision));
  expect(validateAuthoredReply('create_rfi', fixture.input as never, fixture.response as never, actor)).toEqual(fixture.response);
});
for (const field of ['scope', 'actor', 'definition', 'source', 'parent', 'operation', 'extra', 'revision'] as const) test(`authored RFI receipt rejects ${field} mismatch`, () => {
  const fixture = rfiFixture(), value: any = structuredClone(fixture.response);
  if (field === 'scope') value.rfi.project = 'FOREIGN';
  if (field === 'actor') value.revision.author_person = 'FOREIGN';
  if (field === 'definition') value.revision.definition.subject = 'Wrong subject';
  if (field === 'source') value.revision.drawing_references[0].source_sha256 = '0'.repeat(64);
  if (field === 'parent') value.revision.parent_id = crypto.randomUUID();
  if (field === 'operation') value.operation.id = crypto.randomUUID();
  if (field === 'extra') value.revision.native_write = true;
  if (field === 'revision') value.revision.revision_number = 7;
  expect(() => validateAuthoredReply('create_rfi', fixture.input as never, value, actor)).toThrow();
});
test('record digest, explicit kind and exact scope are checked before exposing any list rows', async () => {
  const fixture = rfiFixture(), record: any = { record: fixture.response.revision, record_digest: hash(fixture.response.revision) };
  await expect(validateEngineeringRecord(record, scope, 'rfi_revision', record.record.id)).resolves.toBe(record);
  await expect(validateEngineeringRecord({ ...record, record_digest: '0'.repeat(64) }, scope, 'rfi_revision')).rejects.toThrow();
  await expect(validateEngineeringRecord(record, scope, 'response')).rejects.toThrow();
  await expect(validateEngineeringRecord(record, { ...scope, project: 'FOREIGN' }, 'rfi_revision')).rejects.toThrow();
  const page = { items: [record], next_cursor: null, total: null, count_mode: 'none', limit: 25 } as any;
  await expect(validateEngineeringPage(page, { ...scope, kind: 'rfi_revision', parent_id: fixture.response.rfi.id })).resolves.toBe(page);
  await expect(validateEngineeringPage({ ...page, items: [record, record] }, { ...scope, kind: 'rfi_revision' })).rejects.toThrow();
  await expect(validateEngineeringPage({ ...page, next_cursor: 'old' }, { ...scope, kind: 'rfi_revision', cursor: 'old' })).rejects.toThrow();
});
test('successor confirmation uses captured original basis and refuses a silently rebased revision', () => {
  const fixture = rfiFixture(), original = fixture.response.rfi;
  const input = { ...fixture.input, rfi_id: original.id, expected_version: hash(original) };
  const response = structuredClone(fixture.response); response.revision.id = crypto.randomUUID(); response.revision.predecessor = original.current_revision as never; response.revision.revision_number = 2; response.rfi.current_revision = response.revision.id; response.rfi.revision_number = 2;
  const basis = { header: original as never, header_digest: hash(original) };
  expect(validateAuthoredReply('revise_rfi', input as never, response as never, actor, basis)).toBe(response);
  response.revision.predecessor = crypto.randomUUID() as never;
  expect(() => validateAuthoredReply('revise_rfi', input as never, response as never, actor, basis)).toThrow();
});

for (const wrong of ['none', 'package', 'recipient'] as const) test(`transmittal approval request binds the captured exact package and people: ${wrong}`, async () => {
  const operation_id = crypto.randomUUID();
  const record = { id: crypto.randomUUID(), ...scope, scope_type: 'Project', author_person: actor.personId, author_user: actor.user, created_at: '2026-10-17T05:00:00Z', status: 'awaiting_independent_authorization', subject: { kind: 'official_response', id: crypto.randomUUID() }, subject_digest: 'a'.repeat(64), recipients: [{ user: people[1].user, person: people[1].person }], purpose: 'Coordinate exact technical response', required_response: '', channel: 'internal', source_citations: [], artifacts: [artifact], drawing_references: [], package_digest: 'b'.repeat(64), no_effects: noEffects };
  const effect = { schema: 'cipher.engineering.authorization.v1', action: 'engineering.distribute.v1', subject_kind: 'transmittal', subject_id: record.id, subject_digest: hash(record), package_digest: wrong === 'package' ? 'c'.repeat(64) : record.package_digest, recipients: wrong === 'recipient' ? [{ user: people[1].user, person: 'WRONG-PERSON' }] : record.recipients, channel: 'internal' };
  const manifest = { subject: { doctype: 'Cipher Engineering Transmittal', name: record.id, label: record.purpose }, sources: [{ source_citations: [], artifacts: [artifact], drawing_references: [] }], effect, summary: { schema: 'cipher.engineering.review.v1', definition: null, purpose: record.purpose, no_effects: noEffects, professional_seal: false, external_delivery: false } };
  const packet = { id: crypto.randomUUID(), ...scope, action: 'engineering.distribute.v1', subject: { id: record.id, type: 'Cipher Engineering Transmittal', label: record.purpose }, requester: { id: actor.personId, display_name: 'Alex Author' }, created_at: '2026-10-17T05:00:00Z', expires_at: '2026-10-18T05:00:00Z', manifest_hash: hash(manifest), source_version: hash(record), policy: { id: 'fixture', label: 'Synthetic', synthetic: true }, state: 'Pending', decisions: [], actions: { can_decide: false, can_execute: false, can_withdraw: true, disabled_reason: null }, review_manifest: manifest, schema: 'cipher.engineering.approval.v1' };
  const previous = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', data: { packet, operation: { id: operation_id, status: 'succeeded', replayed: false } } } }), { status: 200 });
  try {
    const send = engineering.send({ kind: 'request_approval', operation_id, basis: { subject: { record: record as never, record_digest: hash(record) } }, payload: { ...scope, action: 'engineering.distribute.v1', subject_id: record.id, expected_version: hash(record) } }, actor);
    if (wrong === 'none') await expect(send).resolves.toMatchObject({ packet: { id: packet.id } }); else await expect(send).rejects.toThrow();
  } finally { globalThis.fetch = previous; }
});
