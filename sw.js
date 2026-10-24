/* «Агро-Радар» — service worker: офлайн-оболочка + последние данные API.
 *
 * Оболочка (html/css/js/иконки/библиотеки) — cache-first: приложение открывается
 * в поле без сети. /api/* — network-first: свежие данные, а без сети — последний
 * удачный ответ. При обновлении фронтенда поднимите VERSION.
 *
 * SW работает только на localhost или HTTPS. По локальной сети через HTTP
 * (http://192.168.x.x) браузер его не регистрирует — приложение работает онлайн.
 */
const VERSION = 'agro-radar-v2';
const SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/vendor/leaflet.css',
  '/static/vendor/leaflet.js',
  '/static/vendor/chart.umd.min.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/favicon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(req));
  } else if (req.mode === 'navigate') {
    // HTML всегда тянем из сети: иначе обновления интерфейса не видны
    event.respondWith(networkFirst(req));
  } else {
    event.respondWith(cacheFirst(req));
  }
});

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  const res = await fetch(req);
  if (res && res.ok) {
    const cache = await caches.open(VERSION);
    cache.put(req, res.clone());
  }
  return res;
}

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const cache = await caches.open(VERSION);
      cache.put(req, res.clone());
    }
    return res;
  } catch (err) {
    const cached = await caches.match(req);
    if (cached) return cached;
    return new Response(
      JSON.stringify({ error: 'offline', message: 'Нет сети, свежих данных пока нет' }),
      { status: 503, headers: { 'Content-Type': 'application/json; charset=utf-8' } },
    );
  }
}
