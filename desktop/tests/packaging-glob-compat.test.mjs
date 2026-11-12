import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, writeFile, rm, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const builder = createRequire(require.resolve('electron-builder'));
const lib = createRequire(builder.resolve('app-builder-lib'));

test('actual Electron packager keeps include/exclude matching and ASAR round trips with patched minimatch', async t => {
  const { FileMatcher } = lib('./fileMatcher');
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-packaging-glob-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = path.join(root, 'app');
  await mkdir(path.join(source, 'src'), { recursive: true });
  const files = { 'src/main.mjs': 'export const fixture = 42;', 'src/secret.key': 'excluded fixture',
    'package.json': '{"name":"fixture","version":"1.0.0","main":"src/main.mjs"}' };
  for (const [name, value] of Object.entries(files)) await writeFile(path.join(source, name), value);
  const matcher = new FileMatcher(source, path.join(root, 'out'), s => s, ['**/*', '!**/*.key']);
  const filter = matcher.createFilter();
  for (const [name, expected] of [['src/main.mjs', true], ['src/secret.key', false], ['package.json', true]]) {
    const file = path.join(source, name);
    assert.equal(filter(file, await stat(file)), expected, name);
  }
  const asar = lib('@electron/asar');
  const archive = path.join(root, 'fixture.asar');
  await asar.createPackageWithOptions(source, archive, { globOptions: { ignore: '**/*.key' } });
  assert.equal(asar.extractFile(archive, 'src/main.mjs').toString(), files['src/main.mjs']);
  assert.equal(asar.listPackage(archive).some(name => name.endsWith('secret.key')), false);
});
