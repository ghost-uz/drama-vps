// Drama.Uz service worker [P5-T6] — offline shell.
// Strategiya ATAYIN konservativ: FAQAT navigatsiya (HTML sahifa) ushlanadi
// (network-first -> oflaynda offline sahifa). Statik/CDN/API so'rovlari
// UMUMAN ushlanmaydi -> eskirgan-asset (stale) klassik PWA xatosi bo'lmaydi.
// Keshni yangilash kerak bo'lsa CACHE versiyasini oshiring (v1 -> v2).
const CACHE = 'drama-pwa-v1';
const OFFLINE_URL = '{% url "offline" %}';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: 'reload' })))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
  }
});
