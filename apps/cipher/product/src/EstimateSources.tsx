import { useEffect, useState } from 'react';
import { Bar, Button, Dialog, Link, Table, TableCell, TableHeaderCell, TableHeaderRow, TableRow, Title } from '@ui5/webcomponents-react';
import { estimating, type EstimateRecords } from './api/estimating';
import { api, ApiError } from './api/client';
import type { EstCitation, EstRateRecord, EstAssemblyRecord, EstSnapshotRecord } from './api/estimating.generated';
import { Empty, Failure, Loading, Status } from './components';
import { date, useResource } from './hooks';
import { exactDisplay } from './estimate-editing';

function unitLabel(records: EstRateRecord['unit_manifest']['records'], id: string) { const unit = records.find(record => record.id === id && record.kind === 'uom'); return unit?.kind === 'uom' ? `${unit.fields.symbol} (${unit.fields.dimension.replaceAll('_', ' ')})` : id; }

export function useEstimateLibrary<K extends 'rate' | 'assembly' | 'conversion'>(company: string, project: string, kind: K) {
  const key = `${company}/${project}/${kind}`;
  const resource = useResource(key, signal => estimating.list(company, project, kind, signal));
  const [more, setMore] = useState<{ key: string; items: EstimateRecords[K][]; next: string | null }>({ key, items: [], next: null });
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<ApiError>();
  useEffect(() => { setMore({ key, items: [], next: resource.data?.next_cursor ?? null }); setError(undefined); }, [key, resource.data]);
  const items = resource.data ? [...resource.data.items, ...(more.key === key ? more.items : [])] : [];
  return { ...resource, items, loadingMore, moreError: error, next: more.key === key ? more.next : resource.data?.next_cursor,
    loadMore: async () => {
      if (!more.next || loadingMore) return;
      setLoadingMore(true); setError(undefined);
      try { const page = await estimating.list(company, project, kind, undefined, more.next); setMore(previous => previous.key === key ? { key, items: [...previous.items, ...page.items], next: page.next_cursor } : previous); }
      catch (failure) { setError(failure as ApiError); }
      finally { setLoadingMore(false); }
    },
  };
}

export function EstimateSourceTables({ rates, assemblies, onInspect }: { rates: EstRateRecord[]; assemblies: EstAssemblyRecord[]; onInspect: (kind: 'rate' | 'assembly', id: string) => void }) {
  return <div className="estimate-source-libraries"><section><Title level="H3">Rate sources</Title>{rates.length ? <Table accessibleName="Estimate rate sources" headerRow={<TableHeaderRow><TableHeaderCell minWidth="15rem">Rate / quote</TableHeaderCell><TableHeaderCell width="9rem" horizontalAlign="End">Unit rate</TableHeaderCell><TableHeaderCell width="8rem">Type</TableHeaderCell><TableHeaderCell width="8rem">Expires</TableHeaderCell></TableHeaderRow>}>
    {rates.map(record => <TableRow key={record.id} rowKey={record.id}><TableCell><div className="record-cell"><Link onClick={() => onInspect('rate', record.id)}>{record.rate.title}</Link><span>Rev. {record.rate.revision} · {record.rate.quote_reference}</span></div></TableCell><TableCell horizontalAlign="End"><span className="exact-number">{record.rate.currency} {exactDisplay(record.rate.rate_amount)}</span></TableCell><TableCell>{record.rate.cost_type}</TableCell><TableCell>{record.rate.expiry_date ? date(record.rate.expiry_date) : 'Not specified'}</TableCell></TableRow>)}
  </Table> : <Empty title="No rate sources" icon="document-text">Authored rates need a qualified unit and a real project source citation.</Empty>}</section>
  <section><Title level="H3">Assembly revisions</Title>{assemblies.length ? <Table accessibleName="Estimate assembly sources" headerRow={<TableHeaderRow><TableHeaderCell minWidth="15rem">Assembly</TableHeaderCell><TableHeaderCell width="7rem">Revision</TableHeaderCell><TableHeaderCell width="8rem">Components</TableHeaderCell></TableHeaderRow>}>{assemblies.map(record => <TableRow key={record.id} rowKey={record.id}><TableCell><Link onClick={() => onInspect('assembly', record.id)}>{record.assembly.title}</Link></TableCell><TableCell>{record.assembly.revision}</TableCell><TableCell>{record.assembly.components.length}</TableCell></TableRow>)}</Table> : <Empty title="No assembly revisions" icon="documents">Direct rate sources can be used without an assembly.</Empty>}</section></div>;
}

export function EstimateSourceInspector({ company, project, kind, id, onClose, onSource }: { company: string; project: string; kind: 'rate' | 'assembly' | 'snapshot'; id: string; onClose: () => void; onSource: (citation: EstCitation) => void }) {
  const record = useResource(`${company}/${project}/${kind}/${id}`, signal => estimating.get(company, project, kind, id, signal));
  const value = record.data;
  return <Dialog open headerText={kind === 'snapshot' ? 'Calculation snapshot' : kind === 'rate' ? 'Rate source' : 'Assembly revision'} className="estimate-inspector" onClose={onClose} footer={<Bar design="Footer" endContent={<Button onClick={onClose}>Close source details</Button>} />}>
    {record.loading ? <Loading label="Loading exact source record…" /> : record.error ? <Failure error={record.error} onRetry={record.refresh} /> : value && <div className="dialog-form">
      {'rate' in value ? <><Title level="H3">{value.rate.title}</Title><div className="estimate-source-price">{value.rate.currency} {exactDisplay(value.rate.rate_amount)}</div><dl className="approval-metadata"><dt>Revision</dt><dd>{value.rate.revision}</dd><dt>Cost type</dt><dd>{value.rate.cost_type}</dd><dt>Rate unit</dt><dd>{unitLabel(value.unit_manifest.records, value.rate.unit_id)}</dd><dt>Quote reference</dt><dd>{value.rate.quote_reference}</dd><dt>Quote date</dt><dd>{date(value.rate.quote_date)}</dd><dt>Expiry</dt><dd>{value.rate.expiry_date ? date(value.rate.expiry_date) : 'Not specified'}</dd><dt>Geography</dt><dd>{value.rate.geography || 'Not specified'}</dd><dt>Includes</dt><dd>{value.rate.inclusions || 'Not specified'}</dd><dt>Excludes</dt><dd>{value.rate.exclusions || 'Not specified'}</dd><dt>Freight / tax</dt><dd>{value.rate.freight_tax_assumptions}</dd><dt>Permission basis</dt><dd>{value.rate.permission_basis}</dd>{value.rate.item && <><dt>Native item</dt><dd>{value.rate.item}</dd></>}{value.rate.party && <><dt>{value.rate.party_type}</dt><dd>{value.rate.party}</dd></>}</dl></> : 'assembly' in value ? <><Title level="H3">{value.assembly.title} · Rev. {value.assembly.revision}</Title><p>{value.assembly.author_basis}</p><Table accessibleName="Assembly component quantities" headerRow={<TableHeaderRow><TableHeaderCell>Source</TableHeaderCell><TableHeaderCell horizontalAlign="End">Work quantity</TableHeaderCell><TableHeaderCell horizontalAlign="End">Resource quantity</TableHeaderCell></TableHeaderRow>}>{value.assembly.components.map(component => <TableRow key={component.line_id}><TableCell>{value.rates[component.rate_source_id]?.title || component.rate_source_id}</TableCell><TableCell horizontalAlign="End">{component.work_quantity.amount} {unitLabel(value.unit_manifest.records, component.work_quantity.unit_id)}</TableCell><TableCell horizontalAlign="End">{component.resource_quantity.amount} {unitLabel(value.unit_manifest.records, component.resource_quantity.unit_id)}</TableCell></TableRow>)}</Table></> : 'result' in value ? <SnapshotFacts snapshot={value} /> : null}
      <CitationList citations={value.source_citations} onSource={onSource} />
      <details><summary>Exact record and source integrity</summary><pre className="estimate-record-json">{JSON.stringify(value, null, 2)}</pre></details>
    </div>}
  </Dialog>;
}

export function SnapshotFacts({ snapshot }: { snapshot: Pick<EstSnapshotRecord, 'currency_policy' | 'input_digest' | 'output_digest' | 'result'> }) {
  return <><Title level="H3">Saved calculation</Title><dl className="approval-metadata"><dt>Currency</dt><dd>{snapshot.currency_policy.currency}</dd><dt>Currency decimals</dt><dd>{snapshot.currency_policy.currency_exponent}</dd><dt>Rounding</dt><dd>Half up after exact line calculation</dd><dt>Input digest</dt><dd className="packet-hash">{snapshot.input_digest}</dd><dt>Output digest</dt><dd className="packet-hash">{snapshot.output_digest}</dd></dl><Table accessibleName="Saved calculation line totals" headerRow={<TableHeaderRow><TableHeaderCell minWidth="14rem">Line</TableHeaderCell><TableHeaderCell width="9rem" horizontalAlign="End">Extension</TableHeaderCell></TableHeaderRow>}>{snapshot.result.lines.map(line => <TableRow key={line.line_id}><TableCell><div className="record-cell"><strong>{line.description}</strong><span>Authored quantity · {line.included ? 'Included' : 'Excluded alternate'}</span></div></TableCell><TableCell horizontalAlign="End"><span className="exact-number">{line.extension.currency} {exactDisplay(line.extension.amount)}</span></TableCell></TableRow>)}</Table></>;
}

export function CitationList({ citations, onSource }: { citations: EstCitation[]; onSource: (citation: EstCitation) => void }) {
  return citations.length ? <div className="estimate-citations"><Title level="H3">Source revisions</Title>{citations.map(citation => <div className="citation" key={citation.id}><div><Link onClick={() => onSource(citation)}>{citation.document_title}</Link><span>Rev. {citation.revision_number} · {citation.page_label}</span><p>{citation.excerpt}</p></div></div>)}</div> : <p className="caption">No document basis citations are attached to this record.</p>;
}

export function EstimateSourcePreview({ company, citation, onClose }: { company: string; citation: EstCitation; onClose: () => void }) {
  const preview = useResource(`${company}/${citation.revision_id}/${citation.page}`, signal => api.preview(company, citation.revision_id, citation.page, signal));
  return <Dialog open headerText="Estimate source text" className="estimate-inspector" onClose={onClose} footer={<Bar design="Footer" endContent={<><Button icon="download" onClick={() => window.open(api.downloadUrl(company, citation.revision_id), '_blank', 'noopener,noreferrer')}>Open original</Button><Button onClick={onClose}>Close source text</Button></>} />}><div className="dialog-form"><Title level="H3">{citation.document_title}</Title><p className="caption">Revision {citation.revision_number} · Page {citation.page}</p>{preview.loading ? <Loading label="Loading stored source page…" /> : preview.error ? <Failure error={preview.error} onRetry={preview.refresh} /> : preview.data ? <pre className="source-text">{preview.data.text}</pre> : <Status value="Unavailable" />}</div></Dialog>;
}
