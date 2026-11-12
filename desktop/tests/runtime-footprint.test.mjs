import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { runtimeFootprint } from '../scripts/runtime-footprint.mjs';

test('footprint measures unpacked logical payload, not unmeasured post-install disk usage', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-footprint-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const [file, size] of [['WebOBS.exe', 10], ['resources/runtime/bin/tool.exe', 20],
    ['resources/runtime/obs/module.dll', 30], ['resources/runtime/go2rtc-www/index.html', 40]]) {
    await mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await writeFile(path.join(root, file), Buffer.alloc(size));
  }
  const report = await runtimeFootprint(root);
  assert.equal(report.schema, 2);
  assert.equal(report.measurementScope, 'packaged-unpacked-tree');
  assert.equal(report.byteMetric, 'logical-file-length');
  assert.equal(report.unpackedPayloadBytes, 100);
  assert.equal(report.postInstallLogicalBytes, null);
  assert.equal(report.postInstallAllocatedBytes, null);
  assert.equal(report.installedBytes, report.unpackedPayloadBytes);
  assert.match(report.deprecatedAliases.installedBytes, /not a post-install measurement/);
  assert.equal(Object.values(report.groups).reduce((sum, group) => sum + group.bytes, 0), report.unpackedPayloadBytes);
  assert.equal(report.fileCount, 4);
  assert.equal(report.groups['electron-shell'].bytes, 10);
  assert.equal(report.groups['runtime/go2rtc-www'].bytes, 40);
  assert.equal(report.largestFiles[0].bytes, 40);
});

test('an empty packaging tree does not turn unmeasured installation metrics into zero', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-footprint-empty-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const report = await runtimeFootprint(root);
  assert.equal(report.unpackedPayloadBytes, 0);
  assert.equal(report.fileCount, 0);
  assert.deepEqual(report.groups, {});
  assert.deepEqual(report.largestFiles, []);
  assert.equal(report.postInstallLogicalBytes, null);
  assert.equal(report.postInstallAllocatedBytes, null);
});
