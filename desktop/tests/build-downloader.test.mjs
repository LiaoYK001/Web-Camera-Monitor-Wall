import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

// Resolve the actual builder download path rather than an unrelated root module.
const require = createRequire(import.meta.url);
const builder = createRequire(require.resolve('electron-builder/package.json'));
const library = createRequire(builder.resolve('app-builder-lib'));
const download = createRequire(library.resolve('@electron/get'));
const { GotDownloader } = download('./GotDownloader.js');

test('the actual Electron build downloader does not reuse another response through max-stale', async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-build-download-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  let requests = 0;
  const server = createServer((request, response) => {
    requests++;
    assert.equal(request.headers.cookie, undefined);
    assert.equal(request.headers.authorization, undefined);
    response.setHeader('Cache-Control', 'max-age=600');
    if (requests === 1) response.setHeader('Set-Cookie', 'fixture-session=first-response');
    response.end(requests === 1 ? 'first-response' : 'fresh-response');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const url = `http://127.0.0.1:${server.address().port}/fixture`;
  const downloader = new GotDownloader();
  await downloader.download(url, path.join(root, 'first'));
  await downloader.download(url, path.join(root, 'second'), { quiet: true, headers: { 'Cache-Control': 'max-stale=999999' } });
  assert.equal(requests, 2);
  assert.equal(await readFile(path.join(root, 'second'), 'utf8'), 'fresh-response');
});
