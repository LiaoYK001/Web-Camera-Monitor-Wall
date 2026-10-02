// Run the real desktop entry against bundled services in a disposable profile.
// This checks desktop lifecycle; it is not clean-install or camera qualification.
const { app, BrowserWindow, dialog } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'webobs-native-main-'));
  process.env.LOCALAPPDATA = temporary;
  // Avoid touching the installed product's login-item registry entry.
  app.setName('WebOBS Native Main Validation');
  const videos = path.join(temporary, 'Videos');
  await fs.mkdir(videos);
  app.setPath('videos', videos);
  const errors = [];
  process.on('uncaughtException', error => errors.push(error));
  process.on('unhandledRejection', error => errors.push(error));
  dialog.showMessageBox = async () => ({ response: 1 });
  dialog.showErrorBox = (_title, message) => errors.push(new Error(message));
  let exitCode = 0;
  try {
    await require('../src/bootstrap.cjs');
    const main = BrowserWindow.getAllWindows()[0];
    assert.ok(main);
    const state = await main.webContents.executeJavaScript('window.webobsDesktop.status()');
    assert.equal(state.runtime.phase, 'ready', state.runtime.detail);
    assert.equal(state.settings.lanEnabled, false);
    assert.equal(state.settings.startAtLogin, false);
    const origin = state.runtime.origin;
    const credentials = { username: 'desktop-main-admin', password: crypto.randomBytes(24).toString('hex') };
    const request = { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(credentials) };
    assert.ok((await fetch(`${origin}/api/v1/auth/setup`, request)).ok);
    const login = await fetch(`${origin}/api/v1/auth/login`, request);
    assert.ok(login.ok);
    const cookies = login.headers.getSetCookie();
    const headers = { Origin: origin, Cookie: cookies.map(value => value.split(';')[0]).join('; ') };
    for (const cookie of cookies) {
      const pair = cookie.split(';')[0], split = pair.indexOf('=');
      await main.webContents.session.cookies.set({ url: origin, name: pair.slice(0, split), value: pair.slice(split + 1), httpOnly: true, sameSite: 'lax' });
    }
    const studio = await (await fetch(`${origin}/api/v1/studio`, { headers })).json();
    const second = { ...structuredClone(studio.scenes[0]), id: 'native-main-second', name: 'Second fixed projector' };
    studio.scenes.push(second);
    assert.ok((await fetch(`${origin}/api/v1/studio`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json', 'If-Match': `"${studio.revision}"` }, body: JSON.stringify(studio) })).ok);
    for (const scene of [studio.scenes[0], second]) {
      await main.webContents.executeJavaScript(`window.webobsDesktop.projector(${JSON.stringify({ mode: 'direct', sceneId: scene.id })})`);
    }
    const projectors = BrowserWindow.getAllWindows().filter(window => window !== main);
    assert.equal(projectors.length, 2);
    for (const projector of projectors) {
      const deadline = Date.now() + 15000;
      while (projector.webContents.isLoading() && Date.now() < deadline) await pause(100);
      assert.equal(projector.webContents.session, main.webContents.session);
      assert.ok(projector.webContents.getURL().includes('#projector?scene='));
      assert.equal(await projector.webContents.executeJavaScript('fetch("/api/v1/auth/session").then(response=>response.status)'), 200);
    }
    main.show(); main.close();
    assert.equal(main.isDestroyed(), false);
    assert.equal(main.isVisible(), false);
    assert.equal((await fetch(`${origin}/api/v1/health`)).status, 200);
    assert.ok(projectors.every(projector => !projector.isDestroyed()));
    app.emit('second-instance');
    assert.equal(main.isVisible(), true);
    for (const window of BrowserWindow.getAllWindows()) {
      await window.webContents.executeJavaScript('window.webobsDesktop.reportWork({dirty:false,exporting:false})');
    }
    const stopped = new Promise(resolve => app.once('will-quit', event => { event.preventDefault(); resolve(); }));
    app.quit();
    let stopTimeout;
    try {
      await Promise.race([stopped, new Promise((_resolve, reject) => { stopTimeout = setTimeout(() => reject(new Error('Desktop normal exit timed out')), 40000); })]);
    } finally { clearTimeout(stopTimeout); }
    await assert.rejects(fetch(`${origin}/api/v1/health`, { signal: AbortSignal.timeout(1000) }));
    // Window closed callbacks must also remain safe after WebContents destruction.
    for (const window of BrowserWindow.getAllWindows()) window.destroy();
    await pause(100);
    assert.deepEqual(errors.map(error => String(error)), []);
    console.log('Actual desktop entry: first login, two fixed Scene projectors, shared session, tray hide and normal exit passed. Camera and clean-install qualification remain separate.');
  } catch (error) {
    exitCode = 1; console.error(error.stack);
    for (const name of ['native-tools', 'core', 'clients']) {
      const log = await fs.readFile(path.join(temporary, 'WebOBS', 'logs', `${name}.log`), 'utf8').catch(() => '');
      if (log) console.error(`${name} diagnostic tail:\n${log.slice(-5000)}`);
    }
  } finally {
    for (const window of BrowserWindow.getAllWindows()) window.destroy();
    if (temporary.startsWith(path.resolve(os.tmpdir()) + path.sep + 'webobs-native-main-')) await fs.rm(temporary, { recursive: true, force: true }).catch(() => {});
  }
  app.exit(exitCode);
})().catch(error => { console.error(error.stack); app.exit(1); });
