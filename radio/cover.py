"""CoverFetcher — обложки треков для Marsik FM (десктоп).

При смене трека берём строку метаданных (обычно «Artist — Title»), ищем
обложку через iTunes Search API (как в мобильной версии, но без CORS —
здесь обычный сетевой запрос из Python) и отдаём QPixmap. Результат
кэшируется на диск (~/.cache/radiofm/covers/), поэтому повторный трек не
дёргает сеть. Если обложку найти не удалось — сигнал ready с пустым
QPixmap (интерфейс сам решает, что показывать).

Обложка привязана к самому треку (ключ artist|title), а не к станции:
заиграл другой трек — fetch с новым ключом, устаревший ответ игнорируется.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

_CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME")
    or os.path.join(os.path.expanduser("~"), ".cache")) / "radiofm" / "covers"
_ITUNES = "https://itunes.apple.com/search?media=music&entity=song&limit=1&term="
# каталог каналов SomaFM (id → логотип 512px) — как в мобильной версии
_SOMA_CATALOG = "https://somafm.com/channels.json"
_SOMA_RE = re.compile(r"ice\d+\.somafm\.com/([a-z0-9]+)-")


def soma_id(url):
    """id канала SomaFM из адреса потока (iceN.somafm.com/<id>-...)."""
    m = _SOMA_RE.search(url or "")
    return m.group(1) if m else None


def parse_playing(text):
    """Разбор «Artist - Title» → (artist, title).

    Копия логики из mobile/index.html (parsePlaying): первый « - ».
    Без разделителя — ( "", text ).
    """
    if not text:
        return ("", "")
    i = text.find(" - ")
    if i > 0:
        return (text[:i].strip(), text[i + 3:].strip())
    return ("", text.strip())


class CoverFetcher(QObject):
    ready = Signal(str, QPixmap)   # track_key, pixmap (пустой при неудаче)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_reply)
        self._pending = {}          # reply → (key, kind)  kind: "search" | "image"
        self._mem = {}              # key → QPixmap
        self._seen = set()         # key, по которому уже искали и не нашли
        self._soma = {}            # id канала SomaFM → url логотипа
        self._load_cache()
        self._load_soma()          # каталог SomaFM грузится в фоне

    # ---------- кэш на диск ----------

    def _load_cache(self):
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            for f in _CACHE_DIR.iterdir():
                if f.suffix.lower() in (".jpg", ".png", ".webp") and f.is_file():
                    pm = QPixmap(str(f))
                    if not pm.isNull():
                        self._mem[f.stem] = pm
        except OSError:
            pass

    @staticmethod
    def _cache_path(key):
        return _CACHE_DIR / ("%s.jpg" % hashlib.md5(key.encode("utf-8")).hexdigest())

    def _load_soma(self):
        """Фоново тянем каталог каналов SomaFM: id → url логотипа."""
        req = QNetworkRequest(QUrl(_SOMA_CATALOG))
        reply = self._net.get(req)
        self._pending[reply] = ("soma", "soma")

    # ---------- публичный API ----------

    @staticmethod
    def key_for(text):
        """Ключ трека (artist|title) — чтобы UI успел выставить его ДО fetch.

        fetch может эмитить ready синхронно (кэш/память), поэтому ключ нужно
        знать заранее, иначе ответ будет отброшен как устаревший.
        """
        artist, title = parse_playing(text)
        return ("%s|%s" % (artist, title)).lower()

    def fetch(self, text):
        """Ищет обложку для трека; эмитит ready(key, pixmap) когда готово."""
        artist, title = parse_playing(text)
        key = ("%s|%s" % (artist, title)).lower()
        if not title:
            self.ready.emit(key, QPixmap())
            return key
        if key in self._mem:
            self.ready.emit(key, self._mem[key])
            return key
        path = self._cache_path(key)
        if path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                self._mem[key] = pm
                self.ready.emit(key, pm)
                return key
        # уже пробовали и не нашли — не дёргаем сеть повторно в этой сессии
        if key in self._seen:
            self.ready.emit(key, QPixmap())
            return key
        self._seen.add(key)
        term = quote(("%s %s" % (artist, title)).strip())
        req = QNetworkRequest(QUrl(_ITUNES + term))
        reply = self._net.get(req)
        self._pending[reply] = (key, "search")
        return key

    def fetch_station(self, station):
        """Обложка СТАНЦИИ из сети: явный `logo`-URL из данных станции либо
        каталог SomaFM (для SomaFM-потоков). Эмитит ready("station|<id>", pm);
        если источника нет — пустой pixmap (вызывающий поставит заглушку)."""
        sid = (station or {}).get("id", "")
        key = "station|%s" % sid
        if not sid:
            self.ready.emit(key, QPixmap())
            return key
        if key in self._mem:
            self.ready.emit(key, self._mem[key])
            return key
        path = self._cache_path(key)
        if path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                self._mem[key] = pm
                self.ready.emit(key, pm)
                return key
        if key in self._seen:
            self.ready.emit(key, QPixmap())
            return key
        url = self._station_logo_url(station)
        if not url:
            # каталог SomaFM мог ещё не догрузиться — не помечаем seen,
            # чтобы повторить попытку позже
            self.ready.emit(key, QPixmap())
            return key
        self._seen.add(key)
        req = QNetworkRequest(QUrl(url))
        reply = self._net.get(req)
        self._pending[reply] = (key, "image")
        return key

    def _station_logo_url(self, station):
        """URL логотипа станции: явный http(s)-logo в данных или каталог SomaFM."""
        logo = ((station or {}).get("logo") or "").strip()
        if logo.startswith("http://") or logo.startswith("https://"):
            return logo
        sid = soma_id((station or {}).get("url", ""))
        if sid:
            return self._soma.get(sid)
        return None

    # ---------- сеть ----------

    def _on_reply(self, reply):
        item = self._pending.pop(reply, None)
        if item is None:
            reply.deleteLater()
            return
        key, kind = item
        data = b""
        ok = reply.error() == QNetworkReply.NoError
        if ok:
            try:
                data = reply.readAll().data()
            except Exception:
                data = b""
        reply.deleteLater()
        if kind == "search":
            self._handle_search(key, data if ok else b"")
        elif kind == "soma":
            self._handle_soma(data if ok else b"")
        else:
            self._handle_image(key, data if ok else b"")

    def _handle_search(self, key, data):
        if not data:
            self.ready.emit(key, QPixmap())
            return
        try:
            j = json.loads(data)
            res = (j.get("results") or [])[:1]
            u100 = res[0].get("artworkUrl100") if res else None
        except (ValueError, AttributeError):
            self.ready.emit(key, QPixmap())
            return
        if not u100:
            self.ready.emit(key, QPixmap())
            return
        url = u100.replace("100x100", "512x512")
        req = QNetworkRequest(QUrl(url))
        reply = self._net.get(req)
        self._pending[reply] = (key, "image")

    def _handle_soma(self, data):
        if not data:
            return
        try:
            j = json.loads(data)
            chans = j.get("channels", j) if isinstance(j, dict) else j
            for c in chans:
                cid = c.get("id")
                img = c.get("xlimage") or c.get("largeimage") or c.get("image")
                if cid and img:
                    self._soma[cid] = img
        except (ValueError, AttributeError, TypeError):
            pass

    def _handle_image(self, key, data):
        if not data:
            self.ready.emit(key, QPixmap())
            return
        img = QImage()
        if not img.loadFromData(data):
            self.ready.emit(key, QPixmap())
            return
        pm = QPixmap.fromImage(img)
        if pm.isNull():
            self.ready.emit(key, QPixmap())
            return
        self._mem[key] = pm
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            pm.save(str(self._cache_path(key)), "JPG")
        except OSError:
            pass
        self.ready.emit(key, pm)
