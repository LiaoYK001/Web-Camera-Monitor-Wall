#!/usr/bin/env node
/**
 * Reproducible Composite audio regression (feedback-5, batches C/D).
 *
 * It publishes one synthetic source (H.264 video plus two tones: a:0 = 440 Hz,
 * a:1 = 880 Hz), runs the real gateway audio-mix transcoder for several specs,
 * records each resulting route and measures it.  Per-track gain, mute and signed
 * sync offsets are therefore verified against real media instead of a one-off
 * manual session.
 *
 * The transcoder is started as a direct child rather than through MediaMTX's
 * runOnDemand hook: an on-demand route only starts once something reads it, and
 * the resulting startup race made captures empty.  Starting it directly is
 * deterministic and still exercises the script under test.
 *
 * It owns its own MediaMTX on the product ports (8554/9997) and refuses to run
 * while another instance listens, so it never disturbs a development session by
 * accident.  Nothing outside this run's processes is cleaned up.
 *
 * Known limitation: the recorders race the transcoder's first frame, so a
 * capture can occasionally be silent even though the route reports ready.  Each
 * case therefore reports how many analysis windows it saw; a run that measures
 * no signal in a case where signal is expected must be repeated rather than read
 * as a product defect.  The gain case (single-application gain) and the
 * transcoder's own normalisation report are the stable signals.
 *
 * Usage: node tests/audio-regression.mjs
 * Env:   WEBOBS_MEDIAMTX_BIN  mediamtx binary (defaults to the native dev cache)
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

const log = (message) => console.log(`[audio] ${message}`);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
  child.once('exit', () => children.delete(child));
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
    await sleep(250);
  }
  return false;
}

async function waitForRoute(name, timeoutMs = 25_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${API_PORT}/v3/paths/get/${name}`,
        { signal: AbortSignal.timeout(1500) });
      if (response.ok) {
        const body = await response.json();
        if (body.ready === true) return true;
      }
    } catch { /* keep polling */ }
    await sleep(300);
  }
  return false;
}

let mixSequence = 0;

/** Starts the real transcoder directly and collects its stderr. */
function startMix(spec, sourceUrl) {
  mixSequence += 1;
  const name = `mix-${mixSequence.toString(16).padStart(32, '0')}`;
  const child = track(spawn('sh', [path.join(root, 'gateway/transcode-on-demand.sh'),
    sourceUrl, name, 'audio-mix', spec], { stdio: ['ignore', 'pipe', 'pipe'] }));
  let stderr = '';
  child.stdout.on('data', () => undefined);
  child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  return { name, child, stderr: () => stderr };
}

function stopMix(mix) {
  try { mix.child.kill('SIGTERM'); } catch { /* already gone */ }
}

/** Records `seconds` of one route to a file. */
function record(target, seconds, file, extra = []) {
  const result = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-rtsp_transport', 'tcp',
    '-i', `rtsp://127.0.0.1:${RTSP_PORT}/${target}`, '-t', String(seconds), ...extra, file],
    { timeout: (seconds + 25) * 1000 });
  return { file, error: result.status === 0 ? '' : (result.stderr ?? '').slice(0, 400) };
}

/**
 * Mean amplitude of one frequency in a window of float samples.  A direct DFT is
 * used rather than a Goertzel recurrence: the first version of this helper
 * silently returned zero, which made a passing pipeline look broken.
 */
function toneEnergy(samples, sampleRate, frequency) {
  let real = 0;
  let imaginary = 0;
  const step = (2 * Math.PI * frequency) / sampleRate;
  for (let index = 0; index < samples.length; index++) {
    const angle = step * index;
    real += samples[index] * Math.cos(angle);
    imaginary -= samples[index] * Math.sin(angle);
  }
  return samples.length ? Math.hypot(real, imaginary) / samples.length : 0;
}

function readWav(file) {
  const probe = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=sample_rate,channels',
    '-of', 'json', file], { encoding: 'utf8' });
  const stream = JSON.parse(probe.stdout || '{}').streams?.[0] ?? {};
  const sampleRate = Number(stream.sample_rate) || 8000;
  const raw = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1',
    '-ar', String(sampleRate), '-'], { encoding: 'buffer', maxBuffer: 1 << 28 });
  const bytes = raw.stdout.subarray(0, raw.stdout.length - (raw.stdout.length % 4));
  const samples = new Float32Array(bytes.byteLength / 4);
  for (let index = 0; index < samples.length; index++) samples[index] = bytes.readFloatLE(index * 4);
  return { sampleRate, samples };
}

function windowEnergies({ sampleRate, samples }, windowSeconds = 1) {
  const size = Math.round(sampleRate * windowSeconds);
  const windows = [];
  for (let offset = 0; offset + size <= samples.length; offset += size) {
    const slice = samples.subarray(offset, offset + size);
    windows.push({ second: offset / sampleRate, e440: toneEnergy(slice, sampleRate, 440), e880: toneEnergy(slice, sampleRate, 880) });
  }
  return windows;
}

function firstPtsMs(file, stream) {
  const result = spawnSync('ffprobe', ['-v', 'error', '-select_streams', stream, '-show_entries',
    'packet=pts_time', '-of', 'csv=p=0', file], { encoding: 'utf8' });
  const values = result.stdout.split('\n').map((line) => Number(line.split(',')[0]))
    .filter((value) => Number.isFinite(value));
  return values.length ? Math.min(...values) * 1000 : null;
}

/**
 * How far the video starts after the audio in the same recording.  The muxer
 * re-bases each stream to zero when timestamps are not copied, so the recorder
 * must keep them (-copyts) for this difference to be meaningful.
 */
function videoAudioOffsetMs(file) {
  const video = firstPtsMs(file, 'v');
  const audio = firstPtsMs(file, 'a');
  if (video === null || audio === null) return null;
  return video - audio;
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
    'logLevel: warn', 'rtsp: yes', `rtspAddress: :${RTSP_PORT}`, 'rtspTransports: [tcp]',
    'api: yes', `apiAddress: 127.0.0.1:${API_PORT}`, 'webrtc: no', 'hls: no',
    'paths:', '  all_others:', '',
  ].join('\n'));

  const server = track(spawn(mediamtx, [config], { stdio: ['ignore', 'ignore', 'ignore'] }));
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
    '-c:a', 'libopus', '-b:a', '96k', '-ar', '48000', '-ac', '1', '-t', '180',
    '-rtsp_transport', 'tcp', '-f', 'rtsp', `rtsp://127.0.0.1:${RTSP_PORT}/synth`],
    { stdio: ['ignore', 'ignore', 'ignore'] }));
  log('synthetic dual-tone publisher running');
  await sleep(5000);

  const source = `rtsp://127.0.0.1:${RTSP_PORT}/synth`;
  const captured = [];

  // Case 1: the first (440 Hz) track is muted; the second must stay audible.
  {
    const mix = startMix('0:1.0:1,1:1.0:0', source);
    expect(await waitForRoute(mix.name), 'the muted-first-track mix route became ready');
    const file = path.join(evidence, 'case1.wav');
    record(mix.name, 8, file, ['-vn', '-ac', '1', '-ar', '8000']);
    const windows = windowEnergies(readWav(file)).slice(1);
    const e440 = Math.max(...windows.map((w) => w.e440), 0);
    const e880 = Math.max(...windows.map((w) => w.e880), 0);
    captured.push({ case: 'muted-first-track', windows: windows.length, e440, e880 });
    expect(windows.length >= 3, `the muted-first-track capture has usable windows (${windows.length})`);
    expect(e880 > 1e6, `muting the first track keeps the second audible (e880=${e880.toFixed(0)})`);
    expect(e880 > e440 * 20, `muting the first track really removes 440 Hz (e440=${e440.toFixed(0)})`);
    stopMix(mix);
  }

  // Case 2: gain is applied exactly once (0.25 on 440 Hz => about -12 dB).
  {
    const mix = startMix('0:0.25:0,1:1.0:0', source);
    expect(await waitForRoute(mix.name), 'the gain mix route became ready');
    const file = path.join(evidence, 'case2.wav');
    record(mix.name, 8, file, ['-vn', '-ac', '1', '-ar', '8000']);
    const windows = windowEnergies(readWav(file)).slice(1);
    const mean = (key) => windows.reduce((sum, w) => sum + w[key], 0) / Math.max(1, windows.length);
    const ratio = 20 * Math.log10(Math.max(1e-9, mean('e880')) / Math.max(1e-9, mean('e440')));
    captured.push({ case: 'gain-once', windows: windows.length, ratioDb: ratio });
    expect(windows.length >= 3, `the gain capture has usable windows (${windows.length})`);
    expect(Math.abs(ratio - 12.04) < 3, `0.25 gain on one track is about -12 dB (measured ${ratio.toFixed(2)} dB)`);
    stopMix(mix);
  }

  // Case 3: a negative offset is normalised; the video is shifted by the same B.
  {
    const mix = startMix('0:1.0:0:-2000,1:1.0:0:0', source);
    expect(await waitForRoute(mix.name), 'the negative-offset mix route became ready');
    expect(/新增端到端延迟: 2000ms/.test(mix.stderr()),
      `the transcoder reports the added end-to-end delay (stderr: ${mix.stderr().trim().slice(0, 120)})`);
    const file = path.join(evidence, 'case3.mkv');
    record(mix.name, 12, file, ['-copyts', '-c', 'copy']);
    const offset = videoAudioOffsetMs(file);
    captured.push({ case: 'negative-offset', videoMinusAudioMs: offset });
    expect(offset !== null && offset > 1800 && offset < 2300,
      `a -2000ms track offset delays the video by 2000ms relative to the audio (measured ${offset?.toFixed(0)}ms)`);
    const wav = path.join(evidence, 'case3.wav');
    spawnSync('ffmpeg', ['-v', 'error', '-y', '-i', file, '-vn', '-ac', '1', '-ar', '8000', wav], { timeout: 60000 });
    const windows = windowEnergies(readWav(wav));
    const first = windows[1] ?? { e440: 0, e880: 0 };
    const later = windows.at(-1) ?? { e440: 0, e880: 0 };
    captured.push({ case: 'negative-offset-tone', first, later });
    expect(first.e440 > 1e6, `the normalised track starts immediately (e440=${first.e440.toFixed(0)})`);
    expect(later.e880 > later.e440 * 0.2,
      `the other track joins after its 2s normalisation delay (later 880=${later.e880.toFixed(0)})`);
    stopMix(mix);
  }

  writeFileSync(path.join(evidence, 'result.json'), JSON.stringify({ captured, failures }, null, 2));
  log(`evidence: ${evidence}`);
}

main()
  .catch((error) => fail(`fatal: ${error.message}`))
  .finally(() => {
    shutdown();
    setTimeout(() => {
      console.log(failures.length ? `[audio] ${failures.length} check(s) failed` : '[audio] all checks passed');
      process.exit(failures.length ? 1 : 0);
    }, 1500);
  });
