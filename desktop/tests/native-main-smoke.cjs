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
    assert.equal(state.app.version, app.getVersion());
    assert.equal(state.app.architecture, 'x64');
    assert.equal(state.app.platform, 'win32');
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
    const waitForUi = async (predicate) => {
      const deadline = Date.now() + 15000;
      while (Date.now() < deadline) {
        if (await main.webContents.executeJavaScript(predicate)) return;
        await pause(100);
      }
      const summary = await main.webContents.executeJavaScript(`({
        account: Boolean(document.querySelector('.account-workspace')),
        desktop: Boolean(document.querySelector('.desktop-settings')),
        login: Boolean(document.querySelector('input[autocomplete=current-password]')),
        forms: document.forms.length,
        alerts: document.querySelectorAll('[role=alert]').length,
        scripts: document.scripts.length,
        bodyChildren: document.body.children.length,
        inputKinds: [...document.querySelectorAll('input')].map(input=>({type:input.type,autocomplete:input.autocomplete})),
        title: document.querySelector('h1')?.textContent,
        control: document.querySelector('.control-diagnostics pre') ? JSON.parse(document.querySelector('.control-diagnostics pre').textContent).connections : null,
        visible: !document.hidden
      })`);
      const auth = await main.webContents.executeJavaScript('fetch("/api/v1/auth/session").then(async response=>({status:response.status,authenticated:(await response.json()).authenticated}))');
      summary.auth = auth;
      summary.profile = await main.webContents.executeJavaScript('({busy:document.querySelector(".config-profile-controls")?.disabled, notices:[...document.querySelectorAll(".config-profile-panel [role=status],.config-profile-panel [role=alert]")].map(element=>element.textContent)})');
      summary.sceneShape = await main.webContents.executeJavaScript('fetch("/api/v1/scene").then(response=>response.json()).then(scene=>({schemaVersion:scene.schemaVersion,revision:scene.revision,idValid:typeof scene.id==="string"&&/^[A-Za-z0-9._-]{1,64}$/.test(scene.id),nameLength:scene.name?.length,canvas:scene.canvas,sources:scene.sources?.map(source=>({kind:source.kind,filters:Array.isArray(source.filters)})),items:scene.items?.map(item=>({sourceId:typeof item.sourceId,crop:Boolean(item.crop)}))}))');
      throw new Error('Desktop settings UI did not reach the expected state: ' + JSON.stringify(summary));
    };
    // Cookie injection does not update LoginGate's initial unauthenticated
    // state. Reload the document after fragment navigation to check the session.
    await main.loadURL(`${origin}/#account`);
    await new Promise(resolve => {
      main.webContents.once('did-finish-load', resolve);
      main.webContents.reloadIgnoringCache();
    });
    await waitForUi('Boolean(document.querySelector("form[aria-label=个人信息] input[maxlength]"))');
    await main.webContents.executeJavaScript(`{
      const input=document.querySelector('form[aria-label="个人信息"] input[maxlength]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Desktop account details');
      input.dispatchEvent(new Event('input',{bubbles:true}));
    }`);
    await waitForUi('!document.querySelector("form[aria-label=个人信息] button[type=submit]").disabled');
    await main.webContents.executeJavaScript('document.querySelector("form[aria-label=个人信息]").requestSubmit()');
    await waitForUi('document.querySelector("form[aria-label=个人信息] button[type=submit]").disabled && document.querySelector(".account-workspace").textContent.includes("个人信息已保存")');
    assert.equal((await (await fetch(`${origin}/api/v2/account/me`, { headers })).json()).displayName, 'Desktop account details');
    await main.loadURL(`${origin}/#settings`);
    await waitForUi('Boolean(document.querySelector(".desktop-port-editor input"))');
    await main.webContents.executeJavaScript(`{
      const input=document.querySelector('.desktop-port-editor input');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'21443');
      input.dispatchEvent(new Event('input',{bubbles:true}));
    }`);
    await waitForUi('!document.querySelector(".desktop-port-editor button[type=submit]").disabled');
    await main.webContents.executeJavaScript('document.querySelector(".desktop-port-editor").requestSubmit()');
    await waitForUi('document.querySelector(".desktop-port-editor button[type=submit]").disabled && document.querySelector(".desktop-settings").textContent.includes("端口已保存")');
    assert.equal((await main.webContents.executeJavaScript('window.webobsDesktop.status()')).settings.lanPort, 21443);
    const savedDesktop = JSON.parse(await fs.readFile(path.join(temporary, 'WebOBS', 'desktop.json'), 'utf8'));
    assert.equal(savedDesktop.lanPort, 21443);
    // The native confirmation is canceled by this fixture. A desktop operation
    // must not flag itself as an unfinished export and reject its own request.
    await main.webContents.executeJavaScript("[...document.querySelectorAll('.desktop-settings button')].find(button=>button.textContent==='应用并重启服务').click()");
    await waitForUi('document.querySelector(".desktop-settings").textContent.includes("服务状态已刷新")');
    assert.equal(await main.webContents.executeJavaScript('Boolean(document.querySelector(".desktop-settings [role=alert]"))'), false);
    // Windows may mark a window covered by the emulator as hidden. Exercise
    // actual foreground resume instead of faking Page Visibility for this gate.
    main.show(); main.restore(); main.focus();
    await waitForUi('!document.hidden');
    await main.webContents.executeJavaScript("document.querySelector('.developer-diagnostics input[type=checkbox]').click()");
    await waitForUi('document.querySelector(".control-diagnostics h3")?.textContent.includes("场景同步正常")');
    const controlStatus = () => main.webContents.executeJavaScript('JSON.parse(document.querySelector(".control-diagnostics pre").textContent).connections[0]');
    const firstControl = await controlStatus();
    assert.ok(firstControl.messages > 0);
    await main.webContents.executeJavaScript("[...document.querySelectorAll('.control-diagnostics button')].find(button=>button.textContent==='重新连接场景同步').click()");
    await waitForUi('JSON.parse(document.querySelector(".control-diagnostics pre").textContent).connections[0].phase === "online" && JSON.parse(document.querySelector(".control-diagnostics pre").textContent).connections[0].attempts > ' + firstControl.attempts);
    const diagnosticText = await main.webContents.executeJavaScript('document.querySelector(".control-diagnostics pre").textContent');
    assert.equal(diagnosticText.includes(origin), false);
    assert.equal(diagnosticText.includes(credentials.username), false);
    await waitForUi('[...document.querySelectorAll(".config-profile-panel button")].some(button => button.textContent === "保存当前配置" && !button.disabled)');
    await main.webContents.executeJavaScript("[...document.querySelectorAll('.config-profile-panel button')].find(button=>button.textContent==='保存当前配置').click()");
    await waitForUi('document.querySelector(".config-profile-panel").textContent.includes("已保存")');
    const savedProfile = await (await fetch(`${origin}/api/v2/account/preferences/config-profiles`, { headers })).json();
    assert.equal(savedProfile.value.profiles[0].studio.scenes[0].schemaVersion, 6);
    await main.webContents.executeJavaScript(`{
      const select=document.querySelector('.config-profile-panel select');
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,'');
      select.dispatchEvent(new Event('change',{bubbles:true}));
    }`);
    await waitForUi('document.querySelector(".config-profile-panel select").value === "" && !document.querySelector(".config-profile-controls").disabled');
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
    console.log('Actual desktop entry: first login, account UI save, port UI persistence, canceled native restart, authenticated scene synchronization and manual reconnect diagnostics, two fixed Scene projectors, shared session, tray hide and normal exit passed. Camera and clean-install qualification remain separate.');
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
