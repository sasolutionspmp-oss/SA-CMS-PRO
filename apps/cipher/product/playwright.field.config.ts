import base from './playwright.config';
import { defineConfig } from '@playwright/test';
export default defineConfig({ ...base, testMatch: /field(?:-validation)?\.spec\.ts/, workers: 1, fullyParallel: false, outputDir: process.env.CIPHER_FIELD_OUTPUT || 'test-results/field-contract', reporter: process.env.CIPHER_FIELD_REPORT ? [['list'], ['json', { outputFile: process.env.CIPHER_FIELD_REPORT }]] : [['list']], use: { ...base.use, baseURL: process.env.CIPHER_FIELD_PREVIEW || base.use?.baseURL }, webServer: process.env.CIPHER_FIELD_PREVIEW ? undefined : base.webServer });
