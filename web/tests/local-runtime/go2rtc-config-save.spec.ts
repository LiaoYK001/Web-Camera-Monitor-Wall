import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

// Real packaged Monaco/editor/module; backend responses are browser fixtures.
async function editorFixture(page: import('@playwright/test').Page) {
  const assets = path.resolve('go2rtc-dist');
  const state = { config: 'streams: {}\n', active: {} as Record<string, object>,
    writes: 0, restarts: 0, recovering: 0, rejectSave: false, rejectRestart: false, alerts: [] as string[] };
  page.on('dialog', async dialog => { state.alerts.push(dialog.message()); await dialog.dismiss(); });
  await page.route('**/api/v1/auth/session', route => route.fulfill({json: {authenticated: true, user: 'admin', via: 'session'}}));
  await page.route('**/api/v1/auth/setup', route => route.fulfill({json: {registrationOpen: false}}));
  await page.route('**/api/v1/runtime/info', route => route.fulfill({json: {platform: 'windows', go2rtcRtspBase: 'rtsp://127.0.0.1:18554/'}}));
  await page.route('**/api/v1/cameras', route => route.fulfill({json: {cameras: []}}));
  await page.route('**/api/v1/go2rtc/**', async route => {
    const url = new URL(route.request().url());
    const target = url.pathname.slice('/api/v1/go2rtc/'.length);
    if (target === 'api') return route.fulfill({json: {version: '1.9.14'}});
    if (target === 'api/config') {
      if (route.request().method() === 'POST') {
        state.writes++;
        if (state.rejectSave) return route.fulfill({status: 400, body: 'invalid YAML'});
        state.config = route.request().postData()!;
      }
      return route.fulfill({contentType: 'application/yaml', body: state.config});
    }
    if (target === 'api/restart') {
      state.restarts++;
      if (state.rejectRestart) return route.fulfill({status: 503, json: {}});
      state.recovering = 3;
      state.active = {'saved-stream': {}};
      return route.fulfill({status: 202, json: {status: 'restarting'}});
    }
    if (target === 'api/streams') return state.recovering-- > 0
      ? route.fulfill({status: 503, json: {}}) : route.fulfill({json: state.active});
    const file = path.resolve(assets, target || 'index.html');
    if (!file.startsWith(assets + path.sep)) return route.abort();
    const body = await readFile(file).catch(() => null);
    if (!body) return route.fulfill({status: 404, body: ''});
    const extension = path.extname(file);
    return route.fulfill({body, contentType: extension === '.js' ? 'application/javascript'
      : extension === '.css' ? 'text/css' : extension === '.json' ? 'application/json' : 'text/html'});
  });
  return state;
}

async function edit(frame: import('@playwright/test').Frame, text: string) {
  await expect.poll(() => frame.evaluate(() => {
    const monaco = (window as unknown as {monaco?: {editor: {getModels(): {getValue(): string}[]}}}).monaco;
    return monaco?.editor.getModels()[0]?.getValue();
  })).toBe('streams: {}\n');
  await frame.evaluate(value => {
    (window as unknown as {monaco: {editor: {getModels(): {setValue(value: string): void}[]}}})
      .monaco.editor.getModels()[0].setValue(value);
  }, text);
}

test('packaged editor reloads before reporting success and refreshes parent without losing the editor', async ({page}) => {
  const state = await editorFixture(page);
  await page.goto('/#/go2rtc');
  await page.getByRole('button', {name: '配置', exact: true}).click();
  await expect(page.locator('iframe')).toBeVisible();
  const frame = await page.locator('iframe').contentFrame();
  await expect(frame.getByRole('button', {name: 'Save & Restart'})).toBeVisible();
  // FrameLocator is useful for controls; the actual Frame exposes Monaco.
  const actual = page.frames().find(value => value.url().endsWith('/config.html'))!;
  await edit(actual, 'streams:\n  saved-stream: rtsp://127.0.0.1:1/synthetic\n');
  await frame.getByRole('button', {name: 'Save & Restart'}).click();
  await expect.poll(() => state.restarts).toBe(1);
  expect(state.alerts).toEqual([]);
  await expect.poll(() => state.alerts[0]).toContain('配置已保存并生效');
  await expect(page.locator('.go2rtc-stream-list')).toContainText('saved-stream');
  expect(actual.isDetached()).toBe(false);
  expect(state.writes).toBe(1);
});

test('save rejection leaves the running service untouched', async ({page}) => {
  const state = await editorFixture(page); state.rejectSave = true;
  await page.goto('/api/v1/go2rtc/config.html');
  await edit(page.mainFrame(), 'streams: [invalid');
  await page.getByRole('button', {name: 'Save & Restart'}).click();
  await expect.poll(() => state.alerts[0]).toContain('配置未保存');
  expect(state.restarts).toBe(0);
  expect(state.config).toBe('streams: {}\n');
  await expect(page.getByRole('button', {name: 'Save & Restart'})).toBeEnabled();
});

test('restart rejection reports persisted configuration without claiming success', async ({page}) => {
  const state = await editorFixture(page); state.rejectRestart = true;
  await page.goto('/api/v1/go2rtc/config.html');
  const config = 'streams:\n  saved-stream: rtsp://127.0.0.1:1/synthetic\n';
  await edit(page.mainFrame(), config);
  await page.getByRole('button', {name: 'Save & Restart'}).click();
  await expect.poll(() => state.alerts[0]).toContain('重载尚未确认');
  expect(state.config).toBe(config);
  // The saved snapshot is the new baseline: a deliberate retry must work.
  state.rejectRestart = false;
  await page.getByRole('button', {name: 'Save & Restart'}).click();
  await expect.poll(() => state.alerts[1]).toContain('配置已保存并生效');
  expect(state.restarts).toBe(2);
});

test('concurrent external edits are preserved without restarting', async ({page}) => {
  const state = await editorFixture(page);
  await page.goto('/api/v1/go2rtc/config.html');
  await edit(page.mainFrame(), 'streams:\n  local-draft: rtsp://127.0.0.1:1/local\n');
  state.config = 'streams:\n  external: rtsp://127.0.0.1:1/external\n';
  await page.getByRole('button', {name: 'Save & Restart'}).click();
  await expect.poll(() => state.alerts[0]).toContain('Config was changed');
  expect(state.writes).toBe(0);
  expect(state.restarts).toBe(0);
});
