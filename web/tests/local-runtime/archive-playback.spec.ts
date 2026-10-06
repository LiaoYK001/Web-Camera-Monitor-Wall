import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // Match the supported older WebView path; no native signal composition required.
  await page.addInitScript(() => {
    Object.defineProperty(AbortSignal, 'any', { value: undefined, configurable: true });
    Object.defineProperty(AbortSignal, 'timeout', { value: undefined, configurable: true });
  });
  await page.goto('/tests/harness/archive-playback.html');
  await expect(page.getByTestId('loading')).toBeAttached();
});

test('streams all bytes and verifies full SHA-256 before exposing a Blob, without endpoint credentials', async ({ page }) => {
  await page.evaluate(() => (window as any).archiveFixture.start());
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.settled)).toBe('success');
  const result = await page.evaluate(() => (window as any).archiveFixture.state);
  expect(result.blobText).toBe('abc'); expect(result.blobSize).toBe(3);
  expect(result.init).toEqual({ method: 'GET', cache: 'no-store', credentials: 'omit', redirect: 'error',
    referrer: '', referrerPolicy: 'no-referrer', signal: true });
  expect(await page.evaluate(() => (window as any).archiveFixture.isLocked())).toBe(false);
});

test('rejects overrun during reading, cancels without consuming trailing chunks, and releases lock', async ({ page }) => {
  await page.evaluate(() => (window as any).archiveFixture.start({ scenario: 'overflow' }));
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.error)).toContain('超过票据');
  expect(await page.evaluate(() => {
    const f = (window as any).archiveFixture;
    return { reads: f.state.reads, cancels: f.state.cancels, locked: f.isLocked(), blobSize: f.state.blobSize };
  })).toEqual({ reads: 2, cancels: 1, locked: false, blobSize: 0 });
});

for (const [scenario, message] of [['underflow', '大小校验失败'], ['hash', 'SHA-256'],
  ['headerOverflow', '大小校验失败'], ['httpError', '无法读取'], ['missingStream', '流式读取']]) {
  test('rejects ' + scenario + ' without producing a Blob', async ({ page }) => {
    await page.evaluate(scenario => (window as any).archiveFixture.start({ scenario }), scenario);
    await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.error)).toContain(message);
    expect(await page.evaluate(() => (window as any).archiveFixture.state.blobSize)).toBe(0);
    if (['headerOverflow', 'httpError'].includes(scenario)) {
      expect(await page.evaluate(() => ({ reads: (window as any).archiveFixture.state.reads, cancels: (window as any).archiveFixture.state.cancels })))
        .toEqual({ reads: 0, cancels: 1 });
    }
  });
}

test('rejects invalid, fractional, unsafe and over-cap ticket sizes before fetching', async ({ page }) => {
  const results = await page.evaluate(async () => {
    const f = (window as any).archiveFixture;
    const output = [];
    for (const sizeBytes of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, f.maxBytes + 1]) {
      f.start({ patch: { sizeBytes } });
      while (!f.state.settled) await new Promise(resolve => setTimeout(resolve, 0));
      output.push({ fetches: f.state.fetches, settled: f.state.settled, blobSize: f.state.blobSize });
    }
    return output;
  });
  for (const result of results) expect(result).toEqual({ fetches: 0, settled: 'Error', blobSize: 0 });
});

test('rejects wrong identity, expired ticket, credentials and non-HTTPS URLs before fetching', async ({ page }) => {
  const results = await page.evaluate(async () => {
    const f = (window as any).archiveFixture;
    const output = [];
    for (const patch of [{ segmentId: 'other' }, { cameraId: 'other' }, { expiresAt: 0 }, { expiresAt: NaN },
      { sha256: '0' }, { credentialExposure: 'permanent' }, { url: 'https://user:secret@archive.invalid/object' },
      { url: 'http://archive.invalid/object' }, { url: 'data:text/plain,abc' }, { url: 'https://archive.invalid/#fragment' }]) {
      f.start({ patch });
      while (!f.state.settled) await new Promise(resolve => setTimeout(resolve, 0));
      output.push({ fetches: f.state.fetches, settled: f.state.settled });
    }
    return output;
  });
  for (const result of results) expect(result).toEqual({ fetches: 0, settled: 'Error' });
});

test('accepts the declared hard-cap boundary without reading or allocating beyond it', async ({ page }) => {
  await page.evaluate(() => { const f = (window as any).archiveFixture; f.start({ patch: { sizeBytes: f.maxBytes } }); });
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.error)).toContain('大小校验失败');
  expect(await page.evaluate(() => (window as any).archiveFixture.state.fetches)).toBe(1);
});

for (const scenario of ['hangTicket', 'hangHeaders', 'hangBody', 'hangHash']) {
  test('total deadline bounds ' + scenario + ' and suppresses late completion', async ({ page }) => {
    await page.clock.install();
    await page.evaluate(scenario => (window as any).archiveFixture.start({ scenario }), scenario);
    if (scenario !== 'hangTicket') await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.fetches)).toBe(1);
    if (scenario === 'hangBody') await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.reads)).toBe(1);
    if (scenario === 'hangHash') await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.reads)).toBe(3);
    await page.clock.runFor(60_000);
    await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.settled)).toBe('TimeoutError');
    expect(await page.evaluate(() => (window as any).archiveFixture.state.aborted)).toBe(true);
    if (scenario === 'hangBody') {
      expect(await page.evaluate(() => (window as any).archiveFixture.state.cancels)).toBe(1);
      expect(await page.evaluate(() => (window as any).archiveFixture.isLocked())).toBe(false);
    }
    await page.evaluate(() => { const f = (window as any).archiveFixture; f.releaseTicket(); f.releaseHeaders(); f.releaseDigest(); });
    await page.clock.runFor(1);
    expect(await page.evaluate(() => (window as any).archiveFixture.state.settled)).toBe('TimeoutError');
    expect(await page.evaluate(() => (window as any).archiveFixture.state.blobSize)).toBe(0);
    expect(await page.evaluate(() => (window as any).archiveFixture.unhandled)).toBe(0);
    if (scenario === 'hangHeaders') expect(await page.evaluate(() => (window as any).archiveFixture.state.cancels)).toBe(1);
    if (scenario === 'hangTicket') expect(await page.evaluate(() => (window as any).archiveFixture.state.fetches)).toBe(0);
  });
}

test('owner abort cancels a hung reader even when stream cancel never resolves', async ({ page }) => {
  await page.evaluate(() => (window as any).archiveFixture.start({ scenario: 'hangBody' }));
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.reads)).toBe(1);
  await page.evaluate(() => (window as any).archiveFixture.controller.abort());
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.settled)).toBe('AbortError');
  expect(await page.evaluate(() => ({ cancels: (window as any).archiveFixture.state.cancels, locked: (window as any).archiveFixture.isLocked() })))
    .toEqual({ cancels: 1, locked: false });
});

test('pre-aborted selection never starts ticket or media fetch', async ({ page }) => {
  await page.evaluate(() => (window as any).archiveFixture.start({ preAbort: true }));
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.settled)).toBe('AbortError');
  expect(await page.evaluate(() => ({ tickets: (window as any).archiveFixture.state.tickets, fetches: (window as any).archiveFixture.state.fetches })))
    .toEqual({ tickets: 0, fetches: 0 });
});

test('one total budget covers ticket delay plus body delay, not a fresh deadline per phase', async ({ page }) => {
  await page.clock.install();
  await page.evaluate(() => (window as any).archiveFixture.start({ scenario: 'hangTicket' }));
  await page.clock.runFor(59_999);
  await page.evaluate(() => { (window as any).archiveFixture.releaseTicket(); window.fetch = () => new Promise(() => undefined); });
  await page.clock.runFor(1);
  await expect.poll(() => page.evaluate(() => (window as any).archiveFixture.state.settled)).toBe('TimeoutError');
});

test('synchronous duplicate suppression and latest-selection ownership ignore stale success and failure', async ({ page }) => {
  await page.evaluate(() => { const h = (window as any).archiveHook; void h.current.select('old', 'camera'); void h.current.select('old', 'camera'); });
  expect(await page.evaluate(() => (window as any).archiveHook.requests.length)).toBe(1);
  await page.evaluate(() => void (window as any).archiveHook.current.select('new', 'camera'));
  expect(await page.evaluate(() => (window as any).archiveHook.requests[0].signal.aborted)).toBe(true);
  await page.evaluate(() => (window as any).archiveHook.resolve(0));
  await expect(page.getByTestId('loading')).toHaveText('new');
  await expect(page.getByTestId('preview')).toHaveText('');
  expect(await page.evaluate(() => (window as any).archiveHook.created.length)).toBe(0);
  await page.evaluate(() => (window as any).archiveHook.resolve(1));
  await expect(page.getByTestId('preview')).toHaveText('new');
  await page.evaluate(() => { const h = (window as any).archiveHook; void h.current.select('third', 'camera'); void h.current.select('fourth', 'camera'); h.reject(2); });
  await expect(page.getByTestId('loading')).toHaveText('fourth');
  await expect(page.getByTestId('error')).toHaveText('');
  expect(await page.evaluate(() => (window as any).archiveHook.revoked)).toEqual(await page.evaluate(() => (window as any).archiveHook.created));
});

test('old success after the newer selection completed cannot replace its URL', async ({ page }) => {
  await page.evaluate(() => { const h = (window as any).archiveHook; void h.current.select('old', 'camera'); void h.current.select('new', 'camera'); });
  await page.evaluate(() => (window as any).archiveHook.resolve(1));
  await expect(page.getByTestId('preview')).toHaveText('new');
  await page.evaluate(() => (window as any).archiveHook.resolve(0));
  await expect(page.getByTestId('preview')).toHaveText('new');
  expect(await page.evaluate(() => (window as any).archiveHook.created.length)).toBe(1);
  expect(await page.evaluate(() => (window as any).archiveHook.revoked.length)).toBe(0);
});

test('close and unmount abort downloads, revoke owned URLs once and prevent late URL creation', async ({ page }) => {
  await page.evaluate(() => void (window as any).archiveHook.current.select('first', 'camera'));
  await page.evaluate(() => (window as any).archiveHook.resolve(0));
  await expect(page.getByTestId('preview')).toHaveText('first');
  await page.evaluate(() => { const h = (window as any).archiveHook; h.current.close(); h.current.close(); void h.current.select('second', 'camera'); });
  await page.evaluate(() => (window as any).archiveHook.current.close());
  await page.evaluate(() => (window as any).archiveHook.resolve(1));
  await expect(page.getByTestId('preview')).toHaveText('');
  await page.evaluate(() => void (window as any).archiveHook.current.select('third', 'camera'));
  await page.evaluate(() => (window as any).archiveHook.resolve(2));
  await expect(page.getByTestId('preview')).toHaveText('third');
  await page.evaluate(() => (window as any).archiveHook.unmount());
  expect(await page.evaluate(() => (window as any).archiveHook.created.length)).toBe(2);
  expect(await page.evaluate(() => (window as any).archiveHook.revoked)).toEqual(await page.evaluate(() => (window as any).archiveHook.created));
  expect(await page.evaluate(() => (window as any).archiveFixture.unhandled)).toBe(0);
});

test('unmount while pending suppresses late completion and clears native install work', async ({ page }) => {
  await page.evaluate(() => void (window as any).archiveHook.current.select('late', 'camera'));
  await expect.poll(() => page.evaluate(() => window.webobsUpdateWork?.().exporting)).toBe(true);
  expect(await page.evaluate(() => !window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })))).toBe(true);
  await expect(page.getByTestId('error')).toContainText('取消下载');
  await page.evaluate(() => (window as any).archiveHook.unmount());
  expect(await page.evaluate(() => (window as any).archiveHook.requests[0].signal.aborted)).toBe(true);
  await page.evaluate(() => (window as any).archiveHook.resolve(0));
  expect(await page.evaluate(() => (window as any).archiveHook.created.length)).toBe(0);
  expect(await page.evaluate(() => window.webobsUpdateWork?.())).toEqual({ dirty: false, exporting: false });
  expect(await page.evaluate(() => window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })))).toBe(true);
});

test('API ticket request carries cancellation and product gate credentials only on same-origin path', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { fetchVerifiedArchivedRecording } = await import('/src/api.ts');
    const calls: any[] = [];
    window.fetch = async (input, init) => {
      calls.push({ url: String(input), credentials: init?.credentials, signal: Boolean(init?.signal), method: init?.method });
      if (calls.length === 1) return new Response(JSON.stringify({ segmentId: 'segment', cameraId: 'camera', url: 'https://archive.invalid/object',
        sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', sizeBytes: 3,
        contentType: 'video/mp4', expiresAt: Date.now() / 1000 + 3600, credentialExposure: 'ephemeral' }));
      return new Response('abc');
    };
    const blob = await fetchVerifiedArchivedRecording('segment', 'camera', new AbortController().signal);
    return { text: await blob.text(), calls };
  });
  expect(result.text).toBe('abc');
  expect(result.calls).toEqual([
    { url: '/api/v2/recordings/segment/playback-ticket?cameraId=camera', credentials: 'same-origin', signal: true, method: 'POST' },
    { url: 'https://archive.invalid/object', credentials: 'omit', signal: true, method: 'GET' },
  ]);
});
