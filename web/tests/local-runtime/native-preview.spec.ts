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
  await expect(page.getByRole('heading', { name: 'Program 已交给原生窗口显示' })).toBeVisible();
  await expect(page.locator('video')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => Number(document.documentElement.dataset.fixtureDeletes || 0))).toBe(5);
  await page.getByRole('button', { name: '浏览器媒体', exact: true }).click();
  await expect(page.locator('.direct-tile.live')).toHaveCount(5);
  expect(await page.evaluate(() => (window as any).nativeFixture.operations.filter((op: string) => op !== 'status'))).toEqual(['open', 'close']);
});
