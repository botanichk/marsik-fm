"""AudioTap — пассивный перехват системного звука для визуализаторов.

Читает monitor-порт sink'а, на котором играет mpv, через GStreamer
(pulsesrc из установленных gst-plugins-good). mpv не трогается, второй
сетевой поток не открывается.

Одна ветка без tee (tee в этой сборке GStreamer не прокидывает данные к
sinks): элемент `spectrum` считает 8 полос и широкую громкость, и он же
пропускает PCM дальше — в appsink, который отдаёт форму волны для
осциллографа. Частота спектра ~33 раза/сек — достаточно для всех режимов.

GstValueList не разбирается через get_value в этой сборке PyGObject, поэтому
полосы читаются из s.to_string() (надёжно, покрыто try/except), а волна —
struct.unpack из appsink. Любая ошибка уводит тап в idle: радио не страдает.
Watchdog раз в 5 секунд следит за сменой default sink.
"""
import re
import struct
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
except Exception:
    Gst = None

_BANDS = 8          # число полос спектра
_WAVE_STEP = 6      # шаг сэмпления формы волны
_WAVE_MAX = 256     # максимум точек в срезе волны
_INTERVAL = 30000000  # 30 мс между спектрами (~33 Гц)
# magnitude=(float){ -13.4, -18.6, ... } → числа через to_string()
_MAG_RE = re.compile(r"magnitude=\(float\)\{([^}]*)\}")


class AudioTap(QObject):
    level = Signal(float)        # громкость 0..1
    bands = Signal(list)         # 8 полос спектра 0..1 (низ → верх)
    wave = Signal(list)          # срез формы волны -1..1 (для scope)
    failed = Signal(str)         # диагностика; визуализаторы уходят в idle

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
        # без tee: spectrum пропускает PCM в appsink и шлёт сообщения на шину
        launch = (
            'pulsesrc device="{dev}" ! audioconvert ! '
            "audio/x-raw,format=F32LE,channels=1,rate=44100 ! "
            "spectrum bands={bands} threshold=-80 post-messages=true "
            "message-magnitude=true interval={intv} ! "
            'appsink name=sink emit-signals=true max-buffers=2 drop=true '
            "sync=false"
        ).format(dev=device, bands=_BANDS, intv=_INTERVAL)
        try:
            pl = Gst.parse_launch(launch)
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
        # из потока GStreamer; teardown откладываем watchdog'у
        if message.type == Gst.MessageType.ERROR:
            if self._want:
                err, _ = message.parse_error()
                self._broken = True
                self.failed.emit(str(err))
            return Gst.BusSyncReply.DROP
        if message.type == Gst.MessageType.EOS:
            return Gst.BusSyncReply.DROP
        if message.type == Gst.MessageType.ELEMENT:
            self._on_spectrum(message)
            return Gst.BusSyncReply.DROP
        return Gst.BusSyncReply.PASS

    def _on_spectrum(self, message):
        """Разбор spectrum → полосы + громкость (через to_string, без numpy)."""
        s = message.get_structure()
        if s is None or s.get_name() != "spectrum":
            return
        try:
            text = s.to_string()
        except Exception:
            return
        m = _MAG_RE.search(text)
        if not m:
            return
        try:
            db = [float(x) for x in m.group(1).split(",") if x.strip()]
        except ValueError:
            return
        if not db:
            return
        # dB → 0..1: музыка лежит в ~-60..-20 dB, тишина ≈ -80
        vals = [max(0.0, min(1.0, (v + 60.0) / 40.0)) for v in db]
        self.level.emit(max(vals))
        self.bands.emit(vals)

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                data = info.data
                n = len(data) // 4           # F32LE = 4 байта на сэмпл
                if n:
                    vals = struct.unpack_from("<%df" % n, data, 0)
                    step = max(1, n // _WAVE_MAX)
                    self.wave.emit(list(vals[::step])[:_WAVE_MAX])
            except Exception:
                pass
            finally:
                buf.unmap(info)
        return Gst.FlowReturn.OK
