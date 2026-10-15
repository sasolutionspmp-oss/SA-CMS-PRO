import { useEffect, useState, type ReactNode } from 'react';
import { Button, Spinner } from '@fluentui/react-components';
import { CheckmarkCircleRegular, WarningRegular } from '@fluentui/react-icons';
import { AppLink } from '../app/navigation';
import { PageHeader } from '../ui/shared';
import { CommercialError } from './client';
import type { Session } from './types';

export interface Controls { session: Session; onChanged: () => void; onSessionLost: () => void }
export function CommercialHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return <PageHeader title={title} subtitle={subtitle} helpContent={<>
    <p>Enter manual quantities from an owned drawing revision and review the server's exact priced estimate. Source locators describe the manual basis; calibrated geometry is unverified.</p>
    <h2>Separate acceptance and application</h2><p>An estimator requests acceptance, a different authorized estimator grants it, and an authorized estimator separately applies that decision. A grant alone leaves the estimate in draft.</p>
    <h2>Subcontract draft</h2><p>An accepted current baseline can supply an immutable all-line handoff. The project manager reviews its exact source and creates a subcontract draft. Customer issue, award, signature and commitment execution remain separate.</p>
    <AppLink href="/estimates">Open estimates</AppLink>
  </>}>{children}</PageHeader>;
}
export function CommercialStatus({ status }: { status: string }) {
  const names: Record<string, string> = { draft: 'Draft', approved: 'Accepted baseline', accepted: 'Accepted baseline', under_review: 'Acceptance requested', pending: 'Acceptance requested', granted: 'Acceptance authorized', consumed: 'Acceptance applied', prepared: 'Handoff prepared', draft_created: 'Subcontract draft created', superseded: 'Superseded', stale: 'Facts changed', expired: 'Expired', invalidated: 'Needs fresh acceptance', current: 'Current source', executed: 'Executed', closed: 'Closed' };
  const positive = ['approved', 'accepted', 'consumed', 'draft_created'].includes(status);
  const warning = ['stale', 'expired', 'invalidated'].includes(status);
  return <span className={`cipher-status cipher-status-${positive ? 'positive' : warning ? 'warning' : 'neutral'}`}>{names[status] ?? 'Current state unavailable'}</span>;
}
export const stamp = (value: string) => Number.isNaN(new Date(value).valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York' }).format(new Date(value)) + ' Eastern';
export function ratioPercent(value: string) {
  const [whole, fraction = ''] = value.split('.');
  const scaled = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'));
  const percent = scaled / 10_000n;
  const rest = (scaled % 10_000n).toString().padStart(4, '0').replace(/0+$/, '');
  return `${percent}${rest ? '.' + rest : ''}%`;
}
export function Markers({ items }: { items: { code: string; message: string }[] }) {
  return items.length ? <ul className="cipher-ap-problems">{items.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}</ul> : null;
}
export function Checks({ items }: { items: { code: string; status: string; message: string; fix?: string | null }[] }) {
  return <ul className="cipher-ap-checks">{items.map((item, index) => <li key={`${item.code}-${index}`}>{item.status === 'passed' ? <CheckmarkCircleRegular aria-hidden="true" /> : <WarningRegular aria-hidden="true" />}<div><span className="cipher-visually-hidden">{item.status === 'passed' ? 'Passed: ' : item.status === 'warning' ? 'Warning: ' : 'Blocked: '}</span>{item.message}{item.fix && <p className="cipher-caption">{item.fix}</p>}</div></li>)}</ul>;
}
export function Changes({ rows }: { rows: { code: string; message: string; target: string | null; affectedRecordIds: string[] }[] }) {
  return rows.length ? <ul className="cipher-ap-problems">{rows.map((row, index) => <li key={`${row.code}-${index}`}>{row.message}</li>)}</ul> : <p>No changed source facts are reported.</p>;
}
export function useRecord<T>(id: string, revision: number, read: (id: string, signal?: AbortSignal) => Promise<T>, controls: Controls) {
  const [record, setRecord] = useState<T | null>(null); const [problem, setProblem] = useState<Error | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    read(id, controller.signal).then(value => { if (!controller.signal.aborted) { setRecord(value); setProblem(null); } }).catch(error => {
      if (controller.signal.aborted || error instanceof Error && error.name === 'AbortError') return;
      setRecord(null); setProblem(error instanceof Error ? error : new Error('The current commercial record could not be loaded.'));
      if (error instanceof CommercialError && error.status === 401) controls.onSessionLost();
    });
    return () => controller.abort();
  }, [id, revision, read]);
  return { record, problem };
}
export function LoadingRecord({ title, problem, onChanged }: { title: string; problem: Error | null; onChanged: () => void }) {
  return <><CommercialHeader title={title} />{problem ? <><p role="alert">{problem.message}</p><Button onClick={onChanged}>Refresh record</Button></> : <Spinner label={`Reading ${title.toLocaleLowerCase()}`} />}</>;
}
