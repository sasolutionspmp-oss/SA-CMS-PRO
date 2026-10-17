import { createHash, randomUUID } from 'node:crypto';
import type { Page, Route } from '@playwright/test';
export const scope = { company: 'Fixture Company', project: 'FIELD-PROJECT' };
export const people = [{ user: 'author@field.test', person: 'FIELD-AUTHOR' }, { user: 'reviewer@field.test', person: 'FIELD-REVIEWER' }, { user: 'acceptor@field.test', person: 'FIELD-ACCEPTOR' }, { user: 'alias@field.test', person: 'FIELD-AUTHOR' }];
export const capabilities = ['field.read', 'field.write', 'field.review', 'field.accept', 'field.acknowledge'];
const canonical = (value: any): string => Array.isArray(value) ? '[' + value.map(canonical).join(',') + ']' : value && typeof value === 'object' ? '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}' : JSON.stringify(value);
export const hash = (value: any) => createHash('sha256').update(canonical(value)).digest('hex');
export const noEffects = Object.fromEntries(['contract_change', 'budget_change', 'procurement_change', 'invoice_change', 'financial_posting', 'payroll_release', 'quality_certification', 'external_transmission'].map(key => [key, false]));
const textBytes = Buffer.from('Field observations: east wall excavation and delivery note line 2.');
const imageBytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5l8AAAAASUVORK5CYII=', 'base64');
export const document = { id: 'field-observations', ...scope, title: 'Field observations', current_revision: 'field-source-r1', revision_number: 1, filename: 'observations.txt', mime_type: 'text/plain', byte_length: textBytes.length, sha256: createHash('sha256').update(textBytes).digest('hex'), scan_status: 'clean', extraction_status: 'ready', page_count: 1 };
export const photoDocument = { ...document, id: 'field-photo', title: 'East wall photo', current_revision: 'photo-source-r1', filename: 'east-wall.png', mime_type: 'image/png', byte_length: imageBytes.length, sha256: createHash('sha256').update(imageBytes).digest('hex') };
export const source = { revision_id: document.current_revision, source_sha256: document.sha256, page: 1, locator: 'East wall observation' };
export const expand = (value: any) => { const row = value.revision_id.startsWith('photo-') ? photoDocument : document; return { ...value, document_id: row.id, revision_number: row.revision_number, byte_length: row.byte_length, mime_type: row.mime_type, page_count: row.page_count }; };
export const dailyDefinition = { local_date: '2026-10-17', superintendent_user: people[0].user, weather: '', weather_sources: [], crews: ['Civil crew · 3 people'], activities: ['Excavated the east wall trench.'], delays: [], visitors: [] };
export function seedDaily(actor = 0, quantity = true) {
  const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[actor].person, author_user: people[actor].user, created_at: '2026-10-17T14:00:00Z', status: 'recorded' });
  const header = { ...base(), number: 'DAILY-FIXTURE-0001', status: 'draft', revision_number: 1, current_revision: '', last_decision: null, accepted_revision: null };
  const revision = { ...base(), parent_id: header.id, revision_number: 1, predecessor: null, prior_decision: null, amendment_of: null, amendment_reason: '', definition: structuredClone(dailyDefinition), superintendent: { user: people[0].user, person: people[0].person }, photos: [], quantity_ids: [] as string[], no_effects: noEffects };
  header.current_revision = revision.id;
  const q = { ...base(), parent_id: header.id, source_revision: revision.id, revision_number: 1, original_event_id: randomUUID(), supersedes_event_id: null, definition: {} as any, no_effects: noEffects };
  q.definition = { original_event_id: q.original_event_id, supersedes_event_id: null, kind: 'installed', description: 'East wall trench', wbs_code: 'CIVIL-01', cost_code: 'EXC', quantity: '12.000001', unit: 'linear feet', location: 'East wall', sources: [expand(source)] };
  if (quantity) revision.quantity_ids.push(q.id);
  return { header, revision, quantities: quantity ? [q] : [] };
}
export async function mockField(page: Page, options: { loseFirst?: boolean; wrongFirst?: boolean; staleFirst?: boolean; seed?: boolean } = {}) {
  let actor = 0, denied = false, readCaps = [...capabilities], first = true;
  const documents = [structuredClone(document), structuredClone(photoDocument)], records = new Map<string, Map<string, any>>(), receipts = new Map<string, any>();
  const writes: { method: string; body: any; key: string | undefined }[] = [];
  const put = (kind: string, value: any) => { if (!records.has(kind)) records.set(kind, new Map()); records.get(kind)!.set(value.id, structuredClone(value)); }, get = (kind: string, id: string) => structuredClone(records.get(kind)?.get(id)), item = (record: any) => ({ record, record_digest: hash(record) });
  if (options.seed) { const seed = seedDaily(); put('daily', seed.header); put('daily_revision', seed.revision); for (const q of seed.quantities) put('quantity', q); }
  await page.route('**/api/method/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('.').at(-1)!, body = request.method() === 'POST' ? request.postDataJSON() : Object.fromEntries(url.searchParams), write = request.method() === 'POST';
    const envelope = (data: any) => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data } } }), failure = (status: number, code = status === 412 ? 'stale_field_record' : 'permission_denied') => route.fulfill({ status, json: { message: { schema: 'cipher.api.v1', error: { code, message: status === 412 ? 'Review the current field version.' : 'Current source or Field access is denied.' } } } });
    if (method === 'session') return envelope({ user: people[actor].user, person: { id: people[actor].person, display_name: people[actor].user }, csrf_token: 'fixture-csrf', company_scopes: [{ company: scope.company, capabilities: [] }] });
    if (method === 'project') return envelope({ id: scope.project, company: scope.company, name: 'Field project', status: 'Open', capabilities: readCaps });
    if (denied) return failure(403);
    if (method === 'list_documents') return envelope({ items: documents, capabilities: { antivirus: true, ocr: false, formats: ['text/plain', 'image/png'] } });
    if (method === 'download_revision') { const photo = body.revision_id.startsWith('photo-'); return route.fulfill({ contentType: photo ? 'image/png' : 'text/plain', body: photo ? imageBytes : textBytes }); }
    if (method === 'get_record') { const record = get(body.kind, body.record_id); return record ? envelope(item(record)) : failure(404); }
    if (method === 'list_records') { const items = [...(records.get(body.kind)?.values() || [])].filter(row => !body.parent_id || row.parent_id === body.parent_id).reverse().map(item); return envelope({ items, next_cursor: null, count_mode: 'none', total: null, limit: 25 }); }
    if (!write) throw Error(`Unhandled field fixture read: ${method}`);
    writes.push({ method, body: structuredClone(body), key: request.headers()['idempotency-key'] });
    if (options.staleFirst && first) { first = false; return failure(412); }
    if (receipts.has(body.operation_id)) { const result = structuredClone(receipts.get(body.operation_id)); result.operation.replayed = true; return envelope(result); }
    const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[actor].person, author_user: people[actor].user, created_at: '2026-10-17T14:00:00Z', status: 'recorded' });
    let result: any;
    if (method === 'create_record' || method === 'revise_record') {
      const old = method === 'revise_record' ? get(body.family, body.record_id) : undefined;
      if (old && hash(old) !== body.expected_version) return failure(412);
      const header = old || { ...base(), number: `${body.family.toUpperCase()}-FIXTURE-${records.get(body.family)?.size || 0}`, status: 'draft', revision_number: 0, current_revision: null, last_decision: null, accepted_revision: null };
      const definition = structuredClone(body.definition); if (body.family === 'daily') definition.weather_sources = definition.weather_sources.map(expand); else definition.lines = definition.lines.map((line: any) => ({ ...line, sources: line.sources.map(expand) }));
      const revision: any = { ...base(), parent_id: header.id, revision_number: header.revision_number + 1, predecessor: header.current_revision, prior_decision: header.last_decision, amendment_of: header.accepted_revision, amendment_reason: body.amendment_reason || '', definition, photos: body.photos.map((photo: any) => ({ ...photo, source: expand(photo.source) })), no_effects: noEffects };
      const quantities = body.quantities.map((row: any) => ({ ...base(), parent_id: header.id, source_revision: revision.id, revision_number: revision.revision_number, original_event_id: row.original_event_id, supersedes_event_id: row.supersedes_event_id, definition: { ...row, sources: row.sources.map(expand) }, no_effects: noEffects }));
      if (body.family === 'daily') { revision.superintendent = { user: body.definition.superintendent_user, person: people.find(row => row.user === body.definition.superintendent_user)?.person || 'SUPERINTENDENT' }; revision.quantity_ids = quantities.map((row: any) => row.id); }
      Object.assign(header, { current_revision: revision.id, revision_number: revision.revision_number, status: 'draft', last_decision: null }); put(body.family, header); put(body.family + '_revision', revision); quantities.forEach((row: any) => put('quantity', row)); result = { family: body.family, header, revision, quantities };
    } else if (method === 'transition') {
      const header = get(body.family, body.record_id), revision = get(body.family + '_revision', header.current_revision);
      if (hash(header) !== body.expected_version) return failure(412);
      if (body.action !== 'submit' && [revision.author_person, revision.superintendent?.person].includes(people[actor].person)) return failure(403);
      const target = { submit: 'submitted', review: 'reviewed', return: 'returned', accept: 'accepted', acknowledge: 'acknowledged' }[body.action as 'submit'];
      const decision = { ...base(), parent_id: header.id, source_revision: revision.id, source_digest: hash(revision), predecessor: header.last_decision, action: body.action, from_status: header.status, to_status: target, comment: body.comment, acknowledged_by: body.acknowledged_by || '', evidence: body.evidence.map(expand), no_effects: noEffects };
      Object.assign(header, { status: target, last_decision: decision.id, ...(body.action === 'accept' ? { accepted_revision: revision.id } : {}) }); put('decision', decision); put(body.family, header); result = { family: body.family, header, revision, decision };
    } else throw Error(`Unhandled field fixture write: ${method}`);
    result = { ...result, history_id: randomUUID(), operation: { id: body.operation_id, status: 'succeeded', replayed: false } }; receipts.set(body.operation_id, structuredClone(result));
    if (first && options.loseFirst) { first = false; return route.abort('failed'); } if (first && options.wrongFirst) { first = false; result = structuredClone(result); result.header.current_revision = randomUUID(); }
    return envelope(result);
  });
  return { records, writes, get, put, item, documents, receipts, setActor: (index: number) => { actor = index; }, setDenied: (value: boolean) => { denied = value; }, setCapabilities: (value: string[]) => { readCaps = value; } };
}
