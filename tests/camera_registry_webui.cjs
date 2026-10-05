// Rendered product and real authenticated API. The named RTSP stream is synthetic.
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const { expect } = createRequire(require('node:path').resolve(__dirname, '../web/package.json'))('@playwright/test');
exports.exerciseCameraRegistry = async (page, base) => {
  await page.goto(base + '/#devices');
  const bridge = page.getByRole('region', { name: 'go2rtc 流接入' });
  await expect(bridge).toContainText('命名流');
  const row = bridge.locator('.go2rtc-stream-list > div').filter({ has: page.getByText('synthetic', { exact: true }) });
  await row.getByRole('button', { name: '检测并添加设备', exact: true }).click();
  await expect(row.getByRole('button', { name: '已在设备目录' })).toBeDisabled();
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.().exporting)).toBe(false);
  const camera = await page.evaluate(async () => {
    const response = await fetch('/api/v1/cameras', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('Cannot read isolated device directory');
    return (await response.json()).cameras.find(camera => camera.name === 'synthetic');
  });
  assert.match(camera.id, /^camera-[a-f0-9]{32}$/);
  assert.equal(camera.profiles[0].transportMode, 'rtsp-tcp');
  await page.getByRole('button', { name: '添加 / ONVIF 发现', exact: true }).click();
  const card = page.locator('.camera-card').filter({ has: page.getByRole('heading', { name: /^synthetic(?: ★)?$/ }) });
  await expect(card.getByLabel('分组', { exact: true })).toBeEnabled();
  await card.getByLabel('分组', { exact: true }).fill('Local fixture group');
  // A second account client changes another field against the same old baseline.
  const remote = await page.evaluate(async id => {
    const value = { displayName: 'synthetic', favorite: true, group: '' };
    const response = await fetch('/api/v2/account/preferences/camera-preferences', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: { cameras: { [id]: value } },
        baseValue: { cameras: { [id]: { ...value, favorite: false } } }, partial: true }),
    });
    return response.status;
  }, camera.id);
  assert.equal(remote, 200);
  await page.getByRole('button', { name: '重新读取设备与偏好' }).click();
  await expect(card.getByLabel('收藏')).toBeChecked();
  await expect(card.getByLabel('分组', { exact: true })).toHaveValue('Local fixture group');
  await card.getByRole('button', { name: '同步显示偏好' }).click();
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
  const saved = await page.evaluate(async id => (await (await fetch('/api/v2/account/preferences/camera-preferences')).json()).value.cameras[id], camera.id);
  assert.equal(saved.favorite, true); assert.equal(saved.group, 'Local fixture group');

  // Lose only the response after the real server accepted a camera creation.
  let submitted;
  await page.route('**/api/v1/cameras', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submitted = route.request().postDataJSON();
    const response = await route.fetch(); assert.equal(response.status(), 201);
    await route.abort('failed'); await page.unroute('**/api/v1/cameras');
  });
  await page.getByLabel('地址', { exact: true }).fill(camera.address);
  await page.getByRole('button', { name: '自动检测', exact: true }).click();
  await page.getByLabel('设备名称', { exact: true }).fill('Response loss fixture');
  await page.getByRole('button', { name: '保存到 Registry', exact: true }).click();
  await expect(page.getByRole('button', { name: '核对添加结果', exact: true })).toBeVisible();
  assert.equal(await page.evaluate(() => window.webobsUpdateWork?.().dirty), true);
  await page.getByRole('button', { name: '继续提交同一设备', exact: true }).click();
  await expect(page.getByRole('button', { name: '核对添加结果', exact: true })).not.toBeVisible();
  const matching = await page.evaluate(async id => (await (await fetch('/api/v1/cameras')).json()).cameras.filter(camera => camera.id === id).length, submitted.id);
  assert.equal(matching, 1);
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
  console.log('PASS: actual go2rtc import, account field merge/draft rebase and response-loss recovery with one stable device ID');
};
