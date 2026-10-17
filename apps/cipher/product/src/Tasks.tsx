import { useEffect, useState } from 'react';
import { Bar, Button, Dialog, Input, Label, Link, MessageStrip, Option, Select, Table, TableCell, TableHeaderCell, TableHeaderRow, TableRow, TextArea, Title } from '@ui5/webcomponents-react';
import { api, ApiError } from './api/client';
import type { AssignTaskRequest, CreateTaskRequest, CreateTaskResponse, Project, Task, TaskControlResponse, UpdateTaskStatusRequest } from './api/types';
import { Failure, Loading, Status } from './components';
import { useResource } from './hooks';
import { useMutation } from './useMutation';

const assignees = (task: Task) => task.assignment_conflict ? 'Assignment needs reconciliation' : task.assignees?.map(person => person.display_name).join(', ') || 'Unassigned';
const validTask = (task: Task | undefined, project: string) => Boolean(task && typeof task.id === 'string' && task.id && task.project === project && typeof task.version === 'string' && task.version && typeof task.status === 'string' && typeof task.subject === 'string' && typeof task.description === 'string' && (task.assignees === undefined || Array.isArray(task.assignees) && task.assignees.every(person => person && typeof person.id === 'string' && typeof person.display_name === 'string')) && (task.assignment_conflict === undefined || typeof task.assignment_conflict === 'boolean'));
const validCurrentTask = (task: Task | undefined, project: string) => validTask(task, project) && Array.isArray(task?.assignees) && typeof task?.assignment_conflict === 'boolean';

export function TaskRegister({ items, onOpen }: { items: Task[]; onOpen: (id: string) => void }) {
  return <Table accessibleName="Project tasks" overflowMode="Scroll" headerRow={<TableHeaderRow>
    <TableHeaderCell minWidth="16rem">Task</TableHeaderCell><TableHeaderCell width="10rem">Status</TableHeaderCell><TableHeaderCell minWidth="12rem">Assigned to</TableHeaderCell><TableHeaderCell minWidth="15rem">Description</TableHeaderCell>
  </TableHeaderRow>}>
    {items.map(task => <TableRow key={task.id} rowKey={task.id}>
      <TableCell><div className="record-cell"><Link onClick={() => onOpen(task.id)}>{task.subject}</Link><span>{task.id}</span></div></TableCell>
      <TableCell><Status value={task.status} /></TableCell><TableCell>{assignees(task)}</TableCell><TableCell>{task.description || 'No description'}</TableCell>
    </TableRow>)}
  </Table>;
}

function useTaskLock(locked: boolean, onLockedChange: (locked: boolean) => void) {
  useEffect(() => { onLockedChange(locked); }, [locked, onLockedChange]);
  useEffect(() => () => onLockedChange(false), [onLockedChange]);
}

export function NewTask({ project, onClose, onSaved, onRefresh, onLockedChange }: { project: Project; onClose: () => void; onSaved: (task: Task) => void; onRefresh: () => void; onLockedChange: (locked: boolean) => void }) {
  const [subject, setSubject] = useState(''); const [description, setDescription] = useState('');
  const [sourceVersion, setSourceVersion] = useState(project.version);
  const [conflict, setConflict] = useState(false);
  const command = useMutation<CreateTaskRequest, CreateTaskResponse>(api.createTask, (result, input) => validTask(result.task, input.project) && result.task.subject === input.subject && typeof result.project_version === 'string' && Boolean(result.project_version));
  useTaskLock(command.locked, onLockedChange);
  const submit = async () => {
    const result = command.unknown ? await command.recover() : await command.run({ company: project.company, project: project.id, expected_version: sourceVersion, subject: subject.trim(), description: description.trim() } as CreateTaskRequest);
    if (result) onSaved(result.task);
  };
  useEffect(() => { if (command.error?.status === 412 && !command.unknown) setConflict(true); }, [command.error, command.unknown]);
  return <Dialog open headerText="Create project task" className="form-dialog" onBeforeClose={event => { if (command.locked) event.preventDefault(); }} onClose={() => { if (!command.locked) onClose(); }} footer={<Bar design="Footer" endContent={<><Button design="Emphasized" disabled={command.busy || (!command.unknown && (!subject.trim() || conflict))} onClick={submit}>{command.busy ? 'Saving…' : command.unknown ? 'Recover task' : 'Create task'}</Button><Button disabled={command.locked} onClick={onClose}>Cancel</Button></>} />}>
    <div className="dialog-form"><p className="caption">{project.name}</p>{command.error && <Failure error={command.error} />}
      {command.unknown && <MessageStrip design="Critical" hideCloseButton>The save result is unknown. Recover this request before editing or leaving.</MessageStrip>}
      {conflict && !command.unknown && <><MessageStrip design="Critical" hideCloseButton>The project changed. Your task text is preserved. Refresh and review the project before saving.</MessageStrip><Button onClick={onRefresh}>Refresh project</Button>{project.version !== sourceVersion && <Button onClick={() => { setSourceVersion(project.version); setConflict(false); }}>Use current project</Button>}</>}
      <Label for="task-subject" required>Task name</Label><Input id="task-subject" accessibleName="Task name" value={subject} maxlength={140} disabled={command.locked} onInput={event => setSubject(event.currentTarget!.value)} />
      <Label for="task-description">Description</Label><TextArea id="task-description" accessibleName="Task description" value={description} rows={4} disabled={command.locked} onInput={event => setDescription(event.currentTarget!.value)} />
    </div>
  </Dialog>;
}

type TaskChange = ({ action: 'assign' } & AssignTaskRequest) | ({ action: 'status' } & UpdateTaskStatusRequest);

export function TaskDetails({ project, taskId, onClose, onSaved, onAccessLost, onLockedChange }: { project: Project; taskId: string; onClose: () => void; onSaved: () => void; onAccessLost: () => void; onLockedChange: (locked: boolean) => void }) {
  const scope = `${project.company}/${project.id}/${taskId}`;
  const current = useResource(scope, async signal => {
    const result = await api.task(project.company, project.id, taskId, signal);
    if (!validCurrentTask(result, project.id) || result.id !== taskId) throw new ApiError('The saved task could not be read. Refresh the task.', 'INVALID_CONTRACT', 200);
    return result;
  });
  const choices = useResource(project.capabilities?.some(value => ['task.assign', 'task.update'].includes(value)) ? `${scope}/choices` : null, async signal => {
    const result = await api.taskChoices(project.company, project.id, signal);
    if (!result || !Array.isArray(result.people) || !result.people.every(person => person && typeof person.id === 'string' && typeof person.display_name === 'string') || !Array.isArray(result.statuses) || !result.statuses.every(value => ['Open', 'Working', 'Pending Review', 'Completed'].includes(value)) || !Array.isArray(result.capabilities) || !result.capabilities.every(value => ['task.assign', 'task.update'].includes(value))) throw new ApiError('The task options could not be read. Refresh the task options.', 'INVALID_CONTRACT', 200);
    return result;
  });
  const [sourceVersion, setSourceVersion] = useState(''); const [person, setPerson] = useState(''); const [status, setStatus] = useState('');
  const [notice, setNotice] = useState(''); const [conflict, setConflict] = useState(false); const [denied, setDenied] = useState(false);
  const command = useMutation<TaskChange, TaskControlResponse>(input => {
    const { action, ...request } = input;
    return action === 'assign' ? api.assignTask(request as AssignTaskRequest) : api.updateTaskStatus(request as UpdateTaskStatusRequest);
  }, (result, input) => validCurrentTask(result.task, input.project) && result.task.id === input.task && typeof result.project_version === 'string' && Boolean(result.project_version) &&
    (input.action === 'status' ? result.task.status === input.status : !Array.isArray(result.task.assignees) ? false : input.assignee_person === null ? result.task.assignees.length === 0 : result.task.assignees.length === 1 && result.task.assignees[0].id === input.assignee_person));
  useTaskLock(command.locked, onLockedChange);
  useEffect(() => {
    if (current.data && !sourceVersion) { setSourceVersion(current.data.version); setPerson(current.data.assignees?.length === 1 ? current.data.assignees[0].id : current.data.assignees?.length ? '' : '__unassigned__'); setStatus(current.data.status); }
  }, [current.data, sourceVersion]);
  useEffect(() => {
    if (!command.error || command.unknown) return;
    if (command.error.status === 412) setConflict(true);
    if ([403, 404].includes(command.error.status)) { setDenied(true); current.refresh(); choices.refresh(); }
  }, [command.error, command.unknown, current.refresh, choices.refresh]);
  useEffect(() => { if (current.error && [403, 404].includes(current.error.status)) onAccessLost(); }, [current.error, onAccessLost]);
  const refresh = () => { current.refresh(); choices.refresh(); };
  const save = async (action: 'assign' | 'status', nextStatus?: string) => {
    setNotice('');
    const base = { company: project.company, project: project.id, task: taskId, expected_version: sourceVersion };
    const result = command.unknown ? await command.recover() : await command.run(action === 'assign' ? { ...base, action, assignee_person: person === '__unassigned__' ? null : person } as TaskChange : { ...base, action, status: nextStatus || status } as TaskChange);
    if (!result) return;
    const people = result.task.assignees || [];
    setSourceVersion(result.task.version); setPerson(people.length === 1 ? people[0].id : people.length ? '' : '__unassigned__'); setStatus(result.task.status); setConflict(false); setDenied(false);
    setNotice(result.operation.replayed ? 'The original task change was recovered.' : 'Task saved.'); refresh(); onSaved();
  };
  const task = current.data;
  const statuses: readonly string[] = choices.data?.statuses.filter(value => task?.status !== 'Completed' || value === 'Open') || [];
  const stale = conflict || Boolean(task && sourceVersion && task.version !== sourceVersion);
  const controlsReady = Boolean(task && !task.assignment_conflict && !current.loading && !current.error && choices.data && !choices.loading && !choices.error && !denied && !stale);
  const canAssign = Boolean(controlsReady && choices.data?.capabilities.includes('task.assign'));
  const canUpdate = Boolean(controlsReady && task?.status !== 'Cancelled' && choices.data?.capabilities.includes('task.update'));
  const closed = task?.status === 'Completed' || task?.status === 'Cancelled';
  const selectedPerson = person === '__unassigned__' || choices.data?.people.some(value => value.id === person);
  return <Dialog open headerText="Project task" className="form-dialog" onBeforeClose={event => { if (command.locked) event.preventDefault(); }} onClose={() => { if (!command.locked) onClose(); }} footer={<Bar design="Footer" endContent={<>{command.unknown && <Button design="Emphasized" disabled={command.busy} onClick={() => save('status')}>{command.busy ? 'Recovering…' : 'Recover task change'}</Button>}<Button disabled={command.locked} onClick={onClose}>Close task</Button></>} />}>
    <div className="dialog-form">
      {notice && <MessageStrip design="Positive" onClose={() => setNotice('')}>{notice}</MessageStrip>}
      {command.error && <Failure error={command.error} />}
      {command.unknown && <MessageStrip design="Critical" hideCloseButton>The save result is unknown. Recover this request before editing or leaving.</MessageStrip>}
      {current.loading ? <Loading label="Loading task…" /> : current.error ? <Failure error={current.error} onRetry={refresh} /> : task && <>
        <Title level="H2">{task.subject}</Title><p>{task.description || 'No description'}</p><Status value={task.status} /><p><strong>Assigned to: </strong>{assignees(task)}</p>
        {stale && !command.unknown && <><MessageStrip design="Critical" hideCloseButton>The task changed. Your selections are preserved. Refresh and review the saved task before continuing.</MessageStrip><Button disabled={command.locked} onClick={refresh}>Refresh task</Button>{task.version !== sourceVersion && <Button disabled={command.locked} onClick={() => { setSourceVersion(task.version); setConflict(false); setDenied(false); }}>Use current task</Button>}</>}
        {denied && !command.unknown && <MessageStrip design="Information" hideCloseButton>Your permissions changed. Close and reopen this task to review current access.</MessageStrip>}
        {task.assignment_conflict && <MessageStrip design="Information" hideCloseButton>This assignment needs administrator reconciliation before the task can change.</MessageStrip>}
        {choices.loading && <Loading label="Loading task options…" />}{choices.error && <Failure error={choices.error} onRetry={choices.refresh} />}
        {canAssign && !closed && <><Label for="task-person">Assigned to</Label><Select id="task-person" accessibleName="Assigned to" disabled={command.locked} onChange={event => setPerson(event.detail.selectedOption.value ?? '')}>
          <Option value="" selected={!selectedPerson}>Choose a person</Option><Option value="__unassigned__" selected={person === '__unassigned__'}>Unassigned</Option>{choices.data!.people.map(value => <Option key={value.id} value={value.id} selected={person === value.id}>{value.display_name}</Option>)}
        </Select><Button disabled={command.locked || !selectedPerson || (task.assignees?.length === 1 ? person === task.assignees[0].id : !task.assignees?.length && person === '__unassigned__')} onClick={() => save('assign')}>Save assignment</Button></>}
        {canUpdate && <><Label for="task-status">Status</Label><Select id="task-status" accessibleName="Task status" disabled={command.locked} onChange={event => setStatus(event.detail.selectedOption.value ?? '')}>
          <Option value="" selected={!statuses.includes(status)}>Choose a status</Option>{statuses.map(value => <Option key={value} value={value} selected={status === value}>{value}</Option>)}
        </Select><Button disabled={command.locked || status === task.status || !statuses.includes(status)} onClick={() => save('status')}>Save status</Button>
          {task.status === 'Completed' ? <Button design="Emphasized" disabled={command.locked || !statuses.includes('Open')} onClick={() => save('status', 'Open')}>Reopen task</Button> : <Button design="Emphasized" disabled={command.locked || !statuses.includes('Completed')} onClick={() => save('status', 'Completed')}>Mark complete</Button>}
        </>}
      </>}
    </div>
  </Dialog>;
}
