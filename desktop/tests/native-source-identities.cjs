// Accepted Scene identifiers must work in the actual native monitor renderer.
const assert = require('node:assert/strict');
const { largeSourceAudioWorkspace } = require('../../tests/fixtures/preference-workspace.cjs');

exports.exerciseNativeSourceIdentities = async (main, origin, headers, waitForUi) => {
  const endpoint = `${origin}/api/v2/account/preferences/monitor-view`;
  const read = async url => {
    const response = await fetch(url, { headers }); assert.equal(response.status, 200);
    return response.json();
  };
  const put = async (url, body, extra = {}) => {
    const response = await fetch(url, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json', ...extra }, body: JSON.stringify(body) });
    assert.equal(response.status, 200);
    return response.json();
  };
  const originalStudio = await read(`${origin}/api/v1/studio`);
  const originalProgram = await read(`${origin}/api/v1/scene`);
  const originalPreferences = (await read(endpoint)).value ?? {};
  const reloadMonitor = async () => {
    await main.loadURL(`${origin}/#monitor`);
    // A fragment navigation may retain App and its preceding preference read.
    // This gate promises an actual document reload and a restored account.
    await new Promise(resolve => {
      main.webContents.once('did-finish-load', resolve);
      main.webContents.reloadIgnoringCache();
    });
    main.show(); main.restore(); main.focus();
  };
  try {
    for (const identity of ['constructor', '__proto__', 'other-scene-999']) {
      const largeAudio = identity === 'other-scene-999' ? largeSourceAudioWorkspace() : null;
      const scene = await read(`${origin}/api/v1/scene`);
      scene.sources = [{ id: identity, kind: 'color', name: 'Native source identity', color: '#214f75',
        muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }];
      scene.items = [{ id: 'native-identity-item', sourceId: identity, x: 0, y: 0,
        width: scene.canvas.width, height: scene.canvas.height, scaleMode: 'contain',
        crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true,
        locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }];
      // Studio TAKE prefixes source identifiers. Use the authenticated Program
      // API to exercise the exact accepted identifiers without changing Preview.
      await put(`${origin}/api/v1/scene`, scene, { 'If-Match': `"${scene.revision}"` });
      const live = await read(`${origin}/api/v1/scene`);
      assert.equal(live.sources[0].id, identity);
      assert.deepEqual(await read(`${origin}/api/v1/studio`), originalStudio);
      await put(endpoint, { value: { ...(largeAudio ?? {}), mode: 'manual', localMonitorVolume: .18,
        sourceDecorations: Object.fromEntries([[identity, { fill: 'contain', telemetry: { enabled: true, fields: ['fps'] } }]]) } });
      await reloadMonitor();
      await waitForUi('!document.hidden && document.querySelectorAll(".direct-tile-position").length === 1 && document.querySelector(".monitor-source-rail").textContent.includes("Native source identity") && document.querySelector("input[aria-label=本地监听主音量]")?.value === "0.18" && !document.querySelector("input[aria-label=本地监听主音量]").closest("fieldset").disabled');
      if (largeAudio) await waitForUi(`document.querySelector('input[aria-label="Native source identity 音量"]')?.value === '0.27' && document.querySelector('button[aria-label="Native source identity 静音"]')?.getAttribute('aria-pressed') === 'false' && document.querySelector('button[aria-label="Native source identity 本地监听"]')?.getAttribute('aria-pressed') === 'false'`);
      await main.webContents.executeJavaScript(`{
        const originalFetch = window.fetch;
        window.nativeIdentityReads = 0;
        window.fetch = (input, init) => {
          if (String(input).endsWith('/account/preferences/monitor-view') && init?.method !== 'PUT') window.nativeIdentityReads++;
          return originalFetch(input, init);
        };
        const input = document.querySelector('input[aria-label="本地监听主音量"]');
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '.22');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }`);
      // A hook focus refresh only starts after its save and encrypted pending
      // cache have settled. Do not stage another full fixture during that save.
      await waitForUi('window.dispatchEvent(new Event("focus")); window.nativeIdentityReads > 0');
      assert.equal((await read(endpoint)).value.localMonitorVolume, .22);
      await reloadMonitor();
      await waitForUi('document.querySelector("input[aria-label=本地监听主音量]")?.value === "0.22" && document.querySelectorAll(".direct-tile-position").length === 1');
      const saved = (await read(endpoint)).value;
      assert.ok(Object.hasOwn(saved.sourceDecorations, identity));
      assert.equal(saved.sourceDecorations[identity].fill, 'contain');
      assert.deepEqual(saved.sourceDecorations[identity].telemetry.fields, ['fps']);
      if (largeAudio) {
        assert.deepEqual(saved.sourceAudio, largeAudio.sourceAudio);
        await waitForUi(`document.querySelector('input[aria-label="Native source identity 音量"]')?.value === '0.27'`);
      }
    }
    console.log('Actual native source identifiers constructor/__proto__: accepted Scene, monitor rendering and preference save/reload retain own decorations. Synthetic color source, not camera qualification.');
    console.log('Actual native 1000-source audio account: last source volume/mute/monitor restored before and after master-volume save/reload; all source controls retained. Color source controls remain disabled; no physical audio qualification.');
  } finally {
    const current = await read(`${origin}/api/v1/scene`);
    await put(`${origin}/api/v1/scene`, { ...originalProgram, revision: current.revision }, { 'If-Match': `"${current.revision}"` });
    assert.deepEqual(await read(`${origin}/api/v1/studio`), originalStudio);
    await put(endpoint, { value: originalPreferences });
    await main.loadURL(`${origin}/#settings`);
  }
};
