const assert = require('node:assert/strict');

exports.exerciseGo2rtcReload = async (supervisor, headers) => {
  const base = supervisor.origin + '/api/v1/go2rtc/';
  const services = supervisor.children.map(entry => [entry.name, entry.process.pid]);
  let config;
  for (let index = 0; index < 7; index++) {
    const name = `reload-${index}`;
    config = `streams:\n  ${name}: rtsp://127.0.0.1:1/synthetic\n`;
    const write = await fetch(base + 'api/config', {method: 'POST', headers, body: config});
    assert.equal(write.status, 200);
    const restart = await fetch(base + 'api/restart', {method: 'POST', headers});
    assert.equal(restart.status, 202);
    const deadline = Date.now() + 15000;
    let loaded = false;
    while (Date.now() < deadline) {
      const active = await fetch(base + 'api/streams', {headers}).catch(() => null);
      if (active?.ok && JSON.stringify(Object.keys(await active.json())) === JSON.stringify([name])) { loaded = true; break; }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(loaded, 'saved stream must replace the previous stream without restarting WebOBS');
    assert.deepEqual(supervisor.children.map(entry => [entry.name, entry.process.pid]), services);
    assert.equal((await fetch(supervisor.origin + '/api/v1/auth/session', {headers})).status, 200);
  }
  const invalid = await fetch(base + 'api/config', {method: 'POST', headers, body: 'streams: [unclosed'});
  assert.equal(invalid.status, 400);
  assert.equal(await (await fetch(base + 'api/config', {headers})).text(), config);
  assert.deepEqual(Object.keys(await (await fetch(base + 'api/streams', {headers})).json()), ['reload-6']);
  console.log('Actual go2rtc: seven successive config reloads, removal of old names, unchanged service owners/session and invalid-YAML preservation passed.');
  return async () => {
    assert.equal(await (await fetch(base + 'api/config', {headers})).text(), config);
    assert.deepEqual(Object.keys(await (await fetch(base + 'api/streams', {headers})).json()), ['reload-6']);
  };
};
