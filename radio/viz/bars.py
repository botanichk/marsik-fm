"""Bars — пилюльные столбики со свечением для Marsik FM.

32 полосы реального спектра → скруглённые столбики, зеркальные
относительно центральной линии. Над каждым — «шапочка» пика, которая
медленно падает. Цвет — градиент темы по частоте (низ → верх), свечение
рисуется аддитивно. Без сигнала — столбики лежат маленькими точками и
едва дышат (честный idle).
"""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter

from ..theme import manager as _themes
from .base import Visualizer

_USE = 30            # верхние бины обычно пусты (потолок потока) — не рисуем


class Bars(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._caps = [0.0] * _USE
        self._capv = [0.0] * _USE

    def _update(self, dt, now):
        for i in range(_USE):
            v = self._smooth[i]
            if v >= self._caps[i]:
                self._caps[i] = v
                self._capv[i] = 0.0
            else:                       # шапочка падает с ускорением
                self._capv[i] += dt * 1.6
                self._caps[i] = max(v, self._caps[i] - self._capv[i] * dt)

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

        margin = w * 0.05
        slot = (w - 2 * margin) / _USE
        bar_w = max(4.0, slot * 0.62)
        mid = h * 0.5
        max_half = h * 0.40
        min_half = bar_w * 0.5

        for i in range(_USE):
            v = self._smooth[i] if self._active else 0.0
            idle = 0.5 + 0.5 * math.sin(t * 1.3 + i * 0.5)
            half = min_half + max_half * max(v, 0.02 * idle) ** 0.9
            cx = margin + slot * (i + 0.5)
            col = th.ramp(i / (_USE - 1))
            # ореол (аддитивно) и ядро
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            p.setPen(Qt.NoPen)
            p.setBrush(th.q(col, int(26 + 40 * v)))
            glow = bar_w * 1.9
            p.drawRoundedRect(QRectF(cx - glow / 2, mid - half - 3,
                                     glow, 2 * half + 6), glow / 2, glow / 2)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            grad = QLinearGradient(0, mid - half, 0, mid + half)
            top = tuple(min(255, int(c + (255 - c) * 0.35)) for c in col)
            grad.setColorAt(0.0, th.q(top, 245))
            grad.setColorAt(0.5, th.q(col, 235))
            grad.setColorAt(1.0, th.q(top, 245))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(cx - bar_w / 2, mid - half,
                                     bar_w, 2 * half), bar_w / 2, bar_w / 2)
            # шапочки пика
            cap = self._caps[i] if self._active else 0.0
            if cap > 0.06:
                ch = min_half + max_half * cap ** 0.9 + bar_w * 0.9
                p.setBrush(th.q(top, 200))
                for sgn in (-1, 1):
                    p.drawRoundedRect(
                        QRectF(cx - bar_w / 2, mid + sgn * ch - bar_w * 0.3,
                               bar_w, bar_w * 0.6), bar_w * 0.3, bar_w * 0.3)
