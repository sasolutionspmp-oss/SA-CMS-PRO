import { useState } from 'react';
import { Table, TableHeaderRow, TableHeaderCell, TableRow, TableCell, Bar, Breadcrumbs, BreadcrumbsItem, Button, Dialog, Input, Label, Link, MessageStrip, ObjectPage, ObjectPageHeader, ObjectPageSection, ObjectPageTitle, TextArea, Title, Toolbar, ToolbarButton, ToolbarSpacer } from '@ui5/webcomponents-react';
import { api, ApiError } from './api/client';
import type { Project, Task } from './api/types';
import { date, human, useResource } from './hooks';
import { Empty, Fact, Failure, Loading, Pagination, Status } from './components';
import { DocumentRegister } from './Documents';
import Approvals from './Approvals';

export default function ProjectDetail({ projectId, company, navigate, refreshProjects, onContext, openRicky }: {
  projectId: string; company: string; navigate: (path: string) => void; refreshProjects: () => void;
  onContext: (project: Project) => void; openRicky: () => void;
}) {
  const project = useResource(`${company}/${projectId}`, signal => api.project(company, projectId, signal));
  const [taskCursor, setTaskCursor] = useState<string>();
  const [taskPages, setTaskPages] = useState<(string | undefined)[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string>();
  const [historyPages, setHistoryPages] = useState<(string | undefined)[]>([]);
  const tasks = useResource(`${company}/${projectId}/tasks/${taskCursor ?? ''}`, signal => api.tasks(company, projectId, signal, taskCursor));
  const history = useResource(`${company}/${projectId}/history/${historyCursor ?? ''}`, signal => api.history(company, projectId, signal, historyCursor));
  const documents = useResource(`${company}/${projectId}/documents`, signal => api.documents(company, projectId, signal));
  const [createOpen, setCreateOpen] = useState(false);
  const [notice, setNotice] = useState('');
  if (project.loading && !project.data) return <Loading label="Opening project workspace…" />;
  if (project.error) return <div className="page"><Failure error={project.error} onRetry={project.refresh} /></div>;
  if (!project.data) return null;
  const current = project.data;
  const refresh = () => { setTaskCursor(undefined); setTaskPages([]); setHistoryCursor(undefined); setHistoryPages([]); project.refresh(); tasks.refresh(); history.refresh(); documents.refresh(); refreshProjects(); };
  return <>
    <ObjectPage className="project-object-page" titleArea={<ObjectPageTitle
      header={<h1>{current.name}</h1>} subHeader={<span className="caption">{current.id} · {current.company}</span>}
      breadcrumbs={<Breadcrumbs><BreadcrumbsItem onClick={() => navigate('/projects')}>Projects</BreadcrumbsItem><BreadcrumbsItem>{current.name}</BreadcrumbsItem></Breadcrumbs>}
      actionsBar={<Toolbar design="Transparent"><ToolbarButton text="Ask Ricky" icon="da" onClick={() => { onContext(current); openRicky(); }} /><ToolbarButton text="Refresh" icon="refresh" onClick={refresh} /></Toolbar>}>
      <Status value={current.status} />
    </ObjectPageTitle>} headerArea={<ObjectPageHeader><div className="project-facts">
      <Fact label="Start date">{date(current.expected_start_date)}</Fact><Fact label="Target completion">{date(current.expected_end_date)}</Fact>
      <Fact label="Tasks">{tasks.data?.total ?? tasks.data?.items.length ?? '—'}</Fact><Fact label="Source documents">{documents.data?.items.length ?? '—'}</Fact>
    </div></ObjectPageHeader>}>
      <ObjectPageSection id="project-tasks" titleText="Tasks">
        <div className="section-body"><Toolbar design="Transparent"><Title level="H2">Project work</Title><ToolbarSpacer />{current.capabilities?.includes('task.create') && <Button icon="add" design="Emphasized" onClick={() => setCreateOpen(true)}>New task</Button>}</Toolbar>
          {notice && <MessageStrip design="Positive" onClose={() => setNotice('')}>{notice}</MessageStrip>}
          {tasks.loading ? <Loading label="Loading project tasks…" /> : tasks.error ? <Failure error={tasks.error} onRetry={tasks.refresh} /> : tasks.data?.items.length ? <Table accessibleName="Project tasks" overflowMode="Scroll" headerRow={<TableHeaderRow>
            <TableHeaderCell width="42%" minWidth="16rem">Task</TableHeaderCell><TableHeaderCell width="10rem">Status</TableHeaderCell><TableHeaderCell minWidth="15rem">Description</TableHeaderCell>
          </TableHeaderRow>}>
            {tasks.data.items.map(task => <TableRow key={task.id} rowKey={task.id}>
              <TableCell><div className="record-cell"><strong>{task.subject}</strong><span>{task.id}</span></div></TableCell>
              <TableCell><Status value={task.status} /></TableCell><TableCell><span>{task.description || 'No description'}</span></TableCell>
            </TableRow>)}
          </Table> : <Empty title="No tasks yet" icon="task">Create a task or ask Ricky to propose one from a project source.</Empty>}
          <Pagination next={tasks.data?.next_cursor} total={tasks.data?.total} page={taskPages.length + 1} previous={Boolean(taskPages.length)} onNext={() => { if (tasks.data?.next_cursor) { setTaskPages([...taskPages, taskCursor]); setTaskCursor(tasks.data.next_cursor); } }} onPrevious={() => { setTaskCursor(taskPages[taskPages.length - 1]); setTaskPages(taskPages.slice(0, -1)); }} />
        </div>
      </ObjectPageSection>
      <ObjectPageSection id="project-documents" titleText="Documents">
        <div className="section-body"><Toolbar design="Transparent"><Title level="H2">Source documents</Title><ToolbarSpacer /><Button icon="folder" onClick={() => navigate(`/projects/${encodeURIComponent(current.id)}/documents`)}>Manage documents</Button></Toolbar>
          {documents.loading ? <Loading label="Loading source documents…" /> : documents.error ? <Failure error={documents.error} onRetry={documents.refresh} /> : <DocumentRegister items={documents.data?.items ?? []} navigate={navigate} />}
        </div>
      </ObjectPageSection>
      <ObjectPageSection id="project-approvals" titleText="Approvals">
        <div className="section-body"><Approvals project={current} onEffect={refresh} /></div>
      </ObjectPageSection>
      <ObjectPageSection id="project-history" titleText="Activity">
        <div className="section-body history-section"><Title level="H2">Project activity</Title>
          {history.loading ? <Loading label="Loading project history…" /> : history.error ? <Failure error={history.error} onRetry={history.refresh} /> : history.data?.items.length ? <ol className="activity-list">{history.data.items.map(item => <li key={item.id}><span className="activity-dot" /><div><strong>{human(item.event)}</strong><p>{item.actor} · {date(item.at)}</p><span className="caption">{item.subject_type}: {item.subject_id}</span></div></li>)}</ol> : <Empty title="No recorded activity" icon="history">Activity from saved project changes will appear here.</Empty>}
          <Pagination next={history.data?.next_cursor} total={history.data?.total} page={historyPages.length + 1} previous={Boolean(historyPages.length)} onNext={() => { if (history.data?.next_cursor) { setHistoryPages([...historyPages, historyCursor]); setHistoryCursor(history.data.next_cursor); } }} onPrevious={() => { setHistoryCursor(historyPages[historyPages.length - 1]); setHistoryPages(historyPages.slice(0, -1)); }} />
        </div>
      </ObjectPageSection>
    </ObjectPage>
    <TaskDialog open={createOpen} project={current} onClose={() => setCreateOpen(false)} onSaved={task => { setNotice(`Task “${task.subject}” was created.`); setCreateOpen(false); refresh(); }} />
  </>;
}

function TaskDialog({ open, project, onClose, onSaved }: { open: boolean; project: Project; onClose: () => void; onSaved: (task: Task) => void }) {
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const save = async () => {
    if (!subject.trim() || saving) return;
    setSaving(true); setError(undefined);
    try {
      const result = await api.createTask({ company: project.company, project: project.id, expected_version: project.version, operation_id: operationId, subject: subject.trim(), description: description.trim() });
      setSubject(''); setDescription(''); setOperationId(crypto.randomUUID()); onSaved(result.task);
    } catch (failure) { setError(failure as ApiError); }
    finally { setSaving(false); }
  };
  const change = () => { setOperationId(crypto.randomUUID()); setError(undefined); };
  return <Dialog open={open} headerText="Create project task" onClose={() => { if (!saving) onClose(); }} className="form-dialog" footer={<Bar design="Footer" endContent={<><Button design="Emphasized" disabled={!subject.trim() || saving} onClick={save}>{saving ? 'Saving…' : 'Create task'}</Button><Button disabled={saving} onClick={onClose}>Cancel</Button></>} />}>
    <div className="dialog-form"><p className="caption">{project.name}</p>{error && <Failure error={error} />}
      <Label for="task-subject" required>Task name</Label><Input id="task-subject" accessibleName="Task name" value={subject} maxlength={140} onInput={event => { setSubject(event.currentTarget!.value); change(); }} />
      <Label for="task-description">Description</Label><TextArea id="task-description" accessibleName="Task description" value={description} rows={4} onInput={event => { setDescription(event.currentTarget!.value); change(); }} />
    </div>
  </Dialog>;
}
