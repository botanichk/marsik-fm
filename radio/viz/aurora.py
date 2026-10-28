"""Aurora — плавные цветные ленты для Marsik FM.

Несколько широких светящихся лент, медленно плывущих вверх, как полярное
сияние. Каждая лента «чувствует» свою полосу спектра (низ → верх): амплитуда
изгиба и яркость дышат в такт реальным частотам из аудио-тапа, положение
плывёт по процедурному шуму. Мягкие многослойные градиенты дают ореол без
тяжёлых эффектов — чистый QPainter, ноль новых зависимостей.

Без сигнала — ленты едва дышат в полутьме (idle). Палитра Marsik:
cyan → blue → violet → magenta.
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ..theme import manager as _themes
from .base import Visualizer

_RIBBONS = 5            # количество лент
# (оттенок 0..1, полоса спектра, фаза, базовая амплитуда)
_PARAMS = (
    (0.00, 0, 0.00, 1.00),   # cyan, «бас»
    (0.22, 1, 1.30, 0.85),
    (0.45, 3, 2.60, 0.75),   # blue-violet, середина
    (0.70, 5, 3.90, 0.65),
    (1.00, 7, 5.20, 0.55),   # magenta, «верх»
)
# ширина/прозрачность слоёв свечения
_GLOW = ((26.0, 0.05), (9.0, 0.16), (3.0, 0.55))


def _ramp(h):
    return _themes.current.ramp(h)


class Aurora(Visualizer):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        t, env = self._t, self._env

        th = _themes.current
        self._draw_bg(p, th.q(th.viz_bg_dark))

        step = max(8, w // 60)
        for idx in range(_RIBBONS):
            hue, band, phase, base_amp = _PARAMS[idx]
            bandv = self._bands[band] if band < len(self._bands) else 0.0
            energy = 0.5 * env + 0.5 * bandv

            # лента плывёт вверх и циклически возвращается (как сияние)
            rise = (t * 0.05 + phase * 0.13) % 1.0
            base_y = h * (0.78 - 0.45 * rise)
            # амплитуда изгиба: реальная (полоса + энергия)
            amp = h * 0.10 * base_amp * (0.55 + 0.9 * energy)
            # медленный боковой дрейф по процедурному шуму
            drift = w * 0.08 * math.sin(t * 0.13 + phase)

            path = QPainterPath()
            x = 0.0
            while x <= w:
                u = x / w
                y = (base_y
                     + amp * math.sin(2.4 * math.pi * u + t * 0.7 + phase)
                     + amp * 0.45 * math.sin(5.1 * math.pi * u - t * 0.45 + phase))
                y += drift * math.sin(math.pi * u)   # край ленты ниже центра
                if x == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
                x += step

            base = _ramp(hue)
            # затухание к краям экрана (лента «уходит» за горизонт)
            fade = 0.35 + 0.65 * (1.0 - rise)
            for width, alpha in _GLOW:
                p.setPen(QPen(QColor(*base), width, Qt.SolidLine, Qt.RoundCap))
                p.setOpacity(alpha * (0.35 + 0.65 * energy) * fade)
                p.drawPath(path)
        p.setOpacity(1.0)
