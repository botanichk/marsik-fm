"""IslandMenu — выпадающий список-«остров», приклеенный к панели (как в Noctalia).

Не отдельное окно, а дочерний виджет главного окна: вырастает из нижнего края
панели-шапки, верхние углы расходятся наружу вогнутыми скруглениями и
перетекают в панель, нижние скруглены обычным образом.

API намеренно повторяет нужное из QMenu, чтобы код окна почти не менялся:
    clear(), addAction(text) -> QAction, addSeparator(), aboutToShow (сигнал),
    toggle(), open_menu(), close_menu(), set_trigger(кнопка).
"""
from PySide6.QtCore import (
    QEasingCurve, QEvent, QRectF, Qt, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

from .theme import manager as _themes

_FLARE = 18        # радиус вогнутых скруглений сверху (наружу)
_ROUND = 18        # радиус скруглений снизу
_PAD_X = 10        # отступ рядов от краёв тела
_PAD_Y = 8
_ROW_H = 38
_SEP_H = 13
_TEXT_PAD = 14
_MAX_W = 520
_OPEN_MS = 260
_CLOSE_MS = 160


class IslandMenu(QWidget):
    aboutToShow = Signal()
    reordered = Signal(int, int)   # перетащили строку: src, куда вставить

    def __init__(self, parent, anchor, trigger=None, center="trigger"):
        """parent — холст окна; anchor — панель, к которой клеимся;
        trigger — кнопка-пилюля; center: "trigger" (под кнопкой) или
        "anchor" (по центру панели)."""
        super().__init__(parent)
        self._anchor = anchor
        self._trigger = trigger
        self._center = center
        self._actions = []
        self._rows = []            # (action, y, h)
        self._hover = -1
        self._scroll = 0
        self._content_h = 0
        self._full_h = 0
        self._geo = (0, 0, 0)      # x, y, w
        self._p = 0.0              # прогресс раскрытия 0..1
        self._open = False
        # перетаскивание: drag_rows — сколько первых строк можно двигать
        self.drag_rows = 0
        self._drag_from = -1
        self._drag_to = -1
        self._press = None
        self._dragging = False
        self.setMouseTracking(True)
        self.hide()

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_done)
        parent.installEventFilter(self)

    # ---------- API в стиле QMenu ----------

    def set_trigger(self, button):
        self._trigger = button

    def isOpen(self):
        return self._open

    def clear(self):
        for a in self._actions:
            a.deleteLater()    # безопасно, даже если мы внутри его triggered
        self._actions = []
        self._rows = []

    def addAction(self, text):
        act = QAction(text, self)
        self._actions.append(act)
        return act

    def addSeparator(self):
        act = QAction(self)
        act.setSeparator(True)
        self._actions.append(act)
        return act

    # ---------- открытие / закрытие ----------

    def toggle(self):
        if self._open:
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        if self._open:
            return
        self.aboutToShow.emit()          # владелец пересобирает пункты
        self._measure()
        self._open = True
        self._hover = -1
        self._scroll = 0
        self._p = 0.0
        x, y, w = self._geo
        self.setGeometry(x, y, w, 1)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(_OPEN_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        QApplication.instance().installEventFilter(self)

    def close_menu(self):
        if not self._open:
            return
        self._open = False
        QApplication.instance().removeEventFilter(self)
        QToolTip.hideText()
        self._anim.stop()
        self._anim.setDuration(_CLOSE_MS)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.setStartValue(float(self._p))
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim(self, value):
        self._p = float(value)
        x, y, w = self._geo
        self.setGeometry(x, y, w, max(1, int(round(self._full_h * self._p))))
        self.update()

    def _on_anim_done(self):
        if not self._open:
            self.hide()

    def refresh(self):
        """Пересчитать геометрию на лету (пункты поменялись, меню открыто)."""
        if not self._open:
            return
        self._measure()
        x, y, w = self._geo
        self.setGeometry(x, y, w, max(1, int(round(self._full_h * self._p))))
        self.update()

    # ---------- геометрия ----------

    def _measure(self):
        fm = QFontMetrics(self.font())
        self._rows = []
        y = _PAD_Y
        widest = 0
        for a in self._actions:
            if a.isSeparator():
                self._rows.append((a, y, _SEP_H))
                y += _SEP_H
            else:
                widest = max(widest, fm.horizontalAdvance(a.text()))
                self._rows.append((a, y, _ROW_H))
                y += _ROW_H
        self._content_h = y + _PAD_Y

        canvas = self.parentWidget()
        min_body = (self._trigger.width() + 30) if self._trigger else 200
        check_w = 26 if any(a.isCheckable() for a in self._actions) else 0
        # колонка времени справа (данные действия — строка «3:45»)
        time_w = (fm.horizontalAdvance("0:00:00") + 14
                  if any(isinstance(a.data(), str) for a in self._actions)
                  else 0)
        body_w = widest + check_w + time_w + 2 * (_PAD_X + _TEXT_PAD)
        body_w = max(min_body, body_w)
        body_w = min(body_w, _MAX_W, canvas.width() - 2 * _FLARE - 24)
        w = int(body_w) + 2 * _FLARE

        top = self._anchor.geometry()
        y0 = top.y() + top.height() - 1    # 1px внахлёст на край панели
        # центр: под кнопкой или по центру панели
        if self._center == "trigger" and self._trigger is not None:
            c = self._trigger.mapTo(canvas, self._trigger.rect().center()).x()
        else:
            c = top.x() + top.width() // 2
        x0 = int(c - w / 2)
        x0 = max(top.x() - _FLARE + 6, min(x0, canvas.width() - w - 6))

        max_h = max(120, canvas.height() - y0 - 110)  # плеер остаётся виден
        self._full_h = int(min(self._content_h, max_h))
        self._geo = (x0, y0, w)

    # ---------- отрисовка ----------

    def _shape(self, w, h, closed=True):
        r = float(min(_FLARE, h))
        r2 = float(max(0.0, min(_ROUND, (h - r) / 2.0 + r / 2.0, h / 2.0)))
        bx0, bx1 = float(_FLARE), float(w - _FLARE)
        path = QPainterPath()
        path.moveTo(bx0 - r, 0)
        # левое вогнутое: сверху (90°) → вправо (0°)
        path.arcTo(QRectF(bx0 - 2 * r, 0, 2 * r, 2 * r), 90, -90)
        path.lineTo(bx0, h - r2)
        # низ-лево
        path.arcTo(QRectF(bx0, h - 2 * r2, 2 * r2, 2 * r2), 180, 90)
        path.lineTo(bx1 - r2, h)
        # низ-право
        path.arcTo(QRectF(bx1 - 2 * r2, h - 2 * r2, 2 * r2, 2 * r2), 270, 90)
        path.lineTo(bx1, r)
        # правое вогнутое: слева (180°) → вверх (90°)
        path.arcTo(QRectF(bx1, 0, 2 * r, 2 * r), 180, -90)
        if closed:
            path.closeSubpath()
        return path

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if h < 3:
            return
        th = _themes.current
        fill = th.q(th.surface, 238)
        edge = th.q(th.on_surface, 46)
        hover = th.q(th.primary, 235)
        text_c = th.q(th.on_surface)
        text_off = th.q(th.disabled)
        sep_c = th.q(th.on_surface, 46)
        accent = th.q(th.primary)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillPath(self._shape(w, h), fill)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self._shape(w, h, closed=False))

        # содержимое: проявляется ближе к концу раскрытия
        p.setClipPath(self._shape(w, h))
        p.setOpacity(max(0.0, min(1.0, (self._p - 0.3) / 0.7)))
        fm = QFontMetrics(self.font())
        bx0, bx1 = _FLARE + _PAD_X, w - _FLARE - _PAD_X
        for i, (a, y, rh) in enumerate(self._rows):
            ry = y - self._scroll
            if ry + rh < 0 or ry > h:
                continue
            if a.isSeparator():
                p.setPen(QPen(sep_c, 1.0))
                mid = ry + rh / 2.0
                p.drawLine(bx0 + 6, int(mid), bx1 - 6, int(mid))
                continue
            rect = QRectF(bx0, ry, bx1 - bx0, rh)
            on = a.isEnabled()
            if i == self._hover and on:
                p.setPen(Qt.NoPen)
                p.setBrush(hover)
                p.drawRoundedRect(rect, 10, 10)
                p.setPen(th.q(th.on_primary))
            else:
                p.setPen(text_c if on else text_off)
            reserve = 26 if a.isCheckable() else 0
            tdata = a.data() if isinstance(a.data(), str) else None
            if tdata is not None:
                reserve += fm.horizontalAdvance("0:00:00") + 14
            text = fm.elidedText(
                a.text(), Qt.ElideRight,
                int(rect.width() - 2 * _TEXT_PAD - reserve))
            p.drawText(rect.adjusted(_TEXT_PAD, 0, -_TEXT_PAD, 0),
                       Qt.AlignVCenter | Qt.AlignLeft, text)
            if tdata:
                tc = (th.q(th.on_primary, 220) if i == self._hover and on
                      else th.q(th.muted))
                p.setPen(tc)
                p.drawText(rect.adjusted(0, 0, -_TEXT_PAD, 0),
                           Qt.AlignVCenter | Qt.AlignRight, tdata)
            if a.isCheckable() and a.isChecked():
                if i != self._hover:
                    p.setPen(accent)
                p.drawText(rect.adjusted(0, 0, -_TEXT_PAD, 0),
                           Qt.AlignVCenter | Qt.AlignRight, "✓")

        # куда встанет перетаскиваемая строка
        if self._dragging and 0 <= self._drag_to <= len(self._rows):
            if self._drag_to < len(self._rows):
                line_y = self._rows[self._drag_to][1] - self._scroll
            elif self._rows:
                a, ry, rh = self._rows[-1]
                line_y = ry + rh - self._scroll
            else:
                line_y = 0
            p.setPen(QPen(accent, 2.0))
            p.drawLine(int(bx0 + 4), int(line_y), int(bx1 - 4), int(line_y))

    # ---------- мышь ----------

    def _row_at(self, pos):
        if not (_FLARE <= pos.x() <= self.width() - _FLARE):
            return -1
        y = pos.y() + self._scroll
        for i, (a, ry, rh) in enumerate(self._rows):
            if ry <= y < ry + rh:
                return i
        return -1

    def _drop_index(self, pos):
        """Куда вставить перетаскиваемую строку (индекс в исходном списке)."""
        y = pos.y() + self._scroll
        index = min(self.drag_rows, len(self._rows))
        for i in range(index):
            if y < self._rows[i][1] + self._rows[i][2] / 2.0:
                return i
        return index

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()
        i = self._row_at(self._press)
        a = self._rows[i][0] if i >= 0 else None
        movable = (a is not None and i < self.drag_rows
                   and not a.isSeparator() and a.isEnabled())
        self._drag_from = i if movable else -1
        self._drag_to = -1

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._drag_from >= 0 and e.buttons() & Qt.LeftButton:
            if not self._dragging and self._press is not None \
                    and (pos - self._press).manhattanLength() > 6:
                self._dragging = True
                self._hover = -1
            if self._dragging:
                self._drag_to = self._drop_index(pos)
                # автопрокрутка у краёв: список может быть длиннее меню
                over = self._content_h - self.height()
                if over > 0:
                    if pos.y() < 24:
                        self._scroll = max(0, self._scroll - 8)
                    elif pos.y() > self.height() - 24:
                        self._scroll = min(over, self._scroll + 8)
                self.update()
                return
        i = self._row_at(pos)
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._open:
            return
        if self._dragging:
            src, dst = self._drag_from, self._drop_index(e.position().toPoint())
            self._dragging = False
            self._drag_from = self._drag_to = -1
            self.update()
            if src >= 0 and dst != src:
                self.reordered.emit(src, dst)
            return
        i = self._row_at(e.position().toPoint())
        if i < 0:
            return
        act = self._rows[i][0]
        if act.isSeparator() or not act.isEnabled():
            return
        self.close_menu()
        act.trigger()

    def wheelEvent(self, e):
        over = self._content_h - self.height()
        if over <= 0:
            return
        step = -e.angleDelta().y() // 3
        self._scroll = max(0, min(over, self._scroll + step))
        self.update()

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            i = self._row_at(e.pos())
            tip = self._rows[i][0].toolTip() if i >= 0 else ""
            # у QAction без явной подсказки toolTip() == text — не дублируем
            if i >= 0 and tip and tip != self._rows[i][0].text():
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    # ---------- закрытие по клику снаружи / Esc ----------

    def eventFilter(self, obj, e):
        t = e.type()
        if obj is self.parentWidget():
            if t == QEvent.Resize and (self._open or self.isVisible()):
                self._anim.stop()
                self._open = False
                QApplication.instance().removeEventFilter(self)
                self.hide()
            return False
        if not self._open:
            return False
        if t == QEvent.MouseButtonPress:
            gp = e.globalPosition().toPoint()
            if self.rect().contains(self.mapFromGlobal(gp)):
                return False
            if (self._trigger is not None
                    and self._trigger.rect().contains(
                        self._trigger.mapFromGlobal(gp))):
                return False       # клик по своей кнопке: toggle сам закроет
            self.close_menu()
        elif t == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self.close_menu()
            return True
        elif t == QEvent.WindowDeactivate and obj is self.window():
            self.close_menu()
        return False
