import { expect, test } from '@playwright/test';

test('switching to native monitoring releases browser players and closes native when returning', async ({ page }) => {
  await page.setViewportSize({ width: 1800, height: 1800 });
  await page.addInitScript(() => {
    const state = { operations: [] as string[], requested: false };
    Object.assign(window, { nativeFixture: state, webobsDesktop: {
      version: 1, reportWork: async () => {},
      nativePreview: async (operation: string) => {
        state.operations.push(operation);
        if (operation === 'open') state.requested = true;
        if (operation === 'close') state.requested = false;
        return { supported: true, requested: state.requested, state: state.requested ? 2 : 0, frames: 25 };
      },
    } });
  });
  await page.goto('/tests/harness/usability.html?layout&raw-performance#/monitor');
  await expect(page.locator('.direct-tile.live')).toHaveCount(5);
  await page.getByRole('button', { name: 'Windows 原生监看（试验）', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Program 原生监看已请求' })).toBeVisible();
  await expect(page.getByText('不代表最终画面、媒体出帧或硬件解码', { exact: false })).toBeVisible();
  await expect(page.getByText('受控绘制诊断（不是画面验证）')).toHaveCount(0); // old backend remains supported
  await expect(page.locator('video')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => Number(document.documentElement.dataset.fixtureDeletes || 0))).toBe(5);
  await page.getByRole('button', { name: '浏览器媒体', exact: true }).click();
  await expect(page.locator('.direct-tile.live')).toHaveCount(5);
  expect(await page.evaluate(() => (window as any).nativeFixture.operations.filter((op: string) => op !== 'status'))).toEqual(['open', 'close']);
});

test('a guarded draw snapshot is diagnostic only, never final-pixel or hardware proof', async ({ page }) => {
  await page.addInitScript(() => {
    Object.assign(window, { webobsDesktop: {
      version: 1, reportWork: async () => {},
      nativePreview: async (operation: string) => ({ supported: true, requested: operation !== 'close', state: operation === 'close' ? 0 : 2, frames: 1445,
        draw_sample: { available: true, video_ready: true, main_texture_ready: true, output_bound: true,
          output_active: true, output_showing: true, base_width: 1920, base_height: 1080,
          display_width: 1280, display_height: 720, frame: 1440, sampled_at_ms: 1000 } }),
    } });
  });
  await page.goto('/tests/harness/usability.html?layout&raw-performance#/monitor');
  await page.getByRole('button', { name: 'Windows 原生监看（试验）', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Program 原生监看已请求' })).toBeVisible();
  await page.getByText('受控绘制诊断（不是画面验证）').click();
  await expect(page.getByText('最近采样回调：1440', { exact: false })).toBeVisible();
  await expect(page.getByText('不证明已 Present、五路出帧或硬解', { exact: false })).toBeVisible();
  await expect(page.getByText('Program 已交给原生窗口显示', { exact: true })).toHaveCount(0);
});
