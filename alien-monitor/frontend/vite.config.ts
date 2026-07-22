import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const base = env.VITE_BASE_PATH || '/';

  return {
    base,
    plugins: [react()],
    server: {
      port: 5173,
    proxy: {
        '/api': `http://localhost:${env.VITE_DEV_PROXY_PORT || '9100'}`,
        '/ws': { target: `ws://localhost:${env.VITE_DEV_PROXY_PORT || '9100'}`, ws: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: [],
    },
  };
});
