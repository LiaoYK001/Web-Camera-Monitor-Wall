// Accepted Scene identifiers must work in the actual native monitor renderer.
const assert = require('node:assert/strict');

exports.exerciseNativeSourceIdentities = async (main, origin, headers, waitForUi) => {
  const endpoint = `${origin}/api/v2/account/preferences/monitor-view`;
  const read = async url => {
    const response = await fetch(url, { headers }); assert.equal(response.status, 200);
    return response.json();
  };
  const put = async (url, body, extra = {}) => {
    const response = await fetch(url, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json', ...extra }, body: JSON.stringify(body) });
    assert.equal(response.status, 200);
  };
  const originalStudio = await read(`${origin}/api/v1/studio`);
  const originalPreferences = (await read(endpoint)).value ?? {};
  try {
    for (const identity of ['constructor', '__proto__']) {
      const studio = await read(`${origin}/api/v1/studio`);
      const scene = studio.scenes.find(value => value.id === studio.previewSceneId);
      scene.sources = [{ id: identity, kind: 'color', name: 'Native source identity', color: '#214f75',
        muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }];
      scene.items = [{ id: 'native-identity-item', sourceId: identity, x: 0, y: 0,
        width: scene.canvas.width, height: scene.canvas.height, scaleMode: 'contain',
        crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true,
        locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }];
      await put(`${origin}/api/v1/studio`, studio, { 'If-Match': `"${studio.revision}"` });
      await put(endpoint, { value: { mode: 'manual', localMonitorVolume: .18,
        sourceDecorations: Object.fromEntries([[identity, { fill: 'contain', telemetry: { enabled: true, fields: ['fps'] } }]]) } });
      await main.loadURL(`${origin}/#monitor`);
      await waitForUi('document.querySelectorAll(".direct-tile-position").length === 1 && document.querySelector(".monitor-source-rail").textContent.includes("Native source identity") && !document.querySelector("input[aria-label=本地监听主音量]").closest("fieldset").disabled');
      await main.webContents.executeJavaScript(`{
        const input = document.querySelector('input[aria-label="本地监听主音量"]');
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '.22');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }`);
      await waitForUi('fetch("/api/v2/account/preferences/monitor-view").then(response=>response.json()).then(result=>result.value.localMonitorVolume === .22)');
      await main.loadURL(`${origin}/#monitor`);
      await waitForUi('document.querySelector("input[aria-label=本地监听主音量]")?.value === "0.22" && document.querySelectorAll(".direct-tile-position").length === 1');
      const saved = (await read(endpoint)).value;
      assert.ok(Object.hasOwn(saved.sourceDecorations, identity));
      assert.equal(saved.sourceDecorations[identity].fill, 'contain');
      assert.deepEqual(saved.sourceDecorations[identity].telemetry.fields, ['fps']);
    }
    console.log('Actual native source identifiers constructor/__proto__: accepted Scene, monitor rendering and preference save/reload retain own decorations. Synthetic color source, not camera qualification.');
  } finally {
    const current = await read(`${origin}/api/v1/studio`);
    await put(`${origin}/api/v1/studio`, { ...originalStudio, revision: current.revision }, { 'If-Match': `"${current.revision}"` });
    await put(endpoint, { value: originalPreferences });
    await main.loadURL(`${origin}/#settings`);
  }
};
