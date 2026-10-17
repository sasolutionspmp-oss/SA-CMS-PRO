import { lazy, Suspense, useEffect, useState } from 'react';
import { Button, Input, Label, MessageStrip, Option, Select, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { sourceApi } from './api/sources';
import { fieldSourceInput } from './api/field';
import type { Scope } from './api/engineering';
import type * as F from './api/field.generated';
import type { ProjectDocumentRecord } from './api/types';
import { Failure, Loading } from './components';
import { useResource } from './hooks';
const PdfDrawing = lazy(() => import('./PdfDrawing'));
const denied = (error?: ApiError) => Boolean(error && [401, 403, 404].includes(error.status));
export function FieldSourcePreview({ scope, source, onDenied }: { scope: Scope; source: F.FdCapturedSource; onDenied: () => void }) {
  const [open, setOpen] = useState(false);
  const original = useResource(open && source.mime_type !== 'application/pdf' ? `${scope.company}/${scope.project}/${source.revision_id}/${source.source_sha256}/field-source` : null, async signal => {
    const response = await fetch(sourceApi({ type: 'Project', ...scope }).downloadUrl(source.revision_id), { credentials: 'same-origin', signal });
    if (!response.ok) throw new ApiError('The original photo is unavailable under your current access.', 'source_unavailable', response.status);
    const bytes = await response.arrayBuffer(), hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (hash !== source.source_sha256 || bytes.byteLength !== source.byte_length || response.headers.get('content-type')?.split(';')[0].trim() !== source.mime_type) throw new ApiError('The original photo bytes did not match this saved source revision.', 'INVALID_CONTRACT', 200);
    const blob = new Blob([bytes], { type: source.mime_type }); return { blob, text: source.mime_type === 'text/plain' ? await blob.text() : undefined };
  });
  const [url, setUrl] = useState('');
  useEffect(() => { if (!original.data) { setUrl(''); return; } const next = URL.createObjectURL(original.data.blob); setUrl(next); return () => URL.revokeObjectURL(next); }, [original.data]);
  useEffect(() => { if (denied(original.error)) onDenied(); }, [original.error, onDenied]);
  const isImage = ['image/jpeg', 'image/png'].includes(source.mime_type), isPdf = source.mime_type === 'application/pdf';
  return <div className="field-source-fact"><span>Revision {source.revision_number} · Page {source.page} · {source.locator}</span><code>{source.revision_id}</code>
    <Button design="Transparent" onClick={() => setOpen(!open)}>{open ? 'Hide source' : isImage ? 'View original photo' : isPdf ? 'View stored PDF page' : 'View original source'}</Button>
    {open && !isPdf && (original.loading ? <Loading label="Checking original source bytes…" /> : original.error ? <Failure error={original.error} onRetry={original.refresh} /> : url && (isImage ? <img className="field-photo" src={url} alt={`Original source: ${source.locator}`} /> : original.data?.text !== undefined ? <pre className="source-text">{original.data.text}</pre> : <a href={url} download={`source-${source.revision_id}`}>Download verified original</a>))}
    {open && isPdf && <Suspense fallback={<Loading />}><PdfDrawing company={scope.company} revisionId={source.revision_id} sourceSha256={source.source_sha256} page={source.page} points={[]} mode="Field source review" disabled onAccessDenied={onDenied} /></Suspense>}
    <details><summary>Source details</summary><p>{source.mime_type} · {source.byte_length} bytes · {source.page_count} pages</p><code>{source.source_sha256}</code></details>
  </div>;
}
export function FieldSourcePicker({ scope, label, sources, onChange, disabled, onDenied, photoOnly = false, maximum = 8, onSelected }: { scope: Scope; label: string; sources: F.FdSourceInput[]; onChange: (sources: F.FdSourceInput[]) => void; disabled: boolean; onDenied: () => void; photoOnly?: boolean; maximum?: number; onSelected?: (source: F.FdCapturedSource) => void }) {
  const api = sourceApi({ type: 'Project', ...scope });
  const documents = useResource(`${scope.company}/${scope.project}/field-sources`, async signal => {
    const value = await api.list(signal);
    if (!Array.isArray(value.items) || value.items.some(row => row.company !== scope.company || !('project' in row) || row.project !== scope.project || !row.current_revision || !/^[a-f0-9]{64}$/.test(row.sha256) || !Number.isSafeInteger(row.page_count) || row.page_count < 1 || row.page_count > 200 || !Number.isSafeInteger(row.byte_length) || row.byte_length < 1)) throw new ApiError('Project sources could not be verified.', 'INVALID_CONTRACT', 200);
    return value.items as ProjectDocumentRecord[];
  });
  const [documentId, setDocumentId] = useState(''), [page, setPage] = useState('1'), [locator, setLocator] = useState('');
  const document = documents.data?.find(row => row.id === documentId), pageNumber = Number(page);
  const validPage = Boolean(document && Number.isSafeInteger(pageNumber) && pageNumber >= 1 && pageNumber <= document.page_count && (!['image/jpeg', 'image/png'].includes(document.mime_type) || pageNumber === 1));
  const selected = document && validPage ? { revision_id: document.current_revision, source_sha256: document.sha256, page: pageNumber, locator, document_id: document.id, revision_number: document.revision_number, byte_length: document.byte_length, mime_type: document.mime_type, page_count: document.page_count } : undefined;
  useEffect(() => { if (denied(documents.error)) onDenied(); }, [documents.error, onDenied]);
  return <section className="field-source-picker" aria-label={label}><div className="field-panel-heading"><Label>{label}</Label><Button design="Transparent" disabled={disabled} onClick={documents.refresh}>Refresh {label.toLowerCase()}</Button></div>
    {sources.map((source, index) => <div className="field-source-chip" key={`${source.revision_id}/${source.page}/${source.locator}`}><span>{documents.data?.find(row => row.current_revision === source.revision_id)?.title || 'Retained source revision'} · Page {source.page} · {source.locator}</span><Button design="Transparent" icon="decline" accessibleName={`Remove ${label} ${index + 1}`} disabled={disabled} onClick={() => onChange(sources.filter((_, i) => i !== index))} /></div>)}
    {documents.loading ? <Loading label="Loading project sources…" /> : documents.error ? <Failure error={documents.error} onRetry={documents.refresh} /> : <Select accessibleName={label} disabled={disabled || sources.length >= maximum} onChange={event => { setDocumentId(event.detail.selectedOption.value || ''); setPage('1'); setLocator(''); }}><Option value="" selected={!documentId}>Choose a stored source</Option>{documents.data?.filter(row => !photoOnly || ['image/jpeg', 'image/png', 'application/pdf'].includes(row.mime_type)).map(row => <Option key={row.id} value={row.id} selected={documentId === row.id}>{row.title} · Rev. {row.revision_number}</Option>)}</Select>}
    {!documents.loading && !documents.error && !documents.data?.length && <MessageStrip hideCloseButton>Upload original sources in Project Documents first.</MessageStrip>}
    {document && <><div className="field-form-grid"><div><Label>Page</Label><Input accessibleName={`${label} page`} value={page} disabled={disabled || ['image/jpeg', 'image/png'].includes(document.mime_type)} onInput={event => setPage(event.currentTarget!.value)} /></div><div><Label required>Location in source</Label><Input accessibleName={`${label} locator`} value={locator} maxlength={1000} disabled={disabled} placeholder="For example: east wall, delivery note line 2" onInput={event => setLocator(event.currentTarget!.value)} /></div></div>
      {photoOnly && <p className="caption">{document.mime_type === 'application/pdf' ? 'This is a photo identified on a PDF page.' : 'This retains the original JPEG or PNG bytes on page 1.'}</p>}
      <Button disabled={disabled || !selected || !locator.trim() || sources.length >= maximum || sources.some(row => row.revision_id === selected?.revision_id && row.page === selected.page && row.locator === locator)} onClick={() => { if (selected) { onChange([...sources, fieldSourceInput(selected)]); onSelected?.(selected); setDocumentId(''); } }}>Attach {label.toLowerCase()}</Button>
    </>}
    <p className="caption">Exact stored revisions are retained. Current source access and content permission are checked by the server.</p>
  </section>;
}
export function FieldPhotoEditor({ scope, photos, onChange, disabled, onDenied }: { scope: Scope; photos: F.FdPhotoInput[]; onChange: (photos: F.FdPhotoInput[]) => void; disabled: boolean; onDenied: () => void }) {
  const [source, setSource] = useState<F.FdCapturedSource>(), [caption, setCaption] = useState(''), [capturedAt, setCapturedAt] = useState('');
  return <section className="field-editor-section"><Title level="H3">Photos</Title><p className="caption">Captions and capture times are your observations. No image reading or camera-authenticity claim is made.</p>
    {photos.map((photo, index) => <div className="field-source-chip" key={index}><span>{photo.caption} · {photo.captured_at} · {photo.representation === 'source_image' ? 'Original image' : 'Photo on PDF page'}</span><Button icon="decline" design="Transparent" accessibleName={`Remove photo ${index + 1}`} disabled={disabled} onClick={() => onChange(photos.filter((_, i) => i !== index))} /></div>)}
    {photos.length < 12 && <><FieldSourcePicker scope={scope} label="Photo source" sources={source ? [fieldSourceInput(source)] : []} onChange={rows => { if (!rows.length) setSource(undefined); }} onSelected={setSource} disabled={disabled} photoOnly maximum={1} onDenied={onDenied} />
      {source && <><Label required>Caption</Label><Input accessibleName="Photo caption" maxlength={1000} value={caption} disabled={disabled} onInput={event => setCaption(event.currentTarget!.value)} /><Label required>Capture time with UTC offset</Label><Input accessibleName="Photo capture time" value={capturedAt} maxlength={40} placeholder="2026-10-17T14:30:00-04:00" disabled={disabled} onInput={event => setCapturedAt(event.currentTarget!.value)} /><Button disabled={disabled || !caption.trim() || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(capturedAt) || !Number.isFinite(Date.parse(capturedAt))} onClick={() => { onChange([...photos, { source: fieldSourceInput(source), caption, captured_at: capturedAt, representation: source.mime_type === 'application/pdf' ? 'photo_on_pdf_page' : 'source_image' }]); setSource(undefined); setCaption(''); setCapturedAt(''); }}>Add photo</Button></>}
    </>}
  </section>;
}
