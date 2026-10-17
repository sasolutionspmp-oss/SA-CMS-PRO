import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Button, Input, Label, Link, MessageStrip, Option, Select, TextArea, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { companyTakeoff } from './api/company-takeoff';
import { invalidTakeoff, matchesCreatedMeasurement, matchesCreatedSet, takeoffShape, validTakeoffPdfMetadata } from './api/company-takeoff-validation';
import type { CommandActor } from './api/company-takeoff-validation';
import type { CompanyTakeoffCreateSetRequest, CompanyTakeoffCreateSetResponse, CompanyTakeoffCreateMeasurementRequest, CompanyTakeoffCreateMeasurementResponse, CompanyTakeoffMeasurementRecord, CompanyTakeoffSetRecord } from './api/company-takeoff.generated';
import CompanyTakeoffBinding, { SavedBinding } from './CompanyTakeoffBinding';
import type { SavedLineBinding } from './CompanyTakeoffBinding';
import { companyTakeoffBinding, matchesBinding } from './api/company-takeoff-binding';
import type { LineReview } from './api/company-takeoff-binding';
import type { CompanyTakeoffBindLineRequest, CompanyTakeoffBindLineResponse } from './api/company-takeoff.generated';
import { sourceApi } from './api/sources';
import { useResource } from './hooks';
import { useMutation } from './useMutation';
import { Empty, Fact, Failure, Loading, PageHeading } from './components';
const PdfDrawing = lazy(() => import('./PdfDrawing'));
type Props = { active: boolean; company: string; user: string; personId: string; capabilities: string[]; setId?: string; navigationLocked?: boolean; navigate: (path: string) => void; onLockedChange: (locked: boolean) => void };
type SetInput = CompanyTakeoffCreateSetRequest;
type MeasureInput = CompanyTakeoffCreateMeasurementRequest;
function quantityLabel(record: CompanyTakeoffMeasurementRecord) {
  const unit = record.unit_manifest.records.find(row => row.kind === 'uom' && row.id === record.result.quantity.unit_id);
  return `${record.result.quantity.amount} ${unit?.kind === 'uom' ? unit.fields.symbol || unit.target?.name || 'Unit unavailable' : 'Unit unavailable'}`;
}
const pathFor = (company: string, id?: string) => `/company/takeoff${id ? '/' + encodeURIComponent(id) : ''}?${new URLSearchParams({ company })}`;

// Keep commands outside the authority-keyed read/form subtree. Known revocation
// clears source pixels and cursors without discarding an uncertain original UUID.
export default function CompanyTakeoff(props: Props) {
  const binding = useRef<(CommandActor & { company: string; documentId?: string }) | undefined>(undefined);
  const [savedSet, setSavedSet] = useState<{ company: string; id: string }>();
  const [commandKind, setCommandKind] = useState<'set' | 'measurement' | 'line'>('set');
  const [notice, setNotice] = useState(''); const [revision, setRevision] = useState(0); const [accessDenied, setAccessDenied] = useState(false);
  const createSet = useMutation<SetInput, CompanyTakeoffCreateSetResponse>(async input => {
    const result = await companyTakeoff.createSet(input);
    if (!binding.current || !matchesCreatedSet(result, input, binding.current)) throw invalidTakeoff(); return result;
  });
  const createMeasurement = useMutation<MeasureInput, CompanyTakeoffCreateMeasurementResponse>(async input => {
    const result = await companyTakeoff.createMeasurement(input);
    if (!binding.current?.documentId || !matchesCreatedMeasurement(result, input, binding.current, binding.current.documentId)) throw invalidTakeoff(); return result;
  });
  const authority = JSON.stringify([props.company, props.user, props.personId, [...props.capabilities].sort()]);
  const currentAuthority = useRef(authority); currentAuthority.current = authority;
  const linePlan = useRef<{ review: LineReview; authority: string; actor: CommandActor; sent: boolean; controller: AbortController } | undefined>(undefined);
  const [savedLine, setSavedLine] = useState<SavedLineBinding>();
  useEffect(() => { const plan = linePlan.current; if (plan && !plan.sent && plan.authority !== authority) plan.controller.abort(); setSavedLine(undefined); }, [authority]);
  const bindLine = useMutation<CompanyTakeoffBindLineRequest, CompanyTakeoffBindLineResponse>(async input => {
    const plan = linePlan.current; if (!plan) throw invalidTakeoff();
    if (!plan.sent) {
      try { await companyTakeoffBinding.preflight(plan.review, plan.controller.signal); if (currentAuthority.current !== plan.authority || plan.controller.signal.aborted) throw invalidTakeoff(); }
      catch (error) { if (error instanceof ApiError && [403, 404].includes(error.status)) throw error; throw new ApiError('Evidence was not submitted. Refresh and review the current estimate and source before trying again.', 'binding_preflight_refused', 412); }
      plan.sent = true;
    }
    const result = await companyTakeoffBinding.bind(input);
    if (!takeoffShape('CompanyTakeoffBindLineResponse', result) || !matchesBinding(result.binding, input, plan.review, plan.actor)) throw invalidTakeoff();
    return result;
  });
  const finishLine = (result?: CompanyTakeoffBindLineResponse) => { const plan = linePlan.current; if (result && plan) { setSavedLine({ response: result, review: plan.review, authority: plan.authority }); setNotice('Quantity evidence attachment confirmed.'); setRevision(n => n + 1); linePlan.current = undefined; binding.current = undefined; } return Boolean(result); };
  const ownLocked = createSet.locked || createMeasurement.locked || bindLine.locked;
  const locked = ownLocked || Boolean(props.navigationLocked);
  const unknown = createSet.unknown || createMeasurement.unknown || bindLine.unknown;
  const sameActor = !binding.current || binding.current.company === props.company && binding.current.user === props.user && binding.current.personId === props.personId;
  useEffect(() => { props.onLockedChange(ownLocked); return () => props.onLockedChange(false); }, [ownLocked, props.onLockedChange]);
  useEffect(() => { setNotice(''); setSavedSet(undefined); }, [authority]);
  const finishSet = (v?: CompanyTakeoffCreateSetResponse) => { if (v) { setSavedSet({ company: v.takeoff_set.company, id: v.takeoff_set.id }); setNotice('Company takeoff set created.'); binding.current = undefined; setRevision(n => n + 1); } return Boolean(v); };
  const finishMeasurement = (v?: CompanyTakeoffCreateMeasurementResponse) => { if (v) { setNotice('Manual measurement saved. This is an authored quantity, without a calibrated geometry claim.'); binding.current = undefined; setRevision(n => n + 1); } return Boolean(v); };
  const commandError = commandKind === 'set' ? createSet.error : commandKind === 'measurement' ? createMeasurement.error : bindLine.error;
  useEffect(() => { if (commandError && [403, 404].includes(commandError.status)) setAccessDenied(true); }, [commandError]);
  return <>
    {(props.active || locked) && <div className="company-takeoff-command" aria-label="Company takeoff command state">
      {unknown && <><MessageStrip design="Critical" hideCloseButton>The result is uncertain. Keep this view open and recover the original request. Recovery lasts while this view stays open.</MessageStrip>{!sameActor && <p>Restore the original Company and signed-in person to recover this request.</p>}<Button disabled={createSet.busy || createMeasurement.busy || bindLine.busy || !sameActor || !props.active || props.navigationLocked} onClick={async () => { if (createSet.unknown) finishSet(await createSet.recover()); else if (createMeasurement.unknown) finishMeasurement(await createMeasurement.recover()); else finishLine(await bindLine.recover()); }}>Recover original takeoff request</Button></>}
      {commandError && <Failure error={commandError} />}
      {notice && <MessageStrip design="Positive" hideCloseButton>{notice}</MessageStrip>}
      {savedSet && !locked && <Button onClick={() => props.navigate(pathFor(savedSet.company, savedSet.id))}>Open created takeoff set</Button>}
    </div>}
    {props.active && !accessDenied && savedLine?.authority === authority && props.capabilities.includes('estimate.read') && props.capabilities.includes('document.read') && <div className="page company-takeoff-page"><SavedBinding saved={savedLine} locked={locked} onDenied={() => setAccessDenied(true)} /></div>}
    {props.active && accessDenied && <div className="page"><MessageStrip design="Information" hideCloseButton>Source access changed. Previous takeoff content is hidden. Recover an uncertain request before reopening current sources.</MessageStrip><Button disabled={locked} onClick={() => { setAccessDenied(false); setRevision(n => n + 1); }}>Recheck Company takeoff access</Button></div>}
    {props.active && !accessDenied && <AuthorityView key={authority} {...props} locked={locked} revision={revision}
      bindLine={async (review, reason) => { if (locked) return false; setCommandKind('line'); binding.current = { company: props.company, user: props.user, personId: props.personId }; linePlan.current = { review: structuredClone(review), authority, actor: { user: props.user, personId: props.personId }, sent: false, controller: new AbortController() }; setNotice(''); setSavedLine(undefined); return finishLine(await bindLine.run({ company: props.company, measurement_id: review.measurement.id, estimate_line_record: review.line.id, quantity_basis: 'net-quantity-v1', reason })); }}
      createSet={async input => { if (locked) return false; setCommandKind('set'); binding.current = { company: props.company, user: props.user, personId: props.personId }; setNotice(''); return finishSet(await createSet.run(input)); }}
      createMeasurement={async (input, documentId) => { if (locked) return false; setCommandKind('measurement'); binding.current = { company: props.company, user: props.user, personId: props.personId, documentId }; setNotice(''); return finishMeasurement(await createMeasurement.run(input)); }} />}
  </>;
}
type ViewProps = Props & { bindLine: (review: LineReview, reason: string) => Promise<boolean>; locked: boolean; revision: number; createSet: (input: SetInput) => Promise<boolean>; createMeasurement: (input: MeasureInput, documentId: string) => Promise<boolean> };
function AuthorityView(props: ViewProps) {
  if (!props.capabilities.includes('estimate.read') || !props.capabilities.includes('document.read')) return <div className="page"><PageHeading eyebrow="COMPANY ESTIMATING" title="Company drawing takeoff" /><Failure error={new ApiError('Company takeoff needs current estimate and source read access.', 'capability_denied', 403)} /></div>;
  return props.setId ? <Workspace key={props.setId} {...props} setId={props.setId} /> : <Register {...props} />;
}
function usePages() {
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]); const [page, setPage] = useState(0); const [generation, setGeneration] = useState(0);
  return { cursor: cursors[page], page, generation,
    verify: <T extends { next_cursor: string | null }>(result: T) => { if (result.next_cursor && cursors.slice(0, page + 1).includes(result.next_cursor)) throw invalidTakeoff(); return result; },
    previous: () => setPage(n => n - 1), next: (cursor: string) => { if (cursors.slice(0, page + 1).includes(cursor)) return; setCursors(old => [...old.slice(0, page + 1), cursor]); setPage(n => n + 1); }, reset: () => { setCursors([undefined]); setPage(0); setGeneration(n => n + 1); } };
}
function Pager({ paging, next, disabled }: { paging: ReturnType<typeof usePages>; next?: string | null; disabled: boolean }) {
  return <div className="page-controls"><Button disabled={disabled || !paging.page} onClick={paging.previous}>Previous takeoff page</Button><span>Page {paging.page + 1}</span><Button disabled={disabled || !next} onClick={() => next && paging.next(next)}>Next takeoff page</Button></div>;
}
function Register(props: ViewProps) {
  const paging = usePages(); const [open, setOpen] = useState(false);
  const rows = useResource(`${props.company}/company-takeoff/${paging.cursor || ''}/${paging.generation}/${props.revision}`, async signal => paging.verify(await companyTakeoff.list({ company: props.company, kind: 'set', cursor: paging.cursor }, signal)));
  return <div className="page company-takeoff-page"><PageHeading eyebrow="COMPANY ESTIMATING" title="Company drawing takeoff" description="Pre-award drawing sets and source-bound authored quantities." actions={<><Button disabled={props.locked} icon="refresh" onClick={paging.reset}>Refresh takeoff sets</Button>{props.capabilities.includes('estimate.write') && <Button disabled={props.locked} icon="add" design="Emphasized" onClick={() => setOpen(v => !v)}>New Company takeoff set</Button>}</>} />
    {open && <CreateSet {...props} onClose={() => setOpen(false)} />}
    <section className="surface"><Title level="H2">Company takeoff sets</Title>{rows.loading ? <Loading /> : rows.error ? <Failure error={rows.error} onRetry={props.locked ? undefined : paging.reset} /> : rows.data?.items.length ? <ul className="company-takeoff-list">{rows.data.items.map(({ record }) => { const r = record as CompanyTakeoffSetRecord; return <li key={r.id}><Button design="Transparent" disabled={props.locked} onClick={() => props.navigate(pathFor(props.company, r.id))}>{r.title}</Button><p>{r.discipline} · {r.drawing_package}</p><p>{r.basis}</p></li>; })}</ul> : <Empty title="No Company takeoff sets" icon="measure">Create a set for a drawing package and an explicit measurement basis.</Empty>}
      {!rows.loading && !rows.error && <Pager paging={paging} next={rows.data?.next_cursor} disabled={props.locked} />}
    </section></div>;
}
function CreateSet(props: ViewProps & { onClose: () => void }) {
  const [title, setTitle] = useState(''); const [discipline, setDiscipline] = useState(''); const [drawingPackage, setPackage] = useState(''); const [basis, setBasis] = useState('');
  const input: SetInput = { company: props.company, title, discipline, drawing_package: drawingPackage, basis };
  return <section className="surface" aria-label="New Company takeoff set"><Title level="H2">New Company takeoff set</Title><div className="company-takeoff-fields"><Field label="Takeoff set title" value={title} onChange={setTitle} disabled={props.locked} /><Field label="Discipline" value={discipline} onChange={setDiscipline} disabled={props.locked} /><Field label="Drawing package" value={drawingPackage} onChange={setPackage} disabled={props.locked} /><Field label="Takeoff set basis" value={basis} onChange={setBasis} disabled={props.locked} /></div><Button design="Emphasized" disabled={props.locked || !takeoffShape('CompanyTakeoffCreateSetRequest', input) || ![title, discipline, drawingPackage, basis].every(v => v.trim())} onClick={async () => { if (await props.createSet(input)) props.onClose(); }}>Create Company takeoff set</Button><Button disabled={props.locked} onClick={props.onClose}>Cancel new takeoff set</Button></section>;
}
function Workspace(props: ViewProps & { setId: string }) {
  const set = useResource(`${props.company}/takeoff-set/${props.setId}/${props.revision}`, signal => companyTakeoff.get(props.company, 'set', props.setId, signal));
  if (set.loading) return <Loading label="Opening Company takeoff set…" />;
  if (set.error) return <div className="page"><Failure error={set.error} onRetry={props.locked ? undefined : set.refresh} /></div>;
  if (!set.data) return null;
  const record = set.data.record as CompanyTakeoffSetRecord;
  return <div className="page company-takeoff-page"><PageHeading eyebrow="COMPANY DRAWING TAKEOFF" title={record.title} description={`${record.discipline} · ${record.drawing_package}`} actions={<Button disabled={props.locked} onClick={() => props.navigate(pathFor(props.company))}>Company takeoff sets</Button>} /><p>{record.basis}</p><MessageStrip design="Information" hideCloseButton>Quantity basis: Manual entry. Record the drawing reference and reason for each authored quantity.</MessageStrip>
    <SourceWorkspace {...props} /><SavedMeasurements {...props} />
  </div>;
}
function SourceWorkspace(props: ViewProps & { setId: string }) {
  const docs = useResource(`${props.company}/takeoff-sources`, signal => companyTakeoff.sources(props.company, signal));
  const [documentId, setDocument] = useState(''); const [revisionId, setRevision] = useState(''); const [page, setPage] = useState(1); const [refresh, setRefresh] = useState(0); const [pdfAttempt, setPdfAttempt] = useState(0); const [verifiedPdf, setVerifiedPdf] = useState('');
  const detail = useResource(documentId && docs.data && !docs.loading && !docs.error ? `${props.company}/takeoff-source/${documentId}/${refresh}` : null, signal => companyTakeoff.source(props.company, documentId, signal));
  const revision = detail.data && !detail.loading && !detail.error ? detail.data.revisions.find(r => r.id === revisionId) : undefined;
  // A drawing may have no embedded text. Raw bytes, their hash and the actual
  // PDF frame authorize this view; text citation availability is independent.
  const valid = Boolean(revision && validTakeoffPdfMetadata(revision) && Number.isInteger(page) && page >= 1 && page <= revision.page_count);
  const current = Boolean(valid && detail.data?.document.current_revision === revisionId);
  const pdfKey = revision ? `${revision.id}/${revision.sha256}/${page}/${refresh}/${pdfAttempt}` : '';
  const frameDenied = verifiedPdf === `denied:${pdfKey}`;
  return <section className="surface company-takeoff-source" aria-label="Company drawing source"><div className="company-takeoff-section-heading"><Title level="H2" wrappingType="Normal">Drawing source</Title><Button disabled={props.locked} onClick={() => { setDocument(''); setRevision(''); setPage(1); setRefresh(n => n + 1); docs.refresh(); }}>Refresh source access</Button></div>
    {docs.loading ? <Loading /> : docs.error ? <Failure error={docs.error} onRetry={props.locked ? undefined : docs.refresh} /> : <><Label>Company source</Label><Select accessibleName="Company takeoff source" disabled={props.locked} onChange={event => { setDocument(event.detail.selectedOption.value!); setRevision(''); setPage(1); setPdfAttempt(n => n + 1); }}><Option value="" selected={!documentId}>Choose an authorized drawing</Option>{docs.data?.items.filter(r => r.mime_type === 'application/pdf').map(r => <Option key={r.id} value={r.id} selected={r.id === documentId}>{r.title}</Option>)}</Select></>}
    {detail.loading && <Loading label="Checking selected Company source…" />}{detail.error && <Failure error={detail.error} onRetry={props.locked ? undefined : detail.refresh} />}
    {detail.data && !detail.loading && !detail.error && <><Label>Stored revision</Label><Select accessibleName="Company takeoff revision" disabled={props.locked} onChange={event => { setRevision(event.detail.selectedOption.value!); setPage(1); setPdfAttempt(n => n + 1); }}><Option value="" selected={!revisionId}>Choose a stored revision</Option>{detail.data.revisions.filter(r => r.mime_type === 'application/pdf').map(r => <Option key={r.id} value={r.id} selected={r.id === revisionId}>Rev. {r.revision_number}{r.id === detail.data!.document.current_revision ? ' · Current working' : ' · Historical'}</Option>)}</Select></>}
    {revision && !valid && <Failure error={invalidTakeoff()} />}
    {valid && revision && <><div className="page-controls"><Button disabled={props.locked || page <= 1} onClick={() => { setPage(n => n - 1); setPdfAttempt(n => n + 1); }}>Previous drawing page</Button><span>Page {page} of {revision.page_count}</span><Button disabled={props.locked || page >= revision.page_count} onClick={() => { setPage(n => n + 1); setPdfAttempt(n => n + 1); }}>Next drawing page</Button></div>
      {frameDenied ? <Failure error={new ApiError('The PDF page count does not match the authorized revision metadata. Refresh source access.', 'PDF_FRAME_MISMATCH', 422)} /> : <Suspense fallback={<Loading />}><PdfDrawing key={pdfKey} company={props.company} revisionId={revision.id} sourceSha256={revision.sha256} page={page} points={[]} disabled mode="Manual quantity source inspection" downloadUrl={sourceApi({ type: 'Company', company: props.company }).downloadUrl(revision.id)} onFrame={frame => { setVerifiedPdf(frame.sourceSha256 === revision.sha256 && frame.pageCount === revision.page_count ? pdfKey : `denied:${pdfKey}`); }} /></Suspense>}
      <details><summary>Exact source reference</summary><p>Revision {revision.revision_number} · Page {page}</p><code>{revision.sha256}</code></details>
      {!current && <MessageStrip design="Information" hideCloseButton>This historical revision is available for inspection. New manual measurements use a current working revision; the server rechecks eligibility when saving.</MessageStrip>}
      {current && verifiedPdf === pdfKey && props.capabilities.includes('estimate.write') && <ManualForm key={`${documentId}/${pdfKey}`} {...props} documentId={documentId} source={{ revision_id: revision.id, source_sha256: revision.sha256, page }} />}
    </>}
  </section>;
}
function ManualForm(props: ViewProps & { setId: string; documentId: string; source: MeasureInput['source'] }) {
  const units = useResource(`${props.company}/takeoff-units`, signal => companyTakeoff.units(props.company, signal));
  const [unitId, setUnit] = useState(''); const [amount, setAmount] = useState(''); const [locator, setLocator] = useState(''); const [reason, setReason] = useState(''); const [error, setError] = useState('');
  const unit = units.data?.items.find(r => r.id === unitId);
  const precision = unit?.fields.precision ?? 0;
  const definition: MeasureInput['definition'] = { method: 'manual', kind: unit?.fields.dimension || 'count', locator, reason, result_unit_id: unitId, result_precision: precision, tolerance: '0.000001', waste_fraction: '0', formula_version: 'cipher.takeoff.planar.v1', manual_quantity: { amount, unit_id: unitId, precision } };
  const input: MeasureInput = { company: props.company, takeoff_set: props.setId, source: props.source, definition, conversion_ids: [] };
  const exact = /^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$/.test(amount) && (amount.split('.')[1]?.length ?? 0) <= precision;
  return <section aria-label="Author manual quantity"><Title level="H3">Author a manual quantity</Title><p>Enter a quantity in its declared unit. Precision comes from the canonical unit; no conversion, geometry or waste is inferred.</p>{units.loading ? <Loading /> : units.error ? <Failure error={units.error} onRetry={props.locked ? undefined : units.refresh} /> : <><Label>Quantity unit</Label><Select accessibleName="Manual quantity unit" disabled={props.locked} onChange={event => setUnit(event.detail.selectedOption.value!)}><Option value="" selected={!unitId}>Choose a qualified unit</Option>{units.data?.items.map(r => <Option key={r.id} value={r.id} selected={unitId === r.id}>{r.fields.symbol} · {r.fields.dimension} · {r.fields.precision} decimal places</Option>)}</Select><div className="company-takeoff-fields"><Field label="Manual quantity" value={amount} onChange={setAmount} disabled={props.locked} /><Field label="Drawing locator" value={locator} onChange={setLocator} disabled={props.locked} /><Field label="Manual quantity reason" value={reason} onChange={setReason} disabled={props.locked} multiline /></div>{unit && <p className="caption">{unit.fields.dimension} · precision {precision} · arithmetic tolerance 0.000001 · waste 0</p>}{error && <MessageStrip design="Negative" hideCloseButton>{error}</MessageStrip>}<Button design="Emphasized" disabled={props.locked || !unit || !exact || !takeoffShape('CompanyTakeoffCreateMeasurementRequest', input) || !locator.trim() || !reason.trim()} onClick={async () => { setError(''); if (!exact || !unit) { setError('Use an exact decimal within the selected unit precision.'); return; } if (await props.createMeasurement(input, props.documentId)) { setAmount(''); setLocator(''); setReason(''); } }}>Save manual measurement</Button></>}
  </section>;
}
function SavedMeasurements(props: ViewProps & { setId: string }) {
  const paging = usePages(); const [selected, setSelected] = useState('');
  const rows = useResource(`${props.company}/${props.setId}/measurements/${paging.cursor || ''}/${paging.generation}/${props.revision}`, async signal => paging.verify(await companyTakeoff.list({ company: props.company, kind: 'measurement', takeoff_set: props.setId, cursor: paging.cursor }, signal)));
  const member = Boolean(!rows.loading && !rows.error && rows.data?.items.some(row => row.record.id === selected));
  const detail = useResource(member ? `${props.company}/${props.setId}/measurement/${selected}/${props.revision}` : null, signal => companyTakeoff.get(props.company, 'measurement', selected, signal, props.setId));
  useEffect(() => { setSelected(''); }, [paging.cursor, paging.generation]);
  const r = member && !detail.loading && !detail.error ? detail.data?.record as CompanyTakeoffMeasurementRecord | undefined : undefined;
  return <section className="surface"><div className="company-takeoff-section-heading"><Title level="H2" wrappingType="Normal">Saved measurements</Title><Button disabled={props.locked} onClick={() => { setSelected(''); paging.reset(); }}>Refresh saved measurements</Button></div>
    {rows.loading ? <Loading /> : rows.error ? <Failure error={rows.error} onRetry={props.locked ? undefined : () => { setSelected(''); paging.reset(); }} /> : rows.data?.items.length ? <ul className="company-takeoff-list">{rows.data.items.map(value => { const row = value.record as CompanyTakeoffMeasurementRecord; return <li key={row.id}><Button disabled={props.locked} design="Transparent" onClick={() => setSelected(row.id)}>{row.definition.locator}</Button><p>{quantityLabel(row)} · {row.result.method === 'manual' ? 'Authored manual quantity' : 'Saved calibrated quantity'}</p><p>{value.current_use?.eligible ? 'Server reports eligible for current use' : 'Historical / unavailable for new use'}</p></li>; })}</ul> : <Empty title="No saved measurements" icon="measure">Save a manual quantity against an exact source page.</Empty>}
    {!rows.loading && !rows.error && <Pager paging={paging} next={rows.data?.next_cursor} disabled={props.locked} />}
    {detail.loading && <Loading label="Reading saved measurement…" />}{detail.error && <Failure error={detail.error} onRetry={props.locked ? undefined : detail.refresh} />}
    {r && <section aria-label="Saved Company measurement"><Title level="H3">{r.definition.locator}</Title><p>{r.definition.reason}</p><Fact label="Quantity">{quantityLabel(r)} · precision {r.result.quantity.precision}</Fact><p>{r.result.method === 'manual' ? 'Authored manual quantity. No calibrated geometry claim.' : 'Historical calibrated result. This workspace provides read-only inspection.'}</p><p>Source revision {r.source.revision_number} · Page {r.source.page}</p><p>{detail.data?.current_use?.eligible ? 'Server reports eligible for current use.' : `Unavailable for new use: ${detail.data?.current_use?.reasons.join(', ')}`}</p><Button disabled={props.locked} onClick={() => props.navigate(`/company/documents/${encodeURIComponent(r.source.document_id)}/revisions/${encodeURIComponent(r.source.revision_id)}?${new URLSearchParams({ company: props.company, page: String(r.source.page) })}`)}>Open exact measurement source</Button>{props.capabilities.includes('estimate.write') && detail.data && <CompanyTakeoffBinding key={r.id} company={props.company} selected={detail.data} locked={props.locked} submit={props.bindLine} />}<details><summary>Stored measurement integrity</summary><code>{r.id}</code><p>Unit {r.result.quantity.unit_id}</p><code>{r.source.source_sha256}</code><p>Recorded {r.created_at} by {r.author_user}</p></details></section>}
  </section>;
}
function Field({ label, value, onChange, disabled, multiline = false }: { label: string; value: string; onChange: (value: string) => void; disabled: boolean; multiline?: boolean }) {
  return <div><Label required>{label}</Label>{multiline ? <TextArea accessibleName={label} value={value} disabled={disabled} rows={3} onInput={e => onChange(e.currentTarget!.value)} /> : <Input accessibleName={label} value={value} disabled={disabled} onInput={e => onChange(e.currentTarget!.value)} />}</div>;
}
