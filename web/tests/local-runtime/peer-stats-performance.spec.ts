import { expect, test } from '@playwright/test';

test('WHEP telemetry and the watchdog share slow statistics and discard closed-peer results', async ({ page }) => {
  await page.goto('/tests/harness/usability.html');
  const result = await page.evaluate(async () => {
    const { connectSource } = await import('/src/whep.ts');
    const { sampleConnectionTelemetry } = await import('/src/mediaTelemetry.ts');
    const original = { peer: window.RTCPeerConnection, fetch: window.fetch, interval: window.setInterval, clear: window.clearInterval };
    let tick: (() => void) | undefined, frame: (() => void) | undefined, now = 1000, calls = 0;
    const reads: Array<{ resolve: (report: any) => void; reject: (reason: Error) => void }> = [];
    Object.defineProperty(performance, 'now', { configurable: true, value: () => now });
    window.setInterval = ((callback: () => void, ms: number) => { if (ms === 1000) tick = callback; return 999; }) as typeof window.setInterval;
    window.clearInterval = (() => undefined) as typeof window.clearInterval;
    class Peer {
      connectionState = 'connected'; iceGatheringState = 'complete'; localDescription: any;
      addTransceiver() {} close() { this.connectionState = 'closed'; }
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
      async setLocalDescription(value: any) { this.localDescription = value; }
      async setRemoteDescription() {} getReceivers() { return []; }
      getStats() { calls++; return new Promise((resolve, reject) => reads.push({ resolve, reject })); }
    }
    window.RTCPeerConnection = Peer as unknown as typeof RTCPeerConnection;
    window.fetch = async (_input, init) => init?.method === 'DELETE' ? new Response(null, { status: 204 }) : new Response(
      'v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=fingerprint:sha-256 AA:BB\r\na=setup:active\r\na=mid:0',
      { status: 201, headers: { 'Content-Type': 'application/sdp', Location: '/api/v1/sources/stat-fixture/whep/session/test' } });
    const video = document.createElement('video'); Object.defineProperty(video, 'paused', { value: false }); video.play = async () => undefined;
    video.requestVideoFrameCallback = (callback) => { frame = callback as unknown as () => void; return 1; }; video.cancelVideoFrameCallback = () => undefined;
    const connection = connectSource(video, '/api/v1/sources/stat-fixture/whep', () => undefined);
    const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
    const report = (timestamp: number, frames: number, bytes: number) => new Map([['video', { type: 'inbound-rtp', kind: 'video', timestamp, framesDecoded: frames, bytesReceived: bytes, packetsReceived: 100, packetsLost: 0, jitter: 0 }]]);
    try {
      await new Promise((resolve) => setTimeout(resolve, 40)); frame?.(); now += 3000; frame?.();
      const consumers = Array.from({ length: 12 }, () => connection.getStats!()); tick?.(); await flush();
      const nativeReads = calls; reads[0].resolve(report(1000, 25, 1000));
      const resolved = await Promise.all(consumers);
      const shared = resolved.every((value) => value === resolved[0]);
      await connection.getStats!(); const immediateReads = calls;
      now += 201;
      const telemetry = sampleConnectionTelemetry(connection, { at: 1000, frames: 25, bytes: 1000 });
      await flush(); reads[1].resolve(report(2000, 40, 3048)); const sampled = await telemetry;
      now += 201; const repeated = sampleConnectionTelemetry(connection, sampled.previous);
      await flush(); reads[2].resolve(report(2000, 40, 3048)); const same = await repeated;
      now += 201; const failing = connection.getStats!().catch(() => null); await flush(); reads[3].reject(new Error('synthetic stats failure')); await failing;
      const retry = connection.getStats!(); await flush(); const retryReads = calls; reads[4].resolve(report(3000, 50, 4096)); await retry;
      now += 201; const pending = connection.getStats!(); await flush(); connection.close(); reads[5].resolve(report(4000, 60, 5000));
      const late = await pending; const closed = await connection.getStats!();
      return { nativeReads, immediateReads, shared, fps: sampled.telemetry.fps, bytesPerSecond: sampled.telemetry.bytesPerSecond, repeatedFps: same.telemetry.fps, retryReads, late, closed };
    } finally {
      connection.close(); window.RTCPeerConnection = original.peer; window.fetch = original.fetch;
      window.setInterval = original.interval; window.clearInterval = original.clear; delete (performance as any).now;
    }
  });
  console.log('PEER_STATS_RECEIPT', JSON.stringify(result));
  expect(result.nativeReads).toBe(1); expect(result.immediateReads).toBe(1); expect(result.shared).toBe(true);
  expect(result.fps).toBe(15); expect(result.bytesPerSecond).toBe(2048); expect(result.repeatedFps).toBeNull();
  expect(result.retryReads).toBe(5); expect(result.late).toBeNull(); expect(result.closed).toBeNull();
});

test('audio liveness bounds slow statistics and rejects the previous peer after reconnect', async ({ page }) => {
  await page.goto('/tests/harness/usability.html');
  const result = await page.evaluate(async () => {
    const { connectAudioTrack } = await import('/src/audioTrackChannel.ts');
    const original = { peer: window.RTCPeerConnection, fetch: window.fetch, interval: window.setInterval, clear: window.clearInterval, timeout: window.setTimeout };
    let tick: (() => void) | undefined, retry: (() => void) | undefined, calls = 0, now = 1000;
    const peers: any[] = [], reads: Array<(report: any) => void> = [], states: string[] = [];
    Object.defineProperty(Date, 'now', { configurable: true, value: () => now });
    window.setInterval = ((callback: () => void, ms: number) => { if (ms === 1000) tick = callback; return 999; }) as typeof window.setInterval;
    window.clearInterval = (() => undefined) as typeof window.clearInterval;
    window.setTimeout = ((callback: () => void, ms: number) => {
      if (ms >= 2400 && ms <= 3600) { retry = callback; return 998; }
      return original.timeout.call(window, callback, ms);
    }) as typeof window.setTimeout;
    class Peer {
      connectionState = 'connected'; iceGatheringState = 'complete'; localDescription: any; onconnectionstatechange?: () => void;
      constructor() { peers.push(this); }
      addTransceiver() {} close() { this.connectionState = 'closed'; }
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
      async setLocalDescription(value: any) { this.localDescription = value; } async setRemoteDescription() {}
      getStats() { calls++; return new Promise((resolve) => reads.push(resolve)); }
    }
    window.RTCPeerConnection = Peer as unknown as typeof RTCPeerConnection;
    window.fetch = async (_input, init) => init?.method === 'DELETE' ? new Response(null, { status: 204 }) : new Response('v=0\r\n',
      { status: 201, headers: { Location: '/api/v1/sources/audio-fixture/audio-tracks/0/whep/session/test' } });
    const connection = connectAudioTrack({ endpoint: '/api/v1/sources/audio-fixture/audio-tracks/0/whep' } as never, (state) => states.push(state));
    const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
    try {
      await new Promise((resolve) => original.timeout.call(window, resolve, 40));
      for (let i = 0; i < 10; i++) { tick?.(); await flush(); now += 1000; }
      const slowReads = calls;
      peers[0].connectionState = 'failed'; peers[0].onconnectionstatechange?.(); retry?.();
      await new Promise((resolve) => original.timeout.call(window, resolve, 40)); tick?.(); await flush();
      const newPeerReads = calls; now += 10_000;
      reads[0](new Map([['audio', { type: 'inbound-rtp', kind: 'audio', packetsReceived: 0 }]])); await flush();
      const stateAfterOldResponse = connection.getState();
      reads[1](new Map([['audio', { type: 'inbound-rtp', kind: 'audio', packetsReceived: 1 }]])); await flush();
      const peersAfterOldResponse = peers.length;
      connection.close(); return { slowReads, newPeerReads, stateAfterOldResponse, peersAfterOldResponse, states };
    } finally {
      connection.close(); window.RTCPeerConnection = original.peer; window.fetch = original.fetch;
      window.setInterval = original.interval; window.clearInterval = original.clear; window.setTimeout = original.timeout; delete (Date as any).now;
    }
  });
  expect(result.slowReads).toBe(1); expect(result.newPeerReads).toBe(2);
  expect(result.stateAfterOldResponse).toBe('connected'); expect(result.peersAfterOldResponse).toBe(2);
  expect(result.states.filter((value) => value === 'reconnecting')).toHaveLength(2); // Scheduling and opening the new channel.
});
