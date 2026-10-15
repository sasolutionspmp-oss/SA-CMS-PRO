import { useEffect, useRef, useState } from 'react';
import { Button, DrawerBody, DrawerHeader, DrawerHeaderTitle, OverlayDrawer, Select, Spinner } from '@fluentui/react-components';
import { BookRegular, BuildingMultipleRegular, DismissRegular, NavigationRegular, PersonRegular, TaskListSquareLtrRegular } from '@fluentui/react-icons';
import { AppLink, navigate, useLocation } from '../app/navigation';
import { abortScopedReads, bindSession, ARError, endSession, readPersonas, readProjects, readSession } from './client';
import { ARMemory } from './Memory';
import { AgingPage, ApprovalPage, BasesPage, BillPage, BillsPage, PreparationPage, ProjectsPage, ReviewsPage, SendPreparationPage } from './pages';
import { ARHeader } from './presentation';
import type { Persona, PersonaId, Project, Session } from './types';
import '../theme/global.css';
import '../app/features.css';
import '../ap/ap.css';
import './ar.css';

export function ARApp() {
  const location = useLocation(); const [session, setSession] = useState<Session | null>(null); const [personas, setPersonas] = useState<Persona[]>([]);
  const [projects, setProjects] = useState<Project[] | null>(null); const [problem, setProblem] = useState<Error | null>(null);
  const [boot, setBoot] = useState(0); const [revision, setRevision] = useState(0); const [busy, setBusy] = useState(false); const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null); const projectRead = useRef<AbortController | null>(null);
  const pathname = location.split('?')[0]; const query = location.split('?')[1] ?? '';
  const parts = pathname.split('/').filter(Boolean).map(part => { try { return decodeURIComponent(part); } catch { return ''; } });
  const personId = session?.person?.id ?? '';
  function sessionLost() {
    projectRead.current?.abort(); abortScopedReads(); setSession(null); setProjects(null); setProblem(new Error('Your AR practice session ended. Choose a registered practice person to continue.')); setBoot(value => value + 1);
  }
  function refresh() { setRevision(value => value + 1); }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([readSession(controller.signal), readPersonas(controller.signal)]).then(([current, options]) => {
      if (controller.signal.aborted) return; setSession(current); setPersonas(options); setProblem(null);
    }).catch(error => { if (!controller.signal.aborted) setProblem(error instanceof Error ? error : new Error('The AR session could not be started.')); });
    return () => controller.abort();
  }, [boot]);
  useEffect(() => {
    if (!personId || busy) { setProjects(null); return; }
    const controller = new AbortController(); projectRead.current = controller;
    Promise.all([readProjects(controller.signal), readSession(controller.signal)]).then(([rows, current]) => {
      if (controller.signal.aborted) return;
      if (!current.authenticated || current.person?.id !== personId) { sessionLost(); return; }
      setSession(current); setProjects(rows.items); setProblem(null);
    }).catch(error => {
      if (controller.signal.aborted || error instanceof Error && error.name === 'AbortError') return;
      setProjects(null); if (error instanceof ARError && error.status === 401) sessionLost(); else setProblem(error instanceof Error ? error : new Error('Current AR project scope could not be read.'));
    });
    return () => controller.abort();
  }, [personId, revision, busy]);
  useEffect(() => {
    setMenuOpen(false); const frame = requestAnimationFrame(() => { document.querySelector<HTMLElement>('[data-page-heading]')?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); });
    return () => cancelAnimationFrame(frame);
  }, [pathname, personId, !!projects]);
  async function choose(personaId: PersonaId) {
    if (!session || busy) return; projectRead.current?.abort(); abortScopedReads(); setBusy(true); setProjects(null); setProblem(null);
    try { setSession(await bindSession(personaId, session.csrfToken)); navigate('/owner-bills'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The registered practice person could not be selected.')); if (error instanceof ARError && error.status === 401) sessionLost(); }
    finally { setBusy(false); }
  }
  async function changePerson() {
    if (!session || busy) return; projectRead.current?.abort(); abortScopedReads(); setBusy(true); setProjects(null); setProblem(null);
    try { setSession(await endSession(session.csrfToken)); setRevision(0); navigate('/'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The AR session could not be ended.')); sessionLost(); }
    finally { setBusy(false); }
  }
  const nav = <nav className="cipher-navigation" aria-label="Main navigation">{[
    { href: '/owner-bills', name: 'Owner bills', Icon: BookRegular, current: !parts.length || parts[0] === 'owner-bills' || parts[0] === 'ar-practice.html' },
    { href: '/owner-bill-approvals', name: 'Owner bill reviews', Icon: TaskListSquareLtrRegular, current: parts[0] === 'owner-bill-approvals' },
    { href: '/owner-send-approvals', name: 'Owner send reviews', Icon: TaskListSquareLtrRegular, current: parts[0] === 'owner-send-approvals' },
    { href: '/owner-bases', name: 'Owner contract bases', Icon: BookRegular, current: parts[0] === 'owner-bases' },
    { href: '/ar-aging', name: 'AR aging', Icon: BookRegular, current: parts[0] === 'ar-aging' },
    { href: '/retainage-aging', name: 'Retainage aging', Icon: BookRegular, current: parts[0] === 'retainage-aging' },
    { href: '/projects', name: 'Projects', Icon: BuildingMultipleRegular, current: parts[0] === 'projects' },
  ].map(({ href, name, Icon, current }) => <a key={href} href={href} title={name} className="cipher-nav-item" aria-current={current ? 'page' : undefined} onClick={event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey) { event.preventDefault(); navigate(href); } }}><Icon aria-hidden="true" /><span className="cipher-nav-label">{name}</span></a>)}</nav>;
  const controls = session ? { session, onChanged: refresh, onSessionLost: sessionLost } : null;
  let content = <><ARHeader title="AR record unavailable" /><p>This route does not identify a record in the current AR entry.</p><AppLink href="/owner-bills">Open current owner bills</AppLink></>;
  if (controls && projects) {
    if (!parts.length || parts[0] === 'ar-practice.html' || parts[0] === 'owner-bills' && parts.length === 1) content = <BillsPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'projects' && parts.length === 1) content = <ProjectsPage revision={revision} {...controls} />;
    else if (parts[0] === 'owner-bases' && parts.length === 1) content = <BasesPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-bases' && parts[2] === 'preparation' && parts.length === 3) content = <PreparationPage key={parts[1]} basisId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-bills' && parts.length === 2) content = <BillPage key={parts[1]} billId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-bills' && parts[2] === 'send-preparation' && parts.length === 3) content = <SendPreparationPage key={parts[1]} billId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-bill-approvals' && parts.length === 1) content = <ReviewsPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-send-approvals' && parts.length === 1) content = <ReviewsPage send query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-bill-approvals' && parts.length === 2) content = <ApprovalPage key={parts[1]} approvalId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'owner-send-approvals' && parts.length === 2) content = <ApprovalPage key={parts[1]} send approvalId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'ar-aging') content = <AgingPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'retainage-aging') content = <AgingPage retainage query={query} revision={revision} {...controls} />;
  }
  return <div className="cipher-shell"><a className="cipher-skip-link" href="#main-content">Skip to content</a>
    <header className="cipher-topbar">{personId && <Button ref={menuTrigger} appearance="subtle" className="cipher-topbar-button cipher-mobile-only" icon={<NavigationRegular />} aria-label="Open navigation" onClick={() => setMenuOpen(true)} />}
      <AppLink href="/owner-bills" className="cipher-wordmark" label="Cipher AR home"><span className="cipher-mark">S&A</span> Cipher</AppLink>
      {projects && <label className="cipher-project-picker"><span className="cipher-visually-hidden">Choose an AR project</span><Select aria-label="Choose an AR project" value={new URLSearchParams(query).get('projectId') ?? ''} onChange={(_, data) => navigate(data.value ? `/owner-bases?projectId=${encodeURIComponent(data.value)}` : '/owner-bases')}><option value="">All projects</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></label>}
      <div className="cipher-topbar-spacer" />{personId && <><span className="cipher-ap-session-person">{session?.person?.displayName}</span><Button appearance="subtle" className="cipher-topbar-button" icon={<PersonRegular />} aria-label="Change practice person" disabled={busy} onClick={changePerson}><span className="cipher-desktop-only">Change person</span></Button></>}
    </header><aside className="cipher-rail">{personId && nav}</aside>
    <div className="cipher-workspace ar-workspace"><div className="cipher-practice-strip"><span>Practice data. Nothing here is real money and nothing is sent.</span><span className="cipher-source-label">Disposable AR practice</span></div>
      <main id="main-content" className="cipher-main" tabIndex={-1} aria-busy={(!session || !!personId && !projects) && !problem}>
        {problem && <div role="alert" className="cipher-message cipher-message-negative"><div><p>{problem.message}</p><Button onClick={() => session ? refresh() : setBoot(value => value + 1)}>Refresh practice session</Button></div></div>}
        {!session ? <><ARHeader title="Start an AR practice session" />{!problem && <Spinner label="Reading the local AR session" />}</>
          : !session.authenticated ? <><ARHeader title="Start an AR practice session" subtitle="Choose one registered synthetic person to explore owner billing, independent posting and synthetic mail-sink review." /><p>This practice selection does not establish real staff identity or Microsoft sign-in.</p><div className="ar-personas">{personas.map(persona => <div className="cipher-ap-persona" key={persona.personaId}><h2>{persona.displayName}</h2><p>Registered synthetic AR person</p><Button disabled={busy} onClick={() => choose(persona.personaId)}>Start as {persona.displayName}</Button></div>)}</div><p className="cipher-caption">Restarting the isolated server discards sessions and practice records.</p></>
            : projects ? <ARMemory key={`${personId}:${session.duties.join(',')}:${session.projectIds.slice().sort().join(',')}`}>{content}</ARMemory>
              : <><ARHeader title="Reading your AR project scope" />{!problem && <Spinner label="Reading current actual project duties" />}</>}
      </main>{projects && <footer className="cipher-workspace-footer">Synthetic owner billing and current standing receivables.<Button appearance="subtle" onClick={refresh}>Refresh scoped records</Button></footer>}
    </div>
    <OverlayDrawer open={menuOpen} onOpenChange={(_, data) => { setMenuOpen(data.open); if (!data.open) requestAnimationFrame(() => menuTrigger.current?.focus()); }} position="start" size="small" className="cipher-mobile-navigation"><DrawerHeader><DrawerHeaderTitle action={<Button appearance="subtle" icon={<DismissRegular />} aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}>Cipher navigation</DrawerHeaderTitle></DrawerHeader><DrawerBody>{nav}</DrawerBody></OverlayDrawer>
  </div>;
}
