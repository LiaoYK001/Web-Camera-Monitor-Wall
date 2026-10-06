import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/local-runtime',
  testMatch: 'archive-playback.spec.ts',
  outputDir: './test-results-archive',
  workers: 1,
  timeout: 15_000,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4186', trace: 'retain-on-failure' },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4186 --strictPort',
    url: 'http://127.0.0.1:4186/tests/harness/archive-playback.html',
    reuseExistingServer: false,
  },
  projects: [{ name: 'chromium', use: {
    ...devices['Desktop Chrome'],
    launchOptions: process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE } : undefined,
  } }],
});
