import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { documentControl, validateDocumentRecord, validateDocumentManifestSubject } from '../src/api/document-control';
import { artifact, document, documentBase, documentPacketFixture, evidenceArtifact, hash, libraryDefinition, people, rightsFixture, scope } from './document-control-fixture';
const actor = { user: people[0].user, personId: people[0].person };
const wrapped = (record: any, library_current: boolean | null = null) => ({ record, record_digest: hash(record), library_current });
async function reply<T>(value: unknown, run: () => Promise<T>) { const old = globalThis.fetch; globalThis.fetch = async () => new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', data: value } }), { status: 200 }); try { return await run(); } finally { globalThis.fetch = old; } }
function subjectFixture(kind: 'issue_set' | 'adoption_request' | 'transmittal') {
  const value: any = { ...documentBase(), artifacts: [artifact] };
  if (kind === 'issue_set') Object.assign(value, { definition: { title: 'Exact construction review set', purpose: 'Internal coordination', issue_purpose: 'coordination' }, adoptions: [], package_digest: hash({ artifacts: [artifact], definition: { title: 'Exact construction review set', purpose: 'Internal coordination', issue_purpose: 'coordination' }, adoptions: [] }) });
  else if (kind === 'adoption_request') Object.assign(value, { parent_id: randomUUID(), library_revision: randomUUID(), library_digest: 'a'.repeat(64), definition: { purpose: 'Use exact specification', target_locator: 'Concrete package §3', change_reason: 'Initial reviewed adoption' } });
  else Object.assign(value, { parent_id: randomUUID(), issue_id: '', issue_digest: 'a'.repeat(64), recipients: [{ user: people[2].user, person: people[2].person }], purpose: 'Internal document review', required_response: '', channel: 'internal', package_digest: 'b'.repeat(64) });
  if (kind === 'transmittal') value.issue_id = value.parent_id;
  const packet: any = documentPacketFixture(kind, value), subject = wrapped(value, kind === 'adoption_request' ? true : null);
  return { value, packet, subject, kind };
}
for (const kind of ['issue_set', 'adoption_request', 'transmittal'] as const) test(`native-shaped ${kind} packet accepts its opaque full envelope hash`, async () => {
  const f = subjectFixture(kind); expect(f.packet.manifest_hash).not.toBe(hash(f.packet.review_manifest)); await expect(validateDocumentManifestSubject(f.packet, f.subject, kind)).resolves.toMatchObject({ id: f.packet.id });
});
for (const change of ['scope', 'source-bytes', 'rights-owner', 'effect', 'summary', 'requester'] as const) test(`approval refuses self-consistent changed ${change} against original subject`, async () => {
  const f = subjectFixture('issue_set'), m = f.packet.review_manifest;
  if (change === 'scope') f.packet.project = 'OTHER-PROJECT';
  if (change === 'source-bytes') m.sources[0].artifacts[0].source_sha256 = 'f'.repeat(64);
  if (change === 'rights-owner') m.sources[0].rights[0].parent_id = randomUUID();
  if (change === 'effect') m.effect.package_digest = 'f'.repeat(64);
  if (change === 'summary') m.summary.definition.purpose = 'Changed purpose';
  if (change === 'requester') f.packet.requester.id = people[1].person;
  f.packet.manifest_hash = hash({ full_synthetic_envelope: m });
  await expect(validateDocumentManifestSubject(f.packet, f.subject, 'issue_set')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('record digest alone cannot authorize a self-consistent different Project record', async () => { const value = { ...rightsFixture(), project: 'OTHER-PROJECT' }; await expect(validateDocumentRecord(wrapped(value), scope, 'rights')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
test('rights save pins reviewed original policy and distinct immutable evidence', async () => {
  const old = rightsFixture(), { evidence_artifact: _evidence, ...fields } = old;
  const definition = { ingest_allowed: false, read_allowed: true, distribute_allowed: false, rights_holder: old.rights_holder, rights_basis: 'Restricted retained use', allowed_purpose: old.allowed_purpose, restriction: 'Internal review', valid_from: null, valid_until: null, evidence_artifact: { revision_id: evidenceArtifact.revision_id, source_sha256: evidenceArtifact.source_sha256 } };
  const command: any = { kind: 'set_rights', payload: { ...scope, document_id: document.id, expected_version: hash(old), definition }, basis: { original: wrapped(old), artifacts: [evidenceArtifact] }, operation_id: randomUUID() };
  const rights = { ...fields, ...definition, id: randomUUID(), predecessor: old.id, revision_number: old.revision_number + 1, evidence_artifact: evidenceArtifact }; const response = { rights, history_id: randomUUID(), operation: { id: command.operation_id, status: 'succeeded', replayed: false } };
  await expect(reply(response, () => documentControl.send(command, actor))).resolves.toMatchObject({ rights: { predecessor: old.id } });
  response.rights.evidence_artifact = { ...evidenceArtifact, document_id: document.id }; response.rights.evidence_artifact.source_sha256 = 'f'.repeat(64); await expect(reply(response, () => documentControl.send(command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('library successor retains header authorship and exact predecessor', async () => {
  const old = { ...documentBase(1), current_revision: randomUUID(), revision_number: 3 }, revision = { ...documentBase(), parent_id: old.id, predecessor: old.current_revision, revision_number: 4, definition: libraryDefinition, artifacts: [artifact] }, library = { ...old, current_revision: revision.id, revision_number: 4 };
  const command: any = { kind: 'revise_library', payload: { ...scope, library_id: old.id, expected_version: hash(old), definition: libraryDefinition, artifact: { revision_id: artifact.revision_id, source_sha256: artifact.source_sha256 } }, basis: { original: wrapped(old), artifacts: [artifact] }, operation_id: randomUUID() };
  const response = { library, library_revision: revision, history_id: randomUUID(), operation: { id: command.operation_id, status: 'succeeded', replayed: false } };
  await expect(reply(response, () => documentControl.send(command, actor))).resolves.toMatchObject({ library: { author_person: people[1].person } }); response.library.author_person = actor.personId; await expect(reply(response, () => documentControl.send(command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
function executionFixture() {
  const f = subjectFixture('transmittal'); const decision = { id: randomUUID(), actor: { id: people[1].person, display_name: people[1].display_name }, decision: 'Grant', reason: 'Exact original reviewed', at: '2026-10-17T05:01:00Z' }; f.packet.state = 'Granted'; f.packet.decisions = [decision];
  const distribution = { ...documentBase(0, 'recorded_internally'), parent_id: f.value.id, subject_id: f.value.id, subject_digest: hash(f.value), packet_id: f.packet.id, decision_id: decision.id, checked_by_person: people[1].person, effect_digest: hash(f.packet.review_manifest.effect), artifacts: [artifact], electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false, package_digest: f.value.package_digest, recipients: f.value.recipients, channel: 'internal' };
  const command: any = { kind: 'authorization_action', payload: scope, packet: f.packet, action: 'execute', reason: '', operation_id: randomUUID() }, response = { packet: structuredClone({ ...f.packet, state: 'Consumed' }), effect: { distribution }, operation: { id: command.operation_id, status: 'succeeded', replayed: false } };
  return { ...f, command, response };
}
test('exact internal distribution consumes the original grant and full opaque hash', async () => { const f = executionFixture(); await expect(reply(f.response, () => documentControl.send(f.command, actor))).resolves.toMatchObject({ effect: { distribution: { external_delivery: false } } }); });
for (const wrong of ['requester', 'grant-person', 'grant-reason', 'grant-time', 'removed-grant', 'recipient-person', 'effect-digest', 'author-person'] as const) test(`distribution reply refuses changed ${wrong}`, async () => {
  const f = executionFixture(), p = f.response.packet, d = f.response.effect.distribution;
  if (wrong === 'requester') p.requester.id = people[2].person;
  if (wrong === 'grant-person') p.decisions[0].actor.id = people[2].person;
  if (wrong === 'grant-reason') p.decisions[0].reason = 'Rewritten decision';
  if (wrong === 'grant-time') p.decisions[0].at = '2026-10-17T05:02:00Z';
  if (wrong === 'removed-grant') p.decisions = [];
  if (wrong === 'recipient-person') d.recipients = [{ user: people[2].user, person: people[1].person }];
  if (wrong === 'effect-digest') d.effect_digest = 'f'.repeat(64);
  if (wrong === 'author-person') d.author_person = people[1].person;
  await expect(reply(f.response, () => documentControl.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('current display label change preserves original canonical grant authority', async () => { const f = executionFixture(); f.response.packet.requester.display_name = 'Current preparer label'; f.response.packet.decisions[0].actor.display_name = 'Current reviewer label'; await expect(reply(f.response, () => documentControl.send(f.command, actor))).resolves.toMatchObject({ packet: { state: 'Consumed' } }); });
