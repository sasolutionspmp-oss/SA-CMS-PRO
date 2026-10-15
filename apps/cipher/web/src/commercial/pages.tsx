import { Button, Input, Select } from '@fluentui/react-components';
import { AppLink, navigate } from '../app/navigation';
import { money } from '../copy/format';
import { KeyFacts, Notice, RecordTable, Section, TechnicalDetails } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { memoryKey, useCommercialMemory } from './Memory';
import { readAcceptancePacket, readApprovals, readComparison, readDraftCommitment, readEstimate, readEstimatePreparation, readEstimates, readHandoff, readHandoffPreparation, readHandoffs, readProjects } from './client';
import { ManualEstimateForm } from './forms';
import { Checks, CommercialHeader, CommercialStatus, LoadingRecord, Markers, ratioPercent, stamp, useRecord, type Controls } from './presentation';
import { ComparisonFacts, DrawingFacts, EstimateDetails, EstimateFacts, EstimateHistory, HandoffLines, estimateName } from './records';
import type { Action, ActionAvailability, CollectionFilters } from './types';

const available = (rows: ActionAvailability[], action: Action) => rows.some(item => item.action === action && item.allowed);
const restrictions = (rows: ActionAvailability[]) => rows.filter(item => !item.allowed && item.reason).map(item => ({ code: item.action, message: item.reason! }));
const projectList = (_id: string, signal?: AbortSignal) => readProjects(signal);
function filters(query: string): CollectionFilters {
  const values = new URLSearchParams(query); return Object.fromEntries(['projectId', 'search', 'status'].flatMap(key => values.get(key) ? [[key, values.get(key)!]] : []));
}
const estimateList = (query: string, signal?: AbortSignal) => readEstimates(signal, filters(query));
const approvalList = (query: string, signal?: AbortSignal) => readApprovals(signal, filters(query));
const handoffList = (query: string, signal?: AbortSignal) => readHandoffs(signal, filters(query));
async function estimateRecord(id: string, signal?: AbortSignal) {
  const [estimate, comparison] = await Promise.all([readEstimate(id, signal), readComparison(id, signal)]);
  if (comparison.estimateId !== estimate.id || comparison.predecessorId !== (estimate.predecessor?.id ?? null) || comparison.totals.afterCents !== estimate.totalCents) throw new Error('The current estimate and comparison changed while reading. Refresh the source record.');
  return { estimate, comparison };
}
async function revisionRecord(id: string, signal?: AbortSignal) {
  const estimate = await readEstimate(id, signal); const preparation = await readEstimatePreparation(estimate.project.id, signal); return { estimate, preparation };
}
export function ProjectsPage({ revision, ...controls }: Controls & { revision: number }) {
  const { record, problem } = useRecord('projects', revision, projectList, controls);
  if (!record) return <LoadingRecord title="Commercial projects" problem={problem} onChanged={controls.onChanged} />;
  return <><CommercialHeader title={`Commercial projects (${record.count})`} subtitle="Current project scope for manual estimates and source-preserving subcontract drafts." /><Section title="Projects"><RecordTable label="Commercial projects" rows={record.items} columns={[
    { key: 'name', label: 'Project', render: row => <AppLink href={`/projects/${encodeURIComponent(row.id)}/estimate-preparation`}>{row.name}</AppLink> },
    { key: 'entity', label: 'Entity', render: row => row.entity }, { key: 'estimates', label: 'Estimates', render: row => String(row.estimateCount) },
    { key: 'handoffs', label: 'Handoffs', render: row => String(row.handoffCount) },
    { key: 'entry', label: 'Manual estimating', render: row => <AppLink href={`/projects/${encodeURIComponent(row.id)}/estimate-preparation`}>Enter a manual estimate</AppLink> },
  ]} empty="No projects are currently available to this practice person." /></Section></>;
}
function ListFilters({ path, query, statuses }: { path: string; query: string; statuses: { value: string; count: number }[] }) {
  const values = new URLSearchParams(query); const search = values.get('search') ?? ''; const status = values.get('status') ?? '';
  function update(key: string, value: string) { const next = new URLSearchParams(query); if (value) next.set(key, value); else next.delete(key); navigate(`${path}${next.size ? '?' + next : ''}`); }
  return <div className="cipher-list-toolbar"><Input aria-label="Search commercial records" placeholder="Search current scoped records" value={search} onChange={(_, data) => update('search', data.value)} /><Select aria-label="Commercial record status" value={status} onChange={(_, data) => update('status', data.value)}><option value="">All statuses</option>{statuses.map(item => <option key={item.value} value={item.value}>{item.value.replaceAll('_', ' ')} ({item.count})</option>)}</Select>{query && <Button appearance="subtle" onClick={() => navigate(path)}>Clear filters</Button>}</div>;
}
export function EstimatesPage({ query, revision, ...controls }: Controls & { query: string; revision: number }) {
  const { record, problem } = useRecord(query, revision, estimateList, controls);
  if (!record) return <LoadingRecord title="Estimates" problem={problem} onChanged={controls.onChanged} />;
  return <><CommercialHeader title={`Estimates (${record.count})`} subtitle="Manual quantities, priced revisions and independent estimator acceptance."><AppLink href="/projects">Enter a manual estimate</AppLink></CommercialHeader>
    <ListFilters path="/estimates" query={query} statuses={record.facets.statuses} />
    <Section title="Current scoped estimate view"><KeyFacts facts={[{ label: 'Records in this view', value: String(record.count) }, ...(record.totals.totalCents === undefined ? [] : [{ label: 'Server total for this view', value: money(record.totals.totalCents) }])]} /><RecordTable label="Commercial estimates" rows={record.items} columns={[
      { key: 'revision', label: 'Estimate', render: row => <AppLink href={`/estimates/${encodeURIComponent(row.id)}`}>{estimateName(row)}<span className="cipher-cell-secondary">{row.project.name}</span></AppLink> },
      { key: 'source', label: 'Drawing source', render: row => <>{row.source.title}<span className="cipher-cell-secondary">Revision {row.source.revision} · {row.source.current ? 'Current drawing' : 'Newer drawing exists'}</span></> },
      { key: 'status', label: 'Business state', render: row => <CommercialStatus status={row.effectiveStatus} /> },
      { key: 'subtotal', label: 'Subtotal', money: true, render: row => money(row.subtotalCents) }, { key: 'contingency', label: 'Contingency', money: true, render: row => money(row.contingencyCents) },
      { key: 'total', label: 'Total', money: true, render: row => money(row.totalCents) },
    ]} empty="No estimates match this view. Open a project to enter an owned manual source." /></Section>
  </>;
}
export function AcceptanceListPage({ query, revision, ...controls }: Controls & { query: string; revision: number }) {
  const { record, problem } = useRecord(query, revision, approvalList, controls);
  if (!record) return <LoadingRecord title="Acceptance reviews" problem={problem} onChanged={controls.onChanged} />;
  return <><CommercialHeader title={`Acceptance reviews (${record.count})`} subtitle="Independent estimator authorization and separate acceptance application." /><ListFilters path="/estimate-approvals" query={query} statuses={record.facets.statuses} /><Section title="Estimator acceptance reviews"><RecordTable label="Estimator acceptance reviews" rows={record.items} columns={[
    { key: 'estimate', label: 'Review', render: row => <AppLink href={`/estimate-approvals/${encodeURIComponent(row.id)}`}>Revision {row.estimateRevision}<span className="cipher-cell-secondary">{row.project.name}</span></AppLink> },
    { key: 'requester', label: 'Requested by', render: row => row.requestedBy.displayName }, { key: 'status', label: 'State', render: row => <CommercialStatus status={row.effectiveStatus} /> },
    { key: 'total', label: 'Estimate total', money: true, render: row => money(row.totalCents) }, { key: 'expires', label: 'Expires', render: row => stamp(row.expiresAt) },
  ]} empty="No acceptance reviews match this current scope." /></Section></>;
}
export function HandoffListPage({ query, revision, ...controls }: Controls & { query: string; revision: number }) {
  const { record, problem } = useRecord(query, revision, handoffList, controls);
  if (!record) return <LoadingRecord title="Estimate handoffs" problem={problem} onChanged={controls.onChanged} />;
  return <><CommercialHeader title={`Estimate handoffs (${record.count})`} subtitle="Immutable accepted-source packages and their own commercial subcontract records." /><ListFilters path="/estimate-handoffs" query={query} statuses={record.facets.statuses} /><Section title="Accepted-source handoffs"><RecordTable label="Accepted estimate handoffs" rows={record.items} columns={[
    { key: 'title', label: 'Handoff', render: row => <AppLink href={`/estimate-handoffs/${encodeURIComponent(row.id)}`}>{row.commitmentTitle}<span className="cipher-cell-secondary">{row.project.name} · Estimate revision {row.estimateRevision}</span></AppLink> },
    { key: 'supplier', label: 'Supplier', render: row => row.supplier.name }, { key: 'status', label: 'State', render: row => <CommercialStatus status={row.effectiveStatus} /> },
    { key: 'total', label: 'Source total', money: true, render: row => money(row.totalCents) },
    { key: 'draft', label: 'Created subcontract', render: row => row.commitmentId ? <AppLink href={`/commercial-commitments/${encodeURIComponent(row.commitmentId)}`}>Open source-bound record</AppLink> : 'No draft created' },
  ]} empty="No accepted-source handoffs match this view." /></Section></>;
}
export function EstimateEntryPage({ projectId, revision, ...controls }: Controls & { projectId: string; revision: number }) {
  const { record, problem } = useRecord(projectId, revision, readEstimatePreparation, controls);
  if (!record) return <LoadingRecord title="Enter a manual estimate" problem={problem} onChanged={controls.onChanged} />;
  return <ManualEstimateForm key={projectId} preparation={record} {...controls} />;
}
export function EstimateRevisionPage({ estimateId, revision, ...controls }: Controls & { estimateId: string; revision: number }) {
  const { record, problem } = useRecord(estimateId, revision, revisionRecord, controls);
  if (!record) return <LoadingRecord title="Revise estimate" problem={problem} onChanged={controls.onChanged} />;
  return <ManualEstimateForm key={estimateId} preparation={record.preparation} estimate={record.estimate} {...controls} />;
}
export function EstimatePage({ estimateId, revision, ...controls }: Controls & { estimateId: string; revision: number }) {
  const { record, problem } = useRecord(estimateId, revision, estimateRecord, controls);
  if (!record) return <LoadingRecord title="Estimate record" problem={problem} onChanged={controls.onChanged} />;
  const e = record.estimate;
  return <><div className="cipher-breadcrumb"><AppLink href="/estimates">Estimates</AppLink><AppLink href="/projects">{e.project.name}</AppLink></div><CommercialHeader title={estimateName(e)} subtitle={e.project.name}><CommercialStatus status={e.effectiveStatus} /></CommercialHeader>
    <Markers items={e.markers} /><EstimateFacts estimate={e} /><ComparisonFacts comparison={record.comparison} /><EstimateHistory estimate={e} />
    <Section title="Current source actions"><Markers items={restrictions(e.availableActions)} /><div className="cipher-link-row">{available(e.availableActions, 'estimate.revise') && <AppLink href={`/estimates/${encodeURIComponent(e.id)}/revise`}>Create a successor revision</AppLink>}{available(e.availableActions, 'estimate.prepareHandoff') && <AppLink href={`/estimates/${encodeURIComponent(e.id)}/handoff-preparation`}>Review accepted-source handoff</AppLink>}</div>
      <ActionPanel action="estimate.request" id={e.id} version={e.version} permitted={available(e.availableActions, 'estimate.request')} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
    </Section><EstimateDetails estimate={e} /></>;
}
export function AcceptancePage({ approvalId, revision, ...controls }: Controls & { approvalId: string; revision: number }) {
  const { record: p, problem } = useRecord(approvalId, revision, readAcceptancePacket, controls); const memory = useCommercialMemory();
  if (!p) return <LoadingRecord title="Estimate acceptance review" problem={problem} onChanged={controls.onChanged} />;
  const show = (action: Action) => available(p.availableActions, action) || !!memory.get(memoryKey(action, approvalId))?.prepared;
  return <><div className="cipher-breadcrumb"><AppLink href="/estimate-approvals">Acceptance reviews</AppLink><AppLink href={`/estimates/${encodeURIComponent(p.estimate.id)}`}>{estimateName(p.estimate)}</AppLink></div><CommercialHeader title={`Review ${estimateName(p.estimate).toLowerCase()}`} subtitle={p.estimate.project.name}><CommercialStatus status={p.approval.effectiveStatus} /></CommercialHeader>
    <Notice>{p.summary}</Notice><EstimateFacts estimate={p.estimate} /><ComparisonFacts comparison={p.comparison} />
    <Section title="Independent estimator decision"><KeyFacts facts={[{ label: 'Requested by', value: p.approval.requestedBy.displayName }, { label: 'Requested', value: stamp(p.approval.requestedAt) }, { label: 'Expires', value: stamp(p.approval.expiresAt) }, ...(p.approval.approvedBy ? [{ label: 'Authorized by', value: p.approval.approvedBy.displayName }] : [])]} /><Checks items={p.checks} /><p>{p.consequence}</p><p>A different authorized estimator grants the decision. An authorized estimator then separately applies it; this is not PM subcontract approval or customer award.</p></Section>
    {show('estimate.accept') && <Section title="Authorize independent acceptance"><ActionPanel action="estimate.accept" id={approvalId} version={p.version} permitted={available(p.availableActions, 'estimate.accept')} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>}
    {show('estimate.apply') && <Section title="Apply authorized acceptance"><ActionPanel action="estimate.apply" id={approvalId} version={p.version} permitted={available(p.availableActions, 'estimate.apply')} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>}
    <Markers items={restrictions(p.availableActions)} /><EstimateDetails estimate={p.estimate} />
  </>;
}
export function HandoffPreparationPage({ estimateId, revision, ...controls }: Controls & { estimateId: string; revision: number }) {
  const { record: p, problem } = useRecord(estimateId, revision, readHandoffPreparation, controls);
  if (!p) return <LoadingRecord title="Prepare accepted-source handoff" problem={problem} onChanged={controls.onChanged} />;
  return <><div className="cipher-breadcrumb"><AppLink href={`/estimates/${encodeURIComponent(estimateId)}`}>{estimateName(p.estimate)}</AppLink></div><CommercialHeader title="Prepare accepted-source handoff" subtitle={p.project.name} />
    <Section title="Fixed audited subcontract package"><KeyFacts facts={[{ label: 'Package title', value: p.package.title }, { label: 'Supplier', value: p.package.supplier.name }, { label: 'Retainage', value: ratioPercent(p.package.retainageRate) }, { label: 'Accepted source', value: estimateName(p.estimate) }, { label: 'Source subtotal', value: money(p.subtotalCents) }, { label: 'Source contingency', value: money(p.contingencyCents) }, { label: 'Source total', value: money(p.totalCents) }]} /><p>{p.consequence}</p><Notice>The server selects this explicit synthetic package. Every accepted source line is retained; no supplier, price, retainage or SOV override is entered here. Nonzero contingency requires separately qualified allocation semantics.</Notice></Section>
    <DrawingFacts source={p.estimate.source} /><Section title="Full accepted line correspondence"><HandoffLines lines={p.lines} /></Section><Section title="Source qualification"><Checks items={p.checks} /><Markers items={restrictions(p.availableActions)} />
      {p.existingHandoffId && <AppLink href={`/estimate-handoffs/${encodeURIComponent(p.existingHandoffId)}`}>Open existing handoff</AppLink>}
      <ActionPanel action="estimate.prepareHandoff" id={estimateId} version={p.version} permitted={available(p.availableActions, 'estimate.prepareHandoff')} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
    </Section></>;
}
export function HandoffPage({ handoffId, revision, ...controls }: Controls & { handoffId: string; revision: number }) {
  const { record: h, problem } = useRecord(handoffId, revision, readHandoff, controls);
  if (!h) return <LoadingRecord title="Accepted estimate handoff" problem={problem} onChanged={controls.onChanged} />;
  return <><div className="cipher-breadcrumb"><AppLink href="/estimate-handoffs">Estimate handoffs</AppLink><AppLink href={`/estimates/${encodeURIComponent(h.estimateId)}`}>Estimate revision {h.estimateRevision}</AppLink></div><CommercialHeader title={h.commitmentTitle} subtitle={h.project.name}><CommercialStatus status={h.effectiveStatus} /></CommercialHeader>
    <Section title="Immutable accepted source package"><KeyFacts facts={[{ label: 'Supplier', value: h.supplier.name }, { label: 'Retainage', value: ratioPercent(h.retainageRate) }, { label: 'Source total', value: money(h.totalCents) }, { label: 'Estimate revision', value: String(h.estimateRevision) }]} /><p>{h.consequence}</p></Section><DrawingFacts source={h.source} /><Section title="All accepted source lines"><HandoffLines lines={h.lines} mapped={h.commitmentId !== null} /></Section>
    {h.commitmentId && <Section title="Created subcontract record"><AppLink href={`/commercial-commitments/${encodeURIComponent(h.commitmentId)}`}>Open source-bound subcontract</AppLink></Section>}
    <Section title="Project manager draft review"><Markers items={restrictions(h.availableActions)} /><ActionPanel action="estimate.createCommitment" id={h.id} version={h.version} permitted={available(h.availableActions, 'estimate.createCommitment')} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>
    <TechnicalDetails entries={[{ label: 'Handoff ID', value: h.id }, { label: 'Source acceptance', value: h.acceptanceApprovalId }]} /></>;
}
export function CommitmentPage({ commitmentId, revision, ...controls }: Controls & { commitmentId: string; revision: number }) {
  const { record: c, problem } = useRecord(commitmentId, revision, readDraftCommitment, controls);
  if (!c) return <LoadingRecord title="Source-bound subcontract record" problem={problem} onChanged={controls.onChanged} />;
  return <><div className="cipher-breadcrumb"><AppLink href={`/estimate-handoffs/${encodeURIComponent(c.handoffId)}`}>Source handoff</AppLink><AppLink href={`/estimates/${encodeURIComponent(c.estimate.id)}`}>Estimate revision {c.estimate.revision}</AppLink></div><CommercialHeader title={c.title} subtitle={c.project.name}><CommercialStatus status={c.status} /></CommercialHeader>
    <Section title="Subcontract record and original source"><KeyFacts facts={[{ label: 'Current record state', value: <CommercialStatus status={c.status} /> }, { label: 'Original creation outcome', value: 'Subcontract draft' }, { label: 'Supplier', value: c.supplier.name }, { label: 'Original exact amount', value: money(c.originalAmountCents) }, { label: 'Retainage', value: ratioPercent(c.retainageRate) }, { label: 'Accepted estimate revision', value: String(c.estimate.revision) }, { label: 'Current source', value: <CommercialStatus status={c.effectiveSourceStatus} /> }]} /><Notice>{c.consequence}</Notice><p>This commercial handoff originally created a draft. Current state reflects the server's verified lifecycle. No contract execution, customer send, award or signature action is offered here.</p></Section>
    <DrawingFacts source={c.source} /><Section title="Original source-to-SOV correspondence"><HandoffLines lines={c.lines} mapped /></Section><Section title="Own commercial source records"><div className="cipher-link-row"><AppLink href={`/estimates/${encodeURIComponent(c.estimate.id)}`}>Open accepted source estimate</AppLink><AppLink href={`/estimate-handoffs/${encodeURIComponent(c.handoffId)}`}>Open original handoff</AppLink></div></Section>
    <TechnicalDetails entries={[{ label: 'Subcontract ID', value: c.id }, { label: 'Original acceptance', value: c.estimate.acceptanceApprovalId }]} /></>;
}
