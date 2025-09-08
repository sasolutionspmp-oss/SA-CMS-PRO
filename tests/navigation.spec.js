import { test, expect } from '@playwright/test';
import fs from 'fs';

test('navigation to Ingest page', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Search Page' })).toBeVisible();
  fs.mkdirSync('docs', { recursive: true });
  await page.screenshot({ path: 'docs/home.png', fullPage: true });
  await page.click('text=Ingest');
  await expect(page.getByRole('heading', { name: 'Ingest Page' })).toBeVisible();
});
