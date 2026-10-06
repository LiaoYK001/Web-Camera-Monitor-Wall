import { defineConfig, devices } from '@playwright/test';

// Isolated from the parent's preview/local runtime servers and reports.
export default defineConfig({
  testDir: './tests/local-runtime',
  testMatch: /support-diagnostics[.]spec[.]ts/,
  outputDir: './test-results-support-diagnostics',
  timeout: 30_000, workers: 1, reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4185', trace: 'retain-on-failure' },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4185 --strictPort',
    url: 'http://127.0.0.1:4185', reuseExistingServer: false,
    env: { WEBOBS_BUILD_VERSION: '9.8.7-dev.42' },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'],
    launchOptions: process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE } : undefined,
  } }],
});
