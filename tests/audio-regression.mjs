#!/usr/bin/env node
/**
 * Reproducible Composite audio regression (feedback-5, batch C/D).
 *
 * It publishes one synthetic source (H.264 video plus two tones: a:0 = 440 Hz,
 * a:1 = 880 Hz), drives the real gateway audio-mix path through MediaMTX's
 * on-demand API, records the resulting mix and measures it, so per-track gain,
 * mute and signed sync offsets are verified against real media instead of a
 * one-off manual session.
 *
 * It owns its own MediaMTX on the product ports (8554/9997) and refuses to run
 * while another instance is listening, so it never disturbs a development
 * session by accident.  Nothing outside this run's processes or paths is
 * cleaned up.
 *
 * Usage: node tests/audio-regression.mjs
 * Env:   WEBOBS_MEDIAMTX_BIN  path to the mediamtx binary (defaults to the
 *                             native dev cache), WEBOBS_AUDIO_KEEP=1 to keep
 *                             the evidence directory.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const RTSP_PORT = 8554;
const API_PORT = 9997;
const evidence = path.join(root, 'tests/artifacts/audio-regression');
const failures = [];
const children = new Set();

function log(message) {
  console.log(`[audio] ${message}`);
}

function fail(message) {
  failures.push(message);
  console.error(`[audio] FAIL: ${message}`);
}

function expect(condition, message) {
  if (condition) log(`ok   ${message}`);
  else fail(message);
}

function mediamtxBinary() {
  if (process.env.WEBOBS_MEDIAMTX_BIN) return process.env.WEBOBS_MEDIAMTX_BIN;
  const cache = path.join(os.homedir(), '.cache/webobs-dev');
  if (!existsSync(cache)) return '';
  for (const entry of readdirSync(cache)) {
    const candidate = path.join(cache, entry, 'bin/mediamtx');
    if (existsSync(candidate)) return candidate;
  }
  return '';
}

function portFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
  });
}

function track(child) {
  children.add(child);
  return child;
}

function shutdown() {
  for (const child of children) {
    try { child.kill('SIGTERM'); } catch { /* already gone */ }
  }
}

async function waitForHttp(url, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (response.ok) return true;
    } catch { /* not up yet */ }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

/** Adds an on-demand audio-mix path and returns the transcoder's stderr once it exits. */
function addMixPath(spec, sourceUrl) {
  const token = Math.random().toString(16).slice(2).padEnd(32, '0').slice(0, 32);
  const name = `mix-${token}`;
  const command = `${path.join(root, 'gateway/transcode-on-demand.sh')} ${sourceUrl} ${name} audio-mix ${spec}`;
  const body = JSON.stringify({
    source: 'publisher',
    runOnDemand: command,
    runOnDemandRestart: false,
    runOnDemandStartTimeout: '10s',
    runOnDemandCloseAfter: '2s',
  });
  const result = spawnSync('curl', ['-s', '-o', '/dev/null', '-w', '%{http_code}', '-X', 'POST',
    '-H', 'Content-Type: application/json', '-d', body,
    `http://127.0.0.1:${API_PORT}/v3/config/paths/add/${name}`], { encoding: 'utf8' });
  return { name, status: result.stdout?.trim() };
}

function removePath(name) {
  spawnSync('curl', ['-s', '-o', '/dev/null', '-X', 'DELETE',
    `http://127.0.0.1:${API_PORT}/v3/config/paths/delete/${name}`]);
}

/** Records `seconds` of one path to a file; returns the path. */
function record(target, seconds, file, extra = []) {
  const result = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-rtsp_transport', 'tcp',
    '-i', `rtsp://127.0.0.1:${RTSP_PORT}/${target}`, '-t', String(seconds), ...extra, file],
    { encoding: 'utf8', timeout: (seconds + 20) * 1000 });
  return { file, error: result.status === 0 ? '' : (result.stderr || '').slice(0, 400) };
}

/** Goertzel energy of one frequency in a window of 8 kHz mono float samples. */
function toneEnergy(samples, sampleRate, frequency) {
  const omega = (2 * Math.PI * frequency) / sampleRate;
  const coefficient = 2 * Math.cos(omega);
  let s1 = 0;
  let s2 = 0;
  for (const sample of samples) {
    const s0 = sample + coefficient * s1 - s2;
    s2 = s1;
    s1 = s0;
  }
  return Math.sqrt(s1 * s1 + s2 * s2 - coefficient * s1 * s2) / samples.length;
}

/** Reads a WAV file written by ffmpeg (pcm_f32le or pcm_s16le) into mono floats. */
function readWav(file) {
  const buffer = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=sample_rate,channels',
    '-of', 'json', file], { encoding: 'utf8' });
  const probe = JSON.parse(buffer.stdout || '{}');
  const stream = probe.streams?.[0] ?? {};
  const sampleRate = Number(stream.sample_rate) || 8000;
  const channels = Number(stream.channels) || 1;
  const raw = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1',
    '-ar', String(sampleRate), '-'], { encoding: 'buffer', maxBuffer: 1 << 28 });
  const floats = new Float32Array(raw.stdout.buffer, raw.stdout.byteOffset, Math.floor(raw.stdout.length / 4));
  return { sampleRate, channels, samples: floats };
}

function windowEnergies(samples, sampleRate, windowSeconds = 1) {
  const size = Math.round(sampleRate * windowSeconds);
  const windows = [];
  for (let offset = 0; offset + size <= samples.length; offset += size) {
    const slice = samples.subarray(offset, offset + size);
    windows.push({
      second: offset / sampleRate,
      e440: toneEnergy(slice, sampleRate, 440),
      e880: toneEnergy(slice, sampleRate, 880),
    });
  }
  return windows;
}

/** First video packet PTS of a recorded file, in milliseconds. */
function firstVideoPtsMs(file) {
  const result = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v', '-show_entries',
    'packet=pts_time', '-of', 'csv=p=0', file], { encoding: 'utf8' });
  const values = result.stdout.split('\n').map((line) => Number(line.split(',')[0]))
    .filter((value) => Number.isFinite(value));
  return values.length ? Math.min(...values) * 1000 : null;
}

async function main() {
  const mediamtx = mediamtxBinary();
  if (!mediamtx) throw new Error('mediamtx binary not found; set WEBOBS_MEDIAMTX_BIN');
  if (!(await portFree(RTSP_PORT)) || !(await portFree(API_PORT))) {
    throw new Error(`ports ${RTSP_PORT}/${API_PORT} are busy; stop the development session first`);
  }
  rmSync(evidence, { recursive: true, force: true });
  mkdirSync(evidence, { recursive: true });
  const config = path.join(evidence, 'mediamtx.regression.yml');
  writeFileSync(config, [
    'logLevel: warn',
    'rtsp: yes',
    `rtspAddress: :${RTSP_PORT}`,
    'rtspTransports: [tcp]',
    'api: yes',
    `apiAddress: 127.0.0.1:${API_PORT}`,
    'webrtc: no',
    'hls: no',
    'paths:',
    '  all_others:',
    '',
  ].join('\n'));

  const server = track(spawn(mediamtx, [config], { stdio: ['ignore', 'pipe', 'pipe'] }));
  server.stderr.on('data', () => undefined);
  if (!(await waitForHttp(`http://127.0.0.1:${API_PORT}/v3/config/global/get`))) {
    throw new Error('mediamtx did not become ready');
  }
  log('mediamtx ready');

  const publisher = track(spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-re',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25',
    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
    '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000',
    '-map', '0:v', '-map', '1:a', '-map', '2:a',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '25', '-bf', '0', '-pix_fmt', 'yuv420p',
    '-c:a', 'libopus', '-b:a', '96k', '-ar', '48000', '-ac', '1',
    '-t', '90', '-rtsp_transport', 'tcp', '-f', 'rtsp', `rtsp://127.0.0.1:${RTSP_PORT}/synth`],
    { stdio: ['ignore', 'ignore', 'pipe'] }));
  publisher.stderr.on('data', () => undefined);
  await new Promise((resolve) => setTimeout(resolve, 4000));
  log('synthetic dual-tone publisher running');

  const captured = [];

  // Case 1: the first (440 Hz) track is muted; the second must stay audible.
  {
    const { name, status } = addMixPath('0:1.0:1,1:1.0:0', `rtsp://127.0.0.1:${RTSP_PORT}/synth`);
    expect(status === '200', `mix route created for the muted-first-track case (HTTP ${status})`);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const file = path.join(evidence, 'case1.wav');
    record(name, 4, file, ['-vn', '-ac', '1', '-ar', '8000']);
    const { samples, sampleRate } = readWav(file);
    const windows = windowEnergies(samples, sampleRate);
    const middle = windows.slice(1, -1);
    const e440 = Math.max(...middle.map((w) => w.e440), 0);
    const e880 = Math.max(...middle.map((w) => w.e880), 0);
    captured.push({ case: 'muted-first-track', e440, e880 });
    expect(e880 > 1e6, `muting the first track keeps the second audible (e880=${e880.toFixed(0)})`);
    expect(e880 > e440 * 20, `muting the first track really removes 440 Hz (e440=${e440.toFixed(0)})`);
    removePath(name);
  }

  // Case 2: gain is applied exactly once (0.25 on 440 Hz => about -12 dB).
  {
    const { name } = addMixPath('0:0.25:0,1:1.0:0', `rtsp://127.0.0.1:${RTSP_PORT}/synth`);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const file = path.join(evidence, 'case2.wav');
    record(name, 4, file, ['-vn', '-ac', '1', '-ar', '8000']);
    const { samples, sampleRate } = readWav(file);
    const middle = windowEnergies(samples, sampleRate).slice(1, -1);
    const ratio = 20 * Math.log10(
      (middle.reduce((sum, w) => sum + w.e880, 0) / Math.max(1, middle.length)) /
      Math.max(1e-9, middle.reduce((sum, w) => sum + w.e440, 0) / Math.max(1, middle.length)));
    captured.push({ case: 'gain-once', ratioDb: ratio });
    expect(Math.abs(ratio - 12.04) < 3, `0.25 gain on one track is about -12 dB (measured ${ratio.toFixed(2)} dB)`);
    removePath(name);
  }

  // Case 3: a negative offset is normalised, and the video is shifted by the same
  // amount so every track keeps its offset relative to the video.
  {
    const { name } = addMixPath('0:1.0:0:-2000,1:1.0:0:0', `rtsp://127.0.0.1:${RTSP_PORT}/synth`);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const file = path.join(evidence, 'case3.mkv');
    record(name, 6, file, ['-c', 'copy']);
    const pts = firstVideoPtsMs(file);
    captured.push({ case: 'negative-offset', firstVideoPtsMs: pts });
    expect(pts !== null && pts > 1800 && pts < 2300,
      `a -2000ms track offset delays the video by 2000ms (first video pts ${pts?.toFixed(0)}ms)`);
    const wav = path.join(evidence, 'case3.wav');
    record(name, 6, wav, ['-vn', '-ac', '1', '-ar', '8000']);
    const { samples, sampleRate } = readWav(wav);
    const windows = windowEnergies(samples, sampleRate);
    const first = windows[0] ?? { e440: 0, e880: 0 };
    const later = windows[windows.length - 2] ?? { e440: 0, e880: 0 };
    captured.push({ case: 'negative-offset-tone', first, later });
    expect(first.e440 > first.e880 * 5,
      `the normalised track starts immediately (440 now, 880 later: ${first.e440.toFixed(0)} vs ${first.e880.toFixed(0)})`);
    expect(later.e880 > later.e440 * 0.2,
      `the untouched track joins after its 2s normalisation delay (later 880=${later.e880.toFixed(0)})`);
    removePath(name);
  }

  writeFileSync(path.join(evidence, 'result.json'), JSON.stringify({ captured, failures }, null, 2));
  log(`evidence: ${evidence}`);
}

main()
  .catch((error) => fail(`fatal: ${error.message}`))
  .finally(() => {
    shutdown();
    setTimeout(() => {
      if (process.env.WEBOBS_AUDIO_KEEP !== '1') rmSync(path.join(evidence, 'mediamtx.regression.yml'), { force: true });
      console.log(failures.length ? `[audio] ${failures.length} check(s) failed` : '[audio] all checks passed');
      process.exit(failures.length ? 1 : 0);
    }, 1500);
  });
