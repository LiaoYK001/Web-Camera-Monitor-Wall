// TEST ONLY adapter. Reuse the existing independent marker/timecode generator,
// never its horizontal-strip geometry. OBS uses 960x540, 3x2, SCALE_INNER.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const pattern = require('../../desktop/tests/native-preview-pattern.cjs');
const ORDER = [0, 1, 2, 3, 4], REVERSED = [4, 3, 2, 1, 0];
function inspect(image, { order = ORDER, dynamic = true, inset = 0 } = {}) {
  assert.equal(order.length, 5);
  const scale = Math.min((image.width - inset * 2) / 960, (image.height - inset * 2) / 540);
  assert.ok(scale > 0 && image.width >= 320 && image.height >= 180, 'Client is too small');
  const left = (image.width - scale * 960) / 2, top = (image.height - scale * 540) / 2;
  const sampleCanvas = (x, y) => image.pixel(Math.floor(left + x * scale), Math.floor(top + y * scale));
  const near = (actual, expected, message, tolerance = 48) => assert.ok(actual.every((v, i) => Math.abs(v - expected[i]) <= tolerance), message + ': ' + actual.join(','));
  const counters = [];
  order.forEach((channel, slot) => {
    // Each 320x180 input fits at 1:1 inside its 320x270 tile with 45px
    // vertical inner bars. Projector/main-Preview scaling is applied afterward.
    const x0 = slot % 3 * 320, y0 = Math.floor(slot / 3) * 270;
    const sample = (x, y) => sampleCanvas(x0 + x, y0 + 45 + y);
    for (const [x, y] of [[40, 70], [260, 70], [160, 150]]) near(sample(x, y), pattern.COLORS[channel], `Wrong channel ${channel + 1} in tile ${slot}`);
    for (const y of [20, 250]) near(sampleCanvas(x0 + 160, y0 + y), [0, 0, 0], `Wrong SCALE_INNER bar in tile ${slot}`, 30);
    if (!dynamic) return;
    near(sample(32, 28), [255, 255, 255], `Missing white marker on channel ${channel + 1}`);
    near(sample(288, 152), [0, 0, 0], `Missing black marker on channel ${channel + 1}`);
    let counter = 0;
    for (let bit = 0; bit < 6; bit++) {
      const rgb = sample(90 + bit * 28, 108), white = rgb.every(v => v >= 200), black = rgb.every(v => v <= 55);
      assert.ok(white || black, `Invalid timecode bit ${bit} on channel ${channel + 1}`);
      if (white) counter |= 1 << bit;
    }
    assert.ok(counter < pattern.FRAMES, `Invalid timecode on channel ${channel + 1}`);
    counters.push(counter);
  });
  for (const [x, y] of [[810, 350], [900, 480], [700, 500]]) near(sampleCanvas(x, y), [0, 0, 0], 'Sixth tile must be empty', 30);
  return counters;
}
function analyze(directory, options) {
  const samples = [];
  for (let i = 0; i < 8; i++) {
    try {
      const bytes = fs.readFileSync(path.join(directory, `client-${i}.bmp`));
      assert.ok(bytes.length <= 64 * 1024 * 1024, 'Oversized screenshot');
      const image = pattern.bitmap(bytes);
      samples.push({ sample: i, passed: true, width: image.width, height: image.height, counters: inspect(image, options) });
    } catch (error) {
      // fs errors contain local paths; public synthetic summaries must not.
      const message = error.code && error.code !== 'ERR_ASSERTION' ? `Synthetic client sample unavailable (${error.code})` : String(error.message).slice(0, 220);
      samples.push({ sample: i, passed: false, error: message });
    }
  }
  let temporalProgress = !options.dynamic, progressError;
  if (options.dynamic) {
    try { pattern.progress(samples.filter(s => s.passed).map(s => s.counters)); temporalProgress = true; }
    catch (error) { progressError = String(error.message); }
  }
  return { passed: samples.every(s => s.passed) && temporalProgress, samples, temporalProgress, ...(progressError ? { progressError } : {}) };
}
function synthetic(width, height, { order = ORDER, counter = 3, inset = 0, dynamic = true } = {}) {
  const sources = order.map(c => pattern.frame(c, counter));
  const scale = Math.min((width - 2 * inset) / 960, (height - 2 * inset) / 540);
  const left = (width - 960 * scale) / 2, top = (height - 540 * scale) / 2;
  return { width, height, pixel(x, y) {
    const cx = (x + 0.5 - left) / scale, cy = (y + 0.5 - top) / scale;
    if (cx < 0 || cx >= 960 || cy < 0 || cy >= 540) return [0, 0, 0];
    const slot = Math.floor(cy / 270) * 3 + Math.floor(cx / 320), sx = Math.floor(cx % 320), sy = Math.floor(cy % 270) - 45;
    if (slot >= 5 || sy < 0 || sy >= 180) return [0, 0, 0];
    if (!dynamic) return pattern.COLORS[order[slot]];
    const at = (sy * 320 + sx) * 3;
    return [...sources[slot].subarray(at, at + 3)];
  } };
}
function selftest() {
  for (const [width, height, inset] of [[960,540,0],[1100,760,0],[601,400,10],[1280,600,10]]) {
    for (const order of [ORDER, REVERSED]) {
      assert.deepEqual(inspect(synthetic(width, height, { order, inset }), { order, inset }), [3,3,3,3,3]);
      assert.deepEqual(inspect(synthetic(width, height, { order, inset, dynamic: false }), { order, inset, dynamic: false }), []);
      assert.throws(() => inspect(synthetic(width, height, { order, inset }), { order: [...order].reverse(), inset }), /Wrong channel/);
    }
  }
  assert.throws(() => inspect({ width: 960, height: 540, pixel: () => [0,0,0] }), /Wrong channel/);
  assert.throws(() => pattern.progress(Array.from({ length: 8 }, () => [3,3,3,3,3])), /Frozen/);
  assert.throws(() => inspect(synthetic(960,540), { inset: 30 }), /Wrong|Missing|Invalid/);
  pattern.progress([0,1,2].map(counter => inspect(synthetic(960,540,{ counter }))));
  console.log('PASS: 3x2 SCALE_INNER, Preview inset, colors, markers, all five temporal channels and negative cases');
}
if (require.main === module) {
  const [mode, ...args] = process.argv.slice(2);
  if (mode === 'selftest') selftest();
  else if (mode === 'fixture') {
    const channel = Number(args[0]);
    assert.ok(Number.isInteger(channel) && channel >= 0 && channel < 5);
    fs.writeFileSync(args[1], Buffer.concat(Array.from({ length: pattern.FRAMES }, (_, counter) => pattern.frame(channel,counter))), { flag: 'wx' });
  } else if (mode === 'analyze') {
    const [directory, role, order, dynamic] = args;
    assert.ok(['main-preview', 'program-projector'].includes(role));
    console.log(JSON.stringify(analyze(directory, { inset: role === 'main-preview' ? 10 : 0, order: order === 'reverse' ? REVERSED : ORDER, dynamic: dynamic === 'true' })));
  } else throw new Error('Expected selftest, fixture or analyze');
}
module.exports = { inspect, analyze, synthetic };
