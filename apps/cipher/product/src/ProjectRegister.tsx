import { useMemo, useState } from 'react';
import { AnalyticalTable, Button, FilterBar, FilterGroupItem, Input, Icon, Link, Option, Select, Title, Toolbar, ToolbarSpacer } from '@ui5/webcomponents-react';
import type { AnalyticalTableColumnDefinition } from '@ui5/webcomponents-react';
import type { Project } from './api/types';
import { date } from './hooks';
import { Empty, Fact, PageHeading, Pagination, Status } from './components';

export default function ProjectRegister({ projects, total, company, search, setSearch, navigate, refresh, pagination }: {
  projects: Project[]; total?: number; company: string; search: string; setSearch: (value: string) => void; navigate: (path: string) => void; refresh: () => void;
  pagination: { next?: string | null; page: number; previous: boolean; onNext: () => void; onPrevious: () => void };
}) {
  const [status, setStatus] = useState('All statuses');
  const statuses = useMemo(() => [...new Set(projects.map(project => project.status))], [projects]);
  const filtered = useMemo(() => projects.filter(project => (!search || `${project.name} ${project.id}`.toLowerCase().includes(search.toLowerCase())) && (status === 'All statuses' || status === project.status)), [projects, search, status]);
  const columns = useMemo<AnalyticalTableColumnDefinition[]>(() => [
    { Header: 'Project', accessor: 'name', minWidth: 260, width: 370, Cell: ({ row }) => { const project = row.original as Project; return <div className="record-cell"><Link onClick={() => navigate(`/projects/${encodeURIComponent(project.id)}`)}>{project.name}</Link><span>{project.id}</span></div>; } },
    { Header: 'Status', accessor: 'status', width: 145, Cell: ({ value }) => <Status value={String(value)} /> },
    { Header: 'Start date', accessor: 'expected_start_date', width: 155, Cell: ({ value }) => <span>{date(value)}</span> },
    { Header: 'Target completion', accessor: 'expected_end_date', width: 170, Cell: ({ value }) => <span>{date(value)}</span> },
    { Header: 'Company', accessor: 'company', minWidth: 180 },
  ], [navigate]);
  const active = projects.filter(project => ['open', 'active', 'in progress'].includes(project.status.toLowerCase())).length;
  const completed = projects.filter(project => ['completed', 'complete'].includes(project.status.toLowerCase())).length;
  return <div className="page register-page">
    <PageHeading eyebrow="PROJECT DELIVERY" title="Projects" description="Your projects, their source documents, and the work ahead." actions={<Button icon="refresh" onClick={refresh}>Refresh</Button>} />
    <section className="summary-strip" aria-label="Loaded project summary">
      <Fact label="Projects in this view" note={total !== undefined && total !== projects.length ? `${total} accessible records · ${projects.length} loaded` : company}>{projects.length}</Fact>
      <Fact label="Active" note="Open and in progress">{active}</Fact>
      <Fact label="Completed" note="Completed projects">{completed}</Fact>
      <div className="context-note"><IconContext /><div><strong>One project context</strong><span>Tasks, documents and Ricky stay connected to the work.</span></div></div>
    </section>
    <section className="surface register-surface" aria-label="Project register">
      <FilterBar hideFilterConfiguration hideToggleFiltersButton showGoOnFB={false} header={<Title level="H2">Project register</Title>}>
        <FilterGroupItem filterKey="search" label="Find a project"><Input accessibleName="Find a project" placeholder="Name or project number" value={search} onInput={event => setSearch(event.currentTarget!.value)} showClearIcon /></FilterGroupItem>
        <FilterGroupItem filterKey="status" label="Status"><Select accessibleName="Project status" onChange={event => setStatus(event.detail.selectedOption.value ?? 'All statuses')}><Option value="All statuses" selected={status === 'All statuses'}>All statuses</Option>{statuses.map(item => <Option key={item} value={item} selected={status === item}>{item}</Option>)}</Select></FilterGroupItem>
      </FilterBar>
      <Toolbar design="Transparent"><span className="result-count">{filtered.length} {filtered.length === 1 ? 'project' : 'projects'}</span><ToolbarSpacer />{(search || status !== 'All statuses') && <Button design="Transparent" onClick={() => { setSearch(''); setStatus('All statuses'); }}>Clear filters</Button>}<span className="caption">Select a project to open its workspace</span></Toolbar>
      {filtered.length ? <AnalyticalTable accessibleName="Projects" columns={columns} data={filtered} sortable rowHeight={62} headerRowHeight={40} minRows={Math.min(filtered.length, 5)} visibleRows={Math.min(Math.max(filtered.length, 3), 10)} scaleWidthMode="Grow" selectionMode="None" />
        : <Empty title={projects.length ? 'No projects match these filters' : 'No projects available'}>{projects.length ? 'Try another name or clear the filters.' : 'Projects you have permission to view will appear here.'}</Empty>}
      <Pagination {...pagination} total={total} />
    </section>
    <div className="page-footnote"><span>Company scope: {company}</span><span>{pagination.next || pagination.previous ? 'Filters apply to this loaded page.' : 'Project access is enforced by your workspace.'}</span></div>
  </div>;
}

function IconContext() { return <div className="context-symbol" aria-hidden="true"><Icon name="chain-link" /></div>; }
