import { useEffect, useRef, useState } from 'react';
import { Button, CheckBox, Icon, Input, Label, Link, MessageStrip, Option, Select, TextArea, Title } from '@ui5/webcomponents-react';
import { ApiError, rpc } from './api/client';
import { companySuggestions } from './api/company-ricky-proposals';
import { matchesSavedSuggestion, matchesSuggestionAdmission, matchesSuggestionEvents, matchesSuggestionRun, matchesSuggestionStop, suggestionDigest, suggestionPointerKey, terminalSuggestion, validSuggestionRunDigests, validSuggestionSelection } from './api/company-ricky-proposals-validation';
import { sameSelectedValue } from './api/company-ricky-validation';
import type { CompanyRickyProposalSelection as Selection, CompanyRickyProposalRunResponse as Run, CompanyRickyProposalResponse as Suggestion } from './api/company-ricky-proposals.generated';
import type { CompanyCitation, CompanyCitationList } from './api/company-documents.generated';
import type { CompanyEstLineRecord, CompanyEstSnapshotRecord } from './api/company-estimating.generated';
import type { CompanyTakeoffListResponse, CompanyTakeoffMeasurementRecord } from './api/company-takeoff.generated';
import { commercial } from './api/commercial';
import { companyEstimating } from './api/company-estimating';
import { useResource, date, human } from './hooks';
import { useMutation } from './useMutation';
import { Empty, Failure, Loading, Status } from './components';

const invalid = () => new ApiError('This saved suggestion or its original sources could not be verified. Refresh access before continuing.', 'INVALID_CONTRACT', 200);
const companyRecord = (row: { company: string; scope_type: string; project: unknown }, company: string) => row.company === company && row.scope_type === 'Company' && row.project === null;
const labels = { 'aec.scope.draft': 'Prepare scope suggestion', 'aec.estimate.draft': 'Prepare estimate suggestion' };
type QuantityChoice = { line_record_id: string; source_kind: 'estimate-line' | 'measurement'; source_id: string; target_unit_id: string };
type Unit = { id: string; kind: string; revision: number; fields: Record<string, unknown>; target: { name?: string } };
const savedUnits = (snapshot?: CompanyEstSnapshotRecord) => snapshot?.inputs.unit_manifest.records.filter(row => row.kind === 'uom') as Unit[] | undefined;
const unitLabel = (row?: Unit) => row ? `${row.target.name || 'Saved unit'} · ${String(row.fields.symbol || '')}` : 'Original unit unavailable';

export default function CompanyRickyProposals({ company, user, person, capabilities, navigate, onClose, onReads, onLockedChange }: { company: string; user: string; person: string; capabilities: string[]; navigate: (path: string) => void; onClose: () => void; onReads: () => void; onLockedChange?: (locked: boolean) => void }) {
  const canRead = Boolean(user && person && company && capabilities.includes('ricky.run'));
  const pointer = suggestionPointerKey(user, person, company);
  const currentAccess = JSON.stringify([...capabilities].sort());
  const [runId, setRunId] = useState(() => sessionStorage.getItem(pointer) || '');
  const [refresh, setRefresh] = useState(0); const [stopped, setStopped] = useState<string>();
  const [building, setBuilding] = useState(false); const preparing = useRef(false); const [localError, setLocalError] = useState<ApiError>();
  const original = useRef<{ selection: Selection; digest: string; created_at?: string; terminal?: Run; proposal?: Suggestion } | undefined>(undefined);
  const pendingDigest = useRef('');
  const start = useMutation<{ company: string; request: Selection; operation_id?: string }, Awaited<ReturnType<typeof companySuggestions.start>>>(companySuggestions.start, (value, input) => matchesSuggestionAdmission(value, input.company, input.request, pendingDigest.current));
  const stop = useMutation<{ company: string; run_id: string; operation_id?: string }, Awaited<ReturnType<typeof companySuggestions.stop>>>(companySuggestions.stop, (value, input) => matchesSuggestionStop(value, input.company, input.run_id));
  const locked = building || start.locked || stop.locked;
  useEffect(() => { onLockedChange?.(locked); return () => onLockedChange?.(false); }, [locked, onLockedChange]);
  const reading = useResource(canRead && runId ? `${pointer}/${currentAccess}/run/${runId}/${refresh}` : null, async signal => {
    const run = await companySuggestions.run({ company, run_id: runId }, signal);
    if (!matchesSuggestionRun(run, company, runId) || !await validSuggestionRunDigests(run) || original.current && (!sameSelectedValue(run.selection, original.current.selection) || run.selection_digest !== original.current.digest || original.current.created_at && run.created_at !== original.current.created_at)) throw invalid();
    if (original.current?.terminal && !sameSelectedValue(run, original.current.terminal)) throw invalid();
    const events = await companySuggestions.events({ company, run_id: runId }, signal);
    if (!matchesSuggestionEvents(events, run)) throw invalid();
    if (!signal.aborted) {
      original.current ||= { selection: structuredClone(run.selection), digest: run.selection_digest, created_at: run.created_at };
      if (terminalSuggestion(run.status) && !original.current.terminal) original.current.terminal = structuredClone(run);
    }
    return { run, events };
  });
  const review = useResource(reading.data?.run.status === 'waiting-for-review' && !reading.loading ? `${pointer}/proposal/${reading.data.run.result!.proposal_id}/${refresh}` : null, async signal => {
    const { run, events } = reading.data!;
    const proposal = await companySuggestions.proposal({ company, proposal_id: run.result!.proposal_id }, signal);
    const citations = await Promise.all(run.selection.sources.map(source => rpc<CompanyCitation>('cipher_aec.documents.company_api.get_citation', { company, revision_id: source.revision_id, page: source.page, excerpt_sha256: source.excerpt_sha256 }, false, signal)));
    let snapshot: CompanyEstSnapshotRecord | undefined;
    if (run.action === 'aec.estimate.draft') {
      const revision = await companyEstimating.get(company, 'revision', String(run.selection.arguments.base_revision_id), signal);
      const estimate = await companyEstimating.get(company, 'estimate', revision.estimate, signal);
      snapshot = await companyEstimating.get(company, 'snapshot', revision.calculation_snapshot, signal);
      if (!companyRecord(revision, company) || !companyRecord(estimate, company) || !companyRecord(snapshot, company) || revision.id !== run.selection.arguments.base_revision_id || estimate.id !== revision.estimate || estimate.pursuit_id !== run.selection.pursuit_id || snapshot.id !== revision.calculation_snapshot || snapshot.estimate !== estimate.id || snapshot.subject_id !== revision.id || snapshot.inputs.unit_manifest.scope.company !== company || snapshot.inputs.unit_manifest.scope.scope_type !== 'Company' || snapshot.inputs.unit_manifest.scope.project !== null) throw invalid();
    }
    if (!await matchesSavedSuggestion(proposal, run, citations, snapshot?.id) || events.items.length !== 1 || events.items[0].id !== proposal.step_id || events.items[0].status !== 'succeeded' || events.items[0].error !== null || original.current?.proposal && !sameSelectedValue(original.current.proposal, proposal)) throw invalid();
    const units = savedUnits(snapshot) || [];
    if (proposal.preparation.kind === 'estimate-draft.v1') for (const row of proposal.preparation.proposed_fields.quantity_selections) {
      const target = units.find(unit => unit.id === row.quantity.target_unit_id);
      if (!target || proposal.source_manifest.qualified_units.find(unit => unit.id === target.id)?.digest !== await suggestionDigest(target)) throw invalid();
    }
    if (!signal.aborted) original.current!.proposal ||= structuredClone(proposal);
    return { proposal, citations, units };
  });
  useEffect(() => { if (!reading.data || terminalSuggestion(reading.data.run.status)) return; const timer = setTimeout(() => setRefresh(value => value + 1), 1800); return () => clearTimeout(timer); }, [reading.data]);
  const accept = (value: Awaited<ReturnType<typeof companySuggestions.start>> | undefined) => {
    if (!value) return;
    original.current = { selection: structuredClone(value.selection), digest: value.selection_digest, created_at: value.created_at };
    sessionStorage.setItem(pointer, value.id); setRunId(value.id); setRefresh(value => value + 1);
  };
  const submit = async (request: Selection) => {
    if (locked || preparing.current || !canRead || !validSuggestionSelection(request)) return;
    preparing.current = true; setBuilding(true); setLocalError(undefined);
    try { pendingDigest.current = await suggestionDigest(request); accept(await start.run({ company, request })); }
    catch { setLocalError(invalid()); }
    finally { preparing.current = false; setBuilding(false); }
  };
  const reset = () => { if (locked) return; original.current = undefined; sessionStorage.removeItem(pointer); setRunId(''); setStopped(undefined); setLocalError(undefined); setRefresh(value => value + 1); };
  const accessError = reading.error || review.error;
  return <aside className="ricky-panel company-suggestions" aria-label="Company saved suggestions">
    <header className="ricky-header"><div className="ricky-identity"><div className="ricky-mark"><Icon name="da" /></div><div><Title level="H2">Saved suggestions</Title><span>Company review</span></div></div><Button icon="decline" accessibleName="Close Ricky" design="Transparent" disabled={locked} onClick={onClose} /></header>
    <div className="ricky-context"><Icon name="building" /><div><span>COMPANY CONTEXT</span><strong>{company}</strong></div></div>
    <div className="ricky-scroll"><Button design="Transparent" disabled={locked} onClick={onReads}>Company reads</Button>
      <MessageStrip design="Information" hideCloseButton>Deterministic preparation; no model call. Saved suggestions require human review and do not change your business records.</MessageStrip>
      {!canRead && <Empty title="Saved suggestions unavailable" icon="locked">Your current Company permissions do not allow these requests.</Empty>}
      {canRead && runId && <>
        {reading.loading && <Loading label="Checking the saved request and current access…" />}
        {accessError && <Failure error={accessError} onRetry={() => setRefresh(value => value + 1)} />}
        {reading.data && !reading.loading && !accessError && <><div className="run-status"><Status value={reading.data.run.status} /><span>Saved Company request</span></div>{reading.data.run.error && <MessageStrip design="Negative" hideCloseButton>{reading.data.run.error.message}</MessageStrip>}{review.loading && <Loading label="Checking the saved suggestion and exact original citations…" />}{review.data && !review.loading && <SavedReview {...review.data} user={user} navigate={navigate} />}{reading.data.events.items.length > 0 && <details><summary>Preparation progress</summary>{reading.data.events.items.map(row => <p key={row.id}>{labels[row.tool_name]} · {human(row.status)}</p>)}</details>}</>}
        <Button disabled={locked} onClick={() => setRefresh(value => value + 1)}>Refresh suggestion access</Button>
      </>}
      {runId && <><Button disabled={stop.busy || building || start.locked || Boolean(stopped)} onClick={async () => { const value = stop.unknown ? await stop.recover() : await stop.run({ company, run_id: runId }); if (value) { setStopped(value.status); setRefresh(value => value + 1); } }}>{stop.unknown ? 'Recover original Stop' : 'Stop this request'}</Button>{stopped && <p role="status">Stop confirmed: {human(stopped)}. This receipt contains no source contents. A terminal saved suggestion remains available under current access.</p>}{!locked && (stopped || reading.data && terminalSuggestion(reading.data.run.status)) && <Button onClick={reset}>New suggestion</Button>}</>}
      {!runId && canRead && <SuggestionForm company={company} pointer={pointer} capabilities={capabilities} locked={locked} onSubmit={submit} />}
      {start.unknown && <Button disabled={start.busy} onClick={async () => accept(await start.recover())}>Recover original suggestion request</Button>}
      {start.error && <Failure error={start.error} />}{stop.error && <Failure error={stop.error} />}{localError && <Failure error={localError} />}
      <p className="caption">Keep this view open if a command result is uncertain. Recover retains the original request. A confirmed request can be reopened in this browser session.</p>
    </div>
  </aside>;
}

function SuggestionForm({ company, pointer, capabilities, locked, onSubmit }: { company: string; pointer: string; capabilities: string[]; locked: boolean; onSubmit: (request: Selection) => Promise<void> }) {
  const [action, setAction] = useState<Selection['action']>('aec.scope.draft');
  const [pursuit, setPursuit] = useState(''); const [owner, setOwner] = useState<{ id: string; revision: string }>();
  const [pursuitCursor, setPursuitCursor] = useState<string>(); const [pursuitPages, setPursuitPages] = useState<(string | undefined)[]>([]);
  const [ownerCursor, setOwnerCursor] = useState<string>(); const [ownerPages, setOwnerPages] = useState<(string | undefined)[]>([]);
  const [linePage, setLinePage] = useState(0); const [target, setTarget] = useState(''); const [source, setSource] = useState(''); const [sourceKind, setSourceKind] = useState<QuantityChoice['source_kind']>('estimate-line');
  const [measurementCursor, setMeasurementCursor] = useState<string>(); const [measurementPages, setMeasurementPages] = useState<(string | undefined)[]>([]);
  const [quantities, setQuantities] = useState<{ choice: QuantityChoice; label: string }[]>([]);
  const [sections, setSections] = useState([{ heading: 'Suggested scope', text: '' }]); const [notes, setNotes] = useState(''); const [claims, setClaims] = useState('');
  const [query, setQuery] = useState(''); const [searched, setSearched] = useState(''); const [citations, setCitations] = useState<CompanyCitation[]>([]);
  const allowed = capabilities.includes('commercial.read') && capabilities.includes('document.read') && (action === 'aec.scope.draft' || capabilities.includes('estimate.read'));
  const pursuits = useResource(allowed ? `${pointer}/suggestion-pursuits/${pursuitCursor || ''}` : null, async signal => { const value = await commercial.pursuits(company, pursuitCursor, signal); if (!Array.isArray(value.items) || value.items.some(row => row.company !== company || !row.id)) throw invalid(); return value; });
  const pursuitRead = useResource(allowed && pursuit ? `${pointer}/suggestion-pursuit/${pursuit}` : null, async signal => { const value = await commercial.pursuit(company, pursuit, signal); if (value.id !== pursuit || value.company !== company) throw invalid(); return value; });
  const proposals = useResource(allowed && pursuit && action === 'aec.scope.draft' ? `${pointer}/suggestion-proposals/${pursuit}/${ownerCursor || ''}` : null, async signal => { const value = await commercial.proposals(company, ownerCursor, signal); if (!Array.isArray(value.items) || value.items.some(row => row.company !== company)) throw invalid(); return value; });
  const estimates = useResource(allowed && pursuit && action === 'aec.estimate.draft' ? `${pointer}/suggestion-estimates/${pursuit}/${ownerCursor || ''}` : null, async signal => { const value = await companyEstimating.list(company, 'estimate', signal, ownerCursor); if (!Array.isArray(value.items) || value.items.some(row => !companyRecord(row, company))) throw invalid(); return value; });
  const base = useResource(allowed && owner && pursuitRead.data ? `${pointer}/suggestion-base/${action}/${pursuit}/${owner.id}/${owner.revision}` : null, async signal => {
    if (action === 'aec.scope.draft') {
      const value = await commercial.proposal(company, owner!.id, signal);
      if (value.id !== owner!.id || value.company !== company || value.pursuit !== pursuit || value.current_revision !== owner!.revision || value.revision.id !== owner!.revision || value.revision.proposal !== owner!.id || value.revision.company !== company || value.revision.status !== 'draft') throw invalid();
      return { number: value.revision.revision_number, revision: value.revision.id };
    }
    const estimate = await companyEstimating.get(company, 'estimate', owner!.id, signal);
    const revision = await companyEstimating.get(company, 'revision', owner!.revision, signal);
    const snapshot = await companyEstimating.get(company, 'snapshot', revision.calculation_snapshot, signal);
    if (!companyRecord(estimate, company) || !companyRecord(revision, company) || !companyRecord(snapshot, company) || estimate.id !== owner!.id || estimate.pursuit_id !== pursuit || estimate.current_revision !== owner!.revision || revision.id !== owner!.revision || revision.estimate !== estimate.id || snapshot.id !== revision.calculation_snapshot || snapshot.subject_id !== revision.id || snapshot.estimate !== estimate.id || snapshot.inputs.unit_manifest.scope.company !== company || snapshot.inputs.unit_manifest.scope.scope_type !== 'Company' || snapshot.inputs.unit_manifest.scope.project !== null) throw invalid();
    return { number: revision.revision_number, revision: revision.id, estimate, snapshot, lines: revision.line_record_ids };
  });
  const lines = useResource(action === 'aec.estimate.draft' && base.data?.lines ? `${pointer}/suggestion-lines/${base.data.revision}/${linePage}` : null, signal => Promise.all(base.data!.lines!.slice(linePage * 20, (linePage + 1) * 20).map(async id => { const value = await rpc<CompanyEstLineRecord>('cipher_aec.estimating.company_api.get_record', { company, kind: 'line', record_id: id }, false, signal); if (!companyRecord(value, company) || value.id !== id || value.estimate !== owner?.id || value.estimate_revision !== base.data!.revision) throw invalid(); return value; })));
  const measurements = useResource(allowed && action === 'aec.estimate.draft' && owner && sourceKind === 'measurement' ? `${pointer}/suggestion-measurements/${owner.id}/${measurementCursor || ''}` : null, async signal => { const value = await rpc<CompanyTakeoffListResponse>('cipher_aec.takeoff.company_api.list_records', { company, kind: 'measurement', cursor: measurementCursor, limit: 20, count_mode: 'none' }, false, signal); if (!Array.isArray(value.items) || value.items.some(row => !companyRecord(row.record, company) || !('definition' in row.record))) throw invalid(); return value; });
  const found = useResource(allowed && searched ? `${pointer}/suggestion-citations/${searched}` : null, async signal => { const value = await rpc<CompanyCitationList>('cipher_aec.documents.company_api.search_documents', { company, query: searched, limit: 8 }, false, signal); if (!Array.isArray(value.items) || value.items.some(row => !companyRecord(row, company) || !row.document_id || !row.id || !row.revision_id)) throw invalid(); return value; });
  const clearOwner = () => { setOwner(undefined); setLinePage(0); setTarget(''); setSource(''); setQuantities([]); };
  const clearParent = () => { clearOwner(); setOwnerCursor(undefined); setOwnerPages([]); setCitations([]); setSearched(''); setQuery(''); };
  const targetLine = lines.data?.find(row => row.id === target); const sourceLine = lines.data?.find(row => row.id === source);
  const measurement = measurements.data?.items.find(row => row.record.id === source && row.current_use?.eligible && 'definition' in row.record)?.record as CompanyTakeoffMeasurementRecord | undefined;
  const units = savedUnits(base.data?.snapshot) || []; const targetUnit = units.find(row => row.id === targetLine?.authored.quantity.unit_id);
  const sourceExists = sourceKind === 'estimate-line' ? Boolean(sourceLine) : Boolean(measurement && ['manual', 'calibrated'].includes(measurement.definition.method));
  const canAdd = Boolean(targetLine && targetUnit && sourceExists && quantities.length < 8 && !quantities.some(row => row.choice.line_record_id === target) && !lines.loading && !measurements.loading);
  const unverified = claims.split('\n').map(row => row.trim()).filter(Boolean);
  const request = { schema: 'cipher.ricky.company.proposal-request.v1', pursuit_id: pursuit, action, arguments: action === 'aec.scope.draft' ? { proposal_revision_id: base.data?.revision, sections: sections.map(row => ({ ...row, citation_ids: citations.map(row => row.id) })), unverified_claims: unverified } : { base_revision_id: base.data?.revision, selections: quantities.map(row => row.choice), notes, citation_ids: citations.map(row => row.id), unverified_claims: unverified }, sources: citations.map(row => ({ citation_id: row.id, revision_id: row.revision_id, page: row.page, excerpt_sha256: row.excerpt_sha256, source_sha256: row.source_sha256 })), measurement_ids: [...new Set(quantities.filter(row => row.choice.source_kind === 'measurement').map(row => row.choice.source_id))] } as Selection;
  const valid = allowed && !pursuitRead.loading && !pursuitRead.error && !base.loading && !base.error && Boolean(base.data) && validSuggestionSelection(request) && (action !== 'aec.scope.draft' || sections.every(row => row.text.trim()));
  const ownerRows = action === 'aec.scope.draft' ? proposals.data?.items.filter(row => row.pursuit === pursuit).map(row => ({ id: row.id, revision: row.current_revision, title: row.title })) : estimates.data?.items.filter(row => row.pursuit_id === pursuit && row.current_revision).map(row => ({ id: row.id, revision: row.current_revision!, title: row.title }));
  const ownerResource = action === 'aec.scope.draft' ? proposals : estimates;
  return <div className="dialog-form">
    {!allowed && <MessageStrip design="Information" hideCloseButton>Current pursuit and source access is required. Estimate suggestions also require estimate access.</MessageStrip>}
    <Label>Suggestion</Label><Select accessibleName="Company suggestion type" disabled={locked} onChange={event => { setAction(event.detail.selectedOption.value as Selection['action']); clearParent(); }}>{Object.entries(labels).filter(([action]) => action === 'aec.scope.draft' || capabilities.includes('estimate.read')).map(([value, label]) => <Option key={value} value={value} selected={action === value}>{label}</Option>)}</Select>
    <Label>Pursuit</Label><Select accessibleName="Suggestion pursuit" disabled={locked || pursuits.loading || !allowed} onChange={event => { setPursuit(event.detail.selectedOption.value!); clearParent(); }}><Option value="" selected={!pursuit}>Choose a pursuit</Option>{pursuits.data?.items.map(row => <Option key={row.id} value={row.id} selected={pursuit === row.id}>{row.title}</Option>)}</Select>{pursuits.error && <Failure error={pursuits.error} />}{pursuitRead.error && <Failure error={pursuitRead.error} />}
    {(pursuitPages.length > 0 || pursuits.data?.next_cursor) && <div className="page-controls"><Button disabled={locked || !pursuitPages.length} onClick={() => { setPursuitCursor(pursuitPages.at(-1)); setPursuitPages(pursuitPages.slice(0, -1)); setPursuit(''); clearParent(); }}>Previous pursuits</Button><Button disabled={locked || !pursuits.data?.next_cursor} onClick={() => { setPursuitPages([...pursuitPages, pursuitCursor]); setPursuitCursor(pursuits.data!.next_cursor!); setPursuit(''); clearParent(); }}>More pursuits</Button></div>}
    <Label>{action === 'aec.scope.draft' ? 'Commercial draft' : 'Working estimate'}</Label><Select accessibleName="Suggestion working record" disabled={locked || !pursuit || ownerResource.loading || !allowed} onChange={event => { const row = ownerRows?.find(row => row.id === event.detail.selectedOption.value); clearOwner(); if (row) setOwner({ id: row.id, revision: row.revision }); }}><Option value="" selected={!owner}>Choose a current working record</Option>{ownerRows?.map(row => <Option key={row.id} value={row.id} selected={owner?.id === row.id}>{row.title}</Option>)}</Select>{ownerResource.error && <Failure error={ownerResource.error} />}
    {(ownerPages.length > 0 || ownerResource.data?.next_cursor) && <div className="page-controls"><Button disabled={locked || !ownerPages.length} onClick={() => { setOwnerCursor(ownerPages.at(-1)); setOwnerPages(ownerPages.slice(0, -1)); clearOwner(); }}>Previous working records</Button><Button disabled={locked || !ownerResource.data?.next_cursor} onClick={() => { setOwnerPages([...ownerPages, ownerCursor]); setOwnerCursor(ownerResource.data!.next_cursor!); clearOwner(); }}>More working records</Button></div>}
    {base.loading && <Loading label="Checking the exact selected working revision…" />}{base.error && <Failure error={base.error} onRetry={() => { clearOwner(); ownerResource.refresh(); }} />}{base.data && !base.loading && <p className="caption">Selected working revision {base.data.number}. The request retains this exact revision.</p>}
    {action === 'aec.scope.draft' ? <><p className="caption">Enter your proposed scope. Every section cites the evidence selected below.</p>{sections.map((row, index) => <div key={index} className="dialog-form"><Label>Section {index + 1}</Label><Input accessibleName={`Scope heading ${index + 1}`} disabled={locked} value={row.heading} maxlength={200} onInput={event => { const heading = event.currentTarget!.value; setSections(values => values.map((value, i) => i === index ? { ...value, heading } : value)); }} /><TextArea accessibleName={`Scope text ${index + 1}`} disabled={locked} value={row.text} rows={3} maxlength={2000} onInput={event => { const text = event.currentTarget!.value; setSections(values => values.map((value, i) => i === index ? { ...value, text } : value)); }} />{sections.length > 1 && <Button disabled={locked} onClick={() => setSections(values => values.filter((_, i) => i !== index))}>Remove section {index + 1}</Button>}</div>)}<Button disabled={locked || sections.length >= 8} onClick={() => setSections([...sections, { heading: '', text: '' }])}>Add scope section</Button></> : <>
      <Label>Target saved line</Label><Select accessibleName="Suggestion target line" disabled={locked || lines.loading || !base.data} onChange={event => setTarget(event.detail.selectedOption.value!)}><Option value="" selected={!target}>Choose a line to review</Option>{lines.data?.map(row => <Option key={row.id} value={row.id} selected={target === row.id}>{row.authored.description} · {row.authored.quantity.amount}</Option>)}</Select>{lines.error && <Failure error={lines.error} />}
      {base.data?.lines && base.data.lines.length > 20 && <div className="page-controls"><Button disabled={locked || !linePage} onClick={() => { setLinePage(value => value - 1); setTarget(''); setSource(''); }}>Previous saved lines</Button><Button disabled={locked || (linePage + 1) * 20 >= base.data.lines.length} onClick={() => { setLinePage(value => value + 1); setTarget(''); setSource(''); }}>More saved lines</Button></div>}
      <Label>Existing quantity source</Label><Select accessibleName="Suggestion quantity source kind" disabled={locked} onChange={event => { setSourceKind(event.detail.selectedOption.value as QuantityChoice['source_kind']); setSource(''); }}><Option value="estimate-line" selected={sourceKind === 'estimate-line'}>Saved estimate line</Option><Option value="measurement" selected={sourceKind === 'measurement'}>Eligible saved measurement</Option></Select>
      <Select accessibleName="Suggestion quantity source" disabled={locked || lines.loading || measurements.loading} onChange={event => setSource(event.detail.selectedOption.value!)}><Option value="" selected={!source}>Choose an existing canonical quantity</Option>{sourceKind === 'estimate-line' ? lines.data?.map(row => <Option key={row.id} value={row.id} selected={source === row.id}>{row.authored.description} · {row.authored.quantity.amount}</Option>) : measurements.data?.items.filter(row => row.current_use?.eligible && 'definition' in row.record).map(row => { const value = row.record as CompanyTakeoffMeasurementRecord; return <Option key={value.id} value={value.id} selected={source === value.id}>{value.definition.locator} · {value.result.quantity.amount}</Option>; })}</Select>{measurements.error && <Failure error={measurements.error} />}
      {(measurementPages.length > 0 || measurements.data?.next_cursor) && sourceKind === 'measurement' && <div className="page-controls"><Button disabled={locked || !measurementPages.length} onClick={() => { setMeasurementCursor(measurementPages.at(-1)); setMeasurementPages(measurementPages.slice(0, -1)); setSource(''); }}>Previous measurements</Button><Button disabled={locked || !measurements.data?.next_cursor} onClick={() => { setMeasurementPages([...measurementPages, measurementCursor]); setMeasurementCursor(measurements.data!.next_cursor!); setSource(''); }}>More measurements</Button></div>}
      {targetLine && <p className="caption">Target line unit: {unitLabel(targetUnit)}. Quantity preparation uses the saved canonical source.</p>}<Button disabled={locked || !canAdd} onClick={() => { if (targetLine && targetUnit) { setQuantities([...quantities, { choice: { line_record_id: target, source_kind: sourceKind, source_id: source, target_unit_id: targetUnit.id }, label: `${targetLine.authored.description} ← ${sourceKind === 'estimate-line' ? sourceLine?.authored.description : measurement?.definition.locator} · ${unitLabel(targetUnit)}` }]); setTarget(''); setSource(''); } }}>Add selected quantity</Button>
      {quantities.map((row, index) => <div key={row.choice.line_record_id}><span>{row.label}</span><Button accessibleName={`Remove quantity ${index + 1}`} design="Transparent" icon="decline" disabled={locked} onClick={() => setQuantities(values => values.filter((_, i) => i !== index))} /></div>)}<Label>Authored estimate notes</Label><TextArea accessibleName="Suggestion estimate notes" disabled={locked} value={notes} maxlength={2000} rows={3} onInput={event => setNotes(event.currentTarget!.value)} />
    </>}
    <Label>Exact source evidence</Label><Input accessibleName="Find suggestion evidence" disabled={locked || !allowed} value={query} onInput={event => setQuery(event.currentTarget!.value)} /><Button disabled={locked || !query.trim() || !allowed} onClick={() => setSearched(query.trim())}>Find suggestion evidence</Button>{found.loading && <Loading label="Finding authorized source excerpts…" />}{found.error && <Failure error={found.error} />}{found.data?.items.map(row => <CheckBox key={row.id} text={`${row.document_title} · Rev. ${row.revision_number} · ${row.page_label}`} disabled={locked || citations.length >= 8 && !citations.some(value => value.id === row.id)} checked={citations.some(value => value.id === row.id)} onChange={event => { const checked = event.currentTarget!.checked; setCitations(values => checked ? [...values.filter(value => value.id !== row.id), row] : values.filter(value => value.id !== row.id)); }} />)}{citations.map(row => <div className="citation" key={row.id}><span>{row.document_title} · {row.page_label}</span><Button disabled={locked} accessibleName={`Remove evidence ${row.page_label}`} icon="decline" design="Transparent" onClick={() => setCitations(values => values.filter(value => value.id !== row.id))} /></div>)}
    <Label>Unverified statements · one per line</Label><TextArea accessibleName="Suggestion unverified statements" disabled={locked} value={claims} rows={2} maxlength={2000} onInput={event => setClaims(event.currentTarget!.value)} />
    {JSON.stringify(request.arguments).length > 4096 && <MessageStrip design="Information" hideCloseButton>Shorten this suggestion before preparing it.</MessageStrip>}
    <Button design="Emphasized" disabled={locked || !valid} onClick={() => onSubmit(request)}>{labels[action]}</Button>
  </div>;
}

function SavedReview({ proposal, citations, units, user, navigate }: { proposal: Suggestion; citations: CompanyCitation[]; units: Unit[]; user: string; navigate: (path: string) => void }) {
  const output = proposal.preparation; const expired = Date.parse(proposal.expires_at) <= Date.now();
  return <section aria-label="Saved suggestion review"><Title level="H3">Saved suggestion</Title><MessageStrip design="Information" hideCloseButton>Review required. This is an unverified author suggestion, prepared deterministically. It has not been applied.</MessageStrip>
    <p>Version {proposal.version} · Prepared {date(proposal.created_at)} · {user}</p><p role="status">{expired ? 'Review window expired. Authorized historical review remains available.' : `Review window ends ${new Date(proposal.expires_at).toLocaleString('en-US')}.`} This view does not grant permission to apply the suggestion.</p>
    <p className="caption">Retained original preparation. Later working revisions do not replace this saved suggestion.</p>
    {output.kind === 'scope-draft.v1' ? output.proposed_fields.sections.map((row, index) => <div key={index}><h4>{row.heading}</h4><p style={{ whiteSpace: 'pre-wrap' }}>{row.text}</p></div>) : <><h4>Proposed canonical quantities</h4>{output.proposed_fields.quantity_selections.map(row => <div key={row.line_record_id}><p>{row.quantity.numerator} / {row.quantity.denominator} {unitLabel(units.find(unit => unit.id === row.quantity.target_unit_id))}</p><p className="caption">{human(row.quantity.provenance)} · {human(row.quantity.quantity_basis)} · {row.quantity.independently_verified ? 'Independently verified source' : 'No independent quantity verification claimed'}</p></div>)}<h4>Authored notes</h4><p style={{ whiteSpace: 'pre-wrap' }}>{output.proposed_fields.notes || 'None supplied.'}</p></>}
    <h4>Unverified statements</h4>{output.unverified_claims.length ? output.unverified_claims.map((row, index) => <p key={index}>{row}</p>) : <p>None supplied.</p>}
    <h4>Original source excerpts</h4>{citations.map(row => <div key={row.id} className="citation"><Icon name="document-text" /><div><Link onClick={() => navigate(`/company/documents/${encodeURIComponent(row.document_id)}/revisions/${encodeURIComponent(row.revision_id)}?${new URLSearchParams({ company: proposal.company, page: String(row.page) })}`)}>{row.document_title} · Rev. {row.revision_number} · {row.page_label}</Link><p>{row.excerpt}</p></div></div>)}
    <details><summary>Original selection and integrity details</summary><pre>{JSON.stringify({ suggestion_id: proposal.id, run_id: proposal.run_id, step_id: proposal.step_id, invocation_id: proposal.invocation_id, version: proposal.version, preparation_digest: proposal.preparation_digest, content_digest: proposal.content_digest, source_manifest: proposal.source_manifest, preparation: proposal.preparation }, null, 2)}</pre></details>
  </section>;
}
