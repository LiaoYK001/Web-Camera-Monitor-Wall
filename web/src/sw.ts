/// <reference lib="webworker" />

import { clientsClaim } from 'workbox-core';
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';
import { NavigationRoute, registerRoute, setCatchHandler } from 'workbox-routing';
import { CacheFirst, NetworkFirst, NetworkOnly } from 'workbox-strategies';

declare let self: ServiceWorkerGlobalScope & { __WB_MANIFEST: Array<{ url: string; revision?: string }> };

const PRIVATE_PATH = /^\/(?:api(?:\/|$)|recordings(?:\/|$)|metrics$)/;
const MEDIA_PATH = /(?:\/whep(?:\/|$)|\.(?:m3u8|m4s|ts|mp4|mjpeg|mjpg)(?:$|\?))/i;
const HASHED_ASSET = /\/[A-Za-z0-9._-]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$/;

precacheAndRoute(self.__WB_MANIFEST, { cleanURLs: false });
cleanupOutdatedCaches();
clientsClaim();

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

// Keep activation user-controlled so an active monitor never mixes two builds.
self.addEventListener('message', (event) => {
  if (event.data === 'WEBOBS_ACTIVATE_UPDATE') void self.skipWaiting();
});
