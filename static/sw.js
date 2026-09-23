/*
 * QP-CRM service worker -- STATIC-ONLY cache, by design.
 *
 * This worker NEVER caches anything but same-origin GET responses under
 * /static/. App HTML routes (/login, the landing menu, every module page),
 * /api/v1 and /app_assets are network-only: those responses are
 * session- or money-dependent and must never be served stale or offline.
 * Non-GET requests (POST/PUT/DELETE -- offers, rent contracts, price
 * updates, admin saves, ...) are not intercepted at all.
 *
 * Service workers only run in a secure context (HTTPS or localhost), so
 * over plain-HTTP LAN access this file is fetched but never activated --
 * the registration guard in templates/landing.html handles that case.
 */

var CACHE_VERSION = 'v1';
var CACHE_NAME = 'qp-crm-static-' + CACHE_VERSION;

/* Core static set fetched on install so the manifest + icons survive a
 * full offline start once the app is installed. Nothing user/DB-derived. */
var PRECACHE = [
  '/static/manifest.webmanifest',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function (cache) { return cache.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (names) {
        return Promise.all(
          names
            .filter(function (name) { return name.indexOf('qp-crm-static-') === 0 && name !== CACHE_NAME; })
            .map(function (name) { return caches.delete(name); })
        );
      })
      .then(function () { return self.clients.claim(); })
  );
});

/* Cache-first for /static GETs only: serve the cached copy when present,
 * otherwise fetch the network, store only successful responses, and give
 * an explicit 503 (never a stale/incorrect payload) when offline on a
 * miss. Bump CACHE_VERSION (above) whenever tracked static files change
 * meaningfully -- activate() then drops the old cache. */
function staticCacheFirst(request) {
  return caches.open(CACHE_NAME).then(function (cache) {
    return cache.match(request).then(function (cached) {
      if (cached) { return cached; }
      return fetch(request).then(function (response) {
        if (response && response.ok && response.type === 'basic') {
          cache.put(request, response.clone());
        }
        return response;
      }).catch(function () {
        return new Response('QP-CRM offline: resource is not cached.',
          { status: 503, statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
      });
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;

  // Never touch state-changing traffic (money/CRUD/API writes).
  if (request.method !== 'GET') { return; }

  // Cross-origin (Google Fonts, site sync calls, ...): plain network.
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) { return; }

  // Static assets only get cached; everything else on this origin
  // (HTML routes, /api, /app_assets) stays network-only.
  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(staticCacheFirst(request));
  }
  // else: no respondWith -> browser default network fetch, never cached.
});
