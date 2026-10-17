import { randomUUID } from 'node:crypto';
import type { Page, Route } from '@playwright/test';
import { artifact, document, drawing, hash, mockEngineering, noEffects, people, scope } from './engineering-fixture';
export { document, drawing, hash, noEffects, people, scope };
export const packagePath = `/projects/${scope.project}/engineering/packages`;
export const unit = { id: '85000000-0000-4000-8000-000000000001', kind: 'uom', revision: 1, fields: { symbol: 'm', dimension: 'length', precision: 6 }, target: { doctype: 'UOM', name: 'Fixture native metre' } };
export const companyRecord = { id: '85000000-0000-4000-8000-000000000002', kind: 'company', revision: 1, fields: { name: scope.company, currency: 'USD', timezone: 'UTC' }, target: { doctype: 'Company', name: scope.company } };
export const unitManifest = (id: string, used = true) => ({ schema: 'cipher.canonical.v1', dataset_id: id, scope, records: [companyRecord, ...(used ? [unit] : [])], unit_conversions: [] });
const types = { basis: 'Cipher Design Basis Revision', calculation: 'Cipher Calculation Revision', deliverable: 'Cipher Deliverable Revision' };
const actions = { basis: 'engineering.basis.check.v1', calculation: 'engineering.calculation.check.v1', deliverable: 'engineering.deliverable.check.v1' };
export async function mockEngineeringPackages(page: Page, options: { loseFirst?: boolean; wrongFirst?: boolean } = {}) {
  const old = await mockEngineering(page); let actor = 0, first = false, denied = false;
  const records = new Map<string, Map<string, any>>(), packets = new Map<string, any>(), receipts = new Map<string, any>();
  const writes: { method: string; body: any; key?: string }[] = [];
  const put = (kind: string, value: any) => { if (!records.has(kind)) records.set(kind, new Map()); records.get(kind)!.set(value.id, structuredClone(value)); return value; }, get = (kind: string, id: string) => records.get(kind)?.get(id);
  const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[actor].person, author_user: people[actor].user, created_at: '2026-10-17T05:00:00Z', status: 'working', no_effects: noEffects });
  const envelope = (route: Route, data: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const failure = (route: Route, status: number) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'fixture_denied', message: 'Current package access is unavailable.' } } }) });
  const capabilities = ['project.read', 'document.read', 'engineering.package.read', 'engineering.package.write', 'engineering.package.check', 'approval.request', 'approval.decide', 'approval.execute'];
  const packetView = (packet: any) => ({ ...packet, actions: { can_decide: packet.review_manifest.effect.checker.person === people[actor].person && packet.requester.id !== people[actor].person && packet.state === 'Pending', can_execute: packet.requester.id === people[actor].person && packet.state === 'Granted', can_withdraw: packet.requester.id === people[actor].person && ['Pending', 'Granted'].includes(packet.state), disabled_reason: null } });
  const review = (kind: string, value: any) => {
    if (!['basis', 'calculation', 'deliverable'].includes(kind)) return null;
    const check = [...(records.get('check')?.values() || [])].find(row => row.subject_id === value.id), packet = [...packets.values()].filter(row => row.subject.id === value.id).at(-1);
    return { state: check ? 'checked' : packet?.state === 'Pending' ? 'in_check' : packet?.state === 'Granted' ? 'grant_awaiting_record' : packet?.state === 'Rejected' ? 'returned' : 'working', check_id: check?.id || null, packet_id: check?.packet_id || packet?.id || null, issue_authorized: false };
  };
  const expand = (refs: any[], kind: string) => refs.map(ref => kind === 'drawing_references' ? { ...drawing, ...ref } : kind === 'artifacts' ? { ...artifact, ...ref } : ref);
  const merge = (...groups: any[]) => { const value: any = {}; for (const key of ['source_citations', 'drawing_references', 'artifacts']) { const rows = groups.flatMap(group => group[key] || []); value[key] = [...new Map(rows.map(row => [JSON.stringify([row.revision_id, row.source_sha256, row.page, row.locator, row.excerpt_sha256]), row])).values()]; } return value; };
  const source = (body: any) => Object.fromEntries(['source_citations', 'drawing_references', 'artifacts'].map(key => [key, expand(body[key] || [], key)]));
  await page.route('**/api/method/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('.').pop()!, q = Object.fromEntries(url.searchParams), body = request.method() === 'POST' ? request.postDataJSON() : q;
    if (url.pathname.endsWith('cipher_aec.api.v1.session')) return envelope(route, { authenticated: true, user: people[actor].user, person: { id: people[actor].person, display_name: people[actor].display_name }, companies: [{ id: scope.company, name: 'Design package fixture company' }], company_scopes: [], capabilities, csrf_token: 'package-fixture-csrf', site_mode: 'synthetic' });
    if (url.pathname.endsWith('cipher_aec.api.v1.project') || url.pathname.endsWith('cipher_aec.api.v1.projects')) { const project = { id: scope.project, company: scope.company, name: 'Cedar Valley Engineering', version: '1', status: 'Open', capabilities: denied ? [] : capabilities }; return envelope(route, method === 'project' ? project : { items: [project], total: 1, limit: 50, count_mode: 'exact', next_cursor: null }); }
    if (url.pathname.endsWith('cipher_aec.api.v1.tasks')) return envelope(route, { items: [], total: 0, next_cursor: null, limit: 50 });
    const isPackage = url.pathname.includes('engineering_packages.api.'), isApproval = url.pathname.includes('cipher_aec.api.approvals.');
    if (!isPackage && !isApproval) return route.fallback();
    if (denied) return failure(route, 403);
    if (request.method() !== 'POST') {
      if (method === 'list_people') return envelope(route, { items: q.role === 'checker' ? people.slice(1) : people, limit: 25, count_mode: 'none', total: null, next_cursor: null });
      if (method === 'list_units') return envelope(route, { items: [unit], limit: 25, count_mode: 'none', total: null, next_cursor: null });
      if (method === 'get_record') { const value = get(q.kind, q.record_id); return value ? envelope(route, { record: value, record_digest: hash(value), review: review(q.kind, value) }) : failure(route, 404); }
      if (method === 'list_records') return envelope(route, { items: [...(records.get(q.kind)?.values() || [])].filter(row => !q.parent_id || row.parent_id === q.parent_id).map(record => ({ record, record_digest: hash(record), review: review(q.kind, record) })), limit: 25, next_cursor: null, count_mode: 'none', total: null });
      if (method === 'read_packet') return packets.has(q.packet_id) ? envelope(route, packetView(packets.get(q.packet_id))) : failure(route, 404);
      if (method === 'list_packets') return envelope(route, { items: [...packets.values()].map(packetView), limit: 50, count_mode: 'exact', total: packets.size, next_cursor: null });
      throw Error(`Unhandled package fixture GET ${method}`);
    }
    writes.push({ method, body: structuredClone(body), key: request.headers()['idempotency-key'] });
    if (receipts.has(body.operation_id)) return envelope(route, { ...receipts.get(body.operation_id), operation: { id: body.operation_id, status: 'succeeded', replayed: true } });
    const operation = { id: body.operation_id, status: 'succeeded', replayed: false }; let result: any;
    if (method === 'create_package' || method === 'revise_package') {
      const previous = method === 'revise_package' ? get('package', body.package_id) : undefined;
      const header = previous ? { ...previous } : { ...base(), number: 'ENG-PKG-00001', revision_number: 0, current_revision: null, basis_head: null, calculation_heads: [], deliverable_heads: [] };
      const responsible = people.find(row => row.user === body.definition.responsible_user)!, checker = people.find(row => row.user === body.definition.checker_user)!;
      const revision = { ...base(), parent_id: header.id, revision_number: header.revision_number + 1, predecessor: header.current_revision, definition: body.definition, responsible: { user: responsible.user, person: responsible.person }, checker: { user: checker.user, person: checker.person } };
      header.current_revision = revision.id; header.revision_number = revision.revision_number; put('package', header); put('package_revision', revision); result = { package: header, revision, history_id: randomUUID(), operation };
    } else if (['create_basis', 'create_calculation', 'create_deliverable'].includes(method)) {
      const kind = method.slice(7), header = { ...get('package', body.package_id) }, assignment = get('package_revision', header.current_revision), basis = get('basis', header.basis_head), previous = kind === 'basis' ? basis : body.predecessor ? get(kind, body.predecessor) : undefined;
      const common = { ...base(), parent_id: header.id, family_id: previous?.family_id || randomUUID(), revision_number: (previous?.revision_number || 0) + 1, predecessor: previous?.id || null, package_revision: assignment.id, package_digest: hash(assignment), checker: assignment.checker, definition: body.definition };
      let value: any;
      if (kind === 'basis') { value = { ...common, ...source(body), quantities: body.quantities, unit_manifest: unitManifest(common.id, body.quantities.length > 0) }; header.basis_head = value.id; }
      else if (kind === 'calculation') { value = { ...common, ...merge(basis, source(body)), basis_revision: basis.id, basis_digest: hash(basis), input_keys: body.input_keys, inputs: body.input_keys.map((key: string) => basis.quantities.find((row: any) => row.key === key)), outputs: body.outputs, unit_manifest: unitManifest(common.id), execution: { kind: 'manual-record', executed_by_cipher: false, solver_qualified: false }, issue_readiness: 'not_authorized_for_issue' }; header.calculation_heads = [...header.calculation_heads.filter((id: string) => id !== body.predecessor), value.id]; }
      else { value = { ...common, ...merge(basis, ...body.calculations.map((ref: any) => get('calculation', ref.id)), source(body)), basis_revision: basis.id, basis_digest: hash(basis), calculations: body.calculations, issue_readiness: 'not_authorized_for_issue' }; header.deliverable_heads = [...header.deliverable_heads.filter((id: string) => id !== body.predecessor), value.id]; }
      put(kind, value); put('package', header); result = { package: header, [kind]: value, history_id: randomUUID(), operation };
    } else if (method === 'request_action') {
      const kind = (Object.keys(actions) as (keyof typeof actions)[]).find(kind => actions[kind] === body.action)!; const value = get(kind, body.subject_id);
      const effect = { schema: 'cipher.engineering.package-check.v1', action: body.action, subject_kind: kind, subject_id: value.id, subject_digest: hash(value), parent_id: value.parent_id, package_revision: value.package_revision, package_digest: value.package_digest, preparer_person: value.author_person, checker: value.checker, outcome: 'checked', issue_authorized: false, sealed: false };
      const manifest = { subject: { doctype: types[kind], name: value.id, label: value.definition.title }, sources: [{ source_citations: value.source_citations, drawing_references: value.drawing_references, artifacts: value.artifacts, unit_manifest: value.unit_manifest || null }], effect, summary: { definition: value.definition, inputs: value.inputs || value.quantities || [], outputs: value.outputs || [], calculations: value.calculations || [], no_effects: noEffects, solver_executed: false, issue_authorized: false, sealed: false } };
      const packet = { id: randomUUID(), ...scope, action: body.action, subject: { id: value.id, type: types[kind], label: value.definition.title }, requester: { id: people[actor].person, display_name: people[actor].display_name }, created_at: '2026-10-17T05:00:00Z', expires_at: '2026-10-18T05:00:00Z', manifest_hash: hash(manifest), source_version: hash(value), policy: { id: 'fixture-design-check', label: 'Synthetic designated independent check', synthetic: true }, state: 'Pending', decisions: [], review_manifest: manifest, schema: 'cipher.engineering.package-approval.v1' }; packets.set(packet.id, packet); result = { packet: packetView(packet), operation };
    } else if (['decide_packet', 'withdraw_packet', 'execute_packet'].includes(method)) {
      const packet = packets.get(body.packet_id); if (!packet || packet.manifest_hash !== body.manifest_hash) return failure(route, 412); let effect: any;
      if (method === 'decide_packet') { if (!packetView(packet).actions.can_decide) return failure(route, 403); packet.state = body.decision === 'Grant' ? 'Granted' : 'Rejected'; packet.decisions.push({ id: randomUUID(), decision: body.decision, actor: { id: people[actor].person, display_name: people[actor].display_name }, at: '2026-10-17T05:15:00Z', reason: body.reason || '' }); }
      else if (method === 'withdraw_packet') packet.state = 'Withdrawn';
      else { if (!packetView(packet).actions.can_execute) return failure(route, 403); const manifest = packet.review_manifest.effect, decision = packet.decisions.find((row: any) => row.decision === 'Grant'); const check = { ...base(), status: 'checked', parent_id: manifest.parent_id, subject_kind: manifest.subject_kind, subject_id: manifest.subject_id, subject_digest: manifest.subject_digest, package_revision: manifest.package_revision, package_digest: manifest.package_digest, checker: manifest.checker, preparer_person: manifest.preparer_person, packet_id: packet.id, decision_id: decision.id, comments: decision.reason, outcome: 'checked', issue_authorized: false, sealed: false }; put('check', check); packet.state = 'Consumed'; effect = { check }; }
      result = { packet: packetView(packet), operation, ...(effect ? { effect } : {}) };
    } else throw Error(`Unhandled package fixture POST ${method}`);
    receipts.set(body.operation_id, structuredClone(result)); if (!first && options.loseFirst) { first = true; return route.abort('failed'); } if (!first && options.wrongFirst) { first = true; result.revision.definition.title = 'Wrong confirmed package'; } return envelope(route, result);
  });
  return { records, packets, writes, seed: put, setActor: (value: number) => { actor = value; old.setActor(value); }, setDenied: (value: boolean) => { denied = value; } };
}
