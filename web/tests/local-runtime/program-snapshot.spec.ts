import { expect, test } from '@playwright/test';
import type { SceneDocument, StudioDocument } from '../../src/types';

for (const operation of ['initial metadata', 'saving Studio']) test(`${operation} retains the actual frozen Program snapshot`, async ({ page }) => {
  const definition: SceneDocument = { schemaVersion: 6, revision: 1, id: 'program', name: '尚未 TAKE 的定义',
    canvas: { width: 640, height: 360, backgroundColor: '#112233' },
    sources: [{ id: 'definition-source', kind: 'color', name: '定义色块', color: '#123456',
      muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }],
    items: [{ id: 'tile', sourceId: 'definition-source', x: 0, y: 0, width: 640, height: 360,
      scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0,
      visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }] };
  const live = structuredClone(definition); live.name = '实际直播画面';
  live.sources[0].id = 'program.live-source'; live.items[0].sourceId = 'program.live-source';
  let studio: StudioDocument = { schemaVersion: 1, revision: 1, previewSceneId: definition.id,
    programSceneId: definition.id, scenes: [definition], transition: { kind: 'cut', durationMs: 0 } };
  let release!: () => void, saved = 0;
  const metadata = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/**', async route => {
    const endpoint = new URL(route.request().url()).pathname;
    const reply = (value: unknown) => route.fulfill({ json: value });
    if (endpoint === '/api/v1/auth/session') return reply({ authenticated: true, authenticationEnabled: true, user: 'fixture-admin' });
    if (endpoint === '/api/v1/studio') {
      if (route.request().method() === 'GET') await metadata;
      else { studio = route.request().postDataJSON(); studio.revision++; saved++; }
      return reply(studio);
    }
    if (endpoint === '/api/v1/cameras') return reply({ cameras: [] });
    if (endpoint === '/api/v1/playback/capabilities') return reply({ modes: { direct: { enabled: true } }, sources: [] });
    if (endpoint === '/api/v2/account/preferences/monitor-view') return reply({ value: {
      mode: 'manual', showAllAudioSources: true,
      sourceAudio: { 'program.live-source': { volume: .27, muted: false, monitor: false } } } });
    if (endpoint.startsWith('/api/v2/account/preferences/')) return reply({ value: null });
    if (endpoint === '/api/v2/operations/issues') return reply({ issues: [] });
    return route.fulfill({ status: 404, json: {} });
  });
  let publish!: () => void, connected!: () => void;
  const socketReady = new Promise<void>(resolve => { connected = resolve; });
  await page.routeWebSocket('**/api/v1/ws', socket => {
    publish = () => socket.send(JSON.stringify({ type: 'scene.snapshot', scene: live }));
    connected();
    if (operation === 'initial metadata') publish();
  });
  if (operation === 'saving Studio') release();
  await page.goto('/tests/harness/offline-workspace.html#monitor');
  if (operation === 'saving Studio') {
    await expect(page.locator('.monitor-heading h1')).toHaveText(definition.name);
    await socketReady; publish();
  }
  await expect(page.locator('.connection.online')).toBeVisible();
  release();
  await expect(page.locator('.monitor-heading h1')).toHaveText(live.name);
  const channel = page.locator('.audio-mixer-channel');
  await expect(channel).toHaveAttribute('data-source-id', 'program.live-source');
  await expect(channel.getByRole('slider', { name: '定义色块 音量' })).toHaveValue('0.27');
  if (operation === 'saving Studio') {
    await page.evaluate(() => { location.hash = '#studio'; });
    await page.getByRole('button', { name: `选择场景 ${definition.name}`, exact: true }).focus();
    await page.keyboard.press('F2');
    const dialog = page.getByRole('dialog', { name: '重命名场景', exact: true });
    await dialog.getByRole('textbox', { name: '场景名称' }).fill('新的场景定义');
    await dialog.getByRole('button', { name: '应用到草稿', exact: true }).click();
    await page.getByRole('button', { name: '保存并应用', exact: true }).click();
    await expect.poll(() => saved).toBe(1);
    await expect(page.getByRole('button', { name: '服务器已保存', exact: true })).toBeVisible();
    await page.evaluate(() => { location.hash = '#monitor'; });
    await expect(page.locator('.monitor-heading h1')).toHaveText(live.name);
    await expect(channel).toHaveAttribute('data-source-id', 'program.live-source');
    await expect(channel.getByRole('slider', { name: '定义色块 音量' })).toHaveValue('0.27');
  }
});
