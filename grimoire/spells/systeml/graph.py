# SPDX-License-Identifier: GPL-3.0-or-later
"""SystemL's drawing: live line graphs, usage bars and the per-core grid, all in black and white.
The first series is a solid white line over a faint fill; a second one is a dashed gray line."""
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from grimoire.theme import FONT

POINTS = 120                                 # samples on screen (two minutes at one a second)
BG, EDGE, GRID = QColor("#0e0e0e"), QColor("#1c1c1c"), QColor("#171717")
INK, SOFT, DIM = QColor("#f2f2f2"), QColor("#8c8c8c"), QColor("#5a5a5a")


def _font(px: int, weight=QFont.Weight.Normal, mono=False) -> QFont:
    f = QFont("IBM Plex Mono" if mono else FONT)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _plot(p: QPainter, area: QRectF, values, top: float, dashed=False, fill=True, points=POINTS):
    if len(values) < 2 or top <= 0:
        return
    step = area.width() / (points - 1)
    x0 = area.right() - step * (len(values) - 1)
    pts = [QPointF(x0 + i * step, area.bottom() - min(1.0, max(0.0, v / top)) * area.height())
           for i, v in enumerate(values)]
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    if fill:
        shade = QPainterPath(path)
        shade.lineTo(pts[-1].x(), area.bottom())
        shade.lineTo(pts[0].x(), area.bottom())
        grad = QLinearGradient(0, area.top(), 0, area.bottom())
        grad.setColorAt(0, QColor(255, 255, 255, 46))
        grad.setColorAt(1, QColor(255, 255, 255, 4))
        p.fillPath(shade, grad)
    pen = QPen(SOFT if dashed else INK, 1.4)
    if dashed:
        pen.setDashPattern([3, 3])
    p.setPen(pen)
    p.drawPath(path)


class Graph(QWidget):
    """A titled card with a live graph. push(a, b=None) adds a sample; fmt turns a value into text; top is
    the fixed ceiling (e.g. 100 for percent) or None to scale to the largest visible value."""

    def __init__(self, title: str, fmt=lambda v: f"{v:.0f}%", top: float | None = 100, labels=("", ""),
                 two=False, height=150):
        super().__init__()
        self.title, self.fmt, self.top, self.labels, self.two = title, fmt, top, labels, two
        self.a, self.b = deque(maxlen=POINTS), deque(maxlen=POINTS)
        self.note = ""                       # small text under the value (e.g. "7.1 of 31 GB")
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def push(self, a: float, b: float | None = None, note: str | None = None):
        self.a.append(a)
        if b is not None:
            self.b.append(b)
        if note is not None:
            self.note = note
        self.update()

    def clear(self):
        self.a.clear()
        self.b.clear()
        self.update()

    def _ceiling(self) -> float:
        if self.top:
            return self.top
        peak = max([*self.a, *self.b, 1.0])
        nice = 1.0
        while nice < peak * 1.15:            # round up to 1, 2, 5 × 10^n so the scale doesn't jitter
            for m in (2, 2.5, 2):
                nice *= m
                if nice >= peak * 1.15:
                    break
        return nice

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(EDGE)
        p.setBrush(BG)
        p.drawRoundedRect(r, 10, 10)
        pad = 16
        p.setFont(_font(11, QFont.Weight.DemiBold))
        p.setPen(DIM)
        p.drawText(QRectF(pad, 12, r.width() - 2 * pad, 16), Qt.AlignmentFlag.AlignLeft, self.title.upper())
        cur_a = self.a[-1] if self.a else 0.0
        p.setFont(_font(22, QFont.Weight.Light))
        p.setPen(INK)
        head = self.fmt(cur_a)
        if self.two and self.b:
            head = f"{self.labels[0]} {self.fmt(cur_a)}"
        p.drawText(QRectF(pad, 28, r.width() - 2 * pad, 30), Qt.AlignmentFlag.AlignLeft, head)
        right = self.note
        if self.two and self.b:
            right = f"{self.labels[1]} {self.fmt(self.b[-1])}" + (f"   {self.note}" if self.note else "")
        p.setFont(_font(12))
        p.setPen(SOFT)
        p.drawText(QRectF(pad, 36, r.width() - 2 * pad, 20), Qt.AlignmentFlag.AlignRight, right)
        area = QRectF(pad, 64, r.width() - 2 * pad, r.height() - 64 - 12)
        top = self._ceiling()
        p.setPen(QPen(GRID, 1))
        for i in range(4):
            y = area.top() + area.height() * i / 3
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        if not self.top:
            p.setFont(_font(10, mono=True))
            p.setPen(DIM)
            p.drawText(QRectF(area.left(), area.top() + 2, area.width() - 2, 14), Qt.AlignmentFlag.AlignRight,
                       self.fmt(top))
        _plot(p, area, list(self.b), top, dashed=True, fill=False)
        _plot(p, area, list(self.a), top)
        p.end()


class Spark(QWidget):
    """A small graph without a card: one core in the core grid, or one app's history line."""

    def __init__(self, label="", top: float | None = 100, height=46):
        super().__init__()
        self.label, self.top = label, top
        self.a = deque(maxlen=POINTS)
        self.points = POINTS
        self.setMinimumHeight(height)

    def push(self, v: float):
        self.a.append(v)
        self.update()

    def set_values(self, values):
        """Show a fixed series (stretched to the full width) instead of a live one."""
        self.points = max(2, len(values))
        self.a = deque(values, maxlen=self.points)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(EDGE)
        p.setBrush(BG)
        p.drawRoundedRect(r, 6, 6)
        top = self.top or max([*self.a, 1.0]) * 1.15
        area = r.adjusted(4, 18 if self.label else 4, -4, -4)
        _plot(p, area, list(self.a), top, points=self.points)
        if self.label:
            p.setFont(_font(10, mono=True))
            p.setPen(SOFT)
            p.drawText(r.adjusted(6, 3, -6, 0), Qt.AlignmentFlag.AlignLeft, self.label)
            p.setPen(INK)
            p.drawText(r.adjusted(6, 3, -6, 0), Qt.AlignmentFlag.AlignRight,
                       f"{self.a[-1]:.0f}%" if self.a else "")
        p.end()


class CoreGrid(QWidget):
    """One small graph per CPU thread."""

    def __init__(self, cores: int):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        cols = 8 if cores > 8 else max(1, cores)
        self.sparks = [Spark(f"{i}") for i in range(cores)]
        for i, s in enumerate(self.sparks):
            grid.addWidget(s, i // cols, i % cols)

    def push(self, values):
        for s, v in zip(self.sparks, values):
            s.push(v)


class Bar(QWidget):
    """A thin usage bar (0..1)."""

    def __init__(self, height=6):
        super().__init__()
        self.v = 0.0
        self.setFixedHeight(height)
        self.setMinimumWidth(60)

    def set(self, v: float):
        self.v = max(0.0, min(1.0, v))
        self.update()

    def sizeHint(self):
        return QSize(160, self.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#222222"))
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(INK)
        if self.v > 0:
            p.drawRoundedRect(QRectF(r.left(), r.top(), max(r.height(), r.width() * self.v), r.height()), rad, rad)
        p.end()
