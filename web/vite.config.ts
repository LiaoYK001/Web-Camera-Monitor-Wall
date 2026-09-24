/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { defineConfig, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import packageJson from './package.json' with { type: 'json' };

const httpsOptions = process.env.WEBOBS_VITE_HTTPS_CERT && process.env.WEBOBS_VITE_HTTPS_KEY
  ? { cert: readFileSync(process.env.WEBOBS_VITE_HTTPS_CERT), key: readFileSync(process.env.WEBOBS_VITE_HTTPS_KEY) }
  : undefined;

// LAN dev (dev-lan-environment): bind Vite on all interfaces and rewrite the
// proxied Host/Origin to loopback so the backend keeps its local-only security
// model while other LAN members reach the UI through this port forward.
const lanMode = process.env.WEBOBS_LAN === '1';
const apiTarget = process.env.WEBOBS_API_PROXY_TARGET ?? 'http://127.0.0.1:8080';
const apiProxy: ProxyOptions = {
  target: apiTarget,
  ws: true,
  changeOrigin: false,
  secure: false,
  configure: (proxy) => {
    if (!lanMode) return;
    const rewrite = (proxyReq: { setHeader: (name: string, value: string) => void }) => {
      const target = new URL(apiTarget);
      const loopbackAuthority = `127.0.0.1:${target.port || '8080'}`;
      proxyReq.setHeader('Host', loopbackAuthority);
      proxyReq.setHeader('Origin', `http://${loopbackAuthority}`);
    };
    proxy.on('proxyReq', rewrite);
    proxy.on('proxyReqWs', rewrite);
  },
};

export default defineConfig({
  define: {
    __WEBOBS_BUILD_VERSION__: JSON.stringify(process.env.WEBOBS_BUILD_VERSION ?? packageJson.version),
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
    host: lanMode ? '0.0.0.0' : '127.0.0.1',
    https: httpsOptions,
    proxy: {
      '/api': apiProxy,
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
