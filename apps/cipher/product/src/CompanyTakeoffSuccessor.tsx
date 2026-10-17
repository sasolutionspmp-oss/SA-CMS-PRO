import { useEffect, type ReactNode } from 'react';
import { Button, Title } from '@ui5/webcomponents-react';
import { human, useResource } from './hooks';
import { Failure, Loading } from './components';
import { savedManual, readSuccessor, readStoredSuccessor } from './api/company-takeoff-successor';
import type { SavedSuccessor } from './api/company-takeoff-successor';
import type { CompanyTakeoffGetResponse, CompanyTakeoffMeasurementRecord as Measurement } from './api/company-takeoff.generated';
export const manualQuantity = (r: Measurement) => { const q = r.result.quantity, u = r.unit_manifest.records.find(row => row.id === q.unit_id && row.kind === 'uom'); return `${q.amount} ${u?.kind === 'uom' ? u.fields.symbol || u.target?.name || 'Unit unavailable' : 'Unit unavailable'} · precision ${q.precision}`; };
export function SuccessorEditor({ selected, locked, onCancel, children }: { selected: CompanyTakeoffGetResponse; locked: boolean; onCancel: () => void; children: (v: Awaited<ReturnType<typeof savedManual>>) => ReactNode }) {
  const original = useResource(`${selected.record.company}/${selected.record.id}/${selected.record_digest}/successor-original`, () => savedManual(selected));
  return <section aria-label="Author manual measurement successor"><Title level="H3" wrappingType="Normal">Author a manual successor</Title><p>The original measurement and its estimate attachments remain unchanged. Select the replacement drawing page and author each new quantity input explicitly.</p><Button disabled={locked} onClick={onCancel}>Cancel successor authoring</Button>{original.loading ? <Loading /> : original.error ? <Failure error={original.error} /> : original.data && <><p>Original revision {original.data.record.revision_number}: {manualQuantity(original.data.record)}</p><p>Original source revision {original.data.record.source.revision_number} · Page {original.data.record.source.page} · {original.data.record.definition.locator}</p>{children(original.data)}</>}</section>;
}
export function SuccessorComparison({ saved, locked, onDenied }: { saved: SavedSuccessor; locked: boolean; onDenied: () => void }) {
  const result = useResource(`${saved.response.measurement.id}/successor-comparison`, signal => readSuccessor(saved, signal));
  useEffect(() => { if (result.error && [403, 404].includes(result.error.status)) onDenied(); }, [result.error, onDenied]);
  if (result.loading) return <Loading label="Independently reading original and successor measurements…" />;
  if (result.error) return <section className="surface"><Title level="H2" wrappingType="Normal">Saved successor comparison</Title><p>The save receipt is confirmed. The independent comparison is currently unavailable.</p><Failure error={result.error} onRetry={locked ? undefined : result.refresh} /></section>;
  if (!result.data) return null;
  return <ComparisonFacts data={result.data} />;
}
export function StoredSuccessorComparison({ selected, locked, onDenied }: { selected: CompanyTakeoffGetResponse; locked: boolean; onDenied: () => void }) {
  const result = useResource(`${selected.record.company}/${selected.record.id}/${selected.record_digest}/stored-predecessor`, signal => readStoredSuccessor(selected.record.company, selected, signal));
  useEffect(() => { if (result.error && [403, 404].includes(result.error.status)) onDenied(); }, [result.error, onDenied]);
  if (result.loading) return <Loading label="Reading saved predecessor and successor…" />;
  if (result.error) return <Failure error={result.error} onRetry={locked ? undefined : result.refresh} />;
  return result.data ? <ComparisonFacts data={result.data} stored /> : null;
}
function ComparisonFacts({ data, stored = false }: { data: Awaited<ReturnType<typeof readSuccessor>>; stored?: boolean }) {
  const { before, after, compared } = data;
  return <section className={stored ? undefined : "surface"} aria-label="Verified measurement successor comparison"><Title level={stored ? "H4" : "H2"} wrappingType="Normal">{stored ? 'Saved predecessor comparison verified' : 'Saved manual successor verified'}</Title><p>Original revision {before.record.revision_number}: {manualQuantity(before.record)}</p><p>Successor revision {after.record.revision_number}: {manualQuantity(after.record)}</p><p>Source revision {before.record.source.revision_number}, page {before.record.source.page} → Source revision {after.record.source.revision_number}, page {after.record.source.page}</p><p>{after.record.definition.locator}</p><p>{after.record.definition.reason}</p><p>Source changed: {compared.changed.source ? 'Yes' : 'No'} · Quantity changed: {compared.changed.quantity ? 'Yes' : 'No'} · Authored inputs changed: {compared.changed.geometry_or_manual_inputs ? 'Yes' : 'No'}</p><p>Both are authored manual quantities, without a calibrated geometry claim. Existing estimate attachments stay on their original measurement; no pricing or binding was changed.</p><p>{after.current_use?.eligible ? 'Server reports the successor eligible for current use.' : `Successor unavailable for new use: ${after.current_use?.reasons.map(human).join(', ')}`}</p><details><summary>Exact comparison references</summary><p>Calibration changed: {compared.changed.calibration ? 'Yes' : 'No'}</p><p>Family {compared.family_id}</p><p>Original {before.record.id}</p><code>{before.record_digest}</code><p>Successor {after.record.id}</p><code>{after.record_digest}</code><p>Original source <code>{before.record.source.source_sha256}</code></p><p>Successor source <code>{after.record.source.source_sha256}</code></p><p>Recorded {after.record.created_at} by {after.record.author_user}</p></details></section>;
}
