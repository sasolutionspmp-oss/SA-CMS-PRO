import { ApiError } from './client';
import { documentControl, type DocumentBasis, type DocumentCommand } from './document-control';
import type * as D from './document-control.generated';
import { quality, privateUploadAllowed, qualityShape, type Command as QualityCommand, type Reply as QualityReply } from './quality-safety';
import type * as Q from './quality-safety.generated';
import type { Actor, Scope } from './engineering';
import { sourceApi } from './sources';

export type PendingPrivateSource = { upload: Q.QsUploadEvidenceResponse; locator: string };
export type IncidentRightsCommand = { kind: 'set_incident_source_rights'; payload: Omit<D.DcSetRightsRequest, 'operation_id'>; basis: DocumentBasis; upload: Q.QsUploadEvidenceResponse; locator: string };
export type Command = Exclude<QualityCommand, { kind: 'upload_evidence' }> | (Extract<QualityCommand, { kind: 'upload_evidence' }> & { locator: string }) | IncidentRightsCommand;
export type Reply = QualityReply | D.DcSetRightsResponse;
export type PrivateSourceState = { policy?: D.DcGetResponse; current: boolean; usable: boolean; pageCount: number };
export const incidentRightsAllowed = (caps: string[]) => privateUploadAllowed(caps) && caps.includes('document.control.read');
export const invalidIncidentSource = () => new ApiError('The exact private source or current content permission could not be verified.', 'INVALID_CONTRACT', 200);
const inputFailure = () => new ApiError('Review the exact private source, authorized use and distinct supporting evidence.', 'incident_source_rights_input', 422);

export function currentIngestPolicy(policy: D.DcGetResponse | undefined, today = new Date().toISOString().slice(0, 10)): boolean {
  const row = policy?.record;
  return Boolean(row && row.status === 'authored_rights_basis' && 'ingest_allowed' in row && row.ingest_allowed && row.read_allowed && (!row.valid_from || row.valid_from <= today) && (!row.valid_until || row.valid_until >= today));
}

// Exhaust the bounded parent-filtered pages. A partial/looping result cannot
// establish the latest policy or authorize source selection.
export async function loadPrivateSource(scope: Scope, upload: Q.QsUploadEvidenceResponse, signal?: AbortSignal): Promise<PrivateSourceState> {
  if (!qualityShape('QsUploadEvidenceResponse', upload) || upload.document.company !== scope.company || upload.document.project !== scope.project || upload.registration.document_id !== upload.document.id || upload.registration.classification !== 'restricted_from_creation') throw invalidIncidentSource();
  const current = await sourceApi({ type: 'Project', ...scope }).document(upload.document.id, signal);
  if (!current?.document || !Array.isArray(current.revisions)) throw invalidIncidentSource();
  const document = current.document;
  if (document.id !== upload.document.id || document.company !== scope.company || document.project !== scope.project) throw invalidIncidentSource();
  const rawOriginal = current.revisions.find(row => row.id === upload.revision.id);
  if (!qualityShape('QsUploadedRevision', rawOriginal)) throw invalidIncidentSource();
  const original = rawOriginal as Q.QsUploadEvidenceResponse['revision'];
  if (original.sha256 !== upload.revision.sha256 || original.byte_length !== upload.revision.byte_length || original.mime_type !== upload.revision.mime_type || original.revision_number !== upload.revision.revision_number) throw invalidIncidentSource();
  const revisions = new Set<number>(), ids = new Set<string>(), cursors = new Set<string>();
  let cursor: string | undefined, policy: D.DcGetResponse | undefined, complete = false;
  for (let pages = 0; pages < 20; pages++) {
    const page = await documentControl.list(scope, 'rights', document.id, cursor, signal);
    for (const item of page.items) {
      const row = item.record as D.DcRights;
      if (row.status !== 'authored_rights_basis' || row.scope_type !== 'Project' || row.company !== scope.company || row.project !== scope.project || row.parent_id !== document.id || ids.has(row.id) || revisions.has(row.revision_number)) throw invalidIncidentSource();
      ids.add(row.id); revisions.add(row.revision_number);
      if (!policy || row.revision_number > (policy.record as D.DcRights).revision_number) policy = item;
    }
    if (!page.next_cursor) { complete = true; break; }
    if (cursors.has(page.next_cursor)) throw invalidIncidentSource();
    cursors.add(page.next_cursor); cursor = page.next_cursor;
  }
  if (!complete) throw invalidIncidentSource();
  const exactCurrent = document.current_revision === upload.revision.id && document.sha256 === upload.revision.sha256 && original.scan_status === 'clean' && original.retrieval_status === 'available' && original.page_count > 0;
  return { policy, current: exactCurrent, usable: exactCurrent && currentIngestPolicy(policy), pageCount: original.page_count };
}

export function rightsInputValid(definition: D.DcRightsDefinition, documentId: string, evidence: D.DcArtifact[], reviewed: boolean): boolean {
  const day = (value: string | null) => !value || /^\d{4}-\d{2}-\d{2}$/.test(value) && Number(value.slice(0, 4)) > 0 && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  return Boolean(reviewed && definition.ingest_allowed === true && definition.read_allowed === true && definition.distribute_allowed === false && definition.rights_holder.trim() && definition.rights_basis.trim() && definition.allowed_purpose.trim() && day(definition.valid_from) && day(definition.valid_until) && (!definition.valid_from || !definition.valid_until || definition.valid_from <= definition.valid_until) && evidence.length === 1 && evidence[0].document_id !== documentId && evidence[0].revision_id === definition.evidence_artifact.revision_id && evidence[0].source_sha256 === definition.evidence_artifact.source_sha256);
}

export const qualityWorkflow = {
  async send(command: Command & { operation_id: string }, actor: Actor): Promise<Reply> {
    if ((command.kind === 'upload_evidence' || command.kind === 'set_incident_source_rights') && (!command.locator.trim() || command.locator.length > 1000)) throw inputFailure();
    if (command.kind !== 'set_incident_source_rights') return quality.send(command, actor);
    const { payload: p, upload, basis } = command;
    if (!qualityShape('QsUploadEvidenceResponse', upload) || upload.document.id !== p.document_id || upload.registration.document_id !== p.document_id || upload.registration.classification !== 'restricted_from_creation' || upload.document.company !== p.company || upload.document.project !== p.project || !rightsInputValid(p.definition, p.document_id, basis.artifacts || [], true)) throw inputFailure();
    // The stored initial basis is replayed unchanged. Do not refresh/rebase here:
    // a successful operation with a lost response must recover its original ID.
    return documentControl.send({ kind: 'set_rights', payload: p, basis, operation_id: command.operation_id } as DocumentCommand & { operation_id: string }, actor) as Promise<D.DcSetRightsResponse>;
  },
};
