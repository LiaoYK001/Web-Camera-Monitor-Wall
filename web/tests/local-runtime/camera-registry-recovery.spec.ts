import { expect, test, type Page } from '@playwright/test';

const fixture = '/tests/harness/device-controls.html';
const detection = (address: string) => ({ adapter: 'rtsp', address, probe: 'ready', profiles: [{
  id: 'main', name: 'Main', role: 'main', endpoint: address, videoCodec: 'h264', audioCodec: '', width: 640, height: 360, fps: 5,
}] });
const camera = (id = 'fixture-camera') => ({ id, name: 'Fixture camera', adapter: 'rtsp', address: 'rtsp://camera.example.invalid/live',
  profiles: detection('rtsp://camera.example.invalid/live').profiles, hardwareDecode: 'auto', health: 'unknown', capabilities: {} });
async function routes(page: Page, cameras: ReturnType<typeof camera>[] = []) {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/cameras') return route.fulfill({ json: { cameras } });
    if (path.includes('/preferences/')) return route.fulfill({ json: { value: { cameras: {} } } });
    if (path.includes('/analytics')) return route.fulfill({ json: { policies: [], revision: 1 } });
    if (path === '/api/v1/camera-detect') return route.fulfill({ json: detection(route.request().postDataJSON().address) });
    return route.fulfill({ status: 404, json: {} });
  });
}
const address = (page: Page) => page.getByLabel('地址', { exact: true });
const add = (page: Page) => page.getByRole('button', { name: '保存到 Registry', exact: true });

test('changing the destination discards staged login credentials before another device is created', async ({ page }) => {
  await routes(page);
  const submitted: any[] = [];
  await page.route('**/api/v1/cameras', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { cameras: [] } });
    submitted.push(route.request().postDataJSON()); return route.fulfill({ json: camera(submitted.at(-1).id) });
  });
  await page.goto(fixture);
  await address(page).fill('rtsp://first-camera.example.invalid/live');
  const login = page.getByLabel('设备登录', { exact: true });
  await login.getByLabel('用户名', { exact: true }).fill('fixture-user');
  await login.getByLabel('密码', { exact: true }).fill('fixture-pass');
  await page.getByRole('button', { name: '记住并加密保存' }).click();
  await address(page).fill('rtsp://second-camera.example.invalid/live');
  await page.getByRole('button', { name: '自动检测', exact: true }).click();
  await page.getByLabel('设备名称', { exact: true }).fill('Second device'); await add(page).click();
  await expect.poll(() => submitted.length).toBe(1);
  expect(submitted[0]).not.toHaveProperty('username'); expect(submitted[0]).not.toHaveProperty('password');
  expect(submitted[0].address).toContain('second-camera');
});

test('a late detection never belongs to a changed address', async ({ page }) => {
  await routes(page);
  await page.addInitScript(() => {
    const original = window.fetch;
    Object.assign(window, { releaseDetection: null });
    window.fetch = async (...args) => {
      if (String(args[0]).endsWith('/camera-detect')) {
        const reply = await original(args[0], { ...args[1], signal: undefined });
        await new Promise<void>(resolve => { Object.assign(window, { releaseDetection: resolve }); }); return reply;
      }
      return original(...args);
    };
  });
  await page.goto(fixture); await address(page).fill('rtsp://first-camera.example.invalid/live');
  await page.getByRole('button', { name: '自动检测', exact: true }).click();
  await expect.poll(() => page.evaluate(() => typeof (window as any).releaseDetection)).toBe('function');
  await address(page).fill('rtsp://second-camera.example.invalid/live');
  await page.evaluate(() => (window as any).releaseDetection());
  await expect(add(page)).not.toBeVisible();
  await expect(page.getByRole('button', { name: '自动检测', exact: true })).toBeEnabled();
});

test('saving a device is single-flight and blocks workspace or updater departure', async ({ page }) => {
  await routes(page); let releases: Array<() => void> = [], calls = 0;
  await page.route('**/api/v1/cameras', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { cameras: [] } });
    calls++; await new Promise<void>(resolve => releases.push(resolve)); return route.fulfill({ json: camera(route.request().postDataJSON().id) });
  });
  await page.goto(fixture); await address(page).fill('rtsp://camera.example.invalid/live');
  await page.getByRole('button', { name: '自动检测', exact: true }).click();
  await page.getByLabel('设备名称', { exact: true }).fill('Device draft');
  await add(page).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect.poll(() => calls).toBe(1); await expect(add(page)).toBeDisabled();
  expect(await page.evaluate(() => window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })))).toBe(false);
  expect(await page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: true, exporting: true });
  releases.forEach(release => release());
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
});

test('a rejected deletion remains visible with a recoverable permission error', async ({ page }) => {
  await routes(page, [camera()]); let calls = 0;
  await page.route('**/api/v1/cameras/fixture-camera', route => {
    calls++; return route.fulfill({ status: 403, json: { error: { code: 'forbidden', message: 'fixture permission denied' } } });
  });
  await page.goto(fixture); page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('权限');
  await expect(page.locator('.camera-card')).toHaveCount(1); expect(calls).toBe(1);
});

test('an unconfirmed creation retains one ID and reconciles a duplicate without another device', async ({ page }) => {
  await routes(page); const submitted: any[] = []; let stored: ReturnType<typeof camera> | undefined;
  await page.addInitScript(() => {
    const fetch = window.fetch;
    window.fetch = async (...args) => {
      const reply = await fetch(args[0], { ...args[1], signal: undefined });
      if (String(args[0]).endsWith('/cameras') && args[1]?.method === 'POST' && !(window as any).releaseCreation) {
        await new Promise<void>(resolve => { (window as any).releaseCreation = resolve; });
      }
      return reply;
    };
  });
  await page.route('**/api/v1/cameras', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { cameras: stored ? [stored] : [] } });
    submitted.push(route.request().postDataJSON());
    if (stored) return route.fulfill({ status: 409, json: { error: { code: 'camera_exists', message: 'already exists' } } });
    stored = camera(submitted[0].id); return route.fulfill({ json: stored });
  });
  await page.goto(fixture); await address(page).fill('rtsp://camera.example.invalid/live');
  await page.getByRole('button', { name: '自动检测', exact: true }).click();
  await page.clock.install(); await add(page).click();
  await expect.poll(() => page.evaluate(() => typeof (window as any).releaseCreation)).toBe('function');
  await page.clock.runFor(20001);
  await expect(page.getByRole('alert').filter({ hasText: '保存设备' })).toContainText('尚未确认');
  expect(submitted).toHaveLength(1);
  expect(await page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: true, exporting: false });
  await page.getByRole('button', { name: '继续提交同一设备', exact: true }).click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[0].id).toBe(submitted[1].id);
  await expect(page.getByRole('button', { name: '核对添加结果' })).not.toBeVisible();
  await page.evaluate(() => (window as any).releaseCreation());
  await expect(page.locator('.camera-card')).toHaveCount(1);
  expect(await page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
});

test('denied preference reads never trigger a write, while slow analytics do not hide preferences', async ({ page }) => {
  await routes(page, [camera()]); let writes = 0;
  await page.route('**/api/v2/account/preferences/camera-preferences', route => {
    if (route.request().method() === 'PUT') writes++;
    return route.fulfill({ status: 403, json: { error: { code: 'forbidden', message: 'denied' } } });
  });
  await page.goto(fixture);
  await expect(page.getByRole('alert')).toContainText('暂不允许覆盖');
  await expect(page.getByRole('button', { name: '同步显示偏好' })).toBeDisabled(); expect(writes).toBe(0);
  await page.route('**/api/v3/analytics/policies', () => new Promise(() => {}));
  await page.route('**/api/v2/account/preferences/camera-preferences', route => route.fulfill({ json: { value: { cameras: {} } } }));
  await page.getByRole('button', { name: '重新读取设备与偏好' }).click();
  await expect(page.getByRole('button', { name: '同步显示偏好' })).toBeEnabled();
});

test('refresh rebases edits onto remote fields and syncing one camera leaves the other draft unsaved', async ({ page }) => {
  await routes(page, [camera('a'), camera('b')]);
  const initial = { displayName: 'Fixture camera', favorite: false, group: '' };
  let values = { a: { ...initial }, b: { ...initial } }; const writes: any[] = [];
  await page.route('**/api/v2/account/preferences/camera-preferences', route => {
    if (route.request().method() === 'PUT') {
      const request = route.request().postDataJSON(); writes.push(request);
      values = { ...values, ...request.value.cameras };
    }
    return route.fulfill({ json: { value: { cameras: values } } });
  });
  await page.goto(fixture);
  const a = page.locator('.camera-card').nth(0), b = page.locator('.camera-card').nth(1);
  await a.getByLabel('分组', { exact: true }).fill('Local A');
  await b.getByLabel('分组', { exact: true }).fill('Local B');
  values.a.favorite = true;
  await page.getByRole('button', { name: '重新读取设备与偏好' }).click();
  await expect(a.getByLabel('收藏')).toBeChecked();
  await expect(a.getByLabel('分组', { exact: true })).toHaveValue('Local A');
  await a.getByRole('button', { name: '同步显示偏好' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ partial: true, value: { cameras: { a: { favorite: true, group: 'Local A' } } } });
  expect(writes[0].value.cameras).not.toHaveProperty('b');
  await expect(b.getByLabel('分组', { exact: true })).toHaveValue('Local B');
  expect(await page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: true, exporting: false });
  await b.getByLabel('分组', { exact: true }).fill('');
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
});

test('go2rtc import owns navigation and updates, and an unconfirmed import keeps one submission ID', async ({ page }) => {
  await routes(page); const submitted: any[] = []; let stored: ReturnType<typeof camera> | undefined;
  await page.route('**/api/v1/runtime/info', route => route.fulfill({ json: { platform: 'linux', go2rtcRtspBase: 'rtsp://127.0.0.1:28554/' } }));
  await page.route('**/api/v1/go2rtc/api/streams', route => route.fulfill({ json: { entrance: {} } }));
  await page.route('**/api/v1/cameras', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { cameras: stored ? [stored] : [] } });
    submitted.push(route.request().postDataJSON());
    if (!stored) { stored = { ...camera(submitted[0].id), ...submitted[0] }; return route.fulfill({ status: 502, json: { error: { code: 'response_lost', message: 'fixture response lost' } } }); }
    return route.fulfill({ status: 409, json: { error: { code: 'camera_exists', message: 'already exists' } } });
  });
  await page.goto(fixture);
  const bridge = page.getByRole('region', { name: 'go2rtc 流接入' });
  await bridge.getByRole('button', { name: '检测并添加设备', exact: true }).click();
  await expect(bridge.getByRole('button', { name: '核对导入结果' })).toBeVisible();
  expect(await page.evaluate(() => window.webobsUpdateWork?.().dirty)).toBe(true);
  expect(submitted[0].address).toBe('rtsp://127.0.0.1:28554/entrance');
  await bridge.getByRole('button', { name: '继续提交同一设备' }).click();
  await expect(bridge.getByRole('button', { name: '已在设备目录' })).toBeDisabled();
  expect(submitted).toHaveLength(2); expect(submitted[0].id).toBe(submitted[1].id);
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
});

test('an active go2rtc import blocks local departure and updater installation', async ({ page }) => {
  await routes(page); let release!: () => void;
  await page.route('**/api/v1/runtime/info', route => route.fulfill({ json: { platform: 'linux', go2rtcRtspBase: 'rtsp://127.0.0.1:28554/' } }));
  await page.route('**/api/v1/go2rtc/api/streams', route => route.fulfill({ json: { entrance: {} } }));
  await page.route('**/api/v1/cameras', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { cameras: [] } });
    await new Promise<void>(resolve => { release = resolve; });
    return route.fulfill({ json: camera(route.request().postDataJSON().id) });
  });
  await page.goto(fixture);
  await page.getByRole('region', { name: 'go2rtc 流接入' }).getByRole('button', { name: '检测并添加设备', exact: true }).click();
  await expect.poll(() => typeof release).toBe('function');
  await expect(page.getByRole('button', { name: '返回设备与来源' })).toBeDisabled();
  expect(await page.evaluate(() => window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })))).toBe(false);
  expect(await page.evaluate(() => window.webobsUpdateWork?.().exporting)).toBe(true);
  release();
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
});

test('an older preference read cannot replace a later confirmed save', async ({ page }) => {
  await routes(page, [camera()]); let reads = 0, value = { displayName: 'Fixture camera', favorite: false, group: '' };
  await page.addInitScript(() => {
    const fetch = window.fetch; let reads = 0;
    window.fetch = async (...args) => {
      const reply = await fetch(args[0], { ...args[1], signal: undefined });
      if (String(args[0]).endsWith('/camera-preferences') && args[1]?.method !== 'PUT' && ++reads === 2)
        await new Promise<void>(resolve => { (window as any).releasePreference = resolve; });
      return reply;
    };
  });
  await page.route('**/api/v2/account/preferences/camera-preferences', route => {
    if (route.request().method() === 'PUT') value = route.request().postDataJSON().value.cameras['fixture-camera'];
    else reads++;
    return route.fulfill({ json: { value: { cameras: { 'fixture-camera': value } } } });
  });
  await page.goto(fixture); const group = page.locator('.camera-card').getByLabel('分组', { exact: true });
  await expect(group).toBeEnabled();
  await page.getByRole('button', { name: '重新读取设备与偏好' }).click();
  await expect.poll(() => page.evaluate(() => typeof (window as any).releasePreference)).toBe('function');
  await group.fill('Saved group'); await page.getByRole('button', { name: '同步显示偏好' }).click();
  await expect.poll(() => reads).toBeGreaterThan(2);
  await page.evaluate(() => (window as any).releasePreference());
  await expect(group).toHaveValue('Saved group');
  expect(await page.evaluate(() => window.webobsUpdateWork?.().dirty)).toBe(false);
});
