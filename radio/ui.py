"""Главное окно Marsik FM: список станций + плеер + светящаяся волна."""
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QSlider, QSplitter, QStyle, QToolButton, QVBoxLayout,
    QWidget, QComboBox, QStackedWidget,
)

from .engine import AudioEngine, CONNECTING, ERROR, PAUSED, PLAYING, STOPPED
from .mascot import MarsikCat
from .stations import DEFAULT_PATH, load_stations
from .tap import AudioTap
from .viz.glowing_wave import GlowingWave
from .viz.nebulous import Nebulous

# состояние -> (текст статуса, цвет)
_STATUS = {
    STOPPED: ("Остановлено", "#8b93a3"),
    CONNECTING: ("Подключение…", "#f0b429"),
    PLAYING: ("Играет", "#3ecf8e"),
    PAUSED: ("Пауза", "#f0b429"),
    ERROR: ("Ошибка", "#ff6b6b"),
}

_STYLE = """
QMainWindow, QWidget {
    background: #14161c;
    color: #e6e9ef;
    font-size: 14px;
}
QLabel#header {
    font-size: 17px;
    font-weight: bold;
    color: #ff6b4a;
}
QLabel#station {
    font-size: 20px;
    font-weight: bold;
}
QLabel#desc {
    color: #9aa3b5;
    font-size: 13px;
}
QLabel#track {
    color: #4f9dff;
    font-size: 15px;
}
QLabel#status {
    font-size: 13px;
}
QListWidget {
    background: #1b1e26;
    border: 1px solid #262b36;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 9px 10px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background: #222734;
}
QListWidget::item:selected {
    background: #2b3a52;
    color: #ffffff;
}
QToolButton {
    background: #232833;
    border: 1px solid #2c3240;
    border-radius: 10px;
    padding: 10px;
}
QToolButton:hover {
    background: #2b3242;
}
QToolButton:pressed {
    background: #364054;
}
QToolButton:disabled {
    color: #555c6b;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #2c3240;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #4f9dff;
}
QSlider::sub-page:horizontal {
    background: #4f9dff;
    border-radius: 2px;
}
QSplitter::handle {
    background: #14161c;
    width: 8px;
}
"""

STYLE = _STYLE


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Marsik FM")
        self.resize(940, 580)
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
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QLabel("📻 Marsik FM")
        header.setObjectName("header")
        root.addWidget(header)

        self.list = QListWidget()
        self.list.setMinimumWidth(300)
        self.list.itemClicked.connect(self._on_station_clicked)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 8, 8, 8)
        panel_layout.setSpacing(8)

        self.lbl_station = QLabel("Выберите станцию")
        self.lbl_station.setObjectName("station")
        self.lbl_station.setWordWrap(True)
        self.lbl_desc = QLabel("")
        self.lbl_desc.setObjectName("desc")
        self.lbl_desc.setWordWrap(True)
        self.lbl_track = QLabel("")
        self.lbl_track.setObjectName("track")
        self.lbl_track.setWordWrap(True)
        panel_layout.addWidget(self.lbl_station)
        panel_layout.addWidget(self.lbl_desc)
        panel_layout.addWidget(self.lbl_track)

        # визуализатор (переключаемый) + маскот-кот
        viz_row = QHBoxLayout()
        viz_row.setSpacing(12)
        self.viz_stack = QStackedWidget()
        self.viz_modes = [GlowingWave(), Nebulous()]
        for v in self.viz_modes:
            self.viz_stack.addWidget(v)
        self.wave = self.viz_modes[0]   # для совместимости (кот и тап)
        self.viz_combo = QComboBox()
        self.viz_combo.addItems(["Glowing Wave", "Nebulous"])
        self.viz_combo.setToolTip("Режим визуализатора")
        self.viz_combo.currentIndexChanged.connect(
            lambda i: self.viz_stack.setCurrentIndex(i))
        viz_col = QVBoxLayout()
        viz_col.setSpacing(6)
        viz_col.addWidget(self.viz_combo, 0, Qt.AlignLeft)
        viz_col.addWidget(self.viz_stack, 1)
        self.cat = MarsikCat()
        viz_row.addLayout(viz_col, 1)
        viz_row.addWidget(self.cat, 0, Qt.AlignVCenter)
        panel_layout.addLayout(viz_row, 1)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.btn_play = QToolButton()
        self.btn_play.setFixedSize(52, 52)
        self.btn_play.setIconSize(self.btn_play.size() * 0.5)
        self.btn_play.clicked.connect(self._on_playpause)
        self.btn_stop = QToolButton()
        self.btn_stop.setFixedSize(52, 52)
        self.btn_stop.setIconSize(self.btn_stop.size() * 0.5)
        self.btn_stop.setIcon(
            self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.clicked.connect(self._on_stop)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(170)
        self.slider.setToolTip("Громкость")
        self.slider.valueChanged.connect(self.engine.set_volume)
        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_stop)
        controls.addStretch(1)
        controls.addWidget(self.slider)
        panel_layout.addLayout(controls)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("status")
        root.addWidget(self.lbl_status)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

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
            item = QListWidgetItem(st["name"])
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
