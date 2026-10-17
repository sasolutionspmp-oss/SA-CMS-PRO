import base from './playwright.config';
import { defineConfig } from '@playwright/test';
export default defineConfig({ ...base, testMatch: /document-control(?:-validation)?\.spec\.ts/, workers: 1, outputDir: process.env.CIPHER_DOCUMENT_OUTPUT || 'test-results/document-control', reporter: process.env.CIPHER_DOCUMENT_REPORT ? [['list'], ['json', { outputFile: process.env.CIPHER_DOCUMENT_REPORT }]] : [['list']], use: { ...base.use, baseURL: process.env.CIPHER_DOCUMENT_PREVIEW || 'http://127.0.0.1:5250' }, webServer: process.env.CIPHER_DOCUMENT_PREVIEW ? undefined : base.webServer });
