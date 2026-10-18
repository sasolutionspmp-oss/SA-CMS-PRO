import { chromium, expect, test, type Page } from '@playwright/test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const harness = '/tests/field-offline-harness.html';
const passphrase = 'Fixture local vault passphrase 2026';
const fixtureMarker = 'OFFLINE-SECRET-OBSERVATION-917643';
test.setTimeout(90000);

async function boot(page: Page, baseURL?: string) {
  await page.goto(baseURL ? new URL(harness, baseURL).href : harness);
  await page.waitForFunction(() => Boolean((window as any).offlineTest?.FieldOfflineVault && (window as any).offlineTest?.engineeringDigest));
  await page.evaluate(({ passphrase, fixtureMarker }) => {
    const w = window as any;
    const context = { origin: location.origin, company: 'Offline Fixture Company', project: 'OFFLINE-PROJECT', person: 'OFFLINE-PERSON', device: '11111111-1111-4111-8111-111111111111', user: 'offline.fixture@example.invalid', identityActive: true, canRead: true };
    const source = { id: 'OFFLINE-SECRET-SOURCE-917643', title: 'Offline confidential source fixture', company: context.company, project: context.project, current_revision: 'offline-source-revision-917643', revision_number: 1, filename: 'offline-fixture.txt', mime_type: 'text/plain', byte_length: 17, sha256: 'a'.repeat(64), scan_status: 'clean', extraction_status: 'ready', page_count: 1 };
    const command = { action: 'create', family: 'daily', definition: { local_date: '2026-10-17', superintendent_user: context.user, weather: '', weather_sources: [], crews: [], activities: [fixtureMarker], delays: [], visitors: [] }, photos: [], quantities: [] };
    const envelope = { schema: 'cipher.field.offline.v1', device_id: context.device, capture_id: '22222222-2222-4222-8222-222222222222', company: context.company, project: context.project, actor_person: context.person, actor_user: context.user, captured_at: '2026-10-17T14:30:00-04:00', command };
    w.vaultFixture = { context, source, command, envelope, passphrase, options: { expiresAt: new Date(Date.now() + 86400000).toISOString(), retainEncrypted: true, label: 'Offline browser fixture' } };
    w.testVaults ||= {};
  }, { passphrase, fixtureMarker });
}

async function create(page: Page, name = 'primary', withCapture = false) {
  return page.evaluate(async ({ name, withCapture }) => {
    const w = window as any, f = w.vaultFixture, vault = new w.offlineTest.FieldOfflineVault(); w.testVaults[name] = vault;
    await vault.create(f.context, f.passphrase, f.options);
    if (withCapture) { await vault.update((value: any) => { value.sources = [f.source]; }); await vault.seal(f.envelope); }
    return { unlocked: vault.unlocked, captures: vault.snapshot().captures.length };
  }, { name, withCapture });
}

async function stored(page: Page) {
  return page.evaluate(async () => {
    const w = window as any;
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open(w.offlineTest.OFFLINE_VAULT_DATABASE, 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    try {
      const names = [...db.objectStoreNames];
      const rows = await new Promise<any[]>((resolve, reject) => { const tx = db.transaction('encrypted_profiles', 'readonly'), request = tx.objectStore('encrypted_profiles').getAll(); let rows: any[] = []; request.onsuccess = () => { rows = request.result; }; tx.oncomplete = () => resolve(rows); tx.onabort = () => reject(tx.error); });
      return { names, rows: rows.map(row => ({ ...row, salt: [...row.salt], iv: [...row.iv], ciphertext: [...new Uint8Array(row.ciphertext)], ciphertextDecoded: new TextDecoder().decode(row.ciphertext) })), localStorage: { ...localStorage }, sessionStorage: { ...sessionStorage } };
    } finally { db.close(); }
  });
}

test('encrypted capture survives closing and restarting a real persistent Chromium profile', async ({}, testInfo) => {
  const baseURL = testInfo.project.use.baseURL;
  const launchOptions = testInfo.project.use.launchOptions || {};
  expect(baseURL, 'The browser fixture needs its isolated preview URL.').toBeTruthy();
  const directory = await mkdtemp(join(tmpdir(), 'cipher-field-vault-browser-'));
  let context = await chromium.launchPersistentContext(directory, { ...launchOptions, headless: true });
  try {
    const page = await context.newPage(); await boot(page, baseURL); await create(page, 'primary', true);
    const original = await page.evaluate(async () => {
      const w = window as any, f = w.vaultFixture, vault = w.testVaults.primary, captureId = f.envelope.capture_id;
      const expectedVersion = await w.offlineTest.engineeringDigest({ fixture: 'original staged capture', capture_id: captureId });
      const request = { company: f.context.company, project: f.context.project, operation_id: captureId, capture_id: captureId, expected_version: expectedVersion };
      // Persist the original request before a hypothetical send. No HTTP is made.
      await vault.begin({ method: 'apply', request, operation_id: captureId, actor: { user: f.context.user, personId: f.context.person }, captured_at: '2026-10-17T14:31:00-04:00', envelope: f.envelope });
      await vault.update((value: any) => { value.pending.uncertain = true; });
      return { journal: vault.snapshot().pending, requestDigest: await w.offlineTest.engineeringDigest(request), envelopeDigest: await w.offlineTest.engineeringDigest(f.envelope) };
    });
    expect(original.journal).toMatchObject({ method: 'apply', operation_id: '22222222-2222-4222-8222-222222222222', uncertain: true });
    expect(original.journal.request_digest).toBe(original.requestDigest);
    expect((await stored(page)).rows).toHaveLength(1);
    await context.close();
    context = await chromium.launchPersistentContext(directory, { ...launchOptions, headless: true });
    const restarted = await context.newPage(); await boot(restarted, baseURL);
    const result = await restarted.evaluate(async () => {
      const w = window as any, f = w.vaultFixture, vault = new w.offlineTest.FieldOfflineVault(); w.testVaults.restarted = vault;
      const before = vault.unlocked, value = await vault.unlock(f.context, f.passphrase);
      return { before, after: vault.unlocked, actor: value.captures[0].envelope.actor_person, source: value.sources[0].id, activity: value.captures[0].envelope.command.definition.activities[0], captures: value.captures.length, digest: value.captures[0].digest, recomputed: await w.offlineTest.engineeringDigest(value.captures[0].envelope), pending: value.pending, requestDigest: await w.offlineTest.engineeringDigest(value.pending.request), journalEnvelopeDigest: await w.offlineTest.engineeringDigest(value.pending.envelope) };
    });
    expect(result).toMatchObject({ before: false, after: true, actor: 'OFFLINE-PERSON', source: 'OFFLINE-SECRET-SOURCE-917643', activity: fixtureMarker, captures: 1 });
    expect(result.digest).toBe(result.recomputed);
    expect(result.pending).toEqual(original.journal);
    expect(result.pending).toMatchObject({ method: 'apply', operation_id: result.pending.envelope.capture_id, uncertain: true, request: { operation_id: result.pending.envelope.capture_id, capture_id: result.pending.envelope.capture_id } });
    expect(result.pending.request_digest).toBe(result.requestDigest); expect(result.requestDigest).toBe(original.requestDigest);
    expect(result.journalEnvelopeDigest).toBe(original.envelopeDigest); expect(result.journalEnvelopeDigest).toBe(result.digest);
  } finally { await context.close(); await rm(directory, { recursive: true, force: true }); }
});

test('another Person, project, registration or disabled identity cannot decrypt or display the capture', async ({ page }) => {
  await boot(page); await create(page, 'primary', true);
  const result = await page.evaluate(async () => {
    const w = window as any, f = w.vaultFixture; w.testVaults.primary.close();
    let decryptions = 0; const decrypt = crypto.subtle.decrypt.bind(crypto.subtle);
    Object.defineProperty(crypto.subtle, 'decrypt', { configurable: true, value: (...args: any[]) => { decryptions++; return (decrypt as any)(...args); } });
    const changes = [{ person: 'ANOTHER-PERSON' }, { project: 'ANOTHER-PROJECT' }, { device: '33333333-3333-4333-8333-333333333333' }, { identityActive: false }, { canRead: false }, { origin: 'https://another-origin.invalid' }];
    const attempts = [];
    try {
      for (const change of changes) {
        const vault = new w.offlineTest.FieldOfflineVault(); let code = '', displayed = false;
        try { await vault.unlock({ ...f.context, ...change }, f.passphrase); } catch (error) { code = (error as any).code; }
        try { displayed = Boolean(vault.snapshot()); } catch {}
        attempts.push({ code, unlocked: vault.unlocked, displayed }); vault.close();
      }
      return { decryptions, attempts };
    } finally { delete (crypto.subtle as any).decrypt; }
  });
  expect(result.decryptions).toBe(0);
  expect(result.attempts.map(row => row.code)).toEqual(['profile_missing', 'profile_missing', 'profile_missing', 'wrong_context', 'wrong_context', 'wrong_context']);
  expect(result.attempts.every(row => !row.unlocked && !row.displayed)).toBe(true);
  await expect(page.locator('body')).not.toContainText(fixtureMarker);
});

test('denying the current identity or read access also clears an already-unlocked vault instance', async ({ page }) => {
  await boot(page); await create(page, 'primary', true);
  const attempts = await page.evaluate(async () => {
    const w = window as any, f = w.vaultFixture, vault = w.testVaults.primary; const results = [];
    for (const change of [{ identityActive: false }, { canRead: false }]) {
      if (!vault.unlocked) await vault.unlock(f.context, f.passphrase);
      let code = '', displayed = false;
      try { await vault.unlock({ ...f.context, ...change }, f.passphrase); } catch (error) { code = (error as any).code; }
      const unlocked = vault.unlocked; try { displayed = Boolean(vault.snapshot()); } catch {}
      results.push({ code, unlocked, displayed }); vault.lock();
    }
    return results;
  });
  expect(attempts).toEqual(Array(2).fill({ code: 'wrong_context', unlocked: false, displayed: false }));
});

test('IndexedDB contains only ciphertext and bounded metadata, and credential fields are rejected', async ({ page }) => {
  await boot(page); await create(page, 'primary', true);
  const before = await stored(page);
  expect(before.names).toEqual(['encrypted_profiles']); expect(before.rows).toHaveLength(1);
  expect(Object.keys(before.rows[0]).sort()).toEqual(['ciphertext', 'ciphertextDecoded', 'expires_at', 'format', 'id', 'iv', 'revision', 'salt']);
  expect(before.rows[0].ciphertext.length).toBeGreaterThan(16); expect(before.rows[0].salt).toHaveLength(16); expect(before.rows[0].iv).toHaveLength(12);
  const serialized = JSON.stringify(before);
  for (const secret of [fixtureMarker, 'OFFLINE-PERSON', 'OFFLINE-PROJECT', 'Offline Fixture Company', 'offline.fixture@example.invalid', 'OFFLINE-SECRET-SOURCE-917643', 'offline-source-revision-917643', passphrase, 'superintendent_user', 'actor_person', 'captures', 'CryptoKey']) expect(serialized).not.toContain(secret);
  expect(before.localStorage).toEqual({}); expect(before.sessionStorage).toEqual({});
  const rejected = await page.evaluate(async () => {
    const w = window as any, vault = w.testVaults.primary; const attempts = [];
    for (const key of ['password', 'passphrase', 'access_token', 'refresh_token', 'csrf_token', 'authorization', 'cookie', 'credentials']) {
      let code = ''; try { await vault.update((value: any) => { value[key] = 'FIXTURE-CREDENTIAL-SHOULD-NEVER-PERSIST'; }); } catch (error) { code = (error as any).code; } attempts.push(code);
    }
    return attempts;
  });
  expect(rejected).toEqual(Array(8).fill('vault_invalid')); expect(await stored(page)).toEqual(before);
});

test('a wrong local passphrase exposes no capture and leaves the original encrypted profile recoverable', async ({ page }) => {
  await boot(page); await create(page, 'primary', true); const before = await stored(page);
  const result = await page.evaluate(async () => {
    const w = window as any, f = w.vaultFixture; w.testVaults.primary.close(); const vault = new w.offlineTest.FieldOfflineVault(); let code = '', displayed = false;
    try { await vault.unlock(f.context, 'Different fixture local passphrase 2026'); } catch (error) { code = (error as any).code; }
    const unlocked = vault.unlocked; try { displayed = Boolean(vault.snapshot()); } catch {}
    const recovered = await vault.unlock(f.context, f.passphrase); return { code, unlocked, displayed, activity: recovered.captures[0].envelope.command.definition.activities[0] };
  });
  expect(result).toEqual({ code: 'unlock_failed', unlocked: false, displayed: false, activity: fixtureMarker }); expect(await stored(page)).toEqual(before);
});

test('duplicate capture UUID replays the same payload and rejects changed content without changing saved state', async ({ page }) => {
  await boot(page); await create(page, 'primary', true);
  const replay = await page.evaluate(async () => {
    const w = window as any, vault = w.testVaults.primary, before = vault.snapshot();
    const after = await vault.seal(structuredClone(w.vaultFixture.envelope));
    return { before, after };
  });
  expect(replay.after).toEqual(replay.before); expect(replay.after.captures).toHaveLength(1);
  const beforeConflict = await stored(page);
  const conflict = await page.evaluate(async () => {
    const w = window as any, vault = w.testVaults.primary, changed = structuredClone(w.vaultFixture.envelope); changed.command.definition.activities = ['CHANGED-CONTENT-SAME-CAPTURE-UUID'];
    let code = ''; try { await vault.seal(changed); } catch (error) { code = (error as any).code; }
    return { code, snapshot: vault.snapshot() };
  });
  expect(conflict.code).toBe('capture_conflict'); expect(conflict.snapshot).toEqual(replay.after); expect(await stored(page)).toEqual(beforeConflict);
});

test('a new locked instance discards only the exact local profile and locks its already-unlocked tab without decryption', async ({ page, context }) => {
  await boot(page); await create(page, 'primary', true); const other = await context.newPage(); await boot(other);
  const result = await other.evaluate(async () => {
    const w = window as any, f = w.vaultFixture, decoy = new w.offlineTest.FieldOfflineVault(); w.testVaults.decoy = decoy;
    await decoy.create({ ...f.context, device: '33333333-3333-4333-8333-333333333333' }, f.passphrase, f.options);
    const discarder = new w.offlineTest.FieldOfflineVault(); w.testVaults.discarder = discarder; const before = discarder.unlocked;
    let decryptions = 0; const decrypt = crypto.subtle.decrypt.bind(crypto.subtle); Object.defineProperty(crypto.subtle, 'decrypt', { configurable: true, value: (...args: any[]) => { decryptions++; return (decrypt as any)(...args); } });
    try { await discarder.discardLocal({ ...f.context, user: '', identityActive: false, canRead: false }); }
    finally { delete (crypto.subtle as any).decrypt; }
    return { before, after: discarder.unlocked, decryptions, exists: await discarder.exists(f.context), decoyUnlocked: decoy.unlocked, decoyDevice: decoy.snapshot().ownership.device };
  });
  expect(result).toEqual({ before: false, after: false, decryptions: 0, exists: false, decoyUnlocked: true, decoyDevice: '33333333-3333-4333-8333-333333333333' });
  await page.waitForFunction(() => !(window as any).testVaults.primary.unlocked);
  const displayed = await page.evaluate(() => { try { return Boolean((window as any).testVaults.primary.snapshot()); } catch { return false; } });
  expect(displayed).toBe(false); expect((await stored(page)).rows).toHaveLength(1);
});

test('changing authenticated row metadata, salt or ciphertext prevents unlocking', async ({ page }) => {
  await boot(page); await create(page, 'primary', true);
  const attempts = await page.evaluate(async () => {
    const w = window as any, f = w.vaultFixture; w.testVaults.primary.close();
    const open = () => new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open(w.offlineTest.OFFLINE_VAULT_DATABASE, 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    const db = await open();
    const original: any = await new Promise((resolve, reject) => { const tx = db.transaction('encrypted_profiles', 'readonly'), request = tx.objectStore('encrypted_profiles').getAll(); request.onsuccess = () => resolve(request.result[0]); request.onerror = () => reject(request.error); }); db.close();
    const results = [];
    for (const mutation of ['revision', 'expiry', 'salt', 'ciphertext']) {
      const row = structuredClone(original);
      if (mutation === 'revision') row.revision++;
      if (mutation === 'expiry') row.expires_at = new Date(Date.parse(row.expires_at) + 3600000).toISOString();
      if (mutation === 'salt') row.salt[0] ^= 1;
      if (mutation === 'ciphertext') new Uint8Array(row.ciphertext)[0] ^= 1;
      const writeDb = await open(); await new Promise<void>((resolve, reject) => { const tx = writeDb.transaction('encrypted_profiles', 'readwrite'); tx.objectStore('encrypted_profiles').put(row); tx.oncomplete = () => resolve(); tx.onabort = () => reject(tx.error); }); writeDb.close();
      const vault = new w.offlineTest.FieldOfflineVault(); let code = ''; try { await vault.unlock(f.context, f.passphrase); } catch (error) { code = (error as any).code; }
      results.push({ mutation, code, unlocked: vault.unlocked }); vault.close();
    }
    return results;
  });
  expect(attempts).toEqual(['revision', 'expiry', 'salt', 'ciphertext'].map(mutation => ({ mutation, code: 'unlock_failed', unlocked: false })));
});

test('an expired stored profile is purged before any decryption', async ({ page }) => {
  await boot(page); await create(page, 'primary', true);
  const result = await page.evaluate(async () => {
    const w = window as any, f = w.vaultFixture; w.testVaults.primary.close();
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open(w.offlineTest.OFFLINE_VAULT_DATABASE, 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    await new Promise<void>((resolve, reject) => { const tx = db.transaction('encrypted_profiles', 'readwrite'), store = tx.objectStore('encrypted_profiles'), request = store.getAll(); request.onsuccess = () => { const row = request.result[0]; row.expires_at = new Date(Date.now() - 1000).toISOString(); store.put(row); }; tx.oncomplete = () => resolve(); tx.onabort = () => reject(tx.error); }); db.close();
    let decryptions = 0; const decrypt = crypto.subtle.decrypt.bind(crypto.subtle); Object.defineProperty(crypto.subtle, 'decrypt', { configurable: true, value: (...args: any[]) => { decryptions++; return (decrypt as any)(...args); } });
    const vault = new w.offlineTest.FieldOfflineVault(); let code = '';
    try { await vault.unlock(f.context, f.passphrase); } catch (error) { code = (error as any).code; } finally { delete (crypto.subtle as any).decrypt; }
    return { code, decryptions, unlocked: vault.unlocked, exists: await vault.exists(f.context) };
  });
  expect(result).toEqual({ code: 'profile_expired', decryptions: 0, unlocked: false, exists: false }); expect((await stored(page)).rows).toHaveLength(0);
});

for (const failure of ['quota', 'abort'] as const) test(`real IndexedDB ${failure} failure rejects the save and retains the original encrypted state`, async ({ page }) => {
  await boot(page); await create(page); const before = await stored(page);
  const result = await page.evaluate(async failure => {
    const w = window as any, vault = w.testVaults.primary, originalPut = IDBObjectStore.prototype.put; let injected = false;
    IDBObjectStore.prototype.put = function (this: IDBObjectStore, ...args: Parameters<IDBObjectStore['put']>) {
      if (this.name === 'encrypted_profiles' && !injected) {
        injected = true;
        if (failure === 'quota') throw new DOMException('Fixture quota is full.', 'QuotaExceededError');
        const request = originalPut.apply(this, args); this.transaction.abort(); return request;
      }
      return originalPut.apply(this, args);
    };
    let outcome = 'resolved', code = '', name = '', message = '';
    try { await vault.update((value: any) => { value.draft = w.vaultFixture.command; }); }
    catch (error) { outcome = 'rejected'; code = String((error as any).code); name = (error as any).name; message = (error as any).message; }
    finally { IDBObjectStore.prototype.put = originalPut; }
    return { outcome, code, name, message, injected, hasDraft: Boolean(vault.snapshot().draft), captures: vault.snapshot().captures.length };
  }, failure);
  expect(result).toMatchObject({ outcome: 'rejected', injected: true, hasDraft: false, captures: 0 });
  if (failure === 'quota') expect(result.name).toBe('QuotaExceededError'); else { expect(result.code).toBe('storage_failed'); expect(result.message).toContain('Not saved'); }
  expect(await stored(page)).toEqual(before);
});

test('concurrent tabs admit one encrypted write and reject the stale compare-and-swap', async ({ page, context }) => {
  await boot(page); await create(page); const other = await context.newPage(); await boot(other);
  await other.evaluate(async () => { const w = window as any, f = w.vaultFixture; w.testVaults.second = new w.offlineTest.FieldOfflineVault(); await w.testVaults.second.unlock(f.context, f.passphrase); });
  const update = (page: Page, name: string, marker: string) => page.evaluate(async ({ name, marker }) => { const w = window as any; try { await w.testVaults[name].update((value: any) => { value.draft = structuredClone(w.vaultFixture.command); value.draft.definition.activities = [marker]; }); return { saved: true, marker, code: '' }; } catch (error) { return { saved: false, marker, code: (error as any).code }; } }, { name, marker });
  const results = await Promise.all([update(page, 'primary', 'FIRST-TAB-WRITE'), update(other, 'second', 'SECOND-TAB-WRITE')]);
  expect(results.filter(row => row.saved)).toHaveLength(1); expect(results.filter(row => row.code === 'vault_conflict')).toHaveLength(1);
  const rows = await stored(page); expect(rows.rows).toHaveLength(1); expect(rows.rows[0].revision).toBe(2);
  const audit = await context.newPage(); await boot(audit); const activity = await audit.evaluate(async () => { const w = window as any, f = w.vaultFixture, vault = new w.offlineTest.FieldOfflineVault(); return (await vault.unlock(f.context, f.passphrase)).draft.definition.activities[0]; });
  expect(activity).toBe(results.find(row => row.saved)!.marker);
});

test('ABA discard and recreation cannot be overwritten by a tab that missed the lock broadcast', async ({ page, context }) => {
  await boot(page);
  // BroadcastChannel is optional in the production adapter. This tab models a
  // missing notification while retaining real IndexedDB and native WebCrypto.
  await page.evaluate(() => { Object.defineProperty(window, 'BroadcastChannel', { configurable: true, value: undefined }); });
  await create(page); const original = (await stored(page)).rows[0];
  const other = await context.newPage(); await boot(other);
  await other.evaluate(async expiresAt => { const w = window as any, f = w.vaultFixture, vault = new w.offlineTest.FieldOfflineVault(); w.testVaults.recreated = vault; await vault.discardLocal(f.context); await vault.create(f.context, f.passphrase, { ...f.options, expiresAt }); }, original.expires_at);
  const recreated = (await stored(page)).rows[0]; expect(recreated.revision).toBe(original.revision); expect(recreated.expires_at).toBe(original.expires_at); expect(recreated.salt).not.toEqual(original.salt);
  const stale = await page.evaluate(async () => { const w = window as any; let code = ''; try { await w.testVaults.primary.update((value: any) => { value.draft = w.vaultFixture.command; }); } catch (error) { code = (error as any).code; } return code; });
  expect(stale).toBe('vault_conflict'); expect((await stored(page)).rows[0]).toEqual(recreated);
});

async function gateNextDerivation(page: Page) {
  await page.evaluate(() => {
    const w = window as any, original = crypto.subtle.deriveKey.bind(crypto.subtle); let held = false;
    w.vaultDerivation = { reached: false, release: undefined };
    Object.defineProperty(crypto.subtle, 'deriveKey', { configurable: true, value: async (...args: any[]) => {
      const key = await (original as any)(...args);
      if (!held) { held = true; w.vaultDerivation.reached = true; await new Promise<void>(resolve => { w.vaultDerivation.release = resolve; }); }
      return key;
    } });
  });
}

test('locking during native key derivation prevents a late create from saving', async ({ page }) => {
  await boot(page); await gateNextDerivation(page);
  await page.evaluate(() => { const w = window as any, f = w.vaultFixture, vault = new w.offlineTest.FieldOfflineVault(); w.testVaults.pending = vault; w.vaultPendingResult = vault.create(f.context, f.passphrase, f.options).then(() => ({ saved: true }), (error: any) => ({ saved: false, code: error.code })); });
  await page.waitForFunction(() => (window as any).vaultDerivation.reached);
  const result = await page.evaluate(async () => { const w = window as any; await w.testVaults.pending.endProfile(true); w.vaultDerivation.release(); const result = await w.vaultPendingResult; delete (crypto.subtle as any).deriveKey; return { ...result, unlocked: w.testVaults.pending.unlocked, exists: await w.testVaults.pending.exists(w.vaultFixture.context) }; });
  expect(result).toEqual({ saved: false, code: 'profile_locked', unlocked: false, exists: false }); expect((await stored(page)).rows).toHaveLength(0);
});

test('a stale unlock cannot clear or expose the new profile opened while derivation was pending', async ({ page }) => {
  await boot(page); await create(page, 'primary', true); await page.evaluate(() => (window as any).testVaults.primary.close()); await gateNextDerivation(page);
  await page.evaluate(() => { const w = window as any, f = w.vaultFixture, vault = new w.offlineTest.FieldOfflineVault(); w.testVaults.switching = vault; w.vaultPendingResult = vault.unlock(f.context, f.passphrase).then(() => ({ opened: true }), (error: any) => ({ opened: false, code: error.code })); });
  await page.waitForFunction(() => (window as any).vaultDerivation.reached);
  const result = await page.evaluate(async () => {
    const w = window as any, f = w.vaultFixture, vault = w.testVaults.switching;
    await vault.create({ ...f.context, project: 'NEXT-OFFLINE-PROJECT' }, f.passphrase, f.options);
    w.vaultDerivation.release(); const old = await w.vaultPendingResult; delete (crypto.subtle as any).deriveKey;
    const snapshot = vault.snapshot(); return { old, unlocked: vault.unlocked, project: snapshot.ownership.project, captures: snapshot.captures.length, sources: snapshot.sources.length };
  });
  expect(result).toEqual({ old: { opened: false, code: 'profile_locked' }, unlocked: true, project: 'NEXT-OFFLINE-PROJECT', captures: 0, sources: 0 });
});
