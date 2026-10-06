import { expect, test, type Page, type BrowserContext } from '@playwright/test';
import type { CameraRecord, SceneDocument, StudioDocument } from '../../src/types';

const scene = (id: string, count: number): SceneDocument => ({ schemaVersion: 5, revision: 1, id, name: id === 'main' ? '主场景' : id,
  canvas: { width: 1920, height: 1080, backgroundColor: '#000000' },
  sources: Array.from({ length: count }, (_, index) => ({ id: `color-${index}`, kind: 'color', name: `来源 ${index + 1}`, color: '#214f75', muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] })),
  items: Array.from({ length: count }, (_, index) => ({ id: `item-${index}`, sourceId: `color-${index}`, x: index * 200, y: 100, width: 200, height: 200, scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: index, visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' })),
});
async function backend(context: BrowserContext, rtspPort = 18554) {
  let studio: StudioDocument = { schemaVersion: 1, revision: 1, programSceneId: 'main', previewSceneId: 'main', transition: { kind: 'cut', durationMs: 0 }, scenes: [scene('main', 6)] };
  const preferences = new Map<string, any>(); const cameras: CameraRecord[] = []; const creates: any[] = [];
  await context.routeWebSocket('**/api/v1/ws', (socket) => {
    socket.send(JSON.stringify({ type: 'scene.snapshot', scene: studio.scenes.find((value) => value.id === studio.programSceneId) }));
  });
  await context.route('**/api/**', async (route) => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    const reply = (json: unknown, status = 200) => route.fulfill({ status, json });
    if (path === '/api/v1/auth/session') return reply({ authenticated: true, user: 'test-user', via: 'session' });
    if (path === '/api/v1/auth/setup') return reply({ registrationOpen: false });
    if (path === '/api/v1/runtime/info') return reply({ schema: 1, platform: 'windows', go2rtcRtspBase: `rtsp://127.0.0.1:${rtspPort}/` });
    if (path === '/api/v2/account/me') return reply({ username: 'test-user', displayName: 'Test', avatar: 'camera', roles: ['admin'], permissions: ['settings.manage', 'scene.manage'], scopes: [], acl: [] });
    if (path.startsWith('/api/v2/account/preferences/')) {
      if (method === 'PUT') preferences.set(path, route.request().postDataJSON().value);
      return reply({ value: preferences.get(path) ?? null });
    }
    if (path === '/api/v1/studio') { if (method === 'PUT') { studio = route.request().postDataJSON(); studio.revision++; } return reply(studio); }
    if (path === '/api/v1/scene') return reply(studio.scenes.find((value) => value.id === studio.programSceneId));
    if (path.endsWith('/capabilities')) return reply({ modes: { direct: { enabled: true }, composite: { enabled: false } }, sources: [], scenes: [] });
    if (path === '/api/v1/cameras') {
      if (method === 'POST') { const value = route.request().postDataJSON(); creates.push(value); const camera = { ...value, id: value.id ?? `imported-${cameras.length}`, revision: 1, health: 'unknown', createdAt: 0, updatedAt: 0 }; cameras.push(camera); return reply(camera); }
      return reply({ cameras });
    }
    if (path === '/api/v1/go2rtc/api/streams') return reply({ entrance: { producers: [{ url: 'rtsp://private:do-not-display@camera.invalid/live' }] }, yard: {} });
    if (path === '/api/v1/camera-detect') return reply({ adapter: 'rtsp', address: route.request().postDataJSON().address, probe: 'ready', profiles: [{ id: 'main', name: 'Main', role: 'main', endpoint: route.request().postDataJSON().address, videoCodec: 'h264', audioCodec: '', width: 640, height: 360, fps: 5 }] });
    if (path === '/api/v2/source-catalog') return reply({ schemaVersion: 2, page: 1, limit: 24, total: cameras.length, items: cameras.map((camera) => ({ ...camera, schemaVersion: 2, addressDisplay: camera.address, kind: 'network-stream', enabled: true, groupId: '', tags: [], profileCount: camera.profiles.length, trackCount: 0, deviceCapabilities: { ptz: false, snapshot: false, talk: false }, profiles: camera.profiles.map((profile) => ({ ...profile, endpointDisplay: profile.endpoint, enabled: true, transportMode: 'rtsp-tcp', probeState: 'ready', tracks: [], lastProbeAt: 0, audioExpectation: 'auto' })) })) });
    if (path.endsWith('/probe')) return reply({});
    if (path.includes('analytics')) return reply({ policies: [] });
    if (path.includes('motion-zones')) return reply({ zones: [] });
    if (path === '/api/v2/settings') return reply({ schemaVersion: 1, revision: 1, values: { defaultTransportMode: 'auto', probeTimeoutSeconds: 8, sourceRecoveryEnabled: true, issueRetentionLimit: 512 }, deployment: {} });
    return reply({}, 404);
  });
  return { getStudio: () => studio, preferences, creates };
}
const sceneMenu = async (page: Page, name: string) => {
  await page.getByRole('button', { name: `选择场景 ${name}`, exact: true }).click({ button: 'right' });
  return page.getByRole('dialog', { name: `${name} 场景选项`, exact: true });
};

test('desktop reuses settings, pinned projectors and runtime-assigned go2rtc ports without a PWA worker', async ({ page, context }) => {
  const server = await backend(context, 28554);
  await context.addInitScript(() => {
    const w = window as any;
    let settings = JSON.parse(localStorage.getItem('desktop-fixture') || 'null') || { autoCheck: true, autoDownload: true, startAtLogin: false, minimizeToTray: true, lanEnabled: false, lanPort: 18443, recordingDirectory: '' };
    const state = () => ({ runtime: { phase: 'ready' }, update: { phase: 'disabled' }, settings, recovery: null });
    w.projectorCalls = [];
    w.webobsDesktop = { version: 1, status: async () => state(), settings: async () => settings,
      saveSettings: async (values: any) => { settings = { ...settings, ...values }; localStorage.setItem('desktop-fixture', JSON.stringify(settings)); return settings; },
      onStatus: () => () => {}, reportWork: async () => {}, displays: async () => [{ id: 7, label: '测试副屏', primary: false, bounds: { x: 1920, y: 0, width: 1920, height: 1080 } }],
      projector: async (options: any) => { w.projectorCalls.push(options); return { id: 2 }; } };
  });
  await page.goto('/#settings');
  const desktop = page.getByRole('region', { name: 'Windows 客户端设置' });
  await expect(desktop.getByRole('checkbox', { name: '自动下载更新（安装前仍需确认）' })).toBeChecked();
  await expect(desktop.getByRole('checkbox', { name: '开启局域网 HTTPS 共享' })).not.toBeChecked();
  await desktop.getByRole('checkbox', { name: '自动下载更新（安装前仍需确认）' }).uncheck();
  await page.reload(); await expect(desktop.getByRole('checkbox', { name: '自动下载更新（安装前仍需确认）' })).not.toBeChecked();
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
  await page.goto('/#studio'); const menu = await sceneMenu(page, '主场景');
  await menu.getByLabel('投影显示器').selectOption('7'); await menu.getByRole('checkbox', { name: '全屏投影（Esc 退出全屏）' }).check();
  await menu.getByRole('menuitem', { name: '投影到所选显示器', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).projectorCalls)).toEqual([{ mode: 'direct', sceneId: 'main', displayId: 7, fullscreen: true }]);
  await page.goto('/#devices');
  const row = page.getByRole('region', { name: 'go2rtc 流接入' }).locator('.go2rtc-stream-list > div').filter({ hasText: 'entrance' });
  await row.getByRole('button', { name: '检测并添加设备', exact: true }).click();
  await expect.poll(() => server.creates[0]?.address).toBe('rtsp://127.0.0.1:28554/entrance');
});

test('creates four- and six-source presets, renames them and retains layouts on reload', async ({ page, context }) => {
  const server = await backend(context); await page.goto('/#studio');
  await page.getByRole('button', { name: '新建场景', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: '新建场景', exact: true });
  await dialog.getByLabel('场景名称').fill('四路值守');
  for (let index = 1; index <= 4; index++) await dialog.getByRole('checkbox', { name: `来源 ${index}`, exact: true }).check();
  await dialog.getByRole('button', { name: '应用到草稿' }).click();
  await page.getByRole('button', { name: '保存并应用', exact: true }).click();
  await expect.poll(() => server.getStudio().scenes.find((value) => value.name === '四路值守')?.sources.length).toBe(4);
  const menu = await sceneMenu(page, '主场景'); await menu.getByRole('menuitem', { name: '复制场景', exact: true }).click();
  dialog = await sceneMenu(page, '主场景 副本'); await dialog.getByRole('menuitem', { name: '重命名', exact: true }).click();
  dialog = page.getByRole('dialog', { name: '重命名场景', exact: true }); await dialog.getByLabel('场景名称').fill('六路总览');
  await dialog.getByRole('button', { name: '应用到草稿' }).click();
  await page.getByRole('button', { name: '保存并应用', exact: true }).click();
  await expect.poll(() => server.getStudio().scenes.find((value) => value.name === '六路总览')?.sources.length).toBe(6);
  await page.reload(); await expect(page.getByRole('button', { name: '选择场景 四路值守', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '选择场景 六路总览', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/scenes-presets.png', fullPage: true });
  expect(server.getStudio().scenes.find((value) => value.name === '四路值守')?.items.map((item) => [item.x, item.y, item.width, item.height])).toEqual([[0,0,960,540],[960,0,960,540],[0,540,960,540],[960,540,960,540]]);
});

test('opens multiple pinned scene projectors and keeps them independent of Program and global auto layout', async ({ page, context }) => {
  const server = await backend(context); server.getStudio().scenes.push(scene('other', 4));
  await page.goto('/#studio');
  let menu = await sceneMenu(page, '主场景');
  const aPromise = page.waitForEvent('popup'); await menu.getByRole('menuitem', { name: '打开场景投影 · 新窗口' }).click(); const a = await aPromise;
  menu = await sceneMenu(page, 'other');
  const bPromise = page.waitForEvent('popup'); await menu.getByRole('menuitem', { name: '打开场景投影 · 新窗口' }).click(); const b = await bPromise;
  await expect(a.locator('.direct-tile-position')).toHaveCount(6); await expect(b.locator('.direct-tile-position')).toHaveCount(4);
  await expect(a.locator('.workspace-sidebar')).toHaveCount(0); await expect(b.locator('.projector-shell')).toHaveAttribute('data-projector-scene', 'other');
  const position = await b.locator('.direct-tile-position').first().getAttribute('style'); expect(position).toContain('left: 0%'); expect(position).toContain('width: 10.4167%');
  server.getStudio().programSceneId = 'other';
  await a.evaluate(() => window.dispatchEvent(new Event('focus'))); await expect(a.locator('.direct-tile-position')).toHaveCount(6);
  server.getStudio().scenes = server.getStudio().scenes.filter((value) => value.id !== 'other');
  await b.evaluate(() => window.dispatchEvent(new Event('focus'))); await expect(b.locator('.projector-waiting')).toContainText('此场景已删除');
  await a.close(); await b.close();
});

test('imports go2rtc streams through detection and registry, without leaking upstream credentials or duplicating devices', async ({ page, context }) => {
  const server = await backend(context); await page.goto('/#devices');
  const bridge = page.getByRole('region', { name: 'go2rtc 流接入' });
  await expect(bridge).toContainText('发现 2 个命名流');
  await expect(bridge).not.toContainText('do-not-display');
  const row = bridge.locator('.go2rtc-stream-list > div').filter({ hasText: 'entrance' });
  await row.getByRole('button', { name: '检测并添加设备', exact: true }).click();
  await expect(row.getByRole('button', { name: '已在设备目录' })).toBeDisabled();
  expect(server.creates).toHaveLength(1); expect(server.creates[0]).toMatchObject({ name: 'entrance', address: 'rtsp://127.0.0.1:18554/entrance', profiles: [{ transportMode: 'rtsp-tcp' }] });
  await page.reload(); await expect(page.getByRole('region', { name: 'go2rtc 流接入' }).locator('.go2rtc-stream-list > div').filter({ hasText: 'entrance' }).getByRole('button', { name: '已在设备目录' })).toBeDisabled();
  await bridge.getByText('从 go2rtc 到正式设备与场景：操作步骤').click(); await expect(bridge).toContainText('命名流无需再次做 ONVIF 发现');
});

test('defaults optimization on, saves user opt-out and tolerates slow cadence without treating it as congestion', async ({ page, context }) => {
  const server = await backend(context); await page.goto('/#settings');
  const enabled = page.getByRole('checkbox', { name: '自动优化视频播放（默认开启）' }); await expect(enabled).toBeChecked();
  await enabled.uncheck(); await expect.poll(() => server.preferences.get('/api/v2/account/preferences/monitor-view')?.playbackOptimization.enabled).toBe(false);
  await page.reload(); await expect(enabled).not.toBeChecked();
  const sourceIds = await page.evaluate(async () => {
    const { cameraSourceId } = await import('/src/SceneCollection.tsx');
    const camera = 'camera-' + 'a'.repeat(128), profile = 'profile-' + 'b'.repeat(128);
    return [cameraSourceId(camera, profile), cameraSourceId(camera, profile), cameraSourceId(camera, profile + '2')];
  });
  expect(sourceIds[0].length).toBeLessThanOrEqual(64);
  expect(sourceIds[0]).toBe(sourceIds[1]); expect(sourceIds[0]).not.toBe(sourceIds[2]);
  const result = await page.evaluate(async () => {
    const { FrameCadence, congested, lowerBandwidthProfile } = await import('/src/playbackOptimization.ts');
    const cadence = new FrameCadence(); for (let i = 0; i < 8; i++) cadence.observe(1 + i * 10000);
    const slow = cadence.stallAfterMs(true), disabled = cadence.stallAfterMs(false);
    const before = { received: 100, lost: 0, jitter: .02, freezes: 0, timestamp: 1000 };
    const after = { received: 101, lost: 0, jitter: .02, freezes: 1, timestamp: 11000 };
    const base = { id: 'main', name: 'Main', role: 'main', endpoint: '', videoCodec: 'h264', audioCodec: 'aac', width: 1920, height: 1080, fps: 25 };
    const lower = lowerBandwidthProfile(base as never, [{ ...base, id: 'silent', width: 320, height: 180, audioCodec: '' }, { ...base, id: 'sub', width: 640, height: 360 }, { ...base, id: 'disabled', width: 320, height: 180, enabled: false }] as never);
    return { slow, disabled, slowCongested: congested(before, after), lossCongested: congested(before, { ...after, received: 200, lost: 20 }), lower: lower?.id };
  });
  expect(result).toEqual({ slow: 53000, disabled: 6000, slowCongested: false, lossCongested: true, lower: 'sub' });
});
