import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/m7',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'line',
  outputDir: '../tests/.m7-cluster/playwright-output',
  use: {
    baseURL: process.env.WEBOBS_M7_CONTROL_URL ?? 'https://127.0.0.1:18443',
    ignoreHTTPSErrors: true,
    launchOptions: { args: ['--ignore-certificate-errors'] },
    trace: 'off', video: 'off', screenshot: 'off',
  },
  projects: [
    { name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
    { name: 'edge', use: { ...devices['Desktop Edge'], channel: 'msedge' } },
  ],
});
