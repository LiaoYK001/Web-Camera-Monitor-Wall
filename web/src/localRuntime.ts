import type { StudioDocument } from './types';
import type { MonitorView } from './monitorView';

const DATABASE = 'webobs-local-v1';
const VERSION = 2;
const LEASE_MS = 7 * 24 * 60 * 60 * 1000;
const STORES = ['identity', 'snapshot', 'localScenes', 'auditQueue', 'runtimeMeta', 'syncQueue', 'syncState'] as const;
type StoreName = typeof STORES[number];

interface EncryptedRecord {
  version: 1;
  iv: ArrayBuffer;
  ciphertext: ArrayBuffer;
  expiresAt: number;
}

export type LocalConfigState = 'online' | 'offline-valid' | 'offline-expired' | 'empty';

export interface SyncMutation {
  kind: 'scene' | 'camera-preference';
  id: string;
  operation: 'upsert' | 'delete';
  fields: Record<string, unknown>;
}

export interface SyncDocument {
  kind: SyncMutation['kind'];
  id: string;
  revision: number;
  deleted: boolean;
  updatedAt: number;
  document: Record<string, unknown> | null;
}

export interface SyncConflict {
  kind: SyncMutation['kind'];
  id: string;
  fields: Array<{ field: string; serverValue: unknown; serverRevision: number }>;
}

export interface LocalSyncState {
  schemaVersion: 1;
  revision: number;
  documents: SyncDocument[];
  conflicts: SyncConflict[];
  lastSyncedAt: number;
}

export interface LocalSyncQueue {
  schemaVersion: 1;
  baseRevision: number;
  mutations: SyncMutation[];
}

export interface OfflineAuditEvent {
  sequence: number;
  type: string;
  outcome: 'accepted' | 'completed' | 'failed' | 'denied' | 'stopped';
  cameraId: string;
  createdAt: number;
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB transaction failed'));
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
  });
}

async function database(): Promise<IDBDatabase> {
  const request = indexedDB.open(DATABASE, VERSION);
  request.onupgradeneeded = () => {
    for (const store of STORES) if (!request.result.objectStoreNames.contains(store)) request.result.createObjectStore(store);
  };
  return requestResult(request);
}

async function wrappingKey(db: IDBDatabase): Promise<CryptoKey> {
  const read = db.transaction('identity', 'readonly');
  const existing = await requestResult(read.objectStore('identity').get('wrapping-key')) as CryptoKey | undefined;
  await transactionDone(read);
  if (existing) return existing;
  const created = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  const write = db.transaction('identity', 'readwrite');
  write.objectStore('identity').put(created, 'wrapping-key');
  await transactionDone(write);
  return created;
}

function assertRedacted(value: unknown): void {
  const serialized = JSON.stringify(value);
  if (/rtsps?:\/\/[^/\s]*@|"(?:password|credentials|credentialsRef|secret|token|rtspUrl|url|filePath|endpoint)"\s*:/i.test(serialized))
    throw new Error('Local PWA snapshots must not contain endpoints or credentials');
}

function redactedStudio(studio: StudioDocument): StudioDocument {
  return {
    ...structuredClone(studio),
    scenes: studio.scenes.map((scene) => {
      const sources = scene.sources.filter((source) =>
        source.kind === 'camera' || source.kind === 'text' || source.kind === 'color' || source.kind === 'nested');
      const sourceIds = new Set(sources.map((source) => source.id));
      return { ...scene, sources: structuredClone(sources), items: scene.items.filter((item) => sourceIds.has(item.sourceId)) };
    }),
  };
}

async function encrypt(value: unknown, expiresAt: number, privateIdentity = false): Promise<EncryptedRecord> {
  if (!privateIdentity) assertRedacted(value);
  const db = await database();
  try {
    const key = await wrappingKey(db);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = new TextEncoder().encode(JSON.stringify(value));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
    return { version: 1, iv: iv.buffer, ciphertext, expiresAt };
  } finally {
    db.close();
  }
}

async function decrypt<T>(record: EncryptedRecord): Promise<T> {
  const db = await database();
  try {
    const key = await wrappingKey(db);
    const plaintext = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: new Uint8Array(record.iv) }, key, record.ciphertext,
    );
    return JSON.parse(new TextDecoder().decode(plaintext)) as T;
  } finally {
    db.close();
  }
}

async function put(store: StoreName, key: IDBValidKey, value: unknown): Promise<void> {
  const db = await database();
  try {
    const transaction = db.transaction(store, 'readwrite');
    transaction.objectStore(store).put(value, key);
    await transactionDone(transaction);
  } finally {
    db.close();
  }
}

async function get<T>(store: StoreName, key: IDBValidKey): Promise<T | undefined> {
  const db = await database();
  try {
    const transaction = db.transaction(store, 'readonly');
    const value = await requestResult(transaction.objectStore(store).get(key)) as T | undefined;
    await transactionDone(transaction);
    return value;
  } finally {
    db.close();
  }
}

async function failClosedNow(): Promise<number | null> {
  const now = Date.now();
  const clock = await get<{ highWater: number }>('runtimeMeta', 'clock');
  if (clock && now + 5 * 60 * 1000 < clock.highWater) return null;
  if (!clock || now > clock.highWater) await put('runtimeMeta', 'clock', { highWater: now });
  return now;
}

export async function saveStudioSnapshot(studio: StudioDocument): Promise<number> {
  const expiresAt = Date.now() + LEASE_MS;
  await put('snapshot', 'studio', await encrypt(redactedStudio(studio), expiresAt));
  await put('runtimeMeta', 'lease', { expiresAt, build: __WEBOBS_BUILD_VERSION__, savedAt: Date.now() });
  await put('runtimeMeta', 'clock', { highWater: Date.now() });
  window.dispatchEvent(new CustomEvent('webobs:local-state', { detail: 'online' }));
  return expiresAt;
}

export async function saveLocalStudio(studio: StudioDocument, announce = true): Promise<void> {
  const expiresAt = Date.now() + LEASE_MS;
  await put('localScenes', 'studio', await encrypt({ kind: 'local-only', studio: redactedStudio(studio) }, expiresAt));
  if (announce) window.dispatchEvent(new CustomEvent('webobs:local-state', { detail: 'offline-valid' }));
}

export async function loadSyncState(): Promise<LocalSyncState | null> {
  const record = await get<EncryptedRecord>('syncState', 'state');
  if (!record || record.expiresAt <= Date.now()) return null;
  try {
    const value = await decrypt<LocalSyncState>(record);
    return value.schemaVersion === 1 ? value : null;
  } catch {
    return null;
  }
}

export async function saveSyncState(state: LocalSyncState): Promise<void> {
  await put('syncState', 'state', await encrypt(state, Date.now() + LEASE_MS));
  window.dispatchEvent(new CustomEvent('webobs:sync-state', { detail: state }));
}

export async function loadSyncQueue(): Promise<LocalSyncQueue | null> {
  const record = await get<EncryptedRecord>('syncQueue', 'queue');
  if (!record || record.expiresAt <= Date.now()) return null;
  try {
    const value = await decrypt<LocalSyncQueue>(record);
    return value.schemaVersion === 1 ? value : null;
  } catch {
    return null;
  }
}

export async function saveSyncQueue(queue: LocalSyncQueue | null): Promise<void> {
  if (!queue) {
    const db = await database();
    try {
      const transaction = db.transaction('syncQueue', 'readwrite');
      transaction.objectStore('syncQueue').delete('queue');
      await transactionDone(transaction);
    } finally {
      db.close();
    }
    return;
  }
  if (queue.mutations.length > 256) throw new Error('Offline sync queue is full');
  await put('syncQueue', 'queue', await encrypt(queue, Date.now() + LEASE_MS));
}

export async function loadAuditQueue(): Promise<OfflineAuditEvent[]> {
  const record = await get<EncryptedRecord>('auditQueue', 'events');
  if (!record || record.expiresAt <= Date.now()) return [];
  try {
    const value = await decrypt<OfflineAuditEvent[]>(record);
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export async function queueOfflineAudit(
  type: string,
  outcome: OfflineAuditEvent['outcome'],
  cameraId = '',
): Promise<void> {
  if (!/^[a-z0-9._-]{1,64}$/.test(type) || !/^[A-Za-z0-9._-]{0,64}$/.test(cameraId))
    throw new Error('Offline audit event is invalid');
  const queue = await loadAuditQueue();
  const random = crypto.getRandomValues(new Uint16Array(1))[0] % 1000;
  queue.push({ sequence: Date.now() * 1000 + random, type, outcome, cameraId, createdAt: Date.now() });
  if (queue.length > 512) queue.splice(0, queue.length - 512);
  await put('auditQueue', 'events', await encrypt(queue, Date.now() + LEASE_MS));
}

export async function consumeAuditQueue(count: number): Promise<void> {
  const queue = await loadAuditQueue();
  const remaining = queue.slice(Math.max(0, count));
  if (!remaining.length) {
    const db = await database();
    try {
      const transaction = db.transaction('auditQueue', 'readwrite');
      transaction.objectStore('auditQueue').delete('events');
      await transactionDone(transaction);
    } finally {
      db.close();
    }
  } else await put('auditQueue', 'events', await encrypt(remaining, Date.now() + LEASE_MS));
}

export async function cacheSyncedScenes(documents: SyncDocument[]): Promise<void> {
  const sceneDocuments = documents.filter((item) => item.kind === 'scene');
  if (!sceneDocuments.length) return;
  const local = await get<EncryptedRecord>('localScenes', 'studio');
  const snapshot = local ?? await get<EncryptedRecord>('snapshot', 'studio');
  if (!snapshot || snapshot.expiresAt <= Date.now()) return;
  const decoded = await decrypt<StudioDocument | { kind: 'local-only'; studio: StudioDocument }>(snapshot);
  const studio = 'kind' in decoded ? decoded.studio : decoded;
  const byId = new Map(studio.scenes.map((scene) => [scene.id, scene]));
  for (const item of sceneDocuments) {
    if (item.deleted) byId.delete(item.id);
    else if (item.document?.schemaVersion === 5) byId.set(item.id, item.document as unknown as StudioDocument['scenes'][number]);
  }
  const scenes = [...byId.values()];
  if (!scenes.length) return;
  const fallback = scenes[0].id;
  await saveLocalStudio({
    ...studio,
    scenes,
    previewSceneId: byId.has(studio.previewSceneId) ? studio.previewSceneId : fallback,
    programSceneId: byId.has(studio.programSceneId) ? studio.programSceneId : fallback,
  }, false);
}

export async function saveMonitorView(view: MonitorView): Promise<void> {
  const expiresAt = Date.now() + LEASE_MS;
  await put('runtimeMeta', 'monitor-view', await encrypt({ kind: 'monitor-view-v1', view }, expiresAt));
}

export async function loadMonitorView(): Promise<MonitorView | null> {
  const record = await get<EncryptedRecord>('runtimeMeta', 'monitor-view');
  if (!record || record.expiresAt <= Date.now()) return null;
  try {
    const decoded = await decrypt<{ kind: 'monitor-view-v1'; view: MonitorView }>(record);
    return decoded.kind === 'monitor-view-v1' ? decoded.view : null;
  } catch {
    return null;
  }
}

export async function loadOfflineStudio(): Promise<{ studio: StudioDocument; state: 'offline-valid'; expiresAt: number } | null> {
  const now = await failClosedNow();
  if (now === null) {
    await clearPrivateRuntimeState();
    return null;
  }
  const identity = await get<EncryptedRecord>('identity', 'browser-device');
  if (!identity) return null;
  if (identity.expiresAt <= now) {
    await clearPrivateRuntimeState();
    return null;
  }
  try {
    const verified = await decrypt<StoredBrowserIdentity>(identity);
    if (!approvedIdentity(verified)) return null;
  } catch {
    await clearPrivateRuntimeState();
    return null;
  }
  const local = await get<EncryptedRecord>('localScenes', 'studio');
  const snapshot = local ?? await get<EncryptedRecord>('snapshot', 'studio');
  if (!snapshot) return null;
  if (snapshot.expiresAt <= now) {
    await clearPrivateRuntimeState();
    window.dispatchEvent(new CustomEvent('webobs:local-state', { detail: 'offline-expired' }));
    return null;
  }
  const decoded = await decrypt<StudioDocument | { kind: 'local-only'; studio: StudioDocument }>(snapshot);
  const studio = 'kind' in decoded ? decoded.studio : decoded;
  window.dispatchEvent(new CustomEvent('webobs:local-state', { detail: 'offline-valid' }));
  return { studio, state: 'offline-valid', expiresAt: snapshot.expiresAt };
}

export async function clearPrivateRuntimeState(): Promise<void> {
  const db = await database();
  try {
    const transaction = db.transaction(['identity', 'snapshot', 'localScenes', 'auditQueue', 'runtimeMeta', 'syncQueue', 'syncState'], 'readwrite');
    for (const store of ['identity', 'snapshot', 'localScenes', 'auditQueue', 'syncQueue', 'syncState'] as const) transaction.objectStore(store).clear();
    transaction.objectStore('runtimeMeta').delete('lease');
    transaction.objectStore('runtimeMeta').delete('monitor-view');
    await transactionDone(transaction);
  } finally {
    db.close();
  }
  window.dispatchEvent(new Event('webobs:browser-authorization-cleared'));
}

export async function localConfigState(controlPlaneValidated = false): Promise<LocalConfigState> {
  const now = await failClosedNow();
  if (now === null) {
    await clearPrivateRuntimeState();
    return 'offline-expired';
  }
  const lease = await get<{ expiresAt: number }>('runtimeMeta', 'lease');
  const identity = await get<EncryptedRecord>('identity', 'browser-device');
  if (identity && identity.expiresAt <= now) {
    await clearPrivateRuntimeState();
    return 'offline-expired';
  }
  if (!lease || !identity) return 'empty';
  if (lease.expiresAt <= now) {
    await clearPrivateRuntimeState();
    return 'offline-expired';
  }
  try {
    if (!approvedIdentity(await decrypt<StoredBrowserIdentity>(identity))) return 'empty';
  } catch {
    await clearPrivateRuntimeState();
    return 'empty';
  }
  return navigator.onLine && controlPlaneValidated ? 'online' : 'offline-valid';
}

export async function requestPersistentStorage(): Promise<boolean> {
  if (!navigator.storage?.persist) return false;
  return navigator.storage.persist();
}

export async function clearAllLocalRuntimeData(): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DATABASE);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error ?? new Error('Could not clear local runtime data'));
    request.onblocked = () => reject(new Error('Local runtime database is busy'));
  });
}

export interface StoredBrowserIdentity {
  enrollmentId: string;
  pairingCode?: string;
  deviceToken: string;
  signingPublicKey: string;
  signingPrivateKey: string;
  encryptionPublicKey: string;
  encryptionPrivateKey: string;
  clientId?: string;
  grantBundle?: Record<string, unknown>;
  grantPayload?: BrowserGrantPayload;
  expiresAt: number;
}

export interface BrowserGrantProfile {
  id: string;
  name: string;
  role: string;
  adapter: 'whep' | 'hls' | 'mjpeg' | string;
  endpoint?: string;
  videoCodec: string;
  audioCodec: string;
  browserDirectEligible: boolean;
  browserDirectReason: string;
}

export interface BrowserGrantPayload {
  format: 'webobs-browser-grant-v1';
  contractVersion: 2;
  clientId: string;
  issuedAt: number;
  expiresAt: number;
  revision: number;
  cameras: Array<{ cameraId: string; name: string; profiles: BrowserGrantProfile[]; permissions: string[] }>;
}

function approvedIdentity(identity: StoredBrowserIdentity): boolean {
  return typeof identity.clientId === 'string' && /^[0-9a-f]{32}$/.test(identity.clientId) &&
    identity.expiresAt > Date.now() && identity.grantPayload?.format === 'webobs-browser-grant-v1' &&
    identity.grantPayload.contractVersion === 2 && identity.grantPayload.clientId === identity.clientId &&
    identity.grantPayload.expiresAt * 1000 === identity.expiresAt;
}

export async function saveBrowserIdentity(identity: StoredBrowserIdentity): Promise<void> {
  const base64url = (value: string, length: number) =>
    value.length === length && new RegExp(`^[A-Za-z0-9_-]{${length}}$`).test(value);
  if (!/^[0-9a-f]{32}$/.test(identity.enrollmentId) || (identity.pairingCode && !/^\d{8}$/.test(identity.pairingCode)) ||
      !base64url(identity.deviceToken, 64) || !base64url(identity.signingPublicKey, 43) ||
      !base64url(identity.signingPrivateKey, 86) || !base64url(identity.encryptionPublicKey, 43) ||
      !base64url(identity.encryptionPrivateKey, 43) || identity.expiresAt <= Date.now() ||
      identity.expiresAt > Date.now() + LEASE_MS + 5 * 60 * 1000 ||
      (identity.clientId !== undefined && !approvedIdentity(identity)))
    throw new Error('Browser identity is invalid or expired');
  await put('identity', 'browser-device', await encrypt(identity, identity.expiresAt, true));
  await put('runtimeMeta', 'clock', { highWater: Date.now() });
}

export async function loadBrowserIdentity(): Promise<StoredBrowserIdentity | null> {
  const now = await failClosedNow();
  if (now === null) {
    await clearPrivateRuntimeState();
    return null;
  }
  const record = await get<EncryptedRecord>('identity', 'browser-device');
  if (!record) return null;
  if (record.expiresAt <= now) {
    await clearPrivateRuntimeState();
    return null;
  }
  return decrypt<StoredBrowserIdentity>(record);
}
