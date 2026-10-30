"""Spectrum — тонкий спектр-анализатор для Marsik FM.

58 узких столбиков по реальному спектру в полном разрешении (64 бина),
растут от нижней линии, под ними — размытое отражение «пола». Над каждым
столбиком — точка пика, которая плавно падает. Цвет — градиент темы по
частоте, на ударе баса вся картинка слегка вспыхивает. Без сигнала —
столбики лежат тонкой линией и едва дышат.
"""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter

from ..theme import manager as _themes
from .base import Visualizer

_N = 58


class Spectrum(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._caps = [0.0] * _N
        self._capv = [0.0] * _N

    def _update(self, dt, now):
        for i in range(_N):
            v = self._smooth64[i] if self._active else 0.0
            if v >= self._caps[i]:
                self._caps[i] = v
                self._capv[i] = 0.0
            else:
                self._capv[i] += dt * 1.8
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

        margin = w * 0.04
        slot = (w - 2 * margin) / _N
        bw = max(2.0, slot * 0.46)
        base_y = h * 0.70
        max_h = h * 0.58
        boost = 1.0 + 0.10 * self._beat

        for i in range(_N):
            v = self._smooth64[i] if self._active else 0.0
            idle = 0.5 + 0.5 * math.sin(t * 1.4 + i * 0.35)
            bh = bw + max_h * max(v, 0.012 * idle) ** 0.85 * boost
            x = margin + slot * (i + 0.5)
            col = th.ramp(i / (_N - 1))
            top = tuple(min(255, int(c + (255 - c) * 0.4)) for c in col)
            # свечение (аддитивно)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            p.setPen(Qt.NoPen)
            p.setBrush(th.q(col, int(22 + 45 * v)))
            gw = bw * 3.0
            p.drawRoundedRect(QRectF(x - gw / 2, base_y - bh - 2, gw, bh + 4), gw / 2, gw / 2)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            # столбик
            g = QLinearGradient(0, base_y - bh, 0, base_y)
            g.setColorAt(0.0, th.q(top, 250))
            g.setColorAt(1.0, th.q(col, 215))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x - bw / 2, base_y - bh, bw, bh), bw / 2, bw / 2)
            # отражение
            rg = QLinearGradient(0, base_y + 3, 0, base_y + 3 + bh * 0.55)
            rg.setColorAt(0.0, th.q(col, 85))
            rg.setColorAt(1.0, th.q(col, 0))
            p.setBrush(rg)
            p.drawRect(QRectF(x - bw / 2, base_y + 3, bw, bh * 0.55))
            # пик
            cap = self._caps[i] if self._active else 0.0
            if cap > 0.05:
                cy = base_y - (bw + max_h * cap ** 0.85 * boost) - bw * 1.6
                p.setBrush(th.q(top, 230))
                p.drawEllipse(QRectF(x - bw * 0.55, cy - bw * 0.55, bw * 1.1, bw * 1.1))

        # линия пола
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        fg = QLinearGradient(margin, 0, w - margin, 0)
        for pos, col in th.stops:
            fg.setColorAt(pos, th.q(col, 120))
        p.setPen(Qt.NoPen)
        p.setBrush(fg)
        p.drawRect(QRectF(margin, base_y + 0.5, w - 2 * margin, 1.5))
