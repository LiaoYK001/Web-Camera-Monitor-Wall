import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(AbortSignal, 'any', { value: undefined, configurable: true });
    Object.defineProperty(AbortSignal, 'timeout', { value: undefined, configurable: true });
  });
  await page.goto('/tests/harness/offline-workspace.html?seed');
  await page.clock.install();
});

for (const transport of ['raw AbortError', 'ignores abort']) test(`deadline reports a bounded TimeoutError when the transport ${transport}`, async ({ page }) => {
  await page.evaluate(async transport => {
    const { withRequestTimeout } = await import('/src/requestTimeout.ts');
    const state = (window as any).deadline = { settled: '', aborted: false, unhandled: 0 };
    addEventListener('unhandledrejection', () => { state.unhandled++; });
    void withRequestTimeout(100, signal => new Promise<string>((_resolve, reject) => {
      (window as any).lateReject = reject;
      signal.addEventListener('abort', () => {
        state.aborted = true;
        if (transport === 'raw AbortError') reject(new DOMException('The user aborted a request.', 'AbortError'));
      });
    })).then(() => { state.settled = 'unexpected success'; }, cause => { state.settled = cause.name; });
  }, transport);
  await page.clock.runFor(100);
  await expect.poll(() => page.evaluate(() => (window as any).deadline.settled)).toBe('TimeoutError');
  expect(await page.evaluate(() => (window as any).deadline.aborted)).toBe(true);
  // A transport can reject well after the UI has recovered. Its rejection must
  // remain handled and must not change the already delivered timeout result.
  await page.evaluate(() => (window as any).lateReject(new Error('late transport failure')));
  await page.clock.runFor(1000);
  expect(await page.evaluate(() => (window as any).deadline)).toEqual({ settled: 'TimeoutError', aborted: true, unhandled: 0 });
});

test('parent cancellation settles even an ignoring transport and retains its original reason', async ({ page }) => {
  await page.evaluate(async () => {
    const { withRequestTimeout } = await import('/src/requestTimeout.ts');
    const parent = (window as any).requestOwner = new AbortController();
    const reason = new DOMException('页面已切换', 'AbortError');
    const state = (window as any).deadline = { settled: '', originalReason: false, started: false };
    void withRequestTimeout(1000, () => { state.started = true; return new Promise(() => undefined); }, parent.signal)
      .catch(cause => { state.settled = cause.name; state.originalReason = cause === reason; });
    await Promise.resolve();
    parent.abort(reason);
  });
  await expect.poll(() => page.evaluate(() => (window as any).deadline)).toEqual({ settled: 'AbortError', originalReason: true, started: true });
  await page.clock.runFor(2000);
  expect(await page.evaluate(() => (window as any).deadline.settled)).toBe('AbortError');
});

test('an already cancelled parent never starts the request or produces an unhandled rejection', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { withRequestTimeout } = await import('/src/requestTimeout.ts');
    let started = 0;
    (window as any).unhandledRequests = 0;
    addEventListener('unhandledrejection', () => { (window as any).unhandledRequests++; });
    const parent = new AbortController(); parent.abort();
    try { await withRequestTimeout(1000, async () => { started++; return 'unexpected'; }, parent.signal); }
    catch (cause) { return { started, name: (cause as Error).name }; }
    return { started, name: 'unexpected success' };
  });
  expect(result).toEqual({ started: 0, name: 'AbortError' });
  await page.clock.runFor(1000);
  expect(await page.evaluate(() => (window as any).unhandledRequests)).toBe(0);
});

test('explicit null owner cancellation preserves the reason without starting a request', async ({ page }) => {
  expect(await page.evaluate(async () => {
    const { withRequestTimeout } = await import('/src/requestTimeout.ts');
    const parent = new AbortController(); parent.abort(null);
    let started = false;
    try { await withRequestTimeout(1000, async () => { started = true; }, parent.signal); }
    catch (cause) { return { started, originalReason: cause === null }; }
    return { started, originalReason: false };
  })).toEqual({ started: false, originalReason: true });
});

test('completed requests keep success and ordinary errors after later timer or parent cancellation', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { withRequestTimeout } = await import('/src/requestTimeout.ts');
    const parent = (window as any).requestOwner = new AbortController();
    let requestSignal!: AbortSignal;
    const success = await withRequestTimeout(1000, async signal => { requestSignal = signal; return 'received'; }, parent.signal);
    const failure = new Error('ordinary operation failure');
    let originalError = false;
    try { await withRequestTimeout(1000, () => { throw failure; }, parent.signal); }
    catch (cause) { originalError = cause === failure; }
    parent.abort();
    (window as any).completedRequest = requestSignal;
    return { success, originalError, aborted: requestSignal.aborted };
  });
  expect(result).toEqual({ success: 'received', originalError: true, aborted: false });
  await page.clock.runFor(2000);
  expect(await page.evaluate(() => (window as any).completedRequest.aborted)).toBe(false);
});
