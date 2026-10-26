"""Oscilloscope — настоящая форма волны для Marsik FM.

Рисует реальные срезы PCM из аудио-тапа (сигнал set_wave, -1..1), а не
процедурную синусоиду: каждая точка — настоящий сэмпл потока. Несколько
призрачных копий сдвинутых по фазе дают послесвечение (как фосфорный
экран осциллографа), яркость — от AGC-энергии.

Когда данных нет (idle/пауза) — спокойная синусоида с затуханием, честно
помеченная как декоративная, за реакцию её не выдаём.

Палитра Marsik: cyan → blue → violet → magenta.
"""
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from .base import Visualizer

_STOPS = (
    (0.00, (61, 216, 255)),   # cyan
    (0.30, (75, 130, 255)),   # blue
    (0.65, (150, 95, 255)),   # violet
    (1.00, (226, 86, 255)),   # magenta
)
_GHOSTS = 3           # призрачных копии (послесвечение фосфора)
_SIGNAL_TTL = 0.5     # сек: свежий срез формы волны


class Oscilloscope(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._wave_time = 0.0     # время последнего среза волны
        self._sweep = 0.0         # плавный разгон луча в idle

    def set_wave(self, wave):
        super().set_wave(wave)
        if wave:
            self._wave_time = time.monotonic()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        t, env = self._t, self._env

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(8, 11, 22))
        bg.setColorAt(1.0, QColor(4, 5, 11))
        self._draw_bg(p, bg)

        # сетка осциллографа (лёгкая, декоративная — как на приборе)
        p.setPen(QPen(QColor(40, 56, 96, 60), 1))
        step = max(24, int(w // 16))
        for x in range(step, int(w), step):
            p.drawLine(int(x), 0, int(x), int(h))
        for y in range(step, int(h), step):
            p.drawLine(0, int(y), int(w), int(y))

        live = time.monotonic() - self._wave_time < _SIGNAL_TTL
        mid = h * 0.5
        amp = h * 0.36

        grad = QLinearGradient(0, 0, w, 0)
        for pos, col in _STOPS:
            grad.setColorAt(pos, QColor(*col))

        if live and self._wave:
            # НАСТОЯЩАЯ форма волны: точки — реальные сэмплы потока
            pts = self._wave
            n = len(pts)
            # яркость от энергии, но форма — всегда реальная
            base_a = 0.55 + 0.45 * env
            ghosts = [
                (0.0, 1.0, 2.6, 0.90),    # (сдвиг индекса, масштаб y, ширина, альфа)
                (-0.012, 0.82, 6.0, 0.22),
                (-0.026, 0.65, 12.0, 0.10),
            ]
            for dx, ky, pen_w, alpha in ghosts[:_GHOSTS]:
                path = QPainterPath()
                first = True
                for i in range(n):
                    j = i + int(dx * n)
                    if j < 0 or j >= n:
                        continue
                    x = w * i / (n - 1)
                    y = mid - max(-1.0, min(1.0, pts[j] * ky)) * amp
                    if first:
                        path.moveTo(x, y)
                        first = False
                    else:
                        path.lineTo(x, y)
                p.setPen(QPen(grad, pen_w, Qt.SolidLine, Qt.RoundCap))
                p.setOpacity(min(1.0, alpha * base_a + (0.12 if dx else 0)))
                p.drawPath(path)
            p.setOpacity(1.0)
        else:
            # idle: декоративная синусоида (не выдаём за реакцию)
            self._sweep += 0.03 + 0.04 * env
            path = QPainterPath()
            fade = 0.30 if self._active else 0.18
            x = 0.0
            step_px = max(6, w // 90)
            while x <= w:
                y = mid + amp * 0.45 * math.sin(
                    2 * math.pi * 2.2 * x / w + self._sweep)
                if x == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
                x += step_px
            p.setPen(QPen(grad, 1.6, Qt.SolidLine, Qt.RoundCap))
            p.setOpacity(fade)
            p.drawPath(path)
            p.setOpacity(1.0)
