import type { ReactNode } from 'react';
import { CheckmarkCircleRegular, WarningRegular } from '@fluentui/react-icons';
import { AppLink } from '../app/navigation';
import { money } from '../copy/format';
import { PageHeader, RecordTable, Section } from '../ui/shared';
import type { Change, Check, Problem, SafeValue } from './types';

export function APHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return <PageHeader title={title} subtitle={subtitle} helpContent={<>
    <p>Explore certified bills using a named synthetic practice person. The accountant requests business approval, a different project manager approves, and the accountant separately posts to the practice working ledger.</p>
    <h2>Review each step</h2><p>Read the current facts and run the review before an action. Changed facts require a new review. Retrying the same action retrieves its original outcome without repeating the effect.</p>
    <h2>Disposable practice</h2><p>Sessions and records disappear when this local server restarts. No real money is sent, and no accounting provider receives these records.</p>
    <AppLink href="/projects">Open practice projects</AppLink>
  </>}>{children}</PageHeader>;
}
export function Problems({ reasons }: { reasons: Problem[] }) {
  return reasons.length ? <ul className="cipher-ap-problems">{reasons.map((reason, index) => <li key={`${reason.code}-${index}`}><strong>{reason.message}</strong>{reason.fix && <p>{reason.fix}</p>}</li>)}</ul> : null;
}
export function Checks({ checks }: { checks: Check[] }) {
  return <ul className="cipher-ap-checks">{checks.map((check, index) => <li key={`${check.code}-${index}`}>
    {check.status === 'passed' ? <CheckmarkCircleRegular aria-hidden="true" /> : <WarningRegular aria-hidden="true" />}
    <div><span className="cipher-visually-hidden">{check.status === 'passed' ? 'Passed: ' : check.status === 'warning' ? 'Warning: ' : 'Blocked: '}</span>{check.message}{check.fix && <p className="cipher-caption">{check.fix}</p>}</div>
  </li>)}</ul>;
}
const labels: Record<string, string> = {
  amountDueCents: 'Amount due', retainageCents: 'Retainage', retainedCents: 'Retainage', thisPeriodCents: 'This period',
  cumulativeGrossCents: 'Gross work and stored materials to date', commitmentVersion: 'Subcontract revision',
  status: 'Status', approvalStatus: 'Approval status', periodId: 'Accounting period', certificationPeriod: 'Certification period',
  certificationPeriodId: 'Certification period', sequence: 'Bill sequence', supplierInvoiceAttached: 'Supplier invoice attached',
  storedEvidenceCount: 'Stored-material evidence records', available: 'Current source facts available',
  supplier: 'Supplier', supplierName: 'Supplier', project: 'Project', projectName: 'Project', commitment: 'Subcontract',
  invoiceNumber: 'Supplier invoice number', invoiceDate: 'Invoice date', dueDate: 'Invoice due date',
  amountCents: 'Invoice amount', evidenceRevisionId: 'Source evidence revision', billId: 'Certified bill',
};
export function factLabel(key: string) { return labels[key] ?? 'Reviewed fact'; }
export function factValue(value: SafeValue | undefined, field = ''): ReactNode {
  if (value === null || value === undefined) return 'Not recorded';
  if (typeof value === 'number') return field.endsWith('Cents') ? money(value) : String(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string') return field.toLowerCase().endsWith('id') ? 'Recorded reference' : value;
  return 'Record facts changed';
}
export function Changes({ changes }: { changes: Change[] }) {
  return changes.length ? <RecordTable label="Changed facts" rows={changes.map((change, index) => ({ ...change, id: String(index) }))} columns={[
    { key: 'fact', label: 'Fact', render: row => factLabel(row.field) },
    { key: 'before', label: 'At request', render: row => factValue(row.before, row.field) },
    { key: 'after', label: 'Now', render: row => factValue(row.after, row.field) },
  ]} /> : <p>No changed facts are reported in this review.</p>;
}
export function IntakeFindings({ effects }: { effects: Record<string, SafeValue> }) {
  const messages: Record<string, string> = {
    amount_mismatch: 'The invoice amount does not equal the eligible certified bill.',
    no_certified_bill: 'Prepare an eligible bill for this subcontract before requesting a match approval.',
    possible_duplicate: 'A possible duplicate requires a separate documented review.',
    evidence_stale: 'The invoice source has a newer revision that requires review.',
    over_commitment: 'The invoice exceeds the authorized subcontract or previously matched amount.',
    not_received: 'Required purchased items have not been received.', damaged_receipt: 'A required receipt reports damaged goods.',
  };
  const codes = effects.matchExceptionCodes;
  return <>{effects.matchStatus === 'matched' && <p>The proposed invoice match passes its current source checks.</p>}
    {effects.matchStatus === 'exception' && <p>The computed match will require attention before approval.</p>}
    {Array.isArray(codes) && codes.length > 0 && <ul className="cipher-ap-problems">{codes.map((code, index) => <li key={index}>{typeof code === 'string' ? messages[code] ?? 'A matching check requires review.' : 'A matching check requires review.'}</li>)}</ul>}
  </>;
}
export function EntryPreview({ effects }: { effects: Record<string, SafeValue> }) {
  const previews = effects.journalPreview;
  if (!Array.isArray(previews)) return null;
  return previews.length ? <Section title="Working ledger entry">{previews.map((preview, journalIndex) => {
    if (!preview || Array.isArray(preview) || typeof preview !== 'object' || !Array.isArray(preview.lines)) return null;
    const rows = preview.lines.map((line, index) => {
      if (!line || Array.isArray(line) || typeof line !== 'object' || typeof line.account !== 'string' ||
          !Number.isSafeInteger(line.debitCents) || !Number.isSafeInteger(line.creditCents)) throw new Error('The reviewed accounting entry is incomplete.');
      return { id: `${journalIndex}-${index}`, account: line.account, accountName: typeof line.accountName === 'string' ? line.accountName : line.account,
        memo: typeof line.memo === 'string' ? line.memo : '', debitCents: line.debitCents as number, creditCents: line.creditCents as number };
    });
    return <div key={journalIndex} className="cipher-ap-entry"><p>{typeof preview.description === 'string' ? preview.description : 'Practice bill entry'}</p><RecordTable label={`Reviewed entry ${journalIndex + 1}`} rows={rows} columns={[
      { key: 'account', label: 'Account', render: row => row.accountName },
      { key: 'memo', label: 'Description', render: row => row.memo },
      { key: 'debit', label: 'Debit', money: true, render: row => money(row.debitCents) },
      { key: 'credit', label: 'Credit', money: true, render: row => money(row.creditCents) },
    ]} /></div>;
  })}<p className="cipher-caption">Working ledger, not for issue. External accounting is unavailable.</p></Section>
    : <p>No working ledger entry is created by this step.</p>;
}
