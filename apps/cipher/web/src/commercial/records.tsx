import { AppLink } from '../app/navigation';
import { money } from '../copy/format';
import { KeyFacts, Notice, RecordTable, Section, TechnicalDetails } from '../ui/shared';
import { CommercialStatus, ratioPercent, stamp } from './presentation';
import type { Comparison, DrawingSource, EstimateRecord, HandoffLine, ReadLine } from './types';

export const estimateName = (record: { revision: number }) => `Estimate revision ${record.revision}`;
export function DrawingFacts({ source }: { source: DrawingSource }) {
  return <Section title="Owned drawing source"><KeyFacts facts={[
    { label: 'Drawing', value: source.title }, { label: 'Drawing revision', value: String(source.revision) },
    { label: 'Source state', value: source.current ? 'Current revision' : 'A newer drawing revision exists' },
    { label: 'Quantity method', value: 'Manual entry' }, { label: 'Calibrated geometry', value: 'Unverified' },
  ]} /><Notice>These quantities were entered manually. A page locator and measurement basis identify the supplied source; they do not establish calibrated geometric takeoff.</Notice></Section>;
}
export function EstimateLines({ lines }: { lines: ReadLine[] }) {
  return <RecordTable label="Manual estimate lines" rows={lines} columns={[
    { key: 'description', label: 'Description', render: line => <>{line.description}<span className="cipher-cell-secondary">Line {line.lineNo} · Cost code {line.costCode}</span></> },
    { key: 'quantity', label: 'Manual quantity', render: line => line.quantity },
    { key: 'unit', label: 'Unit', render: line => line.unit },
    { key: 'price', label: 'Unit price', money: true, render: line => money(line.unitPriceCents) },
    { key: 'amount', label: 'Amount', money: true, render: line => money(line.amountCents) },
    { key: 'locator', label: 'Source locator', render: line => line.sourceLocator },
  ]} />;
}
export function EstimateFacts({ estimate: e }: { estimate: EstimateRecord }) {
  return <>
    <Section title="Priced estimate"><KeyFacts facts={[
      { label: 'Subtotal', value: money(e.subtotalCents) }, { label: 'Contingency', value: money(e.contingencyCents), note: `Recorded rate ${ratioPercent(e.contingencyRate)}` },
      { label: 'Estimate total', value: money(e.totalCents) }, { label: 'Business state', value: <CommercialStatus status={e.effectiveStatus} /> },
      { label: 'Price reference', value: e.priceBookRef ?? 'No price reference supplied' }, { label: 'Measurement basis', value: e.measurementBasis },
    ]} /><EstimateLines lines={e.lines} /><p className="cipher-caption">Amounts and totals come from the server's reviewed estimate. A supplied price reference does not establish licensed content or verified market rates.</p></Section>
    <DrawingFacts source={e.source} />
    <Section title="Recorded scope"><div className="commercial-scope"><div><h3>Inclusions</h3>{e.inclusions.length ? <ul>{e.inclusions.map(text => <li key={text}>{text}</li>)}</ul> : <p>No inclusions supplied.</p>}</div><div><h3>Exclusions</h3>{e.exclusions.length ? <ul>{e.exclusions.map(text => <li key={text}>{text}</li>)}</ul> : <p>No exclusions supplied.</p>}</div></div></Section>
  </>;
}
export function EstimateHistory({ estimate: e }: { estimate: EstimateRecord }) {
  const a = e.acceptance;
  return <Section title="Revision and acceptance history">
    <div className="cipher-link-row">{e.predecessor && <AppLink href={`/estimates/${encodeURIComponent(e.predecessor.id)}`}>Open preceding revision {e.predecessor.revision}</AppLink>}{e.successor && <AppLink href={`/estimates/${encodeURIComponent(e.successor.id)}`}>Open successor revision {e.successor.revision}</AppLink>}</div>
    {!e.predecessor && !e.successor && <p>No preceding or successor revision is recorded.</p>}
    {a ? <><KeyFacts facts={[
      { label: 'Acceptance state', value: <CommercialStatus status={a.effectiveStatus} /> },
      { label: 'Requested by', value: a.requestedBy.displayName }, { label: 'Requested', value: stamp(a.requestedAt) },
      ...(a.acceptedBy && a.acceptedAt ? [{ label: 'Authorized by', value: a.acceptedBy.displayName }, { label: 'Acceptance authorized', value: stamp(a.acceptedAt) }] : []),
      ...(a.appliedBy && a.appliedAt ? [{ label: 'Applied by', value: a.appliedBy.displayName }, { label: 'Acceptance applied', value: stamp(a.appliedAt) }] : []),
    ]} /><AppLink href={`/estimate-approvals/${encodeURIComponent(a.approvalId)}`}>Open acceptance review</AppLink></> : <p>No acceptance authorization is recorded for this revision.</p>}
    <p className="cipher-caption">Independent authorization and application are separate. A superseded accepted baseline remains part of the original history and cannot supply a fresh current handoff.</p>
  </Section>;
}
export function ComparisonFacts({ comparison: c }: { comparison: Comparison }) {
  const label: Record<string, string> = { added: 'Added', removed: 'Removed', changed: 'Changed', unchanged: 'Unchanged' };
  const quantity = (line: ReadLine | null) => line ? `${line.quantity} ${line.unit}` : 'No line';
  return <Section title="Comparison with preceding revision"><KeyFacts facts={[
    { label: 'Previous estimate total', value: c.totals.beforeCents === undefined ? 'No preceding revision' : money(c.totals.beforeCents) },
    { label: 'Current estimate total', value: money(c.totals.afterCents) },
    { label: 'Reviewed total change', value: c.totals.deltaCents === undefined ? 'No preceding revision' : money(c.totals.deltaCents) },
    { label: 'Drawing source', value: c.sourceChanged ? 'Changed' : 'Unchanged' }, { label: 'Price reference', value: c.priceBookChanged ? 'Changed' : 'Unchanged' },
  ]} /><RecordTable label="Estimate line revision comparison" rows={c.lines.map(line => ({ ...line, id: line.stableLineId }))} columns={[
    { key: 'description', label: 'Source line', render: line => <>{line.after?.description ?? line.before?.description}<span className="cipher-cell-secondary">{label[line.kind]}</span></> },
    { key: 'beforeQuantity', label: 'Previous quantity / unit', render: line => quantity(line.before) },
    { key: 'afterQuantity', label: 'Current quantity / unit', render: line => quantity(line.after) },
    { key: 'beforePrice', label: 'Previous unit price', money: true, render: line => line.before ? money(line.before.unitPriceCents) : 'No line' },
    { key: 'afterPrice', label: 'Current unit price', money: true, render: line => line.after ? money(line.after.unitPriceCents) : 'No line' },
    { key: 'beforeAmount', label: 'Previous amount', money: true, render: line => line.before ? money(line.before.amountCents) : 'No line' },
    { key: 'afterAmount', label: 'Current amount', money: true, render: line => line.after ? money(line.after.amountCents) : 'No line' },
    { key: 'beforeSource', label: 'Previous source / cost code', render: line => line.before ? `${line.before.sourceLocator} · ${line.before.costCode}` : 'No line' },
    { key: 'afterSource', label: 'Current source / cost code', render: line => line.after ? `${line.after.sourceLocator} · ${line.after.costCode}` : 'No line' },
  ]} />
    <div className="commercial-scope">{[
      ['Added inclusions', c.scope.addedInclusions], ['Removed inclusions', c.scope.removedInclusions],
      ['Added exclusions', c.scope.addedExclusions], ['Removed exclusions', c.scope.removedExclusions],
    ].map(([title, values]) => <div key={title as string}><h3>{title as string}</h3>{(values as string[]).length ? <ul>{(values as string[]).map(value => <li key={value}>{value}</li>)}</ul> : <p>None reported.</p>}</div>)}</div>
  </Section>;
}
export function HandoffLines({ lines, mapped = false }: { lines: HandoffLine[]; mapped?: boolean }) {
  return <RecordTable label={mapped ? 'Subcontract source-to-SOV correspondence' : 'Accepted source handoff lines'} rows={lines.map(line => ({ ...line, id: line.estimateLineId }))} columns={[
    { key: 'description', label: mapped ? 'Schedule of values source' : 'Accepted line', render: line => <>{line.description}<span className="cipher-cell-secondary">Cost code {line.costCode}</span></> },
    { key: 'quantity', label: 'Manual quantity', render: line => line.quantity }, { key: 'unit', label: 'Unit', render: line => line.unit },
    { key: 'price', label: 'Source unit price', money: true, render: line => money(line.unitPriceCents) },
    { key: 'amount', label: 'Source / SOV amount', money: true, render: line => money(line.amountCents) },
    { key: 'locator', label: 'Source locator', render: line => line.sourceLocator },
    { key: 'basis', label: 'Manual basis', render: line => line.measurementBasis },
  ]} />;
}
export function EstimateDetails({ estimate: e }: { estimate: EstimateRecord }) {
  return <TechnicalDetails entries={[{ label: 'Estimate ID', value: e.id }, { label: 'Drawing document ID', value: e.source.documentId }, { label: 'Drawing revision ID', value: e.source.documentRevisionId }]} />;
}
