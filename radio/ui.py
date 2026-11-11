"""Главное окно Marsik FM: пилюли-островы + визуализатор + плеер.

Раскладка по макету: шапка с логотипом, пилюля станции (выпадающий список),
пилюля скачанных треков, в центре — визуализатор поверх оконного фонового
изображения, снизу — панель плеера (play/←/→/стоп/громкость/сохранить).

Скачивание треков: yt-dlp ищет текущий трек по метаданным радио и
сохраняет mp3 в «Музыка» (XDG Music — туда же можно класть свои файлы,
они появятся в меню пилюли «Скачанные» и играют как плеер). Запуск через
QProcess — интерфейс не замирает.

Вся логика (движок mpv, аудио-тап, 5 режимов визуализации) осталась
прежней — маскот-кот убран из интерфейса (вернёмся к коту-бонго позже).
"""
import os
import math
import random
import re
import shutil
import time
from string import Template

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPropertyAnimation, QProcess,
    Property, QRect, QRectF, QSettings, QStandardPaths, Qt, QTime, QTimer,
)
from PySide6.QtCore import QUrl, Signal
from pathlib import Path
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient, QRegion,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QSlider, QStackedWidget,
    QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from .island import IslandMenu
from .playlist import DurationProbe, PlayQueue, fmt_time
from .theme import THEMES_DIR, hexs, manager as themes
from .engine import AudioEngine, CONNECTING, ERROR, PAUSED, PLAYING, STOPPED
from .stations import DEFAULT_PATH, PROJECT_DIR, load_stations, save_stations
from .tap import AudioTap
from .cover import CoverFetcher
from .viz.glowing_wave import GlowingWave
from .viz.spectrum import Spectrum
from .viz.warp import Warp
from .viz.galaxy import Galaxy
from .viz.oscilloscope import Oscilloscope
from .viz.ring import Ring
from .viz.bars import Bars
from .viz.fireflies import Fireflies
from .viz.dots import Dots
from .viz.liquid import Liquid

# папка для треков: XDG «Музыка» (~/.config/user-dirs.dirs, локаль-независимо)
DL_DIR = (QStandardPaths.writableLocation(QStandardPaths.MusicLocation)
          or os.path.expanduser("~/Music"))
# папка с фонами: кладите сюда png/jpg/webp — они сами появятся в списке
BG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backgrounds")
_BG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_BG_LEGACY = "balcony.png"   # прежний «фон с котом» (для старых настроек)


def _bg_files():
    """Имена картинок из backgrounds/ (кроме логотипа), по алфавиту."""
    try:
        names = [n for n in os.listdir(BG_DIR)
                 if n.lower().endswith(_BG_EXT)
                 and not n.lower().startswith("logo")]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def _bg_label(name):
    return os.path.splitext(name)[0].replace("_", " ").replace("-", " ")


def _resolve_logo(logo):
    """Логотип станции из stations.json → абсолютный путь.

    В stations.json путь относительный («../assets/logo/x.webp»); берём только
    имя файла и ищем в `<проект>/assets/logo` (штатное), затем в корне
    `<проект>/assets`, затем сам путь как есть. Первое найденное — побеждает.
    (Кастомные обложки станций лежат в assets — не в backgrounds.)
    """
    if not logo:
        return None
    name = Path(logo).name
    candidates = [
        PROJECT_DIR / "assets" / "logo" / name,
        PROJECT_DIR / "assets" / name,
        Path(logo),
    ]
    for cand in candidates:
        try:
            if cand.exists():
                return str(cand)
        except OSError:
            continue
    return None


def _hue_of_str(s):
    """Стабильный оттенок 0..359 из строки (без солёного хэша Python)."""
    return sum(ord(c) for c in (s or "")) % 360


def _make_station_cover(name, sid):
    """Обложка станции, сгенерированная из её данных (имя/id), когда нет
    своего логотипа: градиент по hue(id) + крупная буква + название снизу.
    Возвращает квадрат 512×512."""
    S = 512
    pm = QPixmap(S, S)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    h = _hue_of_str(sid or name)
    c1 = QColor.fromHsl(h, 130, 150)
    c2 = QColor.fromHsl((h + 28) % 360, 150, 78)
    g = QLinearGradient(0.0, 0.0, S * 0.35, S)
    g.setColorAt(0.0, c1)
    g.setColorAt(1.0, c2)
    p.fillRect(0, 0, S, S, g)
    # крупная буква
    letter = (name.strip() or "?")[0].upper()
    f = QFont()
    f.setBold(True)
    f.setPointSize(230)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(pm.rect(), Qt.AlignCenter, letter)
    # название снизу (перенос по словам)
    f2 = QFont()
    f2.setBold(True)
    f2.setPointSize(30)
    p.setFont(f2)
    p.setPen(QColor(255, 255, 255, 210))
    tr = QRect(int(S * 0.08), int(S * 0.66), int(S * 0.84), int(S * 0.26))
    p.drawText(tr, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, name or "")
    p.end()
    return pm


def _make_track_cover(text):
    """Обложка, сгенерированная из данных ТРЕКА (artist/title), когда
    настоящей обложки нет ни в iTunes, ни у станции (напр. AI-миксы
    MixStream). Градиент по hue + исполнитель + название. Квадрат 512×512."""
    S = 512
    text = (text or "").strip()
    i = text.find(" - ")
    if i > 0:
        artist, title = text[:i].strip(), text[i + 3:].strip()
    else:
        artist, title = "", text
    pm = QPixmap(S, S)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    h = _hue_of_str(text)
    c1 = QColor.fromHsl(h, 120, 145)
    c2 = QColor.fromHsl((h + 40) % 360, 150, 62)
    g = QLinearGradient(0.0, 0.0, S * 0.4, S)
    g.setColorAt(0.0, c1)
    g.setColorAt(1.0, c2)
    p.fillRect(0, 0, S, S, g)
    # крупная буква названия по центру
    letter = (title[:1] or "♪").upper()
    f = QFont()
    f.setBold(True)
    f.setPointSize(210)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 225))
    p.drawText(pm.rect(), Qt.AlignCenter, letter)
    # исполнитель (сверху над названием) — в одну строку, длинное обрезаем
    if artist:
        fa = QFont()
        fa.setPointSize(22)
        p.setFont(fa)
        p.setPen(QColor(255, 255, 255, 190))
        ar = QRect(int(S * 0.08), int(S * 0.56), int(S * 0.84), int(S * 0.10))
        p.drawText(ar, Qt.AlignHCenter | Qt.AlignBottom,
                   QFontMetrics(fa).elidedText(artist, Qt.ElideRight, ar.width()))
    # название снизу — в 2 строки; если не влезает, обрезаем с многоточием
    ft = QFont()
    ft.setBold(True)
    ft.setPointSize(28)
    p.setFont(ft)
    p.setPen(QColor(255, 255, 255, 220))
    tr = QRect(int(S * 0.08), int(S * 0.67), int(S * 0.84), int(S * 0.28))
    flags = Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap
    fm_t = QFontMetrics(ft)
    shown = title or ""
    if fm_t.boundingRect(tr, flags, shown).height() > tr.height():
        # не влезает в 2 строки — режем по словам, пока текст с «…» не поместится
        while shown and fm_t.boundingRect(tr, flags, shown + "…").height() > tr.height():
            shown = shown[:-1].rstrip()
        shown += "…"
    p.drawText(tr, flags, shown)
    p.end()
    return pm


_VIZ_NAMES = ["Glowing Wave", "Ring", "Bars", "Spectrum", "Fireflies",
              "Fireflies Dots", "Liquid", "Galaxy", "Warp", "Oscilloscope", "Нет"]
NONE_VIZ = len(_VIZ_NAMES) - 1   # «Нет» — визуализатор отключён
CARD_VIZ = -2                    # «Карточка» — flip-карточка трека/станции

# шрифт часов — как у виджета часов в Noctalia, но плотнее: ExtraLight
# (тот, что в виджете) на тёмном фоне читается плохо, SemiBold держит
# тот же точечный рисунок и виден издалека
CLOCK_FONT = "Bitcount Single Cursive SemiBold"
CLOCK_FORMAT = "HH:mm"

_YTDLP = shutil.which("yt-dlp") or ""
# yt-dlp: строка прогресса "[download]  45.2% of ..."
_DL_PCT_RE = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")

_STATUS_TEXT = {
    STOPPED: "Остановлено", CONNECTING: "Подключение…", PLAYING: "Играет",
    PAUSED: "Пауза", ERROR: "Ошибка",
}


def _status_for(state):
    """(текст, цвет) статуса — цвет берётся из текущей темы."""
    th = themes.current
    color = {
        STOPPED: th.muted, CONNECTING: th.warn, PLAYING: th.ok,
        PAUSED: th.warn, ERROR: th.err,
    }.get(state, th.muted)
    return _STATUS_TEXT.get(state, "…"), hexs(color)


# таблица стилей — шаблон: цвета подставляются из темы (theme.py)
_STYLE_T = Template("""
QWidget {
    color: ${text};
    font-size: 14px;
}
QLabel#logo { font-size: 24px; font-weight: 800; color: ${title}; }
QLabel#tagline { font-size: 11px; color: ${accent}; letter-spacing: 2px; }
QLabel#slogan { font-size: 13px; color: ${muted}; font-style: italic; }
QLabel#clock {
    font-family: "Bitcount Single Cursive SemiBold";
    font-size: 40px;
    color: ${primary};
}
QLabel#section { font-size: 12px; color: ${muted}; letter-spacing: 2px; }
QLabel#station { font-size: 20px; font-weight: bold; color: ${text}; }
QLabel#desc { color: ${muted}; font-size: 13px; }
QLabel#track { color: ${accent}; font-size: 14px; }
QLabel#status { font-size: 13px; }
QFrame#panel {
    background: ${panel_bg};
    border: 1px solid ${line};
    border-radius: 16px;
}
QFrame#playerBar {
    background: ${bar_bg};
    border: 1px solid ${line};
    border-radius: 22px;
}
QToolButton#pill {
    background: ${pill_bg};
    border: 1px solid ${pill_border};
    border-radius: 17px;
    padding: 8px 14px;
    font-size: 14px;
    font-weight: bold;
    color: ${title};
}
QToolButton#pill:hover {
    background: ${pill_hover};
    border-color: ${pill_border_h};
}
QToolButton#save {
    background: ${primary_a};
    border: 1px solid ${primary_border};
    border-radius: 10px;
    padding: 9px 16px;
    font-weight: bold;
    color: ${on_primary};
}
QToolButton#save:hover { background: ${primary_h}; }
QToolButton#save:pressed { background: ${primary_p}; }
QToolButton#save:disabled {
    background: ${btn_bg};
    color: ${disabled};
    border: 1px solid ${line2};
}
QProgressBar#dlProgress {
    background: ${prog_bg};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    font-size: 10px;
    color: #ffffff;
}
QProgressBar#dlProgress::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 ${prog_a}, stop:1 ${prog_b});
    border-radius: 5px;
}
QToolButton {
    background: ${btn_bg};
    border: 1px solid ${line2};
    border-radius: 10px;
    padding: 9px;
}
QToolButton:hover { background: ${btn_hover}; }
QToolButton:pressed { background: ${btn_press}; }
QToolButton:disabled { color: ${disabled}; }
QToolButton:checked {
    background: ${primary_a};
    color: ${on_primary};
    border: 1px solid ${primary_border};
}
QLabel#seekTime { color: ${muted}; font-size: 12px; }
QProgressBar#busy {
    background: ${prog_bg};
    border: none;
    border-radius: 3px;
}
QProgressBar#busy::chunk {
    background: ${primary};
    border-radius: 3px;
}
QToolButton#play {
    background: ${pill_bg};
    border: 2px solid ${primary};
    border-radius: 25px;
    padding: 12px;
}
QToolButton#play:hover { background: ${play_hover}; }
QComboBox {
    background: ${btn_bg};
    border: 1px solid ${line2};
    border-radius: 8px;
    padding: 5px 10px;
}
QCheckBox { color: ${muted}; }
QCheckBox:hover { color: ${text}; }
QSlider::groove:horizontal {
    height: 4px;
    background: ${line3};
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: ${primary};
}
QSlider::sub-page:horizontal {
    background: ${primary};
    border-radius: 2px;
}
QDialog, QMessageBox { background: ${surface}; }
QLineEdit {
    background: ${field};
    border: 1px solid ${line2};
    border-radius: 8px;
    padding: 5px 8px;
    selection-background-color: ${primary};
    selection-color: ${on_primary};
}
QPushButton {
    background: ${field};
    border: 1px solid ${line2};
    border-radius: 8px;
    padding: 6px 16px;
}
QPushButton:hover { background: ${btn_hover}; }
QToolTip {
    background: ${surface};
    color: ${text};
    border: 1px solid ${line2};
    padding: 4px;
}
""")


def build_style(th):
    return _STYLE_T.substitute(th.css())


STYLE = build_style(themes.current)   # main.py ставит его как есть


class _SeekSlider(QSlider):
    """Полоса перемотки: клик и перетаскивание, seekRequested(0..1)."""
    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(0, 1000)
        self.dragging = False
        self.setCursor(Qt.PointingHandCursor)

    def _val_at(self, x):
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(x), max(1, self.width()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self.setValue(self._val_at(e.position().x()))
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.setValue(self._val_at(e.position().x()))
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.dragging and e.button() == Qt.LeftButton:
            self.dragging = False
            self.seekRequested.emit(self.value() / float(self.maximum()))
            e.accept()


class _Canvas(QWidget):
    """Центральный холст: рисует оконный фон (картинка + вуаль)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._card_text = None
        self._card_active = False     # режим «Карточка» — рисуем галактику
        # галактика: звёзды и туманности в нормированных координатах (0..1)
        rnd = random.Random(1337)    # фиксированный расклад
        self._stars = [(rnd.random(), rnd.random(),
                        rnd.uniform(0.6, 2.2), rnd.uniform(0, 6.28),
                        rnd.uniform(0.25, 0.8))
                       for _ in range(160)]
        self._nebulae = [(rnd.random(), rnd.random(), rnd.uniform(0.25, 0.5),
                          rnd.uniform(0, 360), rnd.uniform(26, 46))
                         for _ in range(3)]
        self._gal_timer = QTimer(self)
        self._gal_timer.setInterval(50)
        self._gal_timer.timeout.connect(self.update)

    def set_pixmap(self, pm):
        self._pixmap = pm
        self.update()

    def set_card_text(self, text):
        """Подпись поверх фона (название трека в режиме «Карточка трека»)."""
        self._card_text = (text or "").strip() or None
        self.update()

    def set_card_backdrop(self, on):
        """Вкл/выкл галактику+свечение за карточкой (режим «Карточка»)."""
        on = bool(on)
        if on == self._card_active:
            return
        self._card_active = on
        if on:
            self._gal_timer.start()
        else:
            self._gal_timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if self._card_active:
            self._paint_galaxy(p)
            return
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            p.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2, scaled)
            # лёгкая тёплая дымка вместо тёмной вуали
            th = themes.current
            p.fillRect(self.rect(), th.q(th.veil[0], th.veil[1]))
        else:
            p.fillRect(self.rect(), themes.current.q(themes.current.canvas))
        # подпись карточки трека — по центру снизу, с тенью для читаемости
        if self._card_text:
            th = themes.current
            rect = self.rect()
            f = QFont(self.font())
            f.setPointSize(15)
            f.setBold(True)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            yy = rect.bottom() - 22
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(rect.adjusted(0, 0, 0, -20),
                       Qt.AlignHCenter | Qt.AlignBottom, self._card_text)
            p.setPen(th.q(th.on_surface))
            p.drawText(rect.adjusted(0, 0, 0, -22),
                       Qt.AlignHCenter | Qt.AlignBottom, self._card_text)

    def _paint_galaxy(self, p):
        """Галактика + мягкое свечение за карточкой (как в мобильной версии):
        тёмная база, цветные туманности, мерцающие звёзды, пульс в цвет темы."""
        w, h = float(self.width()), float(self.height())
        t = time.monotonic()
        p.fillRect(self.rect(), QColor(6, 8, 16))
        # туманности (мягкие цветные пятна)
        th = themes.current
        for (nx, ny, nr, hue, a) in self._nebulae:
            col = QColor.fromHsl(int(hue) % 360, 140, 120, int(a))
            g = QRadialGradient(nx * w, ny * h, nr * min(w, h))
            g.setColorAt(0.0, col)
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g)
        # звёзды (мерцание)
        p.setPen(Qt.NoPen)
        for (x, y, rad, ph, base) in self._stars:
            b = base + 0.5 * abs(math.sin(t * 1.3 + ph))
            a = int(40 + 200 * b)
            p.setBrush(QColor(255, 255, 255, a))
            p.drawEllipse(QRectF(x * w - rad, y * h - rad, rad * 2, rad * 2))
        # центральное свечение (пульс)
        pulse = 0.55 + 0.45 * abs(math.sin(t * 0.7))
        ac = th.q(th.primary)
        glow = QRadialGradient(w / 2.0, h / 2.0, min(w, h) * 0.6)
        glow.setColorAt(0.0, QColor(ac.red(), ac.green(), ac.blue(),
                                     int(150 * pulse)))
        glow.setColorAt(0.5, QColor(ac.red(), ac.green(), ac.blue(),
                                     int(45 * pulse)))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), glow)


class Pill(QToolButton):
    """Пилюля-остров фиксированной ширины: длинный текст режется многоточием.

    Без ограничения кнопка растягивалась под длинное имя трека/станции и
    сдвигала всю шапку. Полный текст остаётся в подсказке.
    """

    def __init__(self, max_width=220, parent=None):
        super().__init__(parent)
        self._max_w = max_width
        self._hint = ""
        self._full = ""
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def setText(self, text):
        self._full = text
        self._apply()

    def fullText(self):
        return self._full

    def setToolTip(self, tip):
        self._hint = tip
        self._apply()

    def _apply(self):
        avail = self._max_w - 32          # padding 14+14 из QSS + рамка
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, avail)
        super().setText(shown)
        if shown != self._full:
            tip = self._full + ("\n" + self._hint if self._hint else "")
        else:
            tip = self._hint
        super().setToolTip(tip)
        self.updateGeometry()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:   # QSS применил свой шрифт
            self._apply()


class _TrackCard(QWidget):
    """3D flip-карточка (как в мобильной версии).

    front — обложка ТРЕКА (видна по умолчанию). back — обложка СТАНЦИИ
    (кастомная из assets либо сгенерированная заглушка). Клик переворачивает.
    Размер квадратный, позиционируется по центру окна.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._front = QPixmap()
        self._back = QPixmap()
        self._angle = 0.0        # 0 = front (трек), 180 = back (станция)
        self._pop = 0.0          # кратковременный «поп» при смене трека
        self._flip = QPropertyAnimation(self, b"angle", self)
        self._flip.setDuration(620)
        self._flip.setEasingCurve(QEasingCurve.InOutCubic)
        self._pop_anim = QPropertyAnimation(self, b"pop", self)
        self._pop_anim.setDuration(900)
        self._pop_anim.setEasingCurve(QEasingCurve.OutBack)
        self.setCursor(Qt.PointingHandCursor)
        self.hide()

    # кастомные свойства для анимации
    def _get_angle(self):
        return self._angle

    def _set_angle(self, v):
        self._angle = float(v)
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    def _get_pop(self):
        return self._pop

    def _set_pop(self, v):
        self._pop = float(v)
        self.update()

    pop = Property(float, _get_pop, _set_pop)

    # ---------- публичный API ----------

    def set_front(self, pm):
        self._front = pm if pm is not None else QPixmap()
        self.update()

    def set_back(self, pm):
        self._back = pm if pm is not None else QPixmap()
        self.update()

    def toggle_flip(self):
        self._flip.stop()
        self._flip.setStartValue(self._angle)
        self._flip.setEndValue(0.0 if self._angle >= 90.0 else 180.0)
        self._flip.start()

    def mousePressEvent(self, e):
        self.toggle_flip()

    # ---------- отрисовка ----------

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        scale = 1.0 + 0.07 * self._pop
        cx, cy = self.width() / 2.0, self.height() / 2.0
        # квадрат карточки с учётом pop-масштаба
        half = side * scale / 2.0
        bx, by, bw, bh = cx - half, cy - half, half * 2, half * 2

        angle = self._angle
        showing_front = angle < 90.0
        sx = max(0.02, abs(math.cos(math.radians(angle))))
        th = themes.current

        p.save()
        p.translate(cx, cy)
        p.scale(sx, 1.0)              # «поворот» по горизонтали (flip)
        p.translate(-cx, -cy)

        # фон-плашка (на случай пустой картинки)
        grad = QLinearGradient(bx, by, bx, by + bh)
        grad.setColorAt(0.0, th.q(th.primary))
        grad.setColorAt(1.0, th.q(th.canvas))
        p.setBrush(grad)
        p.setPen(QPen(th.q(th.on_surface, 40), 1.0))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 22, 22)

        pm = self._front if showing_front else self._back
        if pm is not None and not pm.isNull():
            # contain внутри карточки с небольшим отступом
            pad = bw * 0.04
            tr = QRectF(bx + pad, by + pad, bw - 2 * pad, bh - 2 * pad)
            pix = pm.scaled(int(tr.width()), int(tr.height()),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dx = bx + (bw - pix.width()) / 2.0
            dy = by + (bh - pix.height()) / 2.0
            p.setBrush(Qt.NoBrush)
            p.setPen(Qt.NoPen)
            # обрезаем по скруглённому квадрату. НЕ setClipPath(путь) — под
            # Wayland/EGL это даёт segfault; клипируем через QRegion-полигон.
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(bx, by, bw, bh), 22, 22)
            p.setClipRegion(QRegion(clip.toFillPolygon().toPolygon()))
            p.drawPixmap(int(dx), int(dy), pix)
            p.setClipping(False)
        else:
            # заглушка: нотка
            p.setPen(th.q(th.on_surface if showing_front else th.on_primary))
            f = QFont(self.font())
            f.setPointSize(int(side * 0.3))
            p.setFont(f)
            p.drawText(QRectF(bx, by, bw, bh), Qt.AlignCenter, "♪")
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Marsik FM")
        self.resize(1100, 640)
        self.setMinimumSize(0, 560)   # ширину задаёт шапка
        self.settings = QSettings("radiofm", "radiofm")
        self.engine = AudioEngine(parent=self)
        self._playing_id = None
        self._last_error = ""
        self._track = ""            # текущий трек (метаданные)
        self._dl_proc = None        # активный процесс yt-dlp
        self._dl_buf = ""           # недописанная строка вывода yt-dlp
        self._local = False         # играет локальный файл (не радио)
        self._viz_idx = 0           # выбранный режим визуализатора
        self.queue = PlayQueue()    # очередь скачанных треков
        self.durations = DurationProbe(self)
        self._dl_actions = {}       # путь → пункт списка (для времени)
        self._cur_dur = 0.0         # длительность играющего файла
        self._bg_name = None        # выбранный фон (имя файла) или None
        self._bg_mode = "none"      # none | image  (карточка теперь в визуализаторах)
        self.cover = CoverFetcher()  # поиск обложек треков (iTunes + кэш)
        self._cover_pixmap = QPixmap()
        self._cover_key = ""        # ключ текущего трека (artist|title)
        self._station_logos = {}    # id станции → скачанный из сети логотип

        self._build()
        self._load_list()
        self._count_downloads()
        self._restore()

        self.engine.stateChanged.connect(self._on_state)
        self.engine.trackChanged.connect(self._on_track)
        self.engine.errorRaised.connect(self._on_error)
        self.engine.positionChanged.connect(self._on_position)
        self.engine.fileEnded.connect(self._on_file_ended)
        self.durations.ready.connect(self._on_duration_ready)
        self.cover.ready.connect(self._on_cover_ready)
        self._on_state(self.engine.state)

        # минимальная ширина шапки без слогана и подписи — от неё считаем,
        # когда их можно показать (resizeEvent)
        self.tagline.hide()
        self.slogan.hide()
        self._hdr_base = self.centralWidget().minimumSizeHint().width()
        themes.changed.connect(self._apply_theme)
        self._apply_theme()
        # main.py ставит STYLE уже после создания окна — перекрываем
        QTimer.singleShot(0, self._apply_theme)

    # ---------- сборка интерфейса ----------

    def _build(self):
        central = _Canvas()
        self._canvas = central
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # --- шапка: логотип-котик + название + слоган ---
        header = QFrame()
        header.setObjectName("panel")
        self.header = header
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(18, 8, 18, 8)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_path = os.path.join(root_dir, "assets", "icon.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(root_dir, "backgrounds", "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
            logo_pic = QLabel()
            logo_pic.setPixmap(QPixmap(logo_path).scaled(
                60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            hbox.addWidget(logo_pic)
        logo_col = QVBoxLayout()
        logo = QLabel("MARSIK FM")
        logo.setObjectName("logo")
        tag = QLabel("GOOD MUSIC · GOOD VIBES · ALWAYS")
        tag.setObjectName("tagline")
        self.tagline = tag
        logo_col.addWidget(logo)
        logo_col.addWidget(tag)
        hbox.addLayout(logo_col)
        hbox.addSpacing(24)

        # «динамический остров»: пилюля активной станции, клик — список
        # список вырастает из панели шапки (остров, как в Noctalia)
        self.menu = IslandMenu(central, header)
        self.pill = Pill()
        self.pill.setObjectName("pill")
        self.pill.setText("Выберите станцию")
        self.pill.setToolTip("Станции (клик — список)")
        self.menu.set_trigger(self.pill)
        self.pill.clicked.connect(self.menu.toggle)
        # меню пересобирается при открытии: пункт «Удалить» всегда актуален
        self.menu.aboutToShow.connect(self._rebuild_menu)
        # перетаскивание станций: новый порядок сразу пишется в stations.json
        self.menu.reordered.connect(self._on_station_reordered)
        hbox.addWidget(self.pill, 0, Qt.AlignVCenter)

        hbox.addSpacing(10)

        # пилюля скачанных треков: список из downloads/, клик — воспроизведение
        self.dl_menu = IslandMenu(central, header)
        self.dl_menu.aboutToShow.connect(self._scan_downloads)
        self.dl_pill = Pill()
        self.dl_pill.setObjectName("pill")
        self.dl_pill.setText("Скачанные")
        self.dl_menu.set_trigger(self.dl_pill)
        self.dl_pill.clicked.connect(self.dl_menu.toggle)
        self.dl_pill.setToolTip("Скачанные треки (клик — список)")
        hbox.addWidget(self.dl_pill, 0, Qt.AlignVCenter)

        hbox.addSpacing(10)

        # пилюля режима визуализатора
        self.viz_menu = IslandMenu(central, header)
        self.viz_menu.aboutToShow.connect(self._build_viz_menu)
        self.viz_pill = Pill()
        self.viz_pill.setObjectName("pill")
        self.viz_pill.setText("✦  %s" % _VIZ_NAMES[0])
        self.viz_pill.setToolTip("Режим визуализатора (клик — список)")
        self.viz_menu.set_trigger(self.viz_pill)
        self.viz_pill.clicked.connect(self.viz_menu.toggle)
        hbox.addWidget(self.viz_pill, 0, Qt.AlignVCenter)

        hbox.addSpacing(10)

        # пилюля фона: картинки из папки backgrounds/
        self.bg_menu = IslandMenu(central, header)
        self.bg_menu.aboutToShow.connect(self._build_bg_menu)
        self.bg_pill = Pill()
        self.bg_pill.setObjectName("pill")
        self.bg_pill.setText("Фон: без фона")
        self.bg_pill.setToolTip(
            "Фон под визуализатором. Свои картинки кладите в папку "
            "backgrounds/ — они появятся в списке сами")
        self.bg_menu.set_trigger(self.bg_pill)
        self.bg_pill.clicked.connect(self.bg_menu.toggle)
        hbox.addWidget(self.bg_pill, 0, Qt.AlignVCenter)

        hbox.addSpacing(10)

        # пилюля темы: цвета интерфейса и визуализаторов (theme.py)
        self.theme_menu = IslandMenu(central, header)
        self.theme_menu.aboutToShow.connect(self._build_theme_menu)
        self.theme_pill = Pill(300)
        self.theme_pill.setObjectName("pill")
        self.theme_pill.setText("Тема: %s" % themes.current.name)
        self.theme_pill.setToolTip("Цветовая тема (клик — список)")
        self.theme_menu.set_trigger(self.theme_pill)
        self.theme_pill.clicked.connect(self.theme_menu.toggle)
        hbox.addWidget(self.theme_pill, 0, Qt.AlignVCenter)

        hbox.addStretch(1)
        slogan = QLabel("Хорошая музыка делает день лучше ✦")
        slogan.setObjectName("slogan")
        self.slogan = slogan
        hbox.addWidget(slogan, 0, Qt.AlignVCenter)

        # часы в правом углу шапки (шрифт как у виджета часов Noctalia)
        hbox.addSpacing(14)
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        self.clock.setToolTip("Текущее время")
        self.clock.setFont(QFont(CLOCK_FONT, 40))
        hbox.addWidget(self.clock, 0, Qt.AlignVCenter)
        self._tick_clock()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()

        root.addWidget(header)

        # --- центр: только визуализатор (место колонок освобождено) ---
        content = QHBoxLayout()
        content.setSpacing(10)
        center = QVBoxLayout()
        center.setSpacing(8)

        viz_row = QHBoxLayout()
        viz_row.setSpacing(12)
        self.viz_stack = QStackedWidget()
        self.viz_modes = [GlowingWave(), Ring(), Bars(), Spectrum(),
                          Fireflies(), Dots(), Liquid(), Galaxy(), Warp(),
                          Oscilloscope()]
        for v in self.viz_modes:
            self.viz_stack.addWidget(v)
        self.wave = self.viz_modes[0]   # для совместимости (тап)
        viz_row.addWidget(self.viz_stack, 1)
        center.addLayout(viz_row, 1)
        content.addLayout(center, 1)

        root.addLayout(content, 1)

        # --- нижняя панель плеера ---
        player = QFrame()
        player.setObjectName("playerBar")
        self.player_frame = player
        ph = QHBoxLayout(player)
        ph.setContentsMargins(20, 8, 20, 8)
        ph.setSpacing(10)
        self.btn_play = QToolButton()
        self.btn_play.setObjectName("play")
        self.btn_play.setFixedSize(52, 52)
        self.btn_play.setIconSize(self.btn_play.size() * 0.42)
        self.btn_play.clicked.connect(self._on_playpause)
        self.btn_stop = QToolButton()
        self.btn_stop.setFixedSize(44, 44)
        self.btn_stop.setIconSize(self.btn_stop.size() * 0.45)
        self.btn_stop.setIcon(self._icon(QStyle.SP_MediaStop))
        self.btn_stop.clicked.connect(self._on_stop)
        btn_prev = QToolButton()
        btn_prev.setFixedSize(44, 44)
        btn_prev.setIconSize(btn_prev.size() * 0.45)
        btn_prev.setIcon(self._icon(QStyle.SP_MediaSkipBackward))
        self.btn_prev = btn_prev
        btn_prev.setToolTip("Предыдущая станция")
        btn_prev.clicked.connect(lambda: self._on_prev_next(-1))
        btn_next = QToolButton()
        btn_next.setFixedSize(44, 44)
        btn_next.setIconSize(btn_next.size() * 0.45)
        btn_next.setIcon(self._icon(QStyle.SP_MediaSkipForward))
        self.btn_next = btn_next
        btn_next.setToolTip("Следующая станция")
        btn_next.clicked.connect(lambda: self._on_prev_next(1))
        ph.addWidget(btn_prev)
        ph.addWidget(self.btn_play)
        ph.addWidget(btn_next)
        ph.addWidget(self.btn_stop)
        self.btn_shuffle = QToolButton()
        self.btn_shuffle.setText("Вперемешку")
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setToolTip(
            "Скачанные треки: по порядку / вперемешку")
        self.btn_shuffle.toggled.connect(self._on_shuffle_toggled)
        self.btn_shuffle.hide()
        ph.addWidget(self.btn_shuffle)
        ph.addStretch(1)

        # текущий трек (метаданные радио) — центр панели
        self.lbl_track = QLabel("")
        self.lbl_track.setObjectName("track")
        self.lbl_track.setAlignment(Qt.AlignCenter)
        ph.addWidget(self.lbl_track, 1)
        ph.addStretch(1)

        # кнопка «Сохранить»: yt-dlp скачивает текущий трек в downloads/
        self.btn_save = QToolButton()
        self.btn_save.setObjectName("save")
        self.btn_save.setText("Сохранить")
        self.btn_save.setToolTip(
            "Скачать текущий трек (yt-dlp) в «Музыка»")
        self.btn_save.clicked.connect(self._on_save_clicked)
        ph.addWidget(self.btn_save, 0, Qt.AlignVCenter)

        vol_icon = QLabel()
        vol_icon.setPixmap(self._icon(QStyle.SP_MediaVolume).pixmap(18, 18))
        self.vol_icon = vol_icon
        ph.addWidget(vol_icon)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(180)
        self.slider.setToolTip("Громкость")
        self.slider.valueChanged.connect(self.engine.set_volume)
        ph.addWidget(self.slider)

        # статус движка — под панелью плеера (маленькой строкой)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setAlignment(Qt.AlignRight)
        root.addWidget(self.lbl_status)

        # прогресс скачивания (скрыт, когда не качаем)
        self.dl_progress = QProgressBar()
        self.dl_progress.setObjectName("dlProgress")
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setTextVisible(True)
        self.dl_progress.setFormat("%p%")
        self.dl_progress.setFixedHeight(10)
        self.dl_progress.hide()
        root.addWidget(self.dl_progress)

        # прогресс воспроизведения локального трека (скрыт для радио)
        self.seek_row = QWidget()
        sh = QHBoxLayout(self.seek_row)
        sh.setContentsMargins(6, 0, 6, 0)
        sh.setSpacing(10)
        self.lbl_pos = QLabel("0:00")
        self.lbl_pos.setObjectName("seekTime")
        self.lbl_dur = QLabel("0:00")
        self.lbl_dur.setObjectName("seekTime")
        self.lbl_pos.setMinimumWidth(64)
        self.seek = _SeekSlider()
        self.seek.setToolTip("Перемотка")
        self.seek.seekRequested.connect(self._on_seek)
        # бегущая полоска, пока трек/станция загружается
        self.busy = QProgressBar()
        self.busy.setObjectName("busy")
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(6)
        self.busy.hide()
        sh.addWidget(self.lbl_pos)
        sh.addWidget(self.seek, 1)
        sh.addWidget(self.busy, 1)
        sh.addWidget(self.lbl_dur)
        self.seek_row.hide()
        root.addWidget(self.seek_row)
        root.addWidget(player)

        self.setCentralWidget(central)

        # flip-карточка трека (поверх визуализатора, под шапкой/плеером)
        self._card = _TrackCard(central)
        self.header.raise_()
        self.player_frame.raise_()
        self._layout_card()

        # аудио-тап → все режимы визуализатора
        self.tap = AudioTap()
        for v in self.viz_modes:
            self.tap.level.connect(v.set_audio_level)
            self.tap.bands.connect(v.set_bands)
            self.tap.wave.connect(v.set_wave)

    def _build_viz_menu(self):
        self.viz_menu.clear()
        for i, name in enumerate(_VIZ_NAMES):
            if i == NONE_VIZ:
                continue          # «Нет» добавим отдельно в конце
            act = self.viz_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(i == self._viz_idx)
            act.triggered.connect(lambda c=False, k=i: self._set_viz(k))
        # карточка трека — отдельный режим центра (рядом с визуализаторами)
        act = self.viz_menu.addAction("🂠  Карточка")
        act.setCheckable(True)
        act.setChecked(self._viz_idx == CARD_VIZ)
        act.triggered.connect(lambda c=False: self._set_viz(CARD_VIZ))
        self.viz_menu.addSeparator()
        act = self.viz_menu.addAction("Нет")
        act.setCheckable(True)
        act.setChecked(self._viz_idx == NONE_VIZ)
        act.triggered.connect(lambda c=False: self._set_viz(NONE_VIZ))

    def _layout_card(self):
        """Позиционирует flip-карточку по центру (между шапкой и плеером)."""
        central = self.centralWidget()
        if central is None:
            return
        r = central.rect()
        top = self.header.height() + 10
        bot = self.player_frame.height() + 10
        avail = r.adjusted(10, top, -10, -bot)
        if avail.width() <= 0 or avail.height() <= 0:
            return
        side = int(min(max(200, min(avail.width(), avail.height())), 512))
        x = int(avail.x() + (avail.width() - side) / 2.0)
        y = int(avail.y() + (avail.height() - side) / 2.0)
        self._card.setGeometry(x, y, side, side)

    def _update_center(self):
        """Что показывать в центре: карточка (режим КАРТОЧКА), визуализатор
        или ничего («Нет» — тогда виден только фон окна)."""
        card_on = self._viz_idx == CARD_VIZ
        self._card.setVisible(card_on)
        self.centralWidget().set_card_backdrop(card_on)
        self.viz_stack.setVisible(
            self._viz_idx != CARD_VIZ and self._viz_idx != NONE_VIZ)

    def _refresh_card(self):
        """Перечитывает обе стороны карточки из текущего состояния:
        front — обложка ТРЕКА (видна по умолчанию), back — обложка СТАНЦИИ."""
        st = self._current_station()
        self._card.set_front(self._front_cover_pm(st))
        self._card.set_back(self._station_cover_pm(st))
        self._card.update()

    def _station_cover_real(self, st):
        """РЕАЛЬНАЯ обложка станции (кастом из assets или скачанный логотип),
        либо None. Заглушку не возвращает — её строит _station_cover_pm."""
        if st:
            path = _resolve_logo(st.get("logo"))
            if path:
                pm = QPixmap(path)
                if not pm.isNull():
                    return pm
            pm = self._station_logos.get(st.get("id", ""))
            if pm is not None and not pm.isNull():
                return pm
        return None

    def _front_cover_pm(self, st):
        """Лицо карточки — обложка ТРЕКА (приоритет): из iTunes, иначе
        сгенерированная из названия трека. Обложку станции сюда НЕ ставим —
        иначе лицо дублирует оборот (как было у MixStream Boogie)."""
        if not self._cover_pixmap.isNull():
            return self._cover_pixmap
        return _make_track_cover(self._track)

    def _station_cover_pm(self, st):
        """Обложка станции для оборота карточки: реальная (кастом/SomaFM/URL),
        иначе сгенерированная заглушка (градиент + буква + имя)."""
        real = self._station_cover_real(st)
        if real is not None:
            return real
        return _make_station_cover(
            st.get("name", "") if st else "",
            st.get("id", "") if st else "")

    def _update_card_station(self):
        """Обновляет оборот карточки (обложка станции) и, если обложки трека
        нет, лицо — по тому же приоритету (реальная станция / обложка трека)."""
        st = self._current_station()
        self._card.set_back(self._station_cover_pm(st))
        if self._cover_pixmap.isNull():
            self._card.set_front(self._front_cover_pm(st))

    def _set_viz(self, idx):
        # допустимые значения: 0..len(viz_modes)-1 — режимы, CARD_VIZ — карточка,
        # NONE_VIZ — без визуализатора (виден фон окна)
        if idx not in (CARD_VIZ, NONE_VIZ) and not (0 <= idx < len(self.viz_modes)):
            idx = 0
        self._viz_idx = idx
        if idx == CARD_VIZ:
            self.viz_pill.setText("✦  Карточка")
            self._refresh_card()     # заполнить обе стороны текущим состоянием
            self._layout_card()      # свежая геометрия (на случай без resize)
        elif idx == NONE_VIZ:
            self.viz_pill.setText("✦  Нет")
        else:
            self.viz_stack.setCurrentIndex(idx)
            self.viz_pill.setText("✦  %s" % _VIZ_NAMES[idx])
        self.settings.setValue("viz", idx)
        self._update_center()

    def _build_bg_menu(self):
        """Пересобирается при каждом открытии: новые файлы видны сразу."""
        self.bg_menu.clear()
        act = self.bg_menu.addAction("Без фона")
        act.setCheckable(True)
        act.setChecked(self._bg_name is None)
        act.triggered.connect(lambda c=False: self._set_bg(None))
        for name in _bg_files():
            act = self.bg_menu.addAction(_bg_label(name))
            act.setCheckable(True)
            act.setChecked(name == self._bg_name)
            act.triggered.connect(lambda c=False, n=name: self._set_bg(n))
        self.bg_menu.addSeparator()
        act = self.bg_menu.addAction("›  Открыть папку с фонами…")
        act.triggered.connect(self._open_bg_folder)

    def _set_bg(self, name):
        # name: None/"none" — без фона; иначе имя файла из backgrounds/
        pm = None
        if name not in (None, "none"):
            cand = QPixmap(os.path.join(BG_DIR, name)) if name else QPixmap()
            pm = cand if not cand.isNull() else None
        self._bg_mode = "image" if pm is not None else "none"
        self._bg_name = name if pm is not None else None
        self.centralWidget().set_pixmap(pm)
        self.centralWidget().set_card_text(None)
        # визуализатор прозрачен поверх картинки; сплошной фон — только без
        # фона (чтобы картинка не перекрывалась чёрным, как просил пользователь)
        for v in self.viz_modes:
            v.set_window_bg(pm is not None)
        self.bg_pill.setText(
            "Фон: %s" % (_bg_label(self._bg_name) if self._bg_name
                         else "без фона"))
        if self._bg_name:
            self.settings.setValue("bg_file", self._bg_name)
        else:
            self.settings.remove("bg_file")

    def _open_bg_folder(self):
        os.makedirs(BG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(BG_DIR))

    def _build_theme_menu(self):
        """Пересобирается при открытии: новые файлы из themes/ видны сразу."""
        themes.reload()
        self.theme_menu.clear()
        for name in themes.names():
            act = self.theme_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == themes.current.name)
            act.triggered.connect(lambda c=False, n=name: self._set_theme(n))
        self.theme_menu.addSeparator()
        act = self.theme_menu.addAction("›  Открыть папку с темами…")
        act.triggered.connect(self._open_themes_folder)

    def _set_theme(self, name):
        themes.set(name)
        self.settings.setValue("theme", themes.current.name)

    def _open_themes_folder(self):
        THEMES_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(THEMES_DIR)))

    def _icon(self, standard, size=64):
        """Стандартная иконка Qt, перекрашенная в цвет текста темы."""
        pm = self.style().standardIcon(standard).pixmap(size, size)
        # холст ниже создаётся с dpr=1: без сброса Qt нарисует иконку в четверть
        # холста на экранах с масштабом 2 и символы в кнопках будут мелкие
        pm.setDevicePixelRatio(1.0)
        out = QPixmap(pm.size())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap(0, 0, pm)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        th = themes.current
        p.fillRect(out.rect(), th.q(th.on_surface))
        p.end()
        return QIcon(out)

    def _apply_theme(self):
        """Перекрашивает интерфейс; визуализаторы читают тему сами."""
        self.setStyleSheet(build_style(themes.current))
        self.btn_stop.setIcon(self._icon(QStyle.SP_MediaStop))
        self.btn_prev.setIcon(self._icon(QStyle.SP_MediaSkipBackward))
        self.btn_next.setIcon(self._icon(QStyle.SP_MediaSkipForward))
        self.vol_icon.setPixmap(
            self._icon(QStyle.SP_MediaVolume).pixmap(18, 18))
        self.theme_pill.setText("Тема: %s" % themes.current.name)
        self.centralWidget().update()
        self._on_state(self.engine.state)   # цвет статуса
        for menu in (self.menu, self.dl_menu, self.viz_menu,
                     self.bg_menu, self.theme_menu):
            menu.update()

    def _tick_clock(self):
        """Обновляет часы в шапке (раз в секунду, меняется раз в минуту)."""
        self.clock.setText(QTime.currentTime().toString(CLOCK_FORMAT))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # на узком окне прячем слоган и подпись, чтобы пилюлям хватало места
        w = event.size().width()
        base = getattr(self, "_hdr_base", None)
        if base is None:
            return
        tag_w = self.tagline.sizeHint().width()
        slog_w = self.slogan.sizeHint().width()
        want_tag = w >= base + tag_w + 24
        want_slog = w >= base + tag_w + slog_w + 48
        if self.tagline.isVisible() != want_tag:
            self.tagline.setVisible(want_tag)
        if self.slogan.isVisible() != want_slog:
            self.slogan.setVisible(want_slog)

    # ---------- список станций (в меню пилюли) ----------

    def _load_list(self):
        try:
            self.stations = load_stations()
        except Exception as exc:
            QMessageBox.warning(
                self, "Marsik FM",
                "Не удалось прочитать файл станций:\n%s\n\n%s\n\n"
                "Исправьте файл и перезапустите приложение."
                % (DEFAULT_PATH, exc))
            self.stations = []
        self._rebuild_menu()

    def _rebuild_menu(self):
        """Пересобирает меню: станции + разделитель + добавить/удалить."""
        self.menu.clear()
        # первые строки (станции) можно таскать мышью — остальные служебные
        self.menu.drag_rows = len(self.stations)
        for st in self.stations:
            act = self.menu.addAction(
                "%s — %s" % (st["name"], st["description"] or "Radio"))
            tooltip = st["description"] or st["url"]
            if st["description"]:
                tooltip += "\n" + st["url"]
            act.setToolTip(tooltip)
            act.triggered.connect(
                lambda c=False, s=st: self._on_menu_station(s))
        self.menu.addSeparator()
        act_add = self.menu.addAction("＋  Добавить станцию…")
        act_add.triggered.connect(self._on_add_station)
        # удалить можно только выбранную (её имя показывает пилюля)
        cur = self._selected_station()
        if cur is not None:
            act_del = self.menu.addAction("✕  Удалить «%s»" % cur["name"])
            act_del.triggered.connect(self._on_delete_station)
        else:
            act_del = self.menu.addAction("✕  Удалить станцию")
            act_del.setEnabled(False)

    def _on_station_reordered(self, src, dst):
        """Строку перетащили в меню: dst — индекс, куда вставить."""
        if not (0 <= src < len(self.stations)) or src == dst:
            return
        st = self.stations.pop(src)
        self.stations.insert(dst - 1 if dst > src else dst, st)
        save_stations(self.stations)
        self._rebuild_menu()
        self.menu.refresh()

    def _selected_station(self):
        """Станция, показанная в пилюле (по игре или по QSettings)."""
        want = self._playing_id or self.settings.value("station", "")
        for st in self.stations:
            if st.get("id") == want:
                return st
        return None

    # ---------- добавление/удаление станций ----------

    def _on_add_station(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Новая станция")
        form = QFormLayout(dlg)
        ed_name = QLineEdit(dlg)
        ed_name.setPlaceholderText("Например: Boot Liquor")
        ed_url = QLineEdit(dlg)
        ed_url.setPlaceholderText("https://ice1.somafm.com/…-128-mp3")
        ed_desc = QLineEdit(dlg)
        ed_desc.setPlaceholderText("Описание (необязательно)")
        form.addRow("Название:", ed_name)
        form.addRow("URL потока:", ed_url)
        form.addRow("Описание:", ed_desc)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.Accepted:
            return

        name = ed_name.text().strip()
        url = ed_url.text().strip()
        # валидация до записи: пустое имя/URL и не-http протокол
        if not name:
            QMessageBox.warning(self, "Marsik FM", "Введите название станции.")
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Marsik FM",
                "URL должен начинаться с http:// или https://")
            return
        st_id = name.lower().replace(" ", "_")
        base, n = st_id, 2
        while any(s.get("id") == st_id for s in self.stations):
            st_id = "%s_%d" % (base, n)
            n += 1
        self.stations.append({
            "id": st_id, "name": name,
            "description": ed_desc.text().strip(), "url": url,
        })
        save_stations(self.stations)
        self._rebuild_menu()
        self._flash_pill("Станция добавлена", "#2a9d6a")

    def _on_delete_station(self):
        st = self._selected_station()
        if st is None:
            return
        answer = QMessageBox.question(
            self, "Marsik FM",
            "Удалить станцию «%s»?" % st["name"],
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.stations.remove(st)
        save_stations(self.stations)
        # если она играла — останавливаем и сбрасываем пилюлю
        if st.get("id") == self._playing_id:
            self.engine.stop()
            self._playing_id = None
            self.pill.setText("Выберите станцию")
            self.settings.setValue("station", "")
        self._rebuild_menu()
        self._flash_pill("Станция удалена", "#d24a2a")

    def _restore(self):
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        try:
            self.slider.setValue(int(self.settings.value("volume", 80)))
        except (TypeError, ValueError):
            self.slider.setValue(80)
        station_id = self.settings.value("station", "")
        self.btn_shuffle.setChecked(
            self.settings.value("shuffle", False) in (True, "true"))

        # тема (до фона: авто-тема может зависеть от станции)
        saved = self.settings.value("theme", "")
        if saved == themes.AUTO:
            themes.set(themes.AUTO)
        elif saved in themes.themes:
            themes.set(saved)

        # фон: новый ключ bg_mode; старые bg_file / bg_image — миграция
        bg_mode = self.settings.value("bg_mode", None)
        if bg_mode is None:
            legacy = self.settings.value("bg_file", "")
            if legacy:
                bg_mode = "image" if legacy in _bg_files() else "none"
            else:
                bg_image = self.settings.value("bg_image", True)
                bg_mode = "image" if bg_image in (True, "true") else "none"
        if bg_mode == "image":
            bg_name = self.settings.value("bg_file", "")
            if bg_name and bg_name not in _bg_files():
                bg_name = ""
            self._set_bg(bg_name or "none")
        else:
            self._set_bg("none")

        # визуализатор: -1 (старый ключ) = «Нет»; «card» из старых настроек —
        # режим «Карточка» теперь живёт в меню визуализатора
        if bg_mode == "card":
            viz = CARD_VIZ
        else:
            try:
                viz = int(self.settings.value("viz", 0))
            except (TypeError, ValueError):
                viz = 0
            if viz == -1:
                viz = NONE_VIZ
        self._set_viz(viz)

        # авто-тема: запасной оттенок по последней станции
        if themes.is_auto():
            themes.set_auto_fallback(station_id or "marsik")

        for st in self.stations:
            if st.get("id") == station_id:
                # пилюля показывает прошлую станцию без автозапуска
                self.pill.setText("♪  %s" % st.get("name", ""))
                break

    # ---------- действия ----------

    def _play_station(self, st):
        self._playing_id = st.get("id")
        self._local = False
        self._set_local_ui(False)
        # пилюля-остров показывает активную станцию
        self.pill.setText("♪  %s" % st.get("name", ""))
        if self._viz_idx == CARD_VIZ:
            self._update_card_station()   # обложка станции на обороте
        # если у станции нет локального логотипа — тянем настоящий из сети
        # (SomaFM-каталог / logo-URL) — он нужен для ОБОРОТА карточки
        if not _resolve_logo(st.get("logo")):
            self.cover.fetch_station(st)
        self.engine.play(st["url"])

    def _on_menu_station(self, st):
        # выбор уже звучащей станции — ничего не делаем
        if (st.get("id") == self._playing_id
                and self.engine.state in (CONNECTING, PLAYING, PAUSED)):
            return
        self._play_station(st)

    def _on_prev_next(self, step):
        if self._local and self.queue.items:
            path = self.queue.next() if step > 0 else self.queue.prev()
            if path:
                self._play_queue_item(path)
            return
        if not self.stations:
            return
        idx = None
        for i, st in enumerate(self.stations):
            if st.get("id") == self._playing_id:
                idx = i
                break
        if idx is None:
            # локальный трек/ничего: ← → на край списка станций
            idx = -1 if step > 0 else 0
        self._play_station(self.stations[(idx + step) % len(self.stations)])

    def _on_playpause(self):
        state = self.engine.state
        if state == CONNECTING:
            self.engine.stop()
            return
        if state in (PLAYING, PAUSED):
            self.engine.toggle_pause()
            return
        # возобновляем последнюю станцию или первую из списка
        st = None
        if self._playing_id:
            for cand in self.stations:
                if cand.get("id") == self._playing_id:
                    st = cand
                    break
        if st is None and self.stations:
            st = self.stations[0]
        if st is not None:
            self._play_station(st)

    def _on_stop(self):
        self.engine.stop()

    # ---------- реакция на движок ----------

    def _on_state(self, state):
        text, color = _status_for(state)
        if state == ERROR:
            text = "Ошибка: " + (self._last_error or "воспроизведение не удалось")
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet("color: %s; font-size: 13px;" % color)

        if state == PLAYING:
            icon = QStyle.SP_MediaPause
        elif state == CONNECTING:
            icon = QStyle.SP_MediaStop
        else:
            icon = QStyle.SP_MediaPlay
        self.btn_play.setIcon(self._icon(icon))
        self.btn_stop.setEnabled(state in (CONNECTING, PLAYING, PAUSED))

        # визуализатор живёт, пока есть воспроизведение
        playing_like = state in (CONNECTING, PLAYING, PAUSED)
        for v in self.viz_modes:
            v.set_active(playing_like)
        if playing_like:
            self.tap.start()
        else:
            self.tap.stop()
        self._update_save_state()
        self._sync_seek_row()

    def _on_track(self, title):
        self._track = (title or "").strip()
        self.lbl_track.setText(self._track)
        # ключ ВЫСТАВЛЯЕМ ДО fetch: при попадании в кэш fetch эмитит ready
        # синхронно, и _on_cover_ready иначе отбросит обложку как устаревшую
        self._cover_key = CoverFetcher.key_for(self._track)
        self.cover.fetch(self._track)
        self._update_save_state()

    def _current_station(self):
        for s in self.stations:
            if s.get("id") == self._playing_id:
                return s
        return None

    def _on_cover_ready(self, key, pm):
        """Готова картинка: обложка трека (лицо) или логотип станции (оборот)."""
        # логотип станции, скачанный из сети (каталог SomaFM / logo-URL)
        if key.startswith("station|"):
            sid = key.split("|", 1)[1]
            if not pm.isNull():
                self._station_logos[sid] = pm
            if sid == self._playing_id and self._viz_idx == CARD_VIZ:
                self._update_card_station()
            return
        if key != self._cover_key:
            return   # трек уже сменился — этот ответ не актуален
        self._cover_pixmap = pm
        if self._viz_idx == CARD_VIZ:
            # лицо всегда = обложка трека (pm или сгенерированная из названия)
            self._card.set_front(self._front_cover_pm(self._current_station()))
            st = self._current_station()
            if (st is not None
                    and not _resolve_logo(st.get("logo"))
                    and st.get("id") not in self._station_logos):
                self.cover.fetch_station(st)   # логотип станции для ОБОРОТА
        if themes.is_auto():
            avg = self._avg_color(pm) if not pm.isNull() else None
            if avg is None:
                themes.set_auto_fallback(self._playing_id or "marsik")
            else:
                themes.set_auto(avg)

    @staticmethod
    def _avg_color(pm):
        """Средний цвет картинки (10×10) — как averageColor в мобильной."""
        if pm.isNull():
            return None
        small = pm.scaled(10, 10, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = small.toImage()
        r = g = b = n = 0
        for y in range(10):
            for x in range(10):
                c = img.pixelColor(x, y)
                r += c.red(); g += c.green(); b += c.blue(); n += 1
        if not n:
            return None
        return (r // n, g // n, b // n)

    def _on_error(self, message):
        self._last_error = message
        if self.engine.state == ERROR:
            self.lbl_status.setText("Ошибка: " + message)
            self.lbl_status.setStyleSheet(
                "color: %s; font-size: 13px;" % _status_for(ERROR)[1])

    # ---------- скачивание треков (yt-dlp) ----------

    def _update_save_state(self):
        # качать можно, только когда играет поток и известен трек
        busy = self._dl_proc is not None
        can = bool(_YTDLP and self.engine.state == PLAYING
                   and self._track and not self._local and not busy)
        self.btn_save.setEnabled(can or busy)
        if not busy:
            self.btn_save.setText("Сохранить")
            self.btn_save.setToolTip(
                "Скачать текущий трек (yt-dlp) в «Музыка»"
                if _YTDLP else
                "yt-dlp не найден в системе — скачивание недоступно")

    def _on_save_clicked(self):
        if self._dl_proc is not None:
            # повторный клик — отмена скачивания
            self._dl_proc.kill()
            return
        if not (_YTDLP and self._track):
            return
        os.makedirs(DL_DIR, exist_ok=True)
        self._dl_proc = QProcess(self)
        self._dl_proc.setProcessChannelMode(QProcess.MergedChannels)
        self._dl_proc.readyRead.connect(self._on_dl_output)
        self._dl_proc.finished.connect(self._on_dl_finished)
        # ищем трек на YouTube, качаем аудио, конвертируем в mp3
        # (без --no-progress: он глушит именно строки с процентами)
        args = [
            _YTDLP, "-x", "--audio-format", "mp3", "--newline",
            "--no-playlist", "--no-colors",
            "-o", os.path.join(DL_DIR, "%(title).120B.%(ext)s"),
            "ytsearch1:" + self._track,
        ]
        self._dl_buf = ""
        self._dl_proc.start(args[0], args[1:])
        self.dl_progress.setValue(0)
        self.dl_progress.show()
        self.btn_save.setText("Отмена")
        self.btn_save.setEnabled(True)

    def _on_dl_output(self):
        """Читаем вывод yt-dlp и обновляем полосу процентами.

        readyRead отдаёт куски, а не строки: последняя строка может прийти
        недописанной, поэтому хвост держим в буфере до следующего чтения.
        """
        data = bytes(self._dl_proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        text = self._dl_buf + data
        *lines, self._dl_buf = text.split("\n")
        for line in lines:
            m = _DL_PCT_RE.search(line)
            if not m:
                continue
            pct = float(m.group(1))
            self.dl_progress.setValue(int(pct))
            self.dl_progress.setFormat("%.0f%%" % pct)

    def _on_dl_finished(self, code, status):
        proc = self._dl_proc
        self._dl_proc = None
        self._dl_buf = ""
        self.dl_progress.hide()
        proc.deleteLater()
        if code == 0:
            self._flash_pill("✓ Сохранено!", "#2a9d6a")
        else:
            self._flash_pill("Ошибка скачивания", "#d24a2a")
        self._update_save_state()

    def _flash_pill(self, text, color, ms=2500):
        # кратковременная подсветка в пилюле скачанных
        self.dl_pill.setText(text)
        self.dl_pill.setStyleSheet("color: %s; font-weight: bold;" % color)
        QTimer.singleShot(ms, self._reset_dl_pill)

    def _reset_dl_pill(self):
        if self._dl_proc is not None:
            return   # идёт скачивание — не сбрасываем текст
        self.dl_pill.setStyleSheet("")
        self._count_downloads()

    # ---------- скачанные треки ----------

    def _downloads_list(self):
        if not os.path.isdir(DL_DIR):
            return []
        try:
            names = [n for n in os.listdir(DL_DIR)
                     if n.lower().endswith((".mp3", ".ogg", ".flac", ".m4a"))]
        except OSError:
            return []
        # новые сверху
        names.sort(key=lambda n: os.path.getmtime(
            os.path.join(DL_DIR, n)), reverse=True)
        return names

    def _count_downloads(self):
        n = len(self._downloads_list())
        self.dl_pill.setText(
            "Скачанные (%d)" % n if n else "Скачанные")

    def _scan_downloads(self):
        self.dl_menu.clear()
        self._dl_actions = {}
        files = self._downloads_list()
        if not files:
            act = self.dl_menu.addAction("Пока ничего не скачано")
            act.setEnabled(False)
            return
        a_all = self.dl_menu.addAction("Играть все по порядку")
        a_all.triggered.connect(lambda c=False: self._start_queue(None, False))
        a_rnd = self.dl_menu.addAction("Играть вперемешку")
        a_rnd.triggered.connect(lambda c=False: self._start_queue(None, True))
        self.dl_menu.addSeparator()
        paths = []
        for name in files:
            path = os.path.join(DL_DIR, name)
            paths.append(path)
            act = self.dl_menu.addAction(os.path.splitext(name)[0])
            dur = self.durations.get(path)
            act.setData(fmt_time(dur) if dur else "")   # "" резервирует колонку
            act.triggered.connect(
                lambda c=False, p=path: self._start_queue(p))
            self._dl_actions[path] = act
        self.durations.request(paths)       # недостающие — в фоне

    def _on_duration_ready(self, path, dur):
        act = self._dl_actions.get(path)
        if act is not None and dur > 0:
            act.setData(fmt_time(dur))
            self.dl_menu.update()

    def _start_queue(self, path=None, shuffle=None):
        """Запуск очереди скачанных: с выбранного трека или с начала."""
        files = [os.path.join(DL_DIR, n) for n in self._downloads_list()]
        if not files:
            return
        if shuffle is not None:
            self.btn_shuffle.setChecked(shuffle)
        self.queue.shuffle = self.btn_shuffle.isChecked()
        if path is None:
            path = random.choice(files) if self.queue.shuffle else files[0]
        self.queue.start(files, path)
        self._play_queue_item(path)

    def _play_queue_item(self, path):
        # локальный трек: показываем имя файла в пилюле станции
        self._playing_id = None
        self._local = True
        self._set_local_ui(True)
        self.pill.setText("♪  %s" % os.path.splitext(
            os.path.basename(path))[0])
        self.engine.play(path)

    def _play_local(self, path):          # совместимость со старым кодом
        self._start_queue(path)

    def _sync_seek_row(self):
        """Строка прогресса: загрузка (бегущая полоска) или позиция трека."""
        connecting = self.engine.state == CONNECTING
        have_dur = self._local and self._cur_dur > 0 and not connecting
        self.busy.setVisible(connecting)
        self.seek.setVisible(have_dur)
        self.lbl_dur.setVisible(have_dur)
        self.lbl_pos.setVisible(connecting or have_dur)
        if connecting:
            self.lbl_pos.setText("Загрузка…")
        self.seek_row.setVisible(connecting or have_dur)

    def _set_local_ui(self, on):
        self.btn_shuffle.setVisible(on)
        self.btn_prev.setToolTip(
            "Предыдущий трек" if on else "Предыдущая станция")
        self.btn_next.setToolTip(
            "Следующий трек" if on else "Следующая станция")
        if not on:
            self._cur_dur = 0.0
            self._sync_seek_row()

    def _on_shuffle_toggled(self, on):
        self.queue.set_shuffle(on)
        self.settings.setValue("shuffle", bool(on))

    def _on_position(self, pos, dur):
        if not self._local or dur <= 0:
            self._cur_dur = 0.0
        else:
            self._cur_dur = dur
            self.lbl_pos.setText(fmt_time(pos))
            self.lbl_dur.setText(fmt_time(dur))
            if not self.seek.dragging:
                self.seek.setValue(
                    int(min(1.0, pos / dur) * self.seek.maximum()))
        self._sync_seek_row()

    def _on_seek(self, frac):
        if self._cur_dur > 0:
            self.engine.seek(frac * self._cur_dur)

    def _on_file_ended(self):
        """Трек доигран: следующий из очереди (по порядку или случайный)."""
        nxt = self.queue.next() if (self._local and self.queue.items) else None
        if nxt:
            self._play_queue_item(nxt)
        else:
            self.engine.stop()

    # ---------- закрытие ----------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_card()

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("volume", self.slider.value())
        self.settings.setValue("station", self._playing_id or "")
        if self._dl_proc is not None:
            self._dl_proc.kill()   # без сирот yt-dlp
            self._dl_proc.waitForFinished(2000)
        self.tap.stop()
        self.engine.shutdown()
        super().closeEvent(event)
