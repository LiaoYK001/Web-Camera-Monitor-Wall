import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/local-runtime', testMatch: 'usability.spec.ts', timeout: 30_000,
  workers: 1, reporter: 'line',
  use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:4175', trace: 'retain-on-failure' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 4175 --strictPort', url: 'http://127.0.0.1:4175', reuseExistingServer: false },
});
