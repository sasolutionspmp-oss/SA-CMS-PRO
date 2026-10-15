import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5178, strictPort: true, proxy: { '/api/rfi-practice': 'http://127.0.0.1:8771' } },
  build: { outDir: 'dist-rfi', sourcemap: false, target: 'es2022', rolldownOptions: { input: 'rfi-practice.html' } },
});
