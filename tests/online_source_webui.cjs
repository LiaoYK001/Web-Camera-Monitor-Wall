// Shared real browser/Android WebView workflow. Run only against an isolated fixture backend.
const { createRequire } = require('node:module');
const requireWeb = createRequire(require('node:path').resolve(__dirname, '../web/package.json'));
const { expect } = requireWeb('@playwright/test');
const assertOnlineVideo = exports.assertOnlineVideo = async (page, base, name) => {
  await page.goto(base + '/api/v1/go2rtc/stream.html?src=' + name + '&mode=mse');
  await page.locator('video').click();
  await page.locator('video').evaluate(video => { video.muted = true; return video.play(); });
  await page.waitForFunction(() => { const video = document.querySelector('video'); return video?.readyState >= 2 && video.videoWidth === 160; }, null, { timeout: 60000 });
  const stamp = await page.locator('video').evaluate(video => video.currentTime);
  await expect.poll(() => page.locator('video').evaluate(video => video.currentTime), { timeout: 15000 }).toBeGreaterThan(stamp + .25);
};
exports.exerciseOnlineSources = async (page, base) => {
  for (const [engine, relative] of [['yt-dlp', 'index.html'], ['streamlink', 'live.m3u8']]) {
    const name = 'website-fixture-' + engine;
    await page.goto(base + '/#go2rtc');
    const region = page.getByRole('region', { name: '网站与直播源' });
    await region.getByLabel('接入方式').selectOption(engine);
    await region.getByLabel('流名称', { exact: true }).fill(name);
    await region.getByLabel('视频网页或直播地址').fill('http://127.0.0.1:19090/' + relative);
    await region.getByRole('button', { name: '保存命名流并重启 go2rtc' }).click();
    await expect.poll(async () => {
      const alert = region.getByRole('alert');
      const error = await alert.count() ? await alert.textContent() : '';
      if (error) throw new Error(error);
      return region.getByRole('status').textContent().catch(() => '');
    }, { timeout: 20000 }).toContain('已保存');
    await expect(page.locator('.go2rtc-stream-list')).toContainText(name);
    // Actual MSE bytes and decoded frames come through the authenticated product proxy.
    await assertOnlineVideo(page, base, name);
    await page.goto(base + '/#go2rtc');
    const row = page.locator('.go2rtc-stream-list > div').filter({ has: page.getByText(name, { exact: true }) });
    await row.getByRole('button', { name: '检测并添加设备', exact: true }).click();
    await expect(row.getByRole('button', { name: '已在设备目录', exact: true })).toBeVisible({ timeout: 60000 });
    const registry = await page.evaluate(async () => (await (await fetch('/api/v1/cameras', { credentials: 'same-origin', cache: 'no-store' })).json()).cameras);
    expect(registry.some(camera => camera.name === name && camera.adapter === 'rtsp' && camera.profiles.length)).toBe(true);
    console.log(engine + ': actual source form, authenticated MSE frame decoding and device import passed');
  }
};
