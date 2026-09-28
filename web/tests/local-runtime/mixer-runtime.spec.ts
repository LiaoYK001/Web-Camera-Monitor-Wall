import { expect, test } from '@playwright/test';

test('applies mute and monitor to both audio paths, reuses sample buffers and stops idle metering', async ({ page }) => {
  await page.route('**/api/**', (route) => route.fulfill({ json: {} }));
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const { DirectAudioMixer } = await import('/src/directAudioMixer.ts');
    const gains: any[] = [], analysers: any[] = [];
    class Node {
      value = 0; fftSize = 1024; gain = this; delayTime = this;
      buffers = new Set<Float32Array>(); calls = 0;
      connect(node: any) { return node; } disconnect() {}
      setTargetAtTime(value: number) { this.value = value; }
      getFloatTimeDomainData(buffer: Float32Array) { this.calls++; this.buffers.add(buffer); buffer.fill(.2); }
    }
    class Context {
      state = 'suspended'; currentTime = 0; destination = new Node();
      createGain() { const node = new Node(); gains.push(node); return node; }
      createAnalyser() { const node = new Node(); analysers.push(node); return node; }
      createDelay() { return new Node(); } createMediaStreamSource() { return new Node(); }
      async resume() { this.state = 'running'; } async suspend() { this.state = 'suspended'; } async close() { this.state = 'closed'; }
    }
    window.AudioContext = Context as unknown as typeof AudioContext;
    const mixer = new DirectAudioMixer(() => undefined);
    const source: any = { id: 'a', kind: 'camera', muted: false, volume: .8, monitoring: 'monitor-and-output', syncOffsetMs: 0 };
    const video = document.createElement('video');
    // A permanently pending offline play() must not block Web Audio startup.
    video.play = () => new Promise(() => undefined);
    const detach = mixer.attach('a', video);
    mixer.configure([source]); mixer.bindStream('a', { getAudioTracks: () => [{}] } as MediaStream);
    const enabled = await Promise.race([mixer.enable(), new Promise((resolve) => setTimeout(() => resolve(false), 600))]);
    const normal = gains[1].value;
    mixer.configure([{ ...source, muted: true }]); const muted = gains[1].value;
    mixer.configure([{ ...source, monitoring: 'off' }]); const unmonitored = gains[1].value;
    mixer.configure([{ ...source, volume: 1.3 }]); const boosted = gains[1].value;
    mixer.configureTracks('a', [{ index: 0, gain: .4, muted: false }]);
    mixer.bindTrack('a', 0, { getAudioTracks: () => [{}] } as MediaStream);
    const videoWithSeparateAudio = gains[1].value;
    mixer.configure([{ ...source, muted: true }]); const separateMuted = gains[2].value;
    mixer.configure([{ ...source, monitoring: 'off' }]); const separateUnmonitored = gains[2].value;
    mixer.configure([source]);
    await new Promise((resolve) => setTimeout(resolve, 350));
    const buffersReused = analysers.every((node) => node.calls > 1 && node.buffers.size === 1);
    mixer.unbindTrack('a', 0); const videoRestored = gains[1].value;
    detach(); const calls = analysers.reduce((sum, node) => sum + node.calls, 0);
    await new Promise((resolve) => setTimeout(resolve, 250));
    const idleStopped = calls === analysers.reduce((sum, node) => sum + node.calls, 0);
    mixer.destroy();
    return { enabled, normal, muted, unmonitored, boosted, videoWithSeparateAudio, separateMuted, separateUnmonitored, buffersReused, videoRestored, idleStopped };
  });
  expect(result).toEqual({ enabled: true, normal: .8, muted: 0, unmonitored: 0, boosted: 1.3,
    videoWithSeparateAudio: 0, separateMuted: 0, separateUnmonitored: 0, buffersReused: true, videoRestored: .8, idleStopped: true });
});

test('prefers a confirmed video-only probe over gateway compatibility audio', async ({ page }) => {
  await page.route('**/api/**', (route) => route.fulfill({ json: {} }));
  await page.goto('/');
  const state = await page.evaluate(async () => {
    const { sourceAudioTrackState } = await import('/src/monitorView.ts');
    return sourceAudioTrackState({ kind: 'camera', streamBound: true, liveAudioTracks: 1, audioCodec: 'opus',
      probeState: 'ready', probeHasAudioTrack: false });
  });
  expect(state).toBe('none');
});
