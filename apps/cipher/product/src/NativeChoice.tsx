import { useEffect, useRef, useState } from 'react';
import { Button, Input, Option, Select } from '@ui5/webcomponents-react';
import { masterChoices, type MasterKind, type NativeMasterChoice } from './api/masters';
import { useResource } from './hooks';
import { Failure } from './components';

export default function NativeChoice({ company, kind, label, value, onChange, disabled = false, filter, onCompanyCurrency, allowedIds }: { company: string; kind: MasterKind; label: string; value: string; onChange: (choice: NativeMasterChoice) => void; disabled?: boolean; filter?: { currency?: string; dimension?: string; unit_id?: string }; onCompanyCurrency?: (currency: string) => void; allowedIds?: string[] }) {
  const [query, setQuery] = useState(''); const [search, setSearch] = useState(''); const [cursor, setCursor] = useState<string>(); const [pages, setPages] = useState<(string | undefined)[]>([]);
  const choices = useResource(`${company}/${kind}/${search}/${cursor || ''}/${JSON.stringify(filter || {})}`, signal => masterChoices(company, kind, search, cursor, signal, filter));
  const currencyCallback = useRef(onCompanyCurrency); currencyCallback.current = onCompanyCurrency;
  useEffect(() => { if (choices.data) currencyCallback.current?.(choices.data.company_currency); }, [choices.data]);
  const selectedInPage = choices.data?.items.some(item => item.id === value || item.unit_id === value);
  return <div className="native-choice"><div className="native-choice-search"><Input accessibleName={`Search ${label}`} value={query} disabled={disabled} placeholder={`Search native ${kind.toLowerCase()}`} onInput={event => setQuery(event.currentTarget!.value)} onKeyDown={event => { if (event.key === 'Enter') { setSearch(query); setCursor(undefined); setPages([]); } }} /><Button icon="search" accessibleName={`Find ${label}`} disabled={disabled} onClick={() => { setSearch(query); setCursor(undefined); setPages([]); }} /></div>
    <Select accessibleName={label} disabled={disabled || choices.loading} onChange={event => { const selected = choices.data?.items.find(item => item.id === event.detail.selectedOption.value); if (selected) onChange(selected); }}><Option value="" selected={!value}>{choices.loading ? 'Loading permitted choices…' : `Choose ${kind.toLowerCase()}`}</Option>{value && !selectedInPage && <Option value={value} selected>{value} · Current selection</Option>}{choices.data?.items.filter(choice => !allowedIds || allowedIds.includes(choice.id)).map(choice => <Option key={choice.id} value={choice.id} selected={choice.id === value || choice.unit_id === value}>{choice.label}{choice.currency ? ` · ${choice.currency}` : ''}</Option>)}</Select>
    {choices.error && <Failure error={choices.error} onRetry={choices.refresh} />}
    {(cursor || choices.data?.next_cursor) && <div className="native-choice-pages"><Button disabled={disabled || !pages.length} onClick={() => { setCursor(pages.at(-1)); setPages(pages.slice(0, -1)); }}>Previous choices</Button><span className="caption">Page {pages.length + 1}</span><Button disabled={disabled || !choices.data?.next_cursor} onClick={() => { if (choices.data?.next_cursor) { setPages([...pages, cursor]); setCursor(choices.data.next_cursor); } }}>More choices</Button></div>}
  </div>;
}
