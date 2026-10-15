import { useEffect, useState, type ReactNode } from 'react';
import { Button, Spinner } from '@fluentui/react-components';
import { CheckmarkCircleRegular, WarningRegular } from '@fluentui/react-icons';
import { AppLink } from '../app/navigation';
import { PageHeader } from '../ui/shared';
import { LibraryError } from './client';
import type { Session } from './types';

export interface Controls { session: Session; onChanged: () => void; onSessionLost: () => void }
export function LibraryHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return <PageHeader title={title} subtitle={subtitle} helpContent={<><p>Author a specification template or contract clause as exact UTF-8 text. Source locators and revision reasons remain with the original stored text.</p><h2>Independent internal reference review</h2><p>Prepare a project locator and purpose, request a different actual PM's review, then separately apply that original grant. A later text revision never rewrites an already adopted internal reference.</p><p>Reference-only adoption does not establish legal execution, engineering certification, external issue, licensed content ingestion or financial effect.</p><AppLink href="/library-entries">Open authored library</AppLink></>}>{children}</PageHeader>;
}
export function LibraryStatus({status}:{status:string}) {
 const names:Record<string,string>={draft:'Authored draft',prepared:'Reference intent prepared',pending:'Awaiting independent PM review',granted:'Reference authorized',consumed:'Original grant applied',adopted_reference:'Internal project reference',stale:'Source facts changed',expired:'Expired',invalidated:'Needs fresh review',current:'Current authored revision',historical:'Original historical revision'};
 return <span className={`cipher-status cipher-status-${['granted','consumed','adopted_reference'].includes(status)?'positive':['stale','expired','invalidated','historical'].includes(status)?'warning':'neutral'}`}>{names[status]??'Current state unavailable'}</span>;
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
      setRecord(null); setProblem(error instanceof Error ? error : new Error('The current library record could not be loaded.'));
      if (error instanceof LibraryError && error.status === 401) controls.onSessionLost();
    });
    return () => controller.abort();
  }, [id, revision, read]);
  return { record, problem };
}
export function LoadingRecord({ title, problem, onChanged }: { title: string; problem: Error | null; onChanged: () => void }) {
  return <><LibraryHeader title={title} />{problem ? <><p role="alert">{problem.message}</p><Button onClick={onChanged}>Refresh record</Button></> : <Spinner label={`Reading ${title.toLocaleLowerCase()}`} />}</>;
}
