import { expect, test, type Page } from '@playwright/test';

const fixture = '/tests/harness/device-controls.html';
const controls = (page: Page) => page.locator('.device-controls');
const stats = (page: Page) => page.evaluate(() => (window as any).deviceFixture.metrics);

const timedCamera = (ptzTimeout: Record<string, unknown>) => ({ cameras: [{
  id: 'timed-fixture', name: 'Timed fixture', address: 'http://camera.example.invalid', adapter: 'onvif',
  profiles: [], enabled: true, hardwareDecode: 'auto', capabilities: { onvif: { ptz: true, ptzTimeout } },
}] });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const data = { metrics: { microphones: 0, stoppedTracks: 0, recorders: 0 }, deferred: false,
      failConstructor: false, pending: null as null | (() => void) };
    Object.assign(window, { deviceFixture: data });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia: () => {
        data.metrics.microphones++;
        const stream = { getTracks: () => [{ stop: () => { data.metrics.stoppedTracks++; } }] };
        return data.deferred ? new Promise(resolve => { data.pending = () => resolve(stream); }) : Promise.resolve(stream);
      },
    } });
    class Recorder {
      static isTypeSupported(type: string) { return type.startsWith('audio/webm'); }
      state = 'inactive'; mimeType = 'audio/webm';
      ondataavailable: any; onstop: any; onerror: any;
      constructor(_stream: unknown) { if (data.failConstructor) throw new Error('fixture constructor failed'); data.metrics.recorders++; Object.assign(data, { recorder: this }); }
      start() { this.state = 'recording'; }
      stop() {
        if (this.state !== 'recording') return;
        this.state = 'inactive';
        queueMicrotask(() => { this.ondataavailable?.({ data: new Blob(['fixture audio'], { type: this.mimeType }) }); this.onstop?.(); });
      }
    }
    Object.assign(window, { MediaRecorder: Recorder });
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/cameras') return route.fulfill({ json: { cameras: [{
      id: 'controlled-fixture', name: 'Fixture device', address: 'http://camera.example.invalid',
      adapter: 'onvif', profiles: [], enabled: true, hardwareDecode: 'auto',
      capabilities: { onvif: { ptz: true, snapshot: true, events: true, talk: true } },
    }] } });
    if (url.pathname.endsWith('/onvif/presets')) return route.fulfill({ json: { presets: [] } });
    if (url.pathname.includes('/onvif/')) return route.fulfill({ json: { state: 'accepted', events: [] } });
    if (url.pathname.includes('/preferences/')) return route.fulfill({ json: { value: null } });
    if (url.pathname.includes('/analytics')) return route.fulfill({ json: { policies: [], revision: 1 } });
    return route.fulfill({ status: 404, json: {} });
  });
});

test('PTZ uses a visible supported pulse and reports the actual timeout acknowledgment', async ({ page }) => {
  await page.route('**/api/v1/cameras', route => route.fulfill({ json: timedCamera({ state: 'available', minimumMs: 500, maximumMs: 1500 }) }));
  const durations: number[] = [];
  await page.route('**/onvif/ptz', route => {
    durations.push(route.request().postDataJSON().durationMs);
    return route.fulfill({ json: { state: 'accepted', autoStopMs: 1000, deviceTimeoutMs: 1000 } });
  });
  await page.goto(fixture);
  const pulse = controls(page).getByLabel('每次移动时长');
  await expect(pulse).toHaveValue('500');
  await pulse.selectOption('1000');
  await controls(page).getByRole('button', { name: '云台右移' }).click();
  expect(durations).toEqual([1000]);
  await expect(controls(page).getByRole('status')).toContainText('1000 毫秒');
  await expect(controls(page)).toContainText('设备侧超时');
});

test('PTZ incompatible timeout range disables movement while Stop remains usable', async ({ page }) => {
  await page.route('**/api/v1/cameras', route => route.fulfill({ json: timedCamera({ state: 'unsupported' }) }));
  const operations: string[] = [];
  await page.route('**/onvif/ptz', route => {
    operations.push(route.request().postDataJSON().operation); return route.fulfill({ json: { state: 'stopped' } });
  });
  await page.goto(fixture);
  await expect(controls(page).getByRole('button', { name: '云台右移' })).toBeDisabled();
  await expect(controls(page)).toContainText('预置位');
  await controls(page).getByRole('button', { name: '停止云台' }).click();
  expect(operations).toEqual(['stop']);
  await expect(controls(page).getByRole('status')).toContainText('停止云台命令已确认');
});

test('unknown device timeout remains explicit and missing timing cannot claim a confirmed deadline', async ({ page }) => {
  await page.goto(fixture);
  await expect(controls(page)).toContainText('尚未确认设备自身的移动超时');
  await controls(page).getByRole('button', { name: '云台右移' }).click();
  await expect(controls(page).getByRole('status')).toContainText('请核对设备位置');
  await expect(controls(page).getByRole('status')).not.toContainText('350 毫秒');
});

test('PTZ stop failures are visible and do not become unhandled rejections', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.route('**/onvif/ptz', route => route.fulfill({ status: 403, json: { error: 'forbidden', message: 'Fixture PTZ denied' } }));
  await page.goto(fixture);
  await controls(page).getByRole('button', { name: /■|停止云台/ }).click();
  await expect(page.getByRole('alert')).toContainText(/权限|denied/);
  expect(errors).toEqual([]);
});

test('an HTTP success without stop acknowledgment cannot display a false stop success', async ({ page }) => {
  await page.route('**/onvif/ptz', route => route.fulfill({ json: { state: 'accepted' } }));
  await page.goto(fixture);
  await controls(page).getByRole('button', { name: '停止云台' }).click();
  await expect(page.getByRole('alert')).toContainText('未确认云台命令');
  await expect(controls(page)).not.toContainText('停止云台命令已确认');
});

test('leaving the device page releases the microphone and never sends the discarded clip', async ({ page }) => {
  let sent = 0; await page.route('**/onvif/talk', route => { sent++; return route.fulfill({ json: { state: 'active' } }); });
  await page.goto(fixture);
  await controls(page).getByRole('button', { name: /短按对讲|录制对讲/ }).click();
  await expect(controls(page).getByRole('status')).toContainText('正在录音');
  await page.getByRole('button', { name: '切换设备页面' }).click();
  await expect.poll(async () => (await stats(page)).stoppedTracks).toBeGreaterThan(0);
  expect(sent).toBe(0);
});

test('a microphone granted after leaving is closed without creating a recorder', async ({ page }) => {
  await page.goto(fixture);
  await page.evaluate(() => { (window as any).deviceFixture.deferred = true; });
  await controls(page).getByRole('button', { name: /短按对讲|录制对讲/ }).click();
  await expect.poll(async () => (await stats(page)).microphones).toBe(1);
  await page.getByRole('button', { name: '切换设备页面' }).click();
  await page.evaluate(() => (window as any).deviceFixture.pending());
  await expect.poll(async () => (await stats(page)).stoppedTracks).toBeGreaterThan(0);
  expect((await stats(page)).recorders).toBe(0);
});

test('recorder construction failure releases the acquired microphone', async ({ page }) => {
  await page.goto(fixture);
  await page.evaluate(() => { (window as any).deviceFixture.failConstructor = true; });
  await controls(page).getByRole('button', { name: /短按对讲|录制对讲/ }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect((await stats(page)).stoppedTracks).toBeGreaterThan(0);
});

test('a hung snapshot has a deadline and late success cannot replace the timeout', async ({ page }) => {
  await page.goto(fixture); await page.clock.install();
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (input, init) => String(input).endsWith('/onvif/snapshot')
      ? new Promise(resolve => Object.assign((window as any).deviceFixture, { releaseSnapshot: () => resolve(new Response(JSON.stringify({
        contentType: 'image/jpeg', data: 'ZmFrZQ==', sha256: 'a'.repeat(64),
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })) })) : original(input, init);
  });
  await controls(page).getByRole('button', { name: '快照', exact: true }).click();
  await expect(controls(page).getByRole('button', { name: '快照', exact: true })).toBeDisabled();
  await page.clock.fastForward(20050);
  await expect(page.getByRole('alert')).toContainText('读取超时');
  await expect(controls(page).getByRole('button', { name: '快照', exact: true })).toBeEnabled();
  await page.evaluate(() => (window as any).deviceFixture.releaseSnapshot());
  await expect(controls(page).locator('img')).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText('读取超时');
});

test('move is not duplicated and stop remains available during another camera operation', async ({ page }) => {
  let moves = 0, stops = 0;
  await page.route('**/onvif/ptz', async route => {
    if (route.request().postDataJSON().operation === 'stop') { stops++; return route.fulfill({ json: { state: 'stopped' } }); }
    moves++; // The fixture deliberately withholds this reply until stop preempts it.
  });
  await page.route('**/onvif/sync', () => { /* Keep the independent registry operation busy. */ });
  await page.goto(fixture);
  await controls(page).getByRole('button', { name: '云台上移' }).click();
  await expect.poll(() => moves).toBe(1);
  await expect(controls(page).getByRole('button', { name: '云台上移' })).toBeDisabled();
  await controls(page).getByRole('button', { name: '云台上移' }).dispatchEvent('click');
  expect(moves).toBe(1);
  await page.getByRole('button', { name: '同步 ONVIF Profile' }).click();
  await expect(controls(page).getByRole('button', { name: '停止云台' })).toBeEnabled();
  await controls(page).getByRole('button', { name: '停止云台' }).click();
  await expect.poll(() => stops).toBe(1);
  await expect(controls(page)).toContainText('停止云台命令已确认');
});

test('Android background releases a recording, sends nothing and never automatically resumes', async ({ page }) => {
  let sent = 0; await page.route('**/onvif/talk', route => { sent++; return route.fulfill({ json: { state: 'active' } }); });
  await page.goto(fixture);
  await controls(page).getByRole('button', { name: '录制对讲', exact: true }).click();
  await expect(controls(page)).toContainText('正在录音');
  await page.evaluate(() => { window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
  await expect.poll(async () => (await stats(page)).stoppedTracks).toBeGreaterThan(0);
  await expect(controls(page)).toContainText('丢弃未发送');
  await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
  expect(sent).toBe(0); expect((await stats(page)).recorders).toBe(1);
  await expect(controls(page).getByRole('button', { name: '录制对讲', exact: true })).toBeEnabled();
});

test('normal short talk sends one bounded clip and releases the microphone', async ({ page }) => {
  const requests: any[] = [];
  await page.route('**/onvif/talk', route => { requests.push(route.request().postDataJSON()); return route.fulfill({ json: { state: 'active' } }); });
  await page.goto(fixture); await page.clock.install();
  await controls(page).getByRole('button', { name: '录制对讲', exact: true }).click();
  await expect(controls(page)).toContainText('正在录音');
  await page.clock.fastForward(10050);
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ operation: 'start', contentType: 'audio/webm', data: Buffer.from('fixture audio').toString('base64') });
  await expect(controls(page)).toContainText('对讲片段已提交');
  expect((await stats(page)).stoppedTracks).toBeGreaterThan(0);
  await expect(controls(page).getByRole('button', { name: '录制对讲', exact: true })).toBeEnabled();
});

test('oversize recording is discarded before sending and a new recording remains possible', async ({ page }) => {
  let sent = 0; await page.route('**/onvif/talk', route => { sent++; return route.fulfill({ json: { state: 'active' } }); });
  await page.goto(fixture);
  await controls(page).getByRole('button', { name: '录制对讲', exact: true }).click();
  await expect(controls(page)).toContainText('正在录音');
  await page.evaluate(() => (window as any).deviceFixture.recorder.ondataavailable({ data: new Blob([new Uint8Array(512 * 1024 + 1)]) }));
  await expect(page.getByRole('alert')).toContainText('512 KiB');
  expect(sent).toBe(0); expect((await stats(page)).stoppedTracks).toBeGreaterThan(0);
  await controls(page).getByRole('button', { name: '录制对讲', exact: true }).click();
  await expect(controls(page)).toContainText('正在录音');
  expect((await stats(page)).recorders).toBe(2);
});

test('a permission timeout closes a later microphone without starting a recording', async ({ page }) => {
  await page.goto(fixture); await page.clock.install();
  await page.evaluate(() => { (window as any).deviceFixture.deferred = true; });
  await controls(page).getByRole('button', { name: '录制对讲', exact: true }).click();
  await expect.poll(async () => (await stats(page)).microphones).toBe(1);
  await page.clock.fastForward(20050);
  await expect(page.getByRole('alert')).toContainText('等待麦克风超时');
  await page.evaluate(() => (window as any).deviceFixture.pending());
  await expect.poll(async () => (await stats(page)).stoppedTracks).toBeGreaterThan(0);
  expect((await stats(page)).recorders).toBe(0);
});

test('an unconfirmed talk timeout is not overwritten by a late acknowledgment', async ({ page }) => {
  await page.goto(fixture); await page.clock.install();
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (input, init) => String(input).endsWith('/onvif/talk')
      ? new Promise(resolve => Object.assign((window as any).deviceFixture, {
        releaseTalk: () => resolve(new Response(JSON.stringify({ state: 'active' }), { status: 200, headers: { 'Content-Type': 'application/json' } })),
      })) : original(input, init);
  });
  await controls(page).getByRole('button', { name: '录制对讲', exact: true }).click();
  await expect(controls(page)).toContainText('正在录音');
  await controls(page).getByRole('button', { name: '停止并发送' }).click();
  await expect(controls(page)).toContainText('正在发送');
  await page.clock.fastForward(20050);
  await expect(page.getByRole('alert')).toContainText('发送结果尚未确认');
  await page.evaluate(() => (window as any).deviceFixture.releaseTalk());
  await expect(controls(page)).not.toContainText('对讲片段已提交');
  await expect(page.getByRole('alert')).toContainText('发送结果尚未确认');
});
