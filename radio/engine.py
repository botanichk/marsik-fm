"""AudioEngine: воспроизведение потоков и плейлистов внешним mpv (JSON IPC).

UI общается только с этим классом — движок можно заменить (например, на
GStreamer с appsink для будущих визуализаторов) без переделки интерфейса.

Два режима воспроизведения:
  play(url)         — одиночный поток (радио) или файл;
  play_playlist()   — очередь файлов из папки: mpv сам переходит к следующему,
                      порядок задаётся shuffle (вперемешку / по порядку).

Состояния: stopped / connecting / playing / paused / error.
"""
import json
import os
import queue
import random
import select
import socket
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal

STOPPED = "stopped"
CONNECTING = "connecting"
PLAYING = "playing"
PAUSED = "paused"
ERROR = "error"

# end-file с этими причинами — штатное поведение (наш stop, quit, подмена файла)
_END_IGNORE = ("stop", "quit", "redirect")


class AudioEngine(QObject):
    stateChanged = Signal(str)
    trackChanged = Signal(str)
    errorRaised = Signal(str)
    playlistChanged = Signal(int, int)   # (позиция в очереди, всего треков)
    positionChanged = Signal(float, float)  # (позиция в треке, длительность)
    seekableChanged = Signal(bool)       # можно ли перематывать (файл, не поток)

    def __init__(self, extra_args=(), parent=None):
        super().__init__(parent)
        self._extra_args = list(extra_args)
        self._cmds = queue.Queue()
        self._stop_evt = threading.Event()
        self._proc = None
        self._thread = None
        self._sock_path = None
        self._pending_volume = 80
        self._paused_prop = False
        self._url = ""              # текущий url (для фильтра media-title)
        self._shuffle = False       # порядок очереди: вперемешку или по порядку
        self._queue_len = 0         # сколько треков в текущей очереди (0 = нет)
        self._seekable = False      # локальный файл: можно перематывать
        self._position = 0.0        # текущая позиция в треке, сек
        self._duration = 0.0        # длительность трека, сек (0 = поток)
        self.state = STOPPED

    # ---------- публичный API (вызывается из UI) ----------

    @property
    def is_running(self):
        return bool(
            self._proc and self._proc.poll() is None
            and self._thread and self._thread.is_alive()
        )

    def _reset_progress(self):
        """Новый трек/поток: позиция с нуля, длительность неизвестна."""
        self._position = 0.0
        self._duration = 0.0
        self.positionChanged.emit(0.0, 0.0)

    def play(self, url):
        if not self._start():
            return
        self._set_state(CONNECTING)
        self._url = url
        self._queue_len = 0
        self._reset_progress()
        self.trackChanged.emit("")
        self._cmds.put(("loadfile", url))

    def play_playlist(self, paths, shuffle=False):
        """Играет очередь файлов; mpv сам переходит к следующему треку.

        paths — список абсолютных путей. shuffle=True перемешивает очередь
        здесь, в Python: mpv не тасует список, собранный через loadfile
        append, а так порядок ровно тот, что мы показали пользователю.
        """
        paths = [p for p in paths if p]
        if not paths:
            return False
        if not self._start():
            return False
        if shuffle and len(paths) > 1:
            first, rest = paths[0], paths[1:]
            random.shuffle(rest)
            paths = [first] + rest
        self._set_state(CONNECTING)
        self._url = paths[0]
        self._queue_len = len(paths)
        self._shuffle = bool(shuffle)
        self._reset_progress()
        self.trackChanged.emit("")
        self._cmds.put(("set_property", "shuffle", "no"))
        self._cmds.put(("loadfile", paths[0], "replace"))
        for path in paths[1:]:
            self._cmds.put(("loadfile", path, "append"))
        return True

    def playlist_next(self):
        """Следующий трек очереди (в конец — по кругу)."""
        if self.is_running and self._queue_len:
            self._cmds.put(("playlist-next", "weak"))

    def playlist_prev(self):
        """Предыдущий трек очереди."""
        if self.is_running and self._queue_len:
            self._cmds.put(("playlist-prev", "weak"))

    def set_shuffle(self, on):
        """Запомнить порядок для следующей очереди (текущая не тасуется)."""
        self._shuffle = bool(on)

    def seek(self, seconds):
        """Перемотка внутри трека (только файлы; у потока длительности нет)."""
        if self.is_running and self._seekable:
            self._cmds.put(("seek", max(0.0, float(seconds)), "absolute"))

    @property
    def seekable(self):
        return self._seekable

    @property
    def has_queue(self):
        return self._queue_len > 0

    def stop(self):
        self._set_state(STOPPED)
        self.trackChanged.emit("")
        self._queue_len = 0
        self._reset_progress()
        if self.is_running:
            self._cmds.put(("stop",))

    def toggle_pause(self):
        if self.is_running:
            self._cmds.put(("cycle", "pause"))

    def set_volume(self, value):
        value = max(0, min(100, int(value)))
        self._pending_volume = value
        if self.is_running:
            self._cmds.put(("set_property", "volume", value))

    def shutdown(self):
        """Гасит mpv и поток; гарантирует отсутствие фоновых сирот."""
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
        if self._sock_path:
            try:
                os.unlink(self._sock_path)
            except OSError:
                pass
        self._thread = None
        self._proc = None
        self._set_state(STOPPED)

    # ---------- запуск mpv ----------

    def _start(self):
        if self.is_running:
            return True
        # остатки прошлой сессии (mpv умер, а поток ещё доживает)
        if self._thread and self._thread.is_alive():
            self._stop_evt.set()
            self._thread.join(timeout=1.5)
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=1.0)

        self._sock_path = "%s/radiofm-%s-%s.sock" % (
            os.environ.get("XDG_RUNTIME_DIR") or "/tmp", os.getpid(),
            id(self) & 0xffff)
        try:
            os.unlink(self._sock_path)
        except OSError:
            pass

        args = [
            "mpv",
            "--no-video",
            "--no-terminal",
            "--idle=yes",
            "--input-ipc-server=" + self._sock_path,
            "--volume=%d" % self._pending_volume,
            "--network-timeout=15",
        ] + self._extra_args

        try:
            self._proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            self._proc = None
            self._set_state(ERROR)
            self.errorRaised.emit("mpv не найден — установите пакет mpv")
            return False

        self._stop_evt.clear()
        self._paused_prop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    # ---------- рабочий поток ----------

    def _run(self):
        sock = self._connect()
        if sock is None:
            if not self._stop_evt.is_set():
                self._set_state(ERROR)
                self.errorRaised.emit("Не удалось подключиться к mpv")
            return
        buf = b""
        try:
            while not self._stop_evt.is_set():
                self._drain_cmds(sock)
                if select.select([sock], [], [], 0.2)[0]:
                    data = sock.recv(65536)
                    if not data:
                        raise ConnectionError("mpv закрыл соединение")
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        if line.strip():
                            self._handle(line)
        except (ConnectionError, OSError):
            if not self._stop_evt.is_set() and self.state not in (STOPPED, ERROR):
                self._set_state(ERROR)
                self.errorRaised.emit("mpv неожиданно завершился")
        finally:
            for payload in (b'{"command":["quit"]}\n',):
                try:
                    sock.sendall(payload)
                except OSError:
                    break
            try:
                sock.close()
            except OSError:
                pass

    def _connect(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop_evt.is_set():
            if self._proc and self._proc.poll() is not None:
                return None
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(self._sock_path)
            except OSError:
                s.close()
                time.sleep(0.05)
                continue
            # подписки: метаданные трека и состояние паузы
            # (icy-title есть не во всех сборках mpv — дублируем media-title)
            for cmd in (("observe_property", 1, "icy-title"),
                        ("observe_property", 2, "pause"),
                        ("observe_property", 3, "media-title"),
                        ("observe_property", 4, "playlist-pos"),
                        ("observe_property", 5, "playlist-count"),
                        ("observe_property", 6, "time-pos"),
                        ("observe_property", 7, "duration"),
                        ("observe_property", 8, "seekable")):
                try:
                    s.sendall((json.dumps({"command": list(cmd)}) + "\n").encode())
                except OSError:
                    s.close()
                    return None
            return s
        return None

    def _drain_cmds(self, sock):
        while True:
            try:
                cmd = self._cmds.get_nowait()
            except queue.Empty:
                return
            try:
                sock.sendall((json.dumps({"command": list(cmd)}) + "\n").encode())
            except OSError:
                return

    # ---------- разбор событий mpv ----------

    def _handle(self, raw):
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return
        ev = msg.get("event")
        if ev == "file-loaded":
            self._set_state(PAUSED if self._paused_prop else PLAYING)
        elif ev == "start-file":
            # переход к следующему треку очереди: полоса начинается с нуля
            self._reset_progress()
        elif ev == "end-file":
            self._on_end_file(msg)
        elif ev == "property-change":
            self._on_property(msg)
        elif ev == "idle":
            # очередь доиграла до конца — mpv ушёл в простой
            if self._queue_len and self.state in (PLAYING, PAUSED):
                self._queue_len = 0
                self._set_state(STOPPED)
                self.trackChanged.emit("")
        elif msg.get("error") not in (None, "success"):
            if self.state == CONNECTING:
                self._set_state(ERROR)
                self.errorRaised.emit("Сервер ответил ошибкой: %s" % msg["error"])

    def _on_end_file(self, msg):
        reason = msg.get("reason", "")
        if reason in _END_IGNORE or self.state == STOPPED:
            return
        detail = msg.get("file_error") or ""
        # eof в очереди — это штатный переход к следующему треку, не ошибка
        if reason == "eof":
            if self._queue_len:
                return
            text = "Соединение с потоком прервано"
        else:
            text = "Не удалось воспроизвести поток — проверьте сеть или URL станции"
        if detail and detail != "loading failed":
            text += " (%s)" % detail
        self._set_state(ERROR)
        self.errorRaised.emit(text)

    def _on_property(self, msg):
        name = msg.get("name")
        if name == "pause":
            self._paused_prop = bool(msg.get("data"))
            if self._paused_prop and self.state == PLAYING:
                self._set_state(PAUSED)
            elif not self._paused_prop and self.state == PAUSED:
                self._set_state(PLAYING)
        elif name in ("time-pos", "duration"):
            data = msg.get("data")
            # у живого потока duration/time-pos может быть None
            if not isinstance(data, (int, float)):
                return
            if name == "duration":
                self._duration = float(data)
            else:
                self._position = float(data)
            self.positionChanged.emit(self._position, self._duration)
        elif name == "seekable":
            new = bool(msg.get("data"))
            if new != self._seekable:
                self._seekable = new
                self.seekableChanged.emit(new)
        elif name in ("playlist-pos", "playlist-count"):
            data = msg.get("data")
            if not isinstance(data, int):
                return
            if name == "playlist-count":
                self._queue_len = max(0, data)
                return
            # playlist-pos: 0-based; -1 = очередь кончилась
            if data >= 0 and self._queue_len > 0:
                self.playlistChanged.emit(data, self._queue_len)
        elif name in ("icy-title", "media-title"):
            data = msg.get("data")
            if not data:
                return
            text = str(data)
            if name == "media-title" and self._is_stream_name(text):
                return   # это имя потока/файла, а не трек
            self.trackChanged.emit(text)

    def _is_stream_name(self, text):
        """media-title до прихода метаданных = имя потока (basename url)."""
        if not self._url.startswith(("http://", "https://")):
            return False   # локальный файл: media-title = имя трека, показываем
        base = os.path.basename(self._url.split("?")[0])
        return text in (base, os.path.splitext(base)[0])

    def _set_state(self, new_state):
        if self.state == new_state:
            return
        self.state = new_state
        self.stateChanged.emit(new_state)
