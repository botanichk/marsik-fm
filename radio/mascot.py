"""Marsik — маскот-кот для Marsik FM.

Силуэт кота, который сидит рядом с волной и реагирует на реальный звук
(ту же AGC-энергию, что и GlowingWave — сигнал общий, дублей нет):

- уши и усы расходятся тем сильнее, чем громче музыка (env 0..1);
- на сильном транзиенте (резкий скачок энергии) кот вздрагивает;
- при остановке воспроизведения — зевает и дремлет;
- без сигнала — спокойно дышит (честный idle, не выдаётся за реакцию).

Всё процедурное и своё — силуэт рисуется QPainter'ом, никаких ассетов.
"""
import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

_IDLE = 0.06           # энергия, ниже которой кот считается спящим
_FLINCH_JUMP = 0.22    # скачок env за тик, выше которого кот вздрагивает


class MarsikCat(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 140)
        self._env = 0.0        # сглаженная энергия 0..1 (из волны)
        self._flinch = 0.0     # вздрагивание 0..1 (затухает)
        self._yawn = 0.0       # зевок 0..1 (затухает)
        self._active = False   # воспроизведение идёт
        self._breath = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------- вход извне ----------

    def set_energy(self, env):
        env = max(0.0, min(1.0, float(env)))
        # резкий скачок энергии = удар → вздрагиваем
        if env - self._env > _FLINCH_JUMP:
            self._flinch = 1.0
        self._env = env

    def set_active(self, active):
        active = bool(active)
        # остановка воспроизведения → зевок
        if self._active and not active:
            self._yawn = 1.0
        self._active = active

    # ---------- анимация ----------

    def _tick(self):
        self._breath += 0.05
        self._flinch = max(0.0, self._flinch - 0.06)
        self._yawn = max(0.0, self._yawn - 0.03)
        self.update()

    # ---------- отрисовка ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())

        env = self._env if self._active else 0.0
        flinch = self._flinch
        # дыхание: глубже во сне, едва заметное в бою
        breathe = (1.0 + 0.04 * math.sin(self._breath)) * (1.0 + 0.05 * (1 - env))

        fur = QColor(30, 34, 52)            # тёмная шёрстка на фоне неба
        rim = QColor(90, 200, 255)          # холодная кайма, как у волны
        eye = QColor(120, 230, 255)         # светящиеся глаза

        cx = w * 0.5
        cy = h * 0.62 + flinch * 6.0        # вздрагивание — короткий «подскок»
        scale = min(w, h) / 200.0

        # --- тело (яйцевидный силуэт с ушами) ---
        body = QPainterPath()
        bw, bh = 46 * scale * breathe, 58 * scale * breathe
        body.addEllipse(QPointF(cx, cy + 24 * scale), bw * 0.8, bh * 0.6)

        # --- голова ---
        head_r = 40 * scale * breathe
        head_y = cy - 10 * scale
        body.addEllipse(QPointF(cx, head_y), head_r, head_r * 0.9)

        # --- уши (реагируют на громкость: вверх от звука, вниз во сне) ---
        perk = env * 1.0                      # 0..1 — «настороженность»
        for side in (-1, 1):
            tip_x = cx + side * head_r * 0.62
            tip_y = head_y - head_r * (0.75 + 0.45 * perk) + flinch * 4.0
            body.moveTo(cx + side * head_r * 0.15, head_y - head_r * 0.72)
            body.lineTo(tip_x, tip_y)
            body.lineTo(cx + side * head_r * 0.95, head_y - head_r * 0.30)
            body.closeSubpath()

        p.setPen(QPen(rim, 1.6))
        p.setBrush(fur)
        p.drawPath(body)

        # --- глаза: прищур во сне, открыты от музыки, сомкнуты при зевке ---
        open_ = max(env, 0.12)
        if self._yawn > 0.3:
            open_ = 0.05
        for side in (-1, 1):
            ex = cx + side * head_r * 0.40
            ey = head_y - head_r * 0.05
            er = head_r * 0.16
            p.setBrush(eye if open_ > 0.3 else fur)
            p.setPen(QPen(rim, 1.2))
            p.drawEllipse(QPointF(ex, ey), er, er * (0.4 + 1.4 * open_))
            # зрачок-щель
            if open_ > 0.3:
                p.setBrush(QColor(10, 14, 26))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(ex, ey), er * 0.3, er * 1.1 * open_)

        # --- нос и рот ---
        p.setBrush(QColor(226, 120, 160))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, head_y + head_r * 0.30),
                      3.5 * scale, 2.5 * scale)

        # зевок — открытая пасть
        if self._yawn > 0.1:
            p.setBrush(QColor(120, 40, 70))
            p.setPen(QPen(rim, 1.0))
            p.drawEllipse(QPointF(cx, head_y + head_r * 0.55),
                          8 * scale * self._yawn, 10 * scale * self._yawn)
        else:
            p.setPen(QPen(rim, 1.4))
            mouth = QPainterPath()
            mouth.moveTo(cx - 6 * scale, head_y + head_r * 0.42)
            mouth.quadTo(cx, head_y + head_r * 0.55,
                         cx + 6 * scale, head_y + head_r * 0.42)
            p.drawPath(mouth)

        # --- усы: расходятся от громкости (реальная энергия) ---
        whisker_len = (26 + 16 * env) * scale
        p.setPen(QPen(rim, 1.2))
        for side in (-1, 1):
            base_x = cx + side * head_r * 0.55
            base_y = head_y + head_r * 0.30
            for spread in (-0.30, -0.05, 0.20):
                dx = side * whisker_len * math.cos(spread)
                dy = whisker_len * math.sin(spread) - env * 6 * scale
                p.drawLine(QPointF(base_x, base_y),
                           QPointF(base_x + dx, base_y + dy))

        # --- хвост: подрагивает в такт, если громко ---
        tail_sway = math.sin(self._breath * (1 + 3 * env)) * (6 + 20 * env)
        p.setPen(QPen(rim, 3.0))
        tail = QPainterPath()
        tail.moveTo(cx + bw * 0.7, cy + 40 * scale)
        tail.quadTo(cx + bw * 1.3 + tail_sway, cy + 30 * scale,
                    cx + bw * 1.1 + tail_sway, cy - 6 * scale)
        p.drawPath(tail)
