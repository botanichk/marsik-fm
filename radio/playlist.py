"""Очередь воспроизведения скачанных треков и длительности для списка.

PlayQueue — порядок «все по очереди» или «вперемешку» (зацикленный).
DurationProbe — в фоне узнаёт длительности файлов (ffprobe, запасной
вариант — mpv) и кеширует их; результат приходит сигналом ready.
"""
import queue
import random
import subprocess
import threading
import os

from PySide6.QtCore import QObject, Signal


def fmt_time(sec):
    """83 → '1:23', 3725 → '1:02:05'."""
    sec = max(0, int(sec + 0.5))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


class PlayQueue:
    """Очередь путей. next()/prev() зациклены; при shuffle порядок случайный,
    но каждый трек играет один раз за круг."""

    def __init__(self):
        self.items = []
        self.shuffle = False
        self._order = []
        self._idx = -1

    def _build(self, current):
        n = len(self.items)
        self._order = list(range(n))
        if self.shuffle:
            random.shuffle(self._order)
            if current is not None and current in self._order:
                self._order.remove(current)
                self._order.insert(0, current)
            self._idx = 0
        else:
            self._idx = self._order.index(current) if current in self._order \
                else 0

    def start(self, items, current_path):
        self.items = list(items)
        cur = self.items.index(current_path) \
            if current_path in self.items else None
        self._build(cur)

    def set_shuffle(self, on):
        on = bool(on)
        if on == self.shuffle:
            return
        self.shuffle = on
        if self.items and self._idx >= 0:
            self._build(self._order[self._idx])

    def current(self):
        if 0 <= self._idx < len(self._order):
            return self.items[self._order[self._idx]]
        return None

    def next(self):
        if not self.items:
            return None
        self._idx += 1
        if self._idx >= len(self._order):
            last = self._order[-1] if self._order else None
            self._order = list(range(len(self.items)))
            if self.shuffle:
                random.shuffle(self._order)
                # не повторяем трек, которым закончился прошлый круг
                if (len(self._order) > 1 and self._order[0] == last):
                    self._order.append(self._order.pop(0))
            self._idx = 0
        return self.current()

    def prev(self):
        if not self.items:
            return None
        self._idx = (self._idx - 1) % len(self._order)
        return self.current()


def _probe(path):
    """Длительность файла в секундах (0.0 — не удалось)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip().splitlines()[0])
    except Exception:
        pass
    try:   # запасной путь: сам mpv
        out = subprocess.run(
            ["mpv", "--no-config", "--vo=null", "--ao=null", "--really-quiet",
             "--end=0.05", "--term-playing-msg=DUR=${=duration}", path],
            capture_output=True, text=True, timeout=15)
        for line in out.stdout.splitlines():
            if line.startswith("DUR="):
                return float(line[4:])
    except Exception:
        pass
    return 0.0


class DurationProbe(QObject):
    ready = Signal(str, float)      # путь, длительность (сек)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}
        self._seen = set()
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._thread = None

    @staticmethod
    def _key(path):
        try:
            return (path, os.stat(path).st_mtime_ns)
        except OSError:
            return (path, 0)

    def get(self, path):
        """Длительность из кеша или None."""
        return self._cache.get(self._key(path))

    def request(self, paths):
        with self._lock:
            for path in paths:
                key = self._key(path)
                if key in self._cache or key in self._seen:
                    continue
                self._seen.add(key)
                self._q.put((path, key))
            if not self._q.empty() and (
                    self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(
                    target=self._run, daemon=True)
                self._thread.start()

    def _run(self):
        while True:
            try:
                path, key = self._q.get(timeout=0.5)
            except queue.Empty:
                with self._lock:
                    if self._q.empty():
                        self._thread = None
                        return
                continue
            dur = _probe(path)
            self._cache[key] = dur
            self.ready.emit(path, dur)
