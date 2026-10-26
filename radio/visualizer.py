"""Glowing Wave — светящаяся плавающая волна для Marsik FM.

Набор тонких линий с общей фазой, но индивидуальной амплитудой: они
сходятся в узлах и расходятся на пиках («косичка», как на референсе).
Свечение — три прогона обводки в аддитивном режиме: ореол + средний +
тонкое ядро. Градиент пути: cyan → blue → violet → magenta.

Реакция на музыку: set_audio_level(0..1) — RMS-огибающая реального звука
(из audio-тапа). Если данных нет — спокойная idle-анимация (LFO).
"""
import math
import time

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

_LINES = 9
_CYCLES = 2.4
_STOPS = (
    (0.00, (61, 216, 255)),   # cyan
    (0.30, (75, 130, 255)),   # blue
    (0.65, (150, 95, 255)),   # violet
    (1.00, (226, 86, 255)),   # magenta (акцент)
)
# ширина/прозрачность слоёв свечения
_GLOW = ((13.0, 0.07), (3.4, 0.28), (1.3, 0.90))
_SIGNAL_TTL = 1.2            # сек: без данных дольше — считаем idle


def _lighten(col, k=0.28):
    return tuple(int(c + (255 - c) * k) for c in col)


class GlowingWave(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self._active = False       # воспроизведение идёт (или подключается)
        self._env = 0.10           # сглаженная огибающая 0..1
        self._sig = 0.0            # последний реальный уровень
        self._sig_time = 0.0        # время последнего реального уровня
        self._baseline = 0.14      # медленная база уровня (AGC)
        self._phase = 0.0
        self._t = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------- вход извне ----------

    def set_audio_level(self, level):
        """Реальный уровень звука 0..1 (вызывается из любого потока)."""
        self._sig = max(0.0, min(1.0, float(level)))
        self._sig_time = time.monotonic()

    def set_active(self, active):
        self._active = bool(active)

    # ---------- анимация ----------

    def _tick(self):
        now = self._clock.elapsed() / 1000.0
        dt = min(0.1, now - self._last) if self._last else 0.016
        self._last = now
        self._t = now

        live = (self._active
                and time.monotonic() - self._sig_time < _SIGNAL_TTL)
        if live:
            # AGC: уровень ОТНОСИТЕЛЬНО медленной базы — ритм виден
            # на любой громкости потока (ударные дают ratio > 1.5)
            self._baseline += (self._sig - self._baseline) * min(1.0, dt * 0.7)
            ratio = self._sig / max(0.03, self._baseline)
            target = max(0.10, min(0.95, 0.45 * ratio - 0.15))
        elif self._active:
            target = 0.13 + 0.04 * math.sin(now * 0.6)   # idle: играем
        else:
            target = 0.08 + 0.02 * math.sin(now * 0.4)   # idle: стоим
        rate = 20.0 if target > self._env else 5.5   # атака быстрее спада
        self._env += (target - self._env) * min(1.0, dt * rate)

        speed = 0.6 + 1.2 * self._env
        if not self._active:
            speed *= 0.5
        self._phase += dt * speed
        self.update()

    # ---------- отрисовка ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        t, env = self._t, self._env

        # фон: глубокий тёмно-синий с затемнением к низу
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(11, 14, 26))
        bg.setColorAt(1.0, QColor(5, 6, 12))
        p.fillRect(self.rect(), bg)

        # мягкое свечение фона за волной (ярче от музыки)
        halo = QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.5)
        a = int(8 + 44 * env)
        halo.setColorAt(0, QColor(64, 96, 200, a))
        halo.setColorAt(1, QColor(64, 96, 200, 0))
        p.fillRect(self.rect(), halo)

        # градиенты: цветной для ореолов, осветлённый — для ядра
        grad = QLinearGradient(0, 0, w, 0)
        grad_core = QLinearGradient(0, 0, w, 0)
        for pos, col in _STOPS:
            grad.setColorAt(pos, QColor(*col))
            grad_core.setColorAt(pos, QColor(*_lighten(col)))

        # пути линий
        mid = h * 0.52
        amp = h * 0.30 * env
        step = max(6, w // 90)
        two_pi = 2 * math.pi
        paths = []
        for i in range(_LINES):
            # амплитуды «дышат» по-разному → узлы сходятся, пики расходятся
            a_i = 0.40 + 0.60 * (0.5 + 0.5 * math.sin(t * 0.33 + i * 0.62))
            drift = i * 0.10 + 0.18 * math.sin(t * 0.21 + i * 0.47)
            path = QPainterPath()
            x = 0.0
            path.moveTo(0.0, mid + amp * a_i * math.sin(self._phase + drift))
            while x <= w:
                y = mid + amp * a_i * math.sin(
                    two_pi * _CYCLES * x / w + self._phase + drift)
                path.lineTo(x, y)
                x += step
            paths.append(path)

        # свечение: аддитивное смешивание, три прогона
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for width, alpha in _GLOW:
            brush = grad_core if width < 2 else grad
            p.setPen(QPen(brush, width, Qt.SolidLine, Qt.RoundCap))
            p.setOpacity(alpha)
            for path in paths:
                p.drawPath(path)
        p.setOpacity(1.0)
