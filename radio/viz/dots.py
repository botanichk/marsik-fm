"""Fireflies Dots — светлячки, от которых разлетаются светящиеся точки.

Плавают чёткие шарики (как в первом Fireflies, только без размытого
ореола). У каждого шарика своя полоса спектра: чем громче эта частота, тем
гуще от него разлетается рой мелких светящихся точек. На ударе баса шарики
вспыхивают и выпускают сразу много точек, точки расходятся, замедляются,
мерцают и гаснут. Без сигнала — спокойное плавание и редкие искорки.
Цвета — градиент темы.
"""
import math
import random

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient

from ..theme import manager as _themes
from .base import Visualizer

_N = 56
_USE = 58
_MAX_DOTS = 1100


class Dots(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        rnd = random.Random(21)
        # x, y (0..1), скорость, радиус, фаза мерцания, полоса, фаза дрейфа, накопитель
        self._orbs = [
            [rnd.random(), rnd.random(), 0.02 + 0.045 * rnd.random(),
             0.007 + 0.014 * rnd.random(), rnd.random() * 6.28,
             rnd.randrange(_USE), rnd.random() * 6.28, rnd.random()]
            for _ in range(_N)
        ]
        # точка: x, y (px), vx, vy (px/с), жизнь 1→0, скорость затухания,
        # оттенок 0..1, радиус (px), фаза мерцания
        self._dots = []
        self._base = 400.0

    def _update(self, dt, now):
        base = self._base
        active = self._active
        beat = self._beat
        w, h = float(self.width()), float(self.height())
        for o in self._orbs:
            o[1] -= o[2] * dt * (1.0 + 1.5 * self._bass if active else 0.5)
            o[0] += math.sin(now * 0.5 + o[6]) * 0.012 * dt * 3.0
            if o[1] < -0.06:
                o[1] = 1.06
                o[0] = random.random()
            v = self._smooth64[o[5]] if active else 0.0
            # сколько точек в секунду выпускает этот шарик
            rate = 1.2 + 34.0 * v ** 1.4 + 38.0 * beat * (0.3 + v)
            o[7] += rate * dt
            while o[7] >= 1.0 and len(self._dots) < _MAX_DOTS:
                o[7] -= 1.0
                ang = random.random() * 6.2832
                sp = base * (0.04 + 0.20 * random.random()) * (1.0 + 1.1 * beat + 0.6 * v)
                self._dots.append([
                    o[0] * w + math.cos(ang) * 2, o[1] * h + math.sin(ang) * 2,
                    math.cos(ang) * sp, math.sin(ang) * sp - base * 0.02,
                    1.0, 0.55 + 0.9 * random.random(),
                    (o[5] / (_USE - 1)) + (random.random() - 0.5) * 0.12,
                    1.1 + 2.0 * random.random(), random.random() * 6.28])
            o[7] = min(o[7], 3.0)
        alive = []
        drag = math.exp(-1.8 * dt)
        for d in self._dots:
            d[0] += d[2] * dt
            d[1] += d[3] * dt
            d[2] *= drag
            d[3] = d[3] * drag - base * 0.012 * dt      # лёгкий подъём вверх
            d[4] -= d[5] * dt
            if d[4] > 0:
                alive.append(d)
        self._dots = alive

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        th = _themes.current
        t = self._t
        self._base = min(w, h)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, th.q(th.viz_bg))
        bg.setColorAt(1.0, th.q(th.viz_bg_dark))
        self._draw_bg(p, bg)

        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        # точки: мелкие, яркие, мерцают
        for x, y, _vx, _vy, life, _d, hue, size, ph in self._dots:
            col = th.ramp(max(0.0, min(1.0, hue)))
            a = life ** 0.8 * (0.65 + 0.35 * math.sin(t * 9.0 + ph))
            core = tuple(min(255, int(c + (255 - c) * 0.55)) for c in col)
            if size > 1.9 and a > 0.35:                                # ореол только у крупных
                p.setBrush(th.q(col, int(70 * a)))
                p.drawEllipse(QPointF(x, y), size * 2.1, size * 2.1)
            p.setBrush(th.q(core, int(255 * min(1.0, a * 1.15))))
            p.drawEllipse(QPointF(x, y), size, size)                   # яркая точка

        # шарики: чёткие, с маленьким ободком вместо большого свечения
        base = self._base
        for x, y, _s, r, ph, band, _d, _acc in self._orbs:
            v = self._smooth64[band] if self._active else 0.0
            twinkle = 0.5 + 0.5 * math.sin(t * 1.6 + ph)
            glow = min(1.0, 0.45 + 0.20 * twinkle + 0.8 * v + 0.5 * self._beat)
            rad = base * r * (0.85 + 0.55 * v + 0.35 * self._beat)
            col = th.ramp(band / (_USE - 1))
            px, py = x * w, y * h
            g = QRadialGradient(px, py, rad * 1.7)
            g.setColorAt(0.0, th.q((255, 255, 255), int(250 * glow)))
            g.setColorAt(0.45, th.q(col, int(235 * glow)))
            g.setColorAt(0.75, th.q(col, int(90 * glow)))
            g.setColorAt(1.0, th.q(col, 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(px, py), rad * 1.7, rad * 1.7)
