"""Главное окно Marsik FM: пилюли-островы + визуализатор + плеер.

Раскладка по макету: шапка с логотипом, пилюля станции (выпадающий список),
пилюля скачанных треков, в центре — визуализатор поверх оконного фонового
изображения, снизу — панель плеера (play/←/→/стоп/громкость/сохранить).

Скачивание треков: yt-dlp ищет текущий трек по метаданным радио и
сохраняет mp3 в downloads/ (запуск через QProcess — интерфейс не замирает).

Вся логика (движок mpv, аудио-тап, 5 режимов визуализации) осталась
прежней — маскот-кот убран из интерфейса (вернёмся к коту-бонго позже).
"""
import os
import re
import shutil

from PySide6.QtCore import (
    QAbstractAnimation, QPropertyAnimation, QProcess, Qt, QSettings, QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QMenu, QMainWindow, QMessageBox, QProgressBar, QSlider, QStackedWidget,
    QStyle, QToolButton, QVBoxLayout, QWidget,
)

from .engine import AudioEngine, CONNECTING, ERROR, PAUSED, PLAYING, STOPPED
from .stations import DEFAULT_PATH, load_stations
from .tap import AudioTap
from .viz.glowing_wave import GlowingWave
from .viz.nebulous import Nebulous
from .viz.galaxy import Galaxy
from .viz.oscilloscope import Oscilloscope
from .viz.aurora import Aurora

# папка скачанных треков (mp3 не попадают в git)
DL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "downloads")
_YTDLP = shutil.which("yt-dlp") or ""
# yt-dlp: строка прогресса "[download]  45.2% of ..."
_DL_PCT_RE = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")

# состояние -> (текст статуса, цвет)
_STATUS = {
    STOPPED: ("Остановлено", "#8a7466"),
    CONNECTING: ("Подключение…", "#c48a1a"),
    PLAYING: ("Играет", "#2a9d6a"),
    PAUSED: ("Пауза", "#c48a1a"),
    ERROR: ("Ошибка", "#d24a2a"),
}

_STYLE = """
QWidget {
    color: #40312a;
    font-size: 14px;
}
QLabel#logo {
    font-size: 24px;
    font-weight: 800;
    color: #4a2f50;
}
QLabel#tagline {
    font-size: 11px;
    color: #c46a2c;
    letter-spacing: 2px;
}
QLabel#slogan {
    font-size: 13px;
    color: #8a6a4a;
    font-style: italic;
}
QLabel#section {
    font-size: 12px;
    color: #8a7466;
    letter-spacing: 2px;
}
QLabel#station {
    font-size: 20px;
    font-weight: bold;
    color: #3f2d36;
}
QLabel#desc {
    color: #8a7466;
    font-size: 13px;
}
QLabel#track {
    color: #c46a2c;
    font-size: 14px;
}
QLabel#status {
    font-size: 13px;
}
QFrame#panel {
    background: rgba(255, 250, 243, 222);
    border: 1px solid rgba(120, 80, 50, 34);
    border-radius: 16px;
}
QFrame#playerBar {
    background: rgba(255, 250, 243, 232);
    border: 1px solid rgba(120, 80, 50, 34);
    border-radius: 22px;
}
QToolButton#pill {
    background: rgba(255, 250, 243, 235);
    border: 1px solid rgba(224, 138, 60, 120);
    border-radius: 17px;
    padding: 8px 18px;
    font-size: 14px;
    font-weight: bold;
    color: #4a2f50;
}
QToolButton#pill:hover {
    background: rgba(240, 200, 160, 220);
    border-color: rgba(224, 138, 60, 220);
}
QToolButton#save {
    background: rgba(224, 138, 60, 235);
    border: 1px solid rgba(180, 100, 40, 160);
    border-radius: 10px;
    padding: 9px 16px;
    font-weight: bold;
    color: #ffffff;
}
QToolButton#save:hover {
    background: rgba(236, 154, 82, 245);
}
QToolButton#save:pressed {
    background: rgba(200, 116, 44, 245);
}
QToolButton#save:disabled {
    background: rgba(255, 252, 246, 220);
    color: #b9ab9e;
    border: 1px solid rgba(120, 80, 50, 46);
}
QProgressBar#dlProgress {
    background: rgba(120, 80, 50, 40);
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    font-size: 10px;
    color: #ffffff;
}
QProgressBar#dlProgress::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #e8a05a, stop:1 #e06a2c);
    border-radius: 5px;
}
QMenu#stationMenu {
    background: rgba(255, 250, 243, 246);
    border: 1px solid rgba(120, 80, 50, 46);
    border-radius: 12px;
    padding: 6px;
}
QMenu#stationMenu::item {
    padding: 9px 16px;
    border-radius: 8px;
    color: #40312a;
}
QMenu#stationMenu::item:selected {
    background: rgba(232, 140, 66, 235);
    color: #ffffff;
}
QToolButton {
    background: rgba(255, 252, 246, 220);
    border: 1px solid rgba(120, 80, 50, 46);
    border-radius: 10px;
    padding: 9px;
}
QToolButton:hover {
    background: rgba(240, 200, 160, 200);
}
QToolButton:pressed {
    background: rgba(226, 170, 120, 220);
}
QToolButton:disabled {
    color: #b9ab9e;
}
QToolButton#play {
    background: rgba(255, 250, 243, 235);
    border: 2px solid #e08a3c;
    border-radius: 25px;
    padding: 12px;
}
QToolButton#play:hover {
    background: rgba(240, 190, 140, 220);
}
QComboBox {
    background: rgba(255, 252, 246, 225);
    border: 1px solid rgba(120, 80, 50, 46);
    border-radius: 8px;
    padding: 5px 10px;
}
QComboBox:hover {
    border-color: rgba(224, 138, 60, 160);
}
QCheckBox {
    color: #8a7466;
}
QCheckBox:hover {
    color: #40312a;
}
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(120, 80, 50, 60);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #e08a3c;
}
QSlider::sub-page:horizontal {
    background: #e08a3c;
    border-radius: 2px;
}
"""

STYLE = _STYLE


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
            p.fillRect(self.rect(), QColor(255, 244, 226, 46))
        else:
            p.fillRect(self.rect(), QColor(248, 240, 228))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Marsik FM")
        self.resize(1100, 640)
        self.setMinimumSize(880, 560)
        self.settings = QSettings("radiofm", "radiofm")
        self.engine = AudioEngine(parent=self)
        self._playing_id = None
        self._last_error = ""
        self._track = ""            # текущий трек (метаданные)
        self._dl_proc = None        # активный процесс yt-dlp
        self._local = False         # играет локальный файл (не радио)

        self._build()
        self._load_list()
        self._count_downloads()
        self._restore()

        self.engine.stateChanged.connect(self._on_state)
        self.engine.trackChanged.connect(self._on_track)
        self.engine.errorRaised.connect(self._on_error)
        self._on_state(self.engine.state)

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
        logo_col.addWidget(logo)
        logo_col.addWidget(tag)
        hbox.addLayout(logo_col)
        hbox.addSpacing(24)

        # «динамический остров»: пилюля активной станции, клик — список
        self.menu = _FadeMenu(self)
        self.menu.setObjectName("stationMenu")
        self.pill = QToolButton()
        self.pill.setObjectName("pill")
        self.pill.setText("Выберите станцию")
        self.pill.setPopupMode(QToolButton.InstantPopup)
        self.pill.setMenu(self.menu)
        self.pill.setToolTip("Станции (клик — список)")
        hbox.addWidget(self.pill, 0, Qt.AlignVCenter)

        hbox.addSpacing(10)

        # пилюля скачанных треков: список из downloads/, клик — воспроизведение
        self.dl_menu = _FadeMenu(self)
        self.dl_menu.setObjectName("stationMenu")
        self.dl_menu.aboutToShow.connect(self._scan_downloads)
        self.dl_pill = QToolButton()
        self.dl_pill.setObjectName("pill")
        self.dl_pill.setText("Скачанные")
        self.dl_pill.setPopupMode(QToolButton.InstantPopup)
        self.dl_pill.setMenu(self.dl_menu)
        self.dl_pill.setToolTip("Скачанные треки (клик — список)")
        hbox.addWidget(self.dl_pill, 0, Qt.AlignVCenter)

        hbox.addStretch(1)
        slogan = QLabel("Хорошая музыка делает день лучше ✦")
        slogan.setObjectName("slogan")
        hbox.addWidget(slogan, 0, Qt.AlignVCenter)
        root.addWidget(header)

        # --- центр: только визуализатор (место колонок освобождено) ---
        content = QHBoxLayout()
        content.setSpacing(10)
        center = QVBoxLayout()
        center.setSpacing(8)
        viz_top = QHBoxLayout()
        self.viz_combo = QComboBox()
        self.viz_combo.addItems(
            ["Glowing Wave", "Nebulous", "Galaxy", "Oscilloscope", "Aurora"])
        self.viz_combo.setToolTip("Режим визуализатора")
        self.viz_combo.currentIndexChanged.connect(
            lambda i: self.viz_stack.setCurrentIndex(i))
        self.bg_check = QCheckBox("Фон с котом")
        self.bg_check.setToolTip("Фоновое изображение под визуализатором")
        self.bg_check.toggled.connect(self._on_bg_toggled)
        viz_top.addWidget(self.viz_combo)
        viz_top.addWidget(self.bg_check)
        viz_top.addStretch(1)
        center.addLayout(viz_top)

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
        self.btn_stop.setIcon(
            self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.clicked.connect(self._on_stop)
        btn_prev = QToolButton()
        btn_prev.setFixedSize(44, 44)
        btn_prev.setIconSize(btn_prev.size() * 0.45)
        btn_prev.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        btn_prev.setToolTip("Предыдущая станция")
        btn_prev.clicked.connect(lambda: self._on_prev_next(-1))
        btn_next = QToolButton()
        btn_next.setFixedSize(44, 44)
        btn_next.setIconSize(btn_next.size() * 0.45)
        btn_next.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSkipForward))
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
            "Скачать текущий трек (yt-dlp) в downloads/")
        self.btn_save.clicked.connect(self._on_save_clicked)
        ph.addWidget(self.btn_save, 0, Qt.AlignVCenter)

        vol_icon = QLabel()
        vol_icon.setPixmap(self.style().standardIcon(
            QStyle.SP_MediaVolume).pixmap(18, 18))
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

    def _on_bg_toggled(self, on):
        # оконный фон (сонный кот на террасе) под всеми режимами
        pm = None
        if on:
            path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "backgrounds", "balcony.png")
            if os.path.exists(path):
                pm = QPixmap(path)
        self.centralWidget().set_pixmap(pm)
        for v in self.viz_modes:
            v.set_window_bg(pm is not None)
        self.settings.setValue("bg_image", bool(on))

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
        for st in self.stations:
            act = self.menu.addAction(
                "%s — %s" % (st["name"], st["description"] or "Radio"))
            tooltip = st["description"] or st["url"]
            if st["description"]:
                tooltip += "\n" + st["url"]
            act.setToolTip(tooltip)
            act.triggered.connect(
                lambda c=False, s=st: self._on_menu_station(s))

    def _restore(self):
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        try:
            self.slider.setValue(int(self.settings.value("volume", 80)))
        except (TypeError, ValueError):
            self.slider.setValue(80)
        station_id = self.settings.value("station", "")
        # фон с котом по умолчанию включён (как в макете)
        if self.settings.value("bg_image", True) in (True, "true"):
            self.bg_check.setChecked(True)
        for st in self.stations:
            if st.get("id") == station_id:
                # пилюля показывает прошлую станцию без автозапуска
                self.pill.setText("♪  %s" % st.get("name", ""))
                break

    # ---------- действия ----------

    def _play_station(self, st):
        self._playing_id = st.get("id")
        self._local = False
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
        text, color = _STATUS.get(state, ("…", "#8b93a3"))
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
        self.btn_play.setIcon(self.style().standardIcon(icon))
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
                "color: %s; font-size: 13px;" % _STATUS[ERROR][1])

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
                "Скачать текущий трек (yt-dlp) в downloads/"
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
        args = [
            _YTDLP, "-x", "--audio-format", "mp3", "--no-progress",
            "--newline", "--no-playlist",
            "-o", os.path.join(DL_DIR, "%(title).120B.%(ext)s"),
            "ytsearch1:" + self._track,
        ]
        self._dl_proc.start(args[0], args[1:])
        self.dl_progress.setValue(0)
        self.dl_progress.show()
        self.btn_save.setText("Отмена")
        self.btn_save.setEnabled(True)

    def _on_dl_output(self):
        data = bytes(self._dl_proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        m = _DL_PCT_RE.findall(data)
        if m:
            self.dl_progress.setValue(int(float(m[-1])))

    def _on_dl_finished(self, code, status):
        proc = self._dl_proc
        self._dl_proc = None
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
        files = self._downloads_list()
        if not files:
            act = self.dl_menu.addAction("Пока ничего не скачано")
            act.setEnabled(False)
            return
        for name in files:
            act = self.dl_menu.addAction(os.path.splitext(name)[0])
            act.triggered.connect(
                lambda c=False, p=os.path.join(DL_DIR, name):
                    self._play_local(p))

    def _play_local(self, path):
        # локальный трек: показываем имя файла в пилюле станции
        self._playing_id = None
        self._local = True
        self.pill.setText("♪  %s" % os.path.splitext(
            os.path.basename(path))[0])
        self.engine.play(path)

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
