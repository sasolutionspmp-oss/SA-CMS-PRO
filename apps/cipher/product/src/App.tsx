import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Avatar, Bar, Button, Dialog, Icon, Link, MessageStrip, NavigationLayout, Option, Select, ShellBar, ShellBarBranding, ShellBarSearch, ShellBarSpacer, SideNavigation, SideNavigationItem, Tag, Title, ToggleButton, Toolbar, ToolbarSpacer } from '@ui5/webcomponents-react';
import type { NavigationLayoutDomRef } from '@ui5/webcomponents-react';
import NavigationLayoutMode from '@ui5/webcomponents-fiori/dist/types/NavigationLayoutMode.js';
import { api, ApiError, rpc } from './api/client';
import type { ModelStatus, Project, Session } from './api/types';
import { useResource, useRoute } from './hooks';
import { Empty, Failure, Loading, PageHeading, Status } from './components';
import ProjectRegister from './ProjectRegister';
import ProjectDetail from './ProjectDetail';
import { DocumentPage, DocumentsPage } from './Documents';
import RickyPanel from './RickyPanel';
import SignIn from './SignIn';
import Approvals from './Approvals';
import Estimates from './Estimates';
const Takeoff = lazy(() => import('./Takeoff'));
const Commercial = lazy(() => import('./Commercial'));
const CompanyDocuments = lazy(() => import('./CompanyDocuments'));
const CompanyEstimates = lazy(() => import('./CompanyEstimates'));
const CompanyApprovals = lazy(() => import('./CompanyApprovals'));
const CostMasters = lazy(() => import('./CostMasters'));
const CompanyActivity = lazy(() => import('./CompanyActivity'));

export default function App() {
  const { path, navigate: navigateRoute } = useRoute();
  const session = useResource('session', signal => api.session(signal));
  const [companySelection, setCompany] = useState('');
  const [projectId, setProjectId] = useState('');
  const [rickyOpen, setRickyOpen] = useState(false);
  const [suggestionLocked, setSuggestionLocked] = useState(false);
  const navigate = useCallback((next: string) => { if (!suggestionLocked) navigateRoute(next); }, [suggestionLocked, navigateRoute]);
  const [profileOpen, setProfileOpen] = useState(false);
  const [mode, setMode] = useState<NavigationLayoutMode>(NavigationLayoutMode.Auto);
  const [phoneLayout, setPhoneLayout] = useState(() => window.matchMedia('(max-width: 599px)').matches);
  const [search, setSearch] = useState('');
  const [dataRevision, setDataRevision] = useState(0);
  const [authRequested, setAuthRequested] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [profileError, setProfileError] = useState<ApiError>();
  const [projectCursor, setProjectCursor] = useState<string>();
  const [projectPages, setProjectPages] = useState<(string | undefined)[]>([]);
  const layoutRef = useRef<NavigationLayoutDomRef>(null);
  const identity = session.data?.person.id ?? '';
  const route = path.split('?')[0].split('/').filter(Boolean).map(segment => { try { return decodeURIComponent(segment); } catch { return segment; } });
  const companyBoundRoute = route[0] === 'company' || (route[0] === 'commercial' && route[1] === 'issues' && route[2] && route[3] === 'award');
  const requestedCompany = companyBoundRoute ? new URLSearchParams(path.split('?')[1] || '').get('company') : null;
  const requestedCompanyAllowed = Boolean(requestedCompany && session.data?.company_scopes.some(scope => scope.company === requestedCompany) && session.data.companies.some(item => item.id === requestedCompany));
  const requestedCompanyDenied = Boolean(requestedCompany && session.data?.authenticated && !requestedCompanyAllowed);
  const company = requestedCompany ? (requestedCompanyAllowed ? requestedCompany : '') : companySelection;
  const companyCommercial = route[0] === 'commercial';
  const companyWorkspace = companyCommercial || route[0] === 'company';
  const projects = useResource(company && identity && !companyWorkspace ? `projects/${identity}/${company}/${projectCursor ?? ''}` : null, signal => api.projects(company, signal, projectCursor));
  const citedPage = Number(new URLSearchParams(path.split('?')[1] ?? '').get('page'));
  const routeProjectId = route[0] === 'projects' ? route[1] : undefined;
  const contextId = companyWorkspace ? undefined : routeProjectId || projectId;
  const contextProject = useResource(company && contextId && identity ? `project-context/${identity}/${company}/${contextId}` : null, signal => api.project(company, contextId!, signal));
  const selectedProject = contextProject.data ?? projects.data?.items.find(project => project.id === contextId);

  useEffect(() => {
    const currentSession = session.data;
    if (currentSession) setCompany(current => requestedCompanyAllowed ? requestedCompany! : currentSession.companies.some(item => item.id === current) ? current : currentSession.companies[0]?.id ?? '');
  }, [session.data, requestedCompany, requestedCompanyAllowed]);
  useEffect(() => { setProjectId(''); setProjectCursor(undefined); setProjectPages([]); setRickyOpen(false); }, [session.data?.user]);
  useEffect(() => {
    const signIn = () => { setAuthRequested(true); setRickyOpen(false); };
    const expired = () => { setAuthRequested(true); setRickyOpen(false); setProfileOpen(false); setProjectId(''); };
    window.addEventListener('cipher:sign-in', signIn); window.addEventListener('cipher:session-expired', expired);
    return () => { window.removeEventListener('cipher:sign-in', signIn); window.removeEventListener('cipher:session-expired', expired); };
  }, []);
  useEffect(() => {
    const phone = window.matchMedia('(max-width: 599px)');
    const resizeNavigation = () => { setPhoneLayout(phone.matches); setMode(phone.matches ? NavigationLayoutMode.Collapsed : NavigationLayoutMode.Auto); };
    resizeNavigation(); phone.addEventListener('change', resizeNavigation);
    return () => phone.removeEventListener('change', resizeNavigation);
  }, []);
  useEffect(() => { if (routeProjectId) setProjectId(routeProjectId); }, [routeProjectId]);
  useEffect(() => { document.title = `${selectedProject?.name ?? (route[0] === 'company' && route[1] === 'activity' ? 'Company activity' : route[0] === 'commercial' ? 'Commercial' : route[0] === 'documents' ? 'Document' : route[0] === 'connections' ? 'Connections' : 'Projects')} · Cipher`; }, [selectedProject?.name, path]);

  const changeCompany = (next: string) => { if (suggestionLocked) return; setCompany(next); setProjectId(''); setSearch(''); setProjectCursor(undefined); setProjectPages([]); navigate(companyWorkspace ? (companyCommercial ? '/commercial/pursuits' : `/company/${route[1] || 'documents'}`) : '/projects'); };
  const refresh = () => { projects.refresh(); contextProject.refresh(); setDataRevision(value => value + 1); };
  const toggleNavigation = () => setMode(layoutRef.current?.isSideCollapsed() ? NavigationLayoutMode.Expanded : NavigationLayoutMode.Collapsed);
  const documentsPath = selectedProject ? `/projects/${encodeURIComponent(selectedProject.id)}/documents` : '/documents';
  const shellSession = !authRequested && !session.error && session.data?.authenticated ? session.data : undefined;
  const personName = shellSession?.person.display_name ?? 'Workspace session';
  const navKey = route[0] === 'company' ? `company-${route[1]}` : companyCommercial ? 'commercial' : route[0] === 'takeoff' || route[2] === 'takeoff' ? 'takeoff' : route[0] === 'estimates' || route[2] === 'estimates' ? 'estimates' : route[0] === 'documents' || route[2] === 'documents' ? 'documents' : route[0] === 'work' || route[2] === 'work' ? 'work' : route[0] === 'connections' ? 'connections' : 'projects';
  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <NavigationLayout ref={layoutRef} id="cipher-navigation" mode={mode} className="product-layout"
      header={<ShellBar id="cipher-shellbar" showSearchField={phoneLayout ? false : undefined} startButton={<Button icon="menu2" design="Transparent" accessibleName="Toggle navigation" onClick={toggleNavigation} />}
        branding={<ShellBarBranding logo={<img src="/cipher-mark.svg" alt="" />} onClick={() => navigate('/projects')}>Cipher <span className="shell-product-subtitle">The AEC/CMS Pro</span></ShellBarBranding>}
        content={<><div className="company-switch">{shellSession?.companies.length ? <Select accessibleName="Company" disabled={suggestionLocked} valueState="None" onChange={event => changeCompany(event.detail.selectedOption.value ?? company)}>{shellSession.companies.map(item => <Option key={item.id} value={item.id} selected={company === item.id}>{item.name}</Option>)}</Select> : null}</div><ShellBarSpacer />{shellSession?.site_mode === 'synthetic' && <Tag design="Set2" colorScheme="7">Synthetic workspace</Tag>}</>}
        searchField={<ShellBarSearch placeholder="Find a project" accessibleName="Search projects" onSearch={event => { setSearch(event.currentTarget!.value); navigate('/projects'); }} />}
        assistant={<ToggleButton icon="da" disabled={suggestionLocked} pressed={rickyOpen} accessibleName="Toggle Ricky assistant" tooltip="Ricky · AEC intelligence" onClick={() => setRickyOpen(value => !value)} />}
        profile={<Avatar initials={initials(personName)} accessibleName={personName} size="XS" />} onProfileClick={() => { if (shellSession) setProfileOpen(true); }} />}
      sideContent={<SideNavigation className="product-navigation" accessibleName="Cipher workspace navigation" onSelectionChange={event => { if (suggestionLocked) { event.preventDefault(); return; } const next = event.detail.item.dataset.path; if (next) { navigate(next); if (window.matchMedia('(max-width: 599px)').matches) { setMode(NavigationLayoutMode.Collapsed); document.getElementById('main-content')?.focus(); } } }} fixedItems={<SideNavigationItem text="Connections" icon="connected" selected={navKey === 'connections'} data-path="/connections" />}>
        <SideNavigationItem text="Projects" icon="building" selected={navKey === 'projects'} data-path="/projects" />
        {shellSession?.company_scopes.some(scope => scope.capabilities.includes('commercial.read')) && <SideNavigationItem text="Commercial" icon="sales-document" selected={navKey === 'commercial'} data-path="/commercial/pursuits" />}
        {shellSession?.company_scopes.some(scope => scope.capabilities.includes('document.read')) && <SideNavigationItem text="Company documents" icon="documents" selected={navKey === 'company-documents'} data-path="/company/documents" />}
        {shellSession?.company_scopes.some(scope => scope.capabilities.includes('estimate.read')) && <SideNavigationItem text="Company estimates" icon="simulate" selected={navKey === 'company-estimates'} data-path="/company/estimates" />}
        {shellSession?.company_scopes.some(scope => scope.capabilities.some(value => value.startsWith('approval.'))) && <SideNavigationItem text="Company approvals" icon="task" selected={navKey === 'company-work'} data-path="/company/work" />}
        {shellSession?.company_scopes.some(scope => scope.company === company && scope.capabilities.includes('company.read')) && <SideNavigationItem text="Company activity" icon="history" selected={navKey === 'company-activity'} data-path="/company/activity" />}
        {shellSession?.company_scopes.some(scope => scope.capabilities.includes('project.cost.read')) && <SideNavigationItem text="Cost setup" icon="settings" selected={navKey === 'company-costs'} data-path="/company/costs/codes" />}
        <SideNavigationItem text="Project work" icon="task" selected={navKey === 'work'} data-path="/work" />
        <SideNavigationItem text="Estimates" icon="simulate" selected={navKey === 'estimates'} data-path={selectedProject ? `/projects/${encodeURIComponent(selectedProject.id)}/estimates` : '/estimates'} />
        <SideNavigationItem text="Drawing takeoff" icon="measure" selected={navKey === 'takeoff'} data-path={selectedProject ? `/projects/${encodeURIComponent(selectedProject.id)}/takeoff` : '/takeoff'} />
        <SideNavigationItem text="Documents" icon="documents" selected={navKey === 'documents'} data-path={documentsPath} />
        <SideNavigationItem text="Ricky" icon="da" design="Action" unselectable onClick={() => { setRickyOpen(true); if (window.matchMedia('(max-width: 599px)').matches) setMode(NavigationLayoutMode.Collapsed); }} />
      </SideNavigation>}>
      <div className={`workspace-frame${rickyOpen ? ' with-assistant' : ''}`}>
        <div className="workspace-main" id="main-content" tabIndex={-1}>
          {session.loading ? <Loading label="Connecting to your workspace…" /> : authRequested || session.error?.status === 401 || (!session.error && !session.data?.authenticated) ? <SignIn onSignedIn={() => { setAuthRequested(false); session.refresh(); }} /> : session.error ? <WorkspaceUnavailable error={session.error} retry={session.refresh} /> : requestedCompanyDenied ? <div className="page"><Empty title="Company context unavailable" icon="locked">The Company in this link is unavailable with your current access. Choose an authorized Company to continue.</Empty></div> : !session.data?.companies.length ? <div className="page"><Empty title="No company access" icon="locked">Your workspace administrator can assign company and project access.</Empty></div> : <>
            <div className="workspace-context-bar"><div><Icon name="building" /><span>{companyLabel(session.data, company)}</span>{selectedProject && <><span className="context-separator">/</span><strong>{selectedProject.name}</strong></>}</div>{companyWorkspace ? <span className="caption">Company workspace</span> : <Select accessibleName="Project context" disabled={suggestionLocked} onChange={event => { const id = event.detail.selectedOption.value ?? ''; setProjectId(id); navigate(id ? `/projects/${encodeURIComponent(id)}` : '/projects'); }}><Option value="" selected={!selectedProject}>All projects</Option>{projects.data?.items.map(project => <Option key={project.id} value={project.id} selected={selectedProject?.id === project.id}>{project.name}</Option>)}</Select>}</div>
            {route[0] === 'company' && company ? <Suspense fallback={<Loading label="Opening Company workspace…" />}>{route[1] === 'activity' ? <CompanyActivity company={company} user={session.data.user} personId={session.data.person.id} capabilities={session.data.company_scopes.find(scope => scope.company === company)?.capabilities || []} navigationLocked={suggestionLocked} navigate={navigate} /> : route[1] === 'costs' ? <CostMasters key={`${company}/${route[2]}`} company={company} capabilities={session.data.company_scopes.find(scope => scope.company === company)?.capabilities || []} kind={route[2] === 'types' ? 'type' : 'code'} navigate={navigate} /> : route[1] === 'documents' ? <CompanyDocuments key={company} company={company} capabilities={session.data.company_scopes.find(scope => scope.company === company)?.capabilities || []} documentId={route[2]} revisionId={route[3] === 'revisions' ? route[4] : undefined} initialPage={Number.isInteger(citedPage) && citedPage > 0 ? citedPage : 1} navigate={navigate} /> : route[1] === 'estimates' ? <CompanyEstimates key={company} company={company} capabilities={session.data.company_scopes.find(scope => scope.company === company)?.capabilities || []} estimateId={route[2]} revisionId={new URLSearchParams(path.split('?')[1] || '').get('revision') || undefined} navigate={navigate} /> : <CompanyApprovals key={company} company={company} packetId={route[2]} navigate={navigate} />}</Suspense> : companyCommercial && company ? <Suspense fallback={<Loading label="Opening company commercial…" />}><Commercial key={company} company={company} personId={session.data.person.id} capabilities={session.data.company_scopes.find(scope => scope.company === company)?.capabilities || []} route={route} navigate={navigate} /></Suspense> : projects.loading && !projects.data ? <Loading label="Loading permitted projects…" /> : projects.error ? <div className="page"><Failure error={projects.error} onRetry={projects.refresh} /></div> : company && <>
              {route[0] === 'takeoff' || route[2] === 'takeoff' ? (contextId && contextProject.loading ? <Loading label="Opening takeoff project context…" /> : contextId && contextProject.error ? <div className="page"><Failure error={contextProject.error} onRetry={contextProject.refresh} /></div> : <Suspense fallback={<Loading />}><Takeoff company={company} project={contextProject.data} setId={route[3]} navigate={navigate} /></Suspense>)
                : route[0] === 'estimates' || route[2] === 'estimates' ? (contextId && contextProject.loading ? <Loading label="Opening estimating project context…" /> : contextId && contextProject.error ? <div className="page"><Failure error={contextProject.error} onRetry={contextProject.refresh} /></div> : <Estimates key={`${company}/${selectedProject?.id}/${route[3] || ''}`} company={company} project={contextProject.data} estimateId={route[3]} revisionId={new URLSearchParams(path.split('?')[1] || '').get('revision') || undefined} navigate={navigate} askRicky={() => setRickyOpen(true)} />)
                : route[0] === 'connections' ? <Connections session={session.data} />
                : route[0] === 'documents' && route[1] ? <DocumentPage key={`${company}/${path}`} company={company} documentId={route[1]} revisionId={route[2] === 'revisions' ? route[3] : undefined} initialPage={Number.isInteger(citedPage) && citedPage > 0 ? citedPage : 1} navigate={navigate} askRicky={id => { setProjectId(id); setRickyOpen(true); }} />
                : route[0] === 'documents' || route[2] === 'documents' ? <DocumentsPage key={`${company}/${selectedProject?.id ?? ''}`} company={company} projectId={selectedProject?.id} projectName={selectedProject?.name} navigate={navigate} canUpload={contextProject.data?.capabilities?.includes('document.write') ?? false} />
                : route[0] === 'work' || route[2] === 'work' ? <WorkPage key={`${company}/${selectedProject?.id}/${dataRevision}`} company={company} project={selectedProject} navigate={navigate} onEffect={() => { projects.refresh(); contextProject.refresh(); }} />
                : route[0] === 'projects' && routeProjectId ? <ProjectDetail key={`${company}/${routeProjectId}/${dataRevision}`} company={company} projectId={routeProjectId} navigate={navigate} refreshProjects={projects.refresh} onContext={project => setProjectId(project.id)} openRicky={() => setRickyOpen(true)} />
                : <ProjectRegister company={companyLabel(session.data, company)} projects={projects.data?.items ?? []} total={projects.data?.total ?? undefined} search={search} setSearch={setSearch} navigate={navigate} refresh={projects.refresh} pagination={{ next: projects.data?.next_cursor, page: projectPages.length + 1, previous: Boolean(projectPages.length), onNext: () => { if (projects.data?.next_cursor) { setProjectPages([...projectPages, projectCursor]); setProjectCursor(projects.data.next_cursor); } }, onPrevious: () => { setProjectCursor(projectPages[projectPages.length - 1]); setProjectPages(projectPages.slice(0, -1)); } }} />}
            </>}
          </>}
        </div>
        {rickyOpen && !requestedCompanyDenied && Boolean(company) && !session.loading && !authRequested && session.data?.authenticated && <RickyPanel key={`${session.data.user}/${session.data.person.id}/${companyWorkspace ? "Company" : "Project"}/${company}/${selectedProject?.id ?? ''}`} user={session.data.user} companyScope={companyWorkspace} companyCapabilities={session.data.company_scopes.find(scope => scope.company === company)?.capabilities || []} company={company} person={session.data.person.id} project={selectedProject} navigate={navigate} onClose={() => setRickyOpen(false)} onSuggestionLockedChange={setSuggestionLocked} onSaved={refresh} />}
      </div>
    </NavigationLayout>
    <Dialog open={profileOpen} headerText="Your workspace session" onClose={() => setProfileOpen(false)} footer={<Bar design="Footer" endContent={<><Button disabled={signingOut || suggestionLocked} onClick={async () => { if (suggestionLocked) return; setSigningOut(true); setProfileError(undefined); try { await api.signOut(); setProfileOpen(false); setAuthRequested(true); setRickyOpen(false); session.refresh(); } catch (error) { setProfileError(error as ApiError); } finally { setSigningOut(false); } }}>{signingOut ? 'Signing out…' : 'Sign out'}</Button><Button onClick={() => setProfileOpen(false)}>Close</Button></>} />}><div className="dialog-form">{profileError && <Failure error={profileError} />}<div className="profile-summary"><Avatar initials={initials(personName)} /><div><Title level="H3">{personName}</Title><p>{session.data?.user ?? 'Not signed in'}</p></div></div><p>Company and project permissions are supplied by your workspace.</p>{session.data?.site_mode === 'synthetic' && <MessageStrip design="Information" hideCloseButton>This workspace contains synthetic data.</MessageStrip>}</div></Dialog>
  </>;
}

function WorkspaceUnavailable({ error, retry }: { error: import('./api/client').ApiError; retry: () => void }) {
  return <div className="page connection-page"><div className="connection-illustration"><Icon name="disconnected" /></div><PageHeading eyebrow="CIPHER WORKSPACE" title={error.status === 401 ? 'Sign in to continue' : 'Your workspace is unavailable'} description="Your project data is loaded from your authenticated workspace." /><Failure error={error} onRetry={retry} /><p className="caption">This application does not substitute sample records when a connection fails.</p></div>;
}

function WorkPage({ company, project, navigate, onEffect }: { company: string; project?: Project; navigate: (path: string) => void; onEffect: () => void }) {
  const tasks = useResource(project ? `${company}/${project.id}/tasks` : null, signal => api.tasks(company, project!.id, signal));
  return <div className="page"><PageHeading eyebrow="PROJECT DELIVERY" title="Project work" description={project ? `Tasks, approvals and follow-up for ${project.name}.` : 'Choose a project to see its work.'} />
    {!project ? <div className="surface"><Empty title="Choose a project" icon="task" action={<Button design="Emphasized" onClick={() => navigate('/projects')}>Open projects</Button>}>Select a project from the context picker or project register.</Empty></div> : tasks.loading ? <Loading label="Loading tasks…" /> : tasks.error ? <Failure error={tasks.error} onRetry={tasks.refresh} /> : <section className="surface work-list"><Toolbar design="Transparent"><Title level="H2">Project tasks ({tasks.data?.items.length ?? 0})</Title><ToolbarSpacer /><Button onClick={() => navigate(`/projects/${encodeURIComponent(project.id)}`)}>Open project</Button></Toolbar>{tasks.data?.items.length ? tasks.data.items.map(task => <div className="work-item" key={task.id}><Icon name="task" /><div><strong>{task.subject}</strong><p>{task.description || task.id}</p></div><Status value={task.status} /></div>) : <Empty title="No tasks yet" icon="task">Create the first task from your project workspace.</Empty>}</section>}
    {project && <section className="surface work-approvals"><Approvals project={project} onEffect={onEffect} /></section>}
  </div>;
}

function Connections({ session }: { session: Session }) {
  const model = useResource('connections/model', signal => rpc<ModelStatus>('cipher_aec.ricky.api.connection_status', {}, false, signal));
  return <div className="page"><PageHeading eyebrow="WORKSPACE" title="Connections" description="Current availability of the services behind your work." actions={<Button icon="refresh" onClick={model.refresh}>Refresh</Button>} />
    <section className="surface connection-list"><div className="connection-item"><div className="connection-icon"><Icon name="database" /></div><div><h2>ERP workspace</h2><p>Authenticated business records, projects and tasks.</p></div><Status value="Connected" /></div><div className="connection-item"><div className="connection-icon"><Icon name="da" /></div><div><h2>Ricky local model</h2><p>{model.data?.message || 'The existing local model connection.'}</p></div>{model.loading ? <span className="caption">Checking…</span> : <Status value={model.data?.available ? 'Connected' : 'Unavailable'} />}</div>{model.error && <Failure error={model.error} onRetry={model.refresh} />}</section>
    <div className="document-policy"><strong>{session.site_mode === 'synthetic' ? 'Synthetic workspace' : 'Workspace access'}</strong><p>Connected records use your current company and project permissions. Ricky availability does not affect manual project work.</p></div>
  </div>;
}

function initials(name: string) { return name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(part => part[0]?.toUpperCase()).join('') || 'C'; }
function companyLabel(session: Session, company: string) { return session.companies.find(item => item.id === company)?.name ?? company; }
