"""Значок в системном трее (StatusNotifierItem через QSystemTrayIcon).

Трей может появиться позже приложения (панель стартует после входа), поэтому
значок не создаётся один раз вслепую: пока трея нет, каждые 2 с идёт
повторная проверка, максимум 60 с.
"""
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

RETRY_MS = 2000     # период повторной проверки трея
RETRIES = 30        # 30 × 2 с = 60 с
CLICK_GAP = 0.4     # двойной клик = один переворот окна, а не два


class Tray(QObject):
    def __init__(self, win, icon):
        super().__init__(win)
        self.win = win
        self.menu = QMenu()
        self.act_toggle = self.menu.addAction("Скрыть", win.toggle_window)
        self.act_play = self.menu.addAction(
            "Воспроизведение", win._on_playpause)
        self.menu.addSeparator()
        self.menu.addAction("Выход", win.quit_app)
        self.icon = QSystemTrayIcon(icon, self)
        self.icon.setToolTip("Marsik FM")
        self.icon.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self._sync_labels)
        self.icon.activated.connect(self._on_activated)
        self._timer = QTimer(self)
        self._timer.setInterval(RETRY_MS)
        self._timer.timeout.connect(self._try_show)
        self._tries = 0
        self._playing = False
        self._last_click = 0.0

    # ---------- показ ----------

    def start(self):
        self._try_show()
        if not self.icon.isVisible():
            self._timer.start()

    def _try_show(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()
        if self.icon.isVisible() or self._tries >= RETRIES:
            self._timer.stop()
        self._tries += 1

    # ---------- реакция ----------

    def _on_activated(self, reason):
        # левый клик — показать/скрыть окно. В части треев (XFCE) двойной
        # клик приходит как Trigger + DoubleClick: второй не считаем
        if reason not in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            return
        now = time.monotonic()
        if now - self._last_click < CLICK_GAP:
            return
        self._last_click = now
        self.win.toggle_window()

    def sync(self, tooltip, playing):
        """Подсказка значка и состояние — из окна (трек, пауза)."""
        self.icon.setToolTip(tooltip)
        self._playing = playing
        self._sync_labels()

    def _sync_labels(self):
        """Подписи меню: актуальны на момент открытия."""
        self.act_play.setText("Пауза" if self._playing else "Воспроизведение")
        self.act_toggle.setText(
            "Скрыть" if self.win.isVisible() else "Показать")
