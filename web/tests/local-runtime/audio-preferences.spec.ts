import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { savePreferenceFixture } from '../harness/preferenceServer';

const fixture = '/tests/harness/usability.html?area=monitor&mixer&account-server';
type Preferences = Record<string, any>;

// Separate browser contexts have no shared IndexedDB, cookies or storage.
// This fixture acts as the account server, shared only by the selected user.
async function account(context: BrowserContext, server: Map<string, Preferences>, user: string, blocked = false) {
  await context.addInitScript(({ blocked }) => {
    let allowResume = !blocked;
    window.addEventListener('pointerdown', () => { allowResume = true; }, { capture: true });
    class Node {
      fftSize = 1024; value = 0; gain = this; delayTime = this;
      connect(node: any) { return node; } disconnect() {}
      setTargetAtTime(value: number) { this.value = value; }
      getFloatTimeDomainData(buffer: Float32Array) { buffer.fill(0); }
    }
    class Context {
      state = 'suspended'; currentTime = 0; destination = new Node();
      createGain() { return new Node(); } createAnalyser() { return new Node(); }
      createDelay() { return new Node(); } createMediaStreamSource() { return new Node(); }
      async resume() {
        if (!allowResume) await new Promise(() => undefined);
        this.state = 'running';
      }
      async suspend() { this.state = 'suspended'; } async close() { this.state = 'closed'; }
    }
    window.AudioContext = Context as unknown as typeof AudioContext;
  }, { blocked });
  await context.route('**/api/v2/account/preferences/monitor-view', async (route) => {
    if (route.request().method() === 'PUT') {
      const request = route.request().postDataJSON();
      server.set(user, savePreferenceFixture(server.get(user), request));
    }
    await route.fulfill({ json: { value: server.get(user) ?? null } });
  });
}
const ready = async (page: Page) => expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeEnabled();
const output = (page: Page) => page.locator('.hero-audio-control').getByRole('combobox', { name: '声音输出模式' });

test('late source audio in a 1000-source account survives edits, reload and a fresh browser', async ({ browser }) => {
  const sourceAudio = Object.fromEntries(Array.from({ length: 1000 }, (_, index) =>
    [`other-scene-${index}`, { volume: .27, muted: false, monitor: false }]));
  const server = new Map<string, Preferences>([['large-audio', { sourceAudio }]]);
  const first = await browser.newContext();
  await account(first, server, 'large-audio');
  const page = await first.newPage();
  const target = `${fixture}&source-identities=other-scene-999`;
  await page.goto(target); await ready(page); await page.clock.install();
  const gain = page.getByRole('slider', { name: '有声音的摄像机 音量' });
  const mute = page.getByRole('button', { name: '有声音的摄像机 静音', exact: true });
  const monitor = page.getByRole('button', { name: '有声音的摄像机 本地监听', exact: true });
  await expect(gain).toHaveValue('0.27');
  await expect(mute).toHaveAttribute('aria-pressed', 'false');
  await expect(monitor).toHaveAttribute('aria-pressed', 'false');
  await gain.fill('0.63'); await page.clock.runFor(400);
  await expect.poll(() => server.get('large-audio')?.sourceAudio?.['other-scene-999']).toEqual({ volume: .63, muted: false, monitor: false });
  expect(Object.keys(server.get('large-audio')!.sourceAudio)).toHaveLength(1000);
  expect(server.get('large-audio')!.sourceAudio['other-scene-0']).toEqual(sourceAudio['other-scene-0']);
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.41');
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  await expect.poll(() => server.get('large-audio')?.localMonitorVolume).toBe(.41);
  await page.reload(); await ready(page);
  await expect(gain).toHaveValue('0.63');
  await expect(mute).toHaveAttribute('aria-pressed', 'false');
  await expect(monitor).toHaveAttribute('aria-pressed', 'false');
  await first.close();
  const fresh = await browser.newContext();
  await account(fresh, server, 'large-audio');
  const restored = await fresh.newPage(); await restored.goto(target); await ready(restored);
  await expect(restored.getByRole('slider', { name: '有声音的摄像机 音量' })).toHaveValue('0.63');
  await expect(restored.getByRole('button', { name: '有声音的摄像机 静音', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(restored.getByRole('button', { name: '有声音的摄像机 本地监听', exact: true })).toHaveAttribute('aria-pressed', 'false');
  expect(Object.keys(server.get('large-audio')!.sourceAudio)).toHaveLength(1000);
  await fresh.close();
});

for (const identity of ['constructor', '__proto__']) test(`prototype-named ${identity} source displays and preserves inherited audio through save and reload`, async ({ page, context }) => {
  const server = new Map<string, Preferences>(); await account(context, server, 'identity-account');
  await page.goto(`${fixture}&source-identities=${identity}`); await ready(page); await page.clock.install();
  const gain = page.getByRole('slider', { name: '有声音的摄像机 音量' });
  await expect(gain).toHaveValue('1');
  await expect(page.getByRole('button', { name: '有声音的摄像机 静音', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await gain.fill('0.63'); await page.clock.runFor(400);
  await expect.poll(() => server.get('identity-account')?.sourceAudio?.[identity]).toEqual({ volume: .63, muted: true, monitor: true });
  await page.reload(); await ready(page);
  await expect(gain).toHaveValue('0.63');
  await expect(page.getByRole('button', { name: '有声音的摄像机 静音', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect(Object.hasOwn(server.get('identity-account')!.sourceAudio, identity)).toBe(true);
});

test('a one-field edit in a large multi-scene account uses a small keepalive body and retains unrelated sources', async ({ page, context }) => {
  const server = new Map<string, Preferences>(); await account(context, server, 'large-account', false);
  await page.goto(fixture.replace('area=monitor', 'area=devices'));
  const base = await page.evaluate(async () => {
    const { defaultMonitorView, defaultSourceDecoration, normalizeMonitorView } = await import('/src/monitorView.ts');
    return normalizeMonitorView({ ...defaultMonitorView(), sourceDecorations: Object.fromEntries(Array.from({ length: 1000 }, (_, index) =>
      [`other-scene-${index}`, defaultSourceDecoration()])) }, 16);
  });
  const fullPairBytes = Buffer.byteLength(JSON.stringify({ baseValue: base, value: { ...base, localMonitorVolume: .31 } }));
  console.log('LARGE_PREFERENCE_BASELINE', { sources: 1000, fullPairBytes });
  expect(fullPairBytes).toBeGreaterThan(1024 * 1024);
  server.set('large-account', base);
  await context.addInitScript(() => {
    const original = window.fetch;
    window.fetch = (input, init) => {
      if (String(input).endsWith('/account/preferences/monitor-view') && init?.method === 'PUT')
        (window as any).preferenceWire = { bytes: new TextEncoder().encode(String(init.body)).byteLength, keepalive: init.keepalive };
      return original(input, init);
    };
  });
  await page.goto(fixture); await ready(page); await page.clock.install();
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.31');
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  await expect.poll(() => server.get('large-account')?.localMonitorVolume).toBe(.31);
  const wire = await page.evaluate(() => (window as any).preferenceWire);
  expect(wire.bytes).toBeLessThan(1024); expect(wire.keepalive).toBe(true);
  expect(server.get('large-account')?.sourceDecorations).toEqual(base.sourceDecorations);
  console.log('LARGE_PREFERENCE_COMPACT', wire);
  await page.getByRole('checkbox', { name: '统计叠层（全部来源）', exact: true }).check();
  await page.clock.runFor(400);
  await expect.poll(() => server.get('large-account')?.sourceDecorations?.['other-scene-999']?.telemetry.enabled).toBe(true);
  const bulk = await page.evaluate(() => (window as any).preferenceWire);
  expect(bulk.bytes).toBeLessThan(1024 * 1024);
  expect(Object.values(server.get('large-account')!.sourceDecorations).every((value: any) => value.telemetry.enabled)).toBe(true);
  expect(server.get('large-account')?.sourceDecorations?.['other-scene-999'].audioMeter).toEqual(base.sourceDecorations['other-scene-999'].audioMeter);
  console.log('LARGE_PREFERENCE_BULK', bulk);
});

test('compact source pairs retain inherited controls, deletion, arrays, null and own property names', async ({ page }) => {
  await page.goto(fixture.replace('area=monitor', 'area=devices'));
  const pairJson = await page.evaluate(async () => {
    const { defaultMonitorView } = await import('/src/monitorView.ts');
    const { compactMonitorPreference } = await import('/src/monitorPreferenceMerge.ts');
    const base = { ...defaultMonitorView(), archiveAudioCameraId: 'old-camera',
      sourceAudio: JSON.parse('{"__proto__":{"volume":0.9,"muted":true,"monitor":true},"untouched":{"volume":1,"muted":false,"monitor":true},"removed":{"volume":0.5,"muted":true,"monitor":false}}') };
    const value = { ...base, archiveAudioCameraId: null, largeSourceIds: ['__proto__'],
      sourceAudio: Object.fromEntries([['__proto__', { volume: .4, muted: true, monitor: true }], ['untouched', base.sourceAudio.untouched]]) };
    return JSON.stringify(compactMonitorPreference(value, base));
  });
  const pair = JSON.parse(pairJson); // Exercise JSON transport, including __proto__, without the test driver's object serializer.
  expect(pair).toEqual({
    baseValue: { archiveAudioCameraId: 'old-camera', largeSourceIds: [], sourceAudio: JSON.parse('{"__proto__":{"volume":0.9,"muted":true,"monitor":true},"removed":{"volume":0.5,"muted":true,"monitor":false}}') },
    value: { archiveAudioCameraId: null, largeSourceIds: ['__proto__'], sourceAudio: JSON.parse('{"__proto__":{"volume":0.4}}') },
    partial: true, removedPaths: [['sourceAudio', 'removed']],
  });
});

test('a failed fresh preference read keeps decoded fixture pictures muted until account recovery', async ({ page, context }) => {
  const server = new Map<string, Preferences>([['alice', { localMonitorVolume: .18, audioMonitorEnabled: true, audioOutput: 'meter-only' }]]);
  await account(context, server, 'alice');
  let failing = true, writes = 0;
  await context.route('**/api/v2/account/preferences/monitor-view', route => {
    if (route.request().method() === 'PUT') writes++;
    return failing && route.request().method() === 'GET' ? route.fulfill({ status: 503, json: {} }) : route.fallback();
  });
  await page.goto(`${fixture}&layout`);
  const retry = page.getByRole('button', { name: '重试账号偏好', exact: true });
  await expect(retry).toBeVisible();
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeDisabled();
  await expect(output(page)).toBeDisabled();
  await expect(page.getByRole('button', { name: '有声音的摄像机 静音', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '窗口预览', exact: true })).toBeEnabled();
  await expect.poll(() => page.locator('.direct-preview video').evaluateAll(videos =>
    videos.length === 2 && videos.every(video => (video as HTMLVideoElement).readyState >= 2 && (video as HTMLVideoElement).currentTime > 0))).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event('webobs:audio-monitor-enable')));
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-enabled', 'false');
  expect(await page.locator('.direct-preview video').evaluateAll(videos => videos.every(video => (video as HTMLVideoElement).muted))).toBe(true);
  expect(writes).toBe(0);
  failing = false; await retry.click();
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeEnabled();
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.18');
  await expect(output(page)).toHaveValue('meter-only');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'true');
  await expect(retry).toHaveCount(0);
  expect(writes).toBe(0);
});

test('settings and program audio expose retry without enabling unknown account defaults', async ({ page, context }) => {
  const server = new Map<string, Preferences>([['alice', { audioMonitorEnabled: false, playbackOptimization: { enabled: false } }]]);
  await account(context, server, 'alice');
  let failing = true, writes = 0;
  await context.route('**/api/v2/account/preferences/monitor-view', route => {
    if (route.request().method() === 'PUT') writes++;
    return failing && route.request().method() === 'GET' ? route.fulfill({ status: 503, json: {} }) : route.fallback();
  });
  await page.goto(fixture.replace('area=monitor', 'area=settings'));
  const optimization = page.getByRole('checkbox', { name: '自动优化视频播放（默认开启）', exact: true });
  await expect(optimization).toBeDisabled();
  await expect(page.getByRole('spinbutton', { name: '探测超时（秒）' })).toBeEnabled();
  failing = false; await page.getByRole('button', { name: '重试账号偏好', exact: true }).click();
  await expect(optimization).toBeEnabled(); await expect(optimization).not.toBeChecked();
  failing = true;
  await page.goto(fixture.replace('area=monitor', 'area=devices'));
  await page.evaluate(async () => {
    const { mountPollingPage } = await import('/tests/harness/pollingMount.tsx');
    const host = document.createElement('div'); host.id = 'program-recovery'; document.body.appendChild(host);
    mountPollingPage('program', host);
  });
  const program = page.locator('#program-recovery');
  await expect(program.getByRole('button', { name: '启用节目声音', exact: true })).toBeDisabled();
  expect(await program.locator('video').evaluate(video => video.muted)).toBe(true);
  await expect(program.getByRole('button', { name: '独立小窗', exact: true })).toBeEnabled();
  failing = false; await program.getByRole('button', { name: '重试账号偏好', exact: true }).click();
  await expect(program.getByRole('button', { name: '启用节目声音', exact: true })).toBeEnabled();
  expect(writes).toBe(0);
});

test('manual retry captures the latest input before reloading a failed pending save', async ({ page, context }) => {
  const server = new Map<string, Preferences>(); await account(context, server, 'alice');
  let failing = true;
  await context.route('**/api/v2/account/preferences/monitor-view', route => failing && route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, json: {} }) : route.fallback());
  await page.goto(fixture); await ready(page); await page.clock.install();
  await output(page).selectOption('meter-only'); await page.clock.runFor(400);
  await expect(page.getByRole('button', { name: '重试账号偏好', exact: true })).toBeVisible();
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.63');
  failing = false; await page.getByRole('button', { name: '重试账号偏好', exact: true }).click();
  await expect.poll(() => server.get('alice')).toMatchObject({ localMonitorVolume: .63, audioOutput: 'meter-only' });
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.63');
  await expect(output(page)).toBeEnabled();
});

test('a valid encrypted private cache restores account controls while the server read is unavailable', async ({ page, context }) => {
  const server = new Map<string, Preferences>(); await account(context, server, 'alice');
  await page.goto(fixture); await ready(page);
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.27');
  await output(page).selectOption('meter-only');
  await expect.poll(() => server.get('alice')).toMatchObject({ localMonitorVolume: .27, audioOutput: 'meter-only' });
  await context.route('**/api/v2/account/preferences/monitor-view', route => route.request().method() === 'GET'
    ? route.fulfill({ status: 503, json: {} }) : route.fallback());
  await page.reload(); await ready(page);
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.27');
  await expect(output(page)).toHaveValue('meter-only');
  await expect(page.getByRole('button', { name: '重试账号偏好', exact: true })).toHaveCount(0);
});

test('a stale same-account window edits only its field and adopts the merged acknowledgement', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  const a = await browser.newContext(), b = await browser.newContext();
  await account(a, server, 'alice', false); await account(b, server, 'alice', false);
  const first = await a.newPage(), second = await b.newPage();
  for (const page of [first, second]) { await page.goto(fixture); await ready(page); await page.clock.install(); }
  await first.getByRole('slider', { name: '本地监听主音量' }).fill('0.41'); await first.clock.runFor(400);
  await expect.poll(() => server.get('alice')?.localMonitorVolume).toBe(.41);
  await output(second).selectOption('meter-only'); await second.clock.runFor(400);
  await expect.poll(() => server.get('alice')).toMatchObject({ localMonitorVolume: .41, audioOutput: 'meter-only' });
  await expect(second.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.41');
  await first.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(output(first)).toHaveValue('meter-only');
  await a.close(); await b.close();
});

test('a failed pending edit keeps its baseline through reload and merges after another device saves', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  const a = await browser.newContext(), b = await browser.newContext();
  await account(a, server, 'alice', false); await account(b, server, 'alice', false);
  let failing = true;
  await a.route('**/api/v2/account/preferences/monitor-view', route => route.request().method() === 'PUT' && failing
    ? route.fulfill({ status: 503, json: {} }) : route.fallback());
  const first = await a.newPage(), second = await b.newPage();
  await first.goto(fixture); await ready(first); await output(first).selectOption('meter-only');
  await expect(first.locator('.direct-preview-shell').getByRole('alert')).toContainText('保存失败');
  await second.goto(fixture); await ready(second);
  await second.getByRole('slider', { name: '本地监听主音量' }).fill('0.44');
  await expect.poll(() => server.get('alice')?.localMonitorVolume).toBe(.44);
  await first.reload(); await ready(first); await expect(output(first)).toHaveValue('meter-only');
  failing = false; await first.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect.poll(() => server.get('alice')).toMatchObject({ localMonitorVolume: .44, audioOutput: 'meter-only' });
  await expect(first.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.44');
  await a.close(); await b.close();
});

test('two stale windows creating the first source controls keep inherited mute and the other volume edit', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  const a = await browser.newContext(), b = await browser.newContext();
  await account(a, server, 'alice', false); await account(b, server, 'alice', false);
  const first = await a.newPage(), second = await b.newPage();
  for (const page of [first, second]) { await page.goto(fixture); await ready(page); await page.clock.install(); }
  await first.getByRole('slider', { name: '有声音的摄像机 音量' }).fill('0.63'); await first.clock.runFor(400);
  await expect.poll(() => server.get('alice')?.sourceAudio?.['audio-source-1']).toMatchObject({ volume: .63, muted: true });
  await second.getByRole('button', { name: '有声音的摄像机 静音', exact: true }).click(); await second.clock.runFor(400);
  await expect.poll(() => server.get('alice')?.sourceAudio?.['audio-source-1']).toMatchObject({ volume: .63, muted: false, monitor: true });
  await expect(second.getByRole('slider', { name: '有声音的摄像机 音量' })).toHaveValue('0.63');
  await a.close(); await b.close();
});

test('a merged acknowledgement preserves a newer local input before its debounce submits', async ({ page, context }) => {
  const server = new Map<string, Preferences>(); await account(context, server, 'alice', false);
  await page.goto(fixture); await ready(page); await page.clock.install();
  let arrived!: () => void, release!: () => void;
  const requested = new Promise<void>(resolve => { arrived = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  let once = true;
  await page.route('**/api/v2/account/preferences/monitor-view', async route => {
    if (!once || route.request().method() !== 'PUT') return route.fallback();
    once = false;
    const value = { ...savePreferenceFixture(server.get('alice'), route.request().postDataJSON()), localMonitorVolume: .41 };
    server.set('alice', value); arrived(); await held;
    await route.fulfill({ json: { value } });
  });
  await output(page).selectOption('meter-only'); await page.clock.runFor(400); await requested;
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.62'); release();
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.62');
  await page.clock.runFor(400);
  await expect.poll(() => server.get('alice')).toMatchObject({ localMonitorVolume: .62, audioOutput: 'meter-only' });
  await expect(output(page)).toHaveValue('meter-only');
});

test('flushes pending account audio changes on the Android lifecycle signal without losing the workspace', async ({ page, context }) => {
  const server = new Map<string, Preferences>();
  await account(context, server, 'android-user');
  await page.goto(fixture); await ready(page);
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.42');
  await page.evaluate(() => { window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
  await expect.poll(() => server.get('android-user')?.localMonitorVolume).toBe(.42);
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.42');
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
  await page.reload(); await ready(page);
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.42');
});

test('restores listening, output, master and source controls after refresh and a fresh browser login', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  let context = await browser.newContext();
  await account(context, server, 'alice');
  let page = await context.newPage();
  await page.goto(fixture); await ready(page);
  await page.getByRole('button', { name: '🔊 启用声音监听', exact: true }).click();
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.37');
  await output(page).selectOption('meter-only');
  await page.getByRole('slider', { name: '有声音的摄像机 音量' }).fill('0.63');
  await page.getByRole('button', { name: '有声音的摄像机 静音', exact: true }).click();
  await page.getByRole('button', { name: '有声音的摄像机 本地监听', exact: true }).click();
  await page.getByRole('region', { name: 'Audio Mixer', exact: true }).getByRole('button', { name: '收起', exact: true }).click();
  await expect.poll(() => server.get('alice')).toMatchObject({ audioMonitorEnabled: true, audioOutput: 'meter-only', localMonitorVolume: .37, audioMixerCollapsed: true,
    sourceAudio: { 'audio-source-1': { volume: .63, muted: false, monitor: false } } });
  await page.reload(); await ready(page);
  await expect(output(page)).toHaveValue('meter-only');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'true');
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.37');
  await context.close();
  context = await browser.newContext();
  await account(context, server, 'alice'); page = await context.newPage();
  await page.goto(fixture); await ready(page);
  await expect(output(page)).toHaveValue('meter-only');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-enabled', 'true');
  await page.getByRole('region', { name: 'Audio Mixer', exact: true }).getByRole('button', { name: '展开', exact: true }).click();
  await expect(page.getByRole('slider', { name: '有声音的摄像机 音量' })).toHaveValue('0.63');
  await expect(page.getByRole('button', { name: '有声音的摄像机 静音', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: '有声音的摄像机 本地监听', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await context.close();
  const other = await browser.newContext(); await account(other, server, 'bob');
  const otherPage = await other.newPage(); await otherPage.goto(fixture); await ready(otherPage);
  await expect(output(otherPage)).toHaveValue('speaker');
  await expect(otherPage.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('1');
  await expect(otherPage.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'false');
  await other.close();
});

test('synchronizes an already open browser for the same account', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  const a = await browser.newContext(), b = await browser.newContext();
  await account(a, server, 'alice'); await account(b, server, 'alice');
  const first = await a.newPage(), second = await b.newPage();
  await first.goto(fixture); await second.goto(fixture); await ready(first); await ready(second);
  await output(first).selectOption('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await second.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(output(second)).toHaveValue('meter-only');
  await a.close(); await b.close();
});

test('flushes a change on pagehide before the debounce fires', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice'); const page = await context.newPage();
  await page.goto(fixture); await ready(page);
  await output(page).selectOption('meter-only');
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide')));
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await page.reload(); await ready(page); await expect(output(page)).toHaveValue('meter-only');
  await context.close();
});

test('account saves work when browser storage is unavailable', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice');
  await context.addInitScript(() => {
    indexedDB.open = () => { throw new Error('storage denied'); };
    Storage.prototype.getItem = Storage.prototype.setItem = () => { throw new Error('storage denied'); };
  });
  const page = await context.newPage(); await page.goto(fixture); await ready(page);
  await output(page).selectOption('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await page.reload(); await ready(page); await expect(output(page)).toHaveValue('meter-only');
  await context.close();
});

test('a delayed account refresh cannot overwrite a newer local adjustment', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice'); const page = await context.newPage();
  await page.goto(fixture); await ready(page);
  let started!: () => void, release!: () => void;
  const requested = new Promise<void>((resolve) => { started = resolve; });
  const held = new Promise<void>((resolve) => { release = resolve; });
  let delaying = true;
  await page.route('**/api/v2/account/preferences/monitor-view', async (route) => {
    if (route.request().method() !== 'GET' || !delaying) return route.fallback();
    delaying = false; const value = server.get('alice') ?? null;
    started(); await held; await route.fulfill({ json: { value } });
  });
  await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await requested;
  await output(page).selectOption('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  release();
  await expect(output(page)).toHaveValue('meter-only');
  await page.reload(); await ready(page); await expect(output(page)).toHaveValue('meter-only');
  await context.close();
});

test('autoplay blocking preserves the saved intent and a click resumes it', async ({ browser }) => {
  const server = new Map<string, Preferences>([['alice', { audioMonitorEnabled: true, audioOutput: 'speaker', localMonitorVolume: .2 }]]);
  const context = await browser.newContext(); await account(context, server, 'alice', true);
  const page = await context.newPage(); await page.goto(fixture); await ready(page);
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-state', 'blocked');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'true');
  await page.getByRole('button', { name: '🔊 恢复声音监听', exact: true }).click();
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-enabled', 'true');
  await page.getByRole('button', { name: '监听中 · 点击关闭', exact: true }).click();
  await expect.poll(() => server.get('alice')?.audioMonitorEnabled).toBe(false);
  await page.reload(); await ready(page);
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'false');
  await context.close();
});

test('a failed save remains visible and the pending local edit recovers on reload', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice'); const page = await context.newPage();
  let failing = true;
  await page.route('**/api/v2/account/preferences/monitor-view', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback();
    if (failing) return route.fulfill({ status: 503, json: {} });
    return route.fallback();
  });
  await page.goto(fixture); await ready(page); await output(page).selectOption('meter-only');
  await expect(page.locator('.direct-preview-shell').getByRole('alert')).toContainText('保存失败');
  expect(server.get('alice')).toBeUndefined();
  // Reload while the server still rejects writes: a focus refresh must retain
  // the pending account preference rather than adopting the server default.
  await page.reload(); await ready(page);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(output(page)).toHaveValue('meter-only');
  failing = false;
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await page.reload(); await ready(page);
  await expect(output(page)).toHaveValue('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await context.close();
});
