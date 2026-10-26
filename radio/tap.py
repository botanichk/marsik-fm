"""AudioTap — пассивный перехват системного звука для визуализатора.

Читает monitor-порт sink'а, на котором играет mpv, через GStreamer
(pulsesrc из уже установленных gst-plugins-good). Воспроизведение mpv не
трогается, второй сетевой поток не открывается.

Любая ошибка делает тап недоступным: визуализатор переходит в idle-режим,
радио продолжает работать. Пока воспроизведение активно, watchdog раз в
5 секунд переподбирает default sink (смена аудиоустройства).
"""
import array
import math
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
except Exception:
    Gst = None


class AudioTap(QObject):
    level = Signal(float)     # RMS-огибающая 0..1 (~43 Гц)
    failed = Signal(str)      # диагностика; визуализатор остаётся в idle

    available = Gst is not None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._want = False
        self._pipeline = None
        self._device = None
        self._broken = False
        self._watch = QTimer(self)
        self._watch.setInterval(5000)
        self._watch.timeout.connect(self._watchdog)

    # ---------- публичный API ----------

    def start(self):
        if Gst is None:
            return
        self._want = True
        self._watch.start()
        if self._pipeline is None:
            self._build()

    def stop(self):
        self._want = False
        self._watch.stop()
        self._teardown()

    # ---------- внутренности ----------

    @staticmethod
    def _default_monitor():
        """Имя monitor-порта sink'а, на котором играет mpv (следуем за default)."""
        try:
            out = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True, text=True, timeout=3)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip() + ".monitor"
        except Exception:
            pass
        return None

    def _build(self):
        device = self._default_monitor()
        if not device:
            self.failed.emit("default sink не найден")
            return
        try:
            pl = Gst.parse_launch(
                'pulsesrc device="%s" ! audioconvert ! '
                "audio/x-raw,format=F32LE,channels=1,rate=44100 ! "
                "appsink name=sink emit-signals=true max-buffers=2 "
                "drop=true sync=false" % device)
            sink = pl.get_by_name("sink")
            sink.connect("new-sample", self._on_sample)
            pl.get_bus().set_sync_handler(self._bus_sync, None)
            ret = pl.set_state(Gst.State.PLAYING)
        except Exception as exc:
            self.failed.emit("не удалось собрать тап: %s" % exc)
            return
        if ret == Gst.StateChangeReturn.FAILURE:
            try:
                pl.set_state(Gst.State.NULL)
            except Exception:
                pass
            self.failed.emit("перехват (%s) не запустился" % device)
            return
        self._pipeline = pl
        self._device = device
        self._broken = False

    def _teardown(self):
        pl, self._pipeline = self._pipeline, None
        self._device = None
        self._broken = False
        if pl is not None and Gst is not None:
            try:
                pl.set_state(Gst.State.NULL)
            except Exception:
                pass

    def _watchdog(self):
        if not self._want:
            return
        if self._pipeline is None or self._broken:
            self._teardown()
            self._build()
            return
        device = self._default_monitor()
        if device and device != self._device:
            self._teardown()
            self._build()

    def _bus_sync(self, bus, message, *args):
        # вызывается из потока GStreamer; teardown откладываем watchdog'у,
        # чтобы не ставить pipeline в NULL из его же потока
        if message.type == Gst.MessageType.ERROR:
            if self._want:
                err, _ = message.parse_error()
                self._broken = True
                self.failed.emit(str(err))
            return Gst.BusSyncReply.DROP
        if message.type == Gst.MessageType.EOS:
            return Gst.BusSyncReply.DROP
        return Gst.BusSyncReply.PASS

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                data = info.data
                arr = array.array("f")
                arr.frombytes(data[: len(data) - len(data) % 4])
                if arr:
                    vals = arr[::4]          # каждым 4-м сэмплом — дёшево
                    rms = math.sqrt(sum(v * v for v in vals) / len(vals))
                    # музыкальный RMS ~0.02..0.35 → удобная шкала 0..1
                    self.level.emit(min(1.0, 1.0 - math.exp(-8.0 * rms)))
            finally:
                buf.unmap(info)
        return Gst.FlowReturn.OK
