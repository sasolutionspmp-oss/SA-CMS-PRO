import CompanyRickyRead from './CompanyRickyRead';
import { useEffect, useRef, useState } from 'react';
import { Button, CheckBox, Icon, Link, MessageStrip, TextArea, Title } from '@ui5/webcomponents-react';
import type { TextAreaDomRef } from '@ui5/webcomponents-react';
import { ApiError, rpc } from './api/client';
import type { Citation, ModelStatus, Project, RickyProposal, RickyRun } from './api/types';
import { human, useResource } from './hooks';
import { Empty, Failure, Loading, Status } from './components';

const prefix = 'cipher_aec.ricky.api.';
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'waiting_for_review', 'waiting-for-review', 'completed']);

export default function RickyPanel(props: { company: string; project?: Project; person: string; user?: string; companyScope?: boolean; companyCapabilities?: string[]; navigate: (path: string) => void; onClose: () => void; onSaved: () => void }) {
  return props.companyScope ? <CompanyRickyRead key={JSON.stringify([props.user, props.person, props.company])} company={props.company} user={props.user || ''} person={props.person} capabilities={props.companyCapabilities || []} navigate={props.navigate} onClose={props.onClose} /> : <ProjectRickyPanel {...props} />;
}

function ProjectRickyPanel({ company, project, person, navigate, onClose, onSaved }: { company: string; project?: Project; person: string; navigate: (path: string) => void; onClose: () => void; onSaved: () => void }) {
  const connection = useResource('ricky/connection', signal => rpc<ModelStatus>(`${prefix}connection_status`, {}, false, signal));
  const storageKey = `cipher.run.${person}.${company}.${project?.id ?? ''}`;
  const [runId, setRunId] = useState<string | null>(() => sessionStorage.getItem(storageKey));
  const [run, setRun] = useState<RickyRun>();
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const [notice, setNotice] = useState('');
  const inputRef = useRef<TextAreaDomRef>(null);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await rpc<RickyRun>(`${prefix}get_run`, { run_id: runId }, false, controller.signal);
        if (controller.signal.aborted) return;
        setRun(next); setError(undefined);
        if (!terminal.has(next.status)) timer = setTimeout(poll, 1800);
      } catch (failure) { if (!controller.signal.aborted) { setError(failure as ApiError); if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) { setRun(undefined); sessionStorage.removeItem(storageKey); } } }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId]);
  const ask = async () => {
    if (!project || !question.trim() || sending) return;
    setSending(true); setError(undefined);
    try {
      const next = await rpc<RickyRun>(`${prefix}start_run`, { company, project: project.id, question: question.trim(), operation_id: operationId }, true);
      setRun(next); setRunId(next.id); sessionStorage.setItem(storageKey, next.id);
    } catch (failure) { setError(failure as ApiError); }
    finally { setSending(false); }
  };
  const cancel = async () => {
    if (!run) return;
    setSending(true);
    try { setRun(await rpc<RickyRun>(`${prefix}cancel_run`, { run_id: run.id, operation_id: crypto.randomUUID() }, true)); }
    catch (failure) { setError(failure as ApiError); }
    finally { setSending(false); }
  };
  const reset = () => { setRun(undefined); setRunId(null); setError(undefined); setNotice(''); setQuestion(''); setOperationId(crypto.randomUUID()); sessionStorage.removeItem(storageKey); setTimeout(() => inputRef.current?.focus(), 0); };
  return <aside className="ricky-panel" aria-label="Ricky project assistant">
    <header className="ricky-header"><div className="ricky-identity"><div className="ricky-mark"><Icon name="da" /></div><div><Title level="H2">Ricky</Title><span>AEC intelligence</span></div></div><Button icon="decline" design="Transparent" accessibleName="Close Ricky" onClick={onClose} /></header>
    <div className="ricky-context"><Icon name="folder" /><div><span>PROJECT CONTEXT</span><strong>{project?.name ?? 'No project selected'}</strong></div></div>
    <div className="ricky-scroll">
      {connection.loading ? <Loading label="Checking local model…" /> : connection.error ? <Failure error={connection.error} onRetry={connection.refresh} /> : connection.data && !connection.data.available ? <div className="model-unavailable"><Icon name="disconnected" /><h3>Ricky is not connected</h3><p>{connection.data.message || 'The existing local model connection has not been configured for this workspace.'}</p><Button icon="refresh" onClick={connection.refresh}>Check connection</Button><p className="caption">Your project, tasks and documents are still available.</p></div> : <div className="model-state"><span className="state-dot" />{connection.data?.adapter_kind?.includes('fixture') ? 'Synthetic model test adapter' : 'Local model available'}</div>}
      {!project ? <Empty title="Start with a project" icon="folder" action={<Button onClick={() => navigate('/projects')}>Open projects</Button>}>Ricky uses the same project and document access as you.</Empty> : <>
        {notice && <MessageStrip design="Positive" onClose={() => setNotice('')}>{notice}</MessageStrip>}
        {!run && !runId && connection.data?.available && <div className="ricky-intro"><h3>Work from the source.</h3><p>Ask about this project, find supporting evidence, or draft the next task.</p><div className="prompt-list">{['Summarize the available project sources.', 'What needs follow-up in the project documents?', 'Propose a task from the source requirements.'].map(prompt => <button key={prompt} className="prompt-button" onClick={() => { setQuestion(prompt); setOperationId(crypto.randomUUID()); inputRef.current?.focus(); }}>{prompt}<Icon name="navigation-right-arrow" /></button>)}</div></div>}
        {error && <Failure error={error} />}
        {runId && !run && !error && <Loading label="Loading saved run…" />}
        {run && <div className="run-content"><div className="question-bubble">{run.question}</div><div className="run-status"><Status value={run.status} /><span className="caption">Saved run</span></div>
          {!terminal.has(run.status) && <div className="run-progress" role="status"><span className="pulse-dot" />{run.cancel_requested ? 'Cancellation requested…' : `${human(run.status)}…`}<Button design="Transparent" disabled={sending || run.cancel_requested} onClick={cancel}>Cancel</Button></div>}
          {run.answer && <div className="answer-text">{run.answer}</div>}
          {run.error && <MessageStrip design="Negative" hideCloseButton>{run.error.message || 'This request could not be completed.'}</MessageStrip>}
          {run.citations?.length > 0 && <div className="citation-list"><h4>Sources</h4>{run.citations.map((citation, index) => <CitationLink key={`${citation.revision_id}-${index}`} citation={citation} navigate={navigate} />)}</div>}
          {run.proposal_ids?.map(id => <ProposalCard key={id} id={id} onSaved={taskName => { setNotice(`Task “${taskName}” was created.`); onSaved(); }} navigate={navigate} />)}
          {terminal.has(run.status) && <Button design="Transparent" icon="add" onClick={reset}>New request</Button>}
        </div>}
      </>}
    </div>
    <div className="ricky-composer"><TextArea ref={inputRef} accessibleName="Ask Ricky about this project" placeholder={project ? 'Ask about this project…' : 'Select a project to begin…'} value={question} rows={3} disabled={!project || !connection.data?.available || Boolean(runId) || sending} onInput={event => { setQuestion(event.currentTarget!.value); setOperationId(crypto.randomUUID()); }} />
      <div className="composer-actions"><span>Sources first. You review changes.</span><Button icon="paper-plane" design="Emphasized" disabled={!question.trim() || !project || !connection.data?.available || Boolean(runId) || sending} onClick={ask} accessibleName="Send question to Ricky">{sending && !run ? 'Sending…' : 'Send'}</Button></div>
    </div>
  </aside>;
}

function ProposalCard({ id, navigate, onSaved }: { id: string; navigate: (path: string) => void; onSaved: (name: string) => void }) {
  const proposal = useResource(id, signal => rpc<RickyProposal>(`${prefix}get_proposal`, { proposal_id: id }, false, signal));
  const [reviewed, setReviewed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [operationId] = useState(() => crypto.randomUUID());
  if (proposal.loading) return <Loading label="Loading proposed task…" />;
  if (proposal.error) return <Failure error={proposal.error} onRetry={proposal.refresh} />;
  if (!proposal.data) return null;
  const current = proposal.data;
  const commit = async () => {
    if (!reviewed || saving) return;
    setSaving(true); setError(undefined);
    try { await rpc(`${prefix}commit_proposal`, { proposal_id: current.id, proposal_version: current.version, operation_id: operationId }, true); setSaved(true); onSaved(current.fields.subject); }
    catch (failure) { setError(failure as ApiError); }
    finally { setSaving(false); }
  };
  return <section className="proposal-card" aria-label="Proposed task"><div className="proposal-heading"><Icon name="task" /><strong>Proposed task</strong><Status value={saved ? 'saved' : current.status} /></div>
    <h4>{current.fields.subject}</h4>{current.fields.description && <p>{current.fields.description}</p>}
    {current.sources?.map((source, index) => <CitationLink key={`${source.revision_id}-${index}`} citation={source} navigate={navigate} />)}
    {error && <Failure error={error} />}
    {!saved && !['committed', 'applied', 'expired', 'cancelled', 'rejected'].includes(current.status) && <><CheckBox checked={reviewed} onChange={event => setReviewed(event.currentTarget!.checked)} text="I reviewed this task and its sources" /><Button design="Emphasized" disabled={!reviewed || saving} onClick={commit}>{saving ? 'Saving…' : 'Create proposed task'}</Button></>}
    {saved && <p className="caption">Saved to this project. No other action was performed.</p>}
  </section>;
}

function CitationLink({ citation, navigate }: { citation: Citation; navigate: (path: string) => void }) {
  return <div className="citation"><Icon name="document-text" /><div><Link onClick={() => navigate(`/documents/${encodeURIComponent(citation.document_id)}/revisions/${encodeURIComponent(citation.revision_id)}?page=${citation.page}`)}>{citation.document_title || 'Source document'}</Link><span>Rev. {citation.revision_number} · {citation.page_label || `Page ${citation.page}`}</span>{citation.excerpt && <p>{citation.excerpt}</p>}</div></div>;
}
