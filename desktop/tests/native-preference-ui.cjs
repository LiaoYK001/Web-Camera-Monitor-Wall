// Actual renderer requests against the complete native runtime. No API mocks.
const assert = require('node:assert/strict');
const { largePreferenceWorkspace } = require('../../tests/fixtures/preference-workspace.cjs');

exports.exerciseNativePreferenceUi = async (main, origin, headers, waitForUi) => {
  const endpoint = `${origin}/api/v2/account/preferences/monitor-view`;
  const read = async () => (await (await fetch(endpoint, { headers })).json()).value;
  const before = await read() ?? {};
  const save = async value => {
    assert.equal((await fetch(endpoint, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }) })).status, 200);
  };
  try {
    const large = largePreferenceWorkspace();
    const fullPairBytes = Buffer.byteLength(JSON.stringify({ baseValue: large, value: { ...large, localMonitorVolume: .31 } }));
    assert.ok(fullPairBytes > 1024 * 1024);
    await save(large);
    await main.loadURL(`${origin}/#monitor`);
    main.show(); main.restore(); main.focus();
    await waitForUi('!document.hidden && Boolean(document.querySelector("input[aria-label=本地监听主音量]")) && !document.querySelector("input[aria-label=本地监听主音量]").closest("fieldset").disabled');
    await main.webContents.executeJavaScript(`{
      const original = window.fetch; window.preferenceWireTest = { writes: [], reads: 0 };
      window.fetch = (input, init) => {
        if (String(input).endsWith('/account/preferences/monitor-view')) {
          if (init?.method === 'PUT') window.preferenceWireTest.writes.push({ bytes: new TextEncoder().encode(String(init.body)).byteLength, keepalive: init.keepalive });
          else window.preferenceWireTest.reads++;
        }
        return original(input, init);
      };
      const input = document.querySelector('input[aria-label="本地监听主音量"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '.31');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }`);
    await waitForUi('window.preferenceWireTest.writes.length > 0');
    // A focus refresh starts only after the hook has acknowledged the save and
    // completed its private pending cache. Do not restore while a save is live.
    for (let attempt = 0; attempt < 100; attempt++) {
      await main.webContents.executeJavaScript("window.dispatchEvent(new Event('focus'))");
      if (await main.webContents.executeJavaScript('window.preferenceWireTest.reads > 0')) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(await main.webContents.executeJavaScript('window.preferenceWireTest.reads > 0'));
    const saved = await read();
    assert.equal(saved.localMonitorVolume, .31);
    assert.deepEqual(saved.sourceDecorations, large.sourceDecorations);
    const wire = await main.webContents.executeJavaScript('window.preferenceWireTest.writes');
    assert.ok(wire.every(request => request.bytes < 1024 && request.keepalive));
    console.log(`Actual native WebUI: 1000-source account preference edit uses ${wire[0].bytes} bytes with keepalive instead of ${fullPairBytes}; unrelated sources preserved.`);
    const beforeBulkReads = await main.webContents.executeJavaScript('window.preferenceWireTest.reads');
    await main.webContents.executeJavaScript("[...document.querySelectorAll('label')].find(label=>label.textContent.trim()==='统计叠层（全部来源）').querySelector('input').click()");
    for (let attempt = 0; attempt < 100; attempt++) {
      await main.webContents.executeJavaScript("window.dispatchEvent(new Event('focus'))");
      if (await main.webContents.executeJavaScript(`window.preferenceWireTest.reads > ${beforeBulkReads}`)) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(await main.webContents.executeJavaScript(`window.preferenceWireTest.reads > ${beforeBulkReads}`));
    const bulk = await read();
    assert.equal(Object.keys(bulk.sourceDecorations).length, 1000);
    assert.ok(Object.values(bulk.sourceDecorations).every(source => source.telemetry.enabled));
    assert.deepEqual(bulk.sourceDecorations['other-scene-999'].audioMeter, large.sourceDecorations['other-scene-999'].audioMeter);
    const bulkWire = await main.webContents.executeJavaScript('window.preferenceWireTest.writes.at(-1)');
    assert.ok(bulkWire.bytes < 1024 * 1024);
    console.log(`Actual native WebUI: atomic 1000-source telemetry update uses ${bulkWire.bytes} bytes and preserves unrelated audio controls.`);
  } finally {
    await save(before);
    await main.loadURL(`${origin}/#settings`);
  }
};
