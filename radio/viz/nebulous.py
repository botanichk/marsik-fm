"""Nebulous — мягкая космическая туманность для Marsik FM.

Несколько дрейфующих газовых пятен (многослойные радиальные градиенты) на
тёмном фоне. Цвет и яркость каждого пятна дышат в такт реальным полосам
спектра (низ/середина/верх из аудио-тапа), а положение медленно плывёт по
процедурному шуму. Форма пятен — не декорация: размер и насыщенность
привязаны к AGC-энергии, поэтому на ударных треках туманность пульсирует
ярче, на тихом эмбиенте — едва дышит. Без сигнала — спокойный idle.

Палитра Marsik: cyan → blue → violet → magenta (как у волны).
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from .base import Visualizer

# (оттенок 0..1 по спектру, радиус-множитель, фаза дрейфа, вес полосы)
_BLOBS = (
    (0.00, 1.15, 0.00, 0),   # cyan, крупный, «бас»
    (0.30, 0.90, 1.70, 1),   # blue, средний
    (0.65, 0.75, 3.10, 2),   # violet, поменьше
    (1.00, 0.55, 4.90, 6),   # magenta, акцент (верх)
    (0.15, 0.70, 2.30, 0),   # голубой, бас
    (0.85, 0.60, 5.60, 5),   # пурпур, верх
)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _ramp(h):
    """Палитра 0..1 → RGB (cyan → blue → violet → magenta)."""
    stops = ((0.00, (61, 216, 255)), (0.30, (75, 130, 255)),
             (0.65, (150, 95, 255)), (1.00, (226, 86, 255)))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if h <= p1:
            t = (h - p0) / (p1 - p0) if p1 > p0 else 0.0
            return _lerp(c0, c1, max(0.0, min(1.0, t)))
    return stops[-1][1]


class Nebulous(Visualizer):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        t, env = self._t, self._env

        # фон: глубокий тёмно-синий с затемнением к низу (как у волны)
        self._draw_bg(p, QColor(7, 9, 18))

        cx, cy = w * 0.5, h * 0.5
        minwh = min(w, h)

        for hue, rf, phase, band in _BLOBS:
            # реальная реакция: вес полосы спектра + общая энергия
            bandv = self._bands[band] if band < len(self._bands) else 0.0
            energy = 0.55 * env + 0.45 * bandv

            # дрейф по процедурному шуму (медленный, органичный)
            ox = 0.16 * w * math.sin(t * 0.11 + phase)
            oy = 0.12 * h * math.cos(t * 0.09 + phase * 1.3)
            bx, by = cx + ox, cy + oy

            # радиус: пульсирует от музыки, еле заметно дышит в idle
            rad = minwh * 0.34 * rf * (0.9 + 0.5 * energy)

            base = _ramp(hue)
            # яркость: тьма в паузах, свет в ударах
            alpha_peak = int(44 + 170 * energy)
            g = QRadialGradient(bx, by, rad)
            g.setColorAt(0.0, QColor(*base, alpha_peak))
            g.setColorAt(0.5, QColor(*base, int(alpha_peak * 0.55)))
            g.setColorAt(1.0, QColor(*base, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(bx, by, rad, rad)

        # мягкое центральное свечение, ярче от общей энергии
        halo = QRadialGradient(cx, cy, minwh * 0.6)
        halo.setColorAt(0, QColor(70, 110, 210, int(10 + 44 * env)))
        halo.setColorAt(1, QColor(70, 110, 210, 0))
        p.fillRect(self.rect(), halo)
