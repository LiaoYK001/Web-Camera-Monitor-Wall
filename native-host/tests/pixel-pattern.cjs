// TEST ONLY adapter. Reuse the existing independent marker/timecode generator,
// never its horizontal-strip geometry. OBS uses 960x540, 3x2, SCALE_INNER.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const pattern = require('../../desktop/tests/native-preview-pattern.cjs');
const ORDER = [0, 1, 2, 3, 4], REVERSED = [4, 3, 2, 1, 0], REPEAT_FIRST = [0, 0, 0, 0, 0];
function geometry(order, quick) {
  assert.ok(order.length >= 1 && order.length <= 64 && order.every(c => Number.isInteger(c) && c >= 0 && c < 5));
  if (!quick) assert.equal(order.length, 5);
  const columns = quick ? Math.ceil(Math.sqrt(order.length)) : 3;
  const rows = quick ? Math.ceil(order.length / columns) : 2;
  const width = 960 / columns, height = 540 / rows, fit = Math.min(width / 320, height / 180);
  return { columns, rows, width, height, fit, padX: (width - 320 * fit) / 2, padY: (height - 180 * fit) / 2 };
}
function quickProgress(samples, count) {
  assert.ok(samples.length >= 3 && samples.every(s => s.length === count), 'Need multiple complete quick-wall samples');
  for (let slot = 0; slot < count; slot++)
    assert.ok(new Set(samples.map(sample => sample[slot])).size >= 2, `Frozen final pixels on slot ${slot + 1}`);
}
function inspect(image, { order = ORDER, dynamic = true, inset = 0, quick = false } = {}) {
  const grid = geometry(order, quick);
  const scale = Math.min((image.width - inset * 2) / 960, (image.height - inset * 2) / 540);
  assert.ok(scale > 0 && image.width >= 320 && image.height >= 180, 'Client is too small');
  const left = (image.width - scale * 960) / 2, top = (image.height - scale * 540) / 2;
  const sampleCanvas = (x, y) => image.pixel(Math.floor(left + x * scale), Math.floor(top + y * scale));
  const near = (actual, expected, message, tolerance = 48) => assert.ok(actual.every((v, i) => Math.abs(v - expected[i]) <= tolerance), message + ': ' + actual.join(','));
  const counters = [];
  order.forEach((channel, slot) => {
    const x0 = slot % grid.columns * grid.width, y0 = Math.floor(slot / grid.columns) * grid.height;
    const sample = (x, y) => sampleCanvas(x0 + grid.padX + x * grid.fit, y0 + grid.padY + y * grid.fit);
    for (const [x, y] of [[40, 70], [260, 70], [160, 150]]) near(sample(x, y), pattern.COLORS[channel], `Wrong channel ${channel + 1} in tile ${slot}`);
    if (grid.padY > 8) for (const y of [grid.padY / 2, grid.height - grid.padY / 2])
      near(sampleCanvas(x0 + grid.width / 2, y0 + y), [0, 0, 0], `Wrong SCALE_INNER bar in tile ${slot}`, 30);
    if (grid.padX > 8) for (const x of [grid.padX / 2, grid.width - grid.padX / 2])
      near(sampleCanvas(x0 + x, y0 + grid.height / 2), [0, 0, 0], `Wrong SCALE_INNER bar in tile ${slot}`, 30);
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
  if (!quick) for (const [x, y] of [[810, 350], [900, 480], [700, 500]])
    near(sampleCanvas(x, y), [0, 0, 0], 'Sixth tile must be empty', 30);
  for (let slot = order.length; slot < grid.columns * grid.rows; slot++)
    for (const offset of [0.25, 0.5, 0.75])
      near(sampleCanvas((slot % grid.columns + offset) * grid.width,
        (Math.floor(slot / grid.columns) + offset) * grid.height), [0, 0, 0], 'Unused quick-wall cell must be empty', 30);
  return counters;
}
function inspectEmpty(image, { inset = 0 } = {}) {
  const scale = Math.min((image.width - inset * 2) / 960, (image.height - inset * 2) / 540);
  assert.ok(scale > 0 && image.width >= 320 && image.height >= 180, 'Client is too small');
  const left = (image.width - scale * 960) / 2, top = (image.height - scale * 540) / 2;
  for (let y = 12; y < 540; y += 24) for (let x = 12; x < 960; x += 24) {
    const rgb = image.pixel(Math.floor(left + x * scale), Math.floor(top + y * scale));
    assert.ok(rgb.every(v => v <= 30), 'Protected preview retained visible media');
  }
  return [];
}
// Evidence only: a frozen slot needs a cause, so every sample also reports
// content digests of the whole client and of each tile region. Identical digests
// across samples say which region stopped repainting without changing any
// colour, marker or timecode assertion.
const fnv1a = (values) => {
  let hash = 0x811c9dc5;
  for (const value of values) { hash ^= value; hash = Math.imul(hash, 0x01000193) >>> 0; }
  return hash.toString(16).padStart(8, '0');
};
function sceneTransform(image, { inset = 0 } = {}) {
  const scale = Math.min((image.width - inset * 2) / 960, (image.height - inset * 2) / 540);
  return { scale, left: (image.width - scale * 960) / 2, top: (image.height - scale * 540) / 2 };
}
function tileDigests(image, options = {}) {
  const { order = ORDER, quick = false } = options;
  const grid = geometry(order, quick);
  const { scale, left, top } = sceneTransform(image, options);
  return order.map((channel, slot) => {
    const x0 = slot % grid.columns * grid.width, y0 = Math.floor(slot / grid.columns) * grid.height;
    const values = [];
    for (let y = 0; y < 180; y += 12) for (let x = 0; x < 320; x += 16)
      values.push(...image.pixel(Math.floor(left + (x0 + grid.padX + x * grid.fit) * scale),
        Math.floor(top + (y0 + grid.padY + y * grid.fit) * scale)));
    return fnv1a(values);
  });
}
function clientDigest(image) {
  const stepX = Math.max(1, Math.round(image.width / 120)), stepY = Math.max(1, Math.round(image.height / 68));
  const values = [];
  for (let y = 0; y < image.height; y += stepY) for (let x = 0; x < image.width; x += stepX)
    values.push(...image.pixel(x, y));
  return fnv1a(values);
}
function analyze(directory, options) {
  const samples = [];
  for (let i = 0; i < 8; i++) {
    let size = '';
    try {
      const bytes = fs.readFileSync(path.join(directory, `client-${i}.bmp`));
      assert.ok(bytes.length <= 64 * 1024 * 1024, 'Oversized screenshot');
      const image = pattern.bitmap(bytes);
      size = ` (bitmap ${image.width}x${image.height})`;
      const counters = options.empty ? inspectEmpty(image, options) : inspect(image, options);
      samples.push({ sample: i, passed: true, width: image.width, height: image.height, counters,
        clientDigest: clientDigest(image),
        tileDigests: options.empty ? [] : tileDigests(image, options) });
    } catch (error) {
      // fs errors contain local paths; public synthetic summaries must not.
      const message = error.code && error.code !== 'ERR_ASSERTION' ? `Synthetic client sample unavailable (${error.code})` : String(error.message).slice(0, 200) + size;
      samples.push({ sample: i, passed: false, error: message });
    }
  }
  let temporalProgress = options.empty || !options.dynamic, progressError;
  if (options.dynamic && !options.empty) {
    try {
      const counters = samples.filter(s => s.passed).map(s => s.counters);
      if (options.quick) quickProgress(counters, options.order.length); else pattern.progress(counters);
      temporalProgress = true;
    }
    catch (error) { progressError = String(error.message); }
  }
  // Which region stopped repainting: one tile, several tiles or the whole client.
  const verified = samples.filter(s => s.passed);
  const distinctClientCount = new Set(verified.map(s => s.clientDigest)).size;
  const distinctTileCounts = options.empty ? [] : options.order.map(
    (_, slot) => new Set(verified.map(s => s.tileDigests[slot])).size);
  const staleTiles = options.empty || !options.dynamic ? [] :
    distinctTileCounts.map((count, slot) => count === 1 && verified.length >= 3 ? slot : -1).filter(slot => slot >= 0);
  return { passed: samples.every(s => s.passed) && temporalProgress, samples, temporalProgress,
    distinctClientCount, distinctTileCounts, staleTiles,
    ...(progressError ? { progressError } : {}) };
}
function synthetic(width, height, { order = ORDER, counter = 3, inset = 0, dynamic = true, quick = false } = {}) {
  const grid = geometry(order, quick);
  const sources = order.map(c => pattern.frame(c, counter));
  const scale = Math.min((width - 2 * inset) / 960, (height - 2 * inset) / 540);
  const left = (width - 960 * scale) / 2, top = (height - 540 * scale) / 2;
  return { width, height, pixel(x, y) {
    const cx = (x + 0.5 - left) / scale, cy = (y + 0.5 - top) / scale;
    if (cx < 0 || cx >= 960 || cy < 0 || cy >= 540) return [0, 0, 0];
    const slot = Math.floor(cy / grid.height) * grid.columns + Math.floor(cx / grid.width);
    const sx = Math.floor((cx % grid.width - grid.padX) / grid.fit), sy = Math.floor((cy % grid.height - grid.padY) / grid.fit);
    if (slot >= order.length || sx < 0 || sx >= 320 || sy < 0 || sy >= 180) return [0, 0, 0];
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
  pattern.progress([0,1,2].map(counter => inspect(synthetic(960,540,{ counter, order: REPEAT_FIRST }), { order: REPEAT_FIRST })));
  assert.throws(() => inspect(synthetic(960,540,{ order: REPEAT_FIRST })), /Wrong channel/);
  assert.throws(() => inspect(synthetic(960,540), { order: REPEAT_FIRST }), /Wrong channel/);
  assert.deepEqual(inspectEmpty({ width: 960, height: 540, pixel: () => [0,0,0] }), []);
  assert.throws(() => inspectEmpty(synthetic(960,540)), /retained visible media/);
  for (const count of [1, 2, 3, 4, 7, 16, 64]) {
    const order = Array.from({ length: count }, (_, i) => i % 5);
    for (const [width, height, inset] of [[960, 540, 0], [1280, 760, 10]])
      assert.deepEqual(inspect(synthetic(width, height, { order, inset, quick: true }), { order, inset, quick: true }), Array(count).fill(3));
    quickProgress([0, 1, 2].map(counter => inspect(synthetic(960, 540, { order, counter, quick: true }), { order, quick: true })), count);
    assert.throws(() => quickProgress(Array.from({ length: 8 }, () => Array(count).fill(3)), count), /Frozen/);
  }
  assert.throws(() => quickProgress([0, 1, 2].map(i => [i,i,i,i,i,i,0]), 7), /slot 7/);
  const wrong = [0, 1, 2, 3, 4, 0, 1];
  assert.throws(() => inspect(synthetic(960,540,{ order: wrong, quick: true }), { order: [1,1,2,3,4,0,1], quick: true }), /Wrong channel/);
  for (const [first, second] of [[3, 4], [3, 39]]) {
    const a = synthetic(960, 540, { counter: first }), b = synthetic(960, 540, { counter: second });
    assert.deepEqual(tileDigests(a, {}), tileDigests(a, {}));
    assert.notDeepEqual(tileDigests(a, {}), tileDigests(b, {}));
    assert.notEqual(clientDigest(a), clientDigest(b));
  }
  assert.equal(new Set(tileDigests(synthetic(960, 540, { order: REPEAT_FIRST }), { order: REPEAT_FIRST })).size, 1);
  for (const count of [1, 5, 7])
    assert.equal(tileDigests(synthetic(1280, 760, { order: Array.from({ length: count }, (_, i) => i % 5), quick: true, inset: 10 }),
      { order: Array.from({ length: count }, (_, i) => i % 5), quick: true, inset: 10 }).length, count);
  assert.equal(tileDigests(synthetic(601, 400, { inset: 10 }), { inset: 10 }).length, 5);
  console.log('PASS: 3x2 SCALE_INNER, Preview inset, colors, markers, all five temporal channels and negative cases');
}
if (require.main === module) {
  const [mode, ...args] = process.argv.slice(2);
  if (mode === 'selftest') selftest();
  else if (mode === 'fixture') {
    const channel = Number(args[0]);
    assert.ok(Number.isInteger(channel) && channel >= 0 && channel < 5);
    fs.writeFileSync(args[1], Buffer.concat(Array.from({ length: pattern.FRAMES }, (_, counter) => pattern.frame(channel,counter))), { flag: 'wx' });
  } else if (mode === 'analyze' || mode === 'analyze-empty') {
    const [directory, role, order, dynamic] = args;
    assert.ok(['main-preview', 'program-projector', 'program-fullscreen', 'fixed-scene-1', 'fixed-scene-2', 'fixed-scene-fullscreen-1', 'fixed-scene-fullscreen-2'].includes(role));
    const quick = /^quick-[1-5](,[1-5]){0,63}$/.test(order);
    assert.ok(quick || ['forward', 'reverse', 'repeat-first'].includes(order));
    const channels = quick ? order.slice(6).split(',').map(c => Number(c) - 1) : order === 'reverse' ? REVERSED : order === 'repeat-first' ? REPEAT_FIRST : ORDER;
    console.log(JSON.stringify(analyze(directory, { inset: role === 'main-preview' ? 10 : 0,
      empty: mode === 'analyze-empty', order: channels, quick, dynamic: dynamic === 'true' })));
  } else throw new Error('Expected selftest, fixture or analyze');
}
module.exports = { inspect, inspectEmpty, analyze, synthetic, tileDigests, clientDigest };
