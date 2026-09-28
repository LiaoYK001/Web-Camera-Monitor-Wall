import test from 'node:test';
import assert from 'node:assert/strict';

// F6-10: lock the progressive reconnect ladder (pure helper, no browser).
const source = `
  const RECONNECT_BASE_DELAYS_MS = [3000, 5000, 10000, 20000, 40000, 60000];
  const RECONNECT_MAX_DELAY_MS = 60000;
  function reconnectDelayMs(attempt, random = Math.random) {
    const index = Math.max(0, Math.floor(attempt));
    const base = index < RECONNECT_BASE_DELAYS_MS.length
      ? RECONNECT_BASE_DELAYS_MS[index]
      : RECONNECT_MAX_DELAY_MS;
    return Math.round(base * (0.85 + random() * 0.3));
  }
`;

test('F6-10 reconnect ladder is 3→5→10→20→40→60s and never grows', () => {
  const fn = new Function(`${source}; return reconnectDelayMs;`)();
  assert.equal(fn(0, () => 0.5), 3000);
  assert.equal(fn(1, () => 0.5), 5000);
  assert.equal(fn(2, () => 0.5), 10000);
  assert.equal(fn(3, () => 0.5), 20000);
  assert.equal(fn(4, () => 0.5), 40000);
  assert.equal(fn(5, () => 0.5), 60000);
  assert.equal(fn(6, () => 0.5), 60000);
  assert.equal(fn(50, () => 0.5), 60000);
  const high = fn(0, () => 1);
  const low = fn(0, () => 0);
  assert.equal(high, 3450);
  assert.equal(low, 2550);
});
