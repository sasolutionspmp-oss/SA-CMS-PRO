import { useState } from 'react';
import { Button, Input, Select, Textarea } from '@fluentui/react-components';
import { AppLink } from '../app/navigation';
import { KeyFacts, Notice, Section } from '../ui/shared';
import { ActionPanel } from './ActionPanel';
import { textBytes, validAuthoredText } from './client';
import { memoryKey, useLibraryMemory } from './Memory';
import { LibraryHeader, type Controls } from './presentation';
import { kindName, TextFacts } from './records';
import type { CreateBody, EntryDetail, Kind, Preparation, ReferenceBody, RevisionDetail, ReviseBody } from './types';
const plain = (value: string, maximum = 1000) => !!value.trim() && value.length <= maximum && !/[\u0000-\u001f\u007f]/.test(value);
export function AuthoredForm({ preparation, entry, ...controls }: Controls & { preparation?: Preparation; entry?: EntryDetail }) {
  const memory = useLibraryMemory(); const action = entry ? 'library.revise' : 'library.create'; const id = entry?.id ?? preparation!.project.id;
  const [, refreshAttempt] = useState(0);
  const original = memory.get(memoryKey(action, id))?.prepared; const saved = original && 'text' in original.body ? original.body : null;
  const [kind, setKind] = useState<Kind | ''>(saved && 'kind' in saved ? saved.kind : entry?.kind ?? ''); const [title, setTitle] = useState(saved && 'title' in saved ? saved.title : entry?.title ?? '');
  const [text, setText] = useState(saved?.text ?? entry?.currentRevision.text ?? ''); const [locator, setLocator] = useState(saved?.sourceLocator ?? entry?.currentRevision.sourceLocator ?? ''); const [reason, setReason] = useState(saved && 'changeReason' in saved ? saved.changeReason : '');
  const [previousId, setPreviousId] = useState(saved && 'previousRevisionId' in saved ? saved.previousRevisionId : entry?.currentRevision.id ?? '');
  const predecessor = entry?.revisions.find(source => source.id === previousId);
  const valid = !!kind && plain(title, 200) && validAuthoredText(text) && plain(locator) && (!entry || plain(reason));
  const create: CreateBody = { kind: kind || 'specification_template', title: title.trim(), text, sourceLocator: locator.trim() };
  const revise: ReviseBody = { previousRevisionId: previousId, text, sourceLocator: locator.trim(), changeReason: reason.trim() };
  const project = entry?.project ?? preparation!.project; const permitted = controls.session.duties.includes('pm') && controls.session.projectIds.includes(project.id) && (!entry || previousId === entry.currentRevision.id);
  const attempt = memory.get(memoryKey(action, id)); const canUseCurrent = entry && previousId !== entry.currentRevision.id && (!attempt?.prepared || !!attempt.receipt);
  return <><div className="cipher-breadcrumb"><AppLink href="/library-entries">Authored library</AppLink>{entry && <AppLink href={`/library-entries/${encodeURIComponent(entry.id)}`}>Original authored entry</AppLink>}</div>
    <LibraryHeader title={entry ? 'Revise authored source text' : 'Author a library entry'} subtitle={project.name} /><Notice>Author your own exact specification template or contract clause. This editor stores UTF-8 text; licensed content ingestion and external distribution remain unavailable.</Notice>
    {entry && predecessor && <Section title="Read-only predecessor"><KeyFacts facts={[{ label: 'Original kind', value: kindName(entry.kind) }, { label: 'Original title', value: entry.title }, { label: 'Previous authored revision', value: String(predecessor.number) }, { label: 'Previous stored UTF-8 bytes', value: String(predecessor.byteCount) }]} /><p>The original revision ID remains fixed for this attempted successor. Existing project reference copies remain intact.</p><details><summary>Read exact predecessor text</summary><TextFacts source={predecessor} label="Exact predecessor authored text" /></details></Section>}
    {canUseCurrent && <><p>The current predecessor changed. Choose it explicitly, retain the editor text and provide a fresh revision reason.</p><Button onClick={() => { memory.delete(memoryKey(action, id)); setPreviousId(entry.currentRevision.id); setReason(''); }}>Use current authored predecessor</Button></>}
    <Section title="Exact authored editor text"><div className="cipher-form library-editor-form">
      {!entry && <><label className="cipher-field"><span>Library entry kind</span><Select aria-label="Library entry kind" value={kind} onChange={(_, data) => setKind(data.value as Kind | '')}><option value="">Choose an authored kind</option>{preparation!.kinds.map(kind => <option key={kind} value={kind}>{kindName(kind)}</option>)}</Select></label><label className="cipher-field"><span>Library entry title</span><Input aria-label="Library entry title" maxLength={200} value={title} onChange={(_, data) => setTitle(data.value)} /></label></>}
      <label className="cipher-field"><span>Authored source text</span><Textarea className="library-editor" aria-label="Authored source text" value={text} spellCheck={false} aria-invalid={text !== '' && !validAuthoredText(text)} onChange={(_, data) => setText(data.value)} /></label><p className="library-byte-count" role="status">{textBytes(text).toLocaleString('en-US')} / 65,536 UTF-8 bytes. Multibyte characters use more than one byte. Text is preserved without trimming.</p>
      <label className="cipher-field"><span>{entry ? 'Revision source locator' : 'Author source locator'}</span><Input aria-label={entry ? 'Revision source locator' : 'Author source locator'} maxLength={1000} value={locator} onChange={(_, data) => setLocator(data.value)} /></label>
      {entry && <label className="cipher-field"><span>Revision change reason</span><Input aria-label="Revision change reason" maxLength={1000} value={reason} onChange={(_, data) => setReason(data.value)} /></label>}
    </div></Section><Section title="Review the exact source before storage">{!valid && <p role="status">Complete the authored kind, title and source locator. Enter nonempty valid UTF-8 text within 64 KiB without NUL characters, and a reason for a successor.</p>}
      {entry && predecessor ? <ActionPanel action="library.revise" id={id} version={entry.version} body={revise} context={{ source: predecessor }} permitted={permitted} inputValid={valid} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} onRetired={() => refreshAttempt(value => value + 1)} /> : !entry && <ActionPanel action="library.create" id={id} version={preparation!.version} body={create} permitted={permitted} inputValid={valid} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} />}
    </Section></>;
}
export function ReferenceForm({ revision: r, ...controls }: Controls & { revision: RevisionDetail }) {
  const memory = useLibraryMemory(); const original = memory.get(memoryKey('library.prepareReference', r.id))?.prepared; const saved = original && 'targetLocator' in original.body ? original.body : null;
  const [target, setTarget] = useState(saved?.targetLocator ?? ''); const [purpose, setPurpose] = useState(saved?.purpose ?? ''); const body: ReferenceBody = { targetLocator: target.trim(), purpose: purpose.trim() };
  const permitted = r.isCurrent && controls.session.duties.includes('pm') && controls.session.projectIds.includes(r.project.id);
  return <Section title="Declare this internal project reference"><div className="cipher-form library-form"><label className="cipher-field"><span>Target project locator</span><Input aria-label="Target project locator" maxLength={1000} value={target} onChange={(_, data) => setTarget(data.value)} /></label><label className="cipher-field"><span>Reference purpose</span><Input aria-label="Reference purpose" maxLength={1000} value={purpose} onChange={(_, data) => setPurpose(data.value)} /></label></div><ActionPanel action="library.prepareReference" id={r.id} version={r.version} body={body} context={{ source: r }} permitted={permitted} inputValid={plain(target) && plain(purpose)} csrf={controls.session.csrfToken} onChanged={controls.onChanged} onSessionLost={controls.onSessionLost} /></Section>;
}
