import { expect, test } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const workerFile = fileURLToPath(new URL('../dist/sw.js', import.meta.url));
const legacyWorker = `self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});`;

test('replaces a stale PWA worker and reloads its open client', async ({ page }) => {
  const currentWorker = await readFile(workerFile);
  try {
    await writeFile(workerFile, legacyWorker);
    await page.addInitScript(() => {
      const key = 'webobs-pwa-security-reload-count';
      localStorage.setItem(key, String(Number(localStorage.getItem(key) ?? '0') + 1));
    });
    await page.goto('/');
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      if (navigator.serviceWorker.controller) return;
      await new Promise<void>((resolve) => {
        navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true });
      });
      await registration.update();
    });
    await expect.poll(() => page.evaluate(() =>
      Number(localStorage.getItem('webobs-pwa-security-reload-count') ?? '0'))).toBe(1);

    await writeFile(workerFile, currentWorker);
    await page.evaluate(async () => (await navigator.serviceWorker.ready).update());
    await expect.poll(() => page.evaluate(() =>
      Number(localStorage.getItem('webobs-pwa-security-reload-count') ?? '0'))).toBeGreaterThan(1);
  } finally {
    await writeFile(workerFile, currentWorker);
  }
});
