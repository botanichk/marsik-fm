"""Glowing Wave — светящаяся плавающая волна для Marsik FM.

Набор тонких линий с общей фазой, но индивидуальной амплитудой: они
сходятся в узлах и расходятся на пиках («косичка», как на референсе).
Свечение — три прогона обводки в аддитивном режиме: ореол + средний +
тонкое ядро. Градиент пути: cyan → blue → violet → magenta.

Реакция на музыку и общая AGC-логика — в базовом классе Visualizer;
здесь только отрисовка.
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)

from ..theme import manager as _themes
from .base import Visualizer

_LINES = 9
_CYCLES = 2.4
# ширина/прозрачность слоёв свечения
_GLOW = ((13.0, 0.07), (3.4, 0.28), (1.3, 0.90))


def _lighten(col, k=0.28):
    return tuple(int(c + (255 - c) * k) for c in col)


class GlowingWave(Visualizer):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        t, env = self._t, self._env
        th = _themes.current

        # фон: цвет темы с затемнением к низу
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, th.q(th.viz_bg))
        bg.setColorAt(1.0, th.q(th.viz_bg_dark))
        self._draw_bg(p, bg)

        # мягкое свечение фона за волной (ярче от музыки)
        halo = QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.5)
        a = int(8 + 44 * env)
        hc = th.stops[1][1]
        halo.setColorAt(0, QColor(hc[0], hc[1], hc[2], a))
        halo.setColorAt(1, QColor(hc[0], hc[1], hc[2], 0))
        p.fillRect(self.rect(), halo)

        # градиенты: цветной для ореолов, осветлённый — для ядра
        grad = QLinearGradient(0, 0, w, 0)
        grad_core = QLinearGradient(0, 0, w, 0)
        for pos, col in th.stops:
            grad.setColorAt(pos, QColor(*col))
            grad_core.setColorAt(pos, QColor(*_lighten(col)))

        # пути линий
        mid = h * 0.52
        amp = h * 0.30 * env
        step = max(6, w // 90)
        two_pi = 2 * math.pi
        paths = []
        for i in range(_LINES):
            # амплитуды «дышат» по-разному → узлы сходятся, пики расходятся
            a_i = 0.40 + 0.60 * (0.5 + 0.5 * math.sin(t * 0.33 + i * 0.62))
            drift = i * 0.10 + 0.18 * math.sin(t * 0.21 + i * 0.47)
            path = QPainterPath()
            x = 0.0
            path.moveTo(0.0, mid + amp * a_i * math.sin(self._phase + drift))
            while x <= w:
                y = mid + amp * a_i * math.sin(
                    two_pi * _CYCLES * x / w + self._phase + drift)
                path.lineTo(x, y)
                x += step
            paths.append(path)

        # свечение: аддитивное смешивание, три прогона
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for width, alpha in _GLOW:
            brush = grad_core if width < 2 else grad
            p.setPen(QPen(brush, width, Qt.SolidLine, Qt.RoundCap))
            p.setOpacity(alpha)
            for path in paths:
                p.drawPath(path)
        p.setOpacity(1.0)
