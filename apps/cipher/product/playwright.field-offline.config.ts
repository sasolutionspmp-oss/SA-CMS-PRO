import base from './playwright.config';
import { defineConfig } from '@playwright/test';
export default defineConfig({ ...base, testMatch: /field-offline(?:-vault|-api)?\.spec\.ts/, workers: 1, fullyParallel: false, outputDir: process.env.CIPHER_OFFLINE_OUTPUT || 'test-results/field-offline', reporter: process.env.CIPHER_OFFLINE_REPORT ? [['list'], ['json', { outputFile: process.env.CIPHER_OFFLINE_REPORT }]] : [['list']], use: { ...base.use, baseURL: process.env.CIPHER_OFFLINE_PREVIEW || base.use?.baseURL }, webServer: process.env.CIPHER_OFFLINE_PREVIEW ? undefined : base.webServer });
