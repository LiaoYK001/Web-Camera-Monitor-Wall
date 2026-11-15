import { expect, test, type Page } from '@playwright/test';

const document = (revision: number, selected = 0, gain = 0.5) => ({
  schemaVersion: 1, revision, previewSceneId: 'audio-scene', programSceneId: 'audio-scene',
  transition: { kind: 'cut', durationMs: 0 },
  scenes: [{ schemaVersion: 6, revision: 0, id: 'audio-scene', name: 'Audio draft',
    canvas: { width: 640, height: 360, backgroundColor: '#000000' }, items: [],
    sources: [{ id: 'audio-source', kind: 'camera', name: 'Camera', cameraId: 'draft-camera', profileId: 'main',
      hardwareDecode: 'auto', muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [],
      audioInputs: [{ track: selected, gain, muted: false, syncOffsetMs: 0 }] }],
  }],
});
type Studio = ReturnType<typeof document>;

async function mount(page: Page, initial: Studio) {
  await page.route('**/api/v1/account-cameras/draft-camera/main/audio-tracks', (route) => route.fulfill({ json: {
    tracks: [0, 1].map((index) => ({ index, streamIndex: index + 1, codec: 'aac', channels: 1,
      channelLayout: 'mono', sampleRate: 48000,
      endpoint: `/api/v1/account-cameras/draft-camera/main/audio-tracks/${index}/whep` })),
  } }));
  await page.goto('/');
  await page.evaluate(async (initialDocument) => {
    const { mountAudioWorkspace } = await import('/tests/harness/audioWorkspaceMount.tsx');
    const host = window.document.createElement('div'); window.document.body.appendChild(host);
    Object.assign(window, { audioDraftFixture: mountAudioWorkspace(initialDocument as never, host, { localPlayback: false }) });
  }, initial);
  await expect(page.locator('.audio-track input')).toHaveCount(2);
}
async function replace(page: Page, next: Studio) {
  await page.evaluate((nextDocument) => {
    (window as unknown as { audioDraftFixture: { replace: (value: unknown) => void } }).audioDraftFixture.replace(nextDocument);
  }, next);
}
const work = (page: Page) => page.evaluate(() => window.webobsUpdateWork!());
const track = (page: Page, index: number) => page.locator('.audio-track input').nth(index);

test('pristine audio tracks follow a new authoritative revision', async ({ page }) => {
  await mount(page, document(1));
  await expect(track(page, 0)).toBeChecked();
  await replace(page, document(2, 1, 0.8));
  await expect(track(page, 0)).not.toBeChecked();
  await expect(track(page, 1)).toBeChecked();
  await expect.poll(() => work(page)).toEqual({ dirty: false, exporting: false });
});

test('track-only drafts retain their base, block navigation and require explicit conflict reload', async ({ page }) => {
  let remote = document(1);
  const writes: Array<{ revision: string | undefined; body: Studio }> = [];
  await page.route('**/api/v1/studio', (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: remote });
    const body = route.request().postDataJSON() as Studio;
    writes.push({ revision: route.request().headers()['if-match'], body });
    remote = { ...body, revision: remote.revision + 1 };
    return route.fulfill({ json: remote });
  });
  await mount(page, remote);
  await track(page, 1).check();
  await expect.poll(() => work(page)).toEqual({ dirty: true, exporting: false });
  await expect(page.getByRole('combobox', { name: 'Scene', exact: true })).toBeDisabled();
  page.once('dialog', (dialog) => dialog.dismiss());
  expect(await page.evaluate(() => window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })))).toBe(false);

  remote = document(2, 1, 0.8);
  await replace(page, remote);
  await expect(page.locator('.audio-workspace .alert')).toContainText('当前修改已保留');
  await expect(track(page, 0)).toBeChecked();
  await expect(track(page, 1)).toBeChecked();
  await expect(page.getByRole('button', { name: '保存音频配置', exact: true })).toBeDisabled();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: '放弃修改并重新载入', exact: true }).click();
  await expect(track(page, 0)).not.toBeChecked();
  await expect(track(page, 1)).toBeChecked();
  await expect.poll(() => work(page)).toEqual({ dirty: false, exporting: false });
  await page.getByRole('checkbox', { name: '来源静音', exact: true }).uncheck();
  await page.getByRole('button', { name: '保存音频配置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].revision).toBe('"2"');
  expect(writes[0].body.scenes[0].sources[0].audioInputs).toEqual([{ track: 1, gain: 0.8, muted: false, syncOffsetMs: 0 }]);
  await expect.poll(() => work(page)).toEqual({ dirty: false, exporting: false });
});

test('a late save reply cannot replace a newer server revision', async ({ page }) => {
  let remote = document(1);
  let finish!: () => void;
  const held = new Promise<void>((resolve) => { finish = resolve; });
  const writes: Studio[] = [];
  await page.route('**/api/v1/studio', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: remote });
    const body = route.request().postDataJSON() as Studio;
    writes.push(body);
    await held;
    return route.fulfill({ json: { ...body, revision: 2 } });
  });
  await mount(page, remote);
  await track(page, 1).check();
  await page.getByRole('button', { name: '保存音频配置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].revision).toBe(1);
  await expect(track(page, 1)).toBeDisabled();
  await expect.poll(() => work(page)).toEqual({ dirty: true, exporting: true });
  expect(await page.evaluate(() => window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })))).toBe(false);
  remote = document(3, 0, 0.7);
  await replace(page, remote);
  finish();
  await expect(page.locator('.audio-workspace .alert')).toContainText('服务器配置再次更新');
  await expect.poll(() => work(page)).toEqual({ dirty: true, exporting: false });
  await page.getByRole('button', { name: '放弃修改并重新载入', exact: true }).click();
  await expect(track(page, 0)).toBeChecked();
  await expect(track(page, 1)).not.toBeChecked();
  await expect.poll(() => work(page)).toEqual({ dirty: false, exporting: false });
});

test('an HTTP If-Match rejection keeps the draft until reload', async ({ page }) => {
  const remote = document(2, 1);
  let attemptedRevision = '';
  await page.route('**/api/v1/studio', (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: remote });
    attemptedRevision = route.request().headers()['if-match'];
    return route.fulfill({ status: 412, json: { error: { code: 'revision_conflict', message: 'conflicting audio revision', revision: 2 } } });
  });
  await mount(page, document(1));
  await track(page, 1).check();
  await page.getByRole('button', { name: '保存音频配置', exact: true }).click();
  await expect(page.locator('.audio-workspace .alert')).toContainText('conflicting audio revision');
  expect(attemptedRevision).toBe('"1"');
  await expect(page.getByRole('button', { name: '保存音频配置', exact: true })).toBeDisabled();
  await expect.poll(() => work(page)).toEqual({ dirty: true, exporting: false });
  await page.getByRole('button', { name: '放弃修改并重新载入', exact: true }).click();
  await expect(track(page, 0)).not.toBeChecked();
  await expect(track(page, 1)).toBeChecked();
  await expect.poll(() => work(page)).toEqual({ dirty: false, exporting: false });
});

test('an uncertain save timeout retains the draft and requires verification', async ({ page }) => {
  let submitted = false;
  let finish!: () => void;
  const held = new Promise<void>((resolve) => { finish = resolve; });
  await page.route('**/api/v1/studio', async (route) => {
    submitted = true;
    await held;
    await route.fulfill({ json: document(2) }).catch(() => undefined);
  });
  await mount(page, document(1));
  await page.clock.install();
  await track(page, 1).check();
  await page.getByRole('button', { name: '保存音频配置', exact: true }).click();
  await expect.poll(() => submitted).toBe(true);
  await page.clock.fastForward(10001);
  await expect(page.locator('.audio-workspace .alert')).toContainText('保存结果尚未确认');
  await expect(track(page, 0)).toBeChecked();
  await expect(track(page, 1)).toBeChecked();
  await expect.poll(() => work(page)).toEqual({ dirty: true, exporting: false });
  await expect(page.getByRole('button', { name: '保存音频配置', exact: true })).toBeDisabled();
  finish();
});

test('unmounting an audio draft aborts its pending save and removes its work owner', async ({ page }) => {
  let submitted = false, aborted = false;
  let finish!: () => void;
  const held = new Promise<void>((resolve) => { finish = resolve; });
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).pathname === '/api/v1/studio' && request.method() === 'PUT') aborted = true;
  });
  await page.route('**/api/v1/studio', async (route) => {
    submitted = true;
    await held;
    await route.fulfill({ json: document(2) }).catch(() => undefined);
  });
  await mount(page, document(1));
  await track(page, 1).check();
  await page.getByRole('button', { name: '保存音频配置', exact: true }).click();
  await expect.poll(() => submitted).toBe(true);
  await page.evaluate(() => {
    (window as unknown as { audioDraftFixture: { unmount: () => void } }).audioDraftFixture.unmount();
  });
  await expect.poll(() => aborted).toBe(true);
  await expect.poll(() => work(page)).toEqual({ dirty: false, exporting: false });
  finish();
  await expect(page.locator('.audio-workspace')).toHaveCount(0);
});
