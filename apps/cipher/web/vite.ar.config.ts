import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5176, strictPort: true, proxy: { '/api/ar-practice': 'http://127.0.0.1:8769' } },
  build: { outDir: 'dist-ar', sourcemap: false, target: 'es2022', rolldownOptions: { input: 'ar-practice.html' } },
});
