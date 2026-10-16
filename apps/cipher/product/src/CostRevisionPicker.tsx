import { useState } from 'react';
import { Bar, Button, Dialog, Input, Link, Table, TableCell, TableHeaderCell, TableHeaderRow, TableRow } from '@ui5/webcomponents-react';
import type { PcMasterItem } from './api/project-controls.generated';
import { projectControls, type CostMasterKind } from './api/project-controls';
import { ApiError } from './api/client';
import { useResource } from './hooks';
import { Empty, Failure, Loading, Pagination, Status } from './components';

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const digest = /^[a-f0-9]{64}$/;
function businessDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T12:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
function matches(item: PcMasterItem, company: string, kind: CostMasterKind, basisDate: string) {
  const master = item?.master; const resolved = item?.revision; const revision = resolved?.revision;
  return Boolean(master && resolved && revision && master.company === company && master.project === null && master.kind === kind && uuid.test(master.id) && digest.test(item.version) && resolved.company === company && resolved.kind === kind && resolved.basis_date === basisDate && digest.test(resolved.revision_digest) && revision.master_id === master.id && revision.company === company && revision.project === null && revision.kind === kind && uuid.test(revision.id) && typeof revision.definition?.title === 'string' && resolved.native?.doctype === (kind === 'code' ? 'Cost Center' : 'Account'));
}

// The owning API returns the revision as of basisDate separately from the
// current authoring head. Selecting a dated revision never substitutes that head.
// This picker makes no new-use eligibility claim; locked plan validation owns it.
export default function CostRevisionPicker({ company, kind, basisDate, selectedRevision, locked = false, onPick, onClose }: { company: string; kind: CostMasterKind; basisDate: string; selectedRevision?: string; locked?: boolean; onPick: (item: PcMasterItem) => void; onClose: () => void }) {
  const scope = `${company}/${kind}/${basisDate}`;
  const [position, setPosition] = useState<{ scope: string; cursor?: string; pages: (string | undefined)[] }>({ scope, pages: [] });
  const cursor = position.scope === scope ? position.cursor : undefined;
  const pages = position.scope === scope ? position.pages : [];
  const [filter, setFilter] = useState('');
  const validDate = businessDate(basisDate);
  const choices = useResource(validDate ? `${scope}/${cursor || ''}` : null, async signal => {
    const data = await projectControls.masters(company, kind, basisDate, cursor, signal);
    if (!Array.isArray(data.items) || data.items.some(item => !matches(item, company, kind, basisDate))) throw new ApiError('The exact dated cost choices could not be verified.', 'INVALID_CONTRACT', 200);
    return data;
  });
  const noun = kind === 'code' ? 'cost code' : 'cost type';
  const items = choices.data?.items.filter(item => `${item.master.code} ${item.revision.revision.definition.title} ${item.revision.native.name}`.toLowerCase().includes(filter.toLowerCase())) || [];
  return <Dialog open headerText={`Choose ${noun}`} className="commercial-form-dialog" onBeforeClose={event => { if (locked) event.preventDefault(); }} onClose={onClose} footer={<Bar endContent={<Button disabled={locked} onClick={onClose}>Close cost choices</Button>} />}><div className="dialog-form">
    <p>Revision date: {validDate ? basisDate : 'Enter the order date first.'}</p><Link disabled={locked} href={`/company/costs/${kind === 'code' ? 'codes' : 'types'}?company=${encodeURIComponent(company)}`} target="_blank" rel="noopener noreferrer">Manage {noun} revisions in a new tab</Link>
    {validDate && <><Input accessibleName={`Filter ${noun} page`} placeholder="Filter this page by code, title or accounting target" value={filter} disabled={locked} onInput={event => setFilter(event.currentTarget!.value)} /><p className="caption">Selections keep their exact dated revision and are rechecked when the award plan is saved.</p>
      {choices.loading ? <Loading label={`Reading dated ${noun} choices…`} /> : choices.error ? <Failure error={choices.error} onRetry={choices.refresh} /> : items.length ? <Table accessibleName={`Dated ${noun} choices`} overflowMode="Popin" headerRow={<TableHeaderRow><TableHeaderCell minWidth="13rem" importance={100} popinText="Cost identity">Cost identity</TableHeaderCell><TableHeaderCell minWidth="11rem" importance={10} popinText="Accounting target">Accounting target</TableHeaderCell><TableHeaderCell minWidth="11rem" importance={20} popinText="Effective dates">Effective dates</TableHeaderCell><TableHeaderCell minWidth="10rem" importance={60} popinText="Selection">Selection</TableHeaderCell></TableHeaderRow>}>{items.map(item => {
        const revision = item.revision.revision; const definition = revision.definition;
        return <TableRow key={revision.id}><TableCell><strong>{item.master.code}</strong><p>{definition.title}</p>{'allocation_class' in definition && <span className="caption">{definition.allocation_class}{definition.cost_category ? ` · ${definition.cost_category}` : ''}</span>}</TableCell><TableCell>{item.revision.native.name}</TableCell><TableCell>{definition.effective_from} – {definition.effective_until || 'No end date'}<div><Status value={definition.enabled ? 'Enabled' : 'Disabled'} /></div></TableCell><TableCell><Button disabled={locked} accessibleName={`Select ${noun} ${item.master.code}`} onClick={() => onPick(item)}>{selectedRevision === revision.id ? 'Selected revision' : 'Select revision'}</Button><p className="caption">Revision {revision.revision_number}</p></TableCell></TableRow>;
      })}</Table> : <Empty title={filter ? 'No matches on this page' : `No ${noun} choices returned`}>Only currently authorized dated records are shown.</Empty>}
      <Pagination page={pages.length + 1} previous={Boolean(pages.length)} next={choices.data?.next_cursor} total={choices.data?.total} onNext={() => { if (choices.data?.next_cursor) setPosition({ scope, cursor: choices.data.next_cursor, pages: [...pages, cursor] }); }} onPrevious={() => setPosition({ scope, cursor: pages.at(-1), pages: pages.slice(0, -1) })} />
    </>}
  </div></Dialog>;
}
