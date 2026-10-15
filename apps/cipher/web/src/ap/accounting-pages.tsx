import { AppLink } from '../app/navigation';
import { date, money } from '../copy/format';
import { KeyFacts, Notice, RecordTable, Section, StatusChip, TechnicalDetails } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { memoryKey, useActionMemory } from './ActionMemory';
import { readAccountingApprovals, readAccountingIntent, readAccountingIntents, readAccountingPacket, readAccountingPlan, readAccountingPlans, readAccountingPreparation } from './client';
import { LoadingRecord, useRecord, type Controls } from './intake-pages';
import { billName } from './pages';
import { APHeader, Problems } from './presentation';
import type { AccountingAction, AccountingApproval, AccountingIntent, AccountingPlan } from './types';

const stamp = (value: string) => new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York' }).format(new Date(value)) + ' Eastern';
function AccountingStatus({ status }: { status: string }) {
  const labels: Record<string, string> = { prepared: 'Plan prepared', queued: 'Queued for practice delivery', submitting: 'Practice step in progress', outcome_unknown: 'Original outcome unknown', simulated_accepted: 'Simulator acknowledged', reconciled: 'Simulation reconciled', refused: 'Practice step refused', stale: 'Facts changed' };
  return labels[status] ? <span className={`cipher-status cipher-status-${status === 'reconciled' ? 'positive' : ['outcome_unknown', 'refused'].includes(status) ? 'warning' : 'neutral'}`}>{labels[status]}</span> : <StatusChip status={status} />;
}
function Qualification() {
  return <Notice>Practice accounting handoff only. QuickBooks official books and payments are unavailable. This fixed aggregate entry carries project and supplier dimensions; cost type and tax qualification remain unavailable.</Notice>;
}
function PlanFacts({ plan: p }: { plan: AccountingPlan }) {
  return <>
    <Section title="Original posted obligation"><KeyFacts facts={[
      { label: 'Original certified cost', value: money(p.original.originalCostCents) },
      { label: 'Original AP liability', value: money(p.original.originalApCents) },
      { label: 'Original retained liability', value: money(p.original.originalRetainageCents) },
      { label: 'Original posting period', value: p.original.sourcePeriod.name },
      { label: 'Posted by', value: p.original.sourcePostedBy.displayName },
      { label: 'Originally posted', value: stamp(p.original.sourcePostedAt) },
      { label: 'Practice transaction date', value: date(p.date.transactionDate), note: 'The original posting period end date under the synthetic period-end policy.' },
      { label: 'Mapping', value: `Synthetic mapping v${p.mapping.version}` },
    ]} /><p className="cipher-caption">These amounts come from the original installed-work posting receipt. The plan preserves that obligation and its original posting period.</p></Section>
    <Section title="Practice handoff entry"><RecordTable label="Practice handoff entry" rows={p.preview.lines} columns={[
      { key: 'account', label: 'Source account', render: line => <>{line.sourceAccountCode} · {line.sourceAccountName}<span className="cipher-cell-secondary">{line.practiceAccountName}</span></> },
      { key: 'project', label: 'Project', render: line => line.projectName },
      { key: 'supplier', label: 'Supplier', render: line => line.supplierName },
      { key: 'debit', label: 'Debit', money: true, render: line => money(line.debitCents) },
      { key: 'credit', label: 'Credit', money: true, render: line => money(line.creditCents) },
    ]} /><KeyFacts facts={[{ label: 'Total debit', value: money(p.preview.debitTotalCents) }, { label: 'Total credit', value: money(p.preview.creditTotalCents) }]} /></Section>
    <Section title="Date and route qualification"><p>The synthetic period-end policy uses the audited original posting period end date. Live accounting date policy remains unqualified. This route is a fixed aggregate practice journal in the owned simulator.</p><Qualification /></Section>
  </>;
}
function PlanLinks({ plan }: { plan: AccountingPlan }) {
  return <Section title="Source and handoff records"><div className="cipher-link-row"><AppLink href={`/bills/${encodeURIComponent(plan.billId)}`}>Open source {billName(plan.source).toLowerCase()}</AppLink><AppLink href="/accounting">Open accounting handoffs</AppLink></div></Section>;
}
function PlanDetails({ plan }: { plan: AccountingPlan }) {
  return <TechnicalDetails entries={[{ label: 'Plan ID', value: plan.id }, { label: 'Original posting receipt', value: plan.source.postingReceiptId }, { label: 'Original journal', value: plan.source.originalJournalId }, { label: 'Date policy', value: plan.date.policy }, { label: 'Practice route', value: plan.route }, { label: 'Original logical operation', value: plan.logicalOperationId }]} />;
}
function AccountingStep({ action, id, version, available, plan, ...controls }: Controls & { action: AccountingAction; id: string; version: string; available: boolean; plan?: AccountingPlan }) {
  return <ActionPanel action={action} id={id} version={version} csrf={controls.session.csrfToken} amountCents={plan?.original.originalApCents ?? 0} permitted={available} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />;
}
export function APAccountingPreparation({ billId, revision, ...controls }: Controls & { billId: string; revision: number }) {
  const { record: p, problem } = useRecord(billId, revision, readAccountingPreparation, controls);
  if (!p || problem) return <LoadingRecord title="Prepare practice accounting handoff" problem={problem} onChanged={controls.onChanged} />;
  return <><div className="cipher-breadcrumb"><AppLink href={`/bills/${encodeURIComponent(billId)}`}>{billName(p.bill)}</AppLink><AppLink href="/accounting">Accounting handoffs</AppLink></div>
    <APHeader title="Prepare practice accounting handoff" subtitle={`${p.bill.supplierName} · ${p.bill.projectName}`} />
    <Qualification />
    <Section title="Certified source bill"><KeyFacts facts={[{ label: 'Certified source cost', value: money(p.bill.thisPeriodCents) }, { label: 'Certified AP amount', value: money(p.bill.amountDueCents) }, { label: 'Source retained liability', value: money(p.bill.retainageCents) }, { label: 'Current bill status', value: <StatusChip status={p.bill.status} /> }, ...(p.bill.posting ? [{ label: 'Original posting period', value: p.bill.posting.period.name }, { label: 'Source posting period end', value: date(p.bill.posting.period.endDate) }] : [])]} /></Section>
    <Section title="Fixed practice mapping"><p>{p.mapping ? `Synthetic mapping v${p.mapping.version} is selected by the server.` : 'No qualified synthetic mapping is available for this source.'} The plan will bind the original installed-work posting receipt and synthetic period-end date. A different accountant must grant the requested handoff.</p></Section>
    {p.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={p.blockedReasons} /></Section>}
    <Section title="Prepare immutable practice plan"><AccountingStep action="accounting.prepare" id={billId} version={p.version} available={p.availableActions.includes('accounting.prepare')} {...controls} /></Section>
  </>;
}
export function APAccountingPlan({ planId, revision, ...controls }: Controls & { planId: string; revision: number }) {
  const { record: p, problem } = useRecord(planId, revision, readAccountingPlan, controls);
  if (!p || problem) return <LoadingRecord title="Practice handoff plan" problem={problem} onChanged={controls.onChanged} />;
  return <><div className="cipher-breadcrumb"><AppLink href="/accounting">Accounting handoffs</AppLink></div><APHeader title={`Practice handoff for ${billName(p.plan.source)}`} subtitle={`${p.plan.source.supplierName} · ${p.plan.source.projectName}`}><AccountingStatus status={p.plan.status} /></APHeader>
    <PlanFacts plan={p.plan} />
    {p.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={p.blockedReasons} /></Section>}
    <Section title="Request independent accountant review"><AccountingStep action="accounting.request" id={planId} version={p.version} plan={p.plan} available={p.availableActions.includes('accounting.request')} {...controls} /></Section>
    <PlanLinks plan={p.plan} /><PlanDetails plan={p.plan} />
  </>;
}
export function APAccountingReview({ approvalId, revision, ...controls }: Controls & { approvalId: string; revision: number }) {
  const { record: p, problem } = useRecord(approvalId, revision, readAccountingPacket, controls); const memory = useActionMemory();
  if (!p || problem) return <LoadingRecord title="Practice handoff review" problem={problem} onChanged={controls.onChanged} />;
  const show = (action: AccountingAction) => p.availableActions.includes(action) || !!memory.get(memoryKey(action, approvalId))?.prepared;
  return <><div className="cipher-breadcrumb"><AppLink href="/accounting">Accounting handoffs</AppLink><AppLink href={`/accounting-plans/${encodeURIComponent(p.plan.id)}`}>Practice plan</AppLink></div>
    <APHeader title={`Review practice handoff for ${billName(p.plan.source)}`} subtitle={`${p.plan.source.supplierName} · ${p.plan.source.projectName}`}><AccountingStatus status={p.approval.effectiveStatus} /></APHeader>
    <PlanFacts plan={p.plan} />
    <Section title="Independent review"><KeyFacts facts={[{ label: 'Requested by', value: p.approval.requestedBy.displayName }, { label: 'Requested', value: stamp(p.approval.requestedAt) }, { label: 'Expires', value: stamp(p.approval.expiresAt) }, ...(p.approval.approvedBy ? [{ label: 'Approved by', value: p.approval.approvedBy.displayName }] : [])]} /><p>A different authorized accountant grants this request. An authorized accountant then explicitly queues the handoff; queueing creates no simulator call or additional working journal.</p></Section>
    {p.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={p.blockedReasons} /></Section>}
    {show('accounting.approve') && <Section title="Grant independent handoff approval"><AccountingStep action="accounting.approve" id={approvalId} version={p.version} plan={p.plan} available={p.availableActions.includes('accounting.approve')} {...controls} /></Section>}
    {show('accounting.queue') && <Section title="Queue approved practice handoff"><AccountingStep action="accounting.queue" id={approvalId} version={p.version} plan={p.plan} available={p.availableActions.includes('accounting.queue')} {...controls} /></Section>}
    <PlanLinks plan={p.plan} /><PlanDetails plan={p.plan} />
  </>;
}
export function APAccountingIntent({ intentId, revision, ...controls }: Controls & { intentId: string; revision: number }) {
  const { record: p, problem } = useRecord(intentId, revision, readAccountingIntent, controls); const memory = useActionMemory();
  if (!p || problem) return <LoadingRecord title="Practice delivery record" problem={problem} onChanged={controls.onChanged} />;
  const show = (action: AccountingAction) => p.availableActions.includes(action) || !!memory.get(memoryKey(action, intentId))?.prepared;
  const messages: Record<AccountingIntent['status'], string> = {
    queued: 'The handoff is queued. An authorized accountant can now explicitly deliver the original practice entry.',
    submitting: 'The original practice step is unfinished. Refresh this record or retry its exact request to retrieve the original outcome.',
    outcome_unknown: 'The original simulation outcome is unknown. Look up the same original logical operation before any further delivery. A new submission is blocked.',
    simulated_accepted: 'The simulator acknowledged the original practice entry. Read back its original record before treating the simulation as reconciled.',
    reconciled: 'The original simulator record matches the approved practice plan. QuickBooks official books and payments remain unavailable.',
    refused: 'The practice step was refused. Review the current restrictions before continuing.',
  };
  return <><div className="cipher-breadcrumb"><AppLink href="/accounting">Accounting handoffs</AppLink><AppLink href={`/accounting-plans/${encodeURIComponent(p.plan.id)}`}>Practice plan</AppLink></div>
    <APHeader title={`Practice delivery for ${billName(p.plan.source)}`} subtitle={`${p.plan.source.supplierName} · ${p.plan.source.projectName}`}><AccountingStatus status={p.intent.status} /></APHeader>
    <Section title="Current simulation state"><Notice>{messages[p.intent.status]}</Notice><KeyFacts facts={[{ label: 'Queued by', value: p.intent.queuedBy.displayName }, { label: 'Queued', value: stamp(p.intent.queuedAt) }, { label: 'Last updated by', value: p.intent.updatedBy.displayName }, { label: 'Updated', value: stamp(p.intent.updatedAt) }, { label: 'Original simulator acknowledgment', value: p.intent.hasAcceptance ? 'Recorded' : 'Unconfirmed' }]} /></Section>
    {p.blockedReasons.length > 0 && <Section title="Current restrictions"><Problems reasons={p.blockedReasons} /></Section>}
    {show('accounting.deliver') && <Section title="Deliver original practice entry"><AccountingStep action="accounting.deliver" id={intentId} version={p.version} plan={p.plan} available={p.availableActions.includes('accounting.deliver')} {...controls} /></Section>}
    {show('accounting.lookup') && <Section title="Recover original outcome"><AccountingStep action="accounting.lookup" id={intentId} version={p.version} plan={p.plan} available={p.availableActions.includes('accounting.lookup')} {...controls} /></Section>}
    {show('accounting.reconcile') && <Section title="Read back original simulator record"><AccountingStep action="accounting.reconcile" id={intentId} version={p.version} plan={p.plan} available={p.availableActions.includes('accounting.reconcile')} {...controls} /></Section>}
    <PlanFacts plan={p.plan} /><PlanLinks plan={p.plan} /><PlanDetails plan={p.plan} />
    <TechnicalDetails entries={[{ label: 'Delivery intent', value: p.intent.id }, { label: 'Intent revision', value: p.intent.revision }]} />
  </>;
}
async function readHandoffs(id: string, signal?: AbortSignal) {
  const [plans, approvals, intents] = await Promise.all([readAccountingPlans(id, signal), readAccountingApprovals(id, signal), readAccountingIntents(id, signal)]);
  // Every related row must belong to this same currently scoped collection read.
  if ([...approvals, ...intents].some(row => !plans.some(plan => plan.id === row.planId))) throw new Error('The current handoff records cannot be shown accurately. Refresh the scoped records.');
  return { plans, approvals, intents };
}
export function APAccountingList({ revision, ...controls }: Controls & { revision: number }) {
  const { record: rows, problem } = useRecord('accounting', revision, readHandoffs, controls);
  if (!rows || problem) return <LoadingRecord title="Accounting handoffs" problem={problem} onChanged={controls.onChanged} />;
  const planFor = (row: AccountingApproval | AccountingIntent) => rows.plans.find(plan => plan.id === row.planId)!;
  return <><APHeader title="Accounting handoffs" subtitle="Independent accountant review and separate practice delivery of original installed-work postings." /><Qualification />
    <Section title="Practice plans"><RecordTable label="Practice accounting plans" rows={rows.plans} columns={[
      { key: 'bill', label: 'Original bill', render: p => <AppLink href={`/accounting-plans/${encodeURIComponent(p.id)}`}>{billName(p.source)}<span className="cipher-cell-secondary">{p.source.supplierName}</span></AppLink> },
      { key: 'project', label: 'Project', render: p => p.source.projectName },
      { key: 'cost', label: 'Original cost', money: true, render: p => money(p.original.originalCostCents) },
      { key: 'ap', label: 'Original AP', money: true, render: p => money(p.original.originalApCents) },
      { key: 'date', label: 'Practice date', render: p => date(p.date.transactionDate) },
    ]} empty="Prepare a practice handoff from an eligible posted, unpaid installed-work bill." /></Section>
    <Section title="Accountant handoff reviews"><RecordTable label="Accounting handoff reviews" rows={rows.approvals} columns={[
      { key: 'bill', label: 'Review', render: a => <AppLink href={`/accounting-approvals/${encodeURIComponent(a.id)}`}>{billName(planFor(a).source)}<span className="cipher-cell-secondary">{planFor(a).source.supplierName}</span></AppLink> },
      { key: 'requester', label: 'Requested by', render: a => a.requestedBy.displayName },
      { key: 'status', label: 'Status', render: a => <AccountingStatus status={a.effectiveStatus} /> },
    ]} empty="No practice handoff reviews are in your current scope." /></Section>
    <Section title="Practice delivery records"><RecordTable label="Accounting practice deliveries" rows={rows.intents} columns={[
      { key: 'bill', label: 'Delivery', render: i => <AppLink href={`/accounting-intents/${encodeURIComponent(i.id)}`}>{billName(planFor(i).source)}<span className="cipher-cell-secondary">{planFor(i).source.supplierName}</span></AppLink> },
      { key: 'queued', label: 'Queued by', render: i => i.queuedBy.displayName },
      { key: 'status', label: 'Current state', render: i => <AccountingStatus status={i.status} /> },
    ]} empty="No approved handoff has been queued for practice delivery." /></Section>
  </>;
}
