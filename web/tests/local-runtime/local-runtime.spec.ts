import { expect, test } from '@playwright/test';

test('encrypts bounded browser state and atomically removes it at expiry', async ({ page, context }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    const future = (Math.floor(Date.now() / 1000) + 60) * 1000;
    await runtime.saveBrowserIdentity({
      enrollmentId: '0123456789abcdef0123456789abcdef', deviceToken: 'd'.repeat(64),
      signingPublicKey: 's'.repeat(43), signingPrivateKey: 'p'.repeat(86),
      encryptionPublicKey: 'e'.repeat(43), encryptionPrivateKey: 'x'.repeat(43),
      clientId: 'abcdef0123456789abcdef0123456789', expiresAt: future,
      grantPayload: {
        format: 'webobs-browser-grant-v1', contractVersion: 2,
        clientId: 'abcdef0123456789abcdef0123456789', issuedAt: Math.floor(Date.now() / 1000),
        expiresAt: future / 1000, revision: 1, cameras: [],
      },
    });
    const studio = {
      schemaVersion: 1 as const, revision: 4, previewSceneId: 'scene-main', programSceneId: 'scene-main',
      transition: { kind: 'cut' as const, durationMs: 0 },
      scenes: [{
        schemaVersion: 5 as const, revision: 4, id: 'scene-main', name: 'Private fixture scene',
        canvas: { width: 640, height: 360, backgroundColor: '#000000' },
        sources: [
          { id: 'camera-main', kind: 'camera' as const, name: 'Camera fixture', cameraId: 'camera-fixture',
            profileId: 'sub', hardwareDecode: 'auto' as const, muted: true, volume: 1, syncOffsetMs: 0,
            monitoring: 'off' as const, audioTrack: 1, filters: [] },
          { id: 'browser-private', kind: 'browser' as const, name: 'Private URL', url: 'https://private.invalid/?token=secret',
            muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [] },
        ],
        items: [
          { id: 'item-camera', sourceId: 'camera-main', x: 0, y: 0, width: 640, height: 360,
            scaleMode: 'contain' as const, crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0,
            visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const },
          { id: 'item-browser', sourceId: 'browser-private', x: 0, y: 0, width: 320, height: 180,
            scaleMode: 'contain' as const, crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 1,
            visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const },
        ],
      }],
    };
    await runtime.saveStudioSnapshot(studio);
    await runtime.saveLocalStudio({ ...studio, revision: 5 });
    const offline = await runtime.loadOfflineStudio();
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const storeNames = Array.from(database.objectStoreNames);
    const transaction = database.transaction(['identity', 'snapshot', 'localScenes'], 'readonly');
    const read = (store: string, key: string) => new Promise<unknown>((resolve, reject) => {
      const request = transaction.objectStore(store).get(key);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const raw = await Promise.all([
      read('identity', 'browser-device'), read('snapshot', 'studio'), read('localScenes', 'studio'),
    ]);
    database.close();
    return {
      storeNames, raw: JSON.stringify(raw), offline,
      sourceKinds: offline?.studio.scenes[0].sources.map((source) => source.kind),
    };
  });
  expect(result.storeNames).toEqual(['auditQueue', 'identity', 'localScenes', 'runtimeMeta', 'snapshot', 'syncQueue', 'syncState']);
  expect(result.raw).not.toContain('d'.repeat(64));
  expect(result.raw).not.toContain('private.invalid');
  expect(result.sourceKinds).toEqual(['camera']);
  expect(result.offline?.studio.revision).toBe(5);

  await context.setOffline(true);
  const expired = await page.evaluate(async () => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const transaction = database.transaction('identity', 'readwrite');
    const store = transaction.objectStore('identity');
    const record = await new Promise<Record<string, unknown>>((resolve, reject) => {
      const request = store.get('browser-device');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    record.expiresAt = Date.now() - 1;
    store.put(record, 'browser-device');
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
    });
    database.close();
    const runtime = await import('/src/localRuntime.ts');
    const state = await runtime.localConfigState();
    const verification = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const counts = await Promise.all(['identity', 'snapshot', 'localScenes', 'auditQueue', 'syncQueue', 'syncState'].map((name) =>
      new Promise<number>((resolve, reject) => {
        const request = verification.transaction(name).objectStore(name).count();
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      })));
    verification.close();
    return { state, counts };
  });
  expect(expired).toEqual({ state: 'offline-expired', counts: [0, 0, 0, 0, 0, 0] });
});

test('migrates the v1 IndexedDB schema and fails closed on material clock rollback', async ({ page }) => {
  // Use the inert same-origin fallback page so the mounted application cannot
  // reopen schema v2 between deleteDatabase() and the deliberate v1 fixture.
  await page.goto('/offline.html');
  const result = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    await runtime.clearAllLocalRuntimeData();
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1', 1);
      request.onupgradeneeded = () => {
        for (const name of ['identity', 'snapshot', 'localScenes', 'auditQueue', 'runtimeMeta'])
          request.result.createObjectStore(name);
      };
      request.onsuccess = () => { request.result.close(); resolve(); };
      request.onerror = () => reject(request.error);
    });
    await runtime.saveSyncState({ schemaVersion: 1, revision: 0, documents: [], conflicts: [], lastSyncedAt: Date.now() });
    const future = (Math.floor(Date.now() / 1000) + 3600) * 1000;
    await runtime.saveBrowserIdentity({
      enrollmentId: '0123456789abcdef0123456789abcdef', deviceToken: 'd'.repeat(64),
      signingPublicKey: 's'.repeat(43), signingPrivateKey: 'p'.repeat(86),
      encryptionPublicKey: 'e'.repeat(43), encryptionPrivateKey: 'x'.repeat(43),
      clientId: 'abcdef0123456789abcdef0123456789', expiresAt: future,
      grantPayload: { format: 'webobs-browser-grant-v1', contractVersion: 2,
        clientId: 'abcdef0123456789abcdef0123456789', issuedAt: Math.floor(Date.now() / 1000),
        expiresAt: future / 1000, revision: 1, cameras: [] },
    });
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const stores = Array.from(database.objectStoreNames);
    const transaction = database.transaction('runtimeMeta', 'readwrite');
    transaction.objectStore('runtimeMeta').put({ highWater: Date.now() + 10 * 60 * 1000 }, 'clock');
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
    });
    database.close();
    const state = await runtime.localConfigState();
    const verification = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const identityCount = await new Promise<number>((resolve, reject) => {
      const request = verification.transaction('identity').objectStore('identity').count();
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    verification.close();
    return { stores, state, identityCount };
  });
  expect(result.stores).toEqual(['auditQueue', 'identity', 'localScenes', 'runtimeMeta', 'snapshot', 'syncQueue', 'syncState']);
  expect(result.state).toBe('offline-expired');
  expect(result.identityCount).toBe(0);
});
