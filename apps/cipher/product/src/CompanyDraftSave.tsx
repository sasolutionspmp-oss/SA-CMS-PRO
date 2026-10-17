import { useEffect, useRef, useState } from 'react';
import { Button, CheckBox, MessageStrip, Title } from '@ui5/webcomponents-react';
import { ApiError, rpc } from './api/client';
import { commercial } from './api/commercial';
import { companyEstimating } from './api/company-estimating';
import { companyDraftSaves } from './api/company-draft-saves';
import { suggestionDigest } from './api/company-ricky-proposals-validation';
import { matchesDraftSaveResponse, matchesDraftSaveSubject, publishedDraftSaveShape, type DraftSaveBase, type DraftSaveBinding } from './api/company-draft-saves-validation';
import type { CompanyDraftSaveRequest, CompanyDraftSaveResponse } from './api/company-draft-saves.generated';
import type { CompanyEstLineRecord } from './api/company-estimating.generated';
import type { CompanyRickyProposalResponse as Suggestion } from './api/company-ricky-proposals.generated';
import { Failure, Loading } from './components';
import { useResource } from './hooks';
import { useMutation } from './useMutation';

const unitSymbol = (base: DraftSaveBase, id: string) => {
  const unit = base.kind === 'estimate' ? base.snapshot.inputs.unit_manifest.records.find(row => row.id === id) : undefined;
  return unit?.kind === 'uom' ? unit.fields.symbol : '';
};
const invalid = () => new ApiError('The proposed draft or its saved receipt could not be verified against the reviewed suggestion.', 'INVALID_CONTRACT', 200);
async function loadBase(proposal: Suggestion, signal: AbortSignal): Promise<DraftSaveBase> {
  const scope = proposal.action === 'aec.scope.draft';
  const head = proposal.source_manifest.preparation_heads.find(row => row.domain === (scope ? 'commercial' : 'estimate'));
  if (!head) throw invalid();
  if (scope) return { kind: 'scope', revision: await commercial.revision(proposal.company, head.revision_id, signal) };
  const revision = await companyEstimating.get(proposal.company, 'revision', head.revision_id, signal);
  if (!publishedDraftSaveShape('CompanyEstRevisionRecord', revision) || revision.id !== head.revision_id || revision.company !== proposal.company || revision.estimate !== head.owner_id || proposal.preparation.kind !== 'estimate-draft.v1') throw invalid();
  const [snapshot, lines] = await Promise.all([
    companyEstimating.get(proposal.company, 'snapshot', revision.calculation_snapshot, signal),
    Promise.all(proposal.preparation.proposed_fields.quantity_selections.map(row => rpc<CompanyEstLineRecord>('cipher_aec.estimating.company_api.get_record', { company: proposal.company, kind: 'line', record_id: row.line_record_id }, false, signal))),
  ]);
  if (!publishedDraftSaveShape('CompanyEstSnapshotRecord', snapshot) || snapshot.id !== revision.calculation_snapshot || snapshot.company !== proposal.company || snapshot.subject_id !== revision.id || await suggestionDigest(snapshot) !== proposal.source_manifest.records.find(row => row.domain === 'estimate' && row.kind === 'snapshot' && row.id === snapshot.id)?.digest) throw invalid();
  const conversions = await Promise.all(snapshot.inputs.unit_manifest.unit_conversions.map(row => companyEstimating.get(proposal.company, 'conversion', row.id, signal)));
  return { kind: 'estimate', revision, snapshot, lines, conversions };
}

// Always mounted in the Company suggestion panel. Revoking a source read must
// hide its contents without discarding an uncertain command or its original UUID.
export default function CompanyDraftSave({ proposal, user, person, capabilities, disabled, onLockedChange, onAccessInvalidated, navigate }: { proposal?: Suggestion; user: string; person: string; capabilities: string[]; disabled: boolean; onLockedChange: (locked: boolean) => void; onAccessInvalidated: () => void; navigate: (path: string) => void }) {
  const [requested, setRequested] = useState(''); const [reviewed, setReviewed] = useState(false);
  const [saved, setSaved] = useState<CompanyDraftSaveResponse>();
  const [now, setNow] = useState(Date.now());
  const pending = useRef<DraftSaveBinding | undefined>(undefined);
  const command = useMutation<CompanyDraftSaveRequest, CompanyDraftSaveResponse>(async input => {
    const result = await companyDraftSaves.save(input);
    if (!pending.current || !await matchesDraftSaveResponse(result, input, pending.current)) throw invalid();
    return result;
  });
  useEffect(() => { onLockedChange(command.locked); return () => onLockedChange(false); }, [command.locked, onLockedChange]);
  useEffect(() => {
    setNow(Date.now());
    const remaining = proposal ? Date.parse(proposal.expires_at) - Date.now() : 0;
    if (remaining <= 0) return;
    const timer = setTimeout(() => setNow(Date.now()), Math.min(remaining + 1, 2147483647));
    return () => clearTimeout(timer);
  }, [proposal?.expires_at]);
  useEffect(() => { if (command.error && [403, 404].includes(command.error.status)) onAccessInvalidated(); }, [command.error, onAccessInvalidated]);
  const access = JSON.stringify([...capabilities].sort());
  const preview = useResource(proposal && requested === proposal.id ? `${proposal.company}/${user}/${person}/${proposal.id}/${proposal.content_digest}/${access}/draft-save` : null, async signal => {
    const [subject, base] = await Promise.all([companyDraftSaves.subject(proposal!.company, proposal!.id, signal), loadBase(proposal!, signal)]);
    if (!await matchesDraftSaveSubject(subject, proposal!, base, user, person)) throw invalid();
    return { subject, base };
  });
  useEffect(() => { setReviewed(false); }, [proposal?.id, preview.data, access]);
  const visible = Boolean(proposal && preview.data && !preview.loading && !preview.error);
  const subject = visible ? preview.data!.subject : undefined;
  const result = subject && (saved?.application.proposal_id === proposal!.id ? saved : subject.application ? { application: subject.application, saved: subject.saved! } : undefined);
  const scope = proposal?.action === 'aec.scope.draft';
  const canWrite = capabilities.includes(scope ? 'commercial.write' : 'estimate.write');
  const eligible = Boolean(proposal && subject?.eligible && !result && canWrite && Date.parse(proposal.expires_at) > now);
  const confirm = (value?: CompanyDraftSaveResponse) => { if (value) { setSaved(value); setReviewed(false); pending.current = undefined; onAccessInvalidated(); } };
  const save = async () => {
    if (!proposal || !subject || !eligible || !reviewed || disabled || command.locked) return;
    pending.current = structuredClone({ proposal, subject, user, person });
    confirm(await command.run({ company: proposal.company, proposal_id: proposal.id, expected_version: proposal.version, expected_content_digest: proposal.content_digest, mapping_version: subject.mapping_version, expected_payload_digest: subject.payload_digest, operation_id: '' }));
  };
  return <section aria-label="Reviewed draft save">
    {proposal && !requested && <Button disabled={disabled || command.locked} onClick={() => setRequested(proposal.id)}>Review draft save</Button>}
    {proposal && requested && requested !== proposal.id && <Button disabled={disabled || command.locked} onClick={() => setRequested(proposal.id)}>Review draft save</Button>}
    {preview.loading && <Loading label="Checking the exact proposed draft and current save eligibility…" />}
    {preview.error && <Failure error={preview.error} onRetry={command.locked || disabled ? undefined : preview.refresh} />}
    {subject && <><Title level="H3">{result ? 'Saved draft' : 'Review the draft to save'}</Title>
      {result ? <><MessageStrip design="Positive" hideCloseButton>Reviewed {scope ? 'proposal' : 'estimate'} draft saved as revision {result.saved.revision.revision_number}. The original suggestion remains unchanged.</MessageStrip><Button disabled={disabled || command.locked} onClick={() => navigate(scope ? `/commercial/proposals/${result.application.target_id}` : `/company/estimates/${result.application.target_id}?${new URLSearchParams({ company: proposal!.company, revision: result.application.saved_revision_id })}`)}>Open {scope ? 'proposal' : 'saved estimate revision'}</Button></> : <>
        <p>This saves a new working revision after your review. The server checks the original sources, current permissions and working revision again when you save.</p>
        {'composition' in subject.payload ? <>
          <h4>Sections to append</h4>{subject.payload.composition.sections.slice(preview.data!.base.kind === 'scope' ? preview.data!.base.revision.composition.sections.length : 0).map(row => <div key={row.id}><strong>{row.title}</strong><p style={{ whiteSpace: 'pre-wrap' }}>{row.text}</p></div>)}
          <details><summary>Retained pricing and terms</summary><p>{subject.payload.composition.currency} · Valid through {subject.payload.composition.valid_till} · {subject.payload.composition.price_list}</p>{subject.payload.composition.price_lines.map(row => <p key={row.id}>{row.description}: {row.quantity} × {row.rate}{row.selected ? '' : ' · unselected alternate'}</p>)}<p style={{ whiteSpace: 'pre-wrap' }}>{subject.payload.composition.terms || 'No terms supplied.'}</p></details>
        </> : <><h4>Quantities in the new draft</h4>{subject.payload.lines.map(row => <div key={row.line_id}><strong>{row.description}</strong><p>{row.quantity.amount} {unitSymbol(preview.data!.base, row.quantity.unit_id)}{row.included ? '' : ' · excluded'}</p></div>)}<h4>Retained basis and labeled notes</h4><p style={{ whiteSpace: 'pre-wrap' }}>{subject.payload.basis_description}</p><p>{subject.payload.adjustments.length} retained cost adjustments.</p></>}
        {subject.reason && <MessageStrip design="Information" hideCloseButton>{subject.reason.message}</MessageStrip>}
        {!canWrite && <MessageStrip design="Information" hideCloseButton>Your current permissions allow review but do not allow saving this draft.</MessageStrip>}
        {Date.parse(proposal!.expires_at) <= now && <p role="status">The original review window has expired. This suggestion is available for historical review.</p>}
        <CheckBox text="I reviewed the proposed draft and its original sources" checked={reviewed} disabled={!eligible || disabled || command.locked} onChange={event => setReviewed(event.target.checked)} />
        <Button design="Emphasized" disabled={!eligible || !reviewed || disabled || command.locked} onClick={save}>{command.busy ? 'Saving reviewed draft…' : `Save reviewed ${scope ? 'scope' : 'estimate'} draft`}</Button>
        <Button disabled={disabled || command.locked} onClick={() => { setReviewed(false); preview.refresh(); }}>Refresh draft eligibility</Button>
      </>}
    </>}
    {command.unknown && <><MessageStrip design="Critical" hideCloseButton>The save result is uncertain. Keep this view open and recover the original request.</MessageStrip><Button disabled={command.busy || disabled} onClick={async () => confirm(await command.recover())}>Recover original draft save</Button></>}
    {command.error && <Failure error={command.error} />}
    {saved && !visible && <p role="status">The original draft save is confirmed. Refresh suggestion access to review its contents.</p>}
  </section>;
}
