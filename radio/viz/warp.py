"""Warp — полёт сквозь звёзды (гиперпрыжок) для Marsik FM.

Звёзды вылетают из центра и растягиваются в полосы; скорость полёта задаёт
бас, а каждый удар — рывок вперёд со вспышкой. Цвет и яркость каждой звезды
берутся из своей полосы спектра. Следы (feedback) закручивают тоннель: чем
громче середина, тем сильнее поворот. Без сигнала — спокойный дрейф.
Цвета — градиент темы.
"""
import math
import random

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient

from ..theme import manager as _themes
from .base import Visualizer

_N = 230
_USE = 58


class Warp(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        rnd = random.Random(11)
        # угол, радиус 0..1+, скорость, полоса
        self._p = [[rnd.random() * 6.2832, rnd.random(), 0.35 + 0.9 * rnd.random(),
                    rnd.randrange(_USE), 0.0] for _ in range(_N)]
        self._flash = 0.0
        self._prev_beat = 0.0
        self._twist = 0.0

    def _update(self, dt, now):
        if self._beat > 0.95 and self._prev_beat <= 0.95:
            self._flash = 1.0
        self._prev_beat = self._beat
        self._flash = max(0.0, self._flash - dt * 2.4)
        kick = (0.30 + 2.0 * self._bass + 2.6 * self._beat) if self._active else 0.18
        for s in self._p:
            s[4] = s[1]                                   # прошлый радиус (для хвоста)
            s[1] += s[2] * kick * dt * (0.25 + s[1])
            if s[1] > 1.15:
                s[0] = random.random() * 6.2832
                s[1] = 0.02 + random.random() * 0.06
                s[4] = s[1]
                s[2] = 0.35 + 0.9 * random.random()
        mid = sum(self._smooth64[10:30]) / 20.0
        self._twist = 0.003 + 0.02 * mid

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        th = _themes.current
        self._draw_bg(p, th.q(th.viz_bg_dark))
        cx, cy = w * 0.5, h * 0.5
        rmax = math.hypot(w, h) * 0.5

        img, q = self._fb_begin(0.86, zoom=1.02 + 0.02 * self._bass,
                                rot=self._twist if self._active else 0.002)
        q.setCompositionMode(QPainter.CompositionMode_Plus)
        for ang, r, sp, band, rp in self._p:
            v = self._smooth64[band] if self._active else 0.15
            ca, sa = math.cos(ang), math.sin(ang)
            r0 = rp * rmax
            r1 = r * rmax
            if r1 - r0 < 1.0:
                r1 = r0 + 1.0
            col = th.ramp(band / (_USE - 1))
            a = int(255 * min(1.0, (0.30 + 0.70 * v) * min(1.0, r * 3)))
            q.setPen(QPen(th.q(col, a), 0.8 + 3.2 * r * (0.5 + v), Qt.SolidLine, Qt.RoundCap))
            q.drawLine(QPointF(cx + ca * r0, cy + sa * r0), QPointF(cx + ca * r1, cy + sa * r1))

        # свет в центре тоннеля
        gr = rmax * (0.10 + 0.10 * self._bass + 0.16 * self._flash)
        g = QRadialGradient(cx, cy, gr)
        g.setColorAt(0.0, th.q((255, 255, 255), int(40 + 120 * self._flash)))
        g.setColorAt(0.4, th.q(th.ramp(0.3), int(40 + 70 * self._bass)))
        g.setColorAt(1.0, th.q(th.ramp(0.3), 0))
        q.setPen(Qt.NoPen)
        q.setBrush(g)
        q.drawEllipse(QPointF(cx, cy), gr, gr)
        self._fb_end(p, img, q)
