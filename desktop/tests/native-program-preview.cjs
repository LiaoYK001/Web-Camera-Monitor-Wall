// Actual Win32/libobs display and five reordered HEVC media sources in an
// isolated product. This is functional coverage, not a hardware/CPU benchmark.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const { spawn, execFileSync } = require('node:child_process');
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
  const route = 'hybrid-' + crypto.randomBytes(16).toString('hex');
  const media = path.join(temporary, 'native-hevc-bframes.mkv');
  const ffmpeg = path.join(runtime, 'bin/ffmpeg.exe');
  execFileSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=10',
    '-t', '4', '-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params', 'pools=1:frame-threads=1:bframes=2:keyint=10', '-an', media],
    { windowsHide: true, timeout: 30000, stdio: 'ignore' });
  const probe = JSON.parse(execFileSync(path.join(runtime, 'bin/ffprobe.exe'), ['-v', 'error', '-show_entries',
    'stream=codec_name,has_b_frames', '-of', 'json', media], { windowsHide: true, timeout: 15000, encoding: 'utf8' }));
  assert.equal(probe.streams[0].codec_name, 'hevc'); assert.ok(probe.streams[0].has_b_frames > 0);
  assert.equal((await fetch(gateway + '/v3/config/paths/add/' + route, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: 'publisher', overridePublisher: false }) })).status, 200);
  let publisher;
  const saveScene = async scene => {
    const current = await get('/api/v1/scene');
    const result = await fetch(origin + '/api/v1/scene', { method: 'PUT', headers: { ...headers,
      'Content-Type': 'application/json', 'If-Match': `"${current.revision}"` }, body: JSON.stringify({ ...scene, revision: current.revision }) });
    assert.ok(result.ok, 'native fixture scene save');
  };
  try {
    publisher = spawn(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-re', '-stream_loop', '-1', '-i', media,
      '-c', 'copy', '-rtsp_transport', 'tcp', '-f', 'rtsp', `rtsp://127.0.0.1:${supervisor.ports.rtsp}/${route}`],
      { windowsHide: true, stdio: ['pipe', 'ignore', 'ignore'] });
    let failure; publisher.on('error', error => { failure = error; });
    await until(async () => {
      if (failure) throw failure;
      const response = await fetch(gateway + '/v3/paths/get/' + route);
      return response.ok && (await response.json()).ready;
    });
    const scene = { ...original, sources: [], items: [] };
    for (let i = 0; i < 5; i++) {
      const id = `native-hevc-${i}`;
      scene.sources.push({ id, kind: 'rtsp', name: `Synthetic native HEVC ${i}`, rtspUrl: `rtsp://127.0.0.1:${supervisor.ports.rtsp}/${route}`,
        transport: 'tcp', muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] });
      scene.items.push({ id: `native-item-${i}`, sourceId: id, x: i * original.canvas.width / 5, y: 0,
        width: original.canvas.width / 5, height: original.canvas.height, zIndex: i, visible: true, locked: false,
        scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' });
    }
    await saveScene(scene);
    await native('POST');
    await until(async () => { const value = await native(); assert.notEqual(value.state, 3); return value.state === 2 && value.frames > 10; });
    await until(async () => { await native(); return (await get('/api/v1/sources/status')).healthy === 5; });
    const before = (await native()).frames;
    await pause(1000);
    assert.ok((await native()).frames > before);
    assert.equal((await get('/api/v1/program/status')).publish, 'idle', 'native display must not activate the encoder/publisher');
    const paths = await (await fetch(gateway + '/v3/paths/list')).json();
    assert.deepEqual(paths.items.filter(item => item.name.startsWith('hybrid-')).map(item => item.name), [route], 'native viewing creates no video compatibility routes');
    await native('DELETE');
    await until(async () => (await native()).state === 0);
    await native('POST');
    await until(async () => (await native()).frames > 10 && (await native()).state === 2);
    // Losing the desktop heartbeat must close the host picture as well.
    await pause(16000);
    const expired = await native(); assert.equal(expired.requested, false); assert.equal(expired.state, 0);
    console.log('Actual native Program: five synthetic reordered HEVC sources healthy, draw callbacks progress, no Composite publisher or compatibility video route, close/reopen and lease expiry passed. Hardware/CPU/camera qualification remains open.');
  } finally {
    await native('DELETE').catch(() => {});
    await until(async () => (await native()).state === 0).catch(() => {});
    await saveScene(original);
    if (publisher && publisher.exitCode === null) {
      const exited = new Promise(resolve => publisher.once('exit', resolve)); publisher.kill(); await exited;
    }
    await fetch(gateway + '/v3/config/paths/delete/' + route, { method: 'DELETE' });
    await fs.rm(media, { force: true });
  }
};
