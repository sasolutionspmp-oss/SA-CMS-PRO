import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5175, strictPort: true, proxy: { '/api/commercial-practice': 'http://127.0.0.1:8768' } },
  build: { outDir: 'dist-commercial', sourcemap: false, target: 'es2022', rolldownOptions: { input: 'commercial-practice.html' } },
});
