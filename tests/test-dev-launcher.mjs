import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
const script = fileURLToPath(new URL('../scripts/dev.mjs', import.meta.url));
function execute(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`dev.mjs ${args.join(' ')} timed out\n${output}`));
    }, 30000);
    child.stdout.on('data', chunk => output += chunk);
    child.stderr.on('data', chunk => output += chunk);
    child.once('error', (error) => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); resolve({ code, output }); });
  });
}
async function fixture(status = 200) {
  const server = http.createServer((request, response) => response.writeHead(status).end('{}'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { server, port: server.address().port, url: `http://127.0.0.1:${server.address().port}` };
}
test('help works without checking Docker or native dependencies', async () => {
  const result = await execute(['--help']);
  assert.equal(result.code, 0);
  assert.match(result.output, /native/);
  assert.match(result.output, /frontend/);
});
test('invalid arguments fail with an actionable message', async () => {
  const result = await execute(['--port', 'oops']);
  assert.equal(result.code, 1);
  assert.match(result.output, /1024–65535/);
});
test('help documents the explicit Composite opt-in for both shells', async () => {
  const result = await execute(['--help']);
  assert.equal(result.code, 0);
  assert.match(result.output, /-Composite/);
  assert.match(result.output, /--composite/);
  assert.match(result.output, /dev\.ps1 -Setup -Composite/);
});
test('help documents the Windows and Linux soak flags', async () => {
  const result = await execute(['--help']);
  assert.equal(result.code, 0);
  assert.match(result.output, /-Soak/);
  assert.match(result.output, /--soak/);
});

test('the soak flag is accepted and validated with the rest of the arguments', async () => {
  const result = await execute(['--soak', '--port', 'oops']);
  assert.equal(result.code, 1);
  assert.match(result.output, /1024–65535/);
  assert.doesNotMatch(result.output, /未知参数/);
});

test('the composite flag is accepted and validated with the rest of the arguments', async () => {
  const result = await execute(['--composite', '--port', 'oops']);
  assert.equal(result.code, 1);
  assert.match(result.output, /1024–65535/);
  assert.doesNotMatch(result.output, /未知参数/);
});
test('frontend check accepts a healthy existing backend without starting Vite', async () => {
  const { server, url } = await fixture();
  try {
    const result = await execute(['--mode', 'frontend', '--api', url, '--check']);
    assert.equal(result.code, 0, result.output);
    assert.match(result.output, /未启动服务/);
  } finally { server.close(); }
});
test('unhealthy backend is rejected instead of silently entering an offline workspace', async () => {
  const { server, url } = await fixture(503);
  try {
    const result = await execute(['--mode', 'frontend', '--api', url, '--check']);
    assert.equal(result.code, 1);
    assert.match(result.output, /不可达/);
  } finally { server.close(); }
});
test('occupied frontend port is preserved and explains how to choose another port', async () => {
  const { server, port, url } = await fixture();
  try {
    const result = await execute(['--mode', 'frontend', '--api', url, '--port', String(port)]);
    assert.equal(result.code, 1);
    assert.match(result.output, /已被占用/);
    assert.equal((await fetch(url)).status, 200);
  } finally { server.close(); }
});

test('help documents the LAN port-forward entry points', async () => {
  const result = await execute(['--help']);
  assert.equal(result.code, 0);
  assert.match(result.output, /dev-lan-environment\.ps1/);
  assert.match(result.output, /dev-lan-environment\.sh/);
  assert.match(result.output, /--lan/);
  assert.match(result.output, /--lan-host/);
  // F6 follow-up: LAN must be HTTPS so Secure Context enables pairing + camera playback.
  assert.match(result.output, /https:\/\//);
  assert.match(result.output, /自签|Secure Context|证书/);
});

test('the lan flag is accepted and validated with the rest of the arguments', async () => {
  const result = await execute(['--lan', '--port', 'oops']);
  assert.equal(result.code, 1);
  assert.match(result.output, /1024–65535/);
  assert.doesNotMatch(result.output, /未知参数/);
});

test('lan mode rejects a non-IPv4 lan host before starting anything', async () => {
  const result = await execute(['--lan', '--lan-host', 'not-an-ip', '--check']);
  assert.equal(result.code, 1);
  assert.match(result.output, /IPv4|lan-host|未能确定局域网/);
});

test('lan mode generates a self-signed HTTPS cert with the LAN IP in the SAN', async () => {
  const { server, url } = await fixture();
  const lanHost = '192.0.2.10';
  const tlsDir = fileURLToPath(new URL('../build/dev-lan-tls/', import.meta.url));
  try {
    const result = await execute(['--lan', '--lan-host', lanHost, '--mode', 'frontend', '--api', url, '--check']);
    assert.equal(result.code, 0, result.output);
    assert.match(result.output, new RegExp(`https://${lanHost.replace(/\./g, '\\.')}:`));
    assert.match(result.output, /自签|self-signed/);
    assert.match(result.output, /Secure Context|证书|trust/i);
    const { readFileSync, existsSync } = await import('node:fs');
    const certPath = `${tlsDir}cert.pem`;
    const keyPath = `${tlsDir}key.pem`;
    assert.ok(existsSync(certPath), certPath);
    assert.ok(existsSync(keyPath), keyPath);
    const text = readFileSync(certPath, 'utf8');
    assert.match(text, /BEGIN CERTIFICATE/);
    assert.match(readFileSync(keyPath, 'utf8'), /BEGIN (RSA )?PRIVATE KEY/);
    const details = spawnSync('openssl', ['x509', '-in', certPath, '-noout', '-text'], { encoding: 'utf8', timeout: 10000, input: '' });
    if (details.status === 0) {
      assert.match(details.stdout, new RegExp(lanHost.replace(/\./g, '\\.')));
      assert.match(details.stdout, /IP Address:127\.0\.0\.1/);
      assert.match(details.stdout, /DNS:localhost/);
    }
  } finally { server.close(); }
});
