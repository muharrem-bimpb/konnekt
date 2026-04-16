// Konnekt Service Worker — PWA install only, no caching
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  // Nuke every old cache so stale HTML can never get stuck again
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k)))));
  self.clients.claim();
});
// No fetch handler → every request goes straight to the network
