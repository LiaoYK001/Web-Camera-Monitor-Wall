import { expect, test } from '@playwright/test';

test('Android read-only preflight sees real Studio edits, failed saves and discard', async ({ page, context }) => {
  await context.routeWebSocket('**/api/v1/ws', () => {});
  let releaseSave: (() => void) | undefined;
  const scene = { schemaVersion: 5, revision: 1, id: 'main', name: '主场景', canvas: { width: 1920, height: 1080, backgroundColor: '#000000' }, sources: [], items: [] };
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/setup') return route.fulfill({ json: { registrationOpen: false } });
    if (path === '/api/v1/auth/session') return route.fulfill({ json: { authenticated: true, user: 'update-fixture', via: 'session' } });
    if (path === '/api/v2/account/me') return route.fulfill({ json: { username: 'update-fixture', roles: ['admin'], permissions: ['settings.manage', 'scenes.manage'] } });
    if (path.includes('/preferences/')) return route.fulfill({ json: { value: null } });
    if (path === '/api/v1/scene') return route.fulfill({ json: scene });
    if (path === '/api/v1/studio') {
      if (route.request().method() !== 'GET') {
        await new Promise<void>(resolve => { releaseSave = resolve; });
        return route.fulfill({ status: 503, json: { error: 'Fixture save unavailable' } });
      }
      return route.fulfill({ json: { schemaVersion: 1, revision: 1, programSceneId: 'main', previewSceneId: 'main', scenes: [scene], transition: { kind: 'cut', durationMs: 0 } } });
    }
    if (path === '/api/v1/cameras') return route.fulfill({ json: { cameras: [] } });
    if (path.endsWith('/capabilities')) return route.fulfill({ json: { modes: { direct: { enabled: true }, composite: { enabled: false } }, scenes: [], sources: [] } });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/#studio');
  const work = () => page.evaluate(() => window.webobsUpdateWork?.());
  await expect(page.getByLabel('场景名称')).toBeVisible();
  await expect.poll(work).toEqual({ dirty: false, exporting: false });
  await page.getByLabel('场景名称').fill('更新前草稿');
  await expect.poll(work).toEqual({ dirty: true, exporting: false });
  expect(await page.evaluate(() => JSON.stringify(window.webobsUpdateWork?.()))).not.toContain('更新前草稿');
  await page.getByRole('button', { name: '保存并应用', exact: true }).click();
  await expect.poll(work).toEqual({ dirty: true, exporting: true });
  releaseSave!();
  await expect.poll(work).toEqual({ dirty: true, exporting: false });
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '放弃', exact: true }).click();
  await expect.poll(work).toEqual({ dirty: false, exporting: false });
});

test('native preflight tracks overlapping export tasks and removes finished owners', async ({ page }) => {
  await page.goto('/tests/harness/offline-workspace.html');
  const states = await page.evaluate(async () => {
    const { desktopTask } = await import('/src/desktopRuntime.ts');
    const first = desktopTask('fixture-one'), second = desktopTask('fixture-two');
    const both = window.webobsUpdateWork!(); first();
    const remaining = window.webobsUpdateWork!(); second();
    return { both, remaining, finished: window.webobsUpdateWork!() };
  });
  expect(states.both).toEqual({ dirty: false, exporting: true });
  expect(states.remaining).toEqual({ dirty: false, exporting: true });
  expect(states.finished).toEqual({ dirty: false, exporting: false });
});
