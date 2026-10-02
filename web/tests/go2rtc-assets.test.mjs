import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { packagedFactorySource, replaceSanitizerFactory } from '../../scripts/patch-monaco-sanitizer.mjs';

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const monaco = path.join(web, 'go2rtc-dist/vendor/monaco-editor');
const evidence = JSON.parse(readFileSync(path.join(monaco, 'webobs-sanitizer.json'), 'utf8'));
const source = readFileSync(path.join(monaco, evidence.file), 'utf8');

test('actual packaged Monaco constructor uses the pinned, patched DOMPurify', () => {
  assert.equal(evidence.dompurifyVersion, '3.4.16');
  assert.equal(createHash('sha256').update(source).digest('hex'), evidence.packagedSha256);
  const constructor = packagedFactorySource(source, evidence.factoryName);
  const purifier = vm.runInNewContext(`(${constructor})()`, {}, {
    timeout: 1000, contextCodeGeneration: { strings: false, wasm: false },
  });
  assert.equal(purifier.version, '3.4.16');
  assert.equal(purifier.isSupported, false, 'Node intentionally has no browser DOM');
  assert.doesNotMatch(constructor, /3\.4\.15/);
  assert.equal(JSON.parse(readFileSync(path.join(monaco, 'package.json'), 'utf8')).dependencies.dompurify, '3.4.16');
});

test('unexpected or already-patched vendor constructors fail closed', () => {
  const purify = readFileSync(path.join(web, 'node_modules/dompurify/dist/purify.min.js'), 'utf8');
  assert.throws(() => replaceSanitizerFactory(source, purify), /one complete pinned/);
  assert.throws(() => replaceSanitizerFactory('function changedVendor() {}', purify), /one complete pinned/);
});
