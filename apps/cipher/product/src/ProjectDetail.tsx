import { useEffect, useState } from 'react';
import { Breadcrumbs, BreadcrumbsItem, Button, MessageStrip, ObjectPage, ObjectPageHeader, ObjectPageSection, ObjectPageTitle, Title, Toolbar, ToolbarButton, ToolbarSpacer } from '@ui5/webcomponents-react';
import { api } from './api/client';
import type { Project } from './api/types';
import { date, human, useResource } from './hooks';
import { Empty, Fact, Failure, Loading, Pagination, Status } from './components';
import { DocumentRegister } from './Documents';
import Approvals from './Approvals';
import { NewTask, TaskDetails, TaskRegister } from './Tasks';

export default function ProjectDetail({ projectId, company, navigate, refreshProjects, onContext, openRicky, onLockedChange }: {
  projectId: string; company: string; navigate: (path: string) => void; refreshProjects: () => void;
  onContext: (project: Project) => void; openRicky: () => void; onLockedChange: (locked: boolean) => void;
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
  const [lastProject, setLastProject] = useState<Project>();
  const [notice, setNotice] = useState('');
  const [selectedTask, setSelectedTask] = useState<string>();
  const [createLocked, setCreateLocked] = useState(false); const [detailLocked, setDetailLocked] = useState(false);
  useEffect(() => { onLockedChange(createLocked || detailLocked); }, [createLocked, detailLocked, onLockedChange]);
  useEffect(() => () => onLockedChange(false), [onLockedChange]);
  useEffect(() => { if (project.data) setLastProject(project.data); }, [project.data]);
  const transientProjectError = Boolean(project.error && ![401, 403, 404].includes(project.error.status));
  // A transient refresh cannot discard an authored create draft. Current access
  // denials still remove the cached project instead of exposing it as current.
  const current = project.data || (createOpen && (!project.error || transientProjectError) ? lastProject : undefined);
  if (project.loading && !current) return <Loading label="Opening project…" />;
  if (project.error && !current) return <div className="page"><Failure error={project.error} onRetry={project.refresh} /></div>;
  if (!current) return null;
  const refresh = () => { setTaskCursor(undefined); setTaskPages([]); setHistoryCursor(undefined); setHistoryPages([]); project.refresh(); tasks.refresh(); history.refresh(); documents.refresh(); refreshProjects(); };
  return <>
    {project.error && <div className="page"><Failure error={project.error} onRetry={project.refresh} /></div>}
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
          {tasks.loading ? <Loading label="Loading project tasks…" /> : tasks.error ? <Failure error={tasks.error} onRetry={tasks.refresh} /> : tasks.data?.items.length ? <TaskRegister items={tasks.data.items} onOpen={setSelectedTask} /> : <Empty title="No tasks yet" icon="task">Create a task or ask Ricky to propose one from a project source.</Empty>}
          <Pagination next={tasks.data?.next_cursor} total={tasks.data?.total} page={taskPages.length + 1} previous={Boolean(taskPages.length)} onNext={() => { if (tasks.data?.next_cursor) { setTaskPages([...taskPages, taskCursor]); setTaskCursor(tasks.data.next_cursor); } }} onPrevious={() => { setTaskCursor(taskPages[taskPages.length - 1]); setTaskPages(taskPages.slice(0, -1)); }} />
        </div>
      </ObjectPageSection>
      <ObjectPageSection id="project-documents" titleText="Documents">
        <div className="section-body"><Toolbar design="Transparent"><Title level="H2">Source documents</Title><ToolbarSpacer /><Button icon="folder" onClick={() => navigate(`/projects/${encodeURIComponent(current.id)}/documents`)}>Manage documents</Button></Toolbar>
          {documents.loading ? <Loading label="Loading source documents…" /> : documents.error ? <Failure error={documents.error} onRetry={documents.refresh} /> : <DocumentRegister items={documents.data?.items ?? []} navigate={navigate} />}
        </div>
      </ObjectPageSection>
      <ObjectPageSection id="project-approvals" titleText="Approvals">
        <div className="section-body"><Approvals project={current} onEffect={refresh} navigate={navigate} /></div>
      </ObjectPageSection>
      <ObjectPageSection id="project-history" titleText="Activity">
        <div className="section-body history-section"><Title level="H2">Project activity</Title>
          {history.loading ? <Loading label="Loading project history…" /> : history.error ? <Failure error={history.error} onRetry={history.refresh} /> : history.data?.items.length ? <ol className="activity-list">{history.data.items.map(item => <li key={item.id}><span className="activity-dot" /><div><strong>{human(item.event)}</strong><p>{item.actor} · {date(item.at)}</p></div></li>)}</ol> : <Empty title="No recorded activity" icon="history">Saved project changes will appear here.</Empty>}
          <Pagination next={history.data?.next_cursor} total={history.data?.total} page={historyPages.length + 1} previous={Boolean(historyPages.length)} onNext={() => { if (history.data?.next_cursor) { setHistoryPages([...historyPages, historyCursor]); setHistoryCursor(history.data.next_cursor); } }} onPrevious={() => { setHistoryCursor(historyPages[historyPages.length - 1]); setHistoryPages(historyPages.slice(0, -1)); }} />
        </div>
      </ObjectPageSection>
    </ObjectPage>
    {createOpen && <NewTask project={current} onClose={() => setCreateOpen(false)} onSaved={task => { setNotice(`Task “${task.subject}” was created.`); setCreateOpen(false); refresh(); }} onRefresh={project.refresh} onLockedChange={setCreateLocked} />}
    {selectedTask && <TaskDetails key={selectedTask} project={current} taskId={selectedTask} onClose={() => setSelectedTask(undefined)} onSaved={refresh} onAccessLost={tasks.refresh} onLockedChange={setDetailLocked} />}
  </>;
}
