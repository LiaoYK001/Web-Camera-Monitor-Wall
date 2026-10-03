const { app, safeStorage, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
app.on('window-all-closed', () => {});

(async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'webobs-native-smoke-'));
  const dataRoot = path.join(temporary, 'WebOBS');
  app.setPath('userData', dataRoot);
  app.setPath('sessionData', path.join(dataRoot, 'browser'));
  let supervisor, window, exitCode = 0;
  try {
    await app.whenReady();
    window = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, partition: 'persist:webobs-desktop' } });
    await window.loadURL('data:text/html,<title>Native runtime startup fixture</title>');
    const { Supervisor } = await import('../src/supervisor.mjs');
    const { defaults } = await import('../src/settings.mjs');
    const { verifyRuntime } = await import('../src/runtime-integrity.mjs');
    const runtime = path.resolve(__dirname, '../runtime');
    const manifest = await verifyRuntime(runtime);
    // A fresh isolated profile exercises bundled dependencies without developer PATH.
    process.env.PATH = path.join(process.env.SystemRoot, 'System32');
    supervisor = new Supervisor({ runtime, root: dataRoot, videos: path.join(temporary, 'Videos'), settings: { ...defaults }, version: manifest.version, safeStorage });
    supervisor.on('status', status => console.log(`Native startup: ${status.phase} ${status.detail}`));
    await supervisor.start();
    assert.equal(supervisor.state.phase, 'ready');
    const origin = supervisor.origin;
    assert.equal((await fetch(`${origin}/api/v1/runtime/info`)).status, 401);
    const credentials = { username: 'desktop-smoke-admin', password: crypto.randomBytes(24).toString('hex') };
    const request = { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(credentials) };
    const setup = await fetch(`${origin}/api/v1/auth/setup`, request);
    assert.ok(setup.ok, `first account setup failed (${setup.status})`);
    const login = await fetch(`${origin}/api/v1/auth/login`, request);
    assert.ok(login.ok, `login failed (${login.status})`);
    const cookie = login.headers.getSetCookie().map(value => value.split(';')[0]).join('; ');
    assert.ok(cookie);
    const headers = { Origin: origin, Cookie: cookie };
    const info = await fetch(`${origin}/api/v1/runtime/info`, { headers });
    assert.equal(info.status, 200);
    const description = await info.json();
    assert.equal(description.platform, 'windows');
    assert.equal(description.go2rtcRtspBase, `rtsp://127.0.0.1:${supervisor.ports.go2rtcRtsp}/`);
    for (const route of ['/api/v1/scene', '/api/v1/go2rtc/api/streams', '/api/v1/go2rtc/index.html']) {
      const result = await fetch(`${origin}${route}`, { headers });
      assert.ok(result.ok, `authenticated native route failed (${route}, ${result.status})`);
      await result.arrayBuffer();
    }
    const { exerciseNativeSync } = require('./native-sync-contract.cjs');
    const assertSyncPersisted = await exerciseNativeSync(origin, headers);
    await supervisor.stop();
    const snapshot = await supervisor.snapshot();
    assert.ok((await fs.stat(path.join(snapshot, 'snapshot.json'))).isFile());
    await supervisor.start();
    const restoredSession = await fetch(`${origin}/api/v1/auth/session`, { headers });
    assert.equal(restoredSession.status, 200, 'account session must survive service restart');
    await assertSyncPersisted();
    await supervisor.stop();
    console.log('Bundled Windows services, first login, authenticated go2rtc, two-device multi-track sync/conflict, snapshot and restart persistence passed. Camera/media qualification remains separate.');
  } catch (error) {
    exitCode = 1; console.error(error.stack);
    if (supervisor) {
      await supervisor.stop().catch(() => {});
      for (const name of ['native-tools', 'core', 'go2rtc', 'clients', 'cluster']) {
        const log = await fs.readFile(path.join(supervisor.root, 'logs', `${name}.log`), 'utf8').catch(() => '');
        if (log) console.error(`${name} diagnostic tail:\n${log.slice(-6000)}`);
      }
    }
  } finally {
    if (window && !window.isDestroyed()) window.destroy();
    if (temporary.startsWith(path.resolve(os.tmpdir()) + path.sep + 'webobs-native-smoke-')) await fs.rm(temporary, { recursive: true, force: true }).catch(() => {});
  }
  app.exit(exitCode);
})();
