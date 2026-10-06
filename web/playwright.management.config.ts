import { defineConfig, devices } from '@playwright/test';

const chromiumExecutable = process.env.WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE;

// Focused management-recovery harness. Port 4184 keeps this run isolated from the
// other local runtime servers and reports; the bundled Playwright Chromium is not
// assumed to exist on this host, so an explicit executable is honoured.
export default defineConfig({
  testDir: './tests/local-runtime',
  testMatch: /management-recovery[.]spec[.]ts/,
  outputDir: './test-results-management',
  timeout: 45_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4184', trace: 'retain-on-failure' },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4184 --strictPort',
    url: 'http://127.0.0.1:4184',
    reuseExistingServer: false,
  },
  projects: [{
    name: 'chromium',
    use: {
      ...devices['Desktop Chrome'],
      launchOptions: chromiumExecutable ? { executablePath: chromiumExecutable } : undefined,
    },
  }],
});
