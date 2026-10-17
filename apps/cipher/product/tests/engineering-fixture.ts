import { createHash, randomUUID } from 'node:crypto';
import type { Page, Route } from '@playwright/test';
import { vectorPdf } from './pdf-fixture';
export const scope = { company: 'ENG-FIXTURE', project: 'ENG-PROJECT' };
export const engineeringPath = `/projects/${scope.project}/engineering`;
export const people = [
  { user: 'fixture.author@example.invalid', person: 'ENG-PERSON-A', display_name: 'Alex Author' },
  { user: 'fixture.reviewer@example.invalid', person: 'ENG-PERSON-B', display_name: 'Casey Reviewer' },
  { user: 'fixture.controller@example.invalid', person: 'ENG-PERSON-C', display_name: 'Jordan Controller' },
];
export const noEffects = { commercial_change: false, contract_change: false, budget_change: false, schedule_change: false, quality_acceptance: false, professional_certification: false, external_transmission: false };
const canonical = (v: any): string => Array.isArray(v) ? '[' + v.map(canonical).join(',') + ']' : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}' : JSON.stringify(v);
export const hash = (v: unknown) => createHash('sha256').update(canonical(v)).digest('hex');
const bytes = vectorPdf();
export const document = { id: randomUUID(), title: 'Synthetic structural detail S-201', ...scope, current_revision: randomUUID(), revision_number: 1, filename: 's201.pdf', mime_type: 'application/pdf', byte_length: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), scan_status: 'not_scanned', extraction_status: 'unavailable', page_count: 1 };
export const drawingInput = { revision_id: document.current_revision, source_sha256: document.sha256, page: 1, locator: 'Grid B/4, detail 3' };
export const drawing = { ...drawingInput, document_id: document.id, revision_number: 1, byte_length: document.byte_length, mime_type: 'application/pdf', page_count: 1 };
export const artifact = { revision_id: document.current_revision, source_sha256: document.sha256, document_id: document.id, revision_number: 1, byte_length: document.byte_length, mime_type: 'application/pdf', page_count: 1 };
export const questionDefinition = { subject: 'Clarify landing connection', question: 'Confirm the connection detail at the east stair landing.', responsible_users: [], due_date: '2026-11-02', location: 'East stair', contract_citation_ids: [] };
export function rfiFixture(operationId = randomUUID()) {
  const base = { ...scope, scope_type: 'Project', author_person: people[0].person, author_user: people[0].user, created_at: '2026-10-17T05:00:00Z' };
  const rfi = { ...base, id: randomUUID(), status: 'open', number: 'ENG-RFI-00001', revision_number: 1, current_revision: randomUUID(), response_head: null, official_response: null };
  const revision = { ...base, id: rfi.current_revision, status: 'working', parent_id: rfi.id, revision_number: 1, predecessor: null, source_citations: [], artifacts: [], drawing_references: [drawing], no_effects: noEffects, definition: questionDefinition, responsible_people: [] };
  return { input: { ...scope, operation_id: operationId, definition: questionDefinition, source_citations: [], drawing_references: [drawingInput] }, response: { rfi, revision, history_id: randomUUID(), operation: { id: operationId, status: 'succeeded', replayed: false } } };
}
// Browser-only contract fixture. These in-memory endpoints are not native persistence evidence.
export async function mockEngineering(page: Page, options: { loseFirstReply?: boolean; wrongFirstReply?: boolean; denied?: boolean } = {}) {
  let actorIndex = 0, lost = false, denied = Boolean(options.denied);
  const records = new Map<string, Map<string, any>>(); const packets = new Map<string, any>(); const receipts = new Map<string, any>();
  const writes: { method: string; body: any; key?: string; actor: number }[] = []; const reads: string[] = [];
  const get = (kind: string, id: string) => records.get(kind)?.get(id);
  const put = (kind: string, record: any) => { if (!records.has(kind)) records.set(kind, new Map()); records.get(kind)!.set(record.id, structuredClone(record)); return record; };
  const base = (status = 'working') => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[actorIndex].person, author_user: people[actorIndex].user, created_at: '2026-10-17T05:00:00Z', status });
  const operation = (body: any) => ({ id: body.operation_id, status: 'succeeded', replayed: false });
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const failure = (route: Route, status: number, message: string) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: `fixture_${status}`, message } } }) });
  const packetView = (packet: any) => ({ ...packet, actions: { can_decide: !packet.authors.includes(people[actorIndex].person) && packet.state === 'Pending', can_execute: packet.requester.id === people[actorIndex].person && packet.state === 'Granted', can_withdraw: packet.requester.id === people[actorIndex].person && ['Pending', 'Granted'].includes(packet.state), disabled_reason: null }, authors: undefined });
  const cleanPacket = (packet: any) => JSON.parse(JSON.stringify(packetView(packet)));
  const capabilities = ['project.read', 'document.read', 'engineering.read', 'engineering.write', 'engineering.distribute', 'approval.request', 'approval.read', 'approval.decide', 'approval.execute'];
  await page.route('**/api/method/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('.').pop()!, q = Object.fromEntries(url.searchParams), body: any = request.method() === 'POST' ? request.postDataJSON() : q;
    if (request.method() === 'POST') writes.push({ method, body: structuredClone(body), key: request.headers()['idempotency-key'], actor: actorIndex }); else reads.push(method);
    if (method === 'session') return envelope(route, { authenticated: true, user: people[actorIndex].user, person: { id: people[actorIndex].person, display_name: people[actorIndex].display_name }, companies: [{ id: scope.company, name: 'Engineering fixture company' }], company_scopes: [], capabilities, csrf_token: 'engineering-fixture-csrf', site_mode: 'synthetic' });
    const project = { id: scope.project, company: scope.company, name: 'Cedar Valley Engineering', version: '1', status: 'Open', capabilities: denied ? [] : capabilities };
    if (method === 'projects') return envelope(route, { items: [project], total: 1, limit: 50, count_mode: 'exact', next_cursor: null });
    if (method === 'project') return envelope(route, project);
    if (method === 'connection_status') return envelope(route, { available: false });
    if (method === 'list_documents') return envelope(route, { items: [document] });
    if (method === 'download_revision') return route.fulfill({ contentType: 'application/pdf', body: bytes });
    if (method === 'preview_revision') return failure(route, 422, 'This vector PDF has no extracted text.');
    if (denied && url.pathname.includes('engineering.')) return failure(route, 403, 'Engineering access is unavailable.');
    if (method === 'list_people') return envelope(route, { items: people, limit: 25, count_mode: 'none', next_cursor: null, total: null });
    if (method === 'get_record') { const record = get(q.kind, q.record_id); return record ? envelope(route, { record, record_digest: hash(record) }) : failure(route, 404, 'Record unavailable.'); }
    if (method === 'list_records') return envelope(route, { items: [...(records.get(q.kind)?.values() || [])].filter(row => (!q.parent_id || row.parent_id === q.parent_id) && (!q.subject_id || row.subject_id === q.subject_id)).map(record => ({ record, record_digest: hash(record) })), limit: 25, next_cursor: null, count_mode: 'none', total: null });
    if (method === 'list_packets') return envelope(route, { items: [...packets.values()].map(cleanPacket), total: packets.size, limit: 50, count_mode: 'exact', next_cursor: null });
    if (method === 'read_packet') return packets.has(q.packet_id) ? envelope(route, cleanPacket(packets.get(q.packet_id))) : failure(route, 404, 'Packet unavailable.');
    if (request.method() !== 'POST') throw Error(`Unhandled engineering fixture GET ${method}`);
    if (receipts.has(body.operation_id)) return envelope(route, { ...receipts.get(body.operation_id), operation: { ...receipts.get(body.operation_id).operation, replayed: true } });
    let result: any;
    const revision = (parent: any, definition: any, number: number, predecessor: string | null, extras: any = {}) => ({ ...base(), parent_id: parent.id, revision_number: number, predecessor, definition, source_citations: [], artifacts: [], drawing_references: [], no_effects: noEffects, ...extras });
    if (method === 'create_rfi' || method === 'revise_rfi') {
      const old = method === 'revise_rfi' ? get('rfi', body.rfi_id) : undefined;
      if (old && hash(old) !== body.expected_version) return failure(route, 412, 'Question changed.');
      const rfi = old ? { ...old } : { ...base('open'), number: 'ENG-RFI-00001', revision_number: 0, current_revision: null, response_head: null, official_response: null };
      const rev = revision(rfi, body.definition, rfi.revision_number + 1, rfi.current_revision, { drawing_references: body.drawing_references.map((row: any) => ({ ...drawing, ...row })), responsible_people: body.definition.responsible_users.map((user: string) => { const p = people.find(p => p.user === user)!; return { user, person: p.person }; }) });
      Object.assign(rfi, { revision_number: rev.revision_number, current_revision: rev.id, response_head: null, official_response: null }); put('rfi', rfi); put('rfi_revision', rev); result = { rfi, revision: rev, history_id: randomUUID(), operation: operation(body) };
    } else if (method === 'create_submittal' || method === 'revise_submission') {
      const old = method === 'revise_submission' ? get('submittal', body.submittal_id) : undefined;
      if (old && hash(old) !== body.expected_version) return failure(route, 412, 'Submission changed.');
      const submittal = old ? { ...old } : { ...base('open'), number: 'ENG-SUB-00001', revision_number: 0, current_submission: null, disposition_head: null, official_disposition: null };
      const reviewer = people.find(person => person.user === body.definition.reviewer_user)!;
      const submission = revision(submittal, body.definition, submittal.revision_number + 1, submittal.current_submission, { artifacts: [artifact], reviewer: { user: reviewer.user, person: reviewer.person } });
      Object.assign(submittal, { revision_number: submission.revision_number, current_submission: submission.id, disposition_head: null, official_disposition: null }); put('submittal', submittal); put('submission', submission); result = { submittal, submission, history_id: randomUUID(), operation: operation(body) };
    } else if (method === 'create_response' || method === 'create_disposition') {
      const response = method === 'create_response', parentKind = response ? 'rfi' : 'submittal', kind = response ? 'response' : 'disposition';
      const parent = { ...get(parentKind, body[response ? 'rfi_id' : 'submittal_id']) }, source = get(response ? 'rfi_revision' : 'submission', body.source_revision);
      if (hash(parent) !== body.expected_version) return failure(route, 412, 'Parent changed.');
      const record = revision(parent, body.definition, body.predecessor ? get(kind, body.predecessor).revision_number + 1 : 1, body.predecessor, { source_revision: source.id, source_digest: hash(source) });
      parent[response ? 'response_head' : 'disposition_head'] = record.id; put(parentKind, parent); put(kind, record); result = { [parentKind]: parent, [kind]: record, history_id: randomUUID(), operation: operation(body) };
    } else if (method === 'create_transmittal') {
      const official = get(body.subject_kind, body.subject_id), response = body.subject_kind === 'official_response', draft = get(response ? 'response' : 'disposition', official.subject_id), original = get(response ? 'rfi_revision' : 'submission', draft.source_revision);
      const transmittal = { ...base('awaiting_independent_authorization'), subject: { kind: body.subject_kind, id: body.subject_id }, subject_digest: body.subject_digest, recipients: body.recipients.map((user: string) => ({ user, person: people.find(person => person.user === user)!.person })), purpose: body.purpose, required_response: body.required_response, channel: 'internal', source_citations: original.source_citations, artifacts: original.artifacts.length ? original.artifacts : [artifact], drawing_references: original.drawing_references, no_effects: noEffects };
      const { subject, subject_digest, artifacts, source_citations, drawing_references, recipients, purpose, required_response } = transmittal;
      const record = { ...transmittal, package_digest: hash({ schema: 'cipher.engineering.package.v1', subject, subject_digest, artifacts, source_citations, drawing_references, recipients, purpose, required_response, channel: 'internal' }) }; put('transmittal', record); result = { transmittal: record, history_id: randomUUID(), operation: operation(body) };
    } else if (method === 'request_action') {
      const kind = body.action === 'engineering.rfi.authorize.v1' ? 'response' : body.action === 'engineering.submittal.authorize.v1' ? 'disposition' : 'transmittal', value = get(kind, body.subject_id), type = kind === 'response' ? 'Cipher RFI Response Revision' : kind === 'disposition' ? 'Cipher Submittal Disposition Revision' : 'Cipher Engineering Transmittal';
      const original = kind === 'transmittal' ? value : get(kind === 'response' ? 'rfi_revision' : 'submission', value.source_revision);
      const authors = kind === 'disposition' ? [value.author_person, original.author_person] : [value.author_person];
      const effect = { schema: 'cipher.engineering.authorization.v1', action: body.action, subject_kind: kind, subject_id: value.id, subject_digest: hash(value), ...(kind === 'transmittal' ? { package_digest: value.package_digest, recipients: value.recipients, channel: 'internal' } : { parent_id: value.parent_id, source_revision: value.source_revision, source_digest: value.source_digest, author_people: [...new Set(authors)].sort() }) };
      const manifest = { subject: { doctype: type, name: value.id, label: `Engineering ${kind}` }, sources: [{ source_citations: original.source_citations, artifacts: original.artifacts, drawing_references: original.drawing_references }], effect, summary: { schema: 'cipher.engineering.review.v1', definition: value.definition || null, purpose: value.purpose || null, no_effects: noEffects, professional_seal: false, external_delivery: false } };
      const packet = { id: randomUUID(), ...scope, action: body.action, subject: { id: value.id, type, label: manifest.subject.label }, requester: { id: people[actorIndex].person, display_name: people[actorIndex].display_name }, created_at: '2026-10-17T05:00:00Z', expires_at: '2026-10-18T05:00:00Z', manifest_hash: hash(manifest), source_version: hash(value), policy: { id: 'fixture-engineering-policy', label: 'Synthetic independent engineering policy', synthetic: true }, state: 'Pending', decisions: [], review_manifest: manifest, schema: 'cipher.engineering.approval.v1', authors };
      packets.set(packet.id, packet); result = { packet: cleanPacket(packet), operation: operation(body) };
    } else if (['decide_packet', 'execute_packet', 'withdraw_packet'].includes(method)) {
      const packet = packets.get(body.packet_id); if (!packet || packet.manifest_hash !== body.manifest_hash) return failure(route, 412, 'Packet changed.');
      if (method === 'decide_packet') { if (!packetView(packet).actions.can_decide) return failure(route, 403, 'Independent person required.'); packet.state = body.decision === 'Grant' ? 'Granted' : 'Rejected'; packet.decisions.push({ id: randomUUID(), decision: body.decision, actor: { id: people[actorIndex].person, display_name: people[actorIndex].display_name }, at: '2026-10-17T05:15:00Z', reason: body.reason || '' }); }
      let effect: any;
      if (method === 'execute_packet') {
        if (!packetView(packet).actions.can_execute) return failure(route, 403, 'Executor unavailable.');
        const e = packet.review_manifest.effect, decision = packet.decisions.find((decision: any) => decision.decision === 'Grant'), value = get(e.subject_kind, e.subject_id), distribution = e.subject_kind === 'transmittal', kind = distribution ? 'distribution' : e.subject_kind === 'response' ? 'official_response' : 'official_disposition';
        const fact = { ...base(distribution ? 'recorded_internally' : 'official'), subject_id: value.id, subject_digest: hash(value), packet_id: packet.id, decision_id: decision.id, checked_by_person: decision.actor.id, no_effects: noEffects, authority: 'internal-technical-only', ...(distribution ? { package_digest: value.package_digest, recipients: value.recipients, channel: 'internal', external_delivery: false } : { parent_id: value.parent_id, source_revision: value.source_revision, source_digest: value.source_digest }) };
        put(kind, fact); if (!distribution) { const parentKind = kind === 'official_response' ? 'rfi' : 'submittal', parent = { ...get(parentKind, value.parent_id), [kind]: fact.id }; put(parentKind, parent); }
        packet.state = 'Consumed'; effect = { [kind]: fact };
      }
      if (method === 'withdraw_packet') packet.state = 'Withdrawn';
      result = { packet: cleanPacket(packet), operation: operation(body), ...(effect ? { effect } : {}) };
    } else if (method === 'close_rfi') { const rfi = { ...get('rfi', body.rfi_id), status: 'closed', closure: { official_response: body.official_response, reason: body.reason, person: people[actorIndex].person, at: '2026-10-17T05:30:00Z' } }; put('rfi', rfi); result = { rfi, history_id: randomUUID(), operation: operation(body) }; }
    else throw Error(`Unhandled engineering fixture POST ${method}`);
    receipts.set(body.operation_id, structuredClone(result));
    if (!lost && options.loseFirstReply) { lost = true; return route.abort('failed'); }
    if (!lost && options.wrongFirstReply) { lost = true; result.revision.definition.subject = 'Wrong receipt subject'; }
    return envelope(route, result);
  });
  return { writes, reads, records, packets, setActor: (index: number) => { actorIndex = index; }, setDenied: (value: boolean) => { denied = value; }, seed: (kind: string, record: any) => put(kind, record) };
}
