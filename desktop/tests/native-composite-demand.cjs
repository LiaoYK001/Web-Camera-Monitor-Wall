const assert = require('node:assert/strict');
const path = require('node:path');
const { createRequire } = require('node:module');
const { chromium, expect } = createRequire(path.resolve(__dirname, '../../web/package.json'))('@playwright/test');

async function exerciseCompositeDemand(origin, headers, gatewayApiPort) {
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
    const beforeFault = await video.evaluate(v => v.getVideoPlaybackQuality().totalVideoFrames);
    await expect.poll(() => video.evaluate(v => v.getVideoPlaybackQuality().totalVideoFrames), { timeout: 10000 }).toBeGreaterThan(beforeFault);
    // Kick only the publisher in this isolated product, leaving the actual
    // viewer to exercise transport loss, retry and publisher recovery.
    const gateway = `http://127.0.0.1:${gatewayApiPort}`;
    const program = await (await fetch(gateway + '/v3/paths/get/program')).json();
    assert.match(program.source?.id || '', /^[0-9a-f-]{36}$/);
    assert.equal((await fetch(gateway + '/v3/webrtcsessions/kick/' + program.source.id, { method: 'POST' })).status, 200);
    await expect.poll(async () => {
      const path = await fetch(gateway + '/v3/paths/get/program');
      if (!path.ok) return false;
      const state = await path.json();
      return state.ready && state.source?.id && state.source.id !== program.source.id;
    }, { timeout: 90000 }).toBeTruthy();
    await expect.poll(() => video.evaluate(v => v.readyState >= 2 && v.videoWidth > 0), { timeout: 45000 }).toBe(true);
    const recoveredStamp = await video.evaluate(v => v.currentTime);
    await expect.poll(() => video.evaluate(v => v.currentTime), { timeout: 15000 }).toBeGreaterThan(recoveredStamp + 1);
    // Recovery refreshed negotiation demand, so wait for its normal grace
    // period before testing that closing the reader releases the publisher.
    await page.waitForTimeout(47000);
    await page.close();
    await expect.poll(async () => (await status()).publish, { timeout: 15000 }).toBe('idle');
    assert.equal((await fetch(origin + '/api/v1/health')).status, 200);
    // Starting again must reset output stop state and create fresh media.
    const resumed = await context.newPage(); await resumed.goto(origin + '/#projector-composite');
    const again = resumed.locator('video').first();
    await expect.poll(() => again.evaluate(v => v.readyState >= 2 && v.videoWidth > 0), { timeout: 45000 }).toBe(true);
    const resumedStamp = await again.evaluate(v => v.currentTime);
    await expect.poll(() => again.evaluate(v => v.currentTime), { timeout: 10000 }).toBeGreaterThan(resumedStamp + 1);
    console.log('On-demand Composite: healthy idle, actual decode, live reader retention, publisher fault recovery, stop and actual restart decode passed');
  } finally { await browser.close(); }
}
module.exports = { exerciseCompositeDemand };
