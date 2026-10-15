import { lazy, Suspense, useState } from 'react';
import { Button, Link, Title } from '@ui5/webcomponents-react';
import type { CompanyApprovalPacket } from './api/contracts.generated';
import type { ComPreparedOutput } from './api/commercial.generated';
import { sourceApi } from './api/sources';
import { ApiError } from './api/client';
import { Failure, Loading } from './components';
const PdfDrawing = lazy(() => import('./PdfDrawing'));
const checksum = /^[a-f0-9]{64}$/;
export function issuePrepared(packet: CompanyApprovalPacket): ComPreparedOutput | undefined {
  if (packet.action !== 'proposal.issue.v1') return;
  const effect = packet.review_manifest?.effect; if (!effect || typeof effect !== 'object') return; const value = effect.prepared_output;
  if (!value || typeof value !== 'object') return;
  const output = value as ComPreparedOutput; const binding = output.binding;
  if (effect.action !== packet.action || effect.revision_id !== packet.subject.id || output.company !== packet.company || output.proposal_revision_id !== packet.subject.id || output.proposal_revision_digest !== effect.proposal_revision_digest || !checksum.test(output.source_sha256) || !checksum.test(output.review_version) || output.review_version !== packet.source_version || !/^REV-[a-f0-9]{32}$/.test(output.revision_id) || !/^DOC-[a-f0-9]{32}$/.test(output.document_id) || !Number.isInteger(output.byte_length) || output.byte_length < 1 || output.byte_length > 10485760 || !Number.isInteger(output.page_count) || output.page_count < 1 || output.page_count > 100 || binding?.company !== packet.company || binding.proposal_id !== output.proposal_id || binding.proposal_revision_id !== packet.subject.id || binding.proposal_revision_digest !== effect.proposal_revision_digest || typeof binding.cover !== 'string' || !Array.isArray(binding.recipients) || binding.recipients.length < 1 || binding.recipients.length > 30 || binding.recipients.some(row => !row || typeof row !== 'object' || typeof row.name !== 'string' || typeof row.email !== 'string' || typeof row.organization !== 'string') || output.rendering?.output_sha256 !== output.source_sha256 || output.rendering.output_byte_length !== output.byte_length) return;
  return output;
}
export default function IssuePreparedReview({ packet, output }: { packet: CompanyApprovalPacket; output?: ComPreparedOutput }) {
  const [show, setShow] = useState(false); const [page, setPage] = useState(1);
  if (!output) return <Failure error={new ApiError('This approval does not contain a verified prepared-PDF source. The action cannot be reviewed here.', 'INVALID_CONTRACT', 200)} />;
  const sources = sourceApi({ type: 'Company', company: packet.company });
  return <section className="issue-prepared-review" aria-label="Exact issue PDF review"><Title level="H4">Prepared PDF in this approval</Title><p className="caption">This is the exact stored PDF and intended recipient set bound to this review. Later distribution is managed separately.</p><div className="proposal-output-summary"><Button onClick={() => setShow(value => !value)}>{show ? 'Hide exact prepared PDF' : 'Review exact prepared PDF'}</Button><Link href={sources.downloadUrl(output.revision_id)} target="_blank">Open exact stored original</Link><span>{output.page_count} pages · {output.byte_length.toLocaleString('en-US')} bytes</span></div>
    {show && <div className="proposal-output-pdf"><Suspense fallback={<Loading label="Opening the manifest-bound prepared PDF…" />}><PdfDrawing key={`${packet.id}/${output.revision_id}`} company={packet.company} revisionId={output.revision_id} sourceSha256={output.source_sha256} downloadUrl={sources.downloadUrl(output.revision_id)} page={page} points={[]} disabled mode="Exact issue review PDF" /></Suspense><div className="page-controls"><Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous approval PDF page</Button><span>Page {page} of {output.page_count}</span><Button disabled={page >= output.page_count} onClick={() => setPage(page + 1)}>Next approval PDF page</Button></div></div>}
    <Title level="H4">Intended recipients at issue review</Title><ul>{output.binding.recipients.map(row => <li key={row.email}>{row.name} · {row.email}{row.organization ? ` · ${row.organization}` : ''}</li>)}</ul><Title level="H4">Cover text in this review</Title><p className="authored-text">{output.binding.cover || 'No cover text.'}</p><details><summary>Prepared source identity</summary><p>Document {output.document_id}</p><p>Exact revision {output.revision_id}</p><p>SHA-256</p><code>{output.source_sha256}</code><p>Proposal revision {output.proposal_revision_id}</p><code>{output.proposal_revision_digest}</code></details>
  </section>;
}
