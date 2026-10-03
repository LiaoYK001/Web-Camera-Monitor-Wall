// Actual authenticated HTTP contract against the bundled native product services.
// The synthetic camera is never activated; this does not qualify audio playback.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

function cbor(value) {
  const header = (major, size) => size < 24 ? Buffer.from([(major << 5) | size])
    : Buffer.from([(major << 5) | 24, size]);
  if (typeof value === 'string') {
    const bytes = Buffer.from(value);
    assert.ok(bytes.length < 256);
    return Buffer.concat([header(3, bytes.length), bytes]);
  }
  if (Buffer.isBuffer(value)) return Buffer.concat([header(2, value.length), value]);
  const entries = Object.entries(value).map(([key, item]) => [cbor(key), cbor(item)])
    .sort(([left], [right]) => left.length - right.length || Buffer.compare(left, right));
  return Buffer.concat([header(5, entries.length), ...entries.flat()]);
}

async function exerciseNativeSync(origin, administratorHeaders) {
  async function request(route, headers, body, expected = 200) {
    const response = await fetch(`${origin}${route}`, { headers: { ...headers,
      ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) });
    assert.equal(response.status, expected, `native sync HTTP status for ${route}`);
    return response.json();
  }
  await request('/api/v1/cameras', administratorHeaders, {
    id: 'sync-camera', name: 'Synthetic sync camera', address: 'rtsp://camera.invalid/live',
    adapter: 'rtsp', credentialsRef: 'sync-camera', hardwareDecode: 'auto', capabilities: {},
    profiles: [{ id: 'sub', name: 'Sub', role: 'sub', endpoint: 'rtsp://camera.invalid/live',
      videoCodec: 'h264', audioCodec: 'aac', width: 640, height: 360, fps: 15, autoProbe: false }],
  }, 201);
  async function enroll(name) {
    const signing = crypto.generateKeyPairSync('ed25519');
    const encryption = crypto.generateKeyPairSync('x25519');
    const rawKey = (key) => key.export({ type: 'spki', format: 'der' }).subarray(-32);
    const nonce = crypto.randomBytes(32);
    const proof = cbor({ purpose: 'webobs-client-enrollment-v1', name, platform: 'web',
      signingPublicKey: rawKey(signing.publicKey), encryptionPublicKey: rawKey(encryption.publicKey), nonce });
    const enrollment = await request('/api/v2/enrollments', { Origin: origin }, {
      name, platform: 'web', signingPublicKey: rawKey(signing.publicKey).toString('base64url'),
      encryptionPublicKey: rawKey(encryption.publicKey).toString('base64url'),
      enrollmentNonce: nonce.toString('base64url'), signature: crypto.sign(null, proof, signing.privateKey).toString('base64url'),
    }, 201);
    await request(`/api/v2/enrollments/${enrollment.enrollmentId}/approve`, administratorHeaders, {
      pairingCode: enrollment.pairingCode, cameraGrants: [{ cameraId: 'sync-camera',
        profileIds: ['sub'], permissions: ['view'], credentialMode: 'none' }],
    });
    const deviceHeaders = { Origin: origin, Authorization: `WebObs-Device ${enrollment.deviceToken}` };
    const completion = await request(`/api/v2/enrollments/${enrollment.enrollmentId}/complete`, deviceHeaders, {});
    assert.equal(completion.grantBundle.contractVersion, 2);
    return deviceHeaders;
  }
  const first = await enroll('Native sync A');
  const second = await enroll('Native sync B');
  const initial = await request('/api/v2/client/bootstrap?sinceRevision=0', first);
  const scene = { schemaVersion: 6, revision: 0, id: 'native-sync-scene', name: 'Native audio selection',
    canvas: { width: 640, height: 360, backgroundColor: '#000000' },
    sources: [{ id: 'sync-input', kind: 'camera', name: 'Synthetic source', cameraId: 'sync-camera', profileId: 'sub',
      hardwareDecode: 'auto', muted: false, volume: 0.37, syncOffsetMs: 120, monitoring: 'monitor-and-output',
      audioTrack: 6, filters: [], audioInputs: [{ track: 0, gain: 0.4, muted: false, syncOffsetMs: -120 },
        { track: 31, gain: 0.8, muted: true }] }],
    items: [{ id: 'sync-item', sourceId: 'sync-input', x: 0, y: 0, width: 640, height: 360,
      scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0,
      visible: true, locked: false, rotation: 0, opacity: 1, blendMode: 'normal' }] };
  const mutation = { kind: 'scene', id: scene.id, operation: 'upsert',
    fields: Object.fromEntries(['name', 'canvas', 'sources', 'items'].map(field => [field, scene[field]])) };
  const batch = { schemaVersion: 1, baseRevision: initial.revision, mutations: [mutation] };
  const saved = await request('/api/v2/client/sync', first, batch);
  const repeated = await request('/api/v2/client/sync', first, batch);
  assert.equal(repeated.revision, saved.revision);
  assert.equal(repeated.accepted[0].unchanged, true);
  const stale = { ...batch, mutations: [{ ...mutation,
    fields: { sources: [{ ...scene.sources[0], audioInputs: [] }] } }] };
  const conflict = await request('/api/v2/client/sync', second, stale, 409);
  assert.deepEqual(conflict.conflicts[0].fields[0].serverValue, scene.sources);
  async function assertPersisted() {
    const bootstrap = await request('/api/v2/client/bootstrap?sinceRevision=0', second);
    const document = bootstrap.sync.documents.find(item => item.id === scene.id)?.document;
    assert.equal(document?.schemaVersion, 6);
    assert.deepEqual(document.sources, scene.sources);
    assert.ok(!JSON.stringify(bootstrap.sync).includes('rtsp://'));
  }
  await assertPersisted();
  return assertPersisted;
}

module.exports = { exerciseNativeSync };
