import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  timeout: 45000,
  expect: { timeout: 10000 },
  use: {
    baseURL: 'http://127.0.0.1:5180',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: { executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] },
  },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:5180', reuseExistingServer: !process.env.CI },
});
