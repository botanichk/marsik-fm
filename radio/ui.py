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
import re
import shutil
from string import Template

from PySide6.QtCore import (
    QAbstractAnimation, QPropertyAnimation, QProcess, QSettings,
    QStandardPaths, Qt, QTimer,
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QSlider, QStackedWidget,
    QStyle, QToolButton, QVBoxLayout, QWidget,
)

from .island import IslandMenu
from .theme import THEMES_DIR, hexs, manager as themes, rgba
from .engine import AudioEngine, CONNECTING, ERROR, PAUSED, PLAYING, STOPPED
from .stations import DEFAULT_PATH, load_stations, save_stations
from .tap import AudioTap
from .tracks import duration as track_duration, fmt_time
from .viz.glowing_wave import GlowingWave
from .viz.nebulous import Nebulous
from .viz.galaxy import Galaxy
from .viz.oscilloscope import Oscilloscope
from .viz.aurora import Aurora

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


def _elide(text, widget, px):
    """Обрезает текст многоточием под ширину px (длинные имена файлов)."""
    fm = widget.fontMetrics()
    return fm.elidedText(text, Qt.ElideMiddle, px)


_VIZ_NAMES = ["Glowing Wave", "Nebulous", "Galaxy", "Oscilloscope", "Aurora"]

_YTDLP = shutil.which("yt-dlp") or ""
# yt-dlp: строка прогресса "[download]  45.2% of ... ETA 00:12"
_DL_PCT_RE = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")
_DL_ETA_RE = re.compile(r"ETA\s+(\d{1,2}:\d{2}(?::\d{2})?)")

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
QFrame#progressBar {
    background: ${bar_bg};
    border: 1px solid ${line};
    border-radius: 14px;
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
QToolButton {
    background: ${btn_bg};
    border: 1px solid ${line2};
    border-radius: 10px;
    padding: 9px;
}
QToolButton:hover { background: ${btn_hover}; }
QToolButton:pressed { background: ${btn_press}; }
QToolButton:disabled { color: ${disabled}; }
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
QSlider#progress {
    min-height: 18px;
}
QSlider#progress::groove:horizontal {
    height: 6px;
    background: ${line3};
    border-radius: 3px;
}
QSlider#progress::handle:horizontal {
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: ${primary};
}
QSlider#progress::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 ${prog_a}, stop:1 ${prog_b});
    border-radius: 3px;
}
QSlider#progress:disabled::handle:horizontal {
    background: ${disabled};
}
QLabel#timepos { font-size: 12px; color: ${muted}; }
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Marsik FM")
        self.resize(1100, 640)
        self.setMinimumSize(1100, 560)
        self.settings = QSettings("radiofm", "radiofm")
        self.engine = AudioEngine(parent=self)
        self._playing_id = None
        self._last_error = ""
        self._track = ""            # текущий трек (метаданные)
        self._dl_proc = None        # активный процесс yt-dlp
        self._dl_buf = ""           # недописанная строка вывода yt-dlp
        self._local = False         # играет локальный файл (не радио)
        self._queue = []            # очередь локальных файлов (плейлист)
        self._queue_pos = 0         # позиция в очереди (1-based, для статуса)
        self._queue_total = 0
        self._shuffle = False       # порядок очереди: вперемешку / по порядку
        self._viz_idx = 0           # выбранный режим визуализатора
        self._bg_name = None        # выбранный фон (имя файла) или None

        self._build()
        self._load_list()
        self._count_downloads()
        self._restore()

        self.engine.stateChanged.connect(self._on_state)
        self.engine.trackChanged.connect(self._on_track)
        self.engine.errorRaised.connect(self._on_error)
        self.engine.playlistChanged.connect(self._on_queue_pos)
        self.engine.positionChanged.connect(self._on_position)
        self.engine.seekableChanged.connect(self._on_seekable)
        self._on_state(self.engine.state)

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
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "backgrounds", "logo.png")
        if os.path.exists(logo_path):
            logo_pic = QLabel()
            logo_pic.setPixmap(QPixmap(logo_path).scaled(
                58, 58, Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation))
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
        self.pill = QToolButton()
        self.pill.setObjectName("pill")
        self.pill.setText("Выберите станцию")
        self.pill.setToolTip("Станции (клик — список)")
        self.menu.set_trigger(self.pill)
        self.pill.clicked.connect(self.menu.toggle)
        # меню пересобирается при открытии: пункт «Удалить» всегда актуален
        self.menu.aboutToShow.connect(self._rebuild_menu)
        hbox.addWidget(self.pill, 0, Qt.AlignVCenter)

        hbox.addSpacing(10)

        # пилюля скачанных треков: список из downloads/, клик — воспроизведение
        self.dl_menu = IslandMenu(central, header)
        self.dl_menu.aboutToShow.connect(self._scan_downloads)
        self.dl_pill = QToolButton()
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
        self.viz_pill = QToolButton()
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
        self.bg_pill = QToolButton()
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
        self.theme_pill = QToolButton()
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
        root.addWidget(header)

        # --- центр: только визуализатор (место колонок освобождено) ---
        content = QHBoxLayout()
        content.setSpacing(10)
        center = QVBoxLayout()
        center.setSpacing(8)

        viz_row = QHBoxLayout()
        viz_row.setSpacing(12)
        self.viz_stack = QStackedWidget()
        self.viz_modes = [GlowingWave(), Nebulous(), Galaxy(),
                          Oscilloscope(), Aurora()]
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
        self.lbl_status.setStyleSheet(
            "padding: 2px 8px; border-radius: 8px;")
        root.addWidget(self.lbl_status)

        # полоса прогресса трека: ползёт от 0 до конца, слева/справа время
        prog_frame = QFrame()
        prog_frame.setObjectName("progressBar")
        progress_row = QHBoxLayout(prog_frame)
        progress_row.setContentsMargins(14, 4, 14, 4)
        progress_row.setSpacing(10)
        self.lbl_pos = QLabel("0:00")
        self.lbl_pos.setObjectName("timepos")
        self.lbl_pos.setMinimumWidth(46)
        self.lbl_pos.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_dur = QLabel("—:—")
        self.lbl_dur.setObjectName("timepos")
        self.lbl_dur.setMinimumWidth(46)
        self.lbl_dur.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setObjectName("progress")
        self.progress.setRange(0, 1000)     # промилле: плавно и без float
        self.progress.setValue(0)
        self.progress.setEnabled(False)
        self.progress.setToolTip(
            "Перемотка трека (для радио недоступна — поток без длительности)")
        self.progress.sliderMoved.connect(self._on_seek_preview)
        self.progress.sliderReleased.connect(self._on_seek_commit)
        progress_row.addWidget(self.lbl_pos)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.lbl_dur)
        root.addWidget(prog_frame)
        self._seek_dragging = False
        self._dur = 0.0
        self._downloading = False   # идёт скачивание: полоса показывает его
        self._dl_pct = 0

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
        # подпись под логотипом не должна сжиматься и резаться на середине
        # слова: ширину считаем после стилей, когда шрифт уже применён
        self.tagline.setMinimumWidth(
            self.tagline.fontMetrics().horizontalAdvance(
                self.tagline.text()) + 4)
        self.btn_stop.setIcon(self._icon(QStyle.SP_MediaStop))
        self.btn_prev.setIcon(self._icon(QStyle.SP_MediaSkipBackward))
        self.btn_next.setIcon(self._icon(QStyle.SP_MediaSkipForward))
        self.vol_icon.setPixmap(
            self._icon(QStyle.SP_MediaVolume).pixmap(18, 18))
        self.theme_pill.setText("Тема: %s" % themes.current.name)
        # время трека лежит поверх фоновой картинки — даём подложку
        time_css = (
            "font-size: 12px; color: %s; padding: 1px 6px;"
            " border-radius: 7px; background: %s;"
            % (hexs(themes.current.muted), rgba(themes.current.surface, 190)))
        self.lbl_pos.setStyleSheet(time_css)
        self.lbl_dur.setStyleSheet(time_css)
        self.centralWidget().update()
        self._on_state(self.engine.state)   # цвет статуса
        for menu in (self.menu, self.dl_menu, self.viz_menu,
                     self.bg_menu, self.theme_menu):
            menu.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # на узком окне прячем слоган и подпись, чтобы пилюлям хватало места
        w = event.size().width()
        self.slogan.setVisible(w >= 1500)
        self.tagline.setVisible(w >= 1250)

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
        # порядок очереди для «Скачанных» — запоминаем между запусками
        self._shuffle = self.settings.value("shuffle", False) in (True, "true")
        self.engine.set_shuffle(self._shuffle)
        for st in self.stations:
            if st.get("id") == station_id:
                # пилюля показывает прошлую станцию без автозапуска
                self.pill.setText("♪  %s" % st.get("name", ""))
                break

    # ---------- действия ----------

    def _play_station(self, st):
        self._playing_id = st.get("id")
        self._local = False
        self._queue = []
        self._queue_total = 0
        self._reset_progress_ui()
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
        # в очереди локальных файлов ←/→ листают треки, а не станции
        if self._local and self.engine.has_queue:
            if step > 0:
                self.engine.playlist_next()
            else:
                self.engine.playlist_prev()
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
        self._paint_status(color)
        if state == PLAYING and self._local:
            self._update_queue_label()
        if state in (STOPPED, ERROR):
            self._reset_progress_ui()

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

    def _paint_status(self, color):
        """Статус лежит поверх фоновой картинки — даём ему подложку темы."""
        th = themes.current
        self.lbl_status.setStyleSheet(
            "color: %s; font-size: 13px; padding: 2px 8px;"
            " border-radius: 8px; background: %s;"
            % (color, rgba(th.surface, 200)))
        # высота с учётом padding: иначе Qt обрезает текст по вертикали
        self.lbl_status.setMinimumHeight(
            self.lbl_status.fontMetrics().height() + 8)

    def _on_track(self, title):
        self._track = (title or "").strip()
        self.lbl_track.setText(_elide(self._track, self.lbl_track, 520))
        self.lbl_track.setToolTip(self._track)
        # в очереди пилюля следит за текущим треком, а не за первым
        if self._local and self._track:
            self._set_pill_track(self._track)
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
            self._paint_status(_status_for(ERROR)[1])

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
        self._dl_begin()
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
            self._dl_set_pct(float(m.group(1)))
            eta = _DL_ETA_RE.search(line)
            if eta and self._dl_pct < 100:
                self.lbl_pos.setText("Скачивание · %s" % eta.group(1))

    def _on_dl_finished(self, code, status):
        proc = self._dl_proc
        self._dl_proc = None
        self._dl_buf = ""
        proc.deleteLater()
        self._dl_end()
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
        """Меню «Скачанные»: режим очереди + файлы из «Музыки».

        Клик по файлу — играет вся папка, начиная с него, дальше mpv сам
        переходит к следующему. Первые два пункта — порядок воспроизведения.
        """
        self.dl_menu.clear()
        files = self._downloads_list()
        act = self.dl_menu.addAction(
            "По порядку" if not self._shuffle else "Вперемешку")
        act.setCheckable(True)
        act.setChecked(self._shuffle)
        act.setToolTip("Как играть очередь: по порядку или вперемешку")
        act.triggered.connect(lambda c=False: self._toggle_shuffle())
        self.dl_menu.addSeparator()
        if not files:
            act = self.dl_menu.addAction("Пока ничего не скачано")
            act.setEnabled(False)
            return
        for name in files:
            path = os.path.join(DL_DIR, name)
            secs = track_duration(path)
            label = os.path.splitext(name)[0]
            if secs:
                label = "%s   ·   %s" % (label, fmt_time(secs))
            act = self.dl_menu.addAction(label)
            act.setToolTip(name)
            act.triggered.connect(
                lambda c=False, p=path: self._play_local(p))

    def _toggle_shuffle(self):
        self._shuffle = not self._shuffle
        self.settings.setValue("shuffle", self._shuffle)
        self.engine.set_shuffle(self._shuffle)
        self._flash_pill(
            "Вперемешку" if self._shuffle else "По порядку",
            hexs(themes.current.tertiary))
        self._update_queue_label()

    def _play_local(self, path):
        """Играет папку «Музыка» как плейлист, начиная с выбранного файла."""
        files = self._downloads_list()
        if not files:
            return
        paths = [os.path.join(DL_DIR, n) for n in files]
        if path in paths and not self._shuffle:
            # по порядку: очередь стартует с выбранного, затем остальные по кругу
            i = paths.index(path)
            paths = paths[i:] + paths[:i]
        elif path in paths:
            # вперемешку: выбранный — первым, остальные тасует mpv
            paths.remove(path)
            paths.insert(0, path)
        self._queue = paths
        self._local = True
        self._playing_id = None
        self._set_pill_track(path)
        self.engine.play_playlist(paths, shuffle=self._shuffle)

    def _set_pill_track(self, path):
        """Пилюля станции показывает текущий файл (с обрезкой по ширине)."""
        name = os.path.splitext(os.path.basename(path))[0]
        self.pill.setText("♪  %s" % _elide(name, self.pill, 230))
        self.pill.setToolTip(name)

    def _on_seekable(self, on):
        """Перемотка доступна только для файлов (у потока нет длительности)."""
        self.progress.setEnabled(on and self._dur > 0)

    def _on_position(self, pos, dur):
        """Позиция и длительность от mpv → полоса и два счётчика времени.

        Для радио прогресс не показываем: у потока нет длительности, а mpv
        отдаёт duration буферизованного куска (десятки секунд) — полоса по
        нему врала бы. Живой прогресс — только для локальных файлов.
        """
        if not self._local:
            self._reset_progress_ui()
            return
        if self._downloading:
            return          # полоса занята скачиванием
        self._dur = dur or 0.0
        if self._dur > 0:
            self.lbl_dur.setText(fmt_time(self._dur))
        else:
            self.lbl_dur.setText("—:—")
        if not self._seek_dragging:
            self.lbl_pos.setText(fmt_time(pos))
            if self._dur > 0:
                self.progress.setValue(
                    int(1000 * min(1.0, max(0.0, pos) / self._dur)))
            else:
                self.progress.setValue(0)
        self.progress.setEnabled(bool(self._dur > 0 and self.engine.seekable))

    def _on_seek_preview(self, value):
        """Тянем ползунок: показываем время, но не трогаем воспроизведение."""
        self._seek_dragging = True
        if self._dur > 0:
            self.lbl_pos.setText(fmt_time(self._dur * value / 1000.0))

    def _on_seek_commit(self):
        """Отпустили ползунок — перематываем."""
        self._seek_dragging = False
        if self._dur > 0:
            self.engine.seek(self._dur * self.progress.value() / 1000.0)

    def _reset_progress_ui(self):
        if self._downloading:
            return          # полоса занята скачиванием — не трогаем
        self._dur = 0.0
        self.progress.setValue(0)
        self.progress.setEnabled(False)
        self.lbl_pos.setText("0:00")
        self.lbl_dur.setText("—:—")

    # ---------- полоса как индикатор скачивания ----------

    def _dl_begin(self):
        """Скачивание стартовало: полоса переключается в режим процентов."""
        self._downloading = True
        self._dl_pct = 0
        self._seek_dragging = False
        self.progress.setEnabled(False)     # перематывать во время загрузки нечего
        self.progress.setToolTip("Скачивание трека…")
        self.progress.setValue(0)
        self.lbl_pos.setText("Скачивание")
        self.lbl_dur.setText("0%")

    def _dl_set_pct(self, pct):
        pct = max(0, min(100, int(round(pct))))
        self._dl_pct = pct
        self.progress.setValue(pct * 10)    # шкала полосы — промилле
        self.lbl_dur.setText("%d%%" % pct)
        if pct >= 100:
            # после 100% yt-dlp ещё конвертирует в mp3 — это не мгновенно
            self.lbl_pos.setText("Обработка…")
            self.progress.setToolTip("Скачано, идёт конвертация в mp3…")

    def _dl_end(self):
        """Скачивание закончилось: возвращаем полосу к воспроизведению."""
        self._downloading = False
        self.progress.setToolTip(
            "Перемотка трека (для радио недоступна — поток без длительности)")
        self.lbl_pos.setText("0:00")
        self.lbl_dur.setText("—:—")
        self.progress.setValue(0)
        self.progress.setEnabled(False)
        self._dur = 0.0

    def _on_queue_pos(self, pos, count):
        """Позиция в очереди от mpv → подпись «3 / 6» в статусе."""
        self._queue_pos = pos + 1
        self._queue_total = count
        self._update_queue_label()

    def _update_queue_label(self):
        if not self._local or not self._queue_total:
            return
        mode = "вперемешку" if self._shuffle else "по порядку"
        self.lbl_status.setText("Играет · %d / %d · %s" % (
            self._queue_pos, self._queue_total, mode))

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
