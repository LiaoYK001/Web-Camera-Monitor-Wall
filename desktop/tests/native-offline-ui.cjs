// Exercise the packaged UI, its real libsodium grant and the authenticated v2 proxy.
// The inactive registry fixture does not qualify camera media or physical audio.
const assert = require('node:assert/strict');

async function exerciseNativeOfflineUi(main, origin, headers, waitForUi) {
  const camera = await fetch(`${origin}/api/v1/cameras`, { method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({
      id: 'ui-sync-camera', name: 'Native UI pairing fixture', address: 'rtsp://camera.invalid/live',
      adapter: 'rtsp', credentialsRef: 'ui-sync-camera', hardwareDecode: 'auto', capabilities: {},
      profiles: [{ id: 'sub', name: 'Sub', role: 'sub', endpoint: 'rtsp://camera.invalid/live',
        videoCodec: 'h264', audioCodec: 'aac', width: 640, height: 360, fps: 15, autoProbe: false }],
    }) });
  assert.equal(camera.status, 201);
  const click = text => main.webContents.executeJavaScript(`{
    const button=[...document.querySelectorAll('button')].find(button=>button.textContent===${JSON.stringify(text)} && !button.disabled);
    if (!button) throw new Error('Native UI action unavailable'); button.click();
  }`);
  await main.loadURL(`${origin}/#/settings`);
  main.show(); main.restore(); main.focus();
  await waitForUi('!document.hidden && Boolean(document.querySelector(".device-sync-panel"))');
  await click('配对与授权管理');
  await waitForUi('[...document.querySelectorAll("button")].some(button=>button.textContent==="创建浏览器配对" && !button.disabled)');
  await click('创建浏览器配对');
  await waitForUi('document.querySelector(".browser-pairing strong")?.textContent.startsWith("配对码：")');
  const code = await main.webContents.executeJavaScript('document.querySelector(".browser-pairing strong").textContent.match(/\\d{8}/)[0]');
  const pending = await (await fetch(`${origin}/api/v2/enrollments`, { headers })).json();
  const enrollment = pending.enrollments.find(value => value.name === '本机浏览器' && value.state === 'pending');
  assert.ok(enrollment);
  const approval = await fetch(`${origin}/api/v2/enrollments/${enrollment.id}/approve`, { method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ pairingCode: code,
      cameraGrants: [{ cameraId: 'ui-sync-camera', profileIds: ['sub'], permissions: ['view'], credentialMode: 'none' }] }) });
  assert.equal(approval.status, 200);
  await click('批准后完成配对');
  await waitForUi('document.querySelector(".browser-pairing strong")?.textContent.startsWith("已配对")');
  await waitForUi('document.querySelector(".device-sync-panel").textContent.includes("最近同步")');
  await click('载入设备布局');
  await waitForUi('Boolean(document.querySelector(".device-workspace-banner"))');
  const previous = await (await fetch(`${origin}/api/v1/studio`, { headers })).json();
  await main.webContents.executeJavaScript(`{
    const input=document.querySelector('input[aria-label="场景名称"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Native device layout');
    input.dispatchEvent(new Event('input',{bubbles:true}));
  }`);
  await waitForUi('[...document.querySelectorAll("button")].some(button=>button.textContent==="保存设备布局" && !button.disabled)');
  await click('保存设备布局');
  await waitForUi('document.querySelector(".device-workspace-banner").textContent.includes("无待上传修改") && [...document.querySelectorAll("button")].some(button=>button.textContent==="设备布局已保存")');
  assert.deepEqual(await (await fetch(`${origin}/api/v1/studio`, { headers })).json(), previous);
  await main.webContents.reloadIgnoringCache();
  await waitForUi('document.querySelector("input[aria-label=场景名称]")?.value === "Native device layout"');
  assert.equal(await main.webContents.executeJavaScript('[...document.querySelectorAll("button")].find(button=>button.textContent==="TAKE").disabled'), true);
  await waitForUi('[...document.querySelectorAll("button")].some(button=>button.textContent==="复制到服务器预览" && !button.disabled)');
  await click('复制到服务器预览');
  await waitForUi('document.querySelector(".notice-alert")?.textContent.includes("Program 保持原状")');
  const copied = await (await fetch(`${origin}/api/v1/studio`, { headers })).json();
  assert.equal(copied.programSceneId, previous.programSceneId);
  assert.deepEqual(copied.scenes.find(scene => scene.id === previous.programSceneId), previous.scenes.find(scene => scene.id === previous.programSceneId));
  assert.notEqual(copied.previewSceneId, copied.programSceneId);
}

module.exports = { exerciseNativeOfflineUi };
