import { browserDeviceHeaders } from './browserEnrollment';
import {
  cacheSyncedScenes,
  clearPrivateRuntimeState,
  consumeAuditQueue,
  loadAuditQueue,
  loadSyncQueue,
  loadSyncState,
  saveSyncQueue,
  saveSyncState,
  type LocalSyncQueue,
  type LocalSyncState,
  type SyncConflict,
  type SyncDocument,
  type SyncMutation,
} from './localRuntime';
import type { StudioDocument } from './types';

const MAX_QUEUE = 256;
const MAX_SYNC_BATCH = 64;
const SYNC_REQUEST_TIMEOUT_MS = 15000;
const runtimeLocks = new Map<string, Promise<unknown>>();
let synchronization: Promise<LocalSyncState | null> | null = null;

async function withRuntimeLock<T>(name: string, operation: () => Promise<T>): Promise<T> {
  const previous = runtimeLocks.get(name) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(() => navigator.locks
    ? navigator.locks.request(`webobs:${name}`, operation)
    : operation());
  runtimeLocks.set(name, next);
  try { return await next; }
  finally { if (runtimeLocks.get(name) === next) runtimeLocks.delete(name); }
}

function keyOf(value: Pick<SyncMutation, 'kind' | 'id'>): string {
  return `${value.kind}\u0000${value.id}`;
}

function mergeDocuments(current: SyncDocument[], incoming: SyncDocument[]): SyncDocument[] {
  const merged = new Map(current.map((document) => [keyOf(document), document]));
  for (const document of incoming) {
    const existing = merged.get(keyOf(document));
    if (!existing || document.revision >= existing.revision) merged.set(keyOf(document), document);
  }
  return [...merged.values()].sort((left, right) => keyOf(left).localeCompare(keyOf(right)));
}

function mergeMutation(current: SyncMutation | undefined, next: SyncMutation): SyncMutation {
  if (!current || next.operation === 'delete' || current.operation === 'delete') return structuredClone(next);
  return { ...next, fields: { ...current.fields, ...next.fields } };
}

async function queueMutations(mutations: SyncMutation[]): Promise<void> {
  return withRuntimeLock('sync-queue', async () => {
    const state = await loadSyncState();
    const queued = await loadSyncQueue();
    const merged = new Map<string, SyncMutation>();
    for (const mutation of queued?.mutations ?? []) merged.set(keyOf(mutation), mutation);
    for (const mutation of mutations) merged.set(keyOf(mutation), mergeMutation(merged.get(keyOf(mutation)), mutation));
    if (merged.size > MAX_QUEUE) throw new Error('离线同步队列已满，请先恢复与服务器的连接');
    await saveSyncQueue({
      schemaVersion: 1,
      baseRevision: queued?.baseRevision ?? state?.revision ?? 0,
      mutations: [...merged.values()],
    });
    window.dispatchEvent(new CustomEvent('webobs:sync-pending', { detail: merged.size }));
  });
}

async function cacheUnqueuedScenes(documents: SyncDocument[]): Promise<void> {
  await withRuntimeLock('sync-queue', async () => {
    const queue = await loadSyncQueue();
    const pending = new Set(queue?.mutations.filter((mutation) => mutation.kind === 'scene')
      .map((mutation) => mutation.id));
    await cacheSyncedScenes(documents.filter((document) => document.kind !== 'scene' || !pending.has(document.id)));
  });
}

async function acknowledgeQueue(request: LocalSyncQueue, result: SyncResponse): Promise<void> {
  await withRuntimeLock('sync-queue', async () => {
    const current = await loadSyncQueue();
    if (!current) return;
    const accepted = new Set(result.accepted.map(keyOf));
    const submitted = new Map(request.mutations.map((mutation) => [keyOf(mutation), mutation]));
    // New saves made while the request was in flight must remain encrypted and queued.
    const mutations = current.mutations.filter((mutation) => !accepted.has(keyOf(mutation)) ||
      JSON.stringify(submitted.get(keyOf(mutation))) !== JSON.stringify(mutation));
    await saveSyncQueue(mutations.length ? {
      ...current, mutations,
      // Rebasing unsubmitted edits could hide another device's genuine conflict.
      baseRevision: !result.conflicts.length && mutations.every((mutation) => accepted.has(keyOf(mutation)))
        ? result.revision : current.baseRevision,
    } : null);
    window.dispatchEvent(new CustomEvent('webobs:sync-pending', { detail: mutations.length }));
  });
}

export async function queueStudioSync(studio: StudioDocument): Promise<void> {
  const state = await loadSyncState();
  const currentSceneIds = new Set(studio.scenes.map((scene) => scene.id));
  const mutations: SyncMutation[] = studio.scenes.map((scene) => {
    const sources = scene.sources.filter((source) => ['camera', 'text', 'color', 'nested'].includes(source.kind));
    const sourceIds = new Set(sources.map((source) => source.id));
    const items = scene.items.filter((item) => sourceIds.has(item.sourceId))
      .sort((left, right) => left.zIndex - right.zIndex)
      .map((item, zIndex) => ({ ...item, zIndex }));
    return {
      kind: 'scene', id: scene.id, operation: 'upsert',
      fields: {
        name: scene.name,
        canvas: structuredClone(scene.canvas),
        sources: structuredClone(sources),
        items: structuredClone(items),
      },
    };
  });
  for (const document of state?.documents ?? []) {
    if (document.kind === 'scene' && !document.deleted && !currentSceneIds.has(document.id))
      mutations.push({ kind: 'scene', id: document.id, operation: 'delete', fields: {} });
  }
  if (mutations.length) await queueMutations(mutations);
}

export async function queueCameraPreference(
  cameraId: string,
  fields: Partial<{ displayName: string; favorite: boolean; group: string }>,
): Promise<void> {
  await queueMutations([{ kind: 'camera-preference', id: cameraId, operation: 'upsert', fields }]);
}

interface BootstrapResponse {
  contractVersion: number;
  revision: number;
  syncPolicy: string;
  sync: { resetRequired: boolean; documents: SyncDocument[]; changes: SyncDocument[] };
}

interface SyncResponse {
  schemaVersion: number;
  revision: number;
  accepted: Array<{ kind: SyncMutation['kind']; id: string; revision: number; unchanged: boolean }>;
  conflicts: SyncConflict[];
}

function validSyncResponse(result: SyncResponse, request: LocalSyncQueue, minimumRevision: number): boolean {
  if (result.schemaVersion !== 1 || !Number.isSafeInteger(result.revision) || result.revision < minimumRevision ||
      !Array.isArray(result.accepted) || !Array.isArray(result.conflicts) ||
      result.accepted.length + result.conflicts.length !== request.mutations.length) return false;
  const mutations = new Map(request.mutations.map((mutation) => [keyOf(mutation), mutation]));
  const seen = new Set<string>();
  for (const entry of result.accepted) {
    if (!entry || !mutations.has(keyOf(entry)) || seen.has(keyOf(entry)) ||
        !Number.isSafeInteger(entry.revision) || entry.revision < 0 || entry.revision > result.revision ||
        typeof entry.unchanged !== 'boolean') return false;
    seen.add(keyOf(entry));
  }
  for (const entry of result.conflicts) {
    if (!entry || seen.has(keyOf(entry))) return false;
    const mutation = mutations.get(keyOf(entry));
    if (!mutation || !Array.isArray(entry.fields) || !entry.fields.length || entry.fields.length > 4) return false;
    const fields = new Set<string>();
    for (const field of entry.fields) {
      if (!field || fields.has(field.field) ||
          !(mutation.operation === 'delete' ? field.field === '*' : Object.hasOwn(mutation.fields, field.field)) ||
          !Object.hasOwn(field, 'serverValue') || !Number.isSafeInteger(field.serverRevision) ||
          field.serverRevision < 0 || field.serverRevision > result.revision) return false;
      fields.add(field.field);
    }
    seen.add(keyOf(entry));
  }
  return true;
}

async function checkedJson<T>(response: Response): Promise<T> {
  if (response.status === 401 || response.status === 403) {
    await clearPrivateRuntimeState();
    throw new Error('浏览器授权已撤销或过期');
  }
  const body = await response.json().catch(() => null) as T | null;
  if (!response.ok && response.status !== 409)
    throw new Error(`浏览器同步失败（HTTP ${response.status}）`);
  if (!body) throw new Error('浏览器同步响应不是有效 JSON');
  return body;
}

async function bootstrap(headers: Record<string, string>, since: number): Promise<BootstrapResponse> {
  const response = await fetch(`/api/v2/client/bootstrap?sinceRevision=${since}`, {
    cache: 'no-store', credentials: 'same-origin', headers, signal: AbortSignal.timeout(SYNC_REQUEST_TIMEOUT_MS),
  });
  if (response.status === 409 && since !== 0) {
    const reset = await bootstrap(headers, 0);
    return { ...reset, sync: { ...reset.sync, resetRequired: true } };
  }
  const body = await checkedJson<BootstrapResponse>(response);
  if (body.contractVersion !== 2 || body.syncPolicy !== 'bidirectional-field-conflict-v1' ||
      !Number.isSafeInteger(body.revision) || !body.sync || !Array.isArray(body.sync.documents) ||
      !Array.isArray(body.sync.changes)) throw new Error('浏览器同步契约版本不匹配');
  return body;
}

async function pull(headers: Record<string, string>, state: LocalSyncState | null): Promise<LocalSyncState> {
  const response = await bootstrap(headers, state?.revision ?? 0);
  const baseDocuments = response.sync.resetRequired ? [] : (state?.documents ?? []);
  const documents = mergeDocuments(
    mergeDocuments(baseDocuments, response.sync.documents), response.sync.changes,
  );
  return {
    schemaVersion: 1,
    revision: response.revision,
    documents,
    conflicts: state?.conflicts ?? [],
    lastSyncedAt: Date.now(),
  };
}

async function performSynchronization(): Promise<LocalSyncState | null> {
  if (!navigator.onLine) return loadSyncState();
  const headers = await browserDeviceHeaders();
  let state = await pull(headers, await loadSyncState());
  const queue = await loadSyncQueue();
  if (queue?.mutations.length && !state.conflicts.length) {
    // Keep nested references/deletions in one transaction rather than splitting
    // a valid scene graph into invalid intermediate graphs.
    const sceneMutations = queue.mutations.filter((mutation) => mutation.kind === 'scene');
    if (sceneMutations.length > MAX_SYNC_BATCH)
      throw new Error('场景变更超过单次 64 项限制；本机内容已保留，请减少同时替换或删除的场景');
    const mutations = [...sceneMutations, ...queue.mutations.filter((mutation) => mutation.kind !== 'scene')];
    // Process a bounded snapshot; saves arriving in flight stay for the next run.
    const baseRevision = Math.min(queue.baseRevision, state.revision);
    for (let offset = 0; offset < mutations.length; offset += MAX_SYNC_BATCH) {
      const requestQueue = { ...queue, baseRevision, mutations: mutations.slice(offset, offset + MAX_SYNC_BATCH) };
      const response = await fetch('/api/v2/client/sync', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        signal: AbortSignal.timeout(SYNC_REQUEST_TIMEOUT_MS),
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(requestQueue satisfies LocalSyncQueue),
      });
      const result = await checkedJson<SyncResponse>(response);
      if (!validSyncResponse(result, requestQueue, state.revision))
        throw new Error('浏览器同步提交响应无效');
      state = { ...state, conflicts: result.conflicts };
      await saveSyncState(state);
      await acknowledgeQueue(requestQueue, result);
      state = await pull(headers, state);
      state.conflicts = result.conflicts;
      if (result.conflicts.length) break;
    }
  }
  const audit = await loadAuditQueue();
  for (let offset = 0; offset < audit.length; offset += 128) {
    const events = audit.slice(offset, offset + 128);
    const response = await fetch('/api/v2/client/audit/batch', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      signal: AbortSignal.timeout(SYNC_REQUEST_TIMEOUT_MS),
      headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ events }),
    });
    await checkedJson<{ accepted: number; received: number }>(response);
    await consumeAuditQueue(events.length);
  }
  await saveSyncState(state);
  await cacheUnqueuedScenes(state.documents);
  return state;
}

export function synchronizeBrowserState(): Promise<LocalSyncState | null> {
  if (synchronization) return synchronization;
  const pending = withRuntimeLock('sync-run', performSynchronization);
  synchronization = pending;
  void pending.finally(() => { if (synchronization === pending) synchronization = null; })
    .catch(() => undefined);
  return pending;
}

export async function resolveSyncConflicts(choice: 'server' | 'local'): Promise<LocalSyncState | null> {
  return withRuntimeLock('sync-run', async () => {
    const state = await loadSyncState();
    if (!state?.conflicts.length) return state;
    await withRuntimeLock('sync-queue', async () => {
      const queue = await loadSyncQueue();
      if (!queue) return;
      if (choice === 'server') {
        const conflicting = new Set(state.conflicts.map(keyOf));
        const mutations = queue.mutations.filter((mutation) => !conflicting.has(keyOf(mutation)));
        await saveSyncQueue(mutations.length ? { ...queue, mutations } : null);
      } else await saveSyncQueue({ ...queue, baseRevision: state.revision });
    });
    await saveSyncState({ ...state, conflicts: [] });
    if (choice === 'server') await cacheUnqueuedScenes(state.documents);
    return choice === 'local' ? performSynchronization() : { ...state, conflicts: [] };
  });
}
