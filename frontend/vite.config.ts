import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: Number(loadEnv(mode, process.cwd(), 'VITE_').VITE_DEV_PORT || 5175),
    strictPort: true,
    watch: { ignored: ['**/test-results/**', '**/playwright-report/**'] },
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') },
    },
  },
  build: { target: 'es2022' },
}));
