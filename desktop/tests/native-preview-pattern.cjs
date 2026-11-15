// TEST ONLY: known pixels, not a brightness-based health check for cameras.
const assert = require('node:assert/strict');
const WIDTH = 320, HEIGHT = 180, FRAMES = 40, FPS = 10;
const COLORS = [[216, 50, 50], [50, 200, 80], [50, 100, 220], [220, 190, 50], [180, 60, 200]];
const DIGITS = ['111101101101111', '010110010010111', '111001111100111', '111001111001111', '101101111001001',
  '111100111001111', '111100111101111', '111001001001001', '111101111101111', '111101111001111'];
function frame(channel, counter) {
  assert.ok(Number.isInteger(channel) && channel >= 0 && channel < 5);
  assert.ok(Number.isInteger(counter) && counter >= 0 && counter < FRAMES);
  const pixels = Buffer.alloc(WIDTH * HEIGHT * 3), color = COLORS[channel];
  for (let at = 0; at < pixels.length; at += 3) { pixels[at] = color[0]; pixels[at + 1] = color[1]; pixels[at + 2] = color[2]; }
  const box = (x, y, w, h, rgb) => {
    for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) {
      const at = (yy * WIDTH + xx) * 3;
      pixels[at] = rgb[0]; pixels[at + 1] = rgb[1]; pixels[at + 2] = rgb[2];
    }
  };
  const black = [0, 0, 0], white = [255, 255, 255];
  box(16, 16, 32, 24, white); box(272, 140, 32, 24, black);
  // Human-readable road number and incrementing frame/time (10 fps, 4s loop).
  const digits = [channel + 1, Math.floor(counter / 10), counter % 10];
  digits.forEach((digit, index) => {
    box(70 + index * 30, 16, 24, 42, black);
    [...DIGITS[digit]].forEach((bit, i) => { if (bit === '1') box(73 + index * 30 + i % 3 * 6, 22 + Math.floor(i / 3) * 6, 6, 6, white); });
  });
  // Machine-readable temporal code; independent of text rasterization.
  for (let bit = 0; bit < 6; bit++) box(80 + bit * 28, 92, 20, 32, counter & (1 << bit) ? white : black);
  return pixels;
}
function bitmap(bytes) {
  assert.ok(Buffer.isBuffer(bytes) && bytes.length >= 54 && bytes.toString('ascii', 0, 2) === 'BM', 'Invalid screenshot BMP');
  const offset = bytes.readUInt32LE(10), header = bytes.readUInt32LE(14);
  const width = bytes.readInt32LE(18), signedHeight = bytes.readInt32LE(22), height = Math.abs(signedHeight);
  const bits = bytes.readUInt16LE(28), compression = bytes.readUInt32LE(30);
  assert.ok(header >= 40 && width > 0 && width <= 8192 && height > 0 && height <= 8192 && [24, 32].includes(bits) && compression === 0, 'Unsupported screenshot BMP');
  const stride = Math.ceil(width * bits / 32) * 4;
  assert.ok(offset >= 14 + header && offset + stride * height <= bytes.length, 'Truncated screenshot BMP');
  return { width, height, pixel(x, y) {
    assert.ok(x >= 0 && x < width && y >= 0 && y < height);
    const at = offset + (signedHeight > 0 ? height - 1 - y : y) * stride + x * (bits / 8);
    return [bytes[at + 2], bytes[at + 1], bytes[at]];
  } };
}
function inspect(image, canvas, { dynamic = true, order = [0, 1, 2, 3, 4] } = {}) {
  assert.ok(canvas.width > 0 && canvas.height > 0 && order.length === 5);
  const scale = Math.min(image.width / canvas.width, image.height / canvas.height);
  const w = canvas.width * scale, h = canvas.height * scale, left = (image.width - w) / 2, top = (image.height - h) / 2;
  const counters = [];
  order.forEach((channel, slot) => {
    const sample = (x, y) => image.pixel(Math.floor(left + (slot + x / WIDTH) * w / 5), Math.floor(top + y / HEIGHT * h));
    const near = (actual, expected, message, tolerance = 48) => assert.ok(actual.every((value, i) => Math.abs(value - expected[i]) <= tolerance), message + ': ' + actual.join(','));
    // Known channel color and asymmetric fiducials detect black, missing,
    // swapped, stretched-to-wrong-position and vertically flipped pictures.
    for (const [x, y] of [[40, 70], [260, 70], [160, 150]]) near(sample(x, y), COLORS[channel], `Wrong/missing channel ${channel + 1} in slot ${slot}`);
    if (!dynamic) return;
    near(sample(32, 28), [255, 255, 255], `Channel ${channel + 1} white location marker`);
    near(sample(288, 152), [0, 0, 0], `Channel ${channel + 1} black location marker`);
    let counter = 0;
    for (let bit = 0; bit < 6; bit++) {
      const rgb = sample(90 + bit * 28, 108), white = rgb.every(v => v >= 200), black = rgb.every(v => v <= 55);
      assert.ok(white || black, `Channel ${channel + 1} invalid temporal bit ${bit}`);
      if (white) counter |= 1 << bit;
    }
    assert.ok(counter < FRAMES, `Channel ${channel + 1} invalid temporal counter`); counters.push(counter);
  });
  return counters;
}
function progress(samples) {
  assert.ok(samples.length >= 3 && samples.every(sample => sample.length === 5), 'Need multiple complete five-channel samples');
  for (let channel = 0; channel < 5; channel++) assert.ok(new Set(samples.map(sample => sample[channel])).size >= 2, `Frozen final pixels on channel ${channel + 1}`);
}
module.exports = { WIDTH, HEIGHT, FRAMES, FPS, COLORS, frame, bitmap, inspect, progress };
