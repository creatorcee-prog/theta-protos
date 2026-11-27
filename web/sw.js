/* Theta's service worker: a cache-first app shell, Web Push, and opening the right message from a notification.
 * Served at /sw.js (scope /). The API (/api/*) is never cached. */
const VERSION = "theta-shell-v34";
const SHELL = ["/", "/static/style.css", "/static/orb.js", "/static/demo.js", "/static/logos.js", "/static/app.js", "/static/features.js", "/manifest.webmanifest",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png", "/static/icons/apple-touch-icon.png", "/static/icons/badge-72.png"];
const ICON = "/static/icons/icon-192.png", BADGE = "/static/icons/badge-72.png";

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => Promise.all(SHELL.map(u => c.add(new Request(u, {cache: "reload"})).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  if (req.mode === "navigate") { // the app is one page: serve the cached shell, refresh it in the background
    e.respondWith(caches.match("/").then(hit => {
      const net = fetch(req).then(r => { if (r.ok) caches.open(VERSION).then(c => c.put("/", r.clone())); return r; });
      return hit ? (e.waitUntil(net.catch(() => {})), hit) : net;
    }).catch(() => caches.match("/")));
    return;
  }
  // the saved copy at once (fast, works offline), while the network refreshes it for next time, so an update
  // reaches the phone on the next open instead of never
  e.respondWith(caches.match(req, {ignoreSearch: true}).then(hit => {
    const net = fetch(req).then(r => {
      if (r.ok && r.type === "basic") { const copy = r.clone(); caches.open(VERSION).then(c => c.put(req, copy)); }
      return r;
    });
    if (hit) { e.waitUntil(net.catch(() => {})); return hit; }
    return net;
  }));
});

// ---- push: {title, body, url, id, tag}. Skipped while Theta is open and in front: the message just appears there.
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {body: e.data ? e.data.text() : ""}; }
  const id = d.id != null ? d.id : (d.data && d.data.id);
  const url = d.url || (id != null ? `/?m=${id}` : "/");
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(list => {
    const front = list.find(c => c.visibilityState === "visible" && c.focused);
    list.forEach(c => c.postMessage({type: "push", id}));
    if (front) return; // no push while the app is open and visible
    return self.registration.showNotification(d.title || "Theta", {
      body: d.body || "Theta texted you.", icon: ICON, badge: BADGE, tag: d.tag || (id != null ? "theta-" + id : "theta"),
      renotify: false, data: {url, id},
    });
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const data = e.notification.data || {}, url = data.url || (data.id != null ? `/?m=${data.id}` : "/");
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(list => {
    const mine = list.find(c => new URL(c.url).origin === location.origin);
    if (mine) {
      mine.postMessage({type: "open", id: data.id, url});
      return mine.focus();
    }
    return self.clients.openWindow(url);
  }));
});
