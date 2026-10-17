import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';
import * as packages from '../src/api/engineering-packages';
import { artifact } from './engineering-fixture';
import { drawing, hash, noEffects, people, scope, unit, unitManifest } from './engineering-packages-fixture';

// Synthetic adapter tests only: fetch is replaced in-process; no browser or native requests.
const actor = { user: people[0].user, personId: people[0].person };
const checker = { user: people[1].user, person: people[1].person };
const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: actor.personId, author_user: actor.user, created_at: '2026-10-17T05:00:00Z', status: 'working', no_effects: noEffects });
const review = { state: 'working', check_id: null, packet_id: null, issue_authorized: false };
const wrapped = (record: any) => ({ record, record_digest: hash(record), review: 'family_id' in record ? review : null });
const exact = (record: any) => ({ revision_id: record.revision_id, source_sha256: record.source_sha256 });
const merged = (...records: any[]) => Object.fromEntries(['source_citations', 'drawing_references', 'artifacts'].map(kind => [kind, [...new Map(records.flatMap(record => record[kind] || []).map(row => [JSON.stringify([row.revision_id, row.page, row.locator, row.excerpt_sha256]), row])).values()]]));
type WorkKind = 'basis' | 'calculation' | 'deliverable';
function fixture(kind: WorkKind, successor = false) {
  const assignment = { ...base(), parent_id: randomUUID(), revision_number: 2, predecessor: randomUUID(), definition: { title: 'Structural package', discipline: 'Structural', scope: 'Check the landing beam.', responsible_user: actor.user, checker_user: checker.user, due_date: null, task_ids: [], wbs_ids: [] }, responsible: { user: actor.user, person: actor.personId }, checker };
  const header = { ...base(), id: assignment.parent_id, number: 'ENG-WP-FIXTURE-00001', revision_number: 2, current_revision: assignment.id, basis_head: '', calculation_heads: [] as string[], deliverable_heads: [] as string[] };
  const quantity = { key: 'span', label: 'Beam span', quantity: { amount: '4.000000', unit_id: unit.id, precision: 6 }, source: { revision_id: drawing.revision_id, source_sha256: drawing.source_sha256, page: 1, locator: drawing.locator } };
  const basis = { ...base(), parent_id: header.id, family_id: randomUUID(), revision_number: 1, predecessor: null, package_revision: assignment.id, package_digest: hash(assignment), checker, source_citations: [], drawing_references: [drawing], artifacts: [artifact], definition: { title: 'Landing basis', criteria: 'Declared design criteria', assumptions: '', design_codes: [], change_reason: 'Initial basis' }, quantities: [quantity], unit_manifest: {} as any };
  basis.unit_manifest = unitManifest(basis.id); header.basis_head = basis.id;
  const calculation = { ...base(), parent_id: header.id, family_id: randomUUID(), revision_number: 1, predecessor: null, package_revision: assignment.id, package_digest: hash(assignment), checker, ...merged(basis), basis_revision: basis.id, basis_digest: hash(basis), definition: { title: 'Landing result', method: 'human-authored-results-v1', algorithm_reference: 'Hand calculation sheet', tool_name: 'Manual worksheet', tool_version: '1', model_version: '', design_codes: [], explanation: 'Recorded human calculation.', change_reason: 'Initial result' }, input_keys: ['span'], inputs: [quantity], outputs: [quantity], unit_manifest: {} as any, execution: { kind: 'manual-record', executed_by_cipher: false, solver_qualified: false }, issue_readiness: 'not_authorized_for_issue' };
  calculation.unit_manifest = unitManifest(calculation.id); header.calculation_heads = [calculation.id];
  const deliverable = { ...base(), parent_id: header.id, family_id: randomUUID(), revision_number: 1, predecessor: null, package_revision: assignment.id, package_digest: hash(assignment), checker, ...merged(basis, calculation), basis_revision: basis.id, basis_digest: hash(basis), definition: { title: 'Landing detail package', deliverable_type: 'Design note', description: 'Exact recorded detail.', checking_notes: '', change_reason: 'Initial deliverable' }, calculations: [{ id: calculation.id, record_digest: hash(calculation) }], issue_readiness: 'not_authorized_for_issue' };
  header.deliverable_heads = [deliverable.id];
  const newArtifact = { ...artifact, revision_id: randomUUID(), document_id: randomUUID(), source_sha256: 'c'.repeat(64) };
  const old = kind === 'basis' ? basis : kind === 'calculation' ? calculation : deliverable;
  const previous = kind === 'basis' || successor ? old : undefined;
  const authored: any = { ...structuredClone(old), id: randomUUID(), family_id: previous?.family_id || randomUUID(), predecessor: previous?.id || null, revision_number: (previous?.revision_number || 0) + 1 };
  let payload: any = { ...scope, package_id: header.id, expected_version: hash(header), definition: authored.definition };
  if (kind === 'basis') { authored.unit_manifest = unitManifest(authored.id); payload = { ...payload, quantities: basis.quantities, source_citations: [], drawing_references: [{ revision_id: drawing.revision_id, source_sha256: drawing.source_sha256, page: drawing.page, locator: drawing.locator }], artifacts: [exact(artifact)] }; }
  else {
    Object.assign(authored, merged(basis, ...(kind === 'deliverable' ? [calculation] : []), { artifacts: [newArtifact] }));
    payload = { ...payload, basis_revision: basis.id, basis_digest: hash(basis), predecessor: previous?.id || null, artifacts: [exact(newArtifact)] };
    if (kind === 'calculation') { authored.unit_manifest = unitManifest(authored.id); payload = { ...payload, input_keys: authored.input_keys, outputs: authored.outputs }; }
    else payload = { ...payload, calculations: authored.calculations, source_citations: [], drawing_references: [] };
  }
  const finalHeader = { ...header, ...(kind === 'basis' ? { basis_head: authored.id } : { [kind + '_heads']: [...header[(kind + '_heads') as 'calculation_heads' | 'deliverable_heads'].filter(id => id !== previous?.id), authored.id] }) };
  const command: any = { kind: `create_${kind}`, operation_id: randomUUID(), payload, basis: { header: wrapped(header), revision: wrapped(assignment), basis: wrapped(basis), calculations: [wrapped(calculation)], ...(previous && kind !== 'basis' ? { predecessor: wrapped(previous) } : {}) } };
  const response: any = { package: finalHeader, [kind]: authored, history_id: randomUUID(), operation: { id: command.operation_id, status: 'succeeded', replayed: false } };
  return { kind, command, response, header, assignment, basis, calculation, deliverable, authored, newArtifact };
}
async function reply<T>(value: unknown, run: () => Promise<T>) {
  const previous = globalThis.fetch; let calls = 0;
  globalThis.fetch = async (_url, init) => { calls++; expect(init?.method).toBe('POST'); return new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', data: value } }), { status: 200 }); };
  try { return await run(); } finally { globalThis.fetch = previous; expect(calls).toBe(1); }
}
const send = (f: ReturnType<typeof fixture>) => reply(f.response, () => packages.engineeringPackages.send(f.command, actor));

for (const kind of ['basis', 'calculation', 'deliverable'] as const) test(`exact ${kind} successor and literal header projection are accepted`, async () => {
  const f = fixture(kind, true); await expect(send(f)).resolves.toMatchObject({ [kind]: { id: f.authored.id } });
});
test('calculation confirmation inherits only basis plus new output artifacts, never unrelated calculations', async () => {
  const f = fixture('calculation');
  f.command.basis.calculations[0].record.artifacts.push({ ...artifact, revision_id: randomUUID(), source_sha256: 'd'.repeat(64) });
  f.command.basis.calculations[0].record_digest = hash(f.command.basis.calculations[0].record);
  await expect(send(f)).resolves.toMatchObject({ calculation: { id: f.authored.id } });
});
test('deliverable confirmation includes selected calculation artifacts and refuses their omission', async () => {
  const f = fixture('deliverable'); const extra = { ...artifact, revision_id: randomUUID(), source_sha256: 'd'.repeat(64) };
  f.command.basis.calculations[0].record.artifacts.push(extra); f.command.basis.calculations[0].record_digest = hash(f.command.basis.calculations[0].record);
  f.command.payload.calculations[0].record_digest = f.command.basis.calculations[0].record_digest; f.authored.calculations = structuredClone(f.command.payload.calculations); f.authored.artifacts.push(extra);
  await expect(send(f)).resolves.toMatchObject({ deliverable: { id: f.authored.id } });
  f.authored.artifacts.pop(); await expect(send(f)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
for (const kind of ['basis', 'calculation', 'deliverable'] as const) for (const wrong of ['family', 'checker', 'header'] as const) test(`${kind} reply refuses changed ${wrong} against its captured original`, async () => {
  const f = fixture(kind, true);
  if (wrong === 'family') f.authored.family_id = randomUUID();
  if (wrong === 'checker') f.authored.checker = { ...checker, user: 'other.checker@example.invalid' };
  if (wrong === 'header') { if (kind === 'basis') f.response.package.calculation_heads = []; else f.response.package.basis_head = randomUUID(); }
  await expect(send(f)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('calculation refuses a self-consistent changed input-unit revision/symbol despite unchanged quantity', async () => {
  const f = fixture('calculation'); f.authored.unit_manifest.records[1] = { ...structuredClone(unit), revision: 2, fields: { ...unit.fields, symbol: 'changed-m' } };
  await expect(send(f)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('calculation successor removes only its original family head and preserves all other heads', async () => {
  const f = fixture('calculation', true), other = randomUUID(); f.header.calculation_heads.push(other); f.command.payload.expected_version = hash(f.header); f.command.basis.header = wrapped(f.header); f.response.package.calculation_heads = [f.authored.id];
  await expect(send(f)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});

function checkFixture(kind: WorkKind) {
  const f = fixture(kind), subject = wrapped(f.authored), value = f.authored;
  const type = { basis: 'Cipher Design Basis Revision', calculation: 'Cipher Calculation Revision', deliverable: 'Cipher Deliverable Revision' }[kind];
  const effect = { schema: 'cipher.engineering.package-check.v1', action: packages.packageAction[kind], subject_kind: kind, subject_id: value.id, subject_digest: subject.record_digest, parent_id: value.parent_id, package_revision: value.package_revision, package_digest: value.package_digest, preparer_person: value.author_person, checker: value.checker, outcome: 'checked', issue_authorized: false, sealed: false };
  const manifest = { subject: { doctype: type, name: value.id, label: value.definition.title }, sources: [{ source_citations: value.source_citations, drawing_references: value.drawing_references, artifacts: value.artifacts, unit_manifest: value.unit_manifest || null }], effect, summary: { definition: value.definition, inputs: value.inputs || value.quantities || [], outputs: value.outputs || [], calculations: value.calculations || [], no_effects: noEffects, solver_executed: false, issue_authorized: false, sealed: false } };
  const packet: any = structuredClone({ id: randomUUID(), ...scope, action: effect.action, subject: { id: value.id, type, label: value.definition.title }, requester: { id: actor.personId, display_name: 'Alex Author' }, created_at: '2026-10-17T05:00:00Z', expires_at: '2026-10-18T05:00:00Z', manifest_hash: hash(manifest), source_version: subject.record_digest, policy: { id: 'fixture', label: 'Synthetic', synthetic: true }, state: 'Pending', decisions: [], actions: { can_decide: false, can_execute: false, can_withdraw: true, disabled_reason: null }, review_manifest: manifest, schema: 'cipher.engineering.package-approval.v1' });
  const command: any = { kind: 'request_check', operation_id: randomUUID(), payload: scope, subject, subjectKind: kind };
  return { packet, subject, command, response: { packet, operation: { id: command.operation_id, status: 'succeeded', replayed: false } } };
}
for (const kind of ['basis', 'calculation', 'deliverable'] as const) test(`checking request accepts the exact ${kind} manifest`, async () => {
  const f = checkFixture(kind); await expect(reply(f.response, () => packages.engineeringPackages.send(f.command, actor))).resolves.toMatchObject({ packet: { id: f.packet.id } });
});
for (const wrong of ['source', 'input', 'output', 'calculations', 'manifest-unit', 'checker'] as const) test(`checking request rejects a self-consistent changed ${wrong} manifest`, async () => {
  const f = checkFixture(wrong === 'calculations' ? 'deliverable' : 'calculation'), m = f.packet.review_manifest;
  if (wrong === 'source') m.sources[0].drawing_references[0].source_sha256 = 'f'.repeat(64);
  if (wrong === 'input') m.summary.inputs[0].quantity.amount = '99.000000';
  if (wrong === 'output') m.summary.outputs[0].quantity.amount = '99.000000';
  if (wrong === 'calculations') m.summary.calculations[0].record_digest = 'f'.repeat(64);
  if (wrong === 'manifest-unit') m.sources[0].unit_manifest.records[1].revision = 2;
  if (wrong === 'checker') m.effect.checker.user = 'other.checker@example.invalid';
  f.packet.manifest_hash = hash(m);
  await expect(reply(f.response, () => packages.engineeringPackages.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('independently read approval helper accepts a historical subject for a different current reader', async () => {
  const f = checkFixture('calculation');
  expect(typeof (packages as any).validatePackageManifestSubject).toBe('function');
  await expect((packages as any).validatePackageManifestSubject(f.packet, f.subject, 'calculation')).resolves.toMatchObject({ id: f.packet.id });
});
test('independently read approval helper refuses full-checker mismatch with the same person', async () => {
  const f = checkFixture('basis'); f.packet.review_manifest.effect.checker.user = 'other.alias@example.invalid'; f.packet.manifest_hash = hash(f.packet.review_manifest);
  expect(typeof (packages as any).validatePackageManifestSubject).toBe('function');
  await expect((packages as any).validatePackageManifestSubject(f.packet, f.subject, 'basis')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
