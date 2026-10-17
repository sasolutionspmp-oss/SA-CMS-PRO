export type { Session, Project, Task, CurrentTask, TaskControlResponse, Person, TaskChoices, CreateTaskRequest, CreateTaskResponse, AssignTaskRequest, UpdateTaskStatusRequest, HistoryItem, ApprovalPacket, ApprovalList, ApprovalCommandResponse, ApprovalExecutionResponse } from './contracts.generated';
export interface Collection<T> { items: T[]; total?: number | null; next_cursor?: string | null; limit?: number; count_mode?: string; }
import type { CompanyDocument } from './company-documents.generated';
export interface ProjectDocumentRecord {
  id: string; title: string; company: string; project: string;
  current_revision: string; revision_number: number; filename: string;
  mime_type: string; byte_length: number; sha256: string;
  scan_status: string; extraction_status: string; page_count: number;
}
export type DocumentRecord = ProjectDocumentRecord | CompanyDocument;
export interface DocumentRevision {
  id: string; revision_number: number; filename?: string; mime_type?: string;
  byte_length?: number; sha256?: string; scan_status?: string; extraction_status?: string;
}
export interface Citation {
  document_id: string; revision_id: string; document_title: string;
  revision_number: number; page: number; page_label?: string;
  excerpt: string; excerpt_sha256?: string; source_sha256?: string;
}
export interface DocumentPreview {
  document_id: string; revision_id: string; page: number; page_count: number;
  text: string; content_type: string; citation: Citation;
}
export interface DocumentCollection extends Collection<DocumentRecord> {
  capabilities?: { antivirus: boolean; ocr: boolean; formats: string[] };
}
export interface ModelStatus {
  available: boolean; status: string; code?: string; message?: string; adapter_kind?: string;
  requirements?: string[]; cloud_fallback?: boolean;
  capabilities?: Record<string, unknown>;
}
export interface RickyProposal {
  id: string; run_id: string; status: string; version: string;
  fields: { subject: string; description?: string }; sources: Citation[];
  content_digest: string; expires_at?: string; receipt?: unknown;
}
export interface RickyRun {
  id: string; status: string; question: string; answer?: string | null; citations: Citation[];
  proposal_ids: string[]; cancel_requested: boolean;
  error?: { code?: string; message?: string; retryable?: boolean } | null;
  steps?: { id: string; status: string; label?: string; tool?: string }[];
}

