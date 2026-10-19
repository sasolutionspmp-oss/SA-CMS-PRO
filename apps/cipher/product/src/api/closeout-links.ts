import { ApiError } from './client';
import { engineeringPackages } from './engineering-packages';
import { documentControl } from './document-control';
import { quality } from './quality-safety';
import { sameValue } from './schema-validation';
import type { Scope } from '../closeout-model';
import type * as C from './closeout.generated';
import type * as E from './engineering-packages.generated';
import type * as D from './document-control.generated';
import type * as Q from './quality-safety.generated';

export type CloseoutLinkChoice = { link: C.CloseoutLink; label: string };
const invalid = () => new ApiError('The supporting record could not be verified.', 'INVALID_CONTRACT', 200);
const reference = (kind: C.CloseoutLink['kind'], row: { record: { id: string }; record_digest: string }): C.CloseoutLink => ({ kind, id: row.record.id, record_digest: row.record_digest });
const ordinaryClosure = (row: Q.QsOrdinaryDecision) => row.action === 'close' && row.to_status === 'closed' && ['inspection', 'deficiency'].includes(row.category);

async function engineeringChoice(scope: Scope, row: E.EpGetResponse, signal?: AbortSignal): Promise<CloseoutLinkChoice> {
  const fact = row.record as E.EpCheck;
  const subject = await engineeringPackages.get(scope, fact.subject_kind, fact.subject_id, signal);
  const value = subject.record as E.EpBasis | E.EpCalculation | E.EpDeliverable;
  if (subject.record_digest !== fact.subject_digest || value.parent_id !== fact.parent_id || value.package_revision !== fact.package_revision || value.package_digest !== fact.package_digest || value.author_person !== fact.preparer_person || !sameValue(value.checker, fact.checker)) throw invalid();
  return { link: reference('engineering_check', row), label: `${value.definition.title} · Rev. ${value.revision_number} · Checked` };
}

async function adoptionChoice(scope: Scope, row: D.DcGetResponse, signal?: AbortSignal): Promise<CloseoutLinkChoice> {
  const fact = row.record as D.DcAdoption;
  const request = await documentControl.get(scope, 'adoption_request', fact.subject_id, signal);
  const original = request.record as D.DcAdoptionRequest;
  if (request.record_digest !== fact.subject_digest || fact.parent_id !== original.id || !sameValue(fact.artifacts, original.artifacts)) throw invalid();
  const revision = await documentControl.get(scope, 'library_revision', original.library_revision, signal);
  const value = revision.record as D.DcLibraryRevision;
  if (revision.record_digest !== original.library_digest || value.parent_id !== original.parent_id || !sameValue(value.artifacts, original.artifacts)) throw invalid();
  return { link: reference('document_adoption', row), label: `${value.definition.title} · Rev. ${value.revision_number} · Adopted` };
}

async function qualityChoice(scope: Scope, row: Q.QsGetResponse, signal?: AbortSignal): Promise<CloseoutLinkChoice> {
  const fact = row.record as Q.QsOrdinaryDecision;
  if (!ordinaryClosure(fact)) throw invalid();
  const revision = await quality.get(scope, 'revision', fact.source_revision, signal);
  const value = revision.record as Q.QsOrdinaryRevision;
  if (revision.record_digest !== fact.source_digest || value.parent_id !== fact.parent_id || value.category !== fact.category) throw invalid();
  return { link: reference('quality_closure', row), label: `${value.definition.title} · ${value.definition.location} · Closed` };
}

export async function listCloseoutLinks(scope: Scope, kind: C.CloseoutLink['kind'], cursor?: string, signal?: AbortSignal): Promise<{ items: CloseoutLinkChoice[]; next_cursor: string | null }> {
  if (kind === 'engineering_check') {
    const page = await engineeringPackages.list(scope, 'check', undefined, cursor, signal);
    return { items: await Promise.all(page.items.map(row => engineeringChoice(scope, row, signal))), next_cursor: page.next_cursor };
  }
  if (kind === 'document_adoption') {
    const page = await documentControl.list(scope, 'adoption', undefined, cursor, signal);
    return { items: await Promise.all(page.items.map(row => adoptionChoice(scope, row, signal))), next_cursor: page.next_cursor };
  }
  if (kind === 'quality_closure') {
    const page = await quality.list(scope, 'decision', undefined, cursor, signal);
    return { items: await Promise.all(page.items.filter(row => ordinaryClosure(row.record as Q.QsOrdinaryDecision)).map(row => qualityChoice(scope, row, signal))), next_cursor: page.next_cursor };
  }
  throw invalid();
}

export async function verifyCloseoutLink(scope: Scope, choice: CloseoutLinkChoice, signal?: AbortSignal): Promise<C.CloseoutLink> {
  const { kind, id, record_digest } = choice.link;
  if (kind === 'engineering_check') {
    const row = await engineeringPackages.get(scope, 'check', id, signal);
    if (row.record_digest !== record_digest) throw invalid();
    return (await engineeringChoice(scope, row, signal)).link;
  }
  if (kind === 'document_adoption') {
    const row = await documentControl.get(scope, 'adoption', id, signal);
    if (row.record_digest !== record_digest) throw invalid();
    return (await adoptionChoice(scope, row, signal)).link;
  }
  if (kind === 'quality_closure') {
    const row = await quality.get(scope, 'decision', id, signal);
    if (row.record_digest !== record_digest) throw invalid();
    return (await qualityChoice(scope, row, signal)).link;
  }
  throw invalid();
}
