/// <reference lib="webworker" />

import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';
import { NavigationRoute, registerRoute, setCatchHandler } from 'workbox-routing';
import { CacheFirst, NetworkFirst, NetworkOnly } from 'workbox-strategies';
import { readSecurityUpdateMarker, writeSecurityUpdateMarker } from './securityUpdateMarker';

declare let self: ServiceWorkerGlobalScope & { __WB_MANIFEST: Array<{ url: string; revision?: string }> };

const PRIVATE_PATH = /^\/(?:api(?:\/|$)|recordings(?:\/|$)|metrics$)/;
const MEDIA_PATH = /(?:\/whep(?:\/|$)|\.(?:m3u8|m4s|ts|mp4|mjpeg|mjpg)(?:$|\?))/i;
const HASHED_ASSET = /\/[A-Za-z0-9._-]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$/;

precacheAndRoute(self.__WB_MANIFEST, { cleanURLs: false });
cleanupOutdatedCaches();

// A stale PWA shell must not keep an older authentication gate alive after the
// server has been upgraded. On an update, activate the new worker immediately
// and reload every open app window so all clients run the matching gate.
self.addEventListener('install', (event) => {
  if (!self.registration.active) return;
  event.waitUntil((async () => {
    // Durable on purpose: activate keeps the record so the reloaded document can
    // still tell the user which in-page input the forced replacement discarded.
    // It is cleared only by an explicit action in that document.
    await writeSecurityUpdateMarker();
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const forceReload = Boolean(await readSecurityUpdateMarker());
    await self.clients.claim();
    if (!forceReload) return;

    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // Request navigations without awaiting their completion: a navigation may
    // wait for this activation event to finish before it can use the new worker.
    for (const client of windows) void client.navigate(client.url).catch(() => undefined);
  })());
});

registerRoute(
  ({ url }) => url.origin !== self.location.origin,
  new NetworkOnly(),
);

registerRoute(
  ({ url }) => PRIVATE_PATH.test(url.pathname) || MEDIA_PATH.test(url.pathname),
  new NetworkOnly(),
);

registerRoute(
  ({ request, url }) => request.destination !== 'document' && url.origin === self.location.origin &&
    url.pathname.startsWith('/assets/') && HASHED_ASSET.test(url.pathname),
  new CacheFirst({ cacheName: 'webobs-static-v2' }),
);

registerRoute(new NavigationRoute(
  new NetworkFirst({ cacheName: 'webobs-navigation-v2', networkTimeoutSeconds: 3 }),
  { denylist: [/^\/api\//, /^\/recordings\//, /^\/metrics$/] },
));

setCatchHandler(async ({ request }) => {
  if (request.mode === 'navigate')
    return (await caches.match('/offline.html', { ignoreSearch: true })) ?? Response.error();
  return Response.error();
});
