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
from PySide6.QtGui import QColor, QImage, QPainter
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
        self._bands = [0.0] * 8    # 8 грубых полос (для старых режимов)
        self._fine = [0.0] * 32    # 32 полосы спектра (низ → верх)
        self._fine64 = [0.0] * 64  # те же данные в полном разрешении (64)
        self._smooth = [0.0] * 32  # 32 полосы: нормированные и сглаженные
        self._smooth64 = [0.0] * 64  # то же в полном разрешении
        self._dt = 0.016           # длительность последнего кадра
        self._fb = None            # буфер следов прошлого кадра
        self._ref = 0.5            # AGC по спектру: медленный максимум
        self._bandref = [0.3] * 64 # то же, но для каждой полосы отдельно
        self._bass = 0.0           # сглаженная энергия баса 0..1
        self._bass_avg = 0.15      # медленная база баса (для детектора)
        self._beat = 0.0           # импульс удара 0..1 (затухает)
        self._last_beat = 0.0
        self._wave = []            # срез формы волны -1..1 (для scope)
        self._bg = None            # фоновая картинка (или None)
        self._win_bg = False       # оконный фон под всеми режимами
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

    @staticmethod
    def _resample(vals, m):
        """Список любой длины → ровно m значений (усреднение или интерполяция)."""
        n = len(vals)
        if n == m:
            return list(vals)
        if n > m and n % m == 0:
            k = n // m
            return [sum(vals[i * k:(i + 1) * k]) / k for i in range(m)]
        out = []
        for i in range(m):
            x = i * (n - 1) / max(1, m - 1)
            lo = int(x)
            hi = min(n - 1, lo + 1)
            f = x - lo
            out.append(vals[lo] * (1 - f) + vals[hi] * f)
        return out

    def set_bands(self, bands):
        """Полосы спектра 0..1 (низ → верх); тап даёт 64, сворачиваем в 32 и 8."""
        if not bands:
            return
        bands = list(bands)
        self._fine64 = self._resample(bands, 64)
        self._fine = self._resample(bands, 32)
        self._bands = self._resample(bands, 8)

    def set_wave(self, wave):
        """Срез сырой формы волны -1..1 (для осциллографа)."""
        if wave:
            self._wave = list(wave)

    def set_active(self, active):
        self._active = bool(active)

    def set_window_bg(self, on):
        """Оконный фон под всеми режимами: режим рисует только вуаль."""
        self._win_bg = bool(on)
        self.update()

    def set_background(self, pixmap):
        """Фоновое изображение (или None — сплошной цвет режима)."""
        self._bg = pixmap
        self.update()

    def _draw_bg(self, p, fill):
        """Общий фон: картинка с тёмной вуалью, либо fill (цвет/градиент).

        Если включён оконный фон (set_window_bg) — заливки нет, только
        лёгкая вуаль, под ней видно общую картинку окна.
        """
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
        elif self._win_bg:
            # окно само рисует картинку с вуалью — здесь ничего не заливаем,
            # иначе зона визуализатора темнеет вдвое
            pass
        else:
            p.fillRect(self.rect(), fill)

    # ---------- анимация (общая) ----------

    def _tick(self):
        # скрытые режимы (неактивная страница стека) ничего не считают
        if not self.isVisible():
            return
        now = self._clock.elapsed() / 1000.0
        dt = min(0.1, now - self._last) if self._last else 0.016
        self._last = now
        self._t = now
        self._dt = dt

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

        self._analyze(dt, now, live)

        speed = 0.6 + 1.2 * self._env
        if not self._active:
            speed *= 0.5
        self._phase += dt * speed

        self._update(dt, now)
        self.update()

    def _analyze(self, dt, now, live):
        """Спектр: нормировка, сглаживание и детектор ударов по басу."""
        n = len(self._smooth64)
        fine = self._fine64 if live else [0.0] * n
        # AGC: медленный максимум — картинка полная на любой громкости
        self._ref = max(0.35, self._ref - dt * 0.05, max(fine))
        for i in range(n):
            # у каждой полосы свой медленный максимум: тихий верх не тонет
            # рядом с громким басом, но и шум пустых полос не раздувается
            br = max(self._bandref[i] - dt * 0.06, fine[i])
            self._bandref[i] = br
            den = max(0.22, 0.4 * self._ref + 0.6 * br)
            tgt = min(1.0, fine[i] / den)
            cur = self._smooth64[i]
            rate = 28.0 if tgt > cur else 7.0       # атака быстрее спада
            self._smooth64[i] = cur + (tgt - cur) * min(1.0, dt * rate)
        # 32 полосы для режимов, которым хватает такой детализации
        sm = self._smooth64
        self._smooth = [(sm[2 * i] + sm[2 * i + 1]) / 2.0 for i in range(32)]

        # бас = нижние 4 бина из 64 (≈ 0–350 Гц)
        bass = sum(fine[:4]) / 4.0
        self._bass += (bass - self._bass) * min(1.0, dt * 18.0)
        self._bass_avg += (bass - self._bass_avg) * min(1.0, dt * 1.5)
        if (live and bass > self._bass_avg * 1.30 + 0.05
                and now - self._last_beat > 0.15):
            self._beat = 1.0
            self._last_beat = now
        self._beat = max(0.0, self._beat - dt * 4.5)

    # ---------- следы (как «feedback» в WinAmp/MilkDrop) ----------

    def _fb_begin(self, fade=0.9, zoom=1.0, rot=0.0):
        """Начинает кадр с затухающим следом прошлого: возвращает (буфер, painter).

        fade — во сколько раз темнеет след за 1/60 с; zoom — масштаб следа
        за тот же интервал (>1 — «летим вперёд»); rot — поворот в радианах.
        Всё нормируется на реальное dt, поэтому скорость не зависит от FPS.
        """
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        new = QImage(max(1, int(w * dpr)), max(1, int(h * dpr)),
                     QImage.Format_ARGB32_Premultiplied)
        new.setDevicePixelRatio(dpr)
        new.fill(Qt.transparent)
        q = QPainter(new)
        q.setRenderHint(QPainter.Antialiasing)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        old = self._fb
        if old is not None and old.size() == new.size():
            k = max(0.0, self._dt * 60.0)
            q.setOpacity(fade ** k)
            q.translate(w / 2.0, h / 2.0)
            q.rotate(math.degrees(rot * k))
            sc = zoom ** k
            q.scale(sc, sc)
            q.translate(-w / 2.0, -h / 2.0)
            q.drawImage(0, 0, old)
            q.resetTransform()
            q.setOpacity(1.0)
        return new, q

    def _fb_end(self, p, new, q):
        """Заканчивает кадр: запоминает буфер и выводит его в виджет."""
        q.end()
        self._fb = new
        p.drawImage(0, 0, new)

    def _update(self, dt, now):
        """Хук для наследников со своей логикой анимации."""
        pass

    def paintEvent(self, event):
        """Наследники обязаны переопределить."""
        pass
