"""The region picker: a frozen copy of each screen, dimmed, where you drag out the part to keep. One frameless
fullscreen window per monitor, all sharing one selection; Enter or releasing the mouse confirms, Esc cancels, Space
or a double click takes the whole screen under the pointer."""
from PySide6.QtCore import QEventLoop, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from grimoire.spells.shotl.capture import screen_rect
from grimoire.theme import FONT


class _Screen(QWidget):
    picked = Signal(object)                    # QRect in grab pixels, or None

    def __init__(self, img, screen, crop: QRect):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)   # ShotL's own window is hidden meanwhile
        self.setWindowTitle("ShotL region")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.img = img.copy(crop)
        self.crop = crop
        self.start: QPoint | None = None
        self.sel = QRect()
        self.mouse = QPoint(-1, -1)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def _k(self) -> float:                     # grab pixels per window pixel
        return self.img.width() / max(1, self.width())

    def _to_grab(self, r: QRect) -> QRect:
        k = self._k()
        return QRect(round(r.x() * k) + self.crop.x(), round(r.y() * k) + self.crop.y(), round(r.width() * k),
                     round(r.height() * k))

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawImage(self.rect(), self.img)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))
        f = QFont(FONT, 10)
        p.setFont(f)
        if self.sel.isValid():
            k = self._k()
            src = QRectF(self.sel.x() * k, self.sel.y() * k, self.sel.width() * k, self.sel.height() * k)
            p.drawImage(QRectF(self.sel), self.img, src)
            p.setPen(QPen(QColor("#ffffff"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.sel.adjusted(0, 0, -1, -1))
            g = self._to_grab(self.sel)
            self._chip(p, f"{g.width()} × {g.height()}", self.sel.bottomLeft() + QPoint(0, 8))
        else:
            hint = "Drag to pick a region  ·  Space or double click: whole screen  ·  Esc: cancel"
            self._chip(p, hint, QPoint(self.width() // 2 - p.fontMetrics().horizontalAdvance(hint) // 2 - 10, 40))
        if self.mouse.x() >= 0 and not self.start:     # thin crosshair guides
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.drawLine(0, self.mouse.y(), self.width(), self.mouse.y())
            p.drawLine(self.mouse.x(), 0, self.mouse.x(), self.height())

    def _chip(self, p: QPainter, text: str, at: QPoint):
        fm = p.fontMetrics()
        r = QRect(at, fm.boundingRect(text).size() + QRect(0, 0, 20, 10).size())
        r.moveLeft(max(4, min(r.left(), self.width() - r.width() - 4)))
        if r.bottom() > self.height() - 4:
            r.moveBottom(self.sel.top() - 8 if self.sel.isValid() else self.height() - 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 220))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("#f2f2f2"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.picked.emit(None)
        elif e.button() == Qt.MouseButton.LeftButton:
            self.start = e.position().toPoint()
            self.sel = QRect()
            self.update()

    def mouseMoveEvent(self, e):
        self.mouse = e.position().toPoint()
        if self.start is not None:
            a, b = self.start, self.mouse
            self.sel = QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(b.x() - a.x()), abs(b.y() - a.y()))
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.start = None
            if self.sel.width() > 3 and self.sel.height() > 3:
                self.picked.emit(self._to_grab(self.sel))
            else:
                self.sel = QRect()
                self.update()

    def mouseDoubleClickEvent(self, e):
        self.picked.emit(QRect(self.crop))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.picked.emit(None)
        elif e.key() == Qt.Key.Key_Space:
            self.picked.emit(QRect(self.crop))
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.sel.isValid():
            self.picked.emit(self._to_grab(self.sel))


def pick(img) -> QRect | None:
    """Show the picker over every screen and wait; the chosen rectangle in the grab's pixels, or None."""
    loop = QEventLoop()
    result: list = [None]
    wins = []

    def done(r):
        result[0] = r
        loop.quit()

    for s in QGuiApplication.screens():
        w = _Screen(img, s, screen_rect(img, s))
        w.picked.connect(done)
        wins.append(w)
        w.showFullScreen()
    if wins:
        wins[0].activateWindow()
        loop.exec()
    for w in wins:
        w.close()
    return result[0]
