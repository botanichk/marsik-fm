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

from .base import Visualizer

_STARS = 220          # количество звёзд
_ARMS = 3             # спиральные рукава
_PHI = 1.375          # угол «золотого сечения» между звёздами (не даёт сгустков)


def _ramp(h):
    """Палитра 0..1 → RGB (cyan → blue → violet → magenta)."""
    stops = ((0.00, (61, 216, 255)), (0.30, (75, 130, 255)),
             (0.65, (150, 95, 255)), (1.00, (226, 86, 255)))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if h <= p1:
            t = (h - p0) / (p1 - p0) if p1 > p0 else 0.0
            c = tuple(int(c0[k] + (c1[k] - c0[k]) * max(0.0, min(1.0, t)))
                      for k in range(3))
            return c
    return stops[-1][1]


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

        self._draw_bg(p, QColor(5, 6, 14))

        cx, cy = w * 0.5, h * 0.5
        R = min(w, h) * 0.46

        # вращение: быстрее от музыки, еле заметно в idle
        spin = t * (0.10 + 0.32 * env)

        # ядро галактики (компактное, иначе съедает рукава)
        core = QRadialGradient(cx, cy, R * 0.26)
        core.setColorAt(0.0, QColor(150, 215, 255, int(24 + 70 * env)))
        core.setColorAt(0.5, QColor(90, 130, 235, int(10 + 40 * env)))
        core.setColorAt(1.0, QColor(40, 60, 160, 0))
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
            flash.setColorAt(0.0, QColor(230, 240, 255, a))
            flash.setColorAt(0.3, QColor(160, 190, 255, int(a * 0.6)))
            flash.setColorAt(1.0, QColor(120, 90, 255, 0))
            p.setBrush(flash)
            p.drawEllipse(cx, cy, R * 0.7 * self._nova, R * 0.7 * self._nova)
