import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { runtimeFootprint } from '../scripts/runtime-footprint.mjs';

test('footprint measures installed bytes across shell and all runtime files', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-footprint-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const [file, size] of [['WebOBS.exe', 10], ['resources/runtime/bin/tool.exe', 20],
    ['resources/runtime/obs/module.dll', 30], ['resources/runtime/go2rtc-www/index.html', 40]]) {
    await mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await writeFile(path.join(root, file), Buffer.alloc(size));
  }
  const report = await runtimeFootprint(root);
  assert.equal(report.installedBytes, 100);
  assert.equal(report.fileCount, 4);
  assert.equal(report.groups['electron-shell'].bytes, 10);
  assert.equal(report.groups['runtime/go2rtc-www'].bytes, 40);
  assert.equal(report.largestFiles[0].bytes, 40);
});
