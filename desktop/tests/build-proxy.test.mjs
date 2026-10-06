import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createServer as createTlsServer } from 'node:https';
import { connect } from 'node:net';
import { spawn } from 'node:child_process';
import { generateKeyPairSync, sign } from 'node:crypto';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
import path from 'node:path';

// Ephemeral self-signed localhost identity: no committed private key, external
// certificate tool, persistent trust-store change, or disabled TLS verification.
function loopbackIdentity() {
  const der = (tag, ...parts) => {
    const body = Buffer.concat(parts.map(p => Buffer.isBuffer(p) ? p : Buffer.from(p)));
    const length = body.length < 128 ? [body.length] : body.length < 256 ? [129, body.length] : [130, body.length >> 8, body.length & 255];
    return Buffer.concat([Buffer.from([tag, ...length]), body]);
  };
  const sequence = (...parts) => der(48, ...parts);
  const oid = hex => der(6, Buffer.from(hex, 'hex'));
  const algorithm = sequence(oid('2a864886f70d01010b'), der(5)); // SHA256 with RSA
  const name = sequence(der(49, sequence(oid('550403'), der(12, 'localhost'))));
  const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const extensions = der(163, sequence(
    sequence(oid('551d13'), der(1, [255]), der(4, sequence(der(1, [255])))),
    sequence(oid('551d11'), der(4, sequence(der(130, 'localhost'), der(135, [127, 0, 0, 1])))),
  ));
  const body = sequence(der(160, der(2, [2])), der(2, [1]), algorithm, name,
    sequence(der(24, '20200101000000Z'), der(24, '21200101000000Z')), name,
    publicKey.export({ format: 'der', type: 'spki' }), extensions);
  const certificate = sequence(body, algorithm, der(3, [0], sign('sha256', body, privateKey)));
  const pem = '-----BEGIN CERTIFICATE-----\n' + certificate.toString('base64').match(/.{1,64}/g).join('\n') + '\n-----END CERTIFICATE-----\n';
  return { key: privateKey.export({ format: 'pem', type: 'pkcs8' }), cert: pem };
}

const worker = fileURLToPath(new URL('./fixtures/build-proxy-worker.cjs', import.meta.url));

test('actual builder downloader preserves direct, proxy, NO_PROXY and verified TLS', { timeout: 30000 }, async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-build-proxy-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const identity = loopbackIdentity();
  const caPath = path.join(root, 'fixture-ca.pem');
  await writeFile(caPath, identity.cert);
  const sockets = new Set();
  const servers = [];
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all(servers.map(server => new Promise(resolve => server.close(resolve))));
  });
  const listen = async server => {
    servers.push(server);
    server.on('connection', socket => {
      sockets.add(socket);
      socket.on('close', () => sockets.delete(socket));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    return server.address().port;
  };
  let originRequests = 0;
  const origin = (request, response) => {
    originRequests++;
    assert.equal(request.headers['proxy-authorization'], undefined);
    response.end('fixture-download');
  };
  const httpPort = await listen(createServer(origin));
  const tlsPort = await listen(createTlsServer(identity, origin));
  let proxyRequests = 0;
  let tunnels = 0;
  const proxy = createServer((request, response) => {
    // Serve at the proxy: missing bootstrap cannot pass by reaching the origin.
    assert.equal(request.url, 'http://127.0.0.1:' + httpPort + '/fixture');
    assert.equal(request.headers['proxy-authorization'], 'Basic ' + Buffer.from('fixture:pass').toString('base64'));
    proxyRequests++;
    response.end('fixture-download');
  });
  proxy.on('connect', (request, client, head) => {
    assert.ok(['127.0.0.1:' + tlsPort, '127.0.0.2:' + tlsPort].includes(request.url));
    assert.equal(request.headers['proxy-authorization'], 'Basic ' + Buffer.from('fixture:pass').toString('base64'));
    tunnels++;
    // Only the fixture's own loopback TLS server is reachable through this proxy.
    const upstream = connect(tlsPort, '127.0.0.1', () => {
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) upstream.write(head);
      client.pipe(upstream).pipe(client);
    });
    sockets.add(upstream);
    upstream.on('close', () => sockets.delete(upstream));
    upstream.on('error', () => client.destroy());
    client.on('error', () => upstream.destroy());
    client.on('close', () => upstream.destroy());
  });
  const proxyPort = await listen(proxy);
  const proxyUrl = 'http://fixture:pass@127.0.0.1:' + proxyPort;
  let runId = 0;
  const run = async (url, { proxyEnabled = false, noProxy = '', ca = false, expected = 'ok' } = {}) => {
    const env = { ...process.env };
    for (const key of Object.keys(env)) {
      if (/proxy|^NODE_EXTRA_CA_CERTS$|^NODE_TLS_REJECT_UNAUTHORIZED$|^NODE_USE_ENV_PROXY$/i.test(key)) delete env[key];
    }
    env.ELECTRON_GET_NO_PROGRESS = '1';
    if (proxyEnabled) Object.assign(env, {
      ELECTRON_GET_USE_PROXY: '1', GLOBAL_AGENT_HTTP_PROXY: proxyUrl,
      GLOBAL_AGENT_HTTPS_PROXY: proxyUrl, GLOBAL_AGENT_NO_PROXY: noProxy,
    });
    const args = [worker, url, path.join(root, String(++runId)), expected];
    if (ca) args.push(caPath);
    const child = spawn(process.execPath, args, { env, stdio: 'inherit', windowsHide: true });
    t.after(() => { if (child.exitCode === null) child.kill(); });
    const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', resolve); });
    assert.equal(code, 0);
  };
  const httpUrl = 'http://127.0.0.1:' + httpPort + '/fixture';
  const tlsUrl = 'https://127.0.0.1:' + tlsPort + '/fixture';
  await t.test('direct HTTP download', async () => { await run(httpUrl); assert.equal(originRequests, 1); assert.equal(proxyRequests, 0); });
  await t.test('authenticated HTTP proxy download', async () => { await run(httpUrl, { proxyEnabled: true }); assert.equal(proxyRequests, 1); assert.equal(originRequests, 1); });
  await t.test('NO_PROXY bypass', async () => { await run(httpUrl, { proxyEnabled: true, noProxy: '127.0.0.1' }); assert.equal(proxyRequests, 1); assert.equal(originRequests, 2); });
  await t.test('direct TLS rejects untrusted certificate', () => run(tlsUrl, { expected: 'DEPTH_ZERO_SELF_SIGNED_CERT|SELF_SIGNED_CERT_IN_CHAIN' }));
  await t.test('direct TLS accepts explicitly trusted CA', () => run(tlsUrl, { ca: true }));
  await t.test('proxy TLS rejects untrusted certificate', () => run(tlsUrl, { proxyEnabled: true, expected: 'DEPTH_ZERO_SELF_SIGNED_CERT|SELF_SIGNED_CERT_IN_CHAIN' }));
  await t.test('proxy TLS accepts explicitly trusted CA', () => run(tlsUrl, { proxyEnabled: true, ca: true }));
  await t.test('proxy TLS still verifies hostname', () => run('https://127.0.0.2:' + tlsPort + '/fixture', { proxyEnabled: true, ca: true, expected: 'ERR_TLS_CERT_ALTNAME_INVALID' }));
  assert.equal(tunnels, 3);
  assert.equal(originRequests, 4);
});
