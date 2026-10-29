"""Ring — круговой спектр вокруг котика для Marsik FM.

Эмблема котика (assets/emblem.png) в круге в центре, вокруг — кольцо из
палочек по 32 полосам реального спектра (симметрично слева/справа). На
ударе бас котик «подпрыгивает» и от него расходится волна. Под кольцом —
надпись MARSiK FM (assets/wordmark.png) на светлой плашке, чтобы она читалась
на любой теме. Нет файлов — рисуется простой круг с нотой. Цвета — из темы.
"""
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)

from ..theme import manager as _themes
from .base import Visualizer

_ROOT = Path(__file__).resolve().parents[2]
_EMBLEM = _ROOT / "assets" / "emblem.png"
_WORDMARK = _ROOT / "assets" / "wordmark.png"
_OLD_LOGO = _ROOT / "backgrounds" / "logo.png"
_USE = 30
_SPOKES = 60           # палочек на кольце (зеркально по _USE бинам)


class Ring(Visualizer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logo = QPixmap(str(_EMBLEM))
        if self._logo.isNull():
            self._logo = QPixmap(str(_OLD_LOGO))
        self._wm = QPixmap(str(_WORDMARK))
        self._shock = 0.0
        self._prev_beat = 0.0

    def _update(self, dt, now):
        # передний фронт импульса удара → расходящаяся волна
        if self._beat > 0.95 and self._prev_beat <= 0.95:
            self._shock = 1.0
        self._prev_beat = self._beat
        self._shock = max(0.0, self._shock - dt * 1.3)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = float(self.width()), float(self.height())
        th = _themes.current
        t = self._t

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, th.q(th.viz_bg))
        bg.setColorAt(1.0, th.q(th.viz_bg_dark))
        self._draw_bg(p, bg)

        base = min(w, h)
        r0 = base * 0.19 * (1.0 + 0.07 * self._beat + 0.03 * self._bass)
        max_len = base * 0.13
        r_out = base * 0.19 * 1.12 + max_len      # максимум кольца
        # надпись под кольцом: считаем общую высоту и центрируем блок
        has_wm = not self._wm.isNull()
        wm_w = min(w * 0.6, base * 0.62)
        wm_h = wm_w * self._wm.height() / self._wm.width() if has_wm else 0.0
        gap = base * 0.04
        total = 2 * r_out + ((gap + wm_h + 16) if has_wm else 0.0)
        cx = w * 0.5
        cy = (h - total) / 2.0 + r_out
        rot = t * 0.08

        # палочки кольца
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for i in range(_SPOKES):
            k = i if i < _SPOKES // 2 else _SPOKES - 1 - i   # зеркало
            bi = min(_USE - 1, int(k * _USE / (_SPOKES / 2)))
            v = self._smooth[bi] if self._active else 0.0
            ln = base * 0.012 + max_len * v ** 0.9
            ang = rot + 2 * math.pi * i / _SPOKES - math.pi / 2
            ca, sa = math.cos(ang), math.sin(ang)
            col = th.ramp(k / (_SPOKES / 2 - 1))
            a = QPointF(cx + ca * (r0 * 1.12), cy + sa * (r0 * 1.12))
            b = QPointF(cx + ca * (r0 * 1.12 + ln), cy + sa * (r0 * 1.12 + ln))
            p.setPen(QPen(th.q(col, int(40 + 50 * v)), base * 0.026,
                          Qt.SolidLine, Qt.RoundCap))
            p.drawLine(a, b)
            p.setPen(QPen(th.q(col, 235), base * 0.011,
                          Qt.SolidLine, Qt.RoundCap))
            p.drawLine(a, b)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # волна от удара
        if self._shock > 0.01:
            rs = r0 * (1.15 + 1.1 * (1.0 - self._shock))
            c = th.ramp(0.15)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(th.q(c, int(150 * self._shock)), 2.0))
            p.drawEllipse(QPointF(cx, cy), rs, rs)

        # круглая подложка и кайма
        p.setPen(QPen(th.q(th.ramp(0.0), 200), 2.2))
        p.setBrush(th.q(th.surface))
        p.drawEllipse(QPointF(cx, cy), r0, r0)

        # котик в круге
        inner = r0 * 0.94
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), inner, inner)
        p.save()
        p.setClipPath(clip)
        if not self._logo.isNull():
            side = 2 * inner
            scaled = self._logo.scaled(int(side), int(side),
                                       Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation)
            p.drawPixmap(int(cx - scaled.width() / 2),
                         int(cy - scaled.height() / 2), scaled)
        else:
            p.setPen(th.q(th.on_surface))
            f = p.font()
            f.setPixelSize(int(inner * 0.9))
            p.setFont(f)
            p.drawText(QRectF(cx - inner, cy - inner, 2 * inner, 2 * inner),
                       Qt.AlignCenter, "♪")
        p.restore()

        # надпись MARSiK FM на светлой плашке (читается на любой теме)
        if has_wm:
            px = cx - wm_w / 2.0
            py = cy + r_out + gap
            plate = QRectF(px - 10, py - 6, wm_w + 20, wm_h + 12)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(253, 239, 220, 238))
            p.drawRoundedRect(plate, 14, 14)
            p.drawPixmap(QRectF(px, py, wm_w, wm_h), self._wm,
                         QRectF(self._wm.rect()))
