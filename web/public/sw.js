// Cache-first for immutable assets (models, part images, Next static chunks),
// network-first with cache fallback for pages, so a visited app works offline.
const VERSION = "v1";
const ASSETS = `assets-${VERSION}`;
const PAGES = `pages-${VERSION}`;
const PRECACHE = ["/", "/home", "/models/car.mpd", "/models/radar-truck.mpd", "/models/lunar.mpd"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(PAGES).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.endsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  const immutable = url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/models/") || url.pathname.startsWith("/parts/") || url.pathname.startsWith("/icons/");
  if (immutable) {
    event.respondWith(
      caches.open(ASSETS).then(async (cache) => {
        const hit = await cache.match(request);
        if (hit) return hit;
        const res = await fetch(request);
        if (res.ok) cache.put(request, res.clone());
        return res;
      }),
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((res) => {
        if (res.ok) caches.open(PAGES).then((c) => c.put(request, res.clone()));
        return res;
      })
      .catch(async () => (await caches.match(request)) ?? (await caches.match("/home")) ?? Response.error()),
  );
});
