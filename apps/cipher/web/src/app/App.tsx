import { useEffect, useRef, useState } from 'react';
import { Button, DrawerBody, DrawerHeader, DrawerHeaderTitle, OverlayDrawer, Select, Spinner } from '@fluentui/react-components';
import { BuildingMultipleRegular, DismissRegular, HomeRegular, NavigationRegular, SearchRegular, TaskListSquareLtrRegular } from '@fluentui/react-icons';
import { dataSource, loadWorkspace } from '../api/client';
import type { Workspace, Collection } from '../api/types';
import { practiceSentence } from '../copy/terms';
import { Home, ListPage, ProjectPage, CommitmentPage, BillPage, ApprovalPage, MissingPage } from '../features/pages';
import { AppLink, navigate, useLocation } from './navigation';
import { PageHeader } from '../ui/shared';
import '../theme/global.css';
import './features.css';

export function App() {
  const location = useLocation();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const searchFocusPending = useRef(false);
  const segments = location.split('?')[0].split('/').filter(Boolean).map(segment => {
    try { return decodeURIComponent(segment); } catch { return ''; }
  });
  const query = new URLSearchParams(location.split('?')[1]);
  const pathname = location.split('?')[0];
  const pending = workspace?.approvals.filter(a => a.status === 'pending').length ?? 0;
  const selectedProject = segments[0] === 'projects' && segments[1] ? segments[1]
    : segments[0] === 'commitments' ? workspace?.commitments.find(c => c.id === segments[1])?.projectId
    : segments[0] === 'bills' ? workspace?.bills.find(b => b.id === segments[1])?.projectId
    : segments[0] === 'approvals' ? workspace?.approvals.find(a => a.id === segments[1])?.projectId : '';

  useEffect(() => {
    const controller = new AbortController();
    setProblem(null);
    loadWorkspace(controller.signal).then(setWorkspace).catch(error => {
      if (!controller.signal.aborted) setProblem(error instanceof Error ? error.message : 'The practice workspace could not be read.');
    });
    return () => controller.abort();
  }, [retry]);
  useEffect(() => {
    setMenuOpen(false);
    const frame = requestAnimationFrame(() => {
      if (searchFocusPending.current) {
        document.querySelector<HTMLInputElement>('input[aria-label="Search projects"]')?.focus();
        searchFocusPending.current = false;
      } else document.querySelector<HTMLElement>('[data-page-heading]')?.focus({ preventScroll: true });
      window.scrollTo({ top: 0 });
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname]);
  function findProject() {
    searchFocusPending.current = true;
    if (window.location.pathname === '/projects') {
      navigate('/projects');
      requestAnimationFrame(() => { document.querySelector<HTMLInputElement>('input[aria-label="Search projects"]')?.focus(); searchFocusPending.current = false; });
    } else navigate('/projects');
  }
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); findProject(); }
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  const navigation = <nav className="cipher-navigation" aria-label="Main navigation">{[
    { label: 'Home', href: '/', Icon: HomeRegular, current: segments.length === 0 },
    { label: 'Approvals', href: '/approvals', Icon: TaskListSquareLtrRegular, current: segments[0] === 'approvals' },
    { label: 'Projects', href: '/projects', Icon: BuildingMultipleRegular, current: ['projects', 'commitments', 'bills'].includes(segments[0]) },
  ].map(({ label, href, Icon, current }) => <a key={label} href={href} className="cipher-nav-item" aria-current={current ? 'page' : undefined} aria-label={label === 'Approvals' ? `Approvals, ${pending} waiting for review` : label} title={label} onClick={event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey) { event.preventDefault(); navigate(href); } }}>
    <Icon aria-hidden="true" /><span className="cipher-nav-label">{label}</span>{label === 'Approvals' && pending > 0 && <span className="cipher-topbar-badge cipher-nav-count" aria-hidden="true">{pending}</span>}
  </a>)}</nav>;

  let page = <MissingPage />;
  if (workspace) {
    if (segments.length === 0) page = <Home workspace={workspace} />;
    else if (['projects', 'commitments', 'bills', 'approvals'].includes(segments[0]) && segments.length === 1) page = <ListPage key={segments[0]} workspace={workspace} collection={segments[0] as Collection} initialStatus={query.get('status') ?? 'all'} initialSearch={query.get('search') ?? ''} />;
    else if (segments[0] === 'projects') {
      const project = workspace.projects.find(p => p.id === segments[1]);
      const tab = segments[2] ?? 'overview';
      if (project && ['overview', 'commitments', 'bills', 'approvals'].includes(tab)) page = <ProjectPage workspace={workspace} project={project} tab={tab} />;
    } else if (segments[0] === 'commitments') {
      const record = workspace.commitments.find(c => c.id === segments[1]);
      if (record) page = <CommitmentPage workspace={workspace} commitment={record} />;
    } else if (segments[0] === 'bills') {
      const record = workspace.bills.find(b => b.id === segments[1]);
      if (record) page = <BillPage workspace={workspace} bill={record} />;
    } else if (segments[0] === 'approvals') {
      const record = workspace.approvals.find(a => a.id === segments[1]);
      if (record) page = <ApprovalPage workspace={workspace} approval={record} />;
    }
  }
  return <div className="cipher-shell">
    <a className="cipher-skip-link" href="#main-content">Skip to content</a>
    <header className="cipher-topbar">
      <Button ref={menuTrigger} appearance="subtle" className="cipher-topbar-button cipher-mobile-only" icon={<NavigationRegular />} aria-label="Open navigation" onClick={() => setMenuOpen(true)} />
      <AppLink href="/" className="cipher-wordmark" label="Cipher home"><span className="cipher-mark">S&A</span> Cipher</AppLink>
      {workspace && <label className="cipher-project-picker"><span className="cipher-visually-hidden">Choose a project</span><Select aria-label="Choose a project" value={selectedProject ?? ''} onChange={(_, data) => {
        if (!data.value) { navigate('/projects'); return; }
        const tab = segments[0] === 'projects' && segments[2] ? `/${segments[2]}` : '';
        navigate(`/projects/${encodeURIComponent(data.value)}${tab}`);
      }}><option value="">All projects</option>{workspace.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></label>}
      <div className="cipher-topbar-spacer" />
      <Button appearance="subtle" className="cipher-topbar-button" icon={<SearchRegular />} aria-label="Find a project, Control K" onClick={findProject}><span className="cipher-desktop-only">Find a project</span></Button>
      <span className="cipher-read-only cipher-desktop-only">Read-only practice</span>
    </header>
    <aside className="cipher-rail">{navigation}</aside>
    <div className="cipher-workspace"><div className="cipher-practice-strip"><span>{practiceSentence}</span><span className="cipher-source-label">{dataSource === 'fixture' ? 'Sample fixture' : 'Practice workspace'}</span></div>
      <main id="main-content" className="cipher-main" tabIndex={-1} aria-busy={!workspace && !problem}>
        {problem ? <><PageHeader title="The practice workspace did not load" /><p role="alert">{problem}</p><p className="cipher-loading-help">Start the local practice server, then try again. Sample data is available only in the explicit fixture mode.</p><Button appearance="primary" onClick={() => setRetry(value => value + 1)}>Try again</Button></>
          : workspace ? page : <div className="cipher-loading"><Spinner label="Loading the practice workspace" /></div>}
      </main>
      {workspace && <footer className="cipher-workspace-footer">Synthetic records. Refreshed {workspace.loadedAt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}. <Button appearance="subtle" onClick={() => setRetry(value => value + 1)}>Refresh read views</Button></footer>}
    </div>
    <OverlayDrawer open={menuOpen} onOpenChange={(_, data) => { setMenuOpen(data.open); if (!data.open) requestAnimationFrame(() => menuTrigger.current?.focus()); }} position="start" size="small" className="cipher-mobile-navigation">
      <DrawerHeader><DrawerHeaderTitle action={<Button appearance="subtle" icon={<DismissRegular />} aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}>Cipher navigation</DrawerHeaderTitle></DrawerHeader>
      <DrawerBody>{navigation}</DrawerBody>
    </OverlayDrawer>
  </div>;
}
