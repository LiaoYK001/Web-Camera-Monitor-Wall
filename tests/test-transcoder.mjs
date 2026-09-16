import { execFile } from 'node:child_process';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'gateway', 'transcode-on-demand.sh');
const token = 'a'.repeat(32);
const audioPath = `audio-${token}-t1`;

// The script validates its arguments before running ffmpeg, so a rejected call
// exits 2 with a specific message and never spawns a process.
function run(args) {
  return new Promise((resolve) => {
    execFile('sh', [script, ...args], { timeout: 10_000 }, (error, stdout, stderr) => {
      resolve({ code: error ? error.code ?? 1 : 0, stdout: String(stdout), stderr: String(stderr) });
    });
  });
}

test('audio-track mode accepts an explicit RTSP source URL', async () => {
  const accepted = await run(['rtsp://127.0.0.1:8554/dual', audioPath, 'audio-track', '1']);
  assert.notEqual(accepted.code, 2, 'a printable RTSP URL must pass validation');
  assert.doesNotMatch(accepted.stderr, /invalid internal/);
});

test('audio-track mode still accepts a direct route and rejects a mismatched track', async () => {
  const accepted = await run([`direct-${token}`, audioPath, 'audio-track', '1']);
  assert.notEqual(accepted.code, 2, 'a direct-<token> source must keep working');
  const mismatched = await run([`direct-${token}`, audioPath, 'audio-track', '0']);
  assert.equal(mismatched.code, 2);
  assert.match(mismatched.stderr, /invalid internal audio-only track path/);
});

test('malformed arguments never reach ffmpeg', async () => {
  const cases = [
    // A URL source is only meaningful for the audio-track mode.
    [['rtsp://127.0.0.1:8554/dual', `hybrid-${token}`, 'transcode', 'copy'], /invalid internal transcoder path/],
    // A hybrid destination may not be fed from an audio-only path.
    [[`direct-${token}`, `audio-${token}-t1`, 'transcode', 'copy'], /invalid internal transcoder path/],
    [[`direct-${token}`, `hybrid-${token}`, 'transcode', 'copy', 'extra'], /invalid internal transcoder path/],
    [['rtsp://127.0.0.1:8554/a b', audioPath, 'audio-track', '1'], /invalid internal transcoder path/],
    [['rtsp://127.0.0.1:8554/a"; touch /tmp/pwned; "', audioPath, 'audio-track', '1'], /invalid internal transcoder path/],
    [[`direct-${token}`, 'audio-short-t1', 'audio-track', '1'], /invalid internal audio-only track path/],
    [[`direct-${token}`, `audio-${'b'.repeat(32)}-t32`, 'audio-track', '32'], /invalid internal audio-only track path/],
    [[`direct-${token}`, audioPath, 'audio-track', '32'], /invalid internal audio-only track path/],
    [['/etc/passwd', audioPath, 'audio-track', '1'], /invalid internal transcoder path/],
    [['rtsp://127.0.0.1:8554/dual', audioPath, 'audio-track'], /invalid internal transcoder path/],
  ];
  for (const [args, expected] of cases) {
    const result = await run(args);
    assert.equal(result.code, 2, `${args.join(' ')} must be rejected`);
    assert.match(result.stderr, expected);
  }
});
