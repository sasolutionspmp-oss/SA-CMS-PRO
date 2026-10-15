import { rpc } from './client';
import type { DocumentPreview, DocumentRecord, DocumentRevision, DocumentCollection } from './types';
import type { CompanyDocumentUploadRequest } from './company-documents.generated';
export type SourceScope = { type: 'Company'; company: string } | { type: 'Project'; company: string; project: string };
type UploadResponse = { document: DocumentRecord; revision: DocumentRevision; operation: { id: string; status: string; replayed: boolean } };
export function sourceApi(scope: SourceScope) {
  const prefix = scope.type === 'Company' ? 'cipher_aec.documents.company_api.' : 'cipher_aec.documents.api.';
  return {
    list: (signal?: AbortSignal) => rpc<DocumentCollection>(prefix + 'list_documents', scope.type === 'Company' ? { company: scope.company } : { company: scope.company, project: scope.project }, false, signal),
    document: (document_id: string, signal?: AbortSignal) => rpc<{ document: DocumentRecord; revisions: DocumentRevision[] }>(prefix + 'get_document', { company: scope.company, document_id }, false, signal),
    preview: (revision_id: string, page: number, signal?: AbortSignal) => rpc<DocumentPreview>(prefix + 'preview_revision', { company: scope.company, revision_id, page }, false, signal),
    upload: (input: CompanyDocumentUploadRequest) => rpc<UploadResponse>(prefix + 'upload_document', { ...input, ...(scope.type === 'Project' ? { project: scope.project } : {}) }, true),
    downloadUrl: (revision_id: string) => `/api/method/${prefix}download_revision?${new URLSearchParams({ company: scope.company, revision_id })}`,
  };
}
