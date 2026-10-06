import { defineConfig, mergeConfig } from 'vite';
import production from './vite.config';

// Test-only entrypoints never enter the product dist or production precache.
export default mergeConfig(production, defineConfig({
  build: {
    outDir: '../tmp/pwa-continuity-dist', emptyOutDir: true,
    rollupOptions: { input: { app: 'index.html', seed: 'tests/harness/pwa-seed.html' } },
  },
}));
