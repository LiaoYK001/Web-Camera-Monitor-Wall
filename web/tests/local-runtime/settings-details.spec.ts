import { expect, test, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

async function accountFixture(page: Page, failRead = false) {
  await page.goto('/tests/harness/usability.html');
  await page.evaluate(async (failRead) => {
    const { mountSettingsDetails } = await import('/tests/harness/settingsDetailsMount.tsx');
    const original = window.fetch;
    const state: any = { failRead, profileWrites: [], passwordWrites: [], profile: { username: 'details-fixture', displayName: '值班管理员', avatar: 'camera', roles: ['admin'], permissions: ['user.manage'], scopes: [], acl: [] } };
    window.fetch = async (input, init) => {
      const path = new URL(String(input), location.origin).pathname;
      if (path === '/api/v2/account/password') {
        // Retain only byte counts in the fixture; never record password values.
        const value = JSON.parse(String(init?.body));
        return new Promise((resolve) => state.passwordWrites.push({ bytes: new TextEncoder().encode(value.newPassword).length, resolve }));
      }
      if (path !== '/api/v2/account/me') return original(input, init);
      if (init?.method === 'PATCH') return new Promise((resolve) => state.profileWrites.push({ value: JSON.parse(String(init.body)), resolve }));
      if (state.failRead) return Response.json({ error: { message: 'fixture-read-unavailable' } }, { status: 503 });
      return Response.json(state.profile);
    };
    const host = document.createElement('div'); host.id = 'details-test'; document.body.appendChild(host);
    (window as any).detailsTest = { ...mountSettingsDetails('account', host), state };
  }, failRead);
  return page.locator('#details-test');
}

async function desktopFixture(page: Page, heldRead = false, failedRead = false) {
  await page.goto('/tests/harness/usability.html');
  await page.evaluate(async ({ heldRead, failedRead }) => {
    const { mountSettingsDetails } = await import('/tests/harness/settingsDetailsMount.tsx');
    const state: any = { app: { version: '3.5.0', platform: 'win32', architecture: 'x64', packaged: true }, runtime: { phase: 'ready' },
      update: { phase: 'idle', signed: false }, settings: { autoCheck: true, autoDownload: true, startAtLogin: false, minimizeToTray: true, lanEnabled: false, lanPort: 18443, recordingDirectory: '' }, recovery: null };
    const fixture: any = { state, heldRead, failedRead, reads: [], saves: [], restarts: 0, checks: 0, work: [] };
    const listeners = new Set<(value: any) => void>();
    fixture.emit = () => { for (const callback of listeners) callback(structuredClone(state)); };
    window.webobsDesktop = {
      version: 1,
      status: async () => {
        if (fixture.failedRead) throw new Error('fixture IPC unavailable');
        if (fixture.heldRead) return new Promise((resolve, reject) => fixture.reads.push({ resolve, reject }));
        return structuredClone(state);
      },
      onStatus: (callback: (value: any) => void) => { listeners.add(callback); return () => listeners.delete(callback); },
      reportWork: async (value: any) => { fixture.work.push(value); },
      saveSettings: (value: any) => new Promise((resolve, reject) => fixture.saves.push({ value, resolve, reject })),
      restartServices: async () => { fixture.restarts++; return structuredClone(state); },
      checkUpdate: async () => { fixture.checks++; state.update = { phase: 'available', version: '3.6.0' }; fixture.emit(); },
    } as any;
    const host = document.createElement('div'); host.id = 'details-test'; document.body.appendChild(host);
    (window as any).detailsTest = { ...mountSettingsDetails('desktop', host), fixture };
  }, { heldRead, failedRead });
  return page.locator('#details-test');
}

test('account read failures offer an accessible retry and never leave a permanent loading message', async ({ page }) => {
  const host = await accountFixture(page, true);
  await expect(host.getByRole('alert')).toContainText('fixture-read-unavailable');
  await expect(host).toContainText('账号信息暂不可用');
  await page.evaluate(() => { (window as any).detailsTest.state.failRead = false; });
  await host.getByRole('button', { name: '重新读取账号信息' }).click();
  await expect(host.getByRole('textbox', { name: '昵称' })).toHaveValue('值班管理员');
  await expect(host.getByRole('alert')).toHaveCount(0);
  await expect(host.getByRole('button', { name: '保存个人信息' })).toBeDisabled();
});

test('profile saves lock inputs, prevent duplicate writes and preserve failed drafts until retry', async ({ page }) => {
  const host = await accountFixture(page);
  const name = host.getByRole('textbox', { name: '昵称' });
  await name.fill('  夜班值守  ');
  await expect(host).toContainText('有未保存修改');
  await host.getByRole('form', { name: '个人信息' }).evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit(); });
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.state.profileWrites.length)).toBe(1);
  await expect(name).toBeDisabled();
  expect(await page.evaluate(async () => (await import('/src/navigationGuard.ts')).canLeaveWorkspace())).toBe(false);
  await host.getByRole('button', { name: '管理用户与审计' }).click();
  await expect(host).not.toHaveAttribute('data-admin-opened', 'true');
  await expect(host).toContainText('正在保存，请稍候再切换页面');
  await page.evaluate(() => (window as any).detailsTest.state.profileWrites[0].resolve(Response.json({ error: { message: 'fixture-save-unavailable' } }, { status: 503 })));
  await expect(host.getByRole('alert')).toContainText('fixture-save-unavailable');
  await expect(name).toHaveValue('  夜班值守  '); await expect(name).toBeEnabled();
  page.once('dialog', (dialog) => dialog.dismiss());
  await host.getByRole('button', { name: '管理用户与审计' }).click();
  await expect(host).not.toHaveAttribute('data-admin-opened', 'true');
  await host.getByRole('button', { name: '保存个人信息' }).click();
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.state.profileWrites.length)).toBe(2);
  await page.evaluate(() => {
    const state = (window as any).detailsTest.state;
    state.profile = { ...state.profile, ...state.profileWrites[1].value };
    state.profileWrites[1].resolve(Response.json(state.profile));
  });
  await expect(name).toHaveValue('夜班值守');
  await expect(host.getByRole('button', { name: '保存个人信息' })).toBeDisabled();
  await expect(host).toContainText('个人信息已保存'); await expect(host.getByRole('alert')).toHaveCount(0);
  expect(await page.evaluate(async () => (await import('/src/navigationGuard.ts')).canLeaveWorkspace())).toBe(true);
});

test('password confirmation honors UTF-8 bytes, locks one submission and clears fields only on success', async ({ page }) => {
  const host = await accountFixture(page);
  const current = host.getByLabel('当前密码', { exact: true });
  const next = host.getByLabel('新密码（至少 16 字节）', { exact: true });
  const confirm = host.getByLabel('确认新密码', { exact: true });
  const password = await page.evaluate(() => ({ current: crypto.randomUUID(), short: String.fromCodePoint(0x732b).repeat(4), valid: String.fromCodePoint(0x732b).repeat(6) }));
  await current.fill(password.current); await next.fill(password.short); await confirm.fill(password.short);
  await expect(host.getByRole('button', { name: '更新密码' })).toBeDisabled();
  await next.fill(password.valid);
  await expect(confirm).toHaveAttribute('aria-invalid', 'true'); await expect(host).toContainText('两次输入的新密码不一致');
  await confirm.fill(password.valid);
  await host.getByRole('form', { name: '修改密码' }).evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit(); });
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.state.passwordWrites.length)).toBe(1);
  await expect(current).toBeDisabled(); await expect(next).toBeDisabled(); await expect(confirm).toBeDisabled();
  expect(await page.evaluate(() => (window as any).detailsTest.state.passwordWrites[0].bytes)).toBe(18);
  await page.evaluate(() => (window as any).detailsTest.state.passwordWrites[0].resolve(Response.json({ error: { message: 'fixture-password-unavailable' } }, { status: 503 })));
  await expect(host.getByRole('alert')).toContainText('fixture-password-unavailable');
  await expect(confirm).toHaveValue(password.valid);
  await host.getByRole('button', { name: '更新密码' }).click();
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.state.passwordWrites.length)).toBe(2);
  await page.evaluate(() => (window as any).detailsTest.state.passwordWrites[1].resolve(new Response(null, { status: 204 })));
  await expect(current).toHaveValue(''); await expect(next).toHaveValue(''); await expect(confirm).toHaveValue('');
  await expect(host).toContainText('密码已更新');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mkdir('../tests/artifacts/settings-details', { recursive: true });
  await host.screenshot({ path: '../tests/artifacts/settings-details/account-mobile.png' });
});

test('desktop push state supersedes held IPC snapshots and refreshes untouched port fields', async ({ page }) => {
  const host = await desktopFixture(page, true);
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.reads.length)).toBe(2);
  await page.evaluate(() => {
    const fixture = (window as any).detailsTest.fixture;
    const old = structuredClone(fixture.state);
    fixture.state.app.version = '3.6.0'; fixture.state.settings.lanPort = 20443;
    fixture.state.update = { phase: 'downloading', percent: 45 }; fixture.emit();
    fixture.reads.forEach((read: any) => read.resolve(old));
  });
  await expect(host.locator('.about-facts dd').first()).toHaveText('3.6.0');
  await expect(host.getByRole('progressbar')).toHaveAttribute('value', '45');
  const port = host.getByRole('spinbutton', { name: '局域网 HTTPS 端口' });
  await expect(port).toHaveValue('20443');
  await port.fill('21443');
  await page.evaluate(() => { const fixture = (window as any).detailsTest.fixture; fixture.state.settings.lanPort = 22443; fixture.emit(); });
  await expect(port).toHaveValue('21443'); await expect(host).toContainText('已保存端口：22443');
  await host.getByRole('button', { name: '撤销端口修改' }).click(); await expect(port).toHaveValue('22443');
});

test('desktop port validation, failed retries and repeat clicks preserve the actual saved value', async ({ page }) => {
  const host = await desktopFixture(page);
  const port = host.getByRole('spinbutton', { name: '局域网 HTTPS 端口' });
  const save = host.getByRole('button', { name: '保存端口', exact: true });
  const restart = host.getByRole('button', { name: '应用并重启服务' });
  await port.fill('0'); await port.press('Tab');
  await expect(port).toHaveAttribute('aria-invalid', 'true'); await expect(host).toContainText('1024–65535');
  await expect(save).toBeDisabled(); await expect(restart).toBeDisabled();
  expect(await page.evaluate(() => (window as any).detailsTest.fixture.saves.length)).toBe(0);
  await port.fill('20443'); await port.press('Tab');
  expect(await page.evaluate(() => (window as any).detailsTest.fixture.saves.length)).toBe(0);
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.work.at(-1)?.dirty)).toBe(true);
  page.once('dialog', (dialog) => dialog.dismiss());
  expect(await page.evaluate(async () => (await import('/src/navigationGuard.ts')).canLeaveWorkspace())).toBe(false);
  await host.getByRole('form', { name: '局域网端口设置' }).evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit(); });
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.saves.length)).toBe(1);
  await expect(port).toBeDisabled();
  await page.evaluate(() => (window as any).detailsTest.fixture.saves[0].reject(new Error('fixture port conflict')));
  await expect(host.getByRole('alert')).toContainText('fixture port conflict'); await expect(port).toHaveValue('20443');
  await expect(host).toContainText('已保存端口：18443');
  await save.click();
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.saves.length)).toBe(2);
  await page.evaluate(() => {
    const fixture = (window as any).detailsTest.fixture;
    Object.assign(fixture.state.settings, fixture.saves[1].value); fixture.emit(); fixture.saves[1].resolve(fixture.state.settings);
  });
  await expect(host).toContainText('端口已保存'); await expect(save).toBeDisabled(); await expect(port).toHaveValue('20443');
  await expect(restart).toBeEnabled();
  await restart.evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.restarts)).toBe(1);
  await expect(host).toContainText('服务状态已刷新');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mkdir('../tests/artifacts/settings-details', { recursive: true });
  await host.locator('.desktop-settings').screenshot({ path: '../tests/artifacts/settings-details/desktop-mobile.png' });
});

test('desktop status failures recover and About accepts newer events during action refreshes', async ({ page }) => {
  const host = await desktopFixture(page, false, true);
  await expect(host.locator('.desktop-settings').getByRole('alert')).toContainText('无法读取客户端状态');
  await page.evaluate(() => { (window as any).detailsTest.fixture.failedRead = false; });
  await host.getByRole('button', { name: '重新读取客户端状态' }).click();
  await expect(host.getByRole('spinbutton', { name: '局域网 HTTPS 端口' })).toHaveValue('18443');
  await page.evaluate(() => (window as any).detailsTest.fixture.emit());
  await page.evaluate(() => { (window as any).detailsTest.fixture.heldRead = true; });
  const check = host.getByRole('button', { name: '检查更新', exact: true });
  await check.evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.checks)).toBe(1);
  await expect.poll(() => page.evaluate(() => (window as any).detailsTest.fixture.reads.length)).toBe(1);
  await page.evaluate(() => {
    const fixture = (window as any).detailsTest.fixture, old = structuredClone(fixture.state);
    fixture.state.update = { phase: 'downloaded', version: '3.6.0' }; fixture.emit(); fixture.reads[0].resolve(old);
  });
  await expect(host.getByRole('button', { name: '重启更新' })).toBeEnabled();
  await expect(host.locator('.about-update')).toContainText('更新已下载，等待安装');
});
