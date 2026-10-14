import { useEffect, useState } from 'react';
import { Button, Input, Select, Spinner, Tab, TabList } from '@fluentui/react-components';
import { SearchRegular } from '@fluentui/react-icons';
import { AppLink, navigate } from '../app/navigation';
import { money, rate, sumCents } from '../copy/format';
import { statusText } from '../copy/terms';
import { KeyFacts, Notice, RecordTable, Section, StatusChip, TechnicalDetails } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { memoryKey, useActionMemory } from './ActionMemory';
import { APError, readPacket } from './client';
import { APHeader, Changes, Checks, Problems } from './presentation';
import type { Approval, Bill, Commitment, Packet, Project, Session, Workspace } from './types';

export const billName = (bill: { sequence: number }) => `Bill ${bill.sequence}`;
const billStatus = (bill: Bill) => bill.businessApproval?.effectiveStatus === 'pending' ? 'pending' : bill.effectiveStatus;
const periodStatus = (status: string) => ({ open: 'Open', closed: 'Closed', locked: 'Locked' })[status] ?? 'Status unavailable';
const stamp = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York',
  }).format(parsed) + ' Eastern';
};
export function BillTable({ rows }: { rows: Bill[] }) {
  return <RecordTable label="Bills" rows={rows} columns={[
    { key: 'bill', label: 'Bill', render: row => <AppLink href={`/bills/${encodeURIComponent(row.id)}`}>{billName(row)}<span className="cipher-cell-secondary">{row.supplierName}</span></AppLink> },
    { key: 'project', label: 'Project', render: row => row.projectName },
    { key: 'period', label: 'Certification period', render: row => row.certificationPeriod.name },
    { key: 'status', label: 'Status', render: row => <StatusChip status={billStatus(row)} /> },
    { key: 'due', label: 'Amount due', money: true, render: row => money(row.amountDueCents) },
    { key: 'payable', label: 'Open payable', money: true, render: row => money(row.currentDueCents) },
    { key: 'retained', label: 'Retainage', money: true, render: row => money(row.retainageCents) },
  ]} empty="No bills match this view." />;
}
export function ApprovalTable({ rows }: { rows: Approval[] }) {
  return <RecordTable label="Business review requests" rows={rows} columns={[
    { key: 'request', label: 'Business review', render: row => <AppLink href={`/approvals/${encodeURIComponent(row.id)}`}>{row.subjectLabel}</AppLink> },
    { key: 'project', label: 'Project', render: row => row.projectName },
    { key: 'requestedBy', label: 'Requested by', render: row => row.requestedBy.displayName },
    { key: 'amount', label: 'Amount due', money: true, render: row => money(row.amountDueCents) },
    { key: 'status', label: 'Status', render: row => <StatusChip status={row.effectiveStatus} /> },
    { key: 'expiry', label: 'Expires', render: row => stamp(row.expiresAt) },
  ]} empty="No business review requests match this view." />;
}
function ProjectTable({ rows }: { rows: Project[] }) {
  return <RecordTable label="Projects" rows={rows} columns={[
    { key: 'project', label: 'Project', render: row => <AppLink href={`/projects/${encodeURIComponent(row.id)}`}>{row.name}</AppLink> },
    { key: 'client', label: 'Client', render: row => row.customerName ?? 'Client not listed' },
    { key: 'budget', label: 'Budget', money: true, render: row => money(row.budgetCents, true) },
  ]} empty="No projects match this search." />;
}
function CommitmentTable({ rows }: { rows: Commitment[] }) {
  return <RecordTable label="Subcontracts" rows={rows} columns={[
    { key: 'title', label: 'Subcontract', render: row => <AppLink href={`/commitments/${encodeURIComponent(row.id)}`}>{row.title}</AppLink> },
    { key: 'supplier', label: 'Supplier', render: row => row.supplierName },
    { key: 'project', label: 'Project', render: row => row.projectName },
    { key: 'status', label: 'Status', render: row => <StatusChip status={row.status} /> },
    { key: 'amount', label: 'Executed amount', money: true, render: row => money(row.executedAmountCents) },
  ]} empty="No subcontracts match this view." />;
}
export function APHome({ workspace: w, session }: { workspace: Workspace; session: Session }) {
  const pending = w.approvals.filter(row => row.effectiveStatus === 'pending');
  const drafts = w.bills.filter(row => row.effectiveStatus === 'draft');
  const isAccountant = session.duties.includes('accountant');
  return <>
    <APHeader title={isAccountant ? 'Books' : 'My projects'} subtitle={`Welcome, ${session.person?.displayName}. Your practice projects and current work.`} />
    <div className="cipher-content-grid"><div className="cipher-main-stack"><Section title="Waiting on you" extra={<AppLink href={isAccountant ? '/posting-queue' : '/approvals'}>View all</AppLink>}>
      {isAccountant ? <><p>Request a draft bill’s business approval or review an approved bill for independent posting.</p><BillTable rows={drafts.slice(0, 5)} /><AppLink className="cipher-ap-page-link" href="/posting-queue">Post approved bills</AppLink></> : <ApprovalTable rows={pending.slice(0, 5)} />}
    </Section></div><aside className="cipher-side-stack" aria-label="Scoped workspace counts"><div className="cipher-metric-grid">
      {[{ label: 'Business reviews pending', value: pending.length, href: '/approvals?status=pending', source: 'Current scoped requests' },
        { label: 'Certified draft bills', value: drafts.length, href: '/bills?status=draft', source: 'Current scoped bills' },
        { label: 'Bills in posting queue', value: w.postingQueue.length, href: '/posting-queue', source: 'Approved scoped bills' },
        { label: 'Practice projects', value: w.projects.length, href: '/projects', source: 'Current project access' }].map(metric =>
        <AppLink key={metric.label} href={metric.href} className="cipher-metric"><strong>{metric.value}</strong><span>{metric.label}</span><small>{metric.source}</small></AppLink>)}
    </div></aside></div>
    <Section title="My projects" extra={<AppLink href="/projects">View all projects</AppLink>}><ProjectTable rows={w.projects} /></Section>
    <Section title="Invoice matches waiting for review" extra={<AppLink href="/match-approvals">View match reviews</AppLink>}><RecordTable label="Pending invoice match reviews" rows={w.matchApprovals.filter(row => row.effectiveStatus === 'pending').slice(0, 5)} columns={[
      { key: 'invoice', label: 'Supplier invoice', render: row => <AppLink href={`/match-approvals/${encodeURIComponent(row.id)}`}>{row.invoiceNumber}<span className="cipher-cell-secondary">{row.supplierName}</span></AppLink> },
      { key: 'requester', label: 'Requested by', render: row => row.requestedBy.displayName },
      { key: 'amount', label: 'Invoice amount', money: true, render: row => money(row.amountCents) },
    ]} empty="No supplier invoice matches are waiting for review in your project scope." /></Section>
    <Section title="Recent bills"><BillTable rows={w.bills.slice(0, 5)} /></Section>
  </>;
}
export function APList({ workspace: w, collection, search, status }: {
  workspace: Workspace; collection: 'projects' | 'commitments' | 'bills' | 'approvals'; search: string; status: string;
}) {
  const names = { projects: 'Projects', commitments: 'Subcontracts', bills: 'Bills', approvals: 'Business reviews' };
  const all = w[collection];
  const rows = all.filter(row => Object.entries(row).filter(([key]) => ['name', 'title', 'supplierName', 'projectName', 'commitmentTitle', 'subjectLabel'].includes(key)).map(([, value]) => value).join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()) &&
    (status === 'all' || ('effectiveStatus' in row ? row.effectiveStatus === status : 'status' in row && row.status === status)));
  const states = [...new Set(all.flatMap(row => 'effectiveStatus' in row ? [row.effectiveStatus] : 'status' in row ? [row.status] : []))];
  function filter(nextSearch: string, nextStatus: string) {
    const query = new URLSearchParams(); if (nextSearch) query.set('search', nextSearch); if (nextStatus !== 'all') query.set('status', nextStatus);
    navigate(`/${collection}${query.size ? `?${query}` : ''}`, true);
  }
  return <>
    <APHeader title={`${names[collection]} (${all.length})`} subtitle="Records in your current practice project scope." />
    <div className="cipher-filter-bar"><label className="cipher-filter-field"><span>Search {names[collection].toLowerCase()}</span><Input aria-label={`Search ${names[collection].toLowerCase()}`} contentBefore={<SearchRegular aria-hidden="true" />} value={search} onChange={(_, data) => filter(data.value, status)} placeholder="Search by name" /></label>
      {states.length > 0 && <label className="cipher-filter-field"><span>Status</span><Select aria-label="Filter by status" value={status} onChange={(_, data) => filter(search, data.value)}><option value="all">All statuses</option>{states.map(state => <option key={state} value={state}>{statusText(state)}</option>)}</Select></label>}
      {(search || status !== 'all') && <Button appearance="subtle" onClick={() => filter('', 'all')}>Clear filters</Button>}
    </div><p className="cipher-caption" role="status">{rows.length} of {all.length} scoped records shown</p>
    <Section title={names[collection]}>{collection === 'projects' ? <ProjectTable rows={rows as Project[]} /> : collection === 'commitments' ? <CommitmentTable rows={rows as Commitment[]} /> : collection === 'bills' ? <BillTable rows={rows as Bill[]} /> : <ApprovalTable rows={rows as Approval[]} />}</Section>
  </>;
}
export function APProject({ project, workspace: w, tab }: { project: Project; workspace: Workspace; tab: string }) {
  const commitments = w.commitments.filter(row => row.projectId === project.id);
  const bills = w.bills.filter(row => row.projectId === project.id);
  const approvals = w.approvals.filter(row => row.projectId === project.id);
  return <>
    <div className="cipher-breadcrumb"><AppLink href="/projects">Projects</AppLink></div>
    <APHeader title={project.name} subtitle={project.customerName ?? project.entity} />
    <TabList selectedValue={tab} className="cipher-tab-bar" aria-label="Project tools" onTabSelect={(_, data) => navigate(`/projects/${encodeURIComponent(project.id)}${data.value === 'overview' ? '' : `/${data.value}`}`)}>{[
      ['overview', 'Overview'], ['commitments', 'Commitments'], ['bills', 'Bills'], ['approvals', 'Business reviews'],
    ].map(([value, label]) => <Tab key={value} value={value}>{label}</Tab>)}</TabList>
    {tab === 'overview' && <><Section title="Cost"><KeyFacts facts={[
      { label: 'Budget', value: money(project.budgetCents, true) },
      { label: 'Committed', value: money(sumCents(commitments.map(row => row.executedAmountCents)), true) },
      { label: 'Open payable', value: money(sumCents(bills.map(row => row.currentDueCents))), note: 'Posted practice bills after recorded payments and credits' },
    ]} /></Section><Section title="Current business reviews"><ApprovalTable rows={approvals.filter(row => row.effectiveStatus === 'pending')} /></Section></>}
    {tab === 'commitments' && <Section title="Subcontracts"><CommitmentTable rows={commitments} /></Section>}
    {tab === 'bills' && <Section title="Bills"><BillTable rows={bills} /></Section>}
    {tab === 'approvals' && <Section title="Business reviews"><ApprovalTable rows={approvals} /></Section>}
    <TechnicalDetails entries={[{ label: 'Project ID', value: project.id }]} />
  </>;
}
export function APCommitment({ commitment: c, workspace: w }: { commitment: Commitment; workspace: Workspace }) {
  return <>
    <div className="cipher-breadcrumb"><AppLink href={`/projects/${encodeURIComponent(c.projectId)}/commitments`}>{c.projectName}</AppLink><span>Subcontracts</span></div>
    <APHeader title={c.title} subtitle={c.supplierName}><StatusChip status={c.status} /></APHeader>
    <Section title="Subcontract amounts"><KeyFacts facts={[
      { label: 'Original amount', value: money(c.originalAmountCents) }, { label: 'Executed amount', value: money(c.executedAmountCents) }, { label: 'Retainage rate', value: rate(c.retainageRateMicros) },
    ]} /></Section>
    <Section title="Prepare and receive"><div className="cipher-link-row"><AppLink href={`/commitments/${encodeURIComponent(c.id)}/prepare-bill`}>Prepare a bill</AppLink><AppLink href={`/commitments/${encodeURIComponent(c.id)}/receive-invoice`}>Receive a supplier invoice</AppLink><AppLink href="/invoices">Open invoices</AppLink></div><p className="cipher-caption">An authorized accountant prepares certified installed work and receives the supplier’s invoice using existing source evidence.</p></Section>
    <Section title="Certified bills"><BillTable rows={w.bills.filter(row => row.commitmentId === c.id)} /></Section>
    <TechnicalDetails entries={[{ label: 'Subcontract ID', value: c.id }]} />
  </>;
}
function BillLines({ bill }: { bill: Bill }) {
  return <RecordTable label="Certified work" rows={bill.lines} columns={[
    { key: 'line', label: 'Description', render: row => row.description }, { key: 'cost', label: 'Cost code', render: row => row.costCode },
    { key: 'prior', label: 'Prior installed work', money: true, render: row => money(row.priorInstalledCents) },
    { key: 'current', label: 'Installed this period', money: true, render: row => money(row.thisPeriodInstalledCents) },
    { key: 'cumulative', label: 'Installed to date', money: true, render: row => money(row.cumulativeInstalledCents) },
  ]} />;
}
function BillHistory({ bill }: { bill: Bill }) {
  return <ol className="cipher-ap-history">
    {bill.businessApproval && <li><strong>Business approval requested by {bill.businessApproval.requestedBy.displayName}</strong><p>{stamp(bill.businessApproval.requestedAt)} · {statusText(bill.businessApproval.effectiveStatus)}</p></li>}
    {bill.businessApproval?.approvedBy && bill.businessApproval.approvedAt && <li><strong>Business approval granted by {bill.businessApproval.approvedBy.displayName}</strong><p>{stamp(bill.businessApproval.approvedAt)}. No journal or payable was created by approval.</p></li>}
    {bill.posting && <li><strong>Posted by {bill.posting.postedBy.displayName} to {bill.posting.period.name}</strong><p>{stamp(bill.posting.postedAt)}{bill.posting.reason && ` · ${bill.posting.reason}`}</p></li>}
    {!bill.businessApproval && !bill.posting && <li>No business approval or posting is recorded.</li>}
  </ol>;
}
export function APBill({ bill: b, session, onChanged, onSessionLost }: {
  bill: Bill; session: Session; onChanged: () => void; onSessionLost: () => void;
}) {
  const rememberedPost = useActionMemory().get(memoryKey('bill.post', b.id))?.prepared?.body;
  const [periodId, setPeriodId] = useState(typeof rememberedPost?.periodId === 'string' ? rememberedPost.periodId : b.posting?.period.id ?? b.postingPeriods.find(period => period.id === b.certificationPeriod.id)?.id ?? b.postingPeriods[0]?.id ?? '');
  const [reason, setReason] = useState(typeof rememberedPost?.reason === 'string' ? rememberedPost.reason : b.posting?.reason ?? '');
  const isAccountant = session.duties.includes('accountant');
  const selected = b.postingPeriods.find(period => period.id === periodId);
  const laterPeriod = periodId !== b.certificationPeriod.id;
  return <>
    <div className="cipher-breadcrumb"><AppLink href={`/projects/${encodeURIComponent(b.projectId)}/bills`}>{b.projectName}</AppLink><span>Bills</span></div>
    <APHeader title={`${billName(b)} from ${b.supplierName}`} subtitle={`${b.commitmentTitle} · Certified in ${b.certificationPeriod.name}`}><StatusChip status={billStatus(b)} /></APHeader>
    <Section title="Certified amounts"><KeyFacts facts={[
      { label: 'Amount due', value: money(b.amountDueCents) }, { label: 'This period', value: money(b.thisPeriodCents), note: 'Certified work and stored materials' },
      { label: 'Retainage this period', value: money(b.retainageCents) }, { label: 'Open payable', value: money(b.currentDueCents), note: b.posting ? 'After recorded payments and credits' : 'No posted payable yet' },
    ]} /></Section>
    <Section title="Review, post, pay"><ol className="cipher-lifecycle"><li><strong>Business review</strong><span>{b.businessApproval?.approvedBy ? `Approved by ${b.businessApproval.approvedBy.displayName}` : 'A project manager reviews and grants business approval.'}</span></li><li><strong>Independent posting</strong><span>{b.posting ? `${b.posting.postedBy.displayName} posted to ${b.posting.period.name}.` : 'A different accountant posts the reviewed working ledger entry.'}</span></li><li><strong>Payment</strong><span>No payment is started by this workflow.</span></li></ol></Section>
    {b.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={b.blockedReasons} /></Section>}
    <Section title="Certified work"><BillLines bill={b} /></Section>
    <Section title="Related records"><div className="cipher-link-row"><AppLink href={`/commitments/${encodeURIComponent(b.commitmentId)}`}>Open subcontract</AppLink>{b.businessApproval && <AppLink href={`/approvals/${encodeURIComponent(b.businessApproval.approvalId)}`}>Open business review</AppLink>}{isAccountant && <AppLink href="/posting-queue">Post approved bills</AppLink>}</div></Section>
    <Section title="Recorded history"><BillHistory bill={b} /></Section>
    <Section title="Resolve bill exceptions"><AppLink href={`/bills/${encodeURIComponent(b.id)}/exceptions`}>Review bill cancellation or correction</AppLink></Section>
    {isAccountant && ['draft', 'pending'].includes(b.status) && <Section title="Request business approval"><ActionPanel action="bill.requestApproval" id={b.id} version={b.version} csrf={session.csrfToken} amountCents={b.amountDueCents} permitted={b.availableActions.includes('bill.requestApproval')} onChanged={onChanged} onSessionLost={onSessionLost} /></Section>}
    {isAccountant && (b.status === 'approved' || b.posting !== null) && <Section title="Post approved bill">
      {!b.posting && <div className="cipher-form"><label className="cipher-field"><span>Posting period</span><Select aria-label="Posting period" value={periodId} onChange={(_, data) => setPeriodId(data.value)}>{b.postingPeriods.map(period => <option key={period.id} value={period.id}>{period.name} · {periodStatus(period.status)}</option>)}</Select></label>
        <label className="cipher-field"><span>{laterPeriod ? 'Reason for a different posting period (required)' : 'Posting reason (optional)'}</span><Input aria-label="Posting reason" value={reason} maxLength={500} required={laterPeriod} onChange={(_, data) => setReason(data.value)} /></label>
        <p className="cipher-caption">Certification stays in {b.certificationPeriod.name}. A different posting period requires a reason and a fresh review.</p></div>}
      <ActionPanel action="bill.post" id={b.id} version={b.version} csrf={session.csrfToken} amountCents={b.amountDueCents} body={{ periodId, reason }} periodName={selected?.name ?? b.posting?.period.name} permitted={b.availableActions.includes('bill.post')} onChanged={onChanged} onSessionLost={onSessionLost} />
    </Section>}
    {!isAccountant && <Notice>Use the business review request to make a project manager’s decision. Independent posting belongs to an accountant.</Notice>}
    <TechnicalDetails entries={[{ label: 'Bill ID', value: b.id }, ...(b.posting ? [{ label: 'Posting receipt', value: b.posting.receiptId }] : [])]} />
  </>;
}
export function APApproval({ approvalId, revision, session, onChanged, onSessionLost }: {
  approvalId: string; revision: number; session: Session; onChanged: () => void; onSessionLost: () => void;
}) {
  const [packet, setPacket] = useState<Packet | null>(null);
  const [problem, setProblem] = useState<Error | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readPacket(approvalId, controller.signal).then(value => { if (!controller.signal.aborted) { setPacket(value); setProblem(null); } }).catch(error => {
      if (controller.signal.aborted || error instanceof Error && error.name === 'AbortError') return;
      setProblem(error instanceof Error ? error : new Error('The business review could not be loaded.'));
      if (error instanceof APError && error.status === 401) onSessionLost();
      else if (error instanceof APError && [403, 404].includes(error.status)) { setPacket(null); onChanged(); }
    });
    return () => controller.abort();
  }, [approvalId, revision]);
  if (!packet) return <><APHeader title="Business review" />{problem ? <><p role="alert">{problem.message}</p><Button onClick={onChanged}>Refresh review</Button></> : <Spinner label="Loading current business review" />}</>;
  const b = packet.bill;
  return <>
    <div className="cipher-breadcrumb"><AppLink href="/approvals">Business reviews</AppLink><AppLink href={`/bills/${encodeURIComponent(b.id)}`}>{billName(b)}</AppLink></div>
    <APHeader title={`Approve ${billName(b)} from ${b.supplierName}`} subtitle={`${b.commitmentTitle} · ${b.projectName}`}><StatusChip status={b.businessApproval?.effectiveStatus ?? packet.status} /></APHeader>
    {problem && <p role="alert">{problem.message}</p>}
    <p className="cipher-current-payment">{money(packet.amountDueCents)} is due for the certified bill after retainage.</p>
    <Section title="Business decision facts"><KeyFacts facts={[
      { label: 'Amount due', value: money(packet.amountDueCents) }, { label: 'Retainage', value: money(packet.retainedCents) },
      { label: 'Certification period', value: b.certificationPeriod.name }, { label: 'Requested by', value: packet.requestedBy.displayName },
      { label: 'Requested', value: stamp(packet.requestedAt) }, { label: 'Expires', value: stamp(packet.expiresAt) },
    ]} /></Section>
    <Section title="Current checks"><Checks checks={packet.checks} /></Section>
    <Section title="What changed"><Changes changes={packet.changes} /></Section>
    <Section title="Source records"><KeyFacts facts={[
      ...(typeof packet.sourceSummary.supplierInvoiceAttached === 'boolean' ? [{ label: 'Supplier invoice', value: packet.sourceSummary.supplierInvoiceAttached ? 'Attached to the certified bill' : 'No invoice attached' }] : []),
      ...(Number.isSafeInteger(packet.sourceSummary.storedEvidenceCount) ? [{ label: 'Stored-material evidence records', value: String(packet.sourceSummary.storedEvidenceCount) }] : []),
    ]} /></Section>
    <Section title="Certified work"><BillLines bill={b} /></Section>
    <details className="cipher-details"><summary>Recorded history and responsibilities</summary><BillHistory bill={b} /><p>Business approval records the project manager’s decision. A different accountant separately posts the entry and payable.</p></details>
    <Section title="Business approval">
      {session.duties.includes('pm') ? <ActionPanel action="bill.approve" id={approvalId} version={packet.version} csrf={session.csrfToken} amountCents={packet.amountDueCents} permitted={packet.status === 'pending'} onChanged={onChanged} onSessionLost={onSessionLost} />
        : <Notice>A project manager reviews and approves this bill. Your accountant session can request approval and separately post an approved bill.</Notice>}
    </Section>
    <TechnicalDetails entries={[{ label: 'Business review ID', value: packet.approvalId }]} />
  </>;
}
export function APPostingQueue({ workspace: w }: { workspace: Workspace }) {
  return <>
    <APHeader title={`Post approved bills (${w.postingQueue.length})`} subtitle="Business-approved bills awaiting independent working ledger posting." />
    <Notice>Approval creates no journal or payable. Open a bill, select a posting period, and review the exact entry before posting.</Notice>
    <Section title="Approved bills"><RecordTable label="Post approved bills" rows={w.postingQueue.map(row => ({ ...row, id: row.billId }))} columns={[
      { key: 'bill', label: 'Bill', render: row => <AppLink href={`/bills/${encodeURIComponent(row.billId)}`}>{billName(row)}<span className="cipher-cell-secondary">{row.supplierName}</span></AppLink> },
      { key: 'commitment', label: 'Subcontract', render: row => row.commitmentTitle },
      { key: 'amount', label: 'Amount due', money: true, render: row => money(row.amountDueCents) },
      { key: 'approver', label: 'Business approver', render: row => row.approvedBy.displayName },
      { key: 'expiry', label: 'Authorization expires', render: row => stamp(row.expiresAt) },
      { key: 'ready', label: 'Posting checks', render: row => row.ready ? 'Ready for current review' : <Problems reasons={row.blockedReasons} /> },
    ]} empty="No approved bills await posting in your current project scope." /></Section>
  </>;
}
export function APMissing() {
  return <><APHeader title="This record is unavailable in your practice project scope" /><p>Refresh your project list or choose a record you can read.</p><AppLink href="/projects">Open projects</AppLink></>;
}
