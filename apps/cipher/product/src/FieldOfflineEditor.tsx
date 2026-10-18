import { useRef, useState } from 'react';
import { Button, CheckBox, Input, Label, MessageStrip, Option, Select, TextArea, Title } from '@ui5/webcomponents-react';
import { offlineShape } from './api/field-offline';
import type { FoCommand, FoDailyDefinitionInput, FoPhotoInput, FoQuantityDefinitionInput, FoSourceInput, FoTicketDefinitionInput, FoTicketLineInput } from './api/field-offline.generated';
import type { ProjectDocumentRecord } from './api/types';
import './field-records.css';
import './field-offline-editor.css';

export type FieldOfflineEditorProps = {
  initial?: FoCommand;
  requireAmendmentReason?: boolean;
  sources: ProjectDocumentRecord[];
  registeredUser: string;
  disabled: boolean;
  onSeal: (command: FoCommand, capturedAt: string) => Promise<void>;
  onCancel: () => void;
};

const emptyDaily = (user: string): FoDailyDefinitionInput => ({ local_date: '', superintendent_user: user, weather: '', weather_sources: [], crews: [], activities: [], delays: [], visitors: [] });
const emptyTicket = (): FoTicketDefinitionInput => ({ local_date: '', title: '', customer_name: '', location: '', work_description: '', potential_change_reference: '', lines: [] });
const lines = (text: string) => text.split('\n');
const populatedLines = (rows: string[]) => rows.filter(row => row.trim());
const sourceKey = (source: FoSourceInput) => JSON.stringify([source.revision_id, source.source_sha256, source.page, source.locator]);
const documentKey = (document: ProjectDocumentRecord) => JSON.stringify([document.id, document.current_revision, document.sha256]);
const cachedDocument = (row: ProjectDocumentRecord) => Boolean(row.current_revision && row.current_revision.length <= 140 && !row.current_revision.includes('\0') && /^[a-f0-9]{64}$/.test(row.sha256) && Number.isSafeInteger(row.page_count) && row.page_count >= 1 && row.page_count <= 200 && Number.isSafeInteger(row.byte_length) && row.byte_length > 0 && row.scan_status === 'clean');
const sourceDocument = (source: FoSourceInput, documents: ProjectDocumentRecord[]) => documents.find(row => cachedDocument(row) && row.current_revision === source.revision_id && row.sha256 === source.source_sha256 && source.page <= row.page_count && (!['image/jpeg', 'image/png'].includes(row.mime_type) || source.page === 1));

type TextFieldProps = { label: string; value: string; onChange: (value: string) => void; disabled: boolean; maximum?: number; multiline?: boolean; required?: boolean; placeholder?: string; exactQuantity?: boolean };
function TextField({ label, value, onChange, disabled, maximum = 240, multiline = false, required = true, placeholder, exactQuantity = false }: TextFieldProps) {
  const invalid = exactQuantity && value.length > 0 && !offlineShape('FoQuantityValue', value);
  return <div className="field-offline-input"><Label required={required}>{label}</Label>{multiline
    ? <TextArea accessibleName={label} value={value} maxlength={maximum} rows={3} disabled={disabled} placeholder={placeholder} onInput={event => onChange(event.currentTarget!.value)} />
    : <Input accessibleName={label} value={value} maxlength={maximum} disabled={disabled} placeholder={placeholder} valueState={invalid ? 'Negative' : 'None'} onInput={event => onChange(event.currentTarget!.value)} />}
    {invalid && <p className="caption field-offline-invalid">Use a positive decimal, up to 12 whole digits and 6 decimal places.</p>}</div>;
}

/** Local form only. The parent owns the encrypted profile, fresh online base choice,
 * envelope identity and seal. Remount for a different profile or prepared command. */
export function FieldOfflineEditor(props: FieldOfflineEditorProps) {
  const [basis] = useState(() => props.initial ? structuredClone(props.initial) : undefined);
  const [family, setFamily] = useState<'daily' | 'ticket'>(basis?.family || 'daily');
  const [daily, setDaily] = useState<FoDailyDefinitionInput>(() => basis?.family === 'daily' ? structuredClone(basis.definition) : emptyDaily(props.registeredUser));
  const [ticket, setTicket] = useState<FoTicketDefinitionInput>(() => basis?.family === 'ticket' ? structuredClone(basis.definition) : emptyTicket());
  const [ticketLineKeys, setTicketLineKeys] = useState<string[]>(() => basis?.family === 'ticket' ? basis.definition.lines.map((_, index) => `prepared-line-${index}`) : []);
  const [photos, setPhotos] = useState<FoPhotoInput[]>(() => structuredClone(basis?.photos || []));
  const [quantities, setQuantities] = useState<FoQuantityDefinitionInput[]>(() => basis?.family === 'daily' ? structuredClone(basis.quantities) : []);
  const [reason, setReason] = useState(basis?.action === 'revise' ? basis.amendment_reason : '');
  const [capturedAt, setCapturedAt] = useState(''), [reviewed, setReviewed] = useState(false), [busy, setBusy] = useState(false), [sealed, setSealed] = useState(false), [sealError, setSealError] = useState('');
  const sealing = useRef(false), disabled = props.disabled || busy || sealed;
  const change = (update: () => void) => { if (disabled) return; update(); setReviewed(false); setSealError(''); };
  const identity = basis?.action === 'revise'
    ? { action: 'revise' as const, record_id: basis.record_id, expected_version: basis.expected_version, base_revision_id: basis.base_revision_id, base_revision_digest: basis.base_revision_digest, amendment_reason: props.requireAmendmentReason ? reason : '' }
    : { action: 'create' as const };
  const command: FoCommand = family === 'daily'
    ? { ...identity, family: 'daily', definition: { ...daily, activities: populatedLines(daily.activities), crews: populatedLines(daily.crews), delays: populatedLines(daily.delays), visitors: populatedLines(daily.visitors) }, photos, quantities }
    : { ...identity, family: 'ticket', definition: ticket, photos, quantities: [] };
  const references = [...(command.family === 'daily' ? [...command.definition.weather_sources, ...command.quantities.flatMap(row => row.sources)] : command.definition.lines.flatMap(row => row.sources)), ...photos.map(photo => photo.source)];
  const missingSources = references.some(source => !sourceDocument(source, props.sources));
  const invalidPhotos = photos.some(photo => { const document = sourceDocument(photo.source, props.sources); return !document || (photo.representation === 'source_image' ? !['image/jpeg', 'image/png'].includes(document.mime_type) || photo.source.page !== 1 : document.mime_type !== 'application/pdf'); });
  const duplicateQuantityIds = new Set(command.quantities.map(row => row.original_event_id)).size !== command.quantities.length;
  const valid = offlineShape('FoCommand', command) && offlineShape('FoTimestamp', capturedAt) && !missingSources && !invalidPhotos && !duplicateQuantityIds && (!props.requireAmendmentReason || Boolean(reason.trim()));
  const input = (label: string, value: string, update: (value: string) => void, options: Partial<Pick<TextFieldProps, 'maximum' | 'multiline' | 'required' | 'placeholder'>> = {}) => <TextField label={label} value={value} disabled={disabled} onChange={value => change(() => update(value))} {...options} />;
  const seal = async () => {
    if (disabled || sealing.current || !valid || !reviewed) return;
    sealing.current = true; setBusy(true); setSealError('');
    try { await props.onSeal(structuredClone(command), capturedAt); setSealed(true); }
    catch (error) { setSealError(error instanceof Error ? error.message : 'This capture could not be sealed. Your entries are retained.'); setReviewed(false); }
    finally { sealing.current = false; setBusy(false); }
  };
  return <section className="field-editor field-offline-editor" aria-label="Offline field capture editor">
    <Title level="H2">{basis?.action === 'revise' ? 'Prepare offline revision' : 'New offline field capture'}</Title>
    <p>Seal an observation in this profile’s encrypted workspace. Reconnect, inspect and apply are separate actions.</p>
    <MessageStrip design="Information" hideCloseButton>Participant attribution is unverified until staging. Declared capture account: {props.registeredUser}. Cached sources do not establish current access or authority.</MessageStrip>
    {!basis && <div className="field-offline-kind"><Label>Record type</Label><Select accessibleName="Offline record type" disabled={disabled} onChange={event => change(() => setFamily(event.detail.selectedOption.value as 'daily' | 'ticket'))}><Option value="daily" selected={family === 'daily'}>Daily report</Option><Option value="ticket" selected={family === 'ticket'}>T&amp;M ticket</Option></Select></div>}
    {basis?.action === 'revise' && <details className="field-offline-base"><summary>Prepared revision base</summary><p>This exact base was loaded by the workspace. Changes after preparation are checked when you reconnect.</p><dl><dt>Record</dt><dd><code>{basis.record_id}</code></dd><dt>Base revision</dt><dd><code>{basis.base_revision_id}</code></dd><dt>Base digest</dt><dd><code>{basis.base_revision_digest}</code></dd><dt>Expected record digest</dt><dd><code>{basis.expected_version}</code></dd></dl></details>}
    {family === 'daily' ? <>
      <div className="field-form-grid">{input('Report date (YYYY-MM-DD)', daily.local_date, local_date => setDaily({ ...daily, local_date }), { maximum: 10, placeholder: '2026-10-17' })}{input('Superintendent account', daily.superintendent_user, superintendent_user => setDaily({ ...daily, superintendent_user }), { maximum: 140 })}</div>
      <p className="caption">The declared superintendent account is checked against its canonical Person and current project access at staging.</p>
      {(['activities', 'crews', 'delays', 'visitors'] as const).map(key => <div key={key}>{input(({ activities: 'Activities, one per line', crews: 'Crews, one per line', delays: 'Delays, one per line', visitors: 'Visitors, one per line' })[key], daily[key].join('\n'), value => setDaily({ ...daily, [key]: lines(value) }), { maximum: 40020, multiline: true, required: key === 'activities' })}<p className="caption">{key === 'activities' ? '1–20 entries' : 'Up to 20 entries'}; 2,000 characters per entry.</p></div>)}
      {input('Weather observations', daily.weather, weather => setDaily({ ...daily, weather }), { maximum: 2000, multiline: true, required: false })}
      <p className="caption">Weather is optional. A weather observation needs at least one source reference.</p>
      <CachedSourcePicker label="Weather sources" documents={props.sources} sources={daily.weather_sources} disabled={disabled} onDirty={() => change(() => {})} onChange={weather_sources => change(() => setDaily({ ...daily, weather_sources }))} />
      <section className="field-editor-section"><Title level="H3">Installed and delivered quantities</Title><p className="caption">Optional, up to 40 rows. Enter exact positive decimal quantities and unit labels. Each row needs a source reference.</p>
        {quantities.map((quantity, index) => <OfflineQuantityRow key={quantity.original_event_id} value={quantity} index={index} documents={props.sources} disabled={disabled} onDirty={() => change(() => {})} onChange={value => change(() => setQuantities(quantities.map((row, i) => i === index ? value : row)))} onRemove={() => change(() => setQuantities(quantities.filter((_, i) => i !== index)))} />)}
        <Button disabled={disabled || quantities.length >= 40} onClick={() => change(() => setQuantities([...quantities, { original_event_id: crypto.randomUUID(), supersedes_event_id: null, kind: 'installed', description: '', wbs_code: '', cost_code: '', quantity: '', unit: '', location: '', sources: [] }]))}>Add quantity</Button>
      </section>
    </> : <>
      <div className="field-form-grid">{input('Ticket date (YYYY-MM-DD)', ticket.local_date, local_date => setTicket({ ...ticket, local_date }), { maximum: 10, placeholder: '2026-10-17' })}{input('Ticket title', ticket.title, title => setTicket({ ...ticket, title }))}{input('Customer or representative', ticket.customer_name, customer_name => setTicket({ ...ticket, customer_name }))}{input('Work location', ticket.location, location => setTicket({ ...ticket, location }))}</div>
      {input('Work performed', ticket.work_description, work_description => setTicket({ ...ticket, work_description }), { maximum: 10000, multiline: true })}{input('Potential change reference', ticket.potential_change_reference, potential_change_reference => setTicket({ ...ticket, potential_change_reference }), { required: false })}
      <section className="field-editor-section"><Title level="H3">Labor, equipment and materials</Title><p className="caption">1–40 quantity lines, each with a source reference. This records observations; it creates no contract, payroll, procurement or financial effect.</p>
        {ticket.lines.map((line, index) => <OfflineTicketLine key={ticketLineKeys[index]} value={line} index={index} documents={props.sources} disabled={disabled} onDirty={() => change(() => {})} onChange={value => change(() => setTicket({ ...ticket, lines: ticket.lines.map((row, i) => i === index ? value : row) }))} onRemove={() => change(() => { setTicket({ ...ticket, lines: ticket.lines.filter((_, i) => i !== index) }); setTicketLineKeys(ticketLineKeys.filter((_, i) => i !== index)); })} />)}
        <Button disabled={disabled || ticket.lines.length >= 40} onClick={() => change(() => { setTicket({ ...ticket, lines: [...ticket.lines, { kind: 'labor', description: '', quantity: '', unit: '', sources: [] }] }); setTicketLineKeys([...ticketLineKeys, crypto.randomUUID()]); })}>Add ticket line</Button>
      </section>
    </>}
    <OfflinePhotos photos={photos} documents={props.sources} disabled={disabled} onDirty={() => change(() => {})} onChange={next => change(() => setPhotos(next))} />
    {basis?.action === 'revise' && props.requireAmendmentReason && input('Amendment reason for the accepted original', reason, setReason, { maximum: 2000, multiline: true, required: true })}
    <section className="field-editor-section"><Title level="H3">Seal this capture</Title>{input('Capture time with UTC offset', capturedAt, setCapturedAt, { maximum: 40, placeholder: '2026-10-17T14:30:00-04:00' })}<Button design="Transparent" disabled={disabled} onClick={() => change(() => setCapturedAt(new Date().toISOString()))}>Use current time</Button><p className="caption">The time is your declared observation. Sealing freezes the capture’s contents; it does not create a server record.</p></section>
    {(missingSources || invalidPhotos) && <MessageStrip design="Critical" hideCloseButton>A retained source is missing from this profile’s cached source list or its page or photo type does not match. Replace or remove that reference before sealing.</MessageStrip>}
    {!valid && <p className="caption" role="status">Complete required fields and a valid capture time. Keep dates, entry counts, exact quantities and source references within the limits shown.</p>}
    {duplicateQuantityIds && <MessageStrip design="Critical" hideCloseButton>Two quantity rows share an observation ID. Prepare this report again from its current record.</MessageStrip>}
    {sealError && <MessageStrip design="Critical" hideCloseButton>{sealError}</MessageStrip>}
    {sealed && <MessageStrip design="Positive" hideCloseButton>Capture sealed locally. Return to the workspace to inspect it after reconnecting.</MessageStrip>}
    <div className="field-review-check"><CheckBox accessibleName="I reviewed this offline capture" text="I reviewed the dates, exact quantities, participants and source references" checked={reviewed} disabled={disabled || !valid} onChange={event => { setReviewed(event.currentTarget!.checked); setSealError(''); }} /></div>
    <div className="field-form-actions"><Button disabled={props.disabled || busy} onClick={props.onCancel}>{sealed ? 'Back to workspace' : 'Cancel'}</Button><Button design="Emphasized" disabled={disabled || !valid || !reviewed} onClick={seal}>{sealed ? 'Sealed locally' : busy ? 'Sealing…' : 'Seal encrypted capture'}</Button></div>
  </section>;
}

type SourcePickerProps = { label: string; documents: ProjectDocumentRecord[]; sources: FoSourceInput[]; disabled: boolean; onChange: (sources: FoSourceInput[]) => void; onDirty: () => void; maximum?: number; photoOnly?: boolean };
function CachedSourcePicker({ label, documents, sources, disabled, onChange, onDirty, maximum = 8, photoOnly = false }: SourcePickerProps) {
  const [choice, setChoice] = useState(''), [page, setPage] = useState('1'), [locator, setLocator] = useState('');
  const available = documents.filter(row => cachedDocument(row) && (!photoOnly || ['image/jpeg', 'image/png', 'application/pdf'].includes(row.mime_type)));
  const selected = available.find(row => documentKey(row) === choice), pageNumber = /^[1-9][0-9]{0,2}$/.test(page) ? Number(page) : 0;
  const candidate: FoSourceInput | undefined = selected && pageNumber <= selected.page_count && pageNumber > 0 && (!['image/jpeg', 'image/png'].includes(selected.mime_type) || pageNumber === 1)
    ? { revision_id: selected.current_revision, source_sha256: selected.sha256, page: pageNumber, locator } : undefined;
  const valid = candidate && offlineShape('FoSourceInput', candidate) && !sources.some(source => sourceKey(source) === sourceKey(candidate));
  return <section className="field-source-picker" aria-label={label}><Label>{label} · {sources.length}/{maximum}</Label>
    {sources.map((source, index) => { const document = sourceDocument(source, documents); return <div className="field-source-chip field-offline-source" key={`${sourceKey(source)}/${index}`}><div><span>{document?.title || 'Retained source revision'} · Page {source.page} · {source.locator}</span><details><summary>Exact reference</summary><code>{source.revision_id}</code><code>{source.source_sha256}</code></details>{!document && <p className="caption field-offline-invalid">This reference is unavailable in the cached list.</p>}</div><Button design="Transparent" accessibleName={`Remove ${label} ${index + 1}`} disabled={disabled} onClick={() => onChange(sources.filter((_, i) => i !== index))}>Remove</Button></div>; })}
    {sources.length < maximum && <><Select accessibleName={label} disabled={disabled || !available.length} onChange={event => { onDirty(); setChoice(event.detail.selectedOption.value || ''); setPage('1'); setLocator(''); }}><Option value="" selected={!choice}>Choose a cached source</Option>{available.map(document => <Option key={documentKey(document)} value={documentKey(document)} selected={choice === documentKey(document)}>{document.title} · Rev. {document.revision_number}</Option>)}</Select>
      {selected && <><div className="field-form-grid"><TextField label={`${label} page`} value={page} maximum={3} disabled={disabled || ['image/jpeg', 'image/png'].includes(selected.mime_type)} onChange={value => { onDirty(); setPage(value); }} /><TextField label={`${label} location in source`} value={locator} maximum={1000} disabled={disabled} placeholder="For example: delivery note, line 2" onChange={value => { onDirty(); setLocator(value); }} /></div><p className="caption">{selected.mime_type === 'application/pdf' ? `${selected.page_count} cached PDF pages. Identify the exact page and location.` : ['image/jpeg', 'image/png'].includes(selected.mime_type) ? 'Original JPEG or PNG reference; page 1.' : `${selected.page_count} cached source pages.`}</p><Button disabled={disabled || !valid} onClick={() => { if (candidate && valid) { onChange([...sources, candidate]); setChoice(''); setPage('1'); setLocator(''); } }}>Add source reference</Button></>}
    </>}
    {!available.length && <p className="caption">No eligible sources are cached in this profile. Add original documents online before preparing source-backed observations.</p>}
    <p className="caption">Only references listed above are included. Current source permissions and revision standing are checked when you reconnect.</p>
  </section>;
}

type RowProps<T> = { value: T; index: number; documents: ProjectDocumentRecord[]; disabled: boolean; onChange: (value: T) => void; onRemove: () => void; onDirty: () => void };
function OfflineQuantityRow({ value, index, documents, disabled, onChange, onRemove, onDirty }: RowProps<FoQuantityDefinitionInput>) {
  const prefix = `Quantity ${index + 1}`;
  return <section className="field-line" aria-label={prefix}><Title level="H4">{prefix}</Title><div className="field-form-grid"><div><Label>Observation</Label><Select accessibleName={`${prefix} kind`} disabled={disabled} onChange={event => onChange({ ...value, kind: event.detail.selectedOption.value as FoQuantityDefinitionInput['kind'] })}><Option value="installed" selected={value.kind === 'installed'}>Installed</Option><Option value="delivered" selected={value.kind === 'delivered'}>Delivered</Option></Select></div>
    {(['description', 'quantity', 'unit', 'location', 'wbs_code', 'cost_code'] as const).map(key => <TextField key={key} label={`${prefix} ${({ description: 'description', quantity: 'exact quantity', unit: 'unit label', location: 'location', wbs_code: 'WBS label', cost_code: 'cost code label' })[key]}`} value={value[key]} maximum={key === 'unit' ? 40 : key.includes('code') ? 140 : key === 'quantity' ? 19 : 1000} required={!key.includes('code')} exactQuantity={key === 'quantity'} disabled={disabled} onChange={next => onChange({ ...value, [key]: next })} />)}
    </div><details><summary>Observation lineage</summary><p>Original observation: <code>{value.original_event_id}</code></p>{value.supersedes_event_id ? <p>Corrects exact capture: <code>{value.supersedes_event_id}</code></p> : <p>New observation.</p>}</details><CachedSourcePicker label={`${prefix} sources`} documents={documents} sources={value.sources} disabled={disabled} onChange={sources => onChange({ ...value, sources })} onDirty={onDirty} /><Button design="Transparent" disabled={disabled} onClick={onRemove}>Remove quantity {index + 1}</Button></section>;
}
function OfflineTicketLine({ value, index, documents, disabled, onChange, onRemove, onDirty }: RowProps<FoTicketLineInput>) {
  const prefix = `Ticket line ${index + 1}`;
  return <section className="field-line" aria-label={prefix}><Title level="H4">{prefix}</Title><div className="field-form-grid"><div><Label>Line kind</Label><Select accessibleName={`${prefix} kind`} disabled={disabled} onChange={event => onChange({ ...value, kind: event.detail.selectedOption.value as FoTicketLineInput['kind'] })}>{(['labor', 'equipment', 'material'] as const).map(kind => <Option key={kind} value={kind} selected={value.kind === kind}>{kind[0].toUpperCase() + kind.slice(1)}</Option>)}</Select></div>
    {(['description', 'quantity', 'unit'] as const).map(key => <TextField key={key} label={`${prefix} ${key === 'quantity' ? 'exact quantity' : key === 'unit' ? 'unit label' : 'description'}`} value={value[key]} maximum={key === 'unit' ? 40 : key === 'quantity' ? 19 : 1000} exactQuantity={key === 'quantity'} disabled={disabled} onChange={next => onChange({ ...value, [key]: next })} />)}
    </div><CachedSourcePicker label={`${prefix} sources`} documents={documents} sources={value.sources} disabled={disabled} onChange={sources => onChange({ ...value, sources })} onDirty={onDirty} /><Button design="Transparent" disabled={disabled} onClick={onRemove}>Remove ticket line {index + 1}</Button></section>;
}

function OfflinePhotos({ photos, documents, disabled, onChange, onDirty }: { photos: FoPhotoInput[]; documents: ProjectDocumentRecord[]; disabled: boolean; onChange: (photos: FoPhotoInput[]) => void; onDirty: () => void }) {
  const [sources, setSources] = useState<FoSourceInput[]>([]), [caption, setCaption] = useState(''), [capturedAt, setCapturedAt] = useState('');
  const source = sources[0], document = source && sourceDocument(source, documents);
  const candidate: FoPhotoInput | undefined = source && document ? { source, caption, captured_at: capturedAt, representation: document.mime_type === 'application/pdf' ? 'photo_on_pdf_page' : 'source_image' } : undefined;
  const valid = candidate && offlineShape('FoPhotoInput', candidate);
  return <section className="field-editor-section"><Title level="H3">Existing photo references</Title><p className="caption">Optional, up to 12. Reference an existing original JPEG or PNG, or identify a photo on a stored PDF page. Captions and times are your observations.</p>
    {photos.map((photo, index) => <div className="field-source-chip field-offline-source" key={index}><div><span>{photo.caption} · {photo.captured_at}</span><p className="caption">{photo.representation === 'source_image' ? 'Original image' : 'Photo on PDF page'} · Page {photo.source.page} · {photo.source.locator}</p><details><summary>Exact reference</summary><code>{photo.source.revision_id}</code><code>{photo.source.source_sha256}</code></details></div><Button design="Transparent" accessibleName={`Remove photo ${index + 1}`} disabled={disabled} onClick={() => onChange(photos.filter((_, i) => i !== index))}>Remove</Button></div>)}
    {photos.length < 12 && <><CachedSourcePicker label="Photo source" documents={documents} sources={sources} maximum={1} photoOnly disabled={disabled} onDirty={onDirty} onChange={next => { onDirty(); setSources(next); }} />{source && <><TextField label="Photo caption" value={caption} maximum={1000} disabled={disabled} onChange={value => { onDirty(); setCaption(value); }} /><TextField label="Photo capture time with UTC offset" value={capturedAt} maximum={40} placeholder="2026-10-17T14:30:00-04:00" disabled={disabled} onChange={value => { onDirty(); setCapturedAt(value); }} /><Button disabled={disabled || !valid} onClick={() => { if (candidate && valid) { onChange([...photos, candidate]); setSources([]); setCaption(''); setCapturedAt(''); } }}>Add photo reference</Button></>}</>}
    <p className="caption">Choose “Add photo reference” to include the selected photo. New camera files and binary uploads cannot be sealed here. Image reading and camera authenticity are not established.</p>
  </section>;
}
