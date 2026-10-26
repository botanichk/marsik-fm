"""AudioEngine: воспроизведение потоков внешним mpv (JSON IPC).

UI общается только с этим классом — движок можно заменить (например, на
GStreamer с appsink для будущих визуализаторов) без переделки интерфейса.

Состояния: stopped / connecting / playing / paused / error.
"""
import json
import os
import queue
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
        self.state = STOPPED

    # ---------- публичный API (вызывается из UI) ----------

    @property
    def is_running(self):
        return bool(
            self._proc and self._proc.poll() is None
            and self._thread and self._thread.is_alive()
        )

    def play(self, url):
        if not self._start():
            return
        self._set_state(CONNECTING)
        self.trackChanged.emit("")
        self._cmds.put(("loadfile", url))

    def stop(self):
        self._set_state(STOPPED)
        self.trackChanged.emit("")
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

        self._sock_path = "%s/radiofm-%s.sock" % (
            os.environ.get("XDG_RUNTIME_DIR") or "/tmp", os.getpid())
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
            for cmd in (("observe_property", 1, "icy-title"),
                        ("observe_property", 2, "pause")):
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
        elif ev == "end-file":
            self._on_end_file(msg)
        elif ev == "property-change":
            self._on_property(msg)
        elif msg.get("error") not in (None, "success"):
            if self.state == CONNECTING:
                self._set_state(ERROR)
                self.errorRaised.emit("Сервер ответил ошибкой: %s" % msg["error"])

    def _on_end_file(self, msg):
        reason = msg.get("reason", "")
        if reason in _END_IGNORE or self.state == STOPPED:
            return
        detail = msg.get("file_error") or ""
        if reason == "eof":
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
        elif name == "icy-title":
            data = msg.get("data")
            if data:
                self.trackChanged.emit(str(data))

    def _set_state(self, new_state):
        if self.state == new_state:
            return
        self.state = new_state
        self.stateChanged.emit(new_state)
