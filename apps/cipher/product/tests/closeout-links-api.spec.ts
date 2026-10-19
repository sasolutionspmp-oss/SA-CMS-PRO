import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { listCloseoutLinks, verifyCloseoutLink } from '../src/api/closeout-links';
import type { CloseoutLink } from '../src/api/closeout.generated';
import { artifact, hash, noEffects, people, scope } from './engineering-fixture';
import { unitManifest } from './engineering-packages-fixture';
import { documentBase, libraryDefinition } from './document-control-fixture';
import { expand, source, scope as qualityScope, people as qualityPeople } from './field-fixture';
import { noEffects as qualityNoEffects } from './quality-safety-fixture';

type Kind = CloseoutLink['kind'];
type Fixture = ReturnType<typeof engineeringFixture>;
const kinds: Kind[] = ['engineering_check', 'document_adoption', 'quality_closure'];
const base = () => ({ id: randomUUID(), ...scope, scope_type: 'Project', author_person: people[0].person, author_user: people[0].user, created_at: '2026-10-17T05:00:00Z', status: 'working', no_effects: noEffects });

function engineeringFixture() {
  const subject: any = { ...base(), parent_id: randomUUID(), family_id: randomUUID(), revision_number: 1, predecessor: null, package_revision: randomUUID(), package_digest: hash('assignment'), checker: { person: people[1].person, user: people[1].user }, source_citations: [], drawing_references: [], artifacts: [], definition: { title: 'Pump design basis', criteria: 'Exact authored design basis', assumptions: '', design_codes: [], change_reason: 'Initial revision' }, quantities: [], unit_manifest: null };
  subject.unit_manifest = unitManifest(subject.id, false);
  const primary: any = { ...base(), status: 'checked', parent_id: subject.parent_id, subject_kind: 'basis', subject_id: subject.id, subject_digest: hash(subject), package_revision: subject.package_revision, package_digest: subject.package_digest, checker: subject.checker, preparer_person: subject.author_person, packet_id: randomUUID(), decision_id: randomUUID(), comments: 'Independent check', outcome: 'checked', issue_authorized: false, sealed: false };
  return { scope, api: 'engineering_packages', primaryKind: 'check', primary, subject, revision: subject, records: new Map<string, any>([['check', primary], ['basis', subject]]), label: 'Pump design basis · Rev. 1 · Checked', rebind: () => { primary.subject_digest = hash(subject); } };
}
function adoptionFixture(): Fixture {
  const revision: any = { ...documentBase(), parent_id: randomUUID(), predecessor: null, revision_number: 2, definition: structuredClone(libraryDefinition), artifacts: [structuredClone(artifact)] };
  const subject: any = { ...documentBase(), parent_id: revision.parent_id, library_revision: revision.id, library_digest: hash(revision), definition: { purpose: 'Use exact specification', target_locator: 'Section 03 30 00', change_reason: 'Initial adoption' }, artifacts: revision.artifacts };
  const primary: any = { ...documentBase(0, 'adopted'), parent_id: subject.id, subject_id: subject.id, subject_digest: hash(subject), packet_id: randomUUID(), decision_id: randomUUID(), checked_by_person: people[1].person, effect_digest: hash('accepted adoption'), artifacts: revision.artifacts, electronic_signature: false, professional_seal: false, external_delivery: false, commercial_execution: false };
  return { scope, api: 'document_control', primaryKind: 'adoption', primary, subject, revision, records: new Map<string, any>([['adoption', primary], ['adoption_request', subject], ['library_revision', revision]]), label: `${libraryDefinition.title} · Rev. 2 · Adopted`, rebind: () => { subject.library_digest = hash(revision); primary.subject_digest = hash(subject); } };
}
function qualityFixture(): Fixture {
  const item = randomUUID(), captured = expand(source);
  const qbase = () => ({ id: randomUUID(), ...qualityScope, scope_type: 'Project', author_person: qualityPeople[0].person, author_user: qualityPeople[0].user, created_at: '2026-10-17T05:00:00Z', status: 'recorded', no_effects: qualityNoEffects });
  const subject: any = { ...qbase(), category: 'deficiency', parent_id: randomUUID(), revision_number: 1, predecessor: null, prior_decision: null, amendment_of: null, amendment_reason: '', definition: { title: 'Pump alignment inspection', local_date: '2026-10-17', location: 'Pump P-101', description: 'Documented alignment review', required_closure_items: [{ item_id: item, description: 'Retain alignment result' }] }, evidence: [captured] };
  const primary: any = { ...qbase(), category: subject.category, parent_id: subject.parent_id, source_revision: subject.id, source_digest: hash(subject), predecessor: randomUUID(), action: 'close', from_status: 'checked', to_status: 'closed', comment: 'Recorded independent closure', evidence: [], closure: [{ item_id: item, evidence: [captured] }], checked_by_person: qualityPeople[1].person };
  return { scope: qualityScope, api: 'quality_safety', primaryKind: 'decision', primary, subject, revision: subject, records: new Map<string, any>([['decision', primary], ['revision', subject]]), label: 'Pump alignment inspection · Pump P-101 · Closed', rebind: () => { primary.source_digest = hash(subject); } };
}
const fixture = (kind: Kind) => kind === 'engineering_check' ? engineeringFixture() : kind === 'document_adoption' ? adoptionFixture() : qualityFixture();
const wrap = (f: Fixture, record: any, kind: string) => ({ record, record_digest: hash(record), ...(f.api === 'engineering_packages' ? { review: kind === 'check' ? null : { state: 'checked', check_id: f.primary.id, packet_id: f.primary.packet_id, issue_authorized: false } } : f.api === 'document_control' ? { library_current: true } : {}) });

async function withFetch(f: Fixture, run: (calls: URL[]) => Promise<void>, options: { status?: number; next?: string | null; items?: any[]; contextStatus?: number } = {}) {
  const original = globalThis.fetch, calls: URL[] = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), 'http://fixture.test'); calls.push(url);
    expect(init?.method).toBe('GET');
    expect(url.pathname).toMatch(new RegExp(`cipher_aec\\.${f.api}\\.api\\.(list_records|get_record)$`));
    expect(url.searchParams.get('company')).toBe(f.scope.company); expect(url.searchParams.get('project')).toBe(f.scope.project);
    expect(init?.body).toBeUndefined();
    const kind = url.searchParams.get('kind')!, primary = kind === f.primaryKind;
    const status = primary ? options.status || 200 : options.contextStatus || 200;
    if (status !== 200) return new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', error: { code: 'fixture_denied', message: 'Current source access is unavailable.' } } }), { status });
    let data: unknown;
    if (url.pathname.endsWith('list_records')) {
      expect(kind).toBe(f.primaryKind); expect(url.searchParams.get('limit')).toBe('25'); expect(url.searchParams.get('count_mode')).toBe('none'); expect(url.searchParams.has('parent_id')).toBe(false);
      data = { items: (options.items || [f.primary]).map(record => wrap(f, record, kind)), limit: 25, count_mode: 'none', total: null, next_cursor: options.next || null };
    } else {
      const record = f.records.get(kind); expect(record).toBeDefined(); expect(url.searchParams.get('record_id')).toBe(record.id); data = wrap(f, record, kind);
    }
    return new Response(JSON.stringify({ message: { schema: 'cipher.api.v1', data } }), { status: 200 });
  };
  try { await run(calls); } finally { globalThis.fetch = original; }
}

for (const kind of kinds) {
  test(`${kind}: authorized scoped pages use exact authored names and reverify the unchanged link`, async () => {
    const f = fixture(kind), controller = new AbortController();
    await withFetch(f, async calls => {
      const page = await listCloseoutLinks(f.scope, kind, 'previous-page', controller.signal);
      expect(page).toEqual({ items: [{ link: { kind, id: f.primary.id, record_digest: hash(f.primary) }, label: f.label }], next_cursor: 'next-page' });
      expect(calls[0].searchParams.get('cursor')).toBe('previous-page');
      await expect(verifyCloseoutLink(f.scope, page.items[0], controller.signal)).resolves.toEqual(page.items[0].link);
      expect(calls.filter(url => url.pathname.endsWith('get_record') && url.searchParams.get('kind') === f.primaryKind)).toHaveLength(1);
    }, { next: 'next-page' });
  });
  for (const status of [403, 404]) test(`${kind}: primary lookup ${status} reaches the caller without choices`, async () => {
    const f = fixture(kind), choice = { link: { kind, id: f.primary.id, record_digest: hash(f.primary) }, label: f.label };
    await withFetch(f, async calls => {
      await expect(listCloseoutLinks(f.scope, kind)).rejects.toMatchObject({ status, code: 'fixture_denied' });
      await expect(verifyCloseoutLink(f.scope, choice)).rejects.toMatchObject({ status, code: 'fixture_denied' });
      expect(calls).toHaveLength(2);
    }, { status });
  });
  test(`${kind}: correctly hashed wrong-Project lookup is rejected`, async () => {
    const f = fixture(kind), choice = { link: { kind, id: f.primary.id, record_digest: hash(f.primary) }, label: f.label }; f.primary.project = 'OTHER';
    await withFetch(f, async calls => {
      await expect(listCloseoutLinks(f.scope, kind)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
      await expect(verifyCloseoutLink(f.scope, choice)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
      expect(calls).toHaveLength(2);
    });
  });
  test(`${kind}: changed fact after selection cannot attach under the listed digest`, async () => {
    const f = fixture(kind);
    await withFetch(f, async calls => {
      const page = await listCloseoutLinks(f.scope, kind), before = calls.length;
      if (kind === 'engineering_check') f.primary.comments = 'Changed check';
      else if (kind === 'document_adoption') f.primary.effect_digest = hash('Changed acceptance');
      else f.primary.comment = 'Changed closure';
      await expect(verifyCloseoutLink(f.scope, page.items[0])).rejects.toMatchObject({ code: 'INVALID_CONTRACT' });
      expect(calls.length - before).toBe(1);
    });
  });
  test(`${kind}: loss of exact contextual source rights prevents listing or attachment`, async () => {
    const f = fixture(kind), choice = { link: { kind, id: f.primary.id, record_digest: hash(f.primary) }, label: f.label };
    await withFetch(f, async () => {
      await expect(listCloseoutLinks(f.scope, kind)).rejects.toMatchObject({ status: 403 });
      await expect(verifyCloseoutLink(f.scope, choice)).rejects.toMatchObject({ status: 403 });
    }, { contextStatus: 403 });
  });
  test(`${kind}: a correctly hashed context from another Project is rejected`, async () => {
    const f = fixture(kind); f.subject.project = 'OTHER'; f.rebind();
    await withFetch(f, async () => { await expect(listCloseoutLinks(f.scope, kind)).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
  });
}

for (const [label, change] of [
  ['subject digest', (f: Fixture) => { f.primary.subject_digest = hash('different subject'); }],
  ['package parent', (f: Fixture) => { f.subject.parent_id = randomUUID(); f.rebind(); }],
  ['package revision', (f: Fixture) => { f.subject.package_revision = randomUUID(); f.rebind(); }],
  ['package digest', (f: Fixture) => { f.subject.package_digest = hash('different package'); f.rebind(); }],
  ['checker', (f: Fixture) => { f.subject.checker = { person: people[2].person, user: people[2].user }; f.rebind(); }],
] as const) test(`engineering check rejects a self-consistent reply with a different ${label}`, async () => {
  const f = engineeringFixture(); change(f); await withFetch(f, async () => { await expect(listCloseoutLinks(f.scope, 'engineering_check')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
});
for (const [label, change] of [
  ['request digest', (f: Fixture) => { f.primary.subject_digest = hash('different request'); }],
  ['request parent', (f: Fixture) => { f.primary.parent_id = randomUUID(); }],
  ['library revision digest', (f: Fixture) => { f.subject.library_digest = hash('different library revision'); f.primary.subject_digest = hash(f.subject); }],
  ['library parent', (f: Fixture) => { f.revision.parent_id = randomUUID(); f.rebind(); }],
  ['retained artifacts', (f: Fixture) => { f.revision.artifacts = [{ ...artifact, revision_id: randomUUID() }]; f.rebind(); }],
] as const) test(`document adoption rejects a self-consistent reply with different ${label}`, async () => {
  const f = adoptionFixture(); change(f); await withFetch(f, async () => { await expect(listCloseoutLinks(f.scope, 'document_adoption')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
});
for (const [label, change] of [
  ['source revision digest', (f: Fixture) => { f.primary.source_digest = hash('different revision'); }],
  ['parent', (f: Fixture) => { f.subject.parent_id = randomUUID(); f.rebind(); }],
  ['ordinary category', (f: Fixture) => { f.subject.category = 'inspection'; f.rebind(); }],
] as const) test(`ordinary closure rejects a self-consistent reply with a different ${label}`, async () => {
  const f = qualityFixture(); change(f); await withFetch(f, async () => { await expect(listCloseoutLinks(f.scope, 'quality_closure')).rejects.toMatchObject({ code: 'INVALID_CONTRACT' }); });
});
test('quality list excludes non-close decisions and other ordinary categories while retaining the next page', async () => {
  const f = qualityFixture(), check = { ...f.primary, id: randomUUID(), action: 'check', from_status: 'submitted', to_status: 'checked', evidence: [expand(source)], closure: [], checked_by_person: null };
  const safety = { ...f.primary, id: randomUUID(), category: 'safety_observation' }, permit = { ...f.primary, id: randomUUID(), category: 'permit_record' };
  await withFetch(f, async calls => {
    await expect(listCloseoutLinks(f.scope, 'quality_closure')).resolves.toEqual({ items: [], next_cursor: 'more-ordinary-decisions' });
    expect(calls).toHaveLength(1); expect(calls[0].searchParams.get('kind')).toBe('decision');
  }, { items: [check, safety, permit], next: 'more-ordinary-decisions' });
});
