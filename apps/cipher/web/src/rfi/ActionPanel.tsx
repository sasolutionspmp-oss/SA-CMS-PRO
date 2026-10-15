import { useEffect, useRef, useState } from 'react';
import { Button } from '@fluentui/react-components';
import { AppLink } from '../app/navigation';
import { TechnicalDetails } from '../ui/shared';
import { applyPreparedAction, RFIError, isDefinitiveRefusal, preflight, prepareAction, type PreparedAction } from './client';
import { memoryKey, useRFIMemory, type RefusedAction } from './Memory';
import { Checks } from './presentation';
import { PreviewFacts } from './records';
import type { Action, Preflight, Receipt, ReviewBodies, ReviewContext } from './types';

const labels: Record<Action, {review:string;apply:string;done:string;consequence:string}> = {
 'rfi.create':{review:'Review RFI question',apply:'Create RFI question',done:'Question and original issued drawing and supporting citations recorded.',consequence:'This creates an open RFI with fixed question and citations. It creates no official answer, change order or contract instruction.'},
 'rfi.draftResponse':{review:'Review proposed response',apply:'Record proposed response',done:'Proposed response recorded. The RFI remains open until an independent PM grant is separately applied.',consequence:'This records a draft response and reported potential impacts. It answers no RFI and adopts no contract, budget or schedule change.'},
 'rfi.requestResponse':{review:'Review official response request',apply:'Request independent response review',done:'Independent PM review of the proposed official response requested.',consequence:'A different actual PM must review the exact response, citations and current source disclosures. That PM must differ from both author and requester.'},
 'rfi.approveResponse':{review:'Review independent response authorization',apply:'Authorize official response',done:'Independent response authorization granted. The RFI remains open until separate application.',consequence:'This grants the original response request. It creates no official answer, distribution, engineering certification or adopted impact.'},
 'rfi.applyResponse':{review:'Review authorized official response',apply:'Apply official response',done:'Exact official response recorded under the original independent PM grant.',consequence:'This answers the RFI using the unchanged original independent authorization. Potential cost and schedule impacts remain informational.'},
 'rfi.setDistribution':{review:'Review synthetic recipient list',apply:'Record synthetic recipient list',done:'Synthetic recipient draft recorded. Distribution authorization remains separate.',consequence:'This records only the selected synthetic recipients. It grants no distribution permission and sends no message.'},
 'rfi.requestDistribution':{review:'Review distribution request',apply:'Request independent distribution review',done:'Independent PM review of the exact local distribution requested.',consequence:'A different actual PM reviews the official response, original citations, current rights and exact synthetic recipients.'},
 'rfi.approveDistribution':{review:'Review independent distribution authorization',apply:'Authorize local distribution',done:'Independent distribution authorization granted. No distribution has occurred.',consequence:'This grants only the exact fixed local practice distribution. It creates no mail-sink record or outside delivery by itself.'},
 'rfi.distribute':{review:'Review authorized local distribution',apply:'Record local practice distribution',done:'One local practice distribution recorded under the original independent grant.',consequence:'This records the authored question, official response and readable citation labels in the local practice mail sink. No source bytes, attachments, external delivery or provider call occurs.'},
};
export function ActionPanel<A extends Action>({ action, id, version, body, context, permitted, inputValid = true, csrf, onChanged, onSessionLost, onRetired }: {
  action: A; id: string; version: string; body?: ReviewBodies[A]; context?: ReviewContext; permitted: boolean; inputValid?: boolean; csrf: string;
  onChanged: () => void; onSessionLost: () => void; onRetired?: () => void;
}) {
  const memory = useRFIMemory(); const input = (body ?? {}) as ReviewBodies[A]; const inputKey = JSON.stringify({ input, inputValid });
  const cached = memory.get(memoryKey(action, id));
  const [review, setReview] = useState<Preflight | null>(null);
  const [prepared, setPrepared] = useState<PreparedAction | null>(cached?.prepared ?? null);
  const [receipt, setReceipt] = useState<Receipt | null>(cached?.receipt ?? null);
  const [refused, setRefused] = useState<RefusedAction | null>(cached?.refused ?? null);
  const [historyMessage, setHistoryMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<'review' | 'apply' | null>(null);
  const [message, setMessage] = useState<string | null>(null); const [problem, setProblem] = useState<Error | null>(cached?.refused?.error ?? null);
  const previous = useRef(`${action}:${id}:${inputKey}`); const current = useRef({ key: previous.current, version });
  current.current = { key: `${action}:${id}:${inputKey}`, version };
  const alive = useRef(true); const copy = labels[action];
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const key = `${action}:${id}:${inputKey}`; if (key === previous.current) return; previous.current = key;
    if (prepared && !receipt && prepared.action === action && prepared.id === id) { setReview(null); setMessage(refused ? 'The original request was refused. Explicitly start a new current review to use the entered facts.' : 'The entered facts changed. Retrieve the original action outcome before reviewing another source.'); return; }
    memory.delete(memoryKey(action, id)); setReview(null); setPrepared(null); setReceipt(null); setRefused(null); setMessage(null); setProblem(null);
  }, [action, id, inputKey, memory, prepared, receipt, refused]);
  useEffect(() => { if (review && review.resourceVersion !== version && !prepared) { setReview(null); setMessage('The source changed. Refresh the facts and review this step again.'); } }, [review, version, prepared]);
  function fail(error: unknown) {
    setProblem(error instanceof Error ? error : new Error('The rfi action could not be completed. Refresh and review its current source.')); setMessage(null);
    if (error instanceof RFIError && error.status === 401) onSessionLost();
  }
  async function reviewStep() {
    if (busy || !inputValid || !permitted || prepared && !receipt) return;
    const reviewed = current.current;
    memory.delete(memoryKey(action, id)); setBusy('review'); setReview(null); setPrepared(null); setReceipt(null); setRefused(null); setProblem(null); setMessage(null);
    try {
      const result = await preflight(action, id, input, csrf, undefined, context);
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
    memory.delete(key); setPrepared(null); setReceipt(null); setRefused(null); setReview(null); setProblem(null);
    setMessage('The original refusal is retained below. Choose current source facts and review them before applying a new request.');
    onRetired?.();
  }
  async function retryRefusal(original: RefusedAction) {
    if (busy) return; setBusy('apply'); setHistoryMessage(null);
    try { await applyPreparedAction(original.prepared, csrf); if (alive.current) setHistoryMessage('The earlier refused request returned an unexpected completed outcome. Refresh current facts before proceeding.'); }
    catch (error) { if (alive.current) { setHistoryMessage(isDefinitiveRefusal(error) ? 'The original request remains refused. No additional RFI, official response or local distribution was completed.' : error instanceof Error ? error.message : 'The original refusal could not be retrieved.'); if (error instanceof RFIError && error.status === 401) onSessionLost(); } }
    finally { if (alive.current) { setBusy(null); onChanged(); } }
  }
  const history = memory.refused.get(memoryKey(action, id)) ?? [];
  const changed = problem instanceof RFIError && [409, 412, 423].includes(problem.status);
  const feedback = message ?? (receipt ? `Original recorded outcome. ${copy.done}` : null);
  return <div className="cipher-ap-action" data-action={action} data-resource-version={version} aria-busy={busy !== null}>
    {feedback && <p role="status" aria-live="polite" className={`cipher-ap-feedback ${receipt ? 'cipher-ap-feedback-positive' : review?.allowed === false ? 'cipher-ap-feedback-warning' : ''}`}>{feedback}</p>}
    {problem && <div role="alert" className="cipher-message cipher-message-negative"><div><p>{problem.message}</p>{changed && <p>{refused ? 'This original action was refused. Refresh source facts, then explicitly start a new current review. Its original request remains available in refusal history.' : 'Refresh current source facts. Retrieve the original action outcome with the exact same request before starting another review.'}</p>}<Button disabled={busy !== null} appearance="subtle" onClick={onChanged}>Refresh facts</Button></div></div>}
    {review && <div className="cipher-ap-review"><h3>Current checks</h3><Checks items={review.checks} />
      {review.preview && <><h3>Exact reviewed RFI facts</h3><PreviewFacts preview={review.preview} /></>}
      <p className="cipher-caption">Review is read-only. Authorization and its application remain separate. No journal, change order, contract value, budget or schedule baseline is changed.</p>{review.safeEffects.invalidatedApprovalsDelta > 0 && <p className="cipher-message cipher-message-warning">Recording this revision invalidates {review.safeEffects.invalidatedApprovalsDelta} open review authorization(s). Fresh independent review will be required.</p>}</div>}
    <p className="cipher-ap-consequence">{copy.consequence}</p>
    {(permitted && inputValid || prepared || receipt || changed) && <div className="cipher-ap-action-footer">
      {permitted && inputValid && !receipt && !prepared && <Button appearance={review?.allowed ? 'secondary' : 'primary'} disabled={busy !== null} onClick={reviewStep}>{busy === 'review' ? 'Reviewing current facts…' : copy.review}</Button>}
      {review?.allowed && inputValid && permitted && !receipt && <Button appearance="primary" disabled={busy !== null || prepared !== null} onClick={() => submit(false)}>{busy === 'apply' ? 'Applying reviewed step…' : copy.apply}</Button>}
      {permitted && inputValid && receipt && prepared && cached?.inputKey !== inputKey && <Button appearance="primary" disabled={busy !== null} onClick={reviewStep}>Review edited RFI facts</Button>}
      {prepared && <Button appearance="secondary" disabled={busy !== null} onClick={() => submit(true)}>{busy === 'apply' ? 'Retrieving original outcome…' : 'Retry same action'}</Button>}
      {refused && prepared && !receipt && <Button appearance="primary" disabled={busy !== null} onClick={retireRefusal}>Start a new current review</Button>}
      {(receipt || changed) && <Button appearance="subtle" disabled={busy !== null} onClick={onChanged}>Refresh record</Button>}
    </div>}
    {prepared && !receipt && cached?.inputKey !== inputKey && <p className="cipher-caption">The original request retains its reviewed source and repeatability key. Current edits are excluded from its exact retry.</p>}
    {!permitted && !prepared && <p className="cipher-caption">This step is unavailable for the current person or source. Read its current restrictions.</p>}
    {receipt && <><TechnicalDetails entries={[{ label: 'Original receipt', value: receipt.receiptId }, { label: 'Outcome', value: receipt.replayed ? 'Original result replayed' : 'Recorded once' }]} />
      <div className="cipher-link-row">
        <AppLink href={`/rfis/${encodeURIComponent(receipt.result.rfiId)}`}>Open current RFI record</AppLink>
        {receipt.result.approvalId && <AppLink href={`/${receipt.result.action.includes('Distribution') || receipt.result.action === 'rfi.distribute' ? 'rfi-distribution-approvals' : 'rfi-response-approvals'}/${encodeURIComponent(receipt.result.approvalId)}`}>Open original {receipt.result.action.includes('Distribution') || receipt.result.action === 'rfi.distribute' ? 'distribution' : 'response'} review</AppLink>}
        <p className="cipher-caption">This is the validated original action outcome. Open the current RFI separately for its present response, source and distribution state.</p>
      </div></>}
    {history.length > 0 && <div className="cipher-ap-review"><h3>Earlier refused requests</h3>{history.map(original => <div key={original.prepared.repeatabilityId}>
      <p>{original.error.message}</p><TechnicalDetails entries={[{ label: 'Original refusal', value: original.error.problem.code }, ...(original.error.receiptId ? [{ label: 'Original refusal receipt', value: original.error.receiptId }] : [])]} />
      <Button appearance="secondary" disabled={busy !== null} onClick={() => retryRefusal(original)}>Retry refused request</Button>
    </div>)}{historyMessage && <p role="status">{historyMessage}</p>}</div>}
  </div>;
}
