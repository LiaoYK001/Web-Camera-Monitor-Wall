import { execFile } from 'node:child_process';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'gateway', 'transcode-on-demand.sh');
const token = 'a'.repeat(32);
const mixPath = `mix-${token}`;
const source = `direct-${token}`;

function run(args) {
  return new Promise((resolve) => {
    execFile('sh', [script, ...args], { timeout: 10_000 }, (error, stdout, stderr) => {
      resolve({ code: error ? error.code ?? 1 : 0, stderr: String(stderr) });
    });
  });
}

test('audio-mix accepts a per-track gain spec from a URL or a direct route', async () => {
  for (const args of [
    ['rtsp://127.0.0.1:8554/dual', mixPath, 'audio-mix', '0:1.0:0,1:0.4:0'],
    [source, mixPath, 'audio-mix', '0:1:0,1:0:1,3:0.25:0'],
  ]) {
    const result = await run(args);
    assert.notEqual(result.code, 2, `${args.join(' ')} must pass validation`);
    assert.doesNotMatch(result.stderr, /invalid internal/);
  }
});

test('audio-mix rejects malformed specs, destinations and argument counts', async () => {
  const cases = [
    [source, mixPath, 'audio-mix', '0:2.0:0'],
    [source, mixPath, 'audio-mix', '32:1.0:0'],
    [source, mixPath, 'audio-mix', '0:1.0:2'],
    [source, mixPath, 'audio-mix', '0-1.0-0'],
    [source, mixPath, 'audio-mix', ''],
    [source, mixPath, 'audio-mix', '0:1.0:0,1:1.0:0,2:1.0:0,3:1.0:0,4:1.0:0,5:1.0:0,6:1.0:0,7:1.0:0,8:1.0:0'],
    [source, `hybrid-${token}`, 'audio-mix', '0:1.0:0'],
    [source, mixPath, 'audio-mix'],
  ];
  for (const args of cases) {
    const result = await run(args);
    assert.equal(result.code, 2, `${args.join(' ')} must be rejected`);
    assert.match(result.stderr, /invalid internal audio-mix spec|invalid internal transcoder path/);
  }
});
