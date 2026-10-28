"""Galaxy — спиральное звёздное поле для Marsik FM.

Звёзды распределены по спиральным рукавам Фибоначчи и медленно вращаются
вокруг центра. Каждая звезда привязана к полосе спектра: её яркость и размер
дышат в такт реальным низким/средним/высоким частотам (env 0..1 + _bands),
поэтому галактика пульсирует с музыкой, а не просто крутится.

На сильном ударе (резкий скачок энергии) вспыхивает сверхновая в центре —
это честная реакция на транзиент, а не декорация. Без сигнала — галактика
спокойно вращается в полутьме (idle). Палитра Marsik: cyan → violet → magenta.
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QRadialGradient

from ..theme import manager as _themes
from .base import Visualizer

_STARS = 220          # количество звёзд
_ARMS = 3             # спиральные рукава
_PHI = 1.375          # угол «золотого сечения» между звёздами (не даёт сгустков)


def _ramp(h):
    """Палитра темы 0..1 → RGB."""
    return _themes.current.ramp(h)


class Galaxy(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        # детерминированные параметры звёзд (генерируются один раз)
        # i → (расстояние 0..1, фаза рукава, полоса спектра, базовая яркость)
        self._stars = []
        for i in range(_STARS):
            frac = (i + 0.5) / _STARS
            radius = frac ** 0.62              # звёзды плотнее к центру
            arm = (i % _ARMS) * (2 * math.pi / _ARMS)
            band = i % 8                        # привязка к полосе спектра
            hue = 0.06 + 0.9 * (1.0 - radius)   # центр — cyan, края — magenta
            self._stars.append((radius, arm, band, hue))
        self._nova = 0.0          # вспышка сверхновой 0..1 (затухает)
        self._prev_env = 0.10

    # ---------- анимация состояния ----------

    def _update(self, dt, now):
        # удар = резкий скачок энергии → сверхновая
        if self._active and (self._env - self._prev_env) > 0.20:
            self._nova = 1.0
        self._prev_env = self._env
        self._nova = max(0.0, self._nova - dt * 1.4)   # вспышка гаснет

    # ---------- отрисовка ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        t, env = self._t, self._env

        th = _themes.current
        self._draw_bg(p, th.q(th.viz_bg_dark))
        c0, c1 = th.stops[0][1], th.stops[1][1]
        c3 = th.stops[3][1]

        cx, cy = w * 0.5, h * 0.5
        R = min(w, h) * 0.46

        # вращение: быстрее от музыки, еле заметно в idle
        spin = t * (0.10 + 0.32 * env)

        # ядро галактики (компактное, иначе съедает рукава)
        core = QRadialGradient(cx, cy, R * 0.26)
        lc = tuple(int(v) for v in (c0[0] + (255 - c0[0]) * 0.4,
                                   c0[1] + (255 - c0[1]) * 0.4,
                                   c0[2] + (255 - c0[2]) * 0.4))
        core.setColorAt(0.0, QColor(*lc, int(24 + 70 * env)))
        core.setColorAt(0.5, QColor(*c1, int(10 + 40 * env)))
        core.setColorAt(1.0, QColor(*c1, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(cx, cy, R * 0.26, R * 0.26)

        # звёзды по спиральным рукавам
        for radius, arm, band, hue in self._stars:
            # реальная реакция: полоса спектра + общая энергия
            bandv = self._bands[band] if band < len(self._bands) else 0.0
            energy = 0.5 * env + 0.5 * bandv

            ang = arm + spin + _PHI * radius * 6.0
            r = radius * R
            x = cx + math.cos(ang) * r
            y = cy + math.sin(ang) * r * 0.86   # лёгкий наклон диска

            base = _ramp(hue)
            size = 1.0 + 2.2 * energy + 0.9 * (1.0 - radius)
            alpha = int(70 + 180 * energy)
            p.setBrush(QColor(*base, alpha))
            p.setPen(Qt.NoPen)
            p.drawEllipse(x, y, size, size)
            # мягкое гало вокруг ярких звёзд (аддитивное свечение)
            if energy > 0.35:
                halo = QRadialGradient(x, y, size * 3.2)
                halo.setColorAt(0.0, QColor(*base, int(60 * energy)))
                halo.setColorAt(1.0, QColor(*base, 0))
                p.setBrush(halo)
                p.drawEllipse(x, y, size * 3.2, size * 3.2)

        # сверхновая на ударе — вспышка в центре
        if self._nova > 0.01:
            flash = QRadialGradient(cx, cy, R * 0.7 * self._nova)
            a = int(200 * self._nova)
            wc = tuple(int(v + (255 - v) * 0.75) for v in c0)
            flash.setColorAt(0.0, QColor(*wc, a))
            flash.setColorAt(0.3, QColor(*c1, int(a * 0.6)))
            flash.setColorAt(1.0, QColor(*c3, 0))
            p.setBrush(flash)
            p.drawEllipse(cx, cy, R * 0.7 * self._nova, R * 0.7 * self._nova)
