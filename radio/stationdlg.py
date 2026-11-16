"""Диалог станции: название, URL потока, описание и обложка.

Один диалог на добавление и на правку. Обложку можно указать ссылкой
(http/https — её понимает и мобильная версия) либо локальным файлом;
кнопка «Скачать» сохраняет картинку из ссылки на компьютер в папку данных
приложения и подставляет уже локальный путь.

Пустое поле обложки = у станции нет картинки (рисуется заглушка).
"""
import re
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QToolButton,
)

from .stations import resolve_logo

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def logo_dir():
    """Папка скачанных обложек станций (~/.local/share/radiofm/logos).

    GenericDataLocation, а не AppDataLocation: та подставляет имя приложения,
    которое на момент вызова может быть ещё не задано.
    """
    base = (QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
            or str(Path.home() / ".local" / "share"))
    return Path(base) / "radiofm" / "logos"


def is_link(value):
    return (value or "").strip().startswith(("http://", "https://"))


def validate(name, url, logo):
    """Текст ошибки или None. Контракт тот же, что был у добавления."""
    if not name:
        return "Введите название станции."
    if not url.startswith(("http://", "https://")):
        return "URL должен начинаться с http:// или https://"
    # относительные пути вида ../assets/logo/x.webp — как в stations.json
    if logo and not is_link(logo) and not resolve_logo(logo):
        return "Файл обложки не найден:\n%s" % logo
    return None


def _ext_of(data):
    """Расширение по сигнатуре байтов (QImage.fromData формат не сохраняет)."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ".png"


def save_logo(data, hint, directory=None):
    """Сохраняет байты картинки в папку обложек. Возвращает путь или None.

    hint — имя станции (для имени файла). Не картинка → None.
    """
    if QImage.fromData(data).isNull():
        return None
    ext = _ext_of(data)
    slug = re.sub(r"\W+", "_", hint or "").strip("_").lower() or "station"
    folder = Path(directory) if directory else logo_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / (slug + ext), 2
    while path.exists():
        path = folder / ("%s-%d%s" % (slug, n, ext))
        n += 1
    try:
        path.write_bytes(data)
    except OSError:
        return None
    return path


class StationDialog(QDialog):
    """Поля станции. station=None — новая; иначе предзаполнение для правки."""

    def __init__(self, parent=None, station=None):
        super().__init__(parent)
        st = station or {}
        self.setWindowTitle("Станция" if station else "Новая станция")
        self.setMinimumWidth(560)
        self._net = QNetworkAccessManager(self)
        self._reply = None

        form = QFormLayout(self)
        self.ed_name = QLineEdit(st.get("name", ""), self)
        self.ed_name.setPlaceholderText("Например: Boot Liquor")
        self.ed_url = QLineEdit(st.get("url", ""), self)
        self.ed_url.setPlaceholderText("https://ice1.somafm.com/…-128-mp3")
        self.ed_desc = QLineEdit(st.get("description", ""), self)
        self.ed_desc.setPlaceholderText("Описание (необязательно)")

        logo_row = QHBoxLayout()
        self.ed_logo = QLineEdit(st.get("logo", ""), self)
        self.ed_logo.setPlaceholderText("ссылка http(s):// или путь к файлу")
        self.btn_browse = QToolButton(self)
        self.btn_browse.setText("Обзор…")
        self.btn_get = QToolButton(self)
        self.btn_get.setText("Скачать")
        logo_row.addWidget(self.ed_logo, 1)
        logo_row.addWidget(self.btn_browse)
        logo_row.addWidget(self.btn_get)

        self.preview = QLabel(self)
        self.preview.setFixedSize(96, 96)
        self.preview.setAlignment(Qt.AlignCenter)

        form.addRow("Название:", self.ed_name)
        form.addRow("URL потока:", self.ed_url)
        form.addRow("Описание:", self.ed_desc)
        form.addRow("Обложка:", logo_row)
        form.addRow("", self.preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.ed_logo.textChanged.connect(self._update_logo_buttons)
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_get.clicked.connect(self._on_download)
        self._update_logo_buttons()
        self._update_preview()

    # ---------- поля ----------

    def values(self):
        logo = self.ed_logo.text().strip()
        return {
            "name": self.ed_name.text().strip(),
            "url": self.ed_url.text().strip(),
            "description": self.ed_desc.text().strip(),
            "logo": logo,
        }

    def _on_ok(self):
        v = self.values()
        err = validate(v["name"], v["url"], v["logo"])
        if err:
            QMessageBox.warning(self, "Marsik FM", err)
            return
        self.accept()

    # ---------- обложка ----------

    def _update_logo_buttons(self):
        self.btn_get.setEnabled(is_link(self.ed_logo.text()))
        self._update_preview()

    def _update_preview(self):
        value = self.ed_logo.text().strip()
        self.preview.setToolTip(value)
        if is_link(value):
            self.preview.setPixmap(QPixmap())
            self.preview.setText("нажмите «Скачать»")
            return
        path = resolve_logo(value) if value else None
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText("нет картинки" if not value else "не читается")
            return
        self.preview.setText("")
        self.preview.setPixmap(pm.scaled(
            96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Обложка станции", str(Path.home()),
            "Картинки (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.ed_logo.setText(path)

    def _on_download(self):
        url = self.ed_logo.text().strip()
        if not is_link(url) or self._reply is not None:
            return
        self.btn_get.setEnabled(False)
        self.btn_get.setText("Скачиваю…")
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(10000)
        self._reply = self._net.get(req)
        self._reply.finished.connect(self._on_downloaded)

    def _on_downloaded(self):
        reply, self._reply = self._reply, None
        data = bytes(reply.readAll().data())
        reply.deleteLater()
        self.btn_get.setText("Скачать")
        self.btn_get.setEnabled(is_link(self.ed_logo.text()))
        path = save_logo(data, self.ed_name.text().strip() or "station")
        if path is None:
            QMessageBox.warning(
                self, "Marsik FM",
                "Не удалось скачать картинку — проверьте ссылку.")
            return
        self.ed_logo.setText(str(path))
