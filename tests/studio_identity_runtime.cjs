// Isolated complete product, optionally with the freshly compiled core mounted.
const { createRequire } = require('node:module');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const net = require('node:net');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const { chromium, expect } = createRequire(path.join(root, 'web/package.json'))('@playwright/test');
const option = name => { const index = process.argv.indexOf(name); return index < 0 ? undefined : process.argv[index + 1]; };
const image = option('--image'), core = option('--core');
if (!image) throw new Error('Supply --image <complete-product-image> and build web/dist first.');
const docker = option('--docker') || 'docker';
const name = 'webobs-studio-identity-' + crypto.randomBytes(5).toString('hex');
const run = (...args) => execFileSync(docker, args, { encoding: 'utf8', windowsHide: true, timeout: 60000 }).trim();
let created = false, browser;
(async () => {
  try {
    const socket = net.createServer();
    const port = await new Promise(resolve => socket.listen(0, '127.0.0.1', () => resolve(socket.address().port)));
    await new Promise(resolve => socket.close(resolve));
    const mounts = ['--mount', `type=bind,source=${path.join(root, 'web/dist')},target=/opt/webobs/ui,readonly`,
      '--mount', `type=bind,source=${path.join(root, 'cluster/cluster_service.py')},target=/opt/webobs/bin/webobs-cluster,readonly`];
    if (core) mounts.push('--mount', `type=bind,source=${path.resolve(core)},target=/opt/obs/bin/webobsd,readonly`);
    run('run', '--detach', '--name', name, '-p', `127.0.0.1:${port}:8080`, ...mounts,
      '-e', 'WEBOBS_LISTEN_ADDRESS=0.0.0.0', '-e', 'WEBOBS_ALLOW_INSECURE_REMOTE=true',
      '-e', 'WEBOBS_COMPOSITE_ENABLED=false', '-e', 'WEBOBS_CLUSTER_ENABLED=true',
      '-e', 'WEBOBS_COMPAT_BASIC_AUTH=false', '-e', 'WEBOBS_SESSION_COOKIE_SECURE=false', image);
    created = true;
    const base = 'http://' + run('port', name, '8080/tcp').split('\n')[0];
    const health = async () => {
      await expect.poll(async () => {
        try { return (await fetch(base + '/api/v1/health', { signal: AbortSignal.timeout(1000) })).status; }
        catch { return 0; }
      }, { timeout: 30000 }).toBe(200);
    };
    await health();
    browser = await chromium.launch();
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const account = { username: 'studio-identity-admin', password: crypto.randomBytes(24).toString('hex') };
    assert.equal((await context.request.post(base + '/api/v1/auth/setup', { headers: { Origin: base }, data: account })).status(), 201);
    assert.equal((await context.request.post(base + '/api/v1/auth/login', { headers: { Origin: base }, data: account })).status(), 200);
    const headers = { Origin: base, Cookie: (await context.cookies(base)).map(cookie => `${cookie.name}=${cookie.value}`).join('; ') };
    const page = await context.newPage();
    const observe = async (program, controls) => {
      await page.goto(base + '/#monitor');
      await page.reload(); // Refresh the real account values, not a fixture cache.
      await expect(page.getByRole('slider', { name: '本地监听主音量', exact: true })).toHaveValue('0.18');
      await expect(page.locator('.direct-tile-position')).toHaveCount(program.items.length);
      for (const [name, control] of Object.entries(controls)) {
        await expect(page.getByRole('slider', { name: `${name} 音量`, exact: true })).toHaveValue(String(control.volume));
        await expect(page.getByRole('button', { name: `${name} 静音`, exact: true })).toHaveAttribute('aria-pressed', String(control.muted));
        await expect(page.getByRole('button', { name: `${name} 本地监听`, exact: true })).toHaveAttribute('aria-pressed', String(control.monitor));
      }
    };
    const assertPersisted = await require('../desktop/tests/native-studio-identity.cjs').exerciseStudioIdentity(base, headers, observe);
    run('stop', '--time', '30', name); run('start', name); await health();
    await assertPersisted(true);
    console.log('PASS actual Linux control server and production WebUI: authenticated TAKE/layer/Scene/nested/reload/restart preference identity checks; OBS disabled. Color fixtures, not physical camera/audio qualification.');
  } catch (error) {
    if (created) {
      const proof = path.join(root, 'build/v4-media-access');
      fs.mkdirSync(proof, { recursive: true });
      fs.writeFileSync(path.join(proof, 'scene-identity-runtime-diagnostics.log'), run('logs', name));
    }
    throw error;
  } finally {
    await browser?.close();
    if (created) run('rm', '--force', name);
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
