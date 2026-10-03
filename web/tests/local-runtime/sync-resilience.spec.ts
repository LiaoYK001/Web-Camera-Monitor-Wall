import { expect, test, type Page, type Route } from '@playwright/test';
import type { SceneDocument, StudioDocument } from '../../src/types';

const fixtureScene: SceneDocument = {
  schemaVersion: 6, revision: 1, id: 'scene-audio', name: 'Private multi-track layout',
  canvas: { width: 640, height: 360, backgroundColor: '#000000' },
  sources: [{ id: 'camera-input', kind: 'camera', name: 'Fixture camera', cameraId: 'camera-fixture',
    profileId: 'sub', hardwareDecode: 'auto', muted: false, volume: 0.37, syncOffsetMs: 120,
    monitoring: 'monitor-and-output', audioTrack: 6, filters: [], audioInputs: [
      { track: 0, gain: 0.4, muted: false, syncOffsetMs: -120 },
      { track: 31, gain: 0.8, muted: true },
    ] }, { id: 'silent-color', kind: 'color', name: 'No input audio', color: '#112233',
    muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1,
    filters: [], audioInputs: [] }],
  items: [{ id: 'camera-item', sourceId: 'camera-input', x: 0, y: 0, width: 640, height: 360,
    scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0,
    visible: true, locked: false, rotation: 0, opacity: 1, blendMode: 'normal' }],
};

async function initialize(page: Page): Promise<void> {
  await page.goto('/');
  await page.evaluate(async (scene) => {
    const runtime = await import('/src/localRuntime.ts');
    const sync = await import('/src/syncRuntime.ts');
    const issuedAt = Math.floor(Date.now() / 1000);
    await runtime.saveBrowserIdentity({
      enrollmentId: '0123456789abcdef0123456789abcdef', deviceToken: 'd'.repeat(64),
      signingPublicKey: 's'.repeat(43), signingPrivateKey: 'p'.repeat(86),
      encryptionPublicKey: 'e'.repeat(43), encryptionPrivateKey: 'x'.repeat(43),
      clientId: 'abcdef0123456789abcdef0123456789', expiresAt: (issuedAt + 3600) * 1000,
      grantPayload: { format: 'webobs-browser-grant-v1', contractVersion: 2,
        clientId: 'abcdef0123456789abcdef0123456789', issuedAt, expiresAt: issuedAt + 3600,
        revision: 1, cameras: [] },
    });
    await runtime.saveSyncState({ schemaVersion: 1, revision: 4, documents: [], conflicts: [], lastSyncedAt: 0 });
    const studio: StudioDocument = {
      schemaVersion: 1, revision: 1, previewSceneId: scene.id, programSceneId: scene.id,
      transition: { kind: 'cut', durationMs: 0 }, scenes: [scene],
    };
    await runtime.saveStudioSnapshot(studio);
    await sync.queueStudioSync(studio);
  }, fixtureScene);
}

function snapshot(scene: SceneDocument, revision: number) {
  return { kind: 'scene', id: scene.id, revision, deleted: false, updatedAt: revision,
    document: scene, changedFields: ['name', 'canvas', 'sources', 'items'] };
}

async function respond(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

test('multi-track sync survives a failed request and browser reload without plaintext storage', async ({ page }) => {
  let failed = false;
  let revision = 4;
  let scene = fixtureScene;
  await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
    const since = Number(new URL(route.request().url()).searchParams.get('sinceRevision'));
    await respond(route, { contractVersion: 2, revision, syncPolicy: 'bidirectional-field-conflict-v1',
      sync: { resetRequired: false, documents: [], changes: revision > since ? [snapshot(scene, revision)] : [] } });
  });
  await page.route('**/api/v2/client/sync', async (route) => {
    const request = route.request().postDataJSON();
    expect(request.mutations[0].fields.sources).toEqual(fixtureScene.sources);
    if (!failed) { failed = true; await respond(route, { error: 'temporary_unavailable' }, 503); return; }
    scene = { ...scene, ...request.mutations[0].fields, revision: ++revision };
    await respond(route, { schemaVersion: 1, revision, conflicts: [],
      accepted: [{ kind: 'scene', id: scene.id, revision, unchanged: false }] });
  });
  await initialize(page);
  const beforeReload = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    const sync = await import('/src/syncRuntime.ts');
    let failed = false;
    try { await sync.synchronizeBrowserState(); } catch { failed = true; }
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const raw = await new Promise<unknown>((resolve, reject) => {
      const request = db.transaction('syncQueue').objectStore('syncQueue').get('queue');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    db.close();
    return { failed, raw: JSON.stringify(raw), queue: await runtime.loadSyncQueue() };
  });
  expect(beforeReload.failed).toBe(true);
  expect(beforeReload.queue?.mutations[0].fields.sources).toEqual(fixtureScene.sources);
  expect(beforeReload.raw).not.toContain('Private multi-track');
  expect(beforeReload.raw).not.toContain('audioInputs');
  await page.reload();
  const afterReload = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    const sync = await import('/src/syncRuntime.ts');
    const state = await sync.synchronizeBrowserState();
    return { scene: state?.documents[0].document, queue: await runtime.loadSyncQueue(),
      cache: (await runtime.loadOfflineStudio())?.studio };
  });
  expect(afterReload.scene).toMatchObject({ schemaVersion: 6, sources: fixtureScene.sources });
  expect(afterReload.queue).toBeNull();
  expect(afterReload.cache?.scenes[0].sources).toEqual(fixtureScene.sources);
});

for (const additionalEdits of [false, true]) {
  test(`an older acknowledgement retains newer saves with additional edits=${additionalEdits}`, async ({ page, context }) => {
    let revision = 4;
    let requests = 0;
    let scene = fixtureScene;
    let unblock!: () => void;
    let started!: () => void;
    const barrier = new Promise<void>((resolve) => { unblock = resolve; });
    const received = new Promise<void>((resolve) => { started = resolve; });
    await context.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
      const since = Number(new URL(route.request().url()).searchParams.get('sinceRevision'));
      await respond(route, { contractVersion: 2, revision, syncPolicy: 'bidirectional-field-conflict-v1',
        sync: { resetRequired: false, documents: [], changes: revision > since ? [snapshot(scene, revision)] : [] } });
    });
    await context.route('**/api/v2/client/sync', async (route) => {
      requests += 1;
      const request = route.request().postDataJSON();
      if (requests === 1) { started(); await barrier; }
      scene = { ...scene, ...request.mutations[0].fields, revision: ++revision };
      await respond(route, { schemaVersion: 1, revision, conflicts: [],
        accepted: request.mutations.map((mutation: { kind: string; id: string }) =>
          ({ kind: mutation.kind, id: mutation.id, revision, unchanged: false })) });
    });
    await initialize(page);
    const inFlight = page.evaluate(async () => {
      const sync = await import('/src/syncRuntime.ts');
      const first = sync.synchronizeBrowserState();
      const second = sync.synchronizeBrowserState();
      const sharedPromise = first === second;
      await Promise.all([first, second]);
      return sharedPromise;
    });
    await received;
    // Another window shares IndexedDB and may save while this request is in flight.
    const other = await context.newPage();
    await other.goto('/');
    const newer = structuredClone(fixtureScene);
    newer.sources[0].audioInputs![0].gain = 0.72;
    await other.evaluate(async ({ scene, additionalEdits }) => {
      const runtime = await import('/src/localRuntime.ts');
      const sync = await import('/src/syncRuntime.ts');
      const studio = (await runtime.loadOfflineStudio())!.studio;
      studio.scenes = [scene];
      await runtime.saveStudioSnapshot(studio);
      await sync.queueStudioSync(studio);
      if (additionalEdits) await Promise.all([
        sync.queueCameraPreference('camera-a', { favorite: true }),
        sync.queueCameraPreference('camera-b', { group: 'Local group' }),
      ]);
    }, { scene: newer, additionalEdits });
    unblock();
    expect(await inFlight).toBe(true);
    expect(requests).toBe(1);
    const queued = await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue());
    expect(queued?.baseRevision).toBe(additionalEdits ? 4 : 5); // Unsubmitted edits retain conflict detection.
    expect(queued?.mutations).toHaveLength(additionalEdits ? 3 : 1);
    expect(queued?.mutations.find((mutation) => mutation.kind === 'scene')?.fields.sources).toEqual(newer.sources);
    const local = await page.evaluate(async () => (await (await import('/src/localRuntime.ts')).loadOfflineStudio())?.studio);
    expect(local?.scenes[0].sources).toEqual(newer.sources);
    await page.evaluate(async () => (await import('/src/syncRuntime.ts')).synchronizeBrowserState());
    expect(requests).toBe(2);
    expect(scene.sources).toEqual(newer.sources);
    expect(await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue())).toBeNull();
    await other.close();
  });
}

for (const choice of ['local', 'server'] as const) {
  test(`multi-track conflicts survive a failed pull and resolve with ${choice} choice`, async ({ page }) => {
    const serverScene = structuredClone(fixtureScene);
    serverScene.revision = 5;
    serverScene.sources[0].audioInputs = [];
    let conflict = true;
    let failPull = false;
    let revision = 5;
    await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
      if (failPull) { failPull = false; await respond(route, {}, 503); return; }
      await respond(route, { contractVersion: 2, revision, syncPolicy: 'bidirectional-field-conflict-v1',
        sync: { resetRequired: false, documents: [snapshot(serverScene, revision)], changes: [] } });
    });
    await page.route('**/api/v2/client/sync', async (route) => {
      const request = route.request().postDataJSON();
      if (conflict) {
        failPull = true;
        await respond(route, { schemaVersion: 1, revision, accepted: [], conflicts: [
          { kind: 'scene', id: fixtureScene.id, fields: [
            { field: 'sources', serverValue: serverScene.sources, serverRevision: revision }] }] }, 409);
      } else {
        expect(request.baseRevision).toBe(choice === 'local' ? 5 : 4);
        if (choice === 'local') {
          expect(request.mutations[0].fields.sources).toEqual(fixtureScene.sources);
          Object.assign(serverScene, request.mutations[0].fields);
        } else expect(request.mutations.every((mutation: { kind: string }) => mutation.kind !== 'scene')).toBe(true);
        revision += 1;
        await respond(route, { schemaVersion: 1, revision, conflicts: [],
          accepted: request.mutations.map((mutation: { kind: string; id: string }) =>
            ({ kind: mutation.kind, id: mutation.id, revision, unchanged: false })) });
      }
    });
    await initialize(page);
    const failed = await page.evaluate(async () => {
      try { await (await import('/src/syncRuntime.ts')).synchronizeBrowserState(); return false; }
      catch { return true; }
    });
    expect(failed).toBe(true);
    await page.reload();
    const pending = await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncState());
    expect(pending?.conflicts[0].fields[0].serverValue).toEqual(serverScene.sources);
    // A subsequent successful pull refreshes the cursor but leaves conflict resolution explicit.
    await page.evaluate(async () => (await import('/src/syncRuntime.ts')).synchronizeBrowserState());
    await page.evaluate(async () => (await import('/src/syncRuntime.ts'))
      .queueCameraPreference('camera-other', { favorite: true }));
    conflict = false;
    await page.evaluate(async (choice) => (await import('/src/syncRuntime.ts')).resolveSyncConflicts(choice), choice);
    if (choice === 'server') {
      const queue = await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue());
      expect(queue?.mutations).toHaveLength(1);
      expect(queue?.mutations[0].kind).toBe('camera-preference');
      await page.evaluate(async () => (await import('/src/syncRuntime.ts')).synchronizeBrowserState());
    }
    expect(serverScene.sources[0].audioInputs).toEqual(choice === 'local' ? fixtureScene.sources[0].audioInputs : []);
    expect(await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue())).toBeNull();
  });
}

test('a large encrypted queue is submitted in bounded batches without duplicate mutations', async ({ page }) => {
  let revision = 4;
  const submitted: string[] = [];
  const sizes: number[] = [];
  await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
    await respond(route, { contractVersion: 2, revision, syncPolicy: 'bidirectional-field-conflict-v1',
      sync: { resetRequired: false, documents: [], changes: [] } });
  });
  await page.route('**/api/v2/client/sync', async (route) => {
    const request = route.request().postDataJSON();
    sizes.push(request.mutations.length);
    expect(request.mutations.length).toBeLessThanOrEqual(64);
    expect(request.baseRevision).toBe(4);
    submitted.push(...request.mutations.map((mutation: { id: string }) => mutation.id));
    await respond(route, { schemaVersion: 1, revision: ++revision, conflicts: [],
      accepted: request.mutations.map((mutation: { kind: string; id: string }) =>
        ({ kind: mutation.kind, id: mutation.id, revision, unchanged: false })) });
  });
  await initialize(page);
  await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    const sync = await import('/src/syncRuntime.ts');
    await runtime.saveSyncQueue(null);
    await Promise.all(Array.from({ length: 70 }, (_, index) =>
      sync.queueCameraPreference(`camera-${index}`, { favorite: true })));
    await sync.synchronizeBrowserState();
  });
  expect(sizes).toEqual([64, 6]);
  expect(new Set(submitted).size).toBe(70);
  expect(await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue())).toBeNull();
});

test('an incomplete acknowledgement is rejected and leaves encrypted changes pending', async ({ page }) => {
  await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
    await respond(route, { contractVersion: 2, revision: 4, syncPolicy: 'bidirectional-field-conflict-v1',
      sync: { resetRequired: false, documents: [], changes: [] } });
  });
  await page.route('**/api/v2/client/sync', async (route) => {
    await respond(route, { schemaVersion: 1, revision: 5, accepted: [], conflicts: [] });
  });
  await initialize(page);
  const result = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    let failure = '';
    try { await (await import('/src/syncRuntime.ts')).synchronizeBrowserState(); }
    catch (error) { failure = (error as Error).message; }
    return { failure, queue: await runtime.loadSyncQueue() };
  });
  expect(result.failure).toContain('提交响应无效');
  expect(result.queue?.mutations[0].fields.sources).toEqual(fixtureScene.sources);
});

test('nested scene updates stay in one transaction when camera preferences fill the queue', async ({ page }) => {
  let revision = 4;
  let batches = 0;
  await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async (route) => {
    await respond(route, { contractVersion: 2, revision, syncPolicy: 'bidirectional-field-conflict-v1',
      sync: { resetRequired: false, documents: [], changes: [] } });
  });
  await page.route('**/api/v2/client/sync', async (route) => {
    const request = route.request().postDataJSON();
    const scenes = request.mutations.filter((mutation: { kind: string }) => mutation.kind === 'scene');
    if (++batches === 1) expect(scenes.map((scene: { id: string }) => scene.id)).toEqual(['scene-parent', fixtureScene.id]);
    else expect(scenes).toHaveLength(0);
    await respond(route, { schemaVersion: 1, revision: ++revision, conflicts: [],
      accepted: request.mutations.map((mutation: { kind: string; id: string }) =>
        ({ kind: mutation.kind, id: mutation.id, revision, unchanged: false })) });
  });
  await initialize(page);
  await page.evaluate(async (child) => {
    const runtime = await import('/src/localRuntime.ts');
    const sync = await import('/src/syncRuntime.ts');
    const fields = { name: child.name, canvas: child.canvas, sources: child.sources, items: child.items };
    await runtime.saveSyncQueue({ schemaVersion: 1, baseRevision: 4, mutations: [
      { kind: 'scene', id: 'scene-parent', operation: 'upsert', fields: {
        ...fields, sources: [{ id: 'nested', kind: 'nested', name: 'Nested child', sceneId: child.id }], items: [] } },
      ...Array.from({ length: 63 }, (_, index) => ({ kind: 'camera-preference' as const,
        id: `camera-${index}`, operation: 'upsert' as const, fields: { favorite: true } })),
      { kind: 'scene', id: child.id, operation: 'upsert', fields },
    ] });
    await sync.synchronizeBrowserState();
  }, fixtureScene);
  expect(batches).toBe(2);
  expect(await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue())).toBeNull();
});
