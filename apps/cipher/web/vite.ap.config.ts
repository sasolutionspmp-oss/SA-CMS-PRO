import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-ap', sourcemap: false, target: 'es2022',
    rolldownOptions: { input: 'ap-practice.html' },
  },
});
