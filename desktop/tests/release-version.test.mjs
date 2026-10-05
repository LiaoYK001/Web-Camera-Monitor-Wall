import test from 'node:test';
import assert from 'node:assert/strict';
import { stableVersion, updateKind } from '../src/release-version.mjs';

test('patches advance independently of minor and major releases', () => {
  assert.equal(updateKind('4.0.0', '4.0.1'), 'patch');
  assert.equal(updateKind('4.0.1', '4.0.2'), 'patch');
  assert.equal(updateKind('4.0.9', '4.0.10'), 'patch');
  assert.equal(updateKind('4.0.99', '4.1.0'), 'minor');
  assert.equal(updateKind('4.9.99', '5.0.0'), 'major');
});

test('equal, older, malformed and development versions never offer a stable upgrade', () => {
  for (const candidate of ['4.0.1', '4.0.0', '3.99.999', '4.0.2-dev.1', '4.0.2+local', '4.00.2', '04.0.2', '4.0', 'v4.0.2', '4.0.9007199254740992', null]) {
    assert.equal(updateKind('4.0.1', candidate), null);
  }
  assert.equal(stableVersion('4.0.2\n'), null);
  assert.equal(updateKind('4.0.0-dev.1', '4.0.1'), null);
});
