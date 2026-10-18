import { createHash, randomUUID } from 'node:crypto';
import type { Page } from '@playwright/test';
import { mockOfflineApp } from './field-offline-app-fixture';
import { document, expand, hash, people, scope, source } from './field-fixture';
export { document, people, scope };
export const qualityPath = (family = 'record', id?: string) => `/projects/${scope.project}/quality-safety/${family === 'incident' ? 'incidents' : 'records'}${id ? '/' + id : ''}`;
export const noEffects = Object.fromEntries(['contract_change','budget_change','procurement_change','invoice_change','financial_posting','payroll_release','award_execution','engineering_approval','regulatory_approval','hazardous_work_authority','medical_advice','compliance_certification','external_transmission'].map(key => [key, false]));
export async function mockQuality(page: Page, options: { loseFirst?: boolean; wrongFirst?: boolean; staleFirst?: boolean; unfilteredTotal?: boolean; crossFamily?: boolean; loseRightsFirst?: boolean; wrongRightsFirst?: boolean; staleRightsFirst?: boolean } = {}) {
  const app = await mockOfflineApp(page);
  const capabilities = ['quality.read','quality.write','quality.check','quality.close','safety.incident.read','safety.incident.write','safety.incident.check','safety.incident.close','safety.incident.evidence.manage','document.read','document.write','document.rights.manage','document.control.read'];
  app.projects.forEach(project => { project.capabilities = [...project.capabilities, ...capabilities]; });
  let actor = 0, denial = 0, first = true;
  const records = new Map<string, Map<string, any>>(), receipts = new Map<string, any>(), uploads = new Map<string, Buffer>(), writes: { method: string; body: any; key?: string }[] = [], reads: any[] = [];
  const put = (kind: string, value: any) => { if (!records.has(kind)) records.set(kind, new Map()); records.get(kind)!.set(value.id, structuredClone(value)); };
  const get = (kind: string, id: string) => structuredClone(records.get(kind)?.get(id));
  const child = (family: string, kind: string) => family === 'incident' ? 'incident_' + kind : kind;
  const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[actor].person, author_user: people[actor].user, created_at: '2026-10-18T14:00:00Z' });
  const privateDocuments = new Map<string, { document: any; revision: any }>(), rightsPolicies = new Map<string, any[]>(), rightsReceipts = new Map<string, any>(), rightsWrites: { body: any; key?: string }[] = [];
  let firstRights = true, rightsDenied = 0;
  const rightsNoEffects = Object.fromEntries(['commercial_change','contract_change','budget_change','schedule_change','quality_acceptance','professional_certification','external_transmission'].map(key => [key, false]));
  const currentPolicy = (id: string) => rightsPolicies.get(id)?.at(-1);
  const putPolicy = (id: string, definition: any) => {
    const previous = currentPolicy(id), artifact = { revision_id: document.current_revision, source_sha256: document.sha256, document_id: document.id, revision_number: document.revision_number, byte_length: document.byte_length, mime_type: document.mime_type, page_count: document.page_count };
    const declared = Object.fromEntries(['ingest_allowed','read_allowed','distribute_allowed','rights_holder','rights_basis','allowed_purpose','restriction','valid_from','valid_until'].map(key => [key, definition[key]]));
    const row = { ...base(), status: 'authored_rights_basis', no_effects: rightsNoEffects, parent_id: id, predecessor: previous?.id || null, revision_number: (previous?.revision_number || 0) + 1, ...declared, evidence_artifact: artifact };
    rightsPolicies.set(id, [...(rightsPolicies.get(id) || []), structuredClone(row)]); return row;
  };
  // The pre-existing non-sensitive upload-permission source has an explicit
  // ingest basis in this fixture. New private uploads have no implicit policy.
  await page.route('**/api/method/cipher_aec.documents.api.get_document*', route => {
    if (denial || rightsDenied) return route.fulfill({ status: denial || rightsDenied });
    const id = new URL(route.request().url()).searchParams.get('document_id')!, value = privateDocuments.get(id);
    return value ? route.fulfill({ json: { message: { schema: 'cipher.api.v1', data: { document: value.document, revisions: [value.revision] } } } }) : route.fulfill({ status: 404 });
  });
  await page.route('**/api/method/cipher_aec.document_control.api.*', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('.').at(-1)!;
    const body = request.method() === 'POST' ? request.postDataJSON() : Object.fromEntries(url.searchParams);
    const envelope = (data: any) => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data } } });
    const error = (status: number) => route.fulfill({ status, json: { message: { schema: 'cipher.api.v1', error: { code: 'private_sensitive_internal_reason', message: 'SENSITIVE SERVER REASON MUST NEVER BE SHOWN' } } } });
    if (denial || rightsDenied) return error(denial || rightsDenied);
    if (body.company !== scope.company || body.project !== scope.project) return error(404);
    if (method === 'list_records') return envelope({ items: (rightsPolicies.get(body.parent_id) || []).map(record => ({ record, record_digest: hash(record), library_current: null })), next_cursor: null, limit: 25, count_mode: 'none', total: null });
    if (method !== 'set_rights' || request.method() !== 'POST') throw new Error('Unexpected private-source fixture route: ' + method);
    rightsWrites.push({ body: structuredClone(body), key: request.headers()['idempotency-key'] });
    if (rightsReceipts.has(body.operation_id)) { const result = structuredClone(rightsReceipts.get(body.operation_id)); result.operation.replayed = true; return envelope(result); }
    const privateSource = privateDocuments.get(body.document_id), previous = currentPolicy(body.document_id);
    if (!privateSource) return error(404);
    if (options.staleRightsFirst && firstRights) { firstRights = false; putPolicy(body.document_id, body.definition); return error(412); }
    if (body.expected_version !== (previous ? hash(previous) : null)) return error(412);
    if (body.definition.evidence_artifact.revision_id !== document.current_revision || body.definition.evidence_artifact.source_sha256 !== document.sha256 || body.definition.evidence_artifact.revision_id === privateSource.revision.id) return error(422);
    const rights = putPolicy(body.document_id, body.definition), result = { rights, history_id: randomUUID(), operation: { id: body.operation_id, status: 'succeeded', replayed: false } };
    rightsReceipts.set(body.operation_id, structuredClone(result));
    if (firstRights && options.loseRightsFirst) { firstRights = false; return route.abort('failed'); }
    if (firstRights && options.wrongRightsFirst) { firstRights = false; result.rights = { ...result.rights, parent_id: 'OTHER-DOCUMENT' }; }
    return envelope(result);
  });
  const seed = (family = 'record') => {
    const category = family === 'incident' ? 'incident' : 'inspection';
    const header = { ...base(), category, number: family === 'incident' ? 'PRIVATE-INCIDENT-001' : 'QUALITY-001', status: 'draft', revision_number: 1, current_revision: '', last_decision: null, closed_revision: null };
    const definition = { title: family === 'incident' ? 'Restricted synthetic incident' : 'East wall inspection', local_date: '2026-10-17', location: 'East wall', description: family === 'incident' ? 'Sensitive synthetic description' : 'Measured the installed closure.', required_closure_items: [{ item_id: randomUUID(), description: 'Retain exact closure evidence' }], ...(family === 'incident' ? { restricted_account: 'Sensitive synthetic incident account', involved_people: ['Synthetic Person'], immediate_response: 'Synthetic response only', shared_evidence_revisions: [], shared_evidence_statement: '' } : {}) };
    const revision = { ...base(), category, status: 'recorded', parent_id: header.id, revision_number: 1, predecessor: null, prior_decision: null, amendment_of: null, amendment_reason: '', definition, evidence: [expand(source)], no_effects: noEffects };
    header.current_revision = revision.id; put(family, header); put(child(family, 'revision'), revision); return { header, revision };
  };
  await page.route('**/api/method/cipher_aec.documents.api.list_documents*', route => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data: { items: [document], capabilities: { antivirus: true, ocr: false, formats: ['text/plain'] } } } } }));
  await page.route('**/api/method/cipher_aec.documents.api.download_revision*', async route => {
    if (denial) return route.fulfill({ status: denial });
    const id = new URL(route.request().url()).searchParams.get('revision_id')!;
    const bytes = uploads.get(id) || Buffer.from('Field observations: east wall excavation and delivery note line 2.');
    return route.fulfill({ contentType: 'text/plain', body: bytes });
  });
  await page.route('**/api/method/cipher_aec.quality_safety.api.*', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('.').at(-1)!, write = request.method() === 'POST', body = write ? request.postDataJSON() : Object.fromEntries(url.searchParams);
    const envelope = (data: unknown) => route.fulfill({ json: { message: { schema: 'cipher.api.v1', data } } }), error = (status: number) => route.fulfill({ status, json: { message: { schema: 'cipher.api.v1', error: { code: 'private_sensitive_internal_reason', message: 'SENSITIVE SERVER REASON MUST NEVER BE SHOWN' } } } });
    if (!write) reads.push(structuredClone(body));
    if (denial) return error(denial);
    if (method === 'list_records') {
      const items = [...(records.get(options.crossFamily && body.kind === 'record' ? 'incident' : body.kind)?.values() || [])].filter(row => !body.parent_id || row.parent_id === body.parent_id).map(record => ({ record, record_digest: hash(record) }));
      return envelope({ items, next_cursor: null, count_mode: 'none', total: options.unfilteredTotal ? 888 : null, limit: 25 });
    }
    if (method === 'get_record') { const record = get(body.kind, body.record_id); return record ? envelope({ record, record_digest: hash(record) }) : error(404); }
    writes.push({ method, body: structuredClone(body), key: request.headers()['idempotency-key'] });
    if (receipts.has(body.operation_id)) { const result = structuredClone(receipts.get(body.operation_id)); result.operation.replayed = true; return envelope(result); }
    if (options.staleFirst && first) { first = false; return error(412); }
    let result: any;
    if (method === 'upload_evidence') {
      const bytes = Buffer.from(body.content_base64, 'base64'); if (bytes.length !== body.byte_length || createHash('sha256').update(bytes).digest('hex') !== body.sha256) return error(422);
      if (body.permission_evidence.some((row: any) => row.revision_id !== document.current_revision || row.source_sha256 !== document.sha256)) return error(409);
      const revision = { id: randomUUID(), revision_number: 1, filename: body.filename, mime_type: 'text/plain', byte_length: bytes.length, sha256: body.sha256, scan_status: 'clean', retrieval_status: 'available', extraction_status: 'ready', extractor_version: 'synthetic-test-text-v1', page_count: 1, extraction_warning: null };
      const doc = { ...revision, id: randomUUID(), title: body.title, current_revision: revision.id, ...scope };
      privateDocuments.set(doc.id, { document: structuredClone(doc), revision: structuredClone(revision) });
      const registration = { ...base(), document_id: doc.id, rights_basis: body.rights_basis, permission_evidence: body.permission_evidence.map(expand), classification: 'restricted_from_creation' };
      uploads.set(revision.id, bytes); result = { family: 'incident', evidence_upload: true, document: doc, revision, registration, history_id: null };
    } else if (method === 'create_record' || method === 'revise_record') {
      const old = method === 'revise_record' ? get(body.family, body.record_id) : undefined;
      if (old && hash(old) !== body.expected_version) return error(412);
      const header = old || { ...base(), category: body.category, number: body.family === 'incident' ? 'PRIVATE-INCIDENT-NEW' : 'QUALITY-NEW', status: 'draft', revision_number: 0, current_revision: null, last_decision: null, closed_revision: null };
      for (const value of body.evidence) { const privateSource = [...privateDocuments.values()].find(row => row.revision.id === value.revision_id); if (privateSource) { const policy = currentPolicy(privateSource.document.id), today = new Date().toISOString().slice(0,10); if (!policy || !policy.ingest_allowed || !policy.read_allowed || policy.valid_from && policy.valid_from > today || policy.valid_until && policy.valid_until < today) return error(409); } }
      const evidence = body.evidence.map((value: any) => { const uploaded = uploads.get(value.revision_id), privateSource = [...privateDocuments.values()].find(row => row.revision.id === value.revision_id); return uploaded ? { ...value, document_id: privateSource!.document.id, revision_number: 1, byte_length: uploaded.length, mime_type: 'text/plain', page_count: 1 } : expand(value); });
      const revision = { ...base(), status: 'recorded', category: header.category, parent_id: header.id, revision_number: header.revision_number + 1, predecessor: header.current_revision, prior_decision: header.last_decision, amendment_of: header.closed_revision, amendment_reason: body.amendment_reason || '', definition: body.definition, evidence, no_effects: noEffects };
      Object.assign(header, { revision_number: revision.revision_number, current_revision: revision.id, status: 'draft', last_decision: null }); put(body.family, header); put(child(body.family, 'revision'), revision); result = { family: body.family, header, revision, history_id: body.family === 'incident' ? null : randomUUID() };
    } else if (method === 'transition') {
      const header = get(body.family, body.record_id), revision = get(child(body.family, 'revision'), header.current_revision);
      if (hash(header) !== body.expected_version) return error(412);
      const previous = header.last_decision && get(child(body.family, 'decision'), header.last_decision);
      if (body.action !== 'submit' && people[actor].person === revision.author_person || body.action === 'close' && people[actor].person === previous?.author_person) return error(403);
      const target = { submit: 'submitted', check: 'checked', return: 'returned', close: 'closed' }[body.action as 'submit'];
      const decision = { ...base(), status: 'recorded', category: header.category, parent_id: header.id, source_revision: revision.id, source_digest: hash(revision), predecessor: header.last_decision, action: body.action, from_status: header.status, to_status: target, comment: body.comment, evidence: body.evidence.map(expand), closure: body.closure.map((row: any) => ({ ...row, evidence: row.evidence.map(expand) })), checked_by_person: body.action === 'close' ? previous.author_person : null, no_effects: noEffects };
      Object.assign(header, { status: target, last_decision: decision.id, closed_revision: body.action === 'close' ? revision.id : header.closed_revision }); put(body.family, header); put(child(body.family, 'decision'), decision); result = { family: body.family, header, revision, decision, history_id: body.family === 'incident' ? null : randomUUID() };
    } else throw new Error(`Unhandled Quality fixture: ${method}`);
    result.operation = { id: body.operation_id, status: 'succeeded', replayed: false }; receipts.set(body.operation_id, structuredClone(result));
    if (first && options.loseFirst) { first = false; return route.abort('failed'); }
    if (first && options.wrongFirst) { first = false; result = structuredClone(result); result.header.company = 'OTHER-COMPANY'; }
    return envelope(result);
  });
  return { ...app, records, receipts, writes, reads, uploads, privateDocuments, rightsPolicies, rightsWrites, rightsReceipts, putPolicy, currentPolicy, seed, get, put, setRightsDenied: (status: number) => { rightsDenied = status; }, setDenied: (status: number) => { denial = status; }, setActor: (index: number) => { actor = index; app.setActor(index); } };
}
