import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';

type User = { id: string; username: string; password: string; revision: string };
type Users = Record<'admin' | 'operator' | 'viewerGroup' | 'viewerCamera' | 'auditor' | 'exporter', User>;

const credentialsPath = process.env.WEBOBS_M7_BROWSER_CREDENTIALS;
if (!credentialsPath) throw new Error('WEBOBS_M7_BROWSER_CREDENTIALS is required');
const users = JSON.parse(fs.readFileSync(credentialsPath, 'utf8')) as Users;

async function login(page: Page, user: User, route = 'monitor') {
  await page.goto(`/#/${route}`);
  await page.getByLabel('用户名').fill(user.username);
  await page.getByLabel('密码').fill(user.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '主导航' })).toBeVisible();
}

async function status(page: Page, path: string, init?: { method?: string; body?: unknown; revision?: string }) {
  return page.evaluate(async ({ target, options }) => {
    const headers: Record<string, string> = {};
    if (options?.body !== undefined) headers['Content-Type'] = 'application/json';
    if (options?.revision) headers['If-Match'] = `"${options.revision}"`;
    const response = await fetch(target, {
      method: options?.method ?? 'GET', headers,
      body: options?.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: 'same-origin', cache: 'no-store',
    });
    return response.status;
  }, { target: path, options: init });
}

test('managed roles and camera/group scopes are enforced by the server', async ({ browser }) => {
  const checks: Array<[keyof Users, string, number]> = [
    ['admin', '/api/v2/users', 200],
    ['operator', '/api/v2/users', 403],
    ['operator', '/api/v2/recordings?cameraId=fixture-01', 200],
    ['operator', '/api/v2/recordings?cameraId=fixture-02', 403],
    ['viewerGroup', '/api/v2/recordings?cameraId=fixture-01', 200],
    ['viewerGroup', '/api/v2/recordings?cameraId=fixture-04', 200],
    ['viewerGroup', '/api/v2/recordings?cameraId=fixture-08', 403],
    ['viewerCamera', '/api/v2/recordings?cameraId=fixture-02', 200],
    ['viewerCamera', '/api/v2/recordings?cameraId=fixture-01', 403],
    ['auditor', '/api/v2/recordings?cameraId=fixture-01', 200],
    ['auditor', '/api/v2/nodes', 403],
    ['exporter', '/api/v2/recordings?cameraId=fixture-01', 200],
    ['exporter', '/api/v2/storage-volumes', 403],
  ];
  for (const [name, path, expected] of checks) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await login(page, users[name]);
    expect(await status(page, path), `${name}: ${path}`).toBe(expected);
    await context.close();
  }
});

test('cluster UI exposes nodes, storage, timeline and verified S3 playback', async ({ page }) => {
  await login(page, users.admin, 'admin');
  await expect(page.getByRole('heading', { name: '集群、权限与灾备' })).toBeVisible();
  await expect(page.getByText('3 nodes')).toBeVisible();
  await expect(page.getByText('3 volumes')).toBeVisible();
  const timeline = page.getByText(/跨节点录像目录（[1-9][0-9]*）/);
  await expect(timeline).toBeVisible();
  await timeline.click();
  const playback = page.getByRole('button', { name: '校验并回放' }).first();
  await expect(playback).toBeVisible();
  await expect(playback).toBeEnabled();
  await playback.click();
  await expect(page.getByText('归档录像已在浏览器本地完成大小与 SHA-256 校验。')).toBeVisible();
  await expect(page.locator('.archive-verified-preview video')).toBeVisible();
});

test('disabled user session is rejected on its next protected request', async ({ browser }) => {
  const adminContext = await browser.newContext();
  const viewerContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const viewer = await viewerContext.newPage();
  await login(admin, users.admin);
  const username = `gate-revoked-${Date.now()}`;
  const password = `Gate-${crypto.randomUUID()}-${crypto.randomUUID()}`;
  const created = await admin.evaluate(async ({ username: value, password: secret }) => {
    const response = await fetch('/api/v2/users', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: value, password: secret, roles: ['viewer'],
        scopes: [{ kind: 'camera', id: 'fixture-01' }] }),
    });
    return { status: response.status, body: await response.json() as { id: string; revision: number } };
  }, { username, password });
  expect(created.status).toBe(201);
  await login(viewer, { id: created.body.id, username, password, revision: String(created.body.revision) });
  expect(await status(viewer, '/api/v2/recordings?cameraId=fixture-01')).toBe(200);
  expect(await status(admin, `/api/v2/users/${created.body.id}`, {
    method: 'PATCH', body: { enabled: false }, revision: String(created.body.revision),
  })).toBe(200);
  expect(await status(viewer, '/api/v2/recordings?cameraId=fixture-01')).toBe(403);
  await adminContext.close();
  await viewerContext.close();
});

test('installed application shell starts while the controller is offline', async ({ context, page }) => {
  await login(page, users.admin);
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('complementary', { name: '主导航' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  await context.setOffline(true);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByText(/登录监控工作台|监看 Monitor/).first()).toBeVisible();
  await context.setOffline(false);
});
