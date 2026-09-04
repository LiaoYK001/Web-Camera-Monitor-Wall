import { expect, test } from '@playwright/test';

test('generates stable bounded Scene v5 layouts for every 1-16 and M/S combination', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const monitor = await import('/src/monitorView.ts');
    const failures: string[] = [];
    for (const portrait of [false, true]) for (let count = 1; count <= 16; count += 1) {
      for (let largeCount = 0; largeCount <= count; largeCount += 1) {
        const width = portrait ? 900 : 1600; const height = portrait ? 1600 : 900;
        const scene = {
          schemaVersion: 5 as const, revision: 1, id: 'fixture', name: 'fixture',
          canvas: { width, height, backgroundColor: '#000000' },
          sources: Array.from({ length: count }, (_, index) => ({
            id: `source-${index}`, kind: 'color' as const, name: `Source ${index}`, color: '#000000',
            muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [],
          })),
          items: Array.from({ length: count }, (_, index) => ({
            id: `item-${index}`, sourceId: `source-${index}`, x: 0, y: 0, width: 1, height: 1,
            scaleMode: 'contain' as const, crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: index,
            visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const,
          })),
        };
        const view = monitor.defaultMonitorView(); view.largeCount = largeCount;
        const laidOut = monitor.applyAutomaticLayout(scene, view);
        for (const item of laidOut.items) if (item.x < 0 || item.y < 0 || item.width <= 0 || item.height <= 0 ||
          item.x + item.width > width + .001 || item.y + item.height > height + .001)
          failures.push(`${portrait}/${count}/${largeCount}:bounds`);
        for (let left = 0; left < laidOut.items.length; left += 1) for (let right = left + 1; right < laidOut.items.length; right += 1) {
          const a = laidOut.items[left], b = laidOut.items[right];
          if (a.x < b.x + b.width - .001 && a.x + a.width > b.x + .001 &&
              a.y < b.y + b.height - .001 && a.y + a.height > b.y + .001)
            failures.push(`${portrait}/${count}/${largeCount}:overlap`);
        }
        if (largeCount > 0 && largeCount < count) {
          const largeArea = laidOut.items[0].width * laidOut.items[0].height;
          const smallArea = laidOut.items[largeCount].width * laidOut.items[largeCount].height;
          if (largeArea <= smallArea) failures.push(`${portrait}/${count}/${largeCount}:large-not-larger`);
        }
        const repeated = monitor.applyAutomaticLayout(laidOut, view);
        if (JSON.stringify(laidOut.items) !== JSON.stringify(repeated.items)) failures.push(`${portrait}/${count}/${largeCount}:unstable`);
      }
    }
    return failures;
  });
  expect(result).toEqual([]);
});

test('keeps browser analytics bounded, zoned, and confirms scene cuts', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const { MotionSceneEngine } = await import('/src/analyticsEngine.ts');
    const ids = { cameraId: 'cam-1', profileId: 'sub' };
    const zoned = new MotionSceneEngine();
    const base = new Uint8Array(16);
    zoned.evaluate({ width: 4, height: 4, pixels: base, timestamp: 1000 }, ids, { sensitivity: .1, debounceMs: 0,
      zones: [{ mode: 'include', polygon: [[0, 0], [0.5, 0], [0.5, 1], [0, 1]] }] });
    const outside = base.slice(); outside[15] = 255;
    const outsideResult = zoned.evaluate({ width: 4, height: 4, pixels: outside, timestamp: 2000 }, ids, { sensitivity: .1, debounceMs: 0,
      zones: [{ mode: 'include', polygon: [[0, 0], [0.5, 0], [0.5, 1], [0, 1]] }] });
    const inside = outside.slice(); inside[0] = 255;
    const insideResult = zoned.evaluate({ width: 4, height: 4, pixels: inside, timestamp: 3000 }, ids, { sensitivity: .1, debounceMs: 0,
      zones: [{ mode: 'include', polygon: [[0, 0], [0.5, 0], [0.5, 1], [0, 1]] }] });
    const cut = new MotionSceneEngine();
    cut.evaluate({ width: 4, height: 4, pixels: base, timestamp: 1000 }, ids);
    cut.evaluate({ width: 4, height: 4, pixels: new Uint8Array(16).fill(255), timestamp: 2000 }, ids,
      { sceneThreshold: .55, sceneConfirmFrames: 2, sceneCooldownMs: 0, sensitivity: 1 });
    const confirmed = cut.evaluate({ width: 4, height: 4, pixels: new Uint8Array(16).fill(255), timestamp: 3000 }, ids,
      { sceneThreshold: .55, sceneConfirmFrames: 2, sceneCooldownMs: 0, sensitivity: 1 });
    return { outside: outsideResult.signals.length, inside: insideResult.signals.some((signal) => signal.kind === 'motion'),
      scene: confirmed.signals.filter((signal) => signal.kind === 'scene-change').length };
  });
  expect(result).toEqual({ outside: 0, inside: true, scene: 1 });
});

test('keeps scene-change histogram baselines scoped to the active zones', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const { MotionSceneEngine } = await import('/src/analyticsEngine.ts');
    const ids = { cameraId: 'cam-zone', profileId: 'sub' };
    const zone = [{ mode: 'include' as const, polygon: [[0, 0], [0.5, 0], [0.5, 1], [0, 1]] }];
    const engine = new MotionSceneEngine();
    const left = new Uint8Array(16); const rightCut = left.slice();
    for (let index = 2; index < rightCut.length; index += 4) rightCut[index] = 255;
    engine.evaluate({ width: 4, height: 4, pixels: left, timestamp: 1000 }, ids, { zones: zone });
    const stable = engine.evaluate({ width: 4, height: 4, pixels: rightCut, timestamp: 2000 }, ids, {
      zones: zone, sceneThreshold: .55, sceneConfirmFrames: 1, sceneCooldownMs: 0,
    });
    return { sceneSignals: stable.signals.filter((signal) => signal.kind === 'scene-change').length, sceneChange: stable.sceneChange };
  });
  expect(result).toEqual({ sceneSignals: 0, sceneChange: 0 });
});

test('maps person boxes through Scene v5 crop and scale transforms', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const { mapDetectionBoxToTile } = await import('/src/monitorView.ts');
    const base = { id: 'item', sourceId: 'source', x: 0, y: 0, width: 1000, height: 1000,
      scaleMode: 'contain' as const, crop: { top: 0, right: 400, bottom: 0, left: 400 }, zIndex: 0,
      visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const };
    const mapped = mapDetectionBoxToTile({ x: .2, y: .25, width: .5, height: .5 }, base, 2000, 1000);
    const clipped = mapDetectionBoxToTile({ x: 0, y: 0, width: .1, height: .1 }, base, 2000, 1000);
    return { mapped, clipped };
  });
  expect(result.mapped.x).toBeGreaterThanOrEqual(0);
  expect(result.mapped.x).toBeLessThan(.01);
  expect(result.mapped.width).toBeGreaterThan(.8);
  expect(result.mapped.width).toBeLessThan(.85);
  expect(result.clipped.width).toBe(0);
});

test('keeps low-power selection and analytics signals fail-closed', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const monitor = await import('/src/monitorView.ts');
    const telemetry = await import('/src/mediaTelemetry.ts');
    const profiles = [
      { id: 'main', name: 'Main', role: 'main' as const, endpoint: '', videoCodec: 'h265', audioCodec: '', width: 1920, height: 1080, fps: 25 },
      { id: 'sub', name: 'Sub', role: 'sub' as const, endpoint: '', videoCodec: 'h264', audioCodec: '', width: 640, height: 360, fps: 5 },
      { id: 'snapshot', name: 'Snapshot', role: 'snapshot' as const, endpoint: '', videoCodec: 'jpeg', audioCodec: '', width: 320, height: 180, fps: 1 },
    ];
    const met = monitor.selectLowPowerProfile(profiles, 2);
    const unmet = monitor.selectLowPowerProfile(profiles.slice(0, 2), 2);
    const valid = monitor.validDetectionSignal({ schemaVersion: 1, cameraId: 'cam-1', profileId: 'sub', kind: 'motion', occurredAt: Date.now(), confidence: .8, source: 'browser' });
    const invalid = monitor.validDetectionSignal({ schemaVersion: 1, cameraId: 'cam-1', profileId: 'sub', kind: 'person', occurredAt: Date.now(), confidence: 2, boxes: [{ x: .9, y: 0, width: .2, height: 1 }], source: 'browser' });
    const motionWithBoxes = monitor.validDetectionSignal({ schemaVersion: 1, cameraId: 'cam-1', profileId: 'sub', kind: 'motion', occurredAt: Date.now(), confidence: .8, boxes: [{ x: 0, y: 0, width: .1, height: .1 }], source: 'browser' });
    const sources = ['a', 'b', 'c', 'd', 'e']; let bag: string[] = [];
    const first = monitor.nextRotationWindow(sources, [], 3, ['a'], 'random', bag, () => 0); bag = first.bag;
    const second = monitor.nextRotationWindow(sources, first.selection, 3, ['a'], 'random', bag, () => 0);
    const sequential = monitor.nextRotationWindow(sources, ['a', 'b'], 2, ['a'], 'sequential');
    return { met: met.profile?.id, metOk: met.targetMet, unmet: unmet.profile?.id, unmetOk: unmet.targetMet,
      reason: unmet.reason, valid, invalid, motionWithBoxes, first: first.selection, second: second.selection,
      randomUnique: new Set([...first.selection.slice(1), ...second.selection.slice(1)]).size,
      sequential: sequential.selection, overlay: monitor.defaultTelemetryOverlay(),
      unavailableText: telemetry.formatTelemetry({ fps: null, bytesPerSecond: null, codec: 'MJPEG', decoder: 'Unknown' }, ['fps', 'bitrate', 'codec', 'decoder']) };
  });
  expect(result).toEqual({ met: 'snapshot', metOk: true, unmet: 'sub', unmetOk: false,
    reason: 'no_low_frame_rate_profile', valid: true, invalid: false, motionWithBoxes: false,
    first: ['a', 'c', 'd'], second: ['a', 'e', 'b'], randomUnique: 4, sequential: ['a', 'c'],
    overlay: { enabled: false, fields: ['fps', 'bitrate', 'codec', 'decoder'], position: 'bottom-left', customX: 0,
      customY: 1, textOpacity: .9, backgroundEnabled: true, backgroundColor: '#000000', backgroundOpacity: .45,
      refreshIntervalMs: 1000 },
    unavailableText: 'FPS — · Speed — · MJPEG · Unknown' });
});

test('measures bounded telemetry and suspends only low-power invisible playback', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const telemetry = await import('/src/mediaTelemetry.ts');
    const lifecycle = await import('/src/mediaLifecycle.ts');
    const monitor = await import('/src/monitorView.ts');
    const now = performance.now();
    const reports = new Map<string, Record<string, unknown>>([
      ['inbound', { id: 'inbound', type: 'inbound-rtp', kind: 'video', isRemote: false,
        framesRendered: 25, framesDecoded: 25, bytesReceived: 46 * 1024, codecId: 'codec', decoderImplementation: 'D3D11 Video Decoder' }],
      ['codec', { id: 'codec', type: 'codec', mimeType: 'video/H265' }],
    ]);
    const sampled = await telemetry.sampleConnectionTelemetry({ close() {}, async getStats() {
      return { forEach: reports.forEach.bind(reports), get: reports.get.bind(reports) } as unknown as RTCStatsReport;
    } }, { at: now - 1000, frames: 10, bytes: 10 * 1024 });
    const video = document.createElement('video');
    const hls = telemetry.sampleElementTelemetry(video, {
      close() {}, getReceivedBytes: () => 30 * 1024, getCodec: () => 'H264',
    }, { at: performance.now() - 1000, frames: 5, bytes: 10 * 1024 }, 20);
    const signal = { schemaVersion: 1 as const, cameraId: 'cam', profileId: 'sub', kind: 'motion' as const,
      occurredAt: Date.now(), confidence: .8, source: 'browser' as const };
    const policy = { allowEventPromotion: true, promotionThreshold: .6, promotionHoldSeconds: 10,
      promotionCooldownSeconds: 20, forceAnalyticsAlwaysOn: false };
    const promoted = monitor.evaluatePromotion(signal, policy, { enabled: true, threshold: .5, holdSeconds: 5,
      cooldownSeconds: 5, lowPowerEnabled: false, now: 1000, cooldownUntil: 0 });
    const lowPowerRejected = monitor.evaluatePromotion(signal, policy, { enabled: true, threshold: .5, holdSeconds: 5,
      cooldownSeconds: 5, lowPowerEnabled: true, now: 1000, cooldownUntil: 0 });
    return {
      fps: sampled.telemetry.fps, speed: sampled.telemetry.bytesPerSecond,
      codec: sampled.telemetry.codec, decoder: sampled.telemetry.decoder,
      hlsFps: hls.telemetry.fps, hlsSpeed: hls.telemetry.bytesPerSecond, hlsCodec: hls.telemetry.codec,
      normalHidden: lifecycle.shouldRunPlayback({ lowPowerEnabled: false, documentVisible: false, tileIntersecting: false }),
      lowPowerDocumentHidden: lifecycle.shouldRunPlayback({ lowPowerEnabled: true, documentVisible: false, tileIntersecting: true }),
      lowPowerTileHidden: lifecycle.shouldRunPlayback({ lowPowerEnabled: true, documentVisible: true, tileIntersecting: false }),
      lowPowerVisible: lifecycle.shouldRunPlayback({ lowPowerEnabled: true, documentVisible: true, tileIntersecting: true }),
      promoted, lowPowerRejected,
    };
  });
  expect(result.fps).toBeGreaterThan(14);
  expect(result.fps).toBeLessThan(16);
  expect(result.speed).toBeGreaterThan(35 * 1024);
  expect(result.speed).toBeLessThan(37 * 1024);
  expect(result.codec).toBe('H265');
  expect(result.decoder).toBe('HW');
  expect(result.hlsFps).toBeGreaterThan(14);
  expect(result.hlsFps).toBeLessThan(16);
  expect(result.hlsSpeed).toBeGreaterThan(19 * 1024);
  expect(result.hlsSpeed).toBeLessThan(21 * 1024);
  expect(result.hlsCodec).toBe('H264');
  expect(result.normalHidden).toBe(true);
  expect(result.lowPowerDocumentHidden).toBe(false);
  expect(result.lowPowerTileHidden).toBe(false);
  expect(result.lowPowerVisible).toBe(true);
  expect(result.promoted).toEqual({ accepted: true, reason: '', holdUntil: 11000, cooldownUntil: 31000 });
  expect(result.lowPowerRejected.reason).toBe('low_power_software_analytics_disabled');
});

test('shares bounded frame and person analysis budgets across monitor tiles', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const scheduler = await import('/src/analyticsScheduler.ts');
    scheduler.resetAnalyticsScheduler();
    const frame = Array.from({ length: 8 }, (_, index) => scheduler.requestAnalyticsSlot('frame', index === 0 ? 'focus' : 'normal', index * 10));
    const person = Array.from({ length: 4 }, (_, index) => scheduler.requestAnalyticsSlot('person', index === 0 ? 'large' : 'normal', index * 10));
    const rejectedFrame = scheduler.requestAnalyticsSlot('frame', 'normal', 100);
    const rejectedPerson = scheduler.requestAnalyticsSlot('person', 'normal', 100);
    const afterWindow = scheduler.requestAnalyticsSlot('frame', 'normal', 1101);
    return { frame, person, rejectedFrame, rejectedPerson, afterWindow,
      snapshot: scheduler.analyticsSchedulerSnapshot(1101) };
  });
  expect(result.frame).toEqual([true, true, true, true, true, true, true, true]);
  expect(result.person).toEqual([true, true, true, true]);
  expect(result.rejectedFrame).toBe(false);
  expect(result.rejectedPerson).toBe(false);
  expect(result.afterWindow).toBe(true);
  expect(result.snapshot).toEqual({ frame: 1, person: 0, limits: { frame: 8, person: 4 } });
});

test('migrates MonitorView v1 safely and keeps operational details bounded', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const monitor = await import('/src/monitorView.ts');
    const issues = await import('/src/issueRuntime.ts');
    const audio = await import('/src/directAudioMixer.ts');
    let snapshot: import('/src/types.ts').OperationalIssue[] = [];
    const unsubscribe = issues.subscribeLocalIssues((value) => { snapshot = value; });
    issues.reportLocalIssue({
      code: 'SAFE_FIXTURE', scopeId: 'camera-1', component: 'test', summary: 'Fixture', explanation: 'Fixture',
      technicalDetails: { codec: 'h264', endpoint: 'rtsp://private.invalid/live', token: 'do-not-copy', retryCount: 2 },
    });
    const migrated = monitor.normalizeMonitorView({ schemaVersion: 1, largeCount: 99,
      localMonitorVolume: 4 } as unknown as Partial<import('/src/monitorView.ts').MonitorView>, 4);
    const issue = snapshot.find((value) => value.code === 'SAFE_FIXTURE');
    unsubscribe();
    return { version: migrated.schemaVersion, largeCount: migrated.largeCount,
      localMonitorVolume: migrated.localMonitorVolume, panels: migrated.panels,
      details: issue?.technicalDetails, silence: audio.amplitudeToDbfs(0), unity: audio.amplitudeToDbfs(1),
      half: audio.amplitudeToDbfs(.5) };
  });
  expect({ ...result, half: undefined }).toEqual({ version: 4, largeCount: 4, localMonitorVolume: 1,
    panels: { detailsOpen: false, issueCenterExpanded: false },
    details: { codec: 'h264', retryCount: 2 }, silence: -120, unity: 0,
    half: undefined });
  expect(result.half).toBeCloseTo(-6.0206, 3);
});

test('normalizes per-source decorations and removes stale overrides', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const monitor = await import('/src/monitorView.ts');
    const normalized = monitor.normalizeMonitorView({
      schemaVersion: 3,
      telemetry: { enabled: true, fields: ['fps', 'not-a-field'] },
      sourceDecorations: {
        'camera-1': { telemetry: { enabled: true, textOpacity: 4, backgroundOpacity: -1 }, audioMeter: { enabled: true, thresholdDbfs: -999, alertBorderWidth: 99 }, promotionKinds: { audio: true } },
        stale: { telemetry: { enabled: true } },
      },
    } as unknown as Partial<import('/src/monitorView.ts').MonitorView>, 2, ['camera-1']);
    return { version: normalized.schemaVersion, ids: Object.keys(normalized.sourceDecorations),
      telemetry: normalized.sourceDecorations['camera-1'].telemetry,
      audio: normalized.sourceDecorations['camera-1'].audioMeter,
      promotion: normalized.sourceDecorations['camera-1'].promotionKinds };
  });
  expect(result.version).toBe(4);
  expect(result.ids).toEqual(['camera-1']);
  expect(result.telemetry.textOpacity).toBe(1);
  expect(result.telemetry.backgroundOpacity).toBe(0);
  expect(result.audio.thresholdDbfs).toBe(-120);
  expect(result.audio.alertBorderWidth).toBe(12);
  expect(result.promotion).toEqual({ audio: true, motion: false, person: false });
});

test('persists the encrypted OBS workspace layout locally', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const runtime = await import('/src/localRuntime.ts');
    await runtime.saveWorkspaceLayout({ schemaVersion: 1, style: 'classic', docks: [
      { id: 'canvas', kind: 'canvas', region: 'center', order: 0, size: 55, collapsed: false },
    ] });
    const loaded = await runtime.loadWorkspaceLayout();
    return loaded && { style: loaded.style, dock: loaded.docks[0] };
  });
  expect(result).toEqual({ style: 'classic', dock: { id: 'canvas', kind: 'canvas', region: 'center', order: 0, size: 55, collapsed: false } });
});
