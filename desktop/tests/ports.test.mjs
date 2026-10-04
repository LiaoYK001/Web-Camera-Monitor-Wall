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

test('automatic shared allocation escapes a whole TCP-reserved ephemeral range', async () => {
  const released = [], requested = [];
  const pair = await bindSharedPort(0, '127.0.0.1', async (port, udp) => {
    requested.push([port, udp]);
    const selected = port || 63700;
    if (!udp && selected >= 63700 && selected < 63800)
      throw Object.assign(new Error('TCP range reserved'), { code: 'EACCES' });
    return { port: selected, release: async () => { released.push(selected); } };
  }, () => 24001);
  assert.deepEqual(pair.map(lease => lease.port), [24001, 24001]);
  assert.deepEqual(requested, [[0, true], [63700, false], [24001, true], [24001, false]]);
  assert.deepEqual(released, [63700]);
  await Promise.all(pair.map(lease => lease.release()));
});

test('automatic shared allocation also recovers when a fallback UDP candidate is denied', async () => {
  const choices = [24001, 25001], released = [];
  const pair = await bindSharedPort(0, '127.0.0.1', async (port, udp) => {
    const selected = port || 63700;
    if ((!udp && selected === 63700) || (udp && selected === 24001))
      throw Object.assign(new Error('protocol restriction'), { code: 'EACCES' });
    return { port: selected, release: async () => { released.push(selected); } };
  }, () => choices.shift());
  assert.deepEqual(pair.map(lease => lease.port), [25001, 25001]);
  assert.deepEqual(released, [63700]);
  await Promise.all(pair.map(lease => lease.release()));
});

test('a saved shared port denied by TCP is tried once without choosing a replacement', async () => {
  let attempts = 0;
  await assert.rejects(bindSharedPort(23456, '127.0.0.1', async (port, udp) => {
    attempts++; assert.equal(port, 23456); assert.equal(udp, false);
    throw Object.assign(new Error('TCP restriction'), { code: 'EACCES' });
  }, () => { throw new Error('A saved port must not be replaced'); }), { code: 'EACCES' });
  assert.equal(attempts, 1);
});
