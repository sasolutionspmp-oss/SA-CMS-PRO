import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { fieldShape, validateFieldRecord, validateFieldReply } from '../src/api/field';
import { dailyDefinition, hash, noEffects, people, scope, seedDaily, source } from './field-fixture';
const actor = { user: people[0].user, personId: people[0].person };
const wrapped = (record: any) => ({ record: structuredClone(record), record_digest: hash(record) });
function createFixture() {
  const seed = seedDaily(), command: any = { kind: 'create_record', operation_id: randomUUID(), payload: { ...scope, family: 'daily', definition: dailyDefinition, photos: [], quantities: seed.quantities.map(row => ({ ...row.definition, sources: [source] })) } };
  const reply: any = { family: 'daily', ...seed, history_id: randomUUID(), operation: { id: command.operation_id, status: 'succeeded', replayed: false } };
  return { command, reply };
}
test('closed Field schema enforces conditional family, exact dates, nonblank values and documentary quantities', async () => {
  const { command, reply } = createFixture(); expect(fieldShape('FdCreateRecordRequest', { ...command.payload, operation_id: command.operation_id })).toBe(true); await expect(validateFieldReply(command, reply, actor)).resolves.toBe(reply);
  for (const quantity of ['0', '0.000000', '-1', '1e3', '01.2', '1.0000001', 1.2]) expect(fieldShape('FdQuantityValue', quantity)).toBe(false);
  for (const value of ['0.000001', '999999999999.999999', '12.000001']) expect(fieldShape('FdQuantityValue', value)).toBe(true);
  expect(fieldShape('FdDate', '2026-02-30')).toBe(false); expect(fieldShape('FdTimestamp', '2026-10-17T14:00:00')).toBe(false); expect(fieldShape('FdSourceInput', { ...source, locator: '   ' })).toBe(false);
  expect(fieldShape('FdCreateRecordRequest', { ...command.payload, operation_id: command.operation_id, family: 'ticket' })).toBe(false);
  expect(fieldShape('FdTicketLineInput', { kind: 'labor', description: 'Recorded work', quantity: '1.0', unit: 'hours', sources: [source], rate: '100.00' })).toBe(false);
  expect(fieldShape('FdDailyDefinitionInput', { ...dailyDefinition, weather: 'Clear', weather_sources: [] })).toBe(false);
});
for (const [label, change] of [
  ['wrong receipt', (r: any) => { r.operation.id = randomUUID(); }],
  ['wrong project', (r: any) => { r.header.project = 'OTHER'; }],
  ['different author Person', (r: any) => { r.revision.author_person = people[1].person; }],
  ['different author login', (r: any) => { r.revision.author_user = people[3].user; }],
  ['wrong current revision', (r: any) => { r.header.current_revision = randomUUID(); }],
  ['changed exact quantity', (r: any) => { r.quantities[0].definition.quantity = '12.000002'; }],
  ['changed unit label', (r: any) => { r.quantities[0].definition.unit = 'feet'; }],
  ['unbound quantity ID', (r: any) => { r.revision.quantity_ids = [randomUUID()]; }],
  ['wrong source bytes', (r: any) => { r.quantities[0].definition.sources[0].source_sha256 = 'b'.repeat(64); }],
  ['financial effect', (r: any) => { r.revision.no_effects = { ...noEffects, invoice_change: true }; }],
  ['invented response field', (r: any) => { r.header.contract_value = '100'; }],
] as const) test(`create receipt rejects ${label}`, async () => { const { command, reply } = createFixture(); change(reply); await expect(validateFieldReply(command, reply, actor)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
function transitionFixture() {
  const seed = seedDaily(), header = { ...seed.header, status: 'reviewed', last_decision: randomUUID() }, reviewer = { user: people[2].user, personId: people[2].person };
  const command: any = { kind: 'transition', operation_id: randomUUID(), payload: { ...scope, family: 'daily', record_id: header.id, expected_version: hash(header), action: 'accept', comment: 'Accept the exact observations.', evidence: [], acknowledged_by: '' }, basis: { header: wrapped(header), revision: wrapped(seed.revision) } };
  const decision = { ...seed.revision, id: randomUUID(), author_user: reviewer.user, author_person: reviewer.personId, parent_id: header.id, source_revision: seed.revision.id, source_digest: hash(seed.revision), predecessor: header.last_decision, action: 'accept', from_status: 'reviewed', to_status: 'accepted', comment: command.payload.comment, acknowledged_by: '', evidence: [], no_effects: noEffects } as any;
  for (const key of ['revision_number', 'prior_decision', 'amendment_of', 'amendment_reason', 'definition', 'superintendent', 'photos', 'quantity_ids']) delete decision[key];
  const reply: any = { family: 'daily', header: { ...header, status: 'accepted', accepted_revision: seed.revision.id, last_decision: decision.id }, revision: seed.revision, decision, history_id: randomUUID(), operation: { id: command.operation_id, status: 'succeeded', replayed: false } };
  return { command, reply, reviewer };
}
test('an original transition receipt validates against its retained basis after a later head would differ', async () => { const f = transitionFixture(); await expect(validateFieldReply(f.command, f.reply, f.reviewer)).resolves.toBe(f.reply); const later = structuredClone(f.reply.header); later.current_revision = randomUUID(); later.status = 'draft'; expect(hash(later)).not.toBe(f.command.payload.expected_version); await expect(validateFieldReply(f.command, { ...f.reply, operation: { ...f.reply.operation, replayed: true } }, f.reviewer)).resolves.toMatchObject({ operation: { replayed: true } }); });
for (const [label, change] of [
  ['different immutable revision', (r: any) => { r.revision.definition.activities = ['Unrelated observation']; }],
  ['wrong source digest', (r: any) => { r.decision.source_digest = 'c'.repeat(64); }],
  ['wrong decision chain', (r: any) => { r.decision.predecessor = randomUUID(); }],
  ['changed comment', (r: any) => { r.decision.comment = 'Another review'; }],
  ['changed header identity', (r: any) => { r.header.author_person = people[2].person; }],
  ['acceptance of another revision', (r: any) => { r.header.accepted_revision = randomUUID(); }],
] as const) test(`transition receipt rejects ${label}`, async () => { const f = transitionFixture(); change(f.reply); await expect(validateFieldReply(f.command, f.reply, f.reviewer)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
test('read validation rejects changed digest, foreign scope and another immutable kind', async () => { const seed = seedDaily(); await expect(validateFieldRecord(wrapped(seed.revision), scope, 'daily_revision', seed.revision.id, seed.header.id)).resolves.toMatchObject({ record: { id: seed.revision.id } }); await expect(validateFieldRecord({ ...wrapped(seed.revision), record_digest: 'd'.repeat(64) }, scope, 'daily_revision')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); await expect(validateFieldRecord(wrapped(seed.revision), { ...scope, project: 'OTHER' }, 'daily_revision')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); await expect(validateFieldRecord(wrapped(seed.revision), scope, 'ticket_revision')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
