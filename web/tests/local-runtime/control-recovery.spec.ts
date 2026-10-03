import { expect, test, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

async function setup(page: Page) {
  await page.goto('/tests/harness/usability.html');
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now() + 100));
  await page.evaluate(async () => {
    const state: any = { sockets: [], states: [], events: [], online: true, throwConstructor: false, clipboard: '' };
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => state.online });
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => { state.clipboard = value; } } });
    Math.random = () => .5;
    class Socket {
      onopen: any; onmessage: any; onclose: any; onerror: any; readyState = 0;
      constructor() { if (state.throwConstructor) throw new Error('private://user:password@private-camera.invalid'); state.sockets.push(this); }
      open() { this.readyState = 1; this.onopen?.(new Event('open')); }
      sendFixture(value: any) { this.onmessage?.({ data: typeof value === 'string' || value instanceof ArrayBuffer ? value : JSON.stringify(value) }); }
      close() { if (this.readyState === 3) return; this.readyState = 3; this.onclose?.({ reason: 'private upstream detail' }); }
    }
    (window as any).WebSocket = Socket;
    const api = await import('/src/api.ts');
    const diagnostics = await import('/src/controlConnectionStatus.ts');
    state.event = { type: 'scene.snapshot', scene: { schemaVersion: 5, revision: 1, id: 'fixture', name: 'private-scene-label',
      canvas: { width: 640, height: 360, backgroundColor: '#000000' }, items: [],
      sources: [{ id: 'browser', kind: 'browser', filters: [], url: 'https://private-camera.invalid/?token=confidential-fixture' }] } };
    state.start = () => api.connectSceneEvents((event: any) => state.events.push(event.scene.revision), (connected: boolean) => state.states.push(connected));
    state.stop = state.start(); state.diagnostics = diagnostics;
    (window as any).controlTest = state;
  });
}
const snapshot = (page: Page) => page.evaluate(() => {
  const state = (window as any).controlTest;
  return { sockets: state.sockets.length, states: state.states, events: state.events, diagnostics: state.diagnostics.getControlConnections(), now: Date.now() };
});

test('HTTP upgrade needs a valid scene and missing snapshots time out', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => (window as any).controlTest.sockets[0].open());
  expect((await snapshot(page)).states).toEqual([]);
  await page.clock.runFor(15_001);
  const failed = await snapshot(page);
  expect(failed.states).toEqual([false]);
  expect(failed.diagnostics[0]).toMatchObject({ phase: 'retrying', reason: 'snapshot_timeout', failures: 1, messages: 0 });
  await page.clock.runFor(500);
  await page.evaluate(() => { const s = (window as any).controlTest; s.sockets[1].open(); s.sockets[1].sendFixture(s.event); });
  expect(await snapshot(page)).toMatchObject({ states: [false, true], events: [1], diagnostics: [{ phase: 'online', messages: 1 }] });
});

test('hung connection and constructor failures retry without leaking exception details', async ({ page }) => {
  await setup(page);
  await page.clock.runFor(15_001);
  expect((await snapshot(page)).diagnostics[0]).toMatchObject({ reason: 'connection_timeout', phase: 'retrying' });
  await page.evaluate(() => { (window as any).controlTest.throwConstructor = true; });
  await page.clock.runFor(500);
  const failed = await snapshot(page);
  expect(failed.diagnostics[0]).toMatchObject({ reason: 'constructor_failed', failures: 2, attempts: 2 });
  expect(JSON.stringify(failed.diagnostics)).not.toMatch(/private|password|camera\.invalid/);
  await page.evaluate(() => { const s = (window as any).controlTest; s.throwConstructor = false; });
  await page.clock.runFor(1_000);
  expect((await snapshot(page)).sockets).toBe(2);
});

test('malformed and oversized messages never replace the last valid scene', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => {
    const s = (window as any).controlTest, socket = s.sockets[0]; socket.open();
    for (const message of ['not-json', { type: 'scene.snapshot', scene: null }, new ArrayBuffer(4), 'x'.repeat(1_048_577),
      { ...s.event, scene: { ...s.event.scene, sources: [null] } }]) socket.sendFixture(message);
  });
  expect(await snapshot(page)).toMatchObject({ states: [], events: [], diagnostics: [{ rejectedMessages: 5 }] });
  await page.evaluate(() => { const s = (window as any).controlTest; s.sockets[0].sendFixture(s.event); s.sockets[0].sendFixture({ type: 'scene.updated', scene: { canvas: null } }); });
  expect(await snapshot(page)).toMatchObject({ states: [true], events: [1], diagnostics: [{ rejectedMessages: 6, messages: 1 }] });
});

test('current v6 scenes retain multi-track inputs through profile save/export/import; unknown versions are rejected', async ({ page }) => {
  await setup(page);
  await page.clock.resume();
  await page.evaluate(() => {
    const original = window.fetch;
    const preferences = new Map<string, unknown>();
    (window as any).controlTest.preferences = preferences;
    window.fetch = async (input, init) => {
      const path = new URL(String(input), location.origin).pathname;
      if (!path.startsWith('/api/v2/account/preferences/')) return original(input, init);
      if (init?.method === 'PUT') preferences.set(path, JSON.parse(String(init.body)).value);
      return Response.json({ value: preferences.get(path) ?? null });
    };
  });
  const result = await page.evaluate(async () => {
    const s = (window as any).controlTest;
    const scene = { ...s.event.scene, schemaVersion: 6, sources: [{ id: 'color', kind: 'color', name: 'Fixture',
      muted: true, volume: .5, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [], color: '#000000',
      audioInputs: [{ track: 0, gain: .7, muted: false }, { track: 2, gain: .3, muted: true, syncOffsetMs: 120 }] }] };
    s.sockets[0].open(); s.sockets[0].sendFixture({ type: 'scene.snapshot', scene });
    s.sockets[0].sendFixture({ type: 'scene.updated', scene: { ...scene, schemaVersion: 7 } });
    const runtime = await import('/src/localRuntime.ts');
    const studio = { schemaVersion: 1 as const, revision: 1, programSceneId: scene.id, previewSceneId: scene.id,
      transition: { kind: 'cut' as const, durationMs: 0 }, scenes: [scene] };
    const profile = await runtime.saveLocalConfigProfile('Current contract', studio);
    const bundle = runtime.makeLocalConfigBundle(profile);
    const imported = await runtime.importLocalConfigBundle(bundle);
    return { scene: imported.studio.scenes[0], events: s.events, rejected: s.diagnostics.getControlConnections()[0].rejectedMessages };
  });
  expect(result).toMatchObject({ events: [1], rejected: 1, scene: { schemaVersion: 6, sources: [{ audioInputs: [
    { track: 0, gain: .7, muted: false }, { track: 2, gain: .3, muted: true, syncOffsetMs: 120 },
  ] }] } });
  expect(await page.evaluate(() => (window as any).controlTest.preferences.size)).toBeGreaterThan(0);
});

test('flapping connections increase backoff and only stable delivery resets it', async ({ page }) => {
  await setup(page);
  for (const delay of [500, 1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000]) {
    await page.evaluate(() => { const s = (window as any).controlTest, socket = s.sockets.at(-1); socket.open(); socket.sendFixture(s.event); socket.close(); });
    const state = await snapshot(page);
    expect(state.diagnostics[0].nextRetryAt! - state.now).toBe(delay);
    await page.clock.runFor(delay);
  }
  await page.evaluate(() => { const s = (window as any).controlTest; s.sockets.at(-1).open(); s.sockets.at(-1).sendFixture(s.event); });
  await page.clock.runFor(30_000);
  await page.evaluate(() => (window as any).controlTest.sockets.at(-1).close());
  const stable = await snapshot(page);
  expect(stable.diagnostics[0].nextRetryAt! - stable.now).toBe(500);
});

test('offline and native background stop failed retries, online and resume reconnect immediately', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => { const s = (window as any).controlTest; s.online = false; window.dispatchEvent(new Event('offline')); });
  await page.clock.runFor(300_000);
  expect(await snapshot(page)).toMatchObject({ sockets: 1, diagnostics: [{ phase: 'offline', nextRetryAt: null }] });
  await page.evaluate(() => { const s = (window as any).controlTest; s.online = true; window.dispatchEvent(new Event('online')); s.sockets.at(-1).open(); s.sockets.at(-1).sendFixture(s.event);
    window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); s.sockets.at(-1).close(); });
  await page.clock.runFor(300_000);
  expect(await snapshot(page)).toMatchObject({ sockets: 2, diagnostics: [{ phase: 'paused', nextRetryAt: null }] });
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
  expect((await snapshot(page)).sockets).toBe(3);
});

test('coincident wake events and short background periods preserve one pending or healthy subscription', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => { window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('webobs:visibility')); window.dispatchEvent(new Event('online')); });
  expect((await snapshot(page)).sockets).toBe(1);
  await page.evaluate(() => { const s = (window as any).controlTest; s.sockets[0].open(); s.sockets[0].sendFixture(s.event);
    window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
  await page.clock.runFor(10_000);
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
  expect(await snapshot(page)).toMatchObject({ sockets: 1, diagnostics: [{ phase: 'online' }] });
});

test('long background resume renews stale subscriptions, old callbacks and cleanup cannot revive them', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => { const s = (window as any).controlTest; s.sockets[0].open(); s.sockets[0].sendFixture(s.event);
    s.oldError = s.sockets[0].onerror; s.oldMessage = s.sockets[0].onmessage;
    window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
  await page.clock.runFor(31_000);
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility'));
    const s = (window as any).controlTest; s.oldError(); s.oldMessage({ data: JSON.stringify({ ...s.event, scene: { ...s.event.scene, revision: 99 } }) }); });
  expect(await snapshot(page)).toMatchObject({ sockets: 2, events: [1], diagnostics: [{ phase: 'connecting' }] });
  await page.evaluate(() => (window as any).controlTest.stop());
  await page.clock.runFor(120_000);
  await page.evaluate(() => { window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('webobs:reconnect-control')); window.dispatchEvent(new Event('webobs:visibility')); });
  expect(await snapshot(page)).toMatchObject({ sockets: 2, diagnostics: [] });
});

test('opt-in diagnostics copy bounded counters and fit mobile without private scene data', async ({ page }) => {
  await setup(page); await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(async () => { const host = document.createElement('div'); host.id = 'control-diagnostics-test'; document.body.appendChild(host);
    const { mountControlDiagnostics } = await import('/tests/harness/controlDiagnosticsMount.tsx'); mountControlDiagnostics(host);
    const s = (window as any).controlTest; s.sockets[0].open(); s.sockets[0].sendFixture(s.event); });
  const host = page.locator('#control-diagnostics-test');
  await expect(host.getByRole('button', { name: '复制诊断计数' })).toHaveCount(0);
  await host.getByRole('checkbox').check();
  await expect(host.getByRole('heading', { name: /场景同步正常/ })).toBeVisible();
  await host.getByRole('button', { name: '复制诊断计数' }).click();
  const copied = await page.evaluate(() => (window as any).controlTest.clipboard);
  expect(JSON.parse(copied)).toMatchObject({ format: 'webobs-control-diagnostics-v1', connections: [{ messages: 1, phase: 'online' }] });
  expect(copied).not.toMatch(/private|confidential|https?:|password|token/);
  await host.getByRole('button', { name: '重新连接场景同步' }).click();
  await expect(host.getByRole('button', { name: '重新连接场景同步' })).toBeDisabled();
  expect((await snapshot(page)).sockets).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mkdir('../tests/artifacts/v4-control-recovery', { recursive: true });
  await host.screenshot({ path: '../tests/artifacts/v4-control-recovery/diagnostics-mobile.png' });
});

test('browser WebSocket reconnects to a new scene after the routed server closes the old subscription', async ({ page, context }) => {
  let sockets = 0;
  await context.routeWebSocket('**/api/v1/ws', (socket) => {
    const revision = ++sockets;
    socket.send(JSON.stringify({ type: 'scene.snapshot', scene: { schemaVersion: 5, revision, id: 'wire-fixture', name: 'Fixture',
      canvas: { width: 640, height: 360, backgroundColor: '#000000' }, sources: [], items: [] } }));
    if (revision === 1) setTimeout(() => socket.close({ code: 1012, reason: 'routed server restart' }), 100);
  });
  await page.goto('/tests/harness/usability.html');
  await page.evaluate(async () => { const { connectSceneEvents } = await import('/src/api.ts'); const state: any = { events: [], states: [] };
    state.stop = connectSceneEvents((event) => state.events.push(event.scene.revision), (connected) => state.states.push(connected)); (window as any).wireControl = state; });
  await expect.poll(() => page.evaluate(() => (window as any).wireControl.events)).toEqual([1, 2]);
  expect(await page.evaluate(() => (window as any).wireControl.states)).toEqual([true, false, true]);
  await page.evaluate(() => (window as any).wireControl.stop());
});
