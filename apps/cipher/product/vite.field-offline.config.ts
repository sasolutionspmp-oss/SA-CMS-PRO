import { defineConfig, mergeConfig } from 'vite';
import base from './vite.config';
// Production bundle for an explicit synthetic test entry; normal app is separate.
export default mergeConfig(base, defineConfig({ build: { outDir: 'dist-field-offline-fixture', rollupOptions: { input: { app: 'index.html', fieldOffline: 'tests/field-offline-harness.html' } } } }));
