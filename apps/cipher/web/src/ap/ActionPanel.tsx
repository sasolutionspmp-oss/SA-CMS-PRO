import { useEffect, useRef, useState } from 'react';
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle,
} from '@fluentui/react-components';
import { APError, applyAction, preflight } from './client';
import { memoryKey, useActionMemory, type PreparedAction } from './ActionMemory';
import { Changes, Checks, EntryPreview, IntakeFindings } from './presentation';
import { money } from '../copy/format';
import { AppLink } from '../app/navigation';
import { TechnicalDetails } from '../ui/shared';
import type { ActionOutcome, APAction, Preflight } from './types';

interface Props {
  action: APAction; id: string; version: string; csrf: string; amountCents: number;
  body?: Record<string, unknown>; permitted: boolean; periodName?: string;
  onChanged: () => void; onSessionLost: () => void;
}
const labels: Record<APAction, { review: string; apply: string; done: string; consequence: string }> = {
  'bill.requestApproval': { review: 'Review request', apply: 'Request business approval', done: 'Business approval requested.', consequence: 'The project manager receives a business review request. No journal or payable is created.' },
  'bill.approve': { review: 'Review approval', apply: 'Approve bill', done: 'Bill approved for business purposes.', consequence: 'This records business approval. No working ledger journal or payable is created.' },
  'bill.post': { review: 'Review posting', apply: 'Post to practice working ledger', done: 'Bill posted to the practice working ledger.', consequence: 'This creates the reviewed entry and payable in the practice working ledger. No payment is started and no external accounting provider receives it.' },
  'bill.prepare': { review: 'Review preparation', apply: 'Prepare draft bill', done: 'Certified draft bill prepared.', consequence: 'This records the reviewed installed work as a certified draft bill. Business approval and independent posting follow separately.' },
  'invoice.receive': { review: 'Review invoice receipt', apply: 'Receive supplier invoice', done: 'Supplier invoice received.', consequence: 'This records the supplied invoice details and selected source evidence. Receiving an invoice creates no journal or payable.' },
  'invoice.computeMatch': { review: 'Review matching', apply: 'Compute invoice match', done: 'Invoice match computed.', consequence: 'This checks the supplier invoice against current subcontract, certified bill and source evidence. Matching exceptions must be resolved before approval.' },
  'invoice.requestMatchApproval': { review: 'Review match request', apply: 'Request match approval', done: 'Invoice match approval requested.', consequence: 'A different authorized accountant reviews the proposed invoice match. Requesting approval creates no journal or payable.' },
  'invoice.approveMatch': { review: 'Review match approval', apply: 'Approve invoice match', done: 'Invoice match approved.', consequence: 'This records approval of the reviewed source match. An authorized accountant separately applies the approved match to the bill.' },
  'invoice.executeMatch': { review: 'Review approved match', apply: 'Apply approved match', done: 'Approved invoice match applied to the bill.', consequence: 'This links the approved invoice to the certified bill. Business approval and independent posting remain separate steps.' },
};
export function ActionPanel({ action, id, version, csrf, amountCents, body = {}, permitted, periodName, onChanged, onSessionLost }: Props) {
  const memory = useActionMemory();
  const bodyKey = JSON.stringify(body);
  const remembered = memory.get(memoryKey(action, id));
  const sameInput = remembered?.inputKey === bodyKey;
  const [review, setReview] = useState<Preflight | null>(null);
  const [prepared, setPrepared] = useState<PreparedAction | null>(sameInput ? remembered?.prepared ?? null : null);
  const [outcome, setOutcome] = useState<ActionOutcome | null>(sameInput ? remembered?.outcome ?? null : null);
  const [busy, setBusy] = useState<'review' | 'action' | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<APError | Error | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const alive = useRef(true);
  const previousInput = useRef(`${action}:${id}:${bodyKey}`);
  const copy = labels[action];
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const key = `${action}:${id}:${bodyKey}`;
    if (key === previousInput.current) return;
    previousInput.current = key;
    memory.delete(memoryKey(action, id));
    setReview(null); setPrepared(null); setOutcome(null); setProblem(null); setMessage(null); setConfirmOpen(false);
  }, [action, id, bodyKey, memory]);
  useEffect(() => {
    memory.set(memoryKey(action, id), { inputKey: bodyKey, prepared, outcome });
  }, [action, id, bodyKey, prepared, outcome, memory]);
  useEffect(() => {
    if (review && review.resourceVersion !== version && !prepared) {
      setReview(null); setMessage('The record changed. Refresh the facts and review this step again.');
    }
  }, [version, review, prepared]);
  function failed(error: unknown) {
    const known = error instanceof Error ? error : new Error('The practice action could not be completed. Refresh the facts and review again.');
    setProblem(known); setMessage(null);
    if (known instanceof APError && known.status === 401) onSessionLost();
  }
  async function reviewAction() {
    memory.delete(memoryKey(action, id));
    setBusy('review'); setProblem(null); setMessage(null); setOutcome(null); setPrepared(null); setReview(null);
    try {
      const current = await preflight(action, id, JSON.parse(bodyKey), csrf);
      if (!alive.current) return;
      if (current.resourceVersion !== version) {
        setMessage('The record changed. Refresh the facts before reviewing this step.'); onChanged(); return;
      }
      setReview(current);
      setMessage(current.allowed ? 'Current facts reviewed. Read the checks and consequence before continuing.' : 'This step is blocked. Read the checks and refresh after the cause is resolved.');
    } catch (error) { if (alive.current) failed(error); }
    finally { if (alive.current) setBusy(null); }
  }
  async function submit(retry = false) {
    if (busy) return;
    const request = retry ? prepared : review?.allowed && review.fingerprint ? {
      action, id, version: review.resourceVersion, repeatabilityId: crypto.randomUUID(),
      body: { ...JSON.parse(bodyKey), fingerprint: review.fingerprint },
    } : null;
    if (!request) return;
    setPrepared(request); setBusy('action'); setProblem(null); setMessage(null); setConfirmOpen(false);
    try {
      const result = await applyAction(request.action, request.id, request.body, csrf, request.version, request.repeatabilityId);
      if (!alive.current) return;
      setOutcome(result); setReview(null);
      setMessage(result.replayed ? `Original outcome retrieved. ${copy.done} No additional effect was applied.` : copy.done);
      onChanged();
    } catch (error) { if (alive.current) { failed(error); onChanged(); } }
    finally { if (alive.current) setBusy(null); }
  }
  const changedOrExpired = problem instanceof APError && [409, 412, 423].includes(problem.status);
  return <div className="cipher-ap-action" data-action={action} aria-busy={busy !== null}>
    {message && <p role="status" aria-live="polite" className={`cipher-ap-feedback ${outcome ? 'cipher-ap-feedback-positive' : review?.allowed === false ? 'cipher-ap-feedback-warning' : ''}`}>{message}</p>}
    {problem && <div role="alert" className="cipher-message cipher-message-negative"><div>
      <p>{problem.message}</p>{problem instanceof APError && problem.problem.fix && <p>{problem.problem.fix}</p>}
      {changedOrExpired && <p>Refresh the record, then run a new review. The original request stays available for an exact retry.</p>}
      <Button appearance="subtle" onClick={onChanged} disabled={busy !== null}>Refresh facts</Button>
    </div></div>}
    {review && <div className="cipher-ap-review"><h3>Current checks</h3><Checks checks={review.checks} />
      {review.changes.length > 0 && <><h3>What changed</h3><Changes changes={review.changes} /></>}
      {action !== 'bill.post' && <div className="cipher-ap-effect-facts">
        {typeof review.safeEffects.amountDueCents === 'number' && <p>Reviewed bill amount due: <strong>{money(review.safeEffects.amountDueCents)}</strong></p>}
        {typeof review.safeEffects.amountCents === 'number' && <p>Reviewed invoice amount: <strong>{money(review.safeEffects.amountCents)}</strong></p>}
        {typeof review.safeEffects.retainageCents === 'number' && <p>Reviewed retainage: <strong>{money(review.safeEffects.retainageCents)}</strong></p>}
        {review.safeEffects.possibleDuplicate === true && <p>A possible duplicate invoice is reported in the source checks.</p>}
        <IntakeFindings effects={review.safeEffects} />
      </div>}
      <EntryPreview effects={review.safeEffects} />
    </div>}
    <p className="cipher-ap-consequence">{copy.consequence}</p>
    <div className="cipher-ap-action-footer">
      {permitted && !outcome && <Button ref={reviewButton} appearance={review?.allowed ? 'secondary' : 'primary'} disabled={busy !== null} onClick={reviewAction}>{busy === 'review' ? 'Reviewing current facts…' : copy.review}</Button>}
      {review?.allowed && !outcome && <Button appearance="primary" disabled={busy !== null || !!prepared} onClick={() => action === 'bill.post' ? setConfirmOpen(true) : submit()}>{busy === 'action' ? 'Applying practice action…' : copy.apply}</Button>}
      {prepared && <Button appearance="secondary" disabled={busy !== null} onClick={() => submit(true)}>{busy === 'action' ? 'Retrieving outcome…' : 'Retry same action'}</Button>}
      {(outcome || changedOrExpired) && <Button appearance="subtle" disabled={busy !== null} onClick={onChanged}>Refresh record</Button>}
    </div>
    {!permitted && !prepared && <p className="cipher-caption">This step is unavailable for the current person or record. Refresh the record to read its current state.</p>}
    {outcome && <TechnicalDetails entries={[{ label: 'Action receipt', value: outcome.receiptId }, { label: 'Outcome', value: outcome.replayed ? 'Original result replayed' : 'Effect applied once' }]} />}
    {outcome && <div className="cipher-link-row cipher-ap-outcome-links">
      {action === 'bill.prepare' && typeof outcome.result.billId === 'string' && <AppLink href={`/bills/${encodeURIComponent(outcome.result.billId)}`}>Open prepared bill</AppLink>}
      {action === 'invoice.receive' && typeof outcome.result.invoiceId === 'string' && <AppLink href={`/invoices/${encodeURIComponent(outcome.result.invoiceId)}`}>Open received invoice</AppLink>}
      {action === 'invoice.requestMatchApproval' && typeof outcome.result.approvalId === 'string' && <AppLink href={`/match-approvals/${encodeURIComponent(outcome.result.approvalId)}`}>Open match review</AppLink>}
      {action === 'invoice.executeMatch' && typeof outcome.result.billId === 'string' && <AppLink href={`/bills/${encodeURIComponent(outcome.result.billId)}`}>Open linked bill</AppLink>}
    </div>}
    <Dialog open={confirmOpen} onOpenChange={(_, data) => { setConfirmOpen(data.open); if (!data.open) requestAnimationFrame(() => reviewButton.current?.focus()); }}>
      <DialogSurface><DialogBody><DialogTitle>Post {money(amountCents)} to {periodName ?? 'the selected practice period'}?</DialogTitle>
        <DialogContent><p>The reviewed bill creates a practice working ledger entry in {periodName ?? 'the selected period'}.</p><p className="cipher-ap-consequence">{copy.consequence}</p></DialogContent>
        <DialogActions><Button appearance="secondary" onClick={() => setConfirmOpen(false)}>Don’t post</Button><Button appearance="primary" disabled={busy !== null} onClick={() => submit()}>Post to {periodName ?? 'selected period'}</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  </div>;
}
