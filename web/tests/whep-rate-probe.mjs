#!/usr/bin/env node
/**
 * Measures what MediaMTX actually delivers over WebRTC/WHEP to a browser, per
 * path and in aggregate.
 *
 * This separates "MediaMTX throttles the WebRTC output" from "the browser
 * cannot receive/decode that many streams": it speaks WHEP straight to
 * MediaMTX, so the application, its authorization and its plan activation stay
 * out of the picture, and it reports framesReceived (transport), framesDecoded
 * (decoder) and presented frames (compositor) side by side.
 *
 * Usage: node tests/whep-rate-probe.mjs <webrtc-base> <path[,path...]> [seconds]
 *   node tests/whep-rate-probe.mjs http://127.0.0.1:8889 rate-1,rate-2 30
 */
import { chromium } from '@playwright/test';

const base = process.argv[2] ?? 'http://127.0.0.1:8889';
const paths = (process.argv[3] ?? '').split(',').map((value) => value.trim()).filter(Boolean);
const seconds = Number(process.argv[4] ?? 30);
if (!paths.length || !Number.isFinite(seconds) || seconds <= 0) {
  console.error('usage: node tests/whep-rate-probe.mjs <webrtc-base> <path[,path...]> [seconds]');
  process.exit(2);
}

// WHEP_PROBE_CHANNEL=chrome uses the installed Google Chrome (a Windows
// browser reaching a WSL backend goes over ICE/TCP); leaving it unset uses
// Playwright's bundled Chromium, which in WSL reaches the ICE/UDP listener.
const channel = process.env.WHEP_PROBE_CHANNEL;
const browser = await chromium.launch({
  ...(channel ? { channel } : {}),
  args: ['--autoplay-policy=no-user-gesture-required'],
});
const page = await browser.newPage();
page.on('pageerror', (error) => console.error('[pageerror]', error.message.slice(0, 200)));

const result = await page.evaluate(async (options) => {
  const wait = (millis) => new Promise((resolve) => setTimeout(resolve, millis));
  const sessions = [];
  for (const name of options.paths) {
    const pc = new RTCPeerConnection({ iceServers: [] });
    pc.addTransceiver('video', { direction: 'recvonly' });
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') { resolve(); return; }
      pc.addEventListener('icegatheringstatechange', () => {
        if (pc.iceGatheringState === 'complete') resolve();
      });
      setTimeout(resolve, 3000);
    });
    const response = await fetch(options.base + '/' + name + '/whep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp' },
      body: pc.localDescription.sdp,
    });
    if (!response.ok) { sessions.push({ name, error: 'WHEP HTTP ' + response.status }); continue; }
    await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() });
    const stream = new MediaStream();
    pc.getReceivers().forEach((receiver) => { if (receiver.track) stream.addTrack(receiver.track); });
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    video.style.width = '320px';
    document.body.append(video);
    video.play().catch(() => undefined);
    sessions.push({ name, pc, video });
  }

  const sample = async () => {
    const rows = [];
    for (const session of sessions) {
      if (!session.pc) { rows.push({ name: session.name, error: session.error }); continue; }
      const report = await session.pc.getStats();
      const row = { name: session.name };
      report.forEach((item) => {
        if (item.type !== 'inbound-rtp' || item.kind !== 'video') return;
        row.framesReceived = Number(item.framesReceived ?? 0);
        row.framesDecoded = Number(item.framesDecoded ?? 0);
        row.framesDropped = Number(item.framesDropped ?? 0);
        row.bytesReceived = Number(item.bytesReceived ?? 0);
        row.packetsLost = Number(item.packetsLost ?? 0);
        row.nackCount = Number(item.nackCount ?? 0);
        row.freezeCount = Number(item.freezeCount ?? 0);
        row.pliCount = Number(item.pliCount ?? 0);
        row.keyFramesDecoded = Number(item.keyFramesDecoded ?? 0);
      });
      const quality = session.video && session.video.getVideoPlaybackQuality
        ? session.video.getVideoPlaybackQuality() : null;
      row.presentedFrames = quality ? quality.totalVideoFrames : null;
      row.elementDroppedFrames = quality ? quality.droppedVideoFrames : null;
      row.width = session.video ? session.video.videoWidth : 0;
      rows.push(row);
    }
    return rows;
  };

  // A rate measured from a late first frame is meaningless: wait for every
  // session to produce at least one frame before the clock starts.
  const readyDeadline = performance.now() + 25000;
  let first = await sample();
  while (performance.now() < readyDeadline
    && first.some((row) => !row.error && (row.framesReceived ?? 0) === 0)) {
    await wait(500);
    first = await sample();
  }
  await wait(2000);
  const start = await sample();
  const startedAt = performance.now();
  await wait(options.seconds * 1000);
  const end = await sample();
  const elapsed = (performance.now() - startedAt) / 1000;
  const rows = end.map((row, index) => {
    const before = start[index] ?? {};
    const rate = (key) => before[key] === undefined || row[key] === undefined
      ? null : Number((((row[key] - before[key]) / elapsed)).toFixed(2));
    return {
      name: row.name,
      error: row.error ?? null,
      width: row.width ?? 0,
      receivedFps: rate('framesReceived'),
      decodedFps: rate('framesDecoded'),
      presentedFps: rate('presentedFrames'),
      kbitPerSecond: before.bytesReceived === undefined
        ? null : Math.round(((row.bytesReceived - before.bytesReceived) * 8) / elapsed / 1000),
      decodedTotal: row.framesDecoded ?? null,
      droppedFrames: row.elementDroppedFrames ?? null,
      packetsLost: row.packetsLost ?? null,
      nackCount: row.nackCount ?? null,
      pliCount: row.pliCount ?? null,
      keyFramesDecoded: row.keyFramesDecoded ?? null,
      freezeCount: row.freezeCount ?? null,
    };
  });
  sessions.forEach((session) => { if (session.pc) session.pc.close(); });
  const totalDecodedFps = Number(rows.reduce((sum, row) => sum + (row.decodedFps ?? 0), 0).toFixed(2));
  return {
    pathCount: options.paths.length,
    elapsedSeconds: Number(elapsed.toFixed(1)),
    totalDecodedFps,
    rows,
  };
}, { base, paths, seconds });

console.log(JSON.stringify(result, null, 1));
await browser.close();
