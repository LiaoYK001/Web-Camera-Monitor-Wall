import test from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as pause } from 'node:timers/promises';
import { NativePreviewClient, requestNativePreview } from '../src/native-preview.mjs';

const value = (requested = true) => ({ supported: true, requested, state: requested ? 2 : 0, frames: 20 });
test('native preview forwards only the local authenticated session and fixed operation', async () => {
  const origin = 'http://127.0.0.1:18080', token = 'a'.repeat(64);
  const calls = [];
  const options = { origin, token, cookies: { async get(query) {
    assert.deepEqual(query, { url: origin }); return [{ name: 'session', value: 'private' }];
  } }, async fetch(url, init) { calls.push({ url, ...init }); return Response.json(value()); } };
  await requestNativePreview('open', options);
  assert.equal(calls[0].url, origin + '/api/v1/program/native-preview');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(calls[0].headers, { Origin: origin, Cookie: 'session=private', 'X-WebOBS-Native-Token': token });
  assert.equal(calls[0].redirect, 'error');
  await assert.rejects(requestNativePreview('exec', options), /Invalid/);
  await assert.rejects(requestNativePreview('open', { ...options, origin: 'http://192.168.1.2:18080' }));
  await assert.rejects(requestNativePreview('open', { ...options, cookies: { async get() { return []; } } }), /登录/);
  await assert.rejects(requestNativePreview('open', { ...options, fetch: async () => new Response('private diagnostic', { status: 403 }) }), /权限/);
  assert.equal(calls.length, 1);
});

test('closing during a slow native open serializes deletion and never restarts its heartbeat', async () => {
  let complete;
  const calls = [];
  const client = new NativePreviewClient(async operation => {
    calls.push(operation);
    if (operation === 'open') return new Promise(resolve => { complete = resolve; });
    return value(false);
  }, 10);
  const opening = client.open();
  await pause(0);
  const closing = client.close();
  complete(value());
  await Promise.all([opening, closing]);
  await pause(40);
  assert.deepEqual(calls, ['open', 'close']);
  assert.equal(client.status().requested, false);
});

test('native lease renewal stops on failed account authorization without retrying indefinitely', async () => {
  const calls = [];
  const client = new NativePreviewClient(async operation => {
    calls.push(operation);
    if (operation === 'status') throw new Error('session revoked');
    return value();
  }, 5);
  await client.open();
  for (let n = 0; n < 100 && client.status().state !== 3; n++) await pause(5);
  assert.equal(client.status().state, 3);
  await pause(30);
  assert.deepEqual(calls, ['open', 'status']);
  assert.equal(client.status().requested, false);
});
