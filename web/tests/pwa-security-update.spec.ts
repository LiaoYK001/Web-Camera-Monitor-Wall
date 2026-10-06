import { expect, test, type Page } from '@playwright/test';
import { origin, pwaServer, studio } from './harness/pwaServer';

// A real HTTP origin is needed: Playwright route() does not intercept worker-owned
// API requests. This serves the actual production-built SW, not a worker imitation.
const fixture = pwaServer();
test.describe.configure({ mode: 'default' });
test.use({ baseURL: origin });
test.beforeAll(() => fixture.start());
test.afterAll(() => fixture.close());
test.beforeEach(() => fixture.reset());

async function controlled(page: Page) {
  await page.evaluate(async () => {
    await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise<void>(resolve => navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true }));
  });
}
async function upgrade(pages: Page[]) {
  const before = await Promise.all(pages.map(p => p.evaluate(() => performance.timeOrigin)));
  fixture.upgrade();
  await pages[0].evaluate(async () => { await (await navigator.serviceWorker.getRegistration())!.update(); });
  for (let i = 0; i < pages.length; i++) {
    await expect.poll(async () => pages[i].evaluate(() => performance.timeOrigin).catch(() => before[i]), { timeout: 8000 }).not.toBe(before[i]);
    await pages[i].waitForLoadState('domcontentloaded');
  }
}
async function seed(page: Page, queued = false) {
  await page.goto('/tests/harness/pwa-seed.html');
  await page.waitForFunction(() => typeof (window as any).pwaSeed === 'function');
  await page.evaluate(async ({ studio, queued }) => { await (window as any).pwaSeed(studio, queued); }, { studio, queued });
}
const notice = (page: Page) => page.getByRole('status', { name: '安全更新恢复提示' });

// Red case before the continuity fix: forced replacement discards the draft,
// but the new UI gives no explanation or recovery boundaries.
test('dirty Studio and fixed projector reload immediately with honest transient-loss notice', async ({ page, context }) => {
  await page.goto('/#/studio');
  await controlled(page);
  await expect(page.getByLabel('场景名称')).toHaveValue('Saved a');
  const projector = await context.newPage();
  await projector.goto('/#projector?scene=scene-a');
  await expect(projector.locator('[data-projector-scene="scene-a"]')).toBeVisible();
  await expect(projector).toHaveTitle('Saved a · 场景投影');
  await page.getByLabel('场景名称').fill('UNSAVED-DRAFT-CANARY');
  const writes = fixture.state.mutations.length;
  await upgrade([page, projector]);
  await expect(page.getByLabel('场景名称')).toHaveValue('Saved a');
  await expect(notice(page)).toContainText('未保存');
  await expect(notice(page)).toContainText('无法恢复');
  await expect(projector.locator('[data-projector-scene="scene-a"]')).toBeVisible();
  await expect(projector).toHaveTitle('Saved a · 场景投影');
  expect(new URL(projector.url()).hash).toBe('#projector?scene=scene-a');
  expect(fixture.state.mutations.slice(writes).filter(v => /studio|scene|exports/.test(v))).toEqual([]);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain('UNSAVED-DRAFT-CANARY');
});

// Red case before the fix: useDeviceSync's mount timer silently uploads the
// durable queue when the replacement document returns online.
test('encrypted saved profile and offline queue survive without automatic recovery upload', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'onLine', { get: () => sessionStorage.getItem('pwa-fixture-offline') !== '1' }));
  await seed(page, true);
  await page.evaluate(() => sessionStorage.setItem('pwa-fixture-offline', '1'));
  fixture.state.offline = true;
  await page.goto('/#/studio');
  await controlled(page);
  await expect(page.getByLabel('场景名称')).toHaveValue('Saved a');
  await expect(page.getByText(/项等待同步/).first()).toBeVisible();
  fixture.state.offline = false;
  await page.evaluate(() => sessionStorage.removeItem('pwa-fixture-offline'));
  await upgrade([page]);
  await expect(page.getByLabel('场景名称')).toHaveValue('Saved a');
  // Observe beyond the existing two-second automatic sync timer.
  await expect(async () => {
    await expect(notice(page)).toContainText('立即同步');
    expect(fixture.state.syncPosts).toBe(0);
  }).toPass({ timeout: 5000 });
  await page.waitForTimeout(2500);
  expect(fixture.state.syncPosts).toBe(0);
  await page.reload();
  await expect(notice(page)).toBeVisible();
  expect(fixture.state.syncPosts).toBe(0);
  await page.getByRole('button', { name: '查看同步与配对' }).click();
  await page.getByRole('button', { name: '立即同步', exact: true }).click();
  await expect.poll(() => fixture.state.syncPosts).toBe(1);
  const reader = await page.context().newPage();
  await reader.goto('/tests/harness/pwa-seed.html');
  await reader.waitForFunction(() => !!(window as any).pwaRead);
  const saved = await reader.evaluate(async () => (window as any).pwaRead());
  expect(saved.profiles.some((p: any) => p.name === 'Saved device profile')).toBe(true);
  expect(saved.queue?.mutations ?? []).toEqual([]);
});

test('accepted evidence export with lost response reconciles after update without duplicate submission', async ({ page }, testInfo) => {
  fixture.state.loseExportResponse = true;
  await page.goto('/#/archive');
  await controlled(page);
  await page.getByRole('button', { name: '快速导出', exact: true }).click();
  // The fixture destroys the socket without a response. Chromium may then resend the
  // identical request itself (no application retry exists in this codebase), so the
  // contract is asserted on request identity and on what the server accepted, never
  // on a raw HTTP count that the page cannot control.
  await expect.poll(() => fixture.state.exportRequestIds.length).toBeGreaterThan(0);
  await expect.poll(() => new Set(fixture.state.exportRequestIds).size).toBe(1);
  await expect.poll(() => fixture.state.jobs.length).toBe(1);
  const postsBeforeUpdate = fixture.state.exportPosts;
  await upgrade([page]);
  await expect(page.getByRole('region', { name: '导出任务' })).toContainText('正在导出');
  // The update path itself submits nothing and never invents a second identity.
  await page.waitForTimeout(2500);
  expect(fixture.state.exportPosts).toBe(postsBeforeUpdate);
  expect(new Set(fixture.state.exportRequestIds).size).toBe(1);
  expect(fixture.state.jobs.length).toBe(1);
  await expect(page.getByRole('button', { name: '恢复同一次提交' })).toHaveCount(0);
  await expect(notice(page)).toContainText('任务列表');
  testInfo.annotations.push({ type: 'raw-http-posts', description: String(postsBeforeUpdate) });
});

test('legacy client without acknowledgement reloads gate and never caches private routes', async ({ page, context }) => {
  fixture.state.authenticated = false;
  await page.goto('/');
  await controlled(page);
  await page.getByLabel('密码', { exact: true }).fill('PASSWORD-TRANSIENT-CANARY');
  const stale = await context.newPage();
  await stale.goto('/tests/harness/pwa-seed.html'); // no update listener or acknowledgements
  await upgrade([page, stale]);
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible();
  await expect(page.getByLabel('密码', { exact: true })).toHaveValue('');
  const result = await page.evaluate(async () => {
    await fetch('/api/v1/auth/session');
    await fetch('/recordings/private-canary.mp4');
    const entries: string[] = [];
    for (const name of await caches.keys()) for (const request of await (await caches.open(name)).keys()) entries.push(request.url);
    return { entries, storage: JSON.stringify({ ...localStorage, ...sessionStorage }) };
  });
  expect(result.entries.some(url => ['/api/', '/recordings/'].some(prefix => new URL(url).pathname.startsWith(prefix)))).toBe(false);
  expect(result.storage).not.toContain('PASSWORD-TRANSIENT-CANARY');
  await expect(notice(page)).toBeVisible();
});
