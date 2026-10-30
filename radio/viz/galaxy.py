"""Galaxy — живая спиральная галактика для Marsik FM.

Звёзды лежат на спиральных рукавах; чем дальше от центра, тем выше частота,
которая заставляет звезду вспыхивать (центр — бас, края — верха), поэтому
рукава «горят» по спектру. На каждом ударе баса галактика получает толчок
вращения, из центра расходится волна и вспыхивает сверхновая. Следы звёзд
(feedback) закручиваются по спирали и тянутся за вращением. Без сигнала —
медленное вращение со слабыми следами. Цвета — градиент темы.
"""
import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient

from ..theme import manager as _themes
from .base import Visualizer

_STARS = 380
_ARMS = 3
_PHI = 1.375
_USE = 58            # верхние бины 64 обычно пусты


class Galaxy(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stars = []
        for i in range(_STARS):
            frac = (i + 0.5) / _STARS
            radius = frac ** 0.62
            arm = (i % _ARMS) * (2 * math.pi / _ARMS)
            band = min(_USE - 1, int(radius * (_USE - 1)))   # дальше — выше частота
            jitter = ((i * 2654435761) % 1000) / 1000.0       # детерминированный разброс
            self._stars.append((radius, arm, band, jitter))
        self._spin = 0.0
        self._kick = 0.0
        self._nova = 0.0
        self._shock = 0.0
        self._prev_beat = 0.0

    def _update(self, dt, now):
        if self._beat > 0.95 and self._prev_beat <= 0.95:
            self._kick += 1.4
            self._nova = 1.0
            self._shock = 1.0
        self._prev_beat = self._beat
        self._kick = max(0.0, self._kick - dt * 2.2)
        self._nova = max(0.0, self._nova - dt * 1.6)
        self._shock = max(0.0, self._shock - dt * 1.1)
        speed = 0.10 + 0.55 * self._bass + 0.55 * self._kick
        if not self._active:
            speed = 0.07
        self._spin += speed * dt

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        th = _themes.current
        env = self._env if self._active else 0.0

        self._draw_bg(p, th.q(th.viz_bg_dark))
        cx, cy = w * 0.5, h * 0.5
        R = min(w, h) * 0.50
        # следы стягиваются по спирали и тянутся за вращением
        fade = 0.87 if self._active else 0.78
        img, q = self._fb_begin(fade, zoom=1.004, rot=0.0022 + 0.004 * self._bass)
        q.setCompositionMode(QPainter.CompositionMode_Plus)
        q.setPen(Qt.NoPen)

        # ядро: пульсирует от баса
        cr = R * (0.17 + 0.10 * self._bass + 0.08 * self._beat)
        core = QRadialGradient(cx, cy, cr)
        c0 = th.ramp(0.0)
        wc = tuple(int(v + (255 - v) * 0.6) for v in c0)
        core.setColorAt(0.0, th.q(wc, int(70 + 150 * self._bass + 80 * self._beat)))
        core.setColorAt(0.5, th.q(c0, int(30 + 70 * self._bass)))
        core.setColorAt(1.0, th.q(c0, 0))
        q.setBrush(core)
        q.drawEllipse(QPointF(cx, cy), cr, cr)

        for radius, arm, band, jit in self._stars:
            v = self._smooth64[band] if self._active else 0.0
            energy = 0.25 * env + 0.75 * v
            ang = arm + self._spin + _PHI * radius * 6.0 + 0.25 * math.sin(self._t * 0.3 + radius * 4)
            r = radius * R * (1.0 + 0.10 * self._bass + 0.05 * self._beat * (1 - radius))
            x = cx + math.cos(ang) * r
            y = cy + math.sin(ang) * r * 0.86
            col = th.ramp(radius)
            size = 1.3 + 3.8 * energy + 1.2 * (1.0 - radius) + 1.0 * jit * energy
            alpha = int(90 + 165 * energy)
            q.setBrush(th.q(col, alpha))
            q.drawEllipse(QPointF(x, y), size, size)
            if energy > 0.45:
                halo = QRadialGradient(x, y, size * 4.0)
                halo.setColorAt(0.0, th.q(col, int(110 * energy)))
                halo.setColorAt(1.0, th.q(col, 0))
                q.setBrush(halo)
                q.drawEllipse(QPointF(x, y), size * 4.0, size * 4.0)

        # волна от удара
        if self._shock > 0.01:
            rs = R * (0.15 + 0.95 * (1.0 - self._shock))
            q.setBrush(Qt.NoBrush)
            q.setPen(QPen(th.q(th.ramp(0.2), int(170 * self._shock)), 2.2))
            q.drawEllipse(QPointF(cx, cy), rs, rs * 0.86)
            q.setPen(Qt.NoPen)
        # сверхновая
        if self._nova > 0.01:
            fr = R * 0.75 * self._nova + 4
            flash = QRadialGradient(cx, cy, fr)
            a = int(210 * self._nova)
            flash.setColorAt(0.0, th.q((255, 255, 255), a))
            flash.setColorAt(0.3, th.q(th.ramp(0.35), int(a * 0.6)))
            flash.setColorAt(1.0, th.q(th.ramp(1.0), 0))
            q.setBrush(flash)
            q.drawEllipse(QPointF(cx, cy), fr, fr)
        self._fb_end(p, img, q)
