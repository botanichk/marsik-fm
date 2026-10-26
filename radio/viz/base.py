"""Базовый класс визуализаторов Marsik FM.

Общий интерфейс, чтобы режимы можно было переключать без переделки UI:
каждый визуализатор — QWidget со стандартными слотами set_audio_level /
set_bands / set_wave / set_active. Внутренние имена приватные (_env и т.д.),
поэтому наследники трогают их через self._env / self._t напрямую — как уже
сделано в GlowingWave.

Здесь же — общая AGC-логика: уровень ОТНОСИТЕЛЬНО медленной базы, чтобы ритм
был виден на любой громкости. Наследники реализуют только paintEvent.
"""
import math
import time

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

_SIGNAL_TTL = 1.2            # сек: без данных дольше — считаем idle


class Visualizer(QWidget):
    envChanged = Signal(float)  # сглаженная энергия 0..1 — для маскота

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 220)
        self._active = False       # воспроизведение идёт (или подключается)
        self._env = 0.10           # сглаженная огибающая 0..1
        self._sig = 0.0            # последний реальный уровень
        self._sig_time = 0.0        # время последнего реального уровня
        self._baseline = 0.14      # медленная база уровня (AGC)
        self._bands = [0.0] * 8    # полосы спектра (низ → верх)
        self._wave = []            # срез формы волны -1..1 (для scope)
        self._bg = None            # фоновая картинка (или None)
        self._phase = 0.0
        self._t = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------- вход извне (стандартный интерфейс) ----------

    def set_audio_level(self, level):
        """Реальный уровень звука 0..1 (вызывается из любого потока)."""
        self._sig = max(0.0, min(1.0, float(level)))
        self._sig_time = time.monotonic()

    def set_bands(self, bands):
        """8 полос спектра 0..1 (низ → верх)."""
        if bands:
            self._bands = list(bands)

    def set_wave(self, wave):
        """Срез сырой формы волны -1..1 (для осциллографа)."""
        if wave:
            self._wave = list(wave)

    def set_active(self, active):
        self._active = bool(active)

    def set_background(self, pixmap):
        """Фоновое изображение (или None — сплошной цвет режима)."""
        self._bg = pixmap
        self.update()

    def _draw_bg(self, p, fill):
        """Общий фон: картинка с тёмной вуалью, либо fill (цвет/градиент)."""
        if self._bg is not None and not self._bg.isNull():
            # cover: заполнить весь виджет с обрезкой по краям
            scaled = self._bg.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            p.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2, scaled)
            # вуаль: без неё свечение не читается на дневном небе
            p.fillRect(self.rect(), QColor(4, 6, 14, 175))
        else:
            p.fillRect(self.rect(), fill)

    # ---------- анимация (общая) ----------

    def _tick(self):
        now = self._clock.elapsed() / 1000.0
        dt = min(0.1, now - self._last) if self._last else 0.016
        self._last = now
        self._t = now

        live = (self._active
                and time.monotonic() - self._sig_time < _SIGNAL_TTL)
        if live:
            # AGC: уровень ОТНОСИТЕЛЬНО медленной базы — ритм виден
            # на любой громкости потока (ударные дают ratio > 1.5)
            self._baseline += (self._sig - self._baseline) * min(1.0, dt * 0.7)
            ratio = self._sig / max(0.03, self._baseline)
            target = max(0.10, min(0.95, 0.45 * ratio - 0.15))
        elif self._active:
            target = 0.13 + 0.04 * math.sin(now * 0.6)   # idle: играем
        else:
            target = 0.08 + 0.02 * math.sin(now * 0.4)   # idle: стоим
        rate = 20.0 if target > self._env else 5.5   # атака быстрее спада
        self._env += (target - self._env) * min(1.0, dt * rate)
        self.envChanged.emit(self._env)

        speed = 0.6 + 1.2 * self._env
        if not self._active:
            speed *= 0.5
        self._phase += dt * speed

        self._update(dt, now)
        self.update()

    def _update(self, dt, now):
        """Хук для наследников со своей логикой анимации."""
        pass

    def paintEvent(self, event):
        """Наследники обязаны переопределить."""
        pass
