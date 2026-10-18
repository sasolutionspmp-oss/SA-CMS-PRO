import { useState } from 'react';
import { Table, TableHeaderRow, TableHeaderCell, TableRow, TableCell, Breadcrumbs, BreadcrumbsItem, Button, Link, MessageStrip, Title, Toolbar, ToolbarSpacer } from '@ui5/webcomponents-react';
import { api, ApiError } from './api/client';
import type { DocumentRecord } from './api/types';
import { useResource } from './hooks';
import { Empty, Fact, Failure, Loading, PageHeading, Status } from './components';
import SourceUpload from './SourceUpload';

export function DocumentRegister({ items, navigate, accessibleName = 'Project documents' }: { items: DocumentRecord[]; navigate: (path: string) => void; accessibleName?: string }) {
  return items.length ? <Table accessibleName={accessibleName} overflowMode="Scroll" headerRow={<TableHeaderRow>
    <TableHeaderCell minWidth="17rem">Document</TableHeaderCell><TableHeaderCell width="6.25rem">Revision</TableHeaderCell><TableHeaderCell width="10rem">Text status</TableHeaderCell><TableHeaderCell width="8.125rem">File</TableHeaderCell>
  </TableHeaderRow>}>
    {items.map(item => <TableRow key={item.id} rowKey={item.id}>
      <TableCell><div className="record-cell"><Link onClick={() => navigate(`/documents/${encodeURIComponent(item.id)}`)}>{item.title}</Link><span>{item.filename}</span></div></TableCell>
      <TableCell>Rev. {item.revision_number}</TableCell><TableCell><Status value={item.extraction_status} /></TableCell><TableCell>{format(item.mime_type)} · {size(item.byte_length)}</TableCell>
    </TableRow>)}
  </Table>
    : <Empty title="No source documents yet" icon="documents">Add a project document to keep the source connected to your work.</Empty>;
}

export function DocumentsPage({ company, projectId, projectName, navigate, canUpload, canControl = false }: { company: string; projectId?: string; projectName?: string; navigate: (path: string) => void; canUpload: boolean; canControl?: boolean }) {
  const documents = useResource(projectId ? `${company}/${projectId}/documents` : null, signal => api.documents(company, projectId!, signal));
  const [uploadOpen, setUploadOpen] = useState(false);
  const [notice, setNotice] = useState('');
  return <div className="page">
    <PageHeading eyebrow="PROJECT SOURCES" title="Documents" description={projectName ? `${projectName} · Documents and versions.` : 'Choose a project to work with its documents.'} actions={projectId ? <><Button icon="refresh" onClick={documents.refresh}>Refresh</Button>{canControl && <Button onClick={() => navigate(`/projects/${encodeURIComponent(projectId)}/document-control`)}>Open document control</Button>}{canUpload && <Button icon="upload" design="Emphasized" onClick={() => setUploadOpen(true)}>Add document</Button>}</> : undefined} />
    {!projectId ? <div className="surface"><Empty title="Choose a project" icon="folder" action={<Button design="Emphasized" onClick={() => navigate('/projects')}>Open projects</Button>}>Open a project to see its documents.</Empty></div> : <>
      {notice && <MessageStrip design="Positive" onClose={() => setNotice('')}>{notice}</MessageStrip>}
      <section className="surface"><Toolbar design="Transparent"><Title level="H2">Document register</Title><ToolbarSpacer /><span className="caption">{documents.data?.items.length ?? '—'} documents · PDF, plain text, JPEG and PNG</span></Toolbar>
        {documents.loading ? <Loading label="Loading project documents…" /> : documents.error ? <Failure error={documents.error} onRetry={documents.refresh} /> : <DocumentRegister items={documents.data?.items ?? []} navigate={navigate} />}
      </section>

      <>{uploadOpen && <SourceUpload scope={{ type: 'Project', company, project: projectId }} onClose={() => setUploadOpen(false)} onSaved={document => { setUploadOpen(false); setNotice(`“${document.title}” was added.`); documents.refresh(); }} />}</>
    </>}
  </div>;
}

export function DocumentPage({ company, documentId, revisionId, initialPage = 1, navigate, askRicky }: { company: string; documentId: string; revisionId?: string; initialPage?: number; navigate: (path: string) => void; askRicky: (projectId: string) => void }) {
  const record = useResource(`${company}/${documentId}`, signal => api.document(company, documentId, signal));
  const [page, setPage] = useState(initialPage);
  const [revisionUpload, setRevisionUpload] = useState(false);
  const sourceProjectId = record.data?.document.project;
  const sourceProject = useResource(sourceProjectId ? `${company}/document-owner/${sourceProjectId}` : null, signal => api.project(company, sourceProjectId!, signal));
  const revisionBelongsToDocument = !revisionId || record.data?.revisions.some(revision => revision.id === revisionId);
  const currentRevision = revisionBelongsToDocument ? (revisionId ?? record.data?.document.current_revision) : undefined;
  const selectedRevision = record.data?.revisions.find(item => item.id === currentRevision);
  const selectedMime = selectedRevision?.mime_type ?? record.data?.document.mime_type;
  const isImage = selectedMime === 'image/jpeg' || selectedMime === 'image/png';
  const preview = useResource(currentRevision && !isImage ? `${company}/${currentRevision}/${page}` : null, signal => api.preview(company, currentRevision!, page, signal));
  if (record.loading) return <Loading label="Opening source document…" />;
  if (record.error) return <div className="page"><Failure error={record.error} onRetry={record.refresh} /></div>;
  if (!record.data) return null;
  const document = record.data.document;
  if (document.project === null) return <div className="page"><Failure error={new ApiError('This source is unavailable in Project scope.', 'SOURCE_SCOPE_UNAVAILABLE', 404)} /></div>;
  if (revisionId && !revisionBelongsToDocument) return <div className="page"><Failure error={new ApiError('This revision is not available for this document.', 'REVISION_UNAVAILABLE', 404)} /><Button onClick={() => navigate(`/documents/${encodeURIComponent(document.id)}`)}>Open current revision</Button></div>;
  const revision = selectedRevision;
  return <div className="page document-page">
    <Breadcrumbs><BreadcrumbsItem onClick={() => navigate('/projects')}>Projects</BreadcrumbsItem><BreadcrumbsItem onClick={() => navigate(`/projects/${encodeURIComponent(document.project)}/documents`)}>Documents</BreadcrumbsItem><BreadcrumbsItem>{document.title}</BreadcrumbsItem></Breadcrumbs>
    <PageHeading eyebrow="SOURCE DOCUMENT" title={document.title} description={revision?.filename ?? document.filename} actions={<><Button icon="da" onClick={() => { if (document.project) askRicky(document.project); }}>Ask Ricky</Button><Button icon="download" onClick={() => window.open(api.downloadUrl(company, currentRevision!), '_blank', 'noopener,noreferrer')}>Open original</Button>{sourceProject.data?.capabilities?.includes('document.write') && <Button onClick={() => setRevisionUpload(true)}>Add working revision</Button>}</>} />
    <section className="summary-strip document-facts"><Fact label="Revision">Rev. {revision?.revision_number ?? document.revision_number}</Fact><Fact label="Format">{format(selectedMime ?? document.mime_type)}</Fact><Fact label="File size">{size(revision?.byte_length ?? document.byte_length)}</Fact><Fact label="Text status"><Status value={revision?.extraction_status ?? document.extraction_status} /></Fact></section>
    <div className="document-reader-grid"><section className="surface source-reader" aria-label="Document source preview"><Toolbar design="Transparent"><Title level="H2">{isImage ? 'Source image' : 'Source text'}</Title><ToolbarSpacer />{preview.data && <span className="caption">Page {page} of {preview.data.page_count}</span>}</Toolbar>
      {isImage ? <Empty title="Original image only">Open the original {format(selectedMime!)} image to review it. Text preview is unavailable.</Empty> : preview.loading ? <Loading label="Loading source text…" /> : preview.error ? <div className="reader-body"><Failure error={preview.error} onRetry={preview.refresh} /></div> : preview.data ? <><div className="reader-body"><div className="source-page-heading">{document.title}<span>Revision {revision?.revision_number ?? document.revision_number} · Page {page}</span></div><pre className="source-text">{preview.data.text}</pre></div>{preview.data.page_count > 1 && <div className="page-controls"><Button icon="navigation-left-arrow" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button><span>Page {page} of {preview.data.page_count}</span><Button icon="navigation-right-arrow" disabled={page >= preview.data.page_count} onClick={() => setPage(page + 1)}>Next</Button></div>}</> : <Empty title="Preview is not available">Open the stored original to review this document.</Empty>}
    </section><aside className="surface source-details"><Title level="H3">Source details</Title><dl><dt>Project</dt><dd><Link onClick={() => navigate(`/projects/${encodeURIComponent(document.project)}`)}>{sourceProject.data?.name || 'Open project'}</Link></dd><dt>Scan status</dt><dd><Status value={revision?.scan_status ?? document.scan_status} /></dd><dt>Available revisions</dt><dd>{record.data.revisions.length}</dd></dl></aside></div>
    {revisionUpload && document.project && <SourceUpload scope={{ type: 'Project', company, project: document.project }} existing={document} onClose={() => setRevisionUpload(false)} onSaved={() => { setRevisionUpload(false); record.refresh(); }} />}
  </div>;
}

function size(bytes: number) { return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : bytes >= 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${bytes} bytes`; }
function format(mime: string) { const labels: Record<string, string> = { 'application/pdf': 'PDF', 'text/plain': 'Plain text', 'image/jpeg': 'JPEG image', 'image/png': 'PNG image' }; return labels[mime] ?? mime; }
