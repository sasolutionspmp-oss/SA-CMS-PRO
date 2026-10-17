/* Generated from cipher_aec/documents/schemas/company-api-v1.schema.json. Do not edit.
 * Source SHA-256: 96dd9104833ff4b734a03fed59b47b0f602c262881b39c59029f72ad3b3c3068
 * Regenerate: npm run generate:api
 */

/**
 * Exact Company ownership on the existing canonical Document/Revision/File authority. Existing Project API contracts are unchanged.
 */
export interface UrnCipherCompanyDocumentsApiV1 {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocument".
 */
export interface CompanyDocument {
  id: string;
  revision_number: number;
  filename: string;
  mime_type: string;
  byte_length: number;
  sha256: string;
  scan_status: string;
  retrieval_status: string;
  extraction_status: string;
  extractor_version: string;
  page_count: number;
  extraction_warning: string | null;
  title: string;
  company: string;
  project: null;
  current_revision: string;
  scope_type: "Company";
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentRevision".
 */
export interface CompanyDocumentRevision {
  id: string;
  revision_number: number;
  filename: string;
  mime_type: string;
  byte_length: number;
  sha256: string;
  scan_status: string;
  retrieval_status: string;
  extraction_status: string;
  extractor_version: string;
  page_count: number;
  extraction_warning: string | null;
  scope_type: "Company";
  company: string;
  project: null;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentDetail".
 */
export interface CompanyDocumentDetail {
  document: CompanyDocument;
  revisions: CompanyDocumentRevision[];
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentList".
 */
export interface CompanyDocumentList {
  items: CompanyDocument[];
  capabilities: {
    antivirus: boolean;
    ocr: boolean;
    formats: string[];
    semantic_search: boolean;
    storage: string;
  };
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentPreview".
 */
export interface CompanyDocumentPreview {
  document_id: string;
  revision_id: string;
  page: number;
  page_count: number;
  text: string;
  content_type: string;
  citation: CompanyCitation;
  scope_type: "Company";
  company: string;
  project: null;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyCitation".
 */
export interface CompanyCitation {
  id: string;
  document_id: string;
  revision_id: string;
  document_title: string;
  page_label: string;
  excerpt: string;
  excerpt_sha256: string;
  source_sha256: string;
  company: string;
  revision_number: number;
  page: number;
  scope_type: "Company";
  project: null;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyCitationList".
 */
export interface CompanyCitationList {
  items: CompanyCitation[];
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentUploadResponse".
 */
export interface CompanyDocumentUploadResponse {
  document: CompanyDocument;
  revision: CompanyDocumentRevision;
  operation: CompanySourceOperation;
  history_id: string;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanySourceOperation".
 */
export interface CompanySourceOperation {
  id: string;
  status: "succeeded";
  replayed: boolean;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentUploadRequest".
 */
export interface CompanyDocumentUploadRequest {
  company: string;
  title: string;
  filename: string;
  content_base64: string;
  sha256: string;
  byte_length: number;
  operation_id?: string;
  document_id?: string | null;
  expected_revision?: number | null;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentListRequest".
 */
export interface CompanyDocumentListRequest {
  company: string;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentDetailRequest".
 */
export interface CompanyDocumentDetailRequest {
  company: string;
  document_id: string;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentPreviewRequest".
 */
export interface CompanyDocumentPreviewRequest {
  company: string;
  revision_id: string;
  page?: number;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyCitationRequest".
 */
export interface CompanyCitationRequest {
  company: string;
  revision_id: string;
  page: number;
  excerpt_sha256?: string | null;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentSearchRequest".
 */
export interface CompanyDocumentSearchRequest {
  company: string;
  query: string;
  limit?: number;
}
/**
 * This interface was referenced by `UrnCipherCompanyDocumentsApiV1`'s JSON-Schema
 * via the `definition` "CompanyDocumentDownloadRequest".
 */
export interface CompanyDocumentDownloadRequest {
  company: string;
  revision_id: string;
}
