import { expect, test, type Page } from '@playwright/test';

const fixture = '/tests/harness/usability.html';
const metrics = async (page: Page) => JSON.parse(await page.locator('html').getAttribute('data-fixture-metrics') ?? '{}');

test('debounces search and ignores an earlier response arriving after the current result', async ({ page }) => {
  await page.goto(fixture);
  await expect(page.locator('.catalog-record')).toHaveCount(24);
  const search = page.getByRole('textbox', { name: '搜索设备' });
  await search.fill('s'); await search.fill('sl'); await search.fill('slow');
  await expect.poll(async () => (await metrics(page)).queries).toContain('slow');
  await search.fill('大门');
  await expect(page.locator('.catalog-record')).toHaveCount(1);
  await expect(page.locator('.catalog-record')).toContainText('大门入口');
  // Wait for the intentionally late fixture response: it must not replace the current row.
  await page.waitForTimeout(1000);
  await expect(page.locator('.catalog-record')).toContainText('大门入口');
  const queries = (await metrics(page)).queries;
  expect(queries).not.toContain('s'); expect(queries).not.toContain('sl');
});

test('pages through large catalogs, keeps selection on its page, and recovers from an empty search', async ({ page }) => {
  await page.goto(fixture);
  await expect(page.locator('.catalog-record')).toHaveCount(24);
  await page.getByRole('checkbox', { name: '全选当前页', exact: true }).check();
  await expect(page.getByRole('group', { name: '已选 24 台' })).toBeVisible();
  await page.getByRole('button', { name: '下一页' }).click();
  await expect(page.locator('.catalog-record').first()).toContainText('25');
  await expect(page.locator('.catalog-batch-bar')).toHaveCount(0);
  await page.getByRole('button', { name: '下一页' }).click();
  await expect(page.locator('.catalog-record')).toHaveCount(5);
  await expect(page.getByRole('button', { name: '下一页' })).toBeDisabled();
  await page.getByRole('textbox', { name: '搜索设备' }).fill('不存在');
  await expect(page.getByRole('heading', { name: '没有匹配的设备' })).toBeVisible();
  await page.getByRole('button', { name: '重置筛选条件' }).click();
  await expect(page.locator('.catalog-record')).toHaveCount(24);
});

test('stops a bulk import after the current item and retains the unprocessed rows', async ({ page }) => {
  await page.goto(fixture);
  await page.getByRole('button', { name: '批量添加', exact: true }).click();
  const input = page.getByRole('textbox', { name: '批量视频源' });
  await input.fill('一号 | rtsp://one.example.invalid/live\n二号 | rtsp://two.example.invalid/live\n三号 | rtsp://three.example.invalid/live');
  await page.getByRole('button', { name: '添加 3 项', exact: true }).click();
  await expect(input).toBeDisabled();
  await page.getByRole('button', { name: '停止后续添加' }).click();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue('二号 | rtsp://two.example.invalid/live\n三号 | rtsp://three.example.invalid/live');
  expect((await metrics(page)).imports).toBe(1);
});

test('supports keyboard dismissal and restores focus after a 4K preview', async ({ page }) => {
  await page.goto(fixture);
  const preview = page.getByRole('button', { name: '预览', exact: true }).first();
  await preview.click();
  const dialog = page.getByRole('dialog', { name: '独立来源预览' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('3840×2160');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(preview).toBeFocused();
});

test('makes every page reachable on a phone without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(fixture);
  await expect(page.locator('.catalog-record')).toHaveCount(24);
  await expect(page.locator('.catalog-health').first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: '更多', exact: true }).click();
  const menu = page.getByRole('dialog', { name: '全部页面' });
  await expect(menu.getByRole('button', { name: '录像回放', exact: true })).toBeVisible();
  await menu.getByRole('button', { name: '我的账号', exact: true }).click();
  await expect(page.getByRole('heading', { name: '我的账号', exact: true })).toBeVisible();
  await expect(menu).toHaveCount(0);
});

test('does not save on load and combines rapid layout adjustments into one ordered write', async ({ page }) => {
  await page.goto(fixture);
  await expect(page.locator('.catalog-record')).toHaveCount(24);
  await page.waitForTimeout(500);
  expect((await metrics(page)).saves).toHaveLength(0);
  const picker = page.getByRole('group', { name: '工作区风格', exact: true });
  await picker.getByRole('button', { name: '经典', exact: true }).click();
  await picker.getByRole('button', { name: 'OBS 风格', exact: true }).click();
  await picker.getByRole('button', { name: '经典', exact: true }).click();
  await expect.poll(async () => (await metrics(page)).saves.length).toBe(1);
  expect((await metrics(page)).saves[0].style).toBe('classic');
  expect((await metrics(page)).maxConcurrentSaves).toBe(1);
});

test('preserves the latest layout when returning to the original choice during a save', async ({ page }) => {
  await page.goto(fixture);
  await expect(page.locator('.catalog-record')).toHaveCount(24);
  const picker = page.getByRole('group', { name: '工作区风格', exact: true });
  await picker.getByRole('button', { name: '经典', exact: true }).click();
  await expect.poll(async () => (await metrics(page)).activeSaves).toBe(1);
  await picker.getByRole('button', { name: 'OBS 风格', exact: true }).click();
  await expect.poll(async () => (await metrics(page)).saves.length).toBe(2);
  expect((await metrics(page)).saves.at(-1).style).toBe('obs');
  expect((await metrics(page)).maxConcurrentSaves).toBe(1);
});
