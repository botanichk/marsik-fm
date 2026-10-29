"""Fireflies — светлячки / боке для Marsik FM.

Мягкие огоньки медленно плывут вверх, как в лоуфай-видео. Каждый привязан
к полосе спектра: яркость дышит в такт своей частоте, на ударе баса все
вспыхивают и подпрыгивают. Цвета — градиент темы. Без сигнала — спокойно
мерцают (idle).
"""
import math
import random

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient

from ..theme import manager as _themes
from .base import Visualizer

_N = 64
_USE = 30


class Fireflies(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        rnd = random.Random(7)
        # x, y (0..1), скорость, радиус, фаза мерцания, полоса, лёгкий дрейф
        self._flies = [
            [rnd.random(), rnd.random(), 0.01 + 0.03 * rnd.random(),
             0.010 + 0.022 * rnd.random(), rnd.random() * 6.28,
             rnd.randrange(_USE), rnd.random() * 6.28]
            for _ in range(_N)
        ]

    def _update(self, dt, now):
        kick = 1.0 + 4.0 * self._beat + 1.5 * self._bass
        for f in self._flies:
            f[1] -= f[2] * dt * kick * (1.0 if self._active else 0.5)
            f[0] += math.sin(now * 0.4 + f[6]) * dt * 0.012
            if f[1] < -0.05:                 # уплыл вверх — снова снизу
                f[1] = 1.05
                f[0] = random.random()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        th = _themes.current
        t = self._t

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, th.q(th.viz_bg))
        bg.setColorAt(1.0, th.q(th.viz_bg_dark))
        self._draw_bg(p, bg)

        base = min(w, h)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        for x, y, _s, r, ph, band, _d in self._flies:
            v = self._smooth[band] if self._active else 0.0
            twinkle = 0.5 + 0.5 * math.sin(t * 1.4 + ph)
            glow = 0.18 + 0.30 * twinkle + 0.75 * v + 0.45 * self._beat
            glow = min(1.0, glow)
            rad = base * r * (0.8 + 0.7 * v + 0.35 * self._beat)
            col = th.ramp(band / (_USE - 1))
            px, py = x * w, y * h
            g = QRadialGradient(px, py, rad * 3.0)
            g.setColorAt(0.0, th.q(col, int(230 * glow)))
            g.setColorAt(0.25, th.q(col, int(110 * glow)))
            g.setColorAt(1.0, th.q(col, 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(px, py), rad * 3.0, rad * 3.0)
            # яркое ядро
            core = tuple(min(255, int(c + (255 - c) * 0.6)) for c in col)
            p.setBrush(th.q(core, int(255 * glow)))
            p.drawEllipse(QPointF(px, py), rad * 0.45, rad * 0.45)
