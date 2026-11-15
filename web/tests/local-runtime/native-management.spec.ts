import { expect, test } from '@playwright/test';

// Real App and AudioWorkspace with in-memory APIs/fixture media, not host or camera qualification.
test('native management keeps Studio editable without automatic video or audio playback', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto('/tests/harness/usability.html?layout&native-management=1#/studio');
  await expect(page.getByRole('region', { name: 'WebOBS Wall 原生画面' })).toBeVisible();
  await expect(page.locator('video,audio')).toHaveCount(0);
  await page.getByRole('button', { name: '布局编辑', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '实时画面', exact: true })).toBeDisabled();
  const tile = page.locator('.stage .camera-tile').first();
  const before = await tile.boundingBox();
  expect(before).not.toBeNull();
  await page.mouse.move(before!.x + 50, before!.y + 50);
  await page.mouse.down();
  await page.mouse.move(before!.x + 90, before!.y + 80, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await tile.boundingBox())!.x).toBeGreaterThan(before!.x + 15);
  await expect(page.getByRole('button', { name: '保存并应用', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '放弃', exact: true }).click();
  await page.evaluate(() => { window.location.hash = 'monitor'; });
  await expect(page.getByRole('region', { name: 'WebOBS Wall 原生画面' })).toBeVisible();
  await expect(page.locator('video,audio')).toHaveCount(0);

  // Supply available selected audio tracks: absence of channels must be the
  // native-management policy, not a failed metadata probe or empty track list.
  await page.evaluate(() => {
    const fallback = window.fetch;
    window.fetch = async (input, init) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.pathname.endsWith('/audio-tracks')) return new Response(JSON.stringify({ tracks: [{
        index: 0, streamIndex: 1, codec: 'aac', channels: 1, channelLayout: 'mono', sampleRate: 48000,
        endpoint: `${url.pathname}/0/whep`,
      }] }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      return fallback(input, init);
    };
    window.location.hash = 'audio';
  });
  await expect(page.locator('.audio-track')).toHaveCount(2);
  await expect(page.getByRole('button', { name: '启用本地监听', exact: true })).toBeDisabled();
  await expect(page.locator('.audio-track-state').first()).toHaveText('浏览器试听关闭');
  await expect(page.locator('video,audio')).toHaveCount(0);
  expect(await page.locator('html').getAttribute('data-fixture-offers')).toBeNull();

  // Browser playback remains a deliberate action, and switching back retires it.
  await page.evaluate(() => { window.location.hash = 'monitor'; });
  await page.getByRole('button', { name: '浏览器媒体', exact: true }).click();
  await expect(page.locator('video')).toHaveCount(2);
  await expect.poll(async () => Number(await page.locator('html').getAttribute('data-fixture-offers'))).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Windows 原生画面', exact: true }).click();
  await expect(page.locator('video,audio')).toHaveCount(0);
});
