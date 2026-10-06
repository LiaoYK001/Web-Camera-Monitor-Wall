// Isolate global-agent's global HTTP hooks from other tests.
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const fs = require('node:fs/promises');
const builder = createRequire(require.resolve('electron-builder/package.json'));
const library = createRequire(builder.resolve('app-builder-lib'));
const download = createRequire(library.resolve('@electron/get'));
const [url, target, expected, caPath] = process.argv.slice(2);
(async () => {
  const agent = download('global-agent');
  const pkg = download('global-agent/package.json');
  assert.equal(pkg.version, '4.1.3');
  assert.equal(typeof agent.bootstrap, 'function');
  assert.equal(pkg.dependencies.roarr, undefined);
  const semver = createRequire(download.resolve('global-agent'))('semver');
  assert.ok(semver.satisfies(process.versions.node, pkg.engines.node));
  library('@electron/get'); // Real entry exercises ELECTRON_GET_USE_PROXY.
  if (process.env.ELECTRON_GET_USE_PROXY) assert.ok(global.GLOBAL_AGENT, 'proxy bootstrap must not silently fail');
  const { GotDownloader } = download('./GotDownloader.js');
  const options = { quiet: true, retry: { limit: 0 }, timeout: { request: 4000 } };
  if (caPath) options.https = { certificateAuthority: await fs.readFile(caPath) };
  const run = () => new GotDownloader().download(url, target, options);
  if (expected === 'ok') {
    await run();
    assert.equal(await fs.readFile(target, 'utf8'), 'fixture-download');
  } else {
    await assert.rejects(run, error => {
      assert.match(error.code, new RegExp(expected));
      return true;
    });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
