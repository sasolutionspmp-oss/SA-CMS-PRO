import { defineConfig } from '@playwright/test';

const staticFixtures = Boolean(process.env.CIPHER_BROWSER_BUILD_DIR);
const port = process.env.CIPHER_BROWSER_PORT || '5180';
const browserURL = staticFixtures ? `http://127.0.0.1:${port}` : 'http://127.0.0.1:5180';
const requestedWorkers = process.env.CIPHER_BROWSER_WORKERS;
if (requestedWorkers && !/^[1-4]$/.test(requestedWorkers)) throw new Error('CIPHER_BROWSER_WORKERS must be between 1 and 4.');

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  ...(requestedWorkers ? { workers: Number(requestedWorkers) } : {}),
  timeout: 45000,
  expect: { timeout: 10000 },
  use: {
    baseURL: browserURL,
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: { executablePath: process.env.CIPHER_CHROME || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage'] },
  },
  webServer: { command: staticFixtures ? 'node scripts/preview-browser-fixtures.mjs' : 'npm run dev', url: browserURL, reuseExistingServer: staticFixtures ? false : !process.env.CI },
});
