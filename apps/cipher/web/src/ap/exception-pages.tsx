import { useState } from 'react';
import { Input, Select, Textarea } from '@fluentui/react-components';
import { AppLink } from '../app/navigation';
import { date, money } from '../copy/format';
import { KeyFacts, Notice, RecordTable, Section, TechnicalDetails } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { memoryKey, useActionMemory } from './ActionMemory';
import { readBillException, readCorrectionApprovals, readCorrectionPacket, readInvoiceException } from './client';
import { decimal, inputCents, IntakeStatus, LoadingRecord, useRecord, type Controls } from './intake-pages';
import { billName } from './pages';
import { APHeader, Changes, Problems } from './presentation';
import type { APAction, BillException, CorrectionApproval, CorrectionPacket, InvoiceEvidence, InvoiceException, Workspace } from './types';

const stamp = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York',
  }).format(parsed) + ' Eastern';
};
function ReasonAction({ action, id, version, available, amountCents, label, withdrawal, ...controls }: Controls & {
  action: APAction; id: string; version: string; available: boolean; amountCents: number; label: string; withdrawal?: boolean;
}) {
  const saved = useActionMemory().get(memoryKey(action, id))?.prepared?.body;
  const [reason, setReason] = useState(typeof saved?.reason === 'string' ? saved.reason : '');
  return <><label className="cipher-field cipher-ap-intake-form"><span>{label}</span><Textarea aria-label={label} value={reason} maxLength={500} resize="vertical" onChange={(_, data) => setReason(data.value)} /></label>
    <p className="cipher-caption">Record the source facts and reason for this decision. The server binds this reason to the reviewed action.</p>
    <ActionPanel action={action} id={id} version={version} csrf={controls.session.csrfToken} amountCents={amountCents} body={{ reason }}
      permitted={available && !!reason.trim()} withdrawal={withdrawal} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
  </>;
}
export function APInvoiceExceptions({ invoiceId, revision, workspace, ...controls }: Controls & { invoiceId: string; revision: number; workspace: Workspace }) {
  const { record, problem } = useRecord(invoiceId, revision, readInvoiceException, controls);
  const memory = useActionMemory();
  if (!record) return <LoadingRecord title="Invoice exception review" problem={problem} onChanged={controls.onChanged} />;
  const invoice = record.invoice;
  const show = (action: APAction) => record.availableActions.includes(action) || !!memory.get(memoryKey(action, invoice.id))?.prepared;
  return <><div className="cipher-breadcrumb"><AppLink href="/invoices">Invoices</AppLink><AppLink href={`/invoices/${encodeURIComponent(invoice.id)}`}>{invoice.invoiceNumber}</AppLink></div>
    <APHeader title={`Review invoice ${invoice.invoiceNumber}`} subtitle={`${invoice.supplierName} · ${invoice.projectName}`}><IntakeStatus status={invoice.status} /></APHeader>
    {problem && <p role="alert">{problem.message}</p>}
    <Section title="Current invoice facts"><KeyFacts facts={[{ label: 'Invoice amount', value: money(invoice.amountCents) }, { label: 'Invoice date', value: date(invoice.invoiceDate) }, { label: 'Due date', value: date(invoice.dueDate) }, { label: 'Source evidence', value: `${invoice.evidence.title} · Revision ${invoice.evidence.revision}` }, { label: 'Duplicate review', value: invoice.duplicateBlocking ? 'Required before matching' : invoice.possibleDuplicate ? 'Recorded review' : 'No duplicate flag' }]} /></Section>
    {record.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={record.blockedReasons} /></Section>}
    {show('invoice.revise') && <Section title="Revise supplier invoice"><RevisionForm key={invoice.id} record={record} evidence={workspace.invoiceEvidence} {...controls} /></Section>}
    {show('invoice.reviewDuplicate') && <Section title="Document a distinct obligation"><Notice>Review the flagged invoice against its source records before recording why it represents a separate obligation.</Notice><ReasonAction action="invoice.reviewDuplicate" id={invoice.id} version={record.version} available={record.availableActions.includes('invoice.reviewDuplicate')} amountCents={invoice.amountCents} label="Duplicate review reason" {...controls} /></Section>}
    {show('invoice.reject') && <Section title="Reject received invoice"><ReasonAction action="invoice.reject" id={invoice.id} version={record.version} available={record.availableActions.includes('invoice.reject')} amountCents={invoice.amountCents} label="Rejection reason" {...controls} /></Section>}
    {invoice.status === 'rejected' && <Notice>This invoice is final. Its number remains reserved and its source evidence can be used for a different received invoice.</Notice>}
    {!record.availableActions.length && invoice.status !== 'rejected' && <Notice>No exception action is available with the current person and source state. Read the restrictions or choose another authorized practice person.</Notice>}
    <Section title="Continue the invoice workflow"><div className="cipher-link-row"><AppLink href={`/invoices/${encodeURIComponent(invoice.id)}`}>Open current invoice and match</AppLink>{invoice.commitmentId && <AppLink href={`/commitments/${encodeURIComponent(invoice.commitmentId)}/receive-invoice`}>Receive another supplier invoice</AppLink>}</div></Section>
    <TechnicalDetails entries={[{ label: 'Invoice ID', value: invoice.id }]} />
  </>;
}
function RevisionForm({ record, evidence, ...controls }: Controls & { record: InvoiceException; evidence: InvoiceEvidence[] }) {
  const inv = record.invoice;
  const saved = useActionMemory().get(memoryKey('invoice.revise', inv.id))?.prepared?.body;
  const [number, setNumber] = useState(typeof saved?.invoiceNumber === 'string' ? saved.invoiceNumber : inv.invoiceNumber);
  const [invoiceDate, setDate] = useState(typeof saved?.invoiceDate === 'string' ? saved.invoiceDate : inv.invoiceDate);
  const [amount, setAmount] = useState(Number.isSafeInteger(saved?.amountCents) ? decimal(saved!.amountCents as number) : decimal(inv.amountCents));
  const [source, setSource] = useState(typeof saved?.evidenceRevisionId === 'string' ? saved.evidenceRevisionId : inv.evidence.revisionId);
  const [reason, setReason] = useState(typeof saved?.reason === 'string' ? saved.reason : '');
  const options = evidence.filter(row => row.projectId === inv.projectId && row.isCurrent && (row.available || row.documentId === inv.evidence.documentId));
  const retained = options.some(row => row.revisionId === source);
  const valid = !!number.trim() && /^\d{4}-\d{2}-\d{2}$/.test(invoiceDate) && inputCents(amount) !== null && inputCents(amount)! > 0 && !!source && !!reason.trim();
  return <><div className="cipher-form cipher-ap-intake-form">
    <label className="cipher-field"><span>Revised supplier invoice number</span><Input aria-label="Revised supplier invoice number" value={number} maxLength={64} onChange={(_, data) => setNumber(data.value)} /></label>
    <label className="cipher-field"><span>Revised invoice date</span><Input aria-label="Revised invoice date" type="date" value={invoiceDate} onChange={(_, data) => setDate(data.value)} /></label>
    <label className="cipher-field"><span>Revised invoice amount (USD)</span><Input aria-label="Revised invoice amount (USD)" inputMode="decimal" value={amount} onChange={(_, data) => setAmount(data.value)} /></label>
    <label className="cipher-field"><span>Revised invoice evidence</span><Select aria-label="Revised invoice evidence" value={source} onChange={(_, data) => setSource(data.value)}><option value="">Choose current invoice evidence</option>{options.map(item => <option key={item.revisionId} value={item.revisionId}>{item.title} · Revision {item.revision}</option>)}{source && !retained && <option value={source}>Previously recorded source revision</option>}</Select></label>
    <label className="cipher-field"><span>Revision reason</span><Textarea aria-label="Revision reason" value={reason} maxLength={500} resize="vertical" onChange={(_, data) => setReason(data.value)} /></label>
    <p className="cipher-caption">Supply the revised invoice facts and a current owned source revision. Changing duplicate facts requires a fresh duplicate review. A new invoice version requires a fresh matching decision.</p>
  </div><ActionPanel action="invoice.revise" id={inv.id} version={record.version} csrf={controls.session.csrfToken} amountCents={inputCents(amount) ?? 0}
    body={{ reason, invoiceNumber: number, invoiceDate, amountCents: inputCents(amount), evidenceRevisionId: source }} permitted={valid && record.availableActions.includes('invoice.revise')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></>;
}
export function APBillExceptions({ billId, revision, ...controls }: Controls & { billId: string; revision: number }) {
  const { record, problem } = useRecord(billId, revision, readBillException, controls);
  if (!record) return <LoadingRecord title="Bill exception review" problem={problem} onChanged={controls.onChanged} />;
  return <BillExceptions record={record} problem={problem} {...controls} />;
}
function BillExceptions({ record, problem, ...controls }: Controls & { record: BillException; problem: Error | null }) {
  const b = record.bill; const memory = useActionMemory();
  const show = (action: APAction) => record.availableActions.includes(action) || !!memory.get(memoryKey(action, b.id))?.prepared;
  const withdrawal = !!b.businessApproval?.approvedBy && b.posting === null;
  return <><div className="cipher-breadcrumb"><AppLink href={`/projects/${encodeURIComponent(b.projectId)}/bills`}>{b.projectName}</AppLink><AppLink href={`/bills/${encodeURIComponent(b.id)}`}>{billName(b)}</AppLink></div>
    <APHeader title={`Review exceptions for ${billName(b)}`} subtitle={`${b.supplierName} · ${b.commitmentTitle}`}><IntakeStatus status={b.status} /></APHeader>
    {problem && <p role="alert">{problem.message}</p>}
    <Section title="Current bill"><KeyFacts facts={[{ label: 'Certified amount due', value: money(b.amountDueCents) }, { label: 'Open payable', value: money(b.currentDueCents) }, { label: 'Certification period', value: b.certificationPeriod.name }, ...(b.posting ? [{ label: 'Original posting period', value: b.posting.period.name }] : [])]} /></Section>
    {record.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={record.blockedReasons} /></Section>}
    {show('bill.cancel') && <Section title={withdrawal ? 'Withdraw approved bill' : 'Cancel unposted bill'}><ReasonAction action="bill.cancel" id={b.id} version={record.version} available={record.availableActions.includes('bill.cancel')} amountCents={b.amountDueCents} label="Cancellation reason" withdrawal={withdrawal} {...controls} /></Section>}
    {show('bill.prepareCorrection') && <Section title="Prepare posted-bill correction"><ReasonAction action="bill.prepareCorrection" id={b.id} version={record.version} available={record.availableActions.includes('bill.prepareCorrection')} amountCents={b.amountDueCents} label="Correction reason" {...controls} /></Section>}
    {record.correction && <Section title="Recorded correction reason"><KeyFacts facts={[{ label: 'Reason', value: record.correction.reason }, { label: 'Requested by', value: record.correction.requestedBy.displayName }, { label: 'Requested', value: stamp(record.correction.requestedAt) }, { label: 'Status', value: <IntakeStatus status={record.correction.status} /> }]} /></Section>}
    {show('bill.requestCorrection') && <Section title="Request independent correction approval"><ActionPanel action="bill.requestCorrection" id={b.id} version={record.version} csrf={controls.session.csrfToken} amountCents={b.amountDueCents} permitted={record.availableActions.includes('bill.requestCorrection')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>}
    {['void', 'corrected'].includes(b.status) && <Section title="Prepare replacement"><Notice>The original record remains in history. Prepare replacement certification from the current subcontract; the replacement needs its own invoice match, business approval and independent posting.</Notice><AppLink href={`/commitments/${encodeURIComponent(b.commitmentId)}/prepare-bill`}>Prepare replacement bill</AppLink></Section>}
    <Section title="Related records"><div className="cipher-link-row"><AppLink href={`/bills/${encodeURIComponent(b.id)}`}>Open original bill</AppLink><AppLink href="/correction-approvals">Open correction reviews</AppLink><AppLink href={`/commitments/${encodeURIComponent(b.commitmentId)}`}>Open subcontract</AppLink></div></Section>
    <TechnicalDetails entries={[{ label: 'Bill ID', value: b.id }, ...(record.correction ? [{ label: 'Correction ID', value: record.correction.id }] : [])]} />
  </>;
}
export function APCorrectionList({ revision, ...controls }: Controls & { revision: number }) {
  const { record: rows, problem } = useRecord('correction-approvals', revision, readCorrectionApprovals, controls);
  if (!rows) return <LoadingRecord title="Correction reviews" problem={problem} onChanged={controls.onChanged} />;
  return <><APHeader title="Correction reviews" subtitle="Accountant decisions on posted, unpaid bill corrections in your current project scope." />{problem && <p role="alert">{problem.message}</p>}
    <Section title="Bill correction reviews"><CorrectionTable rows={rows} /></Section>
  </>;
}
function CorrectionTable({ rows }: { rows: CorrectionApproval[] }) {
  return <RecordTable label="Bill correction reviews" rows={rows} columns={[
    { key: 'bill', label: 'Bill correction', render: row => <AppLink href={`/correction-approvals/${encodeURIComponent(row.approvalId)}`}>{billName(row)}<span className="cipher-cell-secondary">{row.supplierName}</span></AppLink> },
    { key: 'project', label: 'Project', render: row => row.projectName },
    { key: 'requester', label: 'Requested by', render: row => row.requestedBy.displayName },
    { key: 'amount', label: 'Original amount due', money: true, render: row => money(row.amountDueCents) },
    { key: 'status', label: 'Status', render: row => <IntakeStatus status={row.effectiveStatus} /> },
    { key: 'reason', label: 'Correction reason', render: row => row.reason },
  ]} empty="No bill corrections require review in your current scope." />;
}
export function APCorrectionReview({ approvalId, revision, ...controls }: Controls & { approvalId: string; revision: number }) {
  const { record, problem } = useRecord(approvalId, revision, readCorrectionPacket, controls);
  if (!record) return <LoadingRecord title="Bill correction review" problem={problem} onChanged={controls.onChanged} />;
  return <CorrectionReview packet={record} problem={problem} {...controls} />;
}
function CorrectionReview({ packet: p, problem, ...controls }: Controls & { packet: CorrectionPacket; problem: Error | null }) {
  const memory = useActionMemory(); const saved = memory.get(memoryKey('bill.executeCorrection', p.approvalId))?.prepared?.body;
  const [periodId, setPeriodId] = useState(typeof saved?.periodId === 'string' ? saved.periodId : p.correctionPeriods[0]?.id ?? '');
  const selected = p.correctionPeriods.find(period => period.id === periodId);
  const show = (action: APAction) => p.availableActions.includes(action) || !!memory.get(memoryKey(action, p.approvalId))?.prepared;
  return <><div className="cipher-breadcrumb"><AppLink href="/correction-approvals">Correction reviews</AppLink><AppLink href={`/bills/${encodeURIComponent(p.billId)}`}>{billName(p)}</AppLink></div>
    <APHeader title={`Review correction for ${billName(p)}`} subtitle={`${p.supplierName} · ${p.projectName}`}><IntakeStatus status={p.effectiveStatus} /></APHeader>
    {problem && <p role="alert">{problem.message}</p>}
    <Section title="Correction decision facts"><KeyFacts facts={[{ label: 'Original certified cost', value: money(p.bill.thisPeriodCents) }, { label: 'Original retainage', value: money(p.bill.retainageCents) }, { label: 'Original amount due', value: money(p.amountDueCents) }, { label: 'Correction reason', value: p.reason }, { label: 'Requested by', value: p.requestedBy.displayName }, { label: 'Requested', value: stamp(p.requestedAt) }, { label: 'Expires', value: stamp(p.expiresAt) }, ...(p.bill.posting ? [{ label: 'Original posting period', value: p.bill.posting.period.name }] : [])]} /></Section>
    <Section title="What changed"><Changes changes={p.changes} /></Section>
    {p.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={p.blockedReasons} /></Section>}
    {show('bill.approveCorrection') && <Section title="Approve posted-bill correction"><ActionPanel action="bill.approveCorrection" id={p.approvalId} version={p.version} csrf={controls.session.csrfToken} amountCents={p.amountDueCents} permitted={p.availableActions.includes('bill.approveCorrection')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>}
    {show('bill.executeCorrection') && <Section title="Execute approved reversal"><label className="cipher-field cipher-ap-period-field"><span>Correction period</span><Select aria-label="Correction period" value={periodId} onChange={(_, data) => setPeriodId(data.value)}><option value="">Choose an eligible open period</option>{p.correctionPeriods.map(period => <option key={period.id} value={period.id}>{period.name}</option>)}</Select></label>
      <ActionPanel action="bill.executeCorrection" id={p.approvalId} version={p.version} csrf={controls.session.csrfToken} amountCents={p.amountDueCents} body={{ periodId }} periodName={selected?.name} permitted={!!periodId && p.availableActions.includes('bill.executeCorrection')} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
    </Section>}
    {p.approvedBy && <Section title="Recorded correction approval"><p>Approved by {p.approvedBy.displayName}{p.approvedAt && ` on ${stamp(p.approvedAt)}`}. Approval does not reverse a journal.</p></Section>}
    {p.status === 'consumed' && <Section title="Replacement certification"><AppLink href={`/commitments/${encodeURIComponent(p.bill.commitmentId)}/prepare-bill`}>Prepare replacement bill</AppLink><p>The replacement follows current invoice matching, business approval and independent posting.</p></Section>}
    <TechnicalDetails entries={[{ label: 'Correction approval ID', value: p.approvalId }, { label: 'Correction ID', value: p.correctionId }]} />
  </>;
}
