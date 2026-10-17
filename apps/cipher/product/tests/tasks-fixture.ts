import { expect, type Page, type Route } from '@playwright/test';
import type { CreateTaskResponse, Person, Task } from '../src/api/types';
import { company, mockWorkspace, projects } from './fixture';

export const taskPeople: Person[] = [{ id: 'TEST-PERSON-001', display_name: 'Alex Morgan' }, { id: 'TEST-PERSON-002', display_name: 'Jordan Lee' }];
export const taskStatuses = ['Open', 'Working', 'Pending Review', 'Completed'];
type FailureMode = 'lost' | 'server' | 'malformed' | 'wrong-receipt' | 'missing-task-fields';

// Synthetic contract adapter only. It enforces exact current versions and
// original-body replay so browser tests cannot silently manufacture saves.
export async function mockTasks(page: Page, options: { readOnly?: boolean; updateOnly?: boolean; failure?: FailureMode; stale?: boolean; conflict?: boolean; readDelay?: number } = {}) {
  const workspace = await mockWorkspace(page);
  const task = workspace.tasks[0]; task.assignees = [taskPeople[0]]; task.assignment_conflict = Boolean(options.conflict);
  let capabilities = options.readOnly ? ['project.read'] : ['project.read', 'task.create', 'task.update', ...(options.updateOnly ? [] : ['task.assign'])];
  let projectVersion = '1'; let failed = false; let stale = Boolean(options.stale); let denyRecovery = false; let denyRead = false; let effects = 0;
  const writes: { method: string; body: Record<string, unknown> }[] = [];
  const receipts = new Map<string, { body: string; result: CreateTaskResponse }>();
  const envelope = (route: Route, data: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data } }) });
  const failure = (route: Route, status: number, code: string, message: string) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code, message }, request_id: `task-${code}` } }) });
  await page.route('**/api/method/cipher_aec.api.v1.*', async route => {
    const method = new URL(route.request().url()).pathname.split('.').pop()!;
    const query = new URL(route.request().url()).searchParams;
    if (method === 'project') return envelope(route, { ...projects[0], version: projectVersion, capabilities });
    if (method === 'tasks') {
      expect(query.get('company')).toBe(company); expect(query.get('project')).toBe(projects[0].id);
      return denyRead ? failure(route, 403, 'capability_denied', 'Task access was removed.') : envelope(route, { items: workspace.tasks, total: workspace.tasks.length });
    }
    if (method === 'task') {
      expect(query.get('company')).toBe(company); expect(query.get('project')).toBe(projects[0].id); expect(query.get('task')).toBe(task.id);
      if (options.readDelay) await new Promise(resolve => setTimeout(resolve, options.readDelay));
      return denyRead ? failure(route, 403, 'capability_denied', 'Task access was removed.') : envelope(route, task);
    }
    if (method === 'task_choices') {
      if (!capabilities.some(value => ['task.assign', 'task.update'].includes(value))) return failure(route, 403, 'capability_denied', 'Task changes are unavailable.');
      return envelope(route, { people: capabilities.includes('task.assign') ? taskPeople : [], statuses: taskStatuses, capabilities: capabilities.filter(value => ['task.assign', 'task.update'].includes(value)) });
    }
    if (!['assign_task', 'update_task_status'].includes(method)) return route.fallback();
    const body = route.request().postDataJSON() as Record<string, unknown>;
    writes.push({ method, body: structuredClone(body) });
    expect(route.request().headers()['idempotency-key']).toBe(body.operation_id); expect(route.request().headers()['x-frappe-csrf-token']).toBe('test-csrf');
    expect(body.company).toBe(company); expect(body.project).toBe(projects[0].id); expect(body.task).toBe(task.id);
    const previous = receipts.get(String(body.operation_id));
    if (previous) {
      expect(JSON.stringify(body)).toBe(previous.body);
      if (denyRecovery) return failure(route, 403, 'capability_denied', 'Receipt access is unavailable.');
      return envelope(route, { ...previous.result, operation: { ...previous.result.operation, replayed: true } });
    }
    if (!capabilities.includes(method === 'assign_task' ? 'task.assign' : 'task.update')) return failure(route, 403, 'capability_denied', 'Task changes are unavailable.');
    if (stale) { stale = false; task.version = '2'; task.status = 'Working'; return failure(route, 412, 'stale_source', 'The task changed. Refresh and review the latest task.'); }
    expect(body.expected_version).toBe(task.version);
    if (method === 'assign_task') {
      const selected = taskPeople.find(person => person.id === body.assignee_person);
      expect(body.assignee_person === null || Boolean(selected)).toBe(true);
      task.assignees = selected ? [selected] : [];
    } else { expect(taskStatuses).toContain(body.status); task.status = String(body.status); if (task.status === 'Completed') task.assignees = []; }
    task.version = String(Number(task.version) + 1); projectVersion = String(Number(projectVersion) + 1); effects++;
    const result: CreateTaskResponse = { task: structuredClone(task), project_version: projectVersion, operation: { id: String(body.operation_id), status: 'succeeded', replayed: false } };
    receipts.set(String(body.operation_id), { body: JSON.stringify(body), result });
    if (options.failure && !failed) {
      failed = true;
      if (options.failure === 'lost') return route.abort('failed');
      if (options.failure === 'server') return failure(route, 503, 'unavailable', 'The save response is unavailable.');
      if (options.failure === 'malformed') return route.fulfill({ status: 200, contentType: 'application/json', body: '{' });
      if (options.failure === 'missing-task-fields') { const { assignees: omittedAssignees, assignment_conflict: omittedConflict, ...incompleteTask } = result.task; return envelope(route, { ...result, task: incompleteTask }); }
      return envelope(route, { ...result, operation: { ...result.operation, id: 'another-operation' } });
    }
    return envelope(route, result);
  });
  return { task, writes, effects: () => effects, denyRecovery: (value: boolean) => { denyRecovery = value; }, denyRead: () => { denyRead = true; }, revoke: () => { capabilities = ['project.read']; } };
}
