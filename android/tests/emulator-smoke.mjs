import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../../web/package.json', import.meta.url));
const { _android, expect } = require('@playwright/test');
const { largeSourceAudioWorkspace } = require('../tests/fixtures/preference-workspace.cjs');
const pkg = 'io.github.liaoyk001.webobs.android';
const serial = process.env.WEBOBS_ANDROID_SERIAL, base = process.env.WEBOBS_ANDROID_ORIGIN;
assert(serial && base && process.env.WEBOBS_ANDROID_PASSWORD, 'Run through test_emulator.py');
const output = new URL('../../tests/artifacts/android/', import.meta.url);
await mkdir(output, { recursive: true });
const adb = (...args) => execFileSync(process.env.WEBOBS_ANDROID_ADB, ['-s', serial, ...args], { timeout: 30000, stdio: 'pipe' });
const devices = await _android.devices();
const device = devices.find(value => value.serial() === serial);
assert(device, 'Explicit device is not online');
// Some emulators expose two ADB serials for the same device. Closing the alias
// before the probe can stop the shared Playwright driver on the selected serial.
device.setDefaultTimeout(25000);
const checks = [];
const browsers = new Set();
const initialRotation = adb('shell', 'settings', 'get', 'system', 'user_rotation').toString().trim();
const initialAutoRotation = adb('shell', 'settings', 'get', 'system', 'accelerometer_rotation').toString().trim();
const initialRotationMode = adb('shell', 'wm', 'user-rotation').toString().trim();
assert(/^(free|lock(?: [0-3])?)$/.test(initialRotationMode), 'Unrecognized window-manager rotation mode');
const tapNative = async selector => {
  if (selector.res === `${pkg}:id/app_menu`) { adb('shell', 'input', 'keyevent', 'KEYCODE_MENU'); return; }
  const { bounds } = await device.info(selector);
  // Use ADB input for MuMu's native edge toolbar; UiAutomator click can return
  // before MuMu delivers a touch at that edge. Bounds still come from the UI.
  adb('shell', 'input', 'tap', String(Math.round(bounds.x + bounds.width / 2)), String(Math.round(bounds.y + bounds.height / 2)));
};
try {
  adb('shell', 'am', 'force-stop', pkg);
  adb('shell', 'am', 'start', '-W', '-n', `${pkg}/.MainActivity`);
  // Connection may already be stored from a previous run; switch via the native menu.
  if (!await device.info({ res: `${pkg}:id/server_address` }).catch(() => null)) {
    await tapNative({ res: `${pkg}:id/app_menu` });
    await device.wait({ text: '客户端菜单' });
    await tapNative({ text: /连接.*切换服务器/ });
  }
  await device.fill({ res: `${pkg}:id/server_address` }, base);
  await tapNative({ res: `${pkg}:id/connect_server` });
  let page = await (await device.webView({ pkg })).page();
  browsers.add(page.context().browser());
  page.setDefaultTimeout(25000);
  await page.getByLabel('用户名', { exact: true }).fill('android-admin');
  await page.getByLabel('密码', { exact: true }).fill(process.env.WEBOBS_ANDROID_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.getByRole('button', { name: '退出登录', exact: true }).waitFor();
  checks.push('native connection + real backend login');
  console.log('PASS: actual Android login');
  await page.goto(`${base}/#monitor`);
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.37');
  await page.locator('.hero-audio-control').getByRole('combobox', { name: '声音输出模式' }).selectOption('meter-only');
  await expect.poll(() => page.evaluate(async () => (await (await fetch('/api/v2/account/preferences/monitor-view')).json()).value?.localMonitorVolume)).toBe(.37);
  checks.push('actual account audio volume and output preferences');
  const previous = await page.evaluate(async () => ({ program: await (await fetch('/api/v1/scene')).json(),
    preferences: (await (await fetch('/api/v2/account/preferences/monitor-view')).json()).value }));
  const audioWorkspace = { ...previous.preferences, ...largeSourceAudioWorkspace() };
  const accepted = await page.evaluate(async ({ previous, audioWorkspace }) => {
    const program = { ...previous.program,
      sources: [{ id: 'other-scene-999', kind: 'color', name: 'Audio preference check', color: '#214f75',
        muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }],
      items: [{ id: 'audio-preference-tile', sourceId: 'other-scene-999', x: 0, y: 0,
        width: previous.program.canvas.width, height: previous.program.canvas.height, scaleMode: 'contain',
        crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true,
        locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }] };
    const saved = await fetch('/api/v1/scene', { method: 'PUT', headers: { 'Content-Type': 'application/json',
      'If-Match': `"${program.revision}"` }, body: JSON.stringify(program) });
    const preferences = await fetch('/api/v2/account/preferences/monitor-view', { method: 'PUT',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: audioWorkspace }) });
    return [saved.status, preferences.status];
  }, { previous, audioWorkspace });
  assert.deepEqual(accepted, [200, 200]);
  await page.reload();
  const audioChannel = page.locator('.audio-mixer-channel[data-source-id="other-scene-999"]');
  await expect(audioChannel.getByRole('slider', { name: 'Audio preference check 音量' })).toHaveValue('0.27');
  await expect(audioChannel.getByRole('button', { name: 'Audio preference check 静音', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(audioChannel.getByRole('button', { name: 'Audio preference check 本地监听', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.41');
  await page.reload();
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.41');
  await expect(audioChannel.getByRole('slider', { name: 'Audio preference check 音量' })).toHaveValue('0.27');
  assert.deepEqual(await page.evaluate(async () => (await (await fetch('/api/v2/account/preferences/monitor-view')).json()).value.sourceAudio), audioWorkspace.sourceAudio);
  const restored = await page.evaluate(async previous => {
    const current = await (await fetch('/api/v1/scene')).json();
    const program = await fetch('/api/v1/scene', { method: 'PUT', headers: { 'Content-Type': 'application/json',
      'If-Match': `"${current.revision}"` }, body: JSON.stringify({ ...previous.program, revision: current.revision }) });
    const preferences = await fetch('/api/v2/account/preferences/monitor-view', { method: 'PUT',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: previous.preferences }) });
    return [program.status, preferences.status];
  }, previous);
  assert.deepEqual(restored, [200, 200]);
  checks.push('actual Android late-source audio controls from a 1000-source account survive master save/reload; isolated synthetic color, not audio hardware qualification');
  if (process.env.WEBOBS_ANDROID_STUDIO_IDENTITIES === '1') {
    // Older WebView CDP lacks Storage.getCookies. Use its actual same-origin
    // fetch and HttpOnly session instead of extracting or replacing cookies.
    const request = async (url, init) => {
      const result = await page.evaluate(async ({ url, init }) => {
        const response = await fetch(url, init);
        return { status: response.status, body: await response.json() };
      }, { url, init });
      return { status: result.status, json: async () => result.body };
    };
    const finishIdentity = await require('../desktop/tests/native-studio-identity.cjs').exerciseStudioIdentity(base, {}, async (program, controls) => {
      await page.goto(`${base}/#monitor`); await page.reload();
      await expect(page.getByRole('slider', { name: '本地监听主音量', exact: true })).toHaveValue('0.18');
      await expect(page.locator('.direct-tile-position')).toHaveCount(program.items.length);
      for (const [name, control] of Object.entries(controls)) {
        await expect(page.getByRole('slider', { name: `${name} 音量`, exact: true })).toHaveValue(String(control.volume));
        await expect(page.getByRole('button', { name: `${name} 静音`, exact: true })).toHaveAttribute('aria-pressed', String(control.muted));
        await expect(page.getByRole('button', { name: `${name} 本地监听`, exact: true })).toHaveAttribute('aria-pressed', String(control.monitor));
      }
    }, request);
    await finishIdentity();
    // The helper restores Studio through the real API. Refresh its metadata
    // revision before the following editor save; a fragment keeps the old draft.
    await page.reload();
    checks.push('actual installed WebView: UUID TAKE/layer/Scene/nested identities preserve source audio controls on reload; synthetic color, not audio hardware qualification');
  }
  await page.goto(`${base}/#studio`);
  await page.getByRole('button', { name: '新建场景', exact: true }).click();
  const sceneDialog = page.getByRole('dialog', { name: '新建场景', exact: true });
  await sceneDialog.getByLabel('场景名称').fill('安卓值守');
  await sceneDialog.getByRole('button', { name: '应用到草稿' }).click();
  await page.getByRole('button', { name: '保存并应用', exact: true }).click();
  await expect.poll(() => page.evaluate(async () => (await (await fetch('/api/v1/studio')).json()).scenes.some(scene => scene.name === '安卓值守'))).toBe(true);
  checks.push('native WebUI scene creation saved in actual backend');
  await page.getByRole('button', { name: '安卓值守 场景选项', exact: true }).click();
  const sceneOptions = page.getByRole('dialog', { name: '安卓值守 场景选项', exact: true });
  await sceneOptions.getByRole('menuitem', { name: '打开场景投影 · 新窗口', exact: true }).click();
  // Android transfers the temporary popup target into its native WebView.
  // Inspect the resulting live target rather than the transient about:blank page.
  await expect.poll(() => page.context().pages().filter(candidate => !candidate.isClosed() && candidate.url().includes('#projector')).length, { timeout: 25000 }).toBe(1);
  const child = page.context().pages().find(candidate => !candidate.isClosed() && candidate.url().includes('#projector'));
  await child.locator('.projector-shell').waitFor();
  await expect(child.locator('.login-screen')).toHaveCount(0);
  checks.push('actual native projector dialog shares the authenticated session');
  await tapNative({ text: '关闭投影 / 子窗口' });
  adb('shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0');
  adb('shell', 'settings', 'put', 'system', 'user_rotation', '0');
  // MuMu may retain a free-rotation WindowManager override despite settings writes.
  // Set the actual display rotation and restore its original mode during cleanup.
  adb('shell', 'wm', 'user-rotation', 'lock', '0');
  await expect.poll(() => page.evaluate(() => matchMedia('(orientation: portrait)').matches), { timeout: 10000 }).toBe(true);
  // Capture the actual Android surface. Older WebView CDP screenshot targets
  // can stall after a display rotation while the live page remains responsive.
  await writeFile(new URL('portrait.png', output), adb('exec-out', 'screencap', '-p'));
  adb('shell', 'settings', 'put', 'system', 'user_rotation', '1');
  adb('shell', 'wm', 'user-rotation', 'lock', '1');
  await expect.poll(() => page.evaluate(() => matchMedia('(orientation: landscape)').matches), { timeout: 10000 }).toBe(true);
  checks.push('portrait/landscape rotation without losing the session or scene');
  await page.goto(`${base}/#settings`);
  const optimization = page.getByRole('checkbox', { name: '自动优化视频播放（默认开启）', exact: true });
  await expect(optimization).toBeChecked();
  await optimization.uncheck();
  await expect.poll(() => page.evaluate(async () => (await (await fetch('/api/v2/account/preferences/monitor-view')).json()).value?.playbackOptimization?.enabled)).toBe(false);
  await page.reload(); await expect(optimization).not.toBeChecked();
  checks.push('account optimization preference persisted after reload');
  await page.goto(`${base}/#account`);
  await page.getByRole('textbox', { name: '昵称', exact: true }).fill('安卓设置细节验证');
  await page.getByRole('button', { name: '保存个人信息', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存个人信息', exact: true })).toBeDisabled();
  await expect.poll(() => page.evaluate(async () => (await (await fetch('/api/v2/account/me')).json()).displayName)).toBe('安卓设置细节验证');
  await expect(page.getByLabel('确认新密码', { exact: true })).toBeVisible();
  checks.push('actual account editor save and password confirmation UI');
  await page.goto(`${base}/#go2rtc`);
  await page.getByRole('heading', { name: 'go2rtc 管理' }).waitFor();
  await page.getByRole('button', { name: '配置', exact: true }).click();
  await page.frameLocator('iframe[title="go2rtc 官方 WebUI"]').locator('.monaco-editor').waitFor();
  checks.push('authenticated official go2rtc UI + local Monaco');
  console.log('PASS: preferences and actual go2rtc editor');
  if (process.env.WEBOBS_ANDROID_ONLINE_SOURCES === '1') {
    await require('../tests/online_source_webui.cjs').exerciseOnlineSources(page, base);
    checks.push('actual installed Android WebView: yt-dlp/Streamlink website source creation, authenticated synthetic MSE frame decoding and device import; backend extraction, not external-site qualification');
  }
  await page.goto(`${base}/api/v1/go2rtc/stream.html?src=synthetic&mode=mse`);
  // WebView requires a user gesture. The source is real FFmpeg/go2rtc MSE, never mocked.
  await page.locator('video').click();
  await page.locator('video').evaluate(video => { video.muted = true; return video.play(); });
  await page.waitForFunction(() => { const v = document.querySelector('video'); return v?.readyState >= 2 && v.videoWidth === 160; }, null, { timeout: 30000 });
  const start = await page.locator('video').evaluate(video => video.currentTime);
  await expect.poll(() => page.locator('video').evaluate(video => video.currentTime), { timeout: 15000 }).toBeGreaterThan(start + .25);
  checks.push('actual Android WebView decoded live H.264 MSE frames');
  console.log('PASS: actual live H.264 frame playback');
  await writeFile(new URL('mse.png', output), adb('exec-out', 'screencap', '-p'));
  // Playwright enables focus emulation by default, which masks real Page
  // Visibility changes even in an Android WebView. Disable it for this check.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: false });
  adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
  await expect.poll(() => page.evaluate(() => window.webobsAndroidForeground)).toBe(false);
  await expect.poll(() => page.locator('video').evaluate(video => video.paused)).toBe(true);
  adb('shell', 'am', 'start', '-W', '-n', `${pkg}/.MainActivity`);
  await expect.poll(() => page.evaluate(() => window.webobsAndroidForeground)).toBe(true);
  checks.push('actual HOME/resume native lifecycle signal + background video pause');
  await page.goto(`${base}/#archive`);
  const archiveVideo = page.locator('.archive-player video');
  await expect(page.getByRole('slider', { name: '归档监听主音量', exact: true })).toHaveValue('0.37');
  await expect(page.getByRole('combobox', { name: '归档声音输出', exact: true })).toHaveValue('meter-only');
  await expect(page.getByRole('checkbox', { name: 'android-archive', exact: true })).toBeChecked();
  await page.waitForFunction(() => document.querySelector('.archive-player video')?.readyState >= 2);
  await expect.poll(() => archiveVideo.evaluate(video => video.muted && video.volume === .37)).toBe(true);
  await page.getByRole('button', { name: '播放', exact: true }).click();
  await page.waitForFunction(() => { const video = document.querySelector('.archive-player video'); return video?.videoWidth === 160 && !video.paused && video.currentTime > .25; });
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await expect.poll(() => archiveVideo.evaluate(video => video.paused)).toBe(true);
  await page.getByRole('checkbox', { name: '启用声音监听', exact: true }).check();
  await page.getByRole('combobox', { name: '归档声音输出', exact: true }).selectOption('speaker');
  await page.getByRole('slider', { name: '归档监听主音量', exact: true }).fill('0.22');
  await page.getByRole('combobox', { name: '归档声音摄像机', exact: true }).selectOption('android-archive');
  await expect.poll(() => page.evaluate(async () => (await (await fetch('/api/v2/account/preferences/monitor-view')).json()).value)).toMatchObject({
    audioMonitorEnabled: true, audioOutput: 'speaker', localMonitorVolume: .22, archiveAudioCameraId: 'android-archive' });
  await expect.poll(() => archiveVideo.evaluate(video => !video.muted && video.volume === .22)).toBe(true);
  await page.reload();
  await expect(page.getByRole('slider', { name: '归档监听主音量', exact: true })).toHaveValue('0.22');
  await expect(page.getByRole('combobox', { name: '归档声音摄像机', exact: true })).toHaveValue('android-archive');
  await page.getByRole('slider', { name: '归档监听主音量', exact: true }).fill('0.37');
  await page.getByRole('combobox', { name: '归档声音输出', exact: true }).selectOption('meter-only');
  await page.getByRole('checkbox', { name: '启用声音监听', exact: true }).uncheck();
  await expect.poll(() => archiveVideo.evaluate(video => video.muted && video.volume === .37)).toBe(true);
  checks.push('archive audio shares real account volume/output, persists fixed camera/reload and obeys mute');
  await page.getByRole('button', { name: '播放', exact: true }).click();
  await expect.poll(() => archiveVideo.evaluate(video => !video.paused && video.currentTime > .2)).toBe(true);
  adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
  await expect.poll(() => page.evaluate(() => window.webobsAndroidForeground)).toBe(false);
  await expect.poll(() => archiveVideo.evaluate(video => video.paused)).toBe(true);
  await expect(page.getByRole('button', { name: '播放', exact: true })).toBeVisible();
  adb('shell', 'am', 'start', '-W', '-n', `${pkg}/.MainActivity`);
  await expect.poll(() => page.evaluate(() => window.webobsAndroidForeground)).toBe(true);
  await expect(page.getByRole('button', { name: '播放', exact: true })).toBeVisible();
  checks.push('actual archive HOME/resume pauses UI and keeps playback paused until a deliberate click');
  await page.waitForFunction(() => document.querySelector('.archive-thumb')?.naturalWidth > 0);
  await page.getByRole('button', { name: '截图', exact: true }).click();
  const snapshot = page.getByRole('link', { name: '下载最近截图', exact: true });
  await snapshot.waitFor();
  const snapshotDigest = await page.evaluate(async () => {
    const link = document.querySelector('.nvr-content > .export-result a');
    const response = await fetch(link.getAttribute('href'));
    if (!response.ok) throw new Error('Authenticated snapshot download failed');
    const hash = await crypto.subtle.digest('SHA-256', await response.arrayBuffer());
    return [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join('');
  });
  await expect(page.locator('.nvr-content > .export-result span')).toContainText(snapshotDigest);
  const currentDay = await page.getByLabel('UTC 日期').inputValue();
  const previousDay = new Date(Date.parse(`${currentDay}T00:00:00Z`) - 86400000).toISOString().slice(0, 10);
  await page.getByLabel('UTC 日期').fill(previousDay);
  await expect(archiveVideo).toHaveCount(0);
  await expect(page.getByRole('button', { name: '截图', exact: true })).toBeDisabled();
  await page.getByLabel('UTC 日期').fill(currentDay);
  await expect(archiveVideo).toHaveCount(1);
  checks.push('actual H.264/AAC NVR playback, thumbnail, owner snapshot/hash and date-switch cleanup');
  console.log('PASS: actual Android archive playback and snapshot authorization');
  await page.goto(`${base}/#settings`);
  const diagnostics = page.getByRole('region', { name: '开发者诊断', exact: true });
  await diagnostics.getByRole('checkbox').check();
  await expect(diagnostics.getByRole('heading', { name: /场景同步正常/ })).toBeVisible();
  const oldAttempts = await diagnostics.locator('pre').evaluate(element => JSON.parse(element.textContent).connections[0].attempts);
  await diagnostics.getByRole('button', { name: '重新连接场景同步', exact: true }).click();
  await expect.poll(() => diagnostics.locator('pre').evaluate(element => {
    const state = JSON.parse(element.textContent).connections[0]; return state.phase === 'online' ? state.attempts : 0;
  })).toBeGreaterThan(oldAttempts);
  checks.push('actual authenticated scene delivery, opt-in diagnostics and manual control reconnect');
  await tapNative({ res: `${pkg}:id/app_menu` });
  await device.wait({ text: '客户端菜单' });
  await tapNative({ text: '关于与检查更新' });
  await device.wait({ text: /WebOBS Android · 3\.5\.0-dev\.android\.1[\s\S]*/ });
  checks.push('native About version and GitHub links');
  adb('shell', 'input', 'keyevent', 'KEYCODE_BACK');
  // Flush happens on pause, then test a real process restart without clearing app data.
  adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
  adb('shell', 'am', 'force-stop', pkg);
  adb('shell', 'am', 'start', '-W', '-n', `${pkg}/.MainActivity`);
  const newPid = Number(adb('shell', 'pidof', pkg).toString().trim());
  await expect.poll(() => device.webViews().some(view => view.pkg() === pkg && view.pid() === newPid), { timeout: 25000 }).toBe(true);
  page = await (await device.webView({ pkg, socketName: `webview_devtools_remote_${newPid}` })).page();
  browsers.add(page.context().browser());
  page.setDefaultTimeout(25000);
  await page.getByRole('button', { name: '退出登录', exact: true }).waitFor();
  await page.goto(`${base}/#settings`);
  await expect(page.getByRole('checkbox', { name: '自动优化视频播放（默认开启）', exact: true })).not.toBeChecked();
  await page.goto(`${base}/#monitor`);
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.37');
  await expect(page.locator('.hero-audio-control').getByRole('combobox', { name: '声音输出模式' })).toHaveValue('meter-only');
  await page.goto(`${base}/#studio`);
  await expect(page.getByRole('button', { name: '选择场景 安卓值守', exact: true })).toBeVisible();
  await page.goto(`${base}/#account`);
  await expect(page.getByRole('textbox', { name: '昵称', exact: true })).toHaveValue('安卓设置细节验证');
  checks.push('saved server, HttpOnly login session and account preference after process restart');
  await writeFile(new URL('receipt.json', output), JSON.stringify({ device: device.model(), sdk: adb('shell', 'getprop', 'ro.build.version.sdk').toString().trim(), checks, qualification: 'MuMu emulator and synthetic FFmpeg source; not physical camera/ARM qualification' }, null, 2));
  console.log(`PASS: ${checks.join('; ')}`);
} finally {
  for (const [key, value] of [['user_rotation', initialRotation], ['accelerometer_rotation', initialAutoRotation]]) {
    adb('shell', 'settings', value === 'null' ? 'delete' : 'put', 'system', key, ...(value === 'null' ? [] : [value]));
  }
  adb('shell', 'wm', 'user-rotation', ...initialRotationMode.split(' '));
  // Return to connection selection; do not leave a dead test endpoint on screen.
  await tapNative({ res: `${pkg}:id/app_menu` }).catch(() => {});
  await device.wait({ text: '客户端菜单' }).catch(() => {});
  await tapNative({ text: /连接.*切换服务器/ }).catch(() => {});
  await device.fill({ res: `${pkg}:id/server_address` }, '').catch(() => {});
  console.log('Cleaning up Android inspection connections');
  for (const browser of browsers) await browser?.close().catch(() => {});
  console.log('Inspection browsers disconnected');
  await device.close();
  console.log('Selected Android driver closed');
  for (const other of devices) if (other !== device) await other.close();
  console.log('Android aliases closed');
}
// Android's experimental transport can keep ADB polling handles alive after
// all owned browser/driver connections close. Assertions and cleanup are done.
process.exit(0);
