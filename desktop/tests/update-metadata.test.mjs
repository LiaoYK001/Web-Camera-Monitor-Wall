import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { verifyUpdateMetadata } from '../scripts/update-metadata.mjs';
import { digestFile } from '../src/runtime-integrity.mjs';

test('stable unsigned feed matches the complete installer and rejects corruption or a redirected artifact', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-update-metadata-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const name='WebOBS-3.5.0-windows-x64-UNSIGNED.exe', installer=path.join(root,name);
  await writeFile(installer,'NSIS fixture');
  const sha512=await digestFile(installer,'sha512','base64');
  const metadata=url=>`version: 3.5.0\nfiles:\n  - url: ${url}\n    size: 12\n    sha512: ${sha512}\npath: ${url}\nsha512: ${sha512}\n`;
  await writeFile(path.join(root,'latest.yml'),metadata(name));
  assert.equal((await verifyUpdateMetadata(root,'3.5.0')).installer,name);
  await assert.rejects(verifyUpdateMetadata(root,'3.5.0-dev.0'),/Stable/);
  await assert.rejects(verifyUpdateMetadata(root,'3.6.0'),/identity/);
  await writeFile(installer,'NSIS changed');
  await assert.rejects(verifyUpdateMetadata(root,'3.5.0'),/SHA-512/);
  await writeFile(path.join(root,'latest.yml'),metadata('https://other.invalid/update.exe'));
  await assert.rejects(verifyUpdateMetadata(root,'3.5.0'),/Invalid complete NSIS/);
});
