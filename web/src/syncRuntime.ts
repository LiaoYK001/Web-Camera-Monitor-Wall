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
  const state = await loadSyncState();
  const queued = await loadSyncQueue();
  const merged = new Map<string, SyncMutation>();
  for (const mutation of queued?.mutations ?? []) merged.set(keyOf(mutation), mutation);
  for (const mutation of mutations) merged.set(keyOf(mutation), mergeMutation(merged.get(keyOf(mutation)), mutation));
  if (merged.size > MAX_QUEUE) throw new Error('离线同步队列已满，请先恢复与 Docker 的连接');
  await saveSyncQueue({
    schemaVersion: 1,
    baseRevision: queued?.baseRevision ?? state?.revision ?? 0,
    mutations: [...merged.values()],
  });
  window.dispatchEvent(new CustomEvent('webobs:sync-pending', { detail: merged.size }));
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
  accepted: Array<{ kind: string; id: string; revision: number; unchanged: boolean }>;
  conflicts: SyncConflict[];
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
    cache: 'no-store', credentials: 'same-origin', headers,
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

export async function synchronizeBrowserState(): Promise<LocalSyncState | null> {
  if (!navigator.onLine) return loadSyncState();
  const headers = await browserDeviceHeaders();
  let state = await pull(headers, await loadSyncState());
  const queue = await loadSyncQueue();
  if (queue?.mutations.length && !state.conflicts.length) {
    const requestQueue = queue.baseRevision > state.revision
      ? { ...queue, baseRevision: state.revision }
      : queue;
    const response = await fetch('/api/v2/client/sync', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(requestQueue satisfies LocalSyncQueue),
    });
    const result = await checkedJson<SyncResponse>(response);
    if (result.schemaVersion !== 1 || !Number.isSafeInteger(result.revision) ||
        !Array.isArray(result.accepted) || !Array.isArray(result.conflicts))
      throw new Error('浏览器同步提交响应无效');
    if (!result.conflicts.length) await saveSyncQueue(null);
    state = { ...state, conflicts: result.conflicts };
    state = await pull(headers, state);
    state.conflicts = result.conflicts;
  }
  const audit = await loadAuditQueue();
  for (let offset = 0; offset < audit.length; offset += 128) {
    const events = audit.slice(offset, offset + 128);
    const response = await fetch('/api/v2/client/audit/batch', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ events }),
    });
    await checkedJson<{ accepted: number; received: number }>(response);
    await consumeAuditQueue(events.length);
  }
  await saveSyncState(state);
  await cacheSyncedScenes(state.documents);
  return state;
}

export async function resolveSyncConflicts(choice: 'server' | 'local'): Promise<LocalSyncState | null> {
  const state = await loadSyncState();
  if (!state?.conflicts.length) return state;
  if (choice === 'server') await saveSyncQueue(null);
  else {
    const queue = await loadSyncQueue();
    if (queue) await saveSyncQueue({ ...queue, baseRevision: state.revision });
  }
  await saveSyncState({ ...state, conflicts: [] });
  return choice === 'local' ? synchronizeBrowserState() : { ...state, conflicts: [] };
}
