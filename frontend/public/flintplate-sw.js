/* Network-only application/data. Only the generic offline page is stored. */
const CACHE="flintplate-shell-v1";
self.addEventListener("install",event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.add("/flintplate/offline.html")));self.skipWaiting();});
self.addEventListener("activate",event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith("flintplate-shell-")&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));});
self.addEventListener("fetch",event=>{if(event.request.mode==="navigate"){event.respondWith(fetch(event.request).catch(()=>caches.match("/flintplate/offline.html")));}});
