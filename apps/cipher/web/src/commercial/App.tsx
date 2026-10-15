import { useEffect, useRef, useState } from 'react';
import { Button, DrawerBody, DrawerHeader, DrawerHeaderTitle, OverlayDrawer, Select, Spinner } from '@fluentui/react-components';
import { BookRegular, BuildingMultipleRegular, DismissRegular, NavigationRegular, PersonRegular, TaskListSquareLtrRegular } from '@fluentui/react-icons';
import { AppLink, navigate, useLocation } from '../app/navigation';
import { abortScopedReads, bindSession, CommercialError, endSession, readPersonas, readProjects, readSession } from './client';
import { CommercialMemory } from './Memory';
import { AcceptanceListPage, AcceptancePage, CommitmentPage, EstimateEntryPage, EstimatePage, EstimateRevisionPage, EstimatesPage, HandoffListPage, HandoffPage, HandoffPreparationPage, ProjectsPage } from './pages';
import { CommercialHeader } from './presentation';
import type { Persona, PersonaId, ProjectRow, Session } from './types';
import '../theme/global.css';
import '../app/features.css';
import '../ap/ap.css';
import './commercial.css';

export function CommercialApp() {
  const location = useLocation(); const [session, setSession] = useState<Session | null>(null); const [personas, setPersonas] = useState<Persona[]>([]);
  const [projects, setProjects] = useState<ProjectRow[] | null>(null); const [problem, setProblem] = useState<Error | null>(null);
  const [boot, setBoot] = useState(0); const [revision, setRevision] = useState(0); const [busy, setBusy] = useState(false); const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null); const projectRead = useRef<AbortController | null>(null);
  const pathname = location.split('?')[0]; const query = location.split('?')[1] ?? '';
  const parts = pathname.split('/').filter(Boolean).map(part => { try { return decodeURIComponent(part); } catch { return ''; } });
  const personId = session?.person?.id ?? '';
  function sessionLost() {
    projectRead.current?.abort(); abortScopedReads(); setSession(null); setProjects(null); setProblem(new Error('Your commercial practice session ended. Choose a registered practice person to continue.')); setBoot(value => value + 1);
  }
  function refresh() { setRevision(value => value + 1); }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([readSession(controller.signal), readPersonas(controller.signal)]).then(([current, options]) => {
      if (controller.signal.aborted) return; setSession(current); setPersonas(options); setProblem(null);
    }).catch(error => { if (!controller.signal.aborted) setProblem(error instanceof Error ? error : new Error('The commercial session could not be started.')); });
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
      setProjects(null); if (error instanceof CommercialError && error.status === 401) sessionLost(); else setProblem(error instanceof Error ? error : new Error('Current commercial project scope could not be read.'));
    });
    return () => controller.abort();
  }, [personId, revision, busy]);
  useEffect(() => {
    setMenuOpen(false); const frame = requestAnimationFrame(() => { document.querySelector<HTMLElement>('[data-page-heading]')?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); });
    return () => cancelAnimationFrame(frame);
  }, [pathname, personId, !!projects]);
  async function choose(personaId: PersonaId) {
    if (!session || busy) return; projectRead.current?.abort(); abortScopedReads(); setBusy(true); setProjects(null); setProblem(null);
    try { setSession(await bindSession(personaId, session.csrfToken)); navigate('/estimates'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The registered practice person could not be selected.')); if (error instanceof CommercialError && error.status === 401) sessionLost(); }
    finally { setBusy(false); }
  }
  async function changePerson() {
    if (!session || busy) return; projectRead.current?.abort(); abortScopedReads(); setBusy(true); setProjects(null); setProblem(null);
    try { setSession(await endSession(session.csrfToken)); setRevision(0); navigate('/'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The commercial session could not be ended.')); sessionLost(); }
    finally { setBusy(false); }
  }
  const nav = <nav className="cipher-navigation" aria-label="Main navigation">{[
    { href: '/estimates', name: 'Estimates', Icon: BookRegular, current: !parts.length || parts[0] === 'estimates' || parts[0] === 'commercial-practice.html' },
    { href: '/estimate-approvals', name: 'Acceptance reviews', Icon: TaskListSquareLtrRegular, current: parts[0] === 'estimate-approvals' },
    { href: '/estimate-handoffs', name: 'Estimate handoffs', Icon: BookRegular, current: ['estimate-handoffs', 'commercial-commitments'].includes(parts[0]) },
    { href: '/projects', name: 'Projects', Icon: BuildingMultipleRegular, current: parts[0] === 'projects' },
  ].map(({ href, name, Icon, current }) => <a key={href} href={href} title={name} className="cipher-nav-item" aria-current={current ? 'page' : undefined} onClick={event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey) { event.preventDefault(); navigate(href); } }}><Icon aria-hidden="true" /><span className="cipher-nav-label">{name}</span></a>)}</nav>;
  const controls = session ? { session, onChanged: refresh, onSessionLost: sessionLost } : null;
  let content = <><CommercialHeader title="Commercial record unavailable" /><p>This route does not identify a record in the current commercial entry.</p><AppLink href="/estimates">Open current estimates</AppLink></>;
  if (controls && projects) {
    if (!parts.length || parts[0] === 'commercial-practice.html' || parts[0] === 'estimates' && parts.length === 1) content = <EstimatesPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'projects' && parts.length === 1) content = <ProjectsPage revision={revision} {...controls} />;
    else if (parts[0] === 'projects' && parts[2] === 'estimate-preparation' && parts.length === 3) content = <EstimateEntryPage key={parts[1]} projectId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'estimates' && parts.length === 2) content = <EstimatePage key={parts[1]} estimateId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'estimates' && parts[2] === 'revise' && parts.length === 3) content = <EstimateRevisionPage key={parts[1]} estimateId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'estimates' && parts[2] === 'handoff-preparation' && parts.length === 3) content = <HandoffPreparationPage key={parts[1]} estimateId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'estimate-approvals' && parts.length === 1) content = <AcceptanceListPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'estimate-approvals' && parts.length === 2) content = <AcceptancePage key={parts[1]} approvalId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'estimate-handoffs' && parts.length === 1) content = <HandoffListPage query={query} revision={revision} {...controls} />;
    else if (parts[0] === 'estimate-handoffs' && parts.length === 2) content = <HandoffPage key={parts[1]} handoffId={parts[1]} revision={revision} {...controls} />;
    else if (parts[0] === 'commercial-commitments' && parts.length === 2) content = <CommitmentPage key={parts[1]} commitmentId={parts[1]} revision={revision} {...controls} />;
  }
  return <div className="cipher-shell"><a className="cipher-skip-link" href="#main-content">Skip to content</a>
    <header className="cipher-topbar">{personId && <Button ref={menuTrigger} appearance="subtle" className="cipher-topbar-button cipher-mobile-only" icon={<NavigationRegular />} aria-label="Open navigation" onClick={() => setMenuOpen(true)} />}
      <AppLink href="/estimates" className="cipher-wordmark" label="Cipher commercial home"><span className="cipher-mark">S&A</span> Cipher</AppLink>
      {projects && <label className="cipher-project-picker"><span className="cipher-visually-hidden">Choose a commercial project</span><Select aria-label="Choose a commercial project" value={parts[0] === 'projects' ? parts[1] ?? '' : ''} onChange={(_, data) => navigate(data.value ? `/projects/${encodeURIComponent(data.value)}/estimate-preparation` : '/projects')}><option value="">All projects</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></label>}
      <div className="cipher-topbar-spacer" />{personId && <><span className="cipher-ap-session-person">{session?.person?.displayName}</span><Button appearance="subtle" className="cipher-topbar-button" icon={<PersonRegular />} aria-label="Change practice person" disabled={busy} onClick={changePerson}><span className="cipher-desktop-only">Change person</span></Button></>}
    </header><aside className="cipher-rail">{personId && nav}</aside>
    <div className="cipher-workspace commercial-workspace"><div className="cipher-practice-strip"><span>Practice data. Nothing here is real money and nothing is sent.</span><span className="cipher-source-label">Disposable commercial practice</span></div>
      <main id="main-content" className="cipher-main" tabIndex={-1} aria-busy={(!session || !!personId && !projects) && !problem}>
        {problem && <div role="alert" className="cipher-message cipher-message-negative"><div><p>{problem.message}</p><Button onClick={() => session ? refresh() : setBoot(value => value + 1)}>Refresh practice session</Button></div></div>}
        {!session ? <><CommercialHeader title="Start a commercial practice session" />{!problem && <Spinner label="Reading the local commercial session" />}</>
          : !session.authenticated ? <><CommercialHeader title="Start a commercial practice session" subtitle="Choose one registered synthetic person to explore manual estimating and subcontract draft handoff." /><p>This practice selection does not establish real staff identity or Microsoft sign-in.</p><div className="commercial-personas">{personas.map(persona => <div className="cipher-ap-persona" key={persona.personaId}><h2>{persona.displayName}</h2><p>Registered synthetic commercial person</p><Button disabled={busy} onClick={() => choose(persona.personaId)}>Start as {persona.displayName}</Button></div>)}</div><p className="cipher-caption">Restarting the isolated server discards sessions and practice records.</p></>
            : projects ? <CommercialMemory key={`${personId}:${session.duties.join(',')}:${session.projectIds.slice().sort().join(',')}`}>{content}</CommercialMemory>
              : <><CommercialHeader title="Reading your commercial project scope" />{!problem && <Spinner label="Reading current actual project duties" />}</>}
      </main>{projects && <footer className="cipher-workspace-footer">Synthetic manual-source workflow.<Button appearance="subtle" onClick={refresh}>Refresh scoped records</Button></footer>}
    </div>
    <OverlayDrawer open={menuOpen} onOpenChange={(_, data) => { setMenuOpen(data.open); if (!data.open) requestAnimationFrame(() => menuTrigger.current?.focus()); }} position="start" size="small" className="cipher-mobile-navigation"><DrawerHeader><DrawerHeaderTitle action={<Button appearance="subtle" icon={<DismissRegular />} aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}>Cipher navigation</DrawerHeaderTitle></DrawerHeader><DrawerBody>{nav}</DrawerBody></OverlayDrawer>
  </div>;
}
