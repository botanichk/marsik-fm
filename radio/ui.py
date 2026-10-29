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
import random
import re
import shutil
from string import Template

from PySide6.QtCore import (
    QAbstractAnimation, QEvent, QPropertyAnimation, QProcess, QSettings,
    QStandardPaths, Qt, QTime, QTimer,
)
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMainWindow, QMessageBox, QProgressBar, QSlider, QStackedWidget,
    QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from .island import IslandMenu
from .playlist import DurationProbe, PlayQueue, fmt_time
from .theme import THEMES_DIR, hexs, manager as themes
from .engine import AudioEngine, CONNECTING, ERROR, PAUSED, PLAYING, STOPPED
from .stations import DEFAULT_PATH, load_stations, save_stations
from .tap import AudioTap
from .viz.glowing_wave import GlowingWave
from .viz.nebulous import Nebulous
from .viz.galaxy import Galaxy
from .viz.oscilloscope import Oscilloscope
from .viz.ring import Ring
from .viz.bars import Bars
from .viz.fireflies import Fireflies
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


_VIZ_NAMES = ["Glowing Wave", "Ring", "Bars", "Fireflies", "Liquid",
              "Galaxy", "Oscilloscope", "Nebulous"]

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


class _FadeMenu(QMenu):
    """Меню с плавным появлением (fade-in 140 мс)."""

    def showEvent(self, event):
        super().showEvent(event)
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(0.0)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start(QAbstractAnimation.DeleteWhenStopped)


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

    def set_pixmap(self, pm):
        self._pixmap = pm
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
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
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # --- шапка: логотип-котик + название + слоган ---
        header = QFrame()
        header.setObjectName("panel")
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
        # перетаскивание станций: новый порядок сохраняется в stations.json
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

        # ширина пилюль ограничена в Pill (длинный текст режется многоточием)

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
        self.viz_modes = [GlowingWave(), Ring(), Bars(), Fireflies(),
                          Liquid(), Galaxy(), Oscilloscope(), Nebulous()]
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

        # аудио-тап → все режимы визуализатора
        self.tap = AudioTap()
        for v in self.viz_modes:
            self.tap.level.connect(v.set_audio_level)
            self.tap.bands.connect(v.set_bands)
            self.tap.wave.connect(v.set_wave)
        self.viz_stack.currentChanged.connect(self._on_viz_changed)

    def _on_viz_changed(self, idx):
        # плавное появление нового режима (fade-in 180 мс)
        w = self.viz_stack.widget(idx)
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", w)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start(QAbstractAnimation.DeleteWhenStopped)

    def _build_viz_menu(self):
        self.viz_menu.clear()
        for i, name in enumerate(_VIZ_NAMES):
            act = self.viz_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(i == self._viz_idx)
            act.triggered.connect(lambda c=False, k=i: self._set_viz(k))

    def _set_viz(self, idx):
        self._viz_idx = idx
        self.viz_stack.setCurrentIndex(idx)
        self.viz_pill.setText("✦  %s" % _VIZ_NAMES[idx])
        self.settings.setValue("viz", idx)

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
        # оконный фон под всеми режимами; None = «Без фона»
        pm = None
        if name:
            cand = QPixmap(os.path.join(BG_DIR, name))
            if not cand.isNull():
                pm = cand
        self._bg_name = name if pm is not None else None
        self.centralWidget().set_pixmap(pm)
        for v in self.viz_modes:
            v.set_window_bg(pm is not None)
        self.bg_pill.setText(
            "Фон: %s" % (_bg_label(self._bg_name) if self._bg_name
                         else "без фона"))
        self.settings.setValue("bg_file", self._bg_name or "")

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
        # фон: новый ключ bg_file; старый bg_image (вкл/выкл кота) — миграция
        bg = self.settings.value("bg_file", None)
        if bg is None:
            legacy = self.settings.value("bg_image", True)
            bg = _BG_LEGACY if legacy in (True, "true") else ""
        self.btn_shuffle.setChecked(
            self.settings.value("shuffle", False) in (True, "true"))
        saved = self.settings.value("theme", "")
        if saved in themes.themes:
            themes.set(saved)
        if bg and bg not in _bg_files():
            bg = ""
        self._set_bg(bg or None)
        try:
            viz = int(self.settings.value("viz", 0))
        except (TypeError, ValueError):
            viz = 0
        self._set_viz(viz if 0 <= viz < len(_VIZ_NAMES) else 0)
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
        # плавное появление нового трека (fade-in 220 мс)
        if title:
            eff = QGraphicsOpacityEffect(self.lbl_track)
            eff.setOpacity(0.0)
            self.lbl_track.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", self.lbl_track)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._update_save_state()

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
        self.dl_progress.setFormat("%p%")
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
        self.dl_progress.setFormat("%p%")
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
