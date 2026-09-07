const STATIC_PATHS = /*__ASSETS__*/ [];
const CACHE_NAME = 'yijing-shell-__BUILD_HASH__';

export function isStaticRequest(request, origin, allowed = STATIC_PATHS) {
  const url = new URL(request.url);
  return request.method === 'GET' && url.origin === origin && !url.search &&
    url.pathname !== '/api' && !url.pathname.startsWith('/api/') &&
    (allowed.includes(url.pathname) || (request.mode === 'navigate' && url.pathname === '/'));
}

if (typeof self !== 'undefined' && 'ServiceWorkerGlobalScope' in self) {
  self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_PATHS)));
  });
  self.addEventListener('activate', (event) => {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys
      .filter((key) => key.startsWith('yijing-shell-') && key !== CACHE_NAME)
      .map((key) => caches.delete(key)))));
  });
  self.addEventListener('fetch', (event) => {
    if (!isStaticRequest(event.request, self.location.origin)) return;
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      if (event.request.mode === 'navigate') {
        try { return await fetch(event.request); }
        catch { return (await cache.match('/index.html')) ?? Response.error(); }
      }
      return (await cache.match(event.request)) ?? fetch(event.request);
    })());
  });
}
