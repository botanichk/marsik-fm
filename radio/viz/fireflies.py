"""Fireflies — светлячки / боке для Marsik FM (активная версия).

Огоньки плывут вверх и в стороны, ветер задаёт середина спектра; у каждого
своя полоса — яркость и размер дышат в такт частоте. На ударе баса все
вспыхивают и подпрыгивают, а снизу вылетает россыпь искр, которые падают
по дуге. Короткие следы (feedback) превращают движение в мерцающие шлейфы.
Без сигнала — спокойное мерцание. Цвета — градиент темы.
"""
import math
import random

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient

from ..theme import manager as _themes
from .base import Visualizer

_N = 110
_USE = 58
_MAX_SPARKS = 160


class Fireflies(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        rnd = random.Random(7)
        # x, y (0..1), скорость, радиус, фаза мерцания, полоса, фаза дрейфа
        self._flies = [
            [rnd.random(), rnd.random(), 0.03 + 0.07 * rnd.random(),
             0.008 + 0.022 * rnd.random(), rnd.random() * 6.28,
             rnd.randrange(_USE), rnd.random() * 6.28]
            for _ in range(_N)
        ]
        self._sparks = []          # x, y, vx, vy, жизнь, оттенок, размер
        self._prev_beat = 0.0

    def _update(self, dt, now):
        mids = sum(self._smooth64[8:30]) / 22.0
        kick = (1.0 + 6.0 * self._beat + 3.0 * self._bass) if self._active else 0.5
        wind = (0.02 + 0.10 * mids) if self._active else 0.01
        for f in self._flies:
            f[1] -= f[2] * dt * kick
            f[0] += (math.sin(now * 0.6 + f[6]) * wind
                     + math.sin(now * 1.7 + f[4]) * wind * 0.5) * dt * 3.0
            if f[1] < -0.06:
                f[1] = 1.06
                f[0] = random.random()
            if f[0] < -0.05:
                f[0] = 1.05
            elif f[0] > 1.05:
                f[0] = -0.05
        # на ударе — россыпь искр
        if self._beat > 0.95 and self._prev_beat <= 0.95 and self._active:
            for _ in range(22):
                if len(self._sparks) >= _MAX_SPARKS:
                    break
                self._sparks.append([
                    0.15 + 0.7 * random.random(), 0.80 + 0.2 * random.random(),
                    (random.random() - 0.5) * 0.35, -(0.35 + 0.75 * random.random()),
                    1.0, random.random(), 0.006 + 0.012 * random.random()])
        self._prev_beat = self._beat
        alive = []
        for s in self._sparks:
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[3] += 0.55 * dt                    # гравитация: искры идут по дуге
            s[4] -= dt * 0.9
            if s[4] > 0:
                alive.append(s)
        self._sparks = alive

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
        img, q = self._fb_begin(0.78, zoom=1.0)
        q.setCompositionMode(QPainter.CompositionMode_Plus)
        q.setPen(Qt.NoPen)
        for x, y, _s, r, ph, band, _d in self._flies:
            v = self._smooth64[band] if self._active else 0.0
            twinkle = 0.5 + 0.5 * math.sin(t * 1.6 + ph)
            glow = min(1.0, 0.22 + 0.28 * twinkle + 1.1 * v + 0.6 * self._beat)
            rad = base * r * (0.85 + 1.1 * v + 0.55 * self._beat)
            col = th.ramp(band / (_USE - 1))
            px, py = x * w, y * h
            g = QRadialGradient(px, py, rad * 3.4)
            g.setColorAt(0.0, th.q(col, int(240 * glow)))
            g.setColorAt(0.25, th.q(col, int(120 * glow)))
            g.setColorAt(1.0, th.q(col, 0))
            q.setBrush(g)
            q.drawEllipse(QPointF(px, py), rad * 3.4, rad * 3.4)
            core = tuple(min(255, int(c + (255 - c) * 0.6)) for c in col)
            q.setBrush(th.q(core, int(255 * glow)))
            q.drawEllipse(QPointF(px, py), rad * 0.5, rad * 0.5)
        for x, y, vx, vy, life, hue, size in self._sparks:
            col = th.ramp(hue)
            a = max(0.0, life)
            rad = base * size * (0.6 + 0.8 * a)
            px, py = x * w, y * h
            g = QRadialGradient(px, py, rad * 3.0)
            g.setColorAt(0.0, th.q((255, 255, 255), int(230 * a)))
            g.setColorAt(0.3, th.q(col, int(160 * a)))
            g.setColorAt(1.0, th.q(col, 0))
            q.setBrush(g)
            q.drawEllipse(QPointF(px, py), rad * 3.0, rad * 3.0)
        self._fb_end(p, img, q)
