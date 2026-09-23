import { expect, test } from '@playwright/test';

test('keeps the authenticated session after StrictMode cancels its first effect', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'development-fixture', via: 'session' },
  }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  // Wait for the same IndexedDB work used by the offline fallback to settle.
  await page.evaluate(async () => {
    const runtimePath = '/src/localRuntime.ts';
    const runtime = await import(runtimePath);
    await runtime.localConfigState();
  });
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '登录监控工作台' })).toHaveCount(0);
});


test('offers open registration and enters the authenticated workspace', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({ status: 401, json: {} }));
  await page.route('**/api/v1/auth/options', (route) => route.fulfill({ json: { registrationEnabled: true } }));
  await page.route('**/api/v1/auth/register', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ username: 'new-viewer', password: 'registration-password-123' });
    await route.fulfill({ json: { authenticated: true, user: 'new-viewer' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '注册账号', exact: true }).click();
  await page.getByLabel('用户名', { exact: true }).fill('new-viewer');
  await page.getByLabel('密码', { exact: true }).fill('registration-password-123');
  await page.getByRole('button', { name: '注册并登录' }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
});
