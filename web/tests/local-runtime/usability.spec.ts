import { expect, test, type Page } from '@playwright/test';

const fixture = '/tests/harness/usability.html';
const metrics = async (page: Page) => JSON.parse(await page.locator('html').getAttribute('data-fixture-metrics') ?? '{}');

test('edits the real Studio canvas over live video without renegotiating on drag or resize', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(`${fixture}?layout#/studio`);
  await page.getByRole('button', { name: '布局编辑', exact: true }).click();
  const stage = page.locator('.stage-live');
  await expect(stage.locator('video')).toHaveCount(2);
  await expect.poll(() => stage.locator('video').first().evaluate((video: HTMLVideoElement) => video.videoWidth)).toBe(640);
  const offers = await page.locator('html').getAttribute('data-fixture-offers');
  const tile = stage.locator('.camera-tile').first();
  const before = await tile.boundingBox();
  await page.mouse.move(before!.x + 50, before!.y + 50); await page.mouse.down();
  await page.mouse.move(before!.x + 90, before!.y + 80, { steps: 8 }); await page.mouse.up();
  await expect.poll(async () => (await tile.boundingBox())!.x).toBeGreaterThan(before!.x + 15);
  const handle = tile.getByRole('button', { name: /调整.*尺寸/ });
  await handle.scrollIntoViewIfNeeded();
  const grip = await handle.boundingBox();
  const width = (await tile.boundingBox())!.width;
  await page.mouse.move(grip!.x + grip!.width / 2, grip!.y + grip!.height / 2); await page.mouse.down();
  await page.mouse.move(grip!.x + 35, grip!.y + 25, { steps: 6 }); await page.mouse.up();
  await expect.poll(async () => (await tile.boundingBox())!.width).toBeGreaterThan(width + 10);
  expect(await page.locator('html').getAttribute('data-fixture-offers')).toBe(offers);
  await expect.poll(() => stage.locator('video').first().evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0);
  await page.getByRole('checkbox', { name: '实时画面', exact: true }).uncheck();
  await expect(page.locator('.stage video')).toHaveCount(0);
  await page.getByRole('checkbox', { name: '实时画面', exact: true }).check();
  await expect(page.locator('.stage video')).toHaveCount(2);
});

test('persists mixer controls, filters video-only cameras and hides the mixer in true fullscreen', async ({ page }) => {
  await page.goto(`${fixture}?area=monitor&mixer`);
  const mixer = page.getByRole('region', { name: 'Audio Mixer', exact: true });
  await expect(mixer.locator('.audio-mixer-channel')).toHaveCount(1);
  await expect(mixer).toContainText('有声音的摄像机');
  const mute = mixer.getByRole('button', { name: '有声音的摄像机 静音' });
  await mute.click(); await expect(mute).toHaveAttribute('aria-pressed', 'false');
  const monitor = mixer.getByRole('button', { name: '有声音的摄像机 本地监听' });
  await monitor.click(); await expect(monitor).toHaveAttribute('aria-pressed', 'false');
  await mixer.getByRole('slider', { name: '有声音的摄像机 音量' }).fill('0.42');
  await expect.poll(async () => (await metrics(page)).monitorSaves.at(-1)?.sourceAudio?.['audio-source-1']).toEqual({ volume: .42, muted: false, monitor: false });
  await page.getByText('逐路统计 / 声音告警', { exact: true }).click();
  await expect(page.locator('.monitor-decoration-options fieldset')).toHaveCount(1);
  await page.getByRole('checkbox', { name: '显示全部来源（包括无音轨）', exact: true }).check();
  await expect(mixer.locator('.audio-mixer-channel')).toHaveCount(2);
  await expect(page.locator('.monitor-decoration-options fieldset')).toHaveCount(2);
  await expect(mixer.getByRole('button', { name: '无音轨摄像机 静音' })).toBeDisabled();
  await page.getByRole('button', { name: '测试真全屏', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true);
  await expect(mixer).toBeHidden();
  await page.evaluate(() => document.exitFullscreen());
  await expect(mixer).toBeVisible();
  // Leaving and returning exercises account preference readback, without reloading the in-memory fixture.
  await page.getByRole('button', { name: '设备与来源', exact: true }).click();
  await page.getByRole('button', { name: '监看 Monitor', exact: true }).click();
  await expect(page.getByRole('button', { name: '有声音的摄像机 静音' })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('slider', { name: '有声音的摄像机 音量' })).toHaveValue('0.42');
});

test('shows bounded probe failure, supports manual-only mode and refreshes recovered health', async ({ page }) => {
  await page.goto(`${fixture}?probe-fail`);
  const row = page.locator('.catalog-record').first();
  await row.getByRole('button', { name: '详情', exact: true }).click();
  await row.getByRole('button', { name: '探测轨道', exact: true }).click();
  await expect(row.getByRole('alert')).toContainText('探测连接超时');
  await expect(row).toContainText('连续探测失败 10 次');
  await row.getByRole('checkbox', { name: '自动探测' }).uncheck();
  await expect(row).toContainText('仅手动探测');
  await row.getByRole('button', { name: '探测轨道', exact: true }).click();
  await expect(row.locator('.catalog-health')).toContainText('在线');
  await expect(row).toContainText('探测成功');
  await expect(row.getByRole('alert')).toHaveCount(0);
});

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

test('validates and saves runtime settings together, preserving edits after a failed save', async ({ page }) => {
  await page.goto(`${fixture}?area=settings&settings-fail=1`);
  const form = page.getByRole('form', { name: '运行设置' });
  const timeout = form.getByRole('spinbutton', { name: '探测超时（秒）' });
  const save = form.getByRole('button', { name: '保存设置', exact: true });
  await expect(timeout).toHaveValue('8');
  await expect(save).toBeDisabled();
  await timeout.fill(''); await expect(save).toBeDisabled();
  await timeout.fill('31'); await expect(save).toBeDisabled();
  await timeout.fill('12');
  await form.getByRole('combobox', { name: '默认传输方式' }).selectOption('rtsp-tcp');
  expect((await metrics(page)).settingsPatches).toHaveLength(0);
  await save.click(); await expect(timeout).toBeDisabled();
  await expect(form.getByRole('alert')).toContainText('输入已保留');
  await expect(timeout).toHaveValue('12');
  await save.click();
  await expect(form.getByRole('status')).toContainText('系统设置已保存');
  expect((await metrics(page)).settingsPatches).toEqual([
    { defaultTransportMode: 'rtsp-tcp', probeTimeoutSeconds: 12 },
    { defaultTransportMode: 'rtsp-tcp', probeTimeoutSeconds: 12 },
  ]);
  await expect(save).toBeDisabled();
});

test('keeps unsaved settings when navigation is cancelled and supports undo', async ({ page }) => {
  await page.goto(`${fixture}?area=settings`);
  const timeout = page.getByRole('spinbutton', { name: '探测超时（秒）' });
  await timeout.fill('15');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('complementary', { name: '主导航', exact: true }).getByRole('button', { name: '设备与来源' }).click();
  await expect(timeout).toHaveValue('15');
  await page.getByRole('button', { name: '撤销修改', exact: true }).click();
  await expect(timeout).toHaveValue('8');
  expect((await metrics(page)).settingsPatches).toHaveLength(0);
});

test('handles issue failures and keyboard dismissal without losing focus', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: () => Promise.reject(new Error('denied')) } }));
  await page.goto(`${fixture}?issues=1&issues-fail=1`);
  const toggle = page.getByRole('button', { name: /问题中心/ });
  await toggle.click();
  const dialog = page.getByRole('dialog', { name: '问题中心' });
  await expect(dialog.locator('.problem-card')).toHaveCount(1);
  await dialog.getByRole('button', { name: '确认', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '确认中…', exact: true })).toBeDisabled();
  await expect(dialog.getByRole('alert')).toContainText('失败');
  await dialog.getByRole('button', { name: '确认', exact: true }).click();
  await expect(dialog.getByRole('status')).toContainText('问题已确认');
  expect((await metrics(page)).acknowledgments).toBe(2);
  await dialog.getByRole('button', { name: '复制脱敏诊断' }).click();
  await expect(dialog.getByRole('alert')).toContainText('手动选择并复制');
  await dialog.getByRole('combobox', { name: '问题状态' }).selectOption('resolved');
  await expect(dialog.locator('.problem-card')).toContainText('已恢复的测试摄像机');
  await page.keyboard.press('Escape'); await expect(toggle).toBeFocused();
});

test('does not rewrite monitor preferences on entry and preserves decorations from another scene', async ({ page }) => {
  await page.goto(`${fixture}?area=monitor`);
  const quality = page.getByRole('combobox', { name: '监控画质' });
  await expect(quality).toHaveValue('medium');
  await page.waitForTimeout(600);
  expect((await metrics(page)).monitorSaves).toHaveLength(0);
  await quality.selectOption('high');
  await page.getByRole('combobox', { name: '监控画面填充', exact: true }).selectOption('contain');
  await expect.poll(async () => (await metrics(page)).monitorSaves.length).toBe(1);
  expect((await metrics(page)).monitorSaves[0].sourceDecorations['other-scene-source'].audioMeter.opacity).toBe(.6);
});

test('flushes monitor edits on navigation and serializes successive changes', async ({ page }) => {
  await page.goto(`${fixture}?area=monitor`);
  const quality = page.getByRole('combobox', { name: '监控画质' });
  await quality.selectOption('low');
  await expect.poll(async () => (await metrics(page)).activeSaves).toBe(1);
  await quality.selectOption('high');
  await page.getByRole('complementary', { name: '主导航', exact: true }).getByRole('button', { name: '设备与来源' }).click();
  await expect.poll(async () => (await metrics(page)).monitorSaves.length).toBe(2);
  expect((await metrics(page)).monitorSaves.map((view: { streamQuality: string }) => view.streamQuality)).toEqual(['low', 'high']);
  expect((await metrics(page)).maxConcurrentSaves).toBe(1);
  await page.getByRole('complementary', { name: '主导航', exact: true }).getByRole('button', { name: /监看 Monitor/ }).click();
  await expect(quality).toHaveValue('high');
});

test('deletes an active account profile and clears its shared selection', async ({ page }) => {
  await page.goto(`${fixture}?area=settings&profile=1`);
  await expect(page.getByRole('combobox', { name: '当前档案' })).toHaveValue('fixture-profile');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '删除档案', exact: true }).click();
  await expect(page.getByRole('button', { name: '导入 JSON', exact: true })).toBeDisabled();
  await expect(page.getByText('账号配置已删除。', { exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: '当前档案' })).toHaveValue('');
  expect((await metrics(page)).preferenceWrites).toContainEqual({ path: '/api/v2/account/preferences/active-profile', value: { id: null } });
});

test('keeps settings and the issue drawer within a narrow mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${fixture}?area=settings&issues=1`);
  await expect(page.getByRole('heading', { name: '运行设置', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: /问题中心/ }).click();
  const dialog = page.getByRole('dialog', { name: '问题中心' });
  const bounds = await dialog.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeInViewport();
});

test('cancels pending monitor writes when the account is cleared', async ({ page }) => {
  await page.goto(`${fixture}?area=monitor`);
  const quality = page.getByRole('combobox', { name: '监控画质' });
  await quality.selectOption('low');
  await expect.poll(async () => (await metrics(page)).activeSaves).toBe(1);
  await quality.selectOption('high');
  await page.getByRole('button', { name: '模拟退出清理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '设备与来源', exact: true })).toBeVisible();
  await page.waitForTimeout(700);
  expect((await metrics(page)).monitorSaves).toHaveLength(0);
});

test('recovers the monitor from a stalled preference read without writing defaults back', async ({ page }) => {
  await page.goto(`${fixture}?area=monitor&monitor-timeout=1`);
  await expect(page.getByText('正在读取监控偏好…', { exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: '监控画质' })).toHaveValue('medium', { timeout: 12000 });
  await expect(page.getByText('账号配置：待连接服务器', { exact: true })).toBeVisible();
  expect((await metrics(page)).monitorSaves).toHaveLength(0);
});
