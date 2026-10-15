import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5177, strictPort: true, proxy: { '/api/library-practice': 'http://127.0.0.1:8770' } },
  build: { outDir: 'dist-library', sourcemap: false, target: 'es2022', rolldownOptions: { input: 'library-practice.html' } },
});
