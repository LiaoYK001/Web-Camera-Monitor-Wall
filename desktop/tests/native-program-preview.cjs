// Actual Win32/libobs client pixels and five distinguishable reordered HEVC
// media sources in an isolated product. Not a hardware/CPU/camera benchmark.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const { spawn, execFileSync, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const pattern = require('./native-preview-pattern.cjs');
const execute = promisify(execFile);
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

exports.exerciseNativeProgramPreview = async (supervisor, runtime, headers, temporary) => {
  const origin = supervisor.origin, endpoint = origin + '/api/v1/program/native-preview';
  const nativeHeaders = { ...headers, 'X-WebOBS-Native-Token': supervisor.env.WEBOBS_NATIVE_PREVIEW_TOKEN };
  const get = async route => {
    const response = await fetch(origin + route, { headers }); assert.ok(response.ok); return response.json();
  };
  const native = async (method = 'GET') => {
    const response = await fetch(endpoint, { method, headers: nativeHeaders }); assert.equal(response.status, 200); return response.json();
  };
  const until = async predicate => {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) { if (await predicate()) return; await pause(100); }
    throw new Error('Native Program did not reach its expected state');
  };
  assert.equal((await fetch(endpoint)).status, 401);
  assert.equal((await fetch(endpoint, { headers })).status, 403);
  assert.equal((await fetch(endpoint, { headers: { ...nativeHeaders, Origin: 'https://invalid.example' } })).status, 403);
  assert.equal((await fetch(endpoint, { method: 'POST', headers: nativeHeaders, body: '{}' })).status, 400);
  assert.equal((await native()).requested, false);
  const original = await get('/api/v1/scene');
  const gateway = `http://127.0.0.1:${supervisor.ports.gatewayApi}`;
  const prefix = 'hybrid-' + crypto.randomBytes(16).toString('hex');
  const routes = Array.from({ length: 5 }, (_, i) => `${prefix}-${i}`);
  const ffmpeg = path.join(runtime, 'bin/ffmpeg.exe'), publishers = [];
  const receiptPath = path.resolve(__dirname, '../../build/desktop-windows/native-preview-pixels.json');
  const receipt = { schema: 1, scope: 'synthetic-visible-native-client-only', passed: false, stages: [] };
  const saveReceipt = async () => {
    await fs.mkdir(path.dirname(receiptPath), { recursive: true });
    await fs.writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
  };
  const saveScene = async scene => {
    const current = await get('/api/v1/scene');
    const result = await fetch(origin + '/api/v1/scene', { method: 'PUT', headers: { ...headers,
      'Content-Type': 'application/json', 'If-Match': `"${current.revision}"` }, body: JSON.stringify({ ...scene, revision: current.revision }) });
    assert.ok(result.ok, 'native fixture scene save');
  };
  const item = (id, slot, sourceId) => ({ id, sourceId, x: slot * original.canvas.width / 5, y: 0,
    width: original.canvas.width / 5, height: original.canvas.height, zIndex: slot, visible: true, locked: false,
    scaleMode: 'stretch', crop: { top: 0, right: 0, bottom: 0, left: 0 }, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' });
  const capture = async (name, dynamic, order = [0, 1, 2, 3, 4]) => {
    const directory = path.join(temporary, `native-visible-${name}`);
    await fs.mkdir(directory);
    // Renew the authenticated lease while an asynchronous external screenshot
    // utility is running; it receives no session, native token or camera URL.
    const heartbeat = setInterval(() => void native().catch(() => {}), 2000);
    let lastState;
    try {
      lastState = await native();
      const powershell = path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe');
      const env = { ...process.env }; for (const key of Object.keys(env)) if (key.toLowerCase() === 'psmodulepath') delete env[key];
      await execute(powershell, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        path.join(__dirname, 'capture-native-preview.ps1'), '-OwnerProcessId', String(process.pid),
        '-NativeExecutable', path.join(runtime, 'bin/webobsd.exe'), '-OutputDirectory', directory,
        '-SampleCount', dynamic ? '8' : '1'], { windowsHide: true, timeout: 30000, maxBuffer: 1024 * 1024, env });
      const values = [];
      for (let sample = 0; sample < (dynamic ? 8 : 1); sample++) {
        const image = pattern.bitmap(await fs.readFile(path.join(directory, `client-${sample}.bmp`)));
        values.push(pattern.inspect(image, original.canvas, { dynamic, order }));
      }
      if (dynamic) pattern.progress(values);
      receipt.stages.push({ name, passed: true, temporalCodes: values });
      await saveReceipt(); return values;
    } catch (error) {
      // Bounded, non-private state only; screenshots/URLs/tokens stay in the
      // disposable fixture directory, not the public receipt or error text.
      receipt.stages.push({ name, passed: false, nativeState: lastState, failure: String(error.message).slice(0, 4000) });
      await saveReceipt();
      throw new Error(`Native final pixel gate failed at ${name}: ${error.message}`, { cause: error });
    } finally { clearInterval(heartbeat); }
  };
  try {
    // B: establish Program/scene/texture presentation before testing codecs.
    const colors = { ...original, sources: pattern.COLORS.map((rgb, i) => ({ id: `native-color-${i}`, kind: 'color',
      name: `Known color ${i + 1}`, color: '#' + rgb.map(v => v.toString(16).padStart(2, '0')).join(''),
      muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] })), items: [] };
    colors.items = colors.sources.map((source, slot) => item(`native-color-item-${slot}`, slot, source.id));
    await saveScene(colors); await native('POST');
    await until(async () => { const value = await native(); assert.notEqual(value.state, 3); return value.state === 2 && value.frames > 10; });
    await capture('scene-colors', false);
    const scene = { ...original, sources: [], items: [] };
    for (let i = 0; i < 5; i++) {
      const raw = path.join(temporary, `native-pattern-${i}.rgb`), media = path.join(temporary, `native-hevc-${i}.mkv`);
      await fs.writeFile(raw, Buffer.concat(Array.from({ length: pattern.FRAMES }, (_, counter) => pattern.frame(i, counter))));
      execFileSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24',
        '-video_size', `${pattern.WIDTH}x${pattern.HEIGHT}`, '-framerate', String(pattern.FPS), '-i', raw,
        '-c:v', 'libx265', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast', '-x265-params', 'pools=1:frame-threads=1:bframes=2:keyint=10', '-an', media],
        { windowsHide: true, timeout: 30000, stdio: 'ignore' });
      const probe = JSON.parse(execFileSync(path.join(runtime, 'bin/ffprobe.exe'), ['-v', 'error', '-show_entries',
        'stream=codec_name,has_b_frames', '-of', 'json', media], { windowsHide: true, timeout: 15000, encoding: 'utf8' }));
      assert.equal(probe.streams[0].codec_name, 'hevc'); assert.ok(probe.streams[0].has_b_frames > 0);
      assert.equal((await fetch(gateway + '/v3/config/paths/add/' + routes[i], { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: 'publisher', overridePublisher: false }) })).status, 200);
      const publisher = spawn(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-re', '-stream_loop', '-1', '-i', media,
        '-c', 'copy', '-rtsp_transport', 'tcp', '-f', 'rtsp', `rtsp://127.0.0.1:${supervisor.ports.rtsp}/${routes[i]}`],
        { windowsHide: true, stdio: ['pipe', 'ignore', 'ignore'] });
      publishers.push(publisher); let failure; publisher.on('error', error => { failure = error; });
      await until(async () => {
        await native(); if (failure) throw failure;
        const response = await fetch(gateway + '/v3/paths/get/' + routes[i]);
        return response.ok && (await response.json()).ready;
      });
      const id = `native-hevc-${i}`;
      scene.sources.push({ id, kind: 'rtsp', name: `Synthetic native HEVC ${i + 1}`, rtspUrl: `rtsp://127.0.0.1:${supervisor.ports.rtsp}/${routes[i]}`,
        transport: 'tcp', muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] });
      scene.items.push(item(`native-item-${i}`, i, id));
    }
    await saveScene(scene);
    await until(async () => { await native(); return (await get('/api/v1/sources/status')).healthy === 5; });
    // HEVC decoder warmup is independent of source health/callback progress.
    await pause(1500); await capture('five-hevc', true);
    assert.equal((await get('/api/v1/program/status')).publish, 'idle', 'native display must not activate the encoder/publisher');
    const paths = await (await fetch(gateway + '/v3/paths/list')).json();
    assert.deepEqual(paths.items.filter(value => value.name.startsWith('hybrid-')).map(value => value.name).sort(), routes.sort(), 'native viewing creates no video compatibility routes');
    // Changed committed Program must change final positions, not just an API
    // revision. Reusing five source definitions must not swap channel identity.
    scene.items = scene.sources.map((source, i) => item(`native-item-${i}`, 4 - i, source.id));
    await saveScene(scene); await pause(700); await capture('program-reordered', true, [4, 3, 2, 1, 0]);
    await native('DELETE'); await until(async () => (await native()).state === 0);
    await native('POST'); await until(async () => (await native()).frames > 10 && (await native()).state === 2);
    await capture('reopened', true, [4, 3, 2, 1, 0]);
    // Losing the desktop heartbeat must close the host picture as well.
    await pause(16000);
    const expired = await native(); assert.equal(expired.requested, false); assert.equal(expired.state, 0);
    receipt.passed = true; await saveReceipt();
    console.log('Actual native Program: final visible scene colors and five distinct reordered HEVC channel pixels/time progression, committed layout reorder, no publisher/compatibility route, reopen and lease expiry passed. Hardware/CPU/camera qualification remains open.');
  } finally {
    await native('DELETE').catch(() => {});
    await until(async () => (await native()).state === 0).catch(() => {});
    try { await saveScene(original); }
    finally {
      for (const publisher of publishers) if (publisher.exitCode === null && publisher.signalCode === null) {
        const exited = new Promise(resolve => publisher.once('exit', resolve)); publisher.kill(); await exited;
      }
      await Promise.allSettled(routes.map(route => fetch(gateway + '/v3/config/paths/delete/' + route, { method: 'DELETE' })));
    }
  }
};
