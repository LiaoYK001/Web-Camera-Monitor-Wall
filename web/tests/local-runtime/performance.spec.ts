import { expect, test } from '@playwright/test';

test('keeps 12 live tiles stable during audio meter updates and unchanged account refreshes', async ({ page }) => {
  await page.addInitScript(() => {
    class Node {
      fftSize = 1024; gain = this; delayTime = this; calls = 0;
      connect(node: any) { return node; } disconnect() {} setTargetAtTime() {}
      getFloatTimeDomainData(buffer: Float32Array) { buffer.fill((window as any).fixtureSampleAmplitude ?? (.2 + .1 * Math.sin(this.calls++))); }
    }
    class Context {
      state = 'suspended'; currentTime = 0; destination = new Node();
      createGain() { return new Node(); } createAnalyser() { return new Node(); }
      createDelay() { return new Node(); } createMediaStreamSource() { return new Node(); }
      async resume() { this.state = 'running'; } async suspend() { this.state = 'suspended'; } async close() { this.state = 'closed'; }
    }
    window.AudioContext = Context as unknown as typeof AudioContext;
  });
  await page.goto('/tests/harness/usability.html?performance');
  await expect(page.locator('.direct-tile.live')).toHaveCount(12);
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeVisible();
  await page.evaluate(async () => {
    const { getDirectAudioMixer } = await import('/src/directAudioMixer.ts');
    const mixer = getDirectAudioMixer();
    mixer.bindStream('audio-source-1', { getAudioTracks: () => [{}] } as MediaStream);
  });
  await page.getByRole('button', { name: '🔊 启用声音监听', exact: true }).click();
  await page.waitForTimeout(300);
  const result = await page.evaluate(async () => {
    const metrics = (window as any).fixturePerformance;
    const offers = document.documentElement.dataset.fixtureOffers;
    const video = document.querySelector('video')!;
    const startTime = video.currentTime;
    metrics.sceneReads = metrics.commits = metrics.renderMs = 0;
    // The real mixer timer samples a changing synthetic analyser at 10 Hz.
    await new Promise((resolve) => setTimeout(resolve, 4000));
    const meters = { ...metrics };
    metrics.sceneReads = metrics.commits = metrics.renderMs = 0;
    for (let index = 0; index < 3; index++) {
      window.dispatchEvent(new Event('focus'));
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    const requests = JSON.parse(document.documentElement.dataset.fixtureMetrics!);
    return { meters, preferences: { ...metrics }, offersBefore: offers, offersAfter: document.documentElement.dataset.fixtureOffers,
      playedSeconds: video.currentTime - startTime, requests: { monitorReads: requests.monitorReads, monitorSaves: requests.monitorSaves.length } };
  });
  console.log('PERFORMANCE_RECEIPT', JSON.stringify(result));
  expect(result.meters.sceneReads).toBe(0);
  expect(result.preferences.sceneReads).toBe(0);
  expect(result.requests.monitorReads).toBeGreaterThanOrEqual(4);
  expect(result.requests.monitorSaves).toBe(1); // Explicitly enabling monitoring only.
  expect(result.offersAfter).toBe(result.offersBefore);
  expect(result.playedSeconds).toBeGreaterThan(2);
  const tile = page.locator('.direct-tile[data-source-id="audio-source-1"]');
  await page.evaluate(() => { (window as any).fixtureSampleAmplitude = 1; });
  await expect(tile.getByLabel('音频超过阈值')).toBeVisible();
  await expect(tile.getByLabel('音频峰值 0.0 dBFS')).toBeVisible();
  await page.evaluate(() => { (window as any).fixtureSampleAmplitude = 0; });
  await expect(tile.getByLabel('音频超过阈值')).toHaveCount(0);
  await expect(tile.getByLabel('音频峰值 -120.0 dBFS')).toBeVisible();
});

test('analysis samples fresh frames at the configured rate and leaves no callbacks after stop', async ({ page }) => {
  await page.goto('/tests/harness/usability.html');
  const result = await page.evaluate(async () => {
    const { BrowserAnalyticsRuntime } = await import('/src/analyticsRuntime.ts');
    const { resetAnalyticsScheduler } = await import('/src/analyticsScheduler.ts');
    resetAnalyticsScheduler();
    const original = window.Worker;
    let samples = 0, callbacks = 0, stopped = false;
    class WorkerStub {
      addEventListener() {} terminate() { stopped = true; }
      postMessage(message: any) { if (message.type === 'frame') samples++; }
    }
    window.Worker = WorkerStub as unknown as typeof Worker;
    const canvas = document.createElement('canvas'); canvas.width = 160; canvas.height = 90;
    const video = document.createElement('video'); video.muted = true;
    video.srcObject = canvas.captureStream(60); document.body.appendChild(video);
    const frames = window.setInterval(() => { const context = canvas.getContext('2d')!; context.fillStyle = samples % 2 ? 'red' : 'blue'; context.fillRect(0, 0, 160, 90); }, 16);
    await video.play();
    const request = video.requestVideoFrameCallback.bind(video);
    video.requestVideoFrameCallback = (callback) => request((now, metadata) => { callbacks++; callback(now, metadata); });
    const runtime = new BrowserAnalyticsRuntime({ video, cameraId: 'synthetic', profileId: 'main',
      policy: { motionEnabled: true, sceneChangeEnabled: false, personEnabled: false, forceAnalyticsAlwaysOn: false, motion: { sampleFps: 2 } } as never });
    try {
      runtime.start(); await new Promise((resolve) => setTimeout(resolve, 2200));
      const before = { samples, callbacks }; runtime.stop();
      await new Promise((resolve) => setTimeout(resolve, 600));
      return { before, after: { samples, callbacks }, stopped };
    } finally {
      runtime.stop(); window.clearInterval(frames);
      (video.srcObject as MediaStream).getTracks().forEach((track) => track.stop()); video.remove(); window.Worker = original;
    }
  });
  console.log('ANALYTICS_PERFORMANCE_RECEIPT', JSON.stringify(result));
  expect(result.before.samples).toBeGreaterThanOrEqual(3);
  expect(result.before.callbacks).toBeLessThanOrEqual(6);
  expect(result.after).toEqual(result.before);
  expect(result.stopped).toBe(true);
});

test('slow composite meters stay single flight, pause in the background and reject stale results', async ({ page }) => {
  await page.goto('/tests/harness/usability.html');
  await page.evaluate(async () => {
    const originalFetch = window.fetch.bind(window);
    const metrics = { calls: 0, aborted: 0, pending: [] as Array<(peak: number) => void> };
    Object.assign(window, { compositePerformance: metrics });
    window.fetch = async (input, init) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.pathname === '/api/v2/audio/mixer') {
        metrics.calls++;
        // Deliberately ignore cancellation to verify the generation guard too.
        init?.signal?.addEventListener('abort', () => metrics.aborted++, { once: true });
        return new Promise<Response>((resolve) => metrics.pending.push((peak) => resolve(new Response(JSON.stringify({
          sources: [{ sourceId: 'meter-source', rmsDbfs: peak - 3, peakDbfs: peak }],
        }), { headers: { 'Content-Type': 'application/json' } }))));
      }
      return originalFetch(input, init);
    };
    const { mountAudioWorkspace } = await import('/tests/harness/audioWorkspaceMount.tsx');
    const host = document.createElement('div'); document.body.appendChild(host);
    const scene: any = { schemaVersion: 5, revision: 1, id: 'meter-scene', name: 'Meter', canvas: { width: 640, height: 360, backgroundColor: '#000000' },
      sources: [{ id: 'meter-source', kind: 'rtsp', name: 'Synthetic audio', rtspUrl: 'rtsp://127.0.0.1/fixture', muted: true, volume: 1, monitoring: 'off', audioTrack: 1, syncOffsetMs: 0, filters: [] }], items: [] };
    mountAudioWorkspace({ schemaVersion: 1, revision: 1, previewSceneId: scene.id, programSceneId: scene.id, scenes: [scene], transition: { kind: 'cut', durationMs: 0 } }, host);
  });
  // A confirmed track allows the workbench to show the backend's source level.
  await page.evaluate(async () => {
    const original = window.fetch.bind(window);
    window.fetch = async (input, init) => String(input).endsWith('/audio-tracks') ? new Response(JSON.stringify({ probed: true,
      tracks: [{ index: 0, streamIndex: 0, codec: 'opus', channels: 1, channelLayout: 'mono', sampleRate: 48000, language: '', title: 'Synthetic',
        sourceCodecBrowserCompatible: true, endpoint: '/api/v1/sources/meter-source/audio-tracks/0/whep' }] }),
      { headers: { 'Content-Type': 'application/json' } }) : original(input, init);
  });
  await page.getByRole('button', { name: '重新探测', exact: true }).click();
  await page.getByRole('button', { name: 'Composite', exact: true }).click();
  const calls = () => page.evaluate(() => (window as any).compositePerformance.calls);
  await expect.poll(calls).toBe(1);
  await page.waitForTimeout(850);
  expect(await calls()).toBe(1);
  await page.evaluate(() => (window as any).compositePerformance.pending[0](-21));
  await expect(page.getByText('Peak -21.0 dBFS', { exact: true })).toBeVisible();
  await expect.poll(calls).toBe(2);
  await page.evaluate(() => { window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
  await page.waitForTimeout(600);
  expect(await calls()).toBe(2);
  expect(await page.evaluate(() => (window as any).compositePerformance.aborted)).toBe(1);
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
  await expect.poll(calls).toBe(3);
  await page.evaluate(() => (window as any).compositePerformance.pending[2](-9));
  await expect(page.getByText('Peak -9.0 dBFS', { exact: true })).toBeVisible();
  await page.evaluate(() => {
    (window as any).compositePerformance.pending[1](-1);
    window.dispatchEvent(new CustomEvent('webobs:direct-audio-meters', { detail: { state: 'running', inputCount: 1, level: 1, sources: [] } }));
  });
  await page.waitForTimeout(100);
  await expect(page.getByText('Peak -9.0 dBFS', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Direct', exact: true }).click();
  const after = await calls();
  await page.waitForTimeout(400);
  expect(await calls()).toBe(after);
});
