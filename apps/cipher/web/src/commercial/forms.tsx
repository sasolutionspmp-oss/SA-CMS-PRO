import { useState } from 'react';
import { Button, Checkbox, Input, Select, Textarea } from '@fluentui/react-components';
import { AppLink } from '../app/navigation';
import { Notice, Section } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { memoryKey, useCommercialMemory } from './Memory';
import { CommercialHeader, type Controls } from './presentation';
import { DrawingFacts, estimateName } from './records';
import type { EstimateInput, EstimatePreparation, EstimateRecord, RevisionInput } from './types';

const maxCents = 999_999_999_999_999n;
export function inputCents(value: string): number | null {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ''] = value.split('.'); const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  return cents <= maxCents ? Number(cents) : null;
}
const dollars = (cents: number) => `${BigInt(cents) / 100n}.${(BigInt(cents) % 100n).toString().padStart(2, '0')}`;
function rateFromPercent(value: string): string | null {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,4})?$/.test(value)) return null;
  const [whole, fraction = ''] = value.split('.'); const scaled = BigInt(whole) * 10_000n + BigInt(fraction.padEnd(4, '0'));
  if (scaled > 500_000n) return null;
  const tail = (scaled % 1_000_000n).toString().padStart(6, '0').replace(/0+$/, '');
  return `${scaled / 1_000_000n}${tail ? '.' + tail : ''}`;
}
function percentFromRate(value: string) {
  const [whole, fraction = ''] = value.split('.'); const scaled = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'));
  const tail = (scaled % 10_000n).toString().padStart(4, '0').replace(/0+$/, ''); return `${scaled / 10_000n}${tail ? '.' + tail : ''}`;
}
const textLines = (value: string) => value.split('\n').map(line => line.trim()).filter(Boolean);
interface FormLine { key: string; previousLineId: string | null; description: string; quantity: string; unit: string; price: string; sourceLocator: string; costCode: string }
const emptyLine = (): FormLine => ({ key: crypto.randomUUID(), previousLineId: null, description: '', quantity: '', unit: '', price: '', sourceLocator: '', costCode: '' });
const quantityShape = (value: string) => /^(?:0|[1-9]\d{0,14})(?:\.\d{1,15})?$/.test(value);
export function ManualEstimateForm({ preparation: p, estimate: prior, ...controls }: Controls & { preparation: EstimatePreparation; estimate?: EstimateRecord }) {
  const action = prior ? 'estimate.revise' : 'estimate.create'; const id = prior?.id ?? p.project.id;
  const memory = useCommercialMemory(); const remembered = memory.get(memoryKey(action, id))?.prepared?.body;
  const saved = remembered && 'lines' in remembered ? remembered : null;
  const [drawing, setDrawing] = useState(saved?.documentRevisionId ?? prior?.source.documentRevisionId ?? '');
  const [basis, setBasis] = useState(saved?.measurementBasis ?? prior?.measurementBasis ?? '');
  const [book, setBook] = useState(saved?.priceBookRef ?? prior?.priceBookRef ?? '');
  const [inclusions, setInclusions] = useState((saved?.inclusions ?? prior?.inclusions ?? []).join('\n'));
  const [exclusions, setExclusions] = useState((saved?.exclusions ?? prior?.exclusions ?? []).join('\n'));
  const [contingency, setContingency] = useState(saved?.contingencyRate ? percentFromRate(saved.contingencyRate) : prior ? percentFromRate(prior.contingencyRate) : '');
  const [removed, setRemoved] = useState<string[]>(saved && 'removedExclusions' in saved && Array.isArray(saved.removedExclusions) ? saved.removedExclusions.filter((value): value is string => typeof value === 'string') : []);
  const [lines, setLines] = useState<FormLine[]>(() => saved?.lines.map(line => ({
    key: crypto.randomUUID(), previousLineId: 'previousLineId' in line && typeof line.previousLineId === 'string' ? line.previousLineId : null,
    description: line.description, quantity: line.quantity, unit: line.unit, price: dollars(line.unitPriceCents), sourceLocator: line.sourceLocator, costCode: line.costCode,
  })) ?? prior?.lines.map(line => ({ key: crypto.randomUUID(), previousLineId: line.id, description: line.description, quantity: line.quantity, unit: line.unit, price: dollars(line.unitPriceCents), sourceLocator: line.sourceLocator, costCode: line.costCode })) ?? [emptyLine()]);
  const excludedNow = textLines(exclusions); const removedNow = prior?.exclusions.filter(value => !excludedNow.includes(value)) ?? [];
  const oldLinks = lines.map(line => line.previousLineId).filter((value): value is string => value !== null);
  const uniqueLinks = new Set(oldLinks).size === oldLinks.length;
  const valid = p.drawingRevisions.some(source => source.documentRevisionId === drawing && source.current) && !!basis.trim() && rateFromPercent(contingency) !== null && uniqueLinks &&
    lines.length > 0 && lines.every(line => !!line.description.trim() && quantityShape(line.quantity) && p.units.some(unit => unit.unit === line.unit) && inputCents(line.price) !== null && !!line.sourceLocator.trim() && !!line.costCode.trim()) &&
    removedNow.every(value => removed.includes(value));
  const selected = p.drawingRevisions.find(source => source.documentRevisionId === drawing);
  const values = lines.map(line => ({ description: line.description, quantity: line.quantity, unit: line.unit, unitPriceCents: inputCents(line.price) ?? 0, sourceLocator: line.sourceLocator, costCode: line.costCode }));
  const body: EstimateInput = { documentRevisionId: drawing, lines: values, priceBookRef: book.trim() || null, inclusions: textLines(inclusions), exclusions: excludedNow, contingencyRate: rateFromPercent(contingency) ?? '', measurementBasis: basis };
  const revisionBody: RevisionInput = { ...body, lines: values.map((line, index) => ({ ...line, previousLineId: lines[index].previousLineId })), removedExclusions: removedNow.filter(value => removed.includes(value)) };
  function changeLine(key: string, field: keyof FormLine, value: string | null) { setLines(current => current.map(line => line.key === key ? { ...line, [field]: value } : line)); }
  const allowed = (prior?.availableActions ?? p.availableActions).some(item => item.action === action && item.allowed);
  return <>
    <div className="cipher-breadcrumb"><AppLink href="/projects">Projects</AppLink>{prior && <AppLink href={`/estimates/${encodeURIComponent(prior.id)}`}>{estimateName(prior)}</AppLink>}</div>
    <CommercialHeader title={prior ? `Revise ${estimateName(prior).toLowerCase()}` : 'Enter a manual estimate'} subtitle={p.project.name} />
    <Notice>Manual quantity entry. Drawing scale and calibrated geometry are unverified. Read the server's exact priced preview before creating a draft.</Notice>
    <Section title="Drawing and manual basis"><div className="cipher-form commercial-form">
      <label className="cipher-field"><span>Owned drawing revision</span><Select aria-label="Owned drawing revision" value={drawing} onChange={(_, data) => setDrawing(data.value)}><option value="">Choose a current drawing revision</option>{p.drawingRevisions.map(source => <option key={source.documentRevisionId} value={source.documentRevisionId}>{source.title} · Revision {source.revision}</option>)}{drawing && !selected && <option value={drawing}>Previously selected revision is unavailable</option>}</Select></label>
      <label className="cipher-field"><span>Manual measurement basis</span><Textarea aria-label="Manual measurement basis" value={basis} onChange={(_, data) => setBasis(data.value)} /></label>
    </div>{selected && <p className="cipher-caption">Selected source: {selected.title}, revision {selected.revision}. Quantities remain supplied manual facts.</p>}</Section>
    <Section title="Manual priced lines" extra={<Button disabled={lines.length >= 50} onClick={() => setLines(current => [...current, emptyLine()])}>Add manual line</Button>}>
      {lines.map((line, index) => <div className="commercial-entry-line" key={line.key}><div className="commercial-line-title"><h3>Manual line {index + 1}</h3><Button appearance="subtle" disabled={lines.length === 1} aria-label={`Remove manual line ${index + 1}`} onClick={() => setLines(current => current.filter(value => value.key !== line.key))}>Remove line</Button></div><div className="cipher-form commercial-form">
        {prior && <label className="cipher-field"><span>Preceding source line</span><Select aria-label={`Preceding source for manual line ${index + 1}`} value={line.previousLineId ?? ''} onChange={(_, data) => changeLine(line.key, 'previousLineId', data.value || null)}><option value="">New line</option>{prior.lines.map(old => <option key={old.id} value={old.id}>Line {old.lineNo}: {old.description}</option>)}</Select></label>}
        <label className="cipher-field"><span>Description</span><Input aria-label={`Description for manual line ${index + 1}`} value={line.description} onChange={(_, data) => changeLine(line.key, 'description', data.value)} /></label>
        <label className="cipher-field"><span>Manual quantity</span><Input aria-label={`Quantity for manual line ${index + 1}`} inputMode="decimal" value={line.quantity} aria-invalid={line.quantity !== '' && !quantityShape(line.quantity)} onChange={(_, data) => changeLine(line.key, 'quantity', data.value)} /></label>
        <label className="cipher-field"><span>Unit</span><Select aria-label={`Unit for manual line ${index + 1}`} value={line.unit} onChange={(_, data) => changeLine(line.key, 'unit', data.value)}><option value="">Choose a registered unit</option>{p.units.map(unit => <option key={unit.unit} value={unit.unit}>{unit.name} ({unit.unit})</option>)}</Select></label>
        <label className="cipher-field"><span>Unit price (USD)</span><Input aria-label={`Unit price for manual line ${index + 1}`} inputMode="decimal" value={line.price} aria-invalid={line.price !== '' && inputCents(line.price) === null} onChange={(_, data) => changeLine(line.key, 'price', data.value)} /></label>
        <label className="cipher-field"><span>Drawing / page locator</span><Input aria-label={`Source locator for manual line ${index + 1}`} value={line.sourceLocator} onChange={(_, data) => changeLine(line.key, 'sourceLocator', data.value)} /></label>
        <label className="cipher-field"><span>Cost code</span><Input aria-label={`Cost code for manual line ${index + 1}`} value={line.costCode} onChange={(_, data) => changeLine(line.key, 'costCode', data.value)} /></label>
      </div></div>)}
      {!uniqueLinks && <p role="status">Continue each preceding source line at most once. Use New line for an added item.</p>}
      {prior && prior.lines.some(old => !oldLinks.includes(old.id)) && <div><h3>Source lines removed in this revision</h3><ul>{prior.lines.filter(old => !oldLinks.includes(old.id)).map(old => <li key={old.id}>Line {old.lineNo}: {old.description} · {old.quantity} {old.unit}</li>)}</ul></div>}
    </Section>
    <Section title="Scope and pricing reference"><div className="cipher-form commercial-form">
      <label className="cipher-field"><span>Inclusions, one per line</span><Textarea aria-label="Estimate inclusions" value={inclusions} onChange={(_, data) => setInclusions(data.value)} /></label>
      <label className="cipher-field"><span>Exclusions, one per line</span><Textarea aria-label="Estimate exclusions" value={exclusions} onChange={(_, data) => setExclusions(data.value)} /></label>
      <label className="cipher-field"><span>Price source reference, if supplied</span><Input aria-label="Price source reference" value={book} onChange={(_, data) => setBook(data.value)} /></label>
      <label className="cipher-field"><span>Contingency (%)</span><Input aria-label="Contingency percentage" inputMode="decimal" value={contingency} aria-invalid={contingency !== '' && rateFromPercent(contingency) === null} onChange={(_, data) => setContingency(data.value)} /></label>
    </div><p className="cipher-caption">Enter the intended contingency explicitly. The existing estimate engine accepts 0–50%; this does not establish an owner policy. Source-preserving handoff currently requires zero contingency because allocation semantics remain unqualified.</p>
      {removedNow.length > 0 && <div><h3>Confirm removed exclusions</h3>{removedNow.map(value => <Checkbox key={value} checked={removed.includes(value)} label={`Remove exclusion: ${value}`} onChange={(_, data) => setRemoved(current => data.checked ? [...current.filter(item => item !== value), value] : current.filter(item => item !== value))} />)}</div>}
    </Section>
    <Section title={prior ? 'Review the complete successor' : 'Review the complete manual estimate'}>
      {!valid && <p role="status">Complete the source, manual line facts and explicit contingency before review. Confirm each removed exclusion in a revision.</p>}
      {prior ? <ActionPanel action="estimate.revise" id={prior.id} version={prior.version} body={revisionBody} inputValid={valid} permitted={allowed} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />
        : <ActionPanel action="estimate.create" id={p.project.id} version={p.version} body={body} inputValid={valid} permitted={allowed} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />}
    </Section>
    {prior && <DrawingFacts source={prior.source} />}
  </>;
}
