import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './live-tests',
  workers: 1,
  timeout: 90000,
  expect: { timeout: 15000 },
  reporter: 'list',
  use: {
    baseURL: process.env.HR_LIVE_FRONTEND_URL || 'http://localhost:3000',
    channel: 'chrome',
    // Real credentials and tokens must not be captured in traces or reports.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
