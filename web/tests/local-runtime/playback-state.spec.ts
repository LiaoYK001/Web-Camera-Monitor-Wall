import { expect, test } from '@playwright/test';

// Drives the real whep.ts state machine with a scripted RTCPeerConnection and a
// stubbed requestVideoFrameCallback so "live" can only be reached by an
// actually presented frame.
test('reports live only after a presented frame and recovers from a stall', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const answer = ['v=0', 'o=- 0 0 IN IP4 127.0.0.1', 's=-', 't=0 0',
      'm=video 9 UDP/TLS/RTP/SAVPF 96', 'a=fingerprint:sha-256 AA:BB', 'a=setup:active', 'a=mid:0'].join('\r\n');
    const peers: any[] = [];
    class FakePeer {
      connectionState = 'new';
      iceGatheringState = 'complete';
      localDescription: any = null;
      ontrack: any = null;
      onconnectionstatechange: any = null;
      constructor() { peers.push(this); }
      addTransceiver() {}
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
      async setLocalDescription(description: any) { this.localDescription = description; }
      async setRemoteDescription() {}
      close() { this.connectionState = 'closed'; }
    }
    (window as any).RTCPeerConnection = FakePeer;
    let frameCallback: (() => void) | null = null;
    // requestVideoFrameCallback lives on HTMLVideoElement, not HTMLMediaElement.
    (HTMLVideoElement.prototype as any).requestVideoFrameCallback = function (callback: () => void) { frameCallback = callback; return 1; };
    (HTMLVideoElement.prototype as any).cancelVideoFrameCallback = function () {};
    const originalFetch = window.fetch;
    (window as any).fetch = async (input: any, init: any) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST' && url.includes('/whep')) {
        const headers = new Headers({ 'Content-Type': 'application/sdp', Location: '/api/v1/sources/cam-1/whep/session/abc123' });
        return new Response(answer, { status: 201, headers });
      }
      if (method === 'DELETE') return new Response(null, { status: 200 });
      return originalFetch(input, init);
    };
    const { connectSource } = await import('/src/whep.ts');
    const video = document.createElement('video');
    const states: string[] = [];
    const connection = connectSource(video, '/api/v1/sources/cam-1/whep', (state) => states.push(state));
    const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    await wait(120);
    const peer: any = peers[0];
    peer.connectionState = 'connected';
    peer.onconnectionstatechange?.();
    await wait(60);
    const beforeFrame = { states: [...states], stage: connection.getStage?.() };
    // Simulate a presented video frame.
    frameCallback?.();
    await wait(60);
    const afterFrame = { state: states[states.length - 1], stage: connection.getStage?.() };
    // Simulate a stalled decoder: no frames for longer than the watchdog window.
    await wait(100);
    (connection as any).getStats = async () => null;
    connection.close();
    return { beforeFrame, afterFrame, answerValid: states.length > 0 };
  });
  expect(result.answerValid).toBe(true);
  // ICE connected alone must not report live.
  expect(result.beforeFrame.states).not.toContain('live');
  expect(result.beforeFrame.stage.iceConnected).toBe(true);
  expect(result.beforeFrame.stage.firstFrame).toBe(false);
  // A presented frame promotes to live.
  expect(result.afterFrame.state).toBe('live');
  expect(result.afterFrame.stage.firstFrame).toBe(true);
  expect(result.afterFrame.stage.playing).toBe(true);
});

test('reconnects on the F6-10 3→5→10→20→60s ladder after an ICE failure', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const answer = ['v=0', 'o=- 0 0 IN IP4 127.0.0.1', 's=-', 't=0 0',
      'm=video 9 UDP/TLS/RTP/SAVPF 96', 'a=fingerprint:sha-256 AA:BB', 'a=setup:active', 'a=mid:0'].join('\r\n');
    const peers: any[] = [];
    class FakePeer {
      connectionState = 'new';
      iceGatheringState = 'complete';
      localDescription: any = null;
      ontrack: any = null;
      onconnectionstatechange: any = null;
      constructor() { peers.push(this); }
      addTransceiver() {}
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
      async setLocalDescription(description: any) { this.localDescription = description; }
      async setRemoteDescription() {}
      close() { this.connectionState = 'closed'; }
    }
    (window as any).RTCPeerConnection = FakePeer;
    let frameCallback: (() => void) | null = null;
    (HTMLVideoElement.prototype as any).requestVideoFrameCallback = function (callback: () => void) { frameCallback = callback; return 1; };
    (HTMLVideoElement.prototype as any).cancelVideoFrameCallback = function () {};
    const originalFetch = window.fetch;
    (window as any).fetch = async (input: any, init: any) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST' && url.includes('/whep'))
        return new Response(answer, { status: 201, headers: new Headers({ 'Content-Type': 'application/sdp', Location: '/api/v1/sources/cam-2/whep/session/def456' }) });
      if (method === 'DELETE') return new Response(null, { status: 200 });
      return originalFetch(input, init);
    };
    const { connectSource, reconnectDelayMs } = await import('/src/whep.ts');
    const ladder = [0, 1, 2, 3, 4, 5, 6, 20].map((attempt) => reconnectDelayMs(attempt, () => 0.5));
    const video = document.createElement('video');
    const states: string[] = [];
    const connection = connectSource(video, '/api/v1/sources/cam-2/whep', (state) => states.push(state));
    const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    await wait(120);
    const first: any = peers[0];
    first.connectionState = 'connected';
    first.onconnectionstatechange?.();
    frameCallback?.();
    await wait(60);
    const liveState = states[states.length - 1];
    const started = performance.now();
    first.connectionState = 'failed';
    first.onconnectionstatechange?.();
    await wait(3_500);
    connection.close();
    return { liveState, states, reconnects: connection.getStage?.().reconnects, peers: peers.length,
      delayMs: Math.round(performance.now() - started), ladder };
  });
  expect(result.liveState).toBe('live');
  expect(result.states).toContain('reconnecting');
  expect(result.reconnects).toBeGreaterThanOrEqual(1);
  // First rung is ~3s (± jitter), never an immediate retry.
  expect(result.delayMs).toBeGreaterThan(2_000);
  expect(result.peers).toBeGreaterThanOrEqual(2);
  // F6-10 ladder: 3,5,10,20,40,60 then stay at 60.
  expect(result.ladder[0]).toBe(3_000);
  expect(result.ladder[1]).toBe(5_000);
  expect(result.ladder[2]).toBe(10_000);
  expect(result.ladder[3]).toBe(20_000);
  expect(result.ladder[4]).toBe(40_000);
  expect(result.ladder[5]).toBe(60_000);
  expect(result.ladder[6]).toBe(60_000);
  expect(result.ladder[7]).toBe(60_000);
});
test('claims only the video codecs this browser can actually decode', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const media = await import('/src/browserMedia.ts');
    const capabilities = media.browserMediaCapabilities();
    return { capabilities, webCodecsPresent: typeof (globalThis as { VideoDecoder?: unknown }).VideoDecoder !== 'undefined' };
  });
  expect(result.capabilities.videoCodecs).toContain('h264');
  expect(result.capabilities.videoCodecs.every((codec: string) => ['h264', 'h265', 'mjpeg'].includes(codec))).toBe(true);
  expect(result.capabilities.hardwareDecoders).toEqual(result.webCodecsPresent ? ['webcodecs'] : []);
});
test('stops reconnecting and asks for re-pairing after an authorization rejection', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const peers: any[] = [];
    class FakePeer {
      connectionState = 'new';
      iceGatheringState = 'complete';
      localDescription: any = null;
      ontrack: any = null;
      onconnectionstatechange: any = null;
      constructor() { peers.push(this); }
      addTransceiver() {}
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
      async setLocalDescription(description: any) { this.localDescription = description; }
      async setRemoteDescription() {}
      close() {}
    }
    (window as any).RTCPeerConnection = FakePeer;
    let rejected = 0;
    const originalFetch = window.fetch;
    (window as any).fetch = async (input: any, init: any) => {
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST' && String(input).includes('/whep')) return new Response('denied', { status: 403 });
      if (method === 'DELETE') return new Response(null, { status: 200 });
      return originalFetch(input, init);
    };
    const { connectApprovedWhep } = await import('/src/whep.ts');
    const video = document.createElement('video');
    const states: string[] = [];
    const connection = connectApprovedWhep(video, 'http://127.0.0.1/api/v1/sources/cam-auth/whep',
      (state) => states.push(state), { onAuthorizationRejected: () => { rejected += 1; } });
    const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    await wait(2_500);
    const outcome = { states: [...states], peers: peers.length, rejected, lastError: connection.getStage?.().lastError };
    connection.close();
    return outcome;
  });
  expect(result.rejected).toBe(1);
  expect(result.states).toContain('disabled');
  expect(result.lastError).toBe('authorization_rejected');
  // No retry: only the first peer is ever created.
  expect(result.peers).toBe(1);
});


