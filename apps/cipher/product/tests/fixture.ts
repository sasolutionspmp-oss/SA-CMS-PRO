import type { ApprovalPacket } from '../src/api/types';
import type { Page, Route } from '@playwright/test';
import { expect } from '@playwright/test';

// Contract-test data only. The application never imports fixtures or falls back to them.
export const company = 'TEST-AEC';
export const projects = [
  { id: 'TEST-PRJ-001', name: 'Cedar Valley Water Reuse', company, status: 'Open', version: '1', expected_start_date: '2026-06-15', expected_end_date: '2027-04-30' },
  { id: 'TEST-PRJ-002', name: 'North River Pump Station', company, status: 'Open', version: '1', expected_start_date: '2026-08-03', expected_end_date: '2027-02-19' },
  { id: 'TEST-PRJ-003', name: 'Airport Utility Corridor', company, status: 'Completed', version: '1', expected_start_date: '2025-11-10', expected_end_date: '2026-09-30' },
];
const citation = { document_id: 'TEST-DOC-001', revision_id: 'TEST-REV-001', document_title: 'Site coordination requirements', revision_number: 1, page: 1, page_label: 'Page 1', excerpt: 'Coordinate the temporary bypass plan before mobilization.' };
export const sourceText = 'SITE COORDINATION REQUIREMENTS\n\nCoordinate the temporary bypass plan before mobilization.\n\nSubmit a site access plan for review.\n\n<script>window.fixtureInjection=true</script>';

export async function mockWorkspace(page: Page, options: { model?: boolean; loseFirstTaskResponse?: boolean; staleTask?: boolean; login?: boolean; pagination?: boolean; approvals?: boolean; loseFirstApprovalResponse?: boolean; staleApproval?: boolean; documentFailure?: 403 | 404 | 503; estimating?: boolean; domainApproval?: boolean } = {}) {
  let authenticated = !options.login;
  let version = '1';
  let currentStatus = 'Open';
  let reviewer = false;
  let approvalResponseLost = false;
  let documentsRecovered = false;
  const packets: ApprovalPacket[] = [];
  const actor = () => reviewer ? { id: 'TEST-PERSON-REVIEWER', display_name: 'Casey Reviewer' } : { id: 'TEST-PERSON-001', display_name: 'Alex Morgan' };
  const approvals = (packet: ApprovalPacket): ApprovalPacket => packet.action !== 'project.status.change.v1' ? packet : ({ ...packet, actions: { can_decide: reviewer && packet.state === 'Pending', can_execute: !reviewer && packet.state === 'Granted', can_withdraw: !reviewer && packet.state === 'Pending', disabled_reason: packet.state === 'Pending' && !reviewer ? 'A different person must review this request.' : packet.state === 'Granted' && reviewer ? 'A different person must execute this grant.' : null } });
  if (options.domainApproval) packets.push({ id: 'TEST-DOMAIN-001', company, project: projects[0].id, action: 'calibration.verify.v1', subject: { id: 'TEST-CALIBRATION', type: 'Cipher Calibration', label: 'Source page calibration' }, requester: { id: 'TEST-OTHER-PERSON', display_name: 'Other requester' }, created_at: '2026-10-15T12:00:00Z', expires_at: '2030-10-15T12:00:00Z', manifest_hash: 'e'.repeat(64), source_version: 'opaque-domain-version', policy: { id: 'TEST-DOMAIN-POLICY', label: 'Independent scale review', synthetic: true }, state: 'Pending', decisions: [], actions: { can_decide: false, can_execute: false, can_withdraw: false, disabled_reason: 'Independent domain review is required.' }, review_manifest: { subject: { doctype: 'Cipher Calibration', name: 'TEST-CALIBRATION', label: 'Source page calibration' }, effect: { status: 'Verified', source_revision: 'TEST-REV-001' }, summary: { basis: 'Scale verification', exact_length: '200.00' }, sources: [{ revision_id: 'TEST-REV-001', sha256: 'f'.repeat(64) }] } });
  const capabilities = ['project.read', 'task.create', 'document.read', 'document.write', 'ricky.run', ...(options.approvals ? ['approval.request', 'approval.decide', 'approval.execute'] : []), ...(options.estimating ? ['estimate.read', 'estimate.write'] : [])];
  const tasks = [{ id: 'TEST-TASK-001', subject: 'Review temporary works requirements', description: 'Coordinate site access and temporary bypass requirements.', status: 'Open', project: projects[0].id, version: '1' }];
  const documents = [{ id: 'TEST-DOC-001', title: 'Site coordination requirements', company, project: projects[0].id, current_revision: 'TEST-REV-001', revision_number: 1, filename: 'site-coordination.txt', mime_type: 'text/plain', byte_length: sourceText.length, sha256: 'a'.repeat(64), scan_status: 'not_scanned', extraction_status: 'ready', page_count: 1 }];
  const writes: { method: string; body: Record<string, unknown>; key: string | undefined }[] = [];
  let firstLost = false;
  const receipts = new Map<string, unknown>();
  const envelope = async (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data, request_id: 'test-request', meta: { api_version: 'v1', server_time: '2026-10-15T12:00:00Z', request_id: 'test-request' } } }) });
  await page.route('**/api/method/**', async route => {
    const request = route.request();
    const method = new URL(request.url()).pathname.split('/').pop()!.split('.').pop()!;
    const body = request.method() === 'POST' ? request.postDataJSON() as Record<string, unknown> : {};
    if (method === 'login') {
      expect(body.usr).toBe('test.pm@example.invalid'); expect(body.pwd).toBe('fixture-password-only'); authenticated = true;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ message: 'Logged In' }) });
    }
    if (method === 'logout') { authenticated = false; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ message: 'Logged Out' }) }); }
    if (!authenticated) return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'unauthenticated', message: 'Sign in to continue.' } } }) });
    if (request.method() === 'POST') {
      const key = request.headers()['idempotency-key']; writes.push({ method, body, key });
      expect(key).toBe(body.operation_id); expect(request.headers()['x-frappe-csrf-token']).toBe('test-csrf');
    }
    if (method === 'session') return envelope(route, { authenticated: true, user: 'test.pm@example.invalid', person: actor(), companies: [{ id: company, name: 'Synthetic AEC Company' }], company_scopes: [], capabilities, csrf_token: 'test-csrf', site_mode: 'synthetic' });
    if (method === 'projects') {
      const cursor = new URL(request.url()).searchParams.get('cursor');
      if (options.pagination) return envelope(route, { items: (cursor ? projects.slice(2) : projects.slice(0, 2)).map(project => ({ ...project, version, ...(project.id === projects[0].id ? { status: currentStatus } : {}) })), total: projects.length, next_cursor: cursor ? null : 'signed-test-cursor', count_mode: 'exact', limit: 2 });
      return envelope(route, { items: projects.map(project => ({ ...project, version, ...(project.id === projects[0].id ? { status: currentStatus } : {}) })), total: projects.length, next_cursor: null, count_mode: 'exact', limit: 50 });
    }
    if (method === 'project') { const id = new URL(request.url()).searchParams.get('project'); return envelope(route, { ...projects.find(project => project.id === id), version, ...(id === projects[0].id ? { status: currentStatus } : {}), capabilities }); }
    if (method === 'tasks') return envelope(route, { items: tasks, total: tasks.length });
    if (method === 'history') return envelope(route, { items: [{ id: 'TEST-EVENT-001', event: 'task.created', actor: 'Alex Morgan', at: '2026-10-15T12:00:00Z', subject_type: 'Task', subject_id: tasks[tasks.length - 1].id, details: {} }], total: 1 });
    if (method === 'create_task') {
      if (options.staleTask) return route.fulfill({ status: 412, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'stale_source', message: 'The project changed. Refresh and review the latest version before saving.' }, request_id: 'test-stale' } }) });
      const old = receipts.get(String(body.operation_id));
      if (old) return envelope(route, old);
      const task = { id: `TEST-TASK-${tasks.length + 1}`, subject: String(body.subject), description: String(body.description ?? ''), status: 'Open', project: projects[0].id, version: '1' }; tasks.push(task); version = String(Number(version) + 1);
      const result = { task, operation: { id: body.operation_id, status: 'succeeded', replayed: Boolean(options.loseFirstTaskResponse) }, project_version: version }; receipts.set(String(body.operation_id), result);
      if (options.loseFirstTaskResponse && !firstLost) { firstLost = true; return route.abort('failed'); }
      return envelope(route, result);
    }
    if (method === 'list_packets') return envelope(route, { items: packets.map(approvals), total: packets.length, next_cursor: null, count_mode: 'exact', limit: 50 });
    if (method === 'read_packet') return envelope(route, approvals(packets.find(packet => packet.id === new URL(request.url()).searchParams.get('packet_id'))!));
    if (method === 'request_project_status') {
      expect(body.expected_version).toBe(version);
      const packet: ApprovalPacket = { id: 'TEST-APPROVAL-001', company, project: projects[0].id, action: 'project.status.change.v1', subject: { id: projects[0].id, type: 'Project', label: projects[0].name }, requester: actor(), created_at: '2026-10-15T12:00:00Z', expires_at: '2030-10-16T12:00:00Z', manifest_hash: 'b'.repeat(64), source_version: version, changes: { status: { from: currentStatus, to: String(body.status) } }, native_completion: { percent_complete_method: 'Task Completion', percent_complete: '0' }, task_effects: { count: tasks.length, changes: [] }, policy: { id: 'TEST-POLICY', label: 'Independent project status review', synthetic: true }, state: 'Pending', decisions: [], actions: { can_decide: false, can_execute: false, can_withdraw: true, disabled_reason: null } };
      packets.push(packet); return envelope(route, { packet: approvals(packet), operation: { id: body.operation_id, replayed: false } });
    }
    if (['decide_packet', 'execute_packet', 'withdraw_packet'].includes(method)) {
      const old = receipts.get(String(body.operation_id)); if (old) return envelope(route, old);
      const packet = packets.find(item => item.id === body.packet_id)!;
      if (packet.action !== 'project.status.change.v1') throw new Error('This contract fixture only executes project status effects.');
      expect(body.manifest_hash).toBe(packet.manifest_hash);
      if (method === 'decide_packet' && options.staleApproval) { packet.state = 'Stale'; return route.fulfill({ status: 412, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'approval_stale', message: 'The approval source changed. Request a new review.' } } }) }); }
      if (method === 'decide_packet') { expect(reviewer).toBe(true); packet.state = body.decision === 'Grant' ? 'Granted' : 'Rejected'; packet.decisions.push({ id: 'TEST-DECISION', decision: body.decision as 'Grant' | 'Reject', actor: actor(), at: '2026-10-15T12:30:00Z', reason: String(body.reason || '') }); }
      if (method === 'withdraw_packet') packet.state = 'Withdrawn';
      if (method === 'execute_packet') { expect(body.reason).toBeUndefined(); expect(reviewer).toBe(false); expect(packet.state).toBe('Granted'); currentStatus = packet.changes.status.to; version = '2'; packet.state = 'Consumed'; }
      const result = { packet: approvals(packet), operation: { id: body.operation_id, replayed: false }, ...(method === 'execute_packet' ? { effect: { project: { ...projects[0], status: currentStatus, version } } } : {}) };
      receipts.set(String(body.operation_id), result);
      if (method === 'execute_packet' && options.loseFirstApprovalResponse && !approvalResponseLost) { approvalResponseLost = true; return route.abort('failed'); }
      return envelope(route, result);
    }
    if (method === 'list_documents' && options.documentFailure && !documentsRecovered) return route.fulfill({ status: options.documentFailure, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: options.documentFailure === 403 ? 'capability_denied' : options.documentFailure === 404 ? 'not_found' : 'upstream_unavailable', message: `Document access failed (HTTP ${options.documentFailure}).` } } }) });
    if (method === 'list_documents') return envelope(route, { items: documents, capabilities: { antivirus: false, ocr: false, formats: ['text/plain', 'application/pdf'] } });
    if (method === 'upload_document') {
      expect(Buffer.from(String(body.content_base64), 'base64').toString()).toBe('Fixture upload source.');
      expect(body.sha256).toMatch(/^[a-f0-9]{64}$/);
      const doc = { ...documents[0], id: 'TEST-DOC-002', current_revision: 'TEST-REV-002', title: String(body.title), filename: String(body.filename), sha256: String(body.sha256), byte_length: Number(body.byte_length) }; documents.push(doc);
      return envelope(route, { document: doc, revision: { ...doc, id: doc.current_revision }, operation: { replayed: false } });
    }
    if (method === 'get_document') return envelope(route, { document: documents[0], revisions: [{ id: documents[0].current_revision, revision_number: 1, sha256: documents[0].sha256, extraction_status: 'ready', scan_status: 'not_scanned' }] });
    if (method === 'preview_revision') return envelope(route, { document_id: citation.document_id, revision_id: citation.revision_id, page: 1, page_count: 1, text: sourceText, content_type: 'text/plain', citation });
    if (method === 'connection_status') return envelope(route, { available: options.model ?? false, status: options.model ? 'ready' : 'unavailable', code: options.model ? 'ready' : 'not_configured', message: options.model ? 'Synthetic model adapter for browser contract tests.' : 'The existing local Ricky model endpoint is not configured.', adapter_kind: options.model ? 'test_fixture' : 'unconfigured', capabilities: {}, cloud_fallback: false, requirements: ['Existing local model connection'] });
    if (method === 'start_run' || method === 'get_run') return envelope(route, { id: 'TEST-RUN-001', company, project: projects[0].id, status: 'waiting_for_review', question: 'Propose a task from the source requirements.', answer: 'The source requires a temporary bypass plan before mobilization. A task is proposed for your review.', citations: [citation], proposal_ids: ['TEST-PROPOSAL-001'], cancel_requested: false, error: null });
    if (method === 'get_proposal') return envelope(route, { id: 'TEST-PROPOSAL-001', run_id: 'TEST-RUN-001', version: '1', status: 'proposed', fields: { subject: 'Prepare temporary bypass plan', description: citation.excerpt }, sources: [citation], content_digest: 'fixture-content-digest' });
    if (method === 'commit_proposal') { tasks.push({ id: 'TEST-TASK-PROPOSED', subject: 'Prepare temporary bypass plan', description: citation.excerpt, status: 'Open', project: projects[0].id, version: '1' }); version = '2'; return envelope(route, { task: tasks[tasks.length - 1], operation: { id: body.operation_id, status: 'succeeded', replayed: false }, project_version: version }); }
    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'fixture_route_missing', message: `No test handler for ${method}` } } }) });
  });
  return { writes, tasks, documents, packets, recoverDocuments: () => { documentsRecovered = true; }, expireSession: () => { authenticated = false; }, setReviewer: (value: boolean) => { reviewer = value; } };
}
