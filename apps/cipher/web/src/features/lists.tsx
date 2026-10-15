import type { Workspace, Project, Commitment, Bill, Approval } from '../api/types';
import { money, date, sumCents } from '../copy/format';
import { approvalLabel } from '../copy/terms';
import { AppLink } from '../app/navigation';
import { RecordTable, StatusChip, type Column } from '../ui/shared';

export const projectName = (w: Workspace, id: string | null) => w.projects.find(p => p.id === id)?.name ?? 'Company-wide request';
export const billName = (bill: Bill) => `Pay app #${bill.sequence}`;
export const subjectName = (w: Workspace, approval: Approval) => {
  if (approval.subjectLabel) return approval.subjectLabel;
  const bill = w.bills.find(row => row.id === approval.subjectId);
  if (bill) return `${billName(bill)} from ${bill.supplierName ?? 'the recorded supplier'}`;
  const commitment = w.commitments.find(row => row.id === approval.subjectId);
  return commitment?.title ?? 'Recorded request';
};
export function ProjectTable({ workspace, rows = workspace.projects }: { workspace: Workspace; rows?: Project[] }) {
  const columns: Column<Project>[] = [
    { key: 'name', label: 'Project', render: row => <AppLink href={`/projects/${encodeURIComponent(row.id)}`}>{row.name}</AppLink> },
    { key: 'customer', label: 'Client', render: row => row.customerName ?? 'Client not listed' },
    { key: 'budget', label: 'Budget', money: true, render: row => money(row.budgetCents, true) },
    { key: 'committed', label: 'Committed', money: true, render: row => money(sumCents(workspace.commitments.filter(c => c.projectId === row.id && ['executed', 'closed'].includes(c.status)).map(c => c.executedAmountCents)), true) },
    { key: 'apps', label: 'Pay apps', render: row => workspace.bills.filter(b => b.projectId === row.id).length },
  ];
  return <RecordTable label="Projects" rows={rows} columns={columns} empty="No projects match this search. Clear the search to see all practice projects." />;
}
export function CommitmentTable({ workspace, rows = workspace.commitments }: { workspace: Workspace; rows?: Commitment[] }) {
  const columns: Column<Commitment>[] = [
    { key: 'title', label: 'Subcontract', render: row => <AppLink href={`/commitments/${encodeURIComponent(row.id)}`}>{row.title}</AppLink> },
    { key: 'supplier', label: 'Supplier', render: row => row.supplierName ?? 'Supplier not listed' },
    { key: 'status', label: 'Status', render: row => <StatusChip status={row.status} /> },
    { key: 'amount', label: 'Executed amount', money: true, render: row => money(row.executedAmountCents) },
    { key: 'original', label: 'Original amount', money: true, render: row => money(row.originalAmountCents) },
  ];
  return <RecordTable label="Subcontracts" rows={rows} columns={columns} empty="No subcontracts match this view." />;
}
export function BillTable({ workspace, rows = workspace.bills }: { workspace: Workspace; rows?: Bill[] }) {
  const columns: Column<Bill>[] = [
    { key: 'name', label: 'Sub pay app', render: row => <AppLink href={`/bills/${encodeURIComponent(row.id)}`}>{billName(row)}<span className="cipher-cell-secondary">{row.supplierName ?? row.commitmentTitle ?? 'Recorded subcontract'}</span></AppLink> },
    { key: 'period', label: 'Period', render: row => row.periodLabel ?? 'Recorded period' },
    { key: 'status', label: 'Status', render: row => <StatusChip status={row.status} /> },
    { key: 'amount', label: 'Application amount', money: true, render: row => money(row.amountDueCents) },
    { key: 'due', label: 'Open payable', money: true, render: row => money(row.currentDueCents) },
    { key: 'retainage', label: 'Retainage this period', money: true, render: row => money(row.retainageCents) },
  ];
  return <RecordTable label="Sub pay apps" rows={rows} columns={columns} empty="No pay apps match this view." />;
}
export function ApprovalTable({ workspace, rows = workspace.approvals }: { workspace: Workspace; rows?: Approval[] }) {
  const columns: Column<Approval>[] = [
    { key: 'subject', label: 'Review request', render: row => <AppLink href={`/approvals/${encodeURIComponent(row.id)}`}>{approvalLabel(row.operation)}<span className="cipher-cell-secondary">{subjectName(workspace, row)}</span></AppLink> },
    { key: 'project', label: 'Project', render: row => projectName(workspace, row.projectId) },
    { key: 'amount', label: 'Amount', money: true, render: row => row.amountCents === null ? '—' : money(row.amountCents) },
    { key: 'status', label: 'Status', render: row => <StatusChip status={row.status} /> },
    { key: 'expires', label: 'Expires', render: row => date(row.expiresAt) },
  ];
  return <RecordTable label="Review requests" rows={rows} columns={columns} empty="No requests are waiting in this view. Open a project to see its recorded work." />;
}
