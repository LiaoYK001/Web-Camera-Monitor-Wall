import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// Resolve exactly what Vite -> PostCSS loads, not a root test-only dependency.
const require = createRequire(import.meta.url);
const vite = createRequire(require.resolve('vite'));
const postcssRequire = createRequire(vite.resolve('postcss'));
const { SourceMapConsumer, SourceMapGenerator, SourceNode } = postcssRequire('source-map-js');
const basic = { version: 3, sources: ['input.css'], names: [], mappings: 'AAAA', sourcesContent: ['a{}'] };
const indexed = (line, column = 0, map = basic) => ({ version: 3, sections: [{ offset: { line, column }, map }] });

test('Vite/PostCSS resolves the reviewed source-map-js patch', () => {
  assert.equal(postcssRequire('source-map-js/package.json').version, '1.2.2');
});

test('indexed maps reject invalid and excessive offsets before expansion', () => {
  for (const offset of [-1, 0.5, '1', NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => new SourceMapConsumer(indexed(offset)), /non-negative integers/);
    assert.throws(() => new SourceMapConsumer(indexed(0, offset)), /non-negative integers/);
  }
  assert.throws(() => new SourceMapConsumer(indexed(1e7 + 1)), /must not exceed 10000000/);
  assert.throws(() => new SourceMapConsumer(indexed(6e6, 0, indexed(6e6))), /including offsets of nested sections/);
});

test('valid indexed boundaries and exhausted code remain usable', () => {
  const consumer = new SourceMapConsumer(indexed(1e7));
  assert.equal(SourceNode.fromStringWithSourceMap('a{}', consumer).toString(), 'a{}');
  let nested = basic;
  for (let i = 0; i < 12; i++) nested = indexed(0, 0, nested);
  assert.deepEqual(new SourceMapConsumer(nested).sources, ['input.css']);
  const map = new SourceMapGenerator({ file: 'out.css' });
  map.addMapping({ generated: { line: 1, column: 0 } });
  map.addMapping({ generated: { line: 1000003, column: 0 } });
  assert.equal(map.toJSON().mappings.length, 1000004);
});

test('actual PostCSS ordinary map generation still round-trips', async () => {
  const result = await vite('postcss')([]).process('a { color: red }', {
    from: 'input.css', to: 'output.css', map: { inline: false, annotation: false },
  });
  assert.equal(result.css, 'a { color: red }');
  const map = result.map.toJSON();
  const consumer = new SourceMapConsumer(map);
  assert.equal(consumer.originalPositionFor({ line: 1, column: 0 }).source, 'input.css');
  assert.equal(SourceNode.fromStringWithSourceMap(result.css, consumer).toString(), result.css);
});

test('patched Workbox resolver clones and freezes defaults without the vulnerable merge dependency', async t => {
  const { mkdtemp, mkdir, writeFile, rm } = await import('node:fs/promises');
  const path = await import('node:path');
  const os = await import('node:os');
  const { pathToFileURL } = await import('node:url');
  const pwa = createRequire(require.resolve('vite-plugin-pwa'));
  const workbox = createRequire(pwa.resolve('workbox-build'));
  const resolver = workbox('@rollup/plugin-node-resolve');
  const esm = await import(pathToFileURL(path.join(path.dirname(path.dirname(workbox.resolve('@rollup/plugin-node-resolve'))), 'es/index.js')).href);
  assert.deepEqual(esm.DEFAULTS, resolver.DEFAULTS);
  assert.deepEqual(resolver.DEFAULTS.extensions, ['.mjs', '.js', '.json', '.node']);
  assert.equal(Object.isFrozen(resolver.DEFAULTS), true);
  assert.equal(Object.isFrozen(resolver.DEFAULTS.extensions), true);
  assert.equal(Object.isFrozen(esm.DEFAULTS.extensions), true);
  const root = await mkdtemp(path.join(os.tmpdir(), 'webobs-resolver-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'node_modules/fixture-package'), { recursive: true });
  await writeFile(path.join(root, 'node_modules/fixture-package/package.json'), JSON.stringify({ name: 'fixture-package', version: '1.0.0', main: 'index.js' }));
  await writeFile(path.join(root, 'node_modules/fixture-package/index.js'), 'export const answer = 42;');
  await writeFile(path.join(root, 'input.js'), "export { answer } from 'fixture-package';");
  for (const plugin of [resolver.nodeResolve, esm.nodeResolve]) {
    const bundle = await workbox('rollup').rollup({ input: path.join(root, 'input.js'), plugins: [plugin()] });
    try {
      const built = await bundle.generate({ format: 'esm' });
      assert.match(built.output[0].code, /answer = 42/);
      assert.doesNotMatch(built.output[0].code, /from ['"]fixture-package/);
    } finally { await bundle.close(); }
  }
});
