const assert = require('node:assert/strict');
const path = require('node:path');
const { createRequire } = require('node:module');
const { chromium, expect } = createRequire(path.resolve(__dirname, '../../web/package.json'))('@playwright/test');

async function exerciseCompositeDemand(origin, headers) {
  const status = async () => (await fetch(origin + '/api/v1/program/status', { headers })).json();
  assert.equal((await status()).publish, 'idle', 'Direct startup must not publish Composite');
  assert.equal((await fetch(origin + '/api/v1/health')).status, 200, 'Standby is healthy');
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ serviceWorkers: 'block', extraHTTPHeaders: headers });
    const page = await context.newPage();
    await page.goto(origin + '/#projector-composite');
    const video = page.locator('video').first();
    await expect.poll(() => video.evaluate(v => v.readyState >= 2 && v.videoWidth > 0), { timeout: 45000 }).toBe(true);
    const stamp = await video.evaluate(v => v.currentTime);
    await expect.poll(() => video.evaluate(v => v.currentTime), { timeout: 10000 }).toBeGreaterThan(stamp + 1);
    assert.equal((await status()).publish, 'publishing');
    // Keep a real viewer beyond the negotiation grace period: demand must use
    // gateway readers rather than a timer that interrupts an active session.
    await page.waitForTimeout(47000);
    assert.equal((await status()).publish, 'publishing');
    await page.close();
    await expect.poll(async () => (await status()).publish, { timeout: 15000 }).toBe('idle');
    assert.equal((await fetch(origin + '/api/v1/health')).status, 200);
    // Starting again must reset output stop state and create fresh media.
    const resumed = await context.newPage(); await resumed.goto(origin + '/#projector-composite');
    const again = resumed.locator('video').first();
    await expect.poll(() => again.evaluate(v => v.readyState >= 2 && v.videoWidth > 0), { timeout: 45000 }).toBe(true);
    const resumedStamp = await again.evaluate(v => v.currentTime);
    await expect.poll(() => again.evaluate(v => v.currentTime), { timeout: 10000 }).toBeGreaterThan(resumedStamp + 1);
    console.log('On-demand Composite: healthy idle, actual decode, live reader retention, stop and actual restart decode passed');
  } finally { await browser.close(); }
}
module.exports = { exerciseCompositeDemand };
