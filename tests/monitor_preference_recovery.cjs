const { createRequire } = require('node:module');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const net = require('node:net');
const { largePreferenceWorkspace, largeSourceAudioWorkspace } = require('./fixtures/preference-workspace.cjs');
const root = path.resolve(__dirname, '..');
const { chromium, expect } = createRequire(path.join(root, 'web/package.json'))('@playwright/test');
// Build web/dist first and supply a complete product image explicitly.
// node tests/monitor_preference_recovery.cjs --image webobs:test [--docker <executable>]
const option = name => { const index = process.argv.indexOf(name); return index < 0 ? undefined : process.argv[index + 1]; };
const image = option('--image');
if (!image || image.startsWith('--')) throw new Error('Supply --image <complete-product-image>; this test uses an isolated disposable profile.');
const docker = option('--docker') || 'docker';
const name = 'webobs-preference-read-' + crypto.randomBytes(5).toString('hex');
const run = (...args) => execFileSync(docker, args, { encoding: 'utf8', windowsHide: true, timeout: 60000 }).trim();
let created = false, browser;
(async () => {
  try {
    const socket = net.createServer();
    const port = await new Promise(resolve => socket.listen(0, '127.0.0.1', () => resolve(socket.address().port)));
    await new Promise(resolve => socket.close(resolve));
    run('run', '--detach', '--name', name, '-p', '127.0.0.1::8080', '-p', `127.0.0.1:${port}:${port}/udp`,
      '--mount', `type=bind,source=${path.join(root, 'web/dist')},target=/opt/webobs/ui,readonly`,
      '--mount', `type=bind,source=${path.join(root, 'cluster/cluster_service.py')},target=/opt/webobs/bin/webobs-cluster,readonly`,
      '-e', 'WEBOBS_LISTEN_ADDRESS=0.0.0.0', '-e', 'WEBOBS_ALLOW_INSECURE_REMOTE=true',
      '-e', 'WEBOBS_GO2RTC_ENABLED=true', '-e', 'WEBOBS_WEBRTC_ENABLED=true', '-e', 'WEBOBS_COMPOSITE_ENABLED=false',
      '-e', `MTX_WEBRTCLOCALUDPADDRESS=:${port}`, '-e', 'WEBOBS_NVR_ENABLED=true', '-e', 'WEBOBS_CLUSTER_ENABLED=true',
      '-e', 'WEBOBS_COMPAT_BASIC_AUTH=false', '-e', 'WEBOBS_SESSION_COOKIE_SECURE=false', '-e', 'WEBOBS_REGISTRATION_ENABLED=true',
      image);
    created = true;
    const base = 'http://' + run('port', name, '8080/tcp').split('\n')[0];
    for (let i = 0; i < 120; i++) {
      try { if ((await fetch(base + '/api/v1/health', { signal: AbortSignal.timeout(1000) })).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    browser = await chromium.launch();
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const headers = { Origin: base };
    const account = { username: 'preference-recovery', password: crypto.randomBytes(24).toString('hex') };
    assert.equal((await context.request.post(base + '/api/v1/auth/setup', { headers, data: account })).status(), 201);
    assert.equal((await context.request.post(base + '/api/v1/auth/login', { headers, data: account })).status(), 200);
    await require('../desktop/tests/native-preference-json.cjs').exercisePreferenceJson(base, {
      ...headers, Cookie: (await context.cookies(base)).map(cookie => `${cookie.name}=${cookie.value}`).join('; '),
    });
    assert.equal((await context.request.post(base + '/api/v1/go2rtc/api/config', { headers: { ...headers, 'Content-Type': 'text/plain' },
      data: 'streams:\n  synthetic: "ffmpeg:virtual?video=testsrc2&size=320x180#video=h264"\n' })).status(), 200);
    await context.request.post(base + '/api/v1/go2rtc/api/restart', { headers });
    await expect.poll(async () => (await context.request.get(base + '/api/v1/go2rtc/api/streams')).status()).toBe(200);
    const runtime = await (await context.request.get(base + '/api/v1/runtime/info')).json();
    const address = runtime.go2rtcRtspBase + 'synthetic';
    const detection = await context.request.post(base + '/api/v1/camera-detect', { headers, data: { address } });
    assert.equal(detection.status(), 200);
    const detected = await detection.json();
    const response = await context.request.post(base + '/api/v1/cameras', { headers, data: { name: 'Synthetic recovery camera', address,
      adapter: 'rtsp', hardwareDecode: 'auto', credentialsRef: '', capabilities: { bridge: 'go2rtc' },
      profiles: detected.profiles.map(profile => ({ ...profile, transportMode: 'rtsp-tcp' })) } });
    assert.equal(response.status(), 201);
    const camera = await response.json();
    const studio = await (await context.request.get(base + '/api/v1/studio')).json();
    const scene = studio.scenes[0];
    scene.sources = [{ id: 'recovery-camera', name: 'Synthetic recovery camera', kind: 'camera', cameraId: camera.id,
      profileId: camera.profiles[0].id, hardwareDecode: 'auto', muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }];
    scene.items = [{ id: 'recovery-item', sourceId: 'recovery-camera', x: 0, y: 0, width: scene.canvas.width, height: scene.canvas.height,
      scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true, locked: false,
      groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }];
    studio.previewSceneId = studio.programSceneId = scene.id;
    const committed = await context.request.put(base + '/api/v1/studio', { headers: { ...headers, 'If-Match': `"${studio.revision}"` }, data: studio });
    assert.equal(committed.status(), 200);
    assert.equal((await context.request.post(base + '/api/v1/studio/take', { headers: { ...headers, 'If-Match': `"${(await committed.json()).revision}"` } })).status(), 200);
    assert.equal((await (await context.request.get(base + '/api/v1/scene')).json()).sources[0].id, `${scene.id}.recovery-camera`);
    const preferences = { audioMonitorEnabled: true, audioOutput: 'meter-only', localMonitorVolume: .18, mode: 'manual' };
    assert.equal((await context.request.put(base + '/api/v2/account/preferences/monitor-view', { headers, data: { value: preferences } })).status(), 200);
    run('exec', name, 'python3', '-c', "import sqlite3; db=sqlite3.connect('/config/webobs/cluster.sqlite3'); db.execute(\"UPDATE account_preferences SET body_json='{' WHERE kind='monitor-view'\"); db.commit()");
    assert.equal((await context.request.get(base + '/api/v2/account/preferences/monitor-view')).status(), 500);
    const page = await context.newPage();
    let writes = 0;
    page.on('request', request => { if (request.method() === 'PUT' && request.url().endsWith('/account/preferences/monitor-view')) writes++; });
    await page.goto(base + '/#monitor');
    const retry = page.getByRole('button', { name: '重试账号偏好', exact: true });
    await expect(retry).toBeVisible();
    await expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeDisabled();
    await page.waitForFunction(() => {
      const video = document.querySelector('.direct-preview video');
      return video && video.readyState >= 2 && video.getVideoPlaybackQuality().totalVideoFrames >= 10;
    }, null, { timeout: 60000 });
    const before = await page.locator('.direct-preview video').evaluate(video => ({ frames: video.getVideoPlaybackQuality().totalVideoFrames, muted: video.muted }));
    assert.equal(before.muted, true); assert.equal(writes, 0);
    run('exec', name, 'python3', '-c', "import sqlite3,sys; db=sqlite3.connect('/config/webobs/cluster.sqlite3'); db.execute(\"UPDATE account_preferences SET body_json=? WHERE kind='monitor-view'\",(sys.argv[1],)); db.commit()", JSON.stringify(preferences));
    await retry.click();
    await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.18');
    await expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeEnabled();
    await expect(page.locator('.hero-audio-control').getByRole('combobox', { name: '声音输出模式' })).toHaveValue('meter-only');
    await expect.poll(() => page.locator('.direct-preview video').evaluate(video => video.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(before.frames);
    assert.equal(writes, 0);
    console.log('PASS production WebUI + complete isolated Linux product: real go2rtc RTSP import and MediaMTX H264 Direct decoding continue through an actual corrupt preference-row HTTP 500; audio stays muted, no default PUT, explicit retry restores account volume/output while decoded frames advance. No API/media mocks; service workers blocked, OBS disabled. Synthetic source, not physical camera or PWA offline qualification.');
    await page.close();
    const large = largePreferenceWorkspace();
    assert.equal((await context.request.put(base + '/api/v2/account/preferences/monitor-view', { headers, data: { value: large } })).status(), 200);
    const legacyPair = { baseValue: large, value: { ...large, localMonitorVolume: .31 } };
    const fullPairBytes = Buffer.byteLength(JSON.stringify(legacyPair));
    assert.ok(fullPairBytes > 1024 * 1024);
    assert.equal((await context.request.put(base + '/api/v2/account/preferences/monitor-view', { headers, data: legacyPair })).status(), 413);
    const wide = await context.newPage();
    // Navigation keepalive requests may outlive the test driver's Page target.
    // Record only finite byte/keepalive metadata synchronously before invoking
    // the real fetch; sessionStorage survives this same-window reload.
    const observeWire = async () => wide.evaluate(() => {
      const original = window.fetch;
      window.fetch = (input, init) => {
        if (String(input).endsWith('/account/preferences/monitor-view') && init?.method === 'PUT') {
          const receipts = JSON.parse(sessionStorage.getItem('preference-test-wire') || '[]');
          receipts.push({ bytes: new TextEncoder().encode(String(init.body)).byteLength, keepalive: init.keepalive });
          sessionStorage.setItem('preference-test-wire', JSON.stringify(receipts.slice(-16)));
        }
        return original(input, init);
      };
    });
    await wide.goto(base + '/#monitor');
    await expect(wide.getByRole('slider', { name: '本地监听主音量' })).toBeEnabled();
    await observeWire();
    await wide.getByRole('slider', { name: '本地监听主音量' }).fill('0.31');
    await wide.reload();
    await expect(wide.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.31', { timeout: 10000 });
    const saved = (await (await context.request.get(base + '/api/v2/account/preferences/monitor-view')).json()).value;
    assert.equal(saved.localMonitorVolume, .31);
    assert.deepEqual(saved.sourceDecorations, large.sourceDecorations);
    const wire = await wide.evaluate(() => JSON.parse(sessionStorage.getItem('preference-test-wire') || '[]'));
    assert.ok(wire.length > 0 && wire.every(request => request.bytes < 1024 && request.keepalive));
    console.log(`PASS actual large-account API + production UI: prior full pair ${fullPairBytes} bytes is rejected by the unchanged 1 MiB gateway limit; a real reload submits ${wire[0].bytes} bytes with keepalive and preserves 1000 source preferences. No request/response mocks.`);
    await observeWire();
    await wide.getByRole('checkbox', { name: '统计叠层（全部来源）', exact: true }).check();
    await expect.poll(async () => {
      const value = (await (await context.request.get(base + '/api/v2/account/preferences/monitor-view')).json()).value;
      return Object.values(value.sourceDecorations).every(source => source.telemetry.enabled);
    }).toBe(true);
    const bulk = (await (await context.request.get(base + '/api/v2/account/preferences/monitor-view')).json()).value;
    assert.equal(Object.keys(bulk.sourceDecorations).length, 1000);
    assert.deepEqual(bulk.sourceDecorations['other-scene-999'].audioMeter, large.sourceDecorations['other-scene-999'].audioMeter);
    const bulkWire = await wide.evaluate(() => JSON.parse(sessionStorage.getItem('preference-test-wire')).at(-1));
    assert.ok(bulkWire.bytes < 1024 * 1024);
    console.log(`PASS actual atomic bulk update: 1000 source telemetry preferences saved with ${bulkWire.bytes} bytes; unrelated audio meter controls retained.`);
    await wide.close();
    for (const identity of ['constructor', '__proto__']) {
      const currentScene = await (await context.request.get(base + '/api/v1/scene')).json();
      currentScene.sources[0].id = identity; currentScene.items[0].sourceId = identity;
      // TAKE namespaces identifiers. The authenticated Program API also accepts
      // the exact boundary names and must render them without inherited values.
      const staged = await context.request.put(base + '/api/v1/scene', {
        headers: { ...headers, 'If-Match': `"${currentScene.revision}"` }, data: currentScene });
      assert.equal(staged.status(), 200);
      assert.equal((await (await context.request.get(base + '/api/v1/scene')).json()).sources[0].id, identity);
      const identityPreferences = { ...preferences, audioMonitorEnabled: false, showAllAudioSources: true,
        sourceDecorations: Object.fromEntries([[identity, { fill: 'contain', telemetry: { enabled: true, fields: ['fps'] } }]]) };
      assert.equal((await context.request.put(base + '/api/v2/account/preferences/monitor-view', { headers, data: { value: identityPreferences } })).status(), 200);
      const identityPage = await context.newPage();
      await identityPage.goto(base + '/#monitor');
      await expect(identityPage.getByRole('slider', { name: '本地监听主音量' })).toBeEnabled();
      await expect(identityPage.locator('.audio-mixer-channel')).toHaveAttribute('data-source-id', identity);
      await identityPage.waitForFunction(() => document.querySelector('.direct-preview video')?.getVideoPlaybackQuality().totalVideoFrames >= 10,
        null, { timeout: 60000 });
      await identityPage.getByRole('slider', { name: '本地监听主音量' }).fill('0.22');
      await identityPage.reload();
      await expect(identityPage.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.22');
      await expect(identityPage.locator('.audio-mixer-channel')).toHaveAttribute('data-source-id', identity);
      await identityPage.waitForFunction(() => document.querySelector('.direct-preview video')?.getVideoPlaybackQuality().totalVideoFrames >= 10,
        null, { timeout: 60000 });
      const identitySaved = (await (await context.request.get(base + '/api/v2/account/preferences/monitor-view')).json()).value;
      assert.ok(Object.hasOwn(identitySaved.sourceDecorations, identity));
      assert.equal(identitySaved.sourceDecorations[identity].fill, 'contain');
      assert.deepEqual(identitySaved.sourceDecorations[identity].telemetry.fields, ['fps']);
      await identityPage.close();
    }
    console.log('PASS actual accepted Scene identities constructor/__proto__: real Direct H264 frames before and after preference save/reload, with own source decorations retained. No API/media mocks.');
    const audioStudio = await (await context.request.get(base + '/api/v1/scene')).json();
    audioStudio.sources[0].id = 'other-scene-999'; audioStudio.items[0].sourceId = 'other-scene-999';
    assert.equal((await context.request.put(base + '/api/v1/scene', {
      headers: { ...headers, 'If-Match': `"${audioStudio.revision}"` }, data: audioStudio })).status(), 200);
    const audioPreferences = largeSourceAudioWorkspace();
    assert.equal((await context.request.put(base + '/api/v2/account/preferences/monitor-view', { headers, data: { value: audioPreferences } })).status(), 200);
    const audioPage = await context.newPage(); await audioPage.goto(base + '/#monitor');
    await expect(audioPage.getByRole('slider', { name: '本地监听主音量' })).toBeEnabled();
    const sourceGain = audioPage.getByRole('slider', { name: 'Synthetic recovery camera 音量' });
    const sourceMute = audioPage.getByRole('button', { name: 'Synthetic recovery camera 静音', exact: true });
    const sourceMonitor = audioPage.getByRole('button', { name: 'Synthetic recovery camera 本地监听', exact: true });
    await expect(audioPage.locator('.audio-mixer-channel')).toHaveAttribute('data-source-id', 'other-scene-999');
    await expect(sourceGain).toHaveValue('0.27');
    await expect(sourceMute).toHaveAttribute('aria-pressed', 'false');
    await expect(sourceMonitor).toHaveAttribute('aria-pressed', 'false');
    await audioPage.waitForFunction(() => document.querySelector('.direct-preview video')?.getVideoPlaybackQuality().totalVideoFrames >= 10,
      null, { timeout: 60000 });
    await audioPage.getByRole('slider', { name: '本地监听主音量' }).fill('0.33');
    await audioPage.reload();
    await expect(audioPage.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.33');
    await expect(sourceGain).toHaveValue('0.27');
    await expect(sourceMute).toHaveAttribute('aria-pressed', 'false');
    await expect(sourceMonitor).toHaveAttribute('aria-pressed', 'false');
    assert.deepEqual((await (await context.request.get(base + '/api/v2/account/preferences/monitor-view')).json()).value.sourceAudio, audioPreferences.sourceAudio);
    console.log('PASS production UI + actual Linux account API: late source volume/mute/monitor restored from 1000 audio controls before and after a real master-volume save/reload; H264 decoding continues. Video-only synthetic source, not physical audio qualification.');
    await audioPage.close();
  } finally {
    await browser?.close();
    if (created) run('rm', '--force', '--volumes', name);
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
