/* ══════════════════════════════════════════════════════════════
   HARBOUR IAT FIA — Service worker do app mobile (PWA)
   Escopo "/" mas só interfere no app mobile (/m, assets mobile, /api).
   O app desktop ("/", app.js, style.css) passa direto pela rede.
   ══════════════════════════════════════════════════════════════ */
const VERSION = 'harbour-m-v2';
const SHELL = [
  '/m',
  '/static/mobile.css',
  '/static/mobile.js',
  '/static/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/favicon.svg',
  '/static/favicon-harbour.svg',
];
const CHART_CDN = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    await Promise.all(SHELL.map((u) => cache.add(u).catch(() => {})));
    await cache.add(CHART_CDN).catch(() => {});
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

async function networkFirst(request, cacheKey) {
  const cache = await caches.open(VERSION);
  const key = cacheKey || request;
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) cache.put(key, fresh.clone());
    return fresh;
  } catch (e) {
    const cached = await cache.match(key);
    if (cached) return cached;
    if (request.mode === 'navigate') {
      const shell = await cache.match('/m');
      if (shell) return shell;
    }
    throw e;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(VERSION);
  // Sem ignoreSearch: o ?v=<asset_ver> precisa diferenciar versoes, senao o
  // arquivo novo casa com o antigo em cache e a atualizacao nunca aparece.
  const cached = await cache.match(request);
  const network = fetch(request).then((res) => {
    if (res && res.ok) cache.put(request, res.clone());
    return res;
  }).catch(() => null);
  return cached || (await network) || fetch(request);
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return; // escritas: passthrough
  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;

  // Navegação para o app mobile → network-first, fallback ao shell cacheado
  if (request.mode === 'navigate' && sameOrigin && url.pathname === '/m') {
    event.respondWith(networkFirst(request, '/m'));
    return;
  }

  // API → network-first com fallback de cache (último snapshot offline)
  if (sameOrigin && url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Assets do app mobile + Chart.js → stale-while-revalidate
  const isMobileAsset = sameOrigin && /\/static\/(mobile\.(css|js)|icon-|favicon|manifest)/.test(url.pathname);
  const isChart = url.href.indexOf('cdn.jsdelivr.net') !== -1 && url.href.indexOf('chart') !== -1;
  if (isMobileAsset || isChart) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // Resto (app desktop, etc.) → comportamento padrão da rede, sem interferência
});
