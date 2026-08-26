import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import packageJson from './package.json' with { type: 'json' };

export default defineConfig({
  define: {
    __WEBOBS_BUILD_VERSION__: JSON.stringify(packageJson.version),
  },
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectRegister: false,
      registerType: 'prompt',
      includeAssets: ['webobs-icon.svg'],
      manifest: {
        id: '/',
        name: 'WebOBS Monitor Wall',
        short_name: 'WebOBS',
        description: 'Local-first browser camera monitor wall and control workspace',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#090b10',
        theme_color: '#090b10',
        icons: [{
          src: '/webobs-icon.svg', type: 'image/svg+xml', sizes: 'any', purpose: 'any maskable',
        }],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}'],
        globIgnores: ['index.html'],
        maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        ws: true,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
