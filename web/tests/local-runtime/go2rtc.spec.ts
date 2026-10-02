import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({ json: { authenticated: true, user: 'go2rtc-fixture', via: 'session' } }));
  await page.route('**/api/v1/auth/setup', (route) => route.fulfill({ json: { registrationOpen: false } }));
});

test('go2rtc has its own route and exposes the complete official UI', async ({ page }) => {
  await page.route('**/api/v1/go2rtc/api', (route) => route.fulfill({ json: { version: '1.9.14' } }));
  await page.route('**/api/v1/go2rtc/', (route) => route.fulfill({ contentType: 'text/html', body: '<h1>Streams fixture</h1>' }));
  await page.route('**/api/v1/go2rtc/config.html', (route) => route.fulfill({ contentType: 'text/html', body: '<h1>Config fixture</h1>' }));
  await page.goto('/#/go2rtc');
  await expect(page.getByRole('heading', { name: 'go2rtc 管理' })).toBeVisible();
  await expect(page.getByText('已连接 1.9.14')).toBeVisible();
  await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Streams fixture' })).toBeVisible();
  await page.getByRole('button', { name: '配置', exact: true }).click();
  await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Config fixture' })).toBeVisible();
  await expect(page.getByRole('link', { name: '独立打开 WebUI' })).toHaveAttribute('href', '/api/v1/go2rtc/config.html');
  await page.getByRole('button', { name: '接入设备与来源' }).click();
  await expect.poll(() => page.evaluate(() => location.hash)).toBe('#/devices');
});

test('permission failures do not mount an upstream iframe', async ({ page }) => {
  await page.route('**/api/v1/go2rtc/api', (route) => route.fulfill({ status: 403, json: {} }));
  await page.goto('/#/go2rtc');
  await expect(page.getByRole('alert')).toContainText('需要管理员的系统设置权限');
  await expect(page.locator('iframe')).toHaveCount(0);
});

test('an unavailable service can be retried and uses no cached response', async ({ page }) => {
  let ready = false;
  await page.route('**/api/v1/go2rtc/api', (route) => ready
    ? route.fulfill({ json: { version: '1.9.14' } })
    : route.fulfill({ status: 503, json: {} }));
  await page.route('**/api/v1/go2rtc/', (route) => route.fulfill({ contentType: 'text/html', body: '<h1>Recovered</h1>' }));
  await page.goto('/#/go2rtc');
  await expect(page.getByRole('alert')).toContainText('go2rtc 服务暂不可用');
  ready = true;
  await page.getByRole('button', { name: '重新连接', exact: true }).click();
  await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Recovered' })).toBeVisible();
});
