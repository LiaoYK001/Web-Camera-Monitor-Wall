import { defineConfig, devices } from '@playwright/test';

// Temporary local runner: reuses an already running Vite dev server.
export default defineConfig({
  testDir: './tests/local-runtime',
  timeout: 45 * 60_000,
  workers: 1,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'off' },
  projects: [
    { name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
  ],
});
