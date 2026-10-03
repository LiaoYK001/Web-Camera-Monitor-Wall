import { expect, test, type Page } from '@playwright/test';
import type { SceneDocument, StudioDocument } from '../../src/types';

const fixture = '/tests/harness/offline-workspace.html#/studio';
const scene: SceneDocument = { schemaVersion: 6, revision: 1, id: 'fixture-device', name: '设备值班布局',
  canvas: { width: 640, height: 360, backgroundColor: '#112233' }, sources: [], items: [] };
const studio: StudioDocument = { schemaVersion: 1, revision: 1, scenes: [scene],
  programSceneId: scene.id, previewSceneId: scene.id, transition: { kind: 'cut', durationMs: 0 } };

async function seed(page: Page, expiresIn = 3600) {
  await page.goto('/tests/harness/offline-workspace.html?seed');
  await page.evaluate(async ({ studio, expiresIn }) => {
    const runtime = await import('/src/localRuntime.ts');
    const issuedAt = Math.floor(Date.now() / 1000);
    // Encrypted-storage fixture only; real signature verification is checked by native UI validation.
    await runtime.saveBrowserIdentity({ enrollmentId: '0123456789abcdef0123456789abcdef', deviceToken: 'd'.repeat(64),
      signingPublicKey: 's'.repeat(43), signingPrivateKey: 'p'.repeat(86), encryptionPublicKey: 'e'.repeat(43), encryptionPrivateKey: 'x'.repeat(43),
      clientId: 'abcdef0123456789abcdef0123456789', expiresAt: (issuedAt + expiresIn) * 1000,
      grantPayload: { format: 'webobs-browser-grant-v1', contractVersion: 2, clientId: 'abcdef0123456789abcdef0123456789',
        issuedAt, expiresAt: issuedAt + expiresIn, revision: 1, cameras: [] } });
    await runtime.saveStudioSnapshot(studio);
    await runtime.setDeviceWorkspace(true);
  }, { studio, expiresIn });
}

async function protocol(page: Page) {
  const state = { offline: false, unauthenticated: false, revision: 4, document: structuredClone(scene),
    server: { ...structuredClone(studio), scenes: [{ ...structuredClone(scene), id: 'server-on-air', name: '服务器节目' }],
      programSceneId: 'server-on-air', previewSceneId: 'server-on-air' }, uploads: 0, uploadedIds: [] as string[], coreWrites: 0 };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (state.offline) { await route.abort('connectionfailed'); return; }
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/api/v1/auth/session') return reply({ authenticated: !state.unauthenticated, authenticationEnabled: true, user: 'fixture-admin' }, state.unauthenticated ? 401 : 200);
    if (path === '/api/v1/auth/setup') return reply({ registrationOpen: false });
    if (path === '/api/v1/studio') {
      if (route.request().method() === 'PUT') { state.coreWrites++; state.server = route.request().postDataJSON(); state.server.revision++; }
      return reply(state.server);
    }
    if (path === '/api/v1/cameras') return reply({ cameras: [] });
    if (path.startsWith('/api/v2/account/preferences/')) return reply({ value: null });
    if (path === '/api/v2/client/bootstrap') return reply({ contractVersion: 2, syncPolicy: 'bidirectional-field-conflict-v1', revision: state.revision,
      sync: { resetRequired: false, documents: [{ kind: 'scene', id: state.document.id, revision: state.revision, deleted: false, updatedAt: 1, document: state.document }], changes: [] } });
    if (path === '/api/v2/client/sync') {
      const request = route.request().postDataJSON();
      state.uploadedIds = request.mutations.map((mutation: any) => mutation.id);
      state.uploads++; state.revision++;
      state.document = { ...state.document, ...request.mutations[0].fields, revision: state.revision };
      return reply({ schemaVersion: 1, revision: state.revision, conflicts: [],
        accepted: request.mutations.map((mutation: any) => ({ kind: mutation.kind, id: mutation.id, revision: state.revision, unchanged: false })) });
    }
    if (path === '/api/v2/client/audit/batch') return reply({ accepted: 1, received: 1 });
    return reply({}, 404);
  });
  await page.routeWebSocket('**/api/v1/ws', socket => {
    if (state.offline) { socket.close(); return; }
    socket.send(JSON.stringify({ type: 'scene.snapshot', scene: state.server.scenes[0] }));
  });
  return state;
}

async function rename(page: Page, name: string) {
  await page.getByRole('button', { name: /场景选项$/ }).click();
  await page.getByRole('menuitem', { name: '重命名', exact: true }).click();
  await page.getByRole('dialog', { name: '重命名场景' }).getByRole('textbox', { name: '场景名称', exact: true }).fill(name);
  await page.getByRole('button', { name: '应用到草稿', exact: true }).click();
}

test('paired offline editing saves an encrypted upload and restores the actual Studio after reload', async ({ page }) => {
  const state = await protocol(page);
  await seed(page);
  state.offline = true;
  await page.addInitScript(() => Object.defineProperty(navigator, 'onLine', { get: () => false, configurable: true }));
  await page.goto(fixture);
  await expect(page.locator('.offline-session-banner')).toContainText('离线编辑');
  await rename(page, '断网后保存的布局');
  await page.getByRole('button', { name: '保存设备布局', exact: true }).click();
  await expect(page.locator('.device-workspace-banner')).toContainText('1 项等待同步');
  await page.reload();
  await expect(page.getByRole('button', { name: '选择场景 断网后保存的布局', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'TAKE', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: /场景选项$/ }).click();
  await expect(page.getByRole('menuitem', { name: '打开场景投影 · 新窗口', exact: true })).toBeDisabled();
  const saved = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    return { queue: await runtime.loadSyncQueue(), cached: await runtime.loadOfflineStudio() };
  });
  expect(saved.queue?.mutations[0].fields.name).toBe('断网后保存的布局');
  expect(saved.cached?.studio.scenes[0].name).toBe('断网后保存的布局');
  expect(state.coreWrites).toBe(0);
  state.offline = false;
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'onLine', { get: () => true, configurable: true });
    window.dispatchEvent(new Event('online'));
  });
  await expect.poll(() => state.uploads).toBe(1);
  await expect(page.locator('.offline-session-banner')).toHaveCount(0);
  expect(state.coreWrites).toBe(0);
});

test('reconnect uploads device edits without changing Program; explicit copy enters server Preview', async ({ page }) => {
  const state = await protocol(page);
  await seed(page);
  await page.evaluate(async studio => {
    const sync = await import('/src/syncRuntime.ts');
    await sync.queueStudioSync({ ...studio, scenes: [{ ...studio.scenes[0], name: '恢复网络布局' }] });
  }, studio);
  await page.goto(fixture);
  await expect.poll(() => state.uploads).toBe(1);
  await expect(page.locator('.device-workspace-banner')).toContainText('无待上传修改');
  expect(state.coreWrites).toBe(0);
  const before = structuredClone(state.server.scenes[0]);
  await page.getByRole('button', { name: '复制到服务器预览', exact: true }).click();
  await expect.poll(() => state.coreWrites).toBe(1);
  expect(state.server.programSceneId).toBe('server-on-air');
  expect(state.server.scenes[0]).toEqual(before);
  expect(state.server.previewSceneId).not.toBe('server-on-air');
  expect(state.server.scenes[1].name).toBe('恢复网络布局 · 设备布局');
  await expect(page.locator('.notice-alert')).toContainText('Program 保持原状');
});

test('an explicit authentication rejection clears offline authorization instead of bypassing login', async ({ page }) => {
  const state = await protocol(page);
  await seed(page);
  state.unauthenticated = true;
  await page.goto(fixture);
  await expect(page.getByRole('heading', { name: '登录监控工作台' })).toBeVisible();
  await expect(page.locator('.offline-session-banner')).toHaveCount(0);
  expect(await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadBrowserIdentity())).toBeNull();
});

test('offline authorization expires while the application stays open', async ({ page }) => {
  const state = await protocol(page);
  await seed(page, 5);
  state.offline = true;
  await page.goto(fixture);
  await expect(page.locator('.offline-session-banner')).toBeVisible();
  await expect(page.getByRole('heading', { name: '本地服务暂不可用' })).toBeVisible({ timeout: 10000 });
  await expect(page.locator('.device-workspace-banner')).toHaveCount(0);
});

test('Settings exposes pairing management and keeps conflict choices explicit', async ({ page }) => {
  await protocol(page); await seed(page);
  await page.evaluate(async scene => {
    const runtime = await import('/src/localRuntime.ts');
    await runtime.saveSyncQueue({ schemaVersion: 1, baseRevision: 1, mutations: [
      { kind: 'scene', id: scene.id, operation: 'upsert', fields: { name: '本机改名' } },
      { kind: 'camera-preference', id: 'camera-other', operation: 'upsert', fields: { favorite: true } },
    ] });
    await runtime.saveSyncState({ schemaVersion: 1, revision: 4, documents: [{ kind: 'scene', id: scene.id, revision: 4, deleted: false, updatedAt: 1, document: scene as any }],
      conflicts: [{ kind: 'scene', id: scene.id, fields: [{ field: 'name', serverValue: scene.name, serverRevision: 4 }] }], lastSyncedAt: 0 });
  }, scene);
  await page.goto('/tests/harness/offline-workspace.html#/settings');
  const panel = page.getByRole('region', { name: '设备离线与同步' });
  await expect(panel).toContainText('1 个文档发生冲突');
  await panel.getByRole('button', { name: '配对与授权管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '本地客户端与授权' })).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '采用服务端', exact: true }).click();
  await expect(panel).not.toContainText('个文档发生冲突');
  const queue = await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue());
  expect(queue?.mutations.map(mutation => mutation.id)).toEqual(['camera-other']);
});

test('simultaneous first-use writes share one wrapping key and copied nested scenes preserve the on-air graph', async ({ page }) => {
  await protocol(page); await page.goto('/tests/harness/offline-workspace.html?seed');
  const result = await page.evaluate(async studio => {
    const runtime = await import('/src/localRuntime.ts');
    await runtime.clearAllLocalRuntimeData();
    await Promise.all([runtime.saveLocalStudio(studio), runtime.saveSyncQueue({ schemaVersion: 1, baseRevision: 0, mutations: [] }), runtime.saveSyncState({ schemaVersion: 1, revision: 0, documents: [], conflicts: [], lastSyncedAt: 0 })]);
    const { copyDeviceLayoutToPreview } = await import('/src/deviceWorkspace.ts');
    const child = { ...structuredClone(studio.scenes[0]), id: 'child' };
    const source = { id: 'nested', name: 'Nested', kind: 'nested' as const, sceneId: 'child', muted: true, volume: 1, monitoring: 'off' as const, syncOffsetMs: 0, audioTrack: 1, filters: [] };
    const parent = { ...structuredClone(studio.scenes[0]), sources: [source] };
    const device = { ...studio, scenes: [parent, child] };
    const copy = copyDeviceLayoutToPreview(studio, device);
    let excessive = false;
    try { copyDeviceLayoutToPreview({ ...studio, scenes: Array.from({ length: 64 }, () => studio.scenes[0]) }, device); } catch { excessive = true; }
    return { queue: await runtime.loadSyncQueue(), state: await runtime.loadSyncState(), copy, excessive };
  }, studio);
  expect(result.queue?.schemaVersion).toBe(1); expect(result.state?.schemaVersion).toBe(1);
  expect(result.copy.scenes[0]).toEqual(scene);
  expect(result.copy.programSceneId).toBe(studio.programSceneId);
  expect((result.copy.scenes[1].sources[0] as any).sceneId).toBe(result.copy.scenes[2].id);
  expect(result.excessive).toBe(true);
});

test('editing during an in-flight save keeps the newer draft and adopts the committed revision', async ({ page }) => {
  const state = await protocol(page);
  await seed(page);
  await page.goto(fixture);
  await page.getByRole('button', { name: '返回服务器布局', exact: true }).click();
  await expect(page.locator('.device-workspace-banner')).toHaveCount(0);
  let release: (() => void) | undefined;
  let submitted: StudioDocument | undefined;
  await page.route('**/api/v1/studio', async route => {
    if (route.request().method() !== 'PUT') { await route.fallback(); return; }
    submitted = route.request().postDataJSON();
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...submitted, revision: 2 }) });
  });
  const name = page.getByRole('textbox', { name: '场景名称', exact: true });
  await name.fill('提交中的名称');
  await page.getByRole('button', { name: '保存并应用', exact: true }).click();
  await expect.poll(() => !!release).toBe(true);
  await name.fill('提交后继续编辑的名称');
  release!();
  await expect(name).toHaveValue('提交后继续编辑的名称');
  await expect(page.getByRole('button', { name: '保存并应用', exact: true })).toBeEnabled();
  await expect(page.locator('.revision')).toHaveText('s2');
  expect(submitted?.scenes[0].name).toBe('提交中的名称');
  expect(state.server.programSceneId).toBe('server-on-air');
});

test('logout cancels an in-flight device sync and leaves private queues cleared', async ({ page }) => {
  await protocol(page); await seed(page);
  let release: (() => void) | undefined;
  await page.route('**/api/v2/client/bootstrap?sinceRevision=*', async route => {
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ contractVersion: 2,
      syncPolicy: 'bidirectional-field-conflict-v1', revision: 4, sync: { resetRequired: false, documents: [], changes: [] } }) }).catch(() => undefined);
  });
  await page.goto(fixture);
  await expect.poll(() => !!release).toBe(true);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '登录监控工作台' })).toBeVisible();
  release!();
  const remaining = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    return [await runtime.loadBrowserIdentity(), await runtime.loadSyncState(), await runtime.loadSyncQueue()];
  });
  expect(remaining).toEqual([null, null, null]);
});

test('deleting a never-uploaded scene replaces its pending upsert; pairing controls fit a phone', async ({ page }) => {
  const state = await protocol(page); await seed(page);
  state.offline = true;
  const queued = await page.evaluate(async studio => {
    const sync = await import('/src/syncRuntime.ts');
    const runtime = await import('/src/localRuntime.ts');
    const neverUploaded = { ...studio.scenes[0], id: 'never-uploaded' };
    await sync.queueStudioSync({ ...studio, scenes: [neverUploaded], previewSceneId: neverUploaded.id, programSceneId: neverUploaded.id });
    const replacement = { ...studio.scenes[0], id: 'replacement' };
    await sync.queueStudioSync({ ...studio, scenes: [replacement], previewSceneId: replacement.id, programSceneId: replacement.id });
    return runtime.loadSyncQueue();
  }, studio);
  expect(queued?.mutations.find(mutation => mutation.id === 'never-uploaded')?.operation).toBe('delete');
  expect(queued?.mutations.find(mutation => mutation.id === 'replacement')?.operation).toBe('upsert');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tests/harness/offline-workspace.html#/settings');
  await page.getByRole('button', { name: '配对与授权管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '本地客户端与授权' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  state.offline = false;
  await page.evaluate(async () => { await (await import('/src/syncRuntime.ts')).synchronizeBrowserState(); });
  expect(state.uploads).toBe(1);
  expect(state.uploadedIds).toEqual(['replacement']);
  expect(await page.evaluate(async () => (await import('/src/localRuntime.ts')).loadSyncQueue())).toBeNull();
});

test('login and device synchronization work without modern AbortSignal static helpers', async ({ page }) => {
  await protocol(page); await seed(page);
  await page.addInitScript(() => {
    Object.defineProperty(AbortSignal, 'any', { value: undefined, configurable: true });
    Object.defineProperty(AbortSignal, 'timeout', { value: undefined, configurable: true });
  });
  await page.goto(fixture);
  await expect(page.locator('.device-workspace-banner')).toBeVisible();
  await expect.poll(() => page.evaluate(async () => !!(await (await import('/src/localRuntime.ts')).loadSyncState())?.lastSyncedAt)).toBe(true);
  const expired = await page.evaluate(async () => {
    const { withRequestTimeout } = await import('/src/requestTimeout.ts');
    try {
      await withRequestTimeout(10, signal => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason))));
    } catch (reason) { return (reason as Error).name; }
    return 'not-aborted';
  });
  expect(expired).toBe('TimeoutError');
});
