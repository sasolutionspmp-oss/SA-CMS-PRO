import { useEffect, useRef, useState } from 'react';
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle } from '@fluentui/react-components';
import { AppLink } from '../app/navigation';
import { money } from '../copy/format';
import { KeyFacts, TechnicalDetails } from '../ui/shared';
import { applyPreparedAction, ARError, isDefinitiveRefusal, preflight, prepareAction, type PreparedAction } from './client';
import { memoryKey, useARMemory, type RefusedAction } from './Memory';
import { Changes, Checks } from './presentation';
import { CalculationFacts, JournalTable } from './records';
import type { Action, Preflight, Receipt, ReviewBodies } from './types';

const labels: Record<Action, { review: string; apply: string; done: string; consequence: string }> = {
  'ownerBill.prepare': { review: 'Review owner pay app', apply: 'Prepare owner bill', done: 'Owner bill draft prepared from its complete claimed and reviewed source.', consequence: 'This records the exact original owner certification as a draft. It creates no working journal or receivable.' },
  'ownerBill.requestApproval': { review: 'Review owner bill request', apply: 'Request owner bill approval', done: 'Independent owner bill review requested.', consequence: 'A different current accounting person reviews this original source. Requesting approval creates no journal or receivable.' },
  'ownerBill.approve': { review: 'Review owner bill approval', apply: 'Approve owner bill', done: 'Original business authorization granted. The owner bill remains a draft.', consequence: 'This is a journal-free business grant. A different actual accountant or controller separately posts under this same authorization.' },
  'ownerBill.post': { review: 'Review owner bill posting', apply: 'Post owner bill', done: 'One original owner bill entry posted to the practice working ledger.', consequence: 'This consumes the original business grant and posts the reviewed receivable, retained receivable and revenue in the original period. Official books and external settlement remain unavailable.' },
  'ownerBill.requestSend': { review: 'Review owner send request', apply: 'Request owner send approval', done: 'Independent practice send review requested.', consequence: 'A different qualified person reviews the current balance and exact synthetic mail-sink destination. No message is sent by this request.' },
  'ownerBill.approveSend': { review: 'Review owner send approval', apply: 'Approve synthetic owner send', done: 'Separate synthetic send authorization granted.', consequence: 'This authorizes the unchanged practice mail-sink message. It creates no journal, payment or external delivery.' },
  'ownerBill.send': { review: 'Review synthetic send', apply: 'Send to practice mail sink', done: 'One original message recorded in the synthetic mail sink.', consequence: 'This consumes the separate send grant and records one practice mail-sink message. It does not prove external delivery, customer receipt, award or settlement.' },
};
export function ActionPanel<A extends Action>({ action, id, version, body, permitted, inputValid = true, csrf, onChanged, onSessionLost }: {
  action: A; id: string; version: string; body?: ReviewBodies[A]; permitted: boolean; inputValid?: boolean; csrf: string;
  onChanged: () => void; onSessionLost: () => void;
}) {
  const memory = useARMemory(); const input = (body ?? {}) as ReviewBodies[A]; const inputKey = JSON.stringify({ input, inputValid });
  const cached = memory.get(memoryKey(action, id));
  const [review, setReview] = useState<Preflight | null>(null);
  const [prepared, setPrepared] = useState<PreparedAction | null>(cached?.prepared ?? null);
  const [receipt, setReceipt] = useState<Receipt | null>(cached?.receipt ?? null);
  const [refused, setRefused] = useState<RefusedAction | null>(cached?.refused ?? null);
  const [historyMessage, setHistoryMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<'review' | 'apply' | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false); const applyButton = useRef<HTMLButtonElement>(null);
  const [message, setMessage] = useState<string | null>(null); const [problem, setProblem] = useState<Error | null>(cached?.refused?.error ?? null);
  const previous = useRef(`${action}:${id}:${inputKey}`); const current = useRef({ key: previous.current, version });
  current.current = { key: `${action}:${id}:${inputKey}`, version };
  const alive = useRef(true); const copy = labels[action];
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const key = `${action}:${id}:${inputKey}`; if (key === previous.current) return; previous.current = key;
    if (prepared && !receipt && prepared.action === action && prepared.id === id) { setReview(null); setMessage(refused ? 'The original request was refused. Explicitly start a new current review to use the entered facts.' : 'The entered facts changed. Retrieve the original action outcome before reviewing another source.'); return; }
    memory.delete(memoryKey(action, id)); setReview(null); setConfirmOpen(false); setPrepared(null); setReceipt(null); setRefused(null); setMessage(null); setProblem(null);
  }, [action, id, inputKey, memory, prepared, receipt, refused]);
  useEffect(() => { if (review && review.resourceVersion !== version && !prepared) { setReview(null); setConfirmOpen(false); setMessage('The source changed. Refresh the facts and review this step again.'); } }, [review, version, prepared]);
  function fail(error: unknown) {
    setProblem(error instanceof Error ? error : new Error('The owner-billing action could not be completed. Refresh and review its current source.')); setMessage(null);
    if (error instanceof ARError && error.status === 401) onSessionLost();
  }
  async function reviewStep() {
    if (busy || !inputValid || !permitted || prepared && !receipt) return;
    const reviewed = current.current;
    memory.delete(memoryKey(action, id)); setBusy('review'); setReview(null); setPrepared(null); setReceipt(null); setRefused(null); setProblem(null); setMessage(null);
    try {
      const result = await preflight(action, id, input, csrf);
      if (!alive.current) return;
      if (current.current.key !== reviewed.key || current.current.version !== reviewed.version) { setMessage('The entered facts changed while this review was loading. Review the current source again.'); return; }
      if (result.resourceVersion !== version) { setMessage('The source changed. Refresh its facts before reviewing.'); onChanged(); return; }
      setReview(result); setMessage(result.allowed ? 'Current facts reviewed. Read the checks and consequence before applying this step.' : 'This step is blocked. Read the current checks and refresh after the cause is resolved.');
    } catch (error) { if (alive.current) fail(error); }
    finally { if (alive.current) setBusy(null); }
  }
  async function submit(retry: boolean) {
    if (busy) return;
    let original: PreparedAction | null;
    try { original = retry ? prepared : inputValid && permitted && review?.allowed ? prepareAction<A>(review, input) : null; }
    catch (error) { setReview(null); fail(error); return; }
    if (!original) return;
    setConfirmOpen(false);
    const originalInputKey = retry ? memory.get(memoryKey(action, id))?.inputKey ?? inputKey : inputKey;
    memory.set(memoryKey(action, id), { inputKey: originalInputKey, prepared: original, receipt: retry ? receipt : null, refused: retry ? refused : null });
    if (!retry) setRefused(null);
    setPrepared(original); setBusy('apply'); setProblem(null); setMessage(null);
    try {
      const result = await applyPreparedAction(original, csrf); if (!alive.current) return;
      memory.set(memoryKey(action, id), { inputKey: originalInputKey, prepared: original, receipt: result });
      setReceipt(result); setReview(null); setMessage(result.replayed ? `Original outcome retrieved. ${copy.done} No additional effect was applied.` : copy.done); onChanged();
    } catch (error) { if (alive.current) {
      if (isDefinitiveRefusal(error)) { const refusal = Object.freeze({ inputKey: originalInputKey, prepared: original, error }); setRefused(refusal); memory.set(memoryKey(action, id), { inputKey: originalInputKey, prepared: original, receipt: null, refused: refusal }); }
      fail(error); onChanged();
    } }
    finally { if (alive.current) setBusy(null); }
  }
  function retireRefusal() {
    if (busy || !refused || !prepared || refused.prepared !== prepared) return;
    const key = memoryKey(action, id); const history = memory.refused.get(key) ?? [];
    if (!history.some(item => item.prepared.repeatabilityId === refused.prepared.repeatabilityId)) memory.refused.set(key, [...history, refused]);
    memory.delete(key); setPrepared(null); setReceipt(null); setRefused(null); setReview(null); setConfirmOpen(false); setProblem(null);
    setMessage('The original refusal is retained below. Choose current source facts and review them before applying a new request.');
  }
  async function retryRefusal(original: RefusedAction) {
    if (busy) return; setBusy('apply'); setHistoryMessage(null);
    try { await applyPreparedAction(original.prepared, csrf); if (alive.current) setHistoryMessage('The earlier refused request returned an unexpected completed outcome. Refresh current facts before proceeding.'); }
    catch (error) { if (alive.current) { setHistoryMessage(isDefinitiveRefusal(error) ? 'The original request remains refused. No additional owner bill, posting or send was completed.' : error instanceof Error ? error.message : 'The original refusal could not be retrieved.'); if (error instanceof ARError && error.status === 401) onSessionLost(); } }
    finally { if (alive.current) { setBusy(null); onChanged(); } }
  }
  const history = memory.refused.get(memoryKey(action, id)) ?? [];
  const changed = problem instanceof ARError && [409, 412, 423].includes(problem.status);
  const feedback = message ?? (receipt ? `Original recorded outcome. ${copy.done}` : null);
  return <div className="cipher-ap-action" data-action={action} data-resource-version={version} aria-busy={busy !== null}>
    {feedback && <p role="status" aria-live="polite" className={`cipher-ap-feedback ${receipt ? 'cipher-ap-feedback-positive' : review?.allowed === false ? 'cipher-ap-feedback-warning' : ''}`}>{feedback}</p>}
    {problem && <div role="alert" className="cipher-message cipher-message-negative"><div><p>{problem.message}</p>{changed && <p>{refused ? 'This original action was refused. Refresh source facts, then explicitly start a new current review. Its original request remains available in refusal history.' : 'Refresh current source facts. Retrieve the original action outcome with the exact same request before starting another review.'}</p>}<Button disabled={busy !== null} appearance="subtle" onClick={onChanged}>Refresh facts</Button></div></div>}
    {review && <div className="cipher-ap-review"><h3>Current checks</h3><Checks items={review.checks} />{review.changes.length > 0 && <><h3>What changed</h3><Changes rows={review.changes} /></>}
      {review.preview && <><h3>Reviewed owner source and totals</h3><CalculationFacts calculation={review.preview.calculation} /><KeyFacts facts={[{ label: 'Original posting period', value: review.preview.period.name }, { label: 'Synthetic invoice date', value: review.preview.invoiceDate }, { label: 'Due date', value: review.preview.dueDate ?? 'Determined when posted' }]} />
        {action === 'ownerBill.post' && <><h3>Entry created by this posting</h3><JournalTable lines={review.safeEffects.journalPreview} /></>}
        {review.preview.delivery && <><h3>Exact synthetic destination</h3><p>{review.preview.delivery.recipients.join(', ')}</p><p>Channel: practice mail sink. Current balance: {money(review.preview.delivery.balanceDueCents)}. External delivery is unavailable.</p></>}
      </>}
      <p className="cipher-caption">Review is read-only. Only explicit posting creates the reviewed working-ledger entry; synthetic send is a separately authorized act.</p></div>}
    <p className="cipher-ap-consequence">{copy.consequence}</p>
    <div className="cipher-ap-action-footer">
      {permitted && inputValid && !receipt && !prepared && <Button appearance={review?.allowed ? 'secondary' : 'primary'} disabled={busy !== null} onClick={reviewStep}>{busy === 'review' ? 'Reviewing current facts…' : copy.review}</Button>}
      {review?.allowed && inputValid && permitted && !receipt && <Button appearance="primary" disabled={busy !== null || prepared !== null} ref={applyButton} onClick={() => action === 'ownerBill.post' || action === 'ownerBill.send' ? setConfirmOpen(true) : submit(false)}>{busy === 'apply' ? 'Applying reviewed step…' : copy.apply}</Button>}
      {permitted && inputValid && receipt && prepared && cached?.inputKey !== inputKey && <Button appearance="primary" disabled={busy !== null} onClick={reviewStep}>Review edited owner source</Button>}
      {prepared && <Button appearance="secondary" disabled={busy !== null} onClick={() => submit(true)}>{busy === 'apply' ? 'Retrieving original outcome…' : 'Retry same action'}</Button>}
      {refused && prepared && !receipt && <Button appearance="primary" disabled={busy !== null} onClick={retireRefusal}>Start a new current review</Button>}
      {(receipt || changed) && <Button appearance="subtle" disabled={busy !== null} onClick={onChanged}>Refresh record</Button>}
    </div>
    {prepared && !receipt && cached?.inputKey !== inputKey && <p className="cipher-caption">The original request retains its reviewed source and repeatability key. Current edits are excluded from its exact retry.</p>}
    {!permitted && !prepared && <p className="cipher-caption">This step is unavailable for the current person or source. Read its current restrictions.</p>}
    {receipt && <><TechnicalDetails entries={[{ label: 'Original receipt', value: receipt.receiptId }, { label: 'Outcome', value: receipt.replayed ? 'Original result replayed' : 'Recorded once' }]} />
      <div className="cipher-link-row">
        <AppLink href={`/owner-bills/${encodeURIComponent(receipt.result.billId)}`}>{receipt.result.action === 'ownerBill.prepare' ? 'Open prepared owner bill' : 'Open original owner bill'}</AppLink>
        {receipt.result.action === 'ownerBill.requestApproval' && <AppLink href={`/owner-bill-approvals/${encodeURIComponent(receipt.result.approvalId)}`}>Open owner bill approval</AppLink>}
        {receipt.result.action === 'ownerBill.requestSend' && <AppLink href={`/owner-send-approvals/${encodeURIComponent(receipt.result.approvalId)}`}>Open owner send approval</AppLink>}
      </div></>}
    {history.length > 0 && <div className="cipher-ap-review"><h3>Earlier refused requests</h3>{history.map(original => <div key={original.prepared.repeatabilityId}>
      <p>{original.error.message}</p><TechnicalDetails entries={[{ label: 'Original refusal', value: original.error.problem.code }, ...(original.error.receiptId ? [{ label: 'Original refusal receipt', value: original.error.receiptId }] : [])]} />
      <Button appearance="secondary" disabled={busy !== null} onClick={() => retryRefusal(original)}>Retry refused request</Button>
    </div>)}{historyMessage && <p role="status">{historyMessage}</p>}</div>}
    <Dialog open={confirmOpen && !!review?.allowed} onOpenChange={(_, data) => { setConfirmOpen(data.open); if (!data.open) requestAnimationFrame(() => applyButton.current?.focus()); }}>
      <DialogSurface><DialogBody><DialogTitle>{action === 'ownerBill.post' ? `Post this owner bill for ${money(review?.preview?.calculation.amountDueCents ?? 0)}?` : 'Send this owner bill to the practice mail sink?'}</DialogTitle>
        <DialogContent><p>{copy.consequence}</p>{review?.preview && <KeyFacts facts={[{ label: 'Original period', value: review.preview.period.name }, { label: 'Original amount due', value: money(review.preview.calculation.amountDueCents) }, ...(review.preview.delivery ? [{ label: 'Fixed synthetic destination', value: review.preview.delivery.recipients.join(', ') }] : [])]} />}</DialogContent>
        <DialogActions><Button appearance="secondary" onClick={() => { setConfirmOpen(false); requestAnimationFrame(() => applyButton.current?.focus()); }}>{action === 'ownerBill.post' ? "Don't post" : "Don't send"}</Button><Button appearance="primary" disabled={busy !== null} onClick={() => submit(false)}>{action === 'ownerBill.post' ? `Post to ${review?.preview?.period.name ?? 'original period'}` : 'Send synthetic owner bill'}</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  </div>;
}
