import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { packagedFactorySource, replaceSanitizerFactory } from '../../scripts/patch-monaco-sanitizer.mjs';
import { retainGo2rtcMseHistory } from '../../scripts/patch-go2rtc-mse.mjs';

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

// Model MSE coded-frame removal: removing mid-GOP extends through the next
// random access point, even when the requested endpoint precedes the cursor.
function mseUpdate(playerSource, gopSeconds, currentTime) {
  const end = 60.4;
  const video = { currentTime, src: '', srcObject: null };
  let update, removedEnd = 0, requestedEnd;
  const buffer = {
    updating: false,
    buffered: { length: 1, start: () => removedEnd, end: () => end },
    addEventListener: (name, handler) => { if (name === 'updateend') update = handler; },
    remove: (_start, stop) => {
      requestedEnd = stop;
      removedEnd = Math.ceil(stop / gopSeconds) * gopSeconds;
      buffer.updating = true;
    },
  };
  class MediaSource {
    addEventListener() {}
    addSourceBuffer() { return buffer; }
    setLiveSeekableRange() {}
  }
  const Player = vm.runInNewContext(playerSource.replace('export class VideoRTC', 'class VideoRTC') + '; VideoRTC', {
    HTMLElement: class {}, window: {}, MediaSource, Uint8Array,
    URL: { createObjectURL: () => 'blob:fixture', revokeObjectURL() {} },
  }, { timeout: 1000 });
  const player = { video, onmessage: {}, play() {} };
  Player.prototype.onmse.call(player);
  player.onmessage.mse({ type: 'mse', value: 'video/mp4; codecs="avc1.640029"' });
  update();
  return { removedEnd, requestedEnd, currentTime: video.currentTime, rate: video.playbackRate };
}

test('packaged MSE history preserves long-GOP dependencies without widening live-edge recovery', () => {
  const original = readFileSync(path.join(web, '../go2rtc/go2rtc/www/video-rtc.js'), 'utf8');
  const packaged = readFileSync(path.join(web, 'go2rtc-dist/video-rtc.js'), 'utf8');
  assert.equal(packaged, retainGo2rtcMseHistory(original));
  for (const gopSeconds of [5, 10]) {
    const before = mseUpdate(original, gopSeconds, 58.4);
    assert.ok(before.removedEnd > before.currentTime, 'original trim removes the playing GOP');
    const after = mseUpdate(packaged, gopSeconds, 58.4);
    assert.ok(after.removedEnd < after.currentTime, 'history retains the playing GOP');
    assert.equal(after.requestedEnd, 30.4, 'history remains bounded to thirty seconds');
    assert.equal(after.rate, before.rate, 'do not substitute the rejected playback-rate experiment');
    assert.equal(mseUpdate(packaged, gopSeconds, 20).currentTime, 55.4, 'lag still seeks to the five-second live edge');
  }
});

test('unexpected or already-adapted MSE players fail closed', () => {
  const original = readFileSync(path.join(web, '../go2rtc/go2rtc/www/video-rtc.js'), 'utf8');
  assert.throws(() => retainGo2rtcMseHistory('changed upstream'), /Unexpected upstream MSE/);
  assert.throws(() => retainGo2rtcMseHistory(original + original), /Unexpected upstream MSE/);
  assert.throws(() => retainGo2rtcMseHistory(retainGo2rtcMseHistory(original)), /Unexpected upstream MSE/);
});
