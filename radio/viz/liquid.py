"""Liquid — жидкий круг для Marsik FM.

Замкнутая капля, контур которой деформируется реальным спектром
(симметрично слева/справа) и медленно «плывёт» на процедурном шуме. На
ударе баса капля раздувается. Заливка — радиальный градиент темы, края
светятся в три прохода (как у Glowing Wave). Без сигнала — спокойно
дышит (idle).
"""
import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)

from ..theme import manager as _themes
from .base import Visualizer

_USE = 30
_POINTS = 96
_GLOW = ((11.0, 0.10), (4.0, 0.35), (1.6, 0.95))


class Liquid(Visualizer):
    def _blob(self, cx, cy, r0, amp, t, phase):
        """Гладкий замкнутый контур: список точек → путь через середины."""
        pts = []
        half = _POINTS // 2
        for i in range(_POINTS):
            k = i if i < half else _POINTS - 1 - i          # зеркало
            x = k * (_USE - 1) / (half - 1)
            lo = int(x)
            fr = x - lo
            hi = min(_USE - 1, lo + 1)
            v = self._smooth[lo] * (1 - fr) + self._smooth[hi] * fr
            if not self._active:
                v = 0.0
            ang = 2 * math.pi * i / _POINTS - math.pi / 2
            wob = (math.sin(3 * ang + t * 0.55 + phase)
                   + 0.6 * math.sin(5 * ang - t * 0.4 + phase * 1.7)) * 0.025
            r = r0 * (1.0 + wob) + amp * v
            pts.append(QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r))
        path = QPainterPath()
        n = len(pts)
        start = QPointF((pts[0].x() + pts[-1].x()) / 2,
                        (pts[0].y() + pts[-1].y()) / 2)
        path.moveTo(start)
        for i in range(n):
            nxt = pts[(i + 1) % n]
            mid = QPointF((pts[i].x() + nxt.x()) / 2,
                          (pts[i].y() + nxt.y()) / 2)
            path.quadTo(pts[i], mid)
        path.closeSubpath()
        return path

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

        cx, cy = w * 0.5, h * 0.5
        base = min(w, h)
        breathe = 1.0 + 0.03 * math.sin(t * 0.8)
        r0 = base * 0.19 * breathe * (1.0 + 0.10 * self._beat
                                     + 0.05 * self._bass)
        amp = base * 0.17

        # внешняя капля: заливка + свечение контура
        outer = self._blob(cx, cy, r0, amp, t, 0.0)
        fill = QRadialGradient(cx, cy, r0 + amp)
        fill.setColorAt(0.0, th.q(th.ramp(0.0), 150))
        fill.setColorAt(0.55, th.q(th.ramp(0.45), 110))
        fill.setColorAt(1.0, th.q(th.ramp(1.0), 40))
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPath(outer)

        # внутренняя, чуть меньше и в противофазе — объём
        inner = self._blob(cx, cy, r0 * 0.62, amp * 0.5, t, 2.1)
        p.setBrush(th.q(th.ramp(0.25), 60))
        p.drawPath(inner)

        grad = QLinearGradient(cx - r0 - amp, cy, cx + r0 + amp, cy)
        for pos, col in th.stops:
            grad.setColorAt(pos, th.q(col))
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setBrush(Qt.NoBrush)
        for width, alpha in _GLOW:
            p.setPen(QPen(grad, width, Qt.SolidLine, Qt.RoundCap,
                          Qt.RoundJoin))
            p.setOpacity(alpha)
            p.drawPath(outer)
        p.setOpacity(0.45)
        p.setPen(QPen(grad, 1.4))
        p.drawPath(inner)
        p.setOpacity(1.0)
