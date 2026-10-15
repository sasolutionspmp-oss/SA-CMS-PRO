import { Button, Input, Select, Tab, TabList } from '@fluentui/react-components';
import { ArrowLeftRegular, SearchRegular } from '@fluentui/react-icons';
import type { Workspace, Collection, Project, Commitment, Bill, Approval } from '../api/types';
import { AppLink, navigate } from '../app/navigation';
import { money, date, rate, sumCents } from '../copy/format';
import { approvalLabel, statusText } from '../copy/terms';
import { KeyFacts, Notice, PageHeader, Section, StatusChip, TechnicalDetails } from '../ui/shared';
import { ApprovalTable, BillTable, CommitmentTable, ProjectTable, billName, projectName, subjectName } from './lists';

export function Home({ workspace: w }: { workspace: Workspace }) {
  const pending = w.approvals.filter(a => a.status === 'pending');
  const draftBills = w.bills.filter(b => b.status === 'draft');
  return <>
    <PageHeader title="My projects" helpKind="home" />
    <div className="cipher-content-grid"><div className="cipher-main-stack"><Section title="Waiting for review" extra={<AppLink href="/approvals">All requests</AppLink>}><ApprovalTable workspace={w} rows={pending} /></Section></div>
      <aside className="cipher-side-stack" aria-label="Workspace counts"><div className="cipher-metric-grid">
        {[{ label: 'Requests waiting for review', value: pending.length, href: '/approvals?status=pending', source: 'From current review requests' },
          { label: 'Draft sub pay apps', value: draftBills.length, href: '/bills?status=draft', source: 'From recorded pay apps' },
          { label: 'Executed subcontracts', value: w.commitments.filter(c => c.status === 'executed').length, href: '/commitments?status=executed', source: 'From the subcontract register' },
          { label: 'Practice projects', value: w.projects.length, href: '/projects', source: 'From the project list' }].map(metric =>
          <AppLink key={metric.label} href={metric.href} className="cipher-metric"><strong>{metric.value}</strong><span>{metric.label}</span><small>{metric.source}</small></AppLink>)}
      </div></aside>
    </div>
    <Section title="My projects" extra={<AppLink href="/projects">View all projects</AppLink>}><ProjectTable workspace={w} /></Section>
    <Section title="Explore the work"><div className="cipher-link-row"><AppLink href="/commitments">Subcontracts</AppLink><AppLink href="/bills">Sub pay apps</AppLink><AppLink href="/approvals">Review requests</AppLink></div></Section>
  </>;
}

export function ListPage({ workspace: w, collection, initialStatus = 'all', initialSearch = '' }: { workspace: Workspace; collection: Collection; initialStatus?: string; initialSearch?: string }) {
  const search = initialSearch;
  const status = initialStatus;
  const titles = { projects: 'Projects', commitments: 'Subcontracts', bills: 'Sub pay apps', approvals: 'Approvals' };
  const all = w[collection];
  const states = [...new Set(all.flatMap(row => 'status' in row ? [row.status] : []))];
  const includes = (row: Project | Commitment | Bill | Approval) => {
    const text = Object.entries(row).filter(([key]) => ['name', 'title', 'supplierName', 'customerName', 'projectName', 'commitmentTitle', 'subjectLabel', 'periodLabel'].includes(key)).map(([, value]) => value).join(' ').toLocaleLowerCase();
    return text.includes(search.toLocaleLowerCase()) && (status === 'all' || ('status' in row && row.status === status));
  };
  function chooseStatus(value: string) {
    const parameters = new URLSearchParams();
    if (value !== 'all') parameters.set('status', value);
    if (search) parameters.set('search', search);
    navigate(`/${collection}${parameters.size ? `?${parameters}` : ''}`);
  }
  return <>
    <PageHeader title={`${titles[collection]} (${all.length})`} subtitle={collection === 'approvals' ? 'Read the current requests. Decisions are unavailable in this practice view.' : undefined} helpKind={collection === 'approvals' ? 'approvals' : 'projects'} />
    <div className="cipher-filter-bar"><label className="cipher-filter-field"><span>Search {titles[collection].toLocaleLowerCase()}</span><Input contentBefore={<SearchRegular aria-hidden="true" />} value={search} onChange={(_, data) => { const parameters = new URLSearchParams(); if (status !== 'all') parameters.set('status', status); if (data.value) parameters.set('search', data.value); navigate(`/${collection}${parameters.size ? `?${parameters}` : ''}`, true); }} aria-label={`Search ${titles[collection].toLocaleLowerCase()}`} placeholder="Search by name" /></label>
      {states.length > 0 && <label className="cipher-filter-field"><span>Status</span><Select value={status} onChange={(_, data) => chooseStatus(data.value)} aria-label="Filter by status"><option value="all">All statuses</option>{states.map(value => <option key={value} value={value}>{statusText(value)} ({all.filter(row => 'status' in row && row.status === value).length})</option>)}</Select></label>}
      {(search || status !== 'all') && <Button appearance="subtle" onClick={() => navigate(`/${collection}`)}>Clear filters</Button>}
    </div>
    <p className="cipher-caption" role="status">{all.filter(includes).length} of {all.length} records shown</p>
    <Section title={titles[collection]}>
      {collection === 'projects' && <ProjectTable workspace={w} rows={w.projects.filter(includes)} />}
      {collection === 'commitments' && <CommitmentTable workspace={w} rows={w.commitments.filter(includes)} />}
      {collection === 'bills' && <BillTable workspace={w} rows={w.bills.filter(includes)} />}
      {collection === 'approvals' && <ApprovalTable workspace={w} rows={w.approvals.filter(includes)} />}
    </Section>
  </>;
}

export function ProjectPage({ workspace: w, project: p, tab }: { workspace: Workspace; project: Project; tab: string }) {
  const commitments = w.commitments.filter(c => c.projectId === p.id);
  const bills = w.bills.filter(b => b.projectId === p.id);
  const approvals = w.approvals.filter(a => a.projectId === p.id);
  const committed = sumCents(commitments.filter(c => ['executed', 'closed'].includes(c.status)).map(c => c.executedAmountCents));
  const awaiting = approvals.filter(a => a.status === 'pending');
  const tabs = [{ value: 'overview', label: 'Overview' }, { value: 'commitments', label: 'Commitments' }, { value: 'bills', label: 'Sub pay apps' }, { value: 'approvals', label: 'Review requests' }];
  return <>
    <div className="cipher-breadcrumb"><AppLink href="/projects">Projects</AppLink></div>
    <PageHeader title={p.name} subtitle={p.customerName ?? p.entity} helpKind="projects" />
    <TabList className="cipher-tab-bar" selectedValue={tab} onTabSelect={(_, data) => navigate(`/projects/${encodeURIComponent(p.id)}${data.value === 'overview' ? '' : `/${data.value}`}`)} aria-label="Project tools">{tabs.map(item => <Tab key={item.value} value={item.value}>{item.label}</Tab>)}</TabList>
    {tab === 'overview' && <>
      <Section title="Cost"><KeyFacts facts={[{ label: 'Budget', value: money(p.budgetCents, true) }, { label: 'Committed', value: money(committed, true), note: 'Executed and closed subcontracts' }, { label: 'Open payables', value: money(sumCents(bills.map(b => b.currentDueCents)), true), note: 'After recorded payments and credits' }]} /></Section>
      <div className="cipher-content-grid"><div className="cipher-main-stack"><Section title="Needs attention on this project">{awaiting.length > 0 ? <><p>{awaiting.length} {awaiting.length === 1 ? 'request is' : 'requests are'} waiting for review.</p><ApprovalTable workspace={w} rows={awaiting} /></> : <p>Nothing is waiting for review on this project.</p>}</Section></div>
        <aside className="cipher-side-stack"><Section title="This project"><dl className="cipher-compact-facts"><div><dt>Subcontracts</dt><dd><AppLink href={`/projects/${encodeURIComponent(p.id)}/commitments`}>{commitments.length} records</AppLink></dd></div><div><dt>Sub pay apps</dt><dd><AppLink href={`/projects/${encodeURIComponent(p.id)}/bills`}>{bills.length} records</AppLink></dd></div></dl></Section></aside>
      </div>
    </>}
    {tab === 'commitments' && <Section title={`Subcontracts (${commitments.length})`}><CommitmentTable workspace={w} rows={commitments} /></Section>}
    {tab === 'bills' && <Section title={`Sub pay apps (${bills.length})`}><BillTable workspace={w} rows={bills} /></Section>}
    {tab === 'approvals' && <Section title={`Review requests (${approvals.length})`}><ApprovalTable workspace={w} rows={approvals} /></Section>}
    <TechnicalDetails entries={[{ label: 'Project ID', value: p.id }]} />
  </>;
}

export function CommitmentPage({ workspace: w, commitment: c }: { workspace: Workspace; commitment: Commitment }) {
  const bills = w.bills.filter(b => b.commitmentId === c.id);
  const approvals = w.approvals.filter(a => a.subjectId === c.id || bills.some(b => b.id === a.subjectId));
  return <>
    <div className="cipher-breadcrumb"><AppLink href={`/projects/${encodeURIComponent(c.projectId)}/commitments`}>{projectName(w, c.projectId)}</AppLink><span>Subcontracts</span></div>
    <PageHeader title={c.title} subtitle={c.supplierName ?? 'Recorded subcontract'}><StatusChip status={c.status} /></PageHeader>
    <Section title="Subcontract amounts"><KeyFacts facts={[{ label: 'Original amount', value: money(c.originalAmountCents) }, { label: 'Executed amount', value: money(c.executedAmountCents) }, { label: 'Retainage', value: rate(c.retainageRateMicros) }]} /></Section>
    <Notice>Read-only record. Approval decisions, edits, posting, and payments are unavailable here.</Notice>
    <Section title={`Sub pay apps (${bills.length})`}><BillTable workspace={w} rows={bills} /></Section>
    <Section title="Related review requests"><ApprovalTable workspace={w} rows={approvals} /></Section>
    <TechnicalDetails entries={[{ label: 'Subcontract ID', value: c.id }, { label: 'Stored version', value: c.version }]} />
  </>;
}

export function BillPage({ workspace: w, bill: b }: { workspace: Workspace; bill: Bill }) {
  const approvals = w.approvals.filter(a => a.subjectId === b.id);
  return <>
    <div className="cipher-breadcrumb"><AppLink href={`/projects/${encodeURIComponent(b.projectId)}/bills`}>{projectName(w, b.projectId)}</AppLink><span>Sub pay apps</span></div>
    <PageHeader title={`${billName(b)} from ${b.supplierName ?? 'the recorded supplier'}`} subtitle={`${b.commitmentTitle ?? 'Recorded subcontract'} — ${b.periodLabel ?? 'recorded period'}`}><StatusChip status={b.status} /></PageHeader>
    <Section title="Application amounts"><KeyFacts facts={[{ label: 'Application amount', value: money(b.amountDueCents) }, { label: 'Retainage this period', value: money(b.retainageCents) }, { label: 'Open payable', value: money(b.currentDueCents), note: b.status === 'draft' ? 'Drafts have no posted payable' : 'After recorded payments and credits' }, ...(b.thisPeriodCents === undefined ? [] : [{ label: 'Work and stored materials this period', value: money(b.thisPeriodCents) }])]} /></Section>
    <Section title="Recorded workflow"><ol className="cipher-lifecycle"><li><strong>Review</strong><span>Business approval records the review decision without posting. This read-only view cannot grant approval.</span></li><li><strong>Post</strong><span>{b.journalId ? 'The practice workspace contains a posted entry.' : 'No posted entry is recorded.'}</span></li><li><strong>Pay</strong><span>No money is sent from this practice view.</span></li></ol></Section>
    <Section title="Related records"><div className="cipher-link-row"><AppLink href={`/commitments/${encodeURIComponent(b.commitmentId)}`}>Open subcontract</AppLink><AppLink href={`/projects/${encodeURIComponent(b.projectId)}`}>Open project</AppLink></div></Section>
    <Section title="Review requests"><ApprovalTable workspace={w} rows={approvals} /></Section>
    <TechnicalDetails entries={[{ label: 'Bill ID', value: b.id }, { label: 'Accounting period ID', value: b.periodId }, ...(b.journalId ? [{ label: 'Journal ID', value: b.journalId }] : [])]} />
  </>;
}

export function ApprovalPage({ workspace: w, approval: a }: { workspace: Workspace; approval: Approval }) {
  const subject = w.bills.some(b => b.id === a.subjectId) ? `/bills/${encodeURIComponent(a.subjectId)}` : w.commitments.some(c => c.id === a.subjectId) ? `/commitments/${encodeURIComponent(a.subjectId)}` : null;
  return <>
    <div className="cipher-breadcrumb"><AppLink href="/approvals">Approvals</AppLink></div>
    <PageHeader title={approvalLabel(a.operation)} subtitle={subjectName(w, a)} helpKind="approvals"><StatusChip status={a.status} /></PageHeader>
    <Notice>This request is read-only. No approval, posting, or payment can happen in this view.</Notice>
    <Section title="Request facts"><KeyFacts facts={[{ label: 'Amount', value: a.amountCents === null ? 'No amount recorded' : money(a.amountCents) }, { label: 'Project', value: projectName(w, a.projectId) }, { label: 'Requested', value: date(a.requestedAt) }, { label: 'Expires', value: date(a.expiresAt) }]} /></Section>
    <Section title="What happens next"><p>A person needs the complete decision packet and authenticated approval workflow before deciding this request.</p>{subject && <AppLink href={subject}>Open the related record</AppLink>}</Section>
    <details className="cipher-details"><summary>About review, posting, and payment</summary><p>Supplier-bill business approval and ledger posting are separate. A distinct authorized person posts an approved bill; payment follows its own review. This read-only view cannot grant approvals, post entries, or send payments.</p></details>
    <TechnicalDetails entries={[{ label: 'Approval ID', value: a.id }, { label: 'Stored operation', value: a.operation }, { label: 'Subject ID', value: a.subjectId }]} />
  </>;
}

export function MissingPage() {
  return <><PageHeader title="This record is not in the practice workspace" /><p>Open a project or return to the list to choose an available record.</p><Button icon={<ArrowLeftRegular />} onClick={() => navigate('/projects')}>Open projects</Button></>;
}
