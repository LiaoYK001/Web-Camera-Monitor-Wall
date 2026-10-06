import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: 'pwa-security-update.spec.ts',
  timeout: 45_000, expect: { timeout: 10_000 }, fullyParallel: false, workers: 1,
  outputDir: '../tmp/pwa-continuity-results',
  use: { baseURL: 'http://127.0.0.1:4191', headless: true, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium',
    launchOptions: process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE } : undefined,
  } }],
});
