// Exercise malformed legacy writes through the actual authenticated gateway.
const assert = require('node:assert/strict');

exports.exercisePreferenceJson = async (origin, headers) => {
  const endpoint = `${origin}/api/v2/account/preferences/monitor-view`;
  const read = async () => {
    const response = await fetch(endpoint, { headers }); assert.equal(response.status, 200);
    return response.json();
  };
  const write = async value => {
    const response = await fetch(endpoint, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) });
    assert.equal(response.status, 200); return response.json();
  };
  const original = await read();
  try {
    const initial = await write({ localMonitorVolume: .27, sourceAudio: { constructor: { volume: .4 } }, optional: null, flags: [false, true] });
    const bodies = [
      Buffer.from('{"value":'),
      Buffer.concat([Buffer.from('{"value":{"name":"'), Buffer.from([255]), Buffer.from('"}}')]),
      Buffer.from('{"value":{"nested":' + '['.repeat(2048) + '0' + ']'.repeat(2048) + '}}'),
      Buffer.from('{"value":{"number":' + '1'.repeat(5000) + '}}'),
      Buffer.from('{"value":{"localMonitorVolume":NaN}}'),
      Buffer.from('{"value":{"localMonitorVolume":1e309}}'),
    ];
    for (const body of bodies) {
      const response = await fetch(endpoint, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' }, body });
      assert.equal(response.status, 400, 'malformed preference must be a client error');
      const raw = await response.text(); assert.ok(Buffer.byteLength(raw) < 256);
      assert.ok(['invalid_json', 'invalid_preference'].includes(JSON.parse(raw).error.code));
      assert.deepEqual(await read(), initial, 'invalid requests must retain both the value and revision');
    }
    const health = await fetch(`${origin}/api/v1/health`); assert.equal(health.status, 200);
    console.log('Actual authenticated preference gateway: six malformed legacy writes return bounded HTTP 400; prior finite values and revision retained, control service remains healthy. Isolated test account only.');
  } finally { await write(original.value ?? {}); }
};
