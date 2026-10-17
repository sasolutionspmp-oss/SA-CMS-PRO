// Explicit synthetic browser fixture entry, separate from the application build.
import { defineConfig, mergeConfig } from 'vite';
import base from './vite.config';
export default mergeConfig(base, defineConfig({ build: { outDir: 'dist-field-fixture', rollupOptions: { input: { app: 'index.html', field: 'tests/field-harness.html' } } } }));
