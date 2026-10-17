import { lazy, Suspense, useState } from 'react';
import { Button, Link } from '@ui5/webcomponents-react';
import type { AwSourcePreview } from './api/awards.generated';
import { sourceApi } from './api/sources';
import { Loading } from './components';
const PdfDrawing = lazy(() => import('./PdfDrawing'));

export default function AwardIssuePdf({ source }: { source: AwSourcePreview }) {
  const [open, setOpen] = useState(false); const [page, setPage] = useState(1);
  const output = source.issue.prepared_output; const sources = sourceApi({ type: 'Company', company: source.company });
  return <section aria-label="Original issued award source"><div className="proposal-output-summary"><Button onClick={() => setOpen(value => !value)}>{open ? 'Hide original Issue PDF' : 'Review original Issue PDF'}</Button><Link href={sources.downloadUrl(output.revision_id)} target="_blank">Open exact Issue original</Link><span>Issued revision {source.issue.revision_number} · {output.page_count} pages</span></div>{open && <><Suspense fallback={<Loading label="Reading the original issued PDF…" />}><PdfDrawing company={source.company} revisionId={output.revision_id} sourceSha256={output.source_sha256} downloadUrl={sources.downloadUrl(output.revision_id)} page={page} points={[]} disabled mode="Original issued proposal for award" /></Suspense><div className="page-controls"><Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous Issue source page</Button><span>Page {page} of {output.page_count}</span><Button disabled={page >= output.page_count} onClick={() => setPage(page + 1)}>Next Issue source page</Button></div></>}</section>;
}
