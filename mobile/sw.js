// Пустой обработчик: нужен браузеру, чтобы предложить «Установить приложение».
// Кэша нет — станции всё равно требуют сети, а устаревшая страница только мешает.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
