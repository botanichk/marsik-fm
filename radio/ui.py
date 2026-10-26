"""Главное окно Marsik FM: сайдбар станций + визуализатор + плеер.

Раскладка по макету: шапка с логотипом и слоганом, слева панель станций,
в центре — визуализатор поверх оконного фонового изображения, справа —
карточка «СЕЙЧАС В ЭФИРЕ», снизу — панель плеера (play/стоп/←/→/громкость).

Вся логика (движок mpv, аудио-тап, маскот-кот, 5 режимов визуализации)
осталась прежней — перестроен только layout и стили.
"""
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QSlider, QStackedWidget,
    QStyle, QToolButton, QVBoxLayout, QWidget,
)

from .engine import AudioEngine, CONNECTING, ERROR, PAUSED, PLAYING, STOPPED
from .mascot import MarsikCat
from .stations import DEFAULT_PATH, load_stations
from .tap import AudioTap
from .viz.glowing_wave import GlowingWave
from .viz.nebulous import Nebulous
from .viz.galaxy import Galaxy
from .viz.oscilloscope import Oscilloscope
from .viz.aurora import Aurora

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
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 10px;
    margin: 1px 2px;
}
QListWidget::item:hover {
    background: rgba(196, 106, 44, 30);
}
QListWidget::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(232, 140, 66, 235), stop:1 rgba(206, 100, 42, 235));
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

        self._build()
        self._load_list()
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
        hbox.addStretch(1)
        slogan = QLabel("Хорошая музыка делает день лучше ✦")
        slogan.setObjectName("slogan")
        hbox.addWidget(slogan, 0, Qt.AlignVCenter)
        root.addWidget(header)

        # --- центр: сайдбар | визуализатор | карточка ---
        content = QHBoxLayout()
        content.setSpacing(10)

        # сайдбар станций
        sidebar = QFrame()
        sidebar.setObjectName("panel")
        sidebar.setFixedWidth(250)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(10, 12, 10, 12)
        sb.setSpacing(6)
        section = QLabel("СТАНЦИИ")
        section.setObjectName("section")
        sb.addWidget(section)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_station_clicked)
        sb.addWidget(self.list, 1)
        content.addWidget(sidebar, 0)

        # центральная колонка: визуализатор + маскот
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
        self.wave = self.viz_modes[0]   # для совместимости (кот и тап)
        self.cat = MarsikCat()
        viz_row.addWidget(self.viz_stack, 1)
        viz_row.addWidget(self.cat, 0, Qt.AlignVCenter)
        center.addLayout(viz_row, 1)
        content.addLayout(center, 1)

        # карточка «СЕЙЧАС В ЭФИРЕ»
        card = QFrame()
        card.setObjectName("panel")
        card.setFixedWidth(280)
        cc = QVBoxLayout(card)
        cc.setContentsMargins(16, 14, 16, 14)
        cc.setSpacing(8)
        live = QLabel("●  СЕЙЧАС В ЭФИРЕ")
        live.setObjectName("section")
        live.setStyleSheet("color: #d24a2a;")
        cc.addWidget(live)
        self.lbl_station = QLabel("Выберите станцию")
        self.lbl_station.setObjectName("station")
        self.lbl_station.setWordWrap(True)
        self.lbl_desc = QLabel("")
        self.lbl_desc.setObjectName("desc")
        self.lbl_desc.setWordWrap(True)
        self.lbl_track = QLabel("")
        self.lbl_track.setObjectName("track")
        self.lbl_track.setWordWrap(True)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("status")
        cc.addWidget(self.lbl_station)
        cc.addWidget(self.lbl_desc)
        cc.addWidget(self.lbl_track)
        cc.addStretch(1)
        cc.addWidget(self.lbl_status)
        content.addWidget(card, 0)

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
        root.addWidget(player)

        self.setCentralWidget(central)

        # аудио-тап → все режимы визуализатора + маскот
        self.tap = AudioTap()
        for v in self.viz_modes:
            self.tap.level.connect(v.set_audio_level)
            self.tap.bands.connect(v.set_bands)
            self.tap.wave.connect(v.set_wave)
        # кот питается от текущего активного режима
        self.viz_stack.currentChanged.connect(self._on_viz_changed)
        self.viz_modes[0].envChanged.connect(self.cat.set_energy)

    def _on_viz_changed(self, idx):
        # переподключаем маскота к энергии выбранного режима
        for v in self.viz_modes:
            try:
                v.envChanged.disconnect(self.cat.set_energy)
            except Exception:
                pass
        cur = self.viz_stack.currentWidget()
        cur.envChanged.connect(self.cat.set_energy)

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

    # ---------- список станций ----------

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
            # две строки, как в макете: имя + описание (rich text не работает
            # в QListWidget этой сборки Qt — обычный текст в две строки)
            item = QListWidgetItem(
                "%s\n%s" % (st["name"], st["description"] or "Radio"))
            item.setData(Qt.UserRole, st)
            tooltip = st["description"] or st["url"]
            if st["description"]:
                tooltip += "\n" + st["url"]
            item.setToolTip(tooltip)
            self.list.addItem(item)

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
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole).get("id") == station_id:
                self.list.setCurrentRow(row)
                self._show_station(item)
                break

    # ---------- действия ----------

    def _show_station(self, item):
        st = item.data(Qt.UserRole)
        self.lbl_station.setText(st.get("name", ""))
        self.lbl_desc.setText(st.get("description", ""))

    def _play_item(self, item):
        self.list.setCurrentItem(item)
        self._show_station(item)
        self._playing_id = item.data(Qt.UserRole).get("id")
        self.engine.play(item.data(Qt.UserRole)["url"])

    def _on_station_clicked(self, item):
        # клик по уже звучащей станции — ничего не делаем
        if (item.data(Qt.UserRole).get("id") == self._playing_id
                and self.engine.state in (CONNECTING, PLAYING, PAUSED)):
            return
        self._play_item(item)

    def _on_prev_next(self, step):
        if not self.list.count():
            return
        row = self.list.currentRow()
        if row < 0:
            row = 0
        self._play_item(self.list.item((row + step) % self.list.count()))

    def _on_playpause(self):
        state = self.engine.state
        if state == CONNECTING:
            self.engine.stop()
            return
        if state in (PLAYING, PAUSED):
            self.engine.toggle_pause()
            return
        item = self.list.currentItem()
        if item is None and self.list.count():
            item = self.list.item(0)
        if item is not None:
            self._play_item(item)

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

        # визуализатор: все режимы и кот живут, пока есть воспроизведение
        playing_like = state in (CONNECTING, PLAYING, PAUSED)
        for v in self.viz_modes:
            v.set_active(playing_like)
        self.cat.set_active(playing_like)
        if playing_like:
            self.tap.start()
        else:
            self.tap.stop()

    def _on_track(self, title):
        self.lbl_track.setText(title or "")

    def _on_error(self, message):
        self._last_error = message
        if self.engine.state == ERROR:
            self.lbl_status.setText("Ошибка: " + message)
            self.lbl_status.setStyleSheet(
                "color: %s; font-size: 13px;" % _STATUS[ERROR][1])

    # ---------- закрытие ----------

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("volume", self.slider.value())
        item = self.list.currentItem()
        if item is not None:
            self.settings.setValue("station",
                                   item.data(Qt.UserRole).get("id", ""))
        self.tap.stop()
        self.engine.shutdown()
        super().closeEvent(event)
