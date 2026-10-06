import { defineConfig, devices } from '@playwright/test';

const chromiumExecutable = process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: './tests/local-runtime',
  // The support-report suite asserts a specific injected build version, so it runs
  // under playwright.support.config.ts with its own webServer env (pnpm
  // test:support-diagnostics). Everything else in this directory runs here.
  testIgnore: 'support-diagnostics.spec.ts',
  timeout: 30_000,
  workers: 1,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4174', trace: 'retain-on-failure' },
  webServer: {
    command: 'pnpm dev --host 127.0.0.1 --port 4174',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: false,
  },
  projects: [
    { name: 'chromium', use: {
      ...devices['Desktop Chrome'],
      launchOptions: chromiumExecutable ? { executablePath: chromiumExecutable } : undefined,
    } },
    { name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
  ],
});
