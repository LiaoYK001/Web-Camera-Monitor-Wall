import { expect, test, type Page } from '@playwright/test';

const fixture = '/tests/harness/usability.html';
const metrics = async (page: Page) => JSON.parse(await page.locator('html').getAttribute('data-fixture-metrics') ?? '{}');

test('finds pages by purpose, supports keyboard selection and focuses the destination', async ({ page }) => {
  await page.goto(fixture);
  await page.keyboard.press('Control+k');
  const dialog = page.getByRole('dialog', { name: '快速切换页面' });
  const search = dialog.getByRole('textbox', { name: '搜索页面名称或功能' });
  await expect(search).toBeFocused();
  await search.fill('找不到的功能');
  await expect(dialog.getByRole('status')).toContainText('没有匹配的页面');
  await search.fill('更新');
  await page.keyboard.press('Enter');
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '系统设置', exact: true })).toBeVisible();
  await expect(page.locator('#workspace-main')).toBeFocused();
  await page.keyboard.press('Control+k');
  await search.fill(''); await page.keyboard.press('End'); await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: '我的账号', exact: true })).toBeVisible();
});

test('keeps a cancelled settings draft and the quick switch dialog open', async ({ page }) => {
  await page.goto(`${fixture}?area=settings`);
  const timeout = page.getByRole('spinbutton', { name: '探测超时（秒）' });
  await timeout.fill('15');
  await page.keyboard.press('Control+k');
  const dialog = page.getByRole('dialog', { name: '快速切换页面' });
  await dialog.getByRole('textbox').fill('设备与来源');
  page.once('dialog', (prompt) => prompt.dismiss());
  await page.keyboard.press('Enter');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(timeout).toHaveValue('15');
  expect((await metrics(page)).settingsPatches).toHaveLength(0);
});

test('locks background scrolling and ignores dragging from the dialog to the backdrop', async ({ page }) => {
  await page.goto(fixture);
  const opener = page.getByRole('button', { name: '搜索页面', exact: true });
  await opener.click();
  const dialog = page.getByRole('dialog', { name: '快速切换页面' });
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe('hidden');
  const bounds = (await dialog.boundingBox())!;
  await page.mouse.move(bounds.x + 30, bounds.y + 60); await page.mouse.down();
  await page.mouse.move(3, 3); await page.mouse.up();
  await expect(dialog).toBeVisible();
  await page.mouse.click(3, 3);
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe('auto');
});

test('keeps mobile navigation open after cancelling a draft and reaches its close button after scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${fixture}?area=settings`);
  await page.getByRole('spinbutton', { name: '探测超时（秒）' }).fill('13');
  await page.getByRole('button', { name: '更多', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '全部页面' });
  page.once('dialog', (prompt) => prompt.dismiss());
  await dialog.getByRole('button', { name: '设备与来源', exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '我的账号', exact: true }).scrollIntoViewIfNeeded();
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeInViewport();
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(page.getByRole('spinbutton', { name: '探测超时（秒）' })).toHaveValue('13');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('jumps to settings sections, distinguishes save modes and respects reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`${fixture}?area=settings`);
  await page.getByRole('navigation', { name: '设置分区' }).getByRole('button', { name: '播放优化', exact: true }).click();
  await expect(page.locator('#settings-playback')).toBeFocused();
  await expect(page.locator('#settings-playback .save-mode-badge')).toHaveText('按账号立即保存');
  await page.getByRole('spinbutton', { name: '探测超时（秒）' }).fill('12');
  await expect(page.locator('#settings-runtime .save-mode-badge')).toHaveText('有未保存修改');
  await page.getByRole('navigation', { name: '设置分区' }).getByRole('button', { name: '关于与更新', exact: true }).click();
  await expect(page.locator('#settings-about')).toBeFocused();
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog')).toHaveCSS('animation-name', 'none');
});

test('filters scene sources without discarding selections and restores focus through consecutive dialogs', async ({ page }) => {
  await page.goto(`${fixture}?layout#/studio`);
  const scene = page.getByRole('button', { name: '选择场景 测试监控', exact: true });
  await scene.focus(); await page.keyboard.press('F2');
  const rename = page.getByRole('dialog', { name: '重命名场景', exact: true });
  await expect(rename.getByRole('textbox', { name: '场景名称' })).toBeFocused();
  await page.keyboard.press('Escape'); await expect(scene).toBeFocused();
  await page.getByRole('button', { name: '新建场景', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新建场景', exact: true });
  await dialog.getByRole('checkbox', { name: '有声音的摄像机', exact: true }).check();
  await dialog.getByRole('searchbox', { name: '搜索场景来源' }).fill('无音轨');
  await dialog.getByRole('checkbox', { name: '无音轨摄像机', exact: true }).check();
  await expect(dialog.getByRole('group', { name: '选择来源 · 已选 2/64' })).toBeVisible();
  await dialog.getByRole('searchbox').fill('');
  await expect(dialog.getByRole('checkbox', { name: '有声音的摄像机', exact: true })).toBeChecked();
  await dialog.getByRole('button', { name: '清空选择' }).click();
  await expect(dialog.getByRole('group', { name: '选择来源 · 已选 0/64' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '测试监控 场景选项' }).click();
  const menu = page.getByRole('dialog', { name: '测试监控 场景选项' });
  await menu.getByRole('menuitem', { name: '复制场景', exact: true }).focus();
  await page.keyboard.press('ArrowDown');
  await expect(menu.getByRole('menuitem', { name: '重命名', exact: true })).toBeFocused();
});

test('does not write unchanged or invalid bitrate fields and prevents repeat device submissions', async ({ page }) => {
  await page.goto(`${fixture}?catalog-delay`);
  const record = page.locator('.catalog-record').first();
  await record.getByRole('button', { name: '详情', exact: true }).click();
  const cap = record.getByRole('spinbutton', { name: '实时码率上限 kbps' });
  await cap.focus(); await cap.press('Tab');
  expect((await metrics(page)).catalogPatches).toHaveLength(0);
  await cap.fill('1'); await cap.press('Tab');
  await expect(record.getByRole('alert')).toContainText('32–1000000');
  expect((await metrics(page)).catalogPatches).toHaveLength(0);
  await cap.fill('500'); await cap.press('Tab');
  await expect(record.getByRole('button', { name: '处理中…' })).toBeDisabled();
  await expect.poll(async () => (await metrics(page)).catalogPatches).toHaveLength(1);
  await expect(record.getByRole('button', { name: '探测轨道' })).toBeEnabled();
  await record.getByRole('button', { name: '停用', exact: true }).evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(record.getByRole('button', { name: '保存中…' })).toBeDisabled();
  await expect(record.getByRole('button', { name: '启用', exact: true })).toBeEnabled();
  expect((await metrics(page)).catalogPatches).toHaveLength(2);
});

test('rolls back a failed profile toggle with a visible error', async ({ page }) => {
  await page.goto(`${fixture}?catalog-delay&catalog-fail`);
  const record = page.locator('.catalog-record').first();
  await record.getByRole('button', { name: '详情', exact: true }).click();
  const probe = record.getByRole('checkbox', { name: '自动探测' });
  await probe.uncheck(); await expect(probe).toBeDisabled();
  await expect(record.getByRole('alert')).toContainText('设备更新暂时失败');
  await expect(probe).toBeChecked(); await expect(probe).toBeEnabled();
});
