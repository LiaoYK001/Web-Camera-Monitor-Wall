import test from 'node:test';
import assert from 'node:assert/strict';
import { bindPort, bindSharedPort } from '../src/ports.mjs';

test('automatic shared port retries a real TCP collision without closing its owner', async t => {
  const [owner, candidate] = await bindSharedPort();
  t.after(() => owner.release());
  let first = true;
  const pair = await bindSharedPort(0, '127.0.0.1', (port, udp, address) => {
    if (udp && first) { first = false; return candidate; }
    return bindPort(port, udp, address);
  });
  t.after(() => Promise.all(pair.map(lease => lease.release())));
  assert.equal(pair[0].port, pair[1].port);
  assert.notEqual(pair[0].port, owner.port);
  const releasedUdp = await bindPort(candidate.port, true);
  await releasedUdp.release();
  await assert.rejects(bindPort(owner.port), { code: 'EADDRINUSE' });
});

for (const code of ['EACCES', 'EADDRINUSE']) test(`automatic shared port recovers from TCP ${code} and releases rejected UDP leases`, async () => {
  const released = []; let attempts = 0;
  const pair = await bindSharedPort(0, '0.0.0.0', async (port, udp, address) => {
    assert.equal(address, '0.0.0.0');
    if (udp) { const allocated = 20000 + ++attempts; return { port: allocated, release: async () => { released.push(allocated); } }; }
    if (attempts < 3) throw Object.assign(new Error('reserved'), { code });
    return { port, release: async () => undefined };
  });
  assert.equal(attempts, 3);
  assert.deepEqual(released, [20001, 20002]);
  assert.deepEqual(pair.map(lease => lease.port), [20003, 20003]);
  await Promise.all(pair.map(lease => lease.release()));
});

test('a saved shared port reports its conflict and never substitutes a different port', async () => {
  let attempts = 0, released = 0;
  await assert.rejects(bindSharedPort(23456, '127.0.0.1', async (port, udp) => {
    assert.equal(port, 23456);
    if (udp) throw Object.assign(new Error('reserved'), { code: 'EACCES' });
    attempts++; return { port, release: async () => { released++; } };
  }), { code: 'EACCES' });
  assert.equal(attempts, 1); assert.equal(released, 1);
});

test('automatic shared port retry is bounded and releases every rejected candidate', async () => {
  let attempts = 0, released = 0;
  await assert.rejects(bindSharedPort(0, '127.0.0.1', async (port, udp) => {
    if (!udp) throw Object.assign(new Error('reserved'), { code: 'EACCES' });
    attempts++; return { port: 20000 + attempts, release: async () => { released++; } };
  }), { code: 'EACCES' });
  assert.equal(attempts, 16); assert.equal(released, attempts);
});

test('non-conflict TCP failures stop allocation and release the UDP candidate', async () => {
  let attempts = 0, released = 0;
  await assert.rejects(bindSharedPort(0, '127.0.0.1', async (_port, udp) => {
    if (!udp) throw Object.assign(new Error('resource failure'), { code: 'ENOBUFS' });
    attempts++; return { port: 23456, release: async () => { released++; } };
  }), { code: 'ENOBUFS' });
  assert.equal(attempts, 1); assert.equal(released, 1);
});
