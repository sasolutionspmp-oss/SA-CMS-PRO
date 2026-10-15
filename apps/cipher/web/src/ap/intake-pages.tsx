import { useEffect, useState } from 'react';
import { Button, Input, Select, Spinner } from '@fluentui/react-components';
import { AppLink, navigate } from '../app/navigation';
import { date, money, rate } from '../copy/format';
import { KeyFacts, Notice, RecordTable, Section, StatusChip, TechnicalDetails } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { memoryKey, useActionMemory } from './ActionMemory';
import { APError, readInvoice, readMatchPacket, readPreparation } from './client';
import { billName, BillTable } from './pages';
import { APHeader, Changes, Problems } from './presentation';
import type { Invoice, MatchApproval, MatchPacket, Preparation, Session, Workspace } from './types';

export interface Controls { session: Session; onChanged: () => void; onSessionLost: () => void }
const stamp = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York',
  }).format(parsed) + ' Eastern';
};
// Parse user-supplied decimal dollars without floating point arithmetic or rounding.
export function inputCents(value: string): number | null {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ''] = value.split('.');
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  return cents <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(cents) : null;
}
export const decimal = (cents: number) => `${BigInt(cents) / 100n}.${(BigInt(cents) % 100n).toString().padStart(2, '0')}`;
export function IntakeStatus({ status }: { status: string }) {
  const label: Record<string, string> = { received: 'Received', matched: 'Matched', rejected: 'Rejected', exception: 'Match needs attention', stale: 'Facts changed', available: 'Available', in_use: 'In use' };
  return label[status] ? <span className={`cipher-status cipher-status-${status === 'matched' ? 'positive' : status === 'rejected' ? 'negative' : ['exception', 'stale'].includes(status) ? 'warning' : 'neutral'}`}>{label[status]}</span> : <StatusChip status={status} />;
}
export function useRecord<T>(id: string, revision: number, read: (id: string, signal?: AbortSignal) => Promise<T>, controls: Controls) {
  const [record, setRecord] = useState<T | null>(null);
  const [problem, setProblem] = useState<Error | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    read(id, controller.signal).then(value => { if (!controller.signal.aborted) { setRecord(value); setProblem(null); } }).catch(error => {
      if (controller.signal.aborted || error instanceof Error && error.name === 'AbortError') return;
      setProblem(error instanceof Error ? error : new Error('The current practice record could not be loaded.'));
      if (error instanceof APError && error.status === 401) controls.onSessionLost();
      else if (error instanceof APError && [403, 404].includes(error.status)) setRecord(null);
    });
    return () => controller.abort();
  }, [id, revision, read]);
  return { record, problem };
}
export function LoadingRecord({ title, problem, onChanged }: { title: string; problem: Error | null; onChanged: () => void }) {
  return <><APHeader title={title} />{problem ? <><p role="alert">{problem.message}</p><Button onClick={onChanged}>Refresh record</Button></> : <Spinner label={`Reading ${title.toLocaleLowerCase()}`} />}</>;
}
export function InvoiceTable({ rows }: { rows: Invoice[] }) {
  return <RecordTable label="Supplier invoices" rows={rows} columns={[
    { key: 'invoice', label: 'Supplier invoice', render: row => <AppLink href={`/invoices/${encodeURIComponent(row.id)}`}>{row.invoiceNumber}<span className="cipher-cell-secondary">{row.supplierName}</span></AppLink> },
    { key: 'project', label: 'Project', render: row => row.projectName },
    { key: 'subcontract', label: 'Subcontract', render: row => row.commitmentTitle ?? 'Not assigned' },
    { key: 'amount', label: 'Invoice amount', money: true, render: row => money(row.amountCents) },
    { key: 'due', label: 'Due date', render: row => date(row.dueDate) },
    { key: 'status', label: 'Status', render: row => <IntakeStatus status={row.status} /> },
    { key: 'match', label: 'Match', render: row => row.match ? <IntakeStatus status={row.match.status} /> : 'Not computed' },
    { key: 'duplicate', label: 'Duplicate review', render: row => row.duplicateBlocking ? 'Review required' : row.possibleDuplicate ? 'Recorded review' : 'No duplicate flag' },
  ]} empty="No supplier invoices match this view. Open a subcontract to receive an invoice." />;
}
export function MatchTable({ rows }: { rows: MatchApproval[] }) {
  return <RecordTable label="Invoice match reviews" rows={rows} columns={[
    { key: 'invoice', label: 'Invoice match review', render: row => <AppLink href={`/match-approvals/${encodeURIComponent(row.id)}`}>{row.invoiceNumber}<span className="cipher-cell-secondary">{row.supplierName}</span></AppLink> },
    { key: 'project', label: 'Project', render: row => row.projectName },
    { key: 'amount', label: 'Invoice amount', money: true, render: row => money(row.amountCents) },
    { key: 'requester', label: 'Requested by', render: row => row.requestedBy.displayName },
    { key: 'status', label: 'Status', render: row => <IntakeStatus status={row.effectiveStatus} /> },
    { key: 'expires', label: 'Expires', render: row => stamp(row.expiresAt) },
  ]} empty="No invoice match reviews match this view." />;
}
export function APIntakeList({ workspace, collection, search, status }: {
  workspace: Workspace; collection: 'invoices' | 'match-approvals'; search: string; status: string;
}) {
  const isInvoices = collection === 'invoices';
  const all = isInvoices ? workspace.invoices : workspace.matchApprovals;
  const matching = (row: Invoice | MatchApproval) => [row.invoiceNumber, row.supplierName, row.projectName, 'commitmentTitle' in row ? row.commitmentTitle : ''].join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()) &&
    (status === 'all' || ('effectiveStatus' in row ? row.effectiveStatus : row.status) === status);
  const statuses = [...new Set(all.map(row => 'effectiveStatus' in row ? row.effectiveStatus : row.status))];
  const title = isInvoices ? 'Invoices' : 'Match reviews';
  function filters(nextSearch: string, nextStatus: string) {
    const query = new URLSearchParams(); if (nextSearch) query.set('search', nextSearch); if (nextStatus !== 'all') query.set('status', nextStatus);
    navigate(`/${collection}${query.size ? '?' + query : ''}`);
  }
  return <><APHeader title={title} subtitle={isInvoices ? 'Supplier invoice details, source evidence and current matching results in your project scope.' : 'Independent accountant decisions on current supplier invoice matches.'} />
    <div className="cipher-list-toolbar"><Input aria-label={`Search ${title.toLocaleLowerCase()}`} placeholder="Search invoice, supplier or project" value={search} onChange={(_, data) => filters(data.value, status)} />
      <Select aria-label={`Filter ${title.toLocaleLowerCase()} by status`} value={status} onChange={(_, data) => filters(search, data.value)}><option value="all">All statuses</option>{statuses.map(value => <option key={value} value={value}>{({ received: 'Received', matched: 'Matched', rejected: 'Rejected', stale: 'Facts changed', pending: 'Waiting for review', granted: 'Approved', consumed: 'Completed', expired: 'Expired', invalidated: 'Needs approval again' } as Record<string, string>)[value] ?? value}</option>)}</Select>
      {(search || status !== 'all') && <Button appearance="subtle" onClick={() => filters('', 'all')}>Clear filters</Button>}
    </div>
    <Section title={isInvoices ? 'Supplier invoices' : 'Invoice match reviews'}>{isInvoices ? <InvoiceTable rows={workspace.invoices.filter(matching)} /> : <MatchTable rows={workspace.matchApprovals.filter(matching)} />}</Section>
    {isInvoices && <Notice>Open a subcontract to receive an invoice using its existing supplier invoice evidence. No upload or payment occurs here.</Notice>}
  </>;
}
export function APPreparation({ commitmentId, revision, workspace, receive, ...controls }: Controls & {
  commitmentId: string; revision: number; workspace: Workspace; receive: boolean;
}) {
  const { record, problem } = useRecord(commitmentId, revision, readPreparation, controls);
  if (!record) return <LoadingRecord title={receive ? 'Receive supplier invoice' : 'Prepare bill'} problem={problem} onChanged={controls.onChanged} />;
  return <><div className="cipher-breadcrumb"><AppLink href={`/projects/${encodeURIComponent(record.projectId)}/commitments`}>{record.projectName}</AppLink><AppLink href={`/commitments/${encodeURIComponent(record.id)}`}>{record.commitmentTitle}</AppLink></div>
    <APHeader title={receive ? 'Receive supplier invoice' : 'Prepare bill'} subtitle={`${record.commitmentTitle} · ${record.supplierName}`} />
    {problem && <p role="alert">{problem.message}</p>}
    <Section title="Subcontract source"><KeyFacts facts={[{ label: 'Supplier', value: record.supplierName }, { label: 'Project', value: record.projectName }, { label: 'Retainage rate', value: rate(record.retainageRateMicros) }]} /></Section>
    {receive ? <ReceiveForm key={record.id} preparation={record} workspace={workspace} {...controls} /> : <PreparationForm key={record.id} preparation={record} {...controls} />}
    <Section title="Certified bills"><BillTable rows={workspace.bills.filter(bill => bill.commitmentId === record.id)} /></Section>
    <Section title="Related supplier invoices"><InvoiceTable rows={workspace.invoices.filter(invoice => invoice.commitmentId === record.id)} /></Section>
    <TechnicalDetails entries={[{ label: 'Subcontract ID', value: record.id }]} />
  </>;
}
function PreparationForm({ preparation: p, ...controls }: Controls & { preparation: Preparation }) {
  const remembered = useActionMemory().get(memoryKey('bill.prepare', p.id))?.prepared?.body;
  const priorInput = Array.isArray(remembered?.installed) ? remembered.installed : [];
  const [periodId, setPeriodId] = useState(typeof remembered?.periodId === 'string' ? remembered.periodId : p.periods[0]?.id ?? '');
  const [amounts, setAmounts] = useState<Record<string, string>>(() => Object.fromEntries(p.lines.map(line => {
    const saved = priorInput.find(item => item && typeof item === 'object' && 'sovLineId' in item && item.sovLineId === line.sovLineId);
    const cents = saved && typeof saved === 'object' && 'cumulativeInstalledCents' in saved && Number.isSafeInteger(saved.cumulativeInstalledCents) ? saved.cumulativeInstalledCents as number : line.priorInstalledCents;
    return [line.sovLineId, decimal(cents)];
  })));
  const valid = !!periodId && p.lines.every(line => inputCents(amounts[line.sovLineId] ?? '') !== null);
  return <>
    <Section title="Installed work to certify">
      {p.blockedReasons.length > 0 && <Problems reasons={p.blockedReasons} />}
      {p.priorBill && <p>Prior certification: <AppLink href={`/bills/${encodeURIComponent(p.priorBill.id)}`}>{billName(p.priorBill)}</AppLink>. Prior installed amounts below come from that bill.</p>}
      <label className="cipher-field cipher-ap-period-field"><span>Certification period</span><Select aria-label="Certification period" value={periodId} onChange={(_, data) => setPeriodId(data.value)}><option value="">Choose an open period</option>{p.periods.map(period => <option key={period.id} value={period.id}>{period.name}</option>)}</Select></label>
      <RecordTable label="Bill preparation schedule of values" rows={p.lines.map(line => ({ ...line, id: line.sovLineId }))} columns={[
        { key: 'line', label: 'Description', render: line => <>{line.description}<span className="cipher-cell-secondary">Cost code {line.costCode}</span></> },
        { key: 'scheduled', label: 'Scheduled amount', money: true, render: line => money(line.scheduledCents) },
        { key: 'prior', label: 'Prior installed work', money: true, render: line => money(line.priorInstalledCents) },
        { key: 'installed', label: 'Installed to date (USD)', render: line => <Input aria-label={`Installed to date for ${line.description}`} className="cipher-ap-money-input" inputMode="decimal" value={amounts[line.sovLineId] ?? ''} aria-invalid={inputCents(amounts[line.sovLineId] ?? '') === null} onChange={(_, data) => setAmounts(values => ({ ...values, [line.sovLineId]: data.value }))} /> },
      ]} />
      <p className="cipher-caption">Enter cumulative installed work in dollars with at most two decimal places. The server checks the subcontract and predecessor, computes retainage and certifies the reviewed amounts.</p>
      {!valid && <p role="status">Choose a period and enter an exact dollar amount for every schedule line before review.</p>}
      <ActionPanel action="bill.prepare" id={p.id} version={p.version} csrf={controls.session.csrfToken} amountCents={0}
        body={{ periodId, installed: p.lines.map(line => ({ sovLineId: line.sovLineId, cumulativeInstalledCents: inputCents(amounts[line.sovLineId] ?? '') })) }}
        permitted={valid && p.availableActions.includes('bill.prepare')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
    </Section>
    <AppLink href={`/commitments/${encodeURIComponent(p.id)}/receive-invoice`}>Receive a supplier invoice for this subcontract</AppLink>
  </>;
}
function ReceiveForm({ preparation: p, workspace, ...controls }: Controls & { preparation: Preparation; workspace: Workspace }) {
  const remembered = useActionMemory().get(memoryKey('invoice.receive', p.id))?.prepared?.body;
  const [invoiceNumber, setInvoiceNumber] = useState(typeof remembered?.invoiceNumber === 'string' ? remembered.invoiceNumber : '');
  const [invoiceDate, setInvoiceDate] = useState(typeof remembered?.invoiceDate === 'string' ? remembered.invoiceDate : '');
  const [amount, setAmount] = useState(Number.isSafeInteger(remembered?.amountCents) ? decimal(remembered!.amountCents as number) : '');
  const [revisionId, setRevisionId] = useState(typeof remembered?.evidenceRevisionId === 'string' ? remembered.evidenceRevisionId : '');
  const evidence = workspace.invoiceEvidence.filter(row => row.projectId === p.projectId && row.available && row.isCurrent);
  const selected = workspace.invoiceEvidence.find(row => row.revisionId === revisionId && row.projectId === p.projectId);
  const valid = !!invoiceNumber.trim() && /^\d{4}-\d{2}-\d{2}$/.test(invoiceDate) && inputCents(amount) !== null && inputCents(amount)! > 0 && !!revisionId;
  return <Section title="Supplier invoice details">
    <div className="cipher-form cipher-ap-intake-form">
      <label className="cipher-field"><span>Supplier invoice number</span><Input aria-label="Supplier invoice number" value={invoiceNumber} maxLength={64} onChange={(_, data) => setInvoiceNumber(data.value)} /></label>
      <label className="cipher-field"><span>Invoice date</span><Input aria-label="Invoice date" type="date" value={invoiceDate} onChange={(_, data) => setInvoiceDate(data.value)} /></label>
      <label className="cipher-field"><span>Invoice amount (USD)</span><Input aria-label="Invoice amount (USD)" inputMode="decimal" value={amount} aria-invalid={amount !== '' && inputCents(amount) === null} onChange={(_, data) => setAmount(data.value)} /></label>
      <label className="cipher-field"><span>Source invoice evidence</span><Select aria-label="Source invoice evidence" value={revisionId} onChange={(_, data) => setRevisionId(data.value)}><option value="">Choose existing supplier invoice evidence</option>
        {evidence.map(row => <option key={row.revisionId} value={row.revisionId}>{row.title} · Revision {row.revision}</option>)}
        {revisionId && selected && !evidence.includes(selected) && <option value={revisionId}>{selected.title} · Selected revision is now in use</option>}
        {revisionId && !selected && <option value={revisionId}>Previously reviewed source revision is unavailable</option>}
      </Select></label>
      {revisionId && !selected && <p role="status">The selected source revision is no longer listed. Choose current evidence for a new review; an exact retry keeps the original request.</p>}
      {!evidence.length && <Notice>No available supplier invoice evidence is listed for this project. Current records can still be read.</Notice>}
      <p className="cipher-caption">Enter the supplier’s invoice number, date and amount. Select an existing owned source revision; no file is uploaded here. Supplier, project and due date come from the subcontract and audited supplier terms.</p>
      {!valid && <p role="status">Complete the supplied invoice details and choose source evidence before review.</p>}
    </div>
    <ActionPanel action="invoice.receive" id={p.id} version={p.version} csrf={controls.session.csrfToken} amountCents={inputCents(amount) ?? 0}
      body={{ invoiceNumber, invoiceDate, amountCents: inputCents(amount), evidenceRevisionId: revisionId }}
      permitted={valid && p.availableActions.includes('invoice.receive')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
  </Section>;
}
export function APInvoice({ invoiceId, revision, ...controls }: Controls & { invoiceId: string; revision: number }) {
  const { record: invoice, problem } = useRecord(invoiceId, revision, readInvoice, controls);
  if (!invoice) return <LoadingRecord title="Supplier invoice" problem={problem} onChanged={controls.onChanged} />;
  const isAccountant = controls.session.duties.includes('accountant');
  return <><div className="cipher-breadcrumb"><AppLink href="/invoices">Invoices</AppLink><AppLink href={`/projects/${encodeURIComponent(invoice.projectId)}`}>{invoice.projectName}</AppLink></div>
    <APHeader title={`Invoice ${invoice.invoiceNumber}`} subtitle={`${invoice.supplierName} · ${invoice.commitmentTitle ?? invoice.projectName}`}><IntakeStatus status={invoice.status} /></APHeader>
    {problem && <p role="alert">{problem.message}</p>}
    <Section title="Received invoice"><KeyFacts facts={[{ label: 'Invoice amount', value: money(invoice.amountCents) }, { label: 'Invoice date', value: date(invoice.invoiceDate) }, { label: 'Due date', value: date(invoice.dueDate), note: 'Derived from audited supplier terms' }, { label: 'Supplier', value: invoice.supplierName }]} /></Section>
    <Section title="Source evidence"><KeyFacts facts={[{ label: 'Document', value: invoice.evidence.title }, { label: 'Source revision', value: String(invoice.evidence.revision) }, { label: 'Current source', value: invoice.evidence.isCurrent ? 'Current revision' : 'A newer source revision exists' }, { label: 'Duplicate review', value: invoice.duplicateBlocking ? 'Required before match approval' : invoice.possibleDuplicate ? 'Recorded review' : 'No duplicate flag' }]} /></Section>
    {invoice.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={invoice.blockedReasons} /></Section>}
    <Section title="Current invoice match">{invoice.match ? <><KeyFacts facts={[{ label: 'Match status', value: <IntakeStatus status={invoice.match.status} /> }, { label: 'Match basis', value: ['progress', 'installed_work'].includes(invoice.match.basis) ? 'Certified installed work' : invoice.match.basis.replaceAll('_', ' ') }]} />
      {invoice.match.exceptions.length > 0 && <ul className="cipher-ap-problems">{invoice.match.exceptions.map(reason => <li key={reason.code}>{reason.message}</li>)}</ul>}
      {invoice.match.billId && <AppLink href={`/bills/${encodeURIComponent(invoice.match.billId)}`}>Open matched bill</AppLink>}
    </> : <p>No match has been computed for this invoice.</p>}</Section>
    {isAccountant && invoice.status === 'received' && <><Section title="Compute invoice match"><ActionPanel action="invoice.computeMatch" id={invoice.id} version={invoice.version} csrf={controls.session.csrfToken} amountCents={invoice.amountCents} permitted={invoice.availableActions.includes('invoice.computeMatch')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>
      <Section title="Request independent match review"><ActionPanel action="invoice.requestMatchApproval" id={invoice.id} version={invoice.version} csrf={controls.session.csrfToken} amountCents={invoice.amountCents} permitted={invoice.availableActions.includes('invoice.requestMatchApproval')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section></>}
    <Section title="Related records"><div className="cipher-link-row">{invoice.commitmentId && <AppLink href={`/commitments/${encodeURIComponent(invoice.commitmentId)}`}>Open subcontract</AppLink>}{invoice.matchApprovalId && <AppLink href={`/match-approvals/${encodeURIComponent(invoice.matchApprovalId)}`}>Open match review</AppLink>}<AppLink href="/match-approvals">Match reviews</AppLink></div></Section>
    <Section title="Resolve invoice exceptions"><AppLink href={`/invoices/${encodeURIComponent(invoice.id)}/exceptions`}>Review invoice revision, duplicate or rejection</AppLink></Section>
    <TechnicalDetails entries={[{ label: 'Invoice ID', value: invoice.id }, { label: 'Source document', value: invoice.evidence.documentId }, { label: 'Source revision', value: invoice.evidence.revisionId }]} />
  </>;
}
export function APMatchReview({ approvalId, revision, ...controls }: Controls & { approvalId: string; revision: number }) {
  const { record: packet, problem } = useRecord(approvalId, revision, readMatchPacket, controls);
  if (!packet) return <LoadingRecord title="Invoice match review" problem={problem} onChanged={controls.onChanged} />;
  return <MatchReview packet={packet} problem={problem} {...controls} />;
}
function MatchReview({ packet: p, problem, ...controls }: Controls & { packet: MatchPacket; problem: Error | null }) {
  const inv = p.invoice;
  const rememberedGrant = useActionMemory().get(memoryKey('invoice.approveMatch', p.approvalId))?.prepared;
  return <><div className="cipher-breadcrumb"><AppLink href="/match-approvals">Match reviews</AppLink><AppLink href={`/invoices/${encodeURIComponent(inv.id)}`}>{inv.invoiceNumber}</AppLink></div>
    <APHeader title={`Review match for invoice ${inv.invoiceNumber}`} subtitle={`${inv.supplierName} · ${inv.projectName}`}><IntakeStatus status={p.effectiveStatus} /></APHeader>
    {problem && <p role="alert">{problem.message}</p>}
    <Section title="Match decision facts"><KeyFacts facts={[{ label: 'Invoice amount', value: money(p.amountCents) }, { label: 'Requested by', value: p.requestedBy.displayName }, { label: 'Requested', value: stamp(p.requestedAt) }, { label: 'Expires', value: stamp(p.expiresAt) }, { label: 'Source evidence', value: `${inv.evidence.title} · Revision ${inv.evidence.revision}` }, { label: 'Current source', value: inv.evidence.isCurrent ? 'Current revision' : 'Newer revision requires review' }]} /></Section>
    <Section title="What changed"><Changes changes={p.changes} /></Section>
    {p.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={p.blockedReasons} /></Section>}
    <Section title="Review responsibilities"><ol className="cipher-lifecycle"><li><strong>Independent source review</strong><span>A different authorized accountant reviews the supplier invoice and its certified bill.</span></li><li><strong>Apply approved match</strong><span>An authorized accountant applies the approved match to link the invoice to the bill.</span></li><li><strong>Business approval and posting</strong><span>A project manager grants the bill’s business approval. The accountant separately posts the bill.</span></li></ol></Section>
    {inv.match?.billId && <Section title="Matched source records"><div className="cipher-link-row"><AppLink href={`/invoices/${encodeURIComponent(inv.id)}`}>Open supplier invoice</AppLink><AppLink href={`/bills/${encodeURIComponent(inv.match.billId)}`}>Open certified bill</AppLink></div></Section>}
    {controls.session.duties.includes('accountant') ? <>
      {(p.status === 'pending' || !!rememberedGrant || p.availableActions.includes('invoice.approveMatch')) && <Section title="Approve invoice match"><ActionPanel action="invoice.approveMatch" id={p.approvalId} version={p.version} csrf={controls.session.csrfToken} amountCents={p.amountCents} permitted={p.availableActions.includes('invoice.approveMatch')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>}
      {['granted', 'consumed'].includes(p.status) && <Section title="Apply approved invoice match"><ActionPanel action="invoice.executeMatch" id={p.approvalId} version={p.version} csrf={controls.session.csrfToken} amountCents={p.amountCents} permitted={p.availableActions.includes('invoice.executeMatch')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>}
    </> : <Notice>The accountant duty is required to review or apply an invoice match. Business approval remains a separate project manager decision.</Notice>}
    {p.approvedBy && <Section title="Recorded match approval"><p>Approved by {p.approvedBy.displayName}{p.approvedAt && ` on ${stamp(p.approvedAt)}`}. Approval creates no journal or payable.</p></Section>}
    <TechnicalDetails entries={[{ label: 'Match review ID', value: p.approvalId }]} />
  </>;
}
