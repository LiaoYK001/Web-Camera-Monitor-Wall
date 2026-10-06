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
