# SPDX-License-Identifier: GPL-3.0-or-later
"""Small widgets shared by several spells."""
from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSlider, QWidget


class Slider(QWidget):
    """Label + slider + value, in one row."""

    def __init__(self, lo, hi, suffix="", on_change=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.s = QSlider(Qt.Orientation.Horizontal)
        self.s.setRange(lo, hi)
        self.v = QLabel()
        self.v.setObjectName("Muted")
        self.v.setFixedWidth(44)
        self.v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.suffix = suffix
        lay.addWidget(self.s, 1)
        lay.addWidget(self.v)
        self.s.valueChanged.connect(lambda x: self.v.setText(f"{x}{suffix}"))
        if on_change:
            self.s.valueChanged.connect(on_change)

    def value(self):
        return self.s.value()

    def setValue(self, x):
        self.s.setValue(x)
        self.v.setText(f"{x}{self.suffix}")


class Switch(QAbstractButton):
    """A black & white on/off switch: a white pill with a black knob when on, an outlined pill when off.
    The knob slides; toggled(bool) fires like a checkbox."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=140)
        self._anim.valueChanged.connect(self._moved)
        self.toggled.connect(self._slide)

    def sizeHint(self):
        return QSize(46, 26)

    def setChecked(self, on: bool, animate=False):
        """Programmatic changes jump straight to the end unless animate."""
        if on == self.isChecked():
            return                         # don't cut a running slide short
        super().setChecked(on)
        if not animate:
            self._anim.stop()
            self._moved(1.0 if on else 0.0)

    def _slide(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _moved(self, v):
        self._pos = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 1, self.width() - 2, self.height() - 2)
        r = track.height() / 2
        dim = not self.isEnabled()
        on_fill = QColor("#5a5a5a" if dim else "#f2f2f2")
        off_line = QColor("#2a2a2a" if dim else ("#8a8a8a" if self.underMouse() else "#4a4a4a"))
        fill = QColor(on_fill)
        fill.setAlphaF(self._pos)
        p.setPen(off_line if self._pos < 0.5 else Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(track, r, r)
        d = track.height() - 6
        x = track.left() + 3 + (track.width() - 6 - d) * self._pos
        knob_off = QColor("#4a4a4a" if dim else "#9a9a9a")
        knob = QColor("#0b0b0b") if self._pos >= 0.5 else knob_off
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, track.top() + 3, d, d))

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)
