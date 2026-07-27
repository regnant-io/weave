// Weave service worker — offline-tolerant shell (architecture 4.1 / v2 PWA).
// Static assets: cache-first. Navigations: network-first with an offline fallback.
// API + SSE (/api/*) are always network (never cached).
const CACHE = "weave-v2";
const SHELL = ["/", "/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.pathname.startsWith("/api/")) return; // never cache API/SSE

  if (request.mode === "navigate") {
    e.respondWith(
      fetch(request)
        .then((res) => (res.ok ? res : caches.match("/").then((r) => r || Response.error())))
        .catch(() => caches.match("/").then((r) => r || Response.error()))
    );
    return;
  }
  e.respondWith(
    caches.match(request).then((cached) =>
      cached || fetch(request).then((res) => {
        if (res.ok && (url.pathname.startsWith("/_next/") || SHELL.includes(url.pathname))) {
          const clone = res.clone();
          caches.open(CACHE).then((c) => c.put(request, clone));
        }
        return res;
      }).catch(() => cached)
    )
  );
});
