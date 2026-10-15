import { AppLink } from '../app/navigation';
import { KeyFacts, Notice, Section, TechnicalDetails } from '../ui/shared';
import { LibraryStatus, stamp } from './presentation';
import type { Approval, Preview, ReferencePlan, Revision } from './types';
export const kindName = (kind: string) => kind === 'specification_template' ? 'Specification template' : 'Contract clause';
export function TextFacts({ source, label = 'Exact authored source text' }: { source: Preview | Revision; label?: string }) {
  return <div className="library-readback"><KeyFacts facts={[{ label: 'Authored kind', value: kindName(source.kind) }, { label: 'Source title', value: source.title }, { label: 'Original revision', value: String('number' in source ? source.number : source.revisionNumber) }, { label: 'Stored UTF-8 bytes', value: `${source.byteCount.toLocaleString('en-US')} / 65,536` }, { label: 'Encoding', value: source.encoding }, { label: 'Author source locator', value: source.sourceLocator }]} />
    {'targetLocator' in source && source.targetLocator !== null && <KeyFacts facts={[{ label: 'Target project locator', value: source.targetLocator }, { label: 'Reference purpose', value: source.purpose ?? 'Unavailable' }]} />}
    <pre className="library-source-text" role="region" tabIndex={0} aria-label={label}>{source.text}</pre>
    <p className="cipher-caption">Exact authored editor text. No markup executes here. This source does not establish legal execution, professional engineering certification or external issue.</p>
    {'contentHash' in source && <TechnicalDetails entries={[{ label: 'Original authored revision', value: source.id }, { label: 'SHA-256 content', value: source.contentHash }]} />}
  </div>;
}
export function PlanFacts({ plan: p }: { plan: ReferencePlan }) {
  return <><Section title="Original project reference intent"><KeyFacts facts={[{ label: 'Project', value: p.project.name }, { label: 'Target project locator', value: p.targetLocator }, { label: 'Reference purpose', value: p.purpose }, { label: 'Prepared by', value: p.author.displayName }]} /><p>Original creation: <LibraryStatus status={p.creationStatus} /> Current intent: <LibraryStatus status={p.effectiveStatus} /></p></Section>
    <Notice>Internal project reference only. Independent authorization and its separate application do not execute a contract, certify engineering, issue content externally or create a financial obligation.</Notice>
    <Section title="Exact original intent source"><TextFacts source={p.sourceRevision} /><p>Source now: <LibraryStatus status={p.sourceRevision.isCurrent ? 'current' : 'historical'} /></p>{!p.sourceRevision.isCurrent && <AppLink href={`/library-revisions/${encodeURIComponent(p.currentRevisionId)}`}>Open current authored revision</AppLink>}</Section></>;
}
export function ApprovalFacts({ approval: a }: { approval: Approval }) {
  return <Section title="Independent reference authorization"><KeyFacts facts={[{ label: 'Requested by', value: a.requester.displayName }, { label: 'Requested', value: stamp(a.requestedAt) }, { label: 'Independent PM reviewer', value: a.reviewer?.displayName ?? 'Awaiting independent review' }, { label: 'Original review deadline', value: stamp(a.expiresAt) }, { label: 'Granted', value: a.grantedAt ? stamp(a.grantedAt) : 'Not granted' }, { label: 'Applied by', value: a.appliedBy?.displayName ?? 'Not applied' }]} /><p>Original native authorization: <LibraryStatus status={a.status} /> Current authorization: <LibraryStatus status={a.authorizationStatus} /></p></Section>;
}
