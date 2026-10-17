import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, CheckBox, Input, Label, MessageStrip, Option, Select, Table, TableCell, TableHeaderCell, TableHeaderRow, TableRow, TextArea, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { field, invalidField, type FieldBasis, type FieldCommand, type FieldFamily, type FieldKind, type FieldReply, type FieldRevision } from './api/field';
import type { Actor, Scope } from './api/engineering';
import type * as F from './api/field.generated';
import type { Project } from './api/types';
import { Empty, Fact, Failure, Loading, PageHeading, Pagination, Status } from './components';
import { date, human, useResource } from './hooks';
import { useMutation } from './useMutation';
import { FieldEditor } from './FieldEditor';
import { FieldSourcePicker, FieldSourcePreview } from './FieldSources';
import './field-records.css';
export type FieldRecordsProps = { active: boolean; company: string; user: string; personId: string; project?: Project; contextLoading?: boolean; contextError?: ApiError; section?: string; recordId?: string; navigationLocked: boolean; navigate: (path: string) => void; onLockedChange: (locked: boolean) => void };
export const fieldPath = (project: string, family: FieldFamily = 'daily', id?: string) => `/projects/${encodeURIComponent(project)}/field/${family === 'ticket' ? 'tickets' : 'daily'}${id ? '/' + encodeURIComponent(id) : ''}`;
type Submit = (command: FieldCommand) => Promise<FieldReply | undefined>;
// The journal deliberately outlives authority-keyed source/form subtrees.
export default function FieldRecords(props: FieldRecordsProps) {
  const [revision, setRevision] = useState(0), [denied, setDenied] = useState(false), [notice, setNotice] = useState(''), [savedPath, setSavedPath] = useState<string>();
  const captured = useRef<(Actor & Scope) | undefined>(undefined);
  const latestAuthority = useRef({ company: props.company, project: props.project?.id, user: props.user, personId: props.personId });
  latestAuthority.current = { company: props.company, project: props.project?.id, user: props.user, personId: props.personId };
  const authority = JSON.stringify([props.company, props.project?.id, props.user, props.personId, [...(props.project?.capabilities || [])].sort()]);
  const mutation = useMutation<FieldCommand & { operation_id?: string }, FieldReply>(input => { if (!captured.current) throw invalidField(); return field.send(input, captured.current); });
  useEffect(() => props.onLockedChange(mutation.locked), [mutation.locked, props.onLockedChange]);
  useEffect(() => { setDenied(false); setNotice(''); setSavedPath(undefined); }, [authority]);
  useEffect(() => { if (mutation.error && [401, 403, 404].includes(mutation.error.status)) setDenied(true); }, [mutation.error]);
  const onDenied = useCallback(() => setDenied(true), []);
  const permitted = Boolean(props.project?.capabilities?.includes('field.read'));
  const sameActor = Boolean(captured.current && captured.current.company === props.company && captured.current.project === props.project?.id && captured.current.user === props.user && captured.current.personId === props.personId);
  const finish = (result: FieldReply | undefined) => {
    if (!result) return;
    const original = captured.current;
    const current = latestAuthority.current;
    if (original?.company === current.company && original.project === current.project && original.user === current.user && original.personId === current.personId) { setDenied(false); setNotice('Saved. The original revision and documentary receipt are retained.'); setSavedPath(fieldPath(original.project, result.family, result.header.id)); setRevision(value => value + 1); }
    captured.current = undefined; return result;
  };
  const submit: Submit = async command => {
    if (mutation.locked || props.navigationLocked || !props.active || !props.project || !permitted || denied) return;
    captured.current = { company: props.company, project: props.project.id, user: props.user, personId: props.personId }; setNotice(''); setSavedPath(undefined);
    return finish(await mutation.run(command));
  };
  return <>
    {(props.active || mutation.locked) && <div className="field-command-state">{mutation.error && <Failure error={mutation.error} />}
      {mutation.unknown && <><MessageStrip design="Critical" hideCloseButton>The result is uncertain. Keep this workspace open and recover the original request before editing.</MessageStrip>{!sameActor && <p>Restore the original Company, project and signed-in person to recover this request.</p>}<Button disabled={mutation.busy || !sameActor || !props.active || !permitted || props.navigationLocked} onClick={async () => finish(await mutation.recover())}>Recover original field request</Button></>}
      {notice && props.active && !denied && <MessageStrip design="Positive" hideCloseButton>{notice}</MessageStrip>}{savedPath && props.active && !denied && <Button disabled={mutation.locked || props.navigationLocked} onClick={() => props.navigate(savedPath)}>Open saved field record</Button>}
    </div>}
    {props.active && (props.contextLoading ? <Loading label="Opening Field project context…" /> : props.contextError ? <div className="page"><Failure error={props.contextError} /></div> : !props.project ? <div className="page"><PageHeading title="Field" description="Daily reports, photos, quantities and T&M tickets." /><Empty title="Choose a project" action={<Button onClick={() => props.navigate('/projects')}>Open projects</Button>}>Open a project to see its field records.</Empty></div> : !permitted ? <div className="page"><PageHeading title="Field" /><Failure error={new ApiError('Field access is unavailable.', 'capability_denied', 403)} /></div> : denied ? <div className="page"><MessageStrip hideCloseButton>Current Field or source access changed. Previously loaded records are hidden.</MessageStrip><Button disabled={mutation.locked} onClick={() => { setDenied(false); setRevision(value => value + 1); }}>Recheck Field access</Button></div> : <FieldWorkspace key={authority} {...props} project={props.project} revision={revision} locked={mutation.locked || props.navigationLocked} error={mutation.error} submit={submit} onDenied={onDenied} />)}
  </>;
}
type WorkspaceProps = FieldRecordsProps & { project: Project; revision: number; locked: boolean; error?: ApiError; submit: Submit; onDenied: () => void };
function FieldWorkspace(props: WorkspaceProps) {
  const family: FieldFamily = props.section === 'tickets' ? 'ticket' : 'daily', scope = { company: props.company, project: props.project.id };
  const [editor, setEditor] = useState<{ basis?: FieldBasis; quantities?: F.FdQuantity[] }>();
  useEffect(() => setEditor(undefined), [props.recordId, props.section]);
  const canWrite = Boolean(props.project.capabilities?.includes('field.write'));
  return <div className="page field-page"><PageHeading eyebrow={props.project.name} title="Field" description="Daily observations and documentary T&M records." actions={<><Button disabled={props.locked} onClick={() => props.navigate(`/projects/${encodeURIComponent(props.project.id)}/documents`)}>Project documents</Button>{canWrite && <Button design="Emphasized" disabled={props.locked} onClick={() => setEditor({})}>{family === 'daily' ? 'New daily report' : 'New T&M ticket'}</Button>}</>} />
    <nav className="field-tabs" aria-label="Field records"><Button design={family === 'daily' ? 'Emphasized' : 'Transparent'} disabled={props.locked} onClick={() => props.navigate(fieldPath(scope.project))}>Daily reports</Button><Button design={family === 'ticket' ? 'Emphasized' : 'Transparent'} disabled={props.locked} onClick={() => props.navigate(fieldPath(scope.project, 'ticket'))}>T&M tickets</Button></nav>
    <MessageStrip hideCloseButton>Field acceptance records documentary review. T&M acknowledgment does not change contracts, budgets or invoices.</MessageStrip>
    {editor ? <FieldEditor key={`${family}/${editor.basis?.header.record_digest || 'new'}`} scope={scope} family={family} user={props.user} {...editor} locked={props.locked || !canWrite} error={props.error} submit={props.submit} onDenied={props.onDenied} onCancel={() => setEditor(undefined)} onSaved={() => setEditor(undefined)} /> : props.recordId ? <FieldDetail key={`${family}/${props.recordId}`} {...props} scope={scope} family={family} id={props.recordId} canWrite={canWrite} onEdit={(basis, quantities) => setEditor({ basis, quantities })} /> : <FieldRegister key={`${family}/${props.revision}`} scope={scope} family={family} revision={props.revision} locked={props.locked} navigate={props.navigate} onDenied={props.onDenied} />}
  </div>;
}
function FieldRegister({ scope, family, revision, locked, navigate, onDenied }: { scope: Scope; family: FieldFamily; revision: number; locked: boolean; navigate: (path: string) => void; onDenied: () => void }) {
  const [cursor, setCursor] = useState<string>(), [prior, setPrior] = useState<(string | undefined)[]>([]);
  const records = useResource(`${scope.company}/${scope.project}/field/${family}/${revision}/${cursor || ''}`, signal => field.list(scope, family, undefined, cursor, signal));
  useEffect(() => { if (records.error && [401, 403, 404].includes(records.error.status)) onDenied(); }, [records.error, onDenied]);
  return <section className="field-panel"><div className="field-panel-heading"><Title level="H2">{family === 'daily' ? 'Daily reports' : 'T&M tickets'}</Title><Button icon="refresh" disabled={locked} onClick={records.refresh}>Refresh register</Button></div>{records.loading ? <Loading label="Loading field records…" /> : records.error ? <Failure error={records.error} onRetry={records.refresh} /> : !records.data?.items.length ? <Empty title={family === 'daily' ? 'No daily reports yet' : 'No T&M tickets yet'}>Saved field records will appear here.</Empty> : <div className="field-table-scroll"><Table accessibleName="Field register" headerRow={<TableHeaderRow><TableHeaderCell>Record</TableHeaderCell><TableHeaderCell>Revision</TableHeaderCell><TableHeaderCell>Standing</TableHeaderCell><TableHeaderCell>Open</TableHeaderCell></TableHeaderRow>}>{records.data.items.map(({ record }) => { const header = record as F.FdHeader; return <TableRow key={header.id}><TableCell><strong>{header.number}</strong><p className="caption">{date(header.created_at)}</p></TableCell><TableCell>{header.revision_number}</TableCell><TableCell><Status value={header.status} /></TableCell><TableCell><Button disabled={locked} onClick={() => navigate(fieldPath(scope.project, family, header.id))}>Open record</Button></TableCell></TableRow>; })}</Table></div>}
    <Pagination page={prior.length + 1} previous={Boolean(prior.length)} next={locked ? undefined : records.data?.next_cursor} onNext={() => { if (!locked && records.data?.next_cursor) { setPrior([...prior, cursor]); setCursor(records.data.next_cursor); } }} onPrevious={() => { if (!locked) { setCursor(prior.at(-1)); setPrior(prior.slice(0, -1)); } }} /><p className="caption">Only permitted records appear. No unfiltered total is shown.</p>
  </section>;
}
function FieldDetail(props: WorkspaceProps & { scope: Scope; family: FieldFamily; id: string; canWrite: boolean; onEdit: (basis: FieldBasis, quantities: F.FdQuantity[]) => void }) {
  const [selected, setSelected] = useState<string>(), [historyKind, setHistoryKind] = useState<'revisions' | 'decisions'>('revisions'), [cursor, setCursor] = useState<string>(), [prior, setPrior] = useState<(string | undefined)[]>([]);
  const kind = props.family === 'daily' ? 'daily_revision' : 'ticket_revision';
  const detail = useResource(`${props.scope.company}/${props.scope.project}/field/${props.family}/${props.id}/${props.revision}/${selected || 'current'}`, async signal => {
    const header = await field.get(props.scope, props.family, props.id, signal), h = header.record as F.FdHeader;
    const revision = await field.get(props.scope, kind, selected || h.current_revision, signal), r = revision.record as FieldRevision;
    if (r.parent_id !== h.id || (!selected && r.revision_number !== h.revision_number)) throw invalidField();
    const quantities = 'quantity_ids' in r ? await Promise.all(r.quantity_ids.map(id => field.get(props.scope, 'quantity', id, signal))) : [];
    if (quantities.some(row => !('source_revision' in row.record) || row.record.source_revision !== r.id || !('parent_id' in row.record) || row.record.parent_id !== h.id)) throw invalidField();
    return { basis: { header, revision }, quantities: quantities.map(row => row.record as F.FdQuantity) };
  });
  const history = useResource(`${props.scope.company}/${props.scope.project}/field-history/${props.id}/${historyKind}/${props.revision}/${cursor || ''}`, signal => field.list(props.scope, historyKind === 'decisions' ? 'decision' : kind, props.id, cursor, signal));
  useEffect(() => { if ([detail.error, history.error].some(error => error && [401, 403, 404].includes(error.status))) props.onDenied(); }, [detail.error, history.error, props.onDenied]);
  const data = detail.data, header = data?.basis.header.record as F.FdHeader | undefined, revision = data?.basis.revision.record as FieldRevision | undefined;
  if (detail.loading) return <Loading label="Opening exact field revision…" />;
  if (detail.error) return <Failure error={detail.error} onRetry={detail.refresh} />;
  if (!data || !header || !revision) return null;
  const isCurrent = revision.id === header.current_revision;
  return <>
    <section className="field-panel"><div className="field-panel-heading"><div><Title level="H2">{'title' in revision.definition ? revision.definition.title : `Daily report · ${date(revision.definition.local_date)}`}</Title><p className="caption">{header.number} · Revision {revision.revision_number}</p></div><div className="field-inline-actions"><Button disabled={props.locked} icon="refresh" onClick={() => { detail.refresh(); history.refresh(); }}>Refresh record</Button>{props.canWrite && isCurrent && ['draft', 'returned', 'accepted', 'acknowledged'].includes(header.status) && <Button disabled={props.locked} onClick={() => props.onEdit(data.basis, data.quantities)}>{header.accepted_revision ? 'Amend accepted record' : 'Create revision'}</Button>}</div></div>
      <div className="field-facts"><Fact label="Current standing"><Status value={header.status} /></Fact><Fact label="Displayed revision">{revision.revision_number}{isCurrent ? ' · Current' : ' · Historical'}</Fact><Fact label="Recorded by">{revision.author_user}</Fact><Fact label="Local work date">{date(revision.definition.local_date)}</Fact></div>
      {!isCurrent && <MessageStrip hideCloseButton>This is an immutable historical revision. New decisions apply to the current revision.</MessageStrip>}
      {revision.amendment_of && <MessageStrip hideCloseButton>Amendment of an accepted original. Reason: {revision.amendment_reason}</MessageStrip>}
      {header.accepted_revision && <div className="field-inline-actions"><span className="caption">Latest accepted original: <code>{header.accepted_revision}</code></span><Button disabled={props.locked} onClick={() => setSelected(header.accepted_revision!)}>Read accepted original</Button></div>}
      <FieldRevisionFacts scope={props.scope} revision={revision} quantities={data.quantities} onDenied={props.onDenied} />
    </section>
    {isCurrent && <FieldDecision key={`${data.basis.header.record_digest}/${data.basis.revision.record_digest}`} scope={props.scope} family={props.family} basis={data.basis} actor={{ user: props.user, personId: props.personId }} capabilities={props.project.capabilities || []} locked={props.locked} submit={props.submit} onDenied={props.onDenied} />}
    <section className="field-panel"><div className="field-panel-heading"><Title level="H2">Record history</Title><div className="field-inline-actions"><Button disabled={props.locked} onClick={() => { setHistoryKind('revisions'); setCursor(undefined); setPrior([]); }}>Revisions</Button><Button disabled={props.locked} onClick={() => { setHistoryKind('decisions'); setCursor(undefined); setPrior([]); }}>Decisions</Button><Button disabled={props.locked} onClick={() => setSelected(undefined)}>Read current revision</Button></div></div>
      {history.loading ? <Loading label="Loading permitted history…" /> : history.error ? <Failure error={history.error} onRetry={history.refresh} /> : !history.data?.items.length ? <Empty title="No history records" /> : <ol className="field-history">{history.data.items.map(({ record }) => <li key={record.id}>{'action' in record ? <><strong>{human(record.action)} · {record.author_user}</strong><p>{record.comment}</p><p className="caption">{date(record.created_at)} · Exact revision <code>{record.source_revision}</code></p>{record.action === 'acknowledge' && <p>Acknowledgment reported for {record.acknowledged_by}. Documentary evidence only.</p>}{record.evidence.map((source, index) => <FieldSourcePreview key={index} scope={props.scope} source={source} onDenied={props.onDenied} />)}</> : 'revision_number' in record && <><Button disabled={props.locked} onClick={() => setSelected(record.id)}>Read revision {record.revision_number}</Button><span>{record.author_user} · {date(record.created_at)}</span>{'amendment_reason' in record && record.amendment_reason && <p>{record.amendment_reason}</p>}</>}</li>)}</ol>}
      <Pagination page={prior.length + 1} previous={Boolean(prior.length)} next={props.locked ? undefined : history.data?.next_cursor} onNext={() => { if (!props.locked && history.data?.next_cursor) { setPrior([...prior, cursor]); setCursor(history.data.next_cursor); } }} onPrevious={() => { if (!props.locked) { setCursor(prior.at(-1)); setPrior(prior.slice(0, -1)); } }} />
    </section>
  </>;
}
function FieldRevisionFacts({ scope, revision, quantities, onDenied }: { scope: Scope; revision: FieldRevision; quantities: F.FdQuantity[]; onDenied: () => void }) {
  const definition = revision.definition;
  return <div className="field-revision-facts">{'activities' in definition ? <><Fact label="Superintendent">{'superintendent' in revision ? revision.superintendent.user : definition.superintendent_user}</Fact>{(['activities', 'crews', 'delays', 'visitors'] as const).map(key => <section key={key}><Title level="H3">{human(key)}</Title>{definition[key].length ? <ul>{definition[key].map((text, index) => <li key={index}>{text}</li>)}</ul> : <p className="caption">None recorded</p>}</section>)}{definition.weather && <section><Title level="H3">Weather</Title><p>{definition.weather}</p>{definition.weather_sources.map((source, index) => <FieldSourcePreview key={index} scope={scope} source={source} onDenied={onDenied} />)}</section>}
      {!!quantities.length && <section><Title level="H3">Installed and delivered observations</Title>{quantities.map(row => <div className="field-line" key={row.id}><strong>{human(row.definition.kind)} · {row.definition.description}</strong><p className="field-exact-quantity">{row.definition.quantity} {row.definition.unit}</p><p>{row.definition.location}</p><p className="caption">WBS label: {row.definition.wbs_code || 'None'} · Cost code label: {row.definition.cost_code || 'None'}</p>{row.supersedes_event_id && <p className="caption">Correction to <code>{row.supersedes_event_id}</code></p>}{row.definition.sources.map((source, index) => <FieldSourcePreview key={index} scope={scope} source={source} onDenied={onDenied} />)}</div>)}</section>}
    </> : <><div className="field-facts"><Fact label="Customer or representative">{definition.customer_name}</Fact><Fact label="Work location">{definition.location}</Fact><Fact label="Potential change reference">{definition.potential_change_reference || 'None recorded'}</Fact></div><Title level="H3">Work performed</Title><p className="field-authored-text">{definition.work_description}</p><Title level="H3">Documentary quantities</Title>{definition.lines.map((line, index) => <div className="field-line" key={index}><strong>{human(line.kind)} · {line.description}</strong><p className="field-exact-quantity">{line.quantity} {line.unit}</p>{line.sources.map((source, i) => <FieldSourcePreview key={i} scope={scope} source={source} onDenied={onDenied} />)}</div>)}</>}
    {!!revision.photos.length && <section><Title level="H3">Photos</Title>{revision.photos.map((photo, index) => <div className="field-line" key={index}><strong>{photo.caption}</strong><p className="caption">{photo.captured_at} · {photo.representation === 'source_image' ? 'Original JPEG / PNG source' : 'Photo on a PDF page'}</p><FieldSourcePreview scope={scope} source={photo.source} onDenied={onDenied} /></div>)}</section>}
    <details><summary>Revision details</summary><p>Exact revision <code>{revision.id}</code></p><p>Predecessor <code>{revision.predecessor || 'First revision'}</code></p><p className="caption">No contract, budget, procurement, invoice, financial posting, payroll release, quality certification or external transmission effect.</p></details>
  </div>;
}
function FieldDecision({ scope, family, basis, actor, capabilities, locked, submit, onDenied }: { scope: Scope; family: FieldFamily; basis: FieldBasis; actor: Actor; capabilities: string[]; locked: boolean; submit: Submit; onDenied: () => void }) {
  const header = basis.header.record as F.FdHeader, revision = basis.revision.record as FieldRevision;
  const independent = actor.personId !== revision.author_person && (!('superintendent' in revision) || actor.personId !== revision.superintendent.person);
  const actions: F.FdTransitionRequest['action'][] = header.status === 'draft' ? ['submit'] : header.status === 'submitted' ? ['review', 'return'] : header.status === 'reviewed' ? ['accept', 'return'] : header.status === 'accepted' && family === 'ticket' ? ['acknowledge'] : [];
  const allowed = actions.filter(action => capabilities.includes(({ submit: 'field.write', review: 'field.review', return: 'field.review', accept: 'field.accept', acknowledge: 'field.acknowledge' })[action]) && (action === 'submit' || independent));
  const [action, setAction] = useState<F.FdTransitionRequest['action']>(allowed[0] || 'submit'), [comment, setComment] = useState(''), [name, setName] = useState(''), [evidence, setEvidence] = useState<F.FdSourceInput[]>([]), [reviewed, setReviewed] = useState(false);
  if (!actions.length) return null;
  if (!allowed.length) return <section className="field-panel"><MessageStrip hideCloseButton>{!independent && actions[0] !== 'submit' ? 'Review, acceptance and acknowledgment need a person independent of the author and daily superintendent.' : 'Your current Field duties do not allow the next documentary action.'}</MessageStrip></section>;
  return <section className="field-panel" aria-label="Field documentary decision"><Title level="H2">Next action</Title><p className="caption">This decision binds revision {revision.revision_number} and its exact sources.</p><Label>Action</Label><Select accessibleName="Field action" disabled={locked} onChange={event => { setAction(event.detail.selectedOption.value as typeof action); setReviewed(false); }}>{allowed.map(value => <Option key={value} value={value} selected={action === value}>{({ submit: 'Submit for review', review: 'Record independent review', return: 'Return for revision', accept: 'Accept field record', acknowledge: 'Record customer acknowledgment' })[value]}</Option>)}</Select>
    <Label required>Comment</Label><TextArea accessibleName="Field decision comment" value={comment} maxlength={2000} disabled={locked} rows={3} onInput={event => { setComment(event.currentTarget!.value); setReviewed(false); }} />
    {action === 'acknowledge' && <><MessageStrip hideCloseButton>Record evidence and the named representative. This is not an authenticated signature or authority for payment.</MessageStrip><Label required>Acknowledging representative</Label><Input accessibleName="Acknowledging representative" value={name} maxlength={240} disabled={locked} onInput={event => { setName(event.currentTarget!.value); setReviewed(false); }} /></>}
    <FieldSourcePicker scope={scope} label="Decision evidence" sources={evidence} onChange={value => { setEvidence(value); setReviewed(false); }} disabled={locked} onDenied={onDenied} />
    <CheckBox accessibleName="I reviewed this exact field revision" text="I reviewed this exact revision and its evidence" checked={reviewed} disabled={locked} onChange={event => setReviewed(event.currentTarget!.checked)} />
    <div className="field-form-actions"><Button design="Emphasized" disabled={locked || !allowed.includes(action) || !comment.trim() || !reviewed || action === 'acknowledge' && (!name.trim() || !evidence.length)} onClick={async () => { await submit({ kind: 'transition', payload: { ...scope, family, record_id: header.id, expected_version: basis.header.record_digest, action, comment, evidence, acknowledged_by: action === 'acknowledge' ? name : '' }, basis }); }}>Record action</Button></div>
  </section>;
}
