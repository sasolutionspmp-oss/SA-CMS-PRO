import { useEffect, useRef, useState } from 'react';
import { Toolbar, ToolbarButton, ToolbarSelect, ToolbarSelectOption, ToolbarSpacer } from '@ui5/webcomponents-react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy, type PageViewport } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { api, ApiError } from './api/client';
import { Failure, Loading } from './components';
import type { TakeoffPageGeometry } from './api/takeoff.generated';

GlobalWorkerOptions.workerSrc = workerUrl;
export type PdfPoint = [string, string];
export interface PdfFrame { view: number[]; rotation: number; userUnit: number; pageCount: number; sourceSha256: string }
const coordinate = (value: number) => { const text = value.toFixed(6).replace(/\.?0+$/, ''); return !text || text === '-0' ? '0' : text; };
export function pickedPdfPoint(viewport: Pick<PageViewport, 'convertToPdfPoint' | 'width' | 'height'>, rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>, clientX: number, clientY: number): PdfPoint {
  const [x, y] = viewport.convertToPdfPoint((clientX - rect.left) * viewport.width / rect.width, (clientY - rect.top) * viewport.height / rect.height);
  return [coordinate(x), coordinate(y)];
}

export default function PdfDrawing({ company, revisionId, sourceSha256, page, points, onPoint, disabled = false, geometry, geometryType = 'polyline', mode, onFrame, downloadUrl, onAccessDenied }: { company: string; revisionId: string; sourceSha256: string; page: number; points: PdfPoint[]; onPoint?: (point: PdfPoint) => void; disabled?: boolean; geometry?: TakeoffPageGeometry; geometryType?: 'segment' | 'polyline' | 'rectangle' | 'polygon'; mode: string; onFrame?: (frame: PdfFrame) => void; downloadUrl?: string; onAccessDenied?: () => void }) {
  const deniedCallback = useRef(onAccessDenied); deniedCallback.current = onAccessDenied;
  const canvas = useRef<HTMLCanvasElement>(null); const [pdf, setPdf] = useState<PDFDocumentProxy>();
  const sourceUrl = downloadUrl || api.downloadUrl(company, revisionId);
  const sourceKey = `${sourceUrl}/${sourceSha256}`;
  const [zoom, setZoom] = useState(1); const [rotation, setRotation] = useState(0); const [viewport, setViewport] = useState<PageViewport>();
  const renderKey = `${sourceKey}/${page}/${zoom}/${rotation}`;
  const [pdfSource, setPdfSource] = useState(''); const [readyKey, setReadyKey] = useState('');
  const [loading, setLoading] = useState(true); const [rendering, setRendering] = useState(false); const [error, setError] = useState<ApiError>();
  const [reload, setReload] = useState(0); const frameCallback = useRef(onFrame); frameCallback.current = onFrame;
  useEffect(() => {
    const controller = new AbortController(); let loadingTask: ReturnType<typeof getDocument> | undefined; let disposed = false;
    setLoading(true); setError(undefined); setPdf(undefined); setViewport(undefined);
    (async () => {
      const response = await fetch(sourceUrl, { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new ApiError('The stored PDF is unavailable with your current access.', `HTTP_${response.status}`, response.status);
      const buffer = await response.arrayBuffer();
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(value => value.toString(16).padStart(2, '0')).join('');
      if (hash !== sourceSha256) throw new ApiError('The PDF bytes do not match this source revision. Reload the document before measuring.', 'SOURCE_HASH_MISMATCH', 412);
      if (disposed) return;
      loadingTask = getDocument({ data: new Uint8Array(buffer), cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/', iccUrl: '/pdfjs/iccs/', enableXfa: false, stopAtErrors: true });
      const document = await loadingTask.promise;
      if (disposed) return;
      setPdf(document); setPdfSource(sourceKey); setLoading(false);
    })().catch(failure => { if (!disposed) { setError(failure instanceof ApiError ? failure : new ApiError('This PDF could not be rendered. Open the original or choose a supported PDF.', 'PDF_RENDER_UNAVAILABLE', 422)); setLoading(false); } });
    return () => { disposed = true; controller.abort(); void loadingTask?.destroy().catch(() => {}); };
  }, [sourceKey, sourceUrl, sourceSha256, reload]);
  useEffect(() => {
    if (!pdf || pdfSource !== sourceKey) return;
    let disposed = false; let task: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined;
    setRendering(true); setViewport(undefined); setError(undefined);
    (async () => {
      const sheet = await pdf.getPage(page);
      if (disposed) return;
      if (sheet.userUnit !== 1 || (geometry && (sheet.rotate !== geometry.rotate || sheet.view.some((value, index) => value !== Number(geometry.crop_box[index]))))) throw new ApiError('The PDF page frame does not match the qualified source geometry.', 'PDF_FRAME_MISMATCH', 422);
      const frame = sheet.getViewport({ scale: zoom, rotation: (sheet.rotate + rotation) % 360 });
      if (!canvas.current) return;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.current.width = Math.ceil(frame.width * ratio); canvas.current.height = Math.ceil(frame.height * ratio);
      canvas.current.style.width = `${frame.width}px`; canvas.current.style.height = `${frame.height}px`;
      task = sheet.render({ canvas: canvas.current, viewport: frame, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
      await task.promise;
      if (!disposed) { setViewport(frame); setReadyKey(renderKey); setRendering(false); frameCallback.current?.({ view: sheet.view, rotation: sheet.rotate, userUnit: sheet.userUnit, pageCount: pdf.numPages, sourceSha256 }); }
    })().catch(failure => { if (!disposed) { setError(failure instanceof ApiError ? failure : new ApiError('This PDF page could not be rendered.', 'PDF_PAGE_UNAVAILABLE', 422)); setRendering(false); } });
    return () => { disposed = true; task?.cancel(); };
  }, [pdf, pdfSource, sourceKey, renderKey, page, zoom, rotation, geometry, sourceSha256]);
  useEffect(() => { if (error && [401, 403, 404].includes(error.status)) deniedCallback.current?.(); }, [error]);
  const plotted = viewport ? points.map(point => viewport.convertToViewportPoint(Number(point[0]), Number(point[1]))) : [];
  const outline = geometryType === 'rectangle' && points.length === 2 && viewport ? [points[0], [points[1][0], points[0][1]], points[1], [points[0][0], points[1][1]]].map(point => viewport.convertToViewportPoint(Number(point[0]), Number(point[1]))) : plotted;
  return <section className="pdf-drawing" aria-label="Stored PDF drawing">
    <Toolbar design="Transparent" accessibleName="Stored PDF view controls" alignContent="Start"><ToolbarSelect accessibleName="Drawing zoom" width="6rem" overflowPriority="NeverOverflow" disabled={loading} onChange={event => setZoom(Number(event.detail.selectedOption.value))}>{[0.5, 0.75, 1, 1.5, 2].map(value => <ToolbarSelectOption key={value} value={String(value)} selected={zoom === value}>{value * 100}%</ToolbarSelectOption>)}</ToolbarSelect><ToolbarButton text="Rotate view" icon="refresh" overflowPriority="NeverOverflow" disabled={loading || rendering} onClick={() => setRotation(value => (value + 90) % 360)} /><ToolbarSpacer /></Toolbar><p className="caption">Page {page}{pdf ? ` of ${pdf.numPages}` : ''} · {mode}</p>
    {error && <Failure error={error} onRetry={() => setReload(value => value + 1)} />}
    {loading && <Loading label="Checking stored PDF bytes and rendering drawing…" />}
    <div className="drawing-scroll"><div className="drawing-sheet" hidden={!viewport || readyKey !== renderKey || pdfSource !== sourceKey || loading || rendering || Boolean(error)} style={viewport ? { width: viewport.width, height: viewport.height } : undefined}>
      <canvas ref={canvas} aria-label="Authorized stored PDF page" />
      {viewport && !error && <svg aria-label="Drawing point selection" role="img" className="drawing-overlay" width={viewport.width} height={viewport.height} viewBox={`0 0 ${viewport.width} ${viewport.height}`} onClick={event => { if (onPoint && !disabled && !rendering) onPoint(pickedPdfPoint(viewport, event.currentTarget.getBoundingClientRect(), event.clientX, event.clientY)); }}>
        {outline.length > 1 && (geometryType === 'polygon' || geometryType === 'rectangle' ? <polygon points={outline.map(point => point.join(',')).join(' ')} fill="var(--sapSelectedColor)" fillOpacity=".12" stroke="var(--sapSelectedColor)" strokeWidth="2" /> : <polyline points={outline.map(point => point.join(',')).join(' ')} fill="none" stroke="var(--sapSelectedColor)" strokeWidth="2" />)}
        {plotted.map(([x, y], index) => <g key={index}><circle cx={x} cy={y} r="5" fill="var(--sapSelectedColor)" stroke="white" strokeWidth="2" /><text x={x + 9} y={y - 9} fontSize="13" fill="var(--sapTextColor)">{index + 1}</text></g>)}
      </svg>}
    </div></div>
    {rendering && !loading && <Loading label="Rendering PDF view…" />}
    <p className="caption drawing-caption">{onPoint ? "The view uses the stored PDF bytes. Point picks map through the inverse page viewport, including crop, rotation and zoom, into unrotated PDF user coordinates. Picked coordinates round to six decimals; exact coordinates remain editable." : "This view renders the exact stored PDF revision. Zoom or rotate the view without changing the original."}</p>
  </section>;
}
