// Weave service worker — offline-tolerant shell (architecture 4.1 / v2 PWA).
//
// Static assets: cache-first. Navigations: network-first with an offline
// fallback. API + SSE (/api/*) are never touched.
//
// HARD RULE: every promise handed to `event.respondWith` must resolve to a
// Response. The previous version had two paths that did not:
//
//   * `fetch(request).catch(() => cached)` resolved to `undefined` whenever
//     there was no cache entry — "TypeError: Failed to convert value to
//     'Response'".
//   * the navigation branch resolved to `Response.error()`, which the browser
//     reports as "the FetchEvent ... resulted in a network error response".
//
// Together those turned a recoverable server-side error on /app/settings into a
// dead tab. `offlineResponse()` below is the single fallback and is always a
// real Response.
//
// Written in ES5-compatible style on purpose: a service worker is not processed
// by the bundler, so it runs verbatim on the oldest browser we support.

const VERSION = "v5";
const CACHE = "weave-" + VERSION;
const SHELL = ["/icon.svg", "/manifest.webmanifest"];

const OFFLINE_HTML =
  '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  "<title>Weave — offline</title><style>" +
  "html,body{height:100%;margin:0;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;" +
  "background:#fff;color:#12110f;display:flex;align-items:center;justify-content:center}" +
  "@media (prefers-color-scheme:dark){html,body{background:#0c0b0a;color:#f2f0eb}}" +
  "main{text-align:center;padding:2rem;max-width:26rem}" +
  "h1{font-size:1.05rem;font-weight:600;margin:0 0 .5rem}" +
  "p{font-size:.88rem;line-height:1.6;opacity:.7;margin:0 0 1.5rem}" +
  "button{font:inherit;font-size:.85rem;padding:.6rem 1.2rem;border:1px solid currentColor;" +
  "background:none;color:inherit;border-radius:999px;cursor:pointer}" +
  "</style></head><body><main>" +
  "<h1>Hakuna mtandao / You're offline</h1>" +
  "<p>Weave couldn't reach the server. Your work is saved — reconnect and try again.</p>" +
  '<button onclick="location.reload()">Jaribu tena / Retry</button>' +
  "</main></body></html>";

function offlineResponse(status) {
  return new Response(OFFLINE_HTML, {
    status: status || 503,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function emptyResponse() {
  return new Response("", { status: 504, statusText: "offline" });
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(CACHE)
      // addAll() rejects the WHOLE install if any single entry 404s. Precaching
      // is an optimisation, so one missing asset must not block activation.
      .then(function (cache) {
        return Promise.all(
          SHELL.map(function (url) {
            return cache.add(url).catch(function () {
              return undefined;
            });
          }),
        );
      })
      .then(function () {
        return self.skipWaiting();
      })
      .catch(function () {
        return self.skipWaiting();
      }),
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys.map(function (k) {
            return k === CACHE ? undefined : caches.delete(k);
          }),
        );
      })
      .then(function () {
        return self.clients.claim();
      })
      .catch(function () {
        return undefined;
      }),
  );
});

// Lets the page activate a new worker without waiting for every tab to close.
self.addEventListener("message", function (event) {
  if (event && event.data === "weave-skip-waiting") self.skipWaiting();
});

function isPrecacheable(url) {
  return url.pathname.indexOf("/_next/static/") === 0 || SHELL.indexOf(url.pathname) !== -1;
}

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET") return;

  let url;
  try {
    url = new URL(request.url);
  } catch (e) {
    return;
  }

  // Same-origin only: a cross-origin asset, or a backend reached through a
  // separate ngrok host, goes straight to the network untouched.
  if (url.origin !== self.location.origin) return;

  // Never intercept the API. /api/chat is a long-lived SSE stream — buffering
  // or caching it would break streaming outright.
  if (url.pathname.indexOf("/api/") === 0) return;

  // Explicit no-store (RSC payloads, revalidation) bypasses the worker.
  if (request.headers.get("cache-control") === "no-store") return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        // A 4xx/5xx is still a real Response and carries the app's own error
        // page. Substituting our generic offline card would HIDE the real
        // failure — which is exactly what made the settings crash unreadable.
        .catch(function () {
          return caches.match(request).then(function (cached) {
            return cached || offlineResponse(503);
          });
        }),
    );
    return;
  }

  event.respondWith(
    caches
      .match(request)
      .then(function (cached) {
        if (cached) return cached;
        return fetch(request)
          .then(function (res) {
            if (res && res.ok && isPrecacheable(url)) {
              const clone = res.clone();
              caches
                .open(CACHE)
                .then(function (c) {
                  return c.put(request, clone);
                })
                .catch(function () {
                  /* quota exceeded / private mode — caching is best effort */
                });
            }
            return res;
          })
          .catch(emptyResponse);
      })
      .catch(emptyResponse),
  );
});
