import { useEffect, useState } from 'react';
import { Button, CheckBox, Label, Option, Select, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { documentControl, invalidDocumentControl, type DocumentKind } from './api/document-control';
import { sameValue } from './api/schema-validation';
import type { Scope } from './api/engineering';
import type * as D from './api/document-control.generated';
import { sourceApi } from './api/sources';
import { Empty, Failure, Loading, Pagination } from './components';
import { useResource } from './hooks';
export { PackageField as DocumentField } from './EngineeringPackageChoices';
export function useDocumentDenied(error: ApiError | undefined, onDenied: () => void) { useEffect(() => { if (error && [401, 403, 404].includes(error.status)) onDenied(); }, [error, onDenied]); }
export function documentLabel(value: D.DcRecord): string {
  if ('definition' in value) {
    if ('title' in value.definition && typeof value.definition.title === 'string') return value.definition.title;
    if ('purpose' in value.definition && typeof value.definition.purpose === 'string') return value.definition.purpose;
    if ('action' in value.definition) return `${value.definition.action === 'withdraw' ? 'Withdraw' : 'Supersede'} issued document`;
  }
  if ('purpose' in value) return value.purpose;
  if ('statement' in value) return value.statement;
  if (value.status === 'authored_rights_basis') return `Content permission · Revision ${value.revision_number}`;
  if (value.status === 'adopted') return 'Independently adopted library source';
  if (value.status === 'issued') return 'Independently issued document set';
  if (value.status === 'recorded_internally') return 'Internal distribution record';
  if ('proposed_text' in value) return `Proposed clause revision${'revision_number' in value ? ` ${value.revision_number}` : ''}`;
  return `Library entry${'revision_number' in value ? ` · Revision ${value.revision_number}` : ''}`;
}
export function mergeDocumentArtifacts(groups: D.DcArtifact[][]) {
  const rows = new Map<string, D.DcArtifact>();
  for (const row of groups.flat()) {
    const previous = rows.get(row.revision_id);
    if (previous && !sameValue(previous, row)) throw invalidDocumentControl();
    rows.set(row.revision_id, row);
  }
  return [...rows].sort(([a], [b]) => a.localeCompare(b)).map(([, value]) => value);
}
export function DocumentArtifacts({ scope, label, values, onChange, disabled, onDenied, maximum = 8, excludeDocument }: { scope: Scope | { company: string; project?: undefined }; label: string; values: D.DcArtifact[]; onChange: (values: D.DcArtifact[]) => void; disabled: boolean; onDenied: () => void; maximum?: number; excludeDocument?: string }) {
  const source = sourceApi(scope.project ? { type: 'Project', company: scope.company, project: scope.project } : { type: 'Company', company: scope.company }); const [selected, setSelected] = useState('');
  const documents = useResource(`${scope.company}/${scope.project}/doc-control-artifacts`, async signal => {
    const result = await source.list(signal);
    if (!Array.isArray(result.items) || result.items.some(row => row.company !== scope.company || (scope.project ? row.project !== scope.project : row.project !== null || !('scope_type' in row) || row.scope_type !== 'Company') || !row.current_revision || !/^[a-f0-9]{64}$/.test(row.sha256) || !Number.isSafeInteger(row.revision_number) || row.revision_number < 1)) throw invalidDocumentControl();
    return result.items;
  }); useDocumentDenied(documents.error, onDenied);
  const chosen = documents.data?.find(row => row.id === selected);
  return <section className="document-control-choice"><Title level="H3">{label}</Title>{values.map(row => <div className="engineering-source-chip" key={row.revision_id}><span>{documents.data?.find(doc => doc.id === row.document_id)?.title || 'Original document'} · Rev. {row.revision_number}</span><Button disabled={disabled} design="Transparent" icon="decline" accessibleName={`Remove ${label} revision ${row.revision_id}`} onClick={() => onChange(values.filter(value => value.revision_id !== row.revision_id))} /></div>)}
    {documents.loading ? <Loading label="Loading documents…" /> : documents.error ? <Failure error={documents.error} onRetry={documents.refresh} /> : <><Label>{label}</Label><Select accessibleName={label} disabled={disabled || values.length >= maximum} onChange={event => setSelected(event.detail.selectedOption.value || '')}><Option value="" selected={!selected}>Choose a document</Option>{documents.data?.filter(row => row.id !== excludeDocument && !values.some(value => value.revision_id === row.current_revision)).map(row => <Option key={row.id} value={row.id} selected={selected === row.id}>{row.title} · Rev. {row.revision_number}</Option>)}</Select><Button disabled={disabled || !chosen || values.length >= maximum || chosen.id === excludeDocument || values.some(row => row.revision_id === chosen.current_revision)} onClick={() => { if (chosen) { onChange([...values, { document_id: chosen.id, revision_id: chosen.current_revision, source_sha256: chosen.sha256, revision_number: chosen.revision_number, byte_length: chosen.byte_length, mime_type: chosen.mime_type, page_count: chosen.page_count }]); setSelected(''); } }}>Select {label.toLowerCase()}</Button>{!documents.data?.length && <Empty title="No documents available">Add source documents in Documents.</Empty>}</>}
  </section>;
}
export function DocumentRecordChoices({ scope, kind, label, values, onChange, disabled, onDenied, maximum = 8 }: { scope: Scope; kind: DocumentKind; label: string; values: D.DcGetResponse[]; onChange: (values: D.DcGetResponse[]) => void; disabled: boolean; onDenied: () => void; maximum?: number }) {
  const [cursor, setCursor] = useState<string>(); const [prior, setPrior] = useState<(string | undefined)[]>([]);
  const records = useResource(`${scope.company}/${scope.project}/doc-control-choice/${kind}/${cursor || ''}`, signal => documentControl.list(scope, kind, undefined, cursor, signal)); useDocumentDenied(records.error, onDenied);
  return <section className="document-control-choice"><Title level="H3">{label}</Title>{values.map(row => <div className="engineering-source-chip" key={row.record.id}><span>{documentLabel(row.record)}</span><Button design="Transparent" icon="decline" disabled={disabled} accessibleName={`Remove selected ${kind} ${row.record.id}`} onClick={() => onChange(values.filter(value => value.record.id !== row.record.id))} /></div>)}{records.loading ? <Loading label={`Loading ${label.toLowerCase()}…`} /> : records.error ? <Failure error={records.error} onRetry={records.refresh} /> : records.data?.items.length ? records.data.items.map(row => <CheckBox key={row.record.id} text={`${documentLabel(row.record)} · ${row.record.id.slice(0, 8)}`} accessibleName={`${label} ${row.record.id}`} checked={values.some(value => value.record.id === row.record.id)} disabled={disabled || !values.some(value => value.record.id === row.record.id) && values.length >= maximum} onChange={event => onChange(event.currentTarget!.checked ? [...values, row] : values.filter(value => value.record.id !== row.record.id))} />) : <p className="caption">No available {label.toLowerCase()}.</p>}<Pagination next={disabled ? null : records.data?.next_cursor} previous={!disabled && Boolean(prior.length)} page={prior.length + 1} onNext={() => { if (records.data?.next_cursor) { setPrior([...prior, cursor]); setCursor(records.data.next_cursor); } }} onPrevious={() => { setCursor(prior.at(-1)); setPrior(prior.slice(0, -1)); }} /></section>;
}
export function DocumentPeople({ scope, values, onChange, disabled, onDenied }: { scope: Scope; values: D.DcPerson[]; onChange: (values: D.DcPerson[]) => void; disabled: boolean; onDenied: () => void }) {
  const [cursor, setCursor] = useState<string>(); const [prior, setPrior] = useState<(string | undefined)[]>([]);
  const people = useResource(`${scope.company}/${scope.project}/document-control-people/${cursor || ''}`, signal => documentControl.people(scope, cursor, signal)); useDocumentDenied(people.error, onDenied);
  return <section className="document-control-choice"><Title level="H3">Internal recipients</Title>{values.map(row => <div className="engineering-source-chip" key={row.user}><span>{row.user}</span><Button disabled={disabled} icon="decline" design="Transparent" accessibleName={`Remove recipient ${row.user}`} onClick={() => onChange(values.filter(value => value.user !== row.user))} /></div>)}{people.loading ? <Loading label="Loading recipients…" /> : people.error ? <Failure error={people.error} onRetry={people.refresh} /> : <Select accessibleName="Internal recipient" disabled={disabled || values.length >= 30} onChange={event => { const row = people.data?.items.find(row => row.user === event.detail.selectedOption.value); if (row && !values.some(value => value.person === row.person)) onChange([...values, { user: row.user, person: row.person }]); }}><Option value="" selected>Choose a recipient</Option>{people.data?.items.filter(row => !values.some(value => value.person === row.person)).map(row => <Option key={row.user} value={row.user}>{row.display_name} · {row.user}</Option>)}</Select>}<Pagination next={disabled ? null : people.data?.next_cursor} previous={!disabled && Boolean(prior.length)} page={prior.length + 1} onNext={() => { if (people.data?.next_cursor) { setPrior([...prior, cursor]); setCursor(people.data.next_cursor); } }} onPrevious={() => { setCursor(prior.at(-1)); setPrior(prior.slice(0, -1)); }} /></section>;
}
