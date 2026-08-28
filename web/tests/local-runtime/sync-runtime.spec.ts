import { expect, test } from '@playwright/test';

test('encrypts offline Scene mutations and performs incremental field-safe synchronization', async ({ page }) => {
  let bootstrapCalls = 0;
  let auditCalls = 0;
  await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
    bootstrapCalls += 1;
    const since = Number(new URL(route.request().url()).searchParams.get('sinceRevision') ?? 0);
    const change = {
      kind: 'scene', id: 'scene-main', revision: 5, deleted: false, updatedAt: 5,
      changedFields: ['name', 'canvas', 'sources', 'items'],
      document: {
        schemaVersion: 5, revision: 5, id: 'scene-main', name: 'Synced fixture',
        canvas: { width: 640, height: 360, backgroundColor: '#000000' },
        sources: [], items: [],
      },
    };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      contractVersion: 2, revision: since < 5 && bootstrapCalls > 1 ? 5 : 4,
      syncPolicy: 'bidirectional-field-conflict-v1',
      sync: { resetRequired: false, documents: [], changes: since < 5 && bootstrapCalls > 1 ? [change] : [] },
    }) });
  });
  await page.route('**/api/v2/client/sync', async (route) => {
    const body = route.request().postDataJSON() as { baseRevision: number; mutations: unknown[] };
    expect(route.request().headers().authorization).toBe(`WebObs-Device ${'d'.repeat(64)}`);
    expect(body.baseRevision).toBe(4);
    expect(body.mutations).toHaveLength(1);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      schemaVersion: 1, revision: 5,
      accepted: [{ kind: 'scene', id: 'scene-main', revision: 5, unchanged: false }], conflicts: [],
    }) });
  });
  await page.route('**/api/v2/client/audit/batch', async (route) => {
    auditCalls += 1;
    const body = route.request().postDataJSON() as { events: Array<{ type: string }> };
    expect(body.events[0].type).toBe('scene.local-save');
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      accepted: body.events.length, received: body.events.length,
    }) });
  });
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    const sync = await import('/src/syncRuntime.ts');
    const future = (Math.floor(Date.now() / 1000) + 60) * 1000;
    await runtime.saveBrowserIdentity({
      enrollmentId: '0123456789abcdef0123456789abcdef', deviceToken: 'd'.repeat(64),
      signingPublicKey: 's'.repeat(43), signingPrivateKey: 'p'.repeat(86),
      encryptionPublicKey: 'e'.repeat(43), encryptionPrivateKey: 'x'.repeat(43),
      clientId: 'abcdef0123456789abcdef0123456789', expiresAt: future,
      grantPayload: { format: 'webobs-browser-grant-v1', contractVersion: 2,
        clientId: 'abcdef0123456789abcdef0123456789', issuedAt: Math.floor(Date.now() / 1000),
        expiresAt: future / 1000, revision: 1, cameras: [] },
    });
    await runtime.saveSyncState({ schemaVersion: 1, revision: 4, documents: [], conflicts: [], lastSyncedAt: Date.now() });
    const studio = {
      schemaVersion: 1 as const, revision: 1, previewSceneId: 'scene-main', programSceneId: 'scene-main',
      transition: { kind: 'cut' as const, durationMs: 0 },
      scenes: [{ schemaVersion: 5 as const, revision: 1, id: 'scene-main', name: 'Offline private edit',
        canvas: { width: 640, height: 360, backgroundColor: '#000000' }, sources: [], items: [] }],
    };
    await runtime.saveStudioSnapshot(studio);
    await sync.queueStudioSync(studio);
    await runtime.queueOfflineAudit('scene.local-save', 'completed');
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const rawQueue = await new Promise<unknown>((resolve, reject) => {
      const request = db.transaction('syncQueue').objectStore('syncQueue').get('queue');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    db.close();
    const synchronized = await sync.synchronizeBrowserState();
    return {
      rawQueue: JSON.stringify(rawQueue), revision: synchronized?.revision,
      name: synchronized?.documents.find((document) => document.id === 'scene-main')?.document?.name,
      queue: await runtime.loadSyncQueue(), conflicts: synchronized?.conflicts.length,
      audit: await runtime.loadAuditQueue(),
    };
  });
  expect(result.rawQueue).not.toContain('Offline private edit');
  expect(result).toMatchObject({ revision: 5, name: 'Synced fixture', queue: null, conflicts: 0, audit: [] });
  expect(bootstrapCalls).toBe(2);
  expect(auditCalls).toBe(1);
});
