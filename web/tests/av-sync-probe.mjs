#!/usr/bin/env node
/**
 * Measures the audio/video offset a browser actually experiences on a mix route.
 *
 * A negative per-track offset makes the transcoder delay the video by B while
 * each track is delayed by B+d_i. That shift cannot be read from RTP timestamps
 * (a receiver re-bases each stream onto its own timeline), so it is measured
 * from the content: the source carries a full-frame white flash whose audio is a
 * 1 kHz burst at exactly the same instant, and this probe times both against one
 * performance.now() clock inside the page.
 *
 * Usage: node tests/av-sync-probe.mjs <mix-token-32hex> [seconds]
 * Needs MediaMTX on rtsp 8554 / webrtc 8889 with the mix route up.  Two fixture
 * prerequisites are easy to miss: the mix path must be registered through the
 * MediaMTX API first (the dev gateway does not create paths on demand), and a
 * standalone MediaMTX needs the ICE/TCP settings dev-native.py sets
 * (MTX_WEBRTCLOCALTCPADDRESS and friends) or a Windows browser's ICE never
 * connects and WHEP returns a session with no media.
 */
import { chromium } from '@playwright/test';

const token = process.argv[2];
const seconds = Number(process.argv[3] ?? 20);
if (!/^[a-f0-9]{32}$/.test(token ?? '')) {
  console.error('usage: node tests/av-sync-probe.mjs <32hex-token> [seconds]');
  process.exit(2);
}

const browser = await chromium.launch({ channel: 'chrome', args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await browser.newPage();
page.on('console', (message) => { if (message.type() === 'error') console.error('[console]', message.text().slice(0, 160)); });
page.on('pageerror', (error) => console.error('[pageerror]', error.message.slice(0, 200)));

const result = await page.evaluate(async (options) => {
  const pc = new RTCPeerConnection({ iceServers: [] });
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.addTransceiver('audio', { direction: 'recvonly' });
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise((resolve) => {
    if (pc.iceGatheringState === 'complete') { resolve(); return; }
    pc.addEventListener('icegatheringstatechange', () => {
      if (pc.iceGatheringState === 'complete') resolve();
    });
    setTimeout(resolve, 3000);
  });
  const response = await fetch("http://127.0.0.1:8889/mix-" + options.token + "/whep", {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: pc.localDescription.sdp,
  });
  if (!response.ok) return { error: "WHEP HTTP " + response.status };
  const answer = await response.text();
  await pc.setRemoteDescription({ type: 'answer', sdp: answer });
  const remote = new MediaStream();
  pc.getReceivers().forEach((receiver) => { if (receiver.track) remote.addTrack(receiver.track); });
  const video = document.createElement('video');
  video.srcObject = remote;
  video.muted = false;
  video.playsInline = true;
  video.style.width = '160px';
  document.body.append(video);
  // Do not await play(): it only resolves once playback actually starts, which
  // needs the first frame, and the detection loop below is what waits for that.
  video.play().catch(() => undefined);
  const audioContext = new AudioContext();
  if (audioContext.state === "suspended") audioContext.resume().catch(() => undefined);
  const audioStream = new MediaStream(remote.getAudioTracks());
  const source = audioContext.createMediaStreamSource(audioStream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const canvas = document.createElement('canvas');
  canvas.width = 32;
  canvas.height = 18;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  const samples = new Uint8Array(analyser.fftSize);
  const flashes = [];
  const pulses = [];
  let maxMean = 0;
  let maxRms = 0;
  let maxReadyState = 0;
  let lastFlash = -10000;
  let lastPulse = -10000;
  const startedAt = performance.now();
  const loop = () => {
    const now = performance.now();
    if (video.readyState > maxReadyState) maxReadyState = video.readyState;
    if (video.readyState >= 2) {
      context.drawImage(video, 0, 0, 32, 18);
      const pixels = context.getImageData(0, 0, 32, 18).data;
      let total = 0;
      for (let index = 0; index < pixels.length; index += 4) total += pixels[index];
      const mean = total / (pixels.length / 4);
      if (mean > maxMean) maxMean = mean;
      if (mean > 140 && now - lastFlash > 1500) { flashes.push(now); lastFlash = now; }
    }
    analyser.getByteTimeDomainData(samples);
    let energy = 0;
    for (const value of samples) { const delta = (value - 128) / 128; energy += delta * delta; }
    const rms = Math.sqrt(energy / samples.length);
    if (rms > maxRms) maxRms = rms;
    if (rms > 0.05 && now - lastPulse > 1500) { pulses.push(now); lastPulse = now; }
    if (now - startedAt < options.seconds * 1000) requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  await new Promise((resolve) => setTimeout(resolve, options.seconds * 1000 + 600));
  pc.close();
  const pairs = Math.min(flashes.length, pulses.length);
  const deltas = [];
  for (let index = 0; index < pairs; index += 1) deltas.push(flashes[index] - pulses[index]);
  deltas.sort((left, right) => left - right);
  const median = deltas.length ? deltas[Math.floor(deltas.length / 2)] : null;
  return {
    flashes: flashes.length,
    pulses: pulses.length,
    deltasMs: deltas.map((value) => Math.round(value)),
    maxMean: Math.round(maxMean),
    maxRms: Number(maxRms.toFixed(3)),
    maxReadyState,
    videoWidth: video.videoWidth,
    medianMs: median === null ? null : Math.round(median),
  };
}, { token, seconds });

console.log(JSON.stringify(result));
await browser.close();