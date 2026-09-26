import { expect, test } from '@playwright/test';

test('keeps the authenticated session after StrictMode cancels its first effect', async ({ page }) => {
  await page.route('**/api/v1/auth/setup', (route) => route.fulfill({ json: { registrationOpen: false } }));
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'development-fixture', via: 'session' },
  }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '登录监控工作台' })).toHaveCount(0);
});


test('first administrator registration enters the authenticated workspace', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({ status: 401, json: {} }));
  await page.route('**/api/v1/auth/setup', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { registrationOpen: true } });
    expect(route.request().postDataJSON()).toEqual({ username: 'new-admin', password: 'registration-password-123' });
    return route.fulfill({ status: 201, json: { username: 'new-admin', roles: ['admin'] } });
  });
  await page.route('**/api/v1/auth/login', (route) => route.fulfill({ json: { authenticated: true, user: 'new-admin' } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '创建管理员账号' })).toBeVisible();
  await page.getByLabel('用户名', { exact: true }).fill('new-admin');
  await page.getByLabel('密码', { exact: true }).fill('registration-password-123');
  await page.getByRole('button', { name: '创建并登录' }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
});
