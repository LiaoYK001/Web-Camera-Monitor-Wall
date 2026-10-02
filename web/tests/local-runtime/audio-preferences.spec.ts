import { expect, test, type BrowserContext, type Page } from '@playwright/test';

const fixture = '/tests/harness/usability.html?area=monitor&mixer&account-server';
type Preferences = Record<string, any>;

// Separate browser contexts have no shared IndexedDB, cookies or storage.
// This fixture acts as the account server, shared only by the selected user.
async function account(context: BrowserContext, server: Map<string, Preferences>, user: string, blocked = false) {
  await context.addInitScript(({ blocked }) => {
    let allowResume = !blocked;
    window.addEventListener('pointerdown', () => { allowResume = true; }, { capture: true });
    class Node {
      fftSize = 1024; value = 0; gain = this; delayTime = this;
      connect(node: any) { return node; } disconnect() {}
      setTargetAtTime(value: number) { this.value = value; }
      getFloatTimeDomainData(buffer: Float32Array) { buffer.fill(0); }
    }
    class Context {
      state = 'suspended'; currentTime = 0; destination = new Node();
      createGain() { return new Node(); } createAnalyser() { return new Node(); }
      createDelay() { return new Node(); } createMediaStreamSource() { return new Node(); }
      async resume() {
        if (!allowResume) await new Promise(() => undefined);
        this.state = 'running';
      }
      async suspend() { this.state = 'suspended'; } async close() { this.state = 'closed'; }
    }
    window.AudioContext = Context as unknown as typeof AudioContext;
  }, { blocked });
  await context.route('**/api/v2/account/preferences/monitor-view', async (route) => {
    if (route.request().method() === 'PUT') server.set(user, route.request().postDataJSON().value);
    await route.fulfill({ json: { value: server.get(user) ?? null } });
  });
}
const ready = async (page: Page) => expect(page.getByRole('slider', { name: '本地监听主音量' })).toBeVisible();
const output = (page: Page) => page.locator('.hero-audio-control').getByRole('combobox', { name: '声音输出模式' });

test('restores listening, output, master and source controls after refresh and a fresh browser login', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  let context = await browser.newContext();
  await account(context, server, 'alice');
  let page = await context.newPage();
  await page.goto(fixture); await ready(page);
  await page.getByRole('button', { name: '🔊 启用声音监听', exact: true }).click();
  await page.getByRole('slider', { name: '本地监听主音量' }).fill('0.37');
  await output(page).selectOption('meter-only');
  await page.getByRole('slider', { name: '有声音的摄像机 音量' }).fill('0.63');
  await page.getByRole('button', { name: '有声音的摄像机 静音', exact: true }).click();
  await page.getByRole('button', { name: '有声音的摄像机 本地监听', exact: true }).click();
  await page.getByRole('region', { name: 'Audio Mixer', exact: true }).getByRole('button', { name: '收起', exact: true }).click();
  await expect.poll(() => server.get('alice')).toMatchObject({ audioMonitorEnabled: true, audioOutput: 'meter-only', localMonitorVolume: .37, audioMixerCollapsed: true,
    sourceAudio: { 'audio-source-1': { volume: .63, muted: false, monitor: false } } });
  await page.reload(); await ready(page);
  await expect(output(page)).toHaveValue('meter-only');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'true');
  await expect(page.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('0.37');
  await context.close();
  context = await browser.newContext();
  await account(context, server, 'alice'); page = await context.newPage();
  await page.goto(fixture); await ready(page);
  await expect(output(page)).toHaveValue('meter-only');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-enabled', 'true');
  await page.getByRole('region', { name: 'Audio Mixer', exact: true }).getByRole('button', { name: '展开', exact: true }).click();
  await expect(page.getByRole('slider', { name: '有声音的摄像机 音量' })).toHaveValue('0.63');
  await expect(page.getByRole('button', { name: '有声音的摄像机 静音', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: '有声音的摄像机 本地监听', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await context.close();
  const other = await browser.newContext(); await account(other, server, 'bob');
  const otherPage = await other.newPage(); await otherPage.goto(fixture); await ready(otherPage);
  await expect(output(otherPage)).toHaveValue('speaker');
  await expect(otherPage.getByRole('slider', { name: '本地监听主音量' })).toHaveValue('1');
  await expect(otherPage.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'false');
  await other.close();
});

test('synchronizes an already open browser for the same account', async ({ browser }) => {
  const server = new Map<string, Preferences>();
  const a = await browser.newContext(), b = await browser.newContext();
  await account(a, server, 'alice'); await account(b, server, 'alice');
  const first = await a.newPage(), second = await b.newPage();
  await first.goto(fixture); await second.goto(fixture); await ready(first); await ready(second);
  await output(first).selectOption('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await second.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(output(second)).toHaveValue('meter-only');
  await a.close(); await b.close();
});

test('flushes a change on pagehide before the debounce fires', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice'); const page = await context.newPage();
  await page.goto(fixture); await ready(page);
  await output(page).selectOption('meter-only');
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide')));
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await page.reload(); await ready(page); await expect(output(page)).toHaveValue('meter-only');
  await context.close();
});

test('account saves work when browser storage is unavailable', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice');
  await context.addInitScript(() => {
    indexedDB.open = () => { throw new Error('storage denied'); };
    Storage.prototype.getItem = Storage.prototype.setItem = () => { throw new Error('storage denied'); };
  });
  const page = await context.newPage(); await page.goto(fixture); await ready(page);
  await output(page).selectOption('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await page.reload(); await ready(page); await expect(output(page)).toHaveValue('meter-only');
  await context.close();
});

test('a delayed account refresh cannot overwrite a newer local adjustment', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice'); const page = await context.newPage();
  await page.goto(fixture); await ready(page);
  let started!: () => void, release!: () => void;
  const requested = new Promise<void>((resolve) => { started = resolve; });
  const held = new Promise<void>((resolve) => { release = resolve; });
  let delaying = true;
  await page.route('**/api/v2/account/preferences/monitor-view', async (route) => {
    if (route.request().method() !== 'GET' || !delaying) return route.fallback();
    delaying = false; const value = server.get('alice') ?? null;
    started(); await held; await route.fulfill({ json: { value } });
  });
  await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await requested;
  await output(page).selectOption('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  release();
  await expect(output(page)).toHaveValue('meter-only');
  await page.reload(); await ready(page); await expect(output(page)).toHaveValue('meter-only');
  await context.close();
});

test('autoplay blocking preserves the saved intent and a click resumes it', async ({ browser }) => {
  const server = new Map<string, Preferences>([['alice', { audioMonitorEnabled: true, audioOutput: 'speaker', localMonitorVolume: .2 }]]);
  const context = await browser.newContext(); await account(context, server, 'alice', true);
  const page = await context.newPage(); await page.goto(fixture); await ready(page);
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-state', 'blocked');
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'true');
  await page.getByRole('button', { name: '🔊 恢复声音监听', exact: true }).click();
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-enabled', 'true');
  await page.getByRole('button', { name: '监听中 · 点击关闭', exact: true }).click();
  await expect.poll(() => server.get('alice')?.audioMonitorEnabled).toBe(false);
  await page.reload(); await ready(page);
  await expect(page.locator('.hero-audio-control')).toHaveAttribute('data-audio-requested', 'false');
  await context.close();
});

test('a failed save remains visible and the pending local edit recovers on reload', async ({ browser }) => {
  const server = new Map<string, Preferences>(); const context = await browser.newContext();
  await account(context, server, 'alice'); const page = await context.newPage();
  let failing = true;
  await page.route('**/api/v2/account/preferences/monitor-view', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback();
    if (failing) return route.fulfill({ status: 503, json: {} });
    return route.fallback();
  });
  await page.goto(fixture); await ready(page); await output(page).selectOption('meter-only');
  await expect(page.locator('.direct-preview-shell').getByRole('alert')).toContainText('保存失败');
  expect(server.get('alice')).toBeUndefined();
  // Reload while the server still rejects writes: a focus refresh must retain
  // the pending account preference rather than adopting the server default.
  await page.reload(); await ready(page);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(output(page)).toHaveValue('meter-only');
  failing = false;
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await page.reload(); await ready(page);
  await expect(output(page)).toHaveValue('meter-only');
  await expect.poll(() => server.get('alice')?.audioOutput).toBe('meter-only');
  await context.close();
});
