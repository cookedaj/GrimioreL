# SPDX-License-Identifier: GPL-3.0-or-later
"""FocusL's two drawings: the countdown ring and the focus-minutes bar chart, both in black and white."""
import datetime as dt

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from grimoire.theme import FONT


class Ring(QWidget):
    """A big ring that empties clockwise as the phase runs out, the time left in the middle and one dot per round
    underneath (filled when done, ringed for the current one)."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(250, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.frac, self.big, self.top, self.bottom = 1.0, "25:00", "READY", ""
        self.rounds, self.done, self.current, self.dim = 4, 0, 0, False

    def show_state(self, frac: float, big: str, top: str, bottom: str, rounds: int, done: int, current: int,
                   dim: bool):
        new = (round(frac, 4), big, top, bottom, rounds, done, current, dim)
        if new != (round(self.frac, 4), self.big, self.top, self.bottom, self.rounds, self.done, self.current,
                   self.dim):
            self.frac, self.big, self.top, self.bottom, self.rounds, self.done, self.current, self.dim = \
                frac, big, top, bottom, rounds, done, current, dim
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 8
        w = max(6.0, side * 0.03)
        box = QRectF((self.width() - side) / 2 + w / 2, (self.height() - side) / 2 + w / 2, side - w, side - w)
        p.setPen(QPen(QColor("#1c1c1c"), w))
        p.drawEllipse(box)
        if self.frac > 0:
            p.setPen(QPen(QColor("#6f6f6f" if self.dim else "#f2f2f2"), w, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawArc(box, 90 * 16, -int(self.frac * 360 * 16))     # from 12 o'clock, clockwise

        c = box.center()
        f = QFont(FONT)
        f.setPixelSize(max(10, int(side * 0.045)))
        f.setWeight(QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, side * 0.012)
        p.setFont(f)
        p.setPen(QColor("#8c8c8c"))
        p.drawText(QRectF(box.left(), c.y() - side * 0.25, box.width(), side * 0.08), Qt.AlignmentFlag.AlignCenter,
                   self.top)
        f = QFont(FONT)
        f.setPixelSize(max(20, int(side * 0.2)))
        f.setWeight(QFont.Weight.Light)
        p.setFont(f)
        p.setPen(QColor("#8c8c8c" if self.dim else "#ffffff"))
        p.drawText(QRectF(box.left(), c.y() - side * 0.15, box.width(), side * 0.26), Qt.AlignmentFlag.AlignCenter,
                   self.big)
        f = QFont(FONT)
        f.setPixelSize(max(10, int(side * 0.042)))
        p.setFont(f)
        p.setPen(QColor("#6f6f6f"))
        p.drawText(QRectF(box.left(), c.y() + side * 0.11, box.width(), side * 0.07), Qt.AlignmentFlag.AlignCenter,
                   self.bottom)

        r, gap = max(3.0, side * 0.011), max(10.0, side * 0.04)
        x0 = c.x() - (self.rounds - 1) * gap / 2
        for i in range(self.rounds):
            pt = QPointF(x0 + i * gap, c.y() + side * 0.25)
            if i < self.done:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#f2f2f2"))
            else:
                p.setPen(QPen(QColor("#f2f2f2" if i == self.current else "#3a3a3a"), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pt, r, r)
        p.end()


class Bars(QWidget):
    """Focus minutes per day, oldest on the left; today is the brightest bar. Hover a bar for its numbers."""

    def __init__(self):
        super().__init__()
        self.days: list[tuple[dt.date, float, int]] = []
        self.setMinimumHeight(130)
        self.setMouseTracking(True)

    def set_days(self, days):
        self.days = list(days)
        self.update()

    def _slots(self):
        n = max(1, len(self.days))
        left, right, top, bottom = 4, 4, 18, 22
        slot = (self.width() - left - right) / n
        return left, top, self.height() - bottom, slot

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, base, slot = self._slots()
        peak = max([m for _, m, _ in self.days] + [60.0])
        p.setPen(QPen(QColor("#262626"), 1))
        p.drawLine(QPointF(left, base + 0.5), QPointF(self.width() - 4, base + 0.5))
        f = QFont(FONT)
        f.setPixelSize(10)
        p.setFont(f)
        bw = min(26.0, slot * 0.56)
        for i, (day, minutes, _) in enumerate(self.days):
            x = left + i * slot + (slot - bw) / 2
            last = i == len(self.days) - 1
            h = (base - top) * minutes / peak
            if minutes > 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#ffffff" if last else "#9a9a9a"))
                p.drawRoundedRect(QRectF(x, base - max(h, 2), bw, max(h, 2)), 2, 2)
            p.setPen(QColor("#ffffff" if last else "#555555"))
            p.drawText(QRectF(left + i * slot, base + 5, slot, 14), Qt.AlignmentFlag.AlignCenter,
                       day.strftime("%a")[:2])
        if peak > 60 or any(m for _, m, _ in self.days):
            p.setPen(QColor("#555555"))
            p.drawText(QRectF(left, 0, self.width() - 8, 14), Qt.AlignmentFlag.AlignRight,
                       f"{peak / 60:.1f} h" if peak >= 90 else f"{peak:.0f} min")
        p.end()

    def mouseMoveEvent(self, e):
        left, _, _, slot = self._slots()
        i = int((e.position().x() - left) // slot) if slot else -1
        if 0 <= i < len(self.days):
            day, minutes, sessions = self.days[i]
            QToolTip.showText(e.globalPosition().toPoint(), f"{day.strftime('%a %d %b')}\n{minutes:.0f} min of focus"
                              f"\n{sessions} full session{'' if sessions == 1 else 's'}", self)
        else:
            QToolTip.hideText()
