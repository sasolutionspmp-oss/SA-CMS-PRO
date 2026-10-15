import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    strictPort: true,
    ...(process.env.CIPHER_BACKEND_URL ? {
      proxy: { '/api': { target: process.env.CIPHER_BACKEND_URL, changeOrigin: true } },
    } : {}),
  },
  build: { outDir: 'dist', sourcemap: true, chunkSizeWarningLimit: 1500 },
});
