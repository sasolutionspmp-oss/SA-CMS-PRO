import type { ProjectDocumentRecord } from './api/types';
import type { FoCommand, FoEnvelope, FoInspectCaptureResponse, FoCaptureSummary, FoCreateRecordResponse } from './api/field-offline.generated';
import { validateOfflineEnvelope } from './api/field-offline';
import { engineeringDigest } from './api/engineering';
import { sameValue } from './api/schema-validation';

export const OFFLINE_VAULT_DATABASE = 'cipher-field-offline-v1';
const STORE = 'encrypted_profiles', FORMAT = 'cipher.field.offline.vault.v1', ITERATIONS = 600000;
export type VaultContext = { origin: string; company: string; project: string; person: string; device: string; user: string; identityActive: boolean; canRead: boolean };
export type OfflineJournal = { method: 'register' | 'revoke' | 'stage' | 'apply' | 'discard' | 'resolve'; request: Record<string, unknown>; operation_id: string; actor: { user: string; personId: string }; request_digest: string; captured_at: string; uncertain: boolean; envelope?: FoEnvelope };
export type LocalCapture = { envelope: FoEnvelope; digest: string; local_state: 'sealed' | 'staged' | 'conflict' | 'committed' | 'discarded' | 'superseded'; summary?: FoCaptureSummary; capture_version?: string; inspection?: FoInspectCaptureResponse; original_receipt?: FoCreateRecordResponse; replaces_capture_id?: string; replacement_reason?: string };
export type VaultDocument = { schema: typeof FORMAT; ownership: { origin: string; company: string; project: string; person: string; device: string }; expires_at: string; retain_encrypted_on_profile_change: boolean; device: { device_id: string; registered_user: string; label: string; status: 'unregistered' | 'active' | 'revoked'; version?: string }; sources: ProjectDocumentRecord[]; captures: LocalCapture[]; draft?: FoCommand; pending?: OfflineJournal };
type StoredRow = { id: string; format: typeof FORMAT; revision: number; expires_at: string; salt: Uint8Array<ArrayBuffer>; iv: Uint8Array<ArrayBuffer>; ciphertext: ArrayBuffer };
const bytes = (length: number) => crypto.getRandomValues(new Uint8Array(length));
const encoder = new TextEncoder(), uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
export class VaultError extends Error { constructor(message: string, public code: string) { super(message); this.name = 'VaultError'; } }
const fail = (message: string, code: string): never => { throw new VaultError(message, code); };
const ownership = (context: VaultContext) => ({ origin: context.origin, company: context.company, project: context.project, person: context.person, device: context.device });
const validContext = (context: VaultContext) => context.origin === location.origin && context.identityActive && context.canRead && [context.company, context.project, context.person, context.user].every(value => typeof value === 'string' && value.trim()) && uuid.test(context.device);
const expired = (value: string) => !Number.isFinite(Date.parse(value)) || Date.parse(value) <= Date.now();
const aad = (row: Omit<StoredRow, 'iv' | 'ciphertext'>) => encoder.encode(JSON.stringify({ id: row.id, format: row.format, revision: row.revision, expires_at: row.expires_at, salt: [...row.salt] }));
async function partition(context: VaultContext) { return engineeringDigest(['cipher-field-offline-v1', context.origin, context.company, context.project, context.person, context.device]); }
async function derive(passphrase: string, salt: Uint8Array<ArrayBuffer>) {
  const material = encoder.encode(passphrase);
  try { const imported = await crypto.subtle.importKey('raw', material, 'PBKDF2', false, ['deriveKey']); return await crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: ITERATIONS }, imported, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']); }
  finally { material.fill(0); }
}
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_VAULT_DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' });
    request.onerror = () => reject(request.error || new VaultError('Browser storage is unavailable.', 'storage_unavailable'));
    request.onblocked = () => reject(new VaultError('Close another old Field window before opening local storage.', 'storage_blocked'));
    request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
  });
}
async function read(id: string): Promise<StoredRow | undefined> {
  const db = await database();
  try { return await new Promise((resolve, reject) => { const transaction = db.transaction(STORE, 'readonly'), request = transaction.objectStore(STORE).get(id); let value: StoredRow | undefined; request.onsuccess = () => { value = request.result; }; transaction.oncomplete = () => resolve(value); transaction.onabort = () => reject(transaction.error || new VaultError('Browser storage read was aborted.', 'storage_failed')); transaction.onerror = () => {}; }); }
  finally { db.close(); }
}
async function remove(id: string) {
  const db = await database();
  try { await new Promise<void>((resolve, reject) => { const tx = db.transaction(STORE, 'readwrite', { durability: 'strict' }); tx.oncomplete = () => resolve(); tx.onabort = () => reject(tx.error || new VaultError('Local discard was not saved.', 'storage_failed')); tx.onerror = () => {}; tx.objectStore(STORE).delete(id); }); }
  finally { db.close(); }
}
export async function discardAllLocalFieldProfiles() {
  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('cipher-field-offline-lock-v1') : undefined;
  channel?.postMessage({ type: 'lock-all' });
  const db = await database();
  try { await new Promise<void>((resolve, reject) => { const tx = db.transaction(STORE, 'readwrite', { durability: 'strict' }); tx.oncomplete = () => resolve(); tx.onabort = () => reject(tx.error || new VaultError('Local Field profiles were not discarded.', 'storage_failed')); tx.onerror = () => {}; tx.objectStore(STORE).clear(); }); }
  finally { db.close(); channel?.close(); }
}
const equalBytes = (a: ArrayBuffer | Uint8Array, b: ArrayBuffer | Uint8Array) => { const left = a instanceof Uint8Array ? a : new Uint8Array(a), right = b instanceof Uint8Array ? b : new Uint8Array(b); return left.length === right.length && left.every((value, index) => value === right[index]); };
const sameRow = (a: StoredRow, b: StoredRow) => a.id === b.id && a.format === b.format && a.revision === b.revision && a.expires_at === b.expires_at && equalBytes(a.salt, b.salt) && equalBytes(a.iv, b.iv) && equalBytes(a.ciphertext, b.ciphertext);
async function write(row: StoredRow, expected: StoredRow | undefined, stillCurrent: () => boolean) {
  const db = await database();
  try { await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite', { durability: 'strict' }), store = tx.objectStore(STORE); let failure: Error | undefined;
    tx.oncomplete = () => resolve(); tx.onabort = () => reject(failure || tx.error || new VaultError('Not saved. Browser storage rejected the transaction.', 'storage_failed')); tx.onerror = () => {};
    const request = store.get(row.id);
    request.onsuccess = () => { try {
      const previous = request.result as StoredRow | undefined;
      if (!stillCurrent()) fail('The local profile locked before storage completed.', 'profile_locked');
      if (!expected ? Boolean(previous) : !previous || !sameRow(previous, expected)) fail('Another Field window changed or discarded this local profile. Lock and unlock it again before saving.', 'vault_conflict');
      store.put(row);
    } catch (error) { failure = error instanceof Error ? error : new Error('Not saved.'); tx.abort(); } };
  }); }
  finally { db.close(); }
}
function noCredentials(value: unknown, depth = 0): boolean {
  if (depth > 40) return false;
  if (Array.isArray(value)) return value.every(item => noCredentials(item, depth + 1));
  if (value && typeof value === 'object') return Object.entries(value).every(([key, item]) => !['password', 'pwd', 'passphrase', 'access_token', 'refresh_token', 'csrf_token', 'authorization', 'cookie', 'credentials'].includes(key.toLowerCase()) && noCredentials(item, depth + 1));
  return true;
}
// No network, local/sessionStorage, persisted CryptoKey or plaintext payload store.
// Encrypted blobs are not a defense against active same-origin script execution.
export class FieldOfflineVault {
  private context?: VaultContext; private key?: CryptoKey; private value?: VaultDocument; private row?: StoredRow; private activeId?: string; private retainAfterLock?: boolean; private epoch = 0; private timer?: ReturnType<typeof setTimeout>; private channel?: BroadcastChannel;
  constructor(private onLocked: () => void = () => {}) { this.connect(); }
  connect() {
    if (!this.channel && typeof BroadcastChannel !== 'undefined') { this.channel = new BroadcastChannel('cipher-field-offline-lock-v1'); this.channel.onmessage = event => { if (event.data?.type === 'lock-all' || event.data?.type === 'lock' && event.data.id === (this.activeId || this.row?.id)) this.lock(false); }; }
  }
  get unlocked() { return Boolean(this.key && this.value); }
  snapshot() { if (!this.value || !this.context || expired(this.value.expires_at)) { this.lock(); return fail('Unlock an unexpired profile first.', 'profile_locked'); } return structuredClone(this.value); }
  private current(token: number) { return token === this.epoch && Boolean(this.context && validContext(this.context)); }
  private ensure(token: number) { if (!this.current(token)) fail('Your Field profile changed or locked. Unlock the exact current profile again.', 'profile_locked'); }
  private expiryTimer() { clearTimeout(this.timer); if (this.row) this.timer = setTimeout(() => { void this.endProfile(true); }, Math.min(2147483647, Math.max(0, Date.parse(this.row.expires_at) - Date.now()))); }
  lock(broadcast = true) { const id = this.activeId || this.row?.id; if (this.value) this.retainAfterLock = this.value.retain_encrypted_on_profile_change; this.epoch++; this.key = undefined; this.value = undefined; this.context = undefined; clearTimeout(this.timer); if (broadcast && id) this.channel?.postMessage({ type: 'lock', id }); this.onLocked(); }
  async endProfile(forcePurge = false) { const id = this.activeId || this.row?.id, purge = forcePurge || !(this.value?.retain_encrypted_on_profile_change ?? this.retainAfterLock); this.lock(); const token = this.epoch; if (id && purge) await remove(id); if (this.epoch === token) { this.row = undefined; this.activeId = undefined; this.retainAfterLock = undefined; } }
  close() { this.lock(); this.channel?.close(); this.channel = undefined; }
  async exists(context: VaultContext) { const row = await read(await partition(context)); return Boolean(row && row.revision > 0 && !expired(row.expires_at)); }
  async create(context: VaultContext, passphrase: string, options: { expiresAt: string; retainEncrypted: boolean; label: string }) {
    if (!validContext(context)) { this.lock(); return fail('Select the active canonical person and exact project before creating a local profile.', 'wrong_context'); }
    if (passphrase.length < 14 || passphrase.length > 1024) fail('Use a separate local passphrase of at least 14 characters.', 'passphrase_invalid');
    if (expired(options.expiresAt) || Date.parse(options.expiresAt) > Date.now() + 7 * 86400000) fail('Choose a finite profile expiry within seven days.', 'expiry_invalid');
    this.lock(); this.row = undefined; this.activeId = undefined; this.retainAfterLock = undefined; const token = this.epoch; this.context = structuredClone(context);
    const id = await partition(context); this.ensure(token); this.activeId = id; const salt = bytes(16);
    // An opaque empty reservation precedes PBKDF work. Purge/clear/recreation
    // removes or changes it, so a delayed creator cannot resurrect a profile.
    const reservation: StoredRow = { id, format: FORMAT, revision: 0, expires_at: options.expiresAt, salt, iv: bytes(12), ciphertext: new ArrayBuffer(0) };
    await write(reservation, undefined, () => this.current(token)); this.ensure(token);
    const key = await derive(passphrase, salt); this.ensure(token);
    const value: VaultDocument = { schema: FORMAT, ownership: ownership(context), expires_at: options.expiresAt, retain_encrypted_on_profile_change: options.retainEncrypted, device: { device_id: context.device, registered_user: context.user, label: options.label, status: 'unregistered' }, sources: [], captures: [] };
    const base = { id, format: FORMAT, revision: 1, expires_at: value.expires_at, salt } as const, iv = bytes(12), ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad(base), tagLength: 128 }, key, encoder.encode(JSON.stringify(value))); this.ensure(token);
    await write({ ...base, iv, ciphertext }, reservation, () => this.current(token)); this.ensure(token); this.key = key; this.value = value; this.row = { ...base, iv, ciphertext }; this.expiryTimer(); return this.snapshot();
  }
  async unlock(context: VaultContext, passphrase: string) {
    if (!validContext(context)) { this.lock(); return fail('The current account or project cannot unlock this local profile.', 'wrong_context'); }
    this.lock(); this.row = undefined; this.activeId = undefined; this.retainAfterLock = undefined; const token = this.epoch; this.context = structuredClone(context); const id = await partition(context); this.ensure(token); this.activeId = id; const row = await read(id); this.ensure(token);
    if (!row) { this.lock(); return fail('No encrypted profile exists for this exact person, project and registration.', 'profile_missing'); }
    if (row.format !== FORMAT || !Number.isSafeInteger(row.revision) || row.revision < 1 || row.salt?.length !== 16 || row.iv?.length !== 12 || expired(row.expires_at)) { await remove(id); if (this.epoch === token) this.lock(); return fail('This local profile expired or is invalid. Its encrypted copy was discarded.', 'profile_expired'); }
    try {
      const key = await derive(passphrase, row.salt); this.ensure(token); const clear = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: row.iv, additionalData: aad(row), tagLength: 128 }, key, row.ciphertext); this.ensure(token);
      const value = JSON.parse(new TextDecoder().decode(clear)) as VaultDocument; new Uint8Array(clear).fill(0);
      if (!sameValue(value.ownership, ownership(context)) || value.schema !== FORMAT || value.expires_at !== row.expires_at || expired(value.expires_at)) fail('This encrypted profile belongs to another context or has expired.', 'wrong_context');
      await this.validate(value, context); this.ensure(token); const latest = await read(id); this.ensure(token);
      if (!latest || !sameRow(latest, row)) fail('Another window changed or discarded this profile during unlock.', 'vault_conflict');
      this.key = key; this.value = value; this.row = row; this.expiryTimer(); return this.snapshot();
    } catch (error) { if (this.epoch === token) this.lock(); if (error instanceof VaultError) throw error; return fail('The local passphrase or encrypted profile could not be verified.', 'unlock_failed'); }
  }
  private async validate(value: VaultDocument, context: VaultContext) {
    if (!noCredentials(value) || !sameValue(value.ownership, ownership(context)) || value.device.device_id !== context.device || !Array.isArray(value.captures) || value.captures.length > 25 || !Array.isArray(value.sources) || value.sources.length > 100 || encoder.encode(JSON.stringify(value)).length > 5 * 1024 * 1024) fail('The bounded local profile could not be verified.', 'vault_invalid');
    const seen = new Set<string>();
    for (const capture of value.captures) { validateOfflineEnvelope(capture.envelope, { company: context.company, project: context.project, actor: { user: context.user, personId: context.person } }); if (capture.envelope.device_id !== context.device || capture.envelope.actor_user !== value.device.registered_user || seen.has(capture.envelope.capture_id) || await engineeringDigest(capture.envelope) !== capture.digest) fail('A sealed capture identity or digest changed.', 'capture_conflict'); seen.add(capture.envelope.capture_id); }
    if (value.pending && (value.pending.actor.personId !== context.person || value.pending.request.company !== context.company || value.pending.request.project !== context.project || value.pending.request.device_id && value.pending.request.device_id !== context.device || value.pending.envelope && (value.pending.envelope.device_id !== context.device || value.pending.envelope.company !== context.company || value.pending.envelope.project !== context.project || value.pending.envelope.actor_person !== context.person) || value.pending.operation_id !== value.pending.request.operation_id || await engineeringDigest(value.pending.request) !== value.pending.request_digest)) fail('The original request journal could not be verified.', 'journal_invalid');
  }
  async update(change: (draft: VaultDocument) => void) {
    const token = this.epoch; this.ensure(token); if (!this.key || !this.row || !this.context) fail('Unlock this profile before saving.', 'profile_locked');
    const key = this.key!, previous = this.snapshot(), next = structuredClone(previous), context = structuredClone(this.context!), row = this.row!; change(next);
    if (!sameValue(next.ownership, previous.ownership) || next.expires_at !== previous.expires_at || !sameValue(next.device.device_id, previous.device.device_id) || next.device.registered_user !== previous.device.registered_user) fail('Local ownership and original registration cannot be edited.', 'wrong_context');
    for (const old of previous.captures) { const retained = next.captures.find(item => item.envelope.capture_id === old.envelope.capture_id); if (retained && !sameValue(retained.envelope, old.envelope)) fail('A sealed capture cannot be edited. Prepare a linked replacement.', 'capture_conflict'); }
    if (previous.pending && next.pending && !sameValue({ ...previous.pending, uncertain: false }, { ...next.pending, uncertain: false })) fail('Recover the unchanged original request before creating another.', 'journal_pending');
    await this.validate(next, context); this.ensure(token); const base = { id: row.id, format: FORMAT, revision: row.revision + 1, expires_at: row.expires_at, salt: row.salt } as const, iv = bytes(12);
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad(base), tagLength: 128 }, key, encoder.encode(JSON.stringify(next))); this.ensure(token);
    await write({ ...base, iv, ciphertext }, row, () => this.current(token)); this.ensure(token); this.row = { ...base, iv, ciphertext }; this.value = next; return this.snapshot();
  }
  async seal(envelope: FoEnvelope, metadata?: { replaces: string; reason: string }) {
    const token = this.epoch, original = structuredClone(envelope); this.ensure(token); const digest = await engineeringDigest(original); this.ensure(token);
    return this.update(value => { if (value.pending) fail('Recover the original request before sealing another capture.', 'journal_pending'); const existing = value.captures.find(row => row.envelope.capture_id === original.capture_id); if (existing) { if (existing.digest !== digest) fail('This capture UUID already has different content.', 'capture_conflict'); return; } value.captures.push({ envelope: original, digest, local_state: 'sealed', ...(metadata ? { replaces_capture_id: metadata.replaces, replacement_reason: metadata.reason } : {}) }); delete value.draft; });
  }
  async begin(journal: Omit<OfflineJournal, 'request_digest' | 'uncertain'>) {
    const token = this.epoch, original = structuredClone(journal); this.ensure(token); const request_digest = await engineeringDigest(original.request); this.ensure(token);
    return this.update(value => { if (value.pending) fail('Recover the original request before sending another.', 'journal_pending'); value.pending = { ...original, request_digest, uncertain: false }; });
  }
  async discardLocal(context: VaultContext) { const originalToken = this.epoch, id = await partition(context); if (this.epoch !== originalToken) return fail('The local profile changed before discard. Review the selected profile again.', 'profile_locked'); this.lock(); this.channel?.postMessage({ type: 'lock', id }); const token = this.epoch; await remove(id); if (this.epoch === token) { this.row = undefined; this.activeId = undefined; this.retainAfterLock = undefined; } }
}
