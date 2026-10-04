// Complete isolated product + authenticated WebUI; requires the bundled online-source image.
const assert = require('node:assert/strict');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const { execFileSync } = require('node:child_process');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '..');
const { chromium, expect } = createRequire(path.join(root, 'web/package.json'))('@playwright/test');
const option = name => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1]; };
const image = option('--image'), docker = option('--docker') || 'docker';
assert(image, 'Supply a complete image with bundled website tools');
const name = 'webobs-online-source-' + crypto.randomBytes(5).toString('hex');
const run = (...args) => execFileSync(docker, args, { encoding: 'utf8', windowsHide: true, timeout: 60000 }).trim();
let created = false, browser;
(async () => {
  try {
    const socket = net.createServer();
    const port = await new Promise(resolve => socket.listen(0, '127.0.0.1', () => resolve(socket.address().port)));
    await new Promise(resolve => socket.close(resolve));
    run('run', '--detach', '--name', name, '-p', `127.0.0.1:${port}:8080`,
      '--mount', `type=bind,source=${path.join(root, 'web/dist')},target=/opt/webobs/ui,readonly`,
      '--mount', `type=bind,source=${path.join(root, 'tests/prepare_online_source_fixture.py')},target=/tmp/prepare_online_source_fixture.py,readonly`,
      '-e', 'WEBOBS_LISTEN_ADDRESS=0.0.0.0', '-e', 'WEBOBS_ALLOW_INSECURE_REMOTE=true', '-e', 'WEBOBS_GO2RTC_ENABLED=true',
      '-e', 'WEBOBS_COMPOSITE_ENABLED=false', '-e', 'WEBOBS_COMPAT_BASIC_AUTH=false', '-e', 'WEBOBS_SESSION_COOKIE_SECURE=false', image);
    created = true;
    const base = 'http://' + run('port', name, '8080/tcp').split('\n')[0];
    await expect.poll(async () => { try { return (await fetch(base + '/api/v1/health', { signal: AbortSignal.timeout(1000) })).status; } catch { return 0; } }, { timeout: 30000 }).toBe(200);
    run('exec', name, 'python3', '-B', '/tmp/prepare_online_source_fixture.py');
    browser = await chromium.launch();
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const account = { username: 'online-source-admin', password: crypto.randomBytes(24).toString('hex') };
    assert.equal((await context.request.post(base + '/api/v1/auth/setup', { headers: { Origin: base }, data: account })).status(), 201);
    assert.equal((await context.request.post(base + '/api/v1/auth/login', { headers: { Origin: base }, data: account })).status(), 200);
    const response = await context.request.get(base + '/api/v1/runtime/info');
    assert.equal((await response.json()).onlineSourcesEnabled, true);
    const page = await context.newPage();
    await require('./online_source_webui.cjs').exerciseOnlineSources(page, base);
    run('restart', '--time', '30', name);
    await expect.poll(async () => { try { return (await context.request.get(base + '/api/v1/health')).status(); } catch { return 0; } }, { timeout: 30000 }).toBe(200);
    const streams = await (await context.request.get(base + '/api/v1/go2rtc/api/streams')).json();
    assert(Object.hasOwn(streams, 'website-fixture-yt-dlp') && Object.hasOwn(streams, 'website-fixture-streamlink'));
    run('exec', name, 'python3', '-B', '/tmp/prepare_online_source_fixture.py');
    for (const flow of ['website-fixture-yt-dlp', 'website-fixture-streamlink']) await require('./online_source_webui.cjs').assertOnlineVideo(page, base, flow);
    console.log('PASS named website streams retained across normal product restart; synthetic media, no external-site or physical-device qualification');
  } finally { await browser?.close(); if (created) run('rm', '--force', '--volumes', name); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
