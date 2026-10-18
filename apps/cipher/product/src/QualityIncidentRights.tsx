import { useEffect, useRef, useState } from 'react';
import { Button, CheckBox, Input, Label, MessageStrip, TextArea, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { incidentRightsAllowed, loadPrivateSource, rightsInputValid } from './api/quality-incident-rights';
import type * as D from './api/document-control.generated';
import type * as Q from './api/quality-safety.generated';
import type { Scope } from './api/engineering';
import type { SubmitQuality } from './QualitySafety';
import { DocumentArtifacts } from './DocumentControlChoices';
import { useResource } from './hooks';
import { Loading } from './components';

const denied = (error: unknown) => error instanceof ApiError && [401, 403, 404].includes(error.status);
export function QualityIncidentRights({ scope, caps, locked, upload, locator, submit, onDenied, onAttached }: {
  scope: Scope; caps: string[]; locked: boolean; upload: Q.QsUploadEvidenceResponse; locator: string;
  submit: SubmitQuality; onDenied: () => void; onAttached: (source: Q.QsCapturedSource) => void;
}) {
  const alive = useRef(true), attaching = useRef(false), controller = useRef<AbortController | undefined>(undefined);
  useEffect(() => { alive.current = true; return () => { alive.current = false; controller.current?.abort(); }; }, []);
  const [holder, setHolder] = useState(''), [basis, setBasis] = useState(''), [purpose, setPurpose] = useState(''), [restriction, setRestriction] = useState('');
  const [from, setFrom] = useState(''), [until, setUntil] = useState(''), [ingest, setIngest] = useState(false), [read, setRead] = useState(false);
  const [evidence, setEvidence] = useState<D.DcArtifact[]>([]), [reviewed, setReviewed] = useState(false), [sourceReviewed, setSourceReviewed] = useState(false);
  const [busy, setBusy] = useState(false), [attached, setAttached] = useState(false), [notice, setNotice] = useState(''), [requiresRefresh, setRequiresRefresh] = useState(false);
  const allowed = incidentRightsAllowed(caps);
  const policy = useResource(allowed ? `${scope.company}/${scope.project}/incident-source-permission/${upload.document.id}/${upload.revision.id}` : null,
    signal => loadPrivateSource(scope, upload, signal).catch(error => { if (alive.current && denied(error)) onDenied(); throw error; }));
  const current = policy.data?.policy;
  const definition: D.DcRightsDefinition = { ingest_allowed: ingest, read_allowed: read, distribute_allowed: false, rights_holder: holder, rights_basis: basis, allowed_purpose: purpose, restriction, valid_from: from || null, valid_until: until || null,
    evidence_artifact: { revision_id: evidence[0]?.revision_id || '', source_sha256: evidence[0]?.source_sha256 || '' } };
  useEffect(() => { setReviewed(false); }, [holder, basis, purpose, restriction, from, until, ingest, read, evidence, current?.record_digest]);
  useEffect(() => { setSourceReviewed(false); }, [current?.record_digest, policy.data?.current, policy.data?.usable]);
  const valid = allowed && !requiresRefresh && !policy.loading && !policy.error && policy.data?.current && rightsInputValid(definition, upload.document.id, evidence, reviewed);
  const unavailable = locked || busy;
  const refresh = () => { setReviewed(false); setSourceReviewed(false); setNotice(''); setRequiresRefresh(false); policy.refresh(); };
  const field = (label: string, value: string, change: (value: string) => void, max: number, multiline = false) => <div><Label>{label}</Label>{multiline ? <TextArea accessibleName={label} value={value} maxlength={max} disabled={unavailable} onInput={e => change(e.currentTarget!.value)} /> : <Input accessibleName={label} value={value} maxlength={max} disabled={unavailable} onInput={e => change(e.currentTarget!.value)} />}</div>;
  if (!allowed) return <MessageStrip hideCloseButton>Private original stored. A permitted evidence manager with Document control access must verify current source permission before attachment.</MessageStrip>;
  if (policy.error) return <><MessageStrip design="Negative" hideCloseButton>{denied(policy.error) ? 'Source access unavailable. Previously loaded permission is hidden.' : 'Current source permission could not be verified. No source has been attached.'}</MessageStrip><Button disabled={unavailable} onClick={refresh}>Refresh private source permission</Button></>;
  return <section aria-label="Private incident source permission"><Title level="H3">Review private source permission</Title>
    <p>Original stored privately. Recording a permission is a separate authored declaration; uploading does not authorize ingestion or attach this source.</p>
    <p>Exact document <code>{upload.document.id}</code> · Revision {upload.revision.revision_number} · <code>{upload.revision.sha256}</code></p>
    <Button disabled={unavailable} onClick={refresh}>Refresh private source permission</Button>
    {policy.loading ? <Loading label="Reading current private source permission " /> : <MessageStrip hideCloseButton>{!policy.data?.current ? 'This original is no longer the current usable document revision. It cannot be attached for a new incident.' : policy.data.usable ? 'Current authored permission permits reading and ingestion on this UTC date. Review the exact source before selecting it.' : current ? 'Current authored permission does not permit this new use on this UTC date. No source has been attached.' : 'No current authored source permission is recorded. No source has been attached.'}</MessageStrip>}
    <details><summary>Record authorized source permission</summary><p>Use this form only if you are authorized to document the stated permission. It changes only the content-use policy of this exact private original. It does not make the document shared or authorize distribution.</p>
      {field('Private source rights holder', holder, setHolder, 500)}{field('Private source permission basis', basis, setBasis, 4000, true)}{field('Private source permitted purpose', purpose, setPurpose, 4000, true)}{field('Private source use restrictions', restriction, setRestriction, 4000, true)}
      {field('Private source effective from (UTC date)', from, setFrom, 10)}{field('Private source effective through (UTC date)', until, setUntil, 10)}
      <CheckBox accessibleName="Private source ingestion is authorized" text="The stated permission allows ingestion for this purpose" checked={ingest} disabled={unavailable} onChange={e => setIngest(e.currentTarget!.checked)} />
      <CheckBox accessibleName="Private source reading is authorized" text="The stated permission allows reading for this purpose" checked={read} disabled={unavailable} onChange={e => setRead(e.currentTarget!.checked)} />
      <p>Distribution permission remains off.</p><DocumentArtifacts scope={scope} label="Private source permission evidence" maximum={1} values={evidence} onChange={setEvidence} disabled={unavailable} onDenied={onDenied} excludeDocument={upload.document.id} />
      <CheckBox accessibleName="I am authorized and reviewed this private source permission" text="I am authorized to document this permission and reviewed the exact original, permitted use and distinct evidence" checked={reviewed} disabled={unavailable || policy.loading} onChange={e => setReviewed(e.currentTarget!.checked)} />
      <Button disabled={unavailable || !valid} onClick={async () => {
        if (!valid || unavailable) return;
        setReviewed(false); setSourceReviewed(false); setRequiresRefresh(true);
        const result = await submit({ kind: 'set_incident_source_rights', payload: { ...scope, document_id: upload.document.id, expected_version: current?.record_digest || null, definition }, basis: { original: current, artifacts: evidence }, upload, locator });
        if (!alive.current) return;
        if (result && 'rights' in result) { setRequiresRefresh(false); setNotice('Permission recorded. Review its current readback before attaching the source.'); policy.refresh(); }
        else setNotice('No verified permission result was received. Recover any uncertain request, then refresh and review the current permission before another request.');
      }}>Record private source permission</Button>
    </details>
    <CheckBox accessibleName="I reviewed current private source permission for attachment" text="I reviewed this exact private original and its current permission for the new incident" checked={sourceReviewed} disabled={unavailable || policy.loading || !policy.data?.usable || attached} onChange={e => setSourceReviewed(e.currentTarget!.checked)} />
    <Button disabled={unavailable || policy.loading || !policy.data?.usable || !sourceReviewed || attached} onClick={async () => {
      if (unavailable || attaching.current || attached || !sourceReviewed || !policy.data?.usable) return;
      attaching.current = true; setBusy(true); setNotice(''); controller.current = new AbortController();
      try {
        const fresh = await loadPrivateSource(scope, upload, controller.current.signal);
        if (!alive.current) return;
        if (!fresh.current || !fresh.usable || fresh.policy?.record_digest !== current?.record_digest) { setSourceReviewed(false); policy.refresh(); setNotice('The current source or permission changed. Refresh and review it again before attachment.'); return; }
        const r = upload.revision;
        onAttached({ document_id: upload.document.id, revision_id: r.id, source_sha256: r.sha256, revision_number: r.revision_number, byte_length: r.byte_length, mime_type: r.mime_type, page_count: fresh.pageCount, page: 1, locator });
        setAttached(true); setNotice('Private source selected for this incident. Current permission is checked again when the incident is saved.');
      } catch (error) { if (alive.current) { if (denied(error)) onDenied(); setNotice('Current source permission could not be verified. No source has been attached.'); } }
      finally { attaching.current = false; if (alive.current) setBusy(false); }
    }}>Attach reviewed private source</Button>
    {notice && <MessageStrip hideCloseButton>{notice}</MessageStrip>}
  </section>;
}
