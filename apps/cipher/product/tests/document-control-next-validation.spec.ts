import { createHash, randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { isUnknownResult } from '../src/api/client';
import { documentControlNext, validateCompanyDocumentRecord, validateIssuedStanding, validateNextDocumentManifestSubject, validateNextDocumentRecord } from '../src/api/document-control-next';
import { artifact, documentBase, evidenceArtifact, hash, libraryDefinition, noEffects, people, rightsFixture, scope } from './document-control-fixture';

const actor = { user: people[0].user, personId: people[0].person };
const rawHash = (text: string) => createHash('sha256').update(text).digest('hex');
const wrapped = (record: any, library_current: boolean | null = null) => ({ record, record_digest: hash(record), library_current });
const operation = (id: string, replayed = false) => ({ id, status: 'succeeded', replayed });
async function reply<T>(value: unknown, run: () => Promise<T>, inspect?: (url: string, init?: RequestInit) => void) {
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, init) => { inspect?.(String(url), init); return new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', data: value } }), { status: 200 }); };
  try { return await run(); } finally { globalThis.fetch = previous; }
}
const companyBase = (index = 0, status = 'working') => ({ ...documentBase(index, status), project: null, scope_type: 'Company' });
const official = (status = 'adopted') => ({ ...documentBase(0, status), parent_id: randomUUID(), subject_id: '', subject_digest: 'a'.repeat(64), packet_id: randomUUID(), decision_id: randomUUID(), checked_by_person: people[1].person, effect_digest: 'b'.repeat(64), artifacts: [artifact], electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false });
function adopted() { const value = official(); value.subject_id = value.parent_id; return wrapped(value, true); }
function companyLibraryFixture(revise = false) {
  const old = { ...companyBase(1), current_revision: randomUUID(), revision_number: 2 };
  const library = revise ? { ...old } : { ...companyBase(), current_revision: '', revision_number: 0 };
  const revision = { ...companyBase(), parent_id: library.id, predecessor: revise ? old.current_revision : null, revision_number: revise ? 3 : 1, definition: libraryDefinition, artifacts: [artifact] };
  library.current_revision = revision.id; library.revision_number = revision.revision_number;
  const command: any = { kind: revise ? 'company_revise_library' : 'company_create_library', payload: { company: scope.company, definition: libraryDefinition, artifact: { revision_id: artifact.revision_id, source_sha256: artifact.source_sha256 }, ...(revise ? { library_id: old.id, expected_version: hash(old) } : {}) }, basis: { artifacts: [artifact], ...(revise ? { original: wrapped(old) } : {}) }, operation_id: randomUUID() };
  return { old, library, revision, command, response: { library, library_revision: revision, history_id: randomUUID(), operation: operation(command.operation_id) } };
}
function sharedFixture(origin: 'Company' | 'Project' = 'Company') {
  const original = { ...(origin === 'Company' ? companyBase() : { ...documentBase(), project: 'ORIGINAL-PROJECT' }), parent_id: randomUUID(), predecessor: null, revision_number: 1, definition: libraryDefinition, artifacts: [artifact] };
  const library_scope = { scope_type: origin, project: origin === 'Company' ? null : 'ORIGINAL-PROJECT' };
  const definition = { purpose: 'Exact reusable clause adoption', target_locator: 'Concrete §3', change_reason: 'Original selection' };
  const command: any = { kind: 'create_shared_adoption', payload: { ...scope, library_scope, library_revision: original.id, library_digest: hash(original), definition }, basis: { original: wrapped(original, true) }, operation_id: randomUUID() };
  const subject = { ...documentBase(), parent_id: original.parent_id, library_scope, library_revision: original.id, library_digest: hash(original), definition, artifacts: [artifact] };
  return { command, subject, response: { adoption_request: subject, history_id: randomUUID(), operation: operation(command.operation_id) } };
}
function clauseFixture() {
  const adoption = adopted(), text = 'Use concrete 😀 exactly as specified.';
  const source_clause = { revision_id: artifact.revision_id, source_sha256: artifact.source_sha256, page: 1, excerpt_sha256: rawHash(text), start: 0, end: [...text].length };
  const target = { kind: 'proposal_revision', id: randomUUID(), record_digest: 'c'.repeat(64), locator: 'Section 3' };
  const snapshot = { kind: target.kind, id: target.id, record_digest: target.record_digest, parent_id: randomUUID(), company: scope.company, project: null, scope_type: 'Company' };
  const command: any = { kind: 'create_clause_use', payload: { ...scope, adoption_id: adoption.record.id, adoption_digest: adoption.record_digest, source_clause, target, purpose: 'Document exact proposed relationship' }, basis: { adoption, target: structuredClone(snapshot), quotedText: text }, operation_id: randomUUID() };
  const subject = { ...documentBase(0, 'referenced'), parent_id: adoption.record.id, adoption_id: adoption.record.id, adoption_digest: adoption.record_digest, source_clause: { reference: source_clause, text, text_sha256: rawHash(text) }, target, target_snapshot: snapshot, purpose: command.payload.purpose, artifacts: [artifact], target_changed: false };
  return { command, subject, response: { clause_use: subject, history_id: randomUUID(), operation: operation(command.operation_id) } };
}
function redlineFixture(successor = false) {
  const clause = clauseFixture().subject, proposed_text = 'Use the revised concrete requirement.';
  const previous = { ...documentBase(1, 'proposed'), parent_id: clause.id, clause_use_id: clause.id, clause_use_digest: hash(clause), predecessor: null, revision_number: 1, original_text: clause.source_clause.text, proposed_text: 'Previous proposed concrete requirement.', proposed_sha256: rawHash('Previous proposed concrete requirement.'), reason: 'First proposal', target: clause.target, target_snapshot: clause.target_snapshot, artifacts: clause.artifacts, target_changed: false };
  const command: any = { kind: 'create_redline', payload: { ...scope, clause_use_id: clause.id, clause_use_digest: hash(clause), expected_version: successor ? hash(previous) : null, proposed_text, reason: 'Coordinate exact alternative' }, basis: { original: wrapped(clause), ...(successor ? { previous: wrapped(previous) } : {}) }, operation_id: randomUUID() };
  const subject = { ...previous, ...documentBase(0, 'proposed'), predecessor: successor ? previous.id : null, revision_number: successor ? 2 : 1, proposed_text, proposed_sha256: rawHash(proposed_text), reason: command.payload.reason };
  return { command, subject, response: { redline: subject, history_id: randomUUID(), operation: operation(command.operation_id) } };
}
function lifecycleFixture(action: 'withdraw' | 'supersede' = 'withdraw') {
  const issue = { ...official('issued'), package_digest: 'd'.repeat(64) }; issue.subject_id = issue.parent_id;
  const replacementArtifact = { ...artifact, revision_id: randomUUID(), revision_number: 2, source_sha256: 'e'.repeat(64) };
  const replacementIssue = { ...issue, id: randomUUID(), artifacts: [replacementArtifact] };
  const reference = (record: any) => ({ issue_id: record.id, issue_digest: hash(record), revision_id: record.artifacts[0].revision_id, source_sha256: record.artifacts[0].source_sha256 });
  const body = { ...scope, scope_type: 'Project', document_id: artifact.document_id, status: 'issued', original_issued: reference(issue), current_issued: reference(issue), last_event: null };
  const standing = { ...body, version: hash(body) };
  const definition = { action, issue_id: issue.id, issue_digest: hash(issue), replacement_issue_id: action === 'supersede' ? replacementIssue.id : null, replacement_issue_digest: action === 'supersede' ? hash(replacementIssue) : null, reason: 'Exact independently reviewed lifecycle change' };
  const artifacts = action === 'supersede' ? [artifact, replacementArtifact].sort((a, b) => a.revision_id < b.revision_id ? -1 : 1) : [artifact];
  const command: any = { kind: 'request_lifecycle', payload: { ...scope, document_id: artifact.document_id, expected_version: standing.version, definition }, basis: { standing, original: wrapped(issue), ...(action === 'supersede' ? { replacement: wrapped(replacementIssue) } : {}) }, operation_id: randomUUID() };
  const subject = { ...documentBase(), parent_id: artifact.document_id, expected_version: standing.version, before: structuredClone(body), definition, replacement: action === 'supersede' ? reference(replacementIssue) : null, artifacts };
  return { command, subject, response: { lifecycle_request: subject, history_id: randomUUID(), operation: operation(command.operation_id) } };
}

test('issued standing and lifecycle records retain actual native Document and Revision names', async () => {
  const f: any = lifecycleFixture(), documentId = 'DOC-2026-00042', revisionId = 'REV-2026-00073';
  f.subject.parent_id = documentId; f.subject.before.document_id = documentId; f.subject.before.original_issued.revision_id = revisionId; f.subject.before.current_issued.revision_id = revisionId;
  f.subject.artifacts = [{ ...artifact, document_id: documentId, revision_id: revisionId }]; f.subject.expected_version = hash(f.subject.before);
  const standing = { ...f.subject.before, version: f.subject.expected_version };
  await expect(validateIssuedStanding({ standing }, scope, documentId)).resolves.toHaveProperty('standing.document_id', documentId);
  await expect(validateNextDocumentRecord(wrapped(f.subject), scope, 'lifecycle_request', f.subject.id, documentId)).resolves.toHaveProperty('record.artifacts.0.revision_id', revisionId);
});

test('native names remain bounded while documentary issue identities remain UUIDs', async () => {
  const f: any = lifecycleFixture(); f.subject.before.document_id = 'D'.repeat(141);
  await expect(validateIssuedStanding({ standing: { ...f.subject.before, version: hash(f.subject.before) } }, scope)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  f.subject.before.document_id = 'DOC-2026-00042'; f.subject.before.current_issued.issue_id = 'DOC-THIS-IS-NOT-AN-ISSUE';
  await expect(validateIssuedStanding({ standing: { ...f.subject.before, version: hash(f.subject.before) } }, scope)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});

test('clause references preserve native source and document target names without widening commercial identities', async () => {
  const f: any = clauseFixture(), documentId = 'DOC-2026-00042', revisionId = 'REV-2026-00073';
  f.subject.source_clause.reference.revision_id = revisionId; f.subject.artifacts = [{ ...artifact, document_id: documentId, revision_id: revisionId }];
  f.subject.target = { ...f.subject.target, kind: 'document_revision', id: revisionId };
  f.subject.target_snapshot = { ...f.subject.target_snapshot, ...scope, scope_type: 'Project', kind: 'document_revision', id: revisionId, parent_id: documentId };
  await expect(validateNextDocumentRecord(wrapped(f.subject), scope, 'clause_use', f.subject.id)).resolves.toHaveProperty('record.target.id', revisionId);
  f.subject.target.kind = 'proposal_revision'; f.subject.target_snapshot.kind = 'proposal_revision';
  await expect(validateNextDocumentRecord(wrapped(f.subject), scope, 'clause_use', f.subject.id)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
function packetFixture(kind: 'adoption_request' | 'redline' | 'lifecycle_request', subject: any) {
  const action = { adoption_request: 'document.library.adopt.v1', redline: 'document.clause.apply.v1', lifecycle_request: 'document.lifecycle.v1' }[kind];
  const type = { adoption_request: 'Cipher Adoption Request', redline: 'Cipher Redline Revision', lifecycle_request: 'Cipher Document Lifecycle Request' }[kind];
  const effect: any = { schema: 'cipher.document.authorization.v1', action, subject_kind: kind, subject_id: subject.id, subject_digest: hash(subject), artifacts: subject.artifacts, no_effects: noEffects, electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false };
  if (kind === 'adoption_request') Object.assign(effect, { library_revision: subject.library_revision, library_digest: subject.library_digest, library_scope: subject.library_scope, target_locator: subject.definition.target_locator });
  else if (kind === 'redline') for (const key of ['target', 'target_snapshot', 'original_text', 'proposed_text', 'proposed_sha256', 'target_changed']) effect[key] = subject[key];
  else Object.assign(effect, { document_id: subject.parent_id, before: subject.before, definition: subject.definition, replacement: subject.replacement, expected_version: subject.expected_version });
  const rights = [...new Set<string>(subject.artifacts.map((row: any) => row.document_id))].sort().map(id => ({ ...rightsFixture(), parent_id: id, ...(kind === 'adoption_request' ? { scope_type: subject.library_scope.scope_type, project: subject.library_scope.project } : {}) }));
  const label = kind === 'redline' ? subject.reason : kind === 'lifecycle_request' ? subject.definition.reason : subject.definition.purpose;
  const manifest = { subject: { doctype: type, name: subject.id, label }, sources: [{ artifacts: subject.artifacts, rights }], effect, summary: { definition: subject.definition || null, purpose: null, required_response: null, no_effects: noEffects, rights_basis: 'authored-declaration', external_delivery: false, commercial_execution: false } };
  return structuredClone({ id: randomUUID(), ...scope, action, subject: { id: subject.id, type, label }, requester: { id: subject.author_person, display_name: 'Alex Author' }, created_at: '2026-10-17T05:00:00Z', expires_at: '2026-10-18T05:00:00Z', manifest_hash: hash({ opaque_authority_envelope: manifest }), source_version: hash(subject), policy: { id: 'doc-next-policy', label: 'Synthetic review policy', synthetic: true }, state: 'Pending', decisions: [] as any[], actions: { can_decide: false, can_execute: false, can_withdraw: true, disabled_reason: null }, review_manifest: manifest, schema: 'cipher.document.approval.v1' });
}

for (const revise of [false, true]) test(`Company library ${revise ? 'successor' : 'creation'} binds explicit route, source and authorship`, async () => {
  const f = companyLibraryFixture(revise);
  await expect(reply(f.response, () => documentControlNext.send(f.command, actor), (url, init) => { expect(url).toContain(`company_api.${revise ? 'revise' : 'create'}_library`); expect(JSON.parse(String(init?.body))).not.toHaveProperty('project'); expect(new Headers(init?.headers).get('Idempotency-Key')).toBe(f.command.operation_id); })).resolves.toMatchObject({ library: { id: f.library.id } });
  f.response.library.author_person = people[2].person;
  await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('Company rights receipt keeps distinct original evidence and policy predecessor', async () => {
  const previous = { ...rightsFixture(), ...companyBase(1, 'authored_rights_basis') }, { evidence_artifact: _evidence, ...definition } = previous;
  const p = { ingest_allowed: false, read_allowed: true, distribute_allowed: false, rights_basis: definition.rights_basis, rights_holder: definition.rights_holder, allowed_purpose: definition.allowed_purpose, restriction: '', valid_from: null, valid_until: null, evidence_artifact: { revision_id: evidenceArtifact.revision_id, source_sha256: evidenceArtifact.source_sha256 } };
  const command: any = { kind: 'company_set_rights', payload: { company: scope.company, document_id: previous.parent_id, expected_version: hash(previous), definition: p }, basis: { original: wrapped(previous), artifacts: [evidenceArtifact] }, operation_id: randomUUID() };
  const rights = { ...previous, ...companyBase(0, 'authored_rights_basis'), ...p, evidence_artifact: evidenceArtifact, predecessor: previous.id, revision_number: 2 };
  const response = { rights, history_id: randomUUID(), operation: operation(command.operation_id) };
  await expect(reply(response, () => documentControlNext.send(command, actor))).resolves.toMatchObject({ rights: { predecessor: previous.id } });
  response.rights.evidence_artifact = { ...evidenceArtifact, source_sha256: 'f'.repeat(64) };
  await expect(reply(response, () => documentControlNext.send(command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
for (const origin of ['Company', 'Project'] as const) test(`shared adoption and packet preserve exact ${origin} source scope`, async () => {
  const f = sharedFixture(origin), packet: any = packetFixture('adoption_request', f.subject);
  await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).resolves.toMatchObject({ adoption_request: { library_scope: f.command.payload.library_scope } });
  await expect(validateNextDocumentManifestSubject(packet, wrapped(f.subject, true), 'adoption_request')).resolves.toHaveProperty('id');
  packet.review_manifest.sources[0].rights[0].project = scope.project; packet.review_manifest.sources[0].rights[0].scope_type = 'Project';
  await expect(validateNextDocumentManifestSubject(packet, wrapped(f.subject, true), 'adoption_request')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('Company read refuses a self-consistent destination Project record', async () => {
  const f = companyLibraryFixture(); const bad: any = { ...f.revision, project: scope.project, scope_type: 'Project' };
  await expect(validateCompanyDocumentRecord(wrapped(bad, true), scope.company, 'library_revision')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('exact Unicode clause quotation and Company proposal target are accepted', async () => { const f = clauseFixture(); await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).resolves.toHaveProperty('clause_use'); });
for (const changed of ['quote', 'target', 'adoption', 'source']) test(`clause reply refuses changed ${changed}`, async () => {
  const f = clauseFixture();
  if (changed === 'quote') { f.subject.source_clause.text = 'Rewritten source'; f.subject.source_clause.text_sha256 = rawHash(f.subject.source_clause.text); }
  if (changed === 'target') f.subject.target_snapshot.record_digest = 'f'.repeat(64);
  if (changed === 'adoption') f.subject.adoption_digest = 'f'.repeat(64);
  if (changed === 'source') f.subject.artifacts = [{ ...artifact, source_sha256: 'f'.repeat(64) }];
  await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
for (const successor of [false, true]) test(`redline ${successor ? 'successor' : 'first revision'} retains original quotation and target`, async () => { const f = redlineFixture(successor); await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).resolves.toMatchObject({ redline: { revision_number: successor ? 2 : 1 } }); f.subject.predecessor = randomUUID(); await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
for (const action of ['withdraw', 'supersede'] as const) test(`lifecycle ${action} request retains exact standing and complete source closure`, async () => {
  const f = lifecycleFixture(action); await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).resolves.toHaveProperty('lifecycle_request');
  f.subject.before.original_issued.source_sha256 = 'f'.repeat(64);
  await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('standing validates hash and distinguishes supersession event from current issued state', async () => {
  const f = lifecycleFixture('supersede'), before = f.command.basis.standing, { version: _version, ...body } = before;
  const standing = { ...body, current_issued: f.subject.replacement, last_event: { id: randomUUID(), record_digest: 'a'.repeat(64) } }; const value: any = { standing: { ...standing, version: hash(standing) } };
  await expect(validateIssuedStanding(value, scope, artifact.document_id)).resolves.toHaveProperty('standing.status', 'issued');
  value.standing.status = 'superseded'; value.standing.version = hash({ ...standing, status: 'superseded' });
  await expect(validateIssuedStanding(value, scope)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
for (const kind of ['adoption_request', 'redline', 'lifecycle_request'] as const) test(`${kind} authorization request validates exact manifest and operation receipt`, async () => {
  const f = kind === 'adoption_request' ? sharedFixture() : kind === 'redline' ? redlineFixture() : lifecycleFixture();
  const subject = wrapped(f.subject, kind === 'adoption_request' ? true : null), packet: any = packetFixture(kind, f.subject), command: any = { kind: 'request_authorization', payload: scope, subject, subjectKind: kind, operation_id: randomUUID() };
  const response = { packet, operation: operation(command.operation_id) };
  await expect(reply(response, () => documentControlNext.send(command, actor))).resolves.toHaveProperty('packet.id', packet.id);
  response.operation.id = randomUUID();
  await expect(reply(response, () => documentControlNext.send(command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
function executionFixture(kind: 'adoption_request' | 'redline' | 'lifecycle_request') {
  const f = kind === 'adoption_request' ? sharedFixture() : kind === 'redline' ? redlineFixture() : lifecycleFixture('supersede'), packet: any = packetFixture(kind, f.subject);
  const decision = { id: randomUUID(), actor: { id: people[1].person, display_name: people[1].display_name }, decision: 'Grant', reason: 'Exact source reviewed', at: '2026-10-17T05:01:00Z' }; packet.decisions = [decision]; packet.state = 'Granted';
  const key = kind === 'adoption_request' ? 'adoption' : kind === 'redline' ? 'clause_application' : 'lifecycle';
  const fact: any = { ...official(kind === 'adoption_request' ? 'adopted' : kind === 'redline' ? 'approved_relationship' : 'superseded'), parent_id: f.subject.id, subject_id: f.subject.id, subject_digest: hash(f.subject), packet_id: packet.id, decision_id: decision.id, checked_by_person: decision.actor.id, effect_digest: hash(packet.review_manifest.effect), artifacts: f.subject.artifacts };
  if (kind === 'redline') for (const name of ['target', 'target_snapshot', 'original_text', 'proposed_text', 'proposed_sha256', 'target_changed']) fact[name] = (f.subject as any)[name];
  if (kind === 'lifecycle_request') Object.assign(fact, { parent_id: (f.subject as any).parent_id, document_id: (f.subject as any).parent_id, revision_number: 1, predecessor: null, action: 'supersede', reason: (f.subject as any).definition.reason, replacement: (f.subject as any).replacement, before: (f.subject as any).before });
  const command: any = { kind: 'authorization_action', payload: scope, packet, action: 'execute', reason: '', operation_id: randomUUID() };
  return { packet, fact, key, command, response: { packet: structuredClone({ ...packet, state: 'Consumed' }), effect: { [key]: fact }, operation: operation(command.operation_id) } };
}
for (const kind of ['adoption_request', 'redline', 'lifecycle_request'] as const) test(`${kind} execution validates original grant and exact append-only fact`, async () => { const f = executionFixture(kind); await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).resolves.toHaveProperty(`effect.${f.key}`); });
for (const change of ['operation', 'author', 'grant', 'manifest', 'effect', 'target', 'parent']) test(`redline execution refuses changed ${change} and remains an unknown result`, async () => {
  const f = executionFixture('redline');
  if (change === 'operation') f.response.operation.id = randomUUID();
  if (change === 'author') f.fact.author_person = people[2].person;
  if (change === 'grant') f.response.packet.decisions[0].reason = 'Rewritten review';
  if (change === 'manifest') f.response.packet.source_version = 'f'.repeat(64);
  if (change === 'effect') f.fact.effect_digest = 'f'.repeat(64);
  if (change === 'target') f.fact.target = { ...f.fact.target, locator: 'Unreviewed location' };
  if (change === 'parent') f.fact.parent_id = randomUUID();
  const error = await reply(f.response, () => documentControlNext.send(f.command, actor)).catch(error => error);
  expect(error).toMatchObject({ code: 'INVALID_CONTRACT' }); expect(isUnknownResult(error)).toBe(true);
});
test('lifecycle execution requires document parent rather than request parent', async () => { const f = executionFixture('lifecycle_request'); f.fact.parent_id = f.packet.subject.id; await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
for (const action of ['Grant', 'Reject', 'withdraw'] as const) test(`${action} binds its appended canonical decision and normalized reason`, async () => {
  const f = redlineFixture(), packet: any = packetFixture('redline', f.subject), reviewer = action === 'withdraw' ? actor : { user: people[1].user, personId: people[1].person };
  const command: any = { kind: 'authorization_action', payload: scope, packet, action, reason: '  Reviewed exact original  ', operation_id: randomUUID() };
  const decision = { id: randomUUID(), actor: { id: reviewer.personId, display_name: 'Current label' }, decision: action === 'withdraw' ? 'Withdraw' : action, reason: 'Reviewed exact original', at: '2026-10-17T05:01:00Z' };
  const response = { packet: structuredClone({ ...packet, state: action === 'withdraw' ? 'Withdrawn' : action === 'Grant' ? 'Granted' : 'Rejected', decisions: [decision] }), operation: operation(command.operation_id) };
  await expect(reply(response, () => documentControlNext.send(command, reviewer), (_url, init) => expect(JSON.parse(String(init?.body)).reason).toBe('Reviewed exact original'))).resolves.toHaveProperty('packet.decisions.0.decision', decision.decision);
  response.packet.decisions[0].actor.id = people[2].person;
  await expect(reply(response, () => documentControlNext.send(command, reviewer))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
for (const action of ['withdraw', 'supersede'] as const) test(`self-consistent ${action} request cannot hide a mismatched replacement`, async () => {
  const f = lifecycleFixture(action);
  if (action === 'withdraw') f.subject.replacement = { issue_id: randomUUID(), issue_digest: 'a'.repeat(64), revision_id: randomUUID(), source_sha256: 'b'.repeat(64) } as any;
  else f.subject.replacement = null;
  await expect(validateNextDocumentRecord(wrapped(f.subject), scope, 'lifecycle_request')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
test('replayed original receipt can be recovered with the same operation identity', async () => { const f = redlineFixture(); f.response.operation.replayed = true; await expect(reply(f.response, () => documentControlNext.send(f.command, actor))).resolves.toHaveProperty('operation.replayed', true); });
test('self-consistent record digest cannot hide altered original text hash', async () => { const f = redlineFixture(); f.subject.proposed_sha256 = 'f'.repeat(64); await expect(validateNextDocumentRecord(wrapped(f.subject), scope, 'redline')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
test('bounded Company paging rejects wrong Company, duplicate records and repeated cursor', async () => {
  const f = companyLibraryFixture(), item = wrapped(f.revision, true), page = { items: [item], next_cursor: 'cursor-2', limit: 25, count_mode: 'none', total: null };
  await expect(reply(page, () => documentControlNext.companyList(scope.company, 'library_revision', f.library.id, 'cursor-1'))).resolves.toHaveProperty('items');
  page.next_cursor = 'cursor-1'; await expect(reply(page, () => documentControlNext.companyList(scope.company, 'library_revision', f.library.id, 'cursor-1'))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
  page.next_cursor = 'cursor-2'; page.items.push(item); await expect(reply(page, () => documentControlNext.companyList(scope.company, 'library_revision'))).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
});
