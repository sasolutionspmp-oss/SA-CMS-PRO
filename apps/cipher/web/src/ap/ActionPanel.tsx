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
import type { ActionOutcome, APAction, Preflight, WorkerPendingOutcome } from './types';

interface Props {
  action: APAction; id: string; version: string; csrf: string; amountCents: number;
  body?: Record<string, unknown>; permitted: boolean; periodName?: string;
  withdrawal?: boolean;
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
  'invoice.revise': { review: 'Review invoice revision', apply: 'Revise supplier invoice', done: 'Supplier invoice revised.', consequence: 'This records the reviewed replacement source facts and reason. The invoice returns to received, and its match requires fresh review and approval.' },
  'invoice.reject': { review: 'Review invoice rejection', apply: 'Reject supplier invoice', done: 'Supplier invoice rejected.', consequence: 'Rejection is final for this invoice. Its number stays reserved, its open approvals are invalidated, and its source evidence becomes available for another receipt.' },
  'invoice.reviewDuplicate': { review: 'Review duplicate decision', apply: 'Record duplicate review', done: 'Duplicate review recorded.', consequence: 'This records why the flagged invoice is a distinct obligation. Changed duplicate facts require review again before matching.' },
  'bill.cancel': { review: 'Review bill cancellation', apply: 'Cancel unposted bill', done: 'Unposted bill canceled.', consequence: 'This cancels an unposted bill and invalidates its open approval. Approved bills can be withdrawn only by their original business approver with current authority.' },
  'bill.prepareCorrection': { review: 'Review correction preparation', apply: 'Prepare correction request', done: 'Bill correction reason recorded.', consequence: 'This records the reason to correct a posted, unpaid bill. Correction approval and explicit reversal follow separately.' },
  'bill.requestCorrection': { review: 'Review correction request', apply: 'Request correction approval', done: 'Bill correction approval requested.', consequence: 'A different authorized accountant reviews the correction. Requesting approval does not reverse the bill or create a journal.' },
  'bill.approveCorrection': { review: 'Review correction approval', apply: 'Approve bill correction', done: 'Bill correction approved.', consequence: 'This records approval of the reviewed correction. An authorized accountant separately selects an open period and executes its reversal.' },
  'bill.executeCorrection': { review: 'Review correction reversal', apply: 'Execute approved correction', done: 'Approved bill correction executed.', consequence: 'This reverses the reviewed bill journals in the selected practice period, marks the original bill corrected and makes its work available for replacement certification.' },
  'accounting.prepare': { review: 'Review handoff preparation', apply: 'Prepare practice handoff', done: 'Practice accounting handoff prepared.', consequence: 'This records the original posting and fixed synthetic mapping in an immutable practice plan. No new working journal, simulator call or payment is created.' },
  'accounting.request': { review: 'Review handoff request', apply: 'Request handoff approval', done: 'Practice handoff approval requested.', consequence: 'A different authorized accountant reviews this exact source, mapping and synthetic date. No working journal, simulator call or payment is created.' },
  'accounting.approve': { review: 'Review handoff approval', apply: 'Approve practice handoff', done: 'Practice accounting handoff approved.', consequence: 'This records the independent accountant decision. Queueing and simulation remain separate actions.' },
  'accounting.queue': { review: 'Review approved handoff', apply: 'Queue approved practice handoff', done: 'Approved practice handoff queued.', consequence: 'This records one authorized handoff for separate delivery. It creates no working journal, AP balance change, simulator call or payment. Delivery is an explicit later step.' },
  'accounting.deliver': { review: 'Review practice delivery', apply: 'Run practice delivery', done: 'Practice delivery step recorded.', consequence: 'This performs the reviewed delivery step against the fixed practice simulator. The original outcome is recorded separately. QuickBooks official books and payments are untouched.' },
  'accounting.lookup': { review: 'Review original outcome lookup', apply: 'Look up original outcome', done: 'Original simulation outcome checked.', consequence: 'This looks up the original logical operation in the fixed simulator. It cannot submit a replacement or use a new logical operation.' },
  'accounting.reconcile': { review: 'Review simulation readback', apply: 'Reconcile simulation', done: 'Original simulator record checked.', consequence: 'This separately reads back the originally acknowledged simulator record and compares it with the approved practice plan. Official accounting reconciliation remains unavailable.' },
};
export function ActionPanel({ action, id, version, csrf, amountCents, body = {}, permitted, periodName, withdrawal = false, onChanged, onSessionLost }: Props) {
  const memory = useActionMemory();
  const bodyKey = JSON.stringify(body);
  const remembered = memory.get(memoryKey(action, id));
  const sameInput = remembered?.inputKey === bodyKey;
  const [review, setReview] = useState<Preflight | null>(null);
  const [prepared, setPrepared] = useState<PreparedAction | null>(sameInput ? remembered?.prepared ?? null : null);
  const [outcome, setOutcome] = useState<ActionOutcome | null>(sameInput ? remembered?.outcome ?? null : null);
  const [unfinished, setUnfinished] = useState<WorkerPendingOutcome | null>(sameInput ? remembered?.unfinished ?? null : null);
  const [busy, setBusy] = useState<'review' | 'action' | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<APError | Error | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const alive = useRef(true);
  const previousInput = useRef(`${action}:${id}:${bodyKey}`);
  const copy = withdrawal && action === 'bill.cancel' ? {
    review: 'Review approved withdrawal', apply: 'Withdraw approved bill', done: 'Approved bill withdrawn.',
    consequence: 'This records the original business approver’s withdrawal of the unposted bill and invalidates its authorization. No journal or payable is created.',
  } : labels[action];
  const confirmation = ['bill.post', 'invoice.reject', 'bill.cancel', 'bill.executeCorrection'].includes(action);
  const confirmationTitle = action === 'bill.post' ? `Post ${money(amountCents)} to ${periodName ?? 'the selected practice period'}?`
    : action === 'invoice.reject' ? 'Reject this supplier invoice?'
      : action === 'bill.cancel' ? withdrawal ? 'Withdraw this approved bill?' : 'Cancel this unposted bill?'
        : `Reverse the approved bill in ${periodName ?? 'the selected practice period'}?`;
  const safeOption = action === 'bill.post' ? 'Don’t post' : action === 'invoice.reject' ? 'Keep invoice' : action === 'bill.cancel' ? 'Keep bill' : 'Don’t reverse';
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const key = `${action}:${id}:${bodyKey}`;
    if (key === previousInput.current) return;
    previousInput.current = key;
    memory.delete(memoryKey(action, id));
    setReview(null); setPrepared(null); setOutcome(null); setUnfinished(null); setProblem(null); setMessage(null); setConfirmOpen(false);
  }, [action, id, bodyKey, memory]);
  useEffect(() => {
    memory.set(memoryKey(action, id), { inputKey: bodyKey, prepared, outcome, unfinished });
  }, [action, id, bodyKey, prepared, outcome, unfinished, memory]);
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
    setBusy('review'); setProblem(null); setMessage(null); setOutcome(null); setUnfinished(null); setPrepared(null); setReview(null);
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
      setReview(null);
      if (!('result' in result)) {
        setUnfinished(result); setOutcome(null);
        setMessage('This original practice step is unfinished. Refresh its current record or retry the same request; a new delivery is not started by an exact retry.');
      } else {
        setOutcome(result); setUnfinished(null);
        const words = action.startsWith('accounting.') ? accountingOutcome(result, copy.done) : copy.done;
        setMessage(result.replayed ? `Original outcome retrieved. ${words} No additional effect was applied.` : words);
      }
      onChanged();
    } catch (error) { if (alive.current) { failed(error); onChanged(); } }
    finally { if (alive.current) setBusy(null); }
  }
  const changedOrExpired = problem instanceof APError && [409, 412, 423].includes(problem.status);
  const uncertain = unfinished !== null || action.startsWith('accounting.') && !!outcome && ['outcome_unknown', 'refused', 'reconciliation_unavailable', 'reconciliation_conflict'].includes(outcome.result.status as string);
  const restored = action.startsWith('accounting.') ? unfinished
    ? 'This original practice step is unfinished. Refresh its current record or retry the same request.'
    : outcome ? `Original recorded outcome. ${accountingOutcome(outcome, copy.done)}` : null : null;
  const feedback = message ?? restored;
  return <div className="cipher-ap-action" data-action={action} data-resource-version={version} aria-busy={busy !== null}>
    {feedback && <p role="status" aria-live="polite" className={`cipher-ap-feedback ${uncertain ? 'cipher-ap-feedback-warning' : outcome ? 'cipher-ap-feedback-positive' : review?.allowed === false ? 'cipher-ap-feedback-warning' : ''}`}>{feedback}</p>}
    {problem && <div role="alert" className="cipher-message cipher-message-negative"><div>
      <p>{problem.message}</p>{problem instanceof APError && problem.problem.fix && <p>{problem.problem.fix}</p>}
      {changedOrExpired && <p>Refresh the record, then run a new review. The original request stays available for an exact retry.</p>}
      <Button appearance="subtle" onClick={onChanged} disabled={busy !== null}>Refresh facts</Button>
    </div></div>}
    {review && <div className="cipher-ap-review"><h3>Current checks</h3><Checks checks={review.checks} />
      {review.changes.length > 0 && <><h3>What changed</h3><Changes changes={review.changes} /></>}
      {action.startsWith('accounting.') && <p>{review.safeEffects.startsSeparateWorkerInvocation === true ? `The reviewed practice step is ${review.safeEffects.intendedWorkerPhase === 'submit' ? 'original entry delivery' : review.safeEffects.intendedWorkerPhase === 'lookup' ? 'original outcome lookup' : 'original simulator record readback'}. Its outcome is observed separately.` : 'This human handoff step creates no simulator call or additional working journal.'}</p>}
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
      {permitted && !outcome && !unfinished && <Button ref={reviewButton} appearance={review?.allowed ? 'secondary' : 'primary'} disabled={busy !== null} onClick={reviewAction}>{busy === 'review' ? 'Reviewing current facts…' : copy.review}</Button>}
      {action.startsWith('accounting.') && permitted && outcome && !unfinished && <Button ref={reviewButton} appearance="secondary" disabled={busy !== null} onClick={reviewAction}>Review next practice step</Button>}
      {review?.allowed && !outcome && <Button appearance="primary" disabled={busy !== null || !!prepared} onClick={() => confirmation ? setConfirmOpen(true) : submit()}>{busy === 'action' ? 'Applying practice action…' : copy.apply}</Button>}
      {prepared && <Button appearance="secondary" disabled={busy !== null} onClick={() => submit(true)}>{busy === 'action' ? 'Retrieving outcome…' : 'Retry same action'}</Button>}
      {(outcome || unfinished || changedOrExpired) && <Button appearance="subtle" disabled={busy !== null} onClick={onChanged}>Refresh record</Button>}
    </div>
    {!permitted && !prepared && <p className="cipher-caption">This step is unavailable for the current person or record. Refresh the record to read its current state.</p>}
    {outcome && <TechnicalDetails entries={[{ label: 'Action receipt', value: outcome.receiptId }, { label: 'Outcome', value: outcome.replayed ? 'Original result replayed' : action.startsWith('accounting.') ? 'Original practice outcome recorded' : 'Effect applied once' }]} />}
    {unfinished && <TechnicalDetails entries={[{ label: 'Original invocation', value: unfinished.invocationId }, { label: 'Outcome', value: 'Unfinished; refresh current state' }]} />}
    {outcome && <div className="cipher-link-row cipher-ap-outcome-links">
      {action === 'bill.prepare' && typeof outcome.result.billId === 'string' && <AppLink href={`/bills/${encodeURIComponent(outcome.result.billId)}`}>Open prepared bill</AppLink>}
      {action === 'invoice.receive' && typeof outcome.result.invoiceId === 'string' && <AppLink href={`/invoices/${encodeURIComponent(outcome.result.invoiceId)}`}>Open received invoice</AppLink>}
      {action === 'invoice.requestMatchApproval' && typeof outcome.result.approvalId === 'string' && <AppLink href={`/match-approvals/${encodeURIComponent(outcome.result.approvalId)}`}>Open match review</AppLink>}
      {action === 'invoice.executeMatch' && typeof outcome.result.billId === 'string' && <AppLink href={`/bills/${encodeURIComponent(outcome.result.billId)}`}>Open linked bill</AppLink>}
      {action === 'bill.requestCorrection' && typeof outcome.result.approvalId === 'string' && <AppLink href={`/correction-approvals/${encodeURIComponent(outcome.result.approvalId)}`}>Open correction review</AppLink>}
      {action === 'accounting.prepare' && typeof outcome.result.planId === 'string' && <AppLink href={`/accounting-plans/${encodeURIComponent(outcome.result.planId)}`}>Open practice handoff plan</AppLink>}
      {action === 'accounting.request' && typeof outcome.result.approvalId === 'string' && <AppLink href={`/accounting-approvals/${encodeURIComponent(outcome.result.approvalId)}`}>Open handoff review</AppLink>}
      {action === 'accounting.queue' && typeof outcome.result.intentId === 'string' && <AppLink href={`/accounting-intents/${encodeURIComponent(outcome.result.intentId)}`}>Open practice delivery record</AppLink>}
    </div>}
    <Dialog open={confirmOpen} onOpenChange={(_, data) => { setConfirmOpen(data.open); if (!data.open) requestAnimationFrame(() => reviewButton.current?.focus()); }}>
      <DialogSurface><DialogBody><DialogTitle>{confirmationTitle}</DialogTitle>
        <DialogContent>{action === 'bill.post' && <p>The reviewed bill creates a practice working ledger entry in {periodName ?? 'the selected period'}.</p>}<p className="cipher-ap-consequence">{copy.consequence}</p></DialogContent>
        <DialogActions><Button appearance="secondary" onClick={() => setConfirmOpen(false)}>{safeOption}</Button><Button appearance="primary" disabled={busy !== null} onClick={() => submit()}>{action === 'bill.post' ? `Post to ${periodName ?? 'selected period'}` : copy.apply}</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  </div>;
}
function accountingOutcome(outcome: ActionOutcome, fallback: string) {
  return ({
    outcome_unknown: 'The original simulation outcome is unknown. Look up the original outcome before another delivery step.',
    simulated_accepted: 'The practice simulator acknowledged the original handoff. A separate readback check is still required.',
    confirmed_missing: 'The original lookup found no simulator record. A separately reviewed step may use the same logical operation.',
    refused: 'The practice step was refused. Read its current record and restrictions.',
    reconciled: 'The original simulator record matches the approved practice plan. QuickBooks delivery remains unavailable.',
    reconciliation_unavailable: 'The original simulator readback was unavailable. The recorded acknowledgment is retained; simulation reconciliation is still incomplete.',
    reconciliation_conflict: 'The original simulator readback conflicts with the approved practice plan. The recorded acknowledgment is retained; simulation reconciliation is still incomplete.',
  } as Record<string, string>)[outcome.result.status as string] ?? fallback;
}
