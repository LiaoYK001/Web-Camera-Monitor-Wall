import { expect, test } from '@playwright/test';

const sceneFixture = {
  schemaVersion: 5,
  revision: 1,
  id: 'projector-fixture',
  name: 'Projector fixture',
  canvas: { width: 1920, height: 1080, backgroundColor: '#000000' },
  sources: [{
    id: 'source-0', kind: 'color', name: 'Source 0', color: '#101820',
    muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [],
  }],
  items: [{
    id: 'item-0', sourceId: 'source-0', x: 0, y: 0, width: 1920, height: 1080, scaleMode: 'contain',
    crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0,
    visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal',
  }],
};

/** Keeps the projector tests off the media plane and free of real negotiation. */
async function mockBackend(page: import('@playwright/test').Page) {
  await page.route('**/api/**', (route) => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/v1/auth/setup', (route) => route.fulfill({ json: { registrationOpen: false } }));
  await page.route('**/api/v2/account/me', (route) => route.fulfill({ json: {
    username: 'projector-fixture', displayName: 'Test', avatar: 'camera', roles: ['admin'], permissions: ['settings.manage'], scopes: [], acl: [],
  } }));
  await page.route('**/api/v2/account/preferences/*', (route) => route.fulfill({ json: { value: route.request().url().endsWith('/monitor-view') ? {
    telemetry: { enabled: true },
    sourceDecorations: { 'source-0': { audioMeter: { enabled: true } } },
    projectorOutput: 'full',
  } : null } }));
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'projector-fixture', via: 'session' },
  }));
  await page.route('**/api/v1/scene', (route) => route.fulfill({ json: sceneFixture }));
  await page.route('**/api/v1/studio', (route) => route.fulfill({ json: {
    schemaVersion: 1, revision: 1, scenes: [sceneFixture], previewSceneId: sceneFixture.id,
    programSceneId: sceneFixture.id, transition: { kind: 'cut', durationMs: 0 },
  } }));
  await page.route('**/api/v1/program/status', (route) => route.fulfill({ json: { enabled: false } }));
  await page.route('**/api/v1/program/whep', (route) => route.fulfill({ status: 503, json: {} }));
  await page.route('**/api/v1/playback/capabilities', (route) => route.fulfill({ json: { modes: { direct: { enabled: true } }, sources: [] } }));
  await page.route('**/api/v1/cameras', (route) => route.fulfill({ json: { cameras: [] } }));
  await page.route('**/api/v2/source-catalog*', (route) => route.fulfill({
    json: { schemaVersion: 2, page: 1, limit: 256, total: 0, items: [] },
  }));
}

test('projector route shows the final picture without the workspace shell', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#projector');

  const projector = page.locator('.projector-shell');
  await expect(projector).toHaveAttribute('data-projector-mode', 'direct');
  await expect(projector.locator('.direct-preview')).toBeVisible();
  // The detached window must never be a second copy of the wall.
  await expect(page.locator('.workspace-shell')).toHaveCount(0);
  await expect(projector.locator('.monitor-view-controls')).toHaveCount(0);
  await expect(projector.locator('.monitor-source-rail')).toHaveCount(0);
  await expect(projector.locator('.telemetry-overlay')).toBeVisible();
  await expect(projector.locator('.tile-audio-meter')).toBeVisible();
});

test('picture-only projector choice hides in-frame decorations', async ({ page }) => {
  await mockBackend(page);
  await page.route('**/api/v2/account/preferences/monitor-view', (route) => route.fulfill({ json: { value: {
    telemetry: { enabled: true },
    sourceDecorations: { 'source-0': { audioMeter: { enabled: true } } },
    projectorOutput: 'picture',
  } } }));
  await page.goto('/#projector');
  const projector = page.locator('.projector-shell');
  await expect(projector.locator('.direct-preview')).toBeVisible();
  await expect(projector.locator('.telemetry-overlay')).toBeHidden();
  await expect(projector.locator('.tile-audio-meter')).toBeHidden();
});

test('composite projector shows only the program picture', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#projector-composite');

  const projector = page.locator('.projector-shell');
  await expect(projector).toHaveAttribute('data-projector-mode', 'composite');
  await expect(projector.locator('.program-preview')).toHaveCount(1);
  await expect(projector.locator('.program-preview video')).toHaveCount(1);
  await expect(page.locator('.workspace-shell')).toHaveCount(0);
  // Diagnostics stay on the wall; the projector keeps the in-frame status chip.
  await expect(projector.locator('.program-diagnostics')).toBeHidden();
});

test('ordinary routes keep the full workspace shell', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#monitor');

  await expect(page.locator('.workspace-shell')).toHaveCount(1);
  await expect(page.locator('.projector-shell')).toHaveCount(0);
});

test('a delayed optional readout module does not block or replace Monitor playback', async ({ page }) => {
  await mockBackend(page);
  let release!: () => void;
  let requested!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  const loading = new Promise<void>(resolve => { requested = resolve; });
  await page.route('**/src/MonitorProcessStatus.tsx*', async route => {
    requested(); await delayed; await route.continue();
  });
  try {
    await page.goto('/#monitor');
    await loading;
    await expect(page.locator('.monitor-workspace')).toBeVisible({ timeout: 2000 });
    await page.getByRole('button', { name: '服务端 Program', exact: true }).click();
    const video = page.locator('.program-preview video');
    await expect(video).toHaveCount(1);
    const original = await video.elementHandle();
    release();
    await expect(page.getByRole('button', { name: '实时占用', exact: true })).toBeEnabled();
    expect(await video.evaluate((value, retained) => value === retained, original)).toBe(true);
    await original?.dispose();
  } finally { release(); }
});

test('monitor CPU readout preserves the media element and only polls while expanded', async ({ page }, testInfo) => {
  await mockBackend(page);
  let reads = 0;
  await page.route('**/api/v1/system/processes', route => {
    reads++;
    return route.fulfill({ json: { scope: 'desktop-process-tree', cpuLogicalCores: 32, processes: [
      { name: 'desktop', cpuPercent: 320, instances: 5, rssKiB: 1000 },
      { name: 'ffmpeg', cpuPercent: 64, instances: 2, rssKiB: 500 },
      { name: 'webobsd', cpuPercent: 16, instances: 1, rssKiB: 100 },
    ] } });
  });
  await page.clock.install();
  await page.goto('/#monitor');
  await page.getByRole('button', { name: '服务端 Program', exact: true }).click();
  const video = page.locator('.program-preview video');
  await expect(video).toHaveCount(1);
  await video.evaluate(value => { (window as any).retainedMonitorVideo = value; });
  const toggle = page.getByRole('button', { name: '实时占用', exact: true });
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await page.clock.runFor(11_000);
  expect(reads).toBe(0);
  await toggle.click();
  const readout = page.getByRole('region', { name: '监看实时占用' });
  await expect(readout).toContainText('采样中');
  await page.clock.runFor(5001);
  await expect(readout).toContainText('本应用 CPU 12.5%');
  await expect(readout).toContainText('桌面 / 浏览器 10.0%');
  await expect(readout).toContainText('FFmpeg 2.0%');
  await page.screenshot({ path: testInfo.outputPath('monitor-process-readout.png') });
  expect(await video.evaluate(value => value === (window as any).retainedMonitorVideo)).toBe(true);
  expect(new URL(page.url()).hash).toBe('#monitor');
  await toggle.click();
  await expect(readout).toHaveCount(0);
  const stoppedAt = reads;
  await page.clock.runFor(15_000);
  expect(reads).toBe(stoppedAt);
  expect(await video.evaluate(value => value === (window as any).retainedMonitorVideo)).toBe(true);
});

test('monitor readout does not label server-only CPU as the watching device total', async ({ page }) => {
  await mockBackend(page);
  await page.route('**/api/v1/system/processes', route => route.fulfill({ json: {
    processes: [{ name: 'ffmpeg', cpuPercent: 160, instances: 1, rssKiB: 1000 }],
  } }));
  await page.clock.install();
  await page.goto('/#monitor');
  await page.getByRole('button', { name: '实时占用', exact: true }).click();
  const readout = page.getByRole('region', { name: '监看实时占用' });
  await expect(readout).toContainText('单个逻辑处理器 100%');
  await page.clock.runFor(5001);
  await expect(readout).toContainText('FFmpeg 160.0%');
  await expect(readout).not.toContainText('本应用 CPU');
});

test('monitor readout bounds hung reads and cancels hidden or closed observations', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#monitor');
  const toggle = page.getByRole('button', { name: '实时占用', exact: true });
  await expect(toggle).toBeVisible();
  await page.clock.install();
  await page.evaluate(() => {
    const original = window.fetch;
    const requests: any[] = [];
    (window as any).monitorProcessRequests = requests;
    window.fetch = (input, init) => new URL(String(input), location.href).pathname === '/api/v1/system/processes'
      ? new Promise(resolve => requests.push({ signal: init?.signal, resolve })) : original(input, init);
  });
  const count = () => page.evaluate(() => (window as any).monitorProcessRequests.length);
  await toggle.click();
  await expect.poll(count).toBe(1);
  await page.clock.runFor(8001);
  await expect(page.getByRole('region', { name: '监看实时占用' })).toContainText('暂时无法读取');
  expect(await page.evaluate(() => (window as any).monitorProcessRequests[0].signal.aborted)).toBe(true);
  await page.clock.runFor(5001);
  await expect.poll(count).toBe(2);
  await page.evaluate(() => { window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
  await page.clock.runFor(25_000);
  expect(await count()).toBe(2);
  expect(await page.evaluate(() => (window as any).monitorProcessRequests.every((r: any) => r.signal.aborted))).toBe(true);
  await page.evaluate(() => {
    (window as any).monitorProcessRequests.forEach((r: any) => r.resolve(Response.json({ processes: [{ name: 'STALE CPU', cpuPercent: 100 }] })));
  });
  await expect(page.getByRole('region', { name: '监看实时占用' })).not.toContainText('STALE CPU');
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
  await expect.poll(count).toBe(3);
  await toggle.click();
  expect(await page.evaluate(() => (window as any).monitorProcessRequests[2].signal.aborted)).toBe(true);
  await page.clock.runFor(15_000);
  expect(await count()).toBe(3);
});

test('resolves the projector route and opens a reusable detached window', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/');

  const result = await page.evaluate(async () => {
    const projector = await import('/src/projector.ts');
    const opened: string[] = [];
    const original = window.open;
    window.open = ((url?: string | URL, name?: string, features?: string) => {
      opened.push([String(url), String(name), String(features)].join('|'));
      return null;
    }) as typeof window.open;
    try {
      projector.openProjectorWindow('direct');
      projector.openProjectorWindow('composite');
    } finally {
      window.open = original;
    }
    return {
      opened,
      modes: [
        projector.projectorModeFromHash('#projector'),
        projector.projectorModeFromHash('#/projector-composite'),
        projector.projectorModeFromHash('#projector?mode=composite'),
        projector.projectorModeFromHash('#monitor'),
      ],
    };
  });

  expect(result.modes).toEqual(['direct', 'composite', 'direct', null]);
  expect(result.opened).toHaveLength(2);
  expect(result.opened[0]).toMatch(/^\/#projector\|webobs-projector-direct\|/);
  expect(result.opened[1]).toMatch(/^\/#projector-composite\|webobs-projector-composite\|/);
});
