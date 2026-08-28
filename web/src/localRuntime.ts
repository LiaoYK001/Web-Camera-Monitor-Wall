import type { StudioDocument } from './types';
import type { MonitorView } from './monitorView';

const DATABASE = 'webobs-local-v1';
const VERSION = 1;
const LEASE_MS = 7 * 24 * 60 * 60 * 1000;
const STORES = ['identity', 'snapshot', 'localScenes', 'auditQueue', 'runtimeMeta'] as const;
type StoreName = typeof STORES[number];

interface EncryptedRecord {
  version: 1;
  iv: ArrayBuffer;
  ciphertext: ArrayBuffer;
  expiresAt: number;
}

export type LocalConfigState = 'online' | 'offline-valid' | 'offline-expired' | 'empty';

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

export async function saveStudioSnapshot(studio: StudioDocument): Promise<number> {
  const expiresAt = Date.now() + LEASE_MS;
  await put('snapshot', 'studio', await encrypt(redactedStudio(studio), expiresAt));
  await put('runtimeMeta', 'lease', { expiresAt, build: __WEBOBS_BUILD_VERSION__, savedAt: Date.now() });
  window.dispatchEvent(new CustomEvent('webobs:local-state', { detail: 'online' }));
  return expiresAt;
}

export async function saveLocalStudio(studio: StudioDocument): Promise<void> {
  const expiresAt = Date.now() + LEASE_MS;
  await put('localScenes', 'studio', await encrypt({ kind: 'local-only', studio: redactedStudio(studio) }, expiresAt));
  window.dispatchEvent(new CustomEvent('webobs:local-state', { detail: 'offline-valid' }));
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
  const identity = await get<EncryptedRecord>('identity', 'browser-device');
  if (!identity) return null;
  if (identity.expiresAt <= Date.now()) {
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
  if (snapshot.expiresAt <= Date.now()) {
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
    const transaction = db.transaction(['identity', 'snapshot', 'localScenes', 'auditQueue', 'runtimeMeta'], 'readwrite');
    for (const store of ['identity', 'snapshot', 'localScenes', 'auditQueue'] as const) transaction.objectStore(store).clear();
    transaction.objectStore('runtimeMeta').delete('lease');
    transaction.objectStore('runtimeMeta').delete('monitor-view');
    await transactionDone(transaction);
  } finally {
    db.close();
  }
  window.dispatchEvent(new Event('webobs:browser-authorization-cleared'));
}

export async function localConfigState(controlPlaneValidated = false): Promise<LocalConfigState> {
  const lease = await get<{ expiresAt: number }>('runtimeMeta', 'lease');
  const identity = await get<EncryptedRecord>('identity', 'browser-device');
  if (identity && identity.expiresAt <= Date.now()) {
    await clearPrivateRuntimeState();
    return 'offline-expired';
  }
  if (!lease || !identity) return 'empty';
  if (lease.expiresAt <= Date.now()) {
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
}

export async function loadBrowserIdentity(): Promise<StoredBrowserIdentity | null> {
  const record = await get<EncryptedRecord>('identity', 'browser-device');
  if (!record) return null;
  if (record.expiresAt <= Date.now()) {
    await clearPrivateRuntimeState();
    return null;
  }
  return decrypt<StoredBrowserIdentity>(record);
}
