"""Oscilloscope — осциллограф с послесвечением для Marsik FM.

Рисует настоящие срезы PCM из аудио-тапа (set_wave, -1..1). Размах
подстраивается автоматически, чтобы линия всегда занимала экран: тихие
треки не превращаются в ровную линию. Слой следов (feedback) даёт
фосфорное послесвечение, второй трейс идёт со сдвигом фазы другим цветом,
на ударе баса сетка вспыхивает. Без сигнала — спокойная синусоида, честно
декоративная. Цвета — из темы.
"""
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from ..theme import manager as _themes
from .base import Visualizer

_SIGNAL_TTL = 0.5


class Oscilloscope(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._wave_time = 0.0
        self._sweep = 0.0
        self._gain = 2.0

    def set_wave(self, wave):
        super().set_wave(wave)
        if wave:
            self._wave_time = time.monotonic()

    def _trace(self, pts, w, mid, amp, shift, gain):
        n = len(pts)
        path = QPainterPath()
        step = max(1, n // 200)
        first = True
        prev = None
        for i in range(0, n, step):
            j = (i + shift) % n
            x = w * i / (n - 1)
            y = mid - max(-1.0, min(1.0, pts[j] * gain)) * amp
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.quadTo(prev[0], prev[1], (prev[0] + x) / 2, (prev[1] + y) / 2)
            prev = (x, y)
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        th = _themes.current
        env = self._env
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, th.q(th.viz_bg))
        bg.setColorAt(1.0, th.q(th.viz_bg_dark))
        self._draw_bg(p, bg)

        # сетка вспыхивает на ударе
        gc = th.stops[1][1]
        p.setPen(QPen(th.q(gc, int(26 + 70 * self._beat)), 1))
        step = max(24, int(w // 16))
        for x in range(step, int(w), step):
            p.drawLine(int(x), 0, int(x), int(h))
        for y in range(step, int(h), step):
            p.drawLine(0, int(y), int(w), int(y))

        live = time.monotonic() - self._wave_time < _SIGNAL_TTL and self._wave
        mid = h * 0.5
        amp = h * 0.40

        img, q = self._fb_begin(0.80 if live else 0.90, zoom=1.0)
        grad = QLinearGradient(0, 0, w, 0)
        for pos, col in th.stops:
            grad.setColorAt(pos, th.q(col))
        q.setCompositionMode(QPainter.CompositionMode_Plus)

        if live:
            pts = self._wave
            peak = max(0.02, max(abs(v) for v in pts))
            target = max(1.0, min(9.0, 0.9 / peak))
            self._gain += (target - self._gain) * min(1.0, self._dt * 3.0)
            g = self._gain
            thick = 2.4 + 2.6 * self._bass + 2.0 * self._beat
            n = len(pts)
            main = self._trace(pts, w, mid, amp, 0, g)
            ghost = self._trace(pts, w, mid, amp * 0.8, n // 12, g)
            # второй трейс — зеркально и другим концом градиента
            grad2 = QLinearGradient(w, 0, 0, 0)
            for pos, col in th.stops:
                grad2.setColorAt(pos, th.q(col))
            q.setBrush(Qt.NoBrush)
            q.setPen(QPen(grad2, thick * 0.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            q.setOpacity(0.45)
            q.drawPath(ghost)
            for width, alpha in ((thick * 4.0, 0.10), (thick * 1.8, 0.35), (thick * 0.7, 0.95)):
                q.setPen(QPen(grad, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                q.setOpacity(alpha)
                q.drawPath(main)
            q.setOpacity(1.0)
        else:
            self._sweep += 0.03 + 0.04 * env
            path = QPainterPath()
            x, step_px = 0.0, max(6, w // 90)
            while x <= w:
                y = mid + amp * 0.45 * math.sin(2 * math.pi * 2.2 * x / w + self._sweep)
                if x == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
                x += step_px
            q.setBrush(Qt.NoBrush)
            q.setPen(QPen(grad, 1.8, Qt.SolidLine, Qt.RoundCap))
            q.setOpacity(0.30 if self._active else 0.18)
            q.drawPath(path)
            q.setOpacity(1.0)
        self._fb_end(p, img, q)
