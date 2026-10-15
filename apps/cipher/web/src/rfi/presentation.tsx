import { useEffect, useState, type ReactNode } from 'react';
import { Button, Spinner } from '@fluentui/react-components';
import { CheckmarkCircleRegular, WarningRegular } from '@fluentui/react-icons';
import { AppLink } from '../app/navigation';
import { PageHeader } from '../ui/shared';
import { RFIError } from './client';
import type { Session } from './types';

export interface Controls { session: Session; onChanged: () => void; onSessionLost: () => void }
export function RFIHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return <PageHeader title={title} subtitle={subtitle} helpContent={<><p>Record an authored RFI question against an issued drawing and owned supporting revision. Original citations remain fixed; newer working or current revisions are disclosed separately.</p><h2>Independent response and distribution review</h2><p>Staff may draft. An actual PM requests review, a different actual PM grants it, and a PM separately applies that same grant. A response grant alone leaves the RFI open.</p><p>Recipients, independent distribution authorization and local practice distribution are separate acts. Potential impacts remain informational; this workflow does not adopt a contract, budget or schedule change or certify engineering.</p><AppLink href="/rfis">Open RFI log</AppLink></>}>{children}</PageHeader>;
}
export function RFIStatus({status}:{status:string}) {
 const names:Record<string,string>={open:'Open',answered:'Answered',draft:'Proposed response',pending:'Awaiting independent PM review',granted:'Authorized; application separate',consumed:'Original grant applied',distributed:'Local practice distribution',stale:'Current review facts changed',expired:'Expired',invalidated:'Needs fresh review',current:'Current',historical:'Original cited revision'};
 return <span className={`cipher-status cipher-status-${['granted','consumed','answered','distributed'].includes(status)?'positive':['stale','expired','invalidated','historical'].includes(status)?'warning':'neutral'}`}>{names[status]??'Current state unavailable'}</span>;
}
export const stamp = (value: string) => Number.isNaN(new Date(value).valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York' }).format(new Date(value)) + ' Eastern';
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
      setRecord(null); setProblem(error instanceof Error ? error : new Error('The current rfi record could not be loaded.'));
      if (error instanceof RFIError && error.status === 401) controls.onSessionLost();
    });
    return () => controller.abort();
  }, [id, revision, read]);
  return { record, problem };
}
export function LoadingRecord({ title, problem, onChanged }: { title: string; problem: Error | null; onChanged: () => void }) {
  return <><RFIHeader title={title} />{problem ? <><p role="alert">{problem.message}</p><Button onClick={onChanged}>Refresh record</Button></> : <Spinner label={`Reading ${title.toLocaleLowerCase()}`} />}</>;
}
