import { useEffect, useRef, useState } from 'react';
import { Button, DrawerBody, DrawerHeader, DrawerHeaderTitle, OverlayDrawer, Select, Spinner } from '@fluentui/react-components';
import { BookRegular, BuildingMultipleRegular, DismissRegular, NavigationRegular, PersonRegular, TaskListSquareLtrRegular } from '@fluentui/react-icons';
import { AppLink, navigate, useLocation } from '../app/navigation';
import { abortScopedReads, bindSession, RFIError, endSession, readPersonas, readProjects, readSession } from './client';
import { RFIMemory } from './Memory';
import { ApprovalPage, DistributionPage, PreparationPage, ProjectsPage, ResponsePage, ReviewsPage, RFIPage, RFIsPage } from './pages';
import { RFIHeader } from './presentation';
import type { Persona, PersonaId, Project, Session } from './types';
import '../theme/global.css';
import '../app/features.css';
import '../ap/ap.css';
import './rfi.css';

export function RFIApp() {
  const location = useLocation(); const [session, setSession] = useState<Session | null>(null); const [personas, setPersonas] = useState<Persona[]>([]);
  const [projects, setProjects] = useState<Project[] | null>(null); const [problem, setProblem] = useState<Error | null>(null);
  const [boot, setBoot] = useState(0); const [revision, setRevision] = useState(0); const [busy, setBusy] = useState(false); const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null); const projectRead = useRef<AbortController | null>(null);
  const pathname = location.split('?')[0]; const query = location.split('?')[1] ?? '';
  const parts = pathname.split('/').filter(Boolean).map(part => { try { return decodeURIComponent(part); } catch { return ''; } });
  const personId = session?.person?.id ?? '';
  function sessionLost() {
    projectRead.current?.abort(); abortScopedReads(); setSession(null); setProjects(null); setProblem(new Error('Your rfi practice session ended. Choose a registered practice person to continue.')); setBoot(value => value + 1);
  }
  function refresh() { setRevision(value => value + 1); }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([readSession(controller.signal), readPersonas(controller.signal)]).then(([current, options]) => {
      if (controller.signal.aborted) return; setSession(current); setPersonas(options); setProblem(null);
    }).catch(error => { if (!controller.signal.aborted) setProblem(error instanceof Error ? error : new Error('The rfi session could not be started.')); });
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
      setProjects(null); if (error instanceof RFIError && error.status === 401) sessionLost(); else setProblem(error instanceof Error ? error : new Error('Current rfi project scope could not be read.'));
    });
    return () => controller.abort();
  }, [personId, revision, busy]);
  useEffect(() => {
    setMenuOpen(false); const frame = requestAnimationFrame(() => { document.querySelector<HTMLElement>('[data-page-heading]')?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); });
    return () => cancelAnimationFrame(frame);
  }, [pathname, personId, !!projects]);
  async function choose(personaId: PersonaId) {
    if (!session || busy) return; projectRead.current?.abort(); abortScopedReads(); setBusy(true); setProjects(null); setProblem(null);
    try { setSession(await bindSession(personaId, session.csrfToken)); navigate('/rfis'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The registered practice person could not be selected.')); if (error instanceof RFIError && error.status === 401) sessionLost(); }
    finally { setBusy(false); }
  }
  async function changePerson() {
    if (!session || busy) return; projectRead.current?.abort(); abortScopedReads(); setBusy(true); setProjects(null); setProblem(null);
    try { setSession(await endSession(session.csrfToken)); setRevision(0); navigate('/'); }
    catch (error) { setProblem(error instanceof Error ? error : new Error('The rfi session could not be ended.')); sessionLost(); }
    finally { setBusy(false); }
  }
  const nav = <nav className="cipher-navigation" aria-label="Main navigation">{[
    {href:'/rfis',name:'RFI log',Icon:BookRegular,current:!parts.length || ['rfis','rfi-practice.html'].includes(parts[0])},
    {href:'/rfi-response-approvals',name:'Response reviews',Icon:TaskListSquareLtrRegular,current:parts[0]==='rfi-response-approvals'},
    {href:'/rfi-distribution-approvals',name:'Distribution reviews',Icon:TaskListSquareLtrRegular,current:parts[0]==='rfi-distribution-approvals'},
    {href:'/projects',name:'Projects',Icon:BuildingMultipleRegular,current:parts[0]==='projects'},
  ].map(({href,name,Icon,current})=><a key={href} href={href} title={name} className="cipher-nav-item" aria-current={current?'page':undefined} onClick={event=>{if(!event.ctrlKey&&!event.metaKey&&!event.shiftKey){event.preventDefault();navigate(href);}}}><Icon aria-hidden="true"/><span className="cipher-nav-label">{name}</span></a>)}</nav>;
  const controls = session ? { session, onChanged: refresh, onSessionLost: sessionLost } : null;
  let content = <><RFIHeader title="RFI record unavailable"/><p>This route does not identify a record in your current RFI scope.</p><AppLink href="/rfis">Open RFI log</AppLink></>;
  if(controls&&projects){
    if(!parts.length || parts[0]==='rfi-practice.html' || parts[0]==='rfis'&&parts.length===1)content=<RFIsPage query={query} revision={revision} {...controls}/>;
    else if(parts[0]==='projects'&&parts.length===1)content=<ProjectsPage revision={revision} {...controls}/>;
    else if(parts[0]==='projects'&&parts[2]==='rfi-preparation'&&parts.length===3)content=<PreparationPage key={parts[1]} projectId={parts[1]} revision={revision} {...controls}/>;
    else if(parts[0]==='rfis'&&parts.length===2)content=<RFIPage key={parts[1]} rfiId={parts[1]} revision={revision} {...controls}/>;
    else if(parts[0]==='rfis'&&parts[2]==='draft-response'&&parts.length===3)content=<ResponsePage key={parts[1]} rfiId={parts[1]} revision={revision} {...controls}/>;
    else if(parts[0]==='rfis'&&parts[2]==='distribution-list'&&parts.length===3)content=<DistributionPage key={parts[1]} rfiId={parts[1]} revision={revision} {...controls}/>;
    else if(parts[0]==='rfi-response-approvals'&&parts.length===1)content=<ReviewsPage kind="response" query={query} revision={revision} {...controls}/>;
    else if(parts[0]==='rfi-response-approvals'&&parts.length===2)content=<ApprovalPage key={parts[1]} kind="response" approvalId={parts[1]} revision={revision} {...controls}/>;
    else if(parts[0]==='rfi-distribution-approvals'&&parts.length===1)content=<ReviewsPage kind="distribution" query={query} revision={revision} {...controls}/>;
    else if(parts[0]==='rfi-distribution-approvals'&&parts.length===2)content=<ApprovalPage key={parts[1]} kind="distribution" approvalId={parts[1]} revision={revision} {...controls}/>;
  }
  return <div className="cipher-shell"><a className="cipher-skip-link" href="#main-content">Skip to content</a>
    <header className="cipher-topbar">{personId && <Button ref={menuTrigger} appearance="subtle" className="cipher-topbar-button cipher-mobile-only" icon={<NavigationRegular />} aria-label="Open navigation" onClick={() => setMenuOpen(true)} />}
      <AppLink href="/rfis" className="cipher-wordmark" label="Cipher RFI home"><span className="cipher-mark">S&A</span> Cipher</AppLink>
      {projects && <label className="cipher-project-picker"><span className="cipher-visually-hidden">Choose an RFI project</span><Select aria-label="Choose an RFI project" value={parts[0] === 'projects' ? parts[1] ?? '' : ''} onChange={(_, data) => navigate(data.value ? `/projects/${encodeURIComponent(data.value)}/rfi-preparation` : '/projects')}><option value="">All projects</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</Select></label>}
      <div className="cipher-topbar-spacer" />{personId && <><span className="cipher-ap-session-person">{session?.person?.displayName}</span><Button appearance="subtle" className="cipher-topbar-button" icon={<PersonRegular />} aria-label="Change practice person" disabled={busy} onClick={changePerson}><span className="cipher-desktop-only">Change person</span></Button></>}
    </header><aside className="cipher-rail">{personId && nav}</aside>
    <div className="cipher-workspace rfi-workspace"><div className="cipher-practice-strip" role="region" aria-label="Practice workspace status"><span>Practice RFI workflow. Informational impacts; local distribution only.</span><span className="cipher-source-label">Disposable RFI practice</span></div>
      <main id="main-content" className="cipher-main" tabIndex={-1} aria-busy={(!session || !!personId && !projects) && !problem}>
        {problem && <div role="alert" className="cipher-message cipher-message-negative"><div><p>{problem.message}</p><Button onClick={() => session ? refresh() : setBoot(value => value + 1)}>Refresh practice session</Button></div></div>}
        {!session ? <><RFIHeader title="Start an RFI practice session" />{!problem && <Spinner label="Reading the local RFI session" />}</>
          : !session.authenticated ? <><RFIHeader title="Start an RFI practice session" subtitle="Choose a registered synthetic staff member or project PM for the governed RFI workflow." /><p>This practice selection does not establish real staff identity or Microsoft sign-in.</p><div className="rfi-personas">{personas.map(persona => <div className="cipher-ap-persona" key={persona.personaId}><h2>{persona.displayName}</h2><p>{persona.personaId === 'staff' ? 'Current project staff member; drafting only' : 'Current actual project PM'}</p><Button disabled={busy} onClick={() => choose(persona.personaId)}>Start as {persona.displayName}</Button></div>)}</div><p className="cipher-caption">Restarting the isolated server discards sessions and practice records.</p></>
            : projects ? <RFIMemory key={`${personId}:${session.duties.join(',')}:${session.projectIds.slice().sort().join(',')}`}>{content}</RFIMemory>
              : <><RFIHeader title="Reading your RFI project scope" />{!problem && <Spinner label="Reading current actual project duties" />}</>}
      </main>{projects && <footer className="cipher-workspace-footer">Original RFI citations, independent response review and local practice distribution.<Button appearance="subtle" onClick={refresh}>Refresh scoped records</Button></footer>}
    </div>
    <OverlayDrawer open={menuOpen} onOpenChange={(_, data) => { setMenuOpen(data.open); if (!data.open) requestAnimationFrame(() => menuTrigger.current?.focus()); }} position="start" size="small" className="cipher-mobile-navigation"><DrawerHeader><DrawerHeaderTitle action={<Button appearance="subtle" icon={<DismissRegular />} aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}>Cipher navigation</DrawerHeaderTitle></DrawerHeader><DrawerBody>{nav}</DrawerBody></OverlayDrawer>
  </div>;
}
