import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  resolve: {
    conditions: ['browser']
  },
  server: {
    allowedHosts: ['frontend', 'localhost', '127.0.0.1'],
    proxy: {
      '/api/v1': {
        target: process.env.BACKEND_INTERNAL_URL ?? 'http://localhost:8100',
        changeOrigin: true
      }
    }
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    setupFiles: ['./vitest.setup.ts']
  }
});
