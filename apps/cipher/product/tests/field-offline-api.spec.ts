import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { actorScopePerson, fieldOffline, offlineShape, validateOfflineEnvelope, validateOfflineRead, validateOfflineReceipt } from '../src/api/field-offline';
import { dailyDefinition, expand, hash, people, scope, seedDaily, source } from './field-fixture';
const actor = { user: people[0].user, personId: people[0].person }, context = { ...scope, actor };
function fixture() {
  const seed = structuredClone(seedDaily()), captureId = randomUUID(), envelope: any = { schema: 'cipher.field.offline.v1', device_id: randomUUID(), capture_id: captureId, ...scope, actor_person: actor.personId, actor_user: actor.user, captured_at: '2026-10-17T14:00:00-04:00', command: { action: 'create', family: 'daily', definition: structuredClone(dailyDefinition), photos: [], quantities: seed.quantities.map(row => ({ ...row.definition, sources: [source] })) } };
  const receipt: any = { family: 'daily', ...seed, history_id: randomUUID(), operation: { id: captureId, status: 'succeeded', replayed: true } };
  const capture: any = { capture_id: captureId, device_id: envelope.device_id, ...scope, actor_person: actor.personId, actor_user: actor.user, envelope_digest: hash(envelope), status: 'staged', payload_retained: true, replaces_capture_id: null, replacement_capture_id: null };
  return { envelope, receipt, capture, capture_version: 'c'.repeat(64) };
}
function reviseFixture() {
  const f = fixture(), old = structuredClone(f.receipt.header); old.status = 'accepted'; old.last_decision = randomUUID(); old.accepted_revision = old.current_revision;
  const priorQuantity = f.receipt.quantities[0].id;
  f.receipt.revision.id = randomUUID(); f.receipt.revision.revision_number = 2; f.receipt.revision.predecessor = old.current_revision; f.receipt.revision.prior_decision = old.last_decision; f.receipt.revision.amendment_of = old.accepted_revision; f.receipt.revision.amendment_reason = 'Correction.';
  f.receipt.quantities[0].id = randomUUID(); f.receipt.quantities[0].revision_number = 2; f.receipt.quantities[0].source_revision = f.receipt.revision.id; f.receipt.quantities[0].supersedes_event_id = priorQuantity; f.receipt.quantities[0].definition.supersedes_event_id = priorQuantity; f.receipt.revision.quantity_ids = [f.receipt.quantities[0].id];
  f.receipt.header = { ...old, current_revision: f.receipt.revision.id, revision_number: 2, last_decision: null, status: 'draft' };
  Object.assign(f.envelope.command, { action: 'revise', record_id: old.id, expected_version: hash(old), base_revision_id: old.current_revision, base_revision_digest: 'b'.repeat(64), amendment_reason: 'Correction.' }); f.envelope.command.quantities[0].supersedes_event_id = priorQuantity;
  f.capture.envelope_digest = hash(f.envelope); return f;
}
test('exact valid documentary envelope is unchanged and scope partition is canonical Person based', async () => {
  const { envelope, receipt } = fixture(), original = structuredClone(envelope);
  expect(offlineShape('FoEnvelope', envelope)).toBe(true);
  expect(validateOfflineEnvelope(envelope, context)).toBe(envelope);
  expect(envelope).toEqual(original);
  await expect(validateOfflineReceipt(envelope, receipt, context)).resolves.toBe(receipt);
  expect(actorScopePerson(context)).toBe(actorScopePerson({ ...context, actor: { ...actor, user: people[3].user } }));
});
for (const [label, change] of [
  ['extra auth', (e: any) => { e.auth_token = 'secret'; }],
  ['transition action', (e: any) => { e.command.action = 'accept'; }],
  ['capture UUID not v4', (e: any) => { e.capture_id = '00000000-0000-1000-8000-000000000001'; }],
  ['numeric quantity', (e: any) => { e.command.quantities[0].quantity = 12.000001; }],
  ['nonpositive decimal', (e: any) => { e.command.quantities[0].quantity = '0.000000'; }],
  ['invented rate', (e: any) => { e.command.quantities[0].rate = '50.00'; }],
  ['invalid local date', (e: any) => { e.command.definition.local_date = '2026-02-30'; }],
  ['year zero local date', (e: any) => { e.command.definition.local_date = '0000-01-01'; }],
  ['offset omitted', (e: any) => { e.captured_at = '2026-10-17T14:00:00'; }],
  ['normalized invalid date-time', (e: any) => { e.captured_at = '2026-02-30T14:00:00Z'; }],
  ['normalized 24 hour time', (e: any) => { e.captured_at = '2026-10-17T24:00:00Z'; }],
  ['empty superintendent', (e: any) => { e.command.definition.superintendent_user = '   '; }],
  ['binary reference', (e: any) => { e.command.photos = [{ local_blob: 'data:image/png;base64,abc' }]; }],
  ['sparse quantity list', (e: any) => { e.command.quantities = new Array(1); }],
  ['sparse array disguised with extra property', (e: any) => { e.command.photos = Object.assign(new Array(1), { extra: 'x' }); }],
  ['invalid Unicode', (e: any) => { e.command.definition.activities = ['bad\ud800']; }],
] as const) test(`closed envelope rejects ${label}`, () => { const { envelope } = fixture(); change(envelope); expect(offlineShape('FoEnvelope', envelope)).toBe(false); });
test('scope, Person, duplicate quantity attribution, byte/depth and cyclic inputs fail locally', () => {
  const { envelope } = fixture();
  expect(() => validateOfflineEnvelope(envelope, { ...context, project: 'OTHER' })).toThrow();
  expect(() => validateOfflineEnvelope(envelope, { ...context, actor: { ...actor, personId: 'OTHER' } })).toThrow();
  const duplicate = structuredClone(envelope); duplicate.command.quantities.push(structuredClone(duplicate.command.quantities[0])); expect(() => validateOfflineEnvelope(duplicate, context)).toThrow();
  const cyclic: any = {}; cyclic.self = cyclic; expect(offlineShape('FoEnvelope', cyclic)).toBe(false);
  const large = structuredClone(envelope); large.command.definition.activities = ['x'.repeat(262145)]; expect(offlineShape('FoEnvelope', large)).toBe(false);
});
test('command shape also rejects sparse/coercing non-JSON input before sealing', () => {
  const f = fixture(); f.envelope.command.photos = Object.assign(new Array(1), { extra: 'x' });
  expect(offlineShape('FoCommand', f.envelope.command)).toBe(false);
});
for (const [label, change] of [
  ['different capture UUID', (r: any) => { r.operation.id = randomUUID(); }],
  ['foreign project', (r: any) => { r.revision.project = 'OTHER'; }],
  ['different Person', (r: any) => { r.revision.author_person = 'OTHER'; }],
  ['quantity decimal changed', (r: any) => { r.quantities[0].definition.quantity = '12.000002'; }],
  ['source digest changed', (r: any) => { r.quantities[0].definition.sources[0].source_sha256 = 'a'.repeat(64); }],
  ['quantity author alias inconsistent', (r: any) => { r.quantities[0].author_user = people[3].user; }],
  ['header current revision changed', (r: any) => { r.header.current_revision = randomUUID(); }],
  ['financial effect', (r: any) => { r.revision.no_effects.financial_posting = true; }],
] as const) test(`original receipt rejects ${label}`, async () => { const { envelope, receipt } = fixture(); change(receipt); await expect(validateOfflineReceipt(envelope, receipt, context)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
test('same-Person alias replays original author without changing sealed attribution; fresh apply uses actual login', async () => {
  const { envelope, receipt } = fixture(), alias = { ...context, actor: { ...actor, user: people[3].user } };
  expect(validateOfflineEnvelope(envelope, alias)).toBe(envelope);
  await expect(validateOfflineReceipt(envelope, receipt, alias)).resolves.toBe(receipt);
  await expect(validateOfflineReceipt(envelope, receipt, alias, true)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  await expect(validateOfflineReceipt(envelope, receipt, { ...alias, receiptActor: actor })).resolves.toBe(receipt);
  await expect(validateOfflineReceipt(envelope, receipt, { ...alias, receiptActor: alias.actor })).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  const fresh = structuredClone(receipt); fresh.operation.replayed = false; fresh.header.author_user = alias.actor.user; fresh.revision.author_user = alias.actor.user; fresh.quantities.forEach((q: any) => { q.author_user = alias.actor.user; });
  await expect(validateOfflineReceipt(envelope, fresh, alias, true)).resolves.toBe(fresh);
  expect(envelope.actor_user).toBe(actor.user);
});
test('one receipt author login cannot identify a different superintendent Person', async () => {
  const f = fixture(), alias = { ...context, actor: { ...actor, user: people[3].user } };
  f.envelope.command.definition.superintendent_user = alias.actor.user; f.receipt.revision.definition.superintendent_user = alias.actor.user; f.receipt.revision.superintendent.user = alias.actor.user;
  f.receipt.revision.author_user = alias.actor.user; f.receipt.header.author_user = alias.actor.user; f.receipt.quantities.forEach((q: any) => { q.author_user = alias.actor.user; });
  f.receipt.revision.superintendent.person = 'OTHER';
  await expect(validateOfflineReceipt(f.envelope, f.receipt, alias)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('T&M create and acknowledgement-based revision retain documentary lines and exact header', async () => {
  const f = fixture(), definition = { local_date: '2026-10-17', title: 'Pump check', customer_name: 'Owner', location: 'Station', work_description: 'Observed work.', potential_change_reference: '', lines: [{ kind: 'labor', description: 'Pump check', quantity: '1.000001', unit: 'hours', sources: [source] }] };
  f.envelope.command = { action: 'create', family: 'ticket', definition, photos: [], quantities: [] };
  f.receipt.family = 'ticket'; f.receipt.quantities = []; delete f.receipt.revision.superintendent; delete f.receipt.revision.quantity_ids; f.receipt.revision.definition = { ...definition, lines: definition.lines.map(line => ({ ...line, sources: line.sources.map(expand) })) };
  expect(offlineShape('FoEnvelope', f.envelope)).toBe(true); await expect(validateOfflineReceipt(f.envelope, f.receipt, context)).resolves.toBe(f.receipt);
  const old = structuredClone(f.receipt.header); old.status = 'acknowledged'; old.last_decision = randomUUID(); old.accepted_revision = old.current_revision;
  f.receipt.revision.id = randomUUID(); Object.assign(f.receipt.revision, { revision_number: 2, predecessor: old.current_revision, prior_decision: old.last_decision, amendment_of: old.accepted_revision, amendment_reason: 'Correction.' });
  f.receipt.header = { ...old, status: 'draft', revision_number: 2, current_revision: f.receipt.revision.id, last_decision: null };
  Object.assign(f.envelope.command, { action: 'revise', record_id: old.id, expected_version: hash(old), base_revision_id: old.current_revision, base_revision_digest: 'b'.repeat(64), amendment_reason: 'Correction.' });
  expect(offlineShape('FoEnvelope', f.envelope)).toBe(true); await expect(validateOfflineReceipt(f.envelope, f.receipt, context)).resolves.toBe(f.receipt);
  f.receipt.revision.definition.lines[0].quantity = '1.000002'; await expect(validateOfflineReceipt(f.envelope, f.receipt, context)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('revised original receipt preserves exact predecessor, decision, accepted record and header digest', async () => {
  const f = reviseFixture(); expect(offlineShape('FoEnvelope', f.envelope)).toBe(true); await expect(validateOfflineReceipt(f.envelope, f.receipt, context)).resolves.toBe(f.receipt);
  for (const change of [(r: any) => { r.header.revision_number = 999; r.revision.revision_number = 999; r.quantities[0].revision_number = 999; }, (r: any) => { r.revision.prior_decision = randomUUID(); }, (r: any) => { r.header.number = 'OTHER'; }, (r: any) => { r.header.author_person = 'OTHER'; }]) {
    const bad = structuredClone(f.receipt); change(bad); await expect(validateOfflineReceipt(f.envelope, bad, context)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  }
});
test('fresh apply requires committed projection; recovery may retain original metadata status', async () => {
  const f = fixture(), value: any = { capture: f.capture, capture_version: f.capture_version, original_receipt: { ...f.receipt, operation: { ...f.receipt.operation, replayed: false } }, replayed: false };
  await expect(validateOfflineRead('apply', value, context, f.envelope.capture_id, f.envelope)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  value.replayed = true; value.original_receipt.operation.replayed = true;
  await expect(validateOfflineRead('apply', value, context, f.envelope.capture_id, f.envelope)).resolves.toBe(value);
});
test('historical receipt remains valid when projection still staged and later field head differs', async () => {
  const f = fixture(), value: any = { capture: f.capture, capture_version: f.capture_version, disposition: 'committed', conflict: null, original_receipt: f.receipt };
  await expect(validateOfflineRead('inspect', value, context, f.envelope.capture_id, f.envelope)).resolves.toBe(value);
  const later = structuredClone(f.receipt.header); later.current_revision = randomUUID(); expect(later.current_revision).not.toBe(f.receipt.header.current_revision);
  const bad = structuredClone(value); bad.disposition = 'ready'; await expect(validateOfflineRead('inspect', bad, context, f.envelope.capture_id, f.envelope)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('redacted get can bind original receipt only with retained envelope, while full get rejects substituted payload', async () => {
  const f = fixture(), value: any = { capture: { ...f.capture, status: 'committed', payload_retained: false }, capture_version: f.capture_version, envelope: null, original_receipt: f.receipt };
  await expect(validateOfflineRead('get', value, context, f.envelope.capture_id)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  await expect(validateOfflineRead('get', value, context, f.envelope.capture_id, f.envelope)).resolves.toBe(value);
  const full = { ...value, capture: { ...value.capture, payload_retained: true }, envelope: structuredClone(f.envelope) }; full.envelope.command.quantities[0].quantity = '12.000002';
  await expect(validateOfflineRead('get', full, context, f.envelope.capture_id, f.envelope)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('get and inspect cannot substitute a different capture envelope and original receipt', async () => {
  const f = fixture(), other = structuredClone(f.envelope); other.capture_id = randomUUID();
  const receipt = { ...f.receipt, operation: { ...f.receipt.operation, id: other.capture_id } }, capture = { ...f.capture, envelope_digest: hash(other) };
  await expect(validateOfflineRead('get', { capture, capture_version: f.capture_version, envelope: other, original_receipt: receipt }, context, f.envelope.capture_id)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  await expect(validateOfflineRead('inspect', { capture, capture_version: f.capture_version, disposition: 'committed', conflict: null, original_receipt: receipt }, context, f.envelope.capture_id, other)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('adapter exact eight routes, request keys, capture UUID reuse and immutable request snapshots', async () => {
  const f = fixture(), calls: { method: string; body: any; key?: string | null }[] = [], oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const u = new URL(String(url), 'http://fixture.test'), method = u.pathname.split('.').at(-1)!, body = init?.body ? JSON.parse(String(init.body)) : Object.fromEntries(u.searchParams);
    calls.push({ method, body, key: (init?.headers as Record<string, string>)?.['Idempotency-Key'] });
    let result: any;
    if (method === 'register_device' || method === 'revoke_device') result = { device: { device_id: f.envelope.device_id, ...scope, owner_person: actor.personId, registered_user: actor.user, label: 'Site tablet', status: method === 'register_device' ? 'active' : 'revoked' }, device_version: 'a'.repeat(64), operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
    else if (method === 'get_capture') result = { capture: f.capture, capture_version: f.capture_version, envelope: f.envelope, original_receipt: null };
    else if (method === 'inspect_capture') result = { capture: f.capture, capture_version: f.capture_version, disposition: 'ready', conflict: null, original_receipt: null };
    else if (method === 'apply_capture') result = { capture: { ...f.capture, status: 'committed' }, capture_version: f.capture_version, original_receipt: { ...f.receipt, operation: { ...f.receipt.operation, replayed: false } }, replayed: false };
    else if (method === 'resolve_capture') result = { capture: { ...f.capture, capture_id: body.replacement_envelope.capture_id, envelope_digest: hash(body.replacement_envelope), replaces_capture_id: f.envelope.capture_id }, capture_version: f.capture_version, operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
    else result = { capture: method === 'discard_capture' ? { ...f.capture, status: 'discarded', payload_retained: false } : f.capture, capture_version: f.capture_version, operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
    return new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', data: result } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await fieldOffline.registerDevice({ ...scope, device_id: f.envelope.device_id, operation_id: randomUUID(), label: 'Site tablet' }, context);
    await fieldOffline.revokeDevice({ ...scope, device_id: f.envelope.device_id, operation_id: randomUUID(), expected_version: 'a'.repeat(64), reason: 'Device lost.' }, context);
    const stage = { ...scope, operation_id: randomUUID(), envelope: structuredClone(f.envelope) }, stageBefore = structuredClone(stage); const pending = fieldOffline.stage(stage, context); stage.envelope.command.quantities[0].quantity = '99'; await pending;
    expect(calls.at(-1)?.body).toEqual(stageBefore);
    await fieldOffline.get(scope, f.envelope.capture_id, context, f.envelope);
    await fieldOffline.inspect(scope, f.envelope.capture_id, context, f.envelope);
    await fieldOffline.apply({ ...scope, operation_id: f.envelope.capture_id, capture_id: f.envelope.capture_id, expected_version: f.capture_version }, context, f.envelope);
    await fieldOffline.discard({ ...scope, operation_id: randomUUID(), capture_id: f.envelope.capture_id, expected_version: f.capture_version, reason: 'Remove offline copy.' }, context, f.envelope);
    const replacement = { ...structuredClone(f.envelope), capture_id: randomUUID() };
    await fieldOffline.resolve({ ...scope, operation_id: randomUUID(), capture_id: f.envelope.capture_id, expected_version: f.capture_version, reason: 'Use current source.', replacement_envelope: replacement }, context, f.envelope);
    expect(calls.map(row => row.method)).toEqual(['register_device', 'revoke_device', 'stage_capture', 'get_capture', 'inspect_capture', 'apply_capture', 'discard_capture', 'resolve_capture']);
    for (const row of calls.filter(row => row.key)) expect(row.key).toBe(row.body.operation_id);
    expect(calls.find(row => row.method === 'apply_capture')?.key).toBe(f.envelope.capture_id);
    expect(calls.find(row => row.method === 'stage_capture')?.body.envelope).toEqual(f.envelope);
    const count = calls.length;
    await expect(fieldOffline.apply({ ...scope, operation_id: randomUUID(), capture_id: f.envelope.capture_id, expected_version: f.capture_version }, context, f.envelope)).rejects.toMatchObject({ code: 'invalid_field_offline' });
    await expect(fieldOffline.stage({ ...scope, operation_id: f.envelope.capture_id, envelope: f.envelope }, context)).rejects.toMatchObject({ code: 'invalid_field_offline' });
    await expect(fieldOffline.resolve({ ...scope, operation_id: randomUUID(), capture_id: f.envelope.capture_id, expected_version: f.capture_version, reason: 'Conflict.', replacement_envelope: f.envelope }, context, f.envelope)).rejects.toMatchObject({ code: 'invalid_field_offline' });
    expect(calls).toHaveLength(count);
  } finally { globalThis.fetch = oldFetch; }
});
