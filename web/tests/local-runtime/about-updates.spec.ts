import { expect, test, type BrowserContext } from '@playwright/test';
import { mkdir, writeFile, unlink } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';

async function account(context: BrowserContext) {
  await context.routeWebSocket('**/api/v1/ws', () => {});
  await context.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const scene = { schemaVersion: 5, revision: 1, id: 'main', name: '主场景', canvas: { width: 1920, height: 1080, backgroundColor: '#000000' }, sources: [], items: [] };
    if (path === '/api/v1/auth/setup') return route.fulfill({ json: { registrationOpen: false } });
    if (path === '/api/v1/auth/session') return route.fulfill({ json: { authenticated: true, user: 'about-fixture', via: 'session' } });
    if (path === '/api/v2/account/me') return route.fulfill({ json: { username: 'about-fixture', roles: ['admin'], permissions: ['settings.manage'] } });
    if (path.includes('/preferences/')) return route.fulfill({ json: { value: null } });
    if (path === '/api/v1/scene') return route.fulfill({ json: scene });
    if (path === '/api/v1/studio') return route.fulfill({ json: { schemaVersion: 1, revision: 1, programSceneId: 'main', previewSceneId: 'main', scenes: [scene], transition: { kind: 'cut', durationMs: 0 } } });
    if (path === '/api/v1/cameras') return route.fulfill({ json: { cameras: [] } });
    if (path.endsWith('/capabilities')) return route.fulfill({ json: { modes: { direct: { enabled: true }, composite: { enabled: false } }, scenes: [], sources: [] } });
    if (path === '/api/v2/settings') return route.fulfill({ json: { schemaVersion: 1, revision: 1, values: { defaultTransportMode: 'auto', probeTimeoutSeconds: 8, sourceRecoveryEnabled: true, issueRetentionLimit: 512 }, deployment: {} } });
    return route.fulfill({ status: 404, json: {} });
  });
}

test('browser About shows build/source details and checks the real registered worker', async ({ page, context }) => {
  await account(context);
  // Chrome bypasses page routing for worker update fetches; serve a real file.
  const workerName = `about-worker-test-${randomUUID()}.js`;
  const workerFile = new URL(`../../public/${workerName}`, import.meta.url);
  const worker = (version: string) => `self.skipWaiting(); self.addEventListener("activate", event => event.waitUntil(self.clients.claim())); self.addEventListener("message", event => event.ports[0].postMessage("${version}"));`;
  await writeFile(workerFile, worker('one'));
  try {
  await page.goto('/#settings');
  const about = page.getByRole('region', { name: '关于与更新', exact: true });
  await expect(about).toBeVisible();
  await expect(about.locator('dd').first()).toHaveText(/\d+\.\d+\.\d+/);
  await expect(about.getByRole('link', { name: 'GitHub 开源仓库' })).toHaveAttribute('href', 'https://github.com/LiaoYK001/Web-Camera-Monitor-Wall');
  await expect(about.getByRole('link', { name: '版本发布与更新记录' })).toHaveAttribute('href', /\/releases$/);
  await expect(about.getByRole('link', { name: '反馈问题' })).toHaveAttribute('rel', 'noopener noreferrer');
  await page.evaluate(async name => { await navigator.serviceWorker.register(`/${name}`, { updateViaCache: 'none' }); await navigator.serviceWorker.ready; }, workerName);
  await writeFile(workerFile, worker('two'));
  await about.getByRole('button', { name: '检查页面更新' }).click();
  await expect(about.getByRole('status')).toContainText('已检查当前服务器');
  await expect.poll(() => page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration('/');
    return new Promise<string>(resolve => {
      const channel = new MessageChannel(); channel.port1.onmessage = event => resolve(event.data);
      registration?.active?.postMessage('version', [channel.port2]);
    });
  })).toBe('two');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(about).toBeVisible();
  expect(await about.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await mkdir('../tests/artifacts/about', { recursive: true });
  await page.setViewportSize({ width: 390, height: 1600 });
  await about.screenshot({ path: '../tests/artifacts/about/browser-mobile.png' });
  } finally { await unlink(workerFile); }
});

test('desktop About uses the installed version and keeps download/install explicit', async ({ page, context }) => {
  await account(context);
  await context.addInitScript(() => {
    const w = window as any;
    const settings = { autoCheck: true, autoDownload: false, startAtLogin: false, minimizeToTray: true, lanEnabled: false, lanPort: 18443, recordingDirectory: '' };
    const state = { app: { version: '3.5.0', platform: 'win32', architecture: 'x64', packaged: true }, runtime: { phase: 'ready' }, update: { phase: 'idle', signed: false } as any, settings, recovery: null };
    const listeners = new Set<(value: any) => void>();
    const emit = () => { for (const callback of listeners) callback(structuredClone(state)); };
    w.installCalls = 0;
    w.webobsDesktop = {
      version: 1, status: async () => structuredClone(state), reportWork: async () => {},
      onStatus: (callback: (value: any) => void) => { listeners.add(callback); return () => listeners.delete(callback); },
      checkUpdate: async () => {
        state.update = { phase: 'checking' }; emit();
        await new Promise(resolve => setTimeout(resolve, 600));
        state.update = { phase: 'available', version: '3.6.0', lastCheckedAt: new Date().toISOString(), releaseNotes: '<script>fixture</script> 新版说明' }; emit();
      },
      downloadUpdate: async () => {
        state.update.phase = 'downloading'; state.update.percent = 45; emit();
        await new Promise(resolve => setTimeout(resolve, 600));
        state.update.phase = 'downloaded'; emit();
      },
      installUpdate: async () => { w.installCalls++; state.update.message = '有尚未保存的草稿。处理后再点击重启更新。'; emit(); },
    };
  });
  await page.goto('/#settings');
  const about = page.getByRole('region', { name: '关于与更新', exact: true });
  await expect(about.locator('dd').first()).toHaveText('3.5.0');
  await expect(about).toContainText('Windows 客户端 · x64');
  expect(await page.evaluate(() => (window as any).webobsDesktop.version)).toBe(1);
  await about.getByRole('button', { name: '检查更新', exact: true }).click();
  await expect(about.getByRole('button', { name: '正在检查…' })).toBeDisabled();
  await expect(about.getByRole('status')).toHaveText('发现新版本');
  await expect(about).toContainText('最近成功检查');
  await about.getByText('新版本发布说明', { exact: true }).click();
  await expect(about.locator('pre')).toContainText('<script>fixture</script>');
  await about.getByRole('button', { name: '下载更新', exact: true }).click();
  await expect(about.getByRole('progressbar')).toHaveAttribute('value', '45');
  await expect(about.getByRole('button', { name: '重启更新' })).toBeEnabled();
  expect(await page.evaluate(() => (window as any).installCalls)).toBe(0);
  await about.getByRole('button', { name: '重启更新' }).click();
  await expect(about).toContainText('有尚未保存的草稿');
  expect(await page.evaluate(() => (window as any).installCalls)).toBe(1);
  await mkdir('../tests/artifacts/about', { recursive: true });
  await page.setViewportSize({ width: 1280, height: 1400 });
  await about.screenshot({ path: '../tests/artifacts/about/desktop.png' });
});
