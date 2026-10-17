import { useState } from 'react';
import { Button, Title } from '@ui5/webcomponents-react';
import type { HistoryItem } from './api/contracts.generated';
import { activityDestination, activityLabel, readCompanyHistory } from './api/company-history';
import { ApiError } from './api/client';
import { Empty, Failure, Loading, PageHeading } from './components';
import { useResource } from './hooks';

interface Props {
  company: string;
  user: string;
  personId: string;
  capabilities: string[];
  navigationLocked: boolean;
  navigate: (path: string) => void;
}
export default function CompanyActivity(props: Props) {
  // Reset the loaded pages as well as the resource when any authority changes.
  const contextKey = JSON.stringify([props.company, props.user, props.personId, [...props.capabilities].sort()]);
  return <Activity key={contextKey} {...props} />;
}

function Activity({ company, user, personId, capabilities, navigationLocked, navigate }: Props) {
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const [page, setPage] = useState(0);
  const [generation, setGeneration] = useState(0);
  const canRead = capabilities.includes('company.read');
  const cursor = cursors[page];
  const history = useResource(canRead && company && user && personId ? JSON.stringify(['company-history', company, user, personId, cursor ?? '', generation]) : null, async signal => {
    const data = await readCompanyHistory(company, cursor, signal);
    if (data.next_cursor && cursors.slice(0, page + 1).includes(data.next_cursor)) throw new ApiError('This activity page is no longer available. Refresh to begin again.', 'INVALID_CONTRACT', 200);
    return data;
  });
  const refresh = () => { setCursors([undefined]); setPage(0); setGeneration(value => value + 1); };
  const ready = !history.loading && !history.error ? history.data : undefined;
  return <div className="page company-activity-page"><PageHeading eyebrow="COMPANY WORKSPACE" title="Company activity"
    description="Saved changes visible with your current Company and source access."
    actions={<Button icon="refresh" disabled={history.loading || navigationLocked || !canRead} onClick={refresh}>Refresh activity</Button>} />
    {!canRead ? <section className="surface"><Empty title="Company activity unavailable" icon="locked">Your current Company permissions do not allow activity access.</Empty></section>
      : <section className="surface company-activity-surface" aria-labelledby="company-activity-heading">
        <div className="company-activity-heading"><Title id="company-activity-heading" level="H2">Recorded activity</Title><p className="caption">Newest first · Up to 25 visible events per page</p></div>
        {history.loading ? <Loading label="Loading Company activity…" /> : history.error ? <><Failure error={history.error} /><p className="company-activity-hint">Activity from the previous page is hidden. Use Refresh activity to start again with current access.</p></>
          : ready?.items.length ? <ol className="activity-list company-activity-list" aria-label="Company activity events">{ready.items.map(item => <ActivityEvent key={item.id} item={item} company={company} navigationLocked={navigationLocked} navigate={navigate} />)}</ol>
            : ready ? <Empty title="No visible Company activity" icon="history">Saved changes you can currently read will appear here.</Empty> : null}
        {ready && <div className="page-controls company-activity-paging" aria-label="Company activity pagination">
          <Button icon="navigation-left-arrow" disabled={page === 0 || navigationLocked} onClick={() => setPage(value => value - 1)}>Previous page</Button>
          <span role="status">Page {page + 1}</span>
          <Button icon="navigation-right-arrow" disabled={!ready.next_cursor || navigationLocked} onClick={() => {
            if (!ready.next_cursor) return;
            setCursors(values => [...values.slice(0, page + 1), ready.next_cursor!]); setPage(value => value + 1);
          }}>Next page</Button>
        </div>}
      </section>}
  </div>;
}

function ActivityEvent({ item, company, navigationLocked, navigate }: { item: HistoryItem; company: string; navigationLocked: boolean; navigate: Props['navigate'] }) {
  const destination = activityDestination(item, company);
  const at = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC' }).format(new Date(item.at));
  return <li><span className="activity-dot" aria-hidden="true" /><div className="company-activity-event">
    <strong>{activityLabel(item.event)}</strong><p>{item.actor} · <time dateTime={item.at}>{at} UTC</time></p>
    <div className="company-activity-record"><span className="caption">{item.subject_type.replace(/^Cipher /, '')}</span>{destination && <Button design="Transparent" disabled={navigationLocked} onClick={() => navigate(destination.path)}>{destination.label}</Button>}</div>
    <details><summary>Record details</summary><dl><div><dt>Event</dt><dd>{item.event}</dd></div><div><dt>Event ID</dt><dd>{item.id}</dd></div><div><dt>Record ID</dt><dd>{item.subject_id}</dd></div><div><dt>Recorded time</dt><dd>{item.at}</dd></div></dl><pre>{JSON.stringify(item.details, null, 2)}</pre></details>
  </div></li>;
}
