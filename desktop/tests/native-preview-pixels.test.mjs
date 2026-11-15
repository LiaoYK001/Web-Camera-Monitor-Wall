import test from 'node:test';
import assert from 'node:assert/strict';
import pattern from './native-preview-pattern.cjs';
const { WIDTH, HEIGHT, COLORS, FRAMES, frame, bitmap, inspect, progress } = pattern;
const canvas = { width: WIDTH * 5, height: HEIGHT };
function image(channels = [0, 1, 2, 3, 4], counters = [0, 3, 9, 17, 39]) {
  const frames = channels.map((channel, i) => channel === null ? Buffer.alloc(WIDTH * HEIGHT * 3) : frame(channel, counters[i]));
  return { width: canvas.width, height: canvas.height, pixel(x, y) {
    const slot = Math.floor(x / WIDTH), at = (y * WIDTH + x % WIDTH) * 3;
    return [...frames[slot].subarray(at, at + 3)];
  } };
}
test('known five-channel final pixels identify colors, spatial markers and incrementing temporal codes', () => {
  assert.deepEqual(inspect(image(), canvas), [0, 3, 9, 17, 39]);
  assert.deepEqual(inspect(image([4, 3, 2, 1, 0]), canvas, { order: [4, 3, 2, 1, 0] }), [0, 3, 9, 17, 39]);
  for (let counter = 0; counter < FRAMES; counter++) assert.deepEqual(inspect(image(undefined, Array(5).fill(counter)), canvas), Array(5).fill(counter));
});
test('final pixels reject black, missing, swapped, duplicated and flipped sources despite healthy callback counters', () => {
  assert.throws(() => inspect(image([null, null, null, null, null]), canvas), /Wrong\/missing/);
  assert.throws(() => inspect(image([0, 1, null, 3, 4]), canvas), /channel 3/);
  assert.throws(() => inspect(image([1, 0, 2, 3, 4]), canvas), /channel 1/);
  assert.throws(() => inspect(image([0, 0, 0, 0, 0]), canvas), /channel 2/);
  const correct = image();
  assert.throws(() => inspect({ ...correct, pixel: (x, y) => correct.pixel(x, HEIGHT - 1 - y) }, canvas), /marker/);
});
test('known scene-only colors test Program binding without assuming every camera must be bright', () => {
  const staticImage = { ...canvas, pixel: x => COLORS[Math.floor(x / WIDTH)] };
  assert.deepEqual(inspect(staticImage, canvas, { dynamic: false }), []);
  assert.deepEqual(frame(0, 0).subarray((152 * WIDTH + 288) * 3, (152 * WIDTH + 288) * 3 + 3), Buffer.alloc(3));
});
test('each of five final windows regions must change; a single frozen tile fails', () => {
  progress([[0, 1, 2, 3, 4], [1, 2, 3, 4, 5], [2, 3, 4, 5, 6]]);
  assert.throws(() => progress([[0, 1, 2, 3, 4], [1, 2, 2, 4, 5], [2, 3, 2, 5, 6]]), /Frozen final pixels on channel 3/);
  assert.throws(() => progress([[0, 1, 2, 3, 4]]), /multiple complete/);
});
test('pixel check handles OBS letterboxing in physical client coordinates', () => {
  const source = image(), padded = { width: source.width, height: source.height + 120,
    pixel: (x, y) => y >= 60 && y < HEIGHT + 60 ? source.pixel(x, y - 60) : [0, 0, 0] };
  assert.deepEqual(inspect(padded, canvas), [0, 3, 9, 17, 39]);
});
test('bounded BMP parser supports bottom-up 24bit and top-down 32bit captures and rejects truncation', () => {
  for (const bits of [24, 32]) for (const topDown of [false, true]) {
    const bytesPerPixel = bits / 8, stride = Math.ceil(2 * bits / 32) * 4;
    const bytes = Buffer.alloc(54 + stride * 2); bytes.write('BM'); bytes.writeUInt32LE(54, 10); bytes.writeUInt32LE(40, 14);
    bytes.writeInt32LE(2, 18); bytes.writeInt32LE(topDown ? -2 : 2, 22); bytes.writeUInt16LE(bits, 28);
    const row = topDown ? 0 : 1; bytes[54 + row * stride + bytesPerPixel] = 11;
    bytes[54 + row * stride + bytesPerPixel + 1] = 22; bytes[54 + row * stride + bytesPerPixel + 2] = 33;
    assert.deepEqual(bitmap(bytes).pixel(1, 0), [33, 22, 11]);
    assert.throws(() => bitmap(bytes.subarray(0, bytes.length - 1)), /Truncated/);
  }
  assert.throws(() => bitmap(Buffer.alloc(54)), /Invalid/);
});
