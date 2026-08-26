import { expect, test } from '@playwright/test';

test('installs a local-first app shell without caching private routes', async ({ page, context }) => {
  await page.route(/\/(?:api\/private-gate|recordings\/private\.mp4|api\/v1\/program\/whep)$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/octet-stream', body: 'private-fixture' }));
  await page.goto('/');
  await expect(page.locator('body')).toContainText(/WebOBS|登录|离线/);
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise<void>((resolve) => {
      navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true });
      void registration.update();
    });
  });
  await page.evaluate(async () => {
    for (const path of ['/api/private-gate', '/recordings/private.mp4', '/api/v1/program/whep'])
      await fetch(path, { cache: 'no-store' });
  });
  const entries = await page.evaluate(async () => (await Promise.all((await caches.keys()).map(async (name) =>
    (await (await caches.open(name)).keys()).map((request) => request.url)))).flat());
  expect(entries.some((entry) => /\/api\/|\/recordings\/|\/whep(?:\/|$)/i.test(new URL(entry).pathname))).toBeFalsy();
  expect(entries.some((entry) => ['/', '/index.html'].includes(new URL(entry).pathname))).toBeTruthy();

  await context.setOffline(true);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('body')).toContainText(/Web Camera Monitor Wall|WebOBS|离线/);
});

test('publishes install metadata and bounded local stores', async ({ page }) => {
  await page.goto('/');
  const manifest = await page.locator('link[rel="manifest"]').first().getAttribute('href');
  expect(manifest).toBe('/manifest.webmanifest');
  const metadata = await page.evaluate(async () => {
    const response = await fetch('/manifest.webmanifest');
    return response.json() as Promise<{ display: string; scope: string; start_url: string }>;
  });
  expect(metadata).toMatchObject({ display: 'standalone', scope: '/', start_url: '/' });
  expect(await page.evaluate(() => window.isSecureContext)).toBeTruthy();
  const stores = await page.evaluate(async () => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('webobs-local-v1');
      request.onsuccess = () => { request.result.close(); resolve(); };
      request.onerror = () => reject(request.error);
    });
    return Array.from((await indexedDB.databases()).map((database) => database.name));
  });
  expect(stores).toContain('webobs-local-v1');
});
