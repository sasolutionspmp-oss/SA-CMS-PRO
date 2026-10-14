import { useEffect, useRef, useState } from 'react';
import { Button, DrawerBody, DrawerHeader, DrawerHeaderTitle, OverlayDrawer, Select, Spinner } from '@fluentui/react-components';
import {
  BookRegular, BuildingMultipleRegular, DismissRegular, HomeRegular, NavigationRegular,
  PersonRegular, SearchRegular, TaskListSquareLtrRegular,
} from '@fluentui/react-icons';
import { AppLink, navigate, useLocation } from '../app/navigation';
import { APError, abortScopedReads, bindSession, endSession, loadWorkspace, readPersonas, readSession } from './client';
import { APHeader } from './presentation';
import { APApproval, APBill, APCommitment, APHome, APList, APMissing, APPostingQueue, APProject } from './pages';
import { APIntakeList, APInvoice, APMatchReview, APPreparation } from './intake-pages';
import { APBillExceptions, APCorrectionList, APCorrectionReview, APInvoiceExceptions } from './exception-pages';
import type { Persona, Session, Workspace } from './types';
import { ActionMemory } from './ActionMemory';
import '../theme/global.css';
import '../app/features.css';
import './ap.css';

const practiceSentence = 'Practice data. Nothing here is real money and nothing is sent.';
export function APApp() {
  const location = useLocation();
  const [session, setSession] = useState<Session | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [problem, setProblem] = useState<Error | null>(null);
  const [boot, setBoot] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const workspaceRead = useRef<AbortController | null>(null);
  const pathname = location.split('?')[0];
  const parts = pathname.split('/').filter(Boolean).map(part => { try { return decodeURIComponent(part); } catch { return ''; } });
  const query = new URLSearchParams(location.split('?')[1]);
  const personId = session?.person?.id ?? '';
  function sessionLost() {
    workspaceRead.current?.abort(); abortScopedReads();
    setSessionNotice('Your practice session ended. Choose a practice person to continue.');
    setWorkspace(null); setSession(null); setProblem(new Error('Your practice session ended. Choose a practice person to continue.'));
    setBoot(value => value + 1);
  }
  function refresh() { setRevision(value => value + 1); }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([readSession(controller.signal), readPersonas(controller.signal)]).then(([current, options]) => {
      if (controller.signal.aborted) return;
      setSession(current); setPersonas(options); setProblem(null);
    }).catch(error => { if (!controller.signal.aborted) setProblem(error instanceof Error ? error : new Error('The AP practice session could not be started.')); });
    return () => controller.abort();
  }, [boot]);
  useEffect(() => {
    if (!personId || busy) { setWorkspace(null); return; }
    const controller = new AbortController();
    workspaceRead.current = controller;
    Promise.all([loadWorkspace(controller.signal), readSession(controller.signal)]).then(([value, current]) => {
      if (controller.signal.aborted) return;
      if (!current.authenticated || current.person?.id !== personId) { sessionLost(); return; }
      setSession(current); setWorkspace(value); setProblem(null);
    }).catch(error => {
      if (controller.signal.aborted || error instanceof Error && error.name === 'AbortError') return;
      if (error instanceof APError && error.status === 401) sessionLost();
      else { if (error instanceof APError && [403, 404].includes(error.status)) setWorkspace(null); setProblem(error instanceof Error ? error : new Error('The scoped practice records could not be loaded.')); }
    });
    return () => controller.abort();
  }, [personId, revision, busy]);
  useEffect(() => {
    setMenuOpen(false);
    const frame = requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('[data-page-heading]')?.focus({ preventScroll: true }); window.scrollTo({ top: 0 });
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname, personId, !!workspace]);
  function findProject() {
    navigate('/projects'); requestAnimationFrame(() => document.querySelector<HTMLInputElement>('input[aria-label="Search projects"]')?.focus());
  }
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (personId && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); findProject(); }
    }
    window.addEventListener('keydown', shortcut); return () => window.removeEventListener('keydown', shortcut);
  }, [personId]);
  async function choosePerson(personaId: string) {
    if (!session || busy) return;
    workspaceRead.current?.abort(); abortScopedReads();
    setBusy(true); setProblem(null); setWorkspace(null); setSessionNotice(null);
    try { const current = await bindSession(personaId, session.csrfToken); setSession(current); navigate('/'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The practice person could not be selected.')); if (error instanceof APError && error.status === 401) sessionLost(); }
    finally { setBusy(false); }
  }
  async function changePerson() {
    if (!session || busy) return;
    workspaceRead.current?.abort(); abortScopedReads();
    setBusy(true); setWorkspace(null); setProblem(null); setSessionNotice(null);
    try { const current = await endSession(session.csrfToken); setSession(current); setRevision(0); navigate('/'); }
    catch (error) { sessionLost(); setProblem(error instanceof Error ? error : new Error('The practice session could not be ended.')); }
    finally { setBusy(false); }
  }
  const nav = <nav className="cipher-navigation" aria-label="Main navigation">{[
    { href: '/', name: 'Home', Icon: HomeRegular, current: parts.length === 0 },
    { href: '/approvals', name: 'Business reviews', Icon: TaskListSquareLtrRegular, current: parts[0] === 'approvals' },
    { href: '/invoices', name: 'Invoices', Icon: BookRegular, current: parts[0] === 'invoices' },
    { href: '/match-approvals', name: 'Match reviews', Icon: TaskListSquareLtrRegular, current: parts[0] === 'match-approvals' },
    { href: '/correction-approvals', name: 'Correction reviews', Icon: TaskListSquareLtrRegular, current: parts[0] === 'correction-approvals' },
    { href: '/projects', name: 'Projects', Icon: BuildingMultipleRegular, current: ['projects', 'commitments', 'bills'].includes(parts[0]) },
    ...(session?.duties.includes('accountant') ? [{ href: '/posting-queue', name: 'Post approved bills', Icon: BookRegular, current: parts[0] === 'posting-queue' }] : []),
  ].map(({ href, name, Icon, current }) => <a key={href} href={href} className="cipher-nav-item" aria-current={current ? 'page' : undefined} title={name} onClick={event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey) { event.preventDefault(); navigate(href); } }}><Icon aria-hidden="true" /><span className="cipher-nav-label">{name}</span></a>)}</nav>;
  let content = <APMissing />;
  if (workspace && session) {
    if (!parts.length || parts[0] === 'ap-practice.html') content = <APHome workspace={workspace} session={session} />;
    else if (['projects', 'commitments', 'bills', 'approvals'].includes(parts[0]) && parts.length === 1) content = <APList workspace={workspace} collection={parts[0] as 'projects' | 'commitments' | 'bills' | 'approvals'} search={query.get('search') ?? ''} status={query.get('status') ?? 'all'} />;
    else if (['invoices', 'match-approvals'].includes(parts[0]) && parts.length === 1) content = <APIntakeList workspace={workspace} collection={parts[0] as 'invoices' | 'match-approvals'} search={query.get('search') ?? ''} status={query.get('status') ?? 'all'} />;
    else if (parts[0] === 'invoices' && parts.length === 2 && workspace.invoices.some(row => row.id === parts[1])) content = <APInvoice key={parts[1]} invoiceId={parts[1]} revision={revision} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    else if (parts[0] === 'invoices' && parts[2] === 'exceptions' && parts.length === 3 && workspace.invoices.some(row => row.id === parts[1])) content = <APInvoiceExceptions key={parts[1]} invoiceId={parts[1]} revision={revision} workspace={workspace} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    else if (parts[0] === 'match-approvals' && parts.length === 2 && workspace.matchApprovals.some(row => row.id === parts[1])) content = <APMatchReview key={parts[1]} approvalId={parts[1]} revision={revision} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    else if (parts[0] === 'correction-approvals' && parts.length === 1) content = <APCorrectionList revision={revision} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    else if (parts[0] === 'correction-approvals' && parts.length === 2) content = <APCorrectionReview key={parts[1]} approvalId={parts[1]} revision={revision} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    else if (parts[0] === 'posting-queue' && session.duties.includes('accountant')) content = <APPostingQueue workspace={workspace} />;
    else if (parts[0] === 'projects') {
      const project = workspace.projects.find(row => row.id === parts[1]); const tab = parts[2] ?? 'overview';
      if (project && ['overview', 'commitments', 'bills', 'approvals'].includes(tab)) content = <APProject project={project} workspace={workspace} tab={tab} />;
    } else if (parts[0] === 'commitments') {
      const record = workspace.commitments.find(row => row.id === parts[1]);
      if (record && ['prepare-bill', 'receive-invoice'].includes(parts[2])) content = <APPreparation key={`${record.id}:${parts[2]}`} commitmentId={record.id} revision={revision} workspace={workspace} receive={parts[2] === 'receive-invoice'} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
      else if (record && parts.length === 2) content = <APCommitment commitment={record} workspace={workspace} />;
    } else if (parts[0] === 'bills') {
      const record = workspace.bills.find(row => row.id === parts[1]);
      if (record && parts[2] === 'exceptions' && parts.length === 3) content = <APBillExceptions key={record.id} billId={record.id} revision={revision} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
      else if (record && parts.length === 2) content = <APBill key={record.id} bill={record} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    } else if (parts[0] === 'approvals') {
      if (workspace.approvals.some(row => row.id === parts[1])) content = <APApproval key={parts[1]} approvalId={parts[1]} revision={revision} session={session} onChanged={refresh} onSessionLost={sessionLost} />;
    }
  }
  const selectedProject = parts[0] === 'projects' ? parts[1] : parts[0] === 'bills' ? workspace?.bills.find(row => row.id === parts[1])?.projectId : parts[0] === 'commitments' ? workspace?.commitments.find(row => row.id === parts[1])?.projectId : '';
  return <div className="cipher-shell">
    <a className="cipher-skip-link" href="#main-content">Skip to content</a>
    <header className="cipher-topbar">
      {personId && <Button ref={menuTrigger} appearance="subtle" className="cipher-topbar-button cipher-mobile-only" icon={<NavigationRegular />} aria-label="Open navigation" onClick={() => setMenuOpen(true)} />}
      <AppLink href="/" className="cipher-wordmark" label="Cipher home"><span className="cipher-mark">S&A</span> Cipher</AppLink>
      {workspace && <label className="cipher-project-picker"><span className="cipher-visually-hidden">Choose a project</span><Select aria-label="Choose a project" value={selectedProject ?? ''} onChange={(_, data) => navigate(data.value ? `/projects/${encodeURIComponent(data.value)}` : '/projects')}><option value="">All projects</option>{workspace.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></label>}
      <div className="cipher-topbar-spacer" />
      {personId && <><Button appearance="subtle" className="cipher-topbar-button cipher-desktop-only" icon={<SearchRegular />} aria-label="Find a project, Control K" onClick={findProject}>Find a project</Button><span className="cipher-ap-session-person">{session?.person?.displayName}</span><Button appearance="subtle" icon={<PersonRegular />} className="cipher-topbar-button" aria-label="Change practice person" disabled={busy} onClick={changePerson}><span className="cipher-desktop-only">Change person</span></Button></>}
    </header>
    <aside className="cipher-rail">{personId && nav}</aside>
    <div className="cipher-workspace"><div className="cipher-practice-strip"><span>{practiceSentence}</span><span className="cipher-source-label">Disposable AP practice</span></div>
      <main id="main-content" className="cipher-main" tabIndex={-1} aria-busy={(!session || (!!personId && !workspace)) && !problem}>
        {problem && <div role="alert" className="cipher-message cipher-message-negative"><div><p>{problem.message}</p><Button appearance="subtle" onClick={() => session ? refresh() : setBoot(value => value + 1)}>Refresh practice session</Button></div></div>}
        {!session ? <><APHeader title="Start a practice session" />{!problem && <Spinner label="Loading the local practice session" />}</>
          : !session.authenticated ? <><APHeader title="Start a practice session" subtitle="Choose a registered synthetic person to explore the AP workflow." /><div className="cipher-ap-session">{sessionNotice && <p role="status">{sessionNotice}</p>}<p>This selection establishes a disposable local practice session. Microsoft sign-in is not configured here.</p><div className="cipher-ap-personas">{personas.map(persona => <div className="cipher-ap-persona" key={persona.personaId}><h2>{persona.displayName}</h2><p>Registered synthetic practice person</p><Button appearance="secondary" disabled={busy} onClick={() => choosePerson(persona.personaId)}>Start as {persona.displayName}</Button></div>)}</div><p className="cipher-caption">Sessions expire after 30 minutes idle or 8 hours total. Restarting this server discards all sessions and practice records.</p></div></>
            : workspace ? <ActionMemory key={`${personId}:${session.duties.join(',')}:${workspace.projects.map(project => project.id).sort().join(',')}`}>{content}</ActionMemory> : <><APHeader title={problem ? 'Your practice projects are unavailable' : 'Loading your practice projects'} />{!problem && <Spinner label="Reading your current project scope" />}</>}
      </main>
      {workspace && <footer className="cipher-workspace-footer">Synthetic records. Refreshed {workspace.loadedAt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}.<Button appearance="subtle" onClick={refresh}>Refresh scoped records</Button></footer>}
    </div>
    <OverlayDrawer open={menuOpen} onOpenChange={(_, data) => { setMenuOpen(data.open); if (!data.open) requestAnimationFrame(() => menuTrigger.current?.focus()); }} position="start" size="small" className="cipher-mobile-navigation"><DrawerHeader><DrawerHeaderTitle action={<Button appearance="subtle" icon={<DismissRegular />} aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}>Cipher navigation</DrawerHeaderTitle></DrawerHeader><DrawerBody>{nav}</DrawerBody></OverlayDrawer>
  </div>;
}
