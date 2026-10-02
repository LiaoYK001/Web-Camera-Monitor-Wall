const { app, BrowserWindow, ipcMain, nativeImage } = require('electron');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs/promises');
const os = require('node:os');
app.on('window-all-closed', () => {});

(async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'webobs-electron-smoke-'));
  app.setPath('userData', temporary);
  let server;
  let exitCode = 0;
  const windows = [];
  try {
    await app.whenReady();
    server = http.createServer((_request, response) => { response.setHeader('Content-Type', 'text/html'); response.end('<!doctype html><title>Desktop isolation fixture</title>'); });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    const { trustedFrame } = await import('../src/ipc-policy.mjs');
    const known = new Set();
    ipcMain.handle('webobs:desktop', (event, operation) => {
      assert.equal(trustedFrame(event, origin, known), true);
      assert.equal(operation, 'status');
      return { runtime: { phase: 'ready' }, fixture: true };
    });
    windows.push(...[1,2].map(() => new BrowserWindow({ show: false, webPreferences: { preload: path.resolve(__dirname, '../src/preload.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false, partition: 'persist:smoke' } })));
    for (const window of windows) { known.add(window.webContents.id); await window.loadURL(origin); }
    const isolation = await windows[0].webContents.executeJavaScript('(async()=>({node:typeof require,process:typeof process,keys:Object.keys(window.webobsDesktop),status:await window.webobsDesktop.status()}))()');
    assert.equal(isolation.node, 'undefined'); assert.equal(isolation.process, 'undefined'); assert.equal(isolation.status.fixture, true);
    for (const key of ['exec','readFile','writeFile','openPath']) assert.equal(isolation.keys.includes(key), false);
    await windows[0].webContents.executeJavaScript('localStorage.setItem("desktop-session-fixture","shared")');
    assert.equal(await windows[1].webContents.executeJavaScript('localStorage.getItem("desktop-session-fixture")'), 'shared');
    const { createTrayIcon } = await import('../src/tray-icon.mjs');
    const icon = createTrayIcon(nativeImage);
    assert.equal(icon.isEmpty(), false, 'tray image must be valid');
    for (const window of windows) window.destroy();
    console.log('Real Electron sandbox, finite IPC, shared session and tray image smoke passed.');
  } catch (error) { console.error(error.stack); exitCode = 1; }
  finally {
    for (const window of windows) if (!window.isDestroyed()) window.destroy();
    server?.close();
    // The random directory is owned by this fixture and stays below the OS temp root.
    if (temporary.startsWith(path.resolve(os.tmpdir()) + path.sep + 'webobs-electron-smoke-')) await fs.rm(temporary, { recursive: true, force: true }).catch(() => {});
  }
  app.exit(exitCode);
})();
