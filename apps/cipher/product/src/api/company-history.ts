import { ApiError, rpc } from './client';
import type { HistoryItem, HistoryList } from './contracts.generated';

export const COMPANY_HISTORY_LIMIT = 25;
const pageKeys = ['items', 'total', 'limit', 'next_cursor', 'count_mode'];
const itemKeys = ['id', 'event', 'actor', 'at', 'subject_type', 'subject_id', 'details'];
const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const keys = (value: Record<string, unknown>, expected: string[]) => Object.keys(value).length === expected.length && expected.every(key => key in value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const invalid = () => new ApiError('Company activity could not be verified. Refresh to read it again with current access.', 'INVALID_CONTRACT', 200);

// The published DTO has no per-row Company field. Scope belongs to this exact
// request and the server-signed, actor/Company/authority-bound cursor.
export function validateCompanyHistory(value: unknown, cursor?: string): HistoryList {
  if (!object(value) || !keys(value, pageKeys) || value.limit !== COMPANY_HISTORY_LIMIT || value.count_mode !== 'none' || value.total !== null ||
      !Array.isArray(value.items) || value.items.length > COMPANY_HISTORY_LIMIT ||
      !(value.next_cursor === null || text(value.next_cursor)) || (cursor !== undefined && value.next_cursor === cursor)) throw invalid();
  const seen = new Set<string>();
  for (const item of value.items) {
    if (!object(item) || !keys(item, itemKeys) || !text(item.id) || seen.has(item.id) || !text(item.event) || !text(item.actor) ||
        !text(item.subject_type) || !text(item.subject_id) || !text(item.at) ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(item.at) || !Number.isFinite(Date.parse(item.at)) || !object(item.details)) throw invalid();
    seen.add(item.id);
  }
  return value as unknown as HistoryList;
}

export async function readCompanyHistory(company: string, cursor?: string, signal?: AbortSignal): Promise<HistoryList> {
  const result = await rpc<unknown>('cipher_aec.api.company.history', { company, limit: COMPANY_HISTORY_LIMIT, count_mode: 'none', cursor }, false, signal);
  return validateCompanyHistory(result, cursor);
}

const eventLabels: Record<string, string> = {
  'commercial.pursuit.created': 'Pursuit created',
  'commercial.pursuit.revised': 'Pursuit updated',
  'commercial.proposal.revision.created': 'Proposal draft saved',
  'estimate.created': 'Estimate created',
  'estimate.revision.calculated': 'Estimate revision calculated',
  'estimate.accepted': 'Estimate baseline accepted',
  'document.revision.uploaded': 'Document revision uploaded',
  'ricky.company.read.start.accepted': 'Company read requested',
  'ricky.company.read.stop.accepted': 'Company read stop requested',
  'ricky.company.proposal.start.accepted': 'Draft suggestion requested',
  'ricky.company.proposal.stop.accepted': 'Draft suggestion stop requested',
  'ricky.company.proposal.draft-saved': 'Suggestion saved as draft',
};
export function activityLabel(event: string): string {
  return eventLabels[event] ?? event.replace(/[_.-]+/g, ' ').replace(/^\w/, value => value.toUpperCase());
}

// Only routes with a supported Company record view. No speculative revision,
// Run, application or native ERP link is assembled from arbitrary details.
export function activityDestination(item: HistoryItem, company: string): { path: string; label: string } | undefined {
  const id = encodeURIComponent(item.subject_id);
  const query = new URLSearchParams({ company });
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:@ -]{0,159}$/.test(item.subject_id) || ['.', '..'].includes(item.subject_id)) return;
  if (item.subject_type === 'Cipher Estimate') return { path: `/company/estimates/${id}?${query}`, label: 'Open estimate' };
  if (item.subject_type === 'Cipher Document') return { path: `/company/documents/${id}?${query}`, label: 'Open document' };
  // Buttons keep the current Company mounted; these are existing scoped views.
  if (item.subject_type === 'Cipher Pursuit') return { path: `/commercial/pursuits/${id}`, label: 'Open pursuit' };
  if (item.subject_type === 'Cipher Proposal') return { path: `/commercial/proposals/${id}`, label: 'Open proposal' };
}
