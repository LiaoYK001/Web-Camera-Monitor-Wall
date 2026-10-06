import { expect, test } from '@playwright/test';

for (const kind of ['system', 'clients', 'analytics', 'projector', 'program'] as const) {
  test(`${kind} bounds slow reads, refreshes on native resume and rejects late responses`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/tests/harness/usability.html');
    await page.clock.install();
    const paths = kind === 'system' ? ['/api/v1/system/capabilities', '/api/v1/system/processes']
      : kind === 'clients' ? ['/api/v2/enrollments', '/api/v2/clients', '/api/v1/cameras']
        : kind === 'analytics' ? ['/api/v3/analytics/policies', '/api/v3/analytics/status']
          : kind === 'program' ? ['/api/v1/program/status'] : ['/api/v1/studio'];
    await page.evaluate(async ({ kind, paths }) => {
      const mount = await import('/tests/harness/pollingMount.tsx');
      const original = window.fetch;
      const requests: any[] = [];
      let programBootstrap = true;
      window.fetch = (input, init) => {
        const path = new URL(String(input), location.origin).pathname;
        if (!paths.includes(path)) return original(input, init);
        // Program media bootstrap owns a separate initial status check.
        if (kind === 'program' && programBootstrap) { programBootstrap = false; return Promise.resolve(Response.json({ enabled: false })); }
        return new Promise((resolve) => { requests.push({ path, signal: init?.signal, resolve }); });
      };
      if (kind === 'projector') history.replaceState(null, '', '#projector?scene=poll-fixture');
      const host = document.createElement('div'); host.id = 'polling-test'; document.body.appendChild(host);
      (window as any).pollingTest = { requests, original, ...mount.mountPollingPage(kind, host) };
    }, { kind, paths });
    const round = paths.length;
    await expect.poll(() => page.evaluate(() => (window as any).pollingTest.requests.length)).toBe(round);
    // ClientsPanel refreshes through the management layer, which bounds every read
    // (15 s). A server that never answers is therefore rejected at that deadline and
    // retried on the next interval instead of holding the panel hostage; rounds still
    // never overlap. The other panels keep their unbounded in-flight read.
    const boundedRead = kind === 'clients';
    await page.clock.runFor(boundedRead ? 14_000 : 25_000);
    const active = await page.evaluate(() => (window as any).pollingTest.requests.length);
    expect(active).toBe(round);
    if (boundedRead) {
      await page.clock.runFor(6_000);
      expect(await page.evaluate(() => (window as any).pollingTest.requests.length)).toBe(round * 2);
    }
    const beforeHide = await page.evaluate(() => (window as any).pollingTest.requests.length);
    await page.evaluate(() => { window.webobsAndroidForeground = false; window.dispatchEvent(new Event('webobs:visibility')); });
    await page.clock.runFor(25_000);
    expect(await page.evaluate(() => (window as any).pollingTest.requests.every((request: any) => request.signal.aborted))).toBe(true);
    expect(await page.evaluate(() => (window as any).pollingTest.requests.length)).toBe(beforeHide);
    await page.evaluate(() => { window.webobsAndroidForeground = true; window.dispatchEvent(new Event('webobs:visibility')); });
    await expect.poll(() => page.evaluate(() => (window as any).pollingTest.requests.length)).toBe(beforeHide + round);
    // Deliberately ignore AbortSignal in the fixture to exercise stale response guards.
    await page.evaluate(({ kind, paths, beforeHide }) => {
      const response = (path: string, fresh: boolean) => {
        const marker = fresh ? 'fresh-poll-result' : 'stale-poll-result';
        if (kind === 'program') return { enabled: false, reason: marker };
        if (path.endsWith('/capabilities')) {
          const backend = { ready: false };
          return { videoEncoder: { selected: marker, requested: 'auto', backends: { vaapi: backend, qsv: backend, nvenc: backend } }, renderer: { selected: 'idle' }, hardwareDecode: { selected: 'auto' } };
        }
        if (path.endsWith('/processes')) return { processes: [], rtspSessions: 0, gpuBusyPercent: -1 };
        if (path.endsWith('/enrollments')) return { enrollments: [] };
        if (path.endsWith('/clients')) return { clients: [{ id: 'fixture', name: marker, platform: 'web', cameraCount: 0, status: 'active', lastSeen: 1, grantExpiresAt: 2 }] };
        if (path.endsWith('/cameras')) return { cameras: [] };
        if (path.endsWith('/policies')) return { revision: fresh ? 20 : 1, policies: [] };
        if (path.endsWith('/status')) return { statuses: [] };
        const source = { id: 'color', kind: 'color', name: marker, color: '#000000', muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] };
        const item = { id: 'item', sourceId: source.id, x: 0, y: 0, width: 1280, height: 720, scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' };
        const scene = { schemaVersion: 5, revision: fresh ? 20 : 1, id: 'poll-fixture', name: marker, canvas: { width: 1280, height: 720, backgroundColor: '#000000' }, sources: [source], items: [item] };
        return { schemaVersion: 1, revision: scene.revision, scenes: [scene], previewSceneId: scene.id, programSceneId: scene.id, transition: { kind: 'cut', durationMs: 0 } };
      };
      const requests = (window as any).pollingTest.requests;
      // Newest first, old response after it to reproduce the prior overwrite.
      // Mark what this fixture answered: only requests that are still pending can be
      // aborted later, so the cancellation assertions must ignore settled ones.
      requests.slice(beforeHide).forEach((request: any) => { request.settled = true; request.resolve(Response.json(response(request.path, true))); });
      requests.slice(beforeHide - paths.length, beforeHide).forEach((request: any) => { request.settled = true; request.resolve(Response.json(response(request.path, false))); });
    }, { kind, paths, beforeHide });
    const host = page.locator('#polling-test');
    expect(errors).toEqual([]);
    if (kind === 'projector') await expect(page).toHaveTitle('fresh-poll-result · 场景投影');
    else await expect(host).toContainText(kind === 'analytics' ? 'revision 20' : kind === 'system' ? 'FRESH-POLL-RESULT' : 'fresh-poll-result');
    await expect(host).not.toContainText(kind === 'system' ? 'STALE-POLL-RESULT' : 'stale-poll-result');
    await page.clock.runFor(kind === 'analytics' ? 10_001 : 5001);
    const afterResolve = beforeHide + round;
    await expect.poll(() => page.evaluate(() => (window as any).pollingTest.requests.length)).toBe(afterResolve + round);
    await page.evaluate(() => (window as any).pollingTest.unmount());
    expect(await page.evaluate(() => (window as any).pollingTest.requests.filter((request: any) => !request.settled)
      .every((request: any) => request.signal.aborted))).toBe(true);
    await page.clock.runFor(25_000);
    expect(await page.evaluate(() => (window as any).pollingTest.requests.length)).toBe(afterResolve + round);
    console.log('POLLING_RECEIPT', JSON.stringify({ page: kind, activeSlowReads: active, hiddenNewReads: 0, endpoints: round, boundedRead }));
  });
}

test('analytics mutations cancel stale reads and preserve action failures after refresh', async ({ page }) => {
  await page.goto('/tests/harness/usability.html');
  await page.clock.install();
  await page.evaluate(async () => {
    const { mountPollingPage } = await import('/tests/harness/pollingMount.tsx');
    const original = window.fetch;
    const policy = { cameraId: 'poll-camera', profileId: 'main', motionEnabled: false, sceneChangeEnabled: false, personEnabled: false, forceAnalyticsAlwaysOn: false };
    const state: any = { reads: [], revision: 1, policy, hold: false, fail: false };
    window.fetch = async (input, init) => {
      const path = new URL(String(input), location.origin).pathname;
      if (path === '/api/v3/analytics/status') return Response.json({ statuses: [] });
      if (path !== '/api/v3/analytics/policies') return original(input, init);
      if (init?.method === 'PATCH') {
        if (state.fail) return Response.json({ error: { message: 'fixture-conflict' } }, { status: 409 });
        state.policy = JSON.parse(String(init.body)).policies[0]; state.revision++;
        return Response.json({ policies: [state.policy], revision: state.revision });
      }
      if (state.hold) return new Promise((resolve) => state.reads.push({ signal: init?.signal, resolve }));
      return Response.json({ policies: [state.policy], revision: state.revision });
    };
    const host = document.createElement('div'); host.id = 'polling-test'; document.body.appendChild(host);
    (window as any).policyTest = state; mountPollingPage('analytics', host);
  });
  const host = page.locator('#polling-test');
  const motion = host.getByRole('checkbox').first();
  await expect(motion).not.toBeChecked();
  await page.evaluate(() => { (window as any).policyTest.hold = true; });
  await host.getByRole('button', { name: '刷新', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).policyTest.reads.length)).toBe(1);
  await motion.click();
  await expect(motion).toBeChecked();
  await expect(host).toContainText('revision 2');
  expect(await page.evaluate(() => (window as any).policyTest.reads[0].signal.aborted)).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as any).policyTest.reads.length)).toBe(2);
  await page.evaluate(() => {
    const state = (window as any).policyTest;
    state.reads[0].resolve(Response.json({ revision: 1, policies: [{ ...state.policy, motionEnabled: false }] }));
    state.hold = false;
    state.reads[1].resolve(Response.json({ revision: 2, policies: [state.policy] }));
    state.fail = true;
  });
  await expect(motion).toBeChecked();
  await motion.click();
  await expect(host.getByRole('alert')).toContainText('fixture-conflict');
  await host.getByRole('button', { name: '刷新', exact: true }).click();
  await page.clock.runFor(10_001);
  await expect(host.getByRole('alert')).toContainText('fixture-conflict');
  await expect(motion).toBeChecked();
});
