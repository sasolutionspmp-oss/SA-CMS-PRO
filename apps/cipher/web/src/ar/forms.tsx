import { useState } from 'react';
import { Input, Select, Textarea } from '@fluentui/react-components';
import { AppLink } from '../app/navigation';
import { money } from '../copy/format';
import { KeyFacts, Notice, Section } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { canonicalMeasure } from './client';
import { memoryKey, useARMemory } from './Memory';
import { ARHeader, type Controls } from './presentation';
import { BasisFacts } from './records';
import type { DeepReadonly, Preparation, PrepareInput, PrepareLine } from './types';
const measure = /^(?:0|[1-9]\d{0,11})(?:\.\d{1,6})?$/;
const dollars = /^(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$/;
export function OwnerPreparationForm({ preparation: p, ...controls }: Controls & { preparation: Preparation }) {
  const memory = useARMemory(); const original = memory.get(memoryKey('ownerBill.prepare', p.basis.id))?.prepared;
  const saved = original?.action === 'ownerBill.prepare' && 'lines' in original.body ? original.body as DeepReadonly<PrepareInput> : null;
  const [claim, setClaim] = useState(saved?.claimRevisionId ?? ''); const [review, setReview] = useState(saved?.reviewRevisionId ?? ''); const [period, setPeriod] = useState(saved?.periodId ?? '');
  const [lines, setLines] = useState<PrepareLine[]>(() => saved ? saved.lines.map(line => ({ ...line })) : p.basis.sov.map(line => ({ lineId: line.lineId, claimedCumulative: '', reviewedCumulative: '', differenceReason: '', claimSourceLocator: '', reviewSourceLocator: '' })));
  const valid = p.claimSources.some(source => source.revisionId === claim) && p.reviewSources.some(source => source.revisionId === review) && claim !== review && p.periods.some(item => item.id === period && item.status === 'open') && lines.every(line => { const basis = p.basis.sov.find(item => item.lineId === line.lineId); const pattern = basis?.basis === 'lumpSum' ? dollars : measure; return pattern.test(line.claimedCumulative) && pattern.test(line.reviewedCumulative) && !!line.claimSourceLocator.trim() && !!line.reviewSourceLocator.trim() && (canonicalMeasure(line.claimedCumulative) === canonicalMeasure(line.reviewedCumulative) || !!line.differenceReason.trim()); });
  const body: PrepareInput = { claimRevisionId: claim, reviewRevisionId: review, periodId: period, lines };
  function change(lineId: string, field: keyof PrepareLine, value: string) { setLines(current => current.map(line => line.lineId === lineId ? { ...line, [field]: value } : line)); }
  return <><div className="cipher-breadcrumb"><AppLink href="/owner-bases">Owner contract bases</AppLink></div><ARHeader title="Prepare an owner pay app" subtitle={p.basis.project.name} /><BasisFacts basis={p.basis} />
    <Notice>Manual claimed and reviewed progress remain separate. Quantities, owner contract rates and previous certified history are distinct facts. The server calculates every amount before the draft is prepared.</Notice>
    <Section title="Separate owned claim and review documents"><div className="cipher-form ar-form">
      <label className="cipher-field"><span>Claimed progress document</span><Select aria-label="Claimed progress document" value={claim} onChange={(_, data) => setClaim(data.value)}><option value="">Choose the owned claimed-progress revision</option>{p.claimSources.map(source => <option key={source.revisionId} value={source.revisionId}>{source.title} · Revision {source.revision}</option>)}</Select></label>
      <label className="cipher-field"><span>Reviewed progress document</span><Select aria-label="Reviewed progress document" value={review} onChange={(_, data) => setReview(data.value)}><option value="">Choose the separate reviewed-progress revision</option>{p.reviewSources.map(source => <option key={source.revisionId} value={source.revisionId}>{source.title} · Revision {source.revision}</option>)}</Select></label>
      <label className="cipher-field"><span>Owner billing period</span><Select aria-label="Owner billing period" value={period} onChange={(_, data) => setPeriod(data.value)}><option value="">Choose the original open period</option>{p.periods.filter(period => period.status === 'open').map(period => <option key={period.id} value={period.id}>{period.name}</option>)}</Select></label>
    </div></Section>
    <Section title="Claimed and reviewed cumulative progress"><KeyFacts facts={[{ label: 'Previous certified value', value: money(p.previous.certifiedCents) }, { label: 'Previous retained value', value: money(p.previous.retainedCents) }]} />
      {p.basis.sov.map(sov => { const line = lines.find(item => item.lineId === sov.lineId)!; const previous = p.previous.lines.find(item => item.lineId === sov.lineId)!; const quantity = sov.basis === 'unitPrice'; const pattern = quantity ? measure : dollars; const difference = pattern.test(line.claimedCumulative) && pattern.test(line.reviewedCumulative) && canonicalMeasure(line.claimedCumulative) !== canonicalMeasure(line.reviewedCumulative);
        return <div className="ar-entry-line" key={line.lineId}><h3>{sov.lineId} · {sov.description}</h3><KeyFacts facts={[{ label: quantity ? 'Original owner unit price' : 'Original scheduled amount', value: money(quantity ? sov.unitPriceCents! : sov.scheduledAmountCents) }, { label: quantity ? `Previously reviewed quantity (${sov.unit})` : 'Previously reviewed value', value: quantity ? previous.reviewedQuantity! : money(previous.reviewedAmountCents) }]} />
          <div className="ar-line-entry ar-form">
            <label className="cipher-field"><span>Claimed cumulative {quantity ? `quantity (${sov.unit})` : 'value (USD)'}</span><Input aria-label={`Claimed cumulative for owner line ${sov.lineId}`} inputMode="decimal" value={line.claimedCumulative} aria-invalid={line.claimedCumulative !== '' && !pattern.test(line.claimedCumulative)} onChange={(_, data) => change(sov.lineId, 'claimedCumulative', data.value)} /></label>
            <label className="cipher-field"><span>Reviewed cumulative {quantity ? `quantity (${sov.unit})` : 'value (USD)'}</span><Input aria-label={`Reviewed cumulative for owner line ${sov.lineId}`} inputMode="decimal" value={line.reviewedCumulative} aria-invalid={line.reviewedCumulative !== '' && !pattern.test(line.reviewedCumulative)} onChange={(_, data) => change(sov.lineId, 'reviewedCumulative', data.value)} /></label>
            <label className="cipher-field"><span>Claim source locator</span><Input aria-label={`Claim source locator for owner line ${sov.lineId}`} maxLength={240} value={line.claimSourceLocator} onChange={(_, data) => change(sov.lineId, 'claimSourceLocator', data.value)} /></label>
            <label className="cipher-field"><span>Review source locator</span><Input aria-label={`Review source locator for owner line ${sov.lineId}`} maxLength={240} value={line.reviewSourceLocator} onChange={(_, data) => change(sov.lineId, 'reviewSourceLocator', data.value)} /></label>
            <label className="cipher-field ar-full-width"><span>Why the reviewed progress differs{difference ? ' (required)' : ''}</span><Textarea aria-label={`Difference reason for owner line ${sov.lineId}`} maxLength={500} value={line.differenceReason} aria-invalid={difference && !line.differenceReason.trim()} onChange={(_, data) => change(sov.lineId, 'differenceReason', data.value)} /></label>
          </div>{difference && !line.differenceReason.trim() && <p role="status">Enter the review reason for this claimed-versus-reviewed difference.</p>}
        </div>;
      })}
    </Section><Section title="Review the complete original owner source">{!valid && <p role="status">Choose separate claim and review documents, the original period and every line fact. Record a reason for each difference.</p>}<ActionPanel action="ownerBill.prepare" id={p.basis.id} version={p.version} body={body} permitted={p.availableActions.includes('ownerBill.prepare')} inputValid={valid} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>
  </>;
}
