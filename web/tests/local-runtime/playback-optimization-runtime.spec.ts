import { expect, test } from '@playwright/test';

test('the WHEP watchdog samples sustained congestion, bounds jitter buffering and honors opt-out', async ({ page }) => {
  await page.goto('/tests/harness/usability.html?area=devices');
  const result = await page.evaluate(async () => {
    const { connectSource } = await import('/src/whep.ts');
    const saved = { interval: window.setInterval, clear: window.clearInterval, peer: window.RTCPeerConnection, fetch: window.fetch };
    let tick: (() => void) | undefined, frame: (() => void) | undefined, now = 1000;
    let received = 0, lost = 0, jitter = .2;
    const receiver = { track: { kind: 'video' }, jitterBufferTarget: 0 };
    Object.defineProperty(performance, 'now', { configurable: true, value: () => now });
    window.setInterval = ((callback: () => void, ms: number) => { if (ms === 1000) tick = callback; return 999; }) as typeof window.setInterval;
    window.clearInterval = (() => undefined) as typeof window.clearInterval;
    class Peer {
      connectionState = 'connected'; iceGatheringState = 'complete'; localDescription: any;
      addTransceiver() {} close() {} async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
      async setLocalDescription(value: any) { this.localDescription = value; }
      async setRemoteDescription() {} getReceivers() { return [receiver]; }
      async getStats() { return new Map([['video', { type: 'inbound-rtp', kind: 'video', packetsReceived: received, packetsLost: lost, jitter, timestamp: now }]]); }
    }
    window.RTCPeerConnection = Peer as unknown as typeof RTCPeerConnection;
    window.fetch = async (_input, init) => init?.method === 'DELETE' ? new Response(null, { status: 204 }) : new Response(
      'v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=fingerprint:sha-256 AA:BB\r\na=setup:active\r\na=mid:0',
      { status: 201, headers: { 'Content-Type': 'application/sdp', Location: '/api/v1/sources/quality/whep/session/test' } });
    const run = async (enabled: boolean) => {
      const video = document.createElement('video'); Object.defineProperty(video, 'paused', { value: false });
      video.play = async () => undefined;
      video.requestVideoFrameCallback = (callback) => { frame = callback as unknown as () => void; return 1; };
      video.cancelVideoFrameCallback = () => undefined;
      const quality: boolean[] = [];
      const connection = connectSource(video, '/api/v1/sources/quality/whep', () => undefined, undefined, undefined,
        { optimization: { enabled }, onQuality: (weak) => quality.push(weak) });
      await new Promise((resolve) => setTimeout(resolve, 40)); frame?.();
      const sample = async (weak: boolean) => {
        now += 3000; received += 100; if (weak) lost += 20; jitter = weak ? .2 : .02;
        frame?.(); tick?.(); await new Promise((resolve) => setTimeout(resolve, 5));
      };
      await sample(true); await sample(true); await sample(true);
      const beforeThreshold = [...quality]; await sample(true); const target = receiver.jitterBufferTarget;
      for (let index = 0; index < 7; index++) await sample(true);
      for (let index = 0; index < 20; index++) await sample(false);
      connection.close(); return { beforeThreshold, quality, target };
    };
    try {
      const enabled = await run(true); receiver.jitterBufferTarget = 0;
      const disabled = await run(false); return { enabled, disabled };
    } finally {
      window.setInterval = saved.interval; window.clearInterval = saved.clear;
      window.RTCPeerConnection = saved.peer; window.fetch = saved.fetch; delete (performance as any).now;
    }
  });
  expect(result.enabled.beforeThreshold).toEqual([]);
  expect(result.enabled.quality).toEqual([true, true, false]); expect(result.enabled.target).toBe(600);
  expect(result.disabled.quality).toEqual([]); expect(result.disabled.target).toBe(0);
});
