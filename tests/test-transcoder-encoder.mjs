import { execFile } from 'node:child_process';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'gateway', 'transcode-on-demand.sh');
const token = 'c'.repeat(32);
const source = `direct-${token}`;
const target = `hybrid-${token}`;

// A stub ffmpeg that prints the argv it received, so the encoder flags can be
// asserted without starting an encoder.
const stubDirectory = mkdtempSync(path.join(os.tmpdir(), 'webobs-transcoder-'));
const stub = path.join(stubDirectory, 'ffmpeg');
writeFileSync(stub, '#!/bin/sh\nprintf \'%s\\n\' "$@"\n');
chmodSync(stub, 0o755);

function run(args) {
  return new Promise((resolve) => {
    execFile('sh', [script, ...args], {
      timeout: 10_000,
      env: {
        ...process.env,
        PATH: `${stubDirectory}:${process.env.PATH}`,
        WEBOBS_HYBRID_VIDEO_ENCODER: 'x264',
      },
    }, (error, stdout, stderr) => {
      resolve({ code: error ? error.code ?? 1 : 0, argv: String(stdout).trim().split('\n').filter(Boolean), stderr: String(stderr) });
    });
  });
}

test('the hybrid x264 path keeps low latency but never enables x264 slice threads', async () => {
  const result = await run([source, target, 'transcode', 'transcode']);
  assert.equal(result.code, 0, `transcode must run (${result.stderr})`);
  const argv = result.argv.join(' ');
  assert.match(argv, /-c:v libx264/);
  // Slice threads make x264 emit several slices per frame; MediaMTX's H264
  // access-unit assembly then delivers only part of the stream over WHEP.  A
  // 720p25 source measured 15 fps with slice threads and 25 fps without them,
  // with zero packet loss on both sides, so the flag is not optional.
  assert.match(argv, /-x264-params sliced-threads=0/, 'slice threads must be disabled explicitly');
  assert.doesNotMatch(argv, /sliced-threads=1/);
  // The rest of the low-latency tune stays: dropping it entirely would add the
  // encoder lookahead back to every hybrid route.
  assert.match(argv, /-tune zerolatency/);
  assert.match(argv, /-bf 0/);
  assert.match(argv, /-sc_threshold 0/);
});

test('the hybrid copy path stays a copy and adds no x264 tuning', async () => {
  const result = await run([source, target, 'copy', 'copy']);
  assert.equal(result.code, 0, `copy must run (${result.stderr})`);
  const argv = result.argv.join(' ');
  assert.match(argv, /-c:v copy/);
  assert.doesNotMatch(argv, /x264/);
});
