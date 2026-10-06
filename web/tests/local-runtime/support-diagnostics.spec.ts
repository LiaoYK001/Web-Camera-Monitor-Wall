import { expect, test, type Page } from '@playwright/test';

const sentinel = 'SECRET_SENTINEL_账户_摄像机_credential';
async function open(page: Page) {
  await page.goto('/tests/harness/usability.html');
  await page.evaluate(async () => {
    const diagnostics = await import('/src/diagnosticsRuntime.ts');
    const report = await import('/src/supportReport.ts');
    diagnostics.resetDiagnostics();
    const fixture = { diagnostics, report, copied: '', nativeCalls: 0 };
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { fixture.copied = text; } } });
    (window as any).supportFixture = fixture;
  });
}
async function mount(page: Page) {
  await page.evaluate(async () => {
    const host = document.createElement('div'); host.id = 'support-diagnostics'; document.body.appendChild(host);
    const { mountControlDiagnostics } = await import('/tests/harness/controlDiagnosticsMount.tsx');
    (window as any).supportFixture.unmount = mountControlDiagnostics(host);
  });
  return page.locator('#support-diagnostics');
}
function assertNoSecrets(text: string) {
  expect(text).not.toContain(sentinel);
  expect(text).not.toMatch(/https?:|rtsp:|Bearer |secret-camera|private-scene|private-account|C:[/\\]|upstream-password/);
  const forbidden = new Set(['url', 'endpoint', 'address', 'user', 'account', 'password', 'token', 'cameraId', 'scopeId', 'sourceId', 'path', 'summary', 'explanation', 'technicalDetails', 'message', 'stack', 'settings', 'recovery', 'releaseNotes', 'implementation']);
  const scan = (value: unknown) => {
    if (!value || typeof value !== 'object') return;
    for (const [key, item] of Object.entries(value)) { expect(forbidden.has(key), key).toBe(false); scan(item); }
  };
  scan(JSON.parse(text));
}

test('user explicitly generates, copies and downloads bounded local report; mobile and clipboard fallback', async ({ page }) => {
  await open(page); await page.setViewportSize({ width: 390, height: 844 });
  const host = await mount(page);
  await expect(host.getByRole('button', { name: '生成支持报告' })).toHaveCount(0);
  await host.getByRole('checkbox').check();
  const support = host.getByRole('region', { name: '安全支持报告' });
  await expect(support.getByRole('button', { name: '下载支持报告' })).toBeDisabled();
  expect(await page.evaluate(() => (window as any).supportFixture.copied)).toBe('');
  const requests: string[] = []; page.on('request', request => requests.push(request.url()));
  await support.getByRole('button', { name: '生成支持报告' }).click();
  const content = support.getByRole('textbox', { name: '支持报告内容' });
  await expect(content).toBeVisible();
  const text = await content.inputValue(); assertNoSecrets(text);
  expect(JSON.parse(text)).toMatchObject({ format: 'webobs-support-report-v1', nativeRead: 'unavailable',
    identity: { webUI: '9.8.7-dev.42', desktopApp: 'unavailable', apk: 'unavailable', webView: 'unavailable', electron: 'unavailable', sourceRevision: 'unavailable' },
    recorder: { availability: 'unavailable' }, exportJobs: { availability: 'unavailable' } });
  expect(requests.filter(url => url.includes('/api/'))).toEqual([]);
  await support.getByRole('button', { name: '复制支持报告' }).click();
  expect(await page.evaluate(() => (window as any).supportFixture.copied)).toBe(text);
  await page.evaluate(() => { Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: () => Promise.reject(new Error('private-account')) } }); });
  await support.getByRole('button', { name: '复制支持报告' }).click();
  await expect(support.getByRole('alert')).toContainText('手动复制');
  await expect(support.getByRole('alert')).not.toContainText('private-account');
  await expect(content).toHaveValue(text);
  const downloadEvent = page.waitForEvent('download');
  await support.getByRole('button', { name: '下载支持报告' }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('webobs-support-report.json');
  const stream = await download.createReadStream(); const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(Buffer.concat(chunks).toString('utf8')).toBe(text);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await host.getByRole('checkbox').uncheck();
  await expect(content).toHaveCount(0);
});

test('one snapshot distinguishes live video/control loss, foreground silent audio and stopped recorder/export', async ({ page }) => {
  await open(page);
  const text = await page.evaluate(async () => {
    const { diagnostics: d, report } = (window as any).supportFixture;
    const { createControlConnectionStatus } = await import('/src/controlConnectionStatus.ts');
    const control = createControlConnectionStatus();
    control.update({ phase: 'retrying', reason: 'transport_closed', attempts: 3, failures: 2, messages: 4, lastSnapshotAt: Date.now() - 1000, nextRetryAt: Date.now() + 3000 });
    const media = d.createMediaDiagnostic('direct'); media.attempt(); media.frame();
    media.stage({ playing: true, signaling: true, firstFrame: true, iceConnected: true, mediaReceived: true, autoplayBlocked: false, reconnects: 2, frames: 1, lastError: '' });
    window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility'));
    window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility'));
    d.observeAudio({ state: 'suspended', inputCount: 1, sources: [{ sourceId: 'secret-camera', audioTracks: 1, streamBound: true }] });
    d.observeRecorder({ status: 'degraded', diskPressure: true, cameras: [{ id: 'secret-camera', state: 'stopped' }] });
    d.observeExportJobs([{ id: 'secret-camera', state: 'failed', createdUtcMs: Date.now() - 500, updatedUtcMs: Date.now(), request: { mode: 'exact', cameraIds: ['secret-camera'] }, error: { code: 'export_disk_full', message: 'upstream-password' } }]);
    d.observeIssues([{ code: 'MEDIA_DIRECT_FALLBACK', state: 'open', severity: 'warning', component: 'browser-media', scopeId: 'secret-camera', firstSeenAt: Date.now(), lastSeenAt: Date.now(), occurrences: 3,
      technicalDetails: { transportMode: 'rtsp-tcp', adapter: 'rtsp', topology: 'gateway', retryCount: 2 } }], 'local');
    return report.captureSupportReport();
  });
  assertNoSecrets(text); const report = JSON.parse(text);
  expect(report.controls[0]).toMatchObject({ phase: 'retrying', reason: 'transport_closed', attempts: 3, failures: 2 });
  expect(report.media[0]).toMatchObject({ playing: true, reconnects: 2, transport: 'whep', topology: 'direct' });
  expect(report.media[0].firstFrameAt).toBeLessThanOrEqual(report.media[0].lastFrameAt);
  expect(report.media[0].lastFrameAt).toBeLessThanOrEqual(report.capturedAt);
  expect(report.events).toEqual(expect.arrayContaining([expect.objectContaining({ component: 'lifecycle', state: 'background' }), expect.objectContaining({ component: 'lifecycle', state: 'foreground' })]));
  expect(report.audio).toMatchObject({ state: 'suspended', audioTracks: 1 });
  expect(report.recorder).toMatchObject({ status: 'degraded', diskPressure: true, cameras: { counts: { stopped: 1 } } });
  expect(report.exportJobs).toMatchObject({ counts: { failed: 1 }, recent: [{ reason: 'export_disk_full' }] });
  expect(report.issues.local.items[0]).toMatchObject({ code: 'MEDIA_DIRECT_FALLBACK', transportMode: 'rtsp-tcp', topology: 'gateway' });
  expect(report.identity).toMatchObject({ client: 'android-lifecycle-bridge', apk: 'unavailable', webView: 'unavailable' });
});

test('automatic sentinel scan and maximal-count fixture enforce allowlists and UTF-8 size bound', async ({ page }) => {
  await open(page);
  const result = await page.evaluate(async (secret) => {
    const { diagnostics: d, report } = (window as any).supportFixture;
    const hostile = { id: secret, name: secret, url: 'https://private-scene/?password=' + secret, account: secret, path: 'C:/private-account',
      phase: secret, reason: secret, attempts: Infinity, failures: -1, messages: secret, lastSnapshotAt: secret, code: secret, component: secret,
      severity: secret, state: secret, firstSeenAt: Infinity, lastSeenAt: secret, occurrences: secret,
      summary: secret, explanation: secret, technicalDetails: { reason: secret, topology: secret, adapter: secret, codec: secret, transportMode: secret },
      runtime: { phase: secret, detail: secret }, app: { version: '4.0.0-' + secret, platform: secret, architecture: secret },
      update: { phase: secret, message: secret, releaseNotes: secret }, settings: { recordingDirectory: secret }, recovery: { snapshot: secret },
      error: { code: secret, message: secret }, request: { mode: secret, cameraIds: [secret] }, result: { files: [{ downloadUrl: secret, name: secret }] },
      toJSON: () => { throw new Error('Raw inputs must never be serialized'); } };
    for (let i = 0; i < 2048; i++) {
      d.observeControl({ ...hostile, id: i, attempts: 1e30, failures: 1e30, connectedAt: 8640000000000000 });
      const m = d.createMediaDiagnostic(secret); m.attempt(); m.frame(); m.stage({ ...hostile, lastError: secret, frames: 1e30, reconnects: 1e30 }); m.retry(1e30); m.close();
    }
    const many = Array(4096).fill(hostile);
    d.observeIssues(many, 'local'); d.observeIssues(many, 'server'); d.observeExportJobs(many);
    d.observeRecorder({ ...hostile, cameras: many }); d.observeAudio({ ...hostile, sources: many }); d.observeNative(hostile); d.observeSession(hostile);
    const text = await report.captureSupportReport();
    const untrustedVersions = [secret, '4.0.0+' + secret, 'v4.0.0/' + secret, '4.0.0-dev.' + secret, 'http://x'].map(d.injectedVersion);
    return { text, limits: d.DIAGNOSTIC_LIMITS, untrustedVersions, versions: ['4.0.0', '3.4.0-dev.0', '3.5.0-dev.android.1'].map(d.injectedVersion) };
  }, sentinel);
  assertNoSecrets(result.text); const value = JSON.parse(result.text);
  expect(Buffer.byteLength(result.text, 'utf8')).toBeLessThanOrEqual(result.limits.bytes);
  expect(value.controls).toHaveLength(result.limits.controls); expect(value.media).toHaveLength(result.limits.media);
  expect(value.events).toHaveLength(result.limits.events); expect(value.issues.local.items).toHaveLength(result.limits.issues);
  expect(value.exportJobs.sampled).toBe(256); expect(value.exportJobs.omitted).toBe(3840);
  expect(value.recorder.cameras.sampled).toBe(256); expect(value.audio.sourcesSampled).toBe(256);
  expect(value.dropped.media).toBe(2048 - result.limits.media); expect(value.dropped.controls).toBe(2048 - result.limits.controls);
  expect(value.dropped.events).toBeGreaterThan(0); expect(value.controls[0].attempts).toBe(1_000_000_000);
  expect(value.controls[0].lastSnapshotAt).toBe(null); expect(value.issues.server.items[0].code).toBe('unavailable');
  expect(result.untrustedVersions).toEqual(Array(5).fill('unavailable'));
  expect(result.versions).toEqual(['4.0.0', '3.4.0-dev.0', '3.5.0-dev.android.1']);
});

test('native identity is read only on request and newer push supersedes delayed IPC', async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    const f = (window as any).supportFixture;
    (window as any).webobsDesktop = { version: 99, status: () => { f.nativeCalls++; return new Promise(resolve => { f.resolveNative = resolve; }); } };
  });
  const host = await mount(page); await host.getByRole('checkbox').check();
  expect(await page.evaluate(() => (window as any).supportFixture.nativeCalls)).toBe(0);
  await host.getByRole('button', { name: '生成支持报告' }).click();
  await expect(host.getByRole('button', { name: '正在生成支持报告…' })).toBeDisabled();
  await page.evaluate(() => {
    const f = (window as any).supportFixture;
    f.diagnostics.observeNative({ app: { version: '4.0.1', platform: 'win32', architecture: 'x64', packaged: true }, runtime: { phase: 'failed', detail: 'C:/private-account' }, update: { phase: 'error', message: 'upstream-password' } });
    f.resolveNative({ app: { version: '4.0.0' }, runtime: { phase: 'ready' } });
  });
  const content = host.getByRole('textbox', { name: '支持报告内容' }); await expect(content).toBeVisible();
  const text = await content.inputValue(); assertNoSecrets(text);
  expect(JSON.parse(text)).toMatchObject({ identity: { desktopApp: '4.0.1', electron: 'unavailable' }, native: { runtimePhase: 'failed', restartCount: 'unavailable', restartReason: 'unavailable' } });
  expect(await page.evaluate(() => (window as any).supportFixture.nativeCalls)).toBe(1);
});

test('native timeout/rejection/unmount remain bounded; late settlement cannot fabricate state', async ({ page }) => {
  await open(page); await page.clock.install();
  await page.evaluate(() => {
    const f = (window as any).supportFixture;
    (window as any).webobsDesktop = { status: () => { f.nativeCalls++; return new Promise(resolve => { f.resolveNative = resolve; }); } };
  });
  const host = await mount(page); await host.getByRole('checkbox').check();
  await host.getByRole('button', { name: '生成支持报告' }).click();
  await page.clock.runFor(1600);
  const content = host.getByRole('textbox', { name: '支持报告内容' }); await expect(content).toBeVisible();
  expect(JSON.parse(await content.inputValue())).toMatchObject({ nativeRead: 'timeout', native: { availability: 'unavailable' } });
  // Repeated attempts share one pending read instead of accumulating native calls.
  await host.getByRole('button', { name: '生成支持报告' }).click(); await page.clock.runFor(1600);
  await expect(content).toBeVisible();
  expect(await page.evaluate(() => (window as any).supportFixture.nativeCalls)).toBe(1);
  await page.evaluate(() => (window as any).supportFixture.resolveNative({ app: { version: '4.0.0' }, runtime: { phase: 'ready' } }));
  expect(await page.evaluate(() => (window as any).supportFixture.diagnostics.diagnosticSnapshot().native)).toEqual({ availability: 'unavailable' });
  await page.evaluate(() => { (window as any).webobsDesktop.status = () => Promise.reject(new Error('upstream-password')); });
  await host.getByRole('button', { name: '生成支持报告' }).click(); await expect(content).toBeVisible();
  expect(JSON.parse(await content.inputValue()).nativeRead).toBe('unavailable'); assertNoSecrets(await content.inputValue());
  await page.evaluate(() => { (window as any).webobsDesktop.status = () => new Promise(() => {}); });
  await host.getByRole('button', { name: '生成支持报告' }).click(); await host.getByRole('checkbox').uncheck();
  await page.clock.runFor(1600); await host.getByRole('checkbox').check();
  await expect(content).toHaveCount(0); await expect(host.getByRole('button', { name: '生成支持报告' })).toBeEnabled();
});

test('cached observations explicitly age and session reset drops previous observations', async ({ page }) => {
  await open(page); await page.clock.install();
  await page.evaluate(() => {
    const d = (window as any).supportFixture.diagnostics;
    d.observeRecorder({ status: 'ok', diskPressure: false, cameras: [] });
    d.observeExportJobs([]); d.observeNative({ app: { version: '4.0.0' }, runtime: { phase: 'ready' } });
    d.observeSession({ user: 'private-account', authenticated: true, authenticationEnabled: true });
  });
  await page.clock.runFor(30_001);
  const aged = JSON.parse(await page.evaluate(() => (window as any).supportFixture.report.captureSupportReport()));
  expect(aged.recorder.availability).toBe('stale'); expect(aged.exportJobs.availability).toBe('stale');
  await page.evaluate(() => { const d = (window as any).supportFixture.diagnostics; d.resetDiagnostics(); d.observeSession({ authenticated: false }); });
  const reset = await page.evaluate(() => (window as any).supportFixture.report.captureSupportReport()); assertNoSecrets(reset);
  expect(JSON.parse(reset)).toMatchObject({ controls: [], media: [], events: [], recorder: { availability: 'unavailable' }, exportJobs: { availability: 'unavailable' }, native: { availability: 'unavailable' }, session: { authenticated: false } });
});
