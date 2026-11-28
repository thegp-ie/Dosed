/* Dosed service worker (v12.5)
 *
 * - Paths are relative to this file, so it works under /Dosed/ on GitHub Pages
 *   (the old '/' and '/index.html' pointed at the domain root and could break install).
 * - The app page is fetched NETWORK-FIRST, falling back to cache when offline,
 *   so users always get the latest version (including safety fixes) when online.
 * - Third-party libraries (versioned CDN URLs) are cache-first.
 * - Bump CACHE_VERSION on every release so old caches are cleared.
 */
const CACHE_VERSION = 'v12.10';
const CACHE_NAME = `dosed-${CACHE_VERSION}`;

const APP_SHELL = [
  './',
  './index.html',
  './manifest.json',
  './vendor/qrcode.min.js'
];

// Must match the exact URLs loaded by index.html
const CDN_ASSETS = [
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/lucide@0.278.0/dist/lucide.min.js',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js',
  'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Cache each item independently: one failed download must not abort install.
    await Promise.allSettled([
      ...APP_SHELL.map((url) => cache.add(url)),
      ...CDN_ASSETS.map(async (url) => {
        const res = await fetch(url, { mode: 'no-cors' });
        await cache.put(url, res);
      })
    ]);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith('dosed-') && name !== CACHE_NAME)
        .map((name) => caches.delete(name))
    );
    await self.clients.claim();
  })());
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  // Cache by path only: legacy share links carry health data in ?import=...,
  // which must never be written to the cache.
  const url = new URL(request.url);
  const cacheKey = url.origin + url.pathname;
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(cacheKey, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
    if (request.mode === 'navigate') {
      const shell = await cache.match('./index.html') || await cache.match('./');
      if (shell) return shell;
    }
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  // Script/style tags load cross-origin as opaque responses; cache those too.
  if (response && (response.ok || response.type === 'opaque')) {
    cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    event.respondWith(networkFirst(request));
  } else if (CDN_ASSETS.includes(request.url) || url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(cacheFirst(request));
  }
  // Anything else (e.g. wa.me links) goes straight to the network.
});
